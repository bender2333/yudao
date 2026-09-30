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
from ..models import (
    ArtifactRef, DEPARTMENTS, EventType, GIT_VERSION_EVENTS, ProjectEventType, hash_bytes,
)
from ..observability import ObservabilityQuery
from ..projection import (
    RunNotFoundError, project_run, replay_decisions, replay_project, replay_run, load_decisions, saved_project,
)
from ..projects import ProjectNotFoundError, project_projection
from ..replay_check import ReplayIntegrityError, verify_replay
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
    active_work_item_id: str | None
    current_adoption: str | None


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
        rows.append(ProjectRow(
            project_id=state.project_id, name=state.name, goal=state.goal, source=state.source,
            pinned=state.pinned, archived=state.archived, created_at=state.created_at,
            updated_at=state.updated_at, version=state.stream_version, work_item_count=len(state.work_items),
            in_progress_count=sum(item.status == "in_progress" for item in state.work_items),
            active_work_item_id=state.active_work_item_id,
            current_adoption=None if state.current_adoption is None else state.current_adoption.adoption_id,
        ))
    return Snapshot[ProjectList](position=_snapshot_position(store, through), data=ProjectList(projects=rows))


# ---------------------------------------------------------------------------
# project.overview


class ProjectOverview(Contract):
    # 项目内的查询都接受事项范围参数：给出事项时只返回它（设计说明第 4.1 节）
    project_id: str
    work_item: str | None = None


class WorkItemCard(Contract):
    work_item_id: str
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
                    work_item_id=item.work_item_id, title=item.title, text=item.text, run_id=item.run_id,
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
            work_item_id=item.work_item_id, sign=item.title, color_index=index + 1, status=item.status,
            department=item.department, phase=item.phase, round=item.cycle_count,
            started_at=None if bounds is None else bounds[0],
            elapsed_sec=None if bounds is None else _elapsed_seconds(bounds, terminal=run, now=at_time),
            time_limit_sec=item.run_time_limit_sec, pending_question=item.pending_question,
            run_id=item.run_id, adoption_id=item.adoption_id, version=item.stream_version,
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


class DepartmentPromptState(Contract):
    department: str
    configured_version: int
    configured_text: str
    source: str
    used_version: int | None
    used_event_id: str | None


class GuidanceRecord(Contract):
    guidance_id: str
    version: int
    text: str
    status: str
    applied_activation_id: str | None
    response_status: str | None
    response_text: str | None
    created_event_id: str


class DepartmentWorkspaceResult(Contract):
    project_id: str
    department: str
    work_item_id: str | None
    run_id: str | None
    phase: str | None
    active: bool
    prompt: DepartmentPromptState
    guidance: list[GuidanceRecord]
    messages: list[dict[str, Any]]
    context: dict[str, Any]
    last_call: dict[str, Any] | None
    provider: dict[str, Any] | None
    reminders: list[str]


def _department_workspace(application: Application, request: DepartmentWorkspace
                          ) -> Snapshot[DepartmentWorkspaceResult]:
    store = application.system.store
    state = _project(application, request.project_id, include_history=False)
    item = None if request.work_item is None else _work_item(state, request.work_item)
    run = None if item is None else _optional_run(application, item.run_id)
    configured = state.prompt_configs[request.department]
    used = None if run is None else run.department_prompts.get(request.department)
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
            prompt=DepartmentPromptState(
                department=request.department, configured_version=configured.version,
                configured_text=configured.text, source=configured.source,
                used_version=None if used is None else used.version,
                used_event_id=None if used is None else used.created_event_id,
            ),
            guidance=guidance, messages=messages, context=context,
            last_call=_last_call(run, request.department),
            provider=None if run is None else run.provider_bindings.get(request.department),
            reminders=[],
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
    status: Literal["running", "completed", "failed"]
    activation_id: str | None
    step_id: int | None
    input_version: int | None
    prompt_version: int | None
    created_at: str
    receipt: ActionReceipt | None


class RunActionsResult(Contract):
    actions: list[ActionView]


