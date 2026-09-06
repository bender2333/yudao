"""只读视图：从 Event Store 与投影装配 REST 响应。"""

from __future__ import annotations

import json
from typing import Any

from .event_store import EventStore
from .models import Event, EventType, json_dumps
from .projection import RunProjection, project_run


def _plain(value: Any) -> Any:
    return json.loads(json_dumps(value))


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
            }
        )
    return {
        "current_product_spec": _plain(projection.product_spec),
        "effective_contract": _plain(projection.effective_contract),
        "effective_contracts": _plain(projection.effective_contracts),
        "engineering_plan": _plain(projection.engineering_plan),
        "engineering_plans": _plain(projection.engineering_plans),
        "current_delivery_spec": _plain(projection.delivery_spec),
        "effective_decisions": _plain(projection.effective_decisions),
        "pending_request": _plain(projection.pending_request),
        "product_decisions": _plain(projection.product_decisions),
        "specs": specs,
        "requests": _plain(projection.requests),
        "responses": _plain(projection.responses),
        "request_closures": [
            {**event.payload, "created_event_id": event.event_id}
            for event in events if event.type == EventType.COLLABORATION_CLOSED
        ],
        "transitions": projection.transitions,
    }


def evidence_view(projection: RunProjection) -> dict[str, Any]:
    return {
        "deliveries": [_plain(item) for item in projection.delivery_specs],
        "reviews": [_plain(item) for item in projection.reviews],
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
    }


def run_payload(store: EventStore, run_id: str) -> dict[str, Any]:
    projection = project_run(store, run_id)
    events = store.list_events(run_id)
    return {
        "board": run_board(projection),
        "timeline": spec_timeline(projection, events),
        "evidence": evidence_view(projection),
        "context": context_view(projection),
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
