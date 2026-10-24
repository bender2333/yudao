# 系统首页的查询与命令（设计说明第 4.3 节「系统首页」，工单 #127）：
# home.away_report 返回上次查看的位置与时间、所选范围内的汇总与关键事实列表，供画面回放与时间轴使用；
# home.mark_seen 把上次查看的位置更新为用户看到的全局位置，保存在控制主机上，只有一个。
# 汇总与关键事实都由事件得到，没有来源事件的项不返回，不写成零。

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from pydantic import AwareDatetime, Field

from ..event_store import Command
from ..models import CatalogEventType, Event, EventType, ProjectEvent, ProjectEventType, utc_now
from .commands import Rejection
from .contracts import CommandRequest, Contract, NoRefs, Snapshot
from .labels import event_label
from .registry import CommandDefinition, QueryDefinition, UnchangedEvent

if TYPE_CHECKING:
    from .application import Application

# 报告范围（设计说明第 4.3 节）：自上次查看、最近 24 小时、最近 7 天
RANGES: dict[str, str] = {"since_seen": "自上次查看", "24h": "最近 24 小时", "7d": "最近 7 天"}
RANGE_SECONDS = {"24h": 24 * 3600, "7d": 7 * 24 * 3600}

# 范围内的关键事实种类（设计说明第 4.3 节）：询问与回答、返工、放行、采纳、决定请求的发出与回答。
# 故障、修复、部署与回滚、进入与离开等待属于 Stage 4，所属工作包完成之前没有数据
FACT_TYPES: frozenset[str] = frozenset({
    EventType.ASK_STARTED, EventType.ASK_ANSWERED,
    EventType.QA_SUBMITTED, EventType.RUN_DONE, EventType.RUN_PAUSED,
    EventType.RUN_FAILED, EventType.DECISION_REQUESTED, EventType.DECISION_ANSWERED,
    ProjectEventType.DELIVERABLE_ADOPTED, ProjectEventType.WORK_ITEM_CREATED,
})
REWORK_VERDICTS = frozenset({"rework_engineering"})

# 关键事实的种类（时间轴刻度与离开期间的报告使用，设计说明第 5.5 节）：刻度按种类着色。
# 故障、修复、部署与回滚、进入与离开等待属于 Stage 4，事件种类登记以后在这里补上
FACT_KINDS: dict[str, str] = {
    EventType.ASK_STARTED: "ask",
    EventType.ASK_ANSWERED: "answer",
    EventType.RUN_DONE: "release",
    EventType.RUN_PAUSED: "release",
    EventType.RUN_FAILED: "release",
    ProjectEventType.DELIVERABLE_ADOPTED: "adopt",
    EventType.DECISION_REQUESTED: "decision",
    EventType.DECISION_ANSWERED: "decision",
    EventType.DECISION_WITHDRAWN: "decision",
}

def _fact_kind(event: Event | ProjectEvent) -> str | None:
    # 一条关键事实的种类：质检按结论分为放行与返工，其余按事件种类查表；不是关键事实时返回 None
    if event.type == EventType.QA_SUBMITTED:
        return "rework" if event.payload.get("verdict") in REWORK_VERDICTS else "release"
    return FACT_KINDS.get(event.type)

class AwayReportRequest(Contract):
    # 所选范围（默认自上次查看）与可选的项目筛选
    range: Literal["since_seen", "24h", "7d"] = "since_seen"
    project: str | None = None

class ReportItem(Contract):
    # 汇总的一项：标识、标签、数值与单位、来源事件的全局位置、可选的补充说明
    id: str
    label: str
    value: int
    unit: str
    refs: list[int]
    detail: str | None = None

class ReportFact(Contract):
    # 范围内的一条关键事实：时间、项目、种类、事件位置，供画面回放与时间轴使用。
    # kind 是刻度按种类着色用的关键事实种类（handoff、ask、answer、rework、release、adopt、decision 等）
    position: int
    at: AwareDatetime
    type: str
    kind: str | None
    label: str
    project_id: str | None
    work_item_id: str | None

class LastSeen(Contract):
    # 上次查看的位置与时间；从未查看过时两者都为空
    at: AwareDatetime | None
    position: int | None

class AwayRange(Contract):
    # 所选范围的界限：范围内的起始时间与位置、汇总到的全局位置与时间
    id: Literal["since_seen", "24h", "7d"]
    label: str
    from_at: AwareDatetime
    from_position: int
    to_position: int
    to_at: AwareDatetime

class AwayReport(Contract):
    # 离开期间的报告：上次查看的位置与时间、所选范围的界限、汇总与关键事实
    last_seen: LastSeen
    range: AwayRange
    ranges: list[dict[str, str]]
    summary: list[ReportItem]
    facts: list[ReportFact]

def _away_report(application: Application, request: AwayReportRequest) -> Snapshot[AwayReport]:
    store = application.system.store
    to_position = store.end_position()
    to_at = store.created_at_at(to_position) or utc_now()
    from_position, from_at = _range_start(application, request.range, to_at)
    collected = _events_in_range(store, from_position, to_position, request.project)
    summary = _summary(collected)
    facts = [_fact(event) for event in collected if event.type in FACT_TYPES]
    seen = application.home_seen()
    return Snapshot[AwayReport](
        position=to_position,
        data=AwayReport(
            last_seen=LastSeen(at=None if seen is None else seen[1], position=None if seen is None else seen[0]),
            range=AwayRange(id=request.range, label=RANGES[request.range], from_at=from_at,
                            from_position=from_position, to_position=to_position, to_at=to_at),
            ranges=[{"id": key, "label": label} for key, label in RANGES.items()],
            summary=summary, facts=facts,
        ),
    )

