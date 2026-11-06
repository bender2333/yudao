# 骨架接得住第二种路由：任务池跑完一个事项（工单 #864；骨架与应用 docs/design/skeleton-and-application.md「其他路由：骨架要满足的条件」「证明」；
# 总图第四节「路由」缝）。
#
# 证明的样子：同一副骨架（写入口、裁决、边界、薄驱动、最小投影、定义加载）接上另一套应用——
# `second_routing.TaskPool` 与它的收紧检查 `TaskPoolTightening`，配上只在测试目录里的那一整份定义
# （`task_pool_definitions/`，用 `load_definitions(<测试目录>)` 加载）。骨架的模块一行不改（契约模块按
# 工单 #1164 补了可选的读事件入口，其余照旧），产品的 `harness/definitions/` 一个条目也不加，产品代码不导入它们。
#
# 这个文件查五件事：
# 1. 假模型跑完一个事项：发布任务、指派、完成、打回各至少一次；事项以**它自己那份定义里声明的**结束原因结束
#    （`pool_drained`，内核的停止原因清单里没有它）；
# 2. 完成一件事的部门不能自己给这件事结论（基础规则 3，由路由的收紧检查判）；
# 3. 路由自己的应用事件种类按 #828 的登记方式登记，经写入口写入、重放读得回来，骨架事件的登记表不变；
# 4. 定义只在测试目录里，产品的定义与成果驱动的合同没有被改动；
# 5. 产品代码不导入它。
# 写入口按事项所用的那份定义核对停止原因的拒绝与放行（工单 #1165）由 `kernel/test_every_stop_has_reason.py` 守着。
#
# 模块级 `DEFINITIONS` 不替换（工单 #1165）：停止原因与部门由薄驱动交给写入口，写入口按交进来的那份定义核对；
# 只有组装处（`runtime.py`）按组织定义里的名称接上路由那一步仍按模块加载的定义走。
#
# 层：模块层（一个事项的真实运行：事件库、工作区与假模型）。守 R2（各缝的交换字段与版本：路由按组织定义的
# 名称接上、它自己的一份定义由它自己校验、骨架只认得通用的一种成果接纳事件）与 R1（每个 run 以封闭清单里的
# 原因结束：这里的那份清单是路由自己声明的那份）。
#
# 先后由事件决定，不用时长赌：这个事项一轮一个部门，薄驱动按路由的指派依次开始；
# 假模型的脚本按部门给出每一步读的是前面写下的事件。

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from harness import kernel_events, routing_contract
from harness import write_path as write_path_module
from harness.adapters.fake import FakeAdapter
from harness.definitions import DEFAULT_FORM
from harness.definitions import DEFINITIONS as PRODUCT_DEFINITIONS
from harness.definitions import DefinitionError, load_definitions
from harness.event_store import run_stream
from harness.kernel_events import json_dumps
from harness.models import ArtifactRef, EventType
from harness.projection import replay_events
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.tightening import WATCHED_OUTPUTS
from harness.tests import second_routing, task_pool_assembly
from harness.validation import TightenRequest

REPO_ROOT = Path(__file__).resolve().parents[2]
POOL_DEFINITIONS = second_routing.DEFINITIONS_DIR

TASK = {"title": "README 的用法一节补上退出码说明"}

# 假模型的脚本：按部门给出。发一次任务、完成两次（中间被打回一次）、给一次打回与一次
# 接纳的结论。路由自己的提议方式不是产品的提交类工具，所以答复直接写成函数调用（FakeAdapter 的脚本项可以是
# 返回 ModelResponse 的函数）
SCRIPT = {
    "product": [[("submit_task", TASK)]],
    "engineering": [
        [("complete_task", {"summary": "补了用法一节"})],
        [("complete_task", {"summary": "补了退出码说明"})],
    ],
    "quality": [
        [("judge_task", {"verdict": "return", "reason": "用法一节没有写退出码"})],
        [("judge_task", {"verdict": "accept", "reason": "与任务要求一致"})],
    ],
}


class _FakeStore:
    # 只读事件库的替身：组装处接上这个路由时只要事件库有这个读法（工单 #1164），这里不跑任何事项
    def list_events(self, run_id: str) -> list[Any]:
        return []


def _turn(calls: list[list[Any]]):
    # 一次回答里的一组函数调用：名字与参数由脚本给出，调用身份按激活与步骤编，不同部门的身份不重复
    def turn(call):
        output = []
        for index, (name, arguments) in enumerate(calls, start=1):
            identity = f"call-{call.activation_id}-{call.step_id}-{index}"
            output.append({"id": identity, "call_id": identity, "type": "function_call",
                           "name": name, "arguments": json_dumps(arguments)})
        return ModelResponse(output=output)

    return turn


def _script() -> dict[str, list[Any]]:
    return {department: [_turn(calls) for calls in turns] for department, turns in SCRIPT.items()}


