# 事件日志的读取与订阅：投影、接口与只读子命令按流版本、全局位置、项目、事项与状态读取事件与决定请求，
# 进程内订阅提交以后的事件。追加规则与保存投影的事务在内核模块 harness/event_log.py（工单 #1452）：
# 这里只加读取，写入的核对一条不改；内核不反过来导入这里。

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from .event_log import (
    CatalogEvent, Command, CommandIdReused, CommandRecord, DuplicateCommand, Event, EventLog, ProjectEvent,
    SavedDecision, SavedProjection, StaleExecutionRight, StreamVersionConflict, catalog_stream, command_record,
    decision_from_row, dump_decision, end_position_of, from_row, is_catalog_stream, is_run_stream, load_decision,
    load_decisions, project_stream, run_stream,
)

# 这些名字从内核的 event_log 转出：应用与测试一直从 harness.event_store 导入它们，导入处不改（工单 #1452）
__all__ = [
    "CatalogEvent", "Command", "CommandIdReused", "CommandRecord", "DuplicateCommand", "Event", "EventLog",
    "EventStore", "ProjectEvent", "SavedDecision", "SavedProjection", "StaleExecutionRight",
    "StreamVersionConflict", "catalog_stream", "dump_decision", "is_catalog_stream", "is_run_stream",
    "load_decision", "load_decisions", "project_stream", "run_stream",
]


class EventStore(EventLog):
    def subscribe(self, listener: Callable[[list[Event | ProjectEvent]], None]) -> Callable[[], None]:
        # 登记订阅方：每次提交以后在提交的线程中收到这次提交的事件（已有全局位置），此时不持有任何锁；
        # 订阅方应当很快返回。返回取消订阅的函数
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def command(self, command_id: str) -> CommandRecord | None:
        # 登记过的命令；没有登记时为空
        with self._connection() as connection:
            return command_record(connection, command_id)

    def command_events(self, command_id: str) -> list[Event | ProjectEvent]:
        # 一次命令追加的事件，按位置排列
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE command_id = ? ORDER BY position ASC", (command_id,)
            ).fetchall()
        return [from_row(row) for row in rows]

    def decision(self, decision_id: str) -> SavedDecision | None:
        # 按身份读取一个决定请求保存的投影；没有时为空
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM decisions WHERE decision_id = ?", (decision_id,)).fetchone()
        return None if row is None else decision_from_row(row)

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
            position = end_position_of(connection)
            rows = connection.execute(
                f"SELECT d.* FROM decisions d JOIN events e ON e.event_id = d.decision_id {where} "
                "ORDER BY e.position ASC", params,
            ).fetchall()
        return position, [decision_from_row(row) for row in rows]

    def list_events(self, run_id: str, *, after_version: int = 0,
                    through_position: int | None = None) -> list[Event]:
        return self.stream_events(run_stream(run_id), after_version=after_version,
                                  through_position=through_position)

    def list_project_events(self, project_id: str, *, after_version: int = 0,
                            through_position: int | None = None) -> list[ProjectEvent]:
        return self.stream_events(project_stream(project_id), after_version=after_version,
                                  through_position=through_position)

    def read(self, after: int = 0, *, through: int | None = None, limit: int = 1000,
             projects: Sequence[str] = (), work_items: Sequence[str] = (), runs: Sequence[str] = (),
             departments: Sequence[str] = (), types: Sequence[str] = ()) -> list[Event | ProjectEvent]:
        # 按全局位置分批读取：位置大于 after（且不大于 through）的事件，按位置排列，至多 limit 条。
        # 各个范围之间取交集，同一个范围的多个值取并集；省略的范围不限制
        if limit < 1:
            raise ValueError("limit must be positive")
        clauses: list[str] = ["position > ?"]
        params: list[Any] = [after]
        if through is not None:
            clauses.append("position <= ?")
            params.append(through)
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
        return [from_row(row) for row in rows]

    def end_position(self) -> int:
        # 日志末尾的全局位置；日志为空时是 0
        with self._connection() as connection:
            return end_position_of(connection)

    def events_at(self, positions: Sequence[int]) -> dict[int, Event | ProjectEvent | CatalogEvent]:
        # 按全局位置取事件（工单 #1342）：位置 → 那一条事件；这个位置上没有事件时不出现在结果里。
        # 位置是全库自增的，一个位置最多一条事件；请求里重复的位置只查一次
        wanted = sorted({int(position) for position in positions})
        if not wanted:
            return {}
        found: dict[int, Event | ProjectEvent | CatalogEvent] = {}
        with self._connection() as connection:
            for start in range(0, len(wanted), 500):
                batch = wanted[start:start + 500]
                rows = connection.execute(
                    f"SELECT * FROM events WHERE position IN ({', '.join('?' * len(batch))})", batch,
                ).fetchall()
                found.update({int(row["position"]): from_row(row) for row in rows})
        return found

    def stream_position_range(self, stream: str) -> tuple[int, int] | None:
        # 这个流里事件的最早与最末全局位置（工单 #1342）：按位置取事件时用来分辨
        # 「位置早于这个流的第一条（更早的事件已经归档搬走）」与「范围内缺这一条（已经压缩掉）」
        with self._connection() as connection:
            row = connection.execute(
                "SELECT MIN(position) AS first, MAX(position) AS last FROM events WHERE stream = ?", (stream,),
            ).fetchone()
        return None if row is None or row["first"] is None else (int(row["first"]), int(row["last"]))

    def run_time_bounds(self, run_id: str, *, through: int | None = None) -> tuple[str, str] | None:
        # 一个 run 的第一条与最后一条事件的创建时间；没有事件时为空。按 run 与位置的索引读取。
        # through 给出全局位置的上界时只看到该位置以前的最后一条（按位置读取，工单 #127）
        sql_tail = " AND position <= ?" if through is not None else ""
        params: list[Any] = [run_id] if through is None else [run_id, through]
        with self._connection() as connection:
            first = connection.execute(
                f"SELECT created_at FROM events WHERE run_id = ?{sql_tail} ORDER BY position ASC LIMIT 1", params,
            ).fetchone()
            if first is None:
                return None
            last = connection.execute(
                f"SELECT created_at FROM events WHERE run_id = ?{sql_tail} ORDER BY position DESC LIMIT 1", params,
            ).fetchone()
        return first["created_at"], last["created_at"]

    def created_at_at(self, position: int) -> str | None:
        # 位置不大于 position 的最后一条事件的创建时间：按位置读取时用它作为「该位置的时间」（工单 #127）
        if position <= 0:
            return None
        with self._connection() as connection:
            row = connection.execute(
                "SELECT created_at FROM events WHERE position <= ? ORDER BY position DESC LIMIT 1", (position,),
            ).fetchone()
        return None if row is None else row["created_at"]

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

    def list_project_ids(self, *, through: int | None = None) -> list[str]:
        # 有事件的项目，最近写入的在前；through 给出全局位置的上界时只看该位置以前登记的项目（工单 #127）
        sql = "SELECT project_id FROM events WHERE stream LIKE 'project:%'"
        params: list[Any] = []
        if through is not None:
            sql += " AND position <= ?"
            params.append(through)
        sql += " GROUP BY project_id ORDER BY MAX(position) DESC"
        with self._connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [row["project_id"] for row in rows]

    def _get(self, event_id: str) -> Event | ProjectEvent | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
        return None if row is None else from_row(row)
