# 嵌套询问与询问链（工单 #473，三部门的循环结构第 4.4 节）：
# 询问分支里可以再询问其他部门（含回问链上已有的部门），回问在被问部门那里另开一个分支；
# 询问链的层数上限是规则参数 organization.ask_chain_max_depth，默认 3；
# 超过层数时工具许可拒绝这次调用，原因写明链已有几层与上限是多少。
#
# 只跑真实代码，不使用 mock：假模型按会话给出脚本。

import json
from pathlib import Path
from typing import Any

from harness import adjudication
from harness.adapters.fake import FakeAdapter
from harness.definitions import DEFINITIONS
from harness.models import EventType
from harness.proposals import delivery_turn, product_spec, review_turn
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.tests.helpers import explore_turn, quality_turns


def _call(identity: str, name: str, **args: Any) -> dict[str, Any]:
    return {
        "id": identity,
        "call_id": identity,
        "type": "function_call",
        "name": name,
        "arguments": json.dumps(args),
    }


def _ask(identity: str, recipient: str, question: str) -> ModelResponse:
    return ModelResponse(output=[
        _call(identity, "ask", recipient=recipient, question=question,
              background="需要澄清", expected="答复"),
    ])


def _answer(identity: str, text: str) -> ModelResponse:
    return ModelResponse(output=[_call(identity, "answer", answer=text)])


def _events(system, run_id: str, kind: EventType) -> list[Any]:
    return [event for event in system.store.list_events(run_id) if event.type == kind]


def _definitions_with_chain_limit(depth: int):
    # 规则登记里的层数上限改成别的取值：上限从定义读取，不写死在代码里（工单 #473）
    rule = DEFINITIONS.rule("organization.ask_chain_max_depth")
    changed = rule.model_copy(update={"value": depth})
    rules = {**DEFINITIONS.rules, "organization.ask_chain_max_depth": changed}
    return DEFINITIONS.model_copy(update={"rules": rules})


def test_the_nested_ask_answers_the_outer_branch_and_the_run_continues(tmp_path: Path):
    # AC1: 工程询问产品，产品的分支回问工程，工程另开一个分支回答；产品回答，工程收到回答并接着工作。
    # 不出现互相等待：链一层层收回来，两个分支各自结束。
    scripts = {
        "product": [product_spec()],
        "engineering": [
            _ask("ask-1", "product", "输出要不要大写？"),
            delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1].upper())\n"}),
        ],
        # 产品分支：先回问工程（第二层），工程回答以后产品自己回答
        "product:ask": [
            _ask("ask-2", "engineering", "大写以后检查脚本要改吗？"),
            _answer("ans-1", "检查脚本不用改。"),
        ],
        # 工程为回问另开的分支（第二层的分支）
        "engineering:ask": [
            _answer("ans-2", "不用改。"),
        ],
        # 质检的脚本：预测性探索与核验各一轮（工单 #557）
        "quality": [explore_turn(), review_turn("release", "valid uppercase implementation")],
    }
    adapter = FakeAdapter(scripts)
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)

    projection = system.project(run_id)
    assert projection.status == "done", projection.error
    assert projection.status == "done"

    started = _events(system, run_id, EventType.ASK_STARTED)
    answered = _events(system, run_id, EventType.ASK_ANSWERED)
    # 链上两层：工程问产品、产品回问工程
    assert len(started) == 2
    assert len(answered) == 2
    assert all(event.payload["status"] == "answered" for event in answered)
    # 链收干净了：没有还没回答的询问
    assert projection.ask_stack == []
    assert projection.active_ask is None
    # 链从里往外收：内层的回答先到
    assert answered[0].session_id == started[1].payload["branch_session_id"]
    assert answered[1].session_id == started[0].payload["branch_session_id"]
    # 交付与放行照常发生
    assert _events(system, run_id, EventType.DELIVERY_ACCEPTED)
    assert _events(system, run_id, EventType.QA_SUBMITTED)


def test_the_three_layer_chain_answers_and_refuses_the_fourth_layer(tmp_path: Path):
    # AC2: 质检询问工程、工程询问产品、产品再询问质检，三层都得到回答；
    # 再加一层时被拒绝，工具结果写明层数与上限。
    scripts = {
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [
            _ask("ask-1", "engineering", "检查项覆盖了回问吗？"),
            # 预测性探索那一轮没有交付可以核验，提交的结论被拒绝（工单 #557）
            explore_turn(),
            review_turn("release", "ok"),
        ],
        # 工程在分支里回问产品（第二层）
        "engineering:ask": [
            _ask("ask-2", "product", "规格要跟着改吗？"),
            _answer("ans-1", "规格不用改。"),
        ],
        # 产品在分支里再问质检（第三层）
        "product:ask": [
            _ask("ask-3", "quality", "放行标准按哪一份？"),
            _answer("ans-2", "按当前合同。"),
        ],
        # 质检在第三层的分支里再问一层：被拒绝，随后自己回答
        "quality:ask": [
            _ask("ask-4", "engineering", "还能再问一层吗？"),
            _answer("ans-3", "这是链上的第三层。"),
        ],
    }
    adapter = FakeAdapter(scripts)
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)

    projection = system.project(run_id)
    assert projection.status == "done", projection.error

    started = _events(system, run_id, EventType.ASK_STARTED)
    answered = _events(system, run_id, EventType.ASK_ANSWERED)
    # 三层都开出来并得到回答；第四层没有被开出来
    assert len(started) == 3
    assert len(answered) == 3
    assert all(event.payload["status"] == "answered" for event in answered)
    assert projection.ask_stack == []

    # 第四层的那次调用被工具许可拒绝，结果写明链已有几层与上限是多少
    refused = [event for event in _events(system, run_id, EventType.TOOL_CALLED)
               if event.payload.get("name") == "ask" and event.payload.get("ok") is False]
    assert len(refused) == 1
    reason = refused[0].payload.get("error") or ""
    assert "已有 3 层" in reason
    assert "上限是 3 层" in reason


