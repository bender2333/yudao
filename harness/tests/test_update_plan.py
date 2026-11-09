# 更新计划是记录类的主机工具（工作过程的任务与动作标题设计说明「任务」「接口」「边界与范围」，工单 #1660）：
# 每次整份替换，每条一句话加状态（待做、进行中、完成）；事情分几部分时才用，尽量与下一个动作在同一步发出。
# 它不拦任何工作：格式错误（空条目、未知状态）作为工具结果返回，不检查条目数量，不拒绝多条进行中。
# 它不是提案，不经裁决，不算进展事实（循环与收敛设计说明「收敛的检测」），不计入收敛的调用标识，
# 和别的工具调用一样计入步数与用量；只留在写下它的那个角色的历史里，别的角色看不到。
#
# 层：模块层（一个数据目录、几个部门各一轮工作；模型回答由 FakeAdapter 给出，写入与检查真的执行）。
# 守 R2（记录类主机工具不经过动作的缝、不进收敛判定、不改变事项的流转与裁决）与
# R3（计划写成普通的工具调用记录、页面读得到；格式错误与条目多少都不拦工作）。

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from harness import loops
from harness.adapters.fake import FakeAdapter
from harness.definitions import DEFINITIONS, DEFINITIONS_DIR, load_definitions, thaw
from harness.failure_list import tool_result
from harness.models import EventType, json_dumps
from harness.projection import replay_events
from harness.proposals import ask_turn, delivery_turn, product_spec
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.tests.helpers import quality_turns

PLAN = "update_plan"
FORMS = ("several_roles_direct", "single_role_direct")
# 计划里那一句话：它只应出现在写下它的那个角色的请求里
SENTENCE = "把交付拆成写代码与跑检查两部分"


def _call(identity: str, name: str, **args: Any) -> dict[str, Any]:
    return {"id": identity, "call_id": identity, "type": "function_call", "name": name,
            "arguments": json_dumps(args)}


def _response(*items: dict[str, Any]) -> ModelResponse:
    return ModelResponse(output=list(items))


def _plan(*entries: dict[str, Any], identity: str = "plan-1") -> dict[str, Any]:
    return _call(identity, PLAN, plan=list(entries))


def _called(system: LoopSystem, run_id: str, name: str | None = None) -> list[Any]:
    return [event for event in system.store.list_events(run_id)
            if event.type == EventType.TOOL_CALLED
            and (name is None or (event.payload or {}).get("name") == name)]


def _spec_args() -> dict[str, Any]:
    # 与假模型对提交类提案的写法一致：工具名本身说明种类，参数里不带 kind
    return {key: value for key, value in product_spec().items() if key != "kind"}


def test_every_release_defines_the_same_record_host_tool():
    # R2（验收第 6、7 条）：默认与两份形态各自是一份完整的定义，这一项三处逐字相同；
    # 它是主机工具，没有动作类别、没有提案，也没有动作合同的元数据（不经过动作的缝）
    paths = [DEFINITIONS_DIR / "tools.json",
             *(DEFINITIONS_DIR / "forms" / form / "tools.json" for form in FORMS)]
    definitions = [json.loads(path.read_text(encoding="utf-8"))[PLAN] for path in paths]
    assert definitions[0] == definitions[1] == definitions[2]
    tool = DEFINITIONS.tools[PLAN]
    assert (tool.kind, tool.action, tool.proposal, tool.verification, tool.cancellable) == (
        "host", None, None, None, None)
    # 记录形状按设计说明：整份计划一项，每条一句话加状态（待做、进行中、完成）
    schema = json.loads(json_dumps(thaw(tool.parameters)))
    assert schema["required"] == ["plan"] and schema["additionalProperties"] is False
    entry = schema["properties"]["plan"]["items"]
    assert entry["required"] == ["content", "status"]
    assert entry["properties"]["status"]["enum"] == ["pending", "in_progress", "completed"]
    assert entry["properties"]["content"]["type"] == "string"


def test_every_own_role_and_every_work_item_list_offers_the_plan():
    # R2（验收第 6 条）：每个自有角色都有——默认与两份形态的角色定义、变更与建档两种事项的工具清单
    releases = [DEFINITIONS,
                *(load_definitions(DEFINITIONS_DIR / "forms" / form) for form in FORMS)]
    for release in releases:
        for department in release.departments:
            assert PLAN in release.roles[department].tools, department
        for kind, work in release.work_items.kinds.items():
            for department, item in work.departments.items():
                assert PLAN in item.tools, (kind, department)
                assert PLAN in release.tools_for(department, kind), (kind, department)


