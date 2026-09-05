"""从事件重放状态投影。Agent 不能写投影。"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .event_store import EventStore
from .models import (
    AskRequest,
    ContextExclusion,
    ContextManifest,
    ContextSource,
    DeliverySpec,
    Defect,
    Event,
    EventType,
    ProductReaction,
    ProductSpec,
    QAReview,
    RunProjection,
    SessionRecord,
    TERMINAL_PHASES,
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
    if state.phase in TERMINAL_PHASES:
        state.outcome = {"DONE": "done", "PAUSED": "paused", "FAILED": "failed"}[state.phase]
        state.active_department = None
    return state


def apply_event(state: RunProjection, event: Event) -> None:
    state.last_event_id = event.event_id
    state.last_seq = event.seq
    payload = event.payload
    etype = event.type

    if etype == EventType.RUN_CREATED:
        state.run_id = event.run_id
        state.task = payload["task"]
        state.phase = event.state_after
        state.max_cycles = int(payload["max_cycles"])
        state.token_budget = int(payload["token_budget"])
        state.context_window = int(payload.get("context_window", 32_000))
        state.provider = payload.get("provider", "fake")
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
        return

    if etype == EventType.CONTEXT_ASSEMBLED:
        if payload.get("usage_only"):
            state.token_used += int(payload.get("tokens_charged", 0))
            state.cost += float(payload.get("cost", 0.0))
            state.latency_ms += int(payload.get("latency_ms", 0))
            return
        manifest = _manifest_from_payload(payload)
        state.manifests.append(manifest)
        state.token_used += int(payload.get("tokens_charged", manifest.token_estimate))
        state.cost += float(payload.get("cost", 0.0))
        state.latency_ms += int(payload.get("latency_ms", 0))
        if event.model:
            state.model = event.model
        return

    if etype == EventType.TOOL_CALLED:
        if payload.get("name") != "provider_usage":
            state.tool_count += 1
        state.cost += float(payload.get("cost", 0.0))
        state.latency_ms += int(payload.get("latency_ms", 0))
        if event.model:
            state.model = event.model
        return

    if etype == EventType.PROPOSAL_REJECTED:
        state.rejections.append(
            {
                "department": event.role,
                "errors": payload.get("errors", []),
                "event_id": event.event_id,
                "phase": event.state_after,
            }
        )
        return

    if etype == EventType.SPEC_ACCEPTED:
        spec = _product_spec_from_payload(payload, event)
        for existing in state.product_specs:
            if existing.status == "active":
                state.product_specs[state.product_specs.index(existing)] = replace(existing, status="superseded")
        state.product_specs.append(spec)
        state.product_spec = spec
        return

    if etype == EventType.SPEC_SUPERSEDED:
        target = payload.get("content_hash")
        for index, existing in enumerate(state.product_specs):
            if existing.content_hash == target:
                state.product_specs[index] = replace(existing, status="superseded")
        if state.product_spec and state.product_spec.content_hash == target:
            state.product_spec = replace(state.product_spec, status="superseded")
        return

    if etype == EventType.ASK_SUBMITTED:
        ask = _ask_from_payload(payload, event)
        state.asks.append(ask)
        state.pending_ask = ask
        state.ask_count += 1
        return

    if etype == EventType.REACT_SUBMITTED:
        reaction = _reaction_from_payload(payload, event)
        state.reactions.append(reaction)
        state.last_reaction = reaction
        if state.pending_ask and state.pending_ask.id == reaction.ask_id:
            state.pending_ask = None
        for index, ask in enumerate(state.asks):
            if ask.id == reaction.ask_id:
                state.asks[index] = replace(ask, status="answered")
        return

    if etype == EventType.DELIVERY_ACCEPTED:
        delivery = _delivery_from_payload(payload, event)
        state.delivery_specs.append(delivery)
        state.delivery_spec = delivery
        state.evidence.append(
            {
                "kind": "delivery",
                "files": delivery.files,
                "checks": delivery.checks,
                "code_tree_digest": delivery.code_tree_digest,
                "summary": delivery.summary,
            }
        )
        return

    if etype == EventType.QA_SUBMITTED:
        review = _review_from_payload(payload, event)
        state.reviews.append(review)
        state.last_review = review
        if review.verdict in {"rework_product", "rework_engineering"}:
            state.rework_count += 1
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
            state.active_department = {
                "PRODUCT_SPEC": "product",
                "PRODUCT_REACT": "product",
                "REWORK_PRODUCT": "product",
                "ASK_PRODUCT": "product",
                "ENGINEERING": "engineering",
                "REWORK_ENGINEERING": "engineering",
                "QUALITY": "quality",
                "DELIVERY": "quality",
            }.get(event.state_after)
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


def _manifest_from_payload(payload: dict[str, Any]) -> ContextManifest:
    return ContextManifest(
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
    )


def _ask_from_payload(payload: dict[str, Any], event: Event) -> AskRequest:
    return AskRequest(
        id=payload["id"],
        run_id=event.run_id,
        revision=int(payload["revision"]),
        parent_hash=payload.get("parent_hash"),
        content_hash=payload["content_hash"],
        issuer=payload.get("issuer", "engineering"),
        status=payload.get("status", "open"),
        created_event_id=event.event_id,
        product_spec_hash=payload["product_spec_hash"],
        question=payload["question"],
        background=payload.get("background", ""),
        options=list(payload.get("options", [])),
        impact=payload.get("impact", ""),
        recommendation=payload.get("recommendation", ""),
        decide_fields=list(payload.get("decide_fields", [])),
    )


def _reaction_from_payload(payload: dict[str, Any], event: Event) -> ProductReaction:
    return ProductReaction(
        id=payload["id"],
        run_id=event.run_id,
        revision=int(payload["revision"]),
        parent_hash=payload.get("parent_hash"),
        content_hash=payload["content_hash"],
        issuer=payload.get("issuer", "product"),
        status=payload.get("status", "active"),
        created_event_id=event.event_id,
        ask_id=payload["ask_id"],
        ask_hash=payload["ask_hash"],
        decision=payload["decision"],
        rationale=payload["rationale"],
        produces_new_spec=bool(payload.get("produces_new_spec", False)),
        new_spec_hash=payload.get("new_spec_hash"),
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
        summary=payload["summary"],
        files=list(payload.get("files", [])),
        check_names=list(payload.get("check_names", [])),
        checks=list(payload.get("checks", [])),
        known_risks=list(payload.get("known_risks", [])),
        code_tree_digest=payload["code_tree_digest"],
        file_refs=[ArtifactRef(**item) if not isinstance(item, ArtifactRef) else item for item in payload.get("file_refs", [])],
    )


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
        delivery_spec_hash=payload["delivery_spec_hash"],
        code_snapshot_hash=payload["code_snapshot_hash"],
        verdict=payload["verdict"],
        rationale=payload.get("rationale", ""),
        checks=list(payload.get("checks", [])),
        defects=[Defect(**item) if not isinstance(item, Defect) else item for item in payload.get("defects", [])],
        evidence_refs=[ArtifactRef(**item) if not isinstance(item, ArtifactRef) else item for item in payload.get("evidence_refs", [])],
    )
