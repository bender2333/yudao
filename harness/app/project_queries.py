# 项目与事项的查询（设计说明第 4.3 节，当前档）。查询只读取：保存的投影、应用层保存的读取模型
# （调用尝试表与流转记录）与按条件读取的事件；不写入任何内容，也不触发结算、重读或模型调用。
# 结果是快照：position 是这份快照已经包含的最大全局位置，事件流从它之后续上。

from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, field_validator

from ..git_versions import GitVersionError
from ..event_store import run_stream
from ..minimal_projection import MinimalProjection, fold_events
from ..models import (
    ArtifactRef, DEPARTMENTS, TERMINAL_STATUSES, CatalogEventType, EventType, GIT_VERSION_EVENTS,
    ProjectEventType, hash_bytes, stop_reason_name,
)
from ..observability import ObservabilityQuery
from ..providers.selection import ModelSelection
from ..project_projection import replay_project, saved_project
from ..projection import (
    RunNotFoundError, load_decisions, project_run, replay_decisions, replay_events, replay_run, run_handler,
)
from ..projects import ProjectNotFoundError, project_projection
from ..redact import redact_tool_args
from ..streams import STOP_REASON_UPGRADE
from ..replay_check import ReplayIntegrityError, verify_replay
from ..recovery import (
    ACTION_UNKNOWN, OBSERVATION_CANCELLED, OBSERVATION_COMPLETED, OBSERVATION_INTERRUPTED,
    OBSERVATION_PAUSED, OBSERVATION_RUNNING, OBSERVATION_STOPPED, OBSERVATION_WAITING_RESUME,
    action_identity, classify_actions, observation_state, open_decisions, open_resume_decisions,
)
from ..tree_archive import load_tree
from .contracts import Contract, Snapshot, Text
from .labels import event_label, status_name
from .payloads import BaselineCheck, BaselineConclusion, BaselineOmission, BaselineOtherFailure, Department
from .read_models import AttemptStatus, ReadModels
from .registry import QueryDefinition, UnchangedEvent
from .replay import ReplayRequest, check_position

if TYPE_CHECKING:
    from .application import Application


class NotFound(LookupError):
    # 查询的目标不存在：项目、事项、run、事件、尝试或交付中的文件
    pass


class QueryInputInvalid(ValueError):
    # 查询的参数组合或取值不合法：这是输入问题，接口层映射为 422、原因写进 error，命令行打印原因并非零退出。
    # 与 CatalogQueryInvalid 同一类做法（工单 #261）：接口层只认应用层登记过的异常，不去认一个裸 ValueError。
    # 只有登记成这一种输入问题的参数检查才抛它，别的异常照旧冒到框架（工单 #1218）
    pass


# 分页游标：第一页位置、最后一条记录的位置与标识（设计说明第 4.1 节）
CURSOR_PATTERN = re.compile(r"^\d+:\d+:.+$")


# ---------------------------------------------------------------------------
# 公共形状


class AdoptionView(Contract):
    adoption_id: str
    work_item_id: str
    run_id: str
    summary: str
    files: list[str]
    check_names: list[str]
    known_risks: list[str]
    code_tree_digest: str
    adopted_at: str
    event_id: str | None
    # 采纳链：上一次采纳的成果。建档基线是第一个采纳成果，这里为空（设计第 5 节）
    previous_adoption_id: str | None
    # 建档基线特有的三项（工单 #136，设计第 3.4 节）：是否为建档采纳的基线、快照来源（采集的源目录与
    # git 提交、分支、是否有未提交的修改）、现有缺陷数。普通事项的交付采纳：基线为假、来源为空、缺陷数为 0
    onboarding_baseline: bool
    snapshot_source: str | None
    snapshot_provenance: dict[str, Any] | None
    existing_defect_count: int


class InputView(Contract):
    input_id: str
    version: int
    text: str
    kind: str
    byte_start: int
    byte_end: int
    created_event_id: str
    git_version: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# projects.list


class ProjectsList(ReplayRequest):
    # 可回放（设计说明第 4.1 节）：at 是全局位置，省略时读取现在的快照
    include_archived: bool = False


class ProjectRow(Contract):
    project_id: str
    name: str
    goal: str
    source: str
    pinned: bool
    archived: bool
    created_at: str
    updated_at: str
    # 项目基本信息的版本：项目类命令的基准版本
    version: int
    work_item_count: int
    in_progress_count: int
    # 排队中的事项数：状态为未开始或排队中（设计说明第 4.3 节 projects.list 的项目列表字段）
    waiting_count: int
    # 待回答的决定数：本项目等待回答的决定请求数（首页与左侧栏按它显示数量）
    decisions_waiting: int
    # 最近活动时间：项目流与它各 run 的最后一条事件时间中最晚的一个
    last_activity_at: str
    active_work_item_id: str | None
    current_adoption: str | None
    # 建档状态标记：项目由接入已有项目建立且还没有基线时，建档中为 onboarding，等待确认初始 PRD 为
    # awaiting_initial_prd，等待建档（建档停止、还没有基线）为 awaiting_onboarding；其余为空
    onboarding_status: str | None
    # 中断与待恢复的标记（工单 #18）：本项目里处于这些恢复观察状态的事项数；
    # 为零时仍是 0，不省略
    interrupted_count: int
    waiting_resume_count: int


class ProjectList(Contract):
    projects: list[ProjectRow]


def _projects_list(application: Application, request: ProjectsList) -> Snapshot[ProjectList]:
    store = application.system.store
    through = check_position(application, request.at)
    rows: list[ProjectRow] = []
    for project_id in store.list_project_ids(through=through):
        state = _project(application, project_id, through=through)
        if state.archived and not request.include_archived:
            continue
        observations = [_recovery_observation(application, item.run_id) for item in state.work_items]
        rows.append(ProjectRow(
            project_id=state.project_id, name=state.name, goal=state.goal, source=state.source,
            pinned=state.pinned, archived=state.archived, created_at=state.created_at,
            updated_at=state.updated_at, version=state.stream_version, work_item_count=len(state.work_items),
            in_progress_count=sum(item.status == "in_progress" for item in state.work_items),
            waiting_count=sum(item.status in {"not_started", "held"} for item in state.work_items),
            decisions_waiting=sum(1 for item in store.decisions(projects=(project_id,), statuses=("open",))[1]),
            last_activity_at=_last_activity(store, state, through=through),
            active_work_item_id=state.active_work_item_id,
            current_adoption=None if state.current_adoption is None else state.current_adoption.adoption_id,
            onboarding_status=_onboarding_status(state),
            interrupted_count=observations.count(OBSERVATION_INTERRUPTED),
            waiting_resume_count=observations.count(OBSERVATION_WAITING_RESUME),
        ))
    return Snapshot[ProjectList](position=_snapshot_position(store, through), data=ProjectList(projects=rows))

def _last_activity(store: Any, state: Any, *, through: int | None) -> str:
    # 最近活动时间：项目流最后一条事件的时间，与这个项目各 run 最后一条事件的时间取最晚的一个。
    # 项目流没有事件时回落到创建时间；比较用 ISO 字符串（带时区，字典序与时间序一致）
    times = [state.updated_at or state.created_at]
    for item in state.work_items:
        bounds = store.run_time_bounds(item.run_id, through=through)
        if bounds is not None:
            times.append(bounds[1])
    return max(times)

def _onboarding_status(state: Any) -> str | None:
    # 建档中的项目还没有基线采纳：建档事项进行中为 onboarding，已结束而决定请求仍打开为
    # awaiting_initial_prd，其余（建档停止、还没有基线）为 awaiting_onboarding
    if state.source != "existing" or state.current_adoption is not None:
        return None
    if any(item.kind == "onboarding" and item.status == "in_progress" for item in state.work_items):
        return "onboarding"
    if any(item.kind == "onboarding" and item.status == "awaiting_initial_prd" for item in state.work_items):
        return "awaiting_initial_prd"
    return "awaiting_onboarding"

# ---------------------------------------------------------------------------
# project.overview


class ProjectOverview(Contract):
    # 项目内的查询都接受事项范围参数：给出事项时只返回它（设计说明第 4.1 节）
    project_id: str
    work_item: str | None = None


# 部门状态的取值：总图第三节外环的五个词（三部门的循环结构第 2.1 节，工单 #903）
DEPARTMENT_STATES = ("waiting_user", "working", "asking", "verifying", "waiting")
# 阻塞事项的决定请求：回答以前事项（它的 run）不推进（decisions.py 的 blocks）
BLOCKING_SCOPES = ("run", "work_item")
# 谁核验谁的成果取自定义里的「谁能拒绝谁」：成果驱动下只有工程的交付由质检核验（循环结构第 2.1 节）
VERIFIER_OF = {"engineering": "quality"}


class DepartmentState(Contract):
    """一个部门在这个事项上的状态与原因（三部门的循环结构第 2.1 节）。

    state 取总图外环的五个词；note 是一句话，没有原因时为空。
    """
    state: Literal["waiting_user", "working", "asking", "verifying", "waiting"]
    note: str | None = None


class WorkItemProgress(Contract):
    """事项的进度：从成果推算（循环结构第 2 节）。

    阶段不再决定下一个谁工作，进度改由成果推算：当前有效的 PRD 是第几版、
    最新一份交付是第几版、它依据的 PRD 版本，以及对最新交付的结论。
    """

    product_spec_revision: int | None
    delivery_revision: int | None
    delivery_product_spec_revision: int | None
    conclusion: str | None


class KeptDelivery(Contract):
    """已收下的交付（工单 #1239）：事项停止时，这个 run 里已经收下的那一版交付与收下的时间。

    事项因为别的原因停下时，已收下的交付仍然在，页面在停止说明下面写出这一句，
    免得用户看不出这件事已经有一份可用的交付。
    """

    version: int
    accepted_at: str


class WorkItemCard(Contract):
    work_item_id: str
    kind: str
    title: str
    text: str
    run_id: str
    version: int
    created_at: str
    status: str
    department: str | None
    # 事项的进度：从成果推算（循环结构第 2 节、工单 #556）
    progress: WorkItemProgress | None
    # 三个部门各自的状态与原因（循环结构第 2.1 节，工单 #903）：事项没有 run、已经结束或中断时为空
    departments: dict[str, DepartmentState] | None = None
    round: int
    stop_reason: str | None
    # 停止说明（工单 #1162）：让事项停下的那条错误的原文，取自事项结束的事件；只有停止的事项有，
    # 询问分支的失败原因不算，用户自己让事项停下时为空
    stop_note: str | None = None
    # 已收下的交付（工单 #1239）：事项停止时这个 run 里已经收下的那一版交付与收下的时间；
    # 没有已收下的交付时为空。用户自己取消时也写，交付仍然在
    kept_delivery: KeptDelivery | None = None
    human_action: str | None
    pending_question: str | None
    adoption_id: str | None
    start_error: str | None


class WorkItemStats(Contract):
    total: int
    in_progress: int
    adopted: int
    released_unsettled: int
    stopped: int
    held: int
    not_started: int


class ProjectOverviewResult(Contract):
    project_id: str
    name: str
    goal: str
    version: int
    current_adoption: AdoptionView | None
    stats: WorkItemStats
    work_items: list[WorkItemCard]
    # 起点说明（工单 #321）：项目还没有采纳成果时给出起始文件夹与它的文件数，供界面显示
    # 「起点：起始文件夹（N 个文件）」；有采纳成果以后起点是采纳成果，不再返回
    start_point: str | None = None


def _project_overview(application: Application, request: ProjectOverview) -> Snapshot[ProjectOverviewResult]:
    store = application.system.store
    state = _project(application, request.project_id, include_history=False)
    items = ([_work_item(state, request.work_item)] if request.work_item is not None else state.work_items)
    cards: list[WorkItemCard] = []
    for item in items:
        # run 投影、决定请求与事件一起读取一次：进度与部门状态都用这一份（工单 #903）
        run, decisions, events = _item_sources(application, item.run_id)
        progress = _work_item_progress(run)
        cards.append(WorkItemCard(
            work_item_id=item.work_item_id, kind=item.kind, title=item.title, text=item.text, run_id=item.run_id,
            version=item.stream_version, created_at=item.created_at, status=item.status,
            department=item.department,
            progress=progress,
            departments=_departments(run, progress, _observation(run, decisions, events), decisions),
            round=item.cycle_count,
            stop_reason=item.stop_reason, stop_note=item.stop_note,
            kept_delivery=None if item.kept_delivery is None else KeptDelivery(**item.kept_delivery),
            human_action=item.human_action,
            pending_question=item.pending_question, adoption_id=item.adoption_id,
            start_error=item.start_error,
        ))
    return Snapshot[ProjectOverviewResult](
        position=store.end_position(),
        data=ProjectOverviewResult(
            project_id=state.project_id, name=state.name, goal=state.goal, version=state.stream_version,
            current_adoption=_adoption(state.current_adoption),
            stats=_work_item_stats(items),
            start_point=(None if state.current_adoption is not None or not state.initial_snapshot
                         else f"起点：起始文件夹（{len(state.initial_snapshot.get('files') or [])} 个文件）"),
            work_items=cards,
        ),
    )


def _work_item_stats(items: list[Any]) -> WorkItemStats:
    statuses = [item.status for item in items]
    return WorkItemStats(
        total=len(statuses), in_progress=statuses.count("in_progress"), adopted=statuses.count("adopted"),
        released_unsettled=statuses.count("released_unsettled"), stopped=statuses.count("stopped"),
        held=statuses.count("held"), not_started=statuses.count("not_started"),
    )


def _adoption(item: Any) -> AdoptionView | None:
    # 建档基线（工单 #136，设计第 5 节）：prd_ref 有值说明这次采纳的成果是接入时采集的快照本身；
    # 快照来源取它的 source 与 provenance，旧事件没有 provenance 时为空。现有缺陷数是基线核验里状态为
    # existing_defect 的结论数；known_risks 还含未被结论覆盖的其他失败，不计入。普通交付采纳不是建档基线，为 0
    if item is None:
        return None
    snapshot = item.snapshot or {}
    baseline = item.prd_ref is not None
    return AdoptionView(
        adoption_id=item.adoption_id, work_item_id=item.work_item_id, run_id=item.run_id, summary=item.summary,
        files=list(item.files), check_names=list(item.check_names), known_risks=list(item.known_risks),
        code_tree_digest=item.code_tree_digest, adopted_at=item.adopted_at, event_id=item.event_id,
        onboarding_baseline=baseline, snapshot_source=snapshot.get("source"),
        previous_adoption_id=item.previous_adoption_id,
        snapshot_provenance=snapshot.get("provenance"),
        existing_defect_count=len(item.existing_defects) if baseline else 0,
    )


# ---------------------------------------------------------------------------
# project.loop


class ProjectLoop(ReplayRequest):
    # 可回放（设计说明第 4.1 节）：at 是全局位置，省略时读取现在的快照
    project_id: str
    work_item: str | None = None


class WorkItemLoop(Contract):
    work_item_id: str
    kind: str
    sign: str
    color_index: int
    # 事项状态；建档事项结束而初始 PRD 仍待确认时为 awaiting_initial_prd（工单 #136）
    status: str
    department: str | None
    progress: WorkItemProgress | None
    # 三个部门各自的状态与原因（循环结构第 2.1 节，工单 #903）：事项没有 run、已经结束或中断时为空
    departments: dict[str, DepartmentState] | None = None
    round: int
    started_at: str | None
    elapsed_sec: int | None
    time_limit_sec: int
    pending_question: str | None
    run_id: str
    adoption_id: str | None
    # 恢复观察状态（工单 #18、#747）：运行中、中断、待恢复，以及完成、暂停、取消、停止四种结束方式；
    # run 没有创建时没有
    recovery_state: str | None
    # 停止原因与最后活动的部门（工单 #1186，设计说明第 4.3 节 2026-10-29 补充）：画面的门口牌子与概览入口读它们。
    # 停止原因来自所属 run 的停止原因；最后活动的部门取自 run 的最后一条带部门的事件——结束的 run 没有当前部门，
    # 画面按它把门口牌子立在最后工作的那个房间
    stop_reason: str | None
    last_department: str | None
    # 事项的版本：取消事项等命令的基准版本
    version: int


class ProjectLoopResult(Contract):
    project_id: str
    work_items: list[WorkItemLoop]
    adoptions: list[AdoptionView]


