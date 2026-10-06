# 状态投影：运行状态投影由 run 流的事件折叠而成，项目投影由项目流的事件折叠而成，决定请求由所在流中的
# 请求、回答与撤销事件折叠而成。Agent 不能写投影。
# 投影随写入保存（写入口在追加事件的同一个事务中更新），读取时直接读取保存的投影；
# 从头重放只用于重建保存的投影与核对它与重放结果一致。

from __future__ import annotations

from dataclasses import replace
from typing import Any

from pydantic import TypeAdapter

from .definitions import DEFINITIONS
from .event_store import (
    EventStore, SavedDecision, SavedProjection, is_catalog_stream, is_run_stream, project_stream, run_stream,
)
from .models import (
    Adoption,
    CatalogEvent,
    CatalogEventType,
    CatalogProjection,
    CollaborationRequest,
    CollaborationResponse,
    DecisionRequest,
    DEPARTMENT_LABELS,
    DepartmentGuidance,
    DepartmentSetting,
    ArtifactRef,
    ContextExclusion,
    ContextManifest,
    ContextSource,
    DeliverySpec,
    EffectiveContract,
    EngineeringPlan,
    Defect,
    Event,
    EventType,
    GIT_VERSION_EVENTS,
    HeldCandidate,
    LessonCandidate,
    Material,
    ProductDecision,
    ProductSpec,
    ProjectEvent,
    ProjectEventType,
    ProjectProjection,
    QAReview,
    RegisteredCommand,
    RunProjection,
    SessionRecord,
    SourceDirectory,
    UserInput,
    TERMINAL_PHASES,
    WorkItem,
    department_for_phase,
    waiting_reason_for,
)

Projection = RunProjection | ProjectProjection | CatalogProjection

# 保存的投影以 JSON 存放，由 pydantic 按数据类的类型序列化与还原
_RUN_STATE = TypeAdapter(RunProjection)
_PROJECT_STATE = TypeAdapter(ProjectProjection)
_CATALOG_STATE = TypeAdapter(CatalogProjection)
_DECISION_STATE = TypeAdapter(DecisionRequest)

DECISION_EVENTS = frozenset({EventType.DECISION_REQUESTED, EventType.DECISION_ANSWERED, EventType.DECISION_WITHDRAWN})


class RunNotFoundError(KeyError):
    pass


def project_run(store: EventStore, run_id: str) -> RunProjection:
    # 读取保存的运行状态投影
    saved = store.projection(run_stream(run_id))
    if saved is None:
        raise RunNotFoundError(run_id)
    return _RUN_STATE.validate_json(saved.state)


def saved_project(store: EventStore, project_id: str) -> ProjectProjection | None:
    # 读取保存的项目投影；项目不存在时为空
    saved = store.projection(project_stream(project_id))
    return None if saved is None else _PROJECT_STATE.validate_json(saved.state)


def replay_run(store: EventStore, run_id: str, *, through: int | None = None) -> RunProjection:
    # 从 run 流的第一条事件重放运行状态投影：只用于重建、核对与按位置读取（through 给出全局位置的上界）
    events = store.list_events(run_id, through_position=through)
    if not events:
        raise RunNotFoundError(run_id)
    return project_events(events)


def replay_project(store: EventStore, project_id: str, *, through: int | None = None) -> ProjectProjection | None:
    # 从项目流的第一条事件重放项目投影：只用于重建、核对与按位置读取（through 给出全局位置的上界）
    events = store.list_project_events(project_id, through_position=through)
    return replay(project_stream(project_id), events) if events else None


def empty_projection(stream: str) -> Projection:
    if is_run_stream(stream):
        return RunProjection()
    if is_catalog_stream(stream):
        return CatalogProjection()
    return ProjectProjection()


def load_projection(saved: SavedProjection, stream: str) -> Projection:
    if is_run_stream(stream):
        adapter = _RUN_STATE
    elif is_catalog_stream(stream):
        adapter = _CATALOG_STATE
    else:
        adapter = _PROJECT_STATE
    return adapter.validate_json(saved.state)


def dump_projection(state: Projection) -> str:
    if isinstance(state, RunProjection):
        adapter = _RUN_STATE
    elif isinstance(state, CatalogProjection):
        adapter = _CATALOG_STATE
    else:
        adapter = _PROJECT_STATE
    return adapter.dump_json(state).decode("utf-8")


def fold(state: Projection, event: Event | ProjectEvent | CatalogEvent) -> None:
    # 把一条事件并入投影；并入以后的投影与从头重放到这条事件的结果相同
    if isinstance(event, Event):
        apply_event(state, event)
        _settle_run_state(state)
    elif isinstance(event, CatalogEvent):
        apply_catalog_event(state, event)
    else:
        apply_project_event(state, event)


def apply_catalog_event(state: CatalogProjection, event: CatalogEvent) -> None:
    # 目录投影只记最后一条事件与最后一条 catalog_revised 的修订号；目录内容仍由 Provider 模块保存。
    # home_seen 另记用户查看过的全局位置与时间（工单 #127），控制主机上只有一个
    state.last_event_id = event.event_id
    state.stream_version = event.stream_version
    state.updated_at = event.created_at
    if event.type == CatalogEventType.CATALOG_REVISED:
        state.revision = int(event.payload["revision"])
    elif event.type == CatalogEventType.HOME_SEEN:
        state.last_seen_position = int(event.payload["position"])
        state.last_seen_at = event.created_at


