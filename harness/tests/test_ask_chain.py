# 嵌套询问与询问链（工单 #473，ADR-0039）：
# 询问分支里可以再询问其他部门（含回问链上已有的部门），回问在被问部门那里另开一个分支；
# 询问链的层数上限是规则参数 organization.ask_chain_max_depth，默认 3；
# 超过层数时工具许可拒绝这次调用，原因写明链已有几层与上限是多少。
#
# 只跑真实代码，不使用 mock：假模型按会话给出脚本。

import json
from pathlib import Path
from typing import Any

from harness.adapters.fake import FakeAdapter
from harness.adjudication import ask_chain_decision, ask_chain_max_depth, tool_permission
from harness.definitions import DEFINITIONS
from harness.models import EventType, RunProjection
from harness.proposals import delivery_turn, product_spec, review_turn
from harness.providers.call import ModelResponse
from harness.recording import WorkBasis
from harness.runtime import LoopSystem


def _call(identity: str, name: str, **args: Any) -> dict[str, Any]:
    return {
        "id": identity,
        "call_id": identity,
        "type": "function_call",
        "name": name,
        "arguments": json.dumps(args),
    }


def test_the_nested_ask_answers_the_outer_branch_and_the_run_continues(tmp_path: Path):
    # 工程询问产品，产品的分支回问工程，工程另开一个分支回答；产品回答，工程收到回答并接着工作。
    # 不出现互相等待：两个分支各自结束，询问链一层层收回来。
    scripts = {
        "product": [product_spec()],
        "engineering": [
            ModelResponse(output=[
                _call("ask-1", "ask", recipient="product", question="输出要不要大写？",
                      background="需要澄清", expected="规格修订"),
            ]),
            delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1].upper())\n"}),
        ],
        # 产品分支：先回问工程（第二层），工程回答以后产品自己回答
        "product:ask": [
            ModelResponse(output=[
                _call("ask-2", "ask", recipient="engineering", question="大写以后检查脚本要改吗？",
                      background="回问链上已有的部门", expected="改动范围"),
            ]),
            ModelResponse(output=[
                _call("ans-1", "answer", answer="检查脚本不用改。"),
            ]),
        ],
        # 工程为回问另开的分支（第三层）
        "engineering:ask": [
            ModelResponse(output=[
                _call("ans-2", "answer", answer="不用改。"),
            ]),
        ],
        "quality": [review_turn("release", "valid uppercase implementation")],
    }
    adapter = FakeAdapter(scripts)
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)

    projection = system.project(run_id)
    assert projection.outcome == "done", projection.error
    assert projection.phase == "DONE"

    events = system.store.list_events(run_id)
    started = [e for e in events if e.type == EventType.ASK_STARTED]
    answered = [e for e in events if e.type == EventType.ASK_ANSWERED]
    # 链上两层：工程问产品、产品回问工程
    assert len(started) == 2
    assert len(answered) == 2
    # 链收干净了：没有还没回答的询问
    assert projection.ask_stack == []
    assert projection.active_ask is None
    # 交付与放行照常发生
    assert EventType.DELIVERY_ACCEPTED in [e.type for e in events]
    assert EventType.QA_SUBMITTED in [e.type for e in events]


def test_the_ask_chain_decision_follows_the_rule_parameter():
    # 层数上限从规则登记读，不写死在代码里
    assert ask_chain_max_depth() == DEFINITIONS.rule_value("organization.ask_chain_max_depth")
    assert ask_chain_max_depth() == 3

    # 链上还没有询问时可以问第一层
    assert ask_chain_decision(0, 3) == (True, None)
    # 第三层仍然可以（上限 3）
    assert ask_chain_decision(2, 3) == (True, None)
    # 第四层被拒绝，原因写明链已有几层与上限是多少
    allowed, reason = ask_chain_decision(3, 3)
    assert allowed is False
    assert reason is not None and "3" in reason and "上限是 3 层" in reason
    # 上限改成 2 时第三层被拒绝
    assert ask_chain_decision(1, 2) == (True, None)
    assert ask_chain_decision(2, 2)[0] is False


def test_the_nested_ask_is_rejected_at_the_chain_limit():
    # 分支里的回问：层数没有超过上限时允许，超过时工具许可拒绝这次调用
    from harness.actions import WorkspaceFacts

    def projection_at(depth: int) -> RunProjection:
        return RunProjection(
            run_id="run_test",
            phase="ENGINEERING",
            ask_stack=[{"requester": "product", "recipient": "engineering",
                        "branch_session_id": f"ses_ask_{index}"} for index in range(depth)],
        )

    allowed = tool_permission(
        projection_at(1),
        {"name": "ask", "args": {"recipient": "quality", "question": "还能问吗？"}},
        department="engineering",
        guidance_only=False,
        basis=WorkBasis.current(projection_at(1), "engineering"),
        aborted=False,
        facts=WorkspaceFacts(),
    )
    assert allowed.allowed

    limit = ask_chain_max_depth()
    over = projection_at(limit)
    denied = tool_permission(
        over,
        {"name": "ask", "args": {"recipient": "quality", "question": "还能问吗？"}},
        department="engineering",
        guidance_only=False,
        basis=WorkBasis.current(over, "engineering"),
        aborted=False,
        facts=WorkspaceFacts(),
    )
    assert denied.allowed is False
    assert denied.reason is not None
    assert f"上限是 {limit} 层" in denied.reason
