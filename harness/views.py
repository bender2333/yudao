"""只读视图：从 Event Store 与投影装配 REST 响应。"""

from __future__ import annotations

import json
from typing import Any

from .event_store import EventStore
from .models import Event, EventType, GIT_VERSION_EVENTS, json_dumps
from .projection import RunProjection, project_run


def _plain(value: Any) -> Any:
    return json.loads(json_dumps(value))


def compaction_coverage(item: Any) -> dict[str, Any] | None:
    """Return seq / covered_through range for a compaction record or event."""

    if item is None:
        return None
    payload = getattr(item, "payload", None)
    if not isinstance(payload, dict):
        payload = item if isinstance(item, dict) else None
    if not isinstance(payload, dict):
        return None
    body = payload
    checkpoint = body.get("checkpoint") if isinstance(body.get("checkpoint"), dict) else {}
    refs = body.get("source_refs") if isinstance(body.get("source_refs"), list) else []
    seqs = [entry.get("seq") for entry in refs if isinstance(entry, dict) and type(entry.get("seq")) is int]
    event_ids = [entry.get("event_id") for entry in refs if isinstance(entry, dict) and entry.get("event_id")]
    event_id = getattr(item, "event_id", None) or body.get("source_event_id") or body.get("event_id") or body.get("compaction_event_id")
    covered_id = checkpoint.get("covered_through_event_id")
    covered_seq = next(
        (entry.get("seq") for entry in refs
         if isinstance(entry, dict) and entry.get("event_id") == covered_id and type(entry.get("seq")) is int),
        None,
    )
    if event_id is None and covered_id is None and not seqs:
        return None
    return {
        "compaction_event_id": event_id,
        "covered_through_event_id": covered_id,
        "covered_through_seq": covered_seq,
        "source_seq_from": min(seqs) if seqs else None,
        "source_seq_through": max(seqs) if seqs else None,
        "source_event_ids": event_ids,
    }


def _compaction_entry(item: Any) -> dict[str, Any]:
    payload = _plain(item)
    coverage = compaction_coverage(payload)
    if coverage is not None:
        payload["coverage"] = coverage
    return payload


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
    latest_request = projection.model_requests[-1] if projection.model_requests else None
    return {
        "run_id": projection.run_id,
        "project_id": projection.project_id,
        "work_item_id": projection.work_item_id,
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
        "provider_bindings": _plain(projection.provider_bindings),
        "protocol": None if latest_request is None else latest_request.get("protocol"),
        "model_requests": _plain(projection.model_requests),
        "requested_provider": projection.requested_provider,
        "requested_model": projection.requested_model,
        "actual_provider": projection.actual_provider,
        "actual_model": projection.actual_model,
        "input_version": projection.input_version,
        "product_work_input_version": projection.product_work_input_version,
        "processed_input_version": projection.processed_input_version,
        "department_guidance": _plain(projection.department_guidance),
        "pending_guidance_count": sum(item.status in {"received", "in_input"}
                                       for item in projection.department_guidance),
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
        "compactions": [_compaction_entry(item) for item in projection.compactions],
        "sessions": _plain(projection.sessions),
        "stop_reason": projection.stop_reason,
        "human_action": projection.human_action,
        "department_guidance": _plain(projection.department_guidance),
    }


