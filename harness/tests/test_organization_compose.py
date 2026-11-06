# 合成与校验草稿（工单 #1515，项目的组织设计说明「组织是形态加本项目的改动」「合成规则」「草稿与校验」
# 「拒绝与提醒」；总图第四节「定义」缝）。
#
# 守 R2：定义的格式与对外合同——一份组织是发布带的一份形态加本项目的改动，改动按身份只写不同的项；
# 合成结果的版本是内容的摘要，改动为空时等于形态的定义版本；改名只改显示名，身份不变。
# 守 R3：本阶段已走到的行为——去掉部门以后事项以开环完成结束；校验草稿只读不写。
# 守 R1：结构校验的不变式——关注的成果有部门交、事项能结束、运行工作区只有一个写入者；改动的文档不接受
# 未知的字段、这个发布没有的工具与轮转方式。
#
# 合成、提醒与结束说明都用发布带的形态与内存里的改动；「校验草稿不写入」与「拒绝项与提醒」那几条要一个
# 数据目录与项目，属于模块层（临时目录与事件库）。

import json
from copy import deepcopy
from pathlib import Path

import pytest

from harness import organization_compose
from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.app.form_queries import OrganizationDraft
from harness.app.project_queries import NotFound, QueryInputInvalid
from harness.definitions import (
    DEFINITIONS, DefinitionError, OrganizationChanges, definitions_from_contents, load_definitions,
    organization_change_issues, parse_organization_changes,
)
from harness.runtime import LoopSystem

TASK_POOL = Path(__file__).parent / "task_pool_definitions"


def _changes(payload) -> OrganizationChanges:
    # 一份合法的改动文档（不合法的文档由下面的用例单独核对）
    changes, issues = parse_organization_changes(payload)
    assert issues == [] and changes is not None, issues
    return changes


def _compose(payload):
    return organization_compose.compose(DEFINITIONS, _changes(payload))


def _without_quality() -> OrganizationChanges:
    # 去掉质检的改动：页面在编辑时把别的部门对它交出的成果的关注一起去掉，写进改动（「合成规则」第 5 条）
    return _changes({
        "remove_departments": ["quality"],
        "departments": {"product": {"watched": {"remove": ["baseline_review"]}},
                        "engineering": {"watched": {"remove": ["defect_record"]}}}})


# R2：改动为空时合成结果与形态本身内容相同，版本等于形态的定义版本（验收第 1 条）
def test_empty_changes_compose_to_the_form_itself():
    composed = organization_compose.compose(DEFINITIONS, OrganizationChanges())
    assert composed == DEFINITIONS
    assert composed.version == DEFINITIONS.version
    assert organization_change_issues(DEFINITIONS, OrganizationChanges()) == []


# R2、R3：改名只改显示名，身份不变；核验关系、写入范围与角色都按身份跟随原来那一行部门（验收第 2 条）
def test_renaming_a_department_keeps_its_identity():
    composed = _compose({"departments": {"quality": {"label": "验收"}}})
    assert composed.department_labels["quality"] == "验收"
    assert "quality" in composed.departments and "验收" not in composed.departments
    assert composed.verifier_roles() == ("quality",)
    assert composed.rejection_edges() == DEFINITIONS.rejection_edges()
    assert composed.write_scope("quality") == DEFINITIONS.write_scope("quality")
    assert composed.role("quality") == DEFINITIONS.role("quality")
    assert composed.version != DEFINITIONS.version


