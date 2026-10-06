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

from ..git_audit import git_version_detail
from ..definitions import DEFINITIONS
from ..event_store import run_stream
from ..models import (
    ArtifactRef, DEPARTMENTS, TERMINAL_PHASES, CatalogEventType, EventType, GIT_VERSION_EVENTS,
    ProjectEventType, hash_bytes,
)
from ..observability import ObservabilityQuery
from ..providers.selection import ModelSelection
from ..projection import (
    RunNotFoundError, project_run, replay_decisions, replay_project, replay_run, load_decisions, saved_project,
)
from ..projects import ProjectNotFoundError, project_projection
from ..replay_check import ReplayIntegrityError, verify_replay
from ..recovery import (
    ACTION_UNKNOWN, OBSERVATION_INTERRUPTED, OBSERVATION_PENDING_VERIFICATION, OBSERVATION_RUNNING,
    OBSERVATION_TERMINATED, OBSERVATION_WAITING_RESUME, action_identity, observation_state, open_decisions,
    open_resume_decisions, unresolved_unknown_actions,
)
from ..tree_archive import load_tree
from .contracts import Contract, Snapshot, Text
from .payloads import Department
from .read_models import AttemptStatus, ReadModels
from .registry import QueryDefinition
from .replay import ReplayRequest, check_position

if TYPE_CHECKING:
    from .application import Application


class NotFound(LookupError):
    # 查询的目标不存在：项目、事项、run、事件、尝试或交付中的文件
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
    # 建档状态标记：项目由接入已有项目建立且还没有基线时，建档中为 onboarding，等待建档为 awaiting_onboarding；其余为空
    onboarding_status: str | None
    # 中断、待核实与待恢复的标记（工单 #18）：本项目里处于这些恢复观察状态的事项数；
    # 为零时仍是 0，不省略
    interrupted_count: int
    pending_verification_count: int
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
            pending_verification_count=observations.count(OBSERVATION_PENDING_VERIFICATION),
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
    # 建档中的项目还没有基线采纳：有进行中的建档事项时为 onboarding，否则为 awaiting_onboarding
    if state.source != "existing" or state.current_adoption is not None:
        return None
    if any(item.kind == "onboarding" and item.status == "in_progress" for item in state.work_items):
        return "onboarding"
    return "awaiting_onboarding"

# ---------------------------------------------------------------------------
# project.overview


class ProjectOverview(Contract):
    # 项目内的查询都接受事项范围参数：给出事项时只返回它（设计说明第 4.1 节）
    project_id: str
    work_item: str | None = None


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
    phase: str | None
    round: int
    stop_reason: str | None
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


