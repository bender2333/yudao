# 裁决规则（U）：工具许可，以及提案校验与提交的判断。只读取投影、事件与交给它的工作区事实（由执行环境查询，
# 见 actions.py），不写入，不调用模型；许可规则可以增加，只能收紧。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .actions import FactsQuery, TreeFacts, WorkspaceFacts
from .collaboration import tool_error
from .contracts import current_contract_hash
from .definitions import DEFINITIONS
from .models import TERMINAL_STATUSES, Event, RunProjection, hash_bytes
from .tools import has_tool, offers_with_input, proposal_kind, tool_action, tools_for, usable_when_guidance_only
from .validation import FieldError, ProposalDecision, evaluate_proposal

_STALE_BASIS = ("The input, contract, or current work changed after this activation began; "
                "stale results cannot be rebound.")
_STALE_SNAPSHOT = "The workspace snapshot changed after this activation began; stale results cannot be rebound."


def submission_basis(projection: RunProjection) -> dict[str, Any]:
    # 一次提交所依据的东西：用户的意图、当前有效合同与当前交付。
    # 校验以后这几样里任何一样变了，这次提交就不能再按原来的依据接纳
    return {
        "intend_hash": hash_bytes(projection.task.encode("utf-8")),
        "effective_contract_hash": _content_hash(projection.effective_contract),
        "delivery_spec_hash": _content_hash(projection.delivery_spec),
    }


def _content_hash(value: Any) -> str | None:
    return None if value is None else value.content_hash


def guidance_version(projection: RunProjection, department: str) -> int:
    return max((item.version for item in projection.department_guidance
                if item.department == department), default=0)


@dataclass(frozen=True)
class WorkBasis:
    # 激活开始时采用的工作依据；有效合同与指导变了以后，这个会话在下一步收到通知
    # （新版本与改动），接着工作，一轮工作不因此结束（工单 #558，循环结构第 5 节与第 6 节）。
    # 用户输入变了仍然结束这一轮：输入分派给产品部门，由产品在下一轮处理（工单 #556）
    effective_contract_hash: str | None
    input_version: int
    guidance_version: int

    @classmethod
    def current(cls, projection: RunProjection, department: str) -> WorkBasis:
        return cls(
            effective_contract_hash=current_contract_hash(projection),
            input_version=projection.input_version,
            guidance_version=guidance_version(projection, department),
        )

    def changed(self, projection: RunProjection, department: str) -> bool:
        # 依据变了没有：只有用户输入算——输入分派给产品部门，已经装配好的请求不再发出；
        # 有效合同与指导的变化作为通知送达，部门接着工作（工单 #558）
        return projection.input_version != self.input_version


@dataclass(frozen=True)
class ToolPermission:
    # 工具许可的三种结果：允许；拒绝并说明原因，原因作为工具结果交回模型；停止
    stopped: bool = False
    reason: str | None = None

    @property
    def allowed(self) -> bool:
        return not self.stopped and self.reason is None

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


def _ask_branch_permission(projection: RunProjection, session_id: str | None, department: str,
                            name: str) -> ToolPermission | None:
    # 分支会话的许可按会话判定：这个会话是不是某个询问的分支（工单 #473 的嵌套询问）。
    # 同一个部门的主线会话与分支会话是两回事，只有分支会话受分支的约束。
    if projection.ask_by_branch(session_id) is None:
        if name == "answer":
            return ToolPermission(reason="answer tool is only available in an ask branch session")
        return None
    if name == "answer":
        return ToolPermission()
    if name == "ask":
        # 回问：在被问部门那里另开一个询问分支，层数不超过上限（工单 #473）
        if projection.ask_by_origin(session_id) is not None:
            # 这个会话自己那次询问还没结束：继续这一层，不新开一层
            return None
        allowed, reason = ask_chain_decision(projection.ask_position(session_id), ask_chain_max_depth())
        return None if allowed else ToolPermission(reason=reason)
    if department == "product":
        return ToolPermission(reason="Product ask branch can only submit answer")
    if _is_write(name):
        return ToolPermission(reason="The branch session cannot modify files in the running workspace")
    if name == "submit_delivery":
        return ToolPermission(reason="The branch session cannot submit delivery")
    if name == "submit_review":
        return ToolPermission(reason="The branch session cannot submit QA review")
    if proposal_kind(name) is not None:
        return ToolPermission(reason=f"The branch session cannot submit proposal {name}")
    return None


