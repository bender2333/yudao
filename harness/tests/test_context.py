import json

from harness.adapters.fake import FakeAdapter, FakeTurn, prompt_part, prompt_parts
from harness.context import Rules
from harness.models import EventType
from harness.proposals import answer_turn, ask_turn, delivery_turn, judgement_turn, product_spec, review_turn
from harness.runtime import LoopSystem
from harness.tests.helpers import developer_text, explore_turn, quality_turns, recorded_context

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


def test_each_assembled_request_records_the_rule_version_and_the_folded_rounds(data_dir):
    # 守 R2（合同）：每一步的上下文清单记下这一次按哪一版规则算出来的、折叠了哪几轮，
    # 重放时按同一份规则版本复原。规则全关时没有折叠任何一轮；模型的请求体（model_request 工件）
    # 仍然只有发给模型的那几部分，所以「同一份事件同一版规则装配两次逐字节相同」比的始终是同一份字节
    adapter = FakeAdapter({"product": [product_spec()]})
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    events = [event for event in system.store.list_events(run_id)
              if event.type == EventType.CONTEXT_ASSEMBLED]
    assert events
    for event in events:
        payload = event.payload
        assert payload["rules_version"] == Rules().version()
        assert payload["folded_rounds"] == []
        request = json.loads(system.artifacts.get_text(payload["request_ref"]["content_hash"]))
        assert set(request) <= {"input", "tools", "max_output_tokens"}
        # 部门材料那一条在请求的首位（设计说明第 6.1 节「材料恒在首位」）
        assert request["input"][0]["role"] == "developer"