def replay(stream: str, events: list[Event] | list[ProjectEvent] | list[CatalogEvent]) -> Projection:
    state = empty_projection(stream)
    for event in events:
        fold(state, event)
    return state


def project_events(events: list[Event]) -> RunProjection:
    state = RunProjection()
    for event in events:
        apply_event(state, event)
    _settle_run_state(state)
    return state


# ---------------------------------------------------------------------------
# 决定请求：由请求、回答与撤销三种事件折叠而成，每个决定请求另存一份投影，与事件在同一事务中更新


def saved_decision(store: EventStore, decision_id: str) -> DecisionRequest | None:
    # 按身份读取一个决定请求保存的投影；没有时为空
    saved = store.decision(decision_id)
    return None if saved is None else load_decision(saved)


def saved_decisions(store: EventStore, *, projects: tuple[str, ...] = (), work_items: tuple[str, ...] = (),
                    kinds: tuple[str, ...] = (), statuses: tuple[str, ...] = ()) -> tuple[int, list[DecisionRequest]]:
    # 按项目、事项、种类与状态列出决定请求保存的投影，与它们所反映的日志末尾位置
    position, rows = store.decisions(projects=projects, work_items=work_items, kinds=kinds, statuses=statuses)
    return position, [load_decision(row) for row in rows]


def load_decision(saved: SavedDecision) -> DecisionRequest:
    return _DECISION_STATE.validate_json(saved.state)


def load_decisions(saved: SavedProjection | None) -> dict[str, DecisionRequest]:
    # 一个流保存的决定请求，按身份
    return {} if saved is None else {item.decision_id: load_decision(item) for item in saved.decisions}


def dump_decision(decision: DecisionRequest) -> SavedDecision:
    return SavedDecision(decision.decision_id, decision.stream, decision.project_id, decision.work_item_id,
                         decision.run_id, decision.kind, decision.status,
                         _DECISION_STATE.dump_json(decision).decode("utf-8"))


def apply_decision_event(decisions: dict[str, DecisionRequest], event: Event | ProjectEvent) -> str | None:
    # 把一条事件并入这个流的决定请求，返回改变的决定请求的身份；不是决定事件时什么也不改变，返回空
    payload = event.payload
    if event.type == EventType.DECISION_REQUESTED:
        decisions[event.event_id] = DecisionRequest(
            decision_id=event.event_id, stream=event.stream, run_id=event.run_id, project_id=event.project_id,
            work_item_id=event.work_item_id, requested_at=event.created_at, request=dict(payload),
        )
        return event.event_id
    if event.type == EventType.DECISION_ANSWERED:
        decision = decisions[payload["decision_id"]]
        decision.status = "answered"
        decision.answer = {"event_id": event.event_id, "option": payload["option"], "note": payload["note"],
                           "base_version": payload["base_version"], "actor": event.actor,
                           "command_id": event.command_id, "answered_at": event.created_at}
        return decision.decision_id
    if event.type == EventType.DECISION_WITHDRAWN:
        decision = decisions[payload["decision_id"]]
        decision.status = "withdrawn"
        decision.withdrawal = {"event_id": event.event_id, "reason": payload["reason"],
                               "withdrawn_at": event.created_at}
        return decision.decision_id
    return None


def replay_decisions(events: list[Event] | list[ProjectEvent]) -> dict[str, DecisionRequest]:
    decisions: dict[str, DecisionRequest] = {}
    for event in events:
        apply_decision_event(decisions, event)
    return decisions


def _settle_run_state(state: RunProjection) -> None:
    # 由阶段、停止原因与待处理的协作请求得出的字段；可以重复计算，结果只取决于这些字段
    state.waiting_reason = waiting_reason_for(state.phase, state.stop_reason)
    if state.pending_request is not None:
        state.waiting_reason = f"{DEPARTMENT_LABELS[state.pending_request.recipient]}部门正在处理来自{DEPARTMENT_LABELS[state.pending_request.requester]}部门的请求"
    if state.phase in TERMINAL_PHASES:
        state.outcome = {"DONE": "done", "PAUSED": "paused", "FAILED": "failed"}[state.phase]
        state.active_department = None


