# 写入口：所有领域写入唯一的入口。流程编排、步骤驱动的记录、提交、交互与项目服务写入事件都经过这里。
# 一次写入是一个事务（transact）：读取流保存的投影、决定请求与流版本，由调用方判断并追加事件，提交时在同一个
# 数据库事务中核对流版本、执行权编号与命令身份，追加事件并更新保存的投影与改变的决定请求；提交以后事件日志通知订阅方。
# 判断期间不持有锁：另一方在读取以后写入了同一个流时，提交因版本不符被拒绝，调用方按写入以后的状态重新判断；
# 互斥由提交时的版本核对与数据库的写入事务完成，不依赖线程身份，也没有调用方在另一方的判断期间等待。

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import KW_ONLY, dataclass, field
from typing import Any, TypeVar

from .definitions import DEFINITIONS
from .event_store import (
    Command, EventStore, SavedDecision, SavedProjection, StreamVersionConflict, dump_decision, is_catalog_stream,
    is_run_stream, load_decisions,
)
from .kernel_events import (
    CatalogEvent, DecisionRequest, Event, ProjectEvent, SkeletonEventType, StreamHandler, apply_decision_event,
    json_dumps, new_id, replay_decisions, utc_now,
)
from .minimal_projection import MinimalProjection, fold_events, fold_more

T = TypeVar("T")

# 一次写入因为另一方先写入同一个流而重新判断的最多次数；每次被拒绝都说明另一方的写入已经提交，
# 超过这个次数时交回最后一次的版本冲突
MAX_JUDGMENTS = 100

# 结束运行的事件：它承载的停止原因规定的结束方式，与事件写入的终态
_STOP_EVENTS = {SkeletonEventType.RUN_DONE: ("done", "done"), SkeletonEventType.RUN_PAUSED: ("paused", "paused"),
                SkeletonEventType.RUN_FAILED: ("failed", "failed")}


@dataclass(frozen=True)
class NewEvent:
    # 一条要追加的 run 事件；事件编号、日志位置、流内版本与创建时间在追加时确定。
    # actor 是写入方声明的提出者；由命令写入时提出者是命令的提出者
    type: str
    _: KW_ONLY
    state_before: str
    state_after: str
    actor: str | None = None
    department: str | None = None
    parent_event_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    artifact_hashes: list[str] = field(default_factory=list)
    session_id: str | None = None
    provider: str | None = None
    model: str | None = None
    context_digest: str | None = None
    stop_reason: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class NewProjectEvent:
    # 一条要追加的项目事件；actor 是写入方声明的提出者，由命令写入时取命令的提出者
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    actor: str | None = None

@dataclass(frozen=True)
class NewCatalogEvent:
    # 一条要追加的目录事件；actor 是写入方声明的提出者（补写与外部修改声明系统）
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    actor: str | None = None


class Snapshot:
    # 一个流在某个版本的只读视图：保存的投影与它的流版本、这个流中的决定请求（按身份），以及到这个版本为止的事件
    def __init__(self, store: EventStore, stream: str, saved: SavedProjection | None,
                 handler: StreamHandler, minimal_of: Callable[[str, int, list[Any]], MinimalProjection] | None = None
                 ) -> None:
        self.stream = stream
        self.version = 0 if saved is None else saved.version
        self.projection: Any = handler.empty() if saved is None else handler.load(saved)
        self.decisions: dict[str, DecisionRequest] = load_decisions(saved)
        self.handler = handler
        self._store = store
        self._minimal_of = minimal_of
        self._committed: list[Any] | None = None
        self._minimal: MinimalProjection | None = None

    def events(self) -> list[Any]:
        # 流中到读取时的版本为止的全部事件
        if self._committed is None:
            self._committed = self._store.stream_events(self.stream, through_version=self.version)
        return list(self._committed)

    def events_after(self, version: int) -> list[Any]:
        # 流中版本大于 version、到读取时的版本为止的事件
        if self._committed is not None:
            return [event for event in self._committed if event.stream_version > version]
        return self._store.stream_events(self.stream, after_version=version, through_version=self.version)

    def minimal(self) -> MinimalProjection:
        # 到这个版本为止的最小投影（设计说明第 4 节）：裁决只读这一份，由骨架事件折叠而成。
        # 只看已提交的事件，事务里追加的事件由 Transaction 接着折
        if self._minimal is None:
            events = Snapshot.events(self)
            folded = fold_events(events) if self._minimal_of is None else self._minimal_of(self.stream, self.version,
                                                                                          events)
            self._minimal = folded
        return self._minimal


