"""工单 #1516：采用带改动（项目的组织设计说明「采用与历史」「形态一键选用」；形态与核验角色设计说明
「形态随事项冻结」；总图第四节「接口」缝与「定义」缝）。

organization.adopt 接受本项目的改动：采用时重新合成、过同一套结构校验，有拒绝项时拒绝；组织版本是合成结果的
内容摘要，用户看到的版本对不上时拒绝；同一命令身份重发不重做。三条路（换模板、加或去掉核验角色、高级）里
换模板与核验角色这两条的理由可以不写，高级的理由为空时拒绝。project.organization 给出合成结果与每项来源、
版本、历史（原值、新值、原版本、新版本、理由、差异）与发布带的形态清单；改回就是把那一条的形态与改动再采用
一次。换模板时本项目有改动：organization.draft 给出会丢掉哪些，命令本身不拦。

层：模块层（真实事件库与应用层命令、查询，不跑部门循环）。守 R2（对外合同只增：命令与查询只加字段，旧的
项目事件照样能读、重放结果不变）与 R3（形态可换：采用、历史、改回与每项来源都看得见，组织版本跟着合成结果）。

先后由事件决定，不用时长赌（测试分层 docs/design/test-pyramid.md「测试的写法」）：采用、再采用、读查询依次进行。
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from harness.app.application import Application
from harness.app.contracts import Accepted, Rejected
from harness.app.form_commands import OrganizationAdopt
from harness.app.form_queries import OrganizationDraft, ProjectOrganization
from harness.definitions import DEFAULT_FORM
from harness.event_store import project_stream
from harness.models import ProjectEventType
from harness.project_projection import replay_project, saved_project
from harness.runtime import LoopSystem, SEVERAL_ROLES_DIRECT, SINGLE_ROLE_DIRECT
from harness.write_path import NewProjectEvent

GOAL = "做一个可以长期演进的逐行文本处理工具。"


def _system(data_dir: Path) -> LoopSystem:
    # 不跑循环：这一张只看采用、历史与查询，模型回答用不到
    return LoopSystem.for_testing(data_dir, None, resume_on_startup=False)


def _application(system: LoopSystem) -> Application:
    return Application(system)


def _adopt(application: Application, project_id: str, form: str, *, base_version: str | None,
           changes: dict[str, Any] | None = None, reason: str = "", mode: str = "template",
           command_id: str | None = None) -> Accepted | Rejected:
    return asyncio.run(application.command("organization.adopt", OrganizationAdopt(
        command_id=command_id or str(uuid.uuid4()), project_id=project_id, form=form,
        changes={} if changes is None else changes, reason=reason, base_version=base_version, mode=mode),
        actor="user:local"))


def _organization(application: Application, project_id: str):
    return application.query("project.organization", ProjectOrganization(project_id=project_id)).data


def _form_events(system: LoopSystem, project_id: str) -> list[Any]:
    return [event for event in system.store.list_project_events(project_id)
            if event.type == ProjectEventType.PROJECT_FORM_SET]


def _version(system: LoopSystem, form: str) -> str:
    return system.forms[form].definitions.version


# ---------------------------------------------------------------------------
# 验收第 1 条：一个角色直做的项目加上核验角色不写理由成功，历史多一条；再去掉，历史都在，组织回到原来的版本


def test_adding_and_removing_a_verifier_role_keeps_the_history_and_returns_to_the_same_version(tmp_path):
    system = _system(tmp_path / "loop")
    application = _application(system)
    project_id = system.projects.register("加一个核验角色", GOAL)
    single = _version(system, SINGLE_ROLE_DIRECT)

    # 先换成「一个角色直做」：换模板，形态名加空改动，理由不写
    first = _adopt(application, project_id, SINGLE_ROLE_DIRECT,
                   base_version=_organization(application, project_id).version)
    assert isinstance(first, Accepted), first
    started = _organization(application, project_id)
    assert (started.form, started.version) == (SINGLE_ROLE_DIRECT, single)
    assert [(department.id, department.origin) for department in started.departments] == [("engineering", "release")]
    # 没有核验角色：查询给出「加一个核验角色」的改动，没有「去掉」；加的是发布里的质检，核验工程交完成的那一份
    assert started.remove_verifier is None
    addition = started.add_verifier
    assert addition is not None
    [added_department] = addition["add_departments"]
    assert (added_department["id"], added_department["label"]) == ("quality", "质检")
    assert added_department["watched"] == []
    assert "submit_completion_review" in added_department["tools"]
    assert addition["verification"]["verifiers"] == [
        {"role": "quality", "verifies": [{"role": "engineering", "outcomes": ["completion"]}]}]
    assert addition["verification"]["write_scopes"]["quality"] == {
        "scope": "check_materials", "paths": [".yudao-qa-tests"]}

    # 加上它：这一次走「加或去掉核验角色」，理由不写也成功
    with_verifier = _adopt(application, project_id, SINGLE_ROLE_DIRECT,
                           base_version=started.version, changes=addition, mode="verifier")
    assert isinstance(with_verifier, Accepted), with_verifier
    after_add = _organization(application, project_id)
    assert len(after_add.history) == 2
    assert [(department.id, department.origin) for department in after_add.departments] == [
        ("engineering", "release"), ("quality", "added")]
    assert after_add.organization is not None
    assert [(item.verifier, item.verified, item.outcome)
            for item in after_add.organization.verification] == [("quality", "engineering", "completion")]
    assert after_add.version != single
    # 这次采用带上了改动与版本：事件里原值、新值、理由、改动与版本都对
    event = _form_events(system, project_id)[-1]
    assert event.payload == {
        "previous_form": SINGLE_ROLE_DIRECT, "form": SINGLE_ROLE_DIRECT, "reason": "",
        "changes": addition, "version": after_add.version}
    # 历史第二条：原版本是上一次的，新版本是合成结果的摘要；差异里看得到加进来的部门与核验关系
    record = after_add.history[-1]
    assert (record.previous_version, record.version, record.changes) == (single, after_add.version, addition)
    differences = {(item.item, item.before, item.after) for item in record.diff}
    assert ("add_departments.quality.label", "", "质检") in differences
    assert ("verification.verifiers", "", "quality→engineering:completion") in differences

    # 去掉它：查询给出「去掉核验角色」的改动，采用以后组织回到原来的版本，历史三条都在
    removal = after_add.remove_verifier
    assert removal is not None and after_add.add_verifier is None
    removed = _adopt(application, project_id, SINGLE_ROLE_DIRECT,
                     base_version=after_add.version, changes=removal, mode="verifier")
    assert isinstance(removed, Accepted), removed
    restored = _organization(application, project_id)
    assert (restored.form, restored.version) == (SINGLE_ROLE_DIRECT, single)
    assert [department.id for department in restored.departments] == ["engineering"]
    assert [department.origin for department in restored.departments] == ["release"]
    assert len(restored.history) == 3
    assert [(record.previous_form, record.form) for record in restored.history] == [
        (DEFAULT_FORM, SINGLE_ROLE_DIRECT), (SINGLE_ROLE_DIRECT, SINGLE_ROLE_DIRECT),
        (SINGLE_ROLE_DIRECT, SINGLE_ROLE_DIRECT)]
    assert (restored.history[-1].previous_version, restored.history[-1].version) == (after_add.version, single)
    assert restored.history[-1].changes == removal
    # 去掉以后又回到「没有核验角色」：查询重新给出加的那一份
    assert restored.add_verifier is not None
    system.close()


def test_the_several_roles_form_can_add_and_remove_a_verifier_role(tmp_path):
    # 几个角色直做也备着核验角色的那一套：加进来的是质检，核验交完成的工程（产品不交完成）
    system = _system(tmp_path / "loop")
    application = _application(system)
    project_id = system.projects.register("几个角色加核验", GOAL)
    switched = _adopt(application, project_id, SEVERAL_ROLES_DIRECT,
                      base_version=_organization(application, project_id).version)
    assert isinstance(switched, Accepted), switched
    started = _organization(application, project_id)
    addition = started.add_verifier
    assert addition is not None
    assert addition["verification"]["verifiers"] == [
        {"role": "quality", "verifies": [{"role": "engineering", "outcomes": ["completion"]}]}]
    added = _adopt(application, project_id, SEVERAL_ROLES_DIRECT, base_version=started.version,
                   changes=addition, mode="verifier")
    assert isinstance(added, Accepted), added
    after_add = _organization(application, project_id)
    assert [department.id for department in after_add.departments] == ["product", "engineering", "quality"]
    assert after_add.remove_verifier is not None
    removed = _adopt(application, project_id, SEVERAL_ROLES_DIRECT, base_version=after_add.version,
                     changes=after_add.remove_verifier, mode="verifier")
    assert isinstance(removed, Accepted), removed
    assert _organization(application, project_id).version == _version(system, SEVERAL_ROLES_DIRECT)
    system.close()


# ---------------------------------------------------------------------------
# 验收第 2 条：走高级的采用理由为空被拒绝；换模板不写理由成功


def test_the_advanced_path_needs_a_reason_and_changing_the_template_does_not(tmp_path):
    system = _system(tmp_path / "loop")
    application = _application(system)
    project_id = system.projects.register("两条路的理由", GOAL)

    # 换模板：不写理由成功（默认就是换模板这一条路）
    template = _adopt(application, project_id, SINGLE_ROLE_DIRECT,
                      base_version=_organization(application, project_id).version, reason="")
    assert isinstance(template, Accepted), template
    written = len(_form_events(system, project_id))

    # 高级：理由为空（只有空白也算没写）时拒绝，不写事件
    current = _organization(application, project_id)
    refused = _adopt(application, project_id, SINGLE_ROLE_DIRECT, base_version=current.version,
                     changes={"departments": {"engineering": {"label": "开发"}}}, reason="  ", mode="advanced")
    assert isinstance(refused, Rejected) and refused.reason == "not_allowed"
    assert "理由" in refused.message
    assert len(_form_events(system, project_id)) == written

    # 高级：写了理由成功，改动生效，来源标成本项目改过
    accepted = _adopt(application, project_id, SINGLE_ROLE_DIRECT, base_version=current.version,
                      changes={"departments": {"engineering": {"label": "开发"}}},
                      reason="把工程改名为开发", mode="advanced")
    assert isinstance(accepted, Accepted), accepted
    renamed = _organization(application, project_id)
    assert [(department.id, department.label, department.origin)
            for department in renamed.departments] == [("engineering", "开发", "changed")]
    assert renamed.history[-1].reason == "把工程改名为开发"
    assert renamed.history[-1].changes == {"departments": {"engineering": {"label": "开发"}}}
    assert renamed.changes == {"departments": {"engineering": {"label": "开发"}}}

    # 说得与带的东西对不上时同样拒绝：换模板不能带改动，核验角色那一条不能是空改动
    written = len(_form_events(system, project_id))
    template_with_changes = _adopt(application, project_id, SINGLE_ROLE_DIRECT,
                                   base_version=renamed.version,
                                   changes={"departments": {"engineering": {"label": "又改名"}}},
                                   mode="template")
    assert isinstance(template_with_changes, Rejected) and template_with_changes.reason == "not_allowed"
    assert "空改动" in template_with_changes.message
    verifier_without_changes = _adopt(application, project_id, SINGLE_ROLE_DIRECT,
                                      base_version=renamed.version, mode="verifier")
    assert isinstance(verifier_without_changes, Rejected) and verifier_without_changes.reason == "not_allowed"
    assert "改动由查询给出" in verifier_without_changes.message
    assert len(_form_events(system, project_id)) == written
    system.close()


# ---------------------------------------------------------------------------
# 验收第 3 条：看到的版本已被别处改过时被拒绝并带现在的版本；有拒绝项的改动被拒绝并写明哪一项，都不写事件


def test_a_stale_version_and_a_rejected_change_are_refused_without_writing_an_event(tmp_path):
    system = _system(tmp_path / "loop")
    application = _application(system)
    project_id = system.projects.register("拒绝", GOAL)
    current = _organization(application, project_id)

    # 看到的版本对不上：拒绝并带上现在的版本
    stale = _adopt(application, project_id, SINGLE_ROLE_DIRECT, base_version="sha256:seen-elsewhere")
    assert isinstance(stale, Rejected)
    assert (stale.reason, stale.current_version) == ("stale_base", current.version)
    assert _form_events(system, project_id) == []

    # 有拒绝项的改动：新增部门缺自己的三样说明，拒绝说明写明是哪一项；同样不写事件
    rejected = _adopt(application, project_id, DEFAULT_FORM, base_version=current.version,
                      changes={"add_departments": [{"id": "design", "label": "设计"}]},
                      reason="加一个设计部门", mode="advanced")
    assert isinstance(rejected, Rejected) and rejected.reason == "not_allowed"
    for field in ("target", "evidence", "work"):
        assert f"add_departments[0].{field}" in rejected.message
    assert "它对什么负责" in rejected.message
    assert _form_events(system, project_id) == []

    # 改动文档不合法（未知字段）时同样拒绝，写明是哪一项
    unknown = _adopt(application, project_id, DEFAULT_FORM, base_version=current.version,
                     changes={"unknown_section": {}}, reason="试一下未知字段", mode="advanced")
    assert isinstance(unknown, Rejected) and unknown.reason == "not_allowed"
    assert "unknown_section" in unknown.message
    assert _form_events(system, project_id) == []

    # 拒绝项拒绝的是这次提交，项目现在的组织没有变
    assert _organization(application, project_id).version == current.version
    system.close()


# ---------------------------------------------------------------------------
# 验收第 4 条：同一命令身份重发不写第二条事件


def test_the_same_command_identity_does_not_write_a_second_event(tmp_path):
    system = _system(tmp_path / "loop")
    application = _application(system)
    project_id = system.projects.register("重发", GOAL)
    command_id = str(uuid.uuid4())
    version = _organization(application, project_id).version

    first = _adopt(application, project_id, SINGLE_ROLE_DIRECT, base_version=version, command_id=command_id)
    assert isinstance(first, Accepted) and not first.duplicate
    resent = _adopt(application, project_id, SINGLE_ROLE_DIRECT, base_version=version, command_id=command_id)
    assert isinstance(resent, Accepted) and resent.duplicate
    assert (resent.position, resent.command_id) == (first.position, first.command_id)
    assert len(_form_events(system, project_id)) == 1

    # 同一个身份换一份形态：内容不同，按 command_id_reused 拒绝，同样不写事件
    reused = _adopt(application, project_id, DEFAULT_FORM, base_version=version, command_id=command_id)
    assert isinstance(reused, Rejected) and reused.reason == "command_id_reused"
    assert len(_form_events(system, project_id)) == 1
    system.close()


# ---------------------------------------------------------------------------
# 验收第 5 条：老项目事件（没有改动与版本字段）照样能读，重放结果不变


def test_old_project_form_events_without_changes_and_version_are_read_and_replayed(tmp_path):
    system = _system(tmp_path / "loop")
    application = _application(system)
    project_id = system.projects.register("旧事件", GOAL)
    # 旧版本写下的形态改动：只有原值、新值与理由
    system.writes.append(project_stream(project_id), NewProjectEvent(
        ProjectEventType.PROJECT_FORM_SET,
        {"previous_form": DEFAULT_FORM, "form": SINGLE_ROLE_DIRECT, "reason": "旧事件的写法"},
        actor="user:local"))

    organization = _organization(application, project_id)
    assert (organization.form, organization.version) == (SINGLE_ROLE_DIRECT, _version(system, SINGLE_ROLE_DIRECT))
    assert organization.changes == {}
    # 历史照旧读得出：改动为空、新版本为空，原版本是默认形态的版本；差异只有形态名这一项
    [record] = organization.history
    assert (record.previous_form, record.form, record.reason) == (
        DEFAULT_FORM, SINGLE_ROLE_DIRECT, "旧事件的写法")
    assert (record.previous_version, record.version, record.changes) == (
        _version(system, DEFAULT_FORM), None, {})
    assert [(item.item, item.before, item.after) for item in record.diff] == [
        ("form", DEFAULT_FORM, SINGLE_ROLE_DIRECT)]
    # 查询给出的两个改动文档：没有核验角色，给出「加一个核验角色」
    assert organization.add_verifier is not None and organization.remove_verifier is None

    # 重放项目流得到同一份投影：旧事件没有改动与版本，读取不依赖它们
    saved = saved_project(system.store, project_id)
    replayed = replay_project(system.store, project_id)
    assert saved is not None and replayed is not None
    assert replayed.canonical_state() == saved.canonical_state()
    system.close()


# ---------------------------------------------------------------------------
# 验收第 5 条（续）：换模板时本项目有改动，查询给出会丢掉哪些；命令本身不拦


def test_changing_the_template_reports_the_changes_it_would_drop_and_does_not_block(tmp_path):
    system = _system(tmp_path / "loop")
    application = _application(system)
    project_id = system.projects.register("换模板会丢掉哪些", GOAL)
    # 先在本项目里把质检改名（高级：写理由）
    adopted = _adopt(application, project_id, DEFAULT_FORM,
                     base_version=_organization(application, project_id).version,
                     changes={"departments": {"quality": {"label": "验收"}}},
                     reason="把质检改名为验收", mode="advanced")
    assert isinstance(adopted, Accepted), adopted
    current = _organization(application, project_id)
    assert [(department.id, department.label, department.origin)
            for department in current.departments][-1] == ("quality", "验收", "changed")

    # 换模板（改动留空）的草稿：给出会丢掉哪些，采用本身不写拒绝项
    draft = application.query("organization.draft", OrganizationDraft(
        project_id=project_id, form=SINGLE_ROLE_DIRECT, changes="{}")).data
    assert draft.discarded == ["改部门 quality 的显示名"]
    assert draft.rejections == [] and draft.organization is not None
    # 把这一项一起带上（同一份改动）时没有会丢掉的项
    kept = application.query("organization.draft", OrganizationDraft(
        project_id=project_id, form=DEFAULT_FORM,
        changes='{"departments": {"quality": {"label": "验收"}}}')).data
    assert kept.discarded == []

    # 命令本身不拦：换模板照常成功，项目的改动清空，组织版本回到那份形态的版本
    switched = _adopt(application, project_id, SINGLE_ROLE_DIRECT, base_version=current.version)
    assert isinstance(switched, Accepted), switched
    after = _organization(application, project_id)
    assert (after.form, after.version, after.changes) == (
        SINGLE_ROLE_DIRECT, _version(system, SINGLE_ROLE_DIRECT), {})
    assert after.history[-1].diff[-1].item == "form"
    assert {(item.item, item.before, item.after) for item in after.history[-1].diff} >= {
        ("form", DEFAULT_FORM, SINGLE_ROLE_DIRECT),
        ("departments.quality.label", "验收", "")}
    system.close()


# ---------------------------------------------------------------------------
# 查询的一端：发布带的清单、合成结果与版本、每项的来源


def test_the_query_lists_the_release_the_composed_organization_and_each_items_origin(tmp_path):
    system = _system(tmp_path / "loop")
    application = _application(system)
    project_id = system.projects.register("查询的组织", GOAL)
    organization = _organization(application, project_id)
    # 发布带的每一份都在清单里（按登记顺序），现在这一份三部门没有改动：合成结果就是它本身
    assert [choice.form for choice in organization.forms] == [DEFAULT_FORM, SINGLE_ROLE_DIRECT, SEVERAL_ROLES_DIRECT]
    assert (organization.form, organization.version, organization.form_in_release) == (
        DEFAULT_FORM, _version(system, DEFAULT_FORM), True)
    assert organization.organization is not None
    assert organization.organization.version == organization.version
    assert organization.rejections == []
    assert [department.id for department in organization.departments] == list(
        system.forms[DEFAULT_FORM].definitions.departments)
    assert {department.origin for department in organization.departments} == {"release"}
    system.close()
