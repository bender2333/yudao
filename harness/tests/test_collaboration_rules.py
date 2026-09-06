from dataclasses import replace

import pytest

from harness.collaboration import (
    allowed_proposal_kinds, request_basis, request_errors, request_still_applicable,
    response_errors, resume_phase, tool_error,
)
from harness.models import (
    ArtifactRef, CollaborationRequest, DeliverySpec, EffectiveContract, EngineeringPlan,
    Event, EventType, ProductDecision, ProductSpec, RunProjection, hash_bytes, json_dumps,
)


def event(seq, kind, payload, *, role="engineering", run_id="run"):
    return Event(f"event-{seq}", run_id, seq, kind, role, None, "QUALITY", "QUALITY",
                 payload, [], None, None, None, None, None, None, "2026-09-06")


def work(phase="QUALITY"):
    projection = RunProjection(run_id="run", task="Build a CLI.", phase=phase)
    projection.product_spec = ProductSpec(
        "spec", "run", 1, None, "spec-hash", "product", "active", "spec-event",
        "CLI", ["Print text"], [], [], ["Text appears"], [], [], [],
    )
    projection.effective_contract = EffectiveContract(
        "contract-hash", 1, "spec-hash", [], "contract-event", ArtifactRef("prd", "prd-hash", "PRD.md"),
    )
    projection.engineering_plan = EngineeringPlan(
        "plan", "run", "plan-hash", 1, None, "active", "plan-event", "contract-hash",
        "Build", ["cli.py"], [], [], [], "Initial plan", ArtifactRef("plan", "plan-hash", "PLAN.md"),
    )
    projection.delivery_spec = DeliverySpec(
        "delivery", "run", 1, None, "delivery-hash", "engineering", "active", "delivery-event",
        "spec-hash", "contract-hash", "plan-hash", "CLI", ["cli.py"], [], [], [],
        "tree-hash", ArtifactRef("tree", "tree-ref", "tree.json"),
    )
    return projection


def pending(projection, recipient="engineering", request_type="action", action="revise_delivery"):
    requester = {"PRODUCT_SPEC": "product", "ENGINEERING": "engineering", "QUALITY": "quality"}[projection.phase]
    request = CollaborationRequest(
        "request", "run", "request-hash", "event-1", requester, recipient, request_type, action,
        "Investigate", "Current work", "A concrete result", request_basis(projection), projection.phase, "open",
    )
    projection.pending_request = request
    projection.requests.append(request)
    created = event(1, EventType.COLLABORATION_REQUESTED,
                    {"id": request.id, "content_hash": request.content_hash}, role=requester)
    return request, [created]


def tool_events(events, name="write_file", *, output="written", ok=True, recipient="engineering"):
    seq = max(item.seq for item in events) + 1
    identity = {"id": f"call-{seq}", "name": name, "activation_id": "activation", "step_id": 1,
                "request_id": "request"}
    events.append(event(seq, EventType.TOOL_STARTED, identity, role=recipient))
    result = {"ok": ok, "output": output, "error": None if ok else "failed"}
    payload = {**identity, "ok": ok,
               "input_item": {"type": "function_call_output", "call_id": identity["id"], "output": json_dumps(result)}}
    if output is not None:
        payload["output_ref"] = {"content_hash": hash_bytes(json_dumps(output).encode("utf-8"))}
    called = event(seq + 1, EventType.TOOL_CALLED, payload, role=recipient)
    events.append(called)
    return called


def response(status="completed", refs=None):
    return {"kind": "collaboration_response", "request_id": "request", "status": status,
            "text": "Observed result", "result_event_ids": refs or []}


def check_output(projection, **changes):
    return {
        "name": "check", "executor": "host", "exit_code": 0, "tree_changed": False,
        "snapshot_hash": "tree-hash", "activation_id": "activation", "product_spec_hash": "spec-hash",
        "effective_contract_hash": "contract-hash", "engineering_plan_hash": "plan-hash",
        "delivery_spec_hash": projection.delivery_spec.content_hash if projection.delivery_spec else None,
        **changes,
    }


