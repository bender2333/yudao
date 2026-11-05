# 工具许可与提案校验读这个事项所用的那份定义（工单 #1098，docs/design/skeleton-and-application.md「其他路由：骨架要满足的条件」）。
#
# 守 R1「工具调用先有许可」与「写入先过裁决」（docs/design/test-pyramid.md 「一个测试凭什么留」）：
# 一个工具能不能用、一份提案能不能接纳，只看交给它的那份定义里的工具、部门与提案种类，
# 不读模块加载时的那一份。用例自己造定义，只改「定义里有哪些工具、部门与提案种类」这一件事，
# 看许可与校验的决定跟着它变；不跑模型、不起运行，只在内存里判断，属于单元层。
#
# 核验声明（工单 #1388）：定义声明谁核验谁的哪种成果、角色的写入范围，答得出事项最后采纳的成果
# 是不是开环；加载时的核对把核验对象不存在、谁能拒绝谁有环的定义整份拒绝。这部分用例只换声明，
# 看查询与核对跟着它变。
#
# 事项的来源（工单 #1455）：每一种来源由哪个部门接写在定义里，事项开始时开始第一轮的是它；
# 旧定义没有写时两种来源都按关注用户输入的部门解释，没有这样的部门时加载拒绝。

from __future__ import annotations

import pytest
from pydantic import ValidationError

from harness import adjudication, kernel_events, submissions, tools, validation
from harness.actions import TreeFacts, WorkspaceFacts
from harness.definitions import (DEFINITIONS, LEGACY_VERIFICATION, Definitions, Tool, VerificationDeclaration,
                                 VerifiedOutcomes, VerifierRole, WriteScope, source_issues, verification_issues)
from harness.minimal_projection import fold_events
from harness.models import RunProjection, SessionRecord
from harness.path_rules import QA_TESTS_DIR
from harness.tightening import WATCHED_OUTPUTS

# 这些用例只判决定，不看提案内容：种类与部门的检查在格式与内容之前
_FACTS = TreeFacts(digest="sha256:0", files=(), checks=())


def _with_department_tools(definition: Definitions, department: str, names: list[str]) -> Definitions:
    # 一个部门在这个种类的活里能用的工具：角色清单与种类的工作项两处都写成同一份（工单 #1098：
    # tools_for 先看种类的工作项，没有才用角色清单，两处都要改，改动才在许可里看得到）
    roles = dict(definition.roles)
    roles[department] = definition.roles[department].model_copy(update={"tools": tuple(names)})
    kinds = dict(definition.work_items.kinds)
    work = kinds["change"]
    departments = dict(work.departments)
    departments[department] = work.departments[department].model_copy(update={"tools": tuple(names)})
    kinds["change"] = work.model_copy(update={"departments": departments})
    return definition.model_copy(
        update={"roles": roles, "work_items": definition.work_items.model_copy(update={"kinds": kinds})})


def _without_role_tool(definition: Definitions, department: str, name: str) -> Definitions:
    # 这份定义里，部门在这个种类的活里没有这个工具
    kept = [item for item in definition.tools_for(department) if item != name]
    return _with_department_tools(definition, department, kept)


def _with_extra_tool(definition: Definitions, name: str, department: str) -> Definitions:
    # 这份定义里多一个工具，并且写在这个部门在这个种类的活里
    probe = Tool(kind="environment", action="read",
                 description="读一份只在这份定义里有的材料", parameters={})
    widened = definition.model_copy(update={"tools": {**definition.tools, name: probe}})
    return _with_department_tools(widened, department, [*definition.tools_for(department), name])


def _without_tool(definition: Definitions, name: str) -> Definitions:
    # 这份定义里没有这个工具：它提交的提案种类跟着不在定义里
    return definition.model_copy(update={"tools": {item: tool for item, tool in definition.tools.items()
                                                   if item != name}})


def _without_department(definition: Definitions, department: str) -> Definitions:
    # 这份组织定义里没有这个部门
    organization = definition.organization
    departments = tuple(item for item in organization.departments if item.id != department)
    return definition.model_copy(
        update={"organization": organization.model_copy(update={"departments": departments})})


def _view(projection: RunProjection) -> validation.AdjudicationView:
    return validation.AdjudicationView(minimal=fold_events([]), state=projection)