def apply_event(state: RunProjection, event: Event) -> None:
    state.last_event_id = event.event_id
    state.stream_version = event.stream_version
    payload = event.payload
    etype = event.type
    if etype in GIT_VERSION_EVENTS and payload.get("git_version") is not None:
        revision = dict(payload["git_version"])
        if state.git_version is None or revision["commit"] != state.git_version["commit"]:
            state.git_versions.append({"event_id": event.event_id, "type": etype, **revision})
        state.git_version = revision
    if payload.get("request_id") and etype in {
        EventType.TOOL_CALLED, EventType.SPEC_ACCEPTED, EventType.PRODUCT_DECISION_ACCEPTED,
        EventType.PLAN_ACCEPTED, EventType.DELIVERY_ACCEPTED, EventType.CONTRACT_ACCEPTED,
    } and payload.get("name") != "provider_usage":
        state.request_results.append({"event_id": event.event_id, "type": etype, "request_id": payload["request_id"],
                                      "department": event.department, "name": payload.get("name"),
                                      "ok": payload.get("ok"),
                                      "content_hash": payload.get("content_hash")})
    if event.provider and etype not in {
            EventType.DEPARTMENT_ACTIVATED,
            EventType.CONTEXT_ASSEMBLED,
            EventType.MODEL_REQUESTED,
            EventType.MODEL_ATTEMPT_FAILED,
            EventType.MODEL_RETRY_SCHEDULED,
    }:
        state.provider = event.provider
    if event.model and etype not in {
            EventType.DEPARTMENT_ACTIVATED,
            EventType.CONTEXT_ASSEMBLED,
            EventType.MODEL_REQUESTED,
            EventType.MODEL_ATTEMPT_FAILED,
            EventType.MODEL_RETRY_SCHEDULED,
    }:
        state.provider = event.provider or state.provider
        state.model = event.model
        state.actual_provider = event.provider or state.actual_provider
        state.actual_model = event.model
        _bind_actual_model(state, event)

    if etype == EventType.RUN_CREATED:
        state.run_id = event.run_id
        state.task = payload["task"]
        state.intend_ref = payload["intend_ref"]
        initial = _input_from_payload(payload["initial_input"], event)
        state.inputs.append(initial)
        state.input_version = initial.version
        state.product_work_input_version = initial.version
        state.phase = event.state_after
        state.max_cycles = int(payload["max_cycles"])
        state.run_time_limit_sec = int(payload["run_time_limit_sec"])
        state.context_window = int(payload.get("context_window", 32_000))
        state.provider = payload.get("provider", "fake")
        state.adapter = payload["adapter"]
        state.sessions = {
            department: SessionRecord(session_id=session_id, department=department, status="idle")
            for department, session_id in payload.get("sessions", {}).items()
        }
        state.project_id = payload["project_id"]
        state.work_item_id = payload["work_item_id"]
        state.baseline = payload["baseline"]
        state.snapshot = payload.get("snapshot")
        state.workspace_digest = payload["workspace_digest"]
        state.project_context_ref = payload["project_context_ref"]
        state.prompt_config_versions = dict(payload["prompt_config_versions"])
        state.registered_commands = dict(payload.get("registered_commands") or {})
        state.command_versions = dict(payload.get("command_versions") or {})
        # 创建这个 run 时记录的 run 事件版本；旧事件没有这个字段时为 0，与当前版本不同（ADR-0019）
        state.run_event_version = int(payload.get("run_event_version", 0))
        # 创建这个 run 时记录的定义版本；旧事件没有这个字段时为空（ADR-0014）
        state.definitions_version = str(payload.get("definitions_version", ""))
        # 事项种类与仓库概况：旧 run 的创建事件没有这两个字段，种类按普通事项理解（工单 #134）
        state.kind = str(payload.get("kind", "change"))
        state.overview_ref = payload.get("overview_ref")
        return

    if etype == EventType.USER_INPUT_RECEIVED:
        received = _input_from_payload(payload, event)
        state.inputs.append(received)
        state.input_version = received.version
        state.task += received.text
        state.intend_ref = payload["intend_ref"]
        return

    if etype == EventType.PRODUCT_INPUT_ASSIGNED:
        state.product_work_input_version = payload["through_version"]
        state.phase = "PRODUCT_SPEC"
        state.active_department = "product"
        return

    if etype == EventType.DEPARTMENT_GUIDANCE_RECEIVED:
        state.department_guidance.append(_guidance_from_payload(payload, event))
        return

    if etype == EventType.DEPARTMENT_GUIDANCE_APPLIED:
        ids = set(payload.get("guidance_ids", []))
        for index, guidance in enumerate(state.department_guidance):
            if guidance.id in ids and guidance.status in {"received", "in_input"}:
                state.department_guidance[index] = replace(
                    guidance,
                    status="in_input",
                    applied_activation_id=payload.get("activation_id"),
                    applied_context_event_id=payload.get("context_event_id"),
                )
        return

    if etype == EventType.DEPARTMENT_GUIDANCE_RESPONDED:
        guidance_id = payload.get("guidance_id")
        for index, guidance in enumerate(state.department_guidance):
            if guidance.id == guidance_id:
                state.department_guidance[index] = replace(
                    guidance,
                    status=payload.get("status", "needs_work"),
                    response_event_id=event.event_id,
                    response_status=payload.get("status"),
                    response_text=payload.get("text"),
                )
                break
        return

    if etype == EventType.DEPARTMENT_ACTIVATED:
        state.cycle_count += 1
        state.active_department = event.department
        session = state.sessions.get(event.department or "")
        if session:
            session.activations += 1
            session.status = "active"
        activation_id = payload.get("activation_id")
        if event.department and activation_id:
            state.last_activations[event.department] = str(activation_id)
        incoming = payload.get("yielded_work")
        if incoming:
            if state.yielded_work is None:
                state.yielded_work = dict(incoming)
        else:
            state.yielded_work = None
        return

    if etype == EventType.CONTEXT_ASSEMBLED:
        manifest = _manifest_from_payload(payload, event.event_id)
        state.manifests.append(manifest)
        return

    if etype == EventType.MODEL_REQUEST_SERIALIZED:
        for request in reversed(state.model_requests):
            if ((payload.get("attempt_id") and request.get("attempt_id") == payload.get("attempt_id"))
                    or (request.get("activation_id"), request.get("step_id"), request.get("attempt")) == (
                    payload.get("activation_id"), payload.get("step_id"), payload.get("attempt"))):
                request["serialized_event_id"] = event.event_id
                request["serialized_request_ref"] = payload.get("request_ref")
                request["serialized_request_digest"] = payload.get("request_digest")
                request["serialization"] = payload.get("serialization")
                break
        return

    if etype == EventType.COMPACTION_RECORDED:
        state.compactions.append({**payload, "source_event_id": event.event_id, "department": event.department})
        _bind_actual_model(state, event)
        return

    if etype == EventType.MODEL_REQUESTED:
        requested_provider = payload.get("requested_provider")
        requested_model = payload.get("requested_model")
        state.requested_provider = requested_provider
        state.requested_model = requested_model
        state.actual_provider = None
        state.actual_model = None
        state.model = None
        if event.department:
            state.department_call_targets[event.department] = {
                key: payload.get(key)
                for key in ("provider_config_id", "model_id", "provider_name", "protocol", "base_url",
                            "requested_provider", "requested_protocol", "requested_model",
                            "credential_ref", "credential_version", "context_window",
                            "configured_max_output_tokens", "accepts_required_tool_call", "input_modalities",
                            "selection_source",
                            "reasoning_levels", "default_reasoning_level", "reasoning_mode",
                            "requested_tier", "sent_tier")
            }
        state.model_requests.append({
            "event_id": event.event_id,
            "seq": event.stream_version,
            "department": event.department,
            "activation_id": payload.get("activation_id"),
            "step_id": payload.get("step_id"),
            "attempt": payload.get("attempt"),
            "max_attempts": payload.get("max_attempts"),
            "root_step_id": payload.get("root_step_id"),
            "retry_of_step_id": payload.get("retry_of_step_id"),
            "attempt_id": payload.get("attempt_id"),
            "logical_call_id": payload.get("logical_call_id"),
            "collaboration_request_id": payload.get("collaboration_request_id", payload.get("request_id")),
            "context_event_id": payload.get("context_event_id"),
            "purpose": payload.get("purpose"),
            "provider_config_id": payload.get("provider_config_id"),
            "model_id": payload.get("model_id"),
            "provider_name": payload.get("provider_name"),
            "credential_ref": payload.get("credential_ref"),
            "credential_version": payload.get("credential_version"),
            "selection_source": payload.get("selection_source"),
            "prompt_version": payload.get("prompt_version"),
            "requested_tier": payload.get("requested_tier"),
            "sent_tier": payload.get("sent_tier"),
            "provider": requested_provider,
            "requested_provider": requested_provider,
            "requested_protocol": payload.get("requested_protocol"),
            "protocol": payload.get("protocol"),
            "base_url": payload.get("base_url"),
            "requested_model": requested_model,
            "effective_context_window": payload.get("effective_context_window"),
            "max_output_tokens": payload.get("max_output_tokens"),
            "configured_max_output_tokens": payload.get("configured_max_output_tokens"),
            "accepts_required_tool_call": payload.get("accepts_required_tool_call"),
            "input_modalities": payload.get("input_modalities"),
            "actual_provider": None,
            "actual_model": None,
            "context_digest": event.context_digest,
            "started_at": payload.get("started_at"),
            "status": "requesting",
        })
        return

    if etype in {EventType.MODEL_ATTEMPT_FINISHED, EventType.MODEL_ATTEMPT_FAILED}:
        attempt_id = payload.get("attempt_id")
        request = next((item for item in reversed(state.model_requests)
                        if attempt_id and item.get("attempt_id") == attempt_id), None)
        if request is None:
            request = next((item for item in reversed(state.model_requests)
                            if (item.get("activation_id"), item.get("step_id"), item.get("attempt")) == (
                                payload.get("activation_id"), payload.get("step_id"), payload.get("attempt"))), None)
        if request is not None:
            request.update({
                "status": payload.get("status", "completed" if etype == EventType.MODEL_ATTEMPT_FINISHED else "failed"),
                "finished_at": payload.get("finished_at"),
                "duration_ms": payload.get("duration_ms"),
                "response_ref": payload.get("response_ref"),
                "stream_events_ref": payload.get("stream_events_ref"),
                "stream_event_count": payload.get("stream_event_count"),
                "provider_response_id": payload.get("provider_response_id"),
                "usage": payload.get("usage"),
                "raw_usage_ref": payload.get("raw_usage_ref"),
                "collection_scope": payload.get("collection_scope"),
            })
        if event.model:
            _bind_actual_model(state, event)
        return

    if etype == EventType.TOOL_CALLED:
        if payload.get("name") != "provider_usage":
            state.tool_count += 1
            if payload.get("ok") and payload.get("name") in {"write_file", "delete_file", "move_file"}:
                _supersede_active_deliveries(state, "workspace_changed")
        else:
            state.token_used += int(payload.get("tokens_charged", 0))
        state.cost += float(payload.get("cost", 0.0))
        state.latency_ms += int(payload.get("latency_ms", 0))
        if payload.get("name") == "provider_usage":
            _bind_actual_model(state, event)
        return

    if etype == EventType.ACTIVATION_FINISHED:
        state.latency_ms += int(payload.get("latency_ms", 0))
        session = state.sessions.get(event.department or "")
        if session:
            session.status = "closed" if state.phase in TERMINAL_PHASES else "idle"
        return

    if etype == EventType.PROPOSAL_REJECTED:
        item = {
            "department": event.department,
            "errors": payload.get("errors", []),
            "event_id": event.event_id,
            "phase": event.state_after,
        }
        state.rejections.append(item)
        if event.department:
            state.pending_feedback[event.department] = item
        return

    if etype == EventType.LESSON_CANDIDATE_RECORDED:
        state.lesson_candidates.append(LessonCandidate(
            id=payload["id"], run_id=event.run_id, created_event_id=event.event_id,
            source_event_id=payload["source_event_id"], source_type=payload["source_type"],
            observation=payload["observation"], suggestion=payload["suggestion"],
            product_spec_hash=payload["product_spec_hash"], delivery_spec_hash=payload["delivery_spec_hash"],
            checks=payload["checks"], evidence_refs=[ArtifactRef(**ref) for ref in payload["evidence_refs"]],
            status=payload["status"],
        ))
        return

    if etype == EventType.SPEC_ACCEPTED:
        _clear_feedback(state, event.department)
        spec = _product_spec_from_payload(payload, event)
        for existing in state.product_specs:
            if existing.status == "active":
                state.product_specs[state.product_specs.index(existing)] = replace(existing, status="superseded")
        state.product_specs.append(spec)
        state.product_spec = spec
        state.processed_input_version = spec.input_version
        _supersede_active_deliveries(state, "product_spec_changed")
        _refresh_effective_decisions(state)
        return

    if etype == EventType.SPEC_SUPERSEDED:
        target = payload.get("content_hash")
        for index, existing in enumerate(state.product_specs):
            if existing.content_hash == target:
                state.product_specs[index] = replace(existing, status="superseded")
        if state.product_spec and state.product_spec.content_hash == target:
            state.product_spec = replace(state.product_spec, status="superseded")
        return

    if etype == EventType.CONTRACT_ACCEPTED:
        contract = EffectiveContract(
            content_hash=payload["content_hash"], revision=payload["revision"],
            product_spec_hash=payload["product_spec_hash"], decision_hashes=list(payload["decision_hashes"]),
            input_version=payload["input_version"],
            created_event_id=event.event_id, prd_ref=ArtifactRef(**payload["prd_ref"]),
        )
        if state.effective_contract is None or state.effective_contract.content_hash != contract.content_hash:
            _supersede_plans(state)
            _supersede_active_deliveries(state, "effective_contract_changed")
        state.effective_contracts.append(contract)
        state.effective_contract = contract
        return

    if etype == EventType.PLAN_ACCEPTED:
        _clear_feedback(state, event.department)
        _supersede_plans(state)
        _supersede_active_deliveries(state, "engineering_plan_changed")
        plan = EngineeringPlan(
            id=payload["id"], run_id=event.run_id, content_hash=payload["content_hash"],
            revision=payload["revision"], parent_hash=payload["parent_hash"], status=payload["status"],
            created_event_id=event.event_id, effective_contract_hash=payload["effective_contract_hash"],
            objective=payload["objective"], scope=list(payload["scope"]), tasks=list(payload["tasks"]),
            refactoring=list(payload["refactoring"]), assumptions=list(payload["assumptions"]),
            reason=payload["reason"], plan_ref=ArtifactRef(**payload["plan_ref"]),
        )
        state.engineering_plans.append(plan)
        state.engineering_plan = plan
        return

    if etype == EventType.COLLABORATION_REQUESTED:
        _clear_feedback(state, event.department)
        request = CollaborationRequest(
            id=payload["id"], run_id=event.run_id, content_hash=payload["content_hash"], created_event_id=event.event_id,
            requester=payload["requester"], recipient=payload["recipient"], request_type=payload["request_type"],
            action=payload["action"], question=payload["question"], background=payload["background"],
            expected_result=payload["expected_result"], basis=payload["basis"], return_phase=payload["return_phase"], status="open",
        )
        state.requests.append(request)
        state.pending_request = request
        state.active_department = request.recipient
        state.request_count += 1
        return

    if etype in {EventType.COLLABORATION_RESPONDED, EventType.COLLABORATION_CLOSED}:
        _clear_feedback(state, event.department)
        if etype == EventType.COLLABORATION_RESPONDED:
            # 发问方与回答方：旧事件没有这两个字段，按 request_id 查找对应请求（工单 #275）
            request = next((item for item in state.requests if item.id == payload["request_id"]), None)
            state.responses.append(CollaborationResponse(
                id=payload["id"], run_id=event.run_id, content_hash=payload["content_hash"], created_event_id=event.event_id,
                requester=payload.get("requester") or (request.requester if request else None),
                recipient=payload.get("recipient") or (request.recipient if request else None),
                request_id=payload["request_id"], status=payload["status"], text=payload["text"],
                result_event_ids=list(payload["result_event_ids"]), return_phase=payload["return_phase"],
                return_work_valid=payload["return_work_valid"],
            ))
        state.requests = [replace(item, status=payload["status"]) if item.id == payload["request_id"] else item
                          for item in state.requests]
        if state.pending_request and state.pending_request.id == payload["request_id"]:
            state.pending_request = None
        state.phase = payload["return_phase"]
        state.active_department = department_for_phase(state.phase)
        return

    if etype == EventType.PRODUCT_DECISION_ACCEPTED:
        _clear_feedback(state, event.department)
        state.product_decisions.append(ProductDecision(
            id=payload["id"], run_id=event.run_id, content_hash=payload["content_hash"], created_event_id=event.event_id,
            product_spec_hash=payload["product_spec_hash"], statement=payload["statement"],
            rationale=payload["rationale"], request_id=payload["request_id"],
        ))
        _refresh_effective_decisions(state)
        return

    if etype == EventType.DELIVERY_ACCEPTED:
        _clear_feedback(state, event.department)
        _supersede_active_deliveries(state, "replaced")
        delivery = _delivery_from_payload(payload, event)
        state.delivery_specs.append(delivery)
        state.delivery_spec = delivery
        state.evidence.append(
            {
                "kind": "delivery",
                "files": delivery.files,
                "checks": delivery.checks,
                "code_tree_digest": delivery.code_tree_digest,
                "tree_ref": delivery.tree_ref.__dict__,
                "summary": delivery.summary,
            }
        )
        return

    if etype == EventType.STRUCTURE_ACCEPTED:
        _clear_feedback(state, event.department)
        record = {key: value for key, value in payload.items() if key != "git_version"}
        state.structures.append(record)
        state.structure = record
        state.evidence.append({"kind": "structure", "content_hash": payload["content_hash"],
                               "structure_ref": payload["structure_ref"],
                               "code_tree_digest": payload["code_tree_digest"],
                               "product_spec_hash": payload["product_spec_hash"]})
        return

    if etype == EventType.BASELINE_REVIEW_ACCEPTED:
        _clear_feedback(state, event.department)
        record = {key: value for key, value in payload.items() if key != "git_version"}
        state.baseline_reviews.append(record)
        state.baseline_review = record
        if record["verdict"] == "rework_product":
            state.rework_count += 1
            _supersede_active_deliveries(state, "baseline_rework_product")
        state.evidence.append({"kind": "baseline_review", "verdict": record["verdict"],
                               "content_hash": record["content_hash"], "checks": record["checks"],
                               "product_spec_hash": record["product_spec_hash"],
                               "code_snapshot_hash": record["code_snapshot_hash"]})
        return

    if etype == EventType.QA_SUBMITTED:
        _clear_feedback(state, event.department)
        review = _review_from_payload(payload, event)
        state.reviews.append(review)
        state.last_review = review
        if review.verdict in {"rework_product", "rework_engineering"}:
            state.rework_count += 1
            reason = "qa_rework_product" if review.verdict == "rework_product" else "qa_rework_engineering"
            _supersede_active_deliveries(state, reason)
        state.evidence.append(
            {
                "kind": "qa_review",
                "verdict": review.verdict,
                "defects": [defect.__dict__ for defect in review.defects],
                "checks": review.checks,
                "code_snapshot_hash": review.code_snapshot_hash,
                "product_spec_hash": review.product_spec_hash,
            }
        )
        return

    if etype == EventType.TRANSITION:
        state.phase = event.state_after
        route = payload.get("route") or f"{event.state_before}->{event.state_after}"
        state.transitions.append(route)
        if payload.get("yielded_work_resolved"):
            state.yielded_work = None
        if event.state_after not in TERMINAL_PHASES:
            state.active_department = state.pending_request.recipient if state.pending_request else department_for_phase(event.state_after)
        return

    if etype == EventType.RUN_DONE:
        state.phase = "DONE"
        state.outcome = "done"
        state.stop_reason = event.stop_reason
        state.active_department = None
        return

    if etype == EventType.RUN_PAUSED:
        state.phase = "PAUSED"
        state.outcome = "paused"
        state.stop_reason = event.stop_reason
        state.human_action = payload.get("human_action")
        state.error = event.error
        state.active_department = None
        return

    if etype == EventType.RUN_CONTINUED:
        # 用户在暂停以后回答「处理以后继续执行」（工单 #204）：从暂停位置恢复阶段，清除暂停留下的字段；
        # 已用的激活次数、模型步数与运行时间保持在暂停时的值，不在这里重置
        state.phase = payload["resumed_at_phase"]
        state.outcome = "running"
        state.stop_reason = None
        state.human_action = None
        state.error = None
        state.active_department = department_for_phase(state.phase)
        return

    if etype == EventType.RUN_FAILED:
        state.phase = "FAILED"
        state.outcome = "failed"
        state.stop_reason = event.stop_reason
        state.error = event.error
        state.human_action = payload.get("human_action")
        state.active_department = None
        return


