# 事件日志：系统唯一的事实来源。run 事件与项目事件在同一份日志中：每条事件有全局位置（跨项目递增）、
# 所属的流（run:<run_id>、project:<project_id>）与流内版本（同一个流内唯一）；另存项目、事项、run、部门与种类，
# 建立索引供范围读取。日志只追加。
# 每个流保存一份投影（投影的内容由写入口计算，这里按 JSON 文本存放）。提交在一个数据库事务中核对流版本、
# 执行权编号与命令身份，追加事件并保存投影；提交以后在进程内通知订阅方。
# 连接取自连接池：读取各用自己的连接，不等待写入；写入由 SQLite 的写入事务互斥，不依赖线程身份。

from __future__ import annotations

import json
import queue
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Event, ProjectEvent, json_dumps, utc_now


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
    epoch INTEGER,
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
    epoch INTEGER,
    state TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS commands (
    command_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    digest TEXT NOT NULL,
    stream TEXT NOT NULL,
    position INTEGER NOT NULL,
    created_at TEXT NOT NULL
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


class StaleExecutionRight(Exception):
    # 写入携带的执行权编号小于这个流已经记录的编号：写入方已经不再持有执行权，写入被拒绝
    def __init__(self, stream: str, epoch: int, recorded: int) -> None:
        super().__init__(f"execution right {epoch} on {stream} is older than the recorded execution right {recorded}")
        self.stream = stream
        self.epoch = epoch
        self.recorded = recorded


@dataclass(frozen=True)
class Command:
    # 命令身份：客户端生成的身份、命令名称与请求内容的摘要（应用层的命令查重使用）
    command_id: str
    name: str
    digest: str


@dataclass(frozen=True)
class CommandRecord:
    # 登记过的命令：身份、名称、内容摘要、所写的流与这次提交最后一条事件的全局位置
    command_id: str
    name: str
    digest: str
    stream: str
    position: int


class DuplicateCommand(Exception):
    # 同一命令身份、同一内容再次提交：原来的提交已经接受，这次不再执行
    def __init__(self, record: CommandRecord) -> None:
        super().__init__(f"command {record.command_id} was already accepted at position {record.position}")
        self.record = record


class CommandIdReused(Exception):
    # 同一命令身份提交了不同的内容，拒绝
    def __init__(self, record: CommandRecord) -> None:
        super().__init__(f"command id {record.command_id} was already used for different content")
        self.record = record


@dataclass(frozen=True)
class SavedProjection:
    # 一个流保存的投影：投影所反映的流版本、最后一条事件的全局位置、记录过的最大执行权编号与投影的 JSON 文本
    version: int
    position: int
    epoch: int | None
    state: str


class EventStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._idle: queue.SimpleQueue[sqlite3.Connection] = queue.SimpleQueue()
        self._opened: list[sqlite3.Connection] = []
        self._listeners: list[Callable[[list[Event | ProjectEvent]], None]] = []
        self._closed = False
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA)

    def commit(self, stream: str, expected_version: int, events: Sequence[Event | ProjectEvent], state: str, *,
               epoch: int | None = None, command: Command | None = None) -> None:
        # 在一个事务中：核对流的当前版本等于 expected_version，核对执行权编号不小于这个流已经记录的编号，
        # 核对命令身份没有登记过；然后按顺序追加事件（全局位置在这里确定，写回事件）、保存这个流的投影、登记命令。
        # 任何一项核对不通过都拒绝，什么也不写。提交以后通知订阅方
        with self._transaction() as connection:
            saved = connection.execute(
                "SELECT version, position, epoch FROM projections WHERE stream = ?", (stream,)
            ).fetchone()
            current = 0 if saved is None else saved["version"]
            if current != expected_version:
                raise StreamVersionConflict(stream, expected_version, current)
            recorded = None if saved is None else saved["epoch"]
            if epoch is not None and recorded is not None and epoch < recorded:
                raise StaleExecutionRight(stream, epoch, recorded)
            if command is not None:
                _check_command(_command_record(connection, command.command_id), command)
            for event in events:
                event.epoch = epoch
                event.position = _insert(connection, event)
            if events:
                connection.execute(
                    "INSERT INTO projections (stream, version, position, epoch, state) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(stream) DO UPDATE SET version = excluded.version, position = excluded.position, "
                    "epoch = excluded.epoch, state = excluded.state",
                    (stream, expected_version + len(events), events[-1].position,
                     max((value for value in (epoch, recorded) if value is not None), default=None), state),
                )
            if command is not None:
                position = events[-1].position if events else _end_position(connection)
                connection.execute(
                    "INSERT INTO commands (command_id, name, digest, stream, position, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (command.command_id, command.name, command.digest, stream, position, utc_now()),
                )
        if events:
            committed = list(events)
            for listener in list(self._listeners):
                listener(committed)

    def replace_projection(self, stream: str, version: int, state: str) -> None:
        # 用重放得到的投影替换这个流保存的投影；version 是重放到的流版本，流在重放以后又有写入时拒绝
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(stream_version), 0) AS version, COALESCE(MAX(position), 0) AS position, "
                "MAX(epoch) AS epoch FROM events WHERE stream = ?", (stream,),
            ).fetchone()
            if row["version"] != version:
                raise StreamVersionConflict(stream, version, row["version"])
            connection.execute(
                "INSERT INTO projections (stream, version, position, epoch, state) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(stream) DO UPDATE SET version = excluded.version, position = excluded.position, "
                "epoch = excluded.epoch, state = excluded.state",
                (stream, version, row["position"], row["epoch"], state),
            )

    def subscribe(self, listener: Callable[[list[Event | ProjectEvent]], None]) -> Callable[[], None]:
        # 登记订阅方：每次提交以后在提交的线程中收到这次提交的事件（已有全局位置），此时不持有任何锁；
        # 订阅方应当很快返回。返回取消订阅的函数
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def check_command(self, command: Command) -> None:
        # 命令身份已经登记时拒绝：内容相同为 DuplicateCommand，不同为 CommandIdReused，异常带着原来的登记
        with self._connection() as connection:
            _check_command(_command_record(connection, command.command_id), command)

    def projection(self, stream: str) -> SavedProjection | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT version, position, epoch, state FROM projections WHERE stream = ?", (stream,)
            ).fetchone()
        return None if row is None else SavedProjection(row["version"], row["position"], row["epoch"], row["state"])

    def streams_without_projection(self) -> list[str]:
        # 有事件但没有保存投影的流
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT DISTINCT stream FROM events WHERE stream NOT IN (SELECT stream FROM projections)"
            ).fetchall()
        return [row["stream"] for row in rows]

    def stream_events(self, stream: str, *, after_version: int = 0,
                      through_version: int | None = None) -> list[Event] | list[ProjectEvent]:
        # 一个流中流内版本大于 after_version（且不大于 through_version）的事件，按版本排列
        sql = "SELECT * FROM events WHERE stream = ? AND stream_version > ?"
        params: list[Any] = [stream, after_version]
        if through_version is not None:
            sql += " AND stream_version <= ?"
            params.append(through_version)
        with self._connection() as connection:
            rows = connection.execute(sql + " ORDER BY stream_version ASC", params).fetchall()
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
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM events WHERE {' AND '.join(clauses)} ORDER BY position ASC LIMIT ?", params,
            ).fetchall()
        return [_from_row(row) for row in rows]

    def end_position(self) -> int:
        # 日志末尾的全局位置；日志为空时是 0
        with self._connection() as connection:
            return _end_position(connection)

    def get_event(self, event_id: str) -> Event | None:
        event = self._get(event_id)
        return event if isinstance(event, Event) else None

    def get_project_event(self, event_id: str) -> ProjectEvent | None:
        event = self._get(event_id)
        return event if isinstance(event, ProjectEvent) else None

    def list_run_ids(self) -> list[str]:
        # 有事件的 run，最近写入的在前
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT run_id FROM events WHERE stream LIKE 'run:%' GROUP BY run_id ORDER BY MAX(position) DESC"
            ).fetchall()
        return [row["run_id"] for row in rows]

    def list_project_ids(self) -> list[str]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT project_id FROM events WHERE stream LIKE 'project:%' GROUP BY project_id "
                "ORDER BY MAX(position) DESC"
            ).fetchall()
        return [row["project_id"] for row in rows]

    def close(self) -> None:
        self._closed = True
        for connection in self._opened:
            connection.close()

    def _get(self, event_id: str) -> Event | ProjectEvent | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
        return None if row is None else _from_row(row)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        # 从连接池取一个连接，用完放回；没有空闲的连接时新开一个。连接不属于任何线程
        if self._closed:
            raise sqlite3.ProgrammingError("the event store is closed")
        try:
            connection = self._idle.get_nowait()
        except queue.Empty:
            connection = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=30)
            connection.row_factory = sqlite3.Row
            self._opened.append(connection)
        try:
            yield connection
        finally:
            self._idle.put(connection)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        # 写入事务：开始时取得数据库的写入锁，其他写入在 SQLite 中等待这个短事务结束
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            connection.execute("COMMIT")


