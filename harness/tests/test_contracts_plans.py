from dataclasses import asdict, replace

import pytest

import harness.orchestrator as orchestration
from harness.adapters.base import ModelResponse
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.contracts import contract_payload, normalize_scope, path_in_scope, render_plan, render_prd
from harness.models import EventType, json_dumps
from harness.proposals import ask_request, delivery, delivery_turn, engineering_plan, plan_turn, product_spec, reaction, review_turn
from harness.runtime import LoopSystem
from harness.validation import evaluate_proposal


def _call(identity, name, **arguments):
    return {"id": identity, "call_id": identity, "type": "function_call", "name": name,
            "arguments": json_dumps(arguments)}


def _accept_new_spec(system, run_id):
    projection = system.project(run_id)
    decision = evaluate_proposal(phase="PRODUCT_SPEC", department="product", projection=projection,
                                 snapshot=system.workspace(run_id).snapshot(),
                                 proposal=product_spec(requirements=["print the argument in uppercase"]))
    assert decision.accepted
    system.orchestrator._commit_accepted(
        run_id, department="product", projection=projection, artifact=decision.artifact,
        transitions=[], extra=decision.extra, parent_event_id=projection.last_event_id,
        session_id=projection.sessions["product"].session_id, provider="fake", model="fake-script",
    )


def test_prd_and_plan_are_rebuildable_from_the_same_accepted_contract(tmp_path):
    adapter = FakeAdapter([
        product_spec(), ask_request(), reaction("accept", "Treat unknown flags as an error."),
        plan_turn(assumptions=[{"decision": "Use the standard argument parser", "basis": "Python standard library"}]),
        delivery_turn(), review_turn("release", "Verified the current requirements"),
    ])
    system = LoopSystem(tmp_path, adapter)
    run_id = system.create_run("echo")
    result = system.run_until_stop(run_id)
    assert result.phase == "DONE", result.error
    assert len(result.product_specs) == 1
    assert len(result.effective_contracts) == 2
    contract = result.effective_contract
    assert result.effective_contracts[0].content_hash != contract.content_hash
    assert contract.decision_hashes == [result.last_reaction.content_hash]
    assert contract_payload(result)["content_hash"] == contract.content_hash
    expected_prd = render_prd(result, asdict(contract))
    assert system.artifacts.get_for_run(run_id, contract.prd_ref).decode("utf-8") == expected_prd
    assert (tmp_path / "materials" / run_id / "PRD.md").read_bytes() == expected_prd.encode("utf-8")
    for content in (result.effective_decisions[0].recommendation, result.effective_decisions[0].rationale):
        assert content in expected_prd
    plan = result.engineering_plan
    expected_plan = render_plan(asdict(plan))
    assert system.artifacts.get_for_run(run_id, plan.plan_ref).decode("utf-8") == expected_plan
    assert (tmp_path / "materials" / run_id / "PLAN.md").read_bytes() == expected_plan.encode("utf-8")
    assert "PRD.md" not in system.workspace(run_id).list_files()
    assert "PLAN.md" not in system.workspace(run_id).list_files()
    assert result.delivery_spec.effective_contract_hash == result.last_review.effective_contract_hash == contract.content_hash
    assert result.delivery_spec.engineering_plan_hash == result.last_review.engineering_plan_hash == plan.content_hash
    events = system.store.list_events(run_id)
    accepted = next(event.seq for event in events if event.type == EventType.PLAN_ACCEPTED)
    assert all(event.seq > accepted for event in events if event.type == EventType.TOOL_STARTED and event.payload["name"] == "write_file")
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_unplanned_and_out_of_scope_writes_have_repairable_tool_results(tmp_path):
    def first_plan(request):
        plan = engineering_plan(request.effective_contract_hash)
        plan.pop("kind")
        return ModelResponse(output=[_call("unplanned", "write_file", path="unplanned.txt", content="no"),
                                     _call("plan", "submit_plan", **plan),
                                     _call("after-submit", "write_file", path="src/later.py", content="no")])

    def adjusted_plan(request):
        plan = engineering_plan(request.effective_contract_hash, scope=["src/", "docs/"],
                                reason="Document the implemented command beside its code")
        plan.pop("kind")
        return ModelResponse(output=[_call("out-of-scope", "write_file", path="docs/guide.md", content="no"),
                                     _call("adjust", "submit_plan", **plan)])

    system = LoopSystem(tmp_path, FakeAdapter([product_spec(), first_plan, adjusted_plan]))
    run_id = system.create_run("echo")
    for _ in range(3):
        result = system.activate_once(run_id)
    assert result.phase == "ENGINEERING"
    assert system.workspace(run_id).list_files() == []
    assert len(result.engineering_plans) == 2
    assert result.engineering_plans[0].status == "superseded"
    events = system.store.list_events(run_id)
    for identity, text in (("unplanned", "before writing"), ("out-of-scope", "outside")):
        call = next(event for event in events if event.type == EventType.TOOL_CALLED and event.payload.get("id") == identity)
        assert not call.payload["ok"]
        assert text in call.payload["error"]
        assert not any(event.type == EventType.TOOL_STARTED and event.payload["id"] == identity for event in events)
    assert any(event.type == EventType.TOOL_SKIPPED and event.payload["id"] == "after-submit" for event in events)