def _system(tmp_path: Path, script: dict[str, list[Any]] | None = None) -> tuple[LoopSystem, FakeAdapter]:
    # 实例同时加载两份具名的形态（工单 #1392）：产品的三部门与测试目录里的任务池。每个 run 建的时候
    # 冻结用哪一份，之后停止原因、部门、路由、装配与收紧检查都按那一份；模块级的 DEFINITIONS 不替换
    # （工单 #1165、#1392），组装处按每一份定义里的组织定义 routing 名称接上路由（工单 #825、#1164）
    forms = {
        DEFAULT_FORM: (PRODUCT_DEFINITIONS, WATCHED_OUTPUTS),
        second_routing.ROUTING_NAME: (second_routing.DEFINITIONS, second_routing.TIGHTENING),
    }
    adapter = FakeAdapter(_script() if script is None else script)
    system = LoopSystem.for_testing(tmp_path, adapter, assembly=task_pool_assembly.TaskPoolAssembly(),
                                    forms=forms)
    return system, adapter


def _accepted(events: list[Any]) -> list[dict[str, Any]]:
    return [dict(event.payload) for event in events if event.type == EventType.ARTIFACT_ACCEPTED]


def _parts_of(system: LoopSystem, event: Any) -> list[dict[str, Any]]:
    # 一次请求的上下文清单：各段材料的原文（活动记录的工件）
    return json.loads(system.artifacts.get_for_run(event.payload["run_id"],
                                                   ArtifactRef(**event.payload["parts_ref"])))


def test_a_task_pool_runs_one_item_on_the_skeleton(tmp_path):
    system, _adapter = _system(tmp_path)
    run_id = system.create_run("把 README 的用法一节整理清楚", form=second_routing.ROUTING_NAME)

    projection = system.run_until_stop(run_id)

    events = system.store.list_events(run_id)
    accepted = _accepted(events)
    # 一件任务走完一个来回：发布任务、完成、打回、重做、接纳
    assert [item["artifact_kind"] for item in accepted] == [
        "pool_task", "task_completion", "task_verdict", "task_completion", "task_verdict"]
    published = accepted[0]
    assert published["artifact_issuer"] == "product" and published["title"] == TASK["title"]

    # 指派：路由把池子里的这件任务交给工程的这一轮（路由自己的工作引用，原样交给装配与执行）
    engineering_context = next(event for event in events
                               if event.type == EventType.CONTEXT_ASSEMBLED
                               and event.department == "engineering")
    round_task = next(part["text"] for part in _parts_of(system, engineering_context)
                      if part["source"] == "round_task")
    assert published["task"] in round_task and published["title"] in round_task

    # 完成：两次都是领到任务的部门交的
    completions = [item for item in accepted if item["artifact_kind"] == "task_completion"]
    assert [item["artifact_issuer"] for item in completions] == ["engineering", "engineering"]
    # 打回：结论由另一个部门给，先打回再接纳；评价类成果不是完成它的部门提出的（基础规则 3）
    verdicts = [item for item in accepted if item["artifact_kind"] == "task_verdict"]
    assert [item["verdict"] for item in verdicts] == ["return", "accept"]
    assert {item["artifact_issuer"] for item in verdicts} == {"quality"}
    assert all(item["completion"] in {done["content_hash"] for done in completions} for item in verdicts)

    # 事项以它自己那份定义里声明的结束原因结束
    declared = second_routing.DEFINITIONS.routing_definition().end_reasons
    assert projection.stop_reason == second_routing.ITEM_END_REASON
    assert projection.stop_reason in declared
    assert projection.status == declared[projection.stop_reason].outcome
    # 这条原因不在内核的停止原因清单里：它是那份路由定义版本的封闭清单里的一条
    assert projection.stop_reason not in PRODUCT_DEFINITIONS.stop_reasons
    assert projection.stop_reason not in second_routing.DEFINITIONS.stop_reasons


def test_a_completion_cannot_be_judged_by_the_department_that_completed_it(tmp_path):
    # 基础规则 3「生成者不裁决自己」：路由用自己的方式满足（骨架与应用 docs/design/skeleton-and-application.md「其他路由：骨架要满足的条件」），
    # 这里用这次运行里真实写下的事件折出的池子现状来判，不构造假的池子
    system, _adapter = _system(tmp_path)
    run_id = system.create_run("把 README 的用法一节整理清楚", form=second_routing.ROUTING_NAME)
    system.run_until_stop(run_id)

    events = system.store.list_events(run_id)
    # 第一件任务交上来、还没有结论的那一刻：把结论交到完成它的部门手上
    until_verdict = []
    for event in events:
        if (event.type == EventType.ARTIFACT_ACCEPTED
                and (event.payload or {}).get("artifact_kind") == "task_verdict"):
            break
        until_verdict.append(event)
    judged = {"kind": "task_verdict", "verdict": "accept", "reason": "我自己说做好了"}
    by_author = second_routing.TIGHTENING.submission(TightenRequest(
        department="engineering", state=None, proposal=judged,
        events=tuple(until_verdict), definitions=second_routing.DEFINITIONS))
    assert not by_author.accepted
    assert "cannot judge it" in (by_author.reason or "")

    by_other = second_routing.TIGHTENING.submission(TightenRequest(
        department="quality", state=None, proposal=judged,
        events=tuple(until_verdict), definitions=second_routing.DEFINITIONS))
    assert by_other.accepted and by_other.content is not None
    assert by_other.content["verdict"] == "accept"