# R2：给一个部门加工具；发布以后再加的工具也在，两个都在（验收第 2 条）
def test_adding_a_tool_keeps_the_tools_a_later_release_adds():
    composed = _compose({"departments": {"engineering": {"tools": {"add": ["read_range"]}}}})
    assert {"read_range", "bash"} <= set(composed.tools_for("engineering"))
    # 发布升级：工程多了一个发布带的工具（质检的 run_baseline_check），本项目加过的工具仍在
    contents = deepcopy(DEFINITIONS.contents)
    contents["roles.json"]["engineering"]["tools"].append("run_baseline_check")
    for kind in contents["work_items.json"]["kinds"].values():
        work = kind["departments"].get("engineering")
        if work is not None:
            work["tools"].append("run_baseline_check")
    upgrade = definitions_from_contents(contents)
    assert upgrade.version != DEFINITIONS.version
    later = organization_compose.compose(upgrade, _changes(
        {"departments": {"engineering": {"tools": {"add": ["read_range"]}}}}))
    assert {"run_baseline_check", "read_range", "bash"} <= set(later.tools_for("engineering"))


# R3：去掉质检，工程对缺陷记录的关注一起去掉，事项最后采纳的成果没有人核验，得到开环完成的提醒（验收第 3 条）
def test_removing_a_department_leaves_the_open_loop():
    changes = _without_quality()
    assert organization_change_issues(DEFINITIONS, changes) == []
    composed = organization_compose.compose(DEFINITIONS, changes)
    assert composed.departments == ("product", "engineering")
    assert "quality" not in composed.roles
    assert composed.verifier_roles() == ()
    assert composed.rejection_edges() == ()
    assert [item.departments for item in composed.routings.routings] == [("product", "engineering")]
    assert composed.watched_outputs("engineering") == ("product_spec", "guidance")
    finishes, open_loop = organization_compose.finish_statement(composed)
    assert open_loop is True and "开环完成" in finishes
    [reminder] = organization_compose.reminders(composed)
    assert reminder.kind == "open_loop" and "开环完成" in reminder.message


# R2：单值的项整项替换——事项的来源接哪个部门、轮转方式、可见范围与 Prompt；清单类的工具加进来时
# 提案合同跟着重算（「合成规则」第 1、2、3 条）
def test_single_valued_items_replace_and_a_submit_tool_brings_its_contract():
    composed = _compose({
        "departments": {"product": {
            "visibility": ["prior_round"], "prompt": "你是产品部门，只写要求。",
            "tools": {"add": ["submit_structure"]}}},
        "sources": {"user_input": "engineering", "onboarding": "engineering"},
        "routing": "watched_outputs"})
    assert dict(composed.organization.sources) == {"user_input": "engineering", "onboarding": "engineering"}
    assert composed.source_department("user_input") == "engineering"
    assert composed.role("product").visibility == ("prior_round",)
    assert composed.role("product").prompt == "你是产品部门，只写要求。"
    contract = composed.proposal_contract("product", "change")
    assert "submit_structure" in contract["submit_tools"] and "structure" in contract["kinds"]
    assert composed.routing == "watched_outputs"


# R2：新增成果种类写全内容；去掉一种时它从清单与路由认得的成果里一起去掉（「合成规则」第 5 条）
def test_outcome_kinds_can_be_added_and_removed():
    composed = _compose({"outcome_kinds": {
        "add": [{"id": "design_note", "label": "界面稿", "why": "设计部门交的界面稿"}],
        "remove": ["independent_judgement"]}})
    ids = [kind.id for kind in composed.outcome_kinds.kinds]
    assert "independent_judgement" not in ids and ids[-1] == "design_note"
    assert "independent_judgement" not in composed.outcome_kinds.groups[0].kinds


# R2：要去掉的对象在形态里已经不存在时这条改动不起作用（「合成规则」第 5 条）
def test_removing_what_the_form_no_longer_has_does_nothing():
    composed = _compose({"remove_departments": ["design"]})
    assert composed == DEFINITIONS


# R1：关注的成果没有部门交，拒绝并写明是哪个部门的第几项（拒绝第 4 条）
def test_a_watched_outcome_without_a_delivering_department_is_rejected():
    changes = _changes({
        "remove_departments": ["quality"],
        "departments": {"product": {"watched": {"remove": ["baseline_review"]}},
                        "engineering": {"watched": {"add": ["qa_review"], "remove": ["defect_record"]}}}})
    with pytest.raises(DefinitionError) as raised:
        organization_compose.compose(DEFINITIONS, changes)
    [issue] = raised.value.issues
    assert issue[0] == "organization.json" and issue[1] == "departments[1].watched[2]"
    assert "qa_review" in issue[2] and "没有部门交" in issue[2]