def _project_loop(application: Application, request: ProjectLoop) -> Snapshot[ProjectLoopResult]:
    store = application.system.store
    through = check_position(application, request.at)
    state = _project(application, request.project_id, include_history=False, through=through)
    if request.work_item is not None:
        _work_item(state, request.work_item)
    at_time = None if through is None else store.created_at_at(through)
    rows: list[WorkItemLoop] = []
    for index, item in enumerate(state.work_items):
        if request.work_item is not None and item.work_item_id != request.work_item:
            continue
        run, decisions, events = _item_sources(application, item.run_id, through=through)
        progress = _work_item_progress(run)
        observation = _observation(run, decisions, events)
        bounds = store.run_time_bounds(item.run_id, through=through)
        rows.append(WorkItemLoop(
            work_item_id=item.work_item_id, kind=item.kind, sign=item.title, color_index=index + 1, status=item.status,
            department=item.department, progress=progress, round=item.cycle_count,
            departments=_departments(run, progress, observation, decisions),
            started_at=None if bounds is None else bounds[0],
            elapsed_sec=None if bounds is None else _elapsed_seconds(bounds, terminal=run, now=at_time),
            time_limit_sec=item.run_time_limit_sec, pending_question=item.pending_question,
            run_id=item.run_id, adoption_id=item.adoption_id,
            recovery_state=observation, stop_reason=item.stop_reason,
            last_department=_last_department(store, item, through=through), version=item.stream_version,
        ))
    return Snapshot[ProjectLoopResult](
        position=_snapshot_position(store, through),
        data=ProjectLoopResult(project_id=state.project_id, work_items=rows,
                               adoptions=[_adoption(item) for item in state.adoptions]),
    )


def _last_department(store: Any, item: Any, *, through: int | None = None) -> str | None:
    """最后活动的部门（工单 #1186，设计说明第 4.3 节 2026-10-29 补充）。

    进行中的 run 当前就在这个部门里工作，直接用事项的当前部门；结束的 run 没有当前部门，
    从它的事件里找最后一条带部门的事件。没有 run、没有事件或事件里都没有部门时为 None。
    """
    if item.department is not None:
        return item.department
    for event in reversed(store.list_events(item.run_id, through_position=through)):
        if event.department:
            return event.department
    return None


def _work_item_progress(run: Any) -> WorkItemProgress | None:
    """事项的进度：从成果推算（循环结构第 2 节）。

    当前有效的 PRD 是第几版、最新一份交付是第几版、它依据的 PRD 版本，
    以及对最新交付的结论（缺陷记录或放行）。
    """
    if run is None:
        return None
    spec = getattr(run, "product_spec", None)
    delivery = getattr(run, "delivery_spec", None)
    if delivery is None:
        specs = getattr(run, "delivery_specs", None) or []
        delivery = specs[-1] if specs else None
    conclusion = None
    for review in reversed(getattr(run, "reviews", None) or []):
        if delivery is not None and review.delivery_spec_hash == delivery.content_hash:
            conclusion = review.verdict
            break
    # 交付依据的 PRD 版本：按交付记录的 PRD 摘要找到那一版的修订号
    basis_revision = None
    if delivery is not None:
        for item in getattr(run, "product_specs", None) or []:
            if item.content_hash == delivery.product_spec_hash:
                basis_revision = item.revision
                break
    return WorkItemProgress(
        product_spec_revision=None if spec is None else spec.revision,
        delivery_revision=None if delivery is None else delivery.revision,
        delivery_product_spec_revision=basis_revision,
        conclusion=conclusion,
    )


def _item_sources(application: Application, run_id: str, *, through: int | None = None
                  ) -> tuple[Any, dict[str, Any], list[Any]]:
    """一个事项的 run 投影、决定请求与事件（工单 #903）。

    部门状态要会话、进行中的询问、没有回答的决定请求与恢复观察状态一起算，三者一次读出：
    run 投影与它的决定请求来自同一次投影读取，不因为多算一个字段而多读一遍。
    已经结束的 run 不需要事件（恢复观察状态只看状态与停止原因）。
    """
    store = application.system.store
    if through is not None:
        events = store.list_events(run_id, through_position=through)
        if not events:
            return None, {}, []
        return replay_events(events), replay_decisions(events), events
    saved = store.projection(run_stream(run_id))
    if saved is None:
        return None, {}, []
    run = run_handler().load(saved)
    decisions = load_decisions(saved)
    if run.status in TERMINAL_STATUSES:
        return run, decisions, []
    return run, decisions, store.list_events(run_id)


def _observation(run: Any, decisions: Any, events: list[Any]) -> str | None:
    # 一个事项的恢复观察状态（工单 #18）：由已经读出的 run、决定请求与事件算出
    if run is None:
        return None
    return observation_state(events, decisions.values(), status=run.status, stop_reason=run.stop_reason)


def _departments(run: Any, progress: WorkItemProgress | None, observation: str | None,
                 decisions: dict[str, Any]) -> dict[str, DepartmentState] | None:
    """三个部门各自的状态与原因（三部门的循环结构第 2.1 节，工单 #903）。

    状态不单独记录，由已经记录的事实现算：会话的状态、进行中的询问、没有回答的决定请求与成果。
    同时满足几条时按设计说明的顺序取第一条：等用户、在分支里回答、询问中、主线的一轮工作中、核验中、等待工作。
    """
    if run is None or run.status in TERMINAL_STATUSES or observation == OBSERVATION_INTERRUPTED:
        return None
    waiting_user = {decision.request.get("department") for decision in decisions.values()
                    if decision.status == "open" and decision.blocks in BLOCKING_SCOPES}
    # 还没回答的询问：链上每一层一个，最内层在最后（投影的 ask_stack）
    asks = list(run.ask_stack)
    departments: dict[str, DepartmentState] = {}
    for department in DEPARTMENTS:
        session = run.sessions.get(department)
        main_session = None if session is None else session.session_id
        active = session is not None and session.status == "active"
        # 这条部门主线停在自己发出、还没有回答的询问上
        own_ask = next((ask for ask in reversed(asks) if ask.get("origin_session_id") == main_session), None)
        # 还在等这个部门回答的询问：部门在它的分支里回答（分支嵌在提问方那一轮里）
        incoming = next((ask for ask in reversed(asks) if ask.get("recipient") == department), None)
        if department in waiting_user:
            state, note = "waiting_user", None
        elif incoming is not None:
            state, note = "working", f"回答{_department_label(incoming.get('requester') or '')}的询问"
        elif own_ask is not None:
            state, note = "asking", f"在等待{_department_label(own_ask.get('recipient') or '')}的回答"
        elif active:
            # 质检在交付到达之前的一轮是预测性探索：按 PRD 起草测试用例（循环结构第 3.1 节）
            predictive = (department == "quality" and not run.delivery_specs and progress is not None
                          and progress.product_spec_revision is not None)
            state = "working"
            note = (f"预测性探索：按 PRD r{progress.product_spec_revision} 起草测试用例"
                    if predictive else None)
        elif _awaiting_verification(department, progress):
            state, note = "verifying", f"等{_department_label(VERIFIER_OF[department])}核验交付 r{progress.delivery_revision}"
        else:
            state, note = "waiting", None
        departments[department] = DepartmentState(state=state, note=note)
    return departments


def _awaiting_verification(department: str, progress: WorkItemProgress | None) -> bool:
    # 核验中：最新的正式成果在等下游的结论。成果驱动下只有工程有这种情况：
    # 最新的交付还没有质检的缺陷记录或放行（循环结构第 2.1 节）
    if department not in VERIFIER_OF or progress is None or progress.delivery_revision is None:
        return False
    return progress.conclusion is None


def _elapsed_seconds(bounds: tuple[str, str], *, terminal: Any, now: str | None = None) -> int:
    # 已用时间：进行中的 run 到「现在」，终态的 run 到最后一条事件。
    # 按位置读取（now 给出该位置的事件时间）时进行中的 run 也到那个时间为止（设计说明第 4.1 节）
    started = datetime.fromisoformat(bounds[0])
    if terminal is not None:
        stopped = datetime.fromisoformat(bounds[1])
    else:
        stopped = datetime.fromisoformat(now) if now is not None else datetime.now(timezone.utc)
    return max(0, int((stopped - started).total_seconds()))


# ---------------------------------------------------------------------------
# project.flow


class ProjectFlow(Contract):
    project_id: str
    work_item: str | None = None


class FlowRecord(Contract):
    flow_id: str
    kind: str
    status: str
    content: str
    direction_from: str | None
    direction_to: str | None
    run_id: str | None
    work_item_id: str | None
    position: int
    seq: int
    event_id: str
    created_at: str


class ProjectFlowResult(Contract):
    records: list[FlowRecord]


def _project_flow(application: Application, request: ProjectFlow) -> Snapshot[ProjectFlowResult]:
    state = _project(application, request.project_id, include_history=False)
    if request.work_item is not None:
        _work_item(state, request.work_item)
    read_models = _read_models(application)
    position, rows = read_models.flows(project_id=request.project_id, work_item_id=request.work_item)
    return Snapshot[ProjectFlowResult](
        position=position,
        data=ProjectFlowResult(records=[
            FlowRecord(
                flow_id=row["flow_id"], kind=row["kind"], status=row["status"], content=row["content"],
                direction_from=row["direction_from"], direction_to=row["direction_to"], run_id=row["run_id"],
                work_item_id=row["work_item_id"], position=row["position"], seq=row["seq"],
                event_id=row["event_id"], created_at=row["created_at"],
            )
            for row in rows
        ]),
    )


# ---------------------------------------------------------------------------
# work_item.inputs


class WorkItemInputs(Contract):
    project_id: str
    work_item: str


class WorkItemInputsResult(Contract):
    work_item_id: str
    run_id: str
    input_version: int
    processed_input_version: int
    inputs: list[InputView]


def _work_item_inputs(application: Application, request: WorkItemInputs) -> Snapshot[WorkItemInputsResult]:
    store = application.system.store
    state = _project(application, request.project_id, include_history=False)
    item = _work_item(state, request.work_item)
    run = _run(application, item.run_id)
    versions = {entry["event_id"]: entry for entry in run.git_versions}
    return Snapshot[WorkItemInputsResult](
        position=store.end_position(),
        data=WorkItemInputsResult(
            work_item_id=item.work_item_id, run_id=run.run_id, input_version=run.input_version,
            processed_input_version=run.processed_input_version,
            inputs=[
                InputView(
                    input_id=value.id, version=value.version, text=value.text, kind=value.kind,
                    byte_start=value.byte_start, byte_end=value.byte_end,
                    created_event_id=value.created_event_id,
                    git_version=_git_version_of(versions, value.created_event_id),
                )
                for value in run.inputs
            ],
        ),
    )


def _git_version_of(versions: dict[str, Any], event_id: str) -> dict[str, Any] | None:
    entry = versions.get(event_id)
    if entry is None:
        return None
    return {key: value for key, value in entry.items() if key not in {"event_id", "type"}}


# ---------------------------------------------------------------------------
# event.detail


class EventDetail(Contract):
    event_id: str


class EventDetailResult(Contract):
    event: dict[str, Any]
    artifacts: dict[str, Any]


def _event_detail(application: Application, request: EventDetail) -> Snapshot[EventDetailResult]:
    store = application.system.store
    event = store.get_event(request.event_id)
    if event is None:
        project_event = store.get_project_event(request.event_id)
        if project_event is None:
            raise NotFound(f"event not found: {request.event_id}")
        return Snapshot[EventDetailResult](position=project_event.position,
                                           data=EventDetailResult(event=project_event.to_dict(), artifacts={}))
    return Snapshot[EventDetailResult](
        position=event.position,
        data=EventDetailResult(event=event.to_dict(), artifacts=_event_artifacts(application, event)),
    )


def _event_artifacts(application: Application, event: Any) -> dict[str, Any]:
    # 一条 run 事件的完整内容：正式事件的 Git 版本、交付封存、引用的工件原文与压缩来源
    artifacts = application.system.artifacts
    run_id = event.run_id
    loaded: dict[str, Any] = {}
    version = event.payload.get("git_version")
    if event.type in GIT_VERSION_EVENTS:
        if version is None:
            raise NotFound("该正式事件缺少 Git 版本记录")
        try:
            loaded["git_version"] = application.system.git_versions.show(run_id, version)
        except GitVersionError as error:
            raise NotFound(str(error)) from error
    elif version is not None:
        raise NotFound("Git 版本未绑定正式事件")
    if event.type == EventType.DELIVERY_ACCEPTED:
        tree, archive = _delivery_archive(application, event)
        loaded["tree_archive"] = archive
        loaded["tree_files"] = [{"path": item.path, "size": len(item.data)} for item in tree.files]
    ref = event.payload.get("prd_ref")
    if ref:
        loaded["prd"] = artifacts.get_for_run(run_id, ArtifactRef(**ref)).decode("utf-8")
    ref = event.payload.get("request_ref")
    if ref:
        loaded["request"] = json.loads(artifacts.get_for_run(run_id, ArtifactRef(**ref)))
    for key, target in (("input_ref", "input"), ("message_ref", "message"), ("output_ref", "output"),
                        ("guidance_ref", "guidance")):
        ref = event.payload.get(key)
        if not ref:
            continue
        raw = artifacts.get_for_run(run_id, ArtifactRef(**ref))
        loaded[target] = (
            raw.decode("utf-8") if event.type in {EventType.USER_INPUT_RECEIVED,
                                                  EventType.DEPARTMENT_GUIDANCE_RECEIVED}
            else json.loads(raw)
        )
    for key, target in (("intend_ref", "intend"), ("prompt_ref", "prompt")):
        ref = event.payload.get(key)
        if ref:
            loaded[target] = artifacts.get_for_run(run_id, ArtifactRef(**ref)).decode("utf-8")
    if event.payload.get("summary_ref"):
        loaded["compaction_summary"] = artifacts.get_for_run(
            run_id, ArtifactRef(**event.payload["summary_ref"]),
        ).decode("utf-8")
        loaded["compaction_sources"] = _compaction_sources(application, event)
    return loaded


def _compaction_sources(application: Application, event: Any) -> list[dict[str, Any]]:
    # 压缩的来源事件：核对它们与这条压缩记录的部门、序号与步骤一致
    store = application.system.store
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in event.payload["source_refs"]:
        source = store.get_event(ref["event_id"])
        if (source is None or source.run_id != event.run_id or source.department != event.department
                or source.stream_version != ref["seq"]
                or source.payload.get("activation_id") != ref["activation_id"]
                or source.payload.get("step_id") != ref["step_id"]):
            raise ValueError("compaction source does not match its department history")
        if source.event_id not in seen:
            sources.append(source.to_dict())
            seen.add(source.event_id)
    prior = event.payload.get("previous_compaction_event_id")
    if prior:
        source = store.get_event(prior)
        if (source is None or source.run_id != event.run_id or source.department != event.department
                or source.type != EventType.COMPACTION_RECORDED):
            raise ValueError("previous compaction does not match its department")
        sources.insert(0, source.to_dict())
    return sources


def _delivery_archive(application: Application, event: Any) -> tuple[Any, Any]:
    ref = ArtifactRef(**event.payload["tree_ref"])
    artifacts = application.system.artifacts
    tree = load_tree(artifacts, event.run_id, ref)
    if tree.digest != event.payload["code_tree_digest"]:
        raise ValueError("archived tree does not match its accepted delivery")
    return tree, json.loads(artifacts.get_for_run(event.run_id, ref))


# ---------------------------------------------------------------------------
# department.workspace


class DepartmentWorkspace(Contract):
    project_id: str
    department: Department
    work_item: str | None = None


class DepartmentSettingState(Contract):
    department: str
    configured_version: int
    configured_text: str
    source: str
    used_version: int | None
    used_event_id: str | None
    department_setting_configured: bool = False


class GuidanceRecord(Contract):
    # 指导的三种状态（部门指导设计说明第 3 节，工单 #1039）：received 已接收、in_input 已进入模型输入、
    # answered 已回答。已回答由主机在收到它的那一轮正常结束时写，事件记下那一轮与怎么结束的
    guidance_id: str
    version: int
    text: str
    status: str
    applied_activation_id: str | None
    answered_activation_id: str | None
    outcome: str | None
    created_event_id: str


class RoomCrt(Contract):
    # 后墙的 CRT 监视器显示的内容（v8 设计说明第 8.1 节）
    target: str
    model: str
    protocol: str
    status: str
    cycle: int | None

class RoomRole(Contract):
    # 房间里的一个角色（Stage 5 起一个部门有多个角色；当前档一个部门一个 Agent）
    id: str
    name: str
    kind: str
    status: str
    task: str | None

class RoomPipes(Contract):
    # 房间的管道状态：out 是交接管道，letters_waiting 是停在传信管出口的未回答询问数
    out: str
    letters_waiting: int

