# 试用记录的查询（工单 #152；浏览器与 computer use 设计说明「查询」 `run.trials`；应用层与接口层设计说明
# 「查询清单」；总图第四节「接口」缝）。
#
# 数据来源（2026-11-06，main 5083953e）：
# - 试用会话的开始与结束读 run 流的 `trial_session_started` / `trial_session_ended`（工单 #1183）；
# - 试用用例与它的步骤读运行状态投影里折叠出来的 `trial_cases`（工单 #1180）——用例与步骤都由这两类事件与
#   动作事件得出，这里不另外保存；步骤的输入、可访问性结构与浏览器会话身份读动作事件与结果工件；
# - 验收条件的原文读投影里当前 ProductSpec（引用形式见 docs/design/browser-and-computer-use.md「验收条件的引用」：`AC<序号>` 是验收条件在 ProductSpec
#   里的位置）；质检的会话与交付快照的比较读交付事件里的 `code_tree_digest`（会话开始时最近的那一份交付）；
# - 「收到这个结果的请求是否包含图像」读这个结果之后同一个激活的下一次模型请求的调用目标输入方式
#   （docs/design/browser-and-computer-use.md「请求中的图像」：不含图像时截图不进请求）。
#
# 查询只读取：不写事件、不改保存的投影。结果按部门列出（部门的顺序取自定义），会话按开始顺序，用例按打开
# 顺序；快照位置是事件日志末尾（与其他 run 查询相同）。

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal

from ..definitions import DEFINITIONS
from ..models import ArtifactRef, EventType
from ..projection import RunNotFoundError, project_run
from .contracts import Contract, Snapshot
from .project_queries import NotFound
from .registry import QueryDefinition

if TYPE_CHECKING:
    from .application import Application


# 读这个 run 的试用记录需要的事件种类：会话的开始与结束、步骤（动作的开始与结果、动作核实）、
# 收到结果的请求（输入方式）与交付（质检的会话按它给出交付快照的摘要）。用例本身取自运行状态投影
# （工单 #1180 由 `trial_case_opened` / `trial_case_concluded` 与这些动作事件折叠）
TRIAL_EVENT_TYPES = (
    EventType.TRIAL_SESSION_STARTED, EventType.TRIAL_SESSION_ENDED,
    EventType.TOOL_STARTED, EventType.TOOL_CALLED, EventType.ACTION_VERIFIED,
    EventType.MODEL_REQUESTED, EventType.DELIVERY_ACCEPTED,
)
_BATCH = 500


class RunTrials(Contract):
    run_id: str


class TrialCriterion(Contract):
    # 用例引用的一条验收条件：`AC<序号>` 与它在当前 ProductSpec 里的原文。原来的那份规格已经不在投影里
    # （被取代、或旧 run 没有这份规格）时原文为空，序号照旧给出
    criterion: str
    text: str | None


class TrialStepView(Contract):
    # 一个步骤：工具、输入（模型给出的调用参数）、结果状态、截图的工件引用、可访问性结构的摘录、
    # 收到这个结果的请求是否包含图像，以及它是不是用例的作为证据的步骤
    identity: str
    tool: str
    step_id: int | None = None
    activation_id: str = ""
    status: str
    ok: bool | None = None
    error: str | None = None
    input: dict[str, Any]
    screenshots: list[dict[str, Any]]
    accessibility: str | None = None
    request_had_images: bool | None = None
    evidence: bool = False


class TrialCaseView(Contract):
    # 质检的一个试用用例：引用的验收条件与原文、计划的操作与预期结果、实际步骤、结论与观察到的结果、
    # 作为证据的步骤（动作身份）
    case_id: str
    department: str
    # 部门会话（哪些动作是它的步骤）与试用会话（结束时用例结束为中断）两个身份
    session_id: str
    trial_session_id: str
    product_spec_hash: str
    criteria: list[TrialCriterion]
    title: str
    plan: list[str]
    expected: str
    status: str
    result: str | None = None
    observed: str = ""
    reason: str = ""
    evidence_steps: list[str]
    steps: list[TrialStepView]


class TrialSessionView(Contract):
    # 一个试用会话：种类、启动方式（质检的会话是交付说明里的名称）、试用副本的树摘要，核验角色的会话
    # 标明树摘要是否等于会话开始时最近的那一份交付快照；开始与结束、结束方式
    session_id: str
    department: str
    kind: str
    launch_name: str
    tree_digest: str
    source: str
    delivery_snapshot_hash: str | None = None
    matches_delivery_snapshot: bool | None = None
    started_at: str
    ended_at: str | None = None
    end_reason: str | None = None
    status: Literal["running", "ended"]


class TrialDepartmentView(Contract):
    # 一个部门的试用记录：会话与用例。查询按部门列出（页签直接读它
    department: str
    sessions: list[TrialSessionView]
    cases: list[TrialCaseView]


class RunTrialsResult(Contract):
    run_id: str
    departments: list[TrialDepartmentView]


