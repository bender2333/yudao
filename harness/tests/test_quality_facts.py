# 质检在形成自己的判断以前只看到工程内容的事实部分（工单 #554）：
# 工程询问质检时问题与背景分两部分，工程回答质检时回答也分两部分；
# 质检对当前交付提交结论以前，工具结果、质检历史里的问答记录与交付说明都只给事实部分；
# 提交结论以后解释部分进入它之后的请求；新的交付到达后按新交付重新计算。
#
# 集成层：真实代码与真实事件日志，假模型按会话给出脚本。

import json
from pathlib import Path
from typing import Any

from harness.adapters.fake import FakeAdapter
from harness.models import EventType
from harness.proposals import delivery_turn, product_spec, review_turn
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem

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
        # 质检：第一轮先问工程，得到回答以后提交缺陷记录；第二轮核验新的交付
        "quality": [
            ModelResponse(output=[
                _call("ask-q", "ask", recipient="engineering", question="检查项覆盖了换行吗？",
                      background="缺陷记录之前核对", expected="结论"),
            ]),
            review_turn("rework_engineering", "换行没有被检查项覆盖", checks={"smoke": 0},
                        defects=[{"severity": "major", "summary": "换行没有被检查项覆盖"}]),
            review_turn("release", "新的交付已经覆盖换行", checks={"smoke": 0}),
        ],
    }
    adapter = FakeAdapter(scripts)
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo")

    system.activate_once(run_id)   # 产品：产品要求
    system.activate_once(run_id)   # 工程：交付，并回问质检
    assert system.project(run_id).phase == "QUALITY", system.project(run_id).error

    # AC9：质检分支的请求里只有问题与背景的事实部分（质检还没有下结论）
    branch_calls = _quality_branch_calls(adapter)
    assert branch_calls, "质检的分支没有发出请求"
    branch_text = _text(branch_calls[0])
    assert QUESTION_FACTS in branch_text
    assert QUESTION_EXPLANATION not in branch_text

    system.activate_once(run_id)   # 质检第一轮：先问工程，拿到回答以后提交缺陷记录
    assert system.project(run_id).phase == "ENGINEERING", system.project(run_id).error

    quality_calls = _quality_calls(adapter)
    assert len(quality_calls) == 2, quality_calls

    # 质检的第一轮请求：交付说明里没有解释部分（summary 属于解释部分）
    first = _text(quality_calls[0])
    assert FIRST_SUMMARY not in first, first

    # 质检第二轮请求：工具结果与历史里的问答记录都只有回答的事实部分
    second = _text(quality_calls[1])
    assert ANSWER_FACTS in second
    assert ANSWER_EXPLANATION not in second

    # 质检提交缺陷记录以后，工程再问质检：质检分支的请求里有解释部分
    system.activate_once(run_id)   # 工程：再问质检并提交新的交付
    assert system.project(run_id).phase == "QUALITY", system.project(run_id).error
    branch_calls = _quality_branch_calls(adapter)
    assert len(branch_calls) == 2, branch_calls
    branch_text = _text(branch_calls[1])
    # 解释部分进入它之后的请求：工程在问答里的解释（交付说明此时已不可见）
    assert ANSWER_EXPLANATION in branch_text, branch_text

    # 质检核验新的交付：解释部分重新藏起来
    system.activate_once(run_id)   # 质检：核验新的交付
    quality_calls = _quality_calls(adapter)
    assert len(quality_calls) == 3, quality_calls
    third = _text(quality_calls[2])
    assert SECOND_SUMMARY not in third, third
    assert FIRST_SUMMARY not in third, third
    assert ANSWER_EXPLANATION not in third, third

    assert system.project(run_id).phase == "DONE"
    reviews = [event for event in system.store.list_events(run_id) if event.type == EventType.QA_SUBMITTED]
    assert len(reviews) == 2
