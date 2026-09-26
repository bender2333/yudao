import json
from dataclasses import replace

import pytest

from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn, pending_request_id, prompt_parts
from harness.models import EventType, json_dumps
from harness.proposals import (
    collaboration_request, collaboration_response, delivery_turn, plan_turn,
    product_decision, product_spec, response_turn, review, review_turn,
)
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.validation import evaluate_proposal


def _call(identity, name, **arguments):
    return {"id": identity, "call_id": identity, "type": "function_call", "name": name,
            "arguments": json_dumps(arguments)}


def _steps(system, run_id, count):
    for _ in range(count):
        current = system.activate_once(run_id)
    return current


def _events(system, run_id, event_type):
    return [event for event in system.store.list_events(run_id) if event.type == event_type]


@pytest.mark.parametrize("recipient", ["engineering", "quality"])
def test_product_can_consult_before_prd_without_granting_write_or_acceptance(tmp_path, recipient):
    def advise(request):
        assert request.department == recipient
        parts = prompt_parts(request)
        assert "current_contract" not in parts and "current_product_spec" not in parts
        names = {tool["name"] for tool in request.tools}
        assert "write_file" not in names and "submit_response" in names
        assert not {"submit_plan", "submit_delivery", "submit_review", "submit_spec"} & names
        return ModelResponse(output=[
            _call("unauthorized-write", "write_file", path="src/bypass.py", content="no"),
            _call("answer", "submit_response", request_id=pending_request_id(request), status="answered",
                  text="Keep the initial acceptance measurable.", result_event_ids=[]),
        ])

    system = LoopSystem.for_testing(tmp_path, FakeAdapter([collaboration_request(recipient), advise, product_spec()]))
    run_id = system.create_run("build echo")
    pending = system.activate_once(run_id)
    assert pending.phase == "PRODUCT_SPEC"
    basis = pending.pending_request.basis
    assert basis["effective_contract_hash"] is basis["engineering_plan_hash"] is None
    responded = system.activate_once(run_id)
    assert responded.phase == "PRODUCT_SPEC" and responded.pending_request is None
    assert responded.responses[-1].return_work_valid
    assert responded.product_spec is responded.effective_contract is None
    assert system.workspace(run_id).list_files() == []
    rejected = next(event for event in _events(system, run_id, EventType.TOOL_CALLED)
                    if event.payload.get("id") == "unauthorized-write")
    assert rejected.payload["ok"] is False
    assert system.activate_once(run_id).phase == "ENGINEERING"


def test_quality_clarification_preserves_contract_and_requires_a_new_independent_check(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        product_spec(), plan_turn(), delivery_turn(),
        FakeTurn(proposal=collaboration_request("product"), checks={"smoke": 0}),
        response_turn("answered", "Print the argument as defined in the current requirement."),
        review("release", "Reuse the earlier check"),
        review_turn("release", "Checked the current delivery again after the answer."),
    ]))
    run_id = system.create_run("build echo", max_cycles=12)
    old = _steps(system, run_id, 4)
    returned = system.activate_once(run_id)
    assert returned.phase == "QUALITY" and returned.responses[-1].return_work_valid
    assert returned.effective_contract == old.effective_contract
    assert returned.delivery_spec == old.delivery_spec
    assert not returned.product_decisions and not returned.reviews and not returned.lesson_candidates
    rejected = system.activate_once(run_id)
    assert rejected.phase == "QUALITY" and rejected.last_review is None
    assert any(error["field"] == "checks" for error in rejected.rejections[-1]["errors"])
    done = system.activate_once(run_id)
    assert done.phase == "DONE" and done.rework_count == 0
    assert done.last_review.checks[0]["activation_id"] != old.last_activations["quality"]


def test_revision_request_accepts_plan_delivery_then_response_without_changing_main_phase(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        product_spec(), plan_turn(), delivery_turn(),
        collaboration_request("engineering", "Correct the implementation.", request_type="action", action="revise_delivery"),
        plan_turn(reason="Correct the implementation requested by quality."),
        delivery_turn("Corrected echo", files={"src/echo.py": "import sys\nprint(str(sys.argv[1]))\n"}),
        response_turn("completed", "The corrected delivery is ready.", result_types=[EventType.DELIVERY_ACCEPTED]),
        review_turn("release", "Verified the corrected delivery independently."),
    ]))
    run_id = system.create_run("build echo", max_cycles=12)
    pending = _steps(system, run_id, 4)
    original_basis = dict(pending.pending_request.basis)
    original_delivery = pending.delivery_spec.content_hash
    planned = system.activate_once(run_id)
    assert planned.phase == "QUALITY" and planned.active_department == "engineering"
    assert planned.delivery_spec is None and planned.pending_request.basis == original_basis
    delivered = system.activate_once(run_id)
    assert delivered.phase == "QUALITY" and delivered.active_department == "engineering"
    assert delivered.delivery_spec.content_hash != original_delivery
    assert delivered.pending_request.basis == original_basis
    response = system.activate_once(run_id)
    assert response.phase == "QUALITY" and response.active_department == "quality"
    assert not response.responses[-1].return_work_valid
    assert response.responses[-1].result_event_ids == [delivered.delivery_spec.created_event_id]
    assert response.requests[-1].basis == original_basis
    assert system.activate_once(run_id).phase == "DONE"
    assert system.project(run_id).canonical_state() == system.replay(run_id).canonical_state()


