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


def test_replay_survives_ask_and_rework(data_dir):
    from harness.proposals import ask_request, delivery_turn, product_spec, reaction, review_turn

    script = [
        product_spec(),
        ask_request(),
        reaction("accept", "go ahead"),
        delivery_turn(summary="v1"),
        review_turn(
            "rework_engineering",
            "need a fix",
            defects=[{"severity": "minor", "summary": "naming"}],
        ),
        delivery_turn(summary="v2", files={"src/echo.py": "print('v2')\n"}),
        review_turn("release", "ok"),
    ]
    system, projection = run_scripted(data_dir, script)
    replayed = system.replay(projection.run_id)
    assert replayed.canonical_state() == projection.canonical_state()
    assert replayed.ask_count == 1
    assert replayed.rework_count == 1
    assert replayed.phase == "DONE"
    assert len(replayed.effective_decisions) == 1
    assert replayed.effective_decisions[0].decision == "accept"
    assert replayed.effective_decisions[0].rationale == "go ahead"
    assert replayed.effective_decisions[0].background == "The current spec does not mention flags."
    assert replayed.effective_decisions[0].impact == "Error handling changes the public contract."
    assert [item.status for item in replayed.delivery_specs] == ["superseded", "active"]
    assert replayed.delivery_specs[0].invalidation_reason == "qa_rework_engineering"
    assert replayed.delivery_spec.summary == "v2"