def test_the_task_pool_registers_its_own_application_event_kinds(tmp_path):
    #：应用登记自己的事件种类，增加一种不改内核文件
    registered = kernel_events.application_event_types()
    for kind in second_routing.APPLICATION_EVENT_KINDS:
        assert registered.get(kind) == second_routing.APPLICATION
        assert kind not in kernel_events.SKELETON_EVENTS
    # 登记、经写入口写入、重放读得回来：内核的投影不认识这种应用事件，照常跳过，事件还在流里
    system = LoopSystem.for_testing(tmp_path / "events", FakeAdapter([]))
    stream = run_stream("run_task_pool_events")
    system.writes.transact(stream, lambda transaction: transaction.append(
        write_path_module.NewEvent(second_routing.TAKEN_EVENT, state_before="running",
                                   state_after="running", department="engineering",
                                   payload={"task": "task-0000", "department": "engineering"},
                                   actor="system")))
    events = system.store.list_events("run_task_pool_events")
    assert [event.type for event in events] == [second_routing.TAKEN_EVENT]
    assert replay_events(events).stream_version == 1


def test_the_task_pool_definitions_live_only_in_the_test_directory():
    # 它自己的一份定义在测试目录里，用 load_definitions(<测试目录>) 加载（2026-10-28 总架构师补的做法）
    loaded = load_definitions(POOL_DEFINITIONS)
    assert loaded.routing == second_routing.ROUTING_NAME
    assert [item.id for item in loaded.routings.routings] == [second_routing.ROUTING_NAME]
    assert loaded.version == second_routing.DEFINITIONS.version
    # 路由实现按名称接上骨架（组织定义的 routing -> routings.json 的那一条 -> 模块加载时登记的实现）；
    # 这个路由声明了 use_facts，接上时要有事件库可交（工单 #1164），这里给它一个只读事件库的替身
    assert routing_contract.select(loaded.routing, loaded, store=_FakeStore()) is second_routing.ROUTING
    # 产品的定义与成果驱动的合同没有被改动：名称、成果种类与工具都是原来那几样
    assert PRODUCT_DEFINITIONS.routing == "watched_outputs"
    assert [item.id for item in PRODUCT_DEFINITIONS.routings.routings] == ["watched_outputs"]
    assert second_routing.ROUTING_NAME not in {item.id for item in PRODUCT_DEFINITIONS.routings.routings}
    for tool in ("submit_task", "complete_task", "judge_task"):
        assert tool not in PRODUCT_DEFINITIONS.tools
    assert not (REPO_ROOT / "harness" / "definitions").joinpath("task_pool_definitions").exists()


def test_the_routing_rejects_its_own_definition_without_its_end_reason(tmp_path):
    # 内容由路由自己校验：事项结束用的那一条必须声明在这份定义里
    directory = tmp_path / "definitions"
    shutil.copytree(POOL_DEFINITIONS, directory)
    path = directory / "routings.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    reasons = document["routings"][0]["end_reasons"]
    document["routings"][0]["end_reasons"] = {"some_other_reason": reasons[second_routing.ITEM_END_REASON]}
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    declared = load_definitions(directory)

    with pytest.raises(routing_contract.InvalidRoutingDefinition) as raised:
        second_routing.ROUTING.check_definition(declared)
    assert second_routing.ITEM_END_REASON in str(raised.value)
    # 这条路由自己的定义自己是认的
    assert second_routing.ROUTING.check_definition(second_routing.DEFINITIONS) is None
    # 定义文件本身不合法时在加载时就被拒绝（内核核对结构），不是在这一步
    (directory / "routings.json").write_text("{}", encoding="utf-8")
    with pytest.raises(DefinitionError):
        load_definitions(directory)


def test_no_product_code_imports_the_task_pool():
    # 它不进产品：产品的源码里没有这个路由、这个装配与这份定义的名字
    forbidden = ("second_routing", "task_pool_assembly", "task_pool_definitions")
    offenders = sorted(
        str(path.relative_to(REPO_ROOT))
        for path in (REPO_ROOT / "harness").rglob("*.py")
        if "tests" not in path.relative_to(REPO_ROOT).parts
        and any(name in path.read_text(encoding="utf-8") for name in forbidden))
    assert offenders == []