@pytest.mark.parametrize("requester,phase,recipient", [
    ("product", "PRODUCT_SPEC", "engineering"), ("product", "PRODUCT_SPEC", "quality"),
    ("engineering", "ENGINEERING", "product"), ("engineering", "ENGINEERING", "quality"),
    ("quality", "QUALITY", "product"), ("quality", "QUALITY", "engineering"),
])
def test_all_department_directions_can_consult(requester, phase, recipient):
    projection = work(phase)
    proposal = {"recipient": recipient, "request_type": "consultation", "action": None,
                "question": "Question", "background": "Background", "expected_result": "Answer"}
    assert request_errors(proposal, projection, requester) == []
    _, events = pending(projection, recipient, "consultation", None)
    assert response_errors(response("answered"), projection, recipient, events, snapshot_hash="tree-hash") == []


def test_pre_prd_consultation_does_not_grant_write_or_contract_permissions():
    projection = RunProjection(run_id="run", task="Initial intent", phase="PRODUCT_SPEC")
    request, events = pending(projection, "engineering", "consultation", None)
    assert request.basis["effective_contract_hash"] is None
    assert request_still_applicable(request, projection, events)
    assert tool_error(projection, "engineering", "read_file", {}) is None
    assert tool_error(projection, "engineering", "run_check", {}) is None
    assert tool_error(projection, "engineering", "write_file", {})
    assert allowed_proposal_kinds(projection, "engineering") == {"collaboration_response"}


@pytest.mark.parametrize("phase,department,kind", [
    ("PRODUCT_SPEC", "product", "product_spec"), ("REWORK_PRODUCT", "product", "product_decision"),
    ("ENGINEERING", "engineering", "engineering_plan"), ("REWORK_ENGINEERING", "engineering", "delivery_spec"),
    ("QUALITY", "quality", "qa_review"), ("DELIVERY", "quality", "qa_review"),
])
def test_normal_proposals_remain_available(phase, department, kind):
    assert kind in allowed_proposal_kinds(work(phase), department)


def test_nested_request_and_wrong_recipient_are_rejected():
    projection = work()
    pending(projection)
    proposal = {"recipient": "quality", "request_type": "consultation", "question": "Q",
                "background": "B", "expected_result": "A"}
    assert any(item["field"] == "request" for item in request_errors(proposal, projection, "engineering"))
    assert tool_error(projection, "engineering", "submit_request", proposal)
    assert allowed_proposal_kinds(projection, "quality") == set()


@pytest.mark.parametrize("action,recipient", [("revise_requirements", "engineering"), ("revise_delivery", "product")])
def test_revision_requires_responsible_department_and_contract(action, recipient):
    projection = RunProjection(run_id="run", task="Intent", phase="QUALITY")
    errors = request_errors({"recipient": recipient, "request_type": "action", "action": action,
                             "question": "Q", "background": "B", "expected_result": "A"}, projection, "quality")
    assert {item["field"] for item in errors} == {"recipient", "effective_contract"}


@pytest.mark.parametrize("action", ["inspect", "check"])
def test_read_actions_cannot_submit_normative_proposals_or_mutate(action):
    projection = work()
    pending(projection, action=action)
    assert allowed_proposal_kinds(projection, "engineering") == {"collaboration_response"}
    assert tool_error(projection, "engineering", "write_file", {})
    assert tool_error(projection, "engineering", "submit_plan", {})


def test_action_cannot_finish_with_text_only_or_answered_status():
    projection = work()
    _, events = pending(projection, action="inspect")
    assert response_errors(response(), projection, "engineering", events, snapshot_hash="tree-hash")
    assert response_errors(response("answered"), projection, "engineering", events, snapshot_hash="tree-hash")
    assert response_errors(response("declined"), projection, "engineering", events, snapshot_hash="tree-hash") == []