def _input_from_payload(payload: dict[str, Any], event: Event) -> UserInput:
    return UserInput(
        id=payload["id"], run_id=event.run_id, version=payload["version"], text=payload["text"],
        kind=payload["kind"], input_ref=ArtifactRef(**payload["input_ref"]),
        intend_ref=ArtifactRef(**payload["intend_ref"]), byte_start=payload["byte_start"],
        byte_end=payload["byte_end"], created_event_id=event.event_id,
    )



def _guidance_from_payload(payload: dict[str, Any], event: Event) -> DepartmentGuidance:
    return DepartmentGuidance(
        id=payload["id"],
        run_id=event.run_id,
        department=payload["department"],
        version=int(payload["version"]),
        text=payload["text"],
        guidance_ref=ArtifactRef(**payload["guidance_ref"]),
        created_event_id=event.event_id,
        status=payload.get("status", "received"),
        applied_activation_id=payload.get("applied_activation_id"),
        applied_context_event_id=payload.get("applied_context_event_id"),
        response_event_id=payload.get("response_event_id"),
        response_status=payload.get("response_status"),
        response_text=payload.get("response_text"),
    )


def _manifest_from_payload(payload: dict[str, Any], event_id: str) -> ContextManifest:
    return ContextManifest(
        source_event_id=event_id,
        purpose=payload["purpose"],
        max_output_tokens=payload["max_output_tokens"],
        compaction_event_id=payload["compaction_event_id"],
        effective_contract_hash=payload["effective_contract_hash"],
        engineering_plan_hash=payload["engineering_plan_hash"],
        request_id=payload["request_id"],
        input_version=payload["input_version"],
        prompt_version=payload["prompt_version"],
        prompt_hash=payload["prompt_hash"],
        input_token_estimate=payload.get("input_token_estimate"),
        output_reserve_tokens=int(payload.get("output_reserve_tokens", payload.get("max_output_tokens") or 0)),
        parts_ref=payload.get("parts_ref"),
        guidance_ids=list(payload.get("guidance_ids", [])),
        guidance_only=bool(payload.get("guidance_only", False)),
        step_id=payload["step_id"],
        request_ref=payload["request_ref"],
        admitted=payload["admitted"],
        session_id=payload["session_id"],
        department=payload["department"],
        activation_id=payload["activation_id"],
        injected=[ContextSource(**item) for item in payload.get("injected", [])],
        excluded=[ContextExclusion(**item) for item in payload.get("excluded", [])],
        token_estimate=int(payload["token_estimate"]),
        budget=int(payload["budget"]),
        digest=payload["digest"],
        truncated=bool(payload.get("truncated", False)),
    )