def _range_start(application: Application, range_id: str, to_at: str) -> tuple[int, str]:
    # 范围的起始位置与时间：自上次查看取用户查看过的位置；其余按距离现在的时间，取不晚于边界的事件中最后一条
    store = application.system.store
    if range_id == "since_seen":
        seen = application.home_seen()
        if seen is None:
            # 从未查看过：范围从日志开头开始，起始时间取日志开头的时间
            return 0, (store.created_at_at(0) or to_at)
        return seen[0], seen[1]
    boundary = (datetime.fromisoformat(to_at) - timedelta(seconds=RANGE_SECONDS[range_id])).isoformat()
    events = _events_in_range(store, 0, store.end_position(), None)
    before = [event for event in events if event.created_at <= boundary]
    return (before[-1].position if before else 0), boundary

def _events_in_range(store: Any, from_position: int, to_position: int,
                     project: str | None) -> list[Event | ProjectEvent]:
    # 范围内的全部事件（位置大于起点、不大于终点），可按项目筛选
    collected: list[Event | ProjectEvent] = []
    cursor = from_position
    while cursor < to_position:
        batch = store.read(after=cursor, through=to_position, limit=1000,
                           projects=() if project is None else (project,))
        if not batch:
            break
        collected.extend(batch)
        cursor = batch[-1].position
    return collected

def _summary(events: list[Event | ProjectEvent]) -> list[ReportItem]:
    # 汇总各项：由范围内的事件汇总得到，没有来源事件的项不显示（不写成零）。
    # 完成与放行、用量来自现有事件；故障、修复、部署与回滚、等待模型服务、磁盘与报到属于 Stage 4
    # 「完成与放行的事项」只数成果被采纳（deliverable_adopted）或被质检放行的事项：
    # 跑完一轮（run_done）不算——被用户放弃的建档也是跑完过的，但它的成果没有采纳（工单 #707）
    items: list[ReportItem] = []
    released_events = [
        event for event in events
        if (event.type == EventType.QA_SUBMITTED and event.payload.get("verdict") == "release")
        or event.type == ProjectEventType.DELIVERABLE_ADOPTED
    ]
    released_items = {event.work_item_id for event in released_events if event.work_item_id is not None}
    if released_events:
        items.append(ReportItem(id="released", label="完成与放行的事项", value=len(released_items), unit="项",
                                refs=[event.position for event in released_events]))
    attempts = [event for event in events if event.type == EventType.MODEL_ATTEMPT_FINISHED]
    tokens = sum(int((event.payload.get("usage") or {}).get("total_tokens") or 0) for event in attempts)
    if tokens:
        items.append(ReportItem(id="usage", label="用量", value=tokens, unit="token",
                                refs=[event.position for event in attempts],
                                detail=f"{len(attempts)} 次模型请求"))
    rework = [event for event in events
              if event.type == EventType.QA_SUBMITTED and event.payload.get("verdict") in REWORK_VERDICTS]
    if rework:
        items.append(ReportItem(id="rework", label="返工", value=len(rework), unit="次",
                                refs=[event.position for event in rework]))
    return items

def _fact(event: Event | ProjectEvent) -> ReportFact:
    return ReportFact(
        position=event.position, at=event.created_at, type=event.type, kind=_fact_kind(event),
        label=event_label(event.type, event.payload),
        project_id=event.project_id, work_item_id=event.work_item_id,
    )

class MarkSeen(CommandRequest):
    # 把上次查看的位置更新为用户看到的全局位置
    position: int = Field(ge=0)

def _mark_seen_refs(_events: list[Event | ProjectEvent]) -> NoRefs:
    return NoRefs()

async def _mark_seen(application: Application, command: Command, request: MarkSeen) -> None:
    end = application.system.store.end_position()
    if request.position > end:
        raise Rejection("not_allowed", "查看的位置超过日志末尾，请刷新以后重试")
    application.system.mark_seen(request.position, command=command)

HOME_AWAY_REPORT = QueryDefinition(
    name="home.away_report", request=AwayReportRequest, result=AwayReport, handle=_away_report,
    # 已看过也触发重查：点「已看过」以后同一页面立即显示新的上次查看（工单 #301）
    changed_by=tuple(sorted(FACT_TYPES)) + (EventType.MODEL_ATTEMPT_FINISHED, CatalogEventType.HOME_SEEN),
    unchanged_by=(
        UnchangedEvent(EventType.CONTEXT_ASSEMBLED, "上下文装配不改变这份报告的汇总与关键事实"),
        UnchangedEvent(EventType.MODEL_REQUEST_SERIALIZED, "请求序列化不改变这份报告的汇总与关键事实"),
        UnchangedEvent(EventType.MODEL_REQUESTED, "发出模型请求不改变这份报告的汇总与关键事实"),
        UnchangedEvent(EventType.MODEL_MESSAGE, "模型消息不改变这份报告的汇总与关键事实"),
        UnchangedEvent(EventType.MODEL_REASONING, "模型的推理内容不改变这份报告的汇总与关键事实"),
        UnchangedEvent(EventType.MODEL_STREAM_PROGRESS, "流式进度不改变这份报告的汇总与关键事实"),
        UnchangedEvent(EventType.TOOL_STARTED, "工具开始不改变这份报告的汇总与关键事实"),
        UnchangedEvent(EventType.TOOL_CALLED, "工具调用不改变这份报告的汇总与关键事实"),
    ),
)

HOME_MARK_SEEN = CommandDefinition(
    name="home.mark_seen", request=MarkSeen, refs=NoRefs, handle=_mark_seen, derive_refs=_mark_seen_refs,
    reasons=("not_allowed",),
)