def _basis(projection: RunProjection) -> adjudication.WorkBasis:
    return adjudication.WorkBasis(effective_contract_hash=None,
                                  input_version=projection.input_version, guidance_version=0)


def _permission(projection: RunProjection, name: str, department: str,
                definitions: Definitions | None = None, session_id: str | None = None,
                path: str = "README.md"):
    return adjudication.tool_permission(
        _view(projection), {"name": name, "id": "call-1", "args": {"path": path}},
        department=department, session_id=session_id, tightening=WATCHED_OUTPUTS,
        basis=_basis(projection), aborted=False, facts=WorkspaceFacts(), definitions=definitions)


def _decision(projection: RunProjection, proposal: dict, department: str,
              definitions: Definitions | None = None) -> validation.ProposalDecision:
    return validation.evaluate_proposal(
        _view(projection), department=department, proposal=proposal, facts=_FACTS,
        tightening=WATCHED_OUTPUTS, events=[], definitions=definitions)


def test_tool_permission_reads_the_matter_definition() -> None:
    projection = RunProjection()
    assert _permission(projection, "read_file", "engineering").allowed
    narrowed = _without_role_tool(DEFINITIONS, "engineering", "read_file")
    permission = _permission(projection, "read_file", "engineering", narrowed)
    assert not permission.allowed
    assert permission.reason == "engineering cannot use read_file"


def test_tool_permission_sees_a_tool_only_in_the_matter_definition() -> None:
    projection = RunProjection()
    widened = _with_extra_tool(DEFINITIONS, "read_matter_note", "engineering")
    assert not tools.has_tool("engineering", "read_matter_note")
    assert tools.has_tool("engineering", "read_matter_note", definitions=widened)
    assert _permission(projection, "read_matter_note", "engineering", widened).allowed
    refused = _permission(projection, "read_matter_note", "engineering")
    assert not refused.allowed
    assert refused.reason == "engineering cannot use read_matter_note"


def test_proposal_kind_comes_from_the_matter_definition() -> None:
    projection = RunProjection()
    narrowed = _without_tool(DEFINITIONS, "submit_review")
    decision = _decision(projection, {"kind": "qa_review"}, "quality", narrowed)
    assert [error.message for error in decision.errors] == ["unknown proposal kind: 'qa_review'"]
    current = _decision(projection, {"kind": "qa_review"}, "quality")
    assert all("unknown proposal kind" not in error.message for error in current.errors)


def test_proposal_department_comes_from_the_matter_definition() -> None:
    narrowed = _without_department(DEFINITIONS, "quality")
    decision = _decision(RunProjection(), {"kind": "qa_review"}, "quality", narrowed)
    assert [error.message for error in decision.errors] == ["unknown department: quality"]


def test_a_branch_session_judges_a_proposal_by_the_matter_definition() -> None:
    # 询问分支里的会话不能用提交提案的工具；「这个工具提交的是提案」也按事项所用的那份定义判
    # （工单 #1098，docs/design/skeleton-and-application.md「其他路由：骨架要满足的条件」）
    projection = RunProjection(run_id="run_branch", status="running",
                               ask_stack=[{"requester": "engineering", "recipient": "quality",
                                           "question": "这一项怎么验？", "branch_session_id": "ses_ask_qa"}])
    refused = _permission(projection, "submit_structure", "quality", session_id="ses_ask_qa")
    assert refused.reason == "The branch session cannot submit proposal submit_structure"
    narrowed = _without_tool(DEFINITIONS, "submit_structure")
    assert _permission(projection, "submit_structure", "quality", narrowed,
                       session_id="ses_ask_qa").reason == "quality cannot use submit_structure"


def test_the_loaded_definition_is_the_default() -> None:
    # 没有交定义时读的是模块加载的那一份：接缝的默认值不能把许可变成全部拒绝，也不能换一份定义
    assert tools.in_force(None) is DEFINITIONS
    assert tools.proposal_kind("submit_delivery") == "delivery_spec"


def _with_new_kind(definition: Definitions, department: str, tool_name: str,
                   kind: str) -> Definitions:
    # 这份定义里多一个提交类工具，它提交这个部门在这个种类的活里的一种新成果种类
    probe = Tool(kind="host", proposal=kind, description="交一份只在这份定义里有的成果", parameters={})
    widened = definition.model_copy(update={"tools": {**definition.tools, tool_name: probe}})
    return _with_department_tools(widened, department, [*definition.tools_for(department), tool_name])