class Transaction(Snapshot):
    # 一次「读取保存的投影、判断、追加」：追加的事件立即并入 projection、decisions 与 events()，提交时一起写入。
    # 判断可能因为版本冲突重新进行，判断中只做可以重复的事；只应在提交以后发生的进程内效果用 on_commit 登记，
    # 没有提交（判断出错、版本冲突或存储失败）时要撤回的外部效果用 on_abort 登记
    def __init__(self, store: EventStore, stream: str, saved: SavedProjection | None,
                 handler: StreamHandler, command: Command | None = None,
                 minimal_of: Callable[[str, int, list[Any]], MinimalProjection] | None = None) -> None:
        super().__init__(store, stream, saved, handler, minimal_of)
        self.appended: list[Any] = []
        self._command = command
        self._changed_decisions: list[str] = []
        self._compensations: list[Callable[[], None]] = []
        self._committed_effects: list[Callable[[], None]] = []
        self._appended_minimal: MinimalProjection | None = None

    def append(self, *entries: NewEvent | NewProjectEvent) -> list[Any]:
        # 先得出全部事件（载荷无法保存时在这里失败，什么也不追加），再依次并入投影与决定请求。
        # 由命令写入的事件记下命令身份，提出者是命令的提出者
        first = self.version + len(self.appended) + 1
        events = [_event(self.stream, entry, first + offset, self._command) for offset, entry in enumerate(entries)]
        for event in events:
            self.handler.fold(self.projection, event)
            if isinstance(event, Event):
                # run 所属的项目与事项取自它的 run_created 事件
                event.project_id, event.work_item_id = self.projection.project_id, self.projection.work_item_id
            changed = apply_decision_event(self.decisions, event)
            if changed is not None and changed not in self._changed_decisions:
                self._changed_decisions.append(changed)
            self.appended.append(event)
        if self._appended_minimal is not None:
            # 事务里已经折过一份最小投影：这次追加的事件接在后面折，不必整条流重算
            self._appended_minimal = fold_more(self._appended_minimal, events)
        return events

    def minimal(self) -> MinimalProjection:
        # 到这个事务此刻的状态（含已追加、还没提交的事件）为止的最小投影：裁决在一个事务里读这一份
        if self._appended_minimal is None:
            self._appended_minimal = fold_more(Snapshot.minimal(self), self.appended)
        return self._appended_minimal

    def changed_decisions(self) -> list[SavedDecision]:
        # 这次事务改变的决定请求要保存的投影
        return [dump_decision(self.decisions[decision_id]) for decision_id in self._changed_decisions]

    def events(self) -> list[Any]:
        return super().events() + self.appended

    def events_after(self, version: int) -> list[Any]:
        return super().events_after(version) + [event for event in self.appended if event.stream_version > version]

    def on_abort(self, compensation: Callable[[], None]) -> None:
        # 登记事务没有提交时要撤回的外部效果（例如已经发布的材料）
        self._compensations.append(compensation)

    def on_commit(self, effect: Callable[[], None]) -> None:
        # 登记事务提交以后才发生的效果（例如进程内的状态），判断重新进行时不会重复
        self._committed_effects.append(effect)

    def _abort(self) -> None:
        for compensation in reversed(self._compensations):
            compensation()

    def _after_commit(self) -> None:
        for effect in self._committed_effects:
            effect()