def test_inspection_requires_real_event_id_and_matched_tool_pair():
    projection = work()
    _, events = pending(projection, action="inspect")
    called = tool_events(events, "read_file", output="print('hello')")
    assert response_errors(response(refs=[called.event_id]), projection, "engineering", events, snapshot_hash="tree-hash") == []
    assert response_errors(response(refs=[called.payload["id"]]), projection, "engineering", events, snapshot_hash="tree-hash")
    assert response_errors(response(refs=[called.event_id]), projection, "engineering", events[::2], snapshot_hash="tree-hash")


@pytest.mark.parametrize("field,value", [
    ("run_id", "another-run"), ("role", "product"), ("request_id", "another-request"),
    ("activation_id", "another-activation"), ("step_id", 2), ("id", "another-call"),
    ("name", "list_files"), ("seq", 0),
])
def test_results_cannot_be_borrowed_or_mismatched(field, value):
    projection = work()
    _, events = pending(projection, action="inspect")
    called = tool_events(events, "read_file", output="source")
    if field in {"run_id", "role", "seq"}:
        setattr(called, field, value)
    else:
        called.payload[field] = value
    assert response_errors(response(refs=[called.event_id]), projection, "engineering", events, snapshot_hash="tree-hash")


def test_tampered_structured_output_cannot_be_used():
    projection = work()
    _, events = pending(projection, action="inspect")
    called = tool_events(events, "read_file", output="real bytes")
    called.payload["input_item"]["output"] = json_dumps({"ok": True, "output": "invented", "error": None})
    assert response_errors(response(refs=[called.event_id]), projection, "engineering", events, snapshot_hash="tree-hash")


@pytest.mark.parametrize("exit_code", [0, 1, 127])
def test_host_check_completes_even_when_it_finds_a_failure(exit_code):
    projection = work()
    _, events = pending(projection, action="check")
    called = tool_events(events, "run_check", output=check_output(projection, exit_code=exit_code))
    assert response_errors(response(refs=[called.event_id]), projection, "engineering", events, snapshot_hash="tree-hash") == []


@pytest.mark.parametrize("change", [
    {"tree_changed": True}, {"snapshot_hash": "other-tree"}, {"executor": "model"},
    {"exit_code": "0"}, {"activation_id": "old-activation"}, {"effective_contract_hash": "old-contract"},
    {"engineering_plan_hash": "old-plan"}, {"delivery_spec_hash": "old-delivery"},
])
def test_unverifiable_checks_cannot_complete_action(change):
    projection = work()
    _, events = pending(projection, action="check")
    called = tool_events(events, "run_check", output=check_output(projection, **change))
    assert response_errors(response(refs=[called.event_id]), projection, "engineering", events, snapshot_hash="tree-hash")


def test_failed_tool_attempt_can_explain_needs_work_but_cannot_complete():
    projection = work()
    _, events = pending(projection, action="check")
    called = tool_events(events, "run_check", output=None, ok=False)
    assert response_errors(response(refs=[called.event_id]), projection, "engineering", events, snapshot_hash="tree-hash")
    assert response_errors(response("needs_work", [called.event_id]), projection, "engineering", events, snapshot_hash="tree-hash") == []


@pytest.mark.parametrize("status", ["declined", "needs_work"])
@pytest.mark.parametrize("name", ["write_file", "delete_file", "move_file"])
def test_partial_engineering_work_cannot_resume_old_quality(status, name):
    projection = work()
    request, events = pending(projection)
    called = tool_events(events, name)
    projection.delivery_spec = None
    assert request_still_applicable(request, projection, events)
    assert response_errors(response(status, [called.event_id]), projection, "engineering", events, snapshot_hash="changed-tree") == []
    assert response_errors(response(refs=[called.event_id]), projection, "engineering", events, snapshot_hash="changed-tree")
    assert resume_phase(request, projection, events, snapshot_hash="changed-tree") == ("ENGINEERING", False)
    assert request.basis["delivery_spec_hash"] == "delivery-hash"


def test_external_tree_change_does_not_resume_old_quality_even_without_tool_event():
    projection = work()
    request, events = pending(projection, action="inspect")
    assert resume_phase(request, projection, events, snapshot_hash="external-tree") == ("ENGINEERING", False)


