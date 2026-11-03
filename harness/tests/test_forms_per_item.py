"""工单 #1392：项目的形态随事项冻结（形态与核验角色设计说明「形态随事项冻结」；总图第四节「定义」缝）。

同一个实例同时加载几份具名的形态，每份是一份完整的定义版本，默认是三部门。项目流里的一条形态事件记下项目
现在用哪一份；事项创建时冻结形态名与它的定义版本，之后这个事项的写入核对、路由、装配与执行都按那一份，
项目后来改了形态不影响它，重开数据目录继续的事项也按创建时那一份。

这份用例用测试目录里的任务池定义当第二份形态（它不进产品）：发布的那一份与它各跑完一个事项，各按自己
冻结的定义核对停止原因与部门；改形态只影响之后新建的事项；重开数据目录以后按记下的那一份接着跑。

层：集成层（第一、二、三条用例各跑完整的三部门或任务池循环、真实事件库、真实工作区与假模型）。守 R2
（骨架事件与对外合同只增：新的项目流事件在服务端合同与客户端夹具两端登记）与 R3（形态随事项冻结：换一份
定义就换形态，看得见、能撤回，事项按创建时那一份运行）。

先后由事件决定，不用时长赌（测试分层设计说明第 10 节第 7 条）：两个事项一个跑完再建下一个，脚本按部门
给出；任务池那一份定义与装配只在测试里用，产品代码不导入它们。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from harness.adapters.fake import FakeAdapter
from harness.app.contracts import EVENT_TYPES
from harness.definitions import DEFAULT_FORM, DEFINITIONS as PRODUCT_DEFINITIONS
from harness.event_store import project_stream
from harness.models import EventType, ProjectEventType, json_dumps
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.tests import second_routing
from harness.tests.helpers import delivery_turn, merge_scripts, product_spec, quality_turns
from harness.tightening import WATCHED_OUTPUTS
from harness.write_path import NewProjectEvent

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "client" / "tests" / "fixtures" / "event-types.json"
GOAL = "做一个可以长期演进的逐行文本处理工具。"
TASK = {"title": "README 的用法一节补上退出码说明"}

# 实例加载的两份形态（工单 #1392）：发布的三部门与测试目录里的任务池
FORMS = {
    DEFAULT_FORM: (PRODUCT_DEFINITIONS, WATCHED_OUTPUTS),
    second_routing.ROUTING_NAME: (second_routing.DEFINITIONS, second_routing.TIGHTENING),
}


def _turn(calls: list[list[Any]]):
    # 任务池的假模型回答：名字与参数由脚本给出，调用身份按激活与步骤编，不同部门的身份不重复
    def turn(call):
        output = []
        for index, (name, arguments) in enumerate(calls, start=1):
            identity = f"call-{call.activation_id}-{call.step_id}-{index}"
            output.append({"id": identity, "call_id": identity, "type": "function_call",
                           "name": name, "arguments": json_dumps(arguments)})
        return ModelResponse(output=output)

    return turn


def _task_pool_script() -> dict[str, list[Any]]:
    # 任务池跑完一件任务：发任务、完成、被打回、重做完、接纳（形状与 test_second_routing 相同）
    return {
        "product": [_turn([("submit_task", TASK)])],
        "engineering": [_turn([("complete_task", {"summary": "补了用法一节"})]),
                        _turn([("complete_task", {"summary": "补了退出码说明"})])],
        "quality": [_turn([("judge_task", {"verdict": "return", "reason": "用法一节没有写退出码"})]),
                    _turn([("judge_task", {"verdict": "accept", "reason": "与任务要求一致"})])],
    }


def _three_departments_script() -> dict[str, list[Any]]:
    # 三部门跑完一个事项：产品交 PRD、工程交交付、质检先独立判断再放行
    return {
        "product": [product_spec()],
        "engineering": [delivery_turn(summary="补了用法一节")],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }


def _system(data_dir: Path, script: dict[str, list[Any]], *, resume_on_startup: bool = True) -> LoopSystem:
    # 两份形态都交给实例；装配与执行用产品的那一份（两个事项各按自己那份定义取工具与提案合同）
    return LoopSystem.for_testing(data_dir, FakeAdapter(script), forms=FORMS,
                                  resume_on_startup=resume_on_startup)


def _set_form(system: LoopSystem, project_id: str, previous: str, form: str, reason: str = "换个形态") -> None:
    # 改形态的命令在 #1402：这里经写入口直接写这条项目事件（工单正文的做法）
    system.writes.append(project_stream(project_id), NewProjectEvent(
        ProjectEventType.PROJECT_FORM_SET,
        {"previous_form": previous, "form": form, "reason": reason}, actor="user:local"))


def _created(system: LoopSystem, project_id: str, work_item_id: str) -> dict[str, Any]:
    return next(event.payload for event in system.store.list_project_events(project_id)
                if event.type == ProjectEventType.WORK_ITEM_CREATED
                and event.payload["work_item_id"] == work_item_id)


def _run_created(system: LoopSystem, run_id: str) -> dict[str, Any]:
    return next(event.payload for event in system.store.list_events(run_id)
                if event.type == EventType.RUN_CREATED)


def _departments(system: LoopSystem, run_id: str) -> set[str]:
    return {event.department for event in system.store.list_events(run_id)
            if event.department is not None}


def test_two_forms_run_in_one_instance_each_under_its_frozen_definitions(tmp_path):
    # 验收第 1 条：项目的形态是三部门时建一个事项，再改成任务池建一个事项，两个都跑完，
    # 各按自己冻结的定义核对停止原因与部门
    system = _system(tmp_path / "loop", merge_scripts(_three_departments_script(), _task_pool_script()))
    project_id = system.projects.register("两种形态", GOAL)
    assert system.projects.projection(project_id).form == ""          # 从来没有设过形态
    assert system.projects.projection(project_id).form_name == DEFAULT_FORM

    first_item, first_run = system.projects.start_work_item(project_id, "第一步：补用法一节")
    assert _created(system, project_id, first_item)["form"] == DEFAULT_FORM
    assert _created(system, project_id, first_item)["definitions_version"] == PRODUCT_DEFINITIONS.version
    assert system.run_until_stop(first_run).status == "done"
    assert system.projects.settle(first_run).type == ProjectEventType.DELIVERABLE_ADOPTED
    first = system.project(first_run)
    assert first.stop_reason == "released"
    assert _departments(system, first_run) == set(PRODUCT_DEFINITIONS.departments)

    # 项目改成任务池（测试里的第二份形态）：之后新建的事项按它冻结，之前的事项不受影响
    _set_form(system, project_id, DEFAULT_FORM, second_routing.ROUTING_NAME)
    assert system.projects.projection(project_id).form == second_routing.ROUTING_NAME
    second_item, second_run = system.projects.start_work_item(project_id, "第二步：README 补退出码")
    assert _created(system, project_id, second_item)["form"] == second_routing.ROUTING_NAME
    assert _created(system, project_id, second_item)["definitions_version"] == second_routing.DEFINITIONS.version

    ended = system.run_until_stop(second_run)
    # 停止原因来自这一份定义自己声明的封闭清单（内核的清单里没有它）
    assert ended.stop_reason == second_routing.ITEM_END_REASON
    assert ended.status == "failed"
    assert second_routing.ITEM_END_REASON in second_routing.DEFINITIONS.routing_definition().end_reasons
    assert second_routing.ITEM_END_REASON not in PRODUCT_DEFINITIONS.stop_reasons
    assert _departments(system, second_run) == set(second_routing.DEFINITIONS.departments)
    # 任务池的三种成果经通用成果接纳事件写入：第二份形态的提议方式与成果种类真的用上了
    kinds = [event.payload.get("artifact_kind") for event in system.store.list_events(second_run)
             if event.type == EventType.ARTIFACT_ACCEPTED]
    assert kinds == [second_routing.TASK_KIND, second_routing.COMPLETION_KIND,
                     second_routing.VERDICT_KIND, second_routing.COMPLETION_KIND, second_routing.VERDICT_KIND]
    # 第一个事项的事件里没有任务池的任何一种成果：两份定义各管各的事项
    assert not [event for event in system.store.list_events(first_run)
                if event.type == EventType.ARTIFACT_ACCEPTED]
    system.close()


def test_a_running_item_keeps_its_form_when_the_project_form_changes(tmp_path):
    # 验收第 2 条前半：事项创建时冻结形态；事项已经跑起来以后项目改了形态，这个事项仍按创建时那一份跑完
    system = _system(tmp_path / "loop", merge_scripts(_three_departments_script(), _task_pool_script()),
                     resume_on_startup=False)
    project_id = system.projects.register("冻结", GOAL)
    item_id, run_id = system.projects.start_work_item(project_id, "先建事项，再改形态")
    # 先跑一轮（产品交 PRD），事项正在跑；这时把项目的形态改成任务池
    assert system.activate_once(run_id).status == "running"
    _set_form(system, project_id, DEFAULT_FORM, second_routing.ROUTING_NAME)

    ended = system.run_until_stop(run_id)

    assert ended.stop_reason == "released"           # 三部门那一份的结束原因
    assert _run_created(system, run_id)["form"] == DEFAULT_FORM
    assert system.projects.settle(run_id).type == ProjectEventType.DELIVERABLE_ADOPTED
    assert _created(system, project_id, item_id)["form"] == DEFAULT_FORM
    system.close()


def test_a_restarted_instance_resumes_an_item_with_the_form_it_was_created_with(tmp_path):
    # 验收第 2 条后半：进程重启以后继续的事项仍按创建时那份运行。重启之前把项目的形态改回三部门，
    # 事项仍是任务池那一份
    data_dir = tmp_path / "loop"
    script = _task_pool_script()
    first = _system(data_dir, script, resume_on_startup=False)
    project_id = first.projects.register("重启", GOAL)
    _set_form(first, project_id, DEFAULT_FORM, second_routing.ROUTING_NAME)
    item_id, run_id = first.projects.start_work_item(project_id, "README 的用法补退出码")
    # 重启之前把项目改回三部门：已经在跑的事项不受影响，没跑完的重启以后仍按任务池跑
    _set_form(first, project_id, second_routing.ROUTING_NAME, DEFAULT_FORM)
    first.close()

    second = _system(data_dir, script, resume_on_startup=False)
    assert second.projects.projection(project_id).form == DEFAULT_FORM
    assert _created(second, project_id, item_id)["form"] == second_routing.ROUTING_NAME
    ended = second.run_until_stop(run_id)

    assert ended.stop_reason == second_routing.ITEM_END_REASON
    assert _departments(second, run_id) == set(second_routing.DEFINITIONS.departments)
    second.close()


def test_an_upgrade_restart_keeps_the_frozen_form_or_is_refused(tmp_path):
    # 第 2 轮定的边界（项目的组织设计说明「冻结与升级」只写到新建事项被拒绝）：升级重新开始时，事项冻结的
    # 形态已经不在发布里，与新建事项同样拒绝——不换一份形态，原因记在项目流的那条事项上；**这个 run 不停**，
    # 留着它未结束，换回带那一份形态的发布以后由升级重新开始接着跑。同一批里形态还在发布里的 run 照旧重新
    # 开始，实例照常起来。两条路各一条：项目现在的形态还在发布里（原来会静默换成它）、项目现在的形态也不在
    # 发布里（原来会从批量升级里抛出去、实例起不来）
    data_dir = tmp_path / "loop"
    script = merge_scripts(_three_departments_script(), _task_pool_script())
    first = _system(data_dir, script, resume_on_startup=False)
    project_id = first.projects.register("升级时形态不在发布里", GOAL)
    kept_item, kept_run = first.projects.start_work_item(project_id, "三部门的事项")
    assert first.activate_once(kept_run).status == "running"
    _set_form(first, project_id, DEFAULT_FORM, second_routing.ROUTING_NAME)
    gone_item, gone_run = first.projects.start_work_item(project_id, "任务池的事项")
    other_id = first.projects.register("项目的形态也不在发布里", GOAL)
    _set_form(first, other_id, DEFAULT_FORM, second_routing.ROUTING_NAME)
    other_item, other_run = first.projects.start_work_item(other_id, "任务池的另一个事项")
    first.close()

    # 重开成只带默认形态的实例：发布里已经没有任务池那一份；第一个项目的形态改回默认，第二个项目仍是任务池
    second = LoopSystem.for_testing(data_dir, FakeAdapter(script), resume_on_startup=False)
    _set_form(second, project_id, second_routing.ROUTING_NAME, DEFAULT_FORM)
    stopped, restarted = second.stop_and_restart_runs(
        [gone_run, other_run, kept_run], reason="run event version differs from the current version")

    # 形态不在发布里的两条不停止：run 留着未结束，换回带那一份形态的发布以后还能接着跑
    assert stopped == [kept_run]
    for run_id in (gone_run, other_run):
        assert not [event for event in second.store.list_events(run_id)
                    if event.type == EventType.RUN_FAILED]
    # 也不换形态、不建新的事项记录，原因记在这条事项的开始失败上
    for item_id, project in ((gone_item, project_id), (other_item, other_id)):
        gone = next(item for item in second.projects.projection(project).work_items
                    if item.work_item_id == item_id)
        assert gone.form == second_routing.ROUTING_NAME
        assert gone.start_error == (f"unknown form {second_routing.ROUTING_NAME!r}: "
                                    f"the release loads {[DEFAULT_FORM]}")
        assert len([event for event in second.store.list_project_events(project)
                    if event.type == ProjectEventType.WORK_ITEM_CREATED
                    and event.payload["work_item_id"] == item_id]) == 1
    # 同一批里其余 run 照旧重新开始：实例起得来，形态还在发布里的那一份按它自己记下的形态重开
    assert len(restarted) == 1
    resumed = next(item for item in second.projects.projection(project_id).work_items
                   if item.work_item_id == restarted[0])
    assert resumed.form == DEFAULT_FORM
    assert resumed.restarted_from_run_id == kept_run
    old = next(item for item in second.projects.projection(project_id).work_items
               if item.work_item_id == kept_item)
    assert (old.form, old.run_id) == (DEFAULT_FORM, kept_run)
    second.close()

    # 换回带那一份形态的发布（交付说明里给用户的处理方式）：这两个 run 这时才停，事项按它自己记下的形态接着跑
    third = _system(data_dir, script, resume_on_startup=False)
    stopped_back, restarted_back = third.stop_and_restart_runs(
        [gone_run], reason="run event version differs from the current version")
    assert stopped_back == [gone_run]
    assert len(restarted_back) == 1
    back = next(item for item in third.projects.projection(project_id).work_items
                if item.work_item_id == restarted_back[0])
    assert (back.form, back.restarted_from_run_id) == (second_routing.ROUTING_NAME, gone_run)
    third.close()


def test_a_new_item_is_rejected_when_the_project_form_is_not_in_the_release(tmp_path):
    # 发布里没有那一份形态（项目的组织设计说明「冻结与升级」）：新建事项被拒绝，说明写明原因与可选的形态，
    # 不写事项、不开始 run；已经冻结了那一份的旧事项靠自己记下的定义跑，不受影响
    system = _system(tmp_path / "loop", _three_departments_script(), resume_on_startup=False)
    project_id = system.projects.register("未知形态", GOAL)
    _set_form(system, project_id, DEFAULT_FORM, "form_from_a_newer_release")

    with pytest.raises(ValueError, match="unknown form 'form_from_a_newer_release'") as raised:
        system.projects.start_work_item(project_id, "不该开始的事项")
    assert DEFAULT_FORM in str(raised.value)
    assert system.projects.projection(project_id).work_items == []
    system.close()


def test_the_new_project_event_is_registered_on_both_ends():
    # 验收第 3 条：新的项目事件种类在服务端合同与客户端的事件种类夹具两端登记
    assert ProjectEventType.PROJECT_FORM_SET in EVENT_TYPES
    assert ProjectEventType.PROJECT_FORM_SET in {
        event for event in json.loads(FIXTURE.read_text(encoding="utf-8"))}
    assert "project_form_set" == ProjectEventType.PROJECT_FORM_SET
