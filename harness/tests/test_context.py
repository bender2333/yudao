import json
from contextlib import contextmanager

from harness.adapters.fake import FakeAdapter, FakeTurn, prompt_part, prompt_parts
from harness.artifacts import ArtifactStore
from harness.context import ContextAssembler
from harness.department_prompts import DEFAULT_PROMPTS, save_department_prompt
from harness.models import DepartmentPrompt, EventType, RunProjection, SessionRecord
from harness.proposals import collaboration_request, delivery_turn, plan_turn, product_spec, product_decision, response_turn, review_turn
from harness.providers import CredentialChain, ProviderFacade
from harness.runtime import LoopSystem
from harness.smoke import summarize_run
from harness.tests.helpers import developer_text, happy_script, recorded_context, run_scripted
from harness.tests.protocol_helpers import serve
from harness.tests.test_event_sequence import HTTP_REPLIES, HTTP_SCRIPT
from harness.tools import TOOL_DEFS


def _part(call, source: str):
    text = prompt_part(call, source)
    return None if text is None else json.loads(text)


def _sources(call) -> list[str]:
    return list(prompt_parts(call))


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
        assert marker not in developer_text(item)
        manifest = recorded_context(system, item).manifest
        sources = [part.source for part in manifest.injected]
        assert "other_department_transcript" not in sources
        assert "historical_transcript" not in sources
        excluded = {part.source for part in manifest.excluded}
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
    assert unique not in developer_text(engineering_after)
    assert "Build echo v2" in developer_text(engineering_after)
    injected = [part.source for part in recorded_context(system, engineering_after).manifest.injected]
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


def test_quality_runs_its_checks_through_run_check(data_dir):
    adapter = FakeAdapter(happy_script())
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo")
    assert system.run_until_stop(run_id).phase == "DONE"
    [quality] = [item for item in adapter.invocations if item.department == "quality"]
    assert [tool["name"] for tool in quality.tools if TOOL_DEFS[tool["name"]].get("action") == "check"] == ["run_check"]
    checks = [event.payload["name"] for event in system.store.list_events(run_id)
              if event.type == EventType.TOOL_CALLED and event.role == "quality"
              and TOOL_DEFS.get(event.payload["name"], {}).get("action") == "check"]
    assert checks == ["run_check"]


def test_requests_carry_no_remaining_cycles_while_the_host_enforces_the_limit(data_dir):
    adapter = FakeAdapter([product_spec(), collaboration_request(), response_turn()])
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo", max_cycles=2)
    projection = system.run_until_stop(run_id)
    assert projection.phase == "PAUSED" and projection.stop_reason == "max_cycles"
    assert adapter.invocations
    for item in adapter.invocations:
        assert "loop_limits" not in [part.source for part in recorded_context(system, item).parts]
        assert "cycles_remaining" not in json.dumps(item.input_items, ensure_ascii=False)


def test_proposal_contract_and_binding_refs_are_injected(data_dir):
    adapter = FakeAdapter(happy_script())
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)
    for item in adapter.invocations:
        manifest = recorded_context(system, item).manifest
        sources = [part.source for part in manifest.injected]
        assert "proposal_contract" in sources
        assert "binding_refs" in sources
        assert "proposal_contract" in developer_text(item)
        excluded = {part.source for part in manifest.excluded}
        assert "other_department_transcript" in excluded
        assert "internal JSON 实现协议" not in developer_text(item)


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
    assert "validation_feedback" in developer_text(product_calls[1])
    assert "goal" in developer_text(product_calls[1])


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
        assert "DECISION_CANARY_A" in developer_text(request)
        assert "DECISION_CANARY_C" in developer_text(request)


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
        assert "BACKGROUND_CANARY" in developer_text(request)
        assert "IMPACT_CANARY" in developer_text(request)


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
    assert stale not in developer_text(engineering_after)
    assert _part(engineering_after, "current_product_decisions") is None
    excluded = {item.source for item in recorded_context(system, engineering_after).manifest.excluded}
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
        if item.department == "engineering" and "new behavior" in developer_text(item)
    ][0]
    assert _part(engineering_after_r2, "current_delivery_spec") is None
    prior = _part(engineering_after_r2, "prior_delivery")
    assert prior is not None
    assert prior["summary"] == "OLD_DELIVERY_CANARY"
    assert prior["status"] == "superseded"
    assert prior["purpose"] == "repair_basis"
    assert prior["invalidation_reason"]
    assert "current_delivery_spec" not in _sources(engineering_after_r2)
    excluded = {item.source for item in recorded_context(system, engineering_after_r2).manifest.excluded}
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
    assert "validation_feedback" in developer_text(engineering[2])
    later = engineering[-1]
    assert "validation_feedback" not in _sources(later)
    assert developer_text(later).count("validation_feedback") == 0


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


