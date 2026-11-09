"""工单 #1517：新建事项冻结整份合成结果与发布升级（项目的组织设计说明「冻结与升级」「新建的入口」；
形态与核验角色设计说明「形态随事项冻结」；总图第四节「定义」缝）。

新建事项时合成、校验，把合成结果整份存进事实：事项创建事件与 run 的创建事件记下形态名、组织版本与那份
合成结果的工件引用（definitions_ref）。之后写入核对、路由、装配、执行与重放都读这一份，发布后来改了形态、
项目后来改了组织都不影响已经在跑的事项；旧事项只记了形态名，照旧按名字在这一版发布里取。

项目的组织（project.organization）给出和这个项目上一个事项用的组织相比有什么不同（比较两份合成结果，
不另存状态），并在还有事项按旧组织跑时把旧组织的部门也列出来、标出还在用它的几个事项；事项详情
（project.loop 的 organization）给出这个事项用的形态名、版本，以及和项目现在的组织相同还是不同。

层：集成层（每一条都开真实事件库与真实工作区、按部门跑完整的循环，模型回答由假模型按部门给出；
组织本身经真实的应用层命令与查询合成与读取）。守 R2（骨架事件与对外合同只增：新增的是事项创建事件与
run 创建事件上的一个工件引用，旧事件照样读、重放结果不变）与 R3（组织随事项冻结：换了定义组织也看得见、
能撤回，事项按创建时那一份跑完）。

先后由事件决定，不用时长赌（测试分层 docs/design/test-pyramid.md「测试的写法」）：事项一个跑完再建下一个，
脚本按部门给出；换了内容的发布是测试里按定义文件的副本造出来的，产品代码不导入它。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.app.application import Application
from harness.app.contracts import Accepted, Rejected
from harness.app.form_commands import OrganizationAdopt
from harness.app.form_queries import ProjectOrganization
from harness.app.project_and_work_item_commands import WorkItemCreate
from harness.app.project_commands import ProjectCreate, ProjectOnboard
from harness.app.project_queries import ProjectLoop
from harness.definitions import DEFAULT_FORM, DEFINITIONS, Definitions, definitions_from_contents
from harness.event_store import Command, project_stream, run_stream
from harness.models import EventType, ProjectEventType, new_id
from harness.projection import RunProjection, saved_decisions
from harness.projects import definitions_from_ref
from harness.proposals import baseline_review_turn, structure_turn
from harness.runtime import SEVERAL_ROLES_DIRECT, SINGLE_ROLE_DIRECT, LoopSystem
from harness.tests.helpers import delivery_turn, merge_scripts, product_spec, quality_turns
from harness.tests.onboarding_project import ONBOARDING_GOAL, ONBOARDING_REQUIREMENT, onboarding_source
from harness.tightening import WATCHED_OUTPUTS
from harness.write_path import NewProjectEvent

GOAL = "做一个可以长期演进的逐行文本处理工具。"

# 一份只改了质检显示名的发布（验收第 1 条与第 2 条）：编号、角色、核验声明与工具都照旧，只有显示名不同，
# 所以同一个三部门脚本照样跑得完；按定义文件的副本造出来，版本（内容摘要）跟着变
RENAMED_LABEL = "验收"
ADDED_TOOL = "trial_open"          # 发布里有、工程原来没有的一个工具（本项目给工程加它）
RELEASE_ADDED_TOOL = "run_baseline_check"   # 发布改了工程工具时加上的那一个
RELEASE_REMOVED_TOOL = "browser_resize"     # 发布改了工程工具时去掉的那一个


def _release_with(editor) -> Definitions:
    # 按定义文件的副本改出一份新的发布：内容与版本都由同一套加载与校验得出，与真实发布一样是一份完整的定义
    contents = deepcopy(DEFINITIONS.contents)
    editor(contents)
    return definitions_from_contents(contents)


def _renamed_release() -> Definitions:
    def rename(contents: dict[str, Any]) -> None:
        for department in contents["organization.json"]["departments"]:
            if department["id"] == "quality":
                department["label"] = RENAMED_LABEL

    return _release_with(rename)


def _edit_engineering_tools(contents: dict[str, Any], *, remove: str, add: str) -> None:
    # 发布改了工程的工具：角色许可与各事项种类的工作说明里换掉这两个（工具清单里两个都有）
    contents["roles.json"]["engineering"]["tools"] = [
        add if name == remove else name for name in contents["roles.json"]["engineering"]["tools"]]
    for kind in contents["work_items.json"]["kinds"].values():
        work = (kind.get("departments") or {}).get("engineering")
        if work is not None:
            work["tools"] = [add if name == remove else name for name in work.get("tools", [])]


def _release_without(tool: str) -> Definitions:
    # 一份不再带某个工具的发布：工具清单、角色许可与各事项种类的工作说明里都去掉它
    def drop(contents: dict[str, Any]) -> None:
        contents["tools.json"].pop(tool)
        for role in contents["roles.json"].values():
            role["tools"] = [name for name in role["tools"] if name != tool]
        for kind in contents["work_items.json"]["kinds"].values():
            for work in (kind.get("departments") or {}).values():
                work["tools"] = [name for name in work.get("tools", []) if name != tool]

    return _release_with(drop)


def _system(data_dir: Path, script: dict[str, list[Any]], *,
            release: Definitions | None = None, resume_on_startup: bool = True) -> LoopSystem:
    # 实例加载的形态：不给时是发布带的那几份；给了就是这一份（同一个形态名、内容换过的那一次发布）
    forms = None if release is None else {DEFAULT_FORM: (release, WATCHED_OUTPUTS)}
    return LoopSystem.for_testing(data_dir, FakeAdapter(script), forms=forms,
                                  resume_on_startup=resume_on_startup)


def _three_departments_script() -> dict[str, list[Any]]:
    # 三部门跑完一个事项：产品交 PRD、工程交交付、质检先独立判断再放行
    return {
        "product": [product_spec()],
        "engineering": [delivery_turn(summary="补了用法一节")],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }


def _application(system: LoopSystem) -> Application:
    return Application(system)


def _adopt(application: Application, project_id: str, changes: dict[str, Any], *,
           form: str = DEFAULT_FORM, reason: str = "改了组织") -> Accepted | Rejected:
    # 采用本项目的一份组织（工单 #1516 的命令）：走高级这条路，理由写明
    organization = application.query("project.organization",
                                     ProjectOrganization(project_id=project_id)).data
    return asyncio.run(application.command("organization.adopt", OrganizationAdopt(
        command_id=str(uuid.uuid4()), project_id=project_id, form=form, changes=changes,
        reason=reason, base_version=organization.version, mode="advanced"), actor="user:local"))


def _project_organization(application: Application, project_id: str):
    return application.query("project.organization", ProjectOrganization(project_id=project_id)).data


def _item_organization(application: Application, project_id: str, work_item_id: str):
    # 事项详情（project.loop 的 organization）：这个事项用的组织，形态名、版本与和项目现在的组织相同与否
    result = application.query("project.loop", ProjectLoop(project_id=project_id,
                                                           work_item=work_item_id)).data
    [row] = result.work_items
    return row.organization


def _created(system: LoopSystem, project_id: str, work_item_id: str) -> dict[str, Any]:
    return next(event.payload for event in system.store.list_project_events(project_id)
                if event.type == ProjectEventType.WORK_ITEM_CREATED
                and event.payload["work_item_id"] == work_item_id)


def _run_created(system: LoopSystem, run_id: str) -> dict[str, Any]:
    return next(event.payload for event in system.store.list_events(run_id)
                if event.type == EventType.RUN_CREATED)


def _definitions_requests(system: LoopSystem, run_id: str) -> list[Any]:
    # run 流上「定义版本不同」的决定请求
    return [decision for decision in system.writes.read(run_stream(run_id)).decisions.values()
            if decision.request["kind"] == "definitions_changed"]


def _answer_command() -> Command:
    return Command(command_id=new_id("cmd"), name="decision.answer", digest="test", actor="user")


def _finished(system: LoopSystem, run_id: str) -> RunProjection:
    ended = system.run_until_stop(run_id)
    assert system.projects.settle(run_id).type == ProjectEventType.DELIVERABLE_ADOPTED
    return ended


def _departments_of(system: LoopSystem, run_id: str) -> set[str]:
    return {event.department for event in system.store.list_events(run_id)
            if event.department is not None}


# ---------------------------------------------------------------------------
# 验收第 1 条：本项目把质检改名并采用，新建的事项按改名以后的跑完；进行中的事项按改名之前的跑完


def test_an_item_started_after_the_adoption_runs_under_the_names_it_froze(tmp_path):
    system = _system(tmp_path / "loop", _three_departments_script())
    application = _application(system)
    project_id = system.projects.register("改名", GOAL)

    adopted = _adopt(application, project_id, {"departments": {"quality": {"label": RENAMED_LABEL}}})
    assert isinstance(adopted, Accepted), adopted
    organization = _project_organization(application, project_id)
    assert organization.version is not None and organization.version != DEFINITIONS.version

    item_id, run_id = system.projects.start_work_item(project_id, "改名以后新建的事项")
    created = _created(system, project_id, item_id)
    # 事项创建时冻结的是整份合成结果（形态加本项目的改动）：版本是合成结果的摘要，工件引用写进事实。
    # 工件按内容摘要落在项目的范围里，事项创建事件与 run 的创建事件记的是同一份
    assert created["form"] == DEFAULT_FORM
    assert created["definitions_version"] == organization.version
    reference = created["definitions_ref"]
    assert reference["kind"] == "item_definitions"
    assert reference["path"].startswith(f"{project_id}/")
    assert _run_created(system, run_id)["definitions_ref"] == reference
    # 这个事项用的那份定义里，质检的显示名是改名以后的；身份不变
    frozen = system.orchestrator.item_form(run_id).definitions
    assert frozen.department_labels["quality"] == RENAMED_LABEL
    assert frozen.departments == DEFINITIONS.departments

    # 跑完：结束原因、部门与默认那一份相同（事件序列除名字外相同）
    ended = _finished(system, run_id)
    assert ended.status == "done" and ended.stop_reason == "released"
    assert _departments_of(system, run_id) == set(DEFINITIONS.departments)

    # 事项详情：形态名、版本，以及与项目现在的组织相同
    row = _item_organization(application, project_id, item_id)
    assert (row.form, row.version) == (DEFAULT_FORM, organization.version)
    assert row.same_as_project is True
    assert [(role.id, role.label) for role in row.roles] == [
        (department, frozen.department_labels[department]) for department in DEFINITIONS.departments]
    system.close()


def test_an_item_started_before_the_adoption_keeps_the_names_it_froze(tmp_path):
    system = _system(tmp_path / "loop", _three_departments_script())
    application = _application(system)
    project_id = system.projects.register("改名之前就开跑", GOAL)

    item_id, run_id = system.projects.start_work_item(project_id, "改名之前建的事项")
    assert system.activate_once(run_id).status == "running"
    adopted = _adopt(application, project_id, {"departments": {"quality": {"label": RENAMED_LABEL}}})
    assert isinstance(adopted, Accepted), adopted

    # 这个事项仍按它冻结的那一份跑完：改名之前的那份定义里质检还叫原来的名字
    ended = _finished(system, run_id)
    assert ended.status == "done" and ended.stop_reason == "released"
    assert system.orchestrator.item_form(run_id).definitions.department_labels["quality"] == "质检"
    row = _item_organization(application, project_id, item_id)
    assert row.version == DEFINITIONS.version
    assert row.same_as_project is False
    assert _project_organization(application, project_id).version != row.version
    system.close()


# ---------------------------------------------------------------------------
# 验收第 2 条：进程重启后继续的事项仍按它存下的那份合成结果运行，发布里那份形态变了也不影响它


def test_a_restarted_instance_runs_the_organization_the_item_froze_not_the_changed_release(tmp_path):
    data_dir = tmp_path / "loop"
    script = _three_departments_script()
    first = _system(data_dir, script, resume_on_startup=False)
    project_id = first.projects.register("发布改了形态", GOAL)
    item_id, run_id = first.projects.start_work_item(project_id, "发布改了形态以后接着跑")
    assert first.activate_once(run_id).status == "running"
    frozen_version = _created(first, project_id, item_id)["definitions_version"]
    first.close()

    # 换一份发布：同一个形态名，内容变了（质检改了显示名），版本也跟着变
    renamed = _renamed_release()
    assert renamed.version != DEFINITIONS.version
    second = _system(data_dir, script, release=renamed)
    # 发布里这一份变了：先按工单 #1392 的读法发「定义版本不同」的决定请求，不直接继续
    assert run_id not in second.resumed_runs
    [request] = _definitions_requests(second, run_id)
    assert request.request["recorded_definitions_version"] == frozen_version
    assert request.request["current_definitions_version"] == renamed.version

    # 回答「按新版本继续」：仍按创建时存下的那份合成结果运行，发布里改过的那一份不接手
    second.orchestrator.answer_decision(request.decision_id, "continue", None,
                                        base_version=request.version, command=_answer_command())
    ended = second.run_until_stop(run_id)
    assert second.projects.settle(run_id).type == ProjectEventType.DELIVERABLE_ADOPTED
    assert ended.status == "done" and ended.stop_reason == "released"
    frozen = second.orchestrator.item_form(run_id).definitions
    assert frozen.version == frozen_version
    assert frozen.department_labels["quality"] == "质检"
    assert second.forms[DEFAULT_FORM].definitions.department_labels["quality"] == RENAMED_LABEL
    assert second.orchestrator.item_definitions(run_id).version == frozen_version
    second.close()


def test_restarting_does_not_ask_about_the_definitions_version_when_only_the_project_changed(tmp_path):
    # 回归（审查发现）：采用过组织改动以后建的事项，冻结的合成结果里有本项目的改动，版本与发布里那个形态的
    # 版本本来就不同；重启时发布没有变，不该发「定义版本不同」的决定请求，照旧直接接着跑
    data_dir = tmp_path / "loop"
    script = _three_departments_script()
    first = _system(data_dir, script, resume_on_startup=False)
    application = _application(first)
    project_id = first.projects.register("采用过改动的项目", GOAL)
    adopted = _adopt(application, project_id, {"departments": {"quality": {"label": RENAMED_LABEL}}})
    assert isinstance(adopted, Accepted), adopted
    item_id, run_id = first.projects.start_work_item(project_id, "采用之后建的事项")
    assert first.activate_once(run_id).status == "running"
    frozen_version = _created(first, project_id, item_id)["definitions_version"]
    assert frozen_version != DEFINITIONS.version             # 冻结的是合成结果的版本，不是发布里那一份
    first.close()

    second = _system(data_dir, script)
    assert _definitions_requests(second, run_id) == []
    assert second.resumed_runs.get(run_id) is not None
    ended = second.run_until_stop(run_id)
    assert ended.status == "done" and ended.stop_reason == "released"
    assert second.orchestrator.item_form(run_id).definitions.version == frozen_version
    assert second.orchestrator.item_form(run_id).definitions.department_labels["quality"] == RENAMED_LABEL
    second.close()


# ---------------------------------------------------------------------------
# 验收第 3 条：发布改了工程的工具、本项目没碰它，下一个事项用上新工具、本项目加过的工具仍在，
# 查询写明不同；发布不再带本项目加过的工具时新建事项被拒绝并写明原因


def test_the_next_item_follows_the_release_and_the_query_names_the_difference(tmp_path):
    data_dir = tmp_path / "loop"
    script = _three_departments_script()
    first = _system(data_dir, script, resume_on_startup=False)
    application = _application(first)
    project_id = first.projects.register("工具跟着发布走", GOAL)
    # 本项目给工程加一个工具（发布里有、工程原来没有）
    adopted = _adopt(application, project_id,
                     {"departments": {"engineering": {"tools": {"add": [ADDED_TOOL]}}}})
    assert isinstance(adopted, Accepted), adopted
    before_item, before_run = first.projects.start_work_item(project_id, "加工具以后的第一件事项")
    assert ADDED_TOOL in first.orchestrator.item_form(before_run).definitions.roles["engineering"].tools
    assert first.activate_once(before_run).status == "running"
    first.close()

    # 发布改了工程的工具：去掉一个、加上另一个（本项目没有碰这两项）
    release = _release_with(lambda contents: _edit_engineering_tools(
        contents, remove=RELEASE_REMOVED_TOOL, add=RELEASE_ADDED_TOOL))
    second = _system(data_dir, script, release=release, resume_on_startup=False)
    application = _application(second)

    # 「高级」里写明和这个项目上一个事项用的组织相比有什么不同（下一个事项会自动用上现在这份）
    organization = _project_organization(application, project_id)
    previous = organization.previous_item
    assert previous is not None and previous.work_item_id == before_item
    differences = {row.item: (row.before, row.after) for row in previous.differences}
    tools_before, tools_after = differences["departments.engineering.tools"]
    assert RELEASE_ADDED_TOOL in tools_after and RELEASE_ADDED_TOOL not in tools_before
    assert RELEASE_REMOVED_TOOL in tools_before and RELEASE_REMOVED_TOOL not in tools_after
    assert ADDED_TOOL in tools_after and ADDED_TOOL in tools_before

    # 上一个事项还在跑：它冻结着加工具之后的组织，发布改了工具也不影响它
    frozen_before = second.orchestrator.item_form(before_run).definitions
    assert frozen_before.version == _created(second, project_id, before_item)["definitions_version"]
    assert RELEASE_REMOVED_TOOL in frozen_before.roles["engineering"].tools

    after_item, after_run = second.projects.start_work_item(project_id, "发布改了工具以后的事项")
    definitions = second.orchestrator.item_form(after_run).definitions
    # 跟着发布的项用上新工具、去掉发布去掉的那一个，本项目加过的工具仍在
    assert RELEASE_ADDED_TOOL in definitions.roles["engineering"].tools
    assert RELEASE_REMOVED_TOOL not in definitions.roles["engineering"].tools
    assert ADDED_TOOL in definitions.roles["engineering"].tools

    # 下一个事项用的是现在这份组织，所以和上一个事项（它自己）比没有不同
    latest = _project_organization(application, project_id)
    assert latest.previous_item is not None and latest.previous_item.work_item_id == after_item
    assert latest.previous_item.differences == []
    second.close()


def test_a_new_item_is_rejected_when_the_release_no_longer_has_a_tool_the_project_added(tmp_path):
    data_dir = tmp_path / "loop"
    script = _three_departments_script()
    first = _system(data_dir, script, resume_on_startup=False)
    application = _application(first)
    project_id = first.projects.register("发布不再带这个工具", GOAL)
    adopted = _adopt(application, project_id,
                     {"departments": {"engineering": {"tools": {"add": [ADDED_TOOL]}}}})
    assert isinstance(adopted, Accepted), adopted
    item_id, run_id = first.projects.start_work_item(project_id, "加工具以后的事项")
    ended = _finished(first, run_id)
    assert ended.status == "done" and ended.stop_reason == "released"
    frozen_version = _created(first, project_id, item_id)["definitions_version"]
    first.close()

    # 发布不再带这个工具：本项目加的项合不到一起，新建事项被拒绝并写明是哪一项
    second = _system(data_dir, script, release=_release_without(ADDED_TOOL), resume_on_startup=False)
    application = _application(second)
    organization = _project_organization(application, project_id)
    assert organization.version is None
    assert [issue.item for issue in organization.rejections]
    rejected = asyncio.run(application.command("work_item.create", WorkItemCreate(
        command_id=str(uuid.uuid4()), project_id=project_id, text="发布不再带这个工具时建的事项"),
        actor="user:local"))
    assert isinstance(rejected, Rejected), rejected
    assert rejected.reason == "not_allowed"
    assert ADDED_TOOL in rejected.message
    # 已经跑完的那个事项仍按它冻结的那一份读：发布换了内容不影响它
    assert second.orchestrator.item_definitions(run_id).version == frozen_version
    second.close()


# ---------------------------------------------------------------------------
# 验收第 4 条：新建项目带形态名时用那一份；新建事项临时选一份只影响这个事项，项目的组织不变


def test_a_new_project_uses_the_chosen_form_and_an_item_can_choose_another(tmp_path):
    system = _system(tmp_path / "loop", _three_departments_script(), resume_on_startup=False)
    application = _application(system)
    created = asyncio.run(application.command("project.create", ProjectCreate(
        command_id=str(uuid.uuid4()), name="选一张卡建项目", goal=GOAL, form=SEVERAL_ROLES_DIRECT),
        actor="user:local"))
    assert isinstance(created, Accepted), created
    project_id = created.refs.project_id
    organization = _project_organization(application, project_id)
    assert organization.form == SEVERAL_ROLES_DIRECT
    assert organization.version == system.forms[SEVERAL_ROLES_DIRECT].definitions.version

    # 临时选的形态不在发布里：拒绝并列出可以选的形态
    rejected = asyncio.run(application.command("work_item.create", WorkItemCreate(
        command_id=str(uuid.uuid4()), project_id=project_id, text="临时选的形态不在发布里",
        form="form_not_in_release"), actor="user:local"))
    assert isinstance(rejected, Rejected) and rejected.reason == "not_allowed"

    # 新建事项时临时选发布带的另一份形态：只影响这个事项，项目的组织不变
    item_id, run_id = system.projects.start_work_item(project_id, "临时选三部门", form=DEFAULT_FORM)
    row = _item_organization(application, project_id, item_id)
    assert row is not None and row.form == DEFAULT_FORM
    assert row.same_as_project is False
    still = _project_organization(application, project_id)
    assert (still.form, still.version) == (SEVERAL_ROLES_DIRECT, organization.version)

    # 这个事项真的按临时选的那一份跑完：三部门以放行结束（那是这一份定义的结束方式）
    ended = _finished(system, run_id)
    assert ended.status == "done" and ended.stop_reason == "released"
    system.close()


# ---------------------------------------------------------------------------
# 验收第 5 条：项目的部门清单在冻结着旧组织的事项还在跑时包含旧组织的部门并标出


def test_the_project_department_list_keeps_a_department_only_the_running_item_uses(tmp_path):
    system = _system(tmp_path / "loop", _three_departments_script(), resume_on_startup=False)
    application = _application(system)
    project_id = system.projects.register("去掉质检的项目", GOAL)
    item_id, run_id = system.projects.start_work_item(project_id, "去掉质检之前就开跑的事项")
    assert system.activate_once(run_id).status == "running"

    # 本项目去掉质检：别的部门对质检交出的成果的关注一起去掉（合成规则第 5 条）
    adopted = _adopt(application, project_id, {
        "remove_departments": ["quality"],
        "departments": {"product": {"watched": {"remove": ["baseline_review"]}},
                        "engineering": {"watched": {"remove": ["defect_record"]}}}})
    assert isinstance(adopted, Accepted), adopted

    organization = _project_organization(application, project_id)
    departments = {row.id: row for row in organization.departments}
    # 现在这份组织里没有质检；这件事项还在按旧组织跑，所以清单仍然包含它并标出来源是还在跑的事项
    assert organization.organization is not None
    assert [department.id for department in organization.organization.departments] == [
        "product", "engineering"]
    assert [row.id for row in organization.departments] == ["product", "engineering", "quality"]
    quality = departments["quality"]
    assert (quality.origin, quality.running_items, quality.label) == ("running_item", 1, "质检")
    assert (departments["product"].origin, departments["product"].running_items) == ("changed", 1)

    # 事项详情与循环图读的是它冻结的那一份：这个事项的组织里还有质检
    row = _item_organization(application, project_id, item_id)
    assert [role.id for role in row.roles] == list(DEFINITIONS.departments)
    assert row.same_as_project is False

    # 进行中的事项不受影响：它还按冻结的那一份跑完，以放行结束
    ended = _finished(system, run_id)
    assert ended.status == "done" and ended.stop_reason == "released"
    # 跑完以后它不再算在「还在跑的事项」里，清单里只剩现在这份组织的部门
    after = _project_organization(application, project_id)
    assert [item.id for item in after.departments] == ["product", "engineering"]
    system.close()


def test_adopting_an_existing_project_can_choose_a_form(tmp_path):
    # 接入已有项目带形态名（验收第 4 条的后半）：建档事项按选的那一份冻结，项目现在用的组织就是它。
    # 这条的命令在一个事务里追加登记、源目录、形态改动与事项创建四条事件，事项创建事件按种类取得到
    system = _system(tmp_path / "loop", {department: [] for department in DEFINITIONS.departments},
                     resume_on_startup=False)
    application = _application(system)
    source = onboarding_source(tmp_path / "source")
    created = asyncio.run(application.command("project.onboard", ProjectOnboard(
        command_id=str(uuid.uuid4()), name="接入已有项目", goal=ONBOARDING_GOAL, source_name="src",
        source_path=str(source), form=SINGLE_ROLE_DIRECT), actor="user:local"))
    assert isinstance(created, Accepted), created
    organization = _project_organization(application, created.refs.project_id)
    assert organization.form == SINGLE_ROLE_DIRECT
    onboarding = _created(system, created.refs.project_id, created.refs.work_item_id)
    assert onboarding["kind"] == "onboarding"
    assert onboarding["form"] == SINGLE_ROLE_DIRECT
    assert onboarding["definitions_version"] == system.forms[SINGLE_ROLE_DIRECT].definitions.version
    assert onboarding["definitions_ref"]["kind"] == "item_definitions"
    system.close()


def test_the_running_items_count_counts_items_not_organizations(tmp_path):
    # 审查发现：同一份组织有两个事项在用，`running_items` 要数事项（2），不是数几种组织（1）
    system = _system(tmp_path / "loop", merge_scripts(_three_departments_script(),
                                                      _three_departments_script()),
                     resume_on_startup=False)
    application = _application(system)
    project_id = system.projects.register("两个事项在跑", GOAL)
    first_item, first_run = system.projects.start_work_item(project_id, "第一件在跑的事项")
    second_item, second_run = system.projects.start_work_item(project_id, "第二件在跑的事项")
    assert system.activate_once(first_run).status == "running"
    assert system.activate_once(second_run).status == "running"

    adopted = _adopt(application, project_id, {
        "remove_departments": ["quality"],
        "departments": {"product": {"watched": {"remove": ["baseline_review"]}},
                        "engineering": {"watched": {"remove": ["defect_record"]}}}})
    assert isinstance(adopted, Accepted), adopted
    organization = _project_organization(application, project_id)
    departments = {row.id: row for row in organization.departments}
    assert [row.id for row in organization.departments] == ["product", "engineering", "quality"]
    # 两个事项还在跑，两个都用了质检
    assert (departments["quality"].origin, departments["quality"].running_items) == ("running_item", 2)
    assert departments["product"].running_items == 2
    assert (_item_organization(application, project_id, first_item).same_as_project,
            _item_organization(application, project_id, second_item).same_as_project) == (False, False)
    system.close()


def test_an_old_item_without_a_frozen_organization_still_adds_its_departments(tmp_path):
    # 审查发现：只记了形态名的旧事项（没有 definitions_ref）也要算进项目的部门清单：
    # 它的组织按它在那一版发布里取（工单 #1392 的读法），项目改掉组织以后旧组织的部门照样列举并标出
    data_dir = tmp_path / "loop"
    system = _system(data_dir, _three_departments_script(), resume_on_startup=False)
    application = _application(system)
    project_id = system.projects.register("旧事项还在跑", GOAL)
    item_id, run_id = system.projects.start_work_item(project_id, "冻结之前建的事项")
    assert system.activate_once(run_id).status == "running"
    system.close()
    _forget_frozen_organization(data_dir, item_id)

    reopened = _system(data_dir, _three_departments_script(), resume_on_startup=False)
    application = _application(reopened)
    assert _created(reopened, project_id, item_id).get("definitions_ref") is None
    adopted = _adopt(application, project_id, {
        "remove_departments": ["quality"],
        "departments": {"product": {"watched": {"remove": ["baseline_review"]}},
                        "engineering": {"watched": {"remove": ["defect_record"]}}}})
    assert isinstance(adopted, Accepted), adopted
    organization = _project_organization(application, project_id)
    departments = {row.id: row for row in organization.departments}
    assert (departments["quality"].origin, departments["quality"].running_items) == ("running_item", 1)
    reopened.close()


def _forget_frozen_organization(data_dir: Path, work_item_id: str) -> None:
    # 把事项创建事件里的冻结结果去掉，模拟这一单之前登记的事项（只记了形态名）。项目的部门清单只按事项创建
    # 事件里的引用看，这条用例要的就是那一路；事件库里 run 的创建事件原样留着
    connection = sqlite3.connect(data_dir / "events.sqlite")
    try:
        rows = connection.execute(
            "SELECT event_id, payload_json FROM events WHERE type = ?",
            (ProjectEventType.WORK_ITEM_CREATED,)).fetchall()
        for event_id, payload in rows:
            document = json.loads(payload)
            if document.get("work_item_id") != work_item_id:
                continue
            document.pop("definitions_ref", None)
            connection.execute("UPDATE events SET payload_json = ? WHERE event_id = ?",
                               (json.dumps(document, ensure_ascii=False, sort_keys=True), event_id))
        connection.commit()
    finally:
        connection.close()


def test_the_work_item_command_refuses_when_the_project_form_is_not_in_the_release(tmp_path):
    # 审查发现：项目现在的形态不在这一版发布里时，新建事项走命令层要给 not_allowed 与说明，不是未处理的错误
    system = _system(tmp_path / "loop", _three_departments_script(), resume_on_startup=False)
    application = _application(system)
    project_id = system.projects.register("项目的形态不在发布里", GOAL)
    system.writes.append(project_stream(project_id), NewProjectEvent(
        ProjectEventType.PROJECT_FORM_SET,
        {"previous_form": DEFAULT_FORM, "form": "form_from_a_newer_release", "reason": ""},
        actor="user:local"))
    rejected = asyncio.run(application.command("work_item.create", WorkItemCreate(
        command_id=str(uuid.uuid4()), project_id=project_id, text="不该开始的事项"), actor="user:local"))
    assert isinstance(rejected, Rejected), rejected
    assert rejected.reason == "not_allowed"
    assert "form_from_a_newer_release" in rejected.message
    assert system.projects.projection(project_id).work_items == []
    system.close()


def _onboarding_script() -> dict[str, list[Any]]:
    # 建档一轮的三部门回答（与 test_forms_per_item 的做法相同）：产品交初始 PRD、工程交结构说明、
    # 质检做基线核验；质检一轮里可能被唤醒两次，给两条回答
    requirement = ONBOARDING_REQUIREMENT
    return {
        "product": [FakeTurn(proposal=product_spec(
            goal=ONBOARDING_GOAL, requirements=[requirement], acceptance=["run the CLI with a word"]))],
        "engineering": [structure_turn(
            requirement_locations=[{"requirement": requirement, "locations": ["src/echo.py"]}],
            overall="一个包加一个命令行入口")],
        "quality": [baseline_review_turn(conclusions=[
            {"requirement": requirement, "status": "verified", "evidence": "smoke"}]) for _ in range(2)],
    }


def test_an_onboarding_revision_run_keeps_the_frozen_organization(tmp_path):
    # 审查发现：建档修改轮建 run 时只带了形态名，没有带冻结的整份合成结果——项目改过组织时修改轮会按发布里
    # 那一份跑，与事项创建时冻结的那一份不一致。这条看修改轮的 run 记的引用与它读到的组织
    system = LoopSystem.for_testing(tmp_path / "loop", FakeAdapter(_onboarding_script()),
                                    resume_on_startup=False)
    application = _application(system)
    project_id = system.projects.register("两轮建档", ONBOARDING_GOAL, source="existing")
    system.projects.configure_source_directory(project_id, "src",
                                               str(onboarding_source(tmp_path / "source")), base_version=0)
    adopted = _adopt(application, project_id, {"departments": {"quality": {"label": RENAMED_LABEL}}})
    assert isinstance(adopted, Accepted), adopted
    item_id, first_run = system.projects.restart_onboarding(project_id, "src")
    frozen = _created(system, project_id, item_id)["definitions_version"]
    assert frozen != DEFINITIONS.version
    first = system.run_until_stop(first_run)
    assert first.status == "done", first.error
    assert system.projects.settle(first_run) is not None
    _position, open_decisions = saved_decisions(system.store, statuses=("open",))
    [decision] = open_decisions
    assert decision.kind == "initial_prd"

    revision_run = system.orchestrator.answer_decision(
        decision.decision_id, "revise", "把用法说明写进初始 PRD", base_version=decision.version,
        command=_answer_command())
    assert revision_run is not None
    created = _run_created(system, revision_run)
    assert created["definitions_ref"] == _created(system, project_id, item_id)["definitions_ref"]
    assert created["definitions_version"] == frozen
    assert system.orchestrator.item_form(revision_run).definitions.version == frozen
    assert system.orchestrator.item_form(revision_run).definitions.department_labels["quality"] == RENAMED_LABEL
    system.close()


def test_the_frozen_organization_reads_back_as_the_same_definition(tmp_path):
    # 存进事实的那份合成结果读回来是同一份定义：逐文件相同，版本（内容摘要）也相同，重放与恢复读的是它
    system = _system(tmp_path / "loop", _three_departments_script(), resume_on_startup=False)
    project_id = system.projects.register("读回来", GOAL)
    item_id, _run_id = system.projects.start_work_item(project_id, "读回来的一份")
    created = _created(system, project_id, item_id)
    frozen = definitions_from_ref(system.artifacts, created["definitions_ref"])
    assert frozen is not None
    assert frozen.version == created["definitions_version"] == DEFINITIONS.version
    assert frozen.contents == DEFINITIONS.contents
    system.close()
