# 事件日志：系统唯一的事实来源。run 事件与项目事件在同一份日志中：每条事件有全局位置（跨项目递增）、
# 所属的流（run:<run_id>、project:<project_id>）与流内版本（同一个流内唯一）；另存项目、事项、run、部门与种类，
# 建立索引供范围读取。日志只追加。

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Sequence
from dataclasses import KW_ONLY, dataclass, field
from pathlib import Path
from typing import Any

from .models import DEPARTMENTS, Event, EventType, ProjectEvent, json_dumps, new_id, utc_now


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    position INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    stream TEXT NOT NULL,
    stream_version INTEGER NOT NULL,
    project_id TEXT,
    work_item_id TEXT,
    run_id TEXT,
    department TEXT,
    type TEXT NOT NULL,
    role TEXT,
    parent_event_id TEXT,
    state_before TEXT,
    state_after TEXT,
    payload_json TEXT NOT NULL,
    artifact_hashes_json TEXT NOT NULL,
    session_id TEXT,
    provider TEXT,
    model TEXT,
    context_digest TEXT,
    stop_reason TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(stream, stream_version),
    CHECK (stream NOT LIKE 'run:%' OR (state_before IS NOT NULL AND state_after IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_events_project ON events(project_id, position);
CREATE INDEX IF NOT EXISTS idx_events_work_item ON events(work_item_id, position);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, position);
CREATE INDEX IF NOT EXISTS idx_events_department ON events(department, position);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type, position);
"""

_RUN = "run:"
_PROJECT = "project:"


def run_stream(run_id: str) -> str:
    return _RUN + run_id


def project_stream(project_id: str) -> str:
    return _PROJECT + project_id


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


class WritePath:
    # 领域写入唯一的写入函数：流程编排、记录接口、提交与交互写入 run 的事件都经过 append，
    # 一次调用的事件在同一个事务中追加。lock 是「读取运行状态、判断、追加」期间持有的锁，append 也在它之下进行。
    # #44 在 append 上加入流版本与执行权的事务核对，并以同一事务中的读取与判断代替这把锁
    def __init__(self, store: EventStore) -> None:
        self._store = store
        self.lock = threading.RLock()

    def append(self, run_id: str, *events: NewEvent) -> list[Event]:
        with self.lock:
            return self._store.append_batch(run_id, events)


class EventStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.commit()

    def append_batch(self, run_id: str, entries: Sequence[NewEvent]) -> list[Event]:
        stream = run_stream(run_id)
        events = [
            Event(event_id=new_id("evt"), run_id=run_id, type=entry.type, role=entry.role,
                  parent_event_id=entry.parent_event_id, state_before=entry.state_before,
                  state_after=entry.state_after, payload=entry.payload, artifact_hashes=list(entry.artifact_hashes),
                  session_id=entry.session_id, provider=entry.provider, model=entry.model,
                  context_digest=entry.context_digest, stop_reason=entry.stop_reason, error=entry.error,
                  created_at=utc_now(), position=0, stream=stream, stream_version=0, project_id=None,
                  work_item_id=None, department=entry.role if entry.role in DEPARTMENTS else None)
            for entry in entries
        ]
        with self._lock, self._conn:
            version = self._stream_version(stream)
            project_id, work_item_id = self._run_owner(stream, events)
            for offset, event in enumerate(events, start=1):
                event.stream_version = version + offset
                event.project_id, event.work_item_id = project_id, work_item_id
                event.position = self._insert(event)
        return events

    def append_project(self, project_id: str, type: str, payload: dict[str, Any] | None = None) -> ProjectEvent:
        payload = dict(payload or {})
        stream = project_stream(project_id)
        event = ProjectEvent(event_id=new_id("pevt"), project_id=project_id, type=type, payload=payload,
                             created_at=utc_now(), position=0, stream=stream, stream_version=0,
                             work_item_id=payload.get("work_item_id"), run_id=payload.get("run_id"),
                             department=payload.get("department"))
        with self._lock, self._conn:
            event.stream_version = self._stream_version(stream) + 1
            event.position = self._insert(event)
        return event

    def list_events(self, run_id: str, *, after_version: int = 0) -> list[Event]:
        # run 流中流内版本大于 after_version 的事件，按版本排列
        return self._stream_events(run_stream(run_id), after_version)

    def list_project_events(self, project_id: str, *, after_version: int = 0) -> list[ProjectEvent]:
        return self._stream_events(project_stream(project_id), after_version)

    def get_event(self, event_id: str) -> Event | None:
        event = self._get(event_id)
        return event if isinstance(event, Event) else None

    def get_project_event(self, event_id: str) -> ProjectEvent | None:
        event = self._get(event_id)
        return event if isinstance(event, ProjectEvent) else None

    def list_run_ids(self) -> list[str]:
        # 有事件的 run，最近写入的在前
        with self._lock:
            rows = self._conn.execute(
                "SELECT run_id FROM events WHERE stream LIKE 'run:%' GROUP BY run_id ORDER BY MAX(position) DESC"
            ).fetchall()
        return [row["run_id"] for row in rows]

    def list_project_ids(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT project_id FROM events WHERE stream LIKE 'project:%' GROUP BY project_id "
                "ORDER BY MAX(position) DESC"
            ).fetchall()
        return [row["project_id"] for row in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _stream_events(self, stream: str, after_version: int) -> list[Any]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE stream = ? AND stream_version > ? ORDER BY stream_version ASC",
                (stream, after_version),
            ).fetchall()
        return [_from_row(row) for row in rows]

    def _get(self, event_id: str) -> Event | ProjectEvent | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
        return None if row is None else _from_row(row)

    def _stream_version(self, stream: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(stream_version), 0) AS version FROM events WHERE stream = ?", (stream,)
        ).fetchone()
        return int(row["version"])

    def _run_owner(self, stream: str, events: list[Event]) -> tuple[str | None, str | None]:
        # run 所属的项目与事项取自它的 run_created 事件
        if events and events[0].type == EventType.RUN_CREATED:
            return events[0].payload.get("project_id"), events[0].payload.get("work_item_id")
        row = self._conn.execute(
            "SELECT project_id, work_item_id FROM events WHERE stream = ? AND stream_version = 1", (stream,)
        ).fetchone()
        return (None, None) if row is None else (row["project_id"], row["work_item_id"])

    def _insert(self, event: Event | ProjectEvent) -> int:
        if isinstance(event, Event):
            run_columns = (event.role, event.parent_event_id, event.state_before, event.state_after,
                           json_dumps(event.artifact_hashes), event.session_id, event.provider, event.model,
                           event.context_digest, event.stop_reason, event.error)
        else:
            run_columns = (None, None, None, None, json_dumps([]), None, None, None, None, None, None)
        cursor = self._conn.execute(
            """
            INSERT INTO events (
                event_id, stream, stream_version, project_id, work_item_id, run_id, department, type,
                role, parent_event_id, state_before, state_after, artifact_hashes_json,
                session_id, provider, model, context_digest, stop_reason, error, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (event.event_id, event.stream, event.stream_version, event.project_id, event.work_item_id,
             event.run_id, event.department, event.type, *run_columns, json_dumps(event.payload), event.created_at),
        )
        return int(cursor.lastrowid)


def _from_row(row: sqlite3.Row) -> Event | ProjectEvent:
    if row["stream"].startswith(_RUN):
        return Event(
            event_id=row["event_id"], run_id=row["run_id"], type=row["type"], role=row["role"],
            parent_event_id=row["parent_event_id"], state_before=row["state_before"],
            state_after=row["state_after"], payload=json.loads(row["payload_json"]),
            artifact_hashes=json.loads(row["artifact_hashes_json"]), session_id=row["session_id"],
            provider=row["provider"], model=row["model"], context_digest=row["context_digest"],
            stop_reason=row["stop_reason"], error=row["error"], created_at=row["created_at"],
            position=row["position"], stream=row["stream"], stream_version=row["stream_version"],
            project_id=row["project_id"], work_item_id=row["work_item_id"], department=row["department"],
        )
    return ProjectEvent(
        event_id=row["event_id"], project_id=row["project_id"], type=row["type"],
        payload=json.loads(row["payload_json"]), created_at=row["created_at"], position=row["position"],
        stream=row["stream"], stream_version=row["stream_version"], work_item_id=row["work_item_id"],
        run_id=row["run_id"], department=row["department"],
    )
