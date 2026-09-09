import json

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.artifacts import ArtifactStore
from harness.context import ContextAssembler
from harness.department_prompts import DEFAULT_PROMPTS, save_department_prompt
from harness.models import DepartmentPrompt, RunProjection, SessionRecord
from harness.proposals import collaboration_request, delivery_turn, plan_turn, product_spec, product_decision, response_turn, review_turn
from harness.runtime import LoopSystem
from harness.tests.helpers import happy_script, run_scripted


def _part(request, source: str):
    for item in request.context.parts:
        if item.source == source:
            return json.loads(item.text)
    return None


def _sources(request) -> list[str]:
    return [item.source for item in request.context.manifest.injected]


def test_context_is_reassembled_from_projection_not_transcript(data_dir):
    marker = "PRODUCT_PRIVATE_MARKER_DO_NOT_LEAK"
    adapter = FakeAdapter(
        [
            FakeTurn(proposal=product_spec(), transcript=marker),
            collaboration_request(),
            response_turn("answered", "The existing contract covers this input."),
            plan_turn(),
            delivery_turn(),
            review_turn("release", "ok"),
        ]
    )
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo")
    projection = system.run_until_stop(run_id)
    assert projection.phase == "DONE"
    later = [item for item in adapter.invocations if item.department != "product"]
    assert later
    for item in later:
        assert marker not in item.context.prompt_text
        sources = [part.source for part in item.context.manifest.injected]
        assert "other_department_transcript" not in sources
        assert "historical_transcript" not in sources
        excluded = {part.source for part in item.context.manifest.excluded}
        assert "other_department_transcript" in excluded
        assert "superseded_spec_as_current" in excluded


def test_old_spec_full_text_is_not_injected_after_supersede(data_dir):
    unique = "UNIQUE_GOAL_V1_MUST_NOT_LEAK"
    v2 = product_spec(goal="Build echo v2", acceptance=["v2 works"], change_record={
        "changed": ["Use the v2 goal and acceptance criteria"], "retained": ["The echo CLI scope"],
        "retired": ["The original goal and acceptance criteria"], "rationale": "The requested revision replaces v1.",
    })
    adapter = FakeAdapter(
        [
            product_spec(goal=unique),
            collaboration_request(request_type="action", action="revise_requirements"),
            v2,
            response_turn("completed", "Updated the contract.", result_types=["spec_accepted"]),
            plan_turn(),
            delivery_turn(),
            review_turn("release", "v2"),
        ]
    )
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo")
    projection = system.run_until_stop(run_id)
    assert projection.phase == "DONE"
    assert projection.product_spec.goal == "Build echo v2"
    engineering_after = [item for item in adapter.invocations if item.department == "engineering"][-1]
    assert unique not in engineering_after.context.prompt_text
    assert "Build echo v2" in engineering_after.context.prompt_text
    injected = [part.source for part in engineering_after.context.manifest.injected]
    assert injected.count("current_product_spec") == 1


def test_each_department_has_its_own_session(data_dir):
    _, projection = run_scripted(data_dir, happy_script())
    sessions = projection.sessions
    assert set(sessions) == {"product", "engineering", "quality"}
    ids = {item.session_id for item in sessions.values()}
    assert len(ids) == 3
    assert sessions["product"].activations >= 1
    assert sessions["engineering"].activations >= 1
    assert sessions["quality"].activations >= 1


def test_product_and_quality_do_not_receive_write_tools(data_dir):
    adapter = FakeAdapter(happy_script())
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)
    by_dept = {item.department: [tool["name"] for tool in item.tools] for item in adapter.invocations}
    assert "write_file" not in by_dept["product"]
    assert "write_file" in by_dept["engineering"]
    assert "write_file" not in by_dept["quality"]


def test_proposal_contract_and_binding_refs_are_injected(data_dir):
    adapter = FakeAdapter(happy_script())
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)
    for item in adapter.invocations:
        sources = [part.source for part in item.context.manifest.injected]
        assert "proposal_contract" in sources
        assert "binding_refs" in sources
        assert "proposal_contract" in item.context.prompt_text
        excluded = {part.source for part in item.context.manifest.excluded}
        assert "other_department_transcript" in excluded
        assert "internal JSON 实现协议" not in item.context.prompt_text