def _run_events(store: Any, run_id: str) -> list[Any]:
    # 这个 run 的试用记录事件：按位置分批读到没有为止（与 project_queries._tool_events 同一做法，
    # 不扫整个日志）
    collected: list[Any] = []
    cursor = 0
    while True:
        batch = store.read(after=cursor, runs=(run_id,), limit=_BATCH, types=TRIAL_EVENT_TYPES)
        if not batch:
            break
        collected.extend(batch)
        cursor = batch[-1].position
    return collected


def _delivery_digests(events: list[Any]) -> list[tuple[int, str]]:
    # 交付事件的全局位置与快照树摘要：质检的会话按它比较试用副本是否等于交付快照
    return [(event.position, str((event.payload or {}).get("code_tree_digest") or ""))
            for event in events if event.type == EventType.DELIVERY_ACCEPTED]


def _session_views(events: list[Any]) -> list[TrialSessionView]:
    deliveries = _delivery_digests(events)
    started: dict[str, tuple[Any, dict[str, Any]]] = {}
    ended: dict[str, tuple[Any, dict[str, Any]]] = {}
    order: list[str] = []
    for event in events:
        payload = event.payload or {}
        session_id = str(payload.get("session_id") or "")
        if not session_id:
            continue
        if event.type == EventType.TRIAL_SESSION_STARTED:
            if session_id not in started:
                started[session_id] = (event, payload)
                order.append(session_id)
        elif event.type == EventType.TRIAL_SESSION_ENDED:
            ended.setdefault(session_id, (event, payload))

    views: list[TrialSessionView] = []
    for session_id in order:
        start_event, start = started[session_id]
        department = str(start.get("department") or start_event.department or "")
        # 核验角色的会话标明与交付快照的比较；其余部门的试用副本是运行工作区的副本，不做这一比较
        snapshot_hash: str | None = None
        matches: bool | None = None
        if DEFINITIONS.is_verifier(department):
            before = [(position, digest) for position, digest in deliveries
                      if position < start_event.position]
            snapshot_hash = before[-1][1] if before else None
            matches = None if snapshot_hash is None else str(start.get("tree_digest") or "") == snapshot_hash
        end = ended.get(session_id)
        views.append(TrialSessionView(
            session_id=session_id,
            department=department,
            kind=str(start.get("kind") or ""),
            launch_name=str(start.get("launch_name") or ""),
            tree_digest=str(start.get("tree_digest") or ""),
            source=str(start.get("source") or ""),
            delivery_snapshot_hash=snapshot_hash,
            matches_delivery_snapshot=matches,
            started_at=start_event.created_at,
            ended_at=None if end is None else end[0].created_at,
            end_reason=None if end is None else str(end[1].get("reason") or ""),
            status="running" if end is None else "ended",
        ))
    return views


def _criterion_text(spec: Any, criterion: str) -> str | None:
    # `AC<序号>` 指向当前 ProductSpec 里的位置（从 1 开始，docs/design/browser-and-computer-use.md「验收条件的引用」）；规格不在、序号越界或不是
    # 这种形式时原文为空，序号照旧给出
    if spec is None or not criterion.startswith("AC"):
        return None
    try:
        index = int(criterion[2:])
    except ValueError:
        return None
    criteria = list(getattr(spec, "acceptance_criteria", []) or [])
    return str(criteria[index - 1]) if 1 <= index <= len(criteria) else None


def _criterion_views(specs: dict[str, Any], case: Any) -> list[TrialCriterion]:
    spec = specs.get(case.product_spec_hash)
    return [TrialCriterion(criterion=criterion, text=_criterion_text(spec, criterion))
            for criterion in case.criteria]


def _matching_payload(entries: list[tuple[Any, dict[str, Any]]], step: Any
                      ) -> tuple[Any | None, dict[str, Any] | None]:
    # 一个步骤对应的动作事件（开始或结果）：按动作身份与步骤编号、激活核对，与投影折叠步骤的规则相同
    for event, payload in reversed(entries):
        if str(payload.get("id") or "") != step.identity:
            continue
        if step.step_id is not None and payload.get("step_id") is not None \
                and payload.get("step_id") != step.step_id:
            continue
        if step.activation_id and payload.get("activation_id") \
                and str(payload.get("activation_id")) != step.activation_id:
            continue
        return event, payload
    return None, None


def _accessibility(application: Application, run_id: str, output_ref: Any) -> str | None:
    # 步骤结果里的可访问性结构：结果工件里的 accessibility 摘录（浏览器工具的输出，docs/design/browser-and-computer-use.md「保存与绑定」）。
    # 取不出来时为空，不影响这一步的其他字段
    if not isinstance(output_ref, dict):
        return None
    try:
        raw = application.system.artifacts.get_for_run(run_id, ArtifactRef(**output_ref))
        output = json.loads(raw)
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        return None
    value = output.get("accessibility") if isinstance(output, dict) else None
    return value if isinstance(value, str) and value else None