def _event(type_: str, payload: dict) -> kernel_events.Event:
    return kernel_events.Event(
        event_id="evt_matter", run_id="run_matter", type=type_, role=None, parent_event_id=None,
        state_before="running", state_after="running", payload=payload, artifact_hashes=[],
        session_id="ses_engineering", provider=None, model=None, context_digest=None, stop_reason=None,
        error=None, created_at="2026-10-28T00:00:00+00:00", position=1, stream="run:run_matter",
        stream_version=1, project_id=None, work_item_id=None, department="engineering",
    )


def test_a_kind_only_in_the_matter_definition_is_accepted_with_a_generic_event() -> None:
    # 验收第 1 条（工单 #1098）：只在测试定义里声明的新工具与新成果种类，照常经过工具许可与提案校验被接纳；
    # 写下通用的接纳事件、带统一字段，最小投影里有它的当前版本；拿全局定义校验同一种类被拒绝
    widened = _with_new_kind(DEFINITIONS, "engineering", "submit_matter_note", "matter_note")
    projection = RunProjection(run_id="run_matter", kind="change",
                               sessions={"engineering": SessionRecord(
                                   session_id="ses_engineering", department="engineering", status="active")})
    # 工具许可：这个工具只在这份定义里
    permitted = _permission(projection, "submit_matter_note", "engineering", widened)
    assert permitted.allowed, permitted.reason
    assert not _permission(projection, "submit_matter_note", "engineering").allowed
    # 提案校验：种类只在这份定义里，内容就是提案的参数（路由不组装的种类）
    decision = _decision(projection, {"kind": "matter_note", "note": "只在这份定义里的成果"},
                         "engineering", widened)
    assert decision.accepted, [error.to_dict() for error in decision.errors]
    artifact = decision.artifact or {}
    assert artifact["kind"] == "matter_note"
    assert (artifact["issuer"], artifact["revision"], artifact["status"]) == ("engineering", 1, "active")
    assert artifact["content_hash"]
    # 接纳事件：通用的那一种，载荷带统一字段；最小投影按统一字段折叠出它的当前版本
    event_type, payload, _hashes = submissions.generic_acceptance(dict(artifact), tree_digest=_FACTS.digest)
    assert event_type == kernel_events.SkeletonEventType.ARTIFACT_ACCEPTED
    assert event_type in kernel_events.SKELETON_EVENTS
    assert payload["artifact_kind"] == "matter_note" and payload["artifact_version"] == 1
    assert payload["artifact_issuer"] == "engineering"
    assert payload["artifact_tree_digest"] == _FACTS.digest
    minimal = fold_events([_event(event_type, payload)])
    current = minimal.artifact("matter_note")
    assert current is not None and current.version == 1 and current.content_hash == artifact["content_hash"]
    # 同一种类拿全局定义校验被拒绝：说明读的是这个事项所用的那份定义
    refused = _decision(projection, {"kind": "matter_note", "note": "只在这份定义里的成果"}, "engineering")
    assert [error.message for error in refused.errors] == ["unknown proposal kind: 'matter_note'"]


def _declaration(verifiers=(), write_scopes=None) -> VerificationDeclaration:
    return VerificationDeclaration(verifiers=tuple(verifiers),
                                    write_scopes={} if write_scopes is None else dict(write_scopes))


def _declared(verifiers=(), write_scopes=None) -> Definitions:
    # 这份定义把核验声明换成给出的这一份（谁核验谁、写入范围）
    return DEFINITIONS.model_copy(update={"organization": DEFINITIONS.organization.model_copy(
        update={"verification": _declaration(verifiers, write_scopes)})})


def _issues(verifiers=(), write_scopes=None) -> list[tuple[str, str, str]]:
    # 加载时对这份核验声明报出的问题，成果种类取默认定义里的那些
    outcomes = {tool.proposal for tool in DEFINITIONS.tools.values() if tool.proposal is not None}
    return verification_issues(_declared(verifiers, write_scopes).organization, outcomes)


