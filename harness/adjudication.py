# 裁决规则（U）：工具许可，以及提案校验与提交的判断。只读取投影、事件与交给它的工作区事实（由执行环境查询，
# 见 actions.py），不写入，不调用模型；许可规则可以增加，只能收紧。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .actions import FactsQuery, TreeFacts, WorkspaceFacts
from .collaboration import pending_product_input, tool_error
from .contracts import current_contract_hash
from .definitions import DEFINITIONS, Definitions
from .models import TERMINAL_STATUSES, Event, RunProjection, hash_bytes
from .tools import has_tool, in_force, offers_with_input, proposal_kind, tool_action, tools_for
from .validation import FieldError, ProposalDecision, evaluate_proposal

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


def _ask_branch_permission(projection: RunProjection, session_id: str | None, department: str,
                            name: str, definitions: Definitions) -> ToolPermission | None:
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
    if _is_write(name, definitions):
        return ToolPermission(reason="The branch session cannot modify files in the running workspace")
    if name == "submit_delivery":
        return ToolPermission(reason="The branch session cannot submit delivery")
    if name == "submit_review":
        return ToolPermission(reason="The branch session cannot submit QA review")
    if proposal_kind(name, definitions=definitions) is not None:
        return ToolPermission(reason=f"The branch session cannot submit proposal {name}")
    return None


def offered_tools(projection: RunProjection, department: str, *, session_id: str | None = None,
                  input_modalities: tuple[str, ...] = ("text",),
                  definitions: Definitions | None = None) -> list[str]:
    # 请求中提供给模型的工具：部门的工具去掉当前工作不允许的提交，
    # 最后按调用目标的输入方式去掉声明需要图像输入而调用目标不含图像的工具（设计说明第 5.6 节）
    # 工具清单读这个事项所用的那份定义（工单 #1098）；没有交的时候是当前加载的那一份
    definitions = in_force(definitions)
    available = tools_for(department, projection.kind, definitions=definitions)
    if projection.ask_by_branch(session_id) is not None:
        # 询问分支里：可以回答；层数允许时可以回问；不能写工作区、不能提交提案（工单 #473）
        chain_allowed, _ = ask_chain_decision(projection.ask_position(session_id), ask_chain_max_depth())
        nested = ["ask"] if chain_allowed else []
        if department == "product":
            return ["answer"] + nested
        allowed = [name for name in available
                   if name != "ask" and not _is_write(name, definitions)
                   and proposal_kind(name, definitions=definitions) is None]
        return allowed + ["answer"] + nested
    return [name for name in offers_with_input(available, input_modalities, definitions=definitions)
            if tool_error(projection, department, name, {}, definitions=definitions) is None]


def facts_query(call: dict[str, Any], *, definitions: Definitions | None = None) -> FactsQuery:
    # 工具许可依据的工作区事实：写入的目标路径在工作区中的规范形式，命令执行依据中的公开树摘要
    name, args = call["name"], call["args"]
    if tool_action(name, definitions=definitions) == "command":
        return FactsQuery(tree=True)
    if _is_write(name, definitions):
        return FactsQuery(paths=tuple(target for target in _write_targets(name, args) if isinstance(target, str)))
    return FactsQuery()