class RoomView(Contract):
    # 部门房间的画面数据（v8 设计说明第 8 节、v9 设计说明第 1 节）：状态、CRT、角色、门口状态、
    # 信箱与档案盒的数量、管道状态。Stage 4 与 3.2C、3.2D 的字段在当前档保持为空或零。
    department: str
    level: str
    status: str
    crt: RoomCrt
    roles: list[RoomRole]
    existing_read: bool
    pose: dict[str, Any] | None
    door: str | None
    hold_card: str | None
    pending_tool: str | None
    mailbox: int
    summaries: int
    scrolls: int
    pinned_notes: int
    semantic_cards: int
    machine: str | None
    remote_unknown: bool
    waiting_provider: bool
    pipes: RoomPipes
    trial: dict[str, Any] | None
    tool_panel: dict[str, Any] | None
    self_test: dict[str, Any] | None

class EffectiveModel(Contract):
    # 本部门当前生效的模型及来源（设计说明第 9.3 节）：按第 5.3 节的选择规则与当前目录计算，不发送请求。
    # state 为 effective 时给出模型与来源；为 unusable 时给出 reason 与 message；
    # 为 unset 时都没有设置。unusable 与 unset 时不返回其他连接或模型
    state: Literal["effective", "unusable", "unset"]
    provider_id: str | None = None
    model_id: str | None = None
    provider_name: str | None = None
    protocol: str | None = None
    model: str | None = None
    selection_source: str | None = None
    requested_tier: str | None = None
    sent_tier: str | None = None
    reason: str | None = None
    message: str | None = None

class DepartmentWorkspaceResult(Contract):
    project_id: str
    department: str
    work_item_id: str | None
    run_id: str | None
    # run 的状态（进行中与三个终态）：部门进行到哪一步不记在这里（工单 #556）
    run_status: str | None
    # 三个部门各自的状态与原因（循环结构第 2.1 节，工单 #903）：事项没有 run、已经结束或中断时为空
    departments: dict[str, DepartmentState] | None = None
    # 事项状态与停止原因：用户停止的事项在部门页写「已停止」，不写「执行失败」（工单 #319）
    status: str | None
    stop_reason: str | None
    active: bool
    department_setting: DepartmentSettingState
    setting: DepartmentSetting
    effective: EffectiveModel
    guidance: list[GuidanceRecord]
    messages: list[dict[str, Any]]
    context: dict[str, Any]
    last_call: dict[str, Any] | None
    reminders: list[str]
    room: RoomView


def _project_selection(setting: Any) -> ModelSelection | None:
    # 项目部门设置中的模型选择：模型两项与请求档位分别写入，没有写入模型时为空（跟随部门默认）
    if not setting.model_id:
        return None
    return ModelSelection(provider_id=setting.provider_id, model_id=setting.model_id,
                          requested_tier=setting.requested_tier)

def _effective_model(application: Application, setting: Any, department: str) -> EffectiveModel:
    # 本部门当前生效的模型及来源（设计说明第 9.3 节）：按第 5.3 节的顺序解析，不发送请求。
    # 没有任何一层写入模型时为「未设置」，引用无法使用时为「无法使用」并带回原因；
    # 这两种情况都不返回其他连接或模型
    resolution = application.system.facade.resolve_effective_model(department, _project_selection(setting))
    if resolution.resolution is None:
        return EffectiveModel(state="unset")
    target = resolution.resolution
    if not target.available:
        return EffectiveModel(state="unusable", reason=target.reason, message=target.message)
    public = target.public
    return EffectiveModel(
        state="effective",
        provider_id=public.get("provider_config_id"),
        model_id=public.get("model_id"),
        provider_name=public.get("provider_name"),
        protocol=public.get("protocol"),
        model=public.get("requested_model"),
        selection_source=target.selection_source,
        requested_tier=public.get("requested_tier"),
        sent_tier=public.get("sent_tier"),
    )

# 房间状态显示的文字（原型 contract/handlers/department.js 的 STATUS_TEXT）
ROOM_STATUS_TEXT = {
    "idle": "未工作", "working": "工作中", "asking": "等待回答", "paused": "已暂停", "failed": "失败",
    "done": "已完成", "cancelled": "已取消", "interrupted": "中断",
    "waiting_resume": "待恢复",
}
# 钉在指导板上的指导状态（原型 PINNED）：已进入模型输入与已回答的指导还在板上
ROOM_PINNED_GUIDANCE = frozenset({"in_input", "answered"})

def _room_status(run: Any, department: str, observation: str | None) -> str:
    # 房间状态（原型 roomStatus）：本部门正在工作时按恢复观察状态、未回答的询问、run 阶段取值；
    # 本部门参与过这次 run 时按 run 的终态；否则未工作。
    # 恢复观察状态只取待恢复这种由决定请求给出的事实；进程存活性给出的
    if run is None:
        return "idle"
    if run.active_department == department:
        if observation == OBSERVATION_WAITING_RESUME:
            return "waiting_resume"
        if run.status == "paused":
            return "paused"
        if run.status == "failed":
            return "failed"
        if run.status == "done":
            return "done"
        return "working"
    # 本部门参与过这次 run（它的激活记录已写入）时按 run 的终态；否则未工作
    if department not in run.last_activations:
        return "idle"
    if run.stop_reason and run.stop_reason == "cancelled":
        return "cancelled"
    if run.status == "failed":
        return "failed"
    if run.status == "paused":
        return "paused"
    if run.status == "done":
        return "done"
    return "idle"

def _room_door(run: Any, status: str) -> str | None:
    # 门口立牌的文字（原型 doorOf）：暂停与中断写在牌上，其余状态没有牌子
    if status == "paused":
        return "已暂停"
    if status == "interrupted":
        return "中断"
    if run is not None and run.stop_reason and run.stop_reason == STOP_REASON_UPGRADE:
        return "因升级停止"
    return None

def _room_view(application: Application, state: Any, item: Any, run: Any, department: str,
               guidance: list[GuidanceRecord], effective: EffectiveModel, observation: str | None) -> RoomView:
    # 部门房间的画面数据（v8 设计说明第 8 节）：状态、CRT、角色、门口状态、信箱与档案盒、管道状态。
    # Stage 4（运维）、3.2C（远程执行）与 3.2D（试用）的数据尚未进入 run 投影，这些字段保持为空或零。
    # 恢复观察状态由调用处读出（工单 #903）：房间与部门状态用它判断，不各读一次
    status = _room_status(run, department, observation)
    target = "—" if item is None else item.title
    protocol = "—"
    if run is not None:
        call_target = run.provider_bindings.get(department)
        if call_target:
            protocol = call_target.get("requested_protocol") or "—"
    model_label = effective.model_id or "—"
    role_id = department + "-agent"
    role_kind = "ops" if department == "operations" else "agent"
    role_status = "working" if status == "working" else "idle"
    role_name = f"{_department_label(department)}部门 Agent"
    pose = {"role_id": role_id, "action": "typing"} if status == "working" else None
    # 传信数：问本部门、还没有回答的询问数（循环结构第 4.7 节，工单 #903）
    letters_waiting = 0 if run is None else sum(1 for ask in run.ask_stack if ask.get("recipient") == department)
    waiting_provider = False
    scrolls = 0
    if run is not None and department == "product":
        # 卷轴数的来源是产品写出的 PRD 版本数（v8 设计说明第 8.1 节的卷轴架）
        scrolls = len(run.product_specs)
    summaries = 0
    if run is not None:
        summaries = max((int(entry.get("n") or 0) for entry in run.compactions), default=0)
    return RoomView(
        department=department, level="ui", status=status,
        crt=RoomCrt(target=target, model=model_label, protocol=protocol,
                    status=ROOM_STATUS_TEXT[status], cycle=None if run is None else run.cycle_count),
        # 角色的当前任务只在有事实说明它此刻做什么时才填（工单 #1230）：现在系统里还没有这样的事实
        # （一个部门只有一个角色，没有哪一项记录写着它此刻手上的事），所以这一栏是空，
        # 事项标题只留在房间屏幕的目标行（上面的 crt.target），不再借过来当角色的任务
        roles=[RoomRole(id=role_id, name=role_name, kind=role_kind, status=role_status, task=None)],
        existing_read=bool(item is not None and item.kind == "onboarding"),
        pose=pose,
        door=_room_door(run, status),
        hold_card=None,
        pending_tool=None,
        mailbox=sum(1 for value in guidance if value.status == "received"),
        summaries=summaries,
        scrolls=scrolls,
        pinned_notes=sum(1 for value in guidance if value.status in ROOM_PINNED_GUIDANCE),
        semantic_cards=0,
        machine=None,
        remote_unknown=False,
        waiting_provider=waiting_provider,
        pipes=RoomPipes(
            out="stopped" if status == "interrupted" or waiting_provider
            else "flowing" if status == "working" else "idle",
            letters_waiting=letters_waiting,
        ),
        trial=None,
        tool_panel=None,
        self_test=None,
    )

def _department_label(department: str) -> str:
    return {"product": "产品", "engineering": "工程", "quality": "质检", "operations": "运维"}.get(
        department, department)


def _department_workspace(application: Application, request: DepartmentWorkspace
                          ) -> Snapshot[DepartmentWorkspaceResult]:
    store = application.system.store
    state = _project(application, request.project_id, include_history=False)
    item = None if request.work_item is None else _work_item(state, request.work_item)
    # 事项没有给出时没有 run，也没有部门状态；给出时一次读出 run、决定请求与事件（工单 #903）
    run, decisions, events = (None, {}, []) if item is None else _item_sources(application, item.run_id)
    observation = _observation(run, decisions, events)
    progress = _work_item_progress(run)
    configured = state.department_settings[request.department]
    used_version = _last_used_prompt_version(run, request.department)
    effective = _effective_model(application, configured, request.department)
    guidance = [
        GuidanceRecord(
            guidance_id=value.id, version=value.version, text=value.text, status=value.status,
            applied_activation_id=value.applied_activation_id,
            answered_activation_id=value.answered_activation_id, outcome=value.outcome,
            created_event_id=value.created_event_id,
        )
        for value in ([] if run is None else run.department_guidance)
        if value.department == request.department
    ]
    messages = [] if item is None else _department_messages(application, item.run_id, request.department)
    context = {} if run is None else {
        "manifests": [manifest.__dict__ for manifest in run.manifests],
        "compactions": list(run.compactions),
    }
    return Snapshot[DepartmentWorkspaceResult](
        position=store.end_position(),
        data=DepartmentWorkspaceResult(
            project_id=state.project_id, department=request.department,
            work_item_id=None if item is None else item.work_item_id,
            run_id=None if run is None else run.run_id, run_status=None if run is None else run.status,
            departments=_departments(run, progress, observation, decisions),
            status=None if item is None else item.status,
            stop_reason=None if run is None else run.stop_reason,
            active=False if run is None else run.active_department == request.department,
            department_setting=DepartmentSettingState(
                department=request.department, configured_version=configured.version,
                configured_text=configured.text, source=configured.source,
                department_setting_configured=configured.configured_prompt,
                used_version=used_version,
                used_event_id=None if configured.event_id is None else configured.event_id,
            ),
            setting=DepartmentSetting(
                department=request.department, version=configured.version, text=configured.text,
                source=configured.source, provider_id=configured.provider_id,
                model_id=configured.model_id, requested_tier=configured.requested_tier,
                department_setting_configured=configured.configured_prompt),
            effective=effective,
            guidance=guidance, messages=messages, context=context,
            last_call=_last_call(run, request.department),
            # 当前生效模型不具备本部门建议能力时的提醒（设计说明第 5.6 节「部门工作间」）
            reminders=application.system.facade.model_reminders(effective.model_id, request.department),
            room=_room_view(application, state, item, run, request.department, guidance, effective, observation),
        ),
    )


MESSAGE_TYPES = (EventType.USER_INPUT_RECEIVED, EventType.DEPARTMENT_INPUT, EventType.MODEL_MESSAGE,
                 EventType.DEPARTMENT_GUIDANCE_RECEIVED)
MESSAGE_LIMIT = 100
# 部门消息的正文长度上限：太长时给一段，长文本由用户点时间打开原始事件看（工单 #670）
MESSAGE_TEXT_LIMIT = 200
DISCARDED_ATTEMPT_STATUSES = ("failed", "cancelled")


def _department_messages(application: Application, run_id: str, department: str) -> list[dict[str, Any]]:
    # 部门消息：用户输入与这个部门的事件，按日志位置排列，取最近的一批。读取走部门与位置的索引。
    # 失败与取消的尝试只有观察记录，其模型消息不进入部门上下文；它们仍由观测页的
    # project.attempts 与 run.attempt 给出。
    store = application.system.store
    discarded_attempts = _discarded_attempts(application, run_id)
    collected: list[Any] = []
    cursor = 0
    while True:
        batch = store.read(after=cursor, runs=(run_id,), departments=(department,), limit=200,
                           types=MESSAGE_TYPES)
        if not batch:
            break
        collected.extend(batch)
        cursor = batch[-1].position
    kept = [event for event in collected
            if not (event.type == EventType.MODEL_MESSAGE
                    and event.payload.get("attempt_id") in discarded_attempts)]
    return [
        {
            "event_id": event.event_id, "position": event.position, "seq": event.stream_version,
            "type": event.type, "department": event.department, "created_at": event.created_at,
            "text": _message_text(application, run_id, event),
        }
        for event in kept[-MESSAGE_LIMIT:]
    ]


def _message_text(application: Application, run_id: str, event: Any) -> str:
    # 一条部门消息的文字（工单 #670）：载荷里的正文优先；
    # 这两类事件的正文在工件里（department_input 的 input_ref、model_message 的 message_ref），
    # 按引用取工件给一段摘要，取不到就留空由界面说清去哪里看。
    payload = event.payload
    text = payload.get("text") or payload.get("summary") or ""
    if isinstance(text, str) and text != "":
        return _truncate(text)
    for key in ("message_ref", "input_ref"):
        ref = payload.get(key)
        if not isinstance(ref, dict):
            continue
        try:
            raw = application.system.artifacts.get_for_run(run_id, ArtifactRef(**ref))
        except (FileNotFoundError, KeyError, TypeError, ValueError):
            continue
        try:
            item = json.loads(raw)
        except (TypeError, ValueError):
            return raw.decode("utf-8", errors="replace")
        summary = _item_summary(item)
        if summary != "":
            return _truncate(summary)
    return ""


def _truncate(text: str) -> str:
    # 正文太长时给一段，长文本由用户点时间打开原始事件看（工单 #670）
    if len(text) <= MESSAGE_TEXT_LIMIT:
        return text
    return text[:MESSAGE_TEXT_LIMIT] + "…"

def _item_summary(item: Any) -> str:
    # 工件里的一条内容：给一段能看懂的摘要（工单 #670）
    if isinstance(item, str):
        return item
    if isinstance(item, list):
        parts = [_item_summary(entry) for entry in item]
        return "；".join(part for part in parts if part != "")
    if not isinstance(item, dict):
        return ""
    for key in ("text", "content", "summary"):
        value = item.get(key)
        if isinstance(value, str) and value != "":
            return value
        if isinstance(value, list):
            parts = [_item_summary(entry) for entry in value]
            joined = "；".join(part for part in parts if part != "")
            if joined != "":
                return joined
    name = item.get("name")
    if isinstance(name, str) and name != "":
        arguments = item.get("arguments")
        detail = json.dumps(arguments, ensure_ascii=False) if arguments else ""
        return f"调用工具 {name}" + (f"：{detail}" if detail != "" else "")
    return ""


def _discarded_attempts(application: Application, run_id: str) -> set[str]:
    # 失败与取消的调用尝试：按事件日志里的尝试记录核对状态，读取走应用层的调用尝试表
    _position, rows = _read_models(application).attempts(run_id=run_id)
    return {row["attempt_id"] for row in rows if row["status"] in DISCARDED_ATTEMPT_STATUSES}


def _last_used_prompt_version(run: Any, department: str) -> int | None:
    # run 内实际采用的部门 Prompt 版本：该部门最近一次模型请求事件记录的 prompt_version
    if run is None:
        return None
    entry = next((item for item in reversed(run.model_requests) if item.get("department") == department), None)
    if entry is None:
        return None
    version = entry.get("prompt_version")
    return version if isinstance(version, int) else None

def _last_call(run: Any, department: str) -> dict[str, Any] | None:
    if run is None:
        return None
    entry = next((item for item in reversed(run.model_requests) if item.get("department") == department), None)
    if entry is None:
        return None
    return {
        key: entry.get(key) for key in (
            "activation_id", "step_id", "attempt", "requested_provider", "requested_model",
            "actual_provider", "actual_model", "requested_protocol", "snapshot_id", "prompt_version",
            "selection_source", "requested_tier", "sent_tier",
            "input_version", "event_id",
        )
    }