# 核验声明（工单 #1388）：默认定义里质检核验工程的交付、只写检查材料，普通事项最后采纳的成果
# 是交付，所以不是开环；去掉核验角色、或者核验角色只核验中途成果时，交付没有人核验，判断为开环
def test_the_default_definition_reads_the_verifier_the_delivery_and_the_write_scope() -> None:
    assert DEFINITIONS.verifier_roles() == ("quality",)
    assert DEFINITIONS.is_verifier("quality") and not DEFINITIONS.is_verifier("engineering")
    assert DEFINITIONS.verifiers_of("engineering", "delivery_spec") == ("quality",)
    assert DEFINITIONS.verifiers_of("engineering", "product_spec") == ()
    assert DEFINITIONS.rejection_edges() == (("quality", "engineering", "delivery_spec"),)
    assert DEFINITIONS.write_scope("quality") == WriteScope(scope="check_materials", paths=(QA_TESTS_DIR,))
    assert DEFINITIONS.write_scope("engineering") == WriteScope(scope="workspace")
    # 普通事项（work_items.json 的 change）最后采纳的成果是交付，所以这份定义下普通事项不是开环
    assert DEFINITIONS.work_item("change").label == "普通事项"
    assert not DEFINITIONS.is_open_loop("delivery_spec")
    # 旧定义没有写核验声明时读出的就是这一份：与今天写死的三部门相同
    assert DEFINITIONS.verification == LEGACY_VERIFICATION


def test_a_definition_without_a_verifier_marks_the_delivery_open_loop() -> None:
    # 验收第 2 条：去掉核验角色以后，事项最后采纳的成果没有人核验
    without = _declared(verifiers=())
    assert without.verifier_roles() == ()
    assert without.is_open_loop("delivery_spec")


def test_a_verifier_of_a_midway_outcome_leaves_the_delivery_open_loop() -> None:
    # 验收第 2 条：核验角色只核验中途成果（产品要求）时，交付没有人核验，同样判断为开环
    midway = _declared(verifiers=[VerifierRole(role="quality", verifies=(
        VerifiedOutcomes(role="engineering", outcomes=("product_spec",)),))])
    assert midway.verifiers_of("engineering", "product_spec") == ("quality",)
    assert not midway.is_open_loop("product_spec")
    assert midway.is_open_loop("delivery_spec")


def test_several_verifiers_of_one_outcome_all_answer() -> None:
    #docs/design/forms-and-verifier-role.md「定义的校验」：几个核验角色核验同一份成果时，每一个都放行才算放行
    both = _declared(verifiers=[
        VerifierRole(role="quality", verifies=(VerifiedOutcomes(role="engineering", outcomes=("delivery_spec",)),)),
        VerifierRole(role="product", verifies=(VerifiedOutcomes(role="engineering", outcomes=("delivery_spec",)),)),
    ])
    assert both.verifiers_of("engineering", "delivery_spec") == ("quality", "product")
    assert both.verified_by("delivery_spec") == ("quality", "product")
    assert not both.is_open_loop("delivery_spec")


def test_a_verifier_of_a_role_outside_the_definition_is_rejected() -> None:
    issues = _issues(verifiers=[VerifierRole(role="quality", verifies=(
        VerifiedOutcomes(role="reviewer", outcomes=("delivery_spec",)),))])
    assert issues == [("organization.json", "verification.verifiers[0].verifies[0].role",
                       "被核验的角色 reviewer 不属于任何部门")]


def test_a_verifier_of_an_outcome_outside_the_definition_is_rejected() -> None:
    issues = _issues(verifiers=[VerifierRole(role="quality", verifies=(
        VerifiedOutcomes(role="engineering", outcomes=("test_report",)),))])
    assert issues == [("organization.json", "verification.verifiers[0].verifies[0].outcomes[0]",
                       "成果种类 test_report 没有定义")]


def test_a_role_that_verifies_itself_is_rejected_as_a_cycle() -> None:
    # 验收第 3 条：角色核验自己是长度为一的环
    issues = _issues(verifiers=[VerifierRole(role="quality", verifies=(
        VerifiedOutcomes(role="quality", outcomes=("qa_review",)),))])
    assert issues == [("organization.json", "verification.verifiers[0].verifies[0].role",
                       "谁能拒绝谁有环：quality → quality，角色核验自己")]


