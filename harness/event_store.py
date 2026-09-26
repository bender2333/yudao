# 事件日志：系统唯一的事实来源。run 事件与项目事件在同一份日志中：每条事件有全局位置（跨项目递增）、
# 所属的流（run:<run_id>、project:<project_id>）与流内版本（同一个流内唯一）；另存项目、事项、run、部门与种类，
# 建立索引供范围读取。日志只追加。
# 每个流保存一份投影（投影的内容由写入口计算，这里按 JSON 文本存放），与这个流的事件在同一个事务中写入；
# 提交时核对流版本，与调用方读取时的版本不同就拒绝。

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Event, ProjectEvent, json_dumps


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
CREATE TABLE IF NOT EXISTS projections (
    stream TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    position INTEGER NOT NULL,
    state TEXT NOT NULL
);
"""

_RUN = "run:"
_PROJECT = "project:"


def run_stream(run_id: str) -> str:
    return _RUN + run_id


def project_stream(project_id: str) -> str:
    return _PROJECT + project_id


def is_run_stream(stream: str) -> bool:
    return stream.startswith(_RUN)


class StreamVersionConflict(Exception):
    # 追加时给出的期望版本与流的当前版本不同：判断所依据的状态已经过期，写入被拒绝
    def __init__(self, stream: str, expected: int, actual: int) -> None:
        super().__init__(f"stream {stream} is at version {actual}, not the expected version {expected}; "
                         "the judgment was made on a stale state")
        self.stream = stream
        self.expected = expected
        self.actual = actual


@dataclass(frozen=True)
class SavedProjection:
    # 一个流保存的投影：投影所反映的流版本、最后一条事件的全局位置与投影的 JSON 文本
    version: int
    position: int
    state: str


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

    def commit(self, stream: str, expected_version: int, events: Sequence[Event | ProjectEvent], state: str) -> None:
        # 在一个事务中：核对流的当前版本等于 expected_version，按顺序追加事件（全局位置在这里确定，写回事件），
        # 保存这个流的投影。版本不符时拒绝，什么也不写
        with self._lock, self._conn:
            current = self._version(stream)
            if current != expected_version:
                raise StreamVersionConflict(stream, expected_version, current)
            for event in events:
                event.position = self._insert(event)
            position = events[-1].position if events else self._saved_position(stream)
            self._conn.execute(
                "INSERT INTO projections (stream, version, position, state) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(stream) DO UPDATE SET version = excluded.version, position = excluded.position, "
                "state = excluded.state",
                (stream, expected_version + len(events), position, state),
            )

    def replace_projection(self, stream: str, version: int, state: str) -> None:
        # 用重放得到的投影替换这个流保存的投影；version 是重放到的流版本，流在重放以后又有写入时拒绝
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(stream_version), 0) AS version, COALESCE(MAX(position), 0) AS position "
                "FROM events WHERE stream = ?", (stream,),
            ).fetchone()
            if row["version"] != version:
                raise StreamVersionConflict(stream, version, row["version"])
            self._conn.execute(
                "INSERT INTO projections (stream, version, position, state) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(stream) DO UPDATE SET version = excluded.version, position = excluded.position, "
                "state = excluded.state",
                (stream, version, row["position"], state),
            )

    def projection(self, stream: str) -> SavedProjection | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT version, position, state FROM projections WHERE stream = ?", (stream,)
            ).fetchone()
        return None if row is None else SavedProjection(row["version"], row["position"], row["state"])

    def streams_without_projection(self) -> list[str]:
        # 有事件但没有保存投影的流
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT stream FROM events WHERE stream NOT IN (SELECT stream FROM projections)"
            ).fetchall()
        return [row["stream"] for row in rows]

    def stream_events(self, stream: str, *, after_version: int = 0) -> list[Event] | list[ProjectEvent]:
        # 一个流中流内版本大于 after_version 的事件，按版本排列
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE stream = ? AND stream_version > ? ORDER BY stream_version ASC",
                (stream, after_version),
            ).fetchall()
        return [_from_row(row) for row in rows]

    def list_events(self, run_id: str, *, after_version: int = 0) -> list[Event]:
        return self.stream_events(run_stream(run_id), after_version=after_version)

    def list_project_events(self, project_id: str, *, after_version: int = 0) -> list[ProjectEvent]:
        return self.stream_events(project_stream(project_id), after_version=after_version)

    def read(self, after: int = 0, *, limit: int = 1000, projects: Sequence[str] = (),
             work_items: Sequence[str] = (), runs: Sequence[str] = (), departments: Sequence[str] = (),
             types: Sequence[str] = ()) -> list[Event | ProjectEvent]:
        # 按全局位置分批读取：位置大于 after 的事件，按位置排列，至多 limit 条。
        # 各个范围之间取交集，同一个范围的多个值取并集；省略的范围不限制
        if limit < 1:
            raise ValueError("limit must be positive")
        clauses: list[str] = ["position > ?"]
        params: list[Any] = [after]
        for column, values in (("project_id", projects), ("work_item_id", work_items), ("run_id", runs),
                               ("department", departments), ("type", types)):
            if values:
                clauses.append(f"{column} IN ({', '.join('?' * len(values))})")
                params.extend(values)
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM events WHERE {' AND '.join(clauses)} ORDER BY position ASC LIMIT ?", params,
            ).fetchall()
        return [_from_row(row) for row in rows]

    def end_position(self) -> int:
        # 日志末尾的全局位置；日志为空时是 0
        with self._lock:
            row = self._conn.execute("SELECT COALESCE(MAX(position), 0) AS position FROM events").fetchone()
        return int(row["position"])

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

    def _get(self, event_id: str) -> Event | ProjectEvent | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
        return None if row is None else _from_row(row)

    def _version(self, stream: str) -> int:
        row = self._conn.execute("SELECT version FROM projections WHERE stream = ?", (stream,)).fetchone()
        return 0 if row is None else int(row["version"])

    def _saved_position(self, stream: str) -> int:
        row = self._conn.execute("SELECT position FROM projections WHERE stream = ?", (stream,)).fetchone()
        return 0 if row is None else int(row["position"])

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
