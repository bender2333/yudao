"""SQLite append-only Event Store。唯一事实来源。"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterator

from .models import Event, ProjectEvent, json_dumps, new_id, utc_now


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    type TEXT NOT NULL,
    role TEXT,
    parent_event_id TEXT,
    state_before TEXT NOT NULL,
    state_after TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    artifact_hashes_json TEXT NOT NULL,
    session_id TEXT,
    provider TEXT,
    model TEXT,
    context_digest TEXT,
    stop_reason TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_events_run_seq ON events(run_id, seq);
CREATE TABLE IF NOT EXISTS project_events (
    event_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_project_events_project_seq ON project_events(project_id, seq);
"""


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

    def append(
        self,
        run_id: str,
        type: str,
        *,
        role: str | None = None,
        parent_event_id: str | None = None,
        state_before: str,
        state_after: str,
        payload: dict[str, Any] | None = None,
        artifact_hashes: list[str] | None = None,
        session_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        context_digest: str | None = None,
        stop_reason: str | None = None,
        error: str | None = None,
    ) -> Event:
        return self.append_batch(run_id, [{
            "type": type, "role": role, "parent_event_id": parent_event_id,
            "state_before": state_before, "state_after": state_after, "payload": payload,
            "artifact_hashes": artifact_hashes, "session_id": session_id, "provider": provider,
            "model": model, "context_digest": context_digest, "stop_reason": stop_reason, "error": error,
        }])[0]

    def append_batch(self, run_id: str, entries: list[dict[str, Any]]) -> list[Event]:
        events = []
        for entry in entries:
            values = {
                "role": None, "parent_event_id": None, "session_id": None,
                "provider": None, "model": None, "context_digest": None, "stop_reason": None, "error": None,
                **entry,
                "payload": entry.get("payload") or {}, "artifact_hashes": list(entry.get("artifact_hashes") or []),
            }
            events.append(Event(event_id=new_id("evt"), run_id=run_id, seq=0, created_at=utc_now(), **values))
        with self._lock, self._conn:
            seq = self._next_seq(run_id)
            for offset, event in enumerate(events):
                event.seq = seq + offset
                self._insert(event)
        return events

    def _insert(self, event: Event) -> None:
        self._conn.execute(
            """
            INSERT INTO events (
                event_id, run_id, seq, type, role, parent_event_id,
                state_before, state_after, payload_json, artifact_hashes_json,
                session_id, provider, model, context_digest, stop_reason, error, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.run_id,
                event.seq,
                event.type,
                event.role,
                event.parent_event_id,
                event.state_before,
                event.state_after,
                json_dumps(event.payload),
                json_dumps(event.artifact_hashes),
                event.session_id,
                event.provider,
                event.model,
                event.context_digest,
                event.stop_reason,
                event.error,
                event.created_at,
            ),
        )

    def list_events(self, run_id: str, *, after_seq: int = 0) -> list[Event]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE run_id = ? AND seq > ? ORDER BY seq ASC",
                (run_id, after_seq),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def get_event(self, event_id: str) -> Event | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
        return self._from_row(row) if row else None

    def list_run_ids(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT run_id, MAX(seq) AS last_seq FROM events GROUP BY run_id ORDER BY MAX(created_at) DESC"
            ).fetchall()
        return [row["run_id"] for row in rows]

    def iter_all(self) -> Iterator[Event]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM events ORDER BY run_id, seq").fetchall()
        for row in rows:
            yield self._from_row(row)

    def append_project(self, project_id: str, type: str, payload: dict[str, Any] | None = None) -> ProjectEvent:
        """项目流只追加；`seq` 按项目递增，与 run 流的 `seq` 无关。"""
        event = ProjectEvent(event_id=new_id("pevt"), project_id=project_id, seq=0, type=type,
                             payload=dict(payload or {}), created_at=utc_now())
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS seq FROM project_events WHERE project_id = ?", (project_id,)
            ).fetchone()
            event.seq = int(row["seq"]) + 1
            self._conn.execute(
                "INSERT INTO project_events (event_id, project_id, seq, type, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (event.event_id, event.project_id, event.seq, event.type, json_dumps(event.payload), event.created_at),
            )
        return event

    def list_project_events(self, project_id: str, *, after_seq: int = 0) -> list[ProjectEvent]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM project_events WHERE project_id = ? AND seq > ? ORDER BY seq ASC",
                (project_id, after_seq),
            ).fetchall()
        return [self._project_from_row(row) for row in rows]

    def get_project_event(self, event_id: str) -> ProjectEvent | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM project_events WHERE event_id = ?", (event_id,)).fetchone()
        return self._project_from_row(row) if row else None

    def list_project_ids(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT project_id FROM project_events GROUP BY project_id ORDER BY MAX(created_at) DESC"
            ).fetchall()
        return [row["project_id"] for row in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _project_from_row(row: sqlite3.Row) -> ProjectEvent:
        return ProjectEvent(
            event_id=row["event_id"],
            project_id=row["project_id"],
            seq=row["seq"],
            type=row["type"],
            payload=json.loads(row["payload_json"]),
            created_at=row["created_at"],
        )

    def _next_seq(self, run_id: str) -> int:
        row = self._conn.execute("SELECT COALESCE(MAX(seq), 0) AS seq FROM events WHERE run_id = ?", (run_id,)).fetchone()
        return int(row["seq"]) + 1

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Event:
        return Event(
            event_id=row["event_id"],
            run_id=row["run_id"],
            seq=row["seq"],
            type=row["type"],
            role=row["role"],
            parent_event_id=row["parent_event_id"],
            state_before=row["state_before"],
            state_after=row["state_after"],
            payload=json.loads(row["payload_json"]),
            artifact_hashes=json.loads(row["artifact_hashes_json"]),
            session_id=row["session_id"],
            provider=row["provider"],
            model=row["model"],
            context_digest=row["context_digest"],
            stop_reason=row["stop_reason"],
            error=row["error"],
            created_at=row["created_at"],
        )
