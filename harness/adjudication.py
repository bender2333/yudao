# 裁决规则（U）：工具许可，以及提案校验与提交的判断。只读最小投影、事件与交给它的工作区事实（由执行环境
# 查询，见 actions.py），不写入，不调用模型；许可规则可以增加，只能收紧。项目里有内容的判断（输入与指导的
# 版本、这个部门此刻能交什么、按成果内容的检查）归路由的收紧检查，内核把应用的状态原样交给它（S1d，#860）

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .actions import FactsQuery, TreeFacts, WorkspaceFacts
from .definitions import DEFINITIONS, Definitions
from .kernel_events import TERMINAL_STATUSES, Event
from .minimal_projection import MinimalProjection
from .path_rules import is_check_materials_path
from .tools import has_tool, in_force, tool_action
from .validation import (
    AdjudicationView, FieldError, ProposalDecision, TightenRequest, Tightening, evaluate_proposal,
)

_STALE_BASIS = ("The contract or current work changed after this activation began; "
                "stale results cannot be rebound.")
_STALE_SNAPSHOT = "The workspace snapshot changed after this activation began; stale results cannot be rebound."
# 收紧检查要求这次提交等一等、但没有写原因时交回部门的一句通用说明（工单 #1456）
_PENDING_SUBMISSION = "this submission waits for the work in between to end; submit it again after it settles"
_CHECK_MATERIALS_WRITE_OUTSIDE = ("a check materials write scope only allows {dirs}: the other files in the check "
                                  "workspace are the tree the release is judged against")


def submission_basis(projection: MinimalProjection) -> dict[str, Any]:
    # 一次提交所依据的成果版本：最小投影里每一种成果的当前版本（docs/design/skeleton-and-application.md「最小投影」，S1d 工单 #860）。
    # 校验以后其中任何一样变了，这次提交就不能再按原来的依据接纳。有哪几种成果、各自是哪一版，
    # 来自定义与投影，内核不写死（工单 #1456）；用户输入与指导的版本读的是成果的内容，不在这里
    # （归路由的收紧检查，工单 #1095）
    return {"artifacts": {kind: artifact.content_hash
                          for kind, artifact in projection.artifacts.items()}}


@dataclass(frozen=True)
class WorkBasis:
    # 激活开始时采用的工作依据；有效合同、指导与用户输入变了以后，这个会话在下一步收到通知（新版本与改动、
    # 新的输入），接着工作，一轮工作不因此结束（工单 #558、#964，循环结构「工作中途要求变化」与「指导」）。合同摘要来自
    # 最小投影，输入与指导的版本是应用的数据，由流程编排在开始一轮工作时填进来（S1d，工单 #860）
    effective_contract_hash: str | None
    input_version: int
    guidance_version: int


@dataclass(frozen=True)
class ToolPermission:
    # 工具许可的三种结果：允许；拒绝并说明原因，原因作为工具结果交回模型；停止。
    # deferred：这次拒绝只是推迟（#964）——模型还没有看见新的输入，提交推迟到下一步，这一轮不因此结束；
    # wait_for_input：等输入处理完（#561）——放行时发给产品的输入还没有处理完，在安全节点上等到处理完再
    # 重新做工具许可，不返回模型、不写事件、不占步数
    stopped: bool = False
    reason: str | None = None
    deferred: bool = False
    wait_for_input: bool = False

    @property
    def allowed(self) -> bool:
        return not self.stopped and self.reason is None and not self.wait_for_input

def ask_chain_decision(position: int, limit: int) -> tuple[bool, str | None]:
    # 询问链能不能再问一层（工单 #473）：position 是这个会话在链上的位置，
    # 它再问一层是第 position + 1 层。层数不超过上限时可以；
    # 超过上限时给出原因：链已有几层、上限是多少，并提示把要问的内容写进回答。
    if position + 1 <= limit:
        return True, None
    return False, (f"询问链已有 {position} 层，上限是 {limit} 层：不能再回问，"
                   f"把要问的内容写进回答")