def _retry_record(event: Event, *, status: str, base: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = event.payload or {}
    previous = base or {}
    return {
        "status": status,
        "department": event.department or previous.get("department"),
        "activation_id": payload.get("activation_id", previous.get("activation_id")),
        "step_id": payload.get("step_id", previous.get("step_id")),
        "attempt": payload.get("attempt", previous.get("attempt")),
        "max_attempts": payload.get("max_attempts", previous.get("max_attempts", 3)),
        "next_step_id": payload.get("next_step_id", previous.get("next_step_id")),
        "delay_sec": payload.get("delay_sec", previous.get("delay_sec")),
        "next_attempt": payload.get("next_attempt", previous.get("next_attempt")),
        "last_reason": payload.get("reason", previous.get("last_reason")) or event.stop_reason,
        "last_error": payload.get("error", previous.get("last_error")) or event.error,
        "retryable": payload.get("retryable", previous.get("retryable")),
        "root_step_id": payload.get("root_step_id", previous.get("root_step_id")),
        "retry_of_step_id": payload.get("retry_of_step_id", previous.get("retry_of_step_id")),
    }


def retry_view(events: list[Event]) -> dict[str, Any]:
    """Derive the latest provider retry state without extending the run projection."""

    latest: dict[str, Any] | None = None
    attempts: dict[tuple[str | None, int | None], dict[str, Any]] = {}
    scheduled: dict[tuple[str | None, int | None], dict[str, Any]] = {}
    for event in events:
        payload = event.payload or {}
        activation_id = payload.get("activation_id")
        step_id = payload.get("step_id")
        key = (activation_id, step_id)
        if event.type == EventType.DEPARTMENT_ACTIVATED:
            latest = None
        elif event.type == EventType.MODEL_ATTEMPT_FAILED:
            latest = _retry_record(event, status="failed")
            attempts[key] = latest
        elif event.type == EventType.MODEL_RETRY_SCHEDULED:
            failure = attempts.get(key)
            latest = _retry_record(event, status="waiting", base=failure)
            scheduled[(activation_id, payload.get("next_step_id"))] = latest
        elif event.type == EventType.CONTEXT_ASSEMBLED and payload.get("purpose") in {"work", "compaction"}:
            retry = scheduled.pop(key, None)
            if retry is not None:
                latest = _retry_record(event, status="prepared", base=retry)
        elif event.type == EventType.MODEL_REQUESTED:
            attempt = payload.get("attempt", 1)
            retry = (latest if attempt != 1 and latest and latest.get("activation_id") == activation_id else None)
            request_record = _retry_record(event, status="requesting", base=retry)
            attempts[key] = request_record
            if retry is not None or attempt != 1:
                latest = request_record
            else:
                latest = None
        elif event.type == EventType.MODEL_MESSAGE:
            retry = attempts.get(key)
            if (retry is not None and retry.get("attempt", 1) > 1
                    and latest is not None and latest.get("activation_id") == activation_id
                    and latest.get("step_id") == step_id):
                latest = _retry_record(event, status="active", base=retry)
        elif event.type == EventType.MODEL_ATTEMPT_FINISHED:
            latest = None
        elif event.type == EventType.RUN_FAILED and latest is not None:
            latest = _retry_record(event, status="cancelled" if event.stop_reason == "cancelled" else "failed", base=latest)
    if latest is None:
        return {
            "status": "idle",
            "department": None,
            "activation_id": None,
            "step_id": None,
            "attempt": None,
            "max_attempts": 3,
            "next_step_id": None,
            "delay_sec": None,
            "next_attempt": None,
            "last_reason": None,
            "last_error": None,
            "retryable": None,
            "root_step_id": None,
            "retry_of_step_id": None,
        }
    return latest


def event_card(event: Event) -> dict[str, Any]:
    payload = event.payload or {}
    return {
        "event_id": event.event_id,
        "position": event.position,
        "seq": event.stream_version,
        "type": event.type,
        "department": event.department,
        "state_before": event.state_before,
        "state_after": event.state_after,
        "stop_reason": event.stop_reason,
        "error": event.error or (event.payload or {}).get("error"),
        "session_id": event.session_id,
        "provider": event.provider,
        "model": event.model,
        "provider_config_id": payload.get("provider_config_id"),
        "model_id": payload.get("model_id"),
        "protocol": payload.get("protocol"),
        "base_url": payload.get("base_url"),
        "requested_model": payload.get("requested_model"),
        "actual_provider": payload.get("actual_provider"),
        "actual_model": payload.get("actual_model"),
        "credential_ref": payload.get("credential_ref"),
        "credential_version": payload.get("credential_version"),
        "effective_context_window": payload.get("effective_context_window"),
        "configured_max_output_tokens": payload.get("configured_max_output_tokens"),
        "context_digest": event.context_digest,
        "created_at": event.created_at,
        "summary": event.summary(),
        "artifact_hashes": event.artifact_hashes,
        "attempt": payload.get("attempt"),
        "attempt_id": payload.get("attempt_id"),
        "logical_call_id": payload.get("logical_call_id"),
        "collaboration_request_id": payload.get("collaboration_request_id", payload.get("request_id")),
        "context_event_id": payload.get("context_event_id"),
        "max_attempts": payload.get("max_attempts"),
        "retry_of_step_id": payload.get("retry_of_step_id"),
        "root_step_id": payload.get("root_step_id"),
        "reason": payload.get("reason"),
        "retryable": payload.get("retryable"),
        "delay_sec": payload.get("delay_sec"),
        "next_attempt": payload.get("next_attempt"),
        "next_step_id": payload.get("next_step_id"),
        "provider_response_id": payload.get("provider_response_id"),
        "status": payload.get("status"),
        "started_at": payload.get("started_at"),
        "finished_at": payload.get("finished_at"),
        "duration_ms": payload.get("duration_ms"),
        "response_ref": _plain(payload.get("response_ref")),
        "stream_events_ref": _plain(payload.get("stream_events_ref")),
        "stream_event_count": payload.get("stream_event_count"),
        "collection_scope": _plain(payload.get("collection_scope")),
        "git_version": _plain(event.payload.get("git_version")) if event.type in GIT_VERSION_EVENTS else None,
        "input_save_failure": _plain(event.payload.get("input_save_failure"))
        if event.type == EventType.RUN_FAILED and event.stop_reason == "cancelled" else None,
        "guidance_ids": _plain(payload.get("guidance_ids", [])),
        "guidance_id": payload.get("guidance_id"),
    }


def run_payload(store: EventStore, run_id: str) -> dict[str, Any]:
    projection = project_run(store, run_id)
    events = store.list_events(run_id)
    retry = retry_view(events)
    board = run_board(projection)
    board["retry"] = retry
    return {
        "board": board,
        "timeline": spec_timeline(projection, events),
        "evidence": evidence_view(projection, events),
        "context": context_view(projection),
        "inputs": _with_git(projection.inputs, events),
        "department_guidance": _plain(projection.department_guidance),
        "prompts": {
            # 部门 Prompt 来自项目部门设置，run 内没有副本；这里只列出每次激活记录的版本与摘要
            "activations": [
                {"event_id": event.event_id, "department": event.department, **event.payload}
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