def test_two_roles_that_verify_each_other_are_rejected_as_a_cycle() -> None:
    # 验收第 3 条：两个角色互相核验是一个环，报一条，写明环的路径
    issues = _issues(verifiers=[
        VerifierRole(role="quality", verifies=(VerifiedOutcomes(role="engineering", outcomes=("delivery_spec",)),)),
        VerifierRole(role="engineering", verifies=(VerifiedOutcomes(role="quality", outcomes=("qa_review",)),)),
    ])
    assert issues == [("organization.json", "verification.verifiers[1].verifies[0].role",
                       "谁能拒绝谁有环：quality → engineering → quality")]


def test_a_write_scope_of_a_role_outside_the_definition_is_rejected() -> None:
    issues = _issues(write_scopes={"reviewer": WriteScope(scope="workspace")})
    assert issues == [("organization.json", "verification.write_scopes.reviewer", "角色 reviewer 不属于任何部门")]


def test_a_verifier_role_outside_the_definition_is_rejected() -> None:
    issues = _issues(verifiers=[VerifierRole(role="reviewer", verifies=(
        VerifiedOutcomes(role="engineering", outcomes=("delivery_spec",)),))])
    assert issues == [("organization.json", "verification.verifiers[0].role", "核验角色 reviewer 不属于任何部门")]


def test_a_verifier_declared_twice_is_rejected() -> None:
    # 一个角色只声明一次：分成两条写会让「谁能拒绝谁」出现重复的边
    issues = _issues(verifiers=[
        VerifierRole(role="quality", verifies=(VerifiedOutcomes(role="engineering", outcomes=("delivery_spec",)),)),
        VerifierRole(role="quality", verifies=(VerifiedOutcomes(role="engineering", outcomes=("qa_review",)),)),
    ])
    assert issues == [("organization.json", "verification.verifiers[1].role", "核验角色 quality 重复声明")]


def test_a_write_scope_must_name_the_directories_check_materials_writes() -> None:
    # 检查材料的写入范围要写明目录；写工作区的范围不带路径
    with pytest.raises(ValidationError, match="check_materials requires the directories"):
        WriteScope(scope="check_materials")
    with pytest.raises(ValidationError, match="only check_materials takes paths"):
        WriteScope(scope="workspace", paths=(QA_TESTS_DIR,))


def test_an_unknown_department_has_no_write_scope() -> None:
    with pytest.raises(ValueError, match="unknown department 'reviewer'"):
        DEFINITIONS.write_scope("reviewer")


def _renamed_verifier() -> Definitions:
    # 一份把核验角色改名的定义：部门清单里旧的核验角色换成新的名字，角色与核验声明、写入范围跟着换
    organization = DEFINITIONS.organization
    departments = tuple(item.model_copy(update={"id": "inspection"}) if item.id == "quality" else item
                        for item in organization.departments)
    declaration = VerificationDeclaration(
        verifiers=(VerifierRole(role="inspection", verifies=(
            VerifiedOutcomes(role="engineering", outcomes=("delivery_spec",)),)),),
        write_scopes={"inspection": WriteScope(scope="check_materials", paths=(QA_TESTS_DIR,))})
    return DEFINITIONS.model_copy(update={
        "organization": organization.model_copy(update={"departments": departments, "verification": declaration}),
        "roles": {"inspection" if role == "quality" else role: definition
                  for role, definition in DEFINITIONS.roles.items()}})


def test_the_write_scope_of_a_tool_call_is_read_from_the_declaration() -> None:
    # 工单 #1390：写入范围按定义里角色的声明核对，不按部门名。核验角色改名的定义里，改名后的角色写检查材料
    # 以外的文件被拒绝（原因与默认定义下的质检逐字相同、不写部门名），写检查材料放行；
    # 写入范围是工作区的角色不受这个限制
    renamed = _renamed_verifier()
    assert renamed.write_scope("inspection") == WriteScope(scope="check_materials", paths=(QA_TESTS_DIR,))
    projection = RunProjection()
    outside = _permission(projection, "write_file", "inspection", renamed, path="src/echo.py")
    assert not outside.allowed and not outside.stopped
    assert outside.reason == _permission(projection, "write_file", "quality", path="src/echo.py").reason
    assert QA_TESTS_DIR in outside.reason
    for name in ("inspection", "product", "engineering", "quality"):
        assert name not in outside.reason, outside.reason
    assert _permission(projection, "write_file", "inspection", renamed, path=f"{QA_TESTS_DIR}/test_echo.py").allowed
    assert _permission(projection, "write_file", "engineering", renamed, path="src/echo.py").allowed


