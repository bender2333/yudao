# 应用层的事件流（应用层与接口层设计说明第 5 节）：一个 GET /api/events 连接的读取与转发。
#
# 连接的处理顺序（第 5.4 节）：先向事件日志登记一个有界队列订阅，再从 after 按范围分批读取历史事件并发送，
# 然后把队列里位置更大的事件继续发出；空闲 5 秒或连续跳过 1000 条不在范围内的事件时发出检查点；
# 保活注释由接口层每 15 秒发送。队列溢出或 after 大于日志末尾时发出 resync 并关闭（第 5.5 节）。
#
# 范围筛选与按相同条件读取事件日志共用同一组条件（第 5.3 节）：历史读取经 EventStore.read 的 SQL 条件，
# 队列里的事件经 matches 判定，两者语义一致。
#
# 模型输出片段不在事件日志中（第 5.6 节）：带 live=1 的连接接收片段泵按同样范围合并后的片段。

from __future__ import annotations

import asyncio
import queue
from collections.abc import AsyncIterator, Sequence
from typing import Literal, Union

from pydantic import BaseModel, TypeAdapter

from ..app.contracts import Contract, EventObject, OutputDelta
from ..deltas import DeltaFragment, DeltaPump
from ..event_store import EventStore
from ..models import CatalogEvent, Event, ProjectEvent
from .labels import event_label

BATCH_SIZE = 500
# 一个连接的订阅队列长度：客户端处理太慢导致队列溢出时发送 resync 并关闭
QUEUE_LIMIT = 4096
# 空闲这么久没有事件可发时发送一次检查点
CHECKPOINT_IDLE_SEC = 5.0
# 连续跳过这么多条不在范围内的事件时发送一次检查点
CHECKPOINT_SKIPPED = 1000
# 等待新事件与片段的时间片
POLL_SEC = 0.05

StoredEvent = Union[Event, ProjectEvent, CatalogEvent]
# 事件对象：以 type 区分的联合，这里按读到的类型与载荷构造
_EVENT_OBJECT = TypeAdapter(EventObject)

class EventScope(BaseModel):
    # 事件流的范围（第 5.1、5.3 节）：省略项目为跨项目；同一参数的多个值取并集，各参数之间取交集
    model_config = {"extra": "forbid"}

    projects: tuple[str, ...] = ()
    work_items: tuple[str, ...] = ()
    runs: tuple[str, ...] = ()
    departments: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    types: tuple[str, ...] = ()

class StreamEvent(BaseModel):
    # 一条要发送的事件：事件对象（第 5.2 节）与接口层编码 SSE 需要的位置
    kind: Literal["event"] = "event"
    position: int
    previous: int
    event: Contract

class StreamCheckpoint(BaseModel):
    # 检查点：位置为已经扫描到的位置，客户端据此续传
    kind: Literal["checkpoint"] = "checkpoint"
    position: int
    previous: int

class StreamResync(BaseModel):
    # 重新同步：原因与当前日志末尾位置，连接随后关闭（第 5.5 节）
    kind: Literal["resync"] = "resync"
    reason: Literal["queue_overflow", "position_unknown"]
    end_position: int

class StreamDelta(BaseModel):
    # 转发给 live=1 连接的一段模型输出片段（第 5.6 节）：SSE 事件名为 delta，不带 id
    kind: Literal["delta"] = "delta"
    delta: OutputDelta

StreamMessage = Union[StreamEvent, StreamCheckpoint, StreamResync, StreamDelta]

class _Subscriber:
    # 一个连接的有界订阅队列：事件日志的订阅回调同步写入，写满时标记溢出
    def __init__(self, limit: int) -> None:
        self.events: queue.Queue[StoredEvent] = queue.Queue(maxsize=limit)
        self.overflow = False