@pytest.mark.parametrize("status", ["declined", "needs_work"])
@pytest.mark.parametrize("mutation", ["write_file", "delete_file", "move_file"])
def test_partial_mutation_and_response_in_one_activation_cannot_resume_old_quality(tmp_path, status, mutation):
    arguments = {
        "write_file": {"path": "src/echo.py", "content": "incomplete implementation"},
        "delete_file": {"path": "src/echo.py", "reason": "Remove incorrect implementation"},
        "move_file": {"source": "src/echo.py", "destination": "src/old.py", "reason": "Move incomplete code"},
    }[mutation]

    def partial(request):
        return ModelResponse(output=[
            _call("partial-change", mutation, **arguments),
            _call("partial-answer", "submit_response", request_id=pending_request_id(request), status=status,
                  text="Files changed, but the requested revision still needs engineering work.", result_event_ids=[]),
        ])

    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        product_spec(), plan_turn(), delivery_turn(),
        collaboration_request("engineering", request_type="action", action="revise_delivery"), partial,
    ]))
    run_id = system.create_run("build echo")
    pending = _steps(system, run_id, 4)
    current = system.activate_once(run_id)
    assert current.phase == "ENGINEERING", current.rejections
    assert current.pending_request is None and current.active_department == "engineering"
    assert current.delivery_spec is None and current.delivery_specs[-1].status == "superseded"
    assert current.responses[-1].status == status and not current.responses[-1].return_work_valid
    assert current.requests[-1].basis == pending.pending_request.basis
    assert not _events(system, run_id, EventType.COLLABORATION_CLOSED)
    assert current.canonical_state() == system.replay(run_id).canonical_state()


@pytest.mark.parametrize("disposition", ["retain", "integrate", "retire"])
def test_new_spec_explicitly_disposes_each_effective_decision_and_preserves_its_source(tmp_path, disposition):
    def revision(request):
        decisions = json.loads(prompt_parts(request)["current_product_decisions"])
        return product_spec(requirements=["print the argument and reject unknown flags"], change_record={
            "changed": ["Make unknown flag behavior explicit"], "retained": ["Echo valid input"],
            "retired": [], "rationale": "Clarify argument validation",
        }, decision_changes=[{
            "decision_hash": decisions[0]["content_hash"], "disposition": disposition,
            "rationale": "Make the handling of this earlier decision explicit.",
        }])

    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        product_spec(), collaboration_request("product", request_type="action", action="revise_requirements"),
        product_decision("Reject unknown flags.", "Invalid options require an explicit error."),
        response_turn("completed", result_types=[EventType.PRODUCT_DECISION_ACCEPTED]),
        collaboration_request("product", request_type="action", action="revise_requirements"),
        revision, response_turn("completed", result_types=[EventType.SPEC_ACCEPTED]),
    ]))
    run_id = system.create_run("build echo", max_cycles=12)
    before = _steps(system, run_id, 5)
    original_decision = before.product_decisions[0]
    original_spec = before.product_spec.content_hash
    facts = system.workspace(run_id).snapshot().facts
    for changes in ([], [{"decision_hash": "unknown", "disposition": "retain", "rationale": "Unknown"}],
                    [{"decision_hash": original_decision.content_hash, "disposition": "retain", "rationale": "Keep"}] * 2):
        decision = evaluate_proposal(phase=before.phase, department="product", projection=before,
                                     facts=facts, proposal=product_spec(decision_changes=changes, change_record={
                                         "changed": [], "retained": ["Echo behavior"], "retired": [], "rationale": "Review earlier decisions",
                                     }))
        assert not decision.accepted and decision.errors[0].field == "decision_changes"
    revised = system.activate_once(run_id)
    assert revised.product_spec.content_hash != original_spec
    assert revised.product_decisions[0] == original_decision
    assert original_decision.product_spec_hash == original_spec
    expected = [original_decision] if disposition == "retain" else []
    assert revised.effective_decisions == expected
    assert revised.effective_contract.decision_hashes == [item.content_hash for item in expected]
    prd = system.artifacts.get_for_run(run_id, revised.effective_contract.prd_ref).decode("utf-8")
    assert disposition in prd and original_decision.content_hash in prd
    complete = system.activate_once(run_id)
    assert complete.pending_request is None and complete.phase == "ENGINEERING"
    assert complete.canonical_state() == system.replay(run_id).canonical_state()