class WritePath:
    # 所有领域写入唯一的入口；投影的折叠与保存按流的处理者进行，处理者由构造它的一方给出

    def __init__(self, store: EventStore, handler_for: Callable[[str], StreamHandler]) -> None:
        self._store = store
        self._handler_for = handler_for
        # 按流的版本记住折好的最小投影：流只追加，同一版本的结果不变，后面的事件在它上面接着折
        self._minimals: dict[str, tuple[int, MinimalProjection]] = {}

    def minimal(self, stream: str) -> MinimalProjection:
        # 一个流当前的最小投影：裁决只读这一份（设计说明第 4 节，S1d 工单 #860）
        saved = self._store.projection(stream)
        version = 0 if saved is None else saved.version
        return self._minimal_at(stream, version, self._store.stream_events(stream, through_version=version))

    def _minimal_at(self, stream: str, version: int, events: list[Any]) -> MinimalProjection:
        # 到这个版本为止的最小投影：有更早版本的缓存时只折后面的事件
        cached = self._minimals.get(stream)
        if cached is not None and cached[0] <= version:
            state = fold_more(cached[1], [event for event in events if event.stream_version > cached[0]])
        else:
            state = fold_events(events)
        self._minimals[stream] = (version, state)
        return state

    def read(self, stream: str) -> Snapshot:
        # 读取流保存的投影与流版本，用于之后以这个版本作为期望版本提交的判断
        return Snapshot(self._store, stream, self._store.projection(stream), self._handler_for(stream),
                        self._minimal_at)

    def transact(self, stream: str, decide: Callable[[Transaction], T], *, expected_version: int | None = None,
                 command: Command | None = None, epoch: int | None = None) -> T:
        # 在一个事务中读取保存的投影、由 decide 判断并追加事件、提交。
        # expected_version 为空时，提交因另一方的写入被拒绝就按写入以后的状态重新调用 decide，直到提交成功；
        # 给出 expected_version 时，读取或提交时流版本与它不同都拒绝（StreamVersionConflict），不重新判断。
        # command 是引起这次写入的命令：同一身份已经登记时不调用 decide，内容相同拒绝为 DuplicateCommand，不同为
        # CommandIdReused；被拒绝的命令不登记；追加的事件记下命令身份与提出者。epoch 是写入方的执行权编号，随事件记录，
        # 小于这个流已经记录的编号时拒绝（StaleExecutionRight）；取得执行权的规则由 3.1 加入。
        # 提交以后执行 on_commit 登记的效果，再通知事件日志的订阅方；这以后出的错不影响已经提交的写入
        attempt = 0
        while True:
            attempt += 1
            if command is not None:
                self._store.check_command(command)
            transaction = Transaction(self._store, stream, self._store.projection(stream),
                                      self._handler_for(stream), command, self._minimal_at)
            if expected_version is not None and transaction.version != expected_version:
                raise StreamVersionConflict(stream, expected_version, transaction.version)
            try:
                result = decide(transaction)
                if transaction.appended or command is not None:
                    self._store.commit(stream, transaction.version, transaction.appended,
                                       transaction.handler.dump(transaction.projection), epoch=epoch, command=command,
                                       decisions=transaction.changed_decisions())
            except StreamVersionConflict as conflict:
                transaction._abort()
                if expected_version is not None or conflict.stream != stream or attempt == MAX_JUDGMENTS:
                    raise
                continue
            except BaseException:
                transaction._abort()
                raise
            transaction._after_commit()
            self._store.notify(transaction.appended)
            return result

    def append(self, stream: str, *entries: NewEvent | NewProjectEvent, expected_version: int | None = None,
               epoch: int | None = None) -> list[Any]:
        # 不需要读取投影作判断的追加
        return self.transact(stream, lambda transaction: transaction.append(*entries),
                             expected_version=expected_version, epoch=epoch)
    def claim_execution_right(self, stream: str, decide: Callable[[Transaction], T], *,
                              expected_version: int | None = None) -> tuple[int, T]:
        # 取得这个 run 的执行权（工单 #16，ADR-0018）：读取保存的投影，由 decide 判断并追加事件，
        # 在一个事务中核对流版本、以已记录的执行权编号加一作为新编号，随这次追加的事件一起写入并更新保存的投影。
        # 返回这次取得的执行权编号与 decide 的结果；调用方之后的有权推进的写入都携带这个编号，
        # 编号小于这个流已经记录的编号时由写入口拒绝（StaleExecutionRight）。
        # 执行权没有期限与续期，编号只用于进程重启与两个进程同时恢复的情况。
        # 判断期间不持有锁：另一方先写入同一个流时提交因版本不符被拒绝，按写入以后的状态重新判断
        attempt = 0
        while True:
            attempt += 1
            transaction = Transaction(self._store, stream, self._store.projection(stream), self._handler_for(stream),
                                      None, self._minimal_at)
            if expected_version is not None and transaction.version != expected_version:
                raise StreamVersionConflict(stream, expected_version, transaction.version)
            try:
                result = decide(transaction)
                if not transaction.appended:
                    raise ValueError("claiming an execution right requires the events that record it")
                epoch = self._store.claim_execution_right(
                    stream, transaction.version, transaction.appended, transaction.handler.dump(transaction.projection),
                    decisions=transaction.changed_decisions())
            except StreamVersionConflict as conflict:
                transaction._abort()
                if expected_version is not None or conflict.stream != stream or attempt == MAX_JUDGMENTS:
                    raise
                continue
            except BaseException:
                transaction._abort()
                raise
            transaction._after_commit()
            self._store.notify(transaction.appended)
            return epoch, result

    def rebuild(self, stream: str) -> Any:
        # 从这个流的第一条事件重放投影与决定请求，替换保存的投影
        handler = self._handler_for(stream)
        events = self._store.stream_events(stream)
        state = handler.replay(stream, events)
        decisions = replay_decisions(events)
        self._store.replace_projection(stream, len(events), handler.dump(state),
                                       [dump_decision(decision) for decision in decisions.values()])
        return state

    def rebuild_missing(self) -> list[str]:
        # 为有事件但没有保存投影的流重放并保存投影（例如保存的投影被删除以后）
        streams = self._store.streams_without_projection()
        for stream in streams:
            self.rebuild(stream)
        return streams


