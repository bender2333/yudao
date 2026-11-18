# 质检在形成自己的判断以前只看到工程内容的事实部分（工单 #554、#358）：
# 工程询问质检时问题与背景分两部分，工程回答质检时回答也分两部分；
# 质检提交独立判断以前，工具结果、质检历史里的问答记录与交付说明都只给事实部分；
# 独立判断提交以后（先判断后看解释）解释部分进入它之后的请求；新的交付到达后按新交付重新计算。
#
# 集成层：真实代码与真实事件日志，假模型按会话给出脚本。

import json
from pathlib import Path
from typing import Any

from harness.watched_outputs import has_new_work
from harness.adapters.fake import FakeAdapter, prompt_part
from harness.models import EventType
from harness.proposals import default_criteria, delivery_turn, judgement_turn, product_spec, review_turn
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.tests.helpers import python_snippet

QUESTION_FACTS = "接口：echo <文本>，输出大写；文件：src/echo.py"
QUESTION_EXPLANATION = "这样实现是因为历史用例要求大写输出"
ANSWER_FACTS = "检查脚本不用改，改动只在 src/echo.py"
ANSWER_EXPLANATION = "改动风险低，评审时已经确认过"
FIRST_SUMMARY = "大写输出的 echo"
SECOND_SUMMARY = "大写输出并且补了换行"


def _call(identity: str, name: str, **args: Any) -> dict[str, Any]:
    return {
        "id": identity,
        "call_id": identity,
        "type": "function_call",
        "name": name,
        "arguments": json.dumps(args),
    }


def _engineering_asks_quality(identity: str, facts: str, explanation: str) -> ModelResponse:
    # 工程询问质检：问题与背景分两部分（工单 #554）
    return ModelResponse(output=[
        _call(identity, "ask", recipient="quality", question="", background="",
              expected="结论", facts=facts, explanation=explanation),
    ])


def _text(call: Any) -> str:
    # 一次请求里模型能看到的全部文字：钉住的材料、历史的消息与工具结果
    parts: list[str] = []
    for item in call.input_items:
        if isinstance(item.get("content"), str):
            parts.append(item["content"])
        elif isinstance(item.get("output"), str):
            parts.append(item["output"])
    return "\n".join(parts)


def _pinned(call: Any, source: str) -> Any:
    # 请求里钉住的那一段材料（装配在历史以前，同名段第一次出现的是钉住的这份）
    from harness.adapters.fake import prompt_part

    text = prompt_part(call, source)
    return None if text is None else json.loads(text)


def _quality_calls(adapter: FakeAdapter) -> list[Any]:
    return [call for call in adapter.invocations if call.department == "quality"
            and not call.session_id.startswith("ses_ask_")]


def _quality_branch_calls(adapter: FakeAdapter) -> list[Any]:
    return [call for call in adapter.invocations if call.department == "quality"
            and call.session_id.startswith("ses_ask_")]