def test_consultation_cannot_submit_nested_request_or_formal_decision(tmp_path):
    decision = product_decision("Change the goal.", "Not authorized by a consultation.")
    decision.pop("kind")
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        product_spec(), collaboration_request("product"),
        ModelResponse(output=[_call("nested", "submit_request", recipient="engineering", request_type="consultation",
                                    question="Nested?", background="Need more help", expected_result="Advice", action=None)]),
        ModelResponse(output=[_call("formal", "submit_product_decision", **decision)]),
        response_turn("answered", "Advice only."),
    ]))
    run_id = system.create_run("build echo")
    before = _steps(system, run_id, 2)
    current = _steps(system, run_id, 3)
    assert current.pending_request is None and len(current.requests) == 1
    assert current.effective_contract == before.effective_contract and current.product_decisions == []
    for identity in ("nested", "formal"):
        event = next(event for event in _events(system, run_id, EventType.TOOL_CALLED) if event.payload.get("id") == identity)
        assert not event.payload["ok"]
        assert not any(event.payload.get("id") == identity for event in _events(system, run_id, EventType.TOOL_STARTED))


def test_completed_action_requires_an_accepted_result_not_model_claims(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        product_spec(), collaboration_request("product", request_type="action", action="revise_requirements"),
        response_turn("completed", "I changed the requirements.", result_event_ids=["model-call-id"]),
        response_turn("declined", "No product decision was actually accepted."),
    ]))
    run_id = system.create_run("build echo")
    _steps(system, run_id, 2)
    rejected = system.activate_once(run_id)
    assert rejected.pending_request is not None and not rejected.responses
    assert any(error["field"] == "result_event_ids" for error in rejected.rejections[-1]["errors"])
    assert not rejected.product_decisions
    assert system.activate_once(run_id).requests[-1].status == "declined"


def test_quality_recipient_cannot_release_while_answering_a_consultation(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        product_spec(), plan_turn(), collaboration_request("quality"),
        review_turn("release", "A consultation must not release the run."),
        response_turn("answered", "The engineering checks should cover normal and invalid input."),
    ]))
    run_id = system.create_run("build echo")
    _steps(system, run_id, 3)
    rejected = system.activate_once(run_id)
    assert rejected.phase == "ENGINEERING" and rejected.pending_request is not None
    assert not rejected.reviews and not _events(system, run_id, EventType.RUN_DONE)
    assert rejected.rejections[-1]["errors"][0]["field"] == "kind"
    assert system.activate_once(run_id).pending_request is None


def test_response_rejects_wrong_request_or_department_without_closing_current_request(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([collaboration_request("engineering")]))
    run_id = system.create_run("build echo")
    pending = system.activate_once(run_id)
    for department, request_id in (("quality", pending.pending_request.id), ("engineering", "another-request")):
        decision = evaluate_proposal(
            phase=pending.phase, department=department, projection=pending,
            facts=system.workspace(run_id).snapshot().facts, events=system.store.list_events(run_id),
            proposal=collaboration_response(request_id, "answered", "Wrong recipient or request."),
        )
        assert not decision.accepted
    assert system.project(run_id).pending_request.id == pending.pending_request.id


@pytest.mark.parametrize("action,recipient", [("inspect", "engineering"), ("check", "quality")])
def test_read_and_check_actions_use_real_host_results_even_when_check_finds_failure(tmp_path, action, recipient):
    tool_turn = (ModelResponse(output=[_call("inspect-files", "list_files")]) if action == "inspect"
                 else FakeTurn(checks={"smoke": 2}))
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        collaboration_request(recipient, request_type="action", action=action), tool_turn,
        response_turn("completed", "The requested inspection was performed.", result_types=[EventType.TOOL_CALLED]),
    ]))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    current = system.activate_once(run_id)
    assert current.phase == "PRODUCT_SPEC" and current.pending_request is None, current.rejections
    assert current.responses[-1].status == "completed"
    result = system.store.get_event(current.responses[-1].result_event_ids[0])
    assert result.type == EventType.TOOL_CALLED and result.payload["request_id"] == current.requests[-1].id
    assert result.role == recipient and result.payload["ok"]
    assert current.product_spec is None and not current.reviews