def _bind_actual_model(state: RunProjection, event: Event) -> None:
    """Attach a returned model only to the request that produced this event."""

    if not event.model or not state.model_requests:
        return
    payload = event.payload
    activation_id = payload.get("activation_id")
    step_id = payload.get("step_id")
    candidates = [
        item for item in state.model_requests
        if item.get("activation_id") == activation_id and item.get("step_id") == step_id
        and item.get("seq", -1) < event.stream_version
    ]
    if not candidates:
        return
    request = candidates[-1]
    request["actual_provider"] = event.provider
    request["actual_model"] = event.model


def _product_spec_from_payload(payload: dict[str, Any], event: Event) -> ProductSpec:
    return ProductSpec(
        id=payload["id"],
        run_id=event.run_id,
        revision=int(payload["revision"]),
        parent_hash=payload.get("parent_hash"),
        content_hash=payload["content_hash"],
        issuer=payload.get("issuer", "product"),
        status=payload.get("status", "active"),
        created_event_id=event.event_id,
        goal=payload["goal"],
        requirements=list(payload.get("requirements", [])),
        boundaries=list(payload.get("boundaries", [])),
        constraints=list(payload.get("constraints", [])),
        acceptance_criteria=list(payload.get("acceptance_criteria", [])),
        fatal_conditions=list(payload.get("fatal_conditions", [])),
        non_goals=list(payload.get("non_goals", [])),
        decision_changes=list(payload["decision_changes"]),
        change_record=payload["change_record"],
        input_version=payload["input_version"],
    )