def test_validation_feedback_is_injected_after_rejection(data_dir):
    adapter = FakeAdapter(
        [
            {"kind": "product_spec", "goal": "", "requirements": ["r"], "acceptance_criteria": ["a"]},
            product_spec(),
            plan_turn(),
            delivery_turn(),
            review_turn("release", "ok"),
        ]
    )
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)
    product_calls = [item for item in adapter.invocations if item.department == "product"]
    assert len(product_calls) >= 2
    assert "validation_feedback" in product_calls[1].context.prompt_text
    assert "goal" in product_calls[1].context.prompt_text


def test_two_formal_product_decisions_reach_engineering_and_quality(data_dir):
    adapter = FakeAdapter(
        [
            product_spec(),
            collaboration_request(question="First canary choice?", request_type="action", action="revise_requirements"),
            product_decision("Use DECISION_CANARY_A.", "The first requirement needs this exact output."),
            response_turn("completed", "Published the first decision.", result_types=["product_decision_accepted"]),
            collaboration_request(question="Second canary choice?", request_type="action", action="revise_requirements"),
            product_decision("Use DECISION_CANARY_C.", "The second requirement needs this exact output."),
            response_turn("completed", "Published the second decision.", result_types=["product_decision_accepted"]),
            plan_turn(),
            delivery_turn(),
            review_turn("release", "accepted both product decisions"),
        ]
    )
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo", max_cycles=12)
    projection = system.run_until_stop(run_id)
    assert projection.phase == "DONE"
    assert len(projection.effective_decisions) == 2
    assert [item.statement for item in projection.effective_decisions] == [
        "Use DECISION_CANARY_A.",
        "Use DECISION_CANARY_C.",
    ]
    engineering = [item for item in adapter.invocations if item.department == "engineering"][-1]
    quality = [item for item in adapter.invocations if item.department == "quality"][-1]
    for request in (engineering, quality):
        sources = _sources(request)
        assert "current_product_decisions" in sources
        decisions = _part(request, "current_product_decisions")
        assert decisions is not None
        assert len(decisions) == 2
        texts = json.dumps(decisions)
        assert "DECISION_CANARY_A" in texts
        assert "DECISION_CANARY_C" in texts
        assert "first requirement" in texts
        assert "second requirement" in texts
        assert "DECISION_CANARY_A" in request.context.prompt_text
        assert "DECISION_CANARY_C" in request.context.prompt_text


def test_effective_decision_keeps_explicit_requirement_and_request_source(data_dir):
    adapter = FakeAdapter(
        [
            product_spec(),
            collaboration_request(
                question="采用背景中描述的方案吗？",
                background="Actual required output token is BACKGROUND_CANARY",
                request_type="action", action="revise_requirements",
            ),
            product_decision("Print BACKGROUND_CANARY for the selected mode.", "IMPACT_CANARY identifies the required public behavior."),
            response_turn("completed", "The behavior has been published.", result_types=["product_decision_accepted"]),
            plan_turn(),
            delivery_turn(),
            review_turn("release", "accepted the described approach"),
        ]
    )
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo", max_cycles=12)
    projection = system.run_until_stop(run_id)
    assert projection.phase == "DONE"
    assert len(projection.effective_decisions) == 1
    decision = projection.effective_decisions[0]
    assert decision.statement == "Print BACKGROUND_CANARY for the selected mode."
    assert decision.rationale == "IMPACT_CANARY identifies the required public behavior."
    assert decision.request_id == projection.requests[0].id
    engineering = [item for item in adapter.invocations if item.department == "engineering"][-1]
    quality = [item for item in adapter.invocations if item.department == "quality"][-1]
    for request in (engineering, quality):
        decisions = _part(request, "current_product_decisions")
        assert decisions is not None
        assert len(decisions) == 1
        assert decisions[0]["statement"] == decision.statement
        assert decisions[0]["request_id"] == decision.request_id
        assert "BACKGROUND_CANARY" in request.context.prompt_text
        assert "IMPACT_CANARY" in request.context.prompt_text