def test_the_chain_limit_is_read_from_the_rule_registry(tmp_path: Path, monkeypatch):
    # AC3: 把 organization.ask_chain_max_depth 改为 2 以后，同一场景在第三层被拒绝
    monkeypatch.setattr(adjudication, "DEFINITIONS", _definitions_with_chain_limit(2))
    assert adjudication.ask_chain_max_depth() == 2

    scripts = {
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [
            _ask("ask-1", "engineering", "检查项覆盖了回问吗？"),
            # 预测性探索那一轮没有交付可以核验，提交的结论被拒绝（工单 #557）
            explore_turn(),
            review_turn("release", "ok"),
        ],
        "engineering:ask": [
            _ask("ask-2", "product", "规格要跟着改吗？"),
            _answer("ans-1", "规格不用改。"),
        ],
        # 产品在分支里再问质检：第三层被拒绝，随后自己回答
        "product:ask": [
            _ask("ask-3", "quality", "放行标准按哪一份？"),
            _answer("ans-2", "按当前合同。"),
        ],
    }
    adapter = FakeAdapter(scripts)
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)

    assert system.project(run_id).status == "done", system.project(run_id).error
    # 只有两层开出来，第三层被拒绝
    assert len(_events(system, run_id, EventType.ASK_STARTED)) == 2
    refused = [event for event in _events(system, run_id, EventType.TOOL_CALLED)
               if event.payload.get("name") == "ask" and event.payload.get("ok") is False]
    assert len(refused) == 1
    reason = refused[0].payload.get("error") or ""
    assert "已有 2 层" in reason
    assert "上限是 2 层" in reason


def test_the_nested_branch_steps_are_charged_to_the_first_asker(tmp_path: Path):
    # AC5: 嵌套分支的用量计入最初的提问方。提问方四步的预算：它自己的一步开分支，
    # 链上的三步（产品分支两步、嵌套分支一步）算在它头上，它自己没有余步交付。
    from harness.engine import StepLimits

    scripts = {
        "product": [product_spec()],
        "engineering": [
            _ask("ask-1", "product", "输出要不要大写？"),
            delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1].upper())\n"}),
        ],
        "product:ask": [
            _ask("ask-2", "engineering", "大写以后检查脚本要改吗？"),
            _answer("ans-1", "检查脚本不用改。"),
        ],
        "engineering:ask": [
            _answer("ans-2", "不用改。"),
        ],
        # 质检的脚本：预测性探索与核验各一轮（工单 #557）
        "quality": [explore_turn(), review_turn("release", "valid uppercase implementation")],
    }
    adapter = FakeAdapter(scripts)
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=StepLimits(max_model_steps=4))
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)

    events = system.store.list_events(run_id)
    requests = [event for event in events if event.type == EventType.MODEL_REQUESTED]
    # 链上的步数计入提问方：提问方的四步预算里，提问方自己一步、产品分支两步、嵌套分支一步。
    # 同时运行的质检会话不在这个预算里（工单 #557），因此这里只数提问方与链上的分支。
    chain = [event for event in requests
             if (event.session_id or "").startswith("ses_ask_") or event.department == "engineering"]
    assert len(chain) == 4
    # 链上的步数计入提问方：提问方没有余步交付，事项以步数用完暂停
    assert not [event for event in events if event.type == EventType.DELIVERY_ACCEPTED]
    projection = system.project(run_id)
    assert projection.status == "paused"
    assert projection.stop_reason == "model_steps_exhausted"


def test_the_nested_branch_limit_does_not_exceed_the_previous_remaining(tmp_path: Path):
    # AC5: 嵌套分支的上限按上一层的剩余量继承：上一层只剩一步时，嵌套分支只有一步。
    from harness.engine import StepLimits

    scripts = {
        "product": [product_spec()],
        "engineering": [
            _ask("ask-1", "product", "输出要不要大写？"),
            delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1].upper())\n"}),
        ],
        # 产品分支回问工程：它自己的一步用掉以后，嵌套分支只剩一步
        "product:ask": [
            _ask("ask-2", "engineering", "大写以后检查脚本要改吗？"),
            _answer("ans-1", "检查脚本不用改。"),
        ],
        # 嵌套分支要两步才能回答（先回一句文字，再提交回答）
        "engineering:ask": [
            ModelResponse(output=[{"id": "msg-1", "type": "message", "role": "assistant",
                                   "content": [{"type": "output_text", "text": "我看一下。"}]}]),
            _answer("ans-2", "不用改。"),
        ],
        "quality": [review_turn("release", "valid uppercase implementation")],
    }
    adapter = FakeAdapter(scripts)
    # 提问方三步：主线一步开分支，分支两步（回问与回答），嵌套分支只剩一步
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=StepLimits(max_model_steps=3))
    run_id = system.create_run("build echo")
    system.run_until_stop(run_id)

    events = system.store.list_events(run_id)
    nested = [event for event in events
              if event.type == EventType.MODEL_REQUESTED and event.session_id.startswith("ses_ask_eng")]
    # 嵌套分支只有一步可用：第二步没有发生
    assert len(nested) == 1
    answered = [event for event in events if event.type == EventType.ASK_ANSWERED]
    nested_answer = next(event for event in answered
                         if event.payload.get("branch_session_id") is None
                         and event.session_id.startswith("ses_ask_eng"))
    assert nested_answer.payload["status"] == "unable"
    assert "step limit" in nested_answer.payload["reason"]