def offered_tools(projection: RunProjection, department: str, *, session_id: str | None = None,
                  guidance_only: bool = False,
                  input_modalities: tuple[str, ...] = ("text",)) -> list[str]:
    # 请求中提供给模型的工具：部门的工具，只能回应指导时限于回应指导的范围，再去掉当前工作不允许的提交，
    # 最后按调用目标的输入方式去掉声明需要图像输入而调用目标不含图像的工具（设计说明第 5.6 节）
    available = tools_for(department, projection.kind)
    if projection.ask_by_branch(session_id) is not None:
        # 询问分支里：可以回答；层数允许时可以回问；不能写工作区、不能提交提案（工单 #473）
        chain_allowed, _ = ask_chain_decision(projection.ask_position(session_id), ask_chain_max_depth())
        nested = ["ask"] if chain_allowed else []
        if department == "product":
            return ["answer"] + nested
        allowed = [name for name in available
                   if name != "ask" and not _is_write(name) and proposal_kind(name) is None]
        return allowed + ["answer"] + nested
    if guidance_only:
        available = [name for name in available if usable_when_guidance_only(name)]
    return [name for name in offers_with_input(available, input_modalities)
            if tool_error(projection, department, name, {}) is None]


def facts_query(call: dict[str, Any]) -> FactsQuery:
    # 工具许可依据的工作区事实：写入的目标路径在工作区中的规范形式，命令执行依据中的公开树摘要
    name, args = call["name"], call["args"]
    if tool_action(name) == "command":
        return FactsQuery(tree=True)
    if _is_write(name):
        return FactsQuery(paths=tuple(target for target in _write_targets(name, args) if isinstance(target, str)))
    return FactsQuery()


def tool_permission(
    projection: RunProjection,
    call: dict[str, Any],
    *,
    department: str,
    session_id: str | None = None,
    guidance_only: bool,
    basis: WorkBasis,
    aborted: bool,
    facts: WorkspaceFacts,
) -> ToolPermission:
    # facts 是执行环境按 facts_query(call) 查询的结果
    # 有效合同与指导变了不再停止这次激活：它们作为通知送达，部门接着工作（工单 #558）；
    # 用户输入变了仍然停止：输入分派给产品部门，已经装配好的请求不再发出
    if projection.status in TERMINAL_STATUSES or aborted or basis.changed(projection, department):
        return ToolPermission(stopped=True)
    name, args = call["name"], call["args"]
    branch_perm = _ask_branch_permission(projection, session_id, department, name)
    if branch_perm is not None:
        return branch_perm
    if not has_tool(department, name, projection.kind):
        return ToolPermission(reason=f"{department} cannot use {name}")
    if guidance_only and not usable_when_guidance_only(name):
        return ToolPermission(reason="This guidance activation cannot change files or submit normal department work.")
    reason = tool_error(projection, department, name, args)
    if reason:
        return ToolPermission(reason=reason)
    if _is_write(name):
        reason = _write_path_error(name, args, facts)
        if reason:
            return ToolPermission(reason=reason)
    return ToolPermission()


def proposal_decision(projection: RunProjection, *, department: str, proposal: dict[str, Any] | None,
                      facts: TreeFacts, events: list[Event]) -> ProposalDecision:
    # 提案校验：按投影、工作区事实与事件判断提案能否接纳；自然语言与格式错误都成为字段错误
    return evaluate_proposal(department=department, proposal=proposal,
                             projection=projection, facts=facts, events=events)


def commit_decision(
    decision: ProposalDecision,
    *,
    department: str,
    proposal: dict[str, Any] | None,
    basis: WorkBasis,
    started: RunProjection,
    evaluated: RunProjection,
    facts: TreeFacts,
    current: RunProjection,
    current_facts: TreeFacts,
    events: list[Event],
) -> ProposalDecision:
    # 提交判断：提交之前按最新的投影与工作区事实复核校验结果。激活开始以后输入改变，
    # 或者校验以后工作区改变，都拒绝，不重新绑定到新的依据；仍然成立时按最新状态再校验。
    # 有效合同与指导变了不再拒绝：它们作为通知送达，部门接着工作，提交的成果按当前版本核对
    # （工单 #558，循环结构第 5 节、第 6 节与第 7 节）
    now = WorkBasis.current(current, department)
    if (now.input_version != basis.input_version
            or submission_basis(current) != submission_basis(evaluated)):
        decision = ProposalDecision(False, [FieldError("execution_basis", _STALE_BASIS)])
    if current_facts != facts:
        return ProposalDecision(False, [FieldError("execution_basis", _STALE_SNAPSHOT)])
    if decision.accepted:
        return proposal_decision(current, department=department, proposal=proposal,
                                 facts=current_facts, events=events)
    return decision


def _is_write(name: str) -> bool:
    return tool_action(name) == "write"


def _write_path_error(name: str, args: dict[str, Any], facts: WorkspaceFacts) -> str | None:
    # 写入目标在工作区中不能表示时直接拒绝，原因就是执行环境给出的原因；计划范围检查已随 #470 删除
    for target in _write_targets(name, args):
        if not isinstance(target, str):
            continue
        path = facts.paths.get(target)
        if path is not None and path.error is not None:
            return path.error
    return None


def _write_targets(name: str, args: dict[str, Any]) -> list[Any]:
    return [args.get("source"), args.get("destination")] if name == "move_file" else [args.get("path")]