@pytest.mark.parametrize("reason,status,phase", [
    ("provider_timeout", "timed_out", "FAILED"),
    ("model_steps_exhausted", "stopped", "PAUSED"),
])
def test_pending_request_is_closed_before_provider_or_loop_stop(tmp_path, reason, status, phase):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        collaboration_request("quality"), ProviderError("The receiver stopped.", reason=reason),
    ]))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    current = system.activate_once(run_id)
    assert current.phase == phase and current.stop_reason == reason
    assert current.pending_request is None and current.requests[-1].status == status
    closure = _events(system, run_id, EventType.COLLABORATION_CLOSED)[0]
    terminal = _events(system, run_id, EventType.RUN_FAILED if phase == "FAILED" else EventType.RUN_PAUSED)[0]
    assert closure.seq < terminal.seq and terminal.role == "quality"
    assert current.canonical_state() == system.replay(run_id).canonical_state()


def test_pending_request_is_closed_when_activation_limit_is_reached(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([collaboration_request("engineering")]))
    run_id = system.create_run("build echo", max_cycles=1)
    system.activate_once(run_id)
    current = system.activate_once(run_id)
    assert current.phase == "PAUSED" and current.stop_reason == "max_cycles"
    assert current.pending_request is None and current.requests[-1].status == "stopped"
    assert len(system.test_adapter.invocations) == 1


def test_cancellation_during_recipient_model_call_cannot_accept_a_late_response(tmp_path):
    def cancel(request):
        system.cancel(request.run_id)
        return collaboration_response(pending_request_id(request), "answered", "Late answer")

    system = LoopSystem.for_testing(tmp_path, FakeAdapter([collaboration_request("quality"), cancel]))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    current = system.activate_once(run_id)
    assert current.phase == "FAILED" and current.stop_reason == "cancelled"
    assert current.pending_request is None and current.requests[-1].status == "cancelled"
    assert not current.responses
    assert len(_events(system, run_id, EventType.COLLABORATION_CLOSED)) == 1


def test_external_contract_change_closes_request_and_does_not_rebind_its_basis(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec(), collaboration_request("product"), plan_turn()]))
    run_id = system.create_run("build echo")
    before = _steps(system, run_id, 2)
    external = replace(before, phase="PRODUCT_SPEC", pending_request=None)
    snapshot = system.workspace(run_id).snapshot()
    decision = evaluate_proposal(phase=external.phase, department="product", projection=external,
                                 facts=snapshot.facts, proposal=product_spec(requirements=["print the input in uppercase"], change_record={
                                     "changed": ["Uppercase output"], "retained": ["Read one argument"],
                                     "retired": ["Original casing"], "rationale": "The current product goal changed",
                                 }))
    assert decision.accepted
    # 运行之外接纳新的产品规格（经提交的写入函数），协作请求的依据随之改变
    system.orchestrator.submissions.commit(
        projection=external, snapshot=snapshot, workspace_root=system.workspace(run_id).root,
        artifact=decision.artifact, department="product", parent_event_id=before.last_event_id,
        session_id=before.sessions["product"].session_id, provider="fake", model="fake-script",
    )
    current = system.activate_once(run_id)
    assert current.phase == "ENGINEERING" and current.pending_request is None
    assert current.requests[-1].status == "superseded" and current.requests[-1].basis == before.pending_request.basis
    assert not current.responses and current.engineering_plan is not None
    assert _events(system, run_id, EventType.COLLABORATION_CLOSED)[0].payload["return_work_valid"] is False


def test_private_receiver_history_is_not_injected_into_requester_context(tmp_path):
    marker = "RECEIVER_PRIVATE_ANALYSIS_735912"
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        collaboration_request("engineering"), FakeTurn(transcript=marker), response_turn("answered", "Use one clear output check."),
        product_spec(), plan_turn(),
    ]))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.activate_once(run_id)
    resumed_product = system.test_adapter.invocations[-1]
    assert resumed_product.department == "product"
    assert marker not in json_dumps(resumed_product.input_items)
    assert "Use one clear output check." in prompt_parts(resumed_product)["latest_response"]
    system.activate_once(run_id)
    resumed_engineering = system.test_adapter.invocations[-1]
    assert marker in json_dumps(resumed_engineering.input_items)
    assert all(set(item) == {"event_id", "type", "request_id", "role", "name", "ok", "content_hash"}
               for item in system.project(run_id).request_results)