def ask_chain_max_depth() -> int:
    # 询问链的层数上限：规则登记 organization.ask_chain_max_depth（工单 #473），不在代码里写死
    return int(DEFINITIONS.rule_value("organization.ask_chain_max_depth"))


def offered_tools(state: Any, department: str, *, tightening: Tightening,
                  session_id: str | None = None, input_modalities: tuple[str, ...] = ("text",),
                  definitions: Definitions | None = None) -> list[str]:
    # 请求中提供给模型的工具：内核给出部门完整的工具清单，由路由的收紧检查按这一轮的工作与询问分支取舍，
    # 再按调用目标的输入方式去掉声明需要图像输入的工具（docs/design/model-management.md「部门的建议能力」，工单 #1095）。
    # state 是应用侧的运行状态投影：提供的工具由收紧检查按内容判断，内核不读它，原样交过去。
    # 部门的工具清单读这个事项所用的那份定义（工单 #1098），不读模块加载时的那一份
    return tightening.offered(TightenRequest(department=department, state=state, session_id=session_id,
                                             input_modalities=input_modalities, definitions=in_force(definitions)))


def facts_query(call: dict[str, Any], *, definitions: Definitions | None = None) -> FactsQuery:
    # 工具许可依据的工作区事实：写入的目标路径在工作区中的规范形式，命令执行依据中的公开树摘要
    name, args = call["name"], call["args"]
    if tool_action(name, definitions=definitions) == "command":
        return FactsQuery(tree=True)
    if _is_write(name, definitions):
        return FactsQuery(paths=tuple(target for target in _write_targets(name, args) if isinstance(target, str)))
    return FactsQuery()


def tool_permission(
    view: AdjudicationView,
    call: dict[str, Any],
    *,
    department: str,
    tightening: Tightening,
    basis: WorkBasis,
    aborted: bool,
    facts: WorkspaceFacts,
    session_id: str | None = None,
    events: list[Event] | None = None,
    definitions: Definitions | None = None,
) -> ToolPermission:
    # facts 是执行环境按 facts_query(call) 查询的结果
    # 工具许可读这个事项所用的那份定义（工单 #1098）：部门有没有这个工具、这个工具提交什么种类按它判；
    # 没有交的时候是当前加载的那一份
    # 有效合同、指导与用户输入变了都不再停止这次激活：它们作为通知送达，部门接着工作，
    # 这一轮不因此结束（工单 #558、工单 #964，循环结构「工作中途要求变化」与「指导」）
    projection = view.minimal
    definition = in_force(definitions)
    if projection.status in TERMINAL_STATUSES or aborted:
        return ToolPermission(stopped=True)
    name, args = call["name"], call["args"]
    # 成果驱动的取舍交给路由的收紧检查（工单 #1095）：推迟、询问分支、这个部门此刻能交的种类、放行等输入处理完。
    # 内核自己判的是运行状态（上面）、部门有没有这个工具与写入目标的规范形式（下面）
    tight = tightening.tool(TightenRequest(department=department, state=view.state, session_id=session_id,
                                           basis=basis, tool=call, events=tuple(events or ()),
                                           definitions=definition))
    if tight.wait:
        # 等待由步骤驱动的安全节点处理（工单 #561）：不写事件、不占步数、不返回模型
        return ToolPermission(wait_for_input=True)
    if tight.errors:
        return ToolPermission(reason=tight.errors[0].message)
    if tight.reason is not None:
        return ToolPermission(reason=tight.reason, deferred=tight.deferred)
    if not tight.permitted and not has_tool(department, name, projection.work_item_kind, definitions=definition):
        return ToolPermission(reason=f"{department} cannot use {name}")
    if _is_write(name, definition):
        reason = _write_path_error(name, args, facts, definition.write_scope(department))
        if reason:
            return ToolPermission(reason=reason)
    return ToolPermission()


