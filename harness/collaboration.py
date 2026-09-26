"""Pure rules for department requests, result ownership, and work resumption."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .models import (
    DEPARTMENTS, PRODUCT_ACTIVE, QUALITY_ACTIVE, TERMINAL_PHASES, CollaborationRequest, Event,
    EventType, RunProjection, department_for_phase, hash_bytes, json_dumps,
)
from .tools import SUBMIT_KINDS, TOOL_DEFS


_MUTATIONS = {"write_file", "edit_range", "delete_file", "move_file"}
_READS = {"read_file", "list_files"}
_CHECKS = {"run_check"}
_CLAIMABLE_TOOLS = _MUTATIONS | _CHECKS
_ACCEPTED_RESULTS = {
    EventType.SPEC_ACCEPTED, EventType.PRODUCT_DECISION_ACCEPTED,
    EventType.PLAN_ACCEPTED, EventType.DELIVERY_ACCEPTED,
}
_GUIDANCE_ACCEPTED = _ACCEPTED_RESULTS | {EventType.COLLABORATION_REQUESTED}
_GUIDANCE_RESPONSE_STATUSES = {"explained", "completed", "declined", "needs_work"}


def request_basis(projection: RunProjection) -> dict[str, Any]:
    return {
        "intend_hash": hash_bytes(projection.task.encode("utf-8")),
        "effective_contract_hash": _content_hash(projection.effective_contract),
        "engineering_plan_hash": _content_hash(projection.engineering_plan),
        "delivery_spec_hash": _content_hash(projection.delivery_spec),
        "phase": projection.phase,
    }


def allowed_proposal_kinds(projection: RunProjection, department: str) -> set[str]:
    if projection.phase in TERMINAL_PHASES or department not in DEPARTMENTS:
        return set()
    request = projection.pending_request
    has_guidance = _has_pending_guidance(projection, department)
    if request is not None:
        if request.status != "open" or department != request.recipient:
            return set()
        allowed = {"collaboration_response"}
        if request.request_type == "action" and request.action == "revise_requirements":
            allowed.update({"product_spec", "product_decision"})
        if request.request_type == "action" and request.action == "revise_delivery":
            allowed.update({"engineering_plan", "delivery_spec"})
        if has_guidance:
            allowed.add("department_guidance_response")
        return allowed
    if department != department_for_phase(projection.phase):
        return _diverted_guidance_kinds(department, projection) if has_guidance else set()
    allowed = {"collaboration_request"} | {
        "product": {"product_spec", "product_decision"},
        "engineering": {"engineering_plan", "delivery_spec"},
        "quality": {"qa_review"},
    }[department]
    if has_guidance:
        allowed.add("department_guidance_response")
    if projection.input_version > projection.processed_input_version:
        return allowed - {"product_decision"} if department == "product" else set()
    return allowed


def request_errors(proposal: dict[str, Any], projection: RunProjection,
                   department: str) -> list[dict[str, str]]:
    errors = []
    if projection.pending_request is not None:
        errors.append(_error("request", "finish the pending request before starting another request"))
    if department not in DEPARTMENTS:
        errors.append(_error("requester", "only the current working department can start a request"))
    elif (department != department_for_phase(projection.phase)
          and not _has_pending_guidance(projection, department)):
        errors.append(_error("requester", "only the current working department can start a request"))
    recipient = proposal.get("recipient")
    if recipient not in DEPARTMENTS or recipient == department:
        errors.append(_error("recipient", "recipient must be a different department"))
    for field in ("question", "background", "expected_result"):
        if not isinstance(proposal.get(field), str) or not proposal[field].strip():
            errors.append(_error(field, f"{field} must be a non-empty string"))
    request_type, action = proposal.get("request_type"), proposal.get("action")
    if request_type not in {"consultation", "action"}:
        errors.append(_error("request_type", "request_type must be consultation or action"))
    elif request_type == "consultation":
        if action is not None:
            errors.append(_error("action", "a consultation cannot authorize an action"))
    elif action not in {"inspect", "check", "revise_requirements", "revise_delivery"}:
        errors.append(_error("action", "an action request requires a supported action"))
    elif action in {"revise_requirements", "revise_delivery"}:
        expected = "product" if action == "revise_requirements" else "engineering"
        if recipient != expected:
            errors.append(_error("recipient", f"{action} requires the {expected} department"))
        if projection.effective_contract is None:
            errors.append(_error("effective_contract", "revision requires an existing effective contract"))
        if projection.input_version > projection.processed_input_version:
            errors.append(_error("input_version", "accept the pending user input in a complete ProductSpec before revising downstream work"))
    return errors


def tool_error(projection: RunProjection, department: str, name: str,
               args: dict[str, Any]) -> str | None:
    if name in SUBMIT_KINDS and SUBMIT_KINDS[name] not in allowed_proposal_kinds(projection, department):
        return "This proposal is not permitted in the current department work."
    request = projection.pending_request
    if request is None:
        return None
    if request.status != "open" or department != request.recipient or projection.phase in TERMINAL_PHASES:
        return "Only the recipient of the open request may act."
    if TOOL_DEFS.get(name, {}).get("access") == "write" and not (
        request.request_type == "action" and request.action == "revise_delivery"
    ):
        return "This request permits reading and checking, but does not authorize file changes."
    return None


def request_still_applicable(request: CollaborationRequest, projection: RunProjection,
                             events: list[Event]) -> bool:
    creation = _creation(request, events)
    if (creation is None or request.status != "open" or request.run_id != projection.run_id
            or projection.phase in TERMINAL_PHASES or projection.pending_request is None
            or projection.pending_request.id != request.id):
        return False
    expected = dict(request.basis)
    for event in sorted(events, key=lambda item: item.seq):
        if event.run_id != request.run_id or event.seq <= creation.seq:
            continue
        payload = event.payload
        if (event.type in {EventType.COLLABORATION_RESPONDED, EventType.COLLABORATION_CLOSED}
                and payload.get("request_id") == request.id):
            return False
        if event.type in _ACCEPTED_RESULTS | {EventType.CONTRACT_ACCEPTED}:
            if not _owned(event, request, creation) or not _authorized_result(event.type, request):
                return False
            if event.type == EventType.CONTRACT_ACCEPTED:
                if expected["effective_contract_hash"] != payload.get("content_hash"):
                    expected["engineering_plan_hash"] = None
                    expected["delivery_spec_hash"] = None
                expected["effective_contract_hash"] = payload.get("content_hash")
            elif event.type == EventType.SPEC_ACCEPTED:
                expected["delivery_spec_hash"] = None
            elif event.type == EventType.PLAN_ACCEPTED:
                expected["engineering_plan_hash"] = payload.get("content_hash")
                expected["delivery_spec_hash"] = None
            elif event.type == EventType.DELIVERY_ACCEPTED:
                expected["delivery_spec_hash"] = payload.get("content_hash")
        elif event.type == EventType.TOOL_CALLED and payload.get("name") in _MUTATIONS and payload.get("ok"):
            if not _owned(event, request, creation) or request.action != "revise_delivery":
                return False
            if _tool_result(event, request, creation, events) is None:
                return False
            expected["delivery_spec_hash"] = None
    return expected == request_basis(projection)


def response_errors(proposal: dict[str, Any], projection: RunProjection, department: str,
                    events: list[Event], *, snapshot_hash: str) -> list[dict[str, str]]:
    request = projection.pending_request
    if request is None:
        return [_error("request_id", "there is no open request")]
    errors = []
    if proposal.get("request_id") != request.id or department != request.recipient:
        errors.append(_error("request_id", "the response must belong to this request and its recipient"))
    if not request_still_applicable(request, projection, events):
        errors.append(_error("request_id", "the request is closed or its work basis has been superseded"))
    statuses = {"answered", "declined", "needs_work"} if request.request_type == "consultation" else {
        "completed", "declined", "needs_work"
    }
    status = proposal.get("status")
    if status not in statuses:
        errors.append(_error("status", f"this request requires one of: {', '.join(sorted(statuses))}"))
    if not isinstance(proposal.get("text"), str) or not proposal["text"].strip():
        errors.append(_error("text", "a response explanation is required"))
    references = proposal.get("result_event_ids")
    if not isinstance(references, list) or any(not isinstance(item, str) or not item for item in references):
        return errors + [_error("result_event_ids", "result_event_ids must be a list of event IDs")]
    if len(references) != len(set(references)):
        errors.append(_error("result_event_ids", "result event IDs must be unique"))
    creation = _creation(request, events)
    indexed = {event.event_id: event for event in events}
    results = []
    for reference in references:
        event = indexed.get(reference)
        if event is None or creation is None or not _owned(event, request, creation):
            errors.append(_error("result_event_ids", f"{reference} is not a result of this request's recipient"))
            continue
        if event.type == EventType.TOOL_CALLED:
            result = _tool_result(event, request, creation, events)
            if result is None:
                errors.append(_error("result_event_ids", f"{reference} has no matching host tool execution"))
                continue
            if status in {"completed", "answered"} and not _usable_tool_result(event, result, projection, snapshot_hash):
                errors.append(_error("result_event_ids", f"{reference} is failed, changed, or no longer bound to the current work"))
                continue
        elif event.type not in _ACCEPTED_RESULTS or not _authorized_result(event.type, request):
            errors.append(_error("result_event_ids", f"{reference} is not an accepted result allowed by this request"))
            continue
        results.append(event)
    if status == "completed" and not _has_completed_action(request, projection, results, snapshot_hash):
        errors.append(_error("result_event_ids", "completed requires a current host result for the requested action"))
    return errors


def guidance_response_errors(proposal: dict[str, Any], projection: RunProjection, department: str,
                             events: list[Event], *, snapshot_hash: str) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not isinstance(proposal.get("text"), str) or not proposal["text"].strip():
        errors.append(_error("text", "a response explanation is required"))
    status = proposal.get("status")
    if status not in _GUIDANCE_RESPONSE_STATUSES:
        errors.append(_error("status", "status must be explained, completed, declined, or needs_work"))
    references = proposal.get("result_event_ids")
    if not isinstance(references, list) or any(not isinstance(item, str) or not item for item in references):
        return errors + [_error("result_event_ids", "result_event_ids must be a list of event IDs")]
    if len(references) != len(set(references)):
        errors.append(_error("result_event_ids", "result event IDs must be unique"))
    guidance = next((item for item in projection.department_guidance
                     if item.id == proposal.get("guidance_id")), None)
    claimable_ids = {
        event.event_id
        for event in guidance_claimable_results(
            projection, department, events, snapshot_hash, guidance=guidance,
        )
    } if guidance is not None else set()
    if status == "completed":
        for reference in references:
            if reference not in claimable_ids:
                errors.append(_error(
                    "result_event_ids",
                    f"{reference} is not a result of this guidance's adopted work",
                ))
        if not claimable_ids:
            errors.append(_error(
                "result_event_ids",
                "completed requires a current host result produced after this guidance was adopted",
            ))
        return errors
    indexed = {event.event_id: event for event in events}
    owned = lambda item: _guidance_owned(item, projection, department)
    for reference in references:
        event = indexed.get(reference)
        if event is None or not owned(event):
            errors.append(_error("result_event_ids", f"{reference} is not a result of this department's current work"))
            continue
        if event.type == EventType.PROPOSAL_REJECTED:
            errors.append(_error("result_event_ids", f"{reference} is not an accepted result allowed by this guidance"))
    return errors


def guidance_claimable_results(projection: RunProjection, department: str, events: list[Event],
                               snapshot_hash: str, *, guidance: Any | None = None) -> list[Event]:
    items = [guidance] if guidance is not None else [
        item for item in projection.department_guidance
        if item.department == department and item.status in {"received", "in_input"}
    ]
    consumed = _consumed_guidance_result_ids(events, projection.run_id)
    found: list[Event] = []
    seen: set[str] = set()
    for item in items:
        if item is None:
            continue
        after_seq = _event_seq(events, item.created_event_id)
        if after_seq is None:
            continue
        activation_ids: set[str] = set()
        current = projection.last_activations.get(department)
        if current:
            activation_ids.add(current)
        if item.applied_activation_id:
            activation_ids.add(item.applied_activation_id)
        activation_ids.update(_applied_activation_ids(item.id, projection, events))
        for event in _claimable_results_for_activations(
                projection, department, events, snapshot_hash, activation_ids):
            if event.seq <= after_seq or event.event_id in consumed or event.event_id in seen:
                continue
            found.append(event)
            seen.add(event.event_id)
    return found


def guidance_bound_result_ids(proposal: dict[str, Any], projection: RunProjection, department: str,
                              events: list[Event], *, snapshot_hash: str, guidance: Any) -> list[str]:
    provided = [item for item in proposal.get("result_event_ids", []) if isinstance(item, str) and item]
    if proposal.get("status") != "completed":
        return list(dict.fromkeys(provided))
    return [
        event.event_id
        for event in guidance_claimable_results(
            projection, department, events, snapshot_hash, guidance=guidance,
        )
    ]


def guidance_result_summaries(projection: RunProjection, department: str, events: list[Event],
                              snapshot_hash: str) -> list[dict[str, Any]]:
    return [
        {
            "event_id": event.event_id,
            "type": event.type,
            "role": event.role,
            "name": event.payload.get("name"),
            "ok": event.payload.get("ok"),
            "content_hash": event.payload.get("content_hash"),
            "activation_id": event.payload.get("activation_id"),
        }
        for event in guidance_claimable_results(projection, department, events, snapshot_hash)
    ]


def guidance_resume_phase(yielded: dict[str, Any], projection: RunProjection) -> str:
    current = {
        "effective_contract_hash": _content_hash(projection.effective_contract),
        "engineering_plan_hash": _content_hash(projection.engineering_plan),
        "delivery_spec_hash": _content_hash(projection.delivery_spec),
    }
    yielded_hashes = {key: yielded.get(key) for key in current}
    if current == yielded_hashes:
        phase = yielded.get("phase") or projection.phase
        if phase in QUALITY_ACTIVE and projection.delivery_spec is None:
            return "ENGINEERING"
        return phase
    if projection.effective_contract is None:
        return "PRODUCT_SPEC"
    delivery = projection.delivery_spec
    if (delivery is not None
            and delivery.effective_contract_hash == current["effective_contract_hash"]
            and delivery.engineering_plan_hash == current["engineering_plan_hash"]):
        return "QUALITY"
    return "ENGINEERING"


def resume_phase(request: CollaborationRequest, projection: RunProjection, events: list[Event],
                 *, snapshot_hash: str) -> tuple[str, bool]:
    if projection.phase in TERMINAL_PHASES:
        return projection.phase, False
    delivery = projection.delivery_spec
    delivery_current = bool(delivery and delivery.code_tree_digest == snapshot_hash
                            and delivery.effective_contract_hash == _content_hash(projection.effective_contract)
                            and delivery.engineering_plan_hash == _content_hash(projection.engineering_plan))
    unchanged = request.basis == request_basis(projection)
    if unchanged and (delivery is None or delivery_current) and request_still_applicable(request, projection, events):
        return request.return_phase, True
    if projection.phase in PRODUCT_ACTIVE:
        return projection.phase, False
    if delivery_current:
        return "QUALITY", False
    return "ENGINEERING", False


def _has_completed_action(request: CollaborationRequest, projection: RunProjection,
                          results: list[Event], snapshot_hash: str) -> bool:
    if request.action in {"inspect", "check"}:
        names = _READS if request.action == "inspect" else _CHECKS
        return any(event.type == EventType.TOOL_CALLED and event.payload.get("name") in names for event in results)
    if request.action == "revise_requirements":
        return any(
            event.type == EventType.SPEC_ACCEPTED and event.payload.get("content_hash") == _content_hash(projection.product_spec)
            or event.type == EventType.PRODUCT_DECISION_ACCEPTED and any(
                event.payload.get("content_hash") == item.content_hash for item in projection.effective_decisions
            ) for event in results
        )
    delivery = projection.delivery_spec
    return bool(request.action == "revise_delivery" and delivery
                and delivery.code_tree_digest == snapshot_hash
                and delivery.effective_contract_hash == _content_hash(projection.effective_contract)
                and delivery.engineering_plan_hash == _content_hash(projection.engineering_plan)
                and any(event.type == EventType.DELIVERY_ACCEPTED
                        and event.payload.get("content_hash") == delivery.content_hash for event in results))


def _tool_result(event: Event, request: CollaborationRequest, creation: Event,
                 events: list[Event]) -> dict[str, Any] | None:
    return _host_tool_result(
        event, events, owned=lambda item: _owned(item, request, creation), after_seq=creation.seq)


def _host_tool_result(event: Event, events: list[Event], *, owned: Callable[[Event], bool],
                      after_seq: int) -> dict[str, Any] | None:
    payload = event.payload
    if not owned(event) or not all(payload.get(key) is not None for key in ("id", "name", "step_id", "activation_id")):
        return None
    started = [item for item in events if item.type == EventType.TOOL_STARTED
               and after_seq < item.seq < event.seq and owned(item)
               and all(item.payload.get(key) == payload.get(key) for key in ("id", "name", "activation_id", "step_id"))]
    if len(started) != 1:
        return None
    item = payload.get("input_item")
    if not isinstance(item, dict) or item.get("type") != "function_call_output" or item.get("call_id") != payload["id"]:
        return None
    try:
        result = json.loads(item["output"])
    except (KeyError, TypeError, ValueError):
        return None
    if not isinstance(result, dict) or not isinstance(result.get("ok"), bool) or result["ok"] != payload.get("ok"):
        return None
    output_ref = payload.get("output_ref")
    if result.get("output") is not None:
        if not isinstance(output_ref, dict) or output_ref.get("content_hash") != hash_bytes(json_dumps(result["output"]).encode("utf-8")):
            return None
    return result


def _usable_tool_result(event: Event, result: dict[str, Any], projection: RunProjection,
                        snapshot_hash: str) -> bool:
    if not result["ok"]:
        return False
    if event.payload.get("name") not in _CHECKS:
        return event.payload.get("name") in _READS | _MUTATIONS
    output = result.get("output")
    if not isinstance(output, dict):
        return False
    return (output.get("executor") == "host" and output.get("tree_changed") is False
            and type(output.get("exit_code")) is int and output.get("snapshot_hash") == snapshot_hash
            and output.get("activation_id") == event.payload.get("activation_id")
            and output.get("effective_contract_hash") == _content_hash(projection.effective_contract)
            and output.get("engineering_plan_hash") == _content_hash(projection.engineering_plan)
            and output.get("delivery_spec_hash") == _content_hash(projection.delivery_spec)
            and output.get("product_spec_hash") == _content_hash(projection.product_spec))


def _authorized_result(event_type: str, request: CollaborationRequest) -> bool:
    if request.request_type != "action":
        return False
    if request.action == "revise_requirements":
        return event_type in {EventType.SPEC_ACCEPTED, EventType.PRODUCT_DECISION_ACCEPTED, EventType.CONTRACT_ACCEPTED}
    return request.action == "revise_delivery" and event_type in {EventType.PLAN_ACCEPTED, EventType.DELIVERY_ACCEPTED}


def _creation(request: CollaborationRequest, events: list[Event]) -> Event | None:
    return next((event for event in events if event.event_id == request.created_event_id
                 and event.run_id == request.run_id and event.type == EventType.COLLABORATION_REQUESTED
                 and event.role == request.requester and event.payload.get("id") == request.id
                 and event.payload.get("content_hash") == request.content_hash), None)


def _owned(event: Event, request: CollaborationRequest, creation: Event) -> bool:
    return (event.run_id == request.run_id and event.seq > creation.seq
            and event.role == request.recipient and event.payload.get("request_id") == request.id)


def _guidance_owned(event: Event, projection: RunProjection, department: str) -> bool:
    return event.run_id == projection.run_id and event.role == department


def _event_seq(events: list[Event], event_id: str | None) -> int | None:
    if not event_id:
        return None
    event = next((item for item in events if item.event_id == event_id), None)
    return None if event is None else event.seq


def _consumed_guidance_result_ids(events: list[Event], run_id: str) -> set[str]:
    consumed: set[str] = set()
    for event in events:
        if event.run_id != run_id or event.type != EventType.DEPARTMENT_GUIDANCE_RESPONDED:
            continue
        for item in event.payload.get("result_event_ids") or []:
            if isinstance(item, str) and item:
                consumed.add(item)
    return consumed


def _guidance_tool_current(event: Event, projection: RunProjection) -> bool:
    return (event.payload.get("effective_contract_hash") == _content_hash(projection.effective_contract)
            and event.payload.get("engineering_plan_hash") == _content_hash(projection.engineering_plan))


def _current_guidance_result(event: Event, projection: RunProjection, snapshot_hash: str) -> bool:
    payload = event.payload
    if event.type == EventType.SPEC_ACCEPTED:
        return projection.product_spec is not None and payload.get("content_hash") == projection.product_spec.content_hash
    if event.type == EventType.PRODUCT_DECISION_ACCEPTED:
        return any(item.content_hash == payload.get("content_hash") for item in projection.effective_decisions)
    if event.type == EventType.PLAN_ACCEPTED:
        return projection.engineering_plan is not None and payload.get("content_hash") == projection.engineering_plan.content_hash
    if event.type == EventType.DELIVERY_ACCEPTED:
        delivery = projection.delivery_spec
        return bool(delivery and delivery.status == "active"
                    and payload.get("content_hash") == delivery.content_hash
                    and delivery.code_tree_digest == snapshot_hash
                    and delivery.effective_contract_hash == _content_hash(projection.effective_contract)
                    and delivery.engineering_plan_hash == _content_hash(projection.engineering_plan))
    pending = projection.pending_request
    return bool(event.type == EventType.COLLABORATION_REQUESTED and pending is not None
                and pending.created_event_id == event.event_id and pending.requester == event.role)


def _applied_activation_ids(guidance_id: str, projection: RunProjection, events: list[Event]) -> set[str]:
    return {
        str(event.payload.get("activation_id"))
        for event in events
        if event.type == EventType.DEPARTMENT_GUIDANCE_APPLIED and event.run_id == projection.run_id
        and guidance_id in event.payload.get("guidance_ids", []) and event.payload.get("activation_id")
    }


def _claimable_results_for_activations(projection: RunProjection, department: str, events: list[Event],
                                       snapshot_hash: str, activation_ids: set[str]) -> list[Event]:
    activation_ids = {item for item in activation_ids if item}
    starts = [event for event in events
              if event.type == EventType.DEPARTMENT_ACTIVATED and event.run_id == projection.run_id
              and event.role == department and event.payload.get("activation_id") in activation_ids]
    if not starts:
        return []
    windows: list[tuple[Event, int | None]] = []
    for start in starts:
        nxt = next((event for event in events
                    if event.type == EventType.DEPARTMENT_ACTIVATED and event.run_id == projection.run_id
                    and event.role == department and event.seq > start.seq), None)
        windows.append((start, None if nxt is None else nxt.seq))
    owned = lambda item: _guidance_owned(item, projection, department)
    found: list[Event] = []
    seen: set[str] = set()
    for event in events:
        if not owned(event) or event.event_id in seen:
            continue
        start = next((item for item, end in windows
                      if item.seq < event.seq and (end is None or event.seq < end)), None)
        if start is None:
            continue
        if event.type == EventType.TOOL_CALLED:
            if (event.payload.get("activation_id") != start.payload.get("activation_id")
                    or event.payload.get("name") not in _CLAIMABLE_TOOLS):
                continue
            result = _host_tool_result(event, events, owned=owned, after_seq=start.seq)
            if result is None or not result["ok"]:
                continue
            if event.payload.get("name") in _MUTATIONS and not _guidance_tool_current(event, projection):
                continue
            if event.payload.get("name") in _CHECKS and not _usable_tool_result(event, result, projection, snapshot_hash):
                continue
            found.append(event)
            seen.add(event.event_id)
        elif event.type in _GUIDANCE_ACCEPTED and _current_guidance_result(event, projection, snapshot_hash):
            found.append(event)
            seen.add(event.event_id)
    return found


def _has_pending_guidance(projection: RunProjection, department: str) -> bool:
    return any(item.department == department and item.status in {"received", "in_input"}
               for item in projection.department_guidance)


def _diverted_guidance_kinds(department: str, projection: RunProjection) -> set[str]:
    if department == "product":
        allowed = {"collaboration_request", "product_spec", "product_decision", "department_guidance_response"}
        if projection.input_version > projection.processed_input_version:
            return allowed - {"product_decision"}
        return allowed
    return {"department_guidance_response", "collaboration_request"}


def _content_hash(value: Any) -> str | None:
    return None if value is None else value.content_hash


def _error(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}
