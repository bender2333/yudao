# 有效合同与交付的模块层结论：补充决定改变有效合同、无计划写入不受拒、
# 合同改变时未开始的工具调用被跳过、PRD 工件失败不接纳产品与合同。
# 这些结论都由单次激活（activate_once）得出，不需要跑完整三部门循环，登记为模块层。

import json
from dataclasses import replace

import pytest

from harness.adapters.fake import FakeAdapter, FakeTurn, prompt_parts
from harness.event_store import run_stream
from harness.models import EventType
from harness.proposals import (ask_turn, delivery, delivery_turn,
                               product_decision, product_spec, review_turn)
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.tests.helpers import guidance_reply
from harness.validation import evaluate_proposal

def _accept_new_spec(system, run_id):
    projection = system.project(run_id)
    decision = evaluate_proposal(phase="PRODUCT_SPEC", department="product", projection=replace(projection, phase="PRODUCT_SPEC"),
                                 facts=system.workspace(run_id).snapshot().facts,
                                 proposal=product_spec(requirements=["print the argument in uppercase"], change_record={
                                     "changed": ["Print the argument in uppercase"], "retained": ["Keep a single argument CLI"],
                                     "retired": ["Preserve the original case"], "rationale": "The product now requires uppercase output",
                                 }))
    assert decision.accepted
    # 运行之外接纳新的产品规格（经写入口的事务），有效合同随之改变
    system.writes.transact(run_stream(run_id), lambda transaction: system.orchestrator.submissions.prepare(
        transaction, projection=projection, snapshot=system.workspace(run_id).snapshot(),
        environment=system.environment(run_id), artifact=decision.artifact, department="product",
        parent_event_id=projection.last_event_id, session_id=projection.sessions["product"].session_id,
        provider="fake", model="fake-script",
    ).append(transaction))

def test_writes_without_a_plan_are_allowed(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        product_spec(),
        delivery_turn(files={"src/direct.py": "yes\n"}),
    ]))
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    result = system.activate_once(run_id)
    assert result.phase == "QUALITY", result.error
    assert result.delivery_spec is not None
    assert system.workspace(run_id).list_files() == ["src/direct.py"]
    events = system.store.list_events(run_id)
    call = next(event for event in events if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "write_file")
    assert call.payload["ok"]
    assert any(event.type == EventType.TOOL_STARTED and event.payload["name"] == "write_file" for event in events)
    assert any(event.type == EventType.DELIVERY_ACCEPTED for event in events)

def test_supplementary_decision_changes_contract_without_new_spec(tmp_path):
    # 产品的工作由用户的指导触发（工单 #555）：补充决定改变合同，产品要求本身不变
    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        "product": [
            product_spec(),
            product_decision("Use exit code 2 for unknown flags", "Keep invalid arguments distinguishable from normal output."),
            guidance_reply("已给出产品决定。"),
        ],
        "engineering": [delivery_turn(files={"src/echo.py": "print('echo')"}, checks={"smoke": 0})],
        "quality": [
            review_turn("rework_engineering", "the delivery misses an acceptance criterion",
                        defects=[{"severity": "major", "summary": "flags clarification"}]),
        ],
    }))
    run_id = system.create_run("echo")
    old = system.activate_once(run_id)
    assert old.effective_contract.revision == 1
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.add_guidance(run_id, "product", "请补充产品决定。")
    new = system.activate_once(run_id)
    assert new.product_spec.content_hash == old.product_spec.content_hash
    assert new.effective_contract.revision == 2
    assert new.effective_contract.content_hash != old.effective_contract.content_hash
    # 旧合同下的检查回执属于早先激活：新激活直接交付因缺少本次激活的回执被拒绝
    facts = system.workspace(run_id).snapshot().facts
    decision = evaluate_proposal(phase=new.phase, department="engineering", projection=new,
                                 facts=facts, proposal=delivery(check_names=["smoke"]))
    assert not decision.accepted
    assert any(error.field == "check_names" for error in decision.errors)


