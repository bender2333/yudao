# 裁决规则（U）：工具许可，以及提案校验与提交的判断。只读取投影、事件与交给它的工作区事实（由执行环境查询，
# 见 actions.py），不写入，不调用模型；许可规则可以增加，只能收紧。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .actions import FactsQuery, TreeFacts, WorkspaceFacts
from .collaboration import request_basis, tool_error
from .contracts import current_contract_hash
from .models import TERMINAL_PHASES, Event, RunProjection
from .tools import has_tool, offers_with_input, tool_action, tools_for, usable_when_guidance_only
from .validation import FieldError, ProposalDecision, evaluate_proposal

_STALE_BASIS = ("The input, contract, or current work changed after this activation began; "
                "stale results cannot be rebound.")
_STALE_SNAPSHOT = "The workspace snapshot changed after this activation began; stale results cannot be rebound."


def guidance_version(projection: RunProjection, department: str) -> int:
    return max((item.version for item in projection.department_guidance
                if item.department == department), default=0)


@dataclass(frozen=True)
class WorkBasis:
    # 激活开始时采用的工作依据；依据改变以后，这次激活不能再开始模型请求与工具
    effective_contract_hash: str | None
    request_id: str | None
    input_version: int
    guidance_version: int

    @classmethod
    def current(cls, projection: RunProjection, department: str) -> WorkBasis:
        return cls(
            effective_contract_hash=current_contract_hash(projection),
            request_id=None if projection.pending_request is None else projection.pending_request.id,
            input_version=projection.input_version,
            guidance_version=guidance_version(projection, department),
        )

    def changed(self, projection: RunProjection, department: str) -> bool:
        current = WorkBasis.current(projection, department)
        return (current.effective_contract_hash != self.effective_contract_hash
                or current.request_id != self.request_id
                or current.input_version != self.input_version
                or current.guidance_version > self.guidance_version)


@dataclass(frozen=True)
class ToolPermission:
    # 工具许可的三种结果：允许；拒绝并说明原因，原因作为工具结果交回模型；停止
    stopped: bool = False
    reason: str | None = None

    @property
    def allowed(self) -> bool:
        return not self.stopped and self.reason is None


def offered_tools(projection: RunProjection, department: str, *, guidance_only: bool = False,
                  input_modalities: tuple[str, ...] = ("text",)) -> list[str]:
    # 请求中提供给模型的工具：部门的工具，只能回应指导时限于回应指导的范围，再去掉当前工作不允许的提交，
    # 最后按调用目标的输入方式去掉声明需要图像输入而调用目标不含图像的工具（设计说明第 5.6 节）
    available = tools_for(department, projection.kind)
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
    guidance_only: bool,
    basis: WorkBasis,
    aborted: bool,
    facts: WorkspaceFacts,
) -> ToolPermission:
    # facts 是执行环境按 facts_query(call) 查询的结果
    if projection.phase in TERMINAL_PHASES or aborted or basis.changed(projection, department):
        return ToolPermission(stopped=True)
    name, args = call["name"], call["args"]
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
    return evaluate_proposal(phase=projection.phase, department=department, proposal=proposal,
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
    # 提交判断：提交之前按最新的投影与工作区事实复核校验结果。激活开始以后输入、指导、合同、
    # 协作请求或当前工作改变，或者校验以后工作区改变，都拒绝，不重新绑定到新的依据；仍然成立时按最新状态再校验
    before, now = WorkBasis.current(started, department), WorkBasis.current(current, department)
    if (current.phase != started.phase
            or now.input_version != basis.input_version
            or now.guidance_version != basis.guidance_version
            or now.effective_contract_hash != before.effective_contract_hash
            or now.request_id != before.request_id
            or request_basis(current) != request_basis(evaluated)):
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


