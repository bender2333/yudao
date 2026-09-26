from dataclasses import asdict, replace

import pytest

from harness.providers.call import ModelResponse
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.contracts import contract_payload, normalize_scope, path_in_scope, render_plan, render_prd
from harness.models import EventType, json_dumps
from harness.proposals import (collaboration_request, delivery, delivery_turn, engineering_plan, plan_turn,
                               product_decision, product_spec, response_turn, review_turn)
from harness.runtime import LoopSystem
from harness.validation import evaluate_proposal


def _call(identity, name, **arguments):
    return {"id": identity, "call_id": identity, "type": "function_call", "name": name,
            "arguments": json_dumps(arguments)}


def _accept_new_spec(system, run_id):
    projection = system.project(run_id)
    decision = evaluate_proposal(phase="PRODUCT_SPEC", department="product", projection=replace(projection, phase="PRODUCT_SPEC"),
                                 facts=system.workspace(run_id).snapshot().facts,
                                 proposal=product_spec(requirements=["print the argument in uppercase"], change_record={
                                     "changed": ["Print the argument in uppercase"], "retained": ["Keep a single argument CLI"],
                                     "retired": ["Preserve the original case"], "rationale": "The product now requires uppercase output",
                                 }))
    assert decision.accepted
    # 运行之外接纳新的产品规格（经提交的写入函数），有效合同随之改变
    system.orchestrator.submissions.commit(
        projection=projection, snapshot=system.workspace(run_id).snapshot(), workspace_root=system.workspace(run_id).root,
        artifact=decision.artifact, department="product", parent_event_id=projection.last_event_id,
        session_id=projection.sessions["product"].session_id, provider="fake", model="fake-script",
    )


def test_prd_and_plan_are_rebuildable_from_the_same_accepted_contract(tmp_path):
    adapter = FakeAdapter([
        product_spec(), collaboration_request(request_type="action", action="revise_requirements"),
        product_decision("Treat unknown flags as an error.", "Unknown flags must not silently change the command."),
        response_turn("completed", result_types=[EventType.PRODUCT_DECISION_ACCEPTED]),
        plan_turn(assumptions=[{"decision": "Use the standard argument parser", "basis": "Python standard library"}]),
        delivery_turn(), review_turn("release", "Verified the current requirements"),
    ])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    result = system.run_until_stop(run_id)
    assert result.phase == "DONE", result.error
    assert len(result.product_specs) == 1
    assert len(result.effective_contracts) == 2
    contract = result.effective_contract
    assert result.effective_contracts[0].content_hash != contract.content_hash
    assert contract.decision_hashes == [result.product_decisions[-1].content_hash]
    assert contract_payload(result)["content_hash"] == contract.content_hash
    expected_prd = render_prd(result, asdict(contract))
    assert system.artifacts.get_for_run(run_id, contract.prd_ref).decode("utf-8") == expected_prd
    assert (tmp_path / "materials" / run_id / "PRD.md").read_bytes() == expected_prd.encode("utf-8")
    for content in (result.effective_decisions[0].statement, result.effective_decisions[0].rationale):
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
        plan = engineering_plan()
        plan.pop("kind")
        return ModelResponse(output=[_call("unplanned", "write_file", path="unplanned.txt", content="no"),
                                     _call("plan", "submit_plan", **plan),
                                     _call("after-submit", "write_file", path="src/later.py", content="no")])

    def adjusted_plan(request):
        plan = engineering_plan(scope=["src/", "docs/"],
                                reason="Document the implemented command beside its code")
        plan.pop("kind")
        return ModelResponse(output=[_call("out-of-scope", "write_file", path="docs/guide.md", content="no"),
                                     _call("adjust", "submit_plan", **plan)])

    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec(), first_plan, adjusted_plan]))
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
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        product_spec(), plan_turn(),
        FakeTurn(proposal=collaboration_request(request_type="action", action="revise_requirements"),
                 writes={"src/echo.py": "print('echo')"}, checks={"smoke": 0}),
        product_decision("Use exit code 2 for unknown flags", "Keep invalid arguments distinguishable from normal output."),
        response_turn("completed", result_types=[EventType.PRODUCT_DECISION_ACCEPTED]),
        plan_turn(reason="Implement the newly accepted flag decision"),
    ]))
    run_id = system.create_run("echo")
    for _ in range(3):
        old = system.activate_once(run_id)
    receipt = system.workspace(run_id).snapshot().checks[-1]
    system.activate_once(run_id)
    new = system.activate_once(run_id)
    assert new.product_spec.content_hash == old.product_spec.content_hash
    assert new.effective_contract.content_hash != old.effective_contract.content_hash
    assert new.engineering_plan is None
    assert new.engineering_plans[-1].status == "superseded"
    new = system.activate_once(run_id)
    facts = system.workspace(run_id).snapshot().facts
    for replacement in (
        replace(receipt, activation_id=new.last_activations["engineering"], engineering_plan_hash=new.engineering_plan.content_hash),
        replace(receipt, activation_id=new.last_activations["engineering"], effective_contract_hash=new.effective_contract.content_hash),
    ):
        decision = evaluate_proposal(phase=new.phase, department="engineering", projection=new,
                                     facts=facts.model_copy(update={"checks": (replacement,)}), proposal=delivery())
        assert not decision.accepted
        assert any(error.field == "check_names" for error in decision.errors)