def _check_command(record: CommandRecord | None, command: Command) -> None:
    if record is None:
        return
    if (record.name, record.digest) == (command.name, command.digest):
        raise DuplicateCommand(record)
    raise CommandIdReused(record)


def _command_record(connection: sqlite3.Connection, command_id: str) -> CommandRecord | None:
    row = connection.execute(
        "SELECT command_id, name, digest, stream, position FROM commands WHERE command_id = ?", (command_id,)
    ).fetchone()
    return None if row is None else CommandRecord(row["command_id"], row["name"], row["digest"], row["stream"],
                                                  row["position"])


def _end_position(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COALESCE(MAX(position), 0) AS position FROM events").fetchone()
    return int(row["position"])


def _insert(connection: sqlite3.Connection, event: Event | ProjectEvent) -> int:
    if isinstance(event, Event):
        run_columns = (event.role, event.parent_event_id, event.state_before, event.state_after,
                       json_dumps(event.artifact_hashes), event.session_id, event.provider, event.model,
                       event.context_digest, event.stop_reason, event.error)
    else:
        run_columns = (None, None, None, None, json_dumps([]), None, None, None, None, None, None)
    cursor = connection.execute(
        """
        INSERT INTO events (
            event_id, stream, stream_version, project_id, work_item_id, run_id, department, type, epoch,
            role, parent_event_id, state_before, state_after, artifact_hashes_json,
            session_id, provider, model, context_digest, stop_reason, error, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (event.event_id, event.stream, event.stream_version, event.project_id, event.work_item_id,
         event.run_id, event.department, event.type, event.epoch, *run_columns, json_dumps(event.payload),
         event.created_at),
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
            epoch=row["epoch"],
        )
    return ProjectEvent(
        event_id=row["event_id"], project_id=row["project_id"], type=row["type"],
        payload=json.loads(row["payload_json"]), created_at=row["created_at"], position=row["position"],
        stream=row["stream"], stream_version=row["stream_version"], work_item_id=row["work_item_id"],
        run_id=row["run_id"], department=row["department"], epoch=row["epoch"],
    )
