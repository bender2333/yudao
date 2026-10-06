from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.definitions import DEFINITIONS
from harness.proposals import collaboration_request, delivery_turn, plan_turn, product_spec, response_turn, review, review_turn
from harness.runtime import LoopSystem
from harness.tests.helpers import department_history, happy_script, run_scripted


def test_happy_path_requires_quality_release(data_dir):
    system, projection = run_scripted(data_dir, happy_script())
    facts = system.workspace(projection.run_id).snapshot().facts
    engineering_check = facts.latest_check("engineering", "smoke")
    quality_check = facts.latest_check("quality", "smoke")
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


def test_consultation_response_returns_to_engineering(data_dir):
    script = [
        product_spec(),
        collaboration_request(),
        response_turn("answered", "The existing requirements already define ordinary input."),
        plan_turn(),
        delivery_turn(),
        review_turn("release", "accepted path is implemented"),
    ]
    _, projection = run_scripted(data_dir, script)
    assert projection.phase == "DONE"
    assert projection.request_count == 1
    assert projection.requests[0].requester == "engineering"
    assert projection.requests[0].recipient == "product"
    assert projection.responses[0].status == "answered"
    assert projection.responses[0].return_phase == "ENGINEERING"
    assert projection.effective_decisions == []
    assert projection.product_spec.revision == 1


def test_requested_requirements_revision_creates_normal_spec_before_response(data_dir):
    updated = product_spec(
        goal="Build echo with strict flags", acceptance=["unknown flags exit 2"],
        change_record={
            "changed": ["Unknown flags must exit 2"],
            "retained": ["Print the given argument to stdout", "Single-file implementation without file reads or network access"],
            "retired": [],
            "rationale": "Resolve the engineering action request by defining previously unspecified flag behavior.",
        },
    )
    script = [
        product_spec(),
        collaboration_request(request_type="action", action="revise_requirements"),
        updated,
        response_turn("completed", "Unknown flags must fail.", result_types=["spec_accepted"]),
        plan_turn(),
        delivery_turn(),
        review_turn("release", "reply applied"),
    ]
    _, projection = run_scripted(data_dir, script)
    assert projection.phase == "DONE"
    assert projection.responses[0].status == "completed"
    assert projection.responses[0].result_event_ids == [projection.product_spec.created_event_id]
    assert projection.product_spec.revision == 2
    assert projection.product_spec.goal == "Build echo with strict flags"
    assert projection.product_specs[0].status == "superseded"
    assert projection.delivery_spec.product_spec_hash == projection.product_spec.content_hash


def test_consultation_answer_is_not_a_product_decision(data_dir):
    script = [
        product_spec(),
        collaboration_request(),
        response_turn("answered", "A possible future requirement would reject unknown flags."),
        plan_turn(),
        delivery_turn(),
        review_turn("release", "ok"),
    ]
    _, projection = run_scripted(data_dir, script)
    assert projection.phase == "DONE"
    assert projection.effective_decisions == []
    assert len(projection.effective_contracts) == 1
    assert projection.product_spec.revision == 1


def test_declined_request_keeps_engineering_on_current_spec(data_dir):
    script = [
        product_spec(),
        collaboration_request(),
        response_turn("declined", "No requirements revision is needed for the current task."),
        plan_turn(),
        delivery_turn(),
        review_turn("release", "rejected alternative"),
    ]
    _, projection = run_scripted(data_dir, script)
    assert projection.phase == "DONE"
    assert projection.responses[0].status == "declined"
    assert projection.product_spec.revision == 1
    assert projection.responses[0].return_phase == "ENGINEERING"


def test_quality_rework_routes_to_engineering(data_dir):
    script = [
        product_spec(),
        plan_turn(),
        delivery_turn(summary="first delivery"),
        review_turn(
            "rework_engineering",
            "edge case fails",
            defects=[{"severity": "major", "summary": "empty input is unhandled"}],
        ),
        plan_turn(reason="Address the reported empty input defect"),
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
        plan_turn(),
        delivery_turn(),
        review_turn(
            "rework_product",
            "acceptance misses empty input",
            defects=[{"severity": "blocker", "summary": "empty input not in spec"}],
        ),
        product_spec(
            goal="Build echo including empty input", acceptance=["empty input prints a blank line"],
            change_record={
                "changed": ["Empty input must print a blank line"],
                "retained": ["Print the given argument to stdout", "Single-file implementation without file reads or network access"],
                "retired": [],
                "rationale": "Address the quality review identifying missing acceptance coverage for empty input.",
            },
        ),
        plan_turn(reason="Apply the revised empty input requirement"),
        delivery_turn(summary="updated implementation", files={"src/echo.py": "print('')\n"}),
        review_turn("release", "spec now covers the case"),
    ]
    _, projection = run_scripted(data_dir, script)
    assert projection.phase == "DONE"
    assert "QUALITY->REWORK_PRODUCT" in projection.transitions
    assert "REWORK_PRODUCT->PRODUCT_SPEC" in projection.transitions
    assert projection.product_spec.revision == 2