def test_plan_adjustment_requires_reason_and_current_contract(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec(), plan_turn()]))
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    current = system.activate_once(run_id)
    old_hash = engineering_plan()
    old_hash["effective_contract_hash"] = "sha256:old"
    for proposal, field in (
        (engineering_plan(), "reason"),
        (old_hash, "effective_contract_hash"),
        (engineering_plan(scope=["../materials/"], reason="Move files"), "scope"),
    ):
        decision = evaluate_proposal(phase=current.phase, department="engineering", projection=current,
                                     facts=system.workspace(run_id).snapshot().facts, proposal=proposal)
        assert not decision.accepted
        assert any(error.field == field for error in decision.errors)


def test_plan_without_model_hash_is_bound_to_current_contract_by_host(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec(), plan_turn()]))
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    result = system.activate_once(run_id)

    assert result.engineering_plan is not None
    assert result.engineering_plan.effective_contract_hash == result.effective_contract.content_hash
    assert all("effective_contract_hash" not in event.payload.get("raw_keys", [])
               for event in system.store.list_events(run_id)
               if event.type == EventType.PROPOSAL_SUBMITTED)


def test_contract_change_before_tool_start_skips_unstarted_calls(tmp_path):
    calls = [_call("first", "write_file", path="src/first.py", content="no"),
             _call("second", "write_file", path="src/second.py", content="no")]

    def change_during_request(_call):
        # 模型请求进行中合同改变：工具许可按新合同停止，两个写入都不开始
        _accept_new_spec(system, run_id)
        return ModelResponse(output=calls)

    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec(), plan_turn(), change_during_request]))
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    current = system.activate_once(run_id)
    assert current.engineering_plan is None
    assert system.workspace(run_id).list_files() == []
    events = system.store.list_events(run_id)
    skipped = [event.payload["id"] for event in events if event.type == EventType.TOOL_SKIPPED]
    assert skipped == ["first", "second"]


def test_prd_artifact_failure_does_not_accept_product_or_contract(tmp_path, monkeypatch):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec()]))
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


@pytest.mark.parametrize("path", ["../src/", "/src/", "C:/src/", "src/../other/", ".checks/", ".CHECKS/", "src:file", "src/ ", ".checks /", "src./", "NUL", "src/COM1.py"])
def test_plan_scope_rejects_paths_outside_public_workspace(path):
    with pytest.raises(ValueError):
        normalize_scope(path)


def test_scope_matches_files_and_directory_boundaries():
    assert normalize_scope(" src/") == " src/"
    assert path_in_scope(" src/main.py", [" src/"])
    assert path_in_scope("src/main.py", ["src/"])
    assert path_in_scope("src/main.py", ["src/main.py"])
    assert not path_in_scope("src-other/main.py", ["src/"])
    assert not path_in_scope("src/other.py", ["src/main.py"])
    assert not path_in_scope("../materials/run/PRD.md", ["."])
    assert not path_in_scope(".checks/receipts.jsonl", ["."])
    assert not path_in_scope(" src/main.py", ["src/"])
    assert not path_in_scope("src/main.py ", ["src/"])