def _run_actions(application: Application, request: RunActions) -> Snapshot[RunActionsResult]:
    store = application.system.store
    _run(application, request.run_id)
    actions: list[ActionView] = []
    started: dict[str, Any] = {}
    for event in _tool_events(store, request.run_id):
        payload = event.payload or {}
        if payload.get("name") == "provider_usage":
            continue
        action_id = str(payload.get("id") or event.event_id)
        if event.type == EventType.TOOL_STARTED:
            started[action_id] = event
            continue
        started_event = started.pop(action_id, None)
        actions.append(_action_view(event, action_id, started_event, completed=True))
    for action_id, event in started.items():
        actions.append(_action_view(event, action_id, None, completed=False))
    actions.sort(key=lambda item: item.created_at)
    return Snapshot[RunActionsResult](position=store.end_position(), data=RunActionsResult(actions=actions))


def _tool_events(store: Any, run_id: str) -> list[Any]:
    # 一个 run 的工具事件：按位置反复读取到没有为止（按 run 与位置的索引，不是整个日志的扫描）
    collected: list[Any] = []
    cursor = 0
    while True:
        batch = store.read(after=cursor, runs=(run_id,), limit=500,
                           types=(EventType.TOOL_STARTED, EventType.TOOL_CALLED, EventType.TOOL_SKIPPED))
        if not batch:
            break
        collected.extend(batch)
        cursor = batch[-1].position
    return collected


