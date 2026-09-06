from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.proposals import ask_request, delivery_turn, product_spec, reaction, review, review_turn
from harness.runtime import LoopSystem
from harness.tests.helpers import happy_script, run_scripted


def test_happy_path_requires_quality_release(data_dir):
    system, projection = run_scripted(data_dir, happy_script())
    snapshot = system.workspace(projection.run_id).snapshot()
    engineering_check = snapshot.latest_check("engineering", "smoke")
    quality_check = snapshot.latest_check("quality", "smoke")
    assert engineering_check is not None and engineering_check.exit_code == 0
    assert quality_check is not None and quality_check.exit_code == 0
    assert "host-executed" in engineering_check.summary
    assert "host-executed" in quality_check.summary

    assert projection.phase == "DONE"
    assert projection.outcome == "done"
    assert projection.stop_reason == "released"
    assert projection.transitions == [
        "CREATED->PRODUCT_SPEC",
        "PRODUCT_SPEC->ENGINEERING",
        "ENGINEERING->DELIVERY",
        "DELIVERY->QUALITY",
        "QUALITY->DONE",
    ]
    assert projection.product_spec is not None
    assert projection.delivery_spec is not None
    assert projection.last_review is not None
    assert projection.last_review.verdict == "release"
    assert projection.last_review.product_spec_hash == projection.product_spec.content_hash
    assert projection.last_review.code_snapshot_hash == projection.delivery_spec.code_tree_digest


def test_ask_accept_returns_to_engineering(data_dir):
    script = [
        product_spec(),
        ask_request(),
        reaction("accept", "Use option A as specified."),
        delivery_turn(),
        review_turn("release", "accepted path is implemented"),
    ]
    _, projection = run_scripted(data_dir, script)
    assert projection.phase == "DONE"
    assert "ENGINEERING->ASK_PRODUCT" in projection.transitions
    assert "ASK_PRODUCT->PRODUCT_REACT" in projection.transitions
    assert "PRODUCT_REACT->ENGINEERING" in projection.transitions
    assert projection.last_reaction.decision == "accept"
    assert projection.last_reaction.produces_new_spec is False
    assert projection.product_spec.revision == 1


def test_ask_reply_can_create_new_spec(data_dir):
    updated = product_spec(goal="Build echo with strict flags", acceptance=["unknown flags exit 2"])
    script = [
        product_spec(),
        ask_request(),
        reaction("reply", "Unknown flags must fail.", spec_update=updated),
        delivery_turn(),
        review_turn("release", "reply applied"),
    ]
    _, projection = run_scripted(data_dir, script)
    assert projection.phase == "DONE"
    assert projection.last_reaction.decision == "reply"
    assert projection.last_reaction.produces_new_spec is True
    assert projection.product_spec.revision == 2
    assert projection.product_spec.goal == "Build echo with strict flags"
    assert projection.product_specs[0].status == "superseded"
    assert projection.delivery_spec.product_spec_hash == projection.product_spec.content_hash


def test_empty_spec_update_is_not_a_new_contract(data_dir):
    script = [
        product_spec(),
        ask_request(),
        reaction("accept", "keep the current spec", spec_update={}),
        delivery_turn(),
        review_turn("release", "ok"),
    ]
    _, projection = run_scripted(data_dir, script)
    assert projection.phase == "DONE"
    assert projection.last_reaction.decision == "accept"
    assert projection.last_reaction.produces_new_spec is False
    assert projection.product_spec.revision == 1


def test_ask_reject_keeps_engineering_on_current_spec(data_dir):
    script = [
        product_spec(),
        ask_request(),
        reaction("reject", "Do not ignore flags; keep the current contract."),
        delivery_turn(),
        review_turn("release", "rejected alternative"),
    ]
    _, projection = run_scripted(data_dir, script)
    assert projection.phase == "DONE"
    assert projection.last_reaction.decision == "reject"
    assert projection.product_spec.revision == 1
    assert "PRODUCT_REACT->ENGINEERING" in projection.transitions


def test_quality_rework_routes_to_engineering(data_dir):
    script = [
        product_spec(),
        delivery_turn(summary="first delivery"),
        review_turn(
            "rework_engineering",
            "edge case fails",
            defects=[{"severity": "major", "summary": "empty input is unhandled"}],
        ),
        delivery_turn(summary="fixed edge case", files={"src/echo.py": "print('ok')\n"}),
        review_turn("release", "fixed"),
    ]
    _, projection = run_scripted(data_dir, script)
    assert projection.phase == "DONE"
    assert "QUALITY->REWORK_ENGINEERING" in projection.transitions
    assert "REWORK_ENGINEERING->ENGINEERING" in projection.transitions
    assert projection.rework_count == 1


def test_quality_rework_routes_to_product(data_dir):
    script = [
        product_spec(),
        delivery_turn(),
        review_turn(
            "rework_product",
            "acceptance misses empty input",
            defects=[{"severity": "blocker", "summary": "empty input not in spec"}],
        ),
        product_spec(goal="Build echo including empty input", acceptance=["empty input prints a blank line"]),
        delivery_turn(summary="updated implementation", files={"src/echo.py": "print('')\n"}),
        review_turn("release", "spec now covers the case"),
    ]
    _, projection = run_scripted(data_dir, script)
    assert projection.phase == "DONE"
    assert "QUALITY->REWORK_PRODUCT" in projection.transitions
    assert "REWORK_PRODUCT->PRODUCT_SPEC" in projection.transitions
    assert projection.product_spec.revision == 2


