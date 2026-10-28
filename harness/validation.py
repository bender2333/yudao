"""提案 schema、权限、前置条件和绑定校验。控制层普通代码，不调用模型。

裁决读的是最小投影（设计说明第 4 节，S1d 工单 #860）：投影没有的内容（PRD 的内容、用户输入与指导的版本、
质检测试材料）由路由的收紧检查给出，内核不读成果的内容。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from .contracts import artifact_hash, normalize_scope
from .kernel_events import BASELINE_STATUSES, QA_VERDICTS, Event, canonical_hash, spec_content_hash
from .minimal_projection import MinimalProjection
from .actions import TreeFacts
from .definitions import DEFINITIONS, ConditionNames, ProposalCondition

# 提案种类：提交类工具在定义里提交的种类。提案校验按这份清单判断种类认不认识（S2c 改为读事项所用的定义）
PROPOSAL_KINDS = tuple(tool.proposal for tool in DEFINITIONS.tools.values() if tool.proposal is not None)

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
) -> ProposalDecision:
    try:
        return _evaluate_proposal(
            view=view,
            department=department,
            proposal=proposal,
            facts=facts,
            tightening=tightening,
            events=events or [],
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
                        facts: TreeFacts) -> ConditionOutcome:
    """按提案合同核对一种提案的通用条件（设计说明第 5.5 节）。

    条件与参数来自 proposal_contracts.json，内核只按条件名分派：改合同数据就能放宽或收紧这条规则，
    代码里不再写死哪一种成果要绑定哪一份当前版本。条件按合同里列出的顺序核对，
    读的是最小投影里的摘要、依据、作者部门、记下的树摘要与按部门的本轮编号，不读成果的内容。
    """
    context = _ConditionContext(department=department, proposal=proposal, minimal=minimal, facts=facts)
    outcome = ConditionOutcome()
    for condition in DEFINITIONS.proposal_conditions(kind):
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
) -> ProposalDecision:
    if not proposal or not isinstance(proposal, dict):
        return ProposalDecision(False, [FieldError("proposal", "structured proposal is required; natural language cannot change state")])
    kind = proposal.get("kind")
    if kind not in PROPOSAL_KINDS:
        return ProposalDecision(False, [FieldError("kind", f"unknown proposal kind: {kind!r}")])
    if department not in DEFINITIONS.departments:
        return ProposalDecision(False, [FieldError("issuer", f"unknown department: {department}")])
    # 这个部门此刻能提交哪些种类是成果驱动的：问路由的收紧检查（不能放行内核拒绝的东西，
    # 内核先判过上面的格式与部门，再按收紧检查给出的种类收窄）
    allowed = tightening.kinds(TightenRequest(department=department, state=view.state))
    if kind not in allowed:
        return ProposalDecision(False, [FieldError("kind", f"{department} cannot issue {kind} in the current work")])

    errors = _validate_schema(kind, proposal)
    if errors:
        return ProposalDecision(False, errors)

    if kind == "product_spec":
        return _accept_product_spec(proposal, view, facts, department, tightening, events)
    if kind == "product_decision":
        return _accept_product_decision(proposal, view, facts, department)
    if kind == "delivery_spec":
        return _accept_delivery(proposal, view, facts, department)
    if kind == "qa_review":
        return _accept_review(proposal, view, facts, department, tightening, events)
    if kind == "structure":
        return _accept_structure(proposal, view, facts, department, tightening, events)
    if kind == "baseline_review":
        return _accept_baseline_review(proposal, view, facts, department, tightening, events)
    return ProposalDecision(False, [FieldError("kind", "unhandled kind")])


def _validate_schema(kind: str, proposal: dict[str, Any]) -> list[FieldError]:
    if kind == "product_decision":
        return _require_text(proposal, "statement") + _require_text(proposal, "rationale")
    if kind == "product_spec":
        return _require_text(proposal, "goal") + _require_string_list(proposal, "requirements", min_items=1) + _require_string_list(
            proposal, "acceptance_criteria", min_items=1
        ) + _optional_string_list(proposal, "boundaries") + _optional_string_list(proposal, "constraints") + _optional_string_list(
            proposal, "fatal_conditions"
        ) + _optional_string_list(proposal, "non_goals") + _decision_change_errors(proposal) + _change_record_errors(proposal)
    if kind == "delivery_spec":
        return (
            _require_text(proposal, "summary")
            + _require_string_list(proposal, "check_names", min_items=1)
            + _optional_string_list(proposal, "known_risks")
        )
    if kind == "qa_review":
        errors = _require_text(proposal, "rationale")
        verdict = proposal.get("verdict")
        if verdict not in QA_VERDICTS:
            errors.append(FieldError("verdict", "verdict must be rework_engineering or release"))
        errors.extend(_qa_defects_errors(proposal))
        errors.extend(_qa_check_name_errors(proposal))
        defects = [] if "defects" not in proposal else proposal.get("defects")
        if verdict == "release" and isinstance(defects, list) and defects:
            errors.append(FieldError("defects", "release requires an empty defect list"))
        if verdict == "rework_engineering" and isinstance(defects, list) and not defects:
            errors.append(FieldError("defects", "rework requires at least one defect"))
        return errors
    if kind == "structure":
        return _structure_schema_errors(proposal)
    if kind == "baseline_review":
        return _baseline_review_schema_errors(proposal)
    return [FieldError("kind", "unknown kind")]




def _structure_schema_errors(proposal: dict[str, Any]) -> list[FieldError]:
    # submit_structure 的参数形状（definitions/tools.json）：五组必填，约定与注意事项可省略
    allowed = {"kind", "overall", "modules", "entry_points", "build_and_test", "requirement_locations", "conventions"}
    errors = [FieldError(str(key), "unknown field") for key in proposal if key not in allowed]
    errors.extend(_require_text(proposal, "overall"))
    errors.extend(_record_list_errors(proposal, "modules", {"path", "responsibility"}, ("path", "responsibility")))
    entry_errors = _record_list_errors(proposal, "entry_points", {"kind", "path", "how_to_run"}, ("kind", "path", "how_to_run"))
    for index, item in enumerate(proposal.get("entry_points", [])):
        if isinstance(item, dict) and item.get("kind") not in {"program", "command_line", "service"}:
            entry_errors.append(FieldError(f"entry_points[{index}].kind", "kind must be program, command_line, or service"))
    errors.extend(entry_errors)
    errors.extend(_record_list_errors(proposal, "build_and_test", {"name", "command", "purpose"}, ("name", "purpose")))
    for index, item in enumerate(proposal.get("build_and_test", [])):
        if isinstance(item, dict):
            errors.extend(FieldError(f"build_and_test[{index}].command", error.message)
                          for error in _require_text(item, "command"))
    errors.extend(_record_list_errors(proposal, "requirement_locations", {"requirement", "locations"},
                                      ("requirement",)))
    for index, item in enumerate(proposal.get("requirement_locations", [])):
        if isinstance(item, dict):
            errors.extend(FieldError(f"requirement_locations[{index}].{error.field}", error.message)
                          for error in _require_string_list(item, "locations", min_items=1))
    for field in ("modules", "entry_points", "build_and_test", "requirement_locations"):
        value = proposal.get(field)
        if isinstance(value, list) and not value:
            errors.append(FieldError(field, f"{field} must contain at least one entry"))
    return errors + _optional_string_list(proposal, "conventions")


def _baseline_review_schema_errors(proposal: dict[str, Any]) -> list[FieldError]:
    # submit_baseline_review 的参数形状（definitions/tools.json）：结论必填，遗漏与其他失败可省略
    allowed = {"kind", "verdict", "conclusions", "omissions", "checks", "other_failures"}
    errors = [FieldError(str(key), "unknown field") for key in proposal if key not in allowed]
    if proposal.get("verdict") not in {"consistent", "rework_product"}:
        errors.append(FieldError("verdict", "verdict must be consistent or rework_product"))
    errors.extend(_record_list_errors(proposal, "conclusions", {"requirement", "status", "evidence"},
                                     ("requirement", "status", "evidence")))
    for index, item in enumerate(proposal.get("conclusions", [])):
        if isinstance(item, dict) and item.get("status") not in BASELINE_STATUSES:
            errors.append(FieldError(f"conclusions[{index}].status",
                                     "status must be verified, read_only, existing_defect, or unsupported"))
    conclusions = proposal.get("conclusions")
    if isinstance(conclusions, list) and not conclusions:
        errors.append(FieldError("conclusions", "conclusions must cover every requirement of the initial PRD"))
    errors.extend(_qa_check_name_errors(proposal))
    errors.extend(_record_list_errors(proposal, "omissions", {"capability", "location"}, ("capability", "location"),
                                      required_field=False))
    errors.extend(_record_list_errors(proposal, "other_failures", {"check", "reason"}, ("check", "reason"),
                                      required_field=False))
    return errors


def _record_list_errors(proposal: dict[str, Any], field: str, allowed: set[str], texts: tuple[str, ...],
                       *, required_field: bool = True) -> list[FieldError]:
    # 对象清单的通用形状校验：多余的字段名、必填的文字字段；argv 与 locations 这类字符串清单由调用方另行校验
    value = proposal.get(field)
    if value is None and not required_field:
        if field in proposal:
            proposal[field] = []
        return []
    if not isinstance(value, list):
        return [FieldError(field, f"{field} must be a list of objects")]
    errors: list[FieldError] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(FieldError(f"{field}[{index}]", f"{field} items must be objects"))
            continue
        errors.extend(FieldError(f"{field}[{index}].{key}", "unknown field")
                      for key in item if key not in allowed)
        for name in texts:
            errors.extend(FieldError(f"{field}[{index}].{error.field}", error.message)
                          for error in _require_text(item, name))
    return errors


def _location_errors(field: str, values: list[Any], facts: TreeFacts) -> list[FieldError]:
    # 结构说明里写出的位置必须是工作区公开树中真实存在的路径（文件或目录前缀）
    errors: list[FieldError] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            errors.append(FieldError(field, "locations must be non-empty workspace-relative strings"))
            continue
        try:
            relative = normalize_scope(value)
        except ValueError:
            errors.append(FieldError(field, f"invalid workspace location: {value!r}"))
            continue
        errors.extend([] if _location_known(relative, facts) else
                      [FieldError(field, f"unknown workspace location: {value!r}")])
    return errors


def _location_known(relative: str, facts: TreeFacts) -> bool:
    if relative == ".":
        return True
    if relative.endswith("/"):
        return any(item.startswith(relative) for item in facts.files)
    return any(item == relative or item.startswith(relative + "/") for item in facts.files)


def _baseline_conclusions(proposal: dict[str, Any], bound: dict[str, dict[str, Any]],
                          facts: TreeFacts) -> tuple[list[dict[str, str]], list[FieldError]]:
    # 每条结论的依据按状态检查（设计第 4.5 节）。逐条结论覆盖初始 PRD 的每条要求读的是 PRD 的内容，
    # 不在这里：由路由的收紧检查核对（S1d，工单 #860）
    declared = [item["requirement"].strip() for item in proposal["conclusions"]]
    errors: list[FieldError] = []
    if len(declared) != len(set(declared)):
        errors.append(FieldError("conclusions", "each requirement may carry only one conclusion"))
    conclusions: list[dict[str, str]] = []
    for index, item in enumerate(proposal["conclusions"]):
        requirement, status, evidence = item["requirement"].strip(), item["status"], item["evidence"].strip()
        field = f"conclusions[{index}].evidence"
        if status == "verified":
            errors.extend(_check_evidence_error(field, evidence, bound, expect_exit=0,
                                                label="verified requires evidence naming a passing baseline check"))
        elif status == "read_only":
            if not _location_known(evidence.replace("\\", "/"), facts):
                errors.append(FieldError(field, "read_only requires evidence naming a location in the snapshot"))
        elif status == "existing_defect":
            errors.extend(_check_evidence_error(field, evidence, bound, expect_exit=None,
                                                label="existing_defect requires evidence naming a failing baseline check"))
        elif status == "unsupported":
            if evidence in bound:
                errors.append(FieldError(field, "unsupported must not name a baseline check; it states that nothing supports "
                                                "the requirement"))
            elif evidence.lower() in {"none", "n/a", "no basis", ""}:
                errors.append(FieldError(field, "unsupported must state why code, documentation and tests none of them support "
                                                 "the requirement"))
        conclusions.append({"requirement": requirement, "status": status, "evidence": evidence})
    return conclusions, errors


def _check_evidence_error(field: str, evidence: str, bound: dict[str, dict[str, Any]], *, expect_exit: int | None,
                         label: str) -> list[FieldError]:
    # 结论的依据指向本次激活中真实运行过的基线检查；verified 要求退出状态为 0，existing_defect 要求不为 0
    if evidence not in bound:
        if expect_exit is None:
            return [FieldError(field, "existing_defect requires evidence naming a baseline check run in this activation")]
        return [FieldError(field, label)]
    exit_code = bound[evidence]["exit_code"]
    if expect_exit is not None and exit_code != expect_exit:
        return [FieldError(field, f"check {evidence} exited {exit_code}; {label}")]
    if expect_exit is None and exit_code == 0:
        return [FieldError(field, f"check {evidence} exited 0; {label}")]
    return []


def _baseline_omission_records(proposal: dict[str, Any], facts: TreeFacts) -> tuple[list[dict[str, str]], list[FieldError]]:
    # 遗漏必须写出仓库中真实存在的所在
    errors: list[FieldError] = []
    records: list[dict[str, str]] = []
    for index, item in enumerate(proposal.get("omissions", [])):
        capability, location = item["capability"].strip(), item["location"].strip()
        records.append({"capability": capability, "location": location})
        errors.extend(_location_errors(f"omissions[{index}].location", [location], facts))
    return records, errors


def _accept_product_spec(proposal: dict[str, Any], view: AdjudicationView, facts: TreeFacts,
                         department: str, tightening: Tightening, events: list[Event]) -> ProposalDecision:
    # 输入版本、修订说明、有效决定逐条处置都是成果驱动的检查：经路由的收紧检查（工单 #1095）。
    # 输入版本最先判（新输入还没进产品这一轮时只报这一条），修订说明与有效决定排在通用条件之后，
    # 与搬动以前各条报错的先后一致。输入版本是成果的内容，不进最小投影，由收紧检查一并给回（S1d）
    untimely = tightening.submission(TightenRequest(
        department=department, state=view.state, proposal=proposal, events=tuple(events)))
    errors = _tightening_errors(untimely)
    stale_input = [error for error in errors if error.field == "input_version"]
    if stale_input:
        return ProposalDecision(False, stale_input)
    outcome = evaluate_conditions("product_spec", department=department, proposal=proposal,
                                  minimal=view.minimal, facts=facts)
    if outcome.errors:
        return ProposalDecision(False, outcome.errors)
    if errors:
        return ProposalDecision(False, errors)
    minimal = view.minimal
    # 上一版是最后一次被接纳的那一版（失效以后仍然算上一版），版本号接着它编（S1d，工单 #860）
    previous = minimal.latest("product_spec")
    parent = None if previous is None else previous.content_hash
    revision = 1 if previous is None else previous.version + 1
    payload = _product_payload(proposal)
    payload["input_version"] = int(untimely.facts.get("input_version") or 0)
    artifact = {
        **payload,
        "kind": "product_spec",
        "issuer": "product",
        "parent_hash": parent,
        "revision": revision,
        "status": "active",
        "content_hash": spec_content_hash("product_spec", payload, parent_hash=parent, revision=revision),
    }
    # PRD 被接纳以后由关注的成果决定下一个谁工作（工单 #556）：这里不再写阶段迁移
    return ProposalDecision(True, artifact=artifact)


def _accept_product_decision(proposal: dict[str, Any], view: AdjudicationView, facts: TreeFacts,
                             department: str) -> ProposalDecision:
    if view.minimal.artifact("product_spec") is None:
        return ProposalDecision(False, [FieldError("product_spec", "a product decision requires an active ProductSpec")])
    outcome = evaluate_conditions("product_decision", department=department, proposal=proposal,
                                  minimal=view.minimal, facts=facts)
    if outcome.errors:
        return ProposalDecision(False, outcome.errors)
    return ProposalDecision(True, artifact={**(outcome.content or {}), "kind": "product_decision",
                                            "content_hash": outcome.content_hash})


def _accept_delivery(proposal: dict[str, Any], view: AdjudicationView, facts: TreeFacts,
                     department: str) -> ProposalDecision:
    minimal = view.minimal
    spec_hash = minimal.artifact_hash("product_spec")
    if spec_hash is None:
        return ProposalDecision(False, [FieldError("product_spec", "no active ProductSpec")])
    contract_hash = minimal.artifact_hash("contract")
    if contract_hash is None:
        return ProposalDecision(False, [FieldError("effective_contract", "delivery requires a current effective contract")])
    # 依据版本与检查回执由合同里的通用条件核对（设计说明第 5.5 节）：绑定当前 ProductSpec 与合同、来自这一轮
    outcome = evaluate_conditions("delivery_spec", department=department, proposal=proposal,
                                  minimal=minimal, facts=facts)
    if outcome.errors:
        return ProposalDecision(False, outcome.errors)
    # 交付的文件清单由主机从封存的交付快照得出：公开树的全部文件，按路径排序（工单 #677）。
    # 工程不再填清单——三份真实交付的清单只写了「这次改的那个文件」，用户按清单下载拿不全成果。
    files = sorted(item.replace("\\", "/") for item in facts.files)
    checks = [outcome.receipts[name] for name in proposal["check_names"] if name in outcome.receipts]
    previous = minimal.latest("delivery_spec")
    parent = None if previous is None else previous.content_hash
    revision = 1 if previous is None else previous.version + 1
    payload = {
        "summary": proposal["summary"].strip(),
        "files": files,
        "check_names": list(proposal["check_names"]),
        "checks": checks,
        "known_risks": [item.strip() for item in proposal.get("known_risks", [])],
        "product_spec_hash": spec_hash,
        "effective_contract_hash": contract_hash,
        "code_tree_digest": facts.digest,
    }
    artifact = {
        **payload,
        "kind": "delivery_spec",
        "issuer": "engineering",
        "parent_hash": parent,
        "revision": revision,
        "status": "active",
        "content_hash": spec_content_hash("delivery_spec", payload, parent_hash=parent, revision=revision),
    }
    return ProposalDecision(True, artifact=artifact)


def _accept_review(proposal: dict[str, Any], view: AdjudicationView, facts: TreeFacts,
                   department: str, tightening: Tightening, events: list[Event]) -> ProposalDecision:
    minimal = view.minimal
    spec_hash = minimal.artifact_hash("product_spec")
    if spec_hash is None:
        return ProposalDecision(False, [FieldError("product_spec", "no active ProductSpec")])
    # 质检的结论是对当前交付的核验（循环结构第 3.1 节）：这一轮开始时没有交付就没有可以核验的对象。
    # 预测性探索的一轮（工单 #557）没有交付，提交结论在这里被拒绝（成果驱动的检查，经收紧检查，工单 #1095）
    untimely = _tightening_errors(tightening.submission(TightenRequest(
        department=department, state=view.state, proposal=proposal, events=tuple(events))))
    if untimely:
        return ProposalDecision(False, untimely)
    delivery_hash = minimal.artifact_hash("delivery_spec")
    if delivery_hash is None:
        return ProposalDecision(False, [FieldError("delivery_spec", "no active DeliverySpec")])
    contract_hash = minimal.artifact_hash("contract")
    if contract_hash is None:
        return ProposalDecision(False, [FieldError("effective_contract", "quality review requires a current contract")])
    # 依据版本、交付绑定的当前版本、工作区的树与检查回执都由合同里的通用条件核对（设计说明第 5.5 节），
    # 提出评价的部门与交付的作者部门分开也由通用条件核对（基础规则 3）
    outcome = evaluate_conditions("qa_review", department=department, proposal=proposal,
                                  minimal=minimal, facts=facts)
    errors: list[FieldError] = list(outcome.errors)
    check_names, name_errors = _qa_check_names(proposal)
    errors.extend(name_errors)
    bound_checks = [outcome.receipts[name] for name in check_names if name in outcome.receipts]
    verdict = proposal["verdict"]
    if verdict == "release":
        if any(item["exit_code"] != 0 for item in bound_checks):
            errors.append(FieldError("checks", "release requires all quality checks to exit 0"))
        if not bound_checks:
            errors.append(FieldError("checks", "release requires quality-run evidence bound to the current snapshot"))
        # 放行要用当前的质检测试材料：材料摘要的比较读的是内容，属于成果驱动的检查（工单 #1095）
        errors.extend(_tightening_errors(tightening.submission(TightenRequest(
            department=department, state=view.state, proposal=proposal,
            evidence=tuple(bound_checks), events=tuple(events)))))
    defects, defect_errors = _qa_defects(proposal)
    errors.extend(defect_errors)
    if errors:
        return ProposalDecision(False, errors)
    previous = minimal.latest("qa_review")
    parent = None if previous is None else previous.content_hash
    revision = 1 if previous is None else previous.version + 1
    payload = {
        "product_spec_hash": spec_hash,
        "effective_contract_hash": contract_hash,
        "delivery_spec_hash": delivery_hash,
        "code_snapshot_hash": facts.digest,
        "verdict": verdict,
        "rationale": proposal["rationale"].strip(),
        "checks": bound_checks,
        "defects": defects,
        "evidence_refs": [],
    }
    artifact = {
        **payload,
        "kind": "qa_review",
        "issuer": "quality",
        "parent_hash": parent,
        "revision": revision,
        "status": "active",
        "content_hash": spec_content_hash("qa_review", payload, parent_hash=parent, revision=revision),
    }
    # 只有放行结束事项（工单 #556）：缺陷记录让工程开始一轮返工，返工的结论由下一个谁工作决定
    return ProposalDecision(True, artifact=artifact, ends_run=verdict == "release")


def _accept_structure(proposal: dict[str, Any], view: AdjudicationView, facts: TreeFacts,
                      department: str, tightening: Tightening, events: list[Event]) -> ProposalDecision:
    # 现有结构说明（docs/design/existing-project-onboarding.md 第 4.4 节）：构建与测试的每一项都要有本次激活中
    # 绑定当前快照与当前初始 PRD 的 run_check 回执，退出状态照实记录（不要求为 0）；建档中工作区的树不变。
    # 树与回执由合同里的通用条件核对（设计说明第 5.5 节）
    minimal = view.minimal
    spec_hash = minimal.artifact_hash("product_spec")
    if spec_hash is None:
        return ProposalDecision(False, [FieldError("product_spec", "no active ProductSpec")])
    outcome = evaluate_conditions("structure", department=department, proposal=proposal,
                                  minimal=minimal, facts=facts)
    errors: list[FieldError] = list(outcome.errors)
    for index, item in enumerate(proposal["modules"]):
        errors.extend(_location_errors(f"modules[{index}].path", [item["path"]], facts))
    for index, item in enumerate(proposal["entry_points"]):
        errors.extend(_location_errors(f"entry_points[{index}].path", [item["path"]], facts))
    for index, item in enumerate(proposal["requirement_locations"]):
        errors.extend(_location_errors(f"requirement_locations[{index}].locations", item["locations"], facts))
    # 每条要求覆盖一次读的是 PRD 的内容，属于成果驱动的检查（工单 #1095），经收紧检查
    errors.extend(_tightening_errors(tightening.submission(TightenRequest(
        department=department, state=view.state, proposal=proposal, events=tuple(events)))))
    if errors:
        return ProposalDecision(False, errors)
    build_and_test = []
    for item in proposal["build_and_test"]:
        name = item["name"].strip()
        build_and_test.append({**item, "name": name, "purpose": item["purpose"].strip(),
                               "command": item["command"].strip(), "receipt": outcome.receipts[name]})
    previous = minimal.latest("structure")
    parent = None if previous is None else previous.content_hash
    revision = 1 if previous is None else previous.version + 1
    payload = {
        "overall": proposal["overall"].strip(),
        "modules": [{"path": item["path"].strip(), "responsibility": item["responsibility"].strip()}
                    for item in proposal["modules"]],
        "entry_points": [{"kind": item["kind"], "path": item["path"].strip(), "how_to_run": item["how_to_run"].strip()}
                         for item in proposal["entry_points"]],
        "build_and_test": build_and_test,
        "requirement_locations": [{"requirement": item["requirement"].strip(),
                                   "locations": [path.strip() for path in item["locations"]]}
                                  for item in proposal["requirement_locations"]],
        "conventions": [item.strip() for item in proposal.get("conventions", [])],
        "product_spec_hash": spec_hash,
        "code_tree_digest": facts.digest,
    }
    artifact = {
        **payload,
        "kind": "structure",
        "issuer": "engineering",
        "parent_hash": parent,
        "revision": revision,
        "status": "active",
        "content_hash": spec_content_hash("structure", payload, parent_hash=parent, revision=revision),
    }
    return ProposalDecision(True, artifact=artifact)


def _accept_baseline_review(proposal: dict[str, Any], view: AdjudicationView, facts: TreeFacts,
                            department: str, tightening: Tightening, events: list[Event]) -> ProposalDecision:
    # 基线核验（docs/design/existing-project-onboarding.md 第 4.5 节）：逐条结论覆盖初始 PRD 的每条要求，
    # 基线检查绑定当前快照与当前 ProductSpec，退出状态不为 0 的检查都有说明；这里不使用普通事项的放行规则。
    # 结构说明对应当前 PRD、工作区的树与检查回执由合同里的通用条件核对（设计说明第 5.5 节）；
    # 逐条结论覆盖每条要求读的是 PRD 的内容，由路由的收紧检查核对（S1d，工单 #860）
    minimal = view.minimal
    spec_hash = minimal.artifact_hash("product_spec")
    if spec_hash is None:
        return ProposalDecision(False, [FieldError("product_spec", "no active ProductSpec")])
    structure = minimal.artifact("structure")
    outcome = evaluate_conditions("baseline_review", department=department, proposal=proposal,
                                  minimal=minimal, facts=facts)
    errors: list[FieldError] = list(outcome.errors)
    check_names, name_errors = _qa_check_names(proposal)
    errors.extend(name_errors)
    bound: dict[str, dict[str, Any]] = {name: outcome.receipts[name] for name in check_names
                                        if name in outcome.receipts}
    conclusions, conclusion_errors = _baseline_conclusions(proposal, bound, facts)
    errors.extend(conclusion_errors)
    # 标「设计中，未实施」的边界不是现有行为，不能记为现有缺陷，逐条结论覆盖每条要求：都读 PRD 的内容，
    # 属于成果驱动的检查（工单 #1095、#860），经收紧检查
    errors.extend(_tightening_errors(tightening.submission(TightenRequest(
        department=department, state=view.state, proposal=proposal, events=tuple(events)))))
    omissions, omission_errors = _baseline_omission_records(proposal, facts)
    errors.extend(omission_errors)
    failed = sorted(name for name, receipt in bound.items() if receipt["exit_code"] != 0)
    referenced = {item["evidence"] for item in conclusions if item["status"] == "existing_defect"}
    explained = {item["check"] for item in proposal.get("other_failures", []) if isinstance(item, dict)}
    for item in proposal.get("other_failures", []):
        name = item.get("check") if isinstance(item, dict) else None
        if name not in bound:
            errors.append(FieldError("other_failures", f"other_failures must name a baseline check: {name!r}"))
        elif bound[name]["exit_code"] == 0:
            errors.append(FieldError("other_failures", f"check {name} exited 0; only failing checks need an explanation"))
    unexplained = [name for name in failed if name not in referenced and name not in explained]
    if unexplained:
        errors.append(FieldError("checks", "every failing check must be referenced by an existing_defect conclusion or explained "
                                           f"in other_failures: {unexplained}"))
    verdict = proposal["verdict"]
    unsupported = [item["requirement"] for item in conclusions if item["status"] == "unsupported"]
    if verdict == "consistent" and (unsupported or omissions):
        errors.append(FieldError("verdict", f"consistent requires no unsupported conclusion and no omission; got "
                                           f"{len(unsupported)} unsupported and {len(omissions)} omission(s)"))
    if verdict == "rework_product" and not unsupported and not omissions:
        errors.append(FieldError("verdict", "rework_product requires at least one unsupported conclusion or one omission"))
    if errors:
        return ProposalDecision(False, errors)
    previous = minimal.latest("baseline_review")
    parent = None if previous is None else previous.content_hash
    revision = 1 if previous is None else previous.version + 1
    payload = {
        "verdict": verdict,
        "conclusions": conclusions,
        "omissions": omissions,
        "checks": [bound[name] for name in check_names],
        "other_failures": [{"check": item["check"].strip(), "reason": item["reason"].strip()}
                           for item in proposal.get("other_failures", [])],
        "product_spec_hash": spec_hash,
        "structure_hash": None if structure is None else structure.content_hash,
        "code_snapshot_hash": facts.digest,
    }
    artifact = {
        **payload,
        "kind": "baseline_review",
        "issuer": "quality",
        "parent_hash": parent,
        "revision": revision,
        "status": "active",
        "content_hash": spec_content_hash("baseline_review", payload, parent_hash=parent, revision=revision),
    }
    # 基线核验的一致结论结束建档事项；要求产品修改时产品开始一轮工作（工单 #556）
    return ProposalDecision(True, artifact=artifact, ends_run=verdict == "consistent")


def _product_payload(proposal: dict[str, Any]) -> dict[str, Any]:
    return {
        "goal": proposal["goal"].strip(),
        "requirements": [item.strip() for item in proposal["requirements"]],
        "boundaries": [item.strip() for item in proposal.get("boundaries", [])],
        "constraints": [item.strip() for item in proposal.get("constraints", [])],
        "acceptance_criteria": [item.strip() for item in proposal["acceptance_criteria"]],
        "fatal_conditions": [item.strip() for item in proposal.get("fatal_conditions", [])],
        "non_goals": [item.strip() for item in proposal.get("non_goals", [])],
        "decision_changes": [{"decision_hash": item["decision_hash"], "disposition": item["disposition"],
                              "rationale": item["rationale"].strip()} for item in proposal.get("decision_changes", [])],
        "change_record": None if proposal.get("change_record") is None else {
            **{field: [item.strip() for item in proposal["change_record"][field]] for field in ("changed", "retained", "retired")},
            "rationale": proposal["change_record"]["rationale"].strip(),
        },
    }


def _change_record_errors(proposal: dict[str, Any]) -> list[FieldError]:
    record = proposal.get("change_record")
    if record is None:
        return []
    if not isinstance(record, dict):
        return [FieldError("change_record", "change_record must describe changed, retained, and retired behavior and rationale")]
    errors = _require_text(record, "rationale")
    for field in ("changed", "retained", "retired"):
        errors.extend(_require_string_list(record, field, min_items=0))
    return [FieldError(f"change_record.{item.field}", item.message) for item in errors]


def _decision_change_errors(proposal: dict[str, Any]) -> list[FieldError]:
    changes = proposal.get("decision_changes", [])
    if not isinstance(changes, list):
        return [FieldError("decision_changes", "decision_changes must be a list")]
    errors = []
    for index, item in enumerate(changes):
        if not isinstance(item, dict):
            errors.append(FieldError(f"decision_changes[{index}]", "each earlier decision requires a disposition and rationale"))
            continue
        errors.extend(FieldError(f"decision_changes[{index}].{error.field}", error.message)
                      for error in _require_text(item, "decision_hash") + _require_text(item, "rationale"))
        if item.get("disposition") not in {"retain", "integrate", "retire"}:
            errors.append(FieldError(f"decision_changes[{index}].disposition", "disposition must be retain, integrate, or retire"))
    return errors


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


def _qa_check_name_errors(proposal: dict[str, Any]) -> list[FieldError]:
    return _qa_check_names(proposal)[1]


def _qa_check_names(proposal: dict[str, Any]) -> tuple[list[str], list[FieldError]]:
    raw = proposal["checks"] if "checks" in proposal else proposal.get("check_names", [])
    if raw is None or not isinstance(raw, list):
        return [], [FieldError("checks", "checks must be a list of names")]
    if not raw:
        return [], [FieldError("checks", "at least one check name is required")]
    names: list[str] = []
    errors: list[FieldError] = []
    for index, item in enumerate(raw):
        if not isinstance(item, str) or not item.strip():
            errors.append(FieldError(f"checks[{index}]", "check name must be a non-empty string"))
            continue
        names.append(item.strip())
    return names, errors


def _qa_defects_errors(proposal: dict[str, Any]) -> list[FieldError]:
    return _qa_defects(proposal)[1]


def _qa_defects(proposal: dict[str, Any]) -> tuple[list[dict[str, str]], list[FieldError]]:
    if "defects" not in proposal:
        return [], []
    raw = proposal.get("defects")
    if raw is None or not isinstance(raw, list):
        return [], [FieldError("defects", "defects must be a list")]
    defects: list[dict[str, str]] = []
    errors: list[FieldError] = []
    for index, defect in enumerate(raw):
        if not isinstance(defect, dict):
            errors.append(FieldError(f"defects[{index}]", "defect must be an object"))
            continue
        summary = defect.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            errors.append(FieldError(f"defects[{index}].summary", "defect summary is required"))
        severity = defect.get("severity")
        if severity not in {"blocker", "major", "minor"}:
            errors.append(FieldError(f"defects[{index}].severity", "severity must be blocker, major, or minor"))
        if isinstance(summary, str) and summary.strip() and severity in {"blocker", "major", "minor"}:
            defects.append({"severity": severity, "summary": summary.strip()})
    return defects, errors


def _require_text(payload: dict[str, Any], field: str) -> list[FieldError]:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        return [FieldError(field, f"{field} must be a non-empty string")]
    return []


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


def _require_string_list(payload: dict[str, Any], field: str, *, min_items: int) -> list[FieldError]:
    value = payload.get(field)
    if not isinstance(value, list) or len(value) < min_items:
        return [FieldError(field, f"{field} must contain at least {min_items} item(s)")]
    if any(not isinstance(item, str) or not item.strip() for item in value):
        return [FieldError(field, f"{field} items must be non-empty strings")]
    return []


def _optional_string_list(payload: dict[str, Any], field: str) -> list[FieldError]:
    if field not in payload or payload[field] is None:
        payload[field] = []
        return []
    value = payload[field]
    if not isinstance(value, list):
        return [FieldError(field, f"{field} must be a list")]
    if any(not isinstance(item, str) or not item.strip() for item in value):
        return [FieldError(field, f"{field} items must be non-empty strings")]
    return []