# ---------------------------------------------------------------------------
# run.actions


class RunActions(Contract):
    run_id: str


class ActionReceipt(Contract):
    args: dict[str, Any]
    ok: bool
    error: str | None
    output_ref: dict[str, Any] | None
    event_id: str
    created_at: str


class ActionView(Contract):
    action_id: str
    tool: str
    department: str | None
    status: Literal["running", "completed", "failed", "unknown"]
    activation_id: str | None
    step_id: int | None
    input_version: int | None
    prompt_version: int | None
    created_at: str
    receipt: ActionReceipt | None
    before_snapshot_ref: dict[str, Any] | None = None
    after_snapshot_ref: dict[str, Any] | None = None

class BackgroundCommandView(Contract):
    command: str
    started_at: str
    status: Literal["running", "ended"]


class RunActionsResult(Contract):
    actions: list[ActionView]
    background_commands: list[BackgroundCommandView]

def _run_actions(application: Application, request: RunActions) -> Snapshot[RunActionsResult]:
    store = application.system.store
    _run(application, request.run_id)
    events = _tool_events(store, request.run_id)
    actions: list[ActionView] = []
    started: dict[tuple[str, int | None, str], Any] = {}
    background_commands: list[BackgroundCommandView] = []
    jobs_table = None
    orchestrator = getattr(application.system, "orchestrator", None)
    if orchestrator is not None:
        sessions = getattr(orchestrator, "sessions", None)
        if sessions is not None:
            jobs_table = getattr(sessions, "jobs", None)
    for event in events:
        payload = event.payload or {}
        if event.type not in (EventType.TOOL_STARTED, EventType.TOOL_CALLED, EventType.TOOL_SKIPPED,
                              EventType.ACTION_VERIFIED):
            continue
        if payload.get("name") == "provider_usage":
            continue
        identity = action_identity(event)
        if event.type == EventType.TOOL_STARTED:
            started[identity] = event
            continue
        started_event = started.pop(identity, None)
        actions.append(_action_view(event, identity, started_event))
        if event.type == EventType.TOOL_CALLED and payload.get("name") == "bash":
            started_payload = {} if started_event is None else (started_event.payload or {})
            args = dict(payload.get("args") or started_payload.get("args") or {})
            if args.get("background") is True and payload.get("ok"):
                job_id = None
                output_ref = payload.get("output_ref")
                if output_ref:
                    try:
                        raw = application.system.artifacts.get_for_run(request.run_id, ArtifactRef(**output_ref))
                        output_data = json.loads(raw)
                        if isinstance(output_data, dict):
                            job_id = output_data.get("job_id")
                    except Exception:
                        job_id = None
                status: Literal["running", "ended"] = "ended"
                if job_id and jobs_table is not None:
                    if jobs_table.get_status(job_id) == "running":
                        status = "running"
                started_at = started_event.created_at if started_event is not None else event.created_at
                background_commands.append(BackgroundCommandView(
                    command=str(args.get("command") or ""),
                    started_at=started_at,
                    status=status,
                ))
    # 有 tool_started、还没有结果的动作用运行状态区分（工单 #17，恢复契约第 1 节）：这次激活仍在进行
    # 的时候是运行中，否则是结果未知，等待核实
    live = _live_activations(events)
    for identity, event in started.items():
        actions.append(_action_view(None, identity, event, live=identity[0] in live))
    actions.sort(key=lambda item: item.created_at)
    background_commands.sort(key=lambda item: item.started_at)
    return Snapshot[RunActionsResult](
        position=store.end_position(),
        data=RunActionsResult(actions=actions, background_commands=background_commands),
    )


def _live_activations(events: list[Any]) -> set[str]:
    # 仍在进行、还没有 activation_finished 的激活（工单 #17）：DEPARTMENT_ACTIVATED 开启，ACTIVATION_FINISHED 结束
    open_activations: set[str] = set()
    for event in events:
        payload = event.payload or {}
        if event.type == EventType.DEPARTMENT_ACTIVATED and payload.get("activation_id"):
            open_activations.add(str(payload["activation_id"]))
        elif event.type == EventType.ACTIVATION_FINISHED and payload.get("activation_id"):
            open_activations.discard(str(payload["activation_id"]))
    return open_activations

def _tool_events(store: Any, run_id: str) -> list[Any]:
    # 一个 run 的工具事件：按位置反复读取到没有为止（按 run 与位置的索引，不是整个日志的扫描）
    collected: list[Any] = []
    cursor = 0
    while True:
        batch = store.read(after=cursor, runs=(run_id,), limit=500,
                           types=(EventType.TOOL_STARTED, EventType.TOOL_CALLED, EventType.TOOL_SKIPPED,
                                  EventType.ACTION_VERIFIED, EventType.DEPARTMENT_ACTIVATED,
                                  EventType.ACTIVATION_FINISHED))
        if not batch:
            break
        collected.extend(batch)
        cursor = batch[-1].position
    return collected


def _action_view(result_event: Any | None, identity: tuple[str, int | None, str],
                 started_event: Any | None, *, live: bool = False) -> ActionView:
    # 一个动作的读取视图（工单 #17）：状态、回执，以及动作前后的快照引用（动作前取自 tool_started，
    # 动作后取自 tool_called）。result_event 为空表示只有 tool_started、还没有结果。
    action_id = identity[2]
    if result_event is None:
        payload = {} if started_event is None else (started_event.payload or {})
        return ActionView(
            action_id=action_id, tool=str(payload.get("name") or ""),
            department=None if started_event is None else started_event.department,
            status=("running" if live else "unknown"),
            activation_id=payload.get("activation_id"), step_id=payload.get("step_id"),
            input_version=payload.get("input_version"), prompt_version=payload.get("prompt_version"),
            created_at="" if started_event is None else started_event.created_at, receipt=None,
            before_snapshot_ref=payload.get("before_snapshot_ref"),
        )
    payload = result_event.payload or {}
    if result_event.type == EventType.ACTION_VERIFIED:
        resolution = payload.get("resolution")
        started_payload = {} if started_event is None else (started_event.payload or {})
        return ActionView(
            action_id=action_id, tool=str(payload.get("name") or started_payload.get("name") or ""),
            department=result_event.department,
            status="unknown" if resolution == "handed_back" else "completed",
            activation_id=payload.get("activation_id"), step_id=payload.get("step_id"),
            input_version=payload.get("input_version"), prompt_version=payload.get("prompt_version"),
            created_at=result_event.created_at, receipt=None,
            before_snapshot_ref=started_payload.get("before_snapshot_ref"),
        )
    ok = bool(payload.get("ok"))
    started_payload = {} if started_event is None else (started_event.payload or {})
    return ActionView(
        action_id=action_id, tool=str(payload.get("name") or started_payload.get("name") or ""),
        department=result_event.department,
        status="completed" if ok else "failed",
        activation_id=payload.get("activation_id"), step_id=payload.get("step_id"),
        input_version=payload.get("input_version"), prompt_version=payload.get("prompt_version"),
        created_at=result_event.created_at,
        receipt=ActionReceipt(
            args=redact_tool_args(dict(payload.get("args") or started_payload.get("args") or {})),
            ok=ok, error=payload.get("error"),
            output_ref=payload.get("output_ref"), event_id=result_event.event_id,
            created_at=result_event.created_at,
        ),
        before_snapshot_ref=started_payload.get("before_snapshot_ref"),
        after_snapshot_ref=payload.get("after_snapshot_ref"),

    )


# ---------------------------------------------------------------------------
# run.asks


class RunAsks(Contract):
    run_id: str


class AskView(Contract):
    # 一次询问（三部门的循环结构第 4.7 节）：提问方、被询问的部门、问题、状态与回答。
    # 工单 #903 补上询问的编号（分支会话）、上一层询问、询问链与层数、产品的回答附带的 PRD 修订号与起止时间
    id: str
    requester: str
    recipient: str
    question: str
    status: Literal["进行中", "已回答", "没能回答"]
    answer: str | None = None
    reason: str | None = None
    # 上一层询问的编号：这次询问是在另一次询问的分支里发出的时候（回问）有值
    parent: str | None = None
    # 询问链：从最外层的提问方起经过的部门，例如 engineering → product → engineering
    chain: list[str]
    # 询问链上的询问数：最外层为 1
    depth: int
    # 产品的回答附带 PRD 新版本时的修订号
    prd_revision: int | None = None
    start_position: int
    end_position: int | None = None
    started_at: str
    ended_at: str | None = None


class RunAsksResult(Contract):
    asks: list[AskView]


def _run_asks(application: Application, request: RunAsks) -> Snapshot[RunAsksResult]:
    store = application.system.store
    _run(application, request.run_id)
    events = store.list_events(request.run_id)
    # 已经结束的询问按分支会话找它的回答事件；还没回答的没有这一条
    answers: dict[str, Any] = {}
    for event in events:
        if event.type == EventType.ASK_ANSWERED:
            answers.setdefault(event.session_id, event)
    # 开过询问的会话：一次询问的编号就是它的分支会话。询问链上的上一层由此找到（工单 #903）
    opened: dict[str, AskView] = {}
    asks: list[AskView] = []
    for event in events:
        if event.type != EventType.ASK_STARTED:
            continue
        payload = event.payload or {}
        branch_session_id = payload.get("branch_session_id") or ""
        # ask_started 所在的会话是另一次询问的分支会话时，那次询问就是这一层的上一层（回问）
        above = opened.get(event.session_id)
        chain = [*(above.chain if above is not None else []), payload.get("requester") or ""]
        answer_event = answers.get(branch_session_id)
        prd_revision = None
        if answer_event is not None:
            ans_payload = answer_event.payload or {}
            if ans_payload.get("status") == "answered":
                status: Literal["进行中", "已回答", "没能回答"] = "已回答"
                answer = ans_payload.get("answer")
                reason = None
                prd_revision = ans_payload.get("revision")
            else:
                status = "没能回答"
                answer = None
                reason = ans_payload.get("reason")
            end_position = answer_event.position
            ended_at = answer_event.created_at
        else:
            status = "进行中"
            answer = None
            reason = None
            end_position = None
            ended_at = None
        ask = AskView(
            id=branch_session_id,
            requester=payload.get("requester") or "",
            recipient=payload.get("recipient") or "",
            question=payload.get("question") or "",
            status=status,
            answer=answer,
            reason=reason,
            parent=None if above is None else above.id,
            chain=chain,
            depth=len(chain),
            prd_revision=prd_revision,
            start_position=event.position,
            end_position=end_position,
            started_at=event.created_at,
            ended_at=ended_at,
        )
        opened[branch_session_id] = ask
        asks.append(ask)
    return Snapshot[RunAsksResult](
        position=store.end_position(),
        data=RunAsksResult(asks=asks),
    )

# ---------------------------------------------------------------------------
# work_item.materials


class WorkItemMaterials(Contract):
    project_id: str
    work_item: str


class VersionEntry(Contract):
    event_id: str
    kind: str
    status: str
    revision: int | None
    content_hash: str | None
    summary: str | None
    files: list[str]


class ReviewEntry(Contract):
    event_id: str
    verdict: str
    rationale: str
    defects: list[dict[str, Any]]
    checks: list[dict[str, Any]]


class BaselineReviewView(Contract):
    # 某一轮基线核验的内容：逐条结论、遗漏的能力、基线检查与其他失败
    event_id: str
    content_hash: str
    conclusions: list[BaselineConclusion]
    omissions: list[BaselineOmission]
    checks: list[BaselineCheck]
    other_failures: list[BaselineOtherFailure]


class OnboardingDecisionRecord(Contract):
    # 某一轮的确认记录（工单 #136，设计第 4.7 节）：回答与撤销各自一条；请求本身仍是打开的不列在这里
    event_id: str
    decision_id: str
    outcome: Literal["answered", "withdrawn"]
    option: str | None
    note: str | None
    reason: str | None
    decided_at: str


class OnboardingRound(Contract):
    # 一次建档候选（工单 #136，设计第 3.3、4.7 节）：轮次、这一轮 run、候选事件与提出时间，
    # 三份产物与仓库概况的原文、上一轮的修改意见原文、基线核验与这一轮的决定记录。
    # 工件按候选自己的 run 目录存放；提出修改以后开始的修改轮才有修改意见
    round: int
    run_id: str
    candidate_event_id: str
    proposed_at: str
    prd: str
    structure: str
    overview: str
    revision_note: str | None
    baseline_review: BaselineReviewView
    decisions: list[OnboardingDecisionRecord]


class ProjectMaterial(Contract):
    material_id: str
    text: str
    department: str | None
    recorded_at: str
    event_id: str


class OldRunEvent(Contract):
    # 旧 run 的一条事件（只读列表，工单 #1186）：时间与说明。页面上不写事件种类与编号
    position: int
    at: str
    label: str


class OldRunView(Contract):
    # 旧版本的 run（工单 #1186）：这个事项因升级停止的 run，只读列出。事件版本是它创建时记下的
    # run 事件版本；状态与停止原因来自它自己的投影；事件供恢复页显示「因升级停止」时照实列出，不改写
    run_id: str
    run_event_version: int
    state: str
    stop_reason: str | None
    events: list[OldRunEvent]


class WorkItemMaterialsResult(Contract):
    work_item_id: str
    run_id: str
    contracts: list[VersionEntry]
    deliveries: list[VersionEntry]
    reviews: list[ReviewEntry]
    inputs: list[InputView]
    materials: list[ProjectMaterial]
    # 建档各轮的材料（工单 #136，设计第 3.4 节）：按提出顺序列出这个建档事项的每一次候选与确认记录；
    # 普通事项没有建档候选，为空
    onboarding_rounds: list[OnboardingRound]
    # 旧版本的 run（工单 #1186）：因升级停止的 run 与它的事件，只读；没有时为空
    old_runs: list[OldRunView]


def _work_item_materials(application: Application, request: WorkItemMaterials
                         ) -> Snapshot[WorkItemMaterialsResult]:
    store = application.system.store
    state = _project(application, request.project_id, include_history=False)
    item = _work_item(state, request.work_item)
    run = _run(application, item.run_id)
    versions = {entry["event_id"]: entry for entry in run.git_versions}
    # PRD 各版显示真实状态（工单 #654、#683）与一句摘要（工单 #668）：
    # 每一版 PRD 在投影里有自己的内容与摘要。
    specs = {spec.content_hash: spec for spec in run.product_specs}
    # 有效合同按它是不是当前有效的那一版标状态（工单 #683）：「产品决定修订 PRD」产生的新合同
    # 沿用同一条产品需求，按那条需求的状态会让两版都是 active
    current_contract = None if run.effective_contract is None else run.effective_contract.content_hash
    return Snapshot[WorkItemMaterialsResult](
        position=store.end_position(),
        data=WorkItemMaterialsResult(
            work_item_id=item.work_item_id, run_id=run.run_id,
            contracts=[_version_entry(value.created_event_id, "contract",
                                      "active" if value.content_hash == current_contract else "superseded",
                                      value.revision, value.content_hash,
                                      _prd_summary(specs.get(value.product_spec_hash)), [])
                       for value in run.effective_contracts],
            deliveries=[_version_entry(value.created_event_id, "delivery", value.status, value.revision,
                                       value.content_hash, value.summary, list(value.files))
                        for value in run.delivery_specs],
            reviews=[ReviewEntry(event_id=value.created_event_id, verdict=value.verdict,
                                 rationale=value.rationale,
                                 defects=[defect.__dict__ for defect in value.defects],
                                 checks=list(value.checks)) for value in run.reviews],
            inputs=[
                InputView(
                    input_id=value.id, version=value.version, text=value.text, kind=value.kind,
                    byte_start=value.byte_start, byte_end=value.byte_end,
                    created_event_id=value.created_event_id,
                    git_version=_git_version_of(versions, value.created_event_id),
                )
                for value in run.inputs
            ],
            materials=[
                ProjectMaterial(material_id=value.material_id, text=value.text, department=value.department,
                                recorded_at=value.recorded_at, event_id=value.event_id)
                for value in state.materials
            ],
            onboarding_rounds=_onboarding_rounds(application, state, item.work_item_id),
            old_runs=_old_runs(application, state, item.work_item_id),
        ),
    )