def _project_overview(application: Application, request: ProjectOverview) -> Snapshot[ProjectOverviewResult]:
    store = application.system.store
    state = _project(application, request.project_id, include_history=False)
    items = ([_work_item(state, request.work_item)] if request.work_item is not None else state.work_items)
    return Snapshot[ProjectOverviewResult](
        position=store.end_position(),
        data=ProjectOverviewResult(
            project_id=state.project_id, name=state.name, goal=state.goal, version=state.stream_version,
            current_adoption=_adoption(state.current_adoption),
            stats=_work_item_stats(items),
            work_items=[
                WorkItemCard(
                    work_item_id=item.work_item_id, kind=item.kind, title=item.title, text=item.text, run_id=item.run_id,
                    version=item.stream_version, created_at=item.created_at, status=item.status,
                    department=item.department, phase=item.phase, round=item.cycle_count,
                    stop_reason=item.stop_reason, human_action=item.human_action,
                    pending_question=item.pending_question, adoption_id=item.adoption_id,
                    start_error=item.start_error,
                )
                for item in items
            ],
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
    if item is None:
        return None
    return AdoptionView(
        adoption_id=item.adoption_id, work_item_id=item.work_item_id, run_id=item.run_id, summary=item.summary,
        files=list(item.files), check_names=list(item.check_names), known_risks=list(item.known_risks),
        code_tree_digest=item.code_tree_digest, adopted_at=item.adopted_at, event_id=item.event_id,
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
    status: str
    department: str | None
    phase: str | None
    round: int
    started_at: str | None
    elapsed_sec: int | None
    time_limit_sec: int
    pending_question: str | None
    run_id: str
    adoption_id: str | None
    # 恢复观察状态（工单 #18）：运行中、中断、待核实、待恢复、已终止；run 没有创建时没有
    recovery_state: str | None
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
        run = _optional_run(application, item.run_id, through=through)
        bounds = store.run_time_bounds(item.run_id, through=through)
        rows.append(WorkItemLoop(
            work_item_id=item.work_item_id, kind=item.kind, sign=item.title, color_index=index + 1, status=item.status,
            department=item.department, phase=item.phase, round=item.cycle_count,
            started_at=None if bounds is None else bounds[0],
            elapsed_sec=None if bounds is None else _elapsed_seconds(bounds, terminal=run, now=at_time),
            time_limit_sec=item.run_time_limit_sec, pending_question=item.pending_question,
            run_id=item.run_id, adoption_id=item.adoption_id,
            recovery_state=_recovery_observation(application, item.run_id), version=item.stream_version,
        ))
    return Snapshot[ProjectLoopResult](
        position=_snapshot_position(store, through),
        data=ProjectLoopResult(project_id=state.project_id, work_items=rows,
                               adoptions=[_adoption(item) for item in state.adoptions]),
    )


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
    store = application.system.store
    artifacts = application.system.artifacts
    run_id = event.run_id
    loaded: dict[str, Any] = {}
    version = event.payload.get("git_version")
    if event.type in GIT_VERSION_EVENTS:
        if version is None:
            raise ValueError("该正式事件缺少 Git 版本记录")
        loaded["git_version"] = git_version_detail(
            application.system.git_versions, artifacts, store.list_events(run_id), event,
        )
    elif version is not None:
        raise ValueError("Git 版本未绑定正式事件")
    if event.type == EventType.DELIVERY_ACCEPTED:
        tree, archive = _delivery_archive(application, event)
        loaded["tree_archive"] = archive
        loaded["tree_files"] = [{"path": item.path, "size": len(item.data)} for item in tree.files]
    for name in ("prd", "plan"):
        ref = event.payload.get(f"{name}_ref")
        if ref:
            loaded[name] = artifacts.get_for_run(run_id, ArtifactRef(**ref)).decode("utf-8")
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
    guidance_id: str
    version: int
    text: str
    status: str
    applied_activation_id: str | None
    response_status: str | None
    response_text: str | None
    created_event_id: str


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
    phase: str | None
    active: bool
    department_setting: DepartmentSettingState
    setting: DepartmentSetting
    effective: EffectiveModel
    guidance: list[GuidanceRecord]
    messages: list[dict[str, Any]]
    context: dict[str, Any]
    last_call: dict[str, Any] | None
    reminders: list[str]


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


def _department_workspace(application: Application, request: DepartmentWorkspace
                          ) -> Snapshot[DepartmentWorkspaceResult]:
    store = application.system.store
    state = _project(application, request.project_id, include_history=False)
    item = None if request.work_item is None else _work_item(state, request.work_item)
    run = None if item is None else _optional_run(application, item.run_id)
    configured = state.department_settings[request.department]
    used_version = _last_used_prompt_version(run, request.department)
    effective = _effective_model(application, configured, request.department)
    guidance = [
        GuidanceRecord(
            guidance_id=value.id, version=value.version, text=value.text, status=value.status,
            applied_activation_id=value.applied_activation_id, response_status=value.response_status,
            response_text=value.response_text, created_event_id=value.created_event_id,
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
            run_id=None if run is None else run.run_id, phase=None if run is None else run.phase,
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
        ),
    )


MESSAGE_TYPES = (EventType.USER_INPUT_RECEIVED, EventType.DEPARTMENT_INPUT, EventType.MODEL_MESSAGE,
                 EventType.DEPARTMENT_GUIDANCE_RECEIVED)
MESSAGE_LIMIT = 100


def _department_messages(application: Application, run_id: str, department: str) -> list[dict[str, Any]]:
    # 部门消息：用户输入与这个部门的事件，按日志位置排列，取最近的一批。读取走部门与位置的索引
    store = application.system.store
    collected: list[Any] = []
    cursor = 0
    while True:
        batch = store.read(after=cursor, runs=(run_id,), departments=(department,), limit=200,
                           types=MESSAGE_TYPES)
        if not batch:
            break
        collected.extend(batch)
        cursor = batch[-1].position
    return [
        {
            "event_id": event.event_id, "position": event.position, "seq": event.stream_version,
            "type": event.type, "department": event.department, "created_at": event.created_at,
            "text": event.payload.get("text") or event.payload.get("summary") or "",
        }
        for event in collected[-MESSAGE_LIMIT:]
    ]


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
    registered_name: str | None
    registered_argv: list[str] | None
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


class RunActionsResult(Contract):
    actions: list[ActionView]


def _run_actions(application: Application, request: RunActions) -> Snapshot[RunActionsResult]:
    store = application.system.store
    _run(application, request.run_id)
    events = _tool_events(store, request.run_id)
    actions: list[ActionView] = []
    started: dict[tuple[str, int | None, str], Any] = {}
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
    # 有 tool_started、还没有结果的动作用运行状态区分（工单 #17，恢复契约第 1 节）：这次激活仍在进行
    # 的时候是运行中，否则是结果未知，等待核实
    live = _live_activations(events)
    for identity, event in started.items():
        actions.append(_action_view(None, identity, event, live=identity[0] in live))
    actions.sort(key=lambda item: item.created_at)
    return Snapshot[RunActionsResult](position=store.end_position(), data=RunActionsResult(actions=actions))


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
    # 动作后取自 tool_called）。result_event 为空表示只有 tool_started、还没有结果
    action_id = identity[2]
    if result_event is None:
        payload = {} if started_event is None else (started_event.payload or {})
        return ActionView(
            action_id=action_id, tool=str(payload.get("name") or ""),
            department=None if started_event is None else started_event.department,
            status="running" if live else "unknown",
            activation_id=payload.get("activation_id"), step_id=payload.get("step_id"),
            input_version=payload.get("input_version"), prompt_version=payload.get("prompt_version"),
            created_at="" if started_event is None else started_event.created_at, receipt=None,
            before_snapshot_ref=payload.get("before_snapshot_ref"),
        )
    payload = result_event.payload or {}
    if result_event.type == EventType.ACTION_VERIFIED:
        return ActionView(
            action_id=action_id, tool=str(payload.get("name") or ""), department=result_event.department,
            status="completed", activation_id=payload.get("activation_id"), step_id=payload.get("step_id"),
            input_version=payload.get("input_version"), prompt_version=payload.get("prompt_version"),
            created_at=result_event.created_at, receipt=None,
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
            registered_name=payload.get("registered_name") or started_payload.get("registered_name"),
            registered_argv=started_payload.get("registered_argv") or payload.get("registered_argv"),
            args=dict(payload.get("args") or started_payload.get("args") or {}), ok=ok, error=payload.get("error"),
            output_ref=payload.get("output_ref"), event_id=result_event.event_id,
            created_at=result_event.created_at,
        ),
        before_snapshot_ref=started_payload.get("before_snapshot_ref"),
        after_snapshot_ref=payload.get("after_snapshot_ref"),
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


class ProjectMaterial(Contract):
    material_id: str
    text: str
    department: str | None
    recorded_at: str
    event_id: str


class WorkItemMaterialsResult(Contract):
    work_item_id: str
    run_id: str
    contracts: list[VersionEntry]
    plans: list[VersionEntry]
    deliveries: list[VersionEntry]
    reviews: list[ReviewEntry]
    inputs: list[InputView]
    materials: list[ProjectMaterial]


def _work_item_materials(application: Application, request: WorkItemMaterials
                         ) -> Snapshot[WorkItemMaterialsResult]:
    store = application.system.store
    state = _project(application, request.project_id, include_history=False)
    item = _work_item(state, request.work_item)
    run = _run(application, item.run_id)
    versions = {entry["event_id"]: entry for entry in run.git_versions}
    return Snapshot[WorkItemMaterialsResult](
        position=store.end_position(),
        data=WorkItemMaterialsResult(
            work_item_id=item.work_item_id, run_id=run.run_id,
            contracts=[_version_entry(value.created_event_id, "contract", "active", value.revision,
                                      value.content_hash, None, []) for value in run.effective_contracts],
            plans=[_version_entry(value.created_event_id, "plan", value.status, value.revision,
                                  value.content_hash, value.objective, []) for value in run.engineering_plans],
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
        ),
    )


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
    values: dict[str, int | float | None] = {field: None for field in USAGE_FIELDS}
    reported = 0
    for row in rows:
        usage = json.loads(row["record"]).get("usage") or {}
        if usage.get("reported"):
            reported += 1
        for field in USAGE_FIELDS:
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


class CommandSetting(Contract):
    name: str
    version: int
    argv: list[str]
    args: list[str]
    timeout_sec: int
    output_limit: int


class SourceDirectorySetting(Contract):
    name: str
    path: str
    version: int


class ProjectSettingsResult(Contract):
    project_id: str
    name: str
    goal: str
    version: int
    pinned: bool
    archived: bool
    departments: dict[str, DepartmentSetting]
    commands: dict[str, CommandSetting]
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
            commands={
                name: CommandSetting(name=value.name, version=value.version, argv=list(value.argv),
                                     args=list(value.args), timeout_sec=value.timeout_sec,
                                     output_limit=value.output_limit)
                for name, value in state.commands.items()
            },
            source_directories={
                name: SourceDirectorySetting(name=value.name, path=value.path, version=value.version)
                for name, value in state.source_directories.items()
            },
            # 各部门生效模型（跟随部门默认时取部门默认）的建议能力提醒（设计说明第 5.6 节）
            department_reminders=application.system.facade.project_department_reminders(
                {department: {"model_id": setting.model_id} for department, setting in settings.items()}),
        ),
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
        raise ValueError("replay.check takes exactly one of run_id or project_id")
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
    # 一个事项的恢复观察状态（工单 #18，v8 设计说明第 7.2 节）：由 run 的事件、决定请求与投影的终态得出。
    # run 没有创建时没有恢复观察状态
    run = _optional_run(application, run_id)
    if run is None:
        return None
    events = application.system.store.list_events(run_id)
    decisions = _run_decisions(application, run_id)
    return observation_state(events, decisions.values(), terminal=run.phase in TERMINAL_PHASES)

class RecoveryStatus(Contract):
    # 恢复观察的汇总（工单 #18，设计说明第 4.3 节 system.status 的 3.1 部分）：服务重启后自动继续的事项数、
    # 待核实与待恢复的事项数、结果未知的动作数。数字取自事件日志与决定请求，
    # 与 run.recovery、projects.list 用同一份事实
    auto_resumed: int
    pending_verification: int
    waiting_resume: int
    unknown_actions: int

def recovery_status(application: Application) -> RecoveryStatus:
    # 恢复观察的汇总（工单 #18，system.status 的 recovery）：全部 run 按恢复观察状态计数，
    # 结果未知的动作数按未完成动作累加，自动继续的事项数取本次启动自动继续的 run（工单 #16）。
    # 只读取事件日志与决定请求，不写入，不调用模型
    store = application.system.store
    pending_verification = 0
    waiting_resume = 0
    unknown_actions = 0
    for run_id in store.list_run_ids():
        run = _optional_run(application, run_id)
        if run is None:
            continue
        events = store.list_events(run_id)
        decisions = _run_decisions(application, run_id)
        state = observation_state(events, decisions.values(), terminal=run.phase in TERMINAL_PHASES)
        if state == OBSERVATION_PENDING_VERIFICATION:
            pending_verification += 1
        elif state == OBSERVATION_WAITING_RESUME:
            waiting_resume += 1
        unknown_actions += len(unresolved_unknown_actions(events, decisions.values()))
    resumed = getattr(application.system, "resumed_runs", None)
    return RecoveryStatus(
        auto_resumed=0 if not resumed else len(resumed),
        pending_verification=pending_verification,
        waiting_resume=waiting_resume,
        unknown_actions=unknown_actions,
    )


# ---------------------------------------------------------------------------
# 查询登记


PROJECTS_LIST = QueryDefinition(
    name="projects.list", request=ProjectsList, result=ProjectList, handle=_projects_list,
    replayable=True,
    changed_by=(ProjectEventType.PROJECT_REGISTERED, ProjectEventType.PROJECT_RENAMED,
                ProjectEventType.PROJECT_GOAL_CHANGED,
                ProjectEventType.PROJECT_PINNED, ProjectEventType.PROJECT_ARCHIVED,
                ProjectEventType.PROJECT_RESTORED, ProjectEventType.WORK_ITEM_CREATED,
                ProjectEventType.WORK_ITEM_START_FAILED, ProjectEventType.DELIVERABLE_ADOPTED,
                ProjectEventType.ADOPTION_HELD, ProjectEventType.DEPARTMENT_SETTINGS_CONFIGURED,
                ProjectEventType.COMMAND_CONFIGURED, ProjectEventType.MATERIAL_RECORDED,
                EventType.TRANSITION, EventType.RUN_DONE, EventType.RUN_FAILED, EventType.RUN_PAUSED,
                EventType.RUN_CONTINUED, EventType.RUN_RESUMED, EventType.TOOL_STARTED, EventType.ACTION_VERIFIED,
                EventType.DECISION_REQUESTED, EventType.DECISION_ANSWERED, EventType.DECISION_WITHDRAWN),
)

PROJECT_OVERVIEW = QueryDefinition(
    name="project.overview", request=ProjectOverview, result=ProjectOverviewResult, handle=_project_overview,
    changed_by=(ProjectEventType.PROJECT_REGISTERED, ProjectEventType.PROJECT_RENAMED,
                ProjectEventType.PROJECT_GOAL_CHANGED,
                ProjectEventType.WORK_ITEM_CREATED, ProjectEventType.WORK_ITEM_START_FAILED,
                ProjectEventType.DELIVERABLE_ADOPTED, ProjectEventType.ADOPTION_HELD,
                EventType.TRANSITION, EventType.RUN_DONE, EventType.RUN_FAILED, EventType.RUN_PAUSED,
                EventType.RUN_CONTINUED,
                EventType.QA_SUBMITTED, EventType.DELIVERY_ACCEPTED, EventType.COLLABORATION_REQUESTED,
                EventType.COLLABORATION_RESPONDED, EventType.DECISION_REQUESTED),
)

PROJECT_LOOP = QueryDefinition(
    name="project.loop", request=ProjectLoop, result=ProjectLoopResult, handle=_project_loop,
    replayable=True,
    changed_by=(ProjectEventType.WORK_ITEM_CREATED, ProjectEventType.DELIVERABLE_ADOPTED,
                EventType.TRANSITION, EventType.RUN_CREATED, EventType.RUN_DONE, EventType.RUN_FAILED,
                EventType.RUN_PAUSED, EventType.RUN_CONTINUED, EventType.RUN_RESUMED, EventType.DEPARTMENT_ACTIVATED,
                EventType.COLLABORATION_REQUESTED, EventType.TOOL_STARTED, EventType.TOOL_CALLED,
                EventType.TOOL_SKIPPED, EventType.ACTION_VERIFIED, EventType.DECISION_REQUESTED,
                EventType.DECISION_ANSWERED, EventType.DECISION_WITHDRAWN),
)

PROJECT_FLOW = QueryDefinition(
    name="project.flow", request=ProjectFlow, result=ProjectFlowResult, handle=_project_flow,
    changed_by=(EventType.TRANSITION, EventType.COLLABORATION_REQUESTED, EventType.COLLABORATION_RESPONDED,
                EventType.COLLABORATION_CLOSED, EventType.QA_SUBMITTED),
)

WORK_ITEM_INPUTS = QueryDefinition(
    name="work_item.inputs", request=WorkItemInputs, result=WorkItemInputsResult, handle=_work_item_inputs,
    changed_by=(EventType.RUN_CREATED, EventType.USER_INPUT_RECEIVED, EventType.PRODUCT_INPUT_ASSIGNED),
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
                # 本项目的部门设置修改以后生效模型与来源随之更新（工单 #95 的验收）；
                # 目录修订（准入作废、连接修改）以后引用可用性随之更新
                ProjectEventType.DEPARTMENT_SETTINGS_CONFIGURED, CatalogEventType.CATALOG_REVISED),
)

RUN_ACTIONS = QueryDefinition(
    name="run.actions", request=RunActions, result=RunActionsResult, handle=_run_actions,
    changed_by=(EventType.TOOL_STARTED, EventType.TOOL_CALLED, EventType.TOOL_SKIPPED,
                EventType.ACTION_VERIFIED, EventType.DEPARTMENT_ACTIVATED, EventType.ACTIVATION_FINISHED),
)

WORK_ITEM_MATERIALS = QueryDefinition(
    name="work_item.materials", request=WorkItemMaterials, result=WorkItemMaterialsResult,
    handle=_work_item_materials,
    changed_by=(EventType.RUN_CREATED, EventType.USER_INPUT_RECEIVED, EventType.CONTRACT_ACCEPTED,
                EventType.PLAN_ACCEPTED, EventType.DELIVERY_ACCEPTED, EventType.QA_SUBMITTED,
                ProjectEventType.MATERIAL_RECORDED),
)

DELIVERY_FILE = QueryDefinition(
    name="delivery.file", request=DeliveryFile, result=DeliveryFileResult, handle=_delivery_file, changed_by=(),
)

PROJECT_ATTEMPTS = QueryDefinition(
    name="project.attempts", request=ProjectAttempts, result=ProjectAttemptsResult, handle=_project_attempts,
    changed_by=(EventType.CONTEXT_ASSEMBLED, EventType.MODEL_REQUESTED, EventType.MODEL_ATTEMPT_FINISHED,
                EventType.MODEL_ATTEMPT_FAILED, EventType.MODEL_RETRY_SCHEDULED),
)

PROJECT_USAGE = QueryDefinition(
    name="project.usage", request=ProjectUsage, result=UsageReport, handle=_project_usage,
    changed_by=(EventType.MODEL_ATTEMPT_FINISHED, EventType.MODEL_ATTEMPT_FAILED,
                EventType.MODEL_RETRY_SCHEDULED),
)

RUN_ATTEMPT = QueryDefinition(
    name="run.attempt", request=RunAttempt, result=RunAttemptResult, handle=_run_attempt,
    changed_by=(EventType.CONTEXT_ASSEMBLED, EventType.MODEL_REQUESTED, EventType.MODEL_ATTEMPT_FINISHED,
                EventType.MODEL_ATTEMPT_FAILED),
)

PROJECT_SETTINGS = QueryDefinition(
    name="project.settings", request=ProjectSettings, result=ProjectSettingsResult, handle=_project_settings,
    changed_by=(ProjectEventType.PROJECT_REGISTERED, ProjectEventType.PROJECT_RENAMED,
                ProjectEventType.PROJECT_GOAL_CHANGED,
                ProjectEventType.DEPARTMENT_SETTINGS_CONFIGURED, ProjectEventType.COMMAND_CONFIGURED,
                ProjectEventType.SOURCE_DIRECTORY_CONFIGURED,
                # 目录修订（准入作废、模型变更）以后生效模型的建议能力提醒随之更新（工单 #95）
                CatalogEventType.CATALOG_REVISED),
)

RUN_EXPORT = QueryDefinition(
    name="run.export", request=RunExport, result=RunExportResult, handle=_run_export, changed_by=(),
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
    repeatable: bool
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
    # 执行槽位在 3.4A 之前只有一个，holds_slot 表示这个 run 是否占用它
    epoch: int
    since: str
    holds_slot: bool

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

class RunRecoveryResult(Contract):
    # 一个事项的恢复观察（设计说明第 4.3 节）：恢复观察状态、待恢复原因、最后已确认位置、未完成动作、
    # 核实记录、下一项合法操作、继续执行是否可用及原因、限额、执行所有权与迟到结果
    work_item_id: str
    run_id: str
    state: Literal["running", "interrupted", "pending_verification", "waiting_resume", "terminated"]
    reason: str | None
    executable: bool
    last_confirmed_position: int
    last_confirmed_event_id: str | None
    unfinished_actions: list[UnfinishedAction]
    verifications: list[VerificationRecord]
    next_legal_action: str | None
    can_continue: bool
    cannot_continue_reason: str | None
    unusable: UnusableTarget | None
    limits: RecoveryLimits
    owner: RecoveryOwner | None
    late_results: list[LateResult]
    has_unknown_actions: bool

# 一个事项的恢复观察状态对应的下一项合法操作（v8 设计说明第 7.2 节）
_NEXT_ACTION = {
    OBSERVATION_RUNNING: "none",
    OBSERVATION_INTERRUPTED: "continue",
    OBSERVATION_PENDING_VERIFICATION: "verify_action",
    OBSERVATION_WAITING_RESUME: "repair_and_resume",
    OBSERVATION_TERMINATED: None,
}

def _run_recovery(application: Application, request: RunRecovery) -> Snapshot[RunRecoveryResult]:
    # 只读取：run 的事件与决定请求、投影与保存的限额计数。不写入，不触发结算，不调用模型与工具
    store = application.system.store
    run = _run(application, request.run_id)
    events = store.list_events(request.run_id)
    decisions = _run_decisions(application, request.run_id)
    terminal = run.phase in TERMINAL_PHASES
    state = observation_state(events, decisions.values(), terminal=terminal)
    # 已终止的 run 不再继续：未完成动作与未回答的核实请求不由恢复处理，只显示终止原因
    unfinished = [] if terminal else _unfinished_actions(events, decisions.values())
    verifications = _verification_records(events, decisions.values())
    resume_requests = [] if terminal else open_resume_decisions(decisions.values())
    unknown_requests = [] if terminal else open_decisions(decisions.values(), kind="unknown_action")
    return Snapshot[RunRecoveryResult](
        position=store.end_position(),
        data=RunRecoveryResult(
            work_item_id=run.work_item_id or "", run_id=run.run_id, state=state,
            reason=_recovery_reason(run, state, resume_requests),
            executable=not terminal,
            last_confirmed_position=store.end_position(), last_confirmed_event_id=run.last_event_id,
            unfinished_actions=unfinished, verifications=verifications,
            next_legal_action=_NEXT_ACTION[state],
            can_continue=_can_continue(state, terminal),
            cannot_continue_reason=_cannot_continue_reason(run, state, terminal, resume_requests),
            unusable=_unusable_target(resume_requests),
            limits=RecoveryLimits(activations=_activation_count(events),
                                  model_steps=_model_step_count(events),
                                  retries=_retry_count(events), cycle_count=run.cycle_count),
            owner=_owner(run, events, unknown_requests),
            # 迟到结果：3.1 的执行权在写入口拦住旧执行者的写入（write_path 的 claim_execution_right 与
            # StaleExecutionRight），被拒的写入不落盘，因此 3.1 没有迟到结果可列。远程执行代理上的迟到回执
            # 由 3.2C 在 run.actions 上补齐
            late_results=[],
            has_unknown_actions=bool(unfinished) or bool(unknown_requests),
        ),
    )

def _run_decisions(application: Application, run_id: str) -> dict[str, Any]:
    # 一个 run 流保存的决定请求，按身份：与事件在同一个事务中更新，重放只读取
    return load_decisions(application.system.store.projection(run_stream(run_id)))

def _recovery_reason(run: Any, state: str, resume_requests: list[Any]) -> str | None:
    # 恢复观察状态的说明：中断给出停止位置，待恢复给出无法使用的模型，待核实给出未完成动作数，
    # 已终止给出停止原因；运行中不需要说明
    if state == OBSERVATION_INTERRUPTED:
        return f"进程在 {run.phase} 阶段停止，等待启动时自动继续"
    if state == OBSERVATION_WAITING_RESUME and resume_requests:
        return str(resume_requests[0].request.get("description") or resume_requests[0].kind)
    if state == OBSERVATION_PENDING_VERIFICATION:
        return "有结果未知的动作，等待核实的决定请求回答"
    if state == OBSERVATION_TERMINATED:
        return f"运行以 {run.stop_reason or run.outcome} 结束"
    return None

def _can_continue(state: str, terminal: bool) -> bool:
    # 继续执行是否可用：已终止不可继续；运行中已经在执行；其余状态在用户处理（回答或修复）以后可继续
    if terminal:
        return False
    return state == OBSERVATION_RUNNING

def _cannot_continue_reason(run: Any, state: str, terminal: bool, resume_requests: list[Any]) -> str | None:
    # 继续执行不可用的原因
    if terminal:
        return f"运行已经结束：{run.stop_reason or run.outcome}"
    if state == OBSERVATION_WAITING_RESUME:
        return "模型引用无法使用或定义版本不同，等待用户回答决定请求"
    if state == OBSERVATION_PENDING_VERIFICATION:
        return "有结果未知的动作，等待核实以后继续"
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

def _unfinished_actions(events: list[Any], decisions: Any) -> list[UnfinishedAction]:
    # 未完成动作：结果未知的动作（tool_started 没有结果或核实记录）。未发送的动作由保存的模型响应
    # 给出，属于步骤驱动的补执行范围，读取侧只列出已经发出的动作
    action_ids = {identity[2] for identity in unresolved_unknown_actions(events, decisions)}
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
            repeatable=_action_repeatable(tool), before_snapshot_ref=payload.get("before_snapshot_ref"),
            created_at=event.created_at, started_event_id=event.event_id,
        ))
    unfinished.sort(key=lambda item: item.created_at)
    return unfinished