class EventStream:
    # 一个连接的读取与转发。messages() 是异步生成器，接口层逐个取消息并编码成 SSE
    def __init__(self, store: EventStore, scope: EventScope, *, after: int, live: bool = False,
                 pump: DeltaPump | None = None, batch_size: int = BATCH_SIZE, queue_limit: int = QUEUE_LIMIT,
                 checkpoint_idle_sec: float = CHECKPOINT_IDLE_SEC,
                 checkpoint_skipped: int = CHECKPOINT_SKIPPED) -> None:
        self._store = store
        self._scope = scope
        self._after = max(after, 0)
        self._live = live
        self._pump = pump
        self._batch_size = batch_size
        self._queue_limit = queue_limit
        self._checkpoint_idle_sec = checkpoint_idle_sec
        self._checkpoint_skipped = checkpoint_skipped
        # 本连接上一条事件或检查点的位置；第一条为 after（第 5.5 节）
        self._previous = self._after
        self._scanned = self._after
        self._skipped = 0
        # 本连接在片段泵上的待发队列（第 5.6 节）：连接建立时登记，连接结束时取消
        self._delta_queue: deque[DeltaFragment] | None = None
        self._unsubscribe_deltas: Callable[[], None] | None = None

    def matches(self, event: StoredEvent) -> bool:
        # 一条事件是否在范围内（第 5.3 节）：省略的范围不限制，给出的范围取并集；
        # 项目与目录事件没有部门或种类以外的列时为 None，None 不属于任何给出的范围
        scope = self._scope
        return (_within(scope.projects, getattr(event, "project_id", None))
                and _within(scope.work_items, getattr(event, "work_item_id", None))
                and _within(scope.runs, getattr(event, "run_id", None))
                and _within(scope.departments, getattr(event, "department", None))
                and _within(scope.roles, getattr(event, "role", None))
                and _within(scope.types, event.type))

    async def messages(self) -> AsyncIterator[StreamMessage]:
        store = self._store
        end = store.end_position()
        if self._after > end:
            # 位置超过日志末尾：客户端记录的位置来自另一个部署或数据目录
            yield StreamResync(reason="position_unknown", end_position=end)
            return
        subscriber = _Subscriber(self._queue_limit)
        unsubscribe = store.subscribe(lambda events: _collect(subscriber, events))
        if self._live and self._pump is not None:
            # 本连接的片段待发队列；取消函数在连接结束时调用（finally）
            self._delta_queue = self._pump.subscribe()
            self._unsubscribe_deltas = self._pump.unsubscribe(self._delta_queue)
        try:
            async for message in self._backfill(subscriber):
                yield message
        finally:
            unsubscribe()
            if self._unsubscribe_deltas is not None:
                self._unsubscribe_deltas()
                self._unsubscribe_deltas = None
                self._delta_queue = None

    async def _backfill(self, subscriber: _Subscriber) -> AsyncIterator[StreamMessage]:
        store = self._store
        scope = self._scope
        cursor = self._after
        while True:
            batch = store.read(after=cursor, limit=self._batch_size, projects=scope.projects,
                               work_items=scope.work_items, runs=scope.runs,
                               departments=scope.departments, types=scope.types)
            for event in batch:
                if self.matches(event):
                    yield self._event_message(event)
            if len(batch) < self._batch_size:
                break
            cursor = batch[-1].position
        async for message in self._forward(subscriber):
            yield message

    async def _forward(self, subscriber: _Subscriber) -> AsyncIterator[StreamMessage]:
        store = self._store
        idle_since: float | None = None
        while True:
            if subscriber.overflow:
                yield StreamResync(reason="queue_overflow", end_position=store.end_position())
                return
            # 片段先转发：它们不属于事件日志的位置序列，与事件顺序无关
            for message in self._drain_deltas():
                yield message
            drained = _drain(subscriber)
            if drained:
                for event in drained:
                    if event.position <= self._previous:
                        continue
                    if self.matches(event):
                        yield self._event_message(event)
                        idle_since = None
                    else:
                        self._scanned = max(self._scanned, event.position)
                        self._skipped += 1
                continue
            if self._skipped >= self._checkpoint_skipped:
                yield self._checkpoint()
                idle_since = None
                continue
            if idle_since is None:
                idle_since = asyncio.get_running_loop().time()
            if asyncio.get_running_loop().time() - idle_since >= self._checkpoint_idle_sec:
                yield self._checkpoint()
                idle_since = None
                continue
            await asyncio.sleep(POLL_SEC)

    def _checkpoint(self) -> StreamCheckpoint:
        # 检查点的位置是已经扫描到的位置：历史读完以后为日志末尾，队列推进以后为处理过的最大位置
        scanned = max(self._scanned, self._store.end_position())
        checkpoint = StreamCheckpoint(position=scanned, previous=self._previous)
        self._previous = scanned
        self._scanned = scanned
        self._skipped = 0
        return checkpoint

    def _event_message(self, event: StoredEvent) -> StreamEvent:
        message = StreamEvent(position=event.position, previous=self._previous, event=self._object(event))
        self._previous = event.position
        self._scanned = max(self._scanned, event.position)
        return message

    def _object(self, event: StoredEvent) -> Contract:
        # 事件对象（第 5.2 节）：公共字段加上按种类确定的 type 与 payload
        fields = {
            "position": event.position, "previous": self._previous, "event_id": event.event_id,
            "at": event.created_at, "stream": event.stream, "stream_version": event.stream_version,
            "project_id": getattr(event, "project_id", None), "work_item_id": getattr(event, "work_item_id", None),
            "run_id": getattr(event, "run_id", None), "department": getattr(event, "department", None),
            "role": getattr(event, "role", None), "actor": event.actor or "",
            "command_id": event.command_id, "label": event_label(event.type, event.payload),
        }
        return _EVENT_OBJECT.validate_python({**fields, "type": event.type, "payload": event.payload})

    def _drain_deltas(self) -> list[StreamDelta]:
        # 这一合并周期里本连接的片段：先驱动一次泵的合并周期（把被接受的片段分发进每个登记的待发队列，
        # 各连接再从自己的队列弹出），先到的连接取走不影响其他连接（第 5.6 节）
        if not self._live or self._pump is None or self._delta_queue is None:
            return []
        self._pump.drain()
        messages: list[StreamDelta] = []
        while self._delta_queue:
            fragment = self._delta_queue.popleft()
            if not self._in_delta_scope(fragment):
                continue
            delta = OutputDelta(
                attempt_id=fragment.scope.attempt_id, logical_call_id=fragment.scope.logical_call_id,
                project_id=fragment.scope.project_id, work_item_id=fragment.scope.work_item_id,
                run_id=fragment.scope.run_id, department=fragment.scope.department, role=fragment.scope.role,
                channel=fragment.channel, offset=fragment.offset, text=fragment.text,
            )
            messages.append(StreamDelta(delta=delta))
        return messages

    def _in_delta_scope(self, fragment: DeltaFragment) -> bool:
        # 片段按项目、事项、run 与部门与连接的范围比对；种类与角色不适用于片段
        scope = self._scope
        return (_within(scope.projects, fragment.scope.project_id)
                and _within(scope.work_items, fragment.scope.work_item_id)
                and _within(scope.runs, fragment.scope.run_id)
                and _within(scope.departments, fragment.scope.department))

def _collect(subscriber: _Subscriber, events: Sequence[StoredEvent]) -> None:
    # 事件日志的订阅回调：在有界队列里写入这次提交的事件，写满即标记溢出，不阻塞写入方
    for event in events:
        try:
            subscriber.events.put_nowait(event)
        except queue.Full:
            subscriber.overflow = True
            return

def _drain(subscriber: _Subscriber) -> list[StoredEvent]:
    drained: list[StoredEvent] = []
    while True:
        try:
            drained.append(subscriber.events.get_nowait())
        except queue.Empty:
            return drained

def _within(values: tuple[str, ...], value: str | None) -> bool:
    # 一个范围条件：没有给出时不限制；给出时值必须在其中，None 不属于任何给出的范围
    if not values:
        return True
    return value in values