# R1：事项无法结束——去掉交最后采纳成果的部门，路由写明的成果没有部门交了（拒绝第 5 条）
def test_an_item_that_cannot_finish_is_rejected():
    with pytest.raises(DefinitionError) as raised:
        _compose({"remove_departments": ["engineering"]})
    messages = [issue[2] for issue in raised.value.issues]
    assert any("事项无法结束" in message and "delivery_spec" in message for message in messages), messages
    assert all(issue[0] in ("organization.json", "routings.json") for issue in raised.value.issues)


# R1：运行工作区有两个写入者，拒绝并写明是哪几个（拒绝第 7 条）
def test_two_workspace_writers_are_rejected():
    with pytest.raises(DefinitionError) as raised:
        _compose({"add_departments": [{"id": "design", "label": "设计", "target": "做界面",
                                       "evidence": "设计材料", "work": "设计", "tools": ["write_file"]}]})
    [issue] = raised.value.issues
    assert issue[:2] == ("organization.json", "verification.write_scopes")
    assert "运行工作区有两个写入者" in issue[2] and "engineering" in issue[2] and "design" in issue[2]


# R2：新增的部门缺三样说明时拒绝，逐项写明缺哪一样（拒绝第 8 条）
def test_a_new_department_must_state_the_three_statements():
    issues = organization_change_issues(DEFINITIONS, _changes(
        {"add_departments": [{"id": "design", "label": "设计"}]}))
    assert [item[:2] for item in issues] == [
        ("changes.json", "add_departments[0].target"),
        ("changes.json", "add_departments[0].evidence"),
        ("changes.json", "add_departments[0].work"),
    ]
    assert all("design" in item[2] or "设计" in item[2] for item in issues)


# R2：改动文档的未知字段、这个发布没有的工具与轮转方式各拒绝一次，写明是哪一项（拒绝第 10 条）
def test_unknown_fields_tools_and_routings_are_rejected():
    changes, issues = parse_organization_changes({"departments": {"quality": {"name": "验收"}}})
    assert changes is None
    [issue] = issues
    assert issue[:2] == ("changes.json", "departments.quality.name") and "未知的字段 name" in issue[2]

    issues = organization_change_issues(DEFINITIONS, _changes(
        {"departments": {"engineering": {"tools": {"add": ["teleport"]}}}}))
    assert [item[:2] for item in issues] == [("changes.json", "departments.engineering.tools.add[0]")]
    assert "这个发布没有的工具 teleport" in issues[0][2]

    issues = organization_change_issues(DEFINITIONS, _changes({"routing": "task_pool"}))
    assert [item[:2] for item in issues] == [("changes.json", "routing")]
    assert "这个发布没有的轮转方式 task_pool" in issues[0][2] and "watched_outputs" in issues[0][2]

    issues = organization_change_issues(DEFINITIONS, _changes(
        {"add_departments": [{"id": "engineering", "label": "工程", "target": "做", "evidence": "看",
                              "work": "做"}]}))
    assert [item[:2] for item in issues] == [("changes.json", "add_departments[0].id")]


# R2、R3：新增部门写全内容以后合成成功：部门与角色、提案合同、路由的部门清单都跟着改；
# 它不交成果，得到一条提醒（提醒第 5 条），不挡采用
def test_a_new_department_with_its_content_composes():
    composed = _compose({"add_departments": [{"id": "design", "label": "设计", "target": "做界面",
                                              "evidence": "设计材料与用户反馈", "work": "画稿与评审",
                                              "tools": ["read_file"], "watched": ["product_spec"]}]})
    [design] = [item for item in composed.organization.departments if item.id == "design"]
    assert (design.label, design.target, design.evidence, design.work) == (
        "设计", "做界面", "设计材料与用户反馈", "画稿与评审")
    assert "做界面" in composed.role("design").prompt
    assert composed.tools_for("design") == ("read_file",)
    assert composed.proposal_contract("design", "change")["submit_tools"] == []
    assert [item.departments for item in composed.routings.routings] == [
        ("product", "engineering", "quality", "design")]
    assert [item.kind for item in organization_compose.reminders(composed)] == ["no_outcomes"]


