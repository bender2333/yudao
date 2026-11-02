import json
from contextlib import contextmanager

from harness.adapters.fake import FakeAdapter, FakeTurn, prompt_part, prompt_parts
from harness.proposals import answer_turn, ask_turn, delivery_turn, judgement_turn, product_spec, review_turn
from harness.providers import CredentialChain, ProviderFacade
from harness.runtime import LoopSystem
from harness.tests.helpers import developer_text, explore_turn, quality_turns, recorded_context
from harness.tests.protocol_helpers import serve
from harness.tests.provider_replies import HTTP_REPLIES, http_script, reply_index, request_department

def _part(call, source: str):
    text = prompt_part(call, source)
    return None if text is None else json.loads(text)

def _sources(call) -> list[str]:
    return list(prompt_parts(call))

def test_context_is_reassembled_from_projection_not_transcript(data_dir):
    marker = "PRODUCT_PRIVATE_MARKER_DO_NOT_LEAK"
    adapter = FakeAdapter(
        {
            "product": [FakeTurn(proposal=product_spec(), transcript=marker)],
            "engineering": [ask_turn(), delivery_turn()],
            "product:ask": [answer_turn("The existing contract covers this input.")],
            "quality": [explore_turn(), judgement_turn(), review_turn("release", "ok")],
        }
    )
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo")
    projection = system.run_until_stop(run_id)
    assert projection.status == "done"
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
    v2_answer = answer_turn(
        answer="Updated the contract.",
        goal="Build echo v2",
        requirements=["print the given argument in uppercase to stdout"],
        acceptance=["v2 works"],
        change_record={
            "changed": ["Use the v2 goal and acceptance criteria"],
            "retained": ["The echo CLI scope"],
            "retired": ["The original goal and acceptance criteria"],
            "rationale": "The requested revision replaces v1.",
        },
    )
    adapter = FakeAdapter(
        {
            "product": [product_spec(goal=unique)],
            "engineering": [ask_turn(), delivery_turn()],
            "product:ask": [v2_answer],
            "quality": quality_turns("release", "v2"),
        }
    )
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo")
    projection = system.run_until_stop(run_id)
    assert projection.status == "done"
    assert projection.product_spec.goal == "Build echo v2"
    engineering_after = [item for item in adapter.invocations if item.department == "engineering"][-1]
    assert unique not in developer_text(engineering_after)
    assert "Build echo v2" in developer_text(engineering_after)
    injected = [part.source for part in recorded_context(system, engineering_after).manifest.injected]
    assert injected.count("current_product_spec") == 1


def test_superseded_delivery_is_not_injected_as_current(data_dir):
    # 工程发现要求说得不清楚，询问产品，产品在回答里修订 PRD（工单 #555）：
    # 旧交付被取代以后不再当作当前交付注入
    adapter = FakeAdapter(
        {
            "product": [product_spec(acceptance=["old behavior"])],
            "engineering": [
                delivery_turn(summary="OLD_DELIVERY_CANARY"),
                ask_turn(recipient="product", question="验收标准说得不清楚，请修订。"),
                delivery_turn(summary="NEW_DELIVERY_CANARY"),
            ],
            "quality": [
                explore_turn(),
                judgement_turn(),
                review_turn("rework_engineering", "the delivery misses an acceptance criterion",
                            defects=[{"severity": "major", "summary": "contract issue"}]),
                judgement_turn(),
                review_turn("release", "new delivery checked"),
            ],
            "product:ask": [answer_turn(
                answer="已按新的验收标准修订产品要求。",
                requirements=["print the given argument to stdout"],
                acceptance=["new behavior"],
                change_record={
                    "changed": ["Replace old behavior with new behavior"], "retained": ["The echo CLI scope"],
                    "retired": ["The old behavior acceptance criterion"], "rationale": "Address the quality contract defect.",
                })],
        }
    )
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo", max_cycles=12)
    projection = system.run_until_stop(run_id)
    assert projection.status == "done"
    assert [item.status for item in projection.delivery_specs] == ["superseded", "active"]
    assert projection.delivery_specs[0].invalidation_reason in {"qa_rework_engineering", "product_spec_changed"}
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

    quality_calls = [item for item in adapter.invocations if item.department == "quality"]
    before_judgement = quality_calls[-2]
    current = _part(before_judgement, "current_delivery_spec")
    assert current is not None
    # 事实部分总在；解释部分（summary）在质检提交独立判断以前不给（工单 #554；#358：先判断后看解释，
    # 判断提交以后的请求才并入解释——这里的最后一次调用是判断以后的核验请求，解释已经在里面）
    assert current["content_hash"] == projection.delivery_spec.content_hash
    assert current["content_hash"] != projection.delivery_specs[0].content_hash
    assert "summary" not in current
    assert current["status"] == "active"
    assert _part(before_judgement, "prior_delivery") is None
    after_judgement = _part(quality_calls[-1], "current_delivery_spec")
    assert after_judgement is not None and "summary" in after_judgement


@contextmanager
def _bound_system(tmp_path, *, context_window, max_output_tokens):
    # 三个部门绑定测试内启动的 HTTP 服务上的模型（Responses 协议），模型声明给定的窗口与输出上限；
    # 服务按部门回放各自的脚本中的工具调用，记录收到的请求。提交依据的版本取自本次请求装配好的材料
    # （工单 #557：同时运行的会话各自取用自己的脚本，按请求里的工具分派到部门）
    state = {"product": 0, "engineering": 0, "quality": 0}

    def responder(body):
        department = request_department(body)
        index = state[department]
        state[department] += 1
        calls = http_script(body)[department][index]
        return 200, "text/event-stream", [HTTP_REPLIES["responses"](reply_index(department, index), calls)]

    server, capture, base = serve(responder)
    try:
        facade = ProviderFacade(credentials=CredentialChain(overrides={"CONTEXT_KEY": "context-secret"}, use_env=False))
        facade.store_document({
            "providers": [{"id": "local", "name": "Local", "base_url": base + "/v1",
                           "credential_ref": "CONTEXT_KEY", "timeout_sec": 30}],
            "models": [{"id": "model", "provider_id": "local", "model": "model",
                        "protocol": "responses",
                        "context_window": context_window, "max_output_tokens": max_output_tokens}],
            "bindings": {department: {"provider_id": "local", "model_id": "model"}
                         for department in ("product", "engineering", "quality")},
        })
        facade.record_admission("local", "model", admitted_model="model")
        yield LoopSystem(tmp_path, facade=facade), capture
    finally:
        server.shutdown()
        server.server_close()