def _resolve_actor(entry_actor: str | None, command: Command | None, stream: str) -> str:
    # 提出者由写入方经写入口声明（设计第 5.2 节）：由命令写入时取命令的提出者，
    # 其余取写入方声明的提出者；两者都没有时这次写入失败（每条事件都有提出者，不允许落空）
    actor = command.actor if command is not None else entry_actor
    if not isinstance(actor, str) or not actor:
        raise ValueError(f"{stream} event requires a declared actor")
    return actor


def _event(stream: str, entry: NewEvent | NewProjectEvent | NewCatalogEvent, version: int,
           command: Command | None) -> Event | ProjectEvent | CatalogEvent:
    identity = stream.split(":", 1)[1]
    # 载荷取它在日志中保存的形式（JSON），并入投影的内容与从日志重放时读到的完全相同
    payload = json.loads(json_dumps(entry.payload))
    command_id = None if command is None else command.command_id
    actor = _resolve_actor(entry.actor, command, stream)
    if isinstance(entry, NewCatalogEvent):
        if not is_catalog_stream(stream):
            raise TypeError(f"{type(entry).__name__} cannot be appended to {stream}")
        return CatalogEvent(
            event_id=new_id("cevt"), type=entry.type, payload=payload, created_at=utc_now(), position=0,
            stream=stream, stream_version=version, command_id=command_id, actor=actor,
        )
    if is_catalog_stream(stream):
        raise TypeError(f"{type(entry).__name__} cannot be appended to {stream}")
    if is_run_stream(stream) != isinstance(entry, NewEvent):
        raise TypeError(f"{type(entry).__name__} cannot be appended to {stream}")
    if isinstance(entry, NewEvent):
        _check_stop_reason(entry)
        if entry.department is not None and entry.department not in DEFINITIONS.departments:
            raise ValueError(f"unknown department {entry.department!r} on a run event")
        return Event(
            event_id=new_id("evt"), run_id=identity, type=entry.type, role=None,
            parent_event_id=entry.parent_event_id, state_before=entry.state_before, state_after=entry.state_after,
            payload=payload, artifact_hashes=list(entry.artifact_hashes), session_id=entry.session_id,
            provider=entry.provider, model=entry.model, context_digest=entry.context_digest,
            stop_reason=entry.stop_reason, error=entry.error, created_at=utc_now(), position=0, stream=stream,
            stream_version=version, project_id=None, work_item_id=None,
            department=entry.department,
            command_id=command_id, actor=actor,
        )
    return ProjectEvent(
        event_id=new_id("pevt"), project_id=identity, type=entry.type, payload=payload, created_at=utc_now(),
        position=0, stream=stream, stream_version=version, work_item_id=payload.get("work_item_id"),
        run_id=payload.get("run_id"), department=payload.get("department"),
        command_id=command_id, actor=actor,
    )


def _check_stop_reason(entry: NewEvent) -> None:
    # 停止原因只来自定义中的清单，只由结束运行的事件承载，与原因规定的结束方式及事件写入的终态一致，
    # 载荷中的停止原因与事件的停止原因相同；否则这次写入失败
    ending = _STOP_EVENTS.get(entry.type)
    if entry.stop_reason is None:
        if ending is not None:
            raise ValueError(f"{entry.type} requires a stop reason")
        return
    defined = DEFINITIONS.stop_reason(entry.stop_reason).outcome
    if ending is None or defined != ending[0]:
        raise ValueError(f"stop reason {entry.stop_reason} ends a run as {defined}; it cannot be recorded on {entry.type}")
    if entry.state_after != ending[1] or entry.payload.get("stop_reason") != entry.stop_reason:
        raise ValueError(f"{entry.type} with stop reason {entry.stop_reason} must end in {ending[1]} "
                         "and carry the same stop reason in its payload")