def _action_repeatable(tool_name: str) -> bool:
    tool = DEFINITIONS.tools.get(tool_name)
    return bool(tool is not None and tool.repeatable)

def _verification_records(events: list[Any], decisions: Any) -> list[VerificationRecord]:
    # 核实记录：action_verified 事件（用户选择按当前实际状态继续时追加）与已回答的核实请求一起列出。
    # 记录追加在动作之后，原始观察不改写
    answers = {decision.decision_id: decision for decision in decisions
               if decision.kind == "unknown_action" and decision.status == "answered"}
    records: list[VerificationRecord] = []
    for event in events:
        if event.type != EventType.ACTION_VERIFIED:
            continue
        payload = event.payload or {}
        decision_id = payload.get("decision_id")
        answer = answers.get(decision_id) if isinstance(decision_id, str) else None
        records.append(VerificationRecord(
            action_id=str(payload.get("id") or event.event_id), tool=str(payload.get("name") or ""),
            basis="用户选择按当前实际状态继续", result="动作效果按当前实际状态接受",
            decided_by="user", note=None if answer is None else (answer.answer or {}).get("note"),
            decision_id=decision_id if isinstance(decision_id, str) else None,
            at=event.created_at, event_id=event.event_id,
        ))
    records.sort(key=lambda item: item.at)
    return records