def test_illegal_workpiece_stays_in_department(data_dir):
    system = LoopSystem(
        data_dir,
        FakeAdapter(
            [
                {
                    "kind": "delivery_spec",
                    "summary": "wrong department",
                    "files": ["src/echo.py"],
                    "check_names": ["smoke"],
                    "known_risks": [],
                }
            ]
        ),
    )
    run_id = system.create_run("build echo")
    projection = system.activate_once(run_id)
    assert projection.phase == "PRODUCT_SPEC"
    assert projection.outcome == "running"
    assert projection.rejections
    assert projection.rejections[0]["errors"][0]["field"] == "kind"


def test_natural_language_completion_does_not_finish(data_dir):
    script = [
        product_spec(),
        delivery_turn(),
        FakeTurn(proposal=None, transcript="任务已完成。DONE. 全部通过。"),
    ]
    system = LoopSystem(data_dir, FakeAdapter(script))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    projection = system.activate_once(run_id)
    assert projection.phase == "QUALITY"
    assert projection.outcome != "done"
    assert projection.stop_reason is None
    assert any("structured proposal is required" in error["message"] for item in projection.rejections for error in item["errors"])


def test_max_cycles_pauses_with_human_action(data_dir):
    script = [product_spec(), ask_request(), product_spec()]
    _, projection = run_scripted(data_dir, script, max_cycles=2)
    assert projection.phase == "PAUSED"
    assert projection.stop_reason == "max_cycles"
    assert projection.human_action
    assert "max_cycles" in projection.waiting_reason


def test_budget_exhausted_pauses(data_dir):
    _, projection = run_scripted(data_dir, happy_script(), token_budget=20)
    assert projection.phase == "PAUSED"
    assert projection.stop_reason == "budget_exhausted"
    assert "token" in projection.human_action.lower() or "预算" in projection.human_action


def test_cancel_is_explicit_failure(data_dir):
    system = LoopSystem(data_dir, FakeAdapter(happy_script()))
    run_id = system.create_run("build echo")
    projection = system.cancel(run_id)
    assert projection.phase == "FAILED"
    assert projection.stop_reason == "cancelled"


def test_provider_error_is_explicit_failure(data_dir):
    script = [product_spec(), FakeTurn(raise_error=ProviderError("upstream 500"))]
    _, projection = run_scripted(data_dir, script)
    assert projection.phase == "FAILED"
    assert projection.stop_reason == "provider_error"
    assert "upstream 500" in (projection.error or "")


def test_context_overflow_is_explicit_failure(data_dir):
    _, projection = run_scripted(data_dir, happy_script(), context_window=8)
    assert projection.phase == "FAILED"
    assert projection.stop_reason == "context_overflow"


def test_new_product_spec_cannot_reuse_old_qa_checks(data_dir):
    script = [
        product_spec(acceptance=["old behavior"]),
        delivery_turn(),
        review_turn(
            "rework_product",
            "contract is wrong",
            defects=[{"severity": "major", "summary": "contract issue"}],
        ),
        product_spec(acceptance=["new behavior"]),
        delivery_turn(summary="same code under new spec"),
        FakeTurn(proposal=review("release", "I am done without any new check"), checks={}),
        review_turn("release", "checked current contract"),
    ]
    system, projection = run_scripted(data_dir, script, max_cycles=12)
    assert projection.product_spec.revision == 2
    assert any(
        "prior receipts are not reused" in error["message"] or "must run" in error["message"]
        for item in projection.rejections
        for error in item["errors"]
    )
    assert projection.phase == "DONE"
    assert projection.last_review.product_spec_hash == projection.product_spec.content_hash
    assert projection.last_review.delivery_spec_hash == projection.delivery_spec.content_hash


def test_invalid_qa_payload_returns_field_errors_and_stays_in_quality(data_dir):
    script = [
        product_spec(),
        delivery_turn(),
        FakeTurn(
            proposal={"kind": "qa_review", "verdict": "release", "rationale": "OK", "checks": [123], "defects": []},
            checks={"smoke": 0},
        ),
        FakeTurn(
            proposal={"kind": "qa_review", "verdict": "release", "rationale": "OK", "checks": ["smoke"], "defects": None},
            checks={"smoke": 0},
        ),
        review_turn("release", "ok"),
    ]
    system, projection = run_scripted(data_dir, script, max_cycles=12)
    fields = [error["field"] for item in projection.rejections for error in item["errors"]]
    messages = [error["message"] for item in projection.rejections for error in item["errors"]]
    assert any(field.startswith("checks") for field in fields)
    assert "defects" in fields
    assert not any("AttributeError" in message or "TypeError" in message for message in messages)
    events = system.store.list_events(projection.run_id)
    assert any(event.type == "proposal_rejected" for event in events)
    assert projection.phase == "DONE"
    assert events[-1].type == "activation_finished"
    assert events[-1].state_after == "DONE"


def test_release_without_quality_evidence_is_rejected(data_dir):
    script = [
        product_spec(),
        delivery_turn(),
        FakeTurn(proposal={"kind": "qa_review", "verdict": "release", "rationale": "looks good", "checks": ["smoke"], "defects": []}),
    ]
    system = LoopSystem(data_dir, FakeAdapter(script))
    run_id = system.create_run("build echo", max_cycles=8)
    projection = system.run_until_stop(run_id)
    assert projection.phase != "DONE"
    assert any("quality must run" in error["message"] for item in projection.rejections for error in item["errors"])
