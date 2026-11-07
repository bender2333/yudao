"""工单 #1402：项目设置里「形态」的命令与查询（项目的组织设计说明「采用与历史」「模板一键选用」；
形态与核验角色设计说明「形态随事项冻结」；总图第四节「接口」缝与「定义」缝）。

organization.adopt 把项目现在用的形态换成发布带的某一份，带用户看到的组织版本，理由可以不写；改回就是再采用
一次原值。改动写成 #1392 定下的那条项目事件 project_form_set（原值、新值与理由），之后新建的事项按新的那一份
冻结，正在跑的不变。project.organization 回答项目现在用哪一份、它的组织版本、发布带的每一份形态（名字、一句
说明、有没有核验角色）与改动的历史。

层：集成层（每一条都开真实事件库与真实工作区；改回以后那一条跑完整的三部门循环，模型回答由假模型按部门给出）。
守 R2（对外合同只增：新命令与新查询在注册表与接口快照两端登记）与 R3（形态可换：生效、看得见、能改回、历史
在案，事项按创建时那一份运行）。

先后由事件决定，不用时长赌（测试分层 docs/design/test-pyramid.md「测试的写法」）：改形态、建事项、跑完依次进行，脚本按部门给出。
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from harness.adapters.fake import FakeAdapter
from harness.app.application import DEFAULT_REGISTRY, Application
from harness.app.contracts import Accepted, Rejected
from harness.app.form_commands import ORGANIZATION_ADOPT, OrganizationAdopt
from harness.app.form_queries import PROJECT_ORGANIZATION, ProjectOrganization
from harness.definitions import DEFAULT_FORM, DEFINITIONS, VerificationDeclaration
from harness.direct import SINGLE_ROLE_DIRECT
from harness.models import EventType, ProjectEventType
from harness.runtime import SEVERAL_ROLES_DIRECT, LoopSystem
from harness.tests import second_routing
from harness.tests.helpers import delivery_turn, product_spec, quality_turns
from harness.tightening import WATCHED_OUTPUTS

GOAL = "做一个可以长期演进的逐行文本处理工具。"

# 发布带的形态（工单 #1402）：三部门、测试目录里的任务池，以及一份没有核验角色的三部门副本
# （副本的定义内容与三部门相同，只有核验声明为空；发布带里的五份形态中「一个角色直做」就是这个样子）
OPEN_LOOP_FORM = "three_departments_without_verifier"
OPEN_LOOP_DEFINITIONS = DEFINITIONS.model_copy(update={
    "version": "sha256:three-departments-without-verifier",
    "organization": DEFINITIONS.organization.model_copy(
        update={"verification": VerificationDeclaration(verifiers=())}),
})
FORMS = {
    DEFAULT_FORM: (DEFINITIONS, WATCHED_OUTPUTS),
    OPEN_LOOP_FORM: (OPEN_LOOP_DEFINITIONS, WATCHED_OUTPUTS),
    second_routing.ROUTING_NAME: (second_routing.DEFINITIONS, second_routing.TIGHTENING),
}
# 发布里只剩三部门时的形态（现在这一份已经不在发布里的情形）：只带默认那一份
DEFAULT_ONLY = {DEFAULT_FORM: (DEFINITIONS, WATCHED_OUTPUTS)}


def _script() -> dict[str, list[Any]]:
    # 三部门跑完一个事项：产品交 PRD、工程交交付、质检先独立判断再放行
    return {
        "product": [product_spec()],
        "engineering": [delivery_turn(summary="补了用法一节")],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }


def _system(data_dir: Path, forms: dict[str, Any] | None = None) -> LoopSystem:
    return LoopSystem.for_testing(data_dir, FakeAdapter(_script()), forms=forms or FORMS,
                                  resume_on_startup=False)


def _adopt(application: Application, project_id: str, form: str, *, base_version: str | None,
           reason: str = "", changes: dict[str, Any] | None = None,
           command_id: str | None = None) -> Accepted | Rejected:
    return asyncio.run(application.command("organization.adopt", OrganizationAdopt(
        command_id=command_id or str(uuid.uuid4()), project_id=project_id, form=form,
        changes={} if changes is None else changes, reason=reason, base_version=base_version),
        actor="user:local"))


def _organization(application: Application, project_id: str):
    return application.query("project.organization", ProjectOrganization(project_id=project_id)).data


def _form_events(system: LoopSystem, project_id: str) -> list[Any]:
    return [event for event in system.store.list_project_events(project_id)
            if event.type == ProjectEventType.PROJECT_FORM_SET]


def _run_created(system: LoopSystem, run_id: str) -> dict[str, Any]:
    return next(event.payload for event in system.store.list_events(run_id)
                if event.type == EventType.RUN_CREATED)


def _created(system: LoopSystem, project_id: str, work_item_id: str) -> dict[str, Any]:
    return next(event.payload for event in system.store.list_project_events(project_id)
                if event.type == ProjectEventType.WORK_ITEM_CREATED
                and event.payload["work_item_id"] == work_item_id)


def _departments(system: LoopSystem, run_id: str) -> set[str]:
    return {event.department for event in system.store.list_events(run_id) if event.department is not None}


def test_changing_the_form_and_changing_back_writes_two_events_and_the_history_lists_them(tmp_path):
    # 验收第 1 条：把项目的形态改成另一份、再改回，两条项目事件的原值、新值与理由都对；查询的历史按顺序
    # 列出两次；改回以后新建的事项用三部门
    system = _system(tmp_path / "loop")
    application = Application(system)
    project_id = system.projects.register("换形态", GOAL)

    first = _adopt(application, project_id, second_routing.ROUTING_NAME,
                   base_version=_organization(application, project_id).version, reason="换成任务池试一轮")
    assert isinstance(first, Accepted), first
    # 改完以后查询报的是新的那一份与它的组织版本（没有改动时就是那份形态的定义版本）
    changed = _organization(application, project_id)
    assert (changed.form, changed.version) == (second_routing.ROUTING_NAME, second_routing.DEFINITIONS.version)

    # 改回就是再采用一次原值：理由可以不写（docs/design/project-organization.md「模板一键选用」）
    back = _adopt(application, project_id, DEFAULT_FORM, base_version=changed.version)
    assert isinstance(back, Accepted), back

    events = _form_events(system, project_id)
    assert [(event.payload["previous_form"], event.payload["form"], event.payload["reason"])
            for event in events] == [
        (DEFAULT_FORM, second_routing.ROUTING_NAME, "换成任务池试一轮"),
        (second_routing.ROUTING_NAME, DEFAULT_FORM, ""),
    ]
    assert {event.actor for event in events} == {"user:local"}

    # 查询的历史按顺序列出两次，原值、新值、理由、时间与谁改的都对得上那两条事件
    after = _organization(application, project_id)
    assert (after.form, after.version) == (DEFAULT_FORM, DEFINITIONS.version)
    assert [(record.previous_form, record.form, record.reason, record.actor, record.event_id)
            for record in after.history] == [
        (DEFAULT_FORM, second_routing.ROUTING_NAME, "换成任务池试一轮", "user:local", events[0].event_id),
        (second_routing.ROUTING_NAME, DEFAULT_FORM, "", "user:local", events[1].event_id),
    ]
    assert [record.at.isoformat() for record in after.history] == [event.created_at for event in events]

    # 改回以后新建的事项按三部门冻结并跑完：部门事件来自这三个部门，结束时是放行
    item_id, run_id = system.projects.start_work_item(project_id, "改回以后的一个事项")
    assert _created(system, project_id, item_id)["form"] == DEFAULT_FORM
    assert _run_created(system, run_id)["form"] == DEFAULT_FORM
    done = system.run_until_stop(run_id)
    assert done.status == "done", done.error
    assert _departments(system, run_id) == set(DEFINITIONS.departments)
    system.close()


def test_a_stale_current_value_and_an_unknown_form_are_refused_without_writing_an_event(tmp_path):
    # 验收第 2 条：当前值对不上、名字不在清单里，两种各被拒绝、不写事件，拒绝说明写明原因与可选的形态；
    # 不写理由照常改成功
    system = _system(tmp_path / "loop")
    application = Application(system)
    project_id = system.projects.register("拒绝的形态", GOAL)

    # 当前值对不上：带的是别的版本，拒绝并带上现在的版本
    stale = _adopt(application, project_id, second_routing.ROUTING_NAME, base_version="sha256:seen-elsewhere")
    assert isinstance(stale, Rejected)
    assert (stale.reason, stale.current_version) == ("stale_base", DEFINITIONS.version)
    assert _form_events(system, project_id) == []

    # 名字不在发布带的清单里：拒绝说明写明原因与可选的形态
    unknown = _adopt(application, project_id, "form_out_of_the_release", base_version=DEFINITIONS.version)
    assert isinstance(unknown, Rejected)
    assert unknown.reason == "not_allowed"
    assert "发布带里没有形态 form_out_of_the_release" in unknown.message
    for name in FORMS:
        assert name in unknown.message
    assert _form_events(system, project_id) == []

    # 这一版接受本项目的改动（工单 #1516）：改动留空之外，合法的一份改动照常采用，见 test_organization_adopt.py。
    # 不写理由照常改成功：事件里的理由为空
    accepted = _adopt(application, project_id, second_routing.ROUTING_NAME, base_version=DEFINITIONS.version)
    assert isinstance(accepted, Accepted), accepted
    [event] = _form_events(system, project_id)
    assert event.payload == {"previous_form": DEFAULT_FORM, "form": second_routing.ROUTING_NAME, "reason": "",
                             "changes": {}, "version": second_routing.DEFINITIONS.version}
    system.close()


def test_the_same_command_identity_does_not_write_a_second_event(tmp_path):
    # 验收第 3 条：同一个命令身份重发，不再写第二条事件（写入口登记命令身份，重发交回原来的接受结果，
    # duplicate 为真、位置相同）
    system = _system(tmp_path / "loop")
    application = Application(system)
    project_id = system.projects.register("重发", GOAL)
    command_id = str(uuid.uuid4())

    first = _adopt(application, project_id, second_routing.ROUTING_NAME,
                   base_version=DEFINITIONS.version, command_id=command_id)
    assert isinstance(first, Accepted) and not first.duplicate
    resent = _adopt(application, project_id, second_routing.ROUTING_NAME,
                    base_version=DEFINITIONS.version, command_id=command_id)
    assert isinstance(resent, Accepted) and resent.duplicate
    assert (resent.position, resent.command_id) == (first.position, first.command_id)
    assert len(_form_events(system, project_id)) == 1

    # 同一个身份换一份形态：内容不同，按 command_id_reused 拒绝，同样不写事件
    reused = _adopt(application, project_id, DEFAULT_FORM, base_version=second_routing.DEFINITIONS.version,
                    command_id=command_id)
    assert isinstance(reused, Rejected) and reused.reason == "command_id_reused"
    assert len(_form_events(system, project_id)) == 1
    system.close()


def test_the_query_lists_every_form_of_the_release_and_marks_the_one_without_a_verifier(tmp_path):
    # 验收第 4 条：查询列出发布带的每一份形态，标出哪一份没有核验角色（开环与否）
    system = _system(tmp_path / "loop")
    application = Application(system)
    project_id = system.projects.register("列出形态", GOAL)

    organization = _organization(application, project_id)
    assert organization.project_id == project_id
    # 从来没有改过形态：现在是默认的三部门，组织版本就是它这份定义的版本
    assert (organization.form, organization.version, organization.form_in_release) == (
        DEFAULT_FORM, DEFINITIONS.version, True)
    assert organization.history == []
    # 发布带的每一份都在清单里，按登记顺序
    assert [choice.form for choice in organization.forms] == list(FORMS)
    choices = {choice.form: choice for choice in organization.forms}
    for choice in organization.forms:
        assert choice.description.endswith("。") and choice.version
    # 有核验角色的那一份：标出核验角色，不开环
    assert (choices[DEFAULT_FORM].verifier_roles, choices[DEFAULT_FORM].open_loop) == (["quality"], False)
    assert "质检核验工程" in choices[DEFAULT_FORM].description
    # 没有核验角色的那一份：说明里写清楚以开环完成结束
    assert (choices[OPEN_LOOP_FORM].verifier_roles, choices[OPEN_LOOP_FORM].open_loop) == ([], True)
    assert "没有核验角色" in choices[OPEN_LOOP_FORM].description
    assert choices[OPEN_LOOP_FORM].version == "sha256:three-departments-without-verifier"
    # 现在这一份形态里的部门（工单 #1457）：标识、显示名与是不是核验角色，按定义里的顺序。
    # 页面的部门页签、看板列与默认部门按这一项取，不写死三个
    assert [(department.id, department.label, department.verifier)
            for department in organization.departments] == [
        ("product", "产品", False), ("engineering", "工程", False), ("quality", "质检", True)]
    system.close()


def test_the_current_form_leaving_the_release_is_reported_and_can_be_repaired(tmp_path):
    # 自定的边界（设计说明「冻结与升级」最后一条）：项目现在用的那一份不在这次发布里时，查询照样回答，
    # 组织版本为空、form_in_release 为假；页面据此写明原因。用户这时不带版本也能选回发布里的那一份
    data_dir = tmp_path / "loop"
    system = _system(data_dir)
    application = Application(system)
    project_id = system.projects.register("形态不在发布里", GOAL)
    adopted = _adopt(application, project_id, second_routing.ROUTING_NAME, base_version=DEFINITIONS.version)
    assert isinstance(adopted, Accepted), adopted
    system.close()

    # 换一份不带这个形态的发布：项目记的仍是它，查询说它已经不在发布里
    gone = LoopSystem.for_testing(data_dir, FakeAdapter(_script()), forms=DEFAULT_ONLY,
                                  resume_on_startup=False)
    application = Application(gone)
    organization = _organization(application, project_id)
    assert organization.form == second_routing.ROUTING_NAME
    assert (organization.version, organization.form_in_release) == (None, False)
    # 现在这一份不在发布里时部门也为空：不拿别的形态的部门顶替；合成结果没有，拒绝项写明原因，
    # 两个一次点击的改动文档也不给（工单 #1516）
    assert organization.departments == []
    assert organization.organization is None
    assert [item.item for item in organization.rejections] == ["organization.json form"]
    assert organization.add_verifier is None and organization.remove_verifier is None
    assert [choice.form for choice in organization.forms] == [DEFAULT_FORM]

    # 这时候用户看到的版本就是「没有版本」：带上空版本选回发布里的那一份照常成立
    repaired = _adopt(application, project_id, DEFAULT_FORM, base_version=None, reason="换回发布里有的那一份")
    assert isinstance(repaired, Accepted), repaired
    after = _organization(application, project_id)
    assert (after.form, after.version, after.form_in_release) == (DEFAULT_FORM, DEFINITIONS.version, True)
    assert [(record.previous_form, record.form) for record in after.history] == [
        (DEFAULT_FORM, second_routing.ROUTING_NAME), (second_routing.ROUTING_NAME, DEFAULT_FORM)]
    gone.close()


def test_the_query_answers_from_the_release_the_cli_loaded_without_an_assembly(tmp_path):
    # 只读打开（命令行的 --data-dir）没有组装处加载的形态：这条查询按发布带的登记处回答，同样列出每一份
    data_dir = tmp_path / "loop"
    system = _system(data_dir)
    project_id = system.projects.register("只读打开", GOAL)
    system.close()

    application = Application.open_readonly(data_dir)
    organization = _organization(application, project_id)
    assert (organization.form, organization.version, organization.form_in_release) == (
        DEFAULT_FORM, DEFINITIONS.version, True)
    # 发布带的三份形态都列出来（工单 #1395 加了单角色直做，#1454 加了几个角色直做）：
    # 说明与开环与否由每份定义得出
    assert [choice.form for choice in organization.forms] == [
        DEFAULT_FORM, SINGLE_ROLE_DIRECT, SEVERAL_ROLES_DIRECT]
    single = next(choice for choice in organization.forms if choice.form == SINGLE_ROLE_DIRECT)
    assert (single.verifier_roles, single.open_loop) == ([], True)
    assert single.description == "工程；没有核验角色，事项以开环完成结束。"
    several = next(choice for choice in organization.forms if choice.form == SEVERAL_ROLES_DIRECT)
    assert (several.verifier_roles, several.open_loop) == ([], True)
    assert several.description == "产品、工程；没有核验角色，事项以开环完成结束。"
    application.close()


def test_the_command_and_the_query_are_registered_with_the_reasons_they_can_return():
    # 验收第 5 条里的「缝」：命令与查询在注册表里，拒绝原因与刷新清单按声明登记（接口快照由
    # test_openapi_snapshot.py 核对）
    assert DEFAULT_REGISTRY.commands["organization.adopt"] is ORGANIZATION_ADOPT
    assert DEFAULT_REGISTRY.reasons("organization.adopt") == (
        "not_found", "stale_base", "project_archived", "not_allowed", "command_id_reused")
    assert DEFAULT_REGISTRY.queries["project.organization"] is PROJECT_ORGANIZATION
    assert PROJECT_ORGANIZATION.changed_by == (ProjectEventType.PROJECT_FORM_SET,)
