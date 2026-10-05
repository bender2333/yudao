# 应用层保存的读取模型（设计说明第 4.2 节）：调用尝试表（请求记录、用量、请求详情的索引）与流转记录。
# 两者按事件订阅逐步更新，各自记录已处理到的位置；删除以后从事件重放重建，重放不调用模型与工具。
# 写入只发生在这个 SQLite 文件里，不写事件日志与保存的投影；查询在一个读取事务中读取所需的表。

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from ..artifacts import ArtifactStore
from ..event_store import EventStore
from ..models import Event, EventType, ProjectEvent, json_dumps
from ..observability import AttemptFold, search_text
from ..projects import REWORK_VERDICTS

ATTEMPTS = "attempts"
FLOWS = "flows"
BATCH = 500
# 查询按公开状态筛选：合同的字段类型取这里，接口层据此校验请求
AttemptStatus = Literal[("success", "failed", "cancelled", "running")]
# 调用尝试表吸收的事件种类：只有它们会改变一条尝试记录
ATTEMPT_TYPES = frozenset({
    EventType.DEPARTMENT_ACTIVATED, EventType.CONTEXT_ASSEMBLED, EventType.MODEL_REQUESTED,
    EventType.MODEL_REQUEST_SERIALIZED, EventType.MODEL_MESSAGE, EventType.MODEL_ATTEMPT_FINISHED,
    EventType.MODEL_ATTEMPT_FAILED, EventType.MODEL_RETRY_SCHEDULED, EventType.MODEL_STREAM_PROGRESS,
})
# 流转记录吸收的事件种类：阶段迁移、部门之间的请求与回答、质检退回
FLOW_TYPES = frozenset({
    EventType.TRANSITION, EventType.COLLABORATION_REQUESTED, EventType.COLLABORATION_RESPONDED,
    EventType.COLLABORATION_CLOSED, EventType.QA_SUBMITTED,
})
DELIVERY_PHASE = "DELIVERY"
# 质检退回的判定到承接部门的对应；与项目流使用的退回判定必须是同一个集合，启动时核对
_REWORK_DEPARTMENTS = {"rework_product": "product", "rework_engineering": "engineering"}
if set(_REWORK_DEPARTMENTS) != set(REWORK_VERDICTS):
    raise ValueError("the flow read model and the project stream disagree on the rework verdicts")

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_read_positions (
    model TEXT PRIMARY KEY,
    position INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS app_attempt_state (
    run_id TEXT PRIMARY KEY,
    state TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_attempts (
    attempt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    project_id TEXT,
    work_item_id TEXT,
    department TEXT,
    status TEXT,
    purpose TEXT,
    logical_call_id TEXT,
    requested_provider TEXT,
    requested_model TEXT,
    actual_provider TEXT,
    actual_model TEXT,
    seq INTEGER NOT NULL,
    position INTEGER NOT NULL,
    search_text TEXT NOT NULL,
    record TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_app_attempts_project ON app_attempts(project_id, position, attempt_id);
CREATE INDEX IF NOT EXISTS idx_app_attempts_run ON app_attempts(run_id, position, attempt_id);
CREATE TABLE IF NOT EXISTS app_flows (
    flow_id TEXT PRIMARY KEY,
    project_id TEXT,
    work_item_id TEXT,
    run_id TEXT,
    position INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL,
    direction_from TEXT,
    direction_to TEXT,
    status TEXT NOT NULL,
    content TEXT NOT NULL,
    event_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_app_flows_scope ON app_flows(project_id, work_item_id, position);
"""

# 阶段迁移到流转类型的对应：进入工程工作包是需求交接，进入交付是版本交付，退回是返工
_TRANSITION_KINDS = {
    "ENGINEERING": "需求交接",
    DELIVERY_PHASE: "版本交付",
    "REWORK_PRODUCT": "返工",
    "REWORK_ENGINEERING": "返工",
}
_TRANSITION_DEPARTMENTS = {
    "PRODUCT_SPEC": "product", "REWORK_PRODUCT": "product",
    "ENGINEERING": "engineering", "REWORK_ENGINEERING": "engineering",
    "QUALITY": "quality", DELIVERY_PHASE: "quality",
}
_CONSULTATION_STATUS = {
    "answered": "已回应", "declined": "已拒绝", "needs_work": "需要返工", "completed": "已完成",
}
_CLOSED_STATUS = {
    "superseded": "已取代", "stopped": "已停止", "cancelled": "已取消", "timed_out": "已超时",
}


class ReadModels:
    """调用尝试表与流转记录：按订阅逐步更新，可以从事件重放重建。"""

    def __init__(self, store: EventStore, artifacts: ArtifactStore, path: str | Path | None) -> None:
        # path 为空时在内存中建立：只读的打开用这种方式，从事件重放重建，不写数据目录
        self.store = store
        self.artifacts = artifacts
        self.path = None if path is None else Path(path)
        source = ":memory:" if self.path is None else str(self.path)
        self._connection = sqlite3.connect(source, check_same_thread=False, isolation_level=None, timeout=30)
        self._connection.row_factory = sqlite3.Row
        if self.path is not None:
            self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.executescript(SCHEMA)
        self._dirty = True
        self._unsubscribe = store.subscribe(lambda _events: self._mark_dirty())

    def close(self) -> None:
        self._unsubscribe()
        self._connection.close()

    def _mark_dirty(self) -> None:
        # 订阅方由事件日志在提交以后调用；这里只置位，查询时再吸收，不把读取模型的错误带给写入方
        self._dirty = True

    def rebuild(self) -> None:
        # 删除调用尝试表与流转记录以后从事件重放重建；不调用模型与工具
        with self._transaction() as connection:
            for table in ("app_attempt_state", "app_attempts", "app_flows", "app_read_positions"):
                connection.execute(f"DELETE FROM {table}")
        self._dirty = True
        self._catch_up()

    def _read(self, fetch: Callable[[sqlite3.Connection], list[sqlite3.Row]]) -> tuple[int, list[sqlite3.Row]]:
        # 吸收新事件以后在一个读取事务中取得已处理位置与数据：两者来自同一个已提交的状态
        self._catch_up()
        with self._reading() as connection:
            return _read_position(connection), fetch(connection)

    def _catch_up(self) -> None:
        if not self._dirty:
            return
        with self._reading() as connection:
            rows = connection.execute("SELECT model, position FROM app_read_positions").fetchall()
        positions = {row["model"]: int(row["position"]) for row in rows}
        cursor = min(positions.get(model, 0) for model in (ATTEMPTS, FLOWS))
        while True:
            events = self.store.read(after=cursor, limit=BATCH)
            if not events:
                break
            self._absorb(events, positions)
            cursor = events[-1].position
            positions = {ATTEMPTS: cursor, FLOWS: cursor}
        self._dirty = False

    def attempts(self, *, project_id: str | None = None, run_id: str | None = None,
                 work_item_id: str | None = None, department: str | None = None,
                 status: AttemptStatus | None = None, provider: str | None = None,
                 requested_model: str | None = None, actual_model: str | None = None,
                 q: str | None = None) -> tuple[int, list[sqlite3.Row]]:
        clauses, params = _attempt_clauses(project_id=project_id, run_id=run_id, work_item_id=work_item_id,
                                          department=department, status=status, provider=provider,
                                          requested_model=requested_model, actual_model=actual_model, q=q)
        where = _where(clauses)
        return self._read(lambda connection: connection.execute(
            f"SELECT * FROM app_attempts{where} ORDER BY position ASC, attempt_id ASC", params,
        ).fetchall())

    def attempts_page(self, *, through: int | None, after: int, after_id: str, limit: int,
                      project_id: str | None = None, work_item_id: str | None = None,
                      department: str | None = None, status: AttemptStatus | None = None,
                      provider: str | None = None, requested_model: str | None = None,
                      actual_model: str | None = None, q: str | None = None) -> tuple[int, list[sqlite3.Row]]:
        # 带位置的游标分页：只返回第一页位置以前的记录，翻页期间新出现的记录由事件流带来
        clauses, params = _attempt_clauses(project_id=project_id, run_id=None, work_item_id=work_item_id,
                                          department=department, status=status, provider=provider,
                                          requested_model=requested_model, actual_model=actual_model, q=q)

        def fetch(connection: sqlite3.Connection) -> list[sqlite3.Row]:
            first = _read_position(connection) if through is None else through
            page_clauses = [*clauses, "position <= ?", "(position > ? OR (position = ? AND attempt_id > ?))"]
            return connection.execute(
                f"SELECT * FROM app_attempts{_where(page_clauses)} ORDER BY position ASC, attempt_id ASC LIMIT ?",
                [*params, first, after, after, after_id, limit],
            ).fetchall()

        return self._read(fetch)

    def flows(self, *, project_id: str, work_item_id: str | None = None) -> tuple[int, list[sqlite3.Row]]:
        def fetch(connection: sqlite3.Connection) -> list[sqlite3.Row]:
            clauses = ["project_id = ?"]
            params: list[Any] = [project_id]
            if work_item_id is not None:
                clauses.append("work_item_id = ?")
                params.append(work_item_id)
            return connection.execute(
                f"SELECT * FROM app_flows WHERE {' AND '.join(clauses)} ORDER BY position ASC", params,
            ).fetchall()

        return self._read(fetch)

    def _absorb(self, events: Sequence[Event | ProjectEvent], positions: dict[str, int]) -> None:
        attempt_events = [event for event in events
                          if event.position > positions.get(ATTEMPTS, 0) and _is_attempt_event(event)]
        flow_events = [event for event in events
                       if event.position > positions.get(FLOWS, 0) and _is_flow_event(event)]
        cursor = events[-1].position
        with self._transaction() as connection:
            self._absorb_attempts(connection, attempt_events)
            for event in flow_events:
                for row in flow_rows(event):
                    _upsert_flow(connection, row)
            for model in (ATTEMPTS, FLOWS):
                connection.execute(
                    "INSERT INTO app_read_positions (model, position) VALUES (?, ?) "
                    "ON CONFLICT(model) DO UPDATE SET position = excluded.position", (model, cursor),
                )

    def _absorb_attempts(self, connection: sqlite3.Connection, events: Iterable[Event]) -> None:
        by_run: dict[str, list[Event]] = defaultdict(list)
        for event in events:
            by_run[event.run_id].append(event)
        for run_id, run_events in by_run.items():
            saved = connection.execute("SELECT state FROM app_attempt_state WHERE run_id = ?", (run_id,)).fetchone()
            fold = (AttemptFold(self.artifacts, run_id) if saved is None
                    else AttemptFold.load_state(self.artifacts, run_id, saved["state"]))
            for event in run_events:
                fold.merge(event)
            project_id = next((event.project_id for event in run_events if event.project_id), None)
            work_item_id = next((event.work_item_id for event in run_events if event.work_item_id), None)
            records = fold.records()
            for attempt_id, record in records.items():
                position = fold.positions.get(attempt_id, run_events[-1].position)
                _upsert_attempt(connection, run_id, project_id, work_item_id, attempt_id, position, record)
            connection.execute(
                "INSERT INTO app_attempt_state (run_id, state) VALUES (?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET state = excluded.state", (run_id, fold.state()),
            )

    @contextmanager
    def _reading(self) -> Iterator[sqlite3.Connection]:
        # 读取事务：其间的各次读取看到同一个已提交的状态
        self._connection.execute("BEGIN")
        try:
            yield self._connection
        finally:
            self._connection.execute("COMMIT")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield self._connection
            self._connection.execute("COMMIT")
        except BaseException:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise


def _read_position(connection: sqlite3.Connection) -> int:
    # 两个读取模型都已处理到的位置：查询用它作为快照位置、与事件流的位置对齐
    rows = connection.execute("SELECT model, position FROM app_read_positions").fetchall()
    positions = {row["model"]: int(row["position"]) for row in rows}
    return min(positions.get(model, 0) for model in (ATTEMPTS, FLOWS))


def _is_attempt_event(event: Event | ProjectEvent) -> bool:
    return isinstance(event, Event) and event.type in ATTEMPT_TYPES


def _where(clauses: Sequence[str]) -> str:
    return "" if not clauses else f" WHERE {' AND '.join(clauses)}"


def _attempt_clauses(*, project_id: str | None, run_id: str | None, work_item_id: str | None,
                     department: str | None, status: AttemptStatus | None, provider: str | None,
                     requested_model: str | None, actual_model: str | None,
                     q: str | None) -> tuple[list[str], list[Any]]:
    # 调用尝试表的筛选条件（状态按公开状态，实际模型缺失时回退到请求的模型）
    clauses: list[str] = []
    params: list[Any] = []
    for column, value in (("project_id", project_id), ("run_id", run_id), ("work_item_id", work_item_id),
                          ("department", department), ("status", status), ("requested_model", requested_model)):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    if provider is not None:
        clauses.append("(requested_provider = ? OR actual_provider = ?)")
        params.extend([provider, provider])
    if actual_model is not None:
        clauses.append("COALESCE(actual_model, requested_model) = ?")
        params.append(actual_model)
    if q is not None:
        clauses.append("instr(search_text, ?) > 0")
        params.append(q.strip().casefold())
    return clauses, params


def _is_flow_event(event: Event | ProjectEvent) -> bool:
    return isinstance(event, Event) and event.type in FLOW_TYPES


def _upsert_attempt(connection: sqlite3.Connection, run_id: str, project_id: str | None,
                    work_item_id: str | None, attempt_id: str, position: int, record: dict[str, Any]) -> None:
    payload = json_dumps(record)
    existing = connection.execute("SELECT record FROM app_attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
    if existing is not None and existing["record"] == payload:
        return
    connection.execute(
        "INSERT INTO app_attempts (attempt_id, run_id, project_id, work_item_id, department, status, purpose, "
        "logical_call_id, requested_provider, requested_model, actual_provider, actual_model, seq, position, "
        "search_text, record) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(attempt_id) DO UPDATE SET record = excluded.record, status = excluded.status, "
        "department = excluded.department, purpose = excluded.purpose, logical_call_id = excluded.logical_call_id, "
        "requested_provider = excluded.requested_provider, requested_model = excluded.requested_model, "
        "actual_provider = excluded.actual_provider, actual_model = excluded.actual_model, seq = excluded.seq, "
        "project_id = COALESCE(app_attempts.project_id, excluded.project_id), "
        "work_item_id = COALESCE(app_attempts.work_item_id, excluded.work_item_id), "
        "search_text = excluded.search_text",
        (attempt_id, run_id, project_id, work_item_id, record.get("department"), public_status(record),
         record.get("purpose"), record.get("logical_call_id"), record.get("requested_provider"),
         record.get("requested_model"), record.get("actual_provider"), record.get("actual_model"),
         int(record.get("seq") or 0), position, search_text(record), payload),
    )


def public_status(record: dict[str, Any]) -> str:
    status = record.get("status")
    if status == "completed":
        return "success"
    if status in {"prepared", "requesting"}:
        return "running"
    if status == "cancelled":
        return "cancelled"
    return "failed"


def _upsert_flow(connection: sqlite3.Connection, row: dict[str, Any]) -> None:
    connection.execute(
        "INSERT INTO app_flows (flow_id, project_id, work_item_id, run_id, position, seq, kind, direction_from, "
        "direction_to, status, content, event_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(flow_id) DO UPDATE SET status = excluded.status, content = excluded.content, "
        "direction_from = COALESCE(app_flows.direction_from, excluded.direction_from), "
        "direction_to = COALESCE(app_flows.direction_to, excluded.direction_to)",
        (row["flow_id"], row["project_id"], row["work_item_id"], row["run_id"], row["position"], row["seq"],
         row["kind"], row["direction_from"], row["direction_to"], row["status"], row["content"], row["event_id"],
         row["created_at"]),
    )


def flow_rows(event: Event | ProjectEvent) -> list[dict[str, Any]]:
    # 一条事件产生的流转记录：迁移与质检退回产生新记录，部门之间的回答与关闭更新同一条咨询记录
    if not isinstance(event, Event):
        return []
    payload = event.payload or {}
    base = {
        "project_id": event.project_id, "work_item_id": event.work_item_id, "run_id": event.run_id,
        "position": event.position, "seq": event.stream_version, "event_id": event.event_id,
        "created_at": event.created_at,
    }
    if event.type == EventType.TRANSITION:
        kind = _TRANSITION_KINDS.get(event.state_after)
        if kind is None:
            return []
        return [{**base, "flow_id": event.event_id, "kind": kind,
                 "direction_from": _TRANSITION_DEPARTMENTS.get(event.state_before) or event.state_before,
                 "direction_to": _TRANSITION_DEPARTMENTS.get(event.state_after) or event.state_after,
                 "status": "已退回" if kind == "返工" else "已完成",
                 "content": f"{event.state_before}→{event.state_after}"}]
    if event.type == EventType.COLLABORATION_REQUESTED:
        return [{**base, "flow_id": payload["id"], "kind": "咨询",
                 "direction_from": payload["requester"], "direction_to": payload["recipient"],
                 "status": "等待回答", "content": payload["question"]}]
    if event.type == EventType.COLLABORATION_RESPONDED:
        # 回答方回应发问方：两端从载荷取出；旧事件没有这两个字段时方向留空（工单 #275）
        return [{**base, "flow_id": payload["request_id"], "kind": "咨询",
                 "direction_from": payload.get("recipient"), "direction_to": payload.get("requester"),
                 "status": _CONSULTATION_STATUS.get(payload["status"], payload["status"]),
                 "content": payload["text"]}]
    if event.type == EventType.COLLABORATION_CLOSED:
        return [{**base, "flow_id": payload["request_id"], "kind": "咨询", "direction_from": None,
                 "direction_to": None, "status": _CLOSED_STATUS.get(payload["status"], payload["status"]),
                 "content": payload["reason"]}]
    if event.type == EventType.QA_SUBMITTED and payload.get("verdict") in _REWORK_DEPARTMENTS:
        return [{**base, "flow_id": event.event_id, "kind": "问题反馈",
                 "direction_from": "quality", "direction_to": _REWORK_DEPARTMENTS[payload["verdict"]],
                 "status": "已退回", "content": payload.get("rationale", "")}]
    return []