def test_the_plan_is_an_ordinary_tool_call_in_the_same_step_as_the_next_action(data_dir):
    # R3（验收第 1 条）：结果写成普通的工具调用记录，没有新增事件种类；
    # 与下一个动作在同一步发出时，两个动作同属这一步（计划不单独占一步）
    entries = [{"content": SENTENCE, "status": "in_progress"},
               {"content": "跑检查并提交交付", "status": "pending"}]
    system = LoopSystem.for_testing(data_dir, FakeAdapter({
        "product": [product_spec()],
        "engineering": [
            lambda call: _response(
                _plan(*entries),
                _call("write-1", "write_file", path="src/echo.py",
                      content="import sys\nprint(sys.argv[1])\n")),
            delivery_turn(),
        ],
        "quality": quality_turns("release"),
    }))
    run_id = system.create_run("build echo")
    try:
        projection = system.run_until_stop(run_id)
        assert projection.status == "done", projection.error
        [plan] = _called(system, run_id, PLAN)
        assert plan.payload["ok"] is True and plan.payload["error"] is None
        assert plan.payload["args"] == {"plan": entries}
        assert tool_result(plan)["output"] == {"plan": entries}
        write = next(event for event in _called(system, run_id, "write_file")
                     if event.payload["id"] == "write-1")
        assert plan.payload["step_id"] == write.payload["step_id"]
        # 普通工具调用记录：这次调用只有工具开始与工具结果两种事件，没有别的种类
        identity = plan.payload["id"]
        assert {event.type for event in system.store.list_events(run_id)
                if (event.payload or {}).get("id") == identity} == {
                    EventType.TOOL_STARTED, EventType.TOOL_CALLED}
    finally:
        system.close()


def test_a_malformed_plan_is_a_tool_result_and_the_step_goes_on(data_dir):
    # R2（验收第 2 条）：格式错误作为工具结果返回，同一步的其他动作照常；
    # 条目不检查数量，多条进行中也接受——30 条、两条进行中的一份计划原样记下
    many = [{"content": f"第 {index} 部分", "status": "in_progress" if index < 2 else "pending"}
            for index in range(30)]
    system = LoopSystem.for_testing(data_dir, FakeAdapter({
        "product": [
            lambda call: _response(
                _plan({"content": "   ", "status": "pending"}, identity="plan-empty"),
                _plan({"content": "写代码", "status": "doing"}, identity="plan-status"),
                _plan(*many, identity="plan-many"),
                _call("spec-1", "submit_product_spec", **_spec_args())),
        ],
        "engineering": [delivery_turn()],
        "quality": quality_turns("release"),
    }))
    run_id = system.create_run("build echo")
    try:
        projection = system.run_until_stop(run_id)
        assert projection.product_spec is not None, projection.error
        assert projection.status == "done", projection.error
        results = {event.payload["id"]: event.payload for event in _called(system, run_id, PLAN)}
        # 空条目与未知状态都是工具结果里的错误，位置写清是哪一条的哪一项
        assert results["plan-empty"]["ok"] is False and "content" in results["plan-empty"]["error"]
        assert results["plan-status"]["ok"] is False and "status" in results["plan-status"]["error"]
        # 其余情况都接受：条目数量不检查，多条进行中不拒绝
        assert results["plan-many"]["ok"] is True and results["plan-many"]["error"] is None
        [many_event] = [event for event in _called(system, run_id, PLAN)
                        if event.payload["id"] == "plan-many"]
        assert tool_result(many_event)["output"] == {"plan": many}
    finally:
        system.close()


def test_an_ask_branch_offers_and_records_the_plan(data_dir):
    # R3（验收第 1 条）：询问分支里也能用——分支的请求里带着这个工具，调用照常写成工具调用记录
    branch_calls: list[Any] = []

    def branch(call: Any) -> ModelResponse:
        branch_calls.append(call)
        return _response(
            _plan({"content": "先读一问里的事实", "status": "completed"},
                  {"content": "再给出答法", "status": "in_progress"}, identity="plan-branch"),
            _call("ans-1", "answer", answer="空输入打印一行空内容。"))

    system = LoopSystem.for_testing(data_dir, FakeAdapter({
        "product": [product_spec()],
        "engineering": [
            ask_turn(recipient="product", question="空输入打印什么？"),
            delivery_turn(),
        ],
        "product:ask": [branch],
        "quality": quality_turns("release"),
    }))
    run_id = system.create_run("build echo")
    try:
        projection = system.run_until_stop(run_id)
        assert projection.status == "done", projection.error
        assert len(branch_calls) == 1
        assert PLAN in {item["name"] for item in branch_calls[0].tools}
        [plan] = _called(system, run_id, PLAN)
        assert plan.session_id.startswith("ses_ask"), plan.session_id
        assert plan.payload["ok"] is True and plan.payload["error"] is None
    finally:
        system.close()


