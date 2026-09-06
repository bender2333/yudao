"""只读视图：从 Event Store 与投影装配 REST 响应。"""

from __future__ import annotations

import json
from typing import Any

from .event_store import EventStore
from .models import Event, EventType, GIT_VERSION_EVENTS, json_dumps
from .projection import RunProjection, project_run


def _plain(value: Any) -> Any:
    return json.loads(json_dumps(value))


def _with_git(value: Any, events: list[Event]) -> Any:
    item = _plain(value)
    if item is None:
        return None
    if isinstance(item, list):
        return [_with_git(child, events) for child in item]
    event = next((event for event in events if event.event_id == item.get("created_event_id")), None)
    if event is not None and event.type in GIT_VERSION_EVENTS and event.payload.get("git_version"):
        item["git_version"] = _plain(event.payload["git_version"])
    return item


def run_board(projection: RunProjection) -> dict[str, Any]:
    return {
        "run_id": projection.run_id,
        "task": projection.task,
        "phase": projection.phase,
        "active_department": projection.active_department,
        "waiting_reason": projection.waiting_reason,
        "outcome": projection.outcome,
        "stop_reason": projection.stop_reason,
        "human_action": projection.human_action,
        "error": projection.error,
        "cycle_count": projection.cycle_count,
        "max_cycles": projection.max_cycles,
        "token_used": projection.token_used,
        "cost": projection.cost,
        "latency_ms": projection.latency_ms,
        "tool_count": projection.tool_count,
        "rework_count": projection.rework_count,
        "request_count": projection.request_count,
        "pending_request": _plain(projection.pending_request),
        "provider": projection.provider,
        "adapter": projection.adapter,
        "model": projection.model,
        "input_version": projection.input_version,
        "product_work_input_version": projection.product_work_input_version,
        "processed_input_version": projection.processed_input_version,
    }


def spec_timeline(projection: RunProjection, events: list[Event]) -> dict[str, Any]:
    specs = []
    for spec in projection.product_specs:
        specs.append(
            {
                "kind": "product_spec",
                "id": spec.id,
                "revision": spec.revision,
                "status": spec.status,
                "content_hash": spec.content_hash,
                "parent_hash": spec.parent_hash,
                "goal": spec.goal,
                "input_version": spec.input_version,
                "change_record": _plain(spec.change_record),
                "created_event_id": spec.created_event_id,
            }
        )
    return {
        "current_product_spec": _with_git(projection.product_spec, events),
        "effective_contract": _with_git(projection.effective_contract, events),
        "effective_contracts": _with_git(projection.effective_contracts, events),
        "engineering_plan": _with_git(projection.engineering_plan, events),
        "engineering_plans": _with_git(projection.engineering_plans, events),
        "current_delivery_spec": _with_git(projection.delivery_spec, events),
        "effective_decisions": _plain(projection.effective_decisions),
        "pending_request": _plain(projection.pending_request),
        "product_decisions": _with_git(projection.product_decisions, events),
        "specs": _with_git(specs, events),
        "requests": _plain(projection.requests),
        "responses": _plain(projection.responses),
        "request_closures": [
            {**event.payload, "created_event_id": event.event_id}
            for event in events if event.type == EventType.COLLABORATION_CLOSED
        ],
        "transitions": projection.transitions,
    }


def evidence_view(projection: RunProjection, events: list[Event]) -> dict[str, Any]:
    return {
        "deliveries": _with_git(projection.delivery_specs, events),
        "reviews": _with_git(projection.reviews, events),
        "evidence": _plain(projection.evidence),
        "rejections": _plain(projection.rejections),
        "lesson_candidates": _plain(projection.lesson_candidates),
    }


def context_view(projection: RunProjection) -> dict[str, Any]:
    return {
        "manifests": _plain(projection.manifests),
        "compactions": _plain(projection.compactions),
        "sessions": _plain(projection.sessions),
        "stop_reason": projection.stop_reason,
        "human_action": projection.human_action,
    }


def event_card(event: Event) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "seq": event.seq,
        "type": event.type,
        "role": event.role,
        "state_before": event.state_before,
        "state_after": event.state_after,
        "stop_reason": event.stop_reason,
        "error": event.error,
        "session_id": event.session_id,
        "provider": event.provider,
        "model": event.model,
        "context_digest": event.context_digest,
        "created_at": event.created_at,
        "summary": event.summary(),
        "artifact_hashes": event.artifact_hashes,
        "git_version": _plain(event.payload.get("git_version")) if event.type in GIT_VERSION_EVENTS else None,
        "input_save_failure": _plain(event.payload.get("input_save_failure"))
        if event.type == EventType.RUN_FAILED and event.stop_reason == "cancelled" else None,
    }


def run_payload(store: EventStore, run_id: str) -> dict[str, Any]:
    projection = project_run(store, run_id)
    events = store.list_events(run_id)
    return {
        "board": run_board(projection),
        "timeline": spec_timeline(projection, events),
        "evidence": evidence_view(projection, events),
        "context": context_view(projection),
        "inputs": _with_git(projection.inputs, events),
        "prompts": {
            "current": _plain(projection.department_prompts),
            "versions": _plain(projection.prompt_versions),
            "activations": [
                {"event_id": event.event_id, "department": event.role, **event.payload}
                for event in events if event.type == EventType.DEPARTMENT_ACTIVATED
            ],
        },
        "events": [event_card(event) for event in events],
        "aggregates": {
            "tokens": projection.token_used,
            "cost": projection.cost,
            "latency_ms": projection.latency_ms,
            "tool_count": projection.tool_count,
            "rework_count": projection.rework_count,
            "request_count": projection.request_count,
            "cycles": projection.cycle_count,
        },
    }