def _request_had_images(requests: list[tuple[int, dict[str, Any]]], after: int,
                        activation_id: str) -> bool | None:
    # 收到这个结果的请求是否包含图像：这个结果之后同一个激活的下一次模型请求，按调用目标的输入方式判断。
    # 结果之后没有请求（激活结束、run 结束）时为空
    for position, payload in requests:
        if position <= after:
            continue
        if activation_id and str(payload.get("activation_id") or "") != activation_id:
            continue
        return "image" in (payload.get("input_modalities") or [])
    return None


def _case_view(application: Application, run_id: str, specs: dict[str, Any], case: Any,
               started: list[tuple[Any, dict[str, Any]]],
               called: list[tuple[Any, dict[str, Any]]],
               requests: list[tuple[int, dict[str, Any]]]) -> TrialCaseView:
    steps: list[TrialStepView] = []
    for step in case.steps:
        start_event, start = _matching_payload(started, step)
        result_event, result = _matching_payload(called, step)
        payload = result if result is not None else (start or {})
        position = 0 if result_event is None else result_event.position
        if result_event is None and start_event is not None:
            position = start_event.position
        steps.append(TrialStepView(
            identity=step.identity,
            tool=step.tool,
            step_id=step.step_id,
            activation_id=step.activation_id,
            status=step.status,
            ok=step.ok,
            error=step.error,
            input=dict(payload.get("args") or {}),
            screenshots=[dict(item) for item in step.screenshots],
            accessibility=_accessibility(application, run_id, payload.get("output_ref")),
            request_had_images=_request_had_images(requests, position, step.activation_id),
            evidence=step.identity in case.evidence_steps,
        ))
    return TrialCaseView(
        case_id=case.case_id,
        department=case.department,
        session_id=case.session_id,
        trial_session_id=case.trial_session_id,
        product_spec_hash=case.product_spec_hash,
        criteria=_criterion_views(specs, case),
        title=case.title,
        plan=list(case.plan),
        expected=case.expected,
        status=case.status,
        result=case.result,
        observed=case.observed,
        reason=case.reason,
        evidence_steps=list(case.evidence_steps),
        steps=steps,
    )


def _department_views(sessions: list[TrialSessionView], cases: list[TrialCaseView]
                      ) -> list[TrialDepartmentView]:
    # 按部门列出：部门的顺序取自定义（产品、工程、质检），定义里没有的部门排在后面
    groups: dict[str, list[TrialSessionView]] = {}
    case_groups: dict[str, list[TrialCaseView]] = {}
    for session in sessions:
        groups.setdefault(session.department, []).append(session)
    for case in cases:
        case_groups.setdefault(case.department, []).append(case)
    names = [department for department in DEFINITIONS.departments
             if department in groups or department in case_groups]
    names.extend(sorted((set(groups) | set(case_groups)) - set(names)))
    return [TrialDepartmentView(department=name, sessions=groups.get(name, []),
                                cases=case_groups.get(name, []))
            for name in names]


def _run_trials(application: Application, request: RunTrials) -> Snapshot[RunTrialsResult]:
    store = application.system.store
    try:
        run = project_run(store, request.run_id)
    except RunNotFoundError:
        raise NotFound(f"run not found: {request.run_id}") from None
    events = _run_events(store, request.run_id)
    sessions = _session_views(events)
    specs = {spec.content_hash: spec for spec in run.product_specs}
    started = [(event, event.payload or {}) for event in events if event.type == EventType.TOOL_STARTED]
    called = [(event, event.payload or {}) for event in events if event.type == EventType.TOOL_CALLED]
    requests = [(event.position, event.payload or {}) for event in events
                if event.type == EventType.MODEL_REQUESTED]
    cases = [_case_view(application, request.run_id, specs, case, started, called, requests)
             for case in run.trial_cases]
    return Snapshot[RunTrialsResult](
        position=store.end_position(),
        data=RunTrialsResult(run_id=request.run_id, departments=_department_views(sessions, cases)),
    )


RUN_TRIALS = QueryDefinition(
    name="run.trials", request=RunTrials, result=RunTrialsResult, handle=_run_trials,
    # 会话与用例的开始结束改变列表；动作的开始、结果与核实改变步骤；下一次模型请求的输入方式改变
    # 「收到这个结果的请求是否包含图像」；规格被接纳改变验收条件的原文；交付到达改变质检会话比较的
    # 交付快照
    changed_by=(EventType.TRIAL_SESSION_STARTED, EventType.TRIAL_SESSION_ENDED,
                EventType.TRIAL_CASE_OPENED, EventType.TRIAL_CASE_CONCLUDED,
                EventType.TOOL_STARTED, EventType.TOOL_CALLED, EventType.ACTION_VERIFIED,
                EventType.MODEL_REQUESTED, EventType.SPEC_ACCEPTED, EventType.DELIVERY_ACCEPTED),
)

__all__ = [
    "RunTrials",
    "RunTrialsResult",
    "TRIAL_EVENT_TYPES",
    "TrialCaseView",
    "TrialCriterion",
    "TrialDepartmentView",
    "TrialSessionView",
    "TrialStepView",
    "_run_trials",
]