def tool_permission(
    projection: RunProjection,
    call: dict[str, Any],
    *,
    department: str,
    session_id: str | None = None,
    basis: WorkBasis,
    aborted: bool,
    facts: WorkspaceFacts,
    events: list[Event] | None = None,
    definitions: Definitions | None = None,
) -> ToolPermission:
    # facts 是执行环境按 facts_query(call) 查询的结果
    # 工具许可读这个事项所用的那份定义（工单 #1098）：部门能不能用这个工具、它提交什么种类按它判断；
    # 没有交的时候是当前加载的那一份
    # 有效合同、指导与用户输入变了都不再停止这次激活：它们作为通知送达，部门接着工作，
    # 这一轮不因此结束（工单 #558、工单 #964，循环结构第 5 节与第 6 节）
    definitions = in_force(definitions)
    if projection.status in TERMINAL_STATUSES or aborted:
        return ToolPermission(stopped=True)
    name, args = call["name"], call["args"]
    # 正式成果要等模型看见新输入以后再提交：这次提交先不做，下一步的通知里写明新输入
    # （工单 #964）。工具许可的依据是这次请求装配时的输入版本（basis），
    # 它比当前版本旧就说明模型还没有看到这条输入。
    if proposal_kind(name, definitions=definitions) is not None and projection.input_version != basis.input_version:
        return ToolPermission(reason=(
            "new user input arrived and has not entered this session's model input yet; "
            "this proposal is not accepted now. Read the work_notification of the next step, then submit again"
        ), deferred=True)
    branch_perm = _ask_branch_permission(projection, session_id, department, name, definitions)
    if branch_perm is not None:
        return branch_perm
    if not has_tool(department, name, projection.kind, definitions=definitions):
        return ToolPermission(reason=f"{department} cannot use {name}")
    reason = tool_error(projection, department, name, args, definitions=definitions)
    if reason:
        return ToolPermission(reason=reason)
    # 放行要等发给产品的输入处理完（部门指导设计说明第 2.1 节，工单 #561）：还有没处理完的输入时，
    # 这一次调用在安全节点上等，醒来以后按此刻的 PRD 与交付重新做许可。只有质检的放行等，缺陷记录不等；
    # 还没有交付的预测性探索也不等：没有可以放行的交付，这次提交本来就只会被拒绝
    if (_is_release_submission(department, name, args) and projection.delivery_spec is not None
            and pending_product_input(projection, list(events or ()))):
        return ToolPermission(wait_for_input=True)
    if _is_write(name, definitions):
        reason = _write_path_error(name, args, facts)
        if reason:
            return ToolPermission(reason=reason)
    return ToolPermission()


def proposal_decision(projection: RunProjection, *, department: str, proposal: dict[str, Any] | None,
                      facts: TreeFacts, events: list[Event],
                      definitions: Definitions | None = None) -> ProposalDecision:
    # 提案校验：按投影、工作区事实与事件判断提案能否接纳；自然语言与格式错误都成为字段错误。
    # 提案种类、部门与通用条件读这个事项所用的那份定义（工单 #1098）
    return evaluate_proposal(department=department, proposal=proposal, projection=projection, facts=facts,
                             events=events, definitions=definitions)


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
    definitions: Definitions | None = None,
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
                                     facts=current_facts, events=events, definitions=definitions)
    if decision.accepted and _is_pending_release(department, proposal, current, events):
        # 新输入在工具许可之后、提交之前到达：这次放行不当场生效，交回质检，等产品处理完再提交
        # （部门指导设计说明第 2.1 节，工单 #561）
        return ProposalDecision(False, [FieldError("kind", _PENDING_INPUT_RELEASE)])
    return decision


def _is_release_submission(department: str, name: str, args: dict[str, Any]) -> bool:
    # 只有质检的放行（submit_review，结论是 release）等输入处理完；质检提交缺陷记录不等（工单 #561）
    return department == "quality" and name == "submit_review" and args.get("verdict") == "release"


def _is_pending_release(department: str, proposal: dict[str, Any] | None, projection: RunProjection,
                        events: list[Event]) -> bool:
    # 同样只有放行：产品还没有处理完的输入（用户输入或发给产品的指导）让这次放行交回质检
    if department != "quality" or not isinstance(proposal, dict):
        return False
    if proposal.get("kind") != "qa_review" or proposal.get("verdict") != "release":
        return False
    return pending_product_input(projection, list(events))


def _is_write(name: str, definitions: Definitions | None = None) -> bool:
    return tool_action(name, definitions=definitions) == "write"


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


