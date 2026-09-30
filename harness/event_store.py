# 事件日志：系统唯一的事实来源。run 事件、项目事件与目录事件在同一份日志中：每条事件有全局位置（跨项目递增）、
# 所属的流（run:<run_id>、project:<project_id>、catalog:main）与流内版本（同一个流内唯一）；另存项目、事项、run、部门与种类，
# 建立索引供范围读取；另存引起事件的命令身份与事件的提出者。日志只追加，日志身份在建立日志时生成，不再改变。
# 每个流保存一份投影，流中的每个决定请求另存一份投影（按身份查找，按项目、事项、种类与状态列出）；
# 投影的内容由写入口计算，这里按 JSON 文本存放。提交在一个数据库事务中核对流版本、执行权编号与命令身份，
# 追加事件并保存投影；提交以后在进程内通知订阅方。
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

from .models import CatalogEvent, Event, ProjectEvent, json_dumps, new_id, utc_now


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
    command_id TEXT,
    actor TEXT,
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
CREATE INDEX IF NOT EXISTS idx_events_command ON events(command_id, position) WHERE command_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS log (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    log_id TEXT NOT NULL
);
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
CREATE TABLE IF NOT EXISTS decisions (
    decision_id TEXT PRIMARY KEY,
    stream TEXT NOT NULL,
    project_id TEXT,
    work_item_id TEXT,
    run_id TEXT,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    state TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_stream ON decisions(stream);
CREATE INDEX IF NOT EXISTS idx_decisions_scope ON decisions(project_id, work_item_id);
"""

_RUN = "run:"
_PROJECT = "project:"


def run_stream(run_id: str) -> str:
    return _RUN + run_id


def project_stream(project_id: str) -> str:
    return _PROJECT + project_id


_CATALOG = "catalog:"


def catalog_stream() -> str:
    # 模型目录与凭据只有一份，不按项目分开
    return _CATALOG + "main"


def is_catalog_stream(stream: str) -> bool:
    return stream.startswith(_CATALOG)


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
    # 一次命令：客户端生成的身份、命令名称、请求内容的摘要（应用层的命令查重使用）与提出者。
    # 同一身份是否重复只比较名称与摘要；这次提交追加的事件都记下身份与提出者
    command_id: str
    name: str
    digest: str
    actor: str


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
class SavedDecision:
    # 一个决定请求保存的投影：身份（请求事件的编号）、所属的流与对象、种类、状态与投影的 JSON 文本
    decision_id: str
    stream: str
    project_id: str | None
    work_item_id: str | None
    run_id: str | None
    kind: str
    status: str
    state: str


@dataclass(frozen=True)
class SavedProjection:
    # 一个流保存的投影：投影所反映的流版本、最后一条事件的全局位置、记录过的最大执行权编号与投影的 JSON 文本，
    # 以及这个流中的决定请求保存的投影（按请求的先后）
    version: int
    position: int
    epoch: int | None
    state: str
    decisions: tuple[SavedDecision, ...] = ()


class EventStore:
    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        # read_only 用于只读的子命令：不建立目录、不写库结构，连接以只读方式打开；
        # 写入方法在使用时直接拒绝，读取期间不会改动事件日志与保存的投影
        self.path = Path(path)
        self.read_only = read_only
        self._idle: queue.SimpleQueue[sqlite3.Connection] = queue.SimpleQueue()
        self._opened: list[sqlite3.Connection] = []
        self._listeners: list[Callable[[list[Event | ProjectEvent]], None]] = []
        self._closed = False
        if read_only:
            if not self.path.is_file():
                raise FileNotFoundError(f"event log does not exist: {self.path}")
            with self._connection() as connection:
                self.log_id: str = connection.execute("SELECT log_id FROM log").fetchone()["log_id"]
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA)
            connection.execute("INSERT OR IGNORE INTO log (singleton, log_id) VALUES (1, ?)", (new_id("log"),))
            self.log_id: str = connection.execute("SELECT log_id FROM log").fetchone()["log_id"]

    def commit(self, stream: str, expected_version: int, events: Sequence[Event | ProjectEvent], state: str, *,
               epoch: int | None = None, command: Command | None = None,
               decisions: Sequence[SavedDecision] = ()) -> None:
        # 在一个事务中：核对流的当前版本等于 expected_version，核对执行权编号不小于这个流已经记录的编号，
        # 核对命令身份没有登记过；然后按顺序追加事件（全局位置在这里确定，与执行权编号一起写回事件）、
        # 保存这个流的投影与这次改变的决定请求、登记命令。任何一项核对不通过都拒绝，什么也不写。
        # 订阅方由写入口在提交成功以后经 notify 通知
        self._refuse_write()
        if decisions and not events:
            raise ValueError("decision requests change only together with the events that change them")
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
            for decision in decisions:
                _save_decision(connection, stream, decision)
            if command is not None:
                position = events[-1].position if events else _end_position(connection)
                connection.execute(
                    "INSERT INTO commands (command_id, name, digest, stream, position, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (command.command_id, command.name, command.digest, stream, position, utc_now()),
                )

    def notify(self, events: Sequence[Event | ProjectEvent]) -> None:
        # 把一次已经提交的写入交给订阅方；在提交的线程中调用，此时不持有任何锁
        if events:
            committed = list(events)
            for listener in list(self._listeners):
                listener(committed)

    def replace_projection(self, stream: str, version: int, state: str,
                           decisions: Sequence[SavedDecision] = ()) -> None:
        # 用重放得到的投影与决定请求替换这个流保存的投影；version 是重放到的流版本，流在重放以后又有写入时拒绝
        self._refuse_write()
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
            connection.execute("DELETE FROM decisions WHERE stream = ?", (stream,))
            for decision in decisions:
                _save_decision(connection, stream, decision)

    def claim_execution_right(self, stream: str, expected_version: int, events: Sequence[Event],
                              state: str, *, decisions: Sequence[SavedDecision] = ()) -> int:
        # 取得一个 run 的执行权（工单 #16，ADR-0018）：在同一个写入事务中核对流版本等于 expected_version，
        # 以这个流已经记录的执行权编号加一作为新的编号，随这次追加的事件写回，并更新保存的投影与决定请求。
        # 编号跨进程单调：另一个进程已经取得更大的编号时，这里的 expected_version 核对失败，调用方重新判断。
        # 执行权没有期限与续期，编号只用于进程重启与两个进程同时恢复的情况。返回这次取得的执行权编号
        self._refuse_write()
        with self._transaction() as connection:
            saved = connection.execute(
                "SELECT version, epoch FROM projections WHERE stream = ?", (stream,)
            ).fetchone()
            current = 0 if saved is None else saved["version"]
            if current != expected_version:
                raise StreamVersionConflict(stream, expected_version, current)
            recorded = None if saved is None else saved["epoch"]
            epoch = 1 if recorded is None else recorded + 1
            for event in events:
                event.epoch = epoch
                event.position = _insert(connection, event)
            connection.execute(
                "INSERT INTO projections (stream, version, position, epoch, state) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(stream) DO UPDATE SET version = excluded.version, position = excluded.position, "
                "epoch = excluded.epoch, state = excluded.state",
                (stream, expected_version + len(events), events[-1].position, epoch, state),
            )
            for decision in decisions:
                _save_decision(connection, stream, decision)
        return epoch

    def subscribe(self, listener: Callable[[list[Event | ProjectEvent]], None]) -> Callable[[], None]:
        # 登记订阅方：每次提交以后在提交的线程中收到这次提交的事件（已有全局位置），此时不持有任何锁；
        # 订阅方应当很快返回。返回取消订阅的函数
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def check_command(self, command: Command) -> None:
        # 命令身份已经登记时拒绝：内容相同为 DuplicateCommand，不同为 CommandIdReused，异常带着原来的登记
        with self._connection() as connection:
            _check_command(_command_record(connection, command.command_id), command)

    def command(self, command_id: str) -> CommandRecord | None:
        # 登记过的命令；没有登记时为空
        with self._connection() as connection:
            return _command_record(connection, command_id)

    def command_events(self, command_id: str) -> list[Event | ProjectEvent]:
        # 一次命令追加的事件，按位置排列
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE command_id = ? ORDER BY position ASC", (command_id,)
            ).fetchall()
        return [_from_row(row) for row in rows]

    def projection(self, stream: str) -> SavedProjection | None:
        # 流保存的投影与它的决定请求，在同一个读取事务中读取
        with self._reading() as connection:
            row = connection.execute(
                "SELECT version, position, epoch, state FROM projections WHERE stream = ?", (stream,)
            ).fetchone()
            decisions = connection.execute(
                "SELECT d.* FROM decisions d JOIN events e ON e.event_id = d.decision_id WHERE d.stream = ? "
                "ORDER BY e.position ASC", (stream,),
            ).fetchall()
        if row is None:
            return None
        return SavedProjection(row["version"], row["position"], row["epoch"], row["state"],
                               tuple(_decision_from_row(item) for item in decisions))

    def decision(self, decision_id: str) -> SavedDecision | None:
        # 按身份读取一个决定请求保存的投影；没有时为空
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM decisions WHERE decision_id = ?", (decision_id,)).fetchone()
        return None if row is None else _decision_from_row(row)

    def decisions(self, *, projects: Sequence[str] = (), work_items: Sequence[str] = (), kinds: Sequence[str] = (),
                  statuses: Sequence[str] = ()) -> tuple[int, list[SavedDecision]]:
        # 按项目、事项、种类与状态列出决定请求保存的投影（按请求的先后），与日志末尾的全局位置在同一个读取事务中读取。
        # 各个条件之间取交集，同一个条件的多个值取并集；省略的条件不限制
        clauses: list[str] = []
        params: list[Any] = []
        for column, values in (("project_id", projects), ("work_item_id", work_items), ("kind", kinds),
                               ("status", statuses)):
            if values:
                clauses.append(f"d.{column} IN ({', '.join('?' * len(values))})")
                params.extend(values)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._reading() as connection:
            position = _end_position(connection)
            rows = connection.execute(
                f"SELECT d.* FROM decisions d JOIN events e ON e.event_id = d.decision_id {where} "
                "ORDER BY e.position ASC", params,
            ).fetchall()
        return position, [_decision_from_row(row) for row in rows]

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

    def run_time_bounds(self, run_id: str) -> tuple[str, str] | None:
        # 一个 run 的第一条与最后一条事件的创建时间；没有事件时为空。按 run 与位置的索引读取
        with self._connection() as connection:
            first = connection.execute(
                "SELECT created_at FROM events WHERE run_id = ? ORDER BY position ASC LIMIT 1", (run_id,),
            ).fetchone()
            if first is None:
                return None
            last = connection.execute(
                "SELECT created_at FROM events WHERE run_id = ? ORDER BY position DESC LIMIT 1", (run_id,),
            ).fetchone()
        return first["created_at"], last["created_at"]

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

    def _refuse_write(self) -> None:
        # 只读打开的事件日志不接受任何写入
        if self.read_only:
            raise RuntimeError("the event store is open read-only")

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        # 从连接池取一个连接，用完放回；没有空闲的连接时新开一个。连接不属于任何线程
        if self._closed:
            raise sqlite3.ProgrammingError("the event store is closed")
        try:
            connection = self._idle.get_nowait()
        except queue.Empty:
            source = f"file:{self.path.as_posix()}?mode=ro" if self.read_only else str(self.path)
            connection = sqlite3.connect(source, uri=self.read_only, check_same_thread=False, isolation_level=None,
                                         timeout=30)
            connection.row_factory = sqlite3.Row
            self._opened.append(connection)
        try:
            yield connection
        finally:
            self._idle.put(connection)

    @contextmanager
    def _reading(self) -> Iterator[sqlite3.Connection]:
        # 读取事务：其间的各次读取看到同一个已提交的状态，不等待写入
        with self._connection() as connection:
            connection.execute("BEGIN")
            try:
                yield connection
            finally:
                connection.execute("COMMIT")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        # 写入事务：开始时取得数据库的写入锁，其他写入在 SQLite 中等待这个短事务结束。
        # 提交或其间的任何一步出错都回滚，连接放回连接池时不带着未结束的事务
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise


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


def _save_decision(connection: sqlite3.Connection, stream: str, decision: SavedDecision) -> None:
    if decision.stream != stream:
        raise ValueError(f"decision request {decision.decision_id} belongs to {decision.stream}, not {stream}")
    connection.execute(
        "INSERT INTO decisions (decision_id, stream, project_id, work_item_id, run_id, kind, status, state) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(decision_id) DO UPDATE SET status = excluded.status, "
        "state = excluded.state",
        (decision.decision_id, decision.stream, decision.project_id, decision.work_item_id, decision.run_id,
         decision.kind, decision.status, decision.state),
    )


def _decision_from_row(row: sqlite3.Row) -> SavedDecision:
    return SavedDecision(row["decision_id"], row["stream"], row["project_id"], row["work_item_id"], row["run_id"],
                         row["kind"], row["status"], row["state"])


def _end_position(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COALESCE(MAX(position), 0) AS position FROM events").fetchone()
    return int(row["position"])


def _insert(connection: sqlite3.Connection, event: Event | ProjectEvent | CatalogEvent) -> int:
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
            command_id, actor, role, parent_event_id, state_before, state_after, artifact_hashes_json,
            session_id, provider, model, context_digest, stop_reason, error, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (event.event_id, event.stream, event.stream_version, event.project_id, event.work_item_id,
         event.run_id, event.department, event.type, event.epoch, event.command_id, event.actor, *run_columns,
         json_dumps(event.payload), event.created_at),
    )
    return int(cursor.lastrowid)


def _from_row(row: sqlite3.Row) -> Event | ProjectEvent | CatalogEvent:
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
            epoch=row["epoch"], command_id=row["command_id"], actor=row["actor"],
        )
    if row["stream"].startswith(_CATALOG):
        return CatalogEvent(
            event_id=row["event_id"], type=row["type"], payload=json.loads(row["payload_json"]),
            created_at=row["created_at"], position=row["position"], stream=row["stream"],
            stream_version=row["stream_version"], project_id=row["project_id"], work_item_id=row["work_item_id"],
            run_id=row["run_id"], department=row["department"], epoch=row["epoch"], command_id=row["command_id"],
            actor=row["actor"],
        )
    return ProjectEvent(
        event_id=row["event_id"], project_id=row["project_id"], type=row["type"],
        payload=json.loads(row["payload_json"]), created_at=row["created_at"], position=row["position"],
        stream=row["stream"], stream_version=row["stream_version"], work_item_id=row["work_item_id"],
        run_id=row["run_id"], department=row["department"], epoch=row["epoch"], command_id=row["command_id"],
        actor=row["actor"],
    )