def _old_runs(application: Application, state: Any, work_item_id: str) -> list[OldRunView]:
    # 旧版本的 run（工单 #1186）：这个事项因升级停止的 run，只读列出。建档事项因升级重新开始时
    # 同一个事项编号会再登记一条 work_item_created（新 run 在新的一条记录上），普通事项另开一个新事项；
    # 两种都按事项编号收集，旧 run 的事件照实列出，供恢复页显示「因升级停止」时查看
    store = application.system.store
    views: list[OldRunView] = []
    for entry in state.work_items:
        if entry.work_item_id != work_item_id:
            continue
        run = _optional_run(application, entry.run_id)
        if run is None or run.stop_reason != STOP_REASON_UPGRADE:
            continue
        events = store.list_events(run.run_id)
        views.append(OldRunView(
            run_id=run.run_id, run_event_version=run.run_event_version,
            state=observation_state([], [], status=run.status, stop_reason=run.stop_reason),
            stop_reason=run.stop_reason,
            events=[OldRunEvent(position=event.position, at=event.created_at,
                                label=event_label(event.type, event.payload or {})) for event in events],
        ))
    return views

def _onboarding_rounds(application: Application, state: Any,
                       work_item_id: str) -> list[OnboardingRound]:
    # 建档各轮的材料（工单 #136，设计第 3.3、4.7 节）：按提出顺序读项目投影里的候选，
    # 工件按候选自己的 run 目录取得（每一轮的 run 各有目录），确认记录从项目流中回答与撤销的事件读出
    candidates = [value for value in state.initial_prd_candidates if value.work_item_id == work_item_id]
    decided = _onboarding_decision_records(application, state.project_id, work_item_id)
    rounds: list[OnboardingRound] = []
    for candidate in candidates:
        review = candidate.baseline_review
        rounds.append(OnboardingRound(
            round=candidate.round, run_id=candidate.run_id, candidate_event_id=candidate.event_id,
            proposed_at=candidate.proposed_at,
            prd=_artifact_text(application, candidate.run_id, candidate.prd["prd_ref"]),
            structure=_artifact_text(application, candidate.run_id, candidate.structure["structure_ref"]),
            overview=_artifact_text(application, candidate.run_id, candidate.overview_ref),
            revision_note=None if candidate.revision_note_ref is None else
            _artifact_text(application, candidate.run_id, candidate.revision_note_ref),
            baseline_review=BaselineReviewView(
                event_id=review["event_id"], content_hash=review["content_hash"],
                conclusions=[BaselineConclusion(**item) for item in review["conclusions"]],
                omissions=[BaselineOmission(**item) for item in review["omissions"]],
                checks=[BaselineCheck(**item) for item in review["checks"]],
                other_failures=[BaselineOtherFailure(**item) for item in review["other_failures"]],
            ),
            decisions=decided.get(candidate.event_id, []),
        ))
    return rounds


def _onboarding_decision_records(application: Application, project_id: str,
                                 work_item_id: str) -> dict[str, list[OnboardingDecisionRecord]]:
    # 每个建档候选的确认记录（工单 #136，设计第 4.7 节）：项目流中回答与撤销的事件所属的请求
    # 记着提出它的那一轮 run，按它归到对应的候选；没有 run 的事件取它之前最近提出的一轮
    events = application.system.store.list_project_events(project_id)
    proposed = [(event.payload["run_id"], event.event_id, event.created_at) for event in events
                if event.type == ProjectEventType.INITIAL_PRD_PROPOSED
                and event.payload["work_item_id"] == work_item_id]
    records: dict[str, list[OnboardingDecisionRecord]] = {}
    for event in events:
        if event.payload.get("work_item_id") != work_item_id:
            continue
        if event.type == ProjectEventType.PROJECT_DECISION_ANSWERED:
            entry = OnboardingDecisionRecord(
                event_id=event.event_id, decision_id=event.payload["decision_id"], outcome="answered",
                option=event.payload["option"], note=event.payload["note"], reason=None,
                decided_at=event.created_at,
            )
        elif event.type == ProjectEventType.PROJECT_DECISION_WITHDRAWN:
            entry = OnboardingDecisionRecord(
                event_id=event.event_id, decision_id=event.payload["decision_id"], outcome="withdrawn",
                option=None, note=None, reason=event.payload["reason"], decided_at=event.created_at,
            )
        else:
            continue
        candidate_id = _candidate_of(proposed, event.payload.get("run_id"), event.created_at)
        if candidate_id is not None:
            records.setdefault(candidate_id, []).append(entry)
    return records


def _candidate_of(proposed: list[tuple[str, str, str]], run_id: str | None,
                  at: str) -> str | None:
    for proposed_run, candidate_id, _proposed_at in proposed:
        if proposed_run == run_id:
            return candidate_id
    earlier = [candidate_id for proposed_run, candidate_id, proposed_at in proposed if proposed_at <= at]
    return earlier[-1] if earlier else None


def _artifact_text(application: Application, run_id: str, ref: dict[str, Any]) -> str:
    try:
        return application.system.artifacts.get_for_run(run_id, ArtifactRef(**ref)).decode("utf-8")
    except (FileNotFoundError, KeyError):
        return f"（工件已不在工件存储中：{ref.get('path')}）"


def _prd_summary(spec: Any) -> str | None:
    # 有效合同对应的那一版 PRD 的摘要（工单 #668）：目标是哪件事、要求与边界各有几条。
    # 与建档候选的 PRD 摘要同一套说法（harness/projects.py 的 prd_summary）。
    if spec is None:
        return None
    return f"目标：{spec.goal}；要求 {len(spec.requirements)} 条；边界 {len(spec.boundaries)} 条"


def _version_entry(event_id: str, kind: str, status: str, revision: int, content_hash: str,
                   summary: str | None, files: list[str]) -> VersionEntry:
    return VersionEntry(event_id=event_id, kind=kind, status=status, revision=revision,
                        content_hash=content_hash, summary=summary, files=files)


# ---------------------------------------------------------------------------
# delivery.file


class DeliveryFile(Contract):
    event_id: str
    path: Text


class DeliveryFileResult(Contract):
    path: str
    content: str | None
    base64: str | None
    content_hash: str


def _delivery_file(application: Application, request: DeliveryFile) -> Snapshot[DeliveryFileResult]:
    store = application.system.store
    event = store.get_event(request.event_id)
    if event is None or event.type != EventType.DELIVERY_ACCEPTED:
        raise NotFound(f"delivery not found: {request.event_id}")
    tree, _archive = _delivery_archive(application, event)
    item = next((entry for entry in tree.files if entry.path == request.path), None)
    if item is None:
        raise NotFound(f"archived file not found: {request.path}")
    try:
        content = item.data.decode("utf-8")
        encoded = None
    except UnicodeDecodeError:
        content = None
        encoded = base64.b64encode(item.data).decode("ascii")
    return Snapshot[DeliveryFileResult](
        position=event.position,
        data=DeliveryFileResult(path=item.path, content=content, base64=encoded,
                                content_hash=hash_bytes(item.data)),
    )


# ---------------------------------------------------------------------------
# project.attempts 与 project.usage


class ProjectAttempts(Contract):
    project_id: str
    work_item: str | None = None
    department: Department | None = None
    status: AttemptStatus | None = None
    provider: str | None = None
    requested_model: str | None = None
    actual_model: str | None = None
    q: str | None = None
    cursor: str | None = None
    limit: int = Field(default=100, ge=1, le=200)

    @field_validator("cursor")
    @classmethod
    def _cursor_is_a_page_and_a_record(cls, value: str | None) -> str | None:
        # 游标是「第一页位置:记录位置:记录标识」；格式不对时按合同拒绝，不在查询里抛错
        if value not in (None, "") and CURSOR_PATTERN.match(value) is None:
            raise ValueError("cursor must be '<page position>:<record position>:<record id>'")
        return value


class AttemptView(Contract):
    attempt_id: str
    run_id: str
    work_item_id: str | None
    department: str | None
    status: str
    stage: str | None
    purpose: str | None
    prompt_version: int | None
    requested_provider: str | None
    requested_model: str | None
    actual_provider: str | None
    actual_model: str | None
    started_at: str | None
    finished_at: str | None
    duration_ms: int | None
    usage: dict[str, Any]
    position: int


class ProjectAttemptsResult(Contract):
    attempts: list[AttemptView]
    cursor: str | None


def _project_attempts(application: Application, request: ProjectAttempts) -> Snapshot[ProjectAttemptsResult]:
    state = _project(application, request.project_id, include_history=False)
    if request.work_item is not None:
        _work_item(state, request.work_item)
    read_models = _read_models(application)
    page_position, last_position, last_id = _decode_cursor(request.cursor)
    position, rows = read_models.attempts_page(
        through=page_position, after=last_position, after_id=last_id, limit=request.limit,
        project_id=request.project_id, work_item_id=request.work_item, department=request.department,
        status=request.status, provider=request.provider, requested_model=request.requested_model,
        actual_model=request.actual_model, q=request.q,
    )
    attempts = [_attempt_view(row) for row in rows]
    cursor = None
    if len(attempts) == request.limit and attempts:
        first_page = position if page_position is None else page_position
        cursor = _encode_cursor(first_page, attempts[-1].position, attempts[-1].attempt_id)
    return Snapshot[ProjectAttemptsResult](
        position=position,
        data=ProjectAttemptsResult(attempts=attempts, cursor=cursor),
    )


def _encode_cursor(page_position: int, position: int, attempt_id: str) -> str:
    return f"{page_position}:{position}:{attempt_id}"


def _decode_cursor(cursor: str | None) -> tuple[int | None, int, str]:
    # 格式由合同校验：第一页位置、最后一条记录的位置与标识
    if cursor in (None, ""):
        return None, -1, ""
    page, position, attempt_id = cursor.split(":", 2)
    return int(page), int(position), attempt_id


def _attempt_view(row: Any) -> AttemptView:
    record = json.loads(row["record"])
    return AttemptView(
        attempt_id=row["attempt_id"], run_id=row["run_id"], work_item_id=row["work_item_id"],
        department=row["department"], status=row["status"], stage=record.get("stage"),
        purpose=row["purpose"], prompt_version=record.get("prompt_version"),
        requested_provider=row["requested_provider"], requested_model=row["requested_model"],
        actual_provider=row["actual_provider"], actual_model=row["actual_model"],
        started_at=record.get("started_at"), finished_at=record.get("finished_at"),
        duration_ms=record.get("duration_ms"), usage=record.get("usage") or {}, position=row["position"],
    )


class ProjectUsage(Contract):
    project_id: str
    work_item: str | None = None
    department: Department | None = None
    status: AttemptStatus | None = None
    provider: str | None = None
    requested_model: str | None = None
    actual_model: str | None = None
    q: str | None = None


class UsageTotals(Contract):
    attempts: int
    reported: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    total_tokens: int | None = None
    cost: float | None = None
    latency_ms: int | None = None


class UsageGroup(UsageTotals):
    key: str
    label: str


class UsageReport(Contract):
    totals: UsageTotals
    departments: list[UsageGroup]
    models: list[UsageGroup]


def _project_usage(application: Application, request: ProjectUsage) -> Snapshot[UsageReport]:
    state = _project(application, request.project_id, include_history=False)
    if request.work_item is not None:
        _work_item(state, request.work_item)
    read_models = _read_models(application)
    position, rows = read_models.attempts(
        project_id=request.project_id, work_item_id=request.work_item, department=request.department,
        status=request.status, provider=request.provider, requested_model=request.requested_model,
        actual_model=request.actual_model, q=request.q,
    )
    return Snapshot[UsageReport](position=position, data=_usage_report(rows))


def _usage_report(rows: list[Any]) -> UsageReport:
    # 用量汇总：按部门与模型分组；未上报的项为空（None）
    by_department: dict[str, list[Any]] = {}
    by_model: dict[str, list[Any]] = {}
    for row in rows:
        by_department.setdefault(row["department"] or "未知部门", []).append(row)
        by_model.setdefault(
            f"{row['actual_provider'] or row['requested_provider'] or '未知 Provider'} · "
            f"{row['actual_model'] or row['requested_model'] or '未知模型'}", [],
        ).append(row)
    return UsageReport(
        totals=_usage_totals(rows),
        departments=[UsageGroup(key=key, label=key, **_usage_totals(items).model_dump())
                     for key, items in by_department.items()],
        models=[UsageGroup(key=key, label=key, **_usage_totals(items).model_dump())
                for key, items in by_model.items()],
    )


USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "total_tokens",
                "cost", "latency_ms")


def _usage_totals(rows: list[Any]) -> UsageTotals:
    # 用量汇总只累加上报的用量（source == "reported"），未上报的项为空（设计说明第 4.3 节）；
    # latency_ms 是本地测得的用时，与用量是否上报无关，按全部尝试累加
    values: dict[str, int | float | None] = {field: None for field in USAGE_FIELDS}
    reported = 0
    for row in rows:
        usage = json.loads(row["record"]).get("usage") or {}
        is_reported = usage.get("source") == "reported"
        if is_reported:
            reported += 1
        for field in USAGE_FIELDS:
            if field != "latency_ms" and not is_reported:
                continue
            value = usage.get(field)
            if value is None:
                continue
            values[field] = (values[field] or 0) + value
    return UsageTotals(attempts=len(rows), reported=reported, **values)


# ---------------------------------------------------------------------------
# run.attempt


class RunAttempt(Contract):
    run_id: str
    attempt_id: str


class RunAttemptResult(Contract):
    attempt: dict[str, Any]
    siblings: list[dict[str, Any]]
    context: dict[str, Any] | None
    request: Any
    response: Any
    events: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    artifact_refs: dict[str, Any]
    observed_scope: Any


def _run_attempt(application: Application, request: RunAttempt) -> Snapshot[RunAttemptResult]:
    store = application.system.store
    artifacts = application.system.artifacts
    _run(application, request.run_id)
    read_models = _read_models(application)
    position, rows = read_models.attempts(run_id=request.run_id)
    records = {row["attempt_id"]: json.loads(row["record"]) for row in rows}
    attempt = records.get(request.attempt_id)
    if attempt is None:
        raise NotFound(f"attempt not found: {request.attempt_id}")
    context_event_id = attempt.get("context_event_id")
    context_event = None if context_event_id is None else store.get_event(context_event_id)
    detail = ObservabilityQuery(store, artifacts).attempt_detail(request.run_id, attempt, records,
                                                                 context_event=context_event)
    return Snapshot[RunAttemptResult](
        position=position,
        data=RunAttemptResult(
            attempt=detail["attempt"], siblings=detail["siblings"], context=detail["context"],
            request=detail["request"], response=detail["response"], events=detail["events"],
            tools=detail["tools"], artifact_refs=detail["artifact_refs"],
            observed_scope=detail["observed_scope"],
        ),
    )


# ---------------------------------------------------------------------------
# project.settings


class ProjectSettings(Contract):
    project_id: str


class DepartmentSetting(Contract):
    # 项目部门设置：模型访问定义引用、请求档位与部门 Prompt 三项，都可以为空（未写入）；
    # 没有写入的项使用部门默认，部门 Prompt 没有写入时使用内置默认 Prompt
    department: str
    version: int
    text: str
    source: str
    provider_id: str | None = None
    model_id: str | None = None
    requested_tier: str | None = None
    department_setting_configured: bool = False


class SourceDirectorySetting(Contract):
    name: str
    path: str
    version: int
    writeback_enabled: bool = False
    remote: str = ""
    target_branch: str = ""
    check_commands: list[str] = []
    credential_ref: str | None = None

class ProjectSettingsResult(Contract):
    project_id: str
    name: str
    goal: str
    version: int
    pinned: bool
    archived: bool
    departments: dict[str, DepartmentSetting]
    source_directories: dict[str, SourceDirectorySetting]
    # 各部门生效模型不具备该部门建议能力时的提醒（设计说明第 5.6 节「一直显示」）；
    # 生效模型按第 5.3 节解析，包括跟随部门默认的情况
    department_reminders: dict[str, list[str]]


def _project_settings(application: Application, request: ProjectSettings) -> Snapshot[ProjectSettingsResult]:
    store = application.system.store
    state = _project(application, request.project_id, include_history=False)
    settings = {
        department: DepartmentSetting(
            department=department, version=state.department_settings[department].version,
            text=state.department_settings[department].text,
            source=state.department_settings[department].source,
            provider_id=state.department_settings[department].provider_id,
            model_id=state.department_settings[department].model_id,
            requested_tier=state.department_settings[department].requested_tier,
            department_setting_configured=state.department_settings[department].configured_prompt)
        for department in DEPARTMENTS
    }
    return Snapshot[ProjectSettingsResult](
        position=store.end_position(),
        data=ProjectSettingsResult(
            project_id=state.project_id, name=state.name, goal=state.goal, version=state.stream_version,
            pinned=state.pinned, archived=state.archived,
            departments=settings,
            source_directories={
                name: SourceDirectorySetting(
                    name=value.name, path=value.path, version=value.version,
                    writeback_enabled=getattr(value, "writeback_enabled", False),
                    remote=getattr(value, "remote", ""),
                    target_branch=getattr(value, "target_branch", ""),
                    check_commands=list(getattr(value, "check_commands", ())),
                    credential_ref=getattr(value, "credential_ref", None),
                )
                for name, value in state.source_directories.items()
            },
            # 各部门生效模型（跟随部门默认时取部门默认）的建议能力提醒（设计说明第 5.6 节）
            department_reminders=application.system.facade.project_department_reminders(
                {department: {"model_id": setting.model_id} for department, setting in settings.items()}),
        ),
    )