# R1：核验角色只核验中途的成果时给一条提醒，事项仍以开环完成结束（提醒第 1、2 条）
def test_a_verifier_of_a_midway_outcome_only_reminds():
    composed = _compose({"verification": {
        "verifiers": [{"role": "quality", "verifies": [{"role": "engineering", "outcomes": ["product_spec"]}]}],
        "write_scopes": {"quality": {"scope": "check_materials", "paths": [".yudao-qa-tests"]}}}})
    assert organization_compose.reminders(composed)[0].kind == "midway_verifier"
    finishes, open_loop = organization_compose.finish_statement(composed)
    assert open_loop is True and "开环完成" in finishes


# R2：轮转方式没有写明最后采纳的成果时，「事项怎么结束」由它自己的结束原因决定，不标开环
def test_a_routing_without_a_final_outcome_has_no_open_loop():
    pool = load_definitions(TASK_POOL)
    assert pool.routing_definition().final_outcome is None
    finishes, open_loop = organization_compose.finish_statement(pool)
    assert open_loop is None and "结束原因" in finishes


# R1：校验草稿不写任何事件，两次查询给出同一份结果（验收第 5 条）
def test_the_draft_query_writes_no_events(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([]))
    application = Application(system)
    try:
        project_id = system.projects.register("校验草稿", "把一件事做完")
        before = system.store.end_position()
        draft = OrganizationDraft(project_id=project_id, form="three_departments",
                                  changes=json.dumps({"departments": {"quality": {"label": "验收"}}}))
        first = application.query("organization.draft", draft)
        second = application.query("organization.draft", draft)
        assert first.data == second.data
        assert first.data.rejections == [] and first.data.organization is not None
        assert first.data.organization.departments[2].label == "验收"
        assert system.store.end_position() == before == first.position
        assert len(system.store.list_project_events(project_id)) == 1
    finally:
        application.close()


# R3：有拒绝项时不给合成结果、写明是哪一项；提醒不挡采用；未知的形态与项目各是一种输入问题
def test_the_draft_query_reports_rejections_reminders_and_input_errors(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([]))
    application = Application(system)
    try:
        project_id = system.projects.register("校验草稿", "把一件事做完")
        removed = application.query("organization.draft", OrganizationDraft(
            project_id=project_id, form="three_departments",
            changes=json.dumps({"remove_departments": ["quality"],
                                "departments": {"product": {"watched": {"remove": ["baseline_review"]}},
                                                "engineering": {"watched": {"remove": ["defect_record"]}}}})))
        assert removed.data.rejections == []
        assert [item.kind for item in removed.data.reminders] == ["open_loop"]
        assert removed.data.open_loop is True and "开环完成" in removed.data.finishes
        refused = application.query("organization.draft", OrganizationDraft(
            project_id=project_id, form="three_departments",
            changes=json.dumps({"departments": {"quality": {"name": "验收"}}})))
        assert refused.data.organization is None and refused.data.finishes is None
        assert "departments.quality.name" in refused.data.rejections[0].item
        with pytest.raises(QueryInputInvalid):
            application.query("organization.draft", OrganizationDraft(project_id=project_id, form="no_such_form"))
        with pytest.raises(QueryInputInvalid):
            application.query("organization.draft", OrganizationDraft(project_id=project_id,
                                                                      form="three_departments", changes="{"))
        with pytest.raises(NotFound):
            application.query("organization.draft", OrganizationDraft(project_id="no_such_project",
                                                                      form="three_departments"))
    finally:
        application.close()
