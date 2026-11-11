"""工单 #1647：形态卡要的内容不带项目也能读、长期目标可选、项目列表带职能数（项目的组织设计说明
「形态一键选用」「新建的入口」「项目页是循环图加对话」；总图第四节「接口」缝与「定义」缝）。

不带项目的查询 forms.list 回答发布带的形态清单：每份给形态标识、形态名、轮转方式与结束方式两个标记、
卡上的一句话与合成结果；它与 project.organization 的 forms 走同一段代码，对同一份形态给出相同内容。
长期目标在 project.create、project.onboard 里可以不写，project.set_goal 可以清空；不写时项目上下文里
没有「长期目标」这一行。projects.list 的每一行带这个项目现在组织的职能数。

层：模块层（真实的事件库与工件库，一个 LoopSystem；不跑完整循环，不起端口）。
守 R2（对外合同只增：新查询在注册表与接口快照两端登记，形态定义的格式只增一个字段，命令与事件载荷的
其余字段与键不变），第 3 组同时守 R1 的写入口不变式（不写、清空长期目标时项目上下文里没有这一项，
其余各行与事件载荷的键一字不变）。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.app.contracts import Accepted
from harness.app.form_commands import OrganizationAdopt
from harness.app.form_queries import ProjectOrganization
from harness.app.project_and_work_item_commands import ProjectSetGoal
from harness.app.project_commands import ProjectCreate
from harness.app.project_queries import ProjectsList
from harness.definitions import DEFAULT_FORM
from harness.models import ArtifactRef, ProjectEventType
from harness.runtime import SEVERAL_ROLES_DIRECT, SINGLE_ROLE_DIRECT, LoopSystem

GOAL = "做一个可以长期演进的逐行文本处理工具。"

# 卡上的一句话（项目的组织设计说明「形态一键选用」的表格）：写在发布带的形态定义里，查询照定义读出
CARD_LINES = {
    DEFAULT_FORM: "产品写需求、工程做、质检核验，放行才算完成",
    SINGLE_ROLE_DIRECT: "工程一个角色做完就结束，没有人核验",
    SEVERAL_ROLES_DIRECT: "工程做并交付，要求不清就问产品，没有人核验",
}


def _open(data_dir) -> tuple[LoopSystem, Application]:
    system = LoopSystem.for_testing(data_dir, FakeAdapter([]), resume_on_startup=False)
    return system, Application(system)


def _create(application: Application, name: str, *, goal: str | None = GOAL,
            form: str | None = None) -> Any:
    return asyncio.run(application.command("project.create", ProjectCreate(
        command_id=str(uuid.uuid4()), name=name, goal=goal, form=form), actor="user:local"))


def _set_goal(application: Application, project_id: str, goal: str | None) -> Any:
    version = application.query("projects.list", ProjectsList()).data.projects
    base = next(row.version for row in version if row.project_id == project_id)
    return asyncio.run(application.command("project.set_goal", ProjectSetGoal(
        command_id=str(uuid.uuid4()), base_version=base, project_id=project_id, goal=goal),
        actor="user:local"))


def _adopt(application: Application, project_id: str, form: str, *, base_version: str | None,
           changes: dict[str, Any], mode: str) -> Any:
    return asyncio.run(application.command("organization.adopt", OrganizationAdopt(
        command_id=str(uuid.uuid4()), project_id=project_id, form=form, changes=changes,
        reason="", base_version=base_version, mode=mode), actor="user:local"))


def _catalog(application: Application) -> dict[str, Any]:
    return {choice.form: choice for choice in application.query("forms.list", None).data.forms}


def _organization(application: Application, project_id: str) -> Any:
    return application.query("project.organization", ProjectOrganization(project_id=project_id)).data


def _rows(application: Application) -> dict[str, Any]:
    return {row.project_id: row for row in application.query("projects.list", ProjectsList()).data.projects}


def _context(system: LoopSystem, project_id: str, text: str = "做一点小事") -> str:
    """新建一个事项，读它冻结的项目上下文工件（新建事项时写下的那一份）"""
    _work_item_id, run_id = system.projects.start_work_item(project_id, text)
    created = next(event for event in system.store.list_project_events(project_id)
                   if event.type == ProjectEventType.WORK_ITEM_CREATED and event.payload["run_id"] == run_id)
    return system.artifacts.get_for_run(run_id, ArtifactRef(**created.payload["project_context_ref"])).decode("utf-8")


def _goal_changed_payloads(system: LoopSystem, project_id: str) -> list[dict[str, Any]]:
    return [event.payload for event in system.store.list_project_events(project_id)
            if event.type == ProjectEventType.PROJECT_GOAL_CHANGED]


def test_the_form_catalog_reads_without_a_project(data_dir):
    """不带项目读发布带的形态清单：三份形态都有两个标记、一句话与合成结果；发布带没有的形态不出现"""
    _system, application = _open(data_dir)
    forms = _catalog(application)
    assert set(forms) == {DEFAULT_FORM, SINGLE_ROLE_DIRECT, SEVERAL_ROLES_DIRECT}

    default = forms[DEFAULT_FORM]
    assert default.label == "产品 · 工程 · 质检"
    assert (default.routing, default.routing_label) == ("watched_outputs", "成果驱动")
    assert (default.ending, default.open_loop) == ("独立核验放行", False)
    assert [department.id for department in default.organization.departments] == [
        "product", "engineering", "quality"]

    single = forms[SINGLE_ROLE_DIRECT]
    assert (single.label, single.routing, single.routing_label) == ("工程", "direct", "直做")
    assert (single.ending, single.open_loop) == ("开环完成", True)
    assert [department.id for department in single.organization.departments] == ["engineering"]

    several = forms[SEVERAL_ROLES_DIRECT]
    assert (several.label, several.routing, several.ending) == ("产品 · 工程", "direct", "开环完成")
    assert [department.id for department in several.organization.departments] == ["product", "engineering"]

    for name, card_line in CARD_LINES.items():
        assert forms[name].card_line == card_line


def test_the_catalog_and_the_project_read_the_same_forms(data_dir):
    """同一份形态：forms.list 与 project.organization 的 forms 逐字段相同；项目的合成结果也相同"""
    _system, application = _open(data_dir)
    created = _create(application, "读同一份形态")
    assert isinstance(created, Accepted), created
    project_id = created.refs.project_id

    organization = _organization(application, project_id)
    catalog = _catalog(application)
    assert [choice.model_dump() for choice in organization.forms] == [
        choice.model_dump() for choice in catalog.values()]
    # 项目没有改动时，它现在的组织就是这份形态的合成结果
    assert organization.organization is not None
    assert organization.organization.model_dump() == catalog[organization.form].organization.model_dump()


def test_a_project_can_be_created_without_a_goal_and_the_goal_can_be_cleared(data_dir):
    """不写长期目标新建项目成功，项目上下文里没有这一行；写了照旧；清空以后同样没有"""
    system, application = _open(data_dir)
    without = _create(application, "不写目标的项目", goal=None)
    assert isinstance(without, Accepted), without
    without_id = without.refs.project_id
    assert _rows(application)[without_id].goal == ""

    context = _context(system, without_id)
    assert "长期目标" not in context
    assert context.splitlines()[0] == "项目：不写目标的项目"

    with_goal = _create(application, "写了目标的项目", goal=GOAL)
    assert isinstance(with_goal, Accepted), with_goal
    with_id = with_goal.refs.project_id
    assert _rows(application)[with_id].goal == GOAL
    assert f"长期目标：{GOAL}" in _context(system, with_id)

    cleared = _set_goal(application, with_id, None)
    assert isinstance(cleared, Accepted), cleared
    assert _rows(application)[with_id].goal == ""
    assert "长期目标" not in _context(system, with_id)
    # 清空写成一条 project_goal_changed：两个键都在，目标为空串（事件载荷的格式不变）
    [payload] = _goal_changed_payloads(system, with_id)
    assert payload["goal"] == ""
    assert payload["goal_ref"]


def test_projects_list_carries_the_department_count_of_the_current_organization(data_dir):
    """项目列表带现在组织的职能数：一个职能 1、默认 3、加上独立核验以后 2"""
    _system, application = _open(data_dir)
    default = _create(application, "默认形态的项目")
    single = _create(application, "一个职能的项目", form=SINGLE_ROLE_DIRECT)
    assert isinstance(default, Accepted) and isinstance(single, Accepted), (default, single)
    rows = _rows(application)
    assert rows[default.refs.project_id].department_count == 3
    assert rows[single.refs.project_id].department_count == 1

    started = _organization(application, single.refs.project_id)
    assert started.add_verifier is not None
    adopted = _adopt(application, single.refs.project_id, SINGLE_ROLE_DIRECT,
                     base_version=started.version, changes=started.add_verifier, mode="verifier")
    assert isinstance(adopted, Accepted), adopted
    assert _rows(application)[single.refs.project_id].department_count == 2
