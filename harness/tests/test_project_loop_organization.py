"""工单 #1381：事项冻结定义里的组织（画面与播放设计说明「画面跟着定义伸缩」的输入；形态与核验角色设计说明
「形态随事项冻结」；总图第四节「接口」「画面」缝）。

`project.loop` 为每个事项加一项「组织」：角色与显示名、哪些角色是核验角色与各核验谁、直做时交完成的角色、
关注关系、询问关系与打回关系。取值来自这个事项创建时冻结的那份定义——取法与工具许可、提案校验读事项所用
定义的做法相同（工单 #1165、#1392 的形态随事项冻结），不读进程加载时的那份。每项事实带给出它的事件位置与
来源种类，与 project.loop 已有的几个事实元素一样。

这份用例用测试里加载的另一份定义（把三部门里的一个角色改名、只留它一个、没有核验角色）建一个事项，
模块级的 DEFINITIONS 不替换。

层：模块层（真实事件库与真实的定义加载，每项只建一个事项、不跑三部门循环）。守 R2（对外合同只增：查询的
结果多了这一项，已有的字段不变）与 R3（形态随事项冻结：事项给出的组织是它创建时冻结的那一份）。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from harness.app import project_queries
from harness.app.application import Application
from harness.app.project_queries import ProjectLoop, WorkItemOrganization
from harness.definitions import DEFAULT_FORM, DEFINITIONS, DEFINITIONS_DIR, load_definitions
from harness.event_store import project_stream, run_stream
from harness.models import ProjectEventType
from harness.runtime import LoopSystem
from harness.tightening import WATCHED_OUTPUTS
from harness.write_path import NewProjectEvent

GOAL = "把文本按行处理清楚"
# 测试里加载的另一份定义：把工程这个角色改名、只留它一个，没有核验角色（工单 #1381 的验收第 2 条）
KEPT = "engineering"
RENAMED = "maker"
RENAMED_LABEL = "做工的"


def _renamed_definitions(directory: Path) -> Any:
    """一份改了名、只有一个角色的定义（用真实的定义加载读它，不替换模块级的定义）。

    从产品的定义目录复制一份，把三部门里的工程那一个改名、其余两个去掉，核验声明写明没有核验角色；
    工具、规则与事项种类照旧，各表里只留这一个角色。用户输入与建档也由它接（三部门里那是产品的关注）
    """
    shutil.copytree(DEFINITIONS_DIR, directory)

    def load(name: str) -> dict[str, Any]:
        return json.loads((directory / name).read_text(encoding="utf-8"))

    def save(name: str, document: dict[str, Any]) -> None:
        (directory / name).write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

    organization = load("organization.json")
    kept = next(item for item in organization["departments"] if item["id"] == KEPT)
    organization["departments"] = [dict(kept, id=RENAMED, label=RENAMED_LABEL, roles=[RENAMED],
                                        watched=["user_input", *kept["watched"]])]
    # 两种事项的来源都由留下的这个角色接（工单 #1455）：接来源的部门要在这份定义里
    organization["sources"] = {"user_input": RENAMED, "onboarding": RENAMED}
    # 没有核验角色：写明空的核验声明，旧定义缺这一项时按三部门解释，那不是这份定义要的
    organization["verification"] = {"verifiers": []}
    save("organization.json", organization)
    save("roles.json", {RENAMED: load("roles.json")[KEPT]})

    work_items = load("work_items.json")
    for kind in work_items["kinds"].values():
        kind["departments"] = {RENAMED: kind["departments"][KEPT]}
    save("work_items.json", work_items)

    contracts = load("proposal_contracts.json")
    contracts["roles"] = {RENAMED: contracts["roles"][KEPT]}
    kinds = set(contracts["roles"][RENAMED]["kinds"])
    contracts["conditions"] = {name: _renamed_entries(value, KEPT, RENAMED)
                               for name, value in contracts["conditions"].items() if name in kinds}
    save("proposal_contracts.json", contracts)

    routings = load("routings.json")
    for routing in routings["routings"]:
        routing["departments"] = [RENAMED]
    save("routings.json", routings)

    rules = load("rules.json")
    save("rules.json", {(f"roles.{RENAMED}.visibility" if name == f"roles.{KEPT}.visibility" else name): value
                        for name, value in rules.items()
                        if name not in {"roles.product.visibility", "roles.quality.visibility"}})
    return load_definitions(directory)


def _renamed_entries(value: Any, old: str, new: str) -> Any:
    # 提案条件里的部门名（检查回执绑定谁的工作区）跟着改名
    if isinstance(value, dict):
        return {_renamed_entries(key, old, new): _renamed_entries(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_renamed_entries(item, old, new) for item in value]
    return new if value == old else value


def _system(data_dir: Path, forms: dict[str, Any] | None = None) -> LoopSystem:
    # 不跑循环：这几项只看事项创建时冻结的定义，假模型给空脚本即可
    return LoopSystem.for_testing(data_dir, None, forms=forms, resume_on_startup=False)


def _application(system: LoopSystem) -> Application:
    return Application(system)


def _set_form(system: LoopSystem, project_id: str, previous: str, form: str) -> None:
    # 改形态的命令在 #1402：这里经写入口直接写这条项目事件（与 test_forms_per_item 同一做法）
    system.writes.append(project_stream(project_id), NewProjectEvent(
        ProjectEventType.PROJECT_FORM_SET, {"previous_form": previous, "form": form, "reason": "换个形态"},
        actor="user:local"))


def _organization(application: Application, project_id: str, work_item_id: str,
                  at: int | None = None) -> WorkItemOrganization | None:
    item = application.query(
        "project.loop", ProjectLoop(project_id=project_id, work_item=work_item_id, at=at)).data.work_items[0]
    return item.organization


def _run_created_position(system: LoopSystem, run_id: str) -> int:
    # 冻结定义的那条事件（这个 run 的第一条事件）在事件日志里的位置
    return system.store.stream_events(run_stream(run_id), through_version=1)[0].position


def _item_created_position(system: LoopSystem, project_id: str, work_item_id: str) -> int:
    # 事项创建的那条项目流事件的位置：它同样冻结了形态名（还没有 run 的事项用它）
    return next(event.position for event in system.store.list_project_events(project_id)
                if event.type == ProjectEventType.WORK_ITEM_CREATED
                and event.payload["work_item_id"] == work_item_id)


def _pairs(relations: list[Any], *fields: str) -> list[tuple]:
    return [tuple(getattr(relation, field) for field in fields) for relation in relations]


# ---------------------------------------------------------------------------
# 验收第 1 条：默认定义的事项给出三个角色、质检是核验角色、三条关注关系、询问与打回关系


def test_the_default_definition_gives_three_roles_the_verifier_and_the_three_relations(data_dir):
    system = _system(data_dir)
    project_id = system.projects.register("组织", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    organization = _organization(_application(system), project_id, work_item_id)

    # 三个角色与它们的显示名，与定义文件一致
    assert [(role.id, role.label) for role in organization.roles] == [
        (department.id, department.label) for department in DEFINITIONS.organization.departments]
    assert organization.form == DEFAULT_FORM and organization.routing == DEFINITIONS.routing
    # 质检是核验角色，它核验工程的交付
    assert [(verifier.role, [(verified.role, verified.outcomes) for verified in verifier.verifies])
            for verifier in organization.verifiers] == [("quality", [("engineering", ["delivery_spec"])])]
    # 成果驱动以核验角色的放行结束，没有交完成的角色
    assert organization.completing is None
    # 三条关注关系：产品交的 PRD 送到工程与质检，工程交的交付送到质检（推出规则表）
    assert _pairs(organization.watched, "source", "recipient", "outcome") == [
        ("product", "engineering", "product_spec"),
        ("product", "quality", "product_spec"),
        ("engineering", "quality", "delivery_spec"),
    ]
    # 询问关系：三个角色都能问另外两个；打回关系：质检打回工程的那一版交付
    assert _pairs(organization.asks, "requester", "recipient") == [
        ("product", "engineering"), ("product", "quality"),
        ("engineering", "product"), ("engineering", "quality"),
        ("quality", "product"), ("quality", "engineering"),
    ]
    assert _pairs(organization.rejections, "verifier", "role", "outcome") == [
        ("quality", "engineering", "delivery_spec")]

    # 每项事实带给出它的事件位置与来源种类：给出它们的是把这份定义冻结进事项的那条事件（run_created）
    position = _run_created_position(system, run_id)
    refs = [role.ref for role in organization.roles]
    refs += [verifier.ref for verifier in organization.verifiers]
    refs += [relation.ref for relation in organization.watched]
    refs += [relation.ref for relation in organization.asks]
    refs += [relation.ref for relation in organization.rejections]
    assert {(ref.position, ref.source) for ref in refs} == {(position, "user")}


# ---------------------------------------------------------------------------
# 验收第 2 条：一份改了名、只有一个角色的定义建的事项给出这份定义的角色，交完成的是它，没有核验角色


def test_a_single_renamed_role_gives_its_own_role_and_hands_in_completion(tmp_path, data_dir):
    definitions = _renamed_definitions(tmp_path / "single")
    forms = {DEFAULT_FORM: (DEFINITIONS, WATCHED_OUTPUTS), "single": (definitions, WATCHED_OUTPUTS)}
    system = _system(data_dir, forms)
    project_id = system.projects.register("一个角色", GOAL)
    _set_form(system, project_id, DEFAULT_FORM, "single")
    work_item_id, _run_id = system.projects.start_work_item(project_id, "做一件事")
    organization = _organization(_application(system), project_id, work_item_id)

    assert organization.form == "single"
    assert [(role.id, role.label) for role in organization.roles] == [(RENAMED, RENAMED_LABEL)]
    # 直做（一个角色的组织）由它自己交完成
    assert organization.completing is not None and organization.completing.id == RENAMED
    # 没有核验角色：没有核验、没有打回；只有它一个角色，没有可问的对象
    assert organization.verifiers == [] and organization.rejections == [] and organization.asks == []
    # 关注的成果里没有别的角色交得出的（它只交交付），所以没有关注关系
    assert organization.watched == []


def test_the_default_item_keeps_its_own_organization_after_the_form_changed(tmp_path, data_dir):
    # 形态随事项冻结：项目换了形态只影响之后新建的事项（验收第 3 条）
    definitions = _renamed_definitions(tmp_path / "single")
    forms = {DEFAULT_FORM: (DEFINITIONS, WATCHED_OUTPUTS), "single": (definitions, WATCHED_OUTPUTS)}
    system = _system(data_dir, forms)
    project_id = system.projects.register("换形态", GOAL)
    first, _first_run = system.projects.start_work_item(project_id, "第一个")
    _set_form(system, project_id, DEFAULT_FORM, "single")
    second, _second_run = system.projects.start_work_item(project_id, "第二个")
    application = _application(system)

    assert [role.id for role in _organization(application, project_id, first).roles] == [
        "product", "engineering", "quality"]
    assert [role.id for role in _organization(application, project_id, second).roles] == [RENAMED]


def test_the_organization_does_not_follow_the_definition_loaded_in_the_process(tmp_path, data_dir, monkeypatch):
    # 验收第 3 条：进程加载的那份定义在事项创建以后改变，查询给出的仍是事项冻结的那份
    system = _system(data_dir)
    project_id = system.projects.register("进程的定义", GOAL)
    work_item_id, _run_id = system.projects.start_work_item(project_id, "做一件事")
    monkeypatch.setattr(project_queries, "DEFINITIONS", _renamed_definitions(tmp_path / "single"))
    organization = _organization(_application(system), project_id, work_item_id)
    assert [role.id for role in organization.roles] == ["product", "engineering", "quality"]
    assert [verifier.role for verifier in organization.verifiers] == ["quality"]


# ---------------------------------------------------------------------------
# 验收第 4 条：回放到某个位置时，组织一项与那个位置一致


def test_replaying_before_the_item_gives_no_item_and_after_it_gives_the_same_organization(data_dir):
    system = _system(data_dir)
    project_id = system.projects.register("回放", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    application = _application(system)
    created_item = _item_created_position(system, project_id, work_item_id)
    created_run = _run_created_position(system, run_id)

    # 事项创建以前的位置：这个事项还不在列表里，没有组织一项可给
    before = application.query(
        "project.loop", ProjectLoop(project_id=project_id, at=created_item - 1)).data.work_items
    assert [item.work_item_id for item in before] == []
    # 事项创建了、run 还没有：组织一项来自事项创建的那条项目流事件（它同样冻结了形态名）
    early = _organization(application, project_id, work_item_id, at=created_item)
    assert [role.id for role in early.roles] == ["product", "engineering", "quality"]
    assert {role.ref.position for role in early.roles} == {created_item}
    # 冻结定义的那个 run 创建以后：组织一项给出同一份组织，来源换成 run_created
    after = _organization(application, project_id, work_item_id, at=created_run)
    assert _pairs(after.roles, "id") == _pairs(early.roles, "id")
    assert _pairs(after.watched, "source", "recipient", "outcome") == _pairs(
        early.watched, "source", "recipient", "outcome")
    assert {role.ref.position for role in after.roles} == {created_run}
    # 现在读到的与回放到那个位置的一致
    assert _organization(application, project_id, work_item_id, at=created_run) == _organization(
        application, project_id, work_item_id)


def test_an_item_whose_form_is_not_in_the_release_has_no_organization(tmp_path, data_dir):
    # 形态不在这一版发布里时不换一份定义顶替，组织一项为空（项目的组织设计说明「冻结与升级」）
    definitions = _renamed_definitions(tmp_path / "single")
    system = _system(data_dir, {DEFAULT_FORM: (DEFINITIONS, WATCHED_OUTPUTS), "single": (definitions, WATCHED_OUTPUTS)})
    project_id = system.projects.register("不在发布里", GOAL)
    _set_form(system, project_id, DEFAULT_FORM, "single")
    work_item_id, _run_id = system.projects.start_work_item(project_id, "做一件事")
    # 换回不带这一份形态的实例读同一个数据目录
    reopened = _system(data_dir)
    assert _organization(_application(reopened), project_id, work_item_id) is None
