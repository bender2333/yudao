# 独立判断事件（验证的独立性 docs/design/independent-verification.md「先判断后看解释」，工单 #358）：核验角色在只看事实的上下文里对当前交付
# 的每条验收条件写出判断，经写入口写成事实（independent_judgement_committed）。
#
# 这份测试守的行为：
# 1. 一份交付一份判断：同一份交付的第二次判断被拒绝；新交付到达以后可以再交一次。
# 2. 事件的内容：载荷带依据的 PRD 与交付摘要、逐条结论（#151 的形状）、判断的条数；
#    它不是成果——不进版本链、不失效当前交付、不结束运行。
# 3. 探索轮（没有交付）提交判断被拒绝，理由写明需要当前交付（与 #557 的口径一致）。
#
# 集成层：真实代码、真实事件日志与写入口，假模型按部门给出脚本。

from harness.adapters.fake import FakeAdapter
from harness.models import EventType
from harness.proposals import delivery_turn, judgement_turn, product_spec, review_turn
from harness.runtime import LoopSystem


def _script():
    return {
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [review_turn("release", "下结论之前忘了先交判断"),
                    judgement_turn(),
                    review_turn("release", "判断已提交，按它下结论")],
    }


def _events(system, run_id):
    return system.store.list_events(run_id)


def test_a_judgement_covers_one_delivery_and_carries_the_criteria(tmp_path):
    # 判断的内容与它不是成果：一条事件、带依据的交付摘要与逐条结论、不改投影的成果清单
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(_script()))
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)

    events = _events(system, run_id)
    [judgement] = [event for event in events if event.type == EventType.INDEPENDENT_JUDGEMENT_COMMITTED]
    [delivery] = [event for event in events if event.type == EventType.DELIVERY_ACCEPTED]
    payload = judgement.payload
    assert payload["kind"] == "independent_judgement"
    assert payload["delivery_spec_hash"] == delivery.payload["content_hash"]
    assert payload["product_spec_hash"] == delivery.payload["product_spec_hash"]
    assert payload["criteria_count"] == len(payload["criteria"]) >= 1
    assert payload["criteria"][0]["criterion"] == "AC1"
    assert payload["checks"] == ["smoke"]
    # 不是成果：事件不进版本链（没有 git_version）、当前交付仍然有效、运行由放行结束
    assert "git_version" not in payload
    assert system.project(run_id).delivery_spec is not None
    assert system.project(run_id).stop_reason == "released"


def test_a_second_judgement_for_the_same_delivery_is_rejected(tmp_path):
    # 一份交付一份判断：同一份交付的第二次判断被拒绝，字段级错误说明已有
    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [judgement_turn(), judgement_turn(),
                    review_turn("release", "按第一次判断下结论")],
    }))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)   # 产品提交 PRD
    system.activate_once(run_id)   # 工程交付
    projection = system.run_until_stop(run_id)
    assert projection.status == "done", projection.stop_reason

    events = _events(system, run_id)
    judgements = [event for event in events if event.type == EventType.INDEPENDENT_JUDGEMENT_COMMITTED]
    assert len(judgements) == 1
    rejected = [event for event in events if event.type == EventType.PROPOSAL_REJECTED]
    messages = [error["message"] for event in rejected for error in event.payload["errors"]]
    assert any("already committed" in message for message in messages)


def test_an_exploration_round_cannot_commit_a_judgement(tmp_path):
    # 探索轮没有交付：判断被拒绝，理由写明需要当前交付（与 #557 的口径一致）。
    # 质检的脚本全是判断：还没有交付时每次提交都被拒绝，运行到轮次上限暂停
    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [judgement_turn()] * 8,
    }))
    run_id = system.create_run("build echo")
    projection = system.run_until_stop(run_id)
    assert projection.status != "done"
    rejected = [event for event in _events(system, run_id)
                if event.type == EventType.PROPOSAL_REJECTED
                and (event.payload or {}).get("kind") == "independent_judgement"]
    assert rejected, "还没有交付时独立判断没有被拒绝"
    [error] = rejected[0].payload["errors"]
    assert error["field"] == "delivery_spec"
    assert "no delivery to review" in error["message"]
    # 工程交付以后判断可以提交：交付的判断只交一次
    projection = system.run_until_stop(run_id)
    committed = [event for event in _events(system, run_id)
                 if event.type == EventType.INDEPENDENT_JUDGEMENT_COMMITTED]
    assert len(committed) == 1