@contextmanager
def _bound_system(tmp_path, replies, *, context_window, max_output_tokens):
    # 三个部门绑定测试内启动的 HTTP 服务上的模型（Responses 协议），模型声明给定的窗口与输出上限；
    # 服务按请求顺序回放脚本中的工具调用，记录收到的请求
    queue = iter(enumerate(replies, start=1))

    def responder(_body):
        index, calls = next(queue)
        return 200, "text/event-stream", [HTTP_REPLIES["responses"](index, calls)]

    server, capture, base = serve(responder)
    try:
        facade = ProviderFacade(credentials=CredentialChain(overrides={"CONTEXT_KEY": "context-secret"}, use_env=False))
        facade.store_document({
            "providers": [{"id": "local", "name": "Local", "base_url": base + "/v1",
                           "credential_ref": "CONTEXT_KEY", "timeout_sec": 30}],
            "models": [{"id": "model", "provider_id": "local", "model": "model", "protocol": "responses",
                        "context_window": context_window, "max_output_tokens": max_output_tokens}],
            "bindings": {department: {"provider_id": "local", "model_id": "model"}
                         for department in ("product", "engineering", "quality")},
        })
        facade.record_admission("local", "model", admitted_model="model")
        yield LoopSystem(tmp_path, facade=facade), capture
    finally:
        server.shutdown()
        server.server_close()


def _work_assemblies(system, run_id):
    return [event.payload for event in system.store.list_events(run_id)
            if event.type == EventType.CONTEXT_ASSEMBLED and event.payload["purpose"] == "work"]


def test_narrow_window_work_request_spends_the_window_left_after_its_input(tmp_path):
    with _bound_system(tmp_path, HTTP_SCRIPT[:1], context_window=8000, max_output_tokens=4096) as (system, capture):
        run_id = system.create_run("build echo")
        result = system.activate_once(run_id)

    assert result.phase == "ENGINEERING", result.error
    [payload] = _work_assemblies(system, run_id)
    assert payload["effective_context_window"] == 8000 and payload["configured_max_output_tokens"] == 4096
    assert 2000 <= payload["input_token_estimate"] <= 3500  # pinned department material plus tool schemas
    # The request keeps whatever the window leaves after its input, up to the declared limit:
    # the old fixed 15% reserve would have allowed only 1200 tokens here.
    assert payload["max_output_tokens"] == min(4096, 8000 - payload["input_token_estimate"]) >= 4000
    assert payload["output_reserve_tokens"] == payload["max_output_tokens"]
    assert payload["admitted"] is True
    assert capture.requests[0]["max_output_tokens"] == payload["max_output_tokens"]
    assert summarize_run(system, run_id, scenario="narrow")["model_input_audit"]["status"] == "verified"


def test_wide_window_work_requests_keep_the_declared_output_limit(tmp_path):
    with _bound_system(tmp_path, HTTP_SCRIPT, context_window=32000, max_output_tokens=4096) as (system, capture):
        run_id = system.create_run("build echo")
        result = system.run_until_stop(run_id)

    assert result.phase == "DONE", result.error
    payloads = _work_assemblies(system, run_id)
    assert len(payloads) == len(capture.requests) == 4
    assert [request["max_output_tokens"] for request in capture.requests] == [4096] * 4
    # Baseline before the narrow-window reserve: every 32000/4096 work request asked for 4096 tokens.
    assert all(item["max_output_tokens"] == item["output_reserve_tokens"] == 4096 for item in payloads)
    assert all(item["admitted"] is True and item["effective_context_window"] == 32000 for item in payloads)
    assert summarize_run(system, run_id, scenario="wide")["model_input_audit"]["status"] == "verified"