# ---------------------------------------------------------------------------
# project.writeback

class ProjectWriteback(Contract):
    project_id: str


class WritebackRecordView(Contract):
    # 一次写回的结果（工单 #709）：状态与停止原因、推送的分支、目标分支、合并请求、冲突的文件路径
    status: str
    work_item_id: str
    adoption_id: str
    reason: str | None = None
    branch: str | None = None
    target_branch: str | None = None
    pull_request_title: str | None = None
    # 合并请求还只是本地记录，没有在代码托管平台上创建（自举试点的已知边界）
    pull_request_local_only: bool = False
    target_commit: str
    final_tree_digest: str | None = None
    conflicts: list[str] = []
    created_at: str
    event_id: str


class ProjectWritebackResult(Contract):
    project_id: str
    # 最近的写回在前：界面显示最近一次的结果
    records: list[WritebackRecordView]


def _project_writeback(application: Application, request: ProjectWriteback) -> Snapshot[ProjectWritebackResult]:
    store = application.system.store
    state = _project(application, request.project_id, include_history=False)
    records: list[WritebackRecordView] = []
    for record in reversed(state.writebacks):
        pull_request = record.pull_request or {}
        records.append(WritebackRecordView(
            status=record.status, work_item_id=record.work_item_id, adoption_id=record.adoption_id,
            reason=record.reason, branch=record.branch,
            target_branch=pull_request.get("target_branch"),
            pull_request_title=pull_request.get("title"),
            pull_request_local_only=pull_request.get("status") == "local_test_boundary",
            target_commit=record.target_commit, final_tree_digest=record.final_tree_digest,
            conflicts=[str(item.get("path", "")) for item in record.conflicts],
            created_at=record.created_at, event_id=record.event_id,
        ))
    return Snapshot[ProjectWritebackResult](
        position=store.end_position(),
        data=ProjectWritebackResult(project_id=state.project_id, records=records),
    )


# ---------------------------------------------------------------------------
# run.export 与 replay.check


class RunExport(Contract):
    run_id: str


class RunExportResult(Contract):
    run_id: str
    projection: dict[str, Any]
    events: list[dict[str, Any]]
    attempts: list[dict[str, Any]]
    usage: dict[str, Any]


def _run_export(application: Application, request: RunExport) -> Snapshot[RunExportResult]:
    store = application.system.store
    run = _run(application, request.run_id)
    read_models = _read_models(application)
    position, attempts = read_models.attempts(run_id=request.run_id)
    return Snapshot[RunExportResult](
        position=min(store.end_position(), position),
        data=RunExportResult(
            run_id=run.run_id, projection=run.canonical_state(),
            events=[event.to_dict() for event in store.list_events(request.run_id)],
            attempts=[
                ObservabilityQuery.public_attempt(json.loads(row["record"]))
                for row in sorted(attempts, key=lambda item: (item["seq"], item["attempt_id"]))
            ],
            usage=_usage_report(attempts).model_dump(mode="json"),
        ),
    )


class ReplayCheck(Contract):
    run_id: str | None = None
    project_id: str | None = None


class ReplayCheckResult(Contract):
    target: Literal["run", "project"]
    consistent: bool
    differences: list[str]


def _replay_check(application: Application, request: ReplayCheck) -> Snapshot[ReplayCheckResult]:
    if (request.run_id is None) == (request.project_id is None):
        # 重放核对只有一个目标：两个都不给或两个都给是输入问题，接口层回 422（工单 #1218）
        raise QueryInputInvalid("replay.check takes exactly one of run_id or project_id")
    store = application.system.store
    if request.project_id is not None:
        saved = saved_project(store, request.project_id)
        if saved is None:
            raise NotFound(f"project not found: {request.project_id}")
        replayed = replay_project(store, request.project_id)
        differences = _state_differences(saved.canonical_state(), replayed.canonical_state())
        return Snapshot[ReplayCheckResult](
            position=store.end_position(),
            data=ReplayCheckResult(target="project", consistent=not differences, differences=differences),
        )
    run_id = request.run_id
    try:
        verify_replay(store, application.system.artifacts, application.system.git_versions, run_id)
    except RunNotFoundError:
        raise NotFound(f"run not found: {run_id}") from None
    except ReplayIntegrityError as exc:
        return Snapshot[ReplayCheckResult](
            position=store.end_position(),
            data=ReplayCheckResult(target="run", consistent=False, differences=[f"{exc.reason}: {exc}"]),
        )
    saved = store.projection(f"run:{run_id}")
    decisions = replay_decisions(store.list_events(run_id))
    if decisions != load_decisions(saved):
        return Snapshot[ReplayCheckResult](
            position=store.end_position(),
            data=ReplayCheckResult(target="run", consistent=False,
                                   differences=["decision requests differ from their replay"]),
        )
    return Snapshot[ReplayCheckResult](
        position=store.end_position(),
        data=ReplayCheckResult(target="run", consistent=True, differences=[]),
    )


def _state_differences(saved: dict[str, Any], replayed: dict[str, Any], path: str = "") -> list[str]:
    differences: list[str] = []
    if isinstance(saved, dict) and isinstance(replayed, dict):
        for key in sorted(set(saved) | set(replayed)):
            differences.extend(_state_differences(saved.get(key), replayed.get(key),
                                                  f"{path}.{key}" if path else str(key)))
    elif saved != replayed:
        differences.append(path or "<state>")
    return differences


# ---------------------------------------------------------------------------
# 辅助


def _read_models(application: Application) -> ReadModels:
    return application.read_models


def _snapshot_position(store: Any, through: int | None) -> int:
    # 快照的位置：回放时等于 at，否则是日志末尾
    return store.end_position() if through is None else through


def _project(application: Application, project_id: str, *, include_history: bool = False,
             through: int | None = None):
    store = application.system.store
    try:
        return project_projection(store, application.system.artifacts, project_id,
                                  include_history=include_history, through=through)
    except ProjectNotFoundError:
        raise NotFound(f"project not found: {project_id}") from None


def _work_item(state: Any, work_item_id: str) -> Any:
    item = state.work_item(work_item_id)
    if item is None:
        raise NotFound(f"work item not found: {work_item_id}")
    return item


def _run(application: Application, run_id: str, *, through: int | None = None) -> Any:
    try:
        return project_run(application.system.store, run_id) if through is None else \
            replay_run(application.system.store, run_id, through=through)
    except RunNotFoundError:
        raise NotFound(f"run not found: {run_id}") from None


def _optional_run(application: Application, run_id: str, *, through: int | None = None) -> Any:
    try:
        return project_run(application.system.store, run_id) if through is None else \
            replay_run(application.system.store, run_id, through=through)
    except RunNotFoundError:
        return None

def _recovery_observation(application: Application, run_id: str) -> str | None:
    # 一个事项的恢复观察状态（工单 #18，v8 设计说明第 7.2 节；工单 #747 区分结束的方式）：
    # 由 run 的事件、决定请求与投影的终态得出。
    # run 没有创建时没有恢复观察状态
    run = _optional_run(application, run_id)
    if run is None:
        return None
    events = application.system.store.list_events(run_id)
    decisions = _run_decisions(application, run_id)
    return observation_state(events, decisions.values(), status=run.status, stop_reason=run.stop_reason)

class RecoveryStatus(Contract):
    # 恢复观察的汇总（工单 #18，设计说明第 4.3 节 system.status 的 3.1 部分）：服务重启后自动继续的事项数、
    # 待恢复的事项数。数字取自事件日志与决定请求，
    # 与 run.recovery、projects.list 用同一份事实
    auto_resumed: int
    waiting_resume: int

def recovery_status(application: Application) -> RecoveryStatus:
    # 恢复观察的汇总（工单 #18，system.status 的 recovery）：全部 run 按恢复观察状态计数，
    # 自动继续的事项数取本次启动自动继续的 run（工单 #16）。
    # 只读取事件日志与决定请求，不写入，不调用模型
    store = application.system.store
    waiting_resume = 0
    for run_id in store.list_run_ids():
        run = _optional_run(application, run_id)
        if run is None:
            continue
        events = store.list_events(run_id)
        decisions = _run_decisions(application, run_id)
        state = observation_state(events, decisions.values(), status=run.status, stop_reason=run.stop_reason)
        if state == OBSERVATION_WAITING_RESUME:
            waiting_resume += 1
    resumed = getattr(application.system, "resumed_runs", None)
    return RecoveryStatus(
        auto_resumed=0 if not resumed else len(resumed),
        waiting_resume=waiting_resume,
    )


# ---------------------------------------------------------------------------
# 查询登记

# 项目流的全部事件种类：项目流上任何一条事件都改变项目流的版本，而版本是命令的基准
# （保存部门设置、取消事项都以它为准），所以读项目流版本的查询都要列出全部种类
PROJECT_EVENT_KINDS: tuple[str, ...] = (
    ProjectEventType.PROJECT_REGISTERED, ProjectEventType.PROJECT_RENAMED,
    ProjectEventType.PROJECT_GOAL_CHANGED, ProjectEventType.PROJECT_PINNED,
    ProjectEventType.PROJECT_ARCHIVED, ProjectEventType.PROJECT_RESTORED,
    ProjectEventType.WORK_ITEM_CREATED, ProjectEventType.WORK_ITEM_START_FAILED,
    ProjectEventType.DELIVERABLE_ADOPTED, ProjectEventType.ADOPTION_HELD,
    ProjectEventType.DEPARTMENT_SETTINGS_CONFIGURED, ProjectEventType.MATERIAL_RECORDED,
    ProjectEventType.SOURCE_DIRECTORY_CONFIGURED, ProjectEventType.INITIAL_PRD_PROPOSED,
    ProjectEventType.PROJECT_DECISION_REQUESTED, ProjectEventType.PROJECT_DECISION_ANSWERED,
    ProjectEventType.PROJECT_DECISION_WITHDRAWN, ProjectEventType.ONBOARDING_REVISION_STARTED,
    ProjectEventType.BASELINE_ADOPTED, ProjectEventType.PARAMETER_SET,
    ProjectEventType.WRITEBACK_COMPLETED, ProjectEventType.WRITEBACK_STOPPED,
    ProjectEventType.WRITEBACK_NOT_NEEDED, ProjectEventType.WRITEBACK_HELD,
    ProjectEventType.WRITEBACK_VERIFIED,
)

# run 流的全部事件种类：导出（run.export）给出这个 run 的全部事件与投影，任何一条 run 事件都改变它
RUN_EVENT_KINDS: tuple[str, ...] = (
    EventType.RUN_CREATED, EventType.USER_INPUT_RECEIVED, EventType.PRODUCT_INPUT_ASSIGNED,
    EventType.DEPARTMENT_GUIDANCE_RECEIVED, EventType.DEPARTMENT_GUIDANCE_APPLIED,
    EventType.DEPARTMENT_GUIDANCE_RESPONDED, EventType.DEPARTMENT_ACTIVATED, EventType.DEPARTMENT_INPUT,
    EventType.TOOL_CALL_REQUIRED, EventType.ACTIVATION_FINISHED, EventType.CONTEXT_ASSEMBLED,
    EventType.MODEL_REQUEST_SERIALIZED, EventType.MODEL_REASONING, EventType.MODEL_MESSAGE,
    EventType.MODEL_REQUESTED, EventType.MODEL_STREAM_PROGRESS, EventType.MODEL_ATTEMPT_FINISHED,
    EventType.MODEL_ATTEMPT_FAILED, EventType.MODEL_RETRY_SCHEDULED, EventType.COMPACTION_RECORDED,
    EventType.TOOL_CALLED, EventType.TOOL_STARTED, EventType.TOOL_SKIPPED, EventType.ACTION_VERIFIED,
    EventType.PROPOSAL_SUBMITTED, EventType.PROPOSAL_REJECTED, EventType.SPEC_ACCEPTED,
    EventType.SPEC_SUPERSEDED, EventType.CONTRACT_ACCEPTED, EventType.ASK_STARTED, EventType.ASK_ANSWERED,
    EventType.PRODUCT_DECISION_ACCEPTED,
    # 成果失效（骨架事件，S1b，工单 #858）
    EventType.ARTIFACT_INVALIDATED,
    EventType.DELIVERY_ACCEPTED, EventType.QA_SUBMITTED,
    EventType.QA_TESTS_SAVED, EventType.STRUCTURE_ACCEPTED, EventType.BASELINE_REVIEW_ACCEPTED,
    EventType.LESSON_CANDIDATE_RECORDED, EventType.RUN_DONE, EventType.RUN_PAUSED, EventType.RUN_FAILED,
    EventType.RUN_RESUMED, EventType.RUN_CONTINUED, EventType.DECISION_REQUESTED, EventType.DECISION_ANSWERED,
    EventType.DECISION_WITHDRAWN,
)


PROJECTS_LIST = QueryDefinition(
    name="projects.list", request=ProjectsList, result=ProjectList, handle=_projects_list,
    replayable=True,
    # 项目流上的任何一条事件都改变项目流版本（列表里显示的版本），因此全部项目流种类都在清单里
    changed_by=(*PROJECT_EVENT_KINDS,
                EventType.RUN_CREATED, EventType.RUN_DONE, EventType.RUN_FAILED, EventType.RUN_PAUSED,
                EventType.RUN_CONTINUED, EventType.RUN_RESUMED, EventType.TOOL_STARTED, EventType.ACTION_VERIFIED,
                EventType.DECISION_REQUESTED, EventType.DECISION_ANSWERED, EventType.DECISION_WITHDRAWN,
                # 恢复观察的汇总：部门激活与激活结束改变事项的恢复状态
                EventType.DEPARTMENT_ACTIVATED, EventType.ACTIVATION_FINISHED),
)

PROJECT_OVERVIEW = QueryDefinition(
    name="project.overview", request=ProjectOverview, result=ProjectOverviewResult, handle=_project_overview,
    # 项目流上的任何一条事件都改变项目流版本（这一页显示的版本），因此全部项目流种类都在清单里
    changed_by=(*PROJECT_EVENT_KINDS,
                EventType.RUN_CREATED, EventType.RUN_DONE, EventType.RUN_FAILED, EventType.RUN_PAUSED,
                EventType.RUN_CONTINUED, EventType.RUN_RESUMED,
                EventType.DEPARTMENT_ACTIVATED,
                EventType.QA_SUBMITTED, EventType.DELIVERY_ACCEPTED, EventType.SPEC_ACCEPTED,
                EventType.ASK_STARTED, EventType.ASK_ANSWERED,
                EventType.DECISION_REQUESTED,
                # 部门状态（工单 #903）：一轮工作结束以后部门回到等待工作或核验中，
                # 决定请求的回答与撤销让「等用户」结束
                EventType.ACTIVATION_FINISHED, EventType.DECISION_ANSWERED, EventType.DECISION_WITHDRAWN),
)

PROJECT_LOOP = QueryDefinition(
    name="project.loop", request=ProjectLoop, result=ProjectLoopResult, handle=_project_loop,
    replayable=True,
    changed_by=(ProjectEventType.WORK_ITEM_CREATED, ProjectEventType.DELIVERABLE_ADOPTED,
                EventType.RUN_CREATED, EventType.RUN_DONE, EventType.RUN_FAILED,
                EventType.RUN_PAUSED, EventType.RUN_CONTINUED, EventType.RUN_RESUMED, EventType.DEPARTMENT_ACTIVATED,
                EventType.ASK_STARTED, EventType.ASK_ANSWERED, EventType.TOOL_STARTED, EventType.TOOL_CALLED,
                EventType.TOOL_SKIPPED, EventType.ACTION_VERIFIED, EventType.DECISION_REQUESTED,
                EventType.DECISION_ANSWERED, EventType.DECISION_WITHDRAWN,
                ProjectEventType.PROJECT_DECISION_REQUESTED, ProjectEventType.PROJECT_DECISION_ANSWERED,
                ProjectEventType.PROJECT_DECISION_WITHDRAWN, ProjectEventType.ONBOARDING_REVISION_STARTED,
                ProjectEventType.BASELINE_ADOPTED,
                # 事项的进度由成果推算：规格被接纳、交付到达、质检放行与退回都改变它
                EventType.SPEC_ACCEPTED, EventType.DELIVERY_ACCEPTED, EventType.QA_SUBMITTED,
                # 激活结束以后事项的恢复状态改变
                EventType.ACTIVATION_FINISHED),
)