def _delivery_from_payload(payload: dict[str, Any], event: Event) -> DeliverySpec:
    from .models import ArtifactRef

    return DeliverySpec(
        id=payload["id"],
        run_id=event.run_id,
        revision=int(payload["revision"]),
        parent_hash=payload.get("parent_hash"),
        content_hash=payload["content_hash"],
        issuer=payload.get("issuer", "engineering"),
        status=payload.get("status", "active"),
        created_event_id=event.event_id,
        product_spec_hash=payload["product_spec_hash"],
        effective_contract_hash=payload["effective_contract_hash"],
        engineering_plan_hash=payload["engineering_plan_hash"],
        summary=payload["summary"],
        files=list(payload.get("files", [])),
        check_names=list(payload.get("check_names", [])),
        checks=list(payload.get("checks", [])),
        known_risks=list(payload.get("known_risks", [])),
        code_tree_digest=payload["code_tree_digest"],
        tree_ref=ArtifactRef(**payload["tree_ref"]),
        invalidation_reason=payload.get("invalidation_reason"),
    )


def _clear_feedback(state: RunProjection, role: str | None) -> None:
    if role:
        state.pending_feedback.pop(role, None)


def _supersede_active_deliveries(state: RunProjection, reason: str) -> None:
    for index, existing in enumerate(state.delivery_specs):
        if existing.status == "active":
            state.delivery_specs[index] = replace(existing, status="superseded", invalidation_reason=reason)
    if state.delivery_spec is not None:
        state.delivery_spec = None


