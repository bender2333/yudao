import pytest

from harness.adapters.fake import FakeAdapter
from harness.proposals import collaboration_request, delivery_turn, plan_turn, product_decision, product_spec, response_turn, review_turn
from harness.runtime import LoopSystem
from harness.tests.test_web import get_json, running_server
from harness.views import run_payload


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
    system = LoopSystem(tmp_path, FakeAdapter([
        *prefix, collaboration_request(recipient, "Clarify the current work.", expected_result="Provide an explanation."),
        response_turn("answered", "The current work can continue without changing requirements or files."), *suffix,
    ]))
    run_id = system.create_run("build echo", max_cycles=16)
    for _ in range(len(prefix) + 1):
        system.activate_once(run_id)
    with running_server(system) as (_server, host, port):
        pending = get_json(host, port, f"/api/runs/{run_id}")
    assert pending["board"]["phase"] == phase
    assert pending["board"]["active_department"] == recipient
    assert pending["board"]["pending_request"]["requester"] == requester
    assert pending["timeline"]["pending_request"]["recipient"] == recipient
    assert pending["timeline"]["pending_request"]["return_phase"] == phase
    if requester == "product":
        assert pending["timeline"]["current_product_spec"] is None
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
    system = LoopSystem(tmp_path, FakeAdapter([collaboration_request("quality", "Review the initial acceptance approach.")]))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    system.cancel(run_id)
    with running_server(system) as (_server, host, port):
        payload = get_json(host, port, f"/api/runs/{run_id}")
        assert payload["board"]["pending_request"] is None
        timeline = payload["timeline"]
        assert len(timeline["requests"]) == len(timeline["request_closures"]) == 1
        closure = timeline["request_closures"][0]
        assert closure["request_id"] == timeline["requests"][0]["id"]
        assert closure["reason"]
        assert timeline["responses"] == []
        detail = get_json(host, port, f"/api/runs/{run_id}/events/{closure['created_event_id']}")
        assert detail["type"] == "collaboration_closed"


def test_views_keep_product_decision_and_response_as_separate_accepted_events(tmp_path):
    system = LoopSystem(tmp_path, FakeAdapter([
        product_spec(),
        collaboration_request("product", "Define handling of dash-prefixed input.",
                              request_type="action", action="revise_requirements"),
        product_decision("Dash-prefixed input must be printed as ordinary text.", "This CLI echoes its first argument."),
        response_turn("completed", "The requirement has been published.", result_types=["product_decision_accepted"]),
        plan_turn(), delivery_turn(), review_turn("release", "Independent quality checks passed."),
    ]))
    run_id = system.create_run("build echo", max_cycles=16)
    assert system.run_until_stop(run_id).phase == "DONE"
    timeline = run_payload(system.store, run_id)["timeline"]
    assert len(timeline["product_decisions"]) == len(timeline["responses"]) == 1
    decision, response = timeline["product_decisions"][0], timeline["responses"][0]
    assert decision["created_event_id"] != response["created_event_id"]
    assert response["result_event_ids"] == [decision["created_event_id"]]
    assert decision["request_id"] == response["request_id"] == timeline["requests"][0]["id"]
    assert timeline["effective_decisions"][0]["statement"] == decision["statement"]
    assert len(timeline["effective_contracts"]) == 2
