# 工具许可与提案校验读这个事项所用的那份定义（工单 #1098，设计说明第 5.4 节第 3 条）。
#
# 守 R1「工具调用先有许可」与「写入先过裁决」（docs/design/test-pyramid.md 第 13.1 节）：
# 一个工具能不能用、一份提案能不能接纳，只看交给它的那份定义里的工具、部门与提案种类，
# 不读模块加载时的那一份。用例自己造定义，只改「定义里有哪些工具、部门与提案种类」这一件事，
# 看许可与校验的决定跟着它变；不跑模型、不起运行，只在内存里判断，属于单元层。

from __future__ import annotations

from harness import adjudication, kernel_events, submissions, tools, validation
from harness.actions import TreeFacts, WorkspaceFacts
from harness.definitions import DEFINITIONS, Definitions, Tool
from harness.minimal_projection import fold_events
from harness.models import RunProjection, SessionRecord
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
                definitions: Definitions | None = None, session_id: str | None = None):
    return adjudication.tool_permission(
        _view(projection), {"name": name, "id": "call-1", "args": {"path": "README.md"}},
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