def _supersede_plans(state: RunProjection) -> None:
    state.engineering_plans = [replace(item, status="superseded") if item.status == "active" else item
                               for item in state.engineering_plans]
    state.engineering_plan = None


def _refresh_effective_decisions(state: RunProjection) -> None:
    spec = state.product_spec
    if spec is None or spec.status != "active":
        state.effective_decisions = []
        return
    retained = {item["decision_hash"] for item in spec.decision_changes if item["disposition"] == "retain"}
    state.effective_decisions = [item for item in state.product_decisions
                                 if item.product_spec_hash == spec.content_hash or item.content_hash in retained]


def _review_from_payload(payload: dict[str, Any], event: Event) -> QAReview:
    from .models import ArtifactRef

    return QAReview(
        id=payload["id"],
        run_id=event.run_id,
        revision=int(payload["revision"]),
        parent_hash=payload.get("parent_hash"),
        content_hash=payload["content_hash"],
        issuer=payload.get("issuer", "quality"),
        status=payload.get("status", "active"),
        created_event_id=event.event_id,
        product_spec_hash=payload["product_spec_hash"],
        effective_contract_hash=payload["effective_contract_hash"],
        engineering_plan_hash=payload["engineering_plan_hash"],
        delivery_spec_hash=payload["delivery_spec_hash"],
        code_snapshot_hash=payload["code_snapshot_hash"],
        verdict=payload["verdict"],
        rationale=payload.get("rationale", ""),
        checks=list(payload.get("checks", [])),
        defects=[Defect(**item) if not isinstance(item, Defect) else item for item in payload.get("defects", [])],
        evidence_refs=[ArtifactRef(**item) if not isinstance(item, ArtifactRef) else item for item in payload.get("evidence_refs", [])],
    )