def test_the_quality_sees_only_facts_before_its_own_conclusion(tmp_path: Path):
    # AC8 与 AC9：质检在提交结论之前询问工程，工具结果与历史记录只有事实部分；
    # 提交结论以后的请求里有解释部分；新的交付到达以后解释部分重新藏起来。
    scripts = {
        "product": [product_spec()],
        "engineering": [
            _engineering_asks_quality("ask-q1", QUESTION_FACTS, QUESTION_EXPLANATION),
            delivery_turn(summary=FIRST_SUMMARY),
            _engineering_asks_quality("ask-q2", QUESTION_FACTS, QUESTION_EXPLANATION),
            delivery_turn(summary=SECOND_SUMMARY),
        ],
        # 工程在分支里回答质检：回答分两部分（工单 #554）
        "engineering:ask": [
            ModelResponse(output=[
                _call("ans-1", "answer", answer="", facts=ANSWER_FACTS, explanation=ANSWER_EXPLANATION),
            ]),
        ],
        # 质检在分支里回答工程��回问
        "quality:ask": [
            ModelResponse(output=[_call("ans-2", "answer", answer="按现有合同。")]),
            ModelResponse(output=[_call("ans-3", "answer", answer="按现有合同。")]),
        ],
        # 质检：第一轮先问工程，交独立判断（先判断后看解释），得到回答以后提交缺陷记录；
        # 第二轮对新的交付再交独立判断并核验
        "quality": [
            ModelResponse(output=[
                _call("ask-q", "ask", recipient="engineering", question="检查项覆盖了换行吗？",
                      background="缺陷记录之前核对", expected="结论"),
            ]),
            judgement_turn(checks={"smoke": 0}),
            review_turn("rework_engineering", "换行没有被检查项覆盖", checks={"smoke": 0},
                        defects=[{"severity": "major", "summary": "换行没有被检查项覆盖"}]),
            judgement_turn(checks={"smoke": 0}),
            review_turn("release", "新的交付已经覆盖换行", checks={"smoke": 0}),
        ],
    }
    adapter = FakeAdapter(scripts)
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo")

    system.activate_once(run_id)   # 产品：产品要求
    system.activate_once(run_id)   # 工程：交付，并回问质检
    assert has_new_work(system.project(run_id), "quality"), system.project(run_id).error

    # AC9：质检分支的请求里只有问题与背景的事实部分（质检还没有下结论）
    branch_calls = _quality_branch_calls(adapter)
    assert branch_calls, "质检的分支没有发出请求"
    branch_text = _text(branch_calls[0])
    assert QUESTION_FACTS in branch_text
    assert QUESTION_EXPLANATION not in branch_text

    system.activate_once(run_id)   # 质检第一轮：先问工程（回答进不了模型，先交独立判断）
    system.activate_once(run_id)   # 质检这一轮继续：提交缺陷记录
    assert has_new_work(system.project(run_id), "engineering"), system.project(run_id).error

    quality_calls = _quality_calls(adapter)
    # 一次请求一个脚本项：问工程的请求、独立判断的请求、缺陷记录的请求
    assert len(quality_calls) == 3, [item.session_id for item in quality_calls]

    # 质检的第一轮请求（问工程）：交付说明里没有解释部分（summary 属于解释部分）
    first = _text(quality_calls[0])
    assert FIRST_SUMMARY not in first, first

    # 质检提交独立判断以后的请求（缺陷记录）：工具结果与历史里的问答记录有了回答的解释部分
    # （先判断后看解释：解释的进入时机是独立判断，不再是结论；工单 #358）
    review_call = quality_calls[2]
    assert "engineering_explanation" in _text(review_call)

    # 质检提交缺陷记录以后，工程再问质检：质检分支的请求里有解释部分
    system.activate_once(run_id)   # 工程：再问质检并提交新的交付
    assert has_new_work(system.project(run_id), "quality"), system.project(run_id).error
    branch_calls = _quality_branch_calls(adapter)
    assert len(branch_calls) == 2, branch_calls
    branch_text = _text(branch_calls[1])
    # 解释部分进入它之后的请求：工程在问答里的解释（交付说明此时已不可见）
    assert ANSWER_EXPLANATION in branch_text, branch_text

    # 质检核验新的交付：新的交付还没有独立判断，解释部分重新藏起来（钉住的 current_delivery_spec
    # 只给事实部分；历史里已经看过的解释不改写——事件不可变，工单 #554 的口径）
    system.activate_once(run_id)   # 质检：交独立判断
    system.activate_once(run_id)   # 质检：核验新的交付
    quality_calls = _quality_calls(adapter)
    # 面向第二份交付的请求按它写的当前交付区分（判断先于解释的分界，工单 #358）
    second_hash = system.project(run_id).delivery_spec.content_hash
    second_delivery_calls = [call for call in quality_calls[3:] if second_hash in _text(call)]
    assert second_delivery_calls, "第二份交付到达以后质检没有发出请求"
    judgement_call = second_delivery_calls[0]
    current = _pinned(judgement_call, "current_delivery_spec")
    assert current is not None and current["content_hash"] == second_hash
    assert "summary" not in current, "独立判断以前交付的解释部分进入了钉住的材料"
    # 独立判断提交以后的核验请求：交付的解释部分进入了
    review_call = second_delivery_calls[-1]
    review_current = _pinned(review_call, "current_delivery_spec")
    assert review_current is not None and review_current["content_hash"] == second_hash
    assert review_current["summary"] == SECOND_SUMMARY
    # 独立判断事件两份交付各一次
    judgement_events = [event for event in system.store.list_events(run_id)
                        if event.type == EventType.INDEPENDENT_JUDGEMENT_COMMITTED]
    assert len(judgement_events) == 2

    assert system.project(run_id).status == "done"
    reviews = [event for event in system.store.list_events(run_id) if event.type == EventType.QA_SUBMITTED]
    assert len(reviews) == 2