def test_new_spec_does_not_inject_stale_product_decisions(data_dir):
    stale = "RETIRED_DECISION_SHOULD_NOT_LEAK"

    def retire_decisions(request):
        decisions = _part(request, "current_product_decisions")
        return product_spec(acceptance=["new behavior"], change_record={
            "changed": ["Use the new behavior acceptance criterion"], "retained": ["The echo CLI scope"],
            "retired": ["The previous acceptance criterion and product decision"],
            "rationale": "Quality found that the previous product contract was wrong.",
        }, decision_changes=[
            {"decision_hash": item["content_hash"], "disposition": "retire", "rationale": "The new behavior replaces this requirement."}
            for item in decisions
        ])

    adapter = FakeAdapter(
        [
            product_spec(acceptance=["old behavior"]),
            collaboration_request(question="Publish the canary requirement?", request_type="action", action="revise_requirements"),
            product_decision(stale, "This is the initial product requirement."),
            response_turn("completed", "Published the requirement.", result_types=["product_decision_accepted"]),
            plan_turn(),
            delivery_turn(summary="OLD_DELIVERY_CANARY"),
            review_turn(
                "rework_product",
                "contract is wrong",
                defects=[{"severity": "major", "summary": "contract issue"}],
            ),
            retire_decisions,
            plan_turn(reason="Implement the current replacement contract"),
            delivery_turn(summary="new delivery"),
            review_turn("release", "new contract checked"),
        ]
    )
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo", max_cycles=12)
    projection = system.run_until_stop(run_id)
    assert projection.phase == "DONE"
    assert projection.product_spec.revision == 2
    assert projection.effective_decisions == []
    engineering_after = [item for item in adapter.invocations if item.department == "engineering"][-1]
    assert stale not in engineering_after.context.prompt_text
    assert _part(engineering_after, "current_product_decisions") is None
    excluded = {item.source for item in engineering_after.context.manifest.excluded}
    assert "expired_product_decisions" in excluded


def test_superseded_delivery_is_not_injected_as_current(data_dir):
    adapter = FakeAdapter(
        [
            product_spec(acceptance=["old behavior"]),
            plan_turn(),
            delivery_turn(summary="OLD_DELIVERY_CANARY"),
            review_turn(
                "rework_product",
                "contract is wrong",
                defects=[{"severity": "major", "summary": "contract issue"}],
            ),
            product_spec(acceptance=["new behavior"], change_record={
                "changed": ["Replace old behavior with new behavior"], "retained": ["The echo CLI scope"],
                "retired": ["The old behavior acceptance criterion"], "rationale": "Address the quality contract defect.",
            }),
            plan_turn(reason="Implement the current replacement contract"),
            delivery_turn(summary="NEW_DELIVERY_CANARY"),
            review_turn("release", "new delivery checked"),
        ]
    )
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo", max_cycles=12)
    projection = system.run_until_stop(run_id)
    assert projection.phase == "DONE"
    assert [item.status for item in projection.delivery_specs] == ["superseded", "active"]
    assert projection.delivery_specs[0].invalidation_reason in {"qa_rework_product", "product_spec_changed"}
    assert projection.delivery_spec is not None
    assert projection.delivery_spec.summary == "NEW_DELIVERY_CANARY"
    assert projection.delivery_spec.status == "active"
    assert sum(1 for item in projection.delivery_specs if item.status == "active") == 1

    engineering_after_r2 = [
        item
        for item in adapter.invocations
        if item.department == "engineering" and "new behavior" in item.context.prompt_text
    ][0]
    assert _part(engineering_after_r2, "current_delivery_spec") is None
    prior = _part(engineering_after_r2, "prior_delivery")
    assert prior is not None
    assert prior["summary"] == "OLD_DELIVERY_CANARY"
    assert prior["status"] == "superseded"
    assert prior["purpose"] == "repair_basis"
    assert prior["invalidation_reason"]
    assert "current_delivery_spec" not in _sources(engineering_after_r2)
    excluded = {item.source for item in engineering_after_r2.context.manifest.excluded}
    assert "invalid_delivery_as_current" in excluded

    quality = [item for item in adapter.invocations if item.department == "quality"][-1]
    current = _part(quality, "current_delivery_spec")
    assert current is not None
    assert current["summary"] == "NEW_DELIVERY_CANARY"
    assert current["status"] == "active"
    assert _part(quality, "prior_delivery") is None


def test_rework_engineering_keeps_only_one_active_delivery(data_dir):
    adapter = FakeAdapter(
        [
            product_spec(),
            plan_turn(),
            delivery_turn(summary="OLD_DELIVERY_CANARY"),
            review_turn(
                "rework_engineering",
                "need a fix",
                defects=[{"severity": "minor", "summary": "naming"}],
            ),
            plan_turn(reason="Address the quality naming defect"),
            delivery_turn(summary="FIXED_DELIVERY", files={"src/echo.py": "print('v2')\n"}),
            review_turn("release", "ok"),
        ]
    )
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo", max_cycles=12)
    projection = system.run_until_stop(run_id)
    assert projection.phase == "DONE"
    assert [item.status for item in projection.delivery_specs] == ["superseded", "active"]
    assert projection.delivery_specs[0].invalidation_reason == "qa_rework_engineering"
    assert projection.delivery_spec.summary == "FIXED_DELIVERY"
    repair = [
        item
        for item in adapter.invocations
        if item.department == "engineering" and _part(item, "prior_delivery") is not None
    ]
    assert repair
    prior = _part(repair[0], "prior_delivery")
    assert prior["summary"] == "OLD_DELIVERY_CANARY"
    assert prior["status"] == "superseded"
    assert prior["invalidation_reason"] == "qa_rework_engineering"
    assert _part(repair[0], "current_delivery_spec") is None