@pytest.mark.parametrize("disposition", ["retain", "integrate", "retire"])
def test_new_spec_explicitly_disposes_each_effective_decision_and_preserves_its_source(tmp_path, disposition):
    def branch_answer(call):
        parts = prompt_parts(call)
        decisions = json.loads(parts["current_product_decisions"])
        spec = json.loads(parts["current_product_spec"])
        call_id = "ans-1"
        return ModelResponse(output=[{
            "id": call_id,
            "call_id": call_id,
            "type": "function_call",
            "name": "answer",
            "arguments": json.dumps({
                "answer": "Revised spec disposes decision.",
                "goal": "build an echo CLI",
                "requirements": ["print the argument and reject unknown flags"],
                "acceptance_criteria": ["running the program with a word prints that word"],
                "change_record": {
                    "changed": ["Make unknown flag behavior explicit"],
                    "retained": ["Echo valid input"],
                    "retired": [],
                    "rationale": "Clarify argument validation",
                },
                "decision_changes": [{
                    "decision_hash": decisions[0]["content_hash"],
                    "disposition": disposition,
                    "rationale": "Make the handling of this earlier decision explicit.",
                }],
                "basis_product_spec_hash": spec["content_hash"],
            }),
        }])

    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        "product": [
            product_spec(),
            product_decision("Reject unknown flags.", "Invalid options require an explicit error."),
            guidance_reply("已给出产品决定。"),
        ],
        "engineering": [
            delivery_turn(),
            ask_turn(recipient="product", question="Please revise spec to handle flags."),
            delivery_turn(),
        ],
        "product:ask": [
            branch_answer,
        ],
        "quality": [
            review_turn("rework_engineering", "the delivery misses an acceptance criterion",
                        defects=[{"severity": "major", "summary": "flags clarification"}]),
        ],
    }))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)  # product spec -> ENGINEERING
    system.activate_once(run_id)  # engineering delivery -> QUALITY
    system.activate_once(run_id)  # quality records a defect -> ENGINEERING
    system.add_guidance(run_id, "product", "请补充产品决定。")
    dec = system.activate_once(run_id)  # product decision -> ENGINEERING
    assert len(dec.product_decisions) == 1
    original_decision = dec.product_decisions[0]
    original_spec = dec.product_spec.content_hash
    system.activate_once(run_id)  # product replies to the guidance

    facts = system.workspace(run_id).snapshot().facts
    for changes in ([], [{"decision_hash": "unknown", "disposition": "retain", "rationale": "Unknown"}],
                    [{"decision_hash": original_decision.content_hash, "disposition": "retain", "rationale": "Keep"}] * 2):
        decision = evaluate_proposal(phase="PRODUCT_SPEC", department="product", projection=replace(dec, phase="PRODUCT_SPEC"),
                                     facts=facts, proposal=product_spec(decision_changes=changes, change_record={
                                         "changed": [], "retained": ["Echo behavior"], "retired": [],
                                         "rationale": "Review earlier decisions",
                                     }, basis_product_spec_hash=dec.product_spec.content_hash))
        assert not decision.accepted and decision.errors[0].field == "decision_changes"

    revised = system.activate_once(run_id)  # engineering runs, asks product, product answers in branch
    assert revised.product_spec.content_hash != original_spec
    assert revised.product_decisions[0] == original_decision
    assert original_decision.product_spec_hash == original_spec
    expected = [original_decision] if disposition == "retain" else []
    assert revised.effective_decisions == expected
    assert revised.effective_contract.decision_hashes == [item.content_hash for item in expected]
    prd = system.artifacts.get_for_run(run_id, revised.effective_contract.prd_ref).decode("utf-8")
    assert disposition in prd and original_decision.content_hash in prd
    assert revised.canonical_state() == system.replay(run_id).canonical_state()

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
