from harness.projection import project_events
from harness.tests.helpers import happy_script, run_scripted


def test_replay_matches_live_projection(data_dir):
    system, projection = run_scripted(data_dir, happy_script())
    replayed = system.replay(projection.run_id)
    assert replayed.canonical_state() == projection.canonical_state()
    events = system.store.list_events(projection.run_id)
    folded = project_events(events)
    assert folded.canonical_state() == projection.canonical_state()
    assert folded.product_spec.content_hash == projection.product_spec.content_hash
    assert folded.delivery_spec.code_tree_digest == projection.delivery_spec.code_tree_digest
    assert folded.last_review.verdict == "release"


def test_replay_survives_collaboration_and_rework(data_dir):
    from harness.proposals import collaboration_request, delivery_turn, plan_turn, product_spec, product_decision, response_turn, review_turn

    script = [
        product_spec(),
        collaboration_request(request_type="action", action="revise_requirements"),
        product_decision("Dash-prefixed input is ordinary text.", "The CLI echoes arbitrary input."),
        response_turn("completed", "Published the required flag behavior.", result_types=["product_decision_accepted"]),
        plan_turn(),
        delivery_turn(summary="v1"),
        review_turn(
            "rework_engineering",
            "need a fix",
            defects=[{"severity": "minor", "summary": "naming"}],
        ),
        plan_turn(reason="Address the quality naming defect"),
        delivery_turn(summary="v2", files={"src/echo.py": "print('v2')\n"}),
        review_turn("release", "ok"),
    ]
    system, projection = run_scripted(data_dir, script, max_cycles=16)
    replayed = system.replay(projection.run_id)
    assert replayed.canonical_state() == projection.canonical_state()
    assert replayed.request_count == 1
    assert replayed.rework_count == 1
    assert replayed.phase == "DONE"
    assert len(replayed.effective_decisions) == 1
    assert replayed.effective_decisions[0].statement == "Dash-prefixed input is ordinary text."
    assert replayed.effective_decisions[0].rationale == "The CLI echoes arbitrary input."
    assert replayed.effective_decisions[0].request_id == replayed.requests[0].id
    assert replayed.responses[0].result_event_ids == [replayed.effective_decisions[0].created_event_id]
    assert [item.status for item in replayed.delivery_specs] == ["superseded", "active"]
    assert replayed.delivery_specs[0].invalidation_reason == "qa_rework_engineering"
    assert replayed.delivery_spec.summary == "v2"