def _action_view(event: Any, action_id: str, started_event: Any, *, completed: bool) -> ActionView:
    payload = event.payload or {}
    started_payload = {} if started_event is None else started_event.payload
    if not completed:
        return ActionView(
            action_id=action_id, tool=str(payload.get("name") or ""), department=event.department,
            status="running", activation_id=payload.get("activation_id"), step_id=payload.get("step_id"),
            input_version=payload.get("input_version"), prompt_version=payload.get("prompt_version"),
            created_at=event.created_at, receipt=None,
        )
    ok = bool(payload.get("ok"))
    return ActionView(
        action_id=action_id, tool=str(payload.get("name") or started_payload.get("name") or ""),
        department=event.department, status="completed" if ok else "failed",
        activation_id=payload.get("activation_id"), step_id=payload.get("step_id"),
        input_version=payload.get("input_version"), prompt_version=payload.get("prompt_version"),
        created_at=event.created_at,
        receipt=ActionReceipt(
            registered_name=started_payload.get("registered_name") or payload.get("registered_name"),
            registered_argv=started_payload.get("registered_argv"),
            args=dict(payload.get("args") or started_payload.get("args") or {}),
            ok=ok, error=payload.get("error"), output_ref=payload.get("output_ref"),
            event_id=event.event_id, created_at=event.created_at,
        ),
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
    department: str
    version: int
    text: str
    source: str


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


def _project_settings(application: Application, request: ProjectSettings) -> Snapshot[ProjectSettingsResult]:
    store = application.system.store
    state = _project(application, request.project_id, include_history=False)
    return Snapshot[ProjectSettingsResult](
        position=store.end_position(),
        data=ProjectSettingsResult(
            project_id=state.project_id, name=state.name, goal=state.goal, version=state.stream_version,
            pinned=state.pinned, archived=state.archived,
            departments={
                department: DepartmentSetting(department=department, version=state.prompt_configs[department].version,
                                              text=state.prompt_configs[department].text,
                                              source=state.prompt_configs[department].source)
                for department in DEPARTMENTS
            },
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


# ---------------------------------------------------------------------------
# 查询登记


PROJECTS_LIST = QueryDefinition(
    name="projects.list", request=ProjectsList, result=ProjectList, handle=_projects_list,
    replayable=True,
    changed_by=(ProjectEventType.PROJECT_REGISTERED, ProjectEventType.PROJECT_RENAMED,
                ProjectEventType.PROJECT_PINNED, ProjectEventType.PROJECT_ARCHIVED,
                ProjectEventType.PROJECT_RESTORED, ProjectEventType.WORK_ITEM_CREATED,
                ProjectEventType.WORK_ITEM_START_FAILED, ProjectEventType.DELIVERABLE_ADOPTED,
                ProjectEventType.ADOPTION_HELD, ProjectEventType.DEPARTMENT_PROMPT_CONFIGURED,
                ProjectEventType.COMMAND_CONFIGURED, ProjectEventType.MATERIAL_RECORDED,
                EventType.TRANSITION, EventType.RUN_DONE, EventType.RUN_FAILED, EventType.RUN_PAUSED),
)

PROJECT_OVERVIEW = QueryDefinition(
    name="project.overview", request=ProjectOverview, result=ProjectOverviewResult, handle=_project_overview,
    changed_by=(ProjectEventType.PROJECT_REGISTERED, ProjectEventType.PROJECT_RENAMED,
                ProjectEventType.WORK_ITEM_CREATED, ProjectEventType.WORK_ITEM_START_FAILED,
                ProjectEventType.DELIVERABLE_ADOPTED, ProjectEventType.ADOPTION_HELD,
                EventType.TRANSITION, EventType.RUN_DONE, EventType.RUN_FAILED, EventType.RUN_PAUSED,
                EventType.QA_SUBMITTED, EventType.DELIVERY_ACCEPTED, EventType.COLLABORATION_REQUESTED,
                EventType.COLLABORATION_RESPONDED, EventType.DECISION_REQUESTED),
)

PROJECT_LOOP = QueryDefinition(
    name="project.loop", request=ProjectLoop, result=ProjectLoopResult, handle=_project_loop,
    replayable=True,
    changed_by=(ProjectEventType.WORK_ITEM_CREATED, ProjectEventType.DELIVERABLE_ADOPTED,
                EventType.TRANSITION, EventType.RUN_CREATED, EventType.RUN_DONE, EventType.RUN_FAILED,
                EventType.RUN_PAUSED, EventType.DEPARTMENT_ACTIVATED, EventType.COLLABORATION_REQUESTED),
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
    changed_by=(EventType.DEPARTMENT_PROMPT_UPDATED, EventType.DEPARTMENT_GUIDANCE_RECEIVED,
                EventType.DEPARTMENT_GUIDANCE_APPLIED, EventType.DEPARTMENT_GUIDANCE_RESPONDED,
                EventType.DEPARTMENT_ACTIVATED, EventType.MODEL_REQUESTED, EventType.MODEL_MESSAGE,
                EventType.CONTEXT_ASSEMBLED, EventType.COMPACTION_RECORDED, EventType.USER_INPUT_RECEIVED,
                EventType.DEPARTMENT_INPUT),
)

RUN_ACTIONS = QueryDefinition(
    name="run.actions", request=RunActions, result=RunActionsResult, handle=_run_actions,
    changed_by=(EventType.TOOL_STARTED, EventType.TOOL_CALLED, EventType.TOOL_SKIPPED),
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
                ProjectEventType.DEPARTMENT_PROMPT_CONFIGURED, ProjectEventType.COMMAND_CONFIGURED,
                ProjectEventType.SOURCE_DIRECTORY_CONFIGURED),
)

RUN_EXPORT = QueryDefinition(
    name="run.export", request=RunExport, result=RunExportResult, handle=_run_export, changed_by=(),
)

REPLAY_CHECK = QueryDefinition(
    name="replay.check", request=ReplayCheck, result=ReplayCheckResult, handle=_replay_check, changed_by=(),
)

PROJECT_QUERIES = (
    PROJECTS_LIST, PROJECT_OVERVIEW, PROJECT_LOOP, PROJECT_FLOW, WORK_ITEM_INPUTS, EVENT_DETAIL,
    DEPARTMENT_WORKSPACE, RUN_ACTIONS, WORK_ITEM_MATERIALS, DELIVERY_FILE, PROJECT_ATTEMPTS, PROJECT_USAGE,
    RUN_ATTEMPT, PROJECT_SETTINGS, RUN_EXPORT, REPLAY_CHECK,
)