PROJECT_FLOW = QueryDefinition(
    name="project.flow", request=ProjectFlow, result=ProjectFlowResult, handle=_project_flow,
    # 流转记录吸收的事件种类（读取模型的 FLOW_TYPES）：规格被接纳、交付到达与质检结论都进流转记录
    changed_by=(EventType.ASK_STARTED, EventType.ASK_ANSWERED,
                EventType.SPEC_ACCEPTED, EventType.DELIVERY_ACCEPTED,
                EventType.QA_SUBMITTED),
)

WORK_ITEM_INPUTS = QueryDefinition(
    name="work_item.inputs", request=WorkItemInputs, result=WorkItemInputsResult, handle=_work_item_inputs,
    changed_by=(EventType.RUN_CREATED, EventType.USER_INPUT_RECEIVED, EventType.PRODUCT_INPUT_ASSIGNED,
                # 规格被接纳以后这一页显示的已处理输入版本随之更新
                EventType.SPEC_ACCEPTED),
)

EVENT_DETAIL = QueryDefinition(
    name="event.detail", request=EventDetail, result=EventDetailResult, handle=_event_detail, changed_by=(),
)

DEPARTMENT_WORKSPACE = QueryDefinition(
    name="department.workspace", request=DepartmentWorkspace, result=DepartmentWorkspaceResult,
    handle=_department_workspace,
    changed_by=(EventType.DEPARTMENT_GUIDANCE_RECEIVED,
                EventType.DEPARTMENT_GUIDANCE_APPLIED, EventType.DEPARTMENT_GUIDANCE_RESPONDED,
                EventType.DEPARTMENT_ACTIVATED, EventType.MODEL_REQUESTED, EventType.MODEL_MESSAGE,
                EventType.CONTEXT_ASSEMBLED, EventType.COMPACTION_RECORDED, EventType.USER_INPUT_RECEIVED,
                EventType.DEPARTMENT_INPUT,
                ProjectEventType.WORK_ITEM_CREATED, ProjectEventType.DELIVERABLE_ADOPTED,
                EventType.RUN_DONE, EventType.RUN_FAILED, EventType.RUN_PAUSED,
                EventType.RUN_CONTINUED, EventType.RUN_RESUMED,
                EventType.ASK_STARTED, EventType.ASK_ANSWERED,
                # 本项目的部门设置修改以后生效模型与来源随之更新（工单 #95 的验收）；
                # 目录修订（准入作废、连接修改）以后引用可用性随之更新
                ProjectEventType.DEPARTMENT_SETTINGS_CONFIGURED, CatalogEventType.CATALOG_REVISED,
                # 规格被接纳以后这个部门的房间里挂着新的规格
                EventType.SPEC_ACCEPTED,
                # 部门状态与房间的传信数（工单 #903）：一轮工作结束、决定请求的发出与回答、
                # 交付到达与质检结论都改变它们
                EventType.ACTIVATION_FINISHED, EventType.DECISION_REQUESTED, EventType.DECISION_ANSWERED,
                EventType.DECISION_WITHDRAWN, EventType.DELIVERY_ACCEPTED, EventType.QA_SUBMITTED),
)

RUN_ACTIONS = QueryDefinition(
    name="run.actions", request=RunActions, result=RunActionsResult, handle=_run_actions,
    changed_by=(EventType.TOOL_STARTED, EventType.TOOL_CALLED, EventType.TOOL_SKIPPED,
                EventType.ACTION_VERIFIED, EventType.DEPARTMENT_ACTIVATED, EventType.ACTIVATION_FINISHED),
)

RUN_ASKS = QueryDefinition(
    name="run.asks", request=RunAsks, result=RunAsksResult, handle=_run_asks,
    changed_by=(EventType.ASK_STARTED, EventType.ASK_ANSWERED),
)

WORK_ITEM_MATERIALS = QueryDefinition(
    name="work_item.materials", request=WorkItemMaterials, result=WorkItemMaterialsResult,
    handle=_work_item_materials,
    changed_by=(EventType.RUN_CREATED, EventType.USER_INPUT_RECEIVED, EventType.CONTRACT_ACCEPTED,
                EventType.DELIVERY_ACCEPTED, EventType.QA_SUBMITTED,
                # 成果失效（S1b，工单 #858）：交付的失效状态在这一页的交付清单里
                EventType.ARTIFACT_INVALIDATED,
                ProjectEventType.MATERIAL_RECORDED, ProjectEventType.INITIAL_PRD_PROPOSED,
                ProjectEventType.PROJECT_DECISION_REQUESTED, ProjectEventType.PROJECT_DECISION_ANSWERED,
                ProjectEventType.PROJECT_DECISION_WITHDRAWN,
                # 旧版本的 run（工单 #1186）：因升级重新开始时同一个建档事项再登记一条事项记录（新 run），
                # 旧 run 停止时它的状态随之写下
                ProjectEventType.WORK_ITEM_CREATED, EventType.RUN_FAILED),
)

DELIVERY_FILE = QueryDefinition(
    name="delivery.file", request=DeliveryFile, result=DeliveryFileResult, handle=_delivery_file, changed_by=(),
)

PROJECT_ATTEMPTS = QueryDefinition(
    name="project.attempts", request=ProjectAttempts, result=ProjectAttemptsResult, handle=_project_attempts,
    changed_by=(EventType.CONTEXT_ASSEMBLED, EventType.MODEL_REQUESTED, EventType.MODEL_ATTEMPT_FINISHED,
                EventType.MODEL_ATTEMPT_FAILED, EventType.MODEL_RETRY_SCHEDULED),
    unchanged_by=(
        UnchangedEvent(EventType.MODEL_MESSAGE,
                       "模型消息只改变调用尝试表的阶段与输出条数；进行中的阶段由输出片段实时显示（工单 #891）"),
    ),
)

PROJECT_USAGE = QueryDefinition(
    name="project.usage", request=ProjectUsage, result=UsageReport, handle=_project_usage,
    # 用量报告按调用尝试统计：上下文装配多一次就多一条尝试，所以它在清单里
    changed_by=(EventType.CONTEXT_ASSEMBLED, EventType.MODEL_ATTEMPT_FINISHED, EventType.MODEL_ATTEMPT_FAILED,
                EventType.MODEL_RETRY_SCHEDULED),
)

RUN_ATTEMPT = QueryDefinition(
    name="run.attempt", request=RunAttempt, result=RunAttemptResult, handle=_run_attempt,
    changed_by=(EventType.CONTEXT_ASSEMBLED, EventType.MODEL_REQUESTED, EventType.MODEL_ATTEMPT_FINISHED,
                EventType.MODEL_ATTEMPT_FAILED),
    unchanged_by=(
        UnchangedEvent(EventType.MODEL_MESSAGE,
                       "模型消息只改变这次调用的阶段与已收到的输出条数；进行中的阶段由输出片段实时显示（工单 #891）"),
    ),
)

PROJECT_SETTINGS = QueryDefinition(
    name="project.settings", request=ProjectSettings, result=ProjectSettingsResult, handle=_project_settings,
    # 这一页显示的项目版本是项目流的版本：项目流上的任何一条事件都改变它，
    # 因此保存部门设置、取消事项的基准不会过期（工单 #891 的验收）
    changed_by=(*PROJECT_EVENT_KINDS,
                # 目录修订（准入作废、模型变更）以后生效模型的建议能力提醒随之更新（工单 #95）
                CatalogEventType.CATALOG_REVISED),
)

RUN_EXPORT = QueryDefinition(
    name="run.export", request=RunExport, result=RunExportResult, handle=_run_export,
    # 导出给出这个 run 的全部事件与投影：任何一条 run 事件都改变它
    changed_by=RUN_EVENT_KINDS,
)

PROJECT_WRITEBACK = QueryDefinition(
    name="project.writeback", request=ProjectWriteback, result=ProjectWritebackResult, handle=_project_writeback,
    # 写回的五种结果事件：写回完成以后页面上那一节自己更新（工单 #709）
    changed_by=(ProjectEventType.WRITEBACK_COMPLETED, ProjectEventType.WRITEBACK_STOPPED,
                ProjectEventType.WRITEBACK_NOT_NEEDED, ProjectEventType.WRITEBACK_HELD,
                ProjectEventType.WRITEBACK_VERIFIED),
)

REPLAY_CHECK = QueryDefinition(
    name="replay.check", request=ReplayCheck, result=ReplayCheckResult, handle=_replay_check, changed_by=(),
)


# ---------------------------------------------------------------------------
# run.recovery (工单 #18，设计说明第 4.3 节「恢复与动作核实（3.1）」)

class RunRecovery(Contract):
    run_id: str

class UnfinishedAction(Contract):
    # 未完成动作（v8 设计说明第 7.2 节）：动作身份、所属部门、输入依据、执行前后快照与状态。
    # 未发送的动作由保存的模型响应给出（engine 补执行），结果未知的动作有 tool_started 没有结果
    action_id: str
    tool: str
    department: str | None
    status: Literal["not_sent", "unknown"]
    activation_id: str | None
    step_id: int | None
    input_version: int | None
    purpose: str | None
    before_snapshot_ref: dict[str, Any] | None
    created_at: str
    started_event_id: str

class VerificationRecord(Contract):
    # 核实记录：追加在动作之后，不改写原始观察。basis 与 result 是核实依据与核实结果，
    # decision_id 给出覆盖它的决定请求，note 是用户回答时的说明
    action_id: str
    tool: str
    basis: str
    result: str
    decided_by: str
    note: str | None
    decision_id: str | None
    at: str
    event_id: str

class RecoveryLimits(Contract):
    # 限额（v8 设计说明第 7.2 节）：已用激活次数、模型步骤与重试尝试；恢复不清零。
    # 等待模型服务的时间在 Stage 4 加入，等待期间不计入运行时间上限
    activations: int
    model_steps: int
    retries: int
    cycle_count: int

class RecoveryOwner(Contract):
    # 执行所有权（v8 设计说明第 7.2 节）：当前执行者与取得时间。没有有效执行者时为空。
    # 执行槽位在 3.4A 之前只有一个，holds_slot 表示这个 run 是否占用它。
    # 这次取得执行权所依据的中断位置与当时那条事件的文字取自 run_resumed 的依据（工单 #181，设计说明第 4.3 节）
    epoch: int
    since: str
    holds_slot: bool
    interrupted_at_event_id: str | None
    interrupted_at_text: str | None

class UnknownAction(Contract):
    # 重新启动时结果未知的动作与它的处理方式（工单 #181，设计说明第 4.3 节）：核实确认（自动核实，或者
    # 用户选择按当前实际状态接受）或交还发出它的会话。交还以后动作仍列在这里，不等同于「没有发生过」：
    # 原始观察不改写，处理方式与交还给模型的内容照实写出（恢复契约第 4 节）
    action_id: str
    tool: str
    department: str | None
    session_id: str | None
    handling: Literal["confirmed", "returned"]
    purpose: str | None
    input_version: int | None
    before: dict[str, Any] | None
    returned: str | None
    at: str

class RecoverySession(Contract):
    # 一个会话的已用量（设计说明第 4.3 节，三部门的循环结构第 9 节）：部门主线与询问分支各是一个会话，
    # 用量各自累计。已用秒是已结算的运行时间，中断的那一轮不计
    session_id: str
    department: str | None
    kind: Literal["main", "branch"]
    elapsed_sec: int
    activations: int
    model_steps: int

class LateResult(Contract):
    # 迟到结果：旧执行者写入的、不推进状态的记录（v8 设计说明第 7.2 节）
    at: str
    text: str
    event_id: str

class UnusableTarget(Contract):
    # 待恢复原因：哪个部门的模型无法使用、模型与具体问题；供恢复页写明修复入口
    department: str
    model: str | None
    problem: str

class RecoveryUpgrade(Contract):
    # 因升级停止的新旧 run 关联（工单 #1186，设计说明第 4.3 节 2026-10-29 补充）：旧 run 记为因升级停止，
    # 对应的事项用项目的起点重新开始。旧 run 与从它重新开始的新 run 两边的 run.recovery 都给同一份关联：
    # 页面在旧 run 上写「因升级停止」，同时看得到重新开始的新 run。
    # 事件版本是 run_created 记下的 run 事件版本（ADR-0019）；起点是重新开始的那条：采纳成果、
    # 起始文件夹快照或空树。新 run 还没有建立时它为空，起点也为空
    stopped_run_id: str
    stopped_work_item_id: str | None
    stopped_work_item_title: str | None
    stopped_run_event_version: int
    new_run_id: str | None
    new_work_item_id: str | None
    new_work_item_title: str | None
    new_run_event_version: int | None
    start_point: Literal["adoption", "initial_snapshot", "empty"] | None

class RunRecoveryResult(Contract):
    # 一个事项的恢复观察（设计说明第 4.3 节）：恢复观察状态、待恢复原因、最后已确认位置、
    # 未完成动作、核实记录、下一项合法操作、继续执行是否可用及原因、限额、执行所有权与迟到结果。
    # 最后已确认位置的文字、结果未知的动作与各会话的用量是 v13 恢复页要读的内容（工单 #181）
    work_item_id: str
    run_id: str
    state: Literal["running", "interrupted", "waiting_resume", "completed", "paused", "cancelled", "stopped"]
    reason: str | None
    executable: bool
    last_confirmed_position: int
    last_confirmed_event_id: str | None
    last_confirmed_text: str | None
    unfinished_actions: list[UnfinishedAction]
    unknown_actions: list[UnknownAction]
    verifications: list[VerificationRecord]
    next_legal_action: str | None
    can_continue: bool
    cannot_continue_reason: str | None
    unusable: UnusableTarget | None
    limits: RecoveryLimits
    sessions: list[RecoverySession]
    owner: RecoveryOwner | None
    late_results: list[LateResult]
    # 因升级停止的新旧 run 关联（工单 #1186）；这个 run 不是因升级停止、也不是从旧 run 重新开始的，为空
    upgrade: RecoveryUpgrade | None

# 一个事项的恢复观察状态对应的下一项合法操作（v8 设计说明第 7.2 节）
_NEXT_ACTION = {
    OBSERVATION_RUNNING: "none",
    OBSERVATION_INTERRUPTED: "continue",
    OBSERVATION_WAITING_RESUME: "repair_and_resume",
    OBSERVATION_COMPLETED: None,
    OBSERVATION_PAUSED: None,
    OBSERVATION_CANCELLED: None,
    OBSERVATION_STOPPED: None,
}

def _run_recovery(application: Application, request: RunRecovery) -> Snapshot[RunRecoveryResult]:
    # 只读取：run 的事件与决定请求、投影与最小投影里的已用量。不写入，不触发结算，不调用模型与工具
    store = application.system.store
    run = _run(application, request.run_id)
    events = store.list_events(request.run_id)
    # 已用量读最小投影（骨架与应用设计说明第 4 节第 4 条，S1e 工单 #1015）：
    # 激活次数、模型步数与执行权都由它折出来，不在这里从事件数一遍
    minimal = fold_events(events)
    decisions = _run_decisions(application, request.run_id)
    terminal = run.status in TERMINAL_STATUSES
    state = observation_state(events, decisions.values(), status=run.status, stop_reason=run.stop_reason)
    # 已结束的 run 不再继续：未完成动作与未回答的核实请求不由恢复处理，只显示结束原因
    unfinished = [] if terminal else _unfinished_actions(events)
    verifications = _verification_records(events, decisions.values())
    resume_requests = [] if terminal else open_resume_decisions(decisions.values())
    # 最后已确认的位置是这个事项自己最后一条已提交事件的位置（工单 #895）：日志的末尾是全部项目、
    # 全部事项的最新位置，别的项目或事项在这之后写了事件时不能算作这个事项的进度。没有事件时为 0
    confirmed = None if run.last_event_id is None else store.get_event(run.last_event_id)
    return Snapshot[RunRecoveryResult](
        position=store.end_position(),
        data=RunRecoveryResult(
            work_item_id=run.work_item_id or "", run_id=run.run_id, state=state,
            reason=_recovery_reason(run, state, resume_requests),
            executable=not terminal,
            last_confirmed_position=0 if confirmed is None else confirmed.position,
            last_confirmed_event_id=run.last_event_id,
            last_confirmed_text=_event_text(confirmed),
            unfinished_actions=unfinished, unknown_actions=_unknown_actions(events),
            verifications=verifications,
            next_legal_action=_NEXT_ACTION[state],
            can_continue=_can_continue(state, terminal),
            cannot_continue_reason=_cannot_continue_reason(run, state, terminal, resume_requests),
            unusable=_unusable_target(resume_requests),
            # 重试次数不是上限，不进最小投影，仍在这里从事件数（设计说明第 4 节第 4 条）
            limits=RecoveryLimits(activations=minimal.used.activations,
                                  model_steps=minimal.used.model_steps,
                                  retries=_retry_count(events), cycle_count=run.cycle_count),
            sessions=_recovery_sessions(minimal, run, events),
            owner=_execution_owner(minimal, events),
            # 迟到结果：3.1 的执行权在写入口拦住旧执行者的写入（write_path 的 claim_execution_right 与
            # StaleExecutionRight），被拒的写入不落盘，因此 3.1 没有迟到结果可列。远程执行代理上的迟到回执
            # 由 3.2C 在 run.actions 上补齐
            late_results=[],
            upgrade=_recovery_upgrade(application, run),
        ),
    )