def test_supplementary_decision_invalidates_plan_and_old_receipts_without_new_spec(tmp_path):
    system = LoopSystem(tmp_path, FakeAdapter([
        product_spec(), plan_turn(),
        FakeTurn(proposal=ask_request(), writes={"src/echo.py": "print('echo')"}, checks={"smoke": 0}),
        reaction("accept", "Use exit code 2 for unknown flags"), plan_turn(reason="Implement the newly accepted flag decision"),
    ]))
    run_id = system.create_run("echo")
    for _ in range(3):
        old = system.activate_once(run_id)
    receipt = system.workspace(run_id).snapshot().checks[-1]
    new = system.activate_once(run_id)
    assert new.product_spec.content_hash == old.product_spec.content_hash
    assert new.effective_contract.content_hash != old.effective_contract.content_hash
    assert new.engineering_plan is None
    assert new.engineering_plans[-1].status == "superseded"
    new = system.activate_once(run_id)
    snapshot = system.workspace(run_id).snapshot()
    for replacement in (
        replace(receipt, activation_id=new.last_activations["engineering"], engineering_plan_hash=new.engineering_plan.content_hash),
        replace(receipt, activation_id=new.last_activations["engineering"], effective_contract_hash=new.effective_contract.content_hash),
    ):
        decision = evaluate_proposal(phase=new.phase, department="engineering", projection=new,
                                     snapshot=replace(snapshot, checks=(replacement,)), proposal=delivery())
        assert not decision.accepted
        assert any(error.field == "check_names" for error in decision.errors)


def test_plan_adjustment_requires_reason_and_current_contract(tmp_path):
    system = LoopSystem(tmp_path, FakeAdapter([product_spec(), plan_turn()]))
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    current = system.activate_once(run_id)
    for proposal, field in (
        (engineering_plan(current.effective_contract.content_hash), "reason"),
        (engineering_plan("sha256:old", reason="Change requirements"), "effective_contract_hash"),
        (engineering_plan(current.effective_contract.content_hash, scope=["../materials/"], reason="Move files"), "scope"),
    ):
        decision = evaluate_proposal(phase=current.phase, department="engineering", projection=current,
                                     snapshot=system.workspace(run_id).snapshot(), proposal=proposal)
        assert not decision.accepted
        assert any(error.field == field for error in decision.errors)


def test_contract_change_during_proposal_validation_never_rebinds_old_delivery(tmp_path, monkeypatch):
    system = LoopSystem(tmp_path, FakeAdapter([product_spec(), plan_turn(), delivery_turn()]))
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    original = system.activate_once(run_id)
    evaluate = orchestration.evaluate_proposal

    def change_after_evaluation(**arguments):
        decision = evaluate(**arguments)
        assert decision.accepted
        _accept_new_spec(system, run_id)
        return decision

    monkeypatch.setattr(orchestration, "evaluate_proposal", change_after_evaluation)
    current = system.activate_once(run_id)
    assert current.effective_contract.content_hash != original.effective_contract.content_hash
    assert current.delivery_spec is None
    assert current.rejections[-1]["errors"][0]["field"] == "execution_basis"
    receipt = system.workspace(run_id).snapshot().checks[-1]
    assert receipt.effective_contract_hash == original.effective_contract.content_hash
    assert not any(event.type == EventType.DELIVERY_ACCEPTED for event in system.store.list_events(run_id))


def test_contract_change_before_tool_start_skips_unstarted_calls(tmp_path, monkeypatch):
    calls = [_call("first", "write_file", path="src/first.py", content="no"),
             _call("second", "write_file", path="src/second.py", content="no")]
    system = LoopSystem(tmp_path, FakeAdapter([product_spec(), plan_turn(), ModelResponse(output=calls)]))
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    begin = system.orchestrator._begin_tool

    def change_before_start(activation, call):
        _accept_new_spec(system, run_id)
        return begin(activation, call)

    monkeypatch.setattr(system.orchestrator, "_begin_tool", change_before_start)
    current = system.activate_once(run_id)
    assert current.engineering_plan is None
    assert system.workspace(run_id).list_files() == []
    events = system.store.list_events(run_id)
    skipped = [event.payload["id"] for event in events if event.type == EventType.TOOL_SKIPPED]
    assert skipped == ["first", "second"]


def test_prd_artifact_failure_does_not_accept_product_or_contract(tmp_path, monkeypatch):
    system = LoopSystem(tmp_path, FakeAdapter([product_spec()]))
    run_id = system.create_run("echo")
    put = system.artifacts.put

    def fail_prd(run, kind, *args, **kwargs):
        if kind == "prd":
            raise OSError("cannot persist PRD")
        return put(run, kind, *args, **kwargs)

    monkeypatch.setattr(system.artifacts, "put", fail_prd)
    result = system.activate_once(run_id)
    assert result.phase == "FAILED"
    assert result.stop_reason == "host_commit_error"
    assert "cannot persist PRD" in result.error
    assert result.human_action
    events = system.store.list_events(run_id)
    assert not any(event.type in {EventType.SPEC_ACCEPTED, EventType.CONTRACT_ACCEPTED} for event in events)
    assert result.canonical_state() == system.replay(run_id).canonical_state()


@pytest.mark.parametrize("path", ["../src/", "/src/", "C:/src/", "src/../other/", ".checks/", ".CHECKS/", "src:file", " src/", "src/ ", ".checks /", "src./", "NUL", "src/COM1.py"])
def test_plan_scope_rejects_paths_outside_public_workspace(path):
    with pytest.raises(ValueError):
        normalize_scope(path)


def test_scope_matches_files_and_directory_boundaries():
    assert path_in_scope("src/main.py", ["src/"])
    assert path_in_scope("src/main.py", ["src/main.py"])
    assert not path_in_scope("src-other/main.py", ["src/"])
    assert not path_in_scope("src/other.py", ["src/main.py"])
    assert not path_in_scope("../materials/run/PRD.md", ["."])
    assert not path_in_scope(".checks/receipts.jsonl", ["."])
    assert not path_in_scope(" src/main.py", ["src/"])
    assert not path_in_scope("src/main.py ", ["src/"])