def test_writing_the_same_plan_again_is_no_oscillation_and_no_fact(data_dir):
    # R2（验收第 4 条）：反复写同一份计划不触发震荡判定，也不产生进展事实；
    # 三步计划各占一步、与别的工具调用一样计入步数与用量。对照：同样三次相同的调用若是动作工具即为震荡
    plan_call = lambda identity: _response(
        _plan({"content": SENTENCE, "status": "in_progress"}, identity=identity))
    system = LoopSystem.for_testing(data_dir, FakeAdapter({
        "product": [product_spec()],
        "engineering": [
            lambda call: plan_call("plan-1"),
            lambda call: plan_call("plan-2"),
            lambda call: plan_call("plan-3"),
            *[lambda call, path=path: _response(
                _call(f"read-{path}", "read_file", path=path)) for path in
              ("a.py", "b.py", "c.py", "d.py")],
            delivery_turn(),
        ],
        "quality": quality_turns("release"),
    }))
    run_id = system.create_run("build echo")
    try:
        projection = system.run_until_stop(run_id)
        assert projection.status == "done", projection.error
        events = system.store.list_events(run_id)
        tree = loops.build_loop_tree(events)
        activation = next(item for item in tree.activations if item.department == "engineering")
        # 三步计划各是一个工作步，与别的步骤一样计入步数与用量
        assert [step.step_id for step in activation.steps] == [1, 2, 3, 4, 5, 6, 7, 8]
        assert len([event for event in events if event.type == EventType.MODEL_REQUESTED]) >= 8
        # 计划不产生被接纳的事实：三个计划步没有事实，也没有算进调用标识
        plans = [step for step in activation.steps if step.step_id <= 3]
        assert [step.facts for step in plans] == [(), (), ()]
        assert [step.calls for step in plans] == [(), (), ()]
        # 反复写同一份计划不是震荡；窗口由这次运行时冻结的参数给出
        state = loops.step_state(activation.steps, window=tree.parameters[loops.STEP_WINDOW],
                                 repeat=tree.parameters[loops.STEP_REPEAT], stop_reason=None)
        assert state == loops.CONVERGING, state
        # 对照：同样的三次相同调用若是一个动作工具（这里换成 bash），就是震荡
        renamed = [
            replace(event, payload={**event.payload, "name": "bash", "args": {"command": "cat same.py"}})
            if event.type == EventType.TOOL_CALLED and (event.payload or {}).get("name") == PLAN
            else event for event in events]
        control = next(item for item in loops.build_loop_tree(renamed).activations
                       if item.department == "engineering")
        assert loops.step_state(control.steps, window=tree.parameters[loops.STEP_WINDOW],
                                repeat=tree.parameters[loops.STEP_REPEAT],
                                stop_reason=None) == loops.OSCILLATING
        # 与别的工具调用一样计入：工具结果的计数里有这三条计划调用
        assert projection.tool_count == len([
            event for event in _called(system, run_id)
            if (event.payload or {}).get("name") != "provider_usage"])
    finally:
        system.close()


def test_the_other_departments_never_read_the_plan(data_dir):
    # R3（验收第 5 条）：工程写的计划不出现在质检和产品的模型请求里，只留在工程自己的历史里
    system = LoopSystem.for_testing(data_dir, FakeAdapter({
        "product": [product_spec()],
        "engineering": [
            lambda call: _response(_plan({"content": SENTENCE, "status": "in_progress"})),
            delivery_turn(),
        ],
        "quality": quality_turns("release"),
    }))
    run_id = system.create_run("build echo")
    try:
        assert system.run_until_stop(run_id).status == "done"
        invocations = system.test_adapter.invocations
        engineering = [call for call in invocations if call.department == "engineering"]
        others = [call for call in invocations if call.department != "engineering"]
        assert engineering and others
        assert any(SENTENCE in json_dumps(call.input_items) for call in engineering)
        assert not any(SENTENCE in json_dumps(call.input_items) for call in others)
    finally:
        system.close()


def test_the_same_events_without_the_plan_calls_keep_the_flow_the_adjudication_and_the_boundary(data_dir):
    # R2（验收第 3 条）：同一组事件去掉更新计划的调用以后，事项的流转、裁决与边界的结果不变；
    # 去掉的只是工具调用的计数（计划与别的工具调用一样计入）
    system = LoopSystem.for_testing(data_dir, FakeAdapter({
        "product": [lambda call: _response(
            _plan({"content": "先写要求", "status": "in_progress"}, identity="plan-product"),
            _call("spec-1", "submit_product_spec", **_spec_args()))],
        "engineering": [
            lambda call: _response(_plan({"content": SENTENCE, "status": "in_progress"})),
            delivery_turn(),
        ],
        "quality": quality_turns("release"),
    }))
    run_id = system.create_run("build echo")
    try:
        assert system.run_until_stop(run_id).status == "done"
        events = system.store.list_events(run_id)
        without_plan = [event for event in events
                        if not (event.type in (EventType.TOOL_STARTED, EventType.TOOL_CALLED)
                                and (event.payload or {}).get("name") == PLAN)]
        assert len(without_plan) == len(events) - 4  # 两次计划调用，各一条开始与一条结果
        expected = system.project(run_id).canonical_state()
        replayed = replay_events(without_plan).canonical_state()
        # 只有工具调用的计数不同：计划与别的工具调用一样计入
        assert expected.pop("tool_count") == replayed.pop("tool_count") + 2
        assert replayed == expected
    finally:
        system.close()