def _recovery_upgrade(application: Application, run: Any) -> RecoveryUpgrade | None:
    # 因升级停止的新旧 run 关联（工单 #1186）：这个 run 自己是被强制升级停下的旧 run，或者它是从某个旧 run
    # 重新开始的新 run，两种都给同一份关联。旧 run 的新 run 从项目流的事项记录里找（work_item_created 的
    # restarted_from_run_id）；新 run 的旧 run 由事项记录自己写下的字段给出。不是升级的情形为空
    if run.project_id is None:
        return None
    state = _project(application, run.project_id, include_history=False)
    items = {item.run_id: item for item in state.work_items}
    item = items.get(run.run_id)
    if item is not None and item.restarted_from_run_id:
        stopped = _optional_run(application, item.restarted_from_run_id)
        if stopped is None:
            return None
        stopped_item = items.get(stopped.run_id)
        return RecoveryUpgrade(
            stopped_run_id=stopped.run_id, stopped_work_item_id=stopped.work_item_id,
            stopped_work_item_title=None if stopped_item is None else stopped_item.title,
            stopped_run_event_version=stopped.run_event_version,
            new_run_id=run.run_id, new_work_item_id=item.work_item_id, new_work_item_title=item.title,
            new_run_event_version=run.run_event_version, start_point=_upgrade_start_point(item),
        )
    if run.stop_reason != STOP_REASON_UPGRADE:
        return None
    stopped_item = items.get(run.run_id)
    new_item = next((entry for entry in state.work_items if entry.restarted_from_run_id == run.run_id), None)
    if new_item is None:
        # 重新开始的新事项没有建立：旧 run 仍列出，起点与新 run 为空
        return RecoveryUpgrade(
            stopped_run_id=run.run_id, stopped_work_item_id=run.work_item_id,
            stopped_work_item_title=None if stopped_item is None else stopped_item.title,
            stopped_run_event_version=run.run_event_version,
            new_run_id=None, new_work_item_id=None, new_work_item_title=None, new_run_event_version=None,
            start_point=None,
        )
    new_run = _optional_run(application, new_item.run_id)
    return RecoveryUpgrade(
        stopped_run_id=run.run_id, stopped_work_item_id=run.work_item_id,
        stopped_work_item_title=None if stopped_item is None else stopped_item.title,
        stopped_run_event_version=run.run_event_version,
        new_run_id=new_item.run_id, new_work_item_id=new_item.work_item_id, new_work_item_title=new_item.title,
        new_run_event_version=None if new_run is None else new_run.run_event_version,
        start_point=_upgrade_start_point(new_item),
    )

def _upgrade_start_point(item: Any) -> str:
    # 因升级重新开始时的起点（设计说明第 4.3 节、项目的起始文件夹设计说明第 2 节）：有采纳成果时是采纳成果，
    # 其次是起始文件夹快照，都没有时是空树。与事项的起点按同一个顺序取
    if item.baseline is not None:
        return "adoption"
    if item.snapshot is not None:
        return "initial_snapshot"
    return "empty"

def _event_text(event: Any) -> str | None:
    # 一条事件给用户看的文字（与应用层事件流里的说明同一份，工单 #181）：最后已确认的位置与中断位置
    # 都按它写，页面上不出现事件种类与编号
    return None if event is None else event_label(event.type, event.payload or {})

def _run_decisions(application: Application, run_id: str) -> dict[str, Any]:
    # 一个 run 流保存的决定请求，按身份：与事件在同一个事务中更新，重放只读取
    return load_decisions(application.system.store.projection(run_stream(run_id)))

def _recovery_reason(run: Any, state: str, resume_requests: list[Any]) -> str | None:
    # 恢复观察状态的说明：中断给出停止位置，待恢复给出无法使用的模型，
    # 四种结束方式各自说明结束的原因；运行中不需要说明。
    # 阶段与停止原因按中文写（工单 #747）：机器标识不直接出现在给用户看的文字里
    if state == OBSERVATION_INTERRUPTED:
        return "进程停止，等待启动时自动继续"
    if state == OBSERVATION_WAITING_RESUME and resume_requests:
        return str(resume_requests[0].request.get("description") or resume_requests[0].kind)
    if state == OBSERVATION_COMPLETED:
        return f"运行已完成：{stop_reason_name(run.stop_reason)}" if run.stop_reason else "运行已完成"
    if state == OBSERVATION_CANCELLED:
        return "运行已被取消"
    if state == OBSERVATION_PAUSED:
        return (f"运行已暂停，等待处理：{stop_reason_name(run.stop_reason)}"
                if run.stop_reason else "运行已暂停，等待处理")
    if state == OBSERVATION_STOPPED:
        return f"运行已停止：{stop_reason_name(run.stop_reason)}" if run.stop_reason else "运行已停止"
    return None

def _can_continue(state: str, terminal: bool) -> bool:
    # 继续执行是否可用：已结束不可继续；运行中已经在执行；其余状态在用户处理（回答或修复）以后可继续
    if terminal:
        return False
    return state == OBSERVATION_RUNNING

def _cannot_continue_reason(run: Any, state: str, terminal: bool, resume_requests: list[Any]) -> str | None:
    # 继续执行不可用的原因；停止原因按中文写（工单 #747）
    if terminal:
        return f"运行已经结束：{stop_reason_name(run.stop_reason)}" if run.stop_reason else "运行已经结束"
    if state == OBSERVATION_WAITING_RESUME:
        return "模型引用无法使用或定义版本不同，等待用户回答决定请求"
    if state == OBSERVATION_INTERRUPTED:
        return "进程中断，等待启动时自动继续"
    return None

def _unusable_target(resume_requests: list[Any]) -> UnusableTarget | None:
    # 待恢复原因：只对「模型引用无法使用」的请求给出部门、模型与具体问题
    for decision in resume_requests:
        if decision.kind != "model_unavailable":
            continue
        target = decision.request.get("target") or {}
        return UnusableTarget(department=str(decision.request.get("department") or ""),
                              model=target.get("requested_model") or target.get("actual_model"),
                              problem=str(decision.request.get("description") or decision.request.get("message") or ""))
    return None

def _unfinished_actions(events: list[Any]) -> list[UnfinishedAction]:
    # 未完成动作：还没有交还或核实结果的动作（只在进程正在执行这个动作时出现）。
    # 未发送的动作由保存的模型响应给出，属于步骤驱动的补执行范围，读取侧只列出已经发出的动作
    actions = classify_actions(events)
    action_ids = {identity[2] for identity, info in actions.items() if info["status"] == ACTION_UNKNOWN}
    unfinished: list[UnfinishedAction] = []
    for event in events:
        if event.type != EventType.TOOL_STARTED:
            continue
        payload = event.payload or {}
        action_id = str(payload.get("id") or event.event_id)
        if action_id not in action_ids:
            continue
        tool = str(payload.get("name") or "")
        unfinished.append(UnfinishedAction(
            action_id=action_id, tool=tool, department=event.department, status=ACTION_UNKNOWN,
            activation_id=payload.get("activation_id"), step_id=payload.get("step_id"),
            input_version=payload.get("input_version"), purpose=payload.get("purpose"),
            before_snapshot_ref=payload.get("before_snapshot_ref"),
            created_at=event.created_at, started_event_id=event.event_id,
        ))
    unfinished.sort(key=lambda item: item.created_at)
    return unfinished


def _unknown_actions(events: list[Any]) -> list[UnknownAction]:
    # 重新启动时结果未知的动作与它后来的处置（工单 #181，设计说明第 4.3 节）：核实确认或交还发出它的会话。
    # 处置是追加的核实记录，原始观察不改写；同一个动作有几条处置时取最后一条，动作本身仍只有一行
    started = {action_identity(event): event for event in events if event.type == EventType.TOOL_STARTED}
    latest: dict[tuple[str, int | None, str], UnknownAction] = {}
    for event in events:
        if event.type != EventType.ACTION_VERIFIED:
            continue
        payload = event.payload or {}
        identity = action_identity(event)
        source = started.get(identity)
        source_payload = {} if source is None else (source.payload or {})
        latest[identity] = UnknownAction(
            action_id=identity[2],
            tool=str(payload.get("name") or source_payload.get("name") or ""),
            department=event.department or (None if source is None else source.department),
            session_id=event.session_id or (None if source is None else source.session_id),
            # 交还发出它的会话是 handed_back；其余处置都是核实确认（自动核实，或者用户选择按当前实际状态接受）
            handling="returned" if payload.get("resolution") == "handed_back" else "confirmed",
            purpose=payload.get("purpose", source_payload.get("purpose")),
            input_version=source_payload.get("input_version"),
            before=source_payload.get("before_snapshot_ref"),
            returned=_returned_text(payload),
            at=event.created_at,
        )
    return sorted(latest.values(), key=lambda item: item.at)

def _returned_text(payload: Any) -> str | None:
    # 交还给模型的内容（工单 #181）：核实记录里写进部门历史的工具结果原文，模型读到的就是它
    item = payload.get("input_item")
    if not isinstance(item, dict):
        return None
    output = item.get("output")
    if isinstance(output, str):
        return output
    return None if output is None else json.dumps(output, ensure_ascii=False)

def _recovery_sessions(minimal: MinimalProjection, run: Any, events: list[Any]) -> list[RecoverySession]:
    # 各会话的用量（工单 #181，设计说明第 4.3 节）：已用量读最小投影的 sessions，按部门、主线在前的顺序。
    # 主线会话的部门在事项创建时记下；询问分支的部门取自它的激活事件，分支的编号来自运行状态投影
    branches = set(getattr(run, "branch_sessions", None) or ())
    departments: dict[str, str] = {}
    for event in events:
        if event.type != EventType.DEPARTMENT_ACTIVATED:
            continue
        session_id = event.session_id or ""
        if session_id and event.department and session_id not in departments:
            departments[session_id] = event.department
    rows = [
        RecoverySession(
            session_id=session_id,
            department=state.department or departments.get(session_id),
            kind="branch" if session_id in branches else "main",
            elapsed_sec=max(0, round(state.settled_ms / 1000)),
            activations=state.activations, model_steps=state.model_steps,
        )
        for session_id, state in minimal.sessions.items()
    ]
    rows.sort(key=lambda item: (
        DEPARTMENTS.index(item.department) if item.department in DEPARTMENTS else len(DEPARTMENTS),
        item.kind != "main", item.session_id,
    ))
    return rows


def _verification_records(events: list[Any], decisions: Any) -> list[VerificationRecord]:
    # 核实记录有三条来源，都不改写原始观察：
    # - 自动核实（工单 #308）：对比确认动作已经完成，记 action_verified，依据是这次对比；
    # - 交还会话（工单 #581）：重新启动时结果未知，交还发出它的会话；
    # - 用户选择按当前实际状态继续（旧事件，工单 #17、#582）：action_verified 事件里带着决定请求的编号
    answers = {decision.decision_id: decision for decision in decisions
               if decision.kind == "unknown_action" and decision.status == "answered"}
    records: list[VerificationRecord] = []
    for event in events:
        if event.type != EventType.ACTION_VERIFIED:
            continue
        payload = event.payload or {}
        resolution = payload.get("resolution")
        decision_id = payload.get("decision_id")
        answer = answers.get(decision_id) if isinstance(decision_id, str) else None
        if resolution == "auto_verify":
            basis = "自动核实（已完成）"
            result = "动作效果按参数里的目标内容确认完成"
            decided_by = "system"
        elif resolution == "handed_back":
            basis = "重新启动时结果未知，交还发出它的会话"
            result = str(payload.get("error") or "交还发出它的会话处置")
            decided_by = "system"
        else:
            basis = "用户选择按当前实际状态继续"
            result = "动作效果按当前实际状态接受"
            decided_by = "user"
        records.append(VerificationRecord(
            action_id=str(payload.get("id") or event.event_id), tool=str(payload.get("name") or ""),
            basis=basis,
            result=result,
            decided_by=decided_by,
            note=None if answer is None else (answer.answer or {}).get("note"),
            decision_id=decision_id if isinstance(decision_id, str) else None,
            at=event.created_at, event_id=event.event_id,
        ))
    records.sort(key=lambda item: item.at)
    return records


def _retry_count(events: list[Any]) -> int:
    return len([event for event in events if event.type == EventType.MODEL_RETRY_SCHEDULED])

def _execution_owner(minimal: MinimalProjection, events: list[Any]) -> RecoveryOwner | None:
    # 执行所有权读最小投影（S1e 工单 #1015）：编号是投影里的执行权编号，没有取得过执行权时为空。
    # 取得的时间不是投影的内容（内核不为应用加字段），仍取自记下这一次取得的那个事件；
    # 这次取得所依据的中断位置与当时那条事件的文字也来自它（工单 #181，设计说明第 4.3 节）
    epoch = minimal.execution_right
    if epoch <= 0:
        return None
    resumed = next((event for event in reversed(events)
                    if event.type == EventType.RUN_RESUMED
                    and int((event.payload or {}).get("acquired_epoch") or 0) == epoch), None)
    since = resumed.created_at if resumed is not None else ""
    basis = {} if resumed is None else ((resumed.payload or {}).get("basis") or {})
    interrupted_at = basis.get("interrupted_at_event_id")
    interrupted_at = interrupted_at if isinstance(interrupted_at, str) and interrupted_at else None
    interrupted_event = None
    if interrupted_at is not None:
        interrupted_event = next((event for event in events if event.event_id == interrupted_at), None)
    return RecoveryOwner(epoch=epoch, since=since, holds_slot=True,
                         interrupted_at_event_id=interrupted_at, interrupted_at_text=_event_text(interrupted_event))

RUN_RECOVERY = QueryDefinition(
    name="run.recovery", request=RunRecovery, result=RunRecoveryResult, handle=_run_recovery,
    changed_by=(EventType.RUN_RESUMED, EventType.RUN_DONE, EventType.RUN_PAUSED, EventType.RUN_FAILED,
                EventType.TOOL_STARTED, EventType.TOOL_CALLED, EventType.TOOL_SKIPPED,
                EventType.ACTION_VERIFIED, EventType.DECISION_REQUESTED, EventType.DECISION_ANSWERED,
                EventType.DECISION_WITHDRAWN, EventType.DEPARTMENT_ACTIVATED, EventType.ACTIVATION_FINISHED,
                # 因升级停止的新旧 run 关联（工单 #1186）：旧 run 的新 run 由事项记录给出，新 run 的事件版本取自
                # 它的 run_created；两者都改变这份关联
                ProjectEventType.WORK_ITEM_CREATED, EventType.RUN_CREATED),
    unchanged_by=(
        UnchangedEvent(EventType.MODEL_REQUESTED,
                       "模型请求只改变恢复页上的已用模型步数与各会话的模型步骤；那是进度读数，与已用秒数同类（工单 #891）"),
    ),
)

PROJECT_QUERIES = (
    PROJECTS_LIST, PROJECT_OVERVIEW, PROJECT_LOOP, PROJECT_FLOW, WORK_ITEM_INPUTS, EVENT_DETAIL,
    DEPARTMENT_WORKSPACE, RUN_ACTIONS, RUN_ASKS, WORK_ITEM_MATERIALS, DELIVERY_FILE, PROJECT_ATTEMPTS, PROJECT_USAGE,
    RUN_ATTEMPT, PROJECT_SETTINGS, PROJECT_WRITEBACK, RUN_EXPORT, REPLAY_CHECK, RUN_RECOVERY,
)
