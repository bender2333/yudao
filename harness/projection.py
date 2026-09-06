"""从事件重放状态投影。Agent 不能写投影。"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .event_store import EventStore
from .models import (
    CollaborationRequest,
    CollaborationResponse,
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
    LessonCandidate,
    ProductDecision,
    ProductSpec,
    QAReview,
    RunProjection,
    SessionRecord,
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
    if payload.get("request_id") and etype in {
        EventType.TOOL_CALLED, EventType.SPEC_ACCEPTED, EventType.PRODUCT_DECISION_ACCEPTED,
        EventType.PLAN_ACCEPTED, EventType.DELIVERY_ACCEPTED, EventType.CONTRACT_ACCEPTED,
    } and payload.get("name") != "provider_usage":
        state.request_results.append({"event_id": event.event_id, "type": etype, "request_id": payload["request_id"],
                                      "role": event.role, "name": payload.get("name"), "ok": payload.get("ok"),
                                      "content_hash": payload.get("content_hash")})
    if event.provider:
        state.provider = event.provider
    if event.model:
        state.model = event.model

    if etype == EventType.RUN_CREATED:
        state.run_id = event.run_id
        state.task = payload["task"]
        state.intend_ref = payload["intend_ref"]
        state.phase = event.state_after
        state.max_cycles = int(payload["max_cycles"])
        state.context_window = int(payload.get("context_window", 32_000))
        state.provider = payload.get("provider", "fake")
        state.adapter = payload["adapter"]
        state.sessions = {
            department: SessionRecord(session_id=session_id, department=department, status="idle")
            for department, session_id in payload.get("sessions", {}).items()
        }
        state.active_department = "product"
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
        return

    if etype == EventType.CONTEXT_ASSEMBLED:
        manifest = _manifest_from_payload(payload, event.event_id)
        state.manifests.append(manifest)
        if event.model:
            state.model = event.model
        return

    if etype == EventType.COMPACTION_RECORDED:
        state.compactions.append({**payload, "source_event_id": event.event_id, "department": event.role})
        return

    if etype == EventType.MODEL_REQUESTED:
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
        if event.model:
            state.model = event.model
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


def _manifest_from_payload(payload: dict[str, Any], event_id: str) -> ContextManifest:
    return ContextManifest(
        source_event_id=event_id,
        purpose=payload["purpose"],
        max_output_tokens=payload["max_output_tokens"],
        compaction_event_id=payload["compaction_event_id"],
        effective_contract_hash=payload["effective_contract_hash"],
        engineering_plan_hash=payload["engineering_plan_hash"],
        request_id=payload["request_id"],
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