def test_an_old_definition_without_the_declaration_reads_the_three_departments() -> None:
    # 旧定义没有这份声明：读的时候按默认三部门解释，那种解释不是定义的一部分，加载时不核对
    old = DEFINITIONS.model_copy(update={"organization": DEFINITIONS.organization.model_copy(
        update={"verification": None})})
    assert old.verification == LEGACY_VERIFICATION
    assert old.is_open_loop("delivery_spec") is False
    assert verification_issues(old.organization, set()) == []


# 事项的来源（工单 #1455）：每一种来源由哪个部门接写在定义里；旧定义没有写时两种来源都按
# 关注用户输入的部门解释，没有这样的部门就拒绝。加载时的这一项由 source_issues 报出，整份拒绝
def _with_sources(sources=None) -> Definitions:
    # 这份定义把事项的来源换成给出的这一份（None 是没有写的旧定义）
    return DEFINITIONS.model_copy(update={"organization": DEFINITIONS.organization.model_copy(
        update={"sources": sources})})


def test_the_default_definition_gives_both_item_sources_to_one_department() -> None:
    assert dict(DEFINITIONS.organization.sources) == {"user_input": "product", "onboarding": "product"}
    assert DEFINITIONS.source_department("user_input") == "product"
    assert DEFINITIONS.source_department("onboarding") == "product"
    assert DEFINITIONS.input_department() == "product"
    # 事项的种类到来源：建档事项从建档开始，其余从你的输入开始
    assert (DEFINITIONS.item_source("change"), DEFINITIONS.item_source("onboarding")) == (
        "user_input", "onboarding")
    assert source_issues(DEFINITIONS.organization) == []


def test_an_old_definition_reads_both_sources_as_the_department_that_watches_user_input() -> None:
    # 验收第 4 条：不写新字段的旧定义，两种来源都由关注用户输入的部门接
    old = _with_sources(None)
    assert old.source_department("user_input") == "product"
    assert old.source_department("onboarding") == "product"
    assert source_issues(old.organization) == []


def test_an_old_definition_without_a_department_watching_user_input_is_rejected() -> None:
    # 验收第 4 条：旧定义没有这样的部门时拒绝
    organization = DEFINITIONS.organization.model_copy(update={
        "sources": None,
        "departments": tuple(item.model_copy(update={"watched": tuple(
            kind for kind in item.watched if kind != "user_input")})
            for item in DEFINITIONS.organization.departments)})
    assert source_issues(organization) == [(
        "organization.json", "sources",
        "没有写事项的来源，也没有部门关注用户输入：你的输入与建档没有人接")]
    old = DEFINITIONS.model_copy(update={"organization": organization})
    with pytest.raises(ValueError, match="no department that receives the item sources"):
        old.source_department("user_input")


def test_a_source_without_a_department_is_rejected() -> None:
    # 验收第 3 条：一种来源没有部门接，写明是哪一种来源
    issues = source_issues(_with_sources({"user_input": "product"}).organization)
    assert issues == [("organization.json", "sources.onboarding", "事项的来源 onboarding 没有部门接")]


def test_a_source_received_by_a_department_outside_the_definition_is_rejected() -> None:
    # 验收第 3 条：接它的部门不在这份定义里，同样拒绝，写明来源与部门
    issues = source_issues(_with_sources({"user_input": "product", "onboarding": "reviewer"}).organization)
    assert issues == [("organization.json", "sources.onboarding",
                       "接来源 onboarding 的部门 reviewer 不属于任何部门")]


def test_an_unknown_item_source_has_no_department() -> None:
    # 定义里没有这种来源时交回报错，不留回退取值
    declared = _with_sources({"user_input": "engineering", "onboarding": "engineering"})
    assert declared.source_department("user_input") == "engineering"
    with pytest.raises(ValueError, match="item source 'operations' is not in this definition"):
        declared.source_department("operations")