def test_illegal_workpiece_stays_in_department(data_dir):
    system = LoopSystem.for_testing(
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
        plan_turn(),
        delivery_turn(),
        *[FakeTurn(proposal=None, transcript="任务已完成。DONE. 全部通过。") for _ in range(DEFINITIONS.limits.tool_call_required_limit + 1)],
    ]
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.activate_once(run_id)
    projection = system.activate_once(run_id)
    assert projection.phase == "PAUSED"
    assert projection.outcome != "done"
    assert projection.stop_reason == "no_tool_call"
    assert projection.last_review is None


def test_max_cycles_pauses_with_human_action(data_dir):
    script = [product_spec(), collaboration_request(), response_turn()]
    _, projection = run_scripted(data_dir, script, max_cycles=2)
    assert projection.phase == "PAUSED"
    assert projection.stop_reason == "max_cycles"
    assert projection.human_action
    assert "循环次数已达上限" in projection.waiting_reason


def test_cycle_limit_pauses_after_work_without_provider_usage(data_dir):
    _, projection = run_scripted(data_dir, happy_script(), max_cycles=1)
    assert projection.phase == "PAUSED"
    assert projection.stop_reason == "max_cycles"
    assert projection.product_spec is not None
    assert projection.token_used == 0


def test_cancel_is_explicit_failure(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
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
        plan_turn(),
        delivery_turn(),
        review_turn(
            "rework_product",
            "contract is wrong",
            defects=[{"severity": "major", "summary": "contract issue"}],
        ),
        product_spec(
            acceptance=["new behavior"],
            change_record={
                "changed": ["Replace the acceptance criterion with new behavior"],
                "retained": ["The echo goal, argument-printing requirement, and existing implementation constraints"],
                "retired": ["The old behavior acceptance criterion"],
                "rationale": "Correct the contract issue reported by quality; evidence must be collected against the revised criterion.",
            },
        ),
        plan_turn(reason="Apply the revised contract before implementation"),
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
        plan_turn(),
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
        plan_turn(),
        delivery_turn(),
        FakeTurn(proposal={"kind": "qa_review", "verdict": "release", "rationale": "looks good", "checks": ["smoke"], "defects": []}),
    ]
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    run_id = system.create_run("build echo", max_cycles=8)
    projection = system.run_until_stop(run_id)
    assert projection.phase != "DONE"
    assert any("quality must run" in error["message"] for item in projection.rejections for error in item["errors"])


def test_truncated_work_response_is_terminal_without_retry(data_dir):
    from harness.providers.call import ModelResponse
    from harness.models import EventType, json_dumps

    truncated = ModelResponse(
        output=[{"id": "cut", "type": "message", "role": "assistant", "status": "incomplete",
                 "content": [{"type": "output_text", "text": "TRUNCATED_WORK the product spec should"}]}],
        finish_reason="incomplete", error="max_output_tokens",
    )
    adapter = FakeAdapter([truncated, product_spec()])
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo")
    result = system.activate_once(run_id)

    assert result.phase == "FAILED" and result.stop_reason == "provider_error"
    assert len(adapter.invocations) == 1
    events = system.store.list_events(run_id)
    failed = [event for event in events if event.type == EventType.MODEL_ATTEMPT_FAILED]
    assert len(failed) == 1 and failed[0].payload["purpose"] == "work"
    assert failed[0].payload["retryable"] is False and failed[0].payload["will_retry"] is False
    assert not any(event.type == EventType.MODEL_RETRY_SCHEDULED for event in events)
    assert "TRUNCATED_WORK" not in json_dumps(department_history(system, run_id, "product"))
    assert result.canonical_state() == system.replay(run_id).canonical_state()