def test_new_delivery_completes_request_and_requires_new_quality_work():
    projection = work()
    request, events = pending(projection)
    old_delivery = projection.delivery_spec
    tool_events(events)
    accepted = event(4, EventType.DELIVERY_ACCEPTED, {"request_id": request.id, "content_hash": "new-delivery"})
    events.append(accepted)
    projection.delivery_spec = replace(old_delivery, content_hash="new-delivery", code_tree_digest="new-tree")
    assert request_still_applicable(request, projection, events)
    assert response_errors(response(refs=[accepted.event_id]), projection, "engineering", events, snapshot_hash="new-tree") == []
    assert resume_phase(request, projection, events, snapshot_hash="new-tree") == ("QUALITY", False)


def test_requesting_product_work_is_not_skipped_by_new_delivery():
    projection = work("PRODUCT_SPEC")
    request, events = pending(projection)
    accepted = event(2, EventType.DELIVERY_ACCEPTED, {"request_id": request.id, "content_hash": "new-delivery"})
    events.append(accepted)
    projection.delivery_spec = replace(projection.delivery_spec, content_hash="new-delivery")
    assert resume_phase(request, projection, events, snapshot_hash="tree-hash") == ("PRODUCT_SPEC", False)


def test_formal_product_decision_updates_same_contract_and_invalidates_returned_work():
    projection = work()
    request, events = pending(projection, "product", "action", "revise_requirements")
    accepted = event(2, EventType.PRODUCT_DECISION_ACCEPTED,
                     {"request_id": request.id, "content_hash": "decision-hash"}, role="product")
    events.extend([accepted, event(3, EventType.CONTRACT_ACCEPTED,
                                  {"request_id": request.id, "content_hash": "new-contract"}, role="product")])
    projection.effective_decisions = [ProductDecision("decision", "run", "decision-hash", accepted.event_id,
                                                     "spec-hash", "Requirement", "Reason", request.id)]
    projection.effective_contract = replace(projection.effective_contract, content_hash="new-contract")
    projection.engineering_plan = None
    projection.delivery_spec = None
    assert request_still_applicable(request, projection, events)
    assert response_errors(response(refs=[accepted.event_id]), projection, "product", events, snapshot_hash="tree-hash") == []
    assert resume_phase(request, projection, events, snapshot_hash="tree-hash") == ("ENGINEERING", False)
    assert request.basis["effective_contract_hash"] == "contract-hash"


def test_external_contract_change_supersedes_request():
    projection = work()
    request, events = pending(projection, "product", "action", "revise_requirements")
    events.append(event(2, EventType.CONTRACT_ACCEPTED, {"content_hash": "external-contract"}, role="product"))
    projection.effective_contract = replace(projection.effective_contract, content_hash="external-contract")
    projection.engineering_plan = None
    projection.delivery_spec = None
    assert not request_still_applicable(request, projection, events)
    assert response_errors(response("needs_work"), projection, "product", events, snapshot_hash="tree-hash")


@pytest.mark.parametrize("status", ["cancelled", "timed_out", "superseded", "stopped"])
def test_closed_requests_reject_late_responses(status):
    projection = work()
    request, events = pending(projection, action="inspect")
    events.append(event(2, EventType.COLLABORATION_CLOSED, {"request_id": request.id, "status": status}))
    assert not request_still_applicable(request, projection, events)
    assert response_errors(response("needs_work"), projection, "engineering", events, snapshot_hash="tree-hash")


@pytest.mark.parametrize("phase", ["DONE", "FAILED", "PAUSED"])
def test_terminal_work_cannot_be_reawakened(phase):
    projection = work()
    request, events = pending(projection)
    projection.phase = phase
    assert resume_phase(request, projection, events, snapshot_hash="tree-hash") == (phase, False)
    assert not request_still_applicable(request, projection, events)
    assert allowed_proposal_kinds(projection, "engineering") == set()
