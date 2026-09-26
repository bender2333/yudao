# 写入口：所有领域写入唯一的入口。流程编排、记录接口、提交、交互与项目服务写入事件都经过这里；
# 一次调用的事件在同一个事务中追加，同一事务更新这个流保存的投影（运行状态投影或项目投影）。
# lock 是「读取运行状态、判断、追加」期间持有的锁，append 也在它之下进行。
# #44 以同一事务中的读取、判断与流版本核对代替这把锁

from __future__ import annotations

import json
import threading
from collections.abc import Sequence
from dataclasses import KW_ONLY, dataclass, field
from typing import Any

from .event_store import EventStore, is_run_stream, project_stream, run_stream
from .models import DEPARTMENTS, Event, ProjectEvent, json_dumps, new_id, utc_now
from .projection import Projection, dump_projection, empty_projection, fold, load_projection, replay


@dataclass(frozen=True)
class NewEvent:
    # 一条要追加的 run 事件；事件编号、日志位置、流内版本与创建时间在追加时确定
    type: str
    _: KW_ONLY
    state_before: str
    state_after: str
    role: str | None = None
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
    # 一条要追加的项目事件
    type: str
    payload: dict[str, Any] = field(default_factory=dict)


class WritePath:
    def __init__(self, store: EventStore) -> None:
        self._store = store
        self.lock = threading.RLock()

    def append(self, run_id: str, *events: NewEvent) -> list[Event]:
        with self.lock:
            return self._append(run_stream(run_id), events)

    def append_project(self, project_id: str, type: str, payload: dict[str, Any] | None = None) -> ProjectEvent:
        with self.lock:
            return self._append(project_stream(project_id), [NewProjectEvent(type, dict(payload or {}))])[0]

    def rebuild(self, stream: str) -> Projection:
        # 从这个流的第一条事件重放投影，替换保存的投影
        events = self._store.stream_events(stream)
        state = replay(stream, events)
        self._store.replace_projection(stream, len(events), dump_projection(state))
        return state

    def rebuild_missing(self) -> list[str]:
        # 为有事件但没有保存投影的流重放并保存投影（例如保存的投影被删除以后）
        streams = self._store.streams_without_projection()
        for stream in streams:
            self.rebuild(stream)
        return streams

    def _append(self, stream: str, entries: Sequence[NewEvent | NewProjectEvent]) -> list[Any]:
        saved = self._store.projection(stream)
        state = empty_projection(stream) if saved is None else load_projection(saved, stream)
        version = 0 if saved is None else saved.version
        events = []
        for offset, entry in enumerate(entries, start=1):
            event = _event(stream, entry, version + offset)
            fold(state, event)
            if isinstance(event, Event):
                # run 所属的项目与事项取自它的 run_created 事件
                event.project_id, event.work_item_id = state.project_id, state.work_item_id
            events.append(event)
        self._store.commit(stream, version, events, dump_projection(state))
        return events


def _event(stream: str, entry: NewEvent | NewProjectEvent, version: int) -> Event | ProjectEvent:
    identity = stream.split(":", 1)[1]
    if is_run_stream(stream) != isinstance(entry, NewEvent):
        raise TypeError(f"{type(entry).__name__} cannot be appended to {stream}")
    # 载荷取它在日志中保存的形式（JSON），并入投影的内容与从日志重放时读到的完全相同
    payload = json.loads(json_dumps(entry.payload))
    if isinstance(entry, NewEvent):
        return Event(
            event_id=new_id("evt"), run_id=identity, type=entry.type, role=entry.role,
            parent_event_id=entry.parent_event_id, state_before=entry.state_before, state_after=entry.state_after,
            payload=payload, artifact_hashes=list(entry.artifact_hashes), session_id=entry.session_id,
            provider=entry.provider, model=entry.model, context_digest=entry.context_digest,
            stop_reason=entry.stop_reason, error=entry.error, created_at=utc_now(), position=0, stream=stream,
            stream_version=version, project_id=None, work_item_id=None,
            department=entry.role if entry.role in DEPARTMENTS else None,
        )
    return ProjectEvent(
        event_id=new_id("pevt"), project_id=identity, type=entry.type, payload=payload, created_at=utc_now(),
        position=0, stream=stream, stream_version=version, work_item_id=payload.get("work_item_id"),
        run_id=payload.get("run_id"), department=payload.get("department"),
    )
