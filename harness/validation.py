"""提案校验：内核的通用检查，以及一次接纳的统一字段与内容摘要。控制层普通代码，不调用模型。

裁决读的是最小投影（设计说明第 4 节，S1d 工单 #860）：投影没有的内容（PRD 的内容、用户输入与指导的版本、
质检测试材料）由路由的收紧检查给出，内核不读成果的内容。

S2c（工单 #1098，设计说明第 5.4 节第 3 条、第 5.5 节）之后这里只做通用检查：种类在事项所用的那份定义里、
部门有这个工具、提案合同里的通用条件（`evaluate_conditions`，条件是合同数据）。成果的格式检查、按内容的
检查与成果内容的组装都在路由的收紧检查里（`harness/tightening.py`）；内核在它给出的内容之外盖统一字段
（种类、版本、依据、作者部门、记下的树摘要）、算内容摘要，写入口写接纳事件。这里不再按成果种类写分支。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from .contracts import artifact_hash
from .kernel_events import Event, canonical_hash, spec_content_hash
from .minimal_projection import MinimalProjection
from .actions import TreeFacts
from .definitions import ConditionNames, Definitions, ProposalCondition
from .tools import in_force, proposal_kinds_of

if TYPE_CHECKING:  # 工作依据住在 adjudication.py，它导入这里：只在类型检查时导入，避免循环导入
    from .adjudication import WorkBasis


@dataclass(frozen=True)
class AdjudicationView:
    # 裁决一次判断要读的全部内容。minimal 是内核唯一的判断依据（由骨架事件折叠，设计说明第 4 节）；
    # state 是应用侧的运行状态投影（RunProjection），内核不读它，只原样交给路由的收紧检查（第 5.5 节）
    minimal: MinimalProjection
    state: Any = None


@dataclass
class FieldError:
    field: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "message": self.message}


PRD_REVISION_FIELDS = frozenset({
    "goal",
    "requirements",
    "acceptance_criteria",
    "boundaries",
    "constraints",
    "fatal_conditions",
    "non_goals",
    "change_record",
    "decision_changes",
})


@dataclass
class ProposalDecision:
    accepted: bool
    errors: list[FieldError] = field(default_factory=list)
    artifact: dict[str, Any] | None = None
    # 这次接纳以后事项结束（工单 #556）：只有质检的放行与基线核验的一致结论结束事项，
    # 结束以后控制核心不再决定下一个谁工作
    ends_run: bool = False

    @property
    def error_dicts(self) -> list[dict[str, str]]:
        return [item.to_dict() for item in self.errors]


# 路由的收紧检查（工单 #1095，设计说明第 5.5 节）：内核的通用检查通过以后，在同一个写入事务里再问一次路由。
# 结果只有三种：通过、拒绝（写明原因）、等待（写入口按安全节点等待，工单 #561）；收紧检查不能放行内核已经
# 拒绝的东西。接口放在这里是因为 validation 是 adjudication 的下游，放到那边反向导入会成环；
# 实现是应用层的事（现在是一份成果驱动的收紧检查，见 harness/tightening.py），版本与接受实现放在
# 契约圈的 harness/tightening_contract.py：内核文件不导入契约圈以外的模块。


@dataclass(frozen=True)
class TightenRequest:
    # 收紧检查的输入：这一轮的运行状态、正在做的工具或者要提交的提案，以及内核已经核对过的支撑材料。
    # state 是应用侧的运行状态投影（RunProjection）：内核不读它，原样交给收紧检查，内容是应用的（第 5.5 节）
    department: str
    state: Any
    session_id: str | None = None
    basis: WorkBasis | None = None
    tool: dict[str, Any] | None = None
    proposal: dict[str, Any] | None = None
    evidence: tuple[dict[str, Any], ...] = ()
    # 收据、结论这些支撑材料之外，检查「产品还有没有没处理完的输入」要看事件日志本身（工单 #561）
    events: tuple[Event, ...] = ()
    input_modalities: tuple[str, ...] = ("text",)
    # 这次检查在提交事务里跑：工具许可已经通过，输入可能在两者之间到达（工单 #561 的那次竞态）
    commit: bool = False
    # 这个事项所用的那份定义（工单 #1098）：部门、提案种类与工具都按它读，不读模块加载时的常量；
    # 内核不解释它，原样交给收紧检查
    definitions: Any = None
    # 内核已经核对过、交给收紧检查的两样（工单 #1098）：最小投影与工作区事实。收紧检查按成果的内容判
    # 这次提交时读它们（以及提案合同里的通用条件），内核不读成果的内容
    minimal: Any = None
    facts: Any = None


@dataclass(frozen=True)
class Tightened:
    # 收紧检查的结果：三项都为空是通过；reason 或 errors 是拒绝；wait 是等待；
    # deferred 是推迟（模型还没有看见新的输入，下一步再提交，工单 #964）
    reason: str | None = None
    errors: tuple[FieldError, ...] = ()
    wait: bool = False
    deferred: bool = False
    # 部门工具清单里没有这个工具，由收紧检查放行：询问分支里的回答不属于任何部门的工具（工单 #473）
    permitted: bool = False
    # 通过时一并给出、内核算内容时需要而最小投影里没有的事实（S1d，工单 #860）：
    # 例如 PRD 记下的用户输入版本——它是成果的内容，按设计说明第 4 节不进最小投影
    facts: dict[str, Any] = field(default_factory=dict)
    # 通过时给出的成果内容（S2c，工单 #1098，设计说明第 5.5 节「成果的内容由路由组装」）：
    # 内核在它之外盖统一字段、算内容摘要；这里为空时内容就是提案的参数（路由不组装的种类）
    content: dict[str, Any] | None = None
    # 收紧检查自己给出的内容摘要：产品决定按内容去重，摘要来自通用条件，不是内核重算的那一份
    content_hash: str | None = None
    # 这次接纳以后事项结束（工单 #556）：由路由判——成果驱动这一版只有质检放行与基线核验的一致结论结束事项
    ends_run: bool = False

    @property
    def accepted(self) -> bool:
        return self.reason is None and not self.errors and not self.wait


class Tightening(Protocol):
    # 路由实现的收紧检查：内核在同一个写入事务里调用它，三种结果由调用方分别处理。
    # 契约版本由契约圈的 harness/tightening_contract.py 声明与核对，这里只有调用的形状
    CONTRACT_VERSION: int

    def kinds(self, request: TightenRequest) -> set[str]:
        # 这个部门此刻能提交的提案种类（不含询问分支里为回答询问而修订 PRD 的那一种）
        ...

    def offered(self, request: TightenRequest) -> list[str]:
        # 请求中提供给模型的工具
        ...

    def tool(self, request: TightenRequest) -> Tightened:
        # 一次工具调用的许可
        ...

    def submission(self, request: TightenRequest) -> Tightened:
        # 一次提案提交的检查
        ...


def evaluate_proposal(
    view: AdjudicationView,
    *,
    department: str,
    proposal: dict[str, Any] | None,
    facts: TreeFacts,
    tightening: Tightening,
    events: list[Event] | None = None,
    definitions: Definitions | None = None,
) -> ProposalDecision:
    try:
        return _evaluate_proposal(
            view=view,
            department=department,
            proposal=proposal,
            facts=facts,
            tightening=tightening,
            events=events or [],
            definitions=definitions,
        )
    except Exception as exc:
        return ProposalDecision(
            False,
            [FieldError("proposal", f"invalid proposal payload: {type(exc).__name__}: {exc}")],
        )


@dataclass
class ConditionOutcome:
    # 通用条件的结果：错误、绑定的检查回执（按检查名），以及 no_duplicate_content 算出的内容与摘要
    errors: list[FieldError] = field(default_factory=list)
    receipts: dict[str, dict[str, Any]] = field(default_factory=dict)
    content: dict[str, Any] | None = None
    content_hash: str | None = None


@dataclass
class _ConditionContext:
    department: str
    proposal: dict[str, Any]
    minimal: MinimalProjection
    facts: TreeFacts


# 条件读的当前成果：合同里的名称与最小投影里的成果种类；product_decisions 是多版并存的那一种
_ARTIFACTS = {
    "product_spec": "product_spec",
    "delivery_spec": "delivery_spec",
    "contract": "contract",
    "structure": "structure",
    "snapshot": "snapshot",
    "product_decisions": "product_decision",
}


def evaluate_conditions(kind: str, *, department: str, proposal: dict[str, Any], minimal: MinimalProjection,
                        facts: TreeFacts, definitions: Definitions | None = None) -> ConditionOutcome:
    """按提案合同核对一种提案的通用条件（设计说明第 5.5 节）。

    条件与参数来自 proposal_contracts.json，内核只按条件名分派：改合同数据就能放宽或收紧这条规则，
    代码里不再写死哪一种成果要绑定哪一份当前版本。条件按合同里列出的顺序核对，
    读的是最小投影里的摘要、依据、作者部门、记下的树摘要与按部门的本轮编号，不读成果的内容。
    """
    context = _ConditionContext(department=department, proposal=proposal, minimal=minimal, facts=facts)
    outcome = ConditionOutcome()
    for condition in in_force(definitions).proposal_conditions(kind):
        _CONDITION_CHECKS[condition.condition](condition, context, outcome)
    return outcome


def _current_artifact(minimal: MinimalProjection, name: str) -> Any:
    return minimal.artifact(_ARTIFACTS[name])


def _missing_error(condition: ProposalCondition) -> list[FieldError]:
    # 条件引用的成果不存在时的错误，由合同给出字段与理由
    missing = condition.missing
    return [] if missing is None else [FieldError(missing.field, missing.message)]


def _condition_basis_current(condition: ProposalCondition, context: _ConditionContext, outcome: ConditionOutcome) -> None:
    # 通用条件 1：引用的成果是当前版本（提案声明的依据版本与当前版本相同）
    current = artifact_hash(_current_artifact(context.minimal, condition.target))
    outcome.errors.extend(_basis_hash_errors(context.proposal, condition.field, current))


def _condition_referenced_current(condition: ProposalCondition, context: _ConditionContext, outcome: ConditionOutcome) -> None:
    # 通用条件 2：引用的成果所依据的成果也是当前版本（依据按「成果种类 → 内容摘要」记下）
    artifact = _current_artifact(context.minimal, condition.artifact)
    if artifact is None:
        outcome.errors.extend(_missing_error(condition))
        return
    for item in condition.referenced:
        current = artifact_hash(_current_artifact(context.minimal, item.target))
        if artifact.basis.get(item.target) != current:
            outcome.errors.append(FieldError(item.error_field or item.field, item.message))


def _recorded_tree(minimal: MinimalProjection, recorded_in: str) -> str | None:
    # 成果记下的树摘要：建档时的快照或当前交付（接纳事件的统一字段带来，不读内容）
    artifact = _current_artifact(minimal, recorded_in)
    return None if artifact is None else artifact.tree_digest


def _condition_tree_matches(condition: ProposalCondition, context: _ConditionContext, outcome: ConditionOutcome) -> None:
    # 通用条件 4：工作区的树与引用的成果记下的树一致
    recorded = _recorded_tree(context.minimal, condition.recorded_in)
    if recorded is None:
        outcome.errors.extend(_missing_error(condition))
        return
    if context.facts.digest != recorded:
        outcome.errors.append(FieldError(
            condition.field, condition.message.format(actual=context.facts.digest, recorded=recorded)))


def _condition_author_separation(condition: ProposalCondition, context: _ConditionContext, outcome: ConditionOutcome) -> None:
    # 通用条件 5：提出评价类成果的部门不是被评价成果的作者部门（基础规则 3）
    artifact = _current_artifact(context.minimal, condition.evaluated)
    if artifact is None:
        return
    if artifact.issuer is not None and artifact.issuer == context.department:
        outcome.errors.append(FieldError(
            condition.field, condition.message.format(department=context.department)))


def _condition_check_receipts(condition: ProposalCondition, context: _ConditionContext, outcome: ConditionOutcome) -> None:
    # 通用条件 3：列出的检查都有主机执行的回执，回执来自这个会话的这一轮，并绑定当前的依据
    names = _condition_check_names(condition.names, context.proposal)
    activation = context.minimal.rounds.get(condition.department) if condition.activation else None
    bindings = {item.field: artifact_hash(_current_artifact(context.minimal, item.target))
                for item in condition.bind}
    for name, field_name in names:
        receipt = context.facts.latest_check(condition.department, name, activation_id=activation, **bindings)
        if receipt is None:
            outcome.errors.append(FieldError(field_name, condition.message.format(name=name)))
            continue
        outcome.receipts[name] = _receipt_evidence(receipt)


def _condition_check_names(names: ConditionNames, proposal: dict[str, Any]) -> list[tuple[str, str]]:
    # 提案里列出的检查名与它的错误字段：字符串列表，或对象列表里的名称字段
    if names.field is not None:
        values = proposal.get(names.field) or []
        return [((item.strip() if names.trim else item), names.field) for item in values]
    items = proposal.get(names.items) or []
    return [((item[names.item].strip() if names.trim else item[names.item]),
             f"{names.items}[{index}].{names.item}") for index, item in enumerate(items)]


def _condition_no_duplicate_content(condition: ProposalCondition, context: _ConditionContext, outcome: ConditionOutcome) -> None:
    # 通用条件 6：同样内容的成果不重复接纳；内容由合同列出，绑定当前版本的部分算在摘要里。
    # 比的是这一种成果当前有效的各版（多版并存的种类按清单，单版的种类只有一版）
    content = {name: context.proposal[name].strip() for name in condition.content}
    content.update({item.field: artifact_hash(_current_artifact(context.minimal, item.target))
                    for item in condition.bind})
    content_hash = canonical_hash(content)
    accepted = context.minimal.versions_of(_ARTIFACTS[condition.collection])
    if any(item.content_hash == content_hash for item in accepted):
        outcome.errors.append(FieldError(condition.field, condition.message))
    outcome.content = content
    outcome.content_hash = content_hash


_CONDITION_CHECKS = {
    "basis_current": _condition_basis_current,
    "referenced_current": _condition_referenced_current,
    "check_receipts": _condition_check_receipts,
    "tree_matches": _condition_tree_matches,
    "author_separation": _condition_author_separation,
    "no_duplicate_content": _condition_no_duplicate_content,
}


def _tightening_errors(tightened: Tightened, field: str = "proposal") -> list[FieldError]:
    # 收紧检查的拒绝转成字段错误，通过时是空清单。等待在提案校验这一步同样当作拒绝：
    # 这次提交不当场生效，原因写明（新输入在许可之后、提交之前到达，工单 #561）
    if tightened.errors:
        return list(tightened.errors)
    if tightened.wait:
        return [FieldError("kind", tightened.reason or "the submission must wait for the product input")]
    if tightened.reason is not None:
        return [FieldError(field, tightened.reason)]
    return []


def _evaluate_proposal(
    *,
    view: AdjudicationView,
    department: str,
    proposal: dict[str, Any] | None,
    facts: TreeFacts,
    tightening: Tightening,
    events: list[Event],
    definitions: Definitions | None = None,
) -> ProposalDecision:
    if not proposal or not isinstance(proposal, dict):
        return ProposalDecision(False, [FieldError("proposal", "structured proposal is required; natural language cannot change state")])
    # 种类与部门读这个事项所用的那份定义（工单 #1098）：模块加载时算好的常量里没有第二种路由带来的种类
    definition = in_force(definitions)
    kind = proposal.get("kind")
    if kind not in proposal_kinds_of(definitions=definition):
        return ProposalDecision(False, [FieldError("kind", f"unknown proposal kind: {kind!r}")])
    if department not in definition.departments:
        return ProposalDecision(False, [FieldError("issuer", f"unknown department: {department}")])
    # 这个部门此刻能提交哪些种类是成果驱动的：问路由的收紧检查（不能放行内核拒绝的东西，
    # 内核先判过上面的格式与部门，再按收紧检查给出的种类收窄）
    request = TightenRequest(department=department, state=view.state, proposal=proposal,
                             events=tuple(events), minimal=view.minimal, facts=facts,
                             definitions=definition)
    if kind not in tightening.kinds(request):
        return ProposalDecision(False, [FieldError("kind", f"{department} cannot issue {kind} in the current work")])
    # 格式检查、成果驱动的内容检查与成果内容的组装都归路由（设计说明第 5.5 节，工单 #1098）：
    # 内核问它一次，通过时它给出成果的内容；路由不组装的种类，内容就是提案的参数
    tightened = tightening.submission(request)
    errors = _tightening_errors(tightened)
    if errors:
        return ProposalDecision(False, errors)
    # 收紧检查只收窄：它放行以后内核自己的通用条件（提案合同）照样要成立，两侧都通过才算接纳。
    # 六种成果驱动的种类由收紧检查在组装内容时已经问过一次（先后与搬动以前一致），这里再判一次，
    # 路由不组装的种类与换过实现的收紧检查都不能把内核的条件绕过去
    outcome = evaluate_conditions(kind, department=department, proposal=proposal, minimal=view.minimal,
                                  facts=facts, definitions=definition)
    if outcome.errors:
        return ProposalDecision(False, outcome.errors)
    content = tightened.content if tightened.content is not None else {
        key: value for key, value in proposal.items() if key != "kind"}
    return ProposalDecision(True, artifact=_accepted(kind, content, department=department,
                                                     minimal=view.minimal, facts=facts,
                                                     content_hash=tightened.content_hash),
                            ends_run=tightened.ends_run)


def _accepted(kind: str, content: dict[str, Any], *, department: str, minimal: MinimalProjection,
              facts: TreeFacts, content_hash: str | None = None) -> dict[str, Any]:
    """内核在成果的内容之外盖的统一字段（设计说明第 5.5 节，工单 #1098）。

    内核不认识成果的内容：种类、版本、依据、作者部门与记下的树摘要都由这里按最小投影与工作区事实给出，
    内容摘要也由这里算（内容本身不参与判断）。收紧检查自己给出了内容摘要时用它——产品决定按内容去重，
    摘要来自通用条件而不是这里重算。
    """
    # 上一版是最后一次被接纳的那一版（失效以后仍然算上一版），版本号接着它编（S1d，工单 #860）
    previous = minimal.latest(kind)
    parent = None if previous is None else previous.content_hash
    revision = 1 if previous is None else previous.version + 1
    return {
        **content,
        "kind": kind,
        "issuer": department,
        "parent_hash": parent,
        "revision": revision,
        "status": "active",
        "content_hash": content_hash or spec_content_hash(kind, content, parent_hash=parent, revision=revision),
    }


def _receipt_evidence(receipt: Any) -> dict[str, Any]:
    return {
        "activation_id": receipt.activation_id,
        "delivery_spec_hash": receipt.delivery_spec_hash,
        "exit_code": receipt.exit_code,
        "name": receipt.name,
        "product_spec_hash": receipt.product_spec_hash,
        "effective_contract_hash": receipt.effective_contract_hash,
        "snapshot_hash": receipt.snapshot_hash,
        "summary": receipt.summary,
        "qa_tests_hash": getattr(receipt, "qa_tests_hash", None),
    }


# 提交者声明的依据版本（工单 #471）：每个正式成果都要写明它依据的版本；与当前 host 端有效版本的
# content_hash 不一致时整次提交被拒绝，错误指向声明的字段，消息给出实际当前版本，便于模型重试
def _basis_hash_errors(proposal: dict[str, Any], field: str, current_hash: str | None) -> list[FieldError]:
    if field not in proposal:
        return [FieldError(field, f"{field} is required; declare the version this artifact is based on")]
    value = proposal[field]
    if value is not None and (not isinstance(value, str) or not value.strip()):
        return [FieldError(field, f"{field} must be a content hash string or null")]
    if current_hash is None:
        if value is not None:
            return [FieldError(field, f"{field} must be null when no current version exists; current value is {value!r}")]
        return []
    if value != current_hash:
        return [FieldError(field, f"submitted artifact is based on {value!r}; current version is {current_hash!r}. Read the current version and submit again.")]
    return []
