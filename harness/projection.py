"""从事件重放状态投影。Agent 不能写投影。"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .event_store import EventStore
from .models import (
    CollaborationRequest,
    CollaborationResponse,
    DepartmentGuidance,
    DepartmentPrompt,
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
    LessonCandidate,
    ProductDecision,
    ProductSpec,
    QAReview,
    RunProjection,
    SessionRecord,
    UserInput,
    TERMINAL_PHASES,
    department_for_phase,
    waiting_reason_for,
)


class RunNotFoundError(KeyError):
    pass


def project_run(store: EventStore, run_id: str) -> RunProjection:
    events = store.list_events(run_id)
    if not events:
        raise RunNotFoundError(run_id)
    return project_events(events)


def project_events(events: list[Event]) -> RunProjection:
    state = RunProjection()
    for event in events:
        apply_event(state, event)
    state.waiting_reason = waiting_reason_for(state.phase, state.stop_reason)
    if state.pending_request is not None:
        state.waiting_reason = f"{state.pending_request.recipient} is handling a request from {state.pending_request.requester}"
    if state.phase in TERMINAL_PHASES:
        state.outcome = {"DONE": "done", "PAUSED": "paused", "FAILED": "failed"}[state.phase]
        state.active_department = None
    return state


def apply_event(state: RunProjection, event: Event) -> None:
    state.last_event_id = event.event_id
    state.last_seq = event.seq
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
                                      "role": event.role, "name": payload.get("name"), "ok": payload.get("ok"),
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
        for value in payload["department_prompts"].values():
            prompt = _prompt_from_payload(value, event)
            state.department_prompts[prompt.department] = prompt
            state.prompt_versions.append(prompt)
        state.phase = event.state_after
        state.max_cycles = int(payload["max_cycles"])
        state.context_window = int(payload.get("context_window", 32_000))
        state.provider = payload.get("provider", "fake")
        state.adapter = payload["adapter"]
        snapshot = payload.get("provider_snapshot") or {}
        state.provider_snapshot = dict(snapshot) if isinstance(snapshot, dict) else {}
        state.sessions = {
            department: SessionRecord(session_id=session_id, department=department, status="idle")
            for department, session_id in payload.get("sessions", {}).items()
        }
        state.project_id = payload["project_id"]
        state.work_item_id = payload["work_item_id"]
        state.baseline = payload["baseline"]
        state.workspace_digest = payload["workspace_digest"]
        state.project_context_ref = payload["project_context_ref"]
        state.prompt_config_versions = dict(payload["prompt_config_versions"])
        state.active_department = "product"
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

    if etype == EventType.DEPARTMENT_PROMPT_UPDATED:
        prompt = _prompt_from_payload(payload, event)
        state.department_prompts[prompt.department] = prompt
        state.prompt_versions.append(prompt)
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
        state.active_department = event.role
        session = state.sessions.get(event.role or "")
        if session:
            session.activations += 1
            session.status = "active"
        activation_id = payload.get("activation_id")
        if event.role and activation_id:
            state.last_activations[event.role] = str(activation_id)
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
        state.compactions.append({**payload, "source_event_id": event.event_id, "department": event.role})
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
        state.model_requests.append({
            "event_id": event.event_id,
            "seq": event.seq,
            "department": event.role,
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
            "snapshot_id": payload.get("snapshot_id"),
            "provider_config_id": payload.get("provider_config_id"),
            "model_id": payload.get("model_id"),
            "provider_name": payload.get("provider_name"),
            "credential_ref": payload.get("credential_ref"),
            "credential_version": payload.get("credential_version"),
            "provider": requested_provider,
            "requested_provider": requested_provider,
            "requested_protocol": payload.get("requested_protocol"),
            "protocol": payload.get("protocol"),
            "base_url": payload.get("base_url"),
            "requested_model": requested_model,
            "effective_context_window": payload.get("effective_context_window"),
            "max_output_tokens": payload.get("max_output_tokens"),
            "configured_max_output_tokens": payload.get("configured_max_output_tokens"),
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
        session = state.sessions.get(event.role or "")
        if session:
            session.status = "closed" if state.phase in TERMINAL_PHASES else "idle"
        return

    if etype == EventType.PROPOSAL_REJECTED:
        item = {
            "department": event.role,
            "errors": payload.get("errors", []),
            "event_id": event.event_id,
            "phase": event.state_after,
        }
        state.rejections.append(item)
        if event.role:
            state.pending_feedback[event.role] = item
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
        _clear_feedback(state, event.role)
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
        _clear_feedback(state, event.role)
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
        _clear_feedback(state, event.role)
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
        _clear_feedback(state, event.role)
        if etype == EventType.COLLABORATION_RESPONDED:
            state.responses.append(CollaborationResponse(
                id=payload["id"], run_id=event.run_id, content_hash=payload["content_hash"], created_event_id=event.event_id,
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
        _clear_feedback(state, event.role)
        state.product_decisions.append(ProductDecision(
            id=payload["id"], run_id=event.run_id, content_hash=payload["content_hash"], created_event_id=event.event_id,
            product_spec_hash=payload["product_spec_hash"], statement=payload["statement"],
            rationale=payload["rationale"], request_id=payload["request_id"],
        ))
        _refresh_effective_decisions(state)
        return

    if etype == EventType.DELIVERY_ACCEPTED:
        _clear_feedback(state, event.role)
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

    if etype == EventType.QA_SUBMITTED:
        _clear_feedback(state, event.role)
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
        state.stop_reason = event.stop_reason or "released"
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


def _prompt_from_payload(payload: dict[str, Any], event: Event) -> DepartmentPrompt:
    return DepartmentPrompt(
        department=payload["department"], version=payload["version"], text=payload["text"],
        prompt_ref=ArtifactRef(**payload["prompt_ref"]), created_event_id=event.event_id,
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
        and item.get("seq", -1) < event.seq
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