def test_disclosed_ordering_limit_is_checked_before_release(tmp_path: Path):
    # R3：简单样本不区分两种实现。解释揭示限制后，质检用冲突输入补证，按回执打回，修正后核验新交付。
    goal = "置顶项始终排在普通项之前，同类按时间从新到旧。"
    risk = "首版只比较时间；较早的置顶项可能排到较新的普通项后面。"
    path = "src/order.py"
    common = {"aligned": {"command": python_snippet(
        "from src.order import first; assert first([('A', 1, False), ('B', 2, True)]) == 'B'"
    )}}
    conflict = {"conflict": {"command": python_snippet(
        "from src.order import first; assert first([('A', 1, True), ('B', 2, False)]) == 'A'"
    )}}
    unchecked = default_criteria(1, [], method="open", result="unverified")
    failed = default_criteria(1, ["conflict"], result="failed")
    failed[0]["change_reason"] = "独立补查发现较早的置顶项没有排在首位。"
    adapter = FakeAdapter({
        "product": [product_spec(goal, requirements=[goal], acceptance=[
            "输入较早的置顶项 A 和较新的普通项 B，首项为 A。",
        ])],
        "engineering": [
            delivery_turn("按时间排序", files={path: "def first(rows):\n    return max(rows, key=lambda row: row[1])[0]\n"},
                          checks=common, known_risks=[risk]),
            delivery_turn("先比较置顶，再比较时间", files={path:
                          "def first(rows):\n    return max(rows, key=lambda row: (row[2], row[1]))[0]\n"},
                          checks=common),
        ],
        "quality": [
            judgement_turn(checks=common, criteria=unchecked),
            review_turn("rework_engineering", "冲突样本不符合 AC1", checks=conflict, criteria=failed,
                        defects=[{"severity": "major", "summary": "较新的普通项错误地排在置顶项前"}]),
            judgement_turn(checks=conflict),
            review_turn("release", "修正后的交付通过冲突检查", checks=conflict),
        ],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run(goal)
    # 单步驱动，避免预测性探索和工程交付争用同一个阶段。
    system.activate_once(run_id)   # 产品定合同
    system.activate_once(run_id)   # 工程首交
    system.activate_once(run_id)   # 质检仅据事实判断
    system.activate_once(run_id)   # 看到限制，补查并打回
    system.activate_once(run_id)   # 工程返工交付
    system.activate_once(run_id)   # 新交付独立判断
    result = system.activate_once(run_id)   # 按当前回执放行
    assert result.stop_reason == "released", result.error

    product_material = next(prompt_part(call, "work_item_guidance") for call in adapter.invocations
                            if call.department == "product")
    assert "多条规则会争夺同一个结果时" in product_material
    assert "较早的置顶项 A 和较新的普通项 B" in product_material
    assert "期望 A 排在 B 前" in product_material
    assert "询问澄清" in product_material
    quality_material = next(prompt_part(call, "work_item_guidance") for call in _quality_calls(adapter))
    assert "先判断后看解释" in quality_material
    assert "可能违反现行验收条件的具体限制" in quality_material
    assert "用能触发该限制的输入补跑独立检查" in quality_material
    assert "规则未定时用 ask 问产品" in quality_material
    assert "已证不符就返工" in quality_material

    events = system.store.list_events(run_id)
    deliveries = [event for event in events if event.type == EventType.DELIVERY_ACCEPTED]
    judgements = [event for event in events if event.type == EventType.INDEPENDENT_JUDGEMENT_COMMITTED]
    rework, release = reviews = [event for event in events if event.type == EventType.QA_SUBMITTED]
    assert [event.payload["verdict"] for event in reviews] == ["rework_engineering", "release"]
    assert rework.position < deliveries[1].position
    assert deliveries[0].payload["code_tree_digest"] != deliveries[1].payload["code_tree_digest"]
    first_delivery_hash = deliveries[0].payload["content_hash"]
    first_contexts = [context for call in _quality_calls(adapter)
                      if (context := _pinned(call, "current_delivery_spec"))
                      and context["content_hash"] == first_delivery_hash]
    assert "known_risks" not in first_contexts[0]
    assert first_contexts[-1]["known_risks"] == [risk]
    for delivery, judgement, review in zip(deliveries, judgements, reviews, strict=True):
        assert delivery.payload["checks"][0]["exit_code"] == 0  # 两份都通过常规检查
        assert delivery.position < judgement.position < review.position
        assert review.payload["judgement_event"] == judgement.event_id
        [receipt] = [row for row in review.payload["checks"] if row["name"] == "conflict"]
        assert (receipt["exit_code"] == 0) == (review is release)
        assert receipt["snapshot_hash"] == delivery.payload["code_tree_digest"]
        assert receipt["delivery_spec_hash"] == delivery.payload["content_hash"]
        assert receipt["effective_contract_hash"] == delivery.payload["effective_contract_hash"]


