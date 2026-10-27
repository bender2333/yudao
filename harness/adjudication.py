# 裁决规则（U）：工具许可，以及提案校验与提交的判断。只读取投影、事件与交给它的工作区事实（由执行环境查询，
# 见 actions.py），不写入，不调用模型；许可规则可以增加，只能收紧。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .actions import FactsQuery, TreeFacts, WorkspaceFacts
from .contracts import current_contract_hash
from .definitions import DEFINITIONS
from .models import TERMINAL_STATUSES, Event, RunProjection, hash_bytes
from .tools import has_tool, tool_action
from .validation import (FieldError, ProposalDecision, TightenRequest, Tightening, evaluate_proposal)

_STALE_BASIS = ("The input, contract, or current work changed after this activation began; "
                "stale results cannot be rebound.")
_STALE_SNAPSHOT = "The workspace snapshot changed after this activation began; stale results cannot be rebound."
_PENDING_INPUT_RELEASE = ("New user input is waiting for the product; the release is judged after the product "
                          "round that received it has ended.")


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
    # 激活开始时采用的工作依据；有效合同、指导与用户输入变了以后，这个会话在下一步收到通知
    # （新版本与改动、新的输入），接着工作，一轮工作不因此结束（工单 #558、工单 #964，
    # 循环结构第 5 节与第 6 节）。
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


@dataclass(frozen=True)
class ToolPermission:
    # 工具许可的三种结果：允许；拒绝并说明原因，原因作为工具结果交回模型；停止
    # deferred：这次拒绝只是推迟（工单 #964）——模型还没有看见新的用户输入，提交推迟到下一步，
    # 通知在下一步送达，部门接着工作，这一轮不因此结束
    # wait_for_input：等输入处理完（工单 #561）——质检提交放行时发给产品的输入还没有处理完，
    # 这次调用在安全节点上等到处理完再重新做工具许可；不返回模型、不写事件、不占步数
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


def offered_tools(projection: RunProjection, department: str, *, tightening: Tightening,
                  session_id: str | None = None, input_modalities: tuple[str, ...] = ("text",)) -> list[str]:
    # 请求中提供给模型的工具：内核给出部门完整的工具清单，由路由的收紧检查按这一轮的工作与询问分支取舍，
    # 再按调用目标的输入方式去掉声明需要图像输入的工具（设计说明第 5.6 节，工单 #1095）
    return tightening.offered(TightenRequest(department=department, projection=projection,
                                             session_id=session_id, input_modalities=input_modalities))


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
    tightening: Tightening,
    basis: WorkBasis,
    aborted: bool,
    facts: WorkspaceFacts,
    session_id: str | None = None,
    events: list[Event] | None = None,
) -> ToolPermission:
    # facts 是执行环境按 facts_query(call) 查询的结果
    # 有效合同、指导与用户输入变了都不再停止这次激活：它们作为通知送达，部门接着工作，
    # 这一轮不因此结束（工单 #558、工单 #964，循环结构第 5 节与第 6 节）
    if projection.status in TERMINAL_STATUSES or aborted:
        return ToolPermission(stopped=True)
    name, args = call["name"], call["args"]
    # 成果驱动的取舍交给路由的收紧检查（工单 #1095）：推迟、询问分支、这个部门此刻能交的种类、放行等输入处理完。
    # 内核自己判的是运行状态（上面）、部门有没有这个工具与写入目标的规范形式（下面）
    tight = tightening.tool(TightenRequest(department=department, projection=projection,
                                           session_id=session_id, basis=basis, tool=call,
                                           events=tuple(events or ())))
    if tight.wait:
        # 等待由步骤驱动的安全节点处理（工单 #561）：不写事件、不占步数、不返回模型
        return ToolPermission(wait_for_input=True)
    if tight.errors:
        return ToolPermission(reason=tight.errors[0].message)
    if tight.reason is not None:
        return ToolPermission(reason=tight.reason, deferred=tight.deferred)
    if not tight.permitted and not has_tool(department, name, projection.kind):
        return ToolPermission(reason=f"{department} cannot use {name}")
    if _is_write(name):
        reason = _write_path_error(name, args, facts)
        if reason:
            return ToolPermission(reason=reason)
    return ToolPermission()


def proposal_decision(projection: RunProjection, *, department: str, proposal: dict[str, Any] | None,
                      facts: TreeFacts, tightening: Tightening, events: list[Event]) -> ProposalDecision:
    # 提案校验：按投影、工作区事实与事件判断提案能否接纳；自然语言与格式错误都成为字段错误
    return evaluate_proposal(department=department, proposal=proposal, projection=projection,
                             facts=facts, tightening=tightening, events=events)


def commit_decision(
    decision: ProposalDecision,
    *,
    department: str,
    proposal: dict[str, Any] | None,
    evaluated: RunProjection,
    facts: TreeFacts,
    current: RunProjection,
    current_facts: TreeFacts,
    events: list[Event],
    tightening: Tightening,
) -> ProposalDecision:
    # 提交判断：提交之前按最新的投影与工作区事实复核校验结果。校验以后工作区改变，
    # 或者当前工作已经不是校验时的那一份，都拒绝，不重新绑定到新的依据；仍然成立时按最新状态再校验。
    # 有效合同、指导与用户输入变了不再让这次提交作废：它们作为通知送达，部门接着工作，
    # 提交的成果按当前版本核对（工单 #558、工单 #964，循环结构第 5 节、第 6 节与第 7 节）
    if submission_basis(current) != submission_basis(evaluated):
        decision = ProposalDecision(False, [FieldError("execution_basis", _STALE_BASIS)])
    if current_facts != facts:
        return ProposalDecision(False, [FieldError("execution_basis", _STALE_SNAPSHOT)])
    if decision.accepted:
        decision = proposal_decision(current, department=department, proposal=proposal,
                                     facts=current_facts, tightening=tightening, events=events)
    if decision.accepted:
        # 新输入在工具许可之后、提交之前到达：这次提交不当场生效，交回部门，等产品处理完再提交
        # （部门指导设计说明第 2.1 节，工单 #561）。这件事由路由的收紧检查在提交事务里再判一次（工单 #1095）
        tight = tightening.submission(TightenRequest(department=department, projection=current, proposal=proposal,
                                                     events=tuple(events), commit=True))
        if tight.wait:
            return ProposalDecision(False, [FieldError("kind", _PENDING_INPUT_RELEASE)])
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