def apply_project_event(state: ProjectProjection, event: ProjectEvent) -> None:
    payload = event.payload
    etype = event.type
    state.last_event_id = event.event_id
    state.stream_version = event.stream_version
    state.updated_at = event.created_at
    if etype == ProjectEventType.PROJECT_REGISTERED:
        state.project_id = event.project_id
        state.name = payload["name"]
        state.goal = payload["goal"]
        state.goal_ref = payload["goal_ref"]
        state.source = payload["source"]
        state.created_at = event.created_at
        return
    if etype == ProjectEventType.PROJECT_RENAMED:
        state.name = payload["name"]
        return
    if etype == ProjectEventType.PROJECT_GOAL_CHANGED:
        state.goal = payload["goal"]
        state.goal_ref = payload["goal_ref"]
        return
    if etype == ProjectEventType.PROJECT_PINNED:
        state.pinned = bool(payload["pinned"])
        return
    if etype == ProjectEventType.PROJECT_ARCHIVED:
        state.archived = True
        return
    if etype == ProjectEventType.PROJECT_RESTORED:
        state.archived = False
        return
    if etype == ProjectEventType.WORK_ITEM_CREATED:
        state.work_items.append(WorkItem(
            work_item_id=payload["work_item_id"], title=payload["title"], text=payload["text"], run_id=payload["run_id"],
            baseline=payload["baseline"], project_context_ref=payload["project_context_ref"],
            prompt_config_versions=dict(payload["prompt_config_versions"]),
            command_versions=dict(payload.get("command_versions") or {}),
            max_cycles=int(payload["max_cycles"]),
            run_time_limit_sec=int(payload["run_time_limit_sec"]),
            context_window=int(payload["context_window"]), created_at=event.created_at,
            stream_version=event.stream_version, event_id=event.event_id, snapshot=payload.get("snapshot"),
            kind=payload.get("kind", "change"),
        ))
        return
    if etype == ProjectEventType.WORK_ITEM_START_FAILED:
        item = state.work_item(payload["work_item_id"])
        if item is not None:
            item.start_error = payload["error"]
        return
    if etype == ProjectEventType.DELIVERABLE_ADOPTED:
        adoption = Adoption(
            adoption_id=payload["adoption_id"], work_item_id=payload["work_item_id"], run_id=payload["run_id"],
            delivery_event_id=payload["delivery_event_id"], qa_event_id=payload["qa_event_id"],
            tree_ref=payload["tree_ref"], code_tree_digest=payload["code_tree_digest"], summary=payload["summary"],
            files=list(payload["files"]), check_names=list(payload["check_names"]),
            known_risks=list(payload["known_risks"]), previous_adoption_id=payload["previous_adoption_id"],
            adopted_at=event.created_at, stream_version=event.stream_version, event_id=event.event_id,
        )
        state.adoptions.append(adoption)
        state.current_adoption = adoption
        return
    if etype == ProjectEventType.ADOPTION_HELD:
        state.held.append(HeldCandidate(
            work_item_id=payload["work_item_id"], run_id=payload["run_id"],
            delivery_event_id=payload["delivery_event_id"], code_tree_digest=payload["code_tree_digest"],
            reason=payload["reason"], expected_adoption_id=payload["expected_adoption_id"],
            current_adoption_id=payload["current_adoption_id"], held_at=event.created_at,
            stream_version=event.stream_version, event_id=event.event_id,
        ))
        return
    if etype == ProjectEventType.DEPARTMENT_SETTINGS_CONFIGURED:
        department = payload["department"]
        # 旧版本的事件只带 text（部门 Prompt），新版本带 department_prompt 与模型、请求档位（ADR-0019）
        if "department_prompt" in payload:
            configured_prompt = payload["department_prompt"]
            prompt_ref = payload.get("department_prompt_ref")
        else:
            configured_prompt = payload.get("text")
            prompt_ref = payload.get("prompt_ref")
        text = configured_prompt if configured_prompt is not None else DEFINITIONS.role(department).prompt
        setting = DepartmentSetting(
            department=department, version=int(payload["version"]), text=text, source="configured",
            provider_id=payload.get("provider_id"), model_id=payload.get("model_id"),
            requested_tier=payload.get("requested_tier"), configured_prompt=configured_prompt is not None,
            prompt_ref=prompt_ref, base_version=payload.get("base_version"),
            updated_at=event.created_at, event_id=event.event_id,
        )
        state.department_settings[department] = setting
        state.department_setting_history.append(setting)
        return
    if etype == ProjectEventType.COMMAND_CONFIGURED:
        command = RegisteredCommand(
            name=payload["name"], version=int(payload["version"]), argv=list(payload["argv"]),
            args=list(payload["args"]), timeout_sec=int(payload["timeout_sec"]),
            output_limit=int(payload["output_limit"]), base_version=payload["base_version"],
            updated_at=event.created_at, event_id=event.event_id,
        )
        state.commands[command.name] = command
        state.command_history.append(command)
        return
    if etype == ProjectEventType.MATERIAL_RECORDED:
        state.materials.append(Material(
            material_id=payload["material_id"], text=payload["text"], material_ref=payload["material_ref"],
            department=payload["department"], recorded_at=event.created_at, stream_version=event.stream_version,
            event_id=event.event_id,
        ))
        return
    if etype == ProjectEventType.SOURCE_DIRECTORY_CONFIGURED:
        directory = SourceDirectory(
            name=payload["name"], path=payload["path"], version=int(payload["version"]),
            base_version=payload["base_version"], updated_at=event.created_at, event_id=event.event_id,
        )
        state.source_directories[directory.name] = directory
        state.source_directory_history.append(directory)
        return
