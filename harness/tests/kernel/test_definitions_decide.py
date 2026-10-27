# 工具许可与提案校验读这个事项所用的那份定义（工单 #1098，设计说明第 5.4 节第 3 条）。
#
# 守 R1「工具调用先有许可」与「写入先过裁决」（docs/design/test-pyramid.md 第 13.1 节）：
# 一个工具能不能用、一份提案能不能接纳，只看交给它的那份定义里的工具、部门与提案种类，
# 不读模块加载时的那一份。用例自己造定义，只改「定义里有哪些工具、部门与提案种类」这一件事，
# 看许可与校验的决定跟着它变；不跑模型、不起运行，只在内存里判断，属于单元层。

from __future__ import annotations

from harness import adjudication, tools, validation
from harness.actions import TreeFacts, WorkspaceFacts
from harness.definitions import DEFINITIONS, Definitions, Tool
from harness.models import RunProjection

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


def _permission(projection, name: str, department: str, definitions: Definitions | None = None,
                session_id: str | None = None):
    return adjudication.tool_permission(
        projection, {"name": name, "id": "call-1", "args": {"path": "README.md"}},
        department=department, session_id=session_id,
        basis=adjudication.WorkBasis.current(projection, department),
        aborted=False, facts=WorkspaceFacts(), definitions=definitions)


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
    decision = validation.evaluate_proposal(
        department="quality", proposal={"kind": "qa_review"}, projection=projection,
        facts=_FACTS, definitions=narrowed)
    assert [error.message for error in decision.errors] == ["unknown proposal kind: 'qa_review'"]
    current = validation.evaluate_proposal(
        department="quality", proposal={"kind": "qa_review"}, projection=projection, facts=_FACTS)
    assert all("unknown proposal kind" not in error.message for error in current.errors)


def test_proposal_department_comes_from_the_matter_definition() -> None:
    narrowed = _without_department(DEFINITIONS, "quality")
    decision = validation.evaluate_proposal(
        department="quality", proposal={"kind": "qa_review"}, projection=RunProjection(),
        facts=_FACTS, definitions=narrowed)
    assert [error.message for error in decision.errors] == ["unknown department: quality"]


def test_a_branch_session_judges_a_proposal_by_the_matter_definition() -> None:
    # 询问分支里的会话不能用提交提案的工具；「这个工具提交的是提案」也按事项所用的那份定义判
    # （工单 #1098，设计说明第 5.4 节第 3 条）
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
