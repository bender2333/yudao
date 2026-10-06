import pytest

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.app.project_queries import ProjectFlow
from harness.proposals import collaboration_request, delivery_turn, plan_turn, product_decision, product_spec, response_turn, review_turn
from harness.runtime import LoopSystem

def _application(system: LoopSystem) -> Application:
    return Application(system)

@pytest.mark.parametrize("requester,recipient", [
    ("product", "engineering"), ("product", "quality"),
    ("engineering", "product"), ("engineering", "quality"),
    ("quality", "product"), ("quality", "engineering"),
])
def test_every_consultation_direction_is_visible_and_returns_to_original_work(tmp_path, requester, recipient):
    product = [product_spec()]
    engineering = [plan_turn(), delivery_turn()]
    quality = [review_turn("release", "Independent quality checks passed.")]
    prefix = [] if requester == "product" else product if requester == "engineering" else product + engineering
    suffix = product + engineering + quality if requester == "product" else engineering + quality if requester == "engineering" else quality
    phase = {"product": "PRODUCT_SPEC", "engineering": "ENGINEERING", "quality": "QUALITY"}[requester]
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        *prefix, collaboration_request(recipient, "Clarify the current work.", expected_result="Provide an explanation."),
        response_turn("answered", "The current work can continue without changing requirements or files."), *suffix,
    ]))
    project_id = system.projects.register("咨询可见性", "把文本按行处理清楚")
    work_item_id, run_id = system.projects.start_work_item(project_id, "build echo")
    for _ in range(len(prefix) + 1):
        system.activate_once(run_id)
    # 咨询记录在流转查询里可见：发起方向、等待状态与问题
    flow = _application(system).query("project.flow", ProjectFlow(project_id=project_id, work_item=work_item_id))
    consultation = next(record for record in flow.data.records if record.kind == "咨询")
    assert consultation.direction_from == requester
    assert consultation.direction_to == recipient
    assert consultation.status == "等待回答"
    assert consultation.content == "Clarify the current work."
    pending = system.project(run_id)
    assert pending.phase == phase
    assert pending.active_department == recipient
    assert pending.pending_request.requester == requester
    responded = system.activate_once(run_id)
    assert responded.phase == phase
    assert responded.active_department == requester
    assert responded.pending_request is None
    assert responded.responses[-1].return_work_valid is True
    assert responded.reviews == []
    assert responded.lesson_candidates == []
    final = system.run_until_stop(run_id)
    assert final.phase == "DONE"
    assert final.rework_count == 0
    assert final.product_spec.revision == 1
    assert final.effective_decisions == []
    assert final.canonical_state() == system.replay(run_id).canonical_state()

def test_cancelled_request_is_visible_with_its_closure_reason_and_event(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([collaboration_request("quality", "Review the initial acceptance approach.")]))
    project_id = system.projects.register("取消咨询", "把文本按行处理清楚")
    work_item_id, run_id = system.projects.start_work_item(project_id, "build echo")
    system.activate_once(run_id)
    system.cancel(run_id)
    flow = _application(system).query("project.flow", ProjectFlow(project_id=project_id, work_item=work_item_id))
    consultations = [record for record in flow.data.records if record.kind == "咨询"]
    assert len(consultations) == 1
    closure = consultations[0]
    assert closure.status == "已取消"
    assert closure.content
    assert system.project(run_id).pending_request is None

def test_projection_keeps_product_decision_and_response_as_separate_accepted_events(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        product_spec(),
        collaboration_request("product", "Define handling of dash-prefixed input.",
                              request_type="action", action="revise_requirements"),
        product_decision("Dash-prefixed input must be printed as ordinary text.", "This CLI echoes its first argument."),
        response_turn("completed", "The requirement has been published.", result_types=["product_decision_accepted"]),
        plan_turn(), delivery_turn(), review_turn("release", "Independent quality checks passed."),
    ]))
    run_id = system.create_run("build echo", max_cycles=16)
    assert system.run_until_stop(run_id).phase == "DONE"
    projection = system.project(run_id)
    assert len(projection.product_decisions) == len(projection.responses) == 1
    decision, response = projection.product_decisions[0], projection.responses[0]
    assert decision.created_event_id != response.created_event_id
    assert response.result_event_ids == [decision.created_event_id]
    assert decision.request_id == response.request_id == projection.requests[0].id
    assert projection.effective_decisions[0].statement == decision.statement
    assert len(projection.effective_contracts) == 2
