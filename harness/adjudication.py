# 裁决规则（U）：工具许可，以及提案校验与提交的判断。只读取投影、事件与交给它的工作区事实（由执行环境查询，
# 见 actions.py），不写入，不调用模型；许可规则可以增加，只能收紧。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .actions import FactsQuery, TreeFacts, WorkspaceFacts
from .collaboration import request_basis, tool_error
from .contracts import current_contract_hash, current_plan_hash, path_in_scope
from .models import TERMINAL_PHASES, Event, RunProjection
from .tools import TOOL_DEFS, has_tool, tools_for
from .validation import FieldError, ProposalDecision, evaluate_proposal

# 因待处理指导被提前安排、只能回应指导的激活可以使用的工具
GUIDANCE_ONLY_TOOLS = frozenset({
    "read_file", "list_files", "run_check", "submit_guidance_response", "submit_request",
})

_STALE_BASIS = ("The input, contract, plan, or current work changed after this activation began; "
                "stale results cannot be rebound.")
_STALE_SNAPSHOT = "The workspace snapshot changed after this activation began; stale results cannot be rebound."


def guidance_version(projection: RunProjection, department: str) -> int:
    return max((item.version for item in projection.department_guidance
                if item.department == department), default=0)


@dataclass(frozen=True)
class WorkBasis:
    # 激活开始时采用的工作依据；依据改变以后，这次激活不能再开始模型请求与工具
    effective_contract_hash: str | None
    engineering_plan_hash: str | None
    request_id: str | None
    input_version: int
    guidance_version: int

    @classmethod
    def current(cls, projection: RunProjection, department: str) -> WorkBasis:
        return cls(
            effective_contract_hash=current_contract_hash(projection),
            engineering_plan_hash=current_plan_hash(projection),
            request_id=None if projection.pending_request is None else projection.pending_request.id,
            input_version=projection.input_version,
            guidance_version=guidance_version(projection, department),
        )

    def changed(self, projection: RunProjection, department: str) -> bool:
        current = WorkBasis.current(projection, department)
        return (current.effective_contract_hash != self.effective_contract_hash
                or current.engineering_plan_hash != self.engineering_plan_hash
                or current.request_id != self.request_id
                or current.input_version != self.input_version
                or current.guidance_version > self.guidance_version)


@dataclass(frozen=True)
class ToolPermission:
    # 工具许可的三种结果：允许（登记命令附带执行依据）；拒绝并说明原因，原因作为工具结果交回模型；停止
    stopped: bool = False
    reason: str | None = None
    command_basis: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return not self.stopped and self.reason is None


def offered_tools(projection: RunProjection, department: str, *, guidance_only: bool = False) -> list[str]:
    # 请求中提供给模型的工具：部门的工具，只能回应指导时限于回应指导的范围，再去掉当前工作不允许的提交
    available = tools_for(department)
    if guidance_only:
        available = [name for name in available if name in GUIDANCE_ONLY_TOOLS]
    return [name for name in available if tool_error(projection, department, name, {}) is None]


def facts_query(call: dict[str, Any]) -> FactsQuery:
    # 工具许可依据的工作区事实：写入的目标路径在工作区中的规范形式，登记命令执行依据中的公开树摘要
    name, args = call["name"], call["args"]
    if name == "run_command":
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
    if not has_tool(department, name):
        return ToolPermission(reason=f"{department} cannot use {name}")
    if guidance_only and name not in GUIDANCE_ONLY_TOOLS:
        return ToolPermission(reason="This guidance activation cannot change files or submit normal department work.")
    reason = tool_error(projection, department, name, args)
    if reason:
        return ToolPermission(reason=reason)
    command_basis: dict[str, Any] = {}
    if name == "run_command":
        # 登记命令在执行前核对冻结的登记表：未登记的名称与越界参数在这里拒绝，不执行
        reason, command_basis = _run_command_basis(projection, args, facts)
        if reason:
            return ToolPermission(reason=reason)
    if _is_write(name):
        reason = _plan_scope_error(projection, name, args, facts)
        if reason:
            return ToolPermission(reason=reason)
    return ToolPermission(command_basis=command_basis)


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
    # 提交判断：提交之前按最新的投影与工作区事实复核校验结果。激活开始以后输入、指导、合同、计划、
    # 协作请求或当前工作改变，或者校验以后工作区改变，都拒绝，不重新绑定到新的依据；仍然成立时按最新状态再校验
    before, now = WorkBasis.current(started, department), WorkBasis.current(current, department)
    if (current.phase != started.phase
            or now.input_version != basis.input_version
            or now.guidance_version != basis.guidance_version
            or now.effective_contract_hash != before.effective_contract_hash
            or now.engineering_plan_hash != before.engineering_plan_hash
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
    return TOOL_DEFS.get(name, {}).get("action") == "write"


def _write_targets(name: str, args: dict[str, Any]) -> list[Any]:
    return [args.get("source"), args.get("destination")] if name == "move_file" else [args.get("path")]


def _run_command_basis(projection: RunProjection, args: dict[str, Any],
                       facts: WorkspaceFacts) -> tuple[str | None, dict[str, Any]]:
    # 执行前依据：命令身份（登记名与完整参数）加当时公开树的摘要；只读核对，不执行
    name = args.get("name")
    if not isinstance(name, str) or not name:
        return "run_command requires a registered command name", {}
    entry = projection.registered_commands.get(name)
    if entry is None:
        return f"unknown registered command: {name}; only project-registered commands may run", {}
    extra = args.get("args", [])
    if extra is None:
        extra = []
    if not isinstance(extra, list) or any(not isinstance(item, str) for item in extra):
        return f"run_command {name} args must be a list of strings", {}
    for item in extra:
        if item not in entry.get("args", []):
            return f"argument not allowlisted for {name}: {item}", {}
    return None, {"registered_name": name, "registered_argv": [*entry["argv"], *extra],
                  "snapshot_hash": facts.tree.digest}


def _plan_scope_error(projection: RunProjection, name: str, args: dict[str, Any],
                      facts: WorkspaceFacts) -> str | None:
    # 写入只能落在当前有效合同的工程计划范围之内，按路径在工作区中的规范形式再核对一次
    plan = projection.engineering_plan
    if plan is None or plan.effective_contract_hash != current_contract_hash(projection):
        return "Submit an engineering plan for the current effective contract before writing files."
    for target in _write_targets(name, args):
        if not path_in_scope(target, plan.scope):
            return "The file is outside the current engineering plan scope; submit an adjusted plan with a reason first."
        path = facts.paths[target]
        if path.error is not None:
            return path.error
        if not path_in_scope(path.canonical, plan.scope):
            return "The resolved file is outside the current engineering plan scope."
    return None