def _activation_count(events: list[Any]) -> int:
    return len([event for event in events if event.type == EventType.DEPARTMENT_ACTIVATED])

def _model_step_count(events: list[Any]) -> int:
    return len([event for event in events if event.type == EventType.MODEL_REQUESTED])

def _retry_count(events: list[Any]) -> int:
    return len([event for event in events if event.type == EventType.MODEL_RETRY_SCHEDULED])

def _owner(run: Any, events: list[Any], unknown_requests: list[Any]) -> RecoveryOwner | None:
    # 执行所有权：最后一次取得执行权的事件（run_resumed）给出编号与时间；没有恢复过时没有执行者。
    # 结果未知的动作还等待回答时不占用执行槽位（它没有在推进）
    resumed = [event for event in events if event.type == EventType.RUN_RESUMED]
    if not resumed:
        return None
    last = resumed[-1]
    return RecoveryOwner(epoch=int(last.payload.get("acquired_epoch") or 0), since=last.created_at,
                         holds_slot=not unknown_requests)

RUN_RECOVERY = QueryDefinition(
    name="run.recovery", request=RunRecovery, result=RunRecoveryResult, handle=_run_recovery,
    changed_by=(EventType.RUN_RESUMED, EventType.RUN_DONE, EventType.RUN_PAUSED, EventType.RUN_FAILED,
                EventType.TOOL_STARTED, EventType.TOOL_CALLED, EventType.TOOL_SKIPPED,
                EventType.ACTION_VERIFIED, EventType.DECISION_REQUESTED, EventType.DECISION_ANSWERED,
                EventType.DECISION_WITHDRAWN, EventType.DEPARTMENT_ACTIVATED, EventType.ACTIVATION_FINISHED),
)

PROJECT_QUERIES = (
    PROJECTS_LIST, PROJECT_OVERVIEW, PROJECT_LOOP, PROJECT_FLOW, WORK_ITEM_INPUTS, EVENT_DETAIL,
    DEPARTMENT_WORKSPACE, RUN_ACTIONS, WORK_ITEM_MATERIALS, DELIVERY_FILE, PROJECT_ATTEMPTS, PROJECT_USAGE,
    RUN_ATTEMPT, PROJECT_SETTINGS, RUN_EXPORT, REPLAY_CHECK, RUN_RECOVERY,
)