def proposal_decision(view: AdjudicationView, *, department: str, proposal: dict[str, Any] | None,
                      facts: TreeFacts, tightening: Tightening, events: list[Event],
                      definitions: Definitions | None = None) -> ProposalDecision:
    # 提案校验：按最小投影、工作区事实与事件判断提案能否接纳；自然语言与格式错误都成为字段错误。
    # 种类与部门读这个事项所用的那份定义（工单 #1098）
    return evaluate_proposal(view=view, department=department, proposal=proposal, definitions=definitions,
                             facts=facts, tightening=tightening, events=events)


def commit_decision(
    decision: ProposalDecision,
    *,
    department: str,
    proposal: dict[str, Any] | None,
    evaluated: AdjudicationView,
    facts: TreeFacts,
    current: AdjudicationView,
    current_facts: TreeFacts,
    events: list[Event],
    tightening: Tightening,
    definitions: Definitions | None = None,
) -> ProposalDecision:
    # 提交判断：提交之前按最新的投影与工作区事实复核校验结果。校验以后工作区改变，
    # 或者当前工作已经不是校验时的那一份，都拒绝，不重新绑定到新的依据；仍然成立时按最新状态再校验。
    # 有效合同、指导与用户输入变了不再让这次提交作废：它们作为通知送达，部门接着工作，
    # 提交的成果按当前版本核对（工单 #558、工单 #964，循环结构「工作中途要求变化」、「指导」与「提交与版本」）
    definition = in_force(definitions)
    if submission_basis(current.minimal) != submission_basis(evaluated.minimal):
        decision = ProposalDecision(False, [FieldError("execution_basis", _STALE_BASIS)])
    if current_facts != facts:
        return ProposalDecision(False, [FieldError("execution_basis", _STALE_SNAPSHOT)])
    if decision.accepted:
        decision = proposal_decision(current, department=department, proposal=proposal, definitions=definition,
                                     facts=current_facts, tightening=tightening, events=events)
    if decision.accepted:
        # 还有没处理完的输入时这次提交不当场生效：等不等、为什么等是路由的收紧检查的判断与说明
        # （部门指导设计说明「放行怎么等」，工单 #561、#1456），内核只把它的原因交回部门
        tight = tightening.submission(TightenRequest(department=department, state=current.state, proposal=proposal,
                                                     events=tuple(events), commit=True, definitions=definition,
                                                     minimal=current.minimal, facts=current_facts))
        if tight.wait:
            return ProposalDecision(False, [FieldError("kind", tight.reason or _PENDING_SUBMISSION)])
    return decision


def _is_write(name: str, definitions: Definitions | None = None) -> bool:
    return tool_action(name, definitions=definitions) == "write"


def _write_path_error(name: str, args: dict[str, Any], facts: WorkspaceFacts, scope: Any) -> str | None:
    # 写入范围是检查材料的角色只写检查材料目录（docs/design/forms-and-verifier-role.md「核验角色」中「写入范围是检查材料」）：检查工作区里其余文件参与放行时
    # 核对的树（提案条件 tree_matches），改动它们会让放行被拒绝；原因里不写部门名。
    # 写入目标在工作区中不能表示时直接拒绝，原因就是执行环境给出的原因（计划范围检查已随 #470 删除）
    for target in _write_targets(name, args):
        if scope.scope == "check_materials" and not (isinstance(target, str)
                                                     and is_check_materials_path(target, *scope.paths)):
            return _CHECK_MATERIALS_WRITE_OUTSIDE.format(dirs="/, ".join(scope.paths) + "/")
        if not isinstance(target, str):
            continue
        path = facts.paths.get(target)
        if path is not None and path.error is not None:
            return path.error
    return None


def _write_targets(name: str, args: dict[str, Any]) -> list[Any]:
    return [args.get("source"), args.get("destination")] if name == "move_file" else [args.get("path")]