def test_validation_feedback_is_not_kept_after_successful_proposal(data_dir):
    adapter = FakeAdapter(
        [
            product_spec(),
            plan_turn(),
            {"kind": "delivery_spec", "summary": "", "files": ["src/echo.py"], "check_names": ["smoke"]},
            delivery_turn(summary="first valid delivery"),
            review_turn(
                "rework_engineering",
                "need a fix",
                defects=[{"severity": "minor", "summary": "naming"}],
            ),
            plan_turn(reason="Address the quality naming defect"),
            delivery_turn(summary="fixed", files={"src/echo.py": "print('v2')\n"}),
            review_turn("release", "ok"),
        ]
    )
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo", max_cycles=12)
    projection = system.run_until_stop(run_id)
    assert projection.phase == "DONE"
    engineering = [item for item in adapter.invocations if item.department == "engineering"]
    assert "validation_feedback" in engineering[2].context.prompt_text
    later = engineering[-1]
    assert "validation_feedback" not in _sources(later)
    assert later.context.prompt_text.count("validation_feedback") == 0


def test_assembler_records_budget_and_digest(tmp_path):
    prompt_text = DEFAULT_PROMPTS["engineering"]
    prompt_ref = save_department_prompt(ArtifactStore(tmp_path), "run_x", "engineering", prompt_text)
    projection = RunProjection(
        run_id="run_x",
        task="task",
        phase="ENGINEERING",
        context_window=8000,
        sessions={"engineering": SessionRecord("ses_e", "engineering", "active")},
        department_prompts={"engineering": DepartmentPrompt("engineering", 1, prompt_text, prompt_ref, "initial-prompt")},
    )
    assembled = ContextAssembler().assemble(projection, department="engineering", session_id="ses_e", activation_id="act_1")
    assert assembled.manifest.budget == 8000
    assert assembled.manifest.digest.startswith("sha256:")
    assert assembled.manifest.token_estimate > 0
    assert any(item.source == "department_rules" for item in assembled.manifest.injected)


def test_compaction_request_with_widened_output_limit_stays_within_the_window(tmp_path):
    from harness.compaction import plan_compaction
    from harness.models import canonical_hash

    prompt_text = DEFAULT_PROMPTS["engineering"]
    prompt_ref = save_department_prompt(ArtifactStore(tmp_path), "run_x", "engineering", prompt_text)
    projection = RunProjection(
        run_id="run_x", task="task", phase="ENGINEERING", context_window=8000,
        sessions={"engineering": SessionRecord("ses_e", "engineering", "active")},
        department_prompts={"engineering": DepartmentPrompt("engineering", 1, prompt_text, prompt_ref, "initial-prompt")},
    )
    assembler = ContextAssembler()
    pinned = assembler.assemble(projection, department="engineering", session_id="ses_e", activation_id="act_1",
                                context_window=8000, max_output_tokens=1200)
    records = []
    for index in range(1, 9):
        item = {"id": f"msg-{index}", "type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": f"Evidence {index}: " + "x" * 2400}]}
        records.append({"event_id": f"event-{index}", "seq": index, "activation_id": "act_0", "step_id": index,
                        "item": item, "item_digest": canonical_hash(item)})
    plan = plan_compaction(records, None, 8000, pinned.input_items, pinned.tools, output_limit=4096)
    assert plan is not None
    assert plan.max_output_tokens == min(4096, 8000 - plan.input_token_estimate) > 8000 - 8000 * 85 // 100
    assembled = assembler.assemble_compaction(
        pinned, input_items=plan.input_items, source_refs=plan.source_refs,
        max_output_tokens=plan.max_output_tokens, compaction_event_id=None,
    )
    manifest = assembled.manifest
    assert manifest.purpose == "compaction" and assembled.tools == []
    assert manifest.input_token_estimate == plan.input_token_estimate
    assert manifest.output_reserve_tokens == manifest.max_output_tokens == plan.max_output_tokens
    # Admission is input estimate plus the output limit within the effective window.
    assert manifest.input_token_estimate + manifest.output_reserve_tokens <= manifest.budget == 8000
