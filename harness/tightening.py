# 成果驱动的收紧检查（应用层）：路由交给内核的收紧检查的实现（工单 #1095）。
#
# 内核的通用检查（流版本、执行权、运行状态、边界、工具许可、提案合同）通过以后，在同一个写入事务里问这里一次；
# 结果只有三种：通过、拒绝（写明原因）、等待（写入口按安全节点等，工单 #561）。这里只做成果驱动特有的检查，
# 它读的是成果的当前内容与应用状态，不是内核的通用规则：
#   - 这个部门此刻能提交哪些种类（按调度算出来的当前工作），以及请求里提供哪些工具；
#   - 询问分支的工具限制与回问深度（工单 #473）；
#   - 工作依据里的输入版本（工单 #964）、放行等产品处理完输入（工单 #561）；
#   - 探索轮不能交质检结论、放行用当前质检测试材料；
#   - 按 PRD 内容的检查：每条要求覆盖一次、有效决定逐条保留或退役、「设计中，未实施」的边界不是现有缺陷。
# 它不能放行内核已经拒绝的东西：内核先判，这里只收窄。换一份收紧检查（另一种路由）时整体换掉这一份，
# 内核不改。
#
# S2c（工单 #1098）：六种成果驱动的形状检查（原 validation.py 的 _validate_schema）与成果内容的组装也在这里。
# 通过时 submission 一并给出成果的内容（Tightened.content），内核在它之外盖统一字段、算内容摘要、写接纳事件；
# 路由不组装的种类不给内容，内核按提案的参数当内容写通用的接纳事件。

from __future__ import annotations

import re
from typing import Any

from .actions import TreeFacts
from .adjudication import ask_chain_decision, ask_chain_max_depth
from .watched_outputs import has_new_work, is_working
from .contracts import normalize_scope
from .coverage import coverage_report, method_is_executable, open_criteria
from .definitions import Definitions
from .kernel_events import BASELINE_STATUSES, QA_METHODS, QA_RESULTS, QA_VERDICTS
from .models import TERMINAL_STATUSES, Event, EventType, ProductSpec, RunProjection
from .tools import in_force, offers_with_input, proposal_kind, proposal_kinds, tool_action, tools_for
from . import tightening_contract
from .validation import ConditionOutcome, FieldError, TightenRequest, Tightened, evaluate_conditions

# 建档时写进边界条目的标记（工单 #346）：这条边界是设计里描述、代码尚未实现的能力，
# 不是现有行为，质检的结论不能把它记成 existing_defect
DESIGN_PENDING_MARK = "设计中，未实施"

ANSWER_ONLY_IN_BRANCH = "answer tool is only available in an ask branch session"
PRODUCT_BRANCH_ANSWER_ONLY = "Product ask branch can only submit answer"
BRANCH_CANNOT_WRITE = "The branch session cannot modify files in the running workspace"
BRANCH_CANNOT_DELIVER = "The branch session cannot submit delivery"
BRANCH_CANNOT_REVIEW = "The branch session cannot submit QA review"
# 一轮没有正常结束的两种状态：暂停与失败（取消、上限、运行时间用完都落在这两种里）。
# 正常结束包括事项随这一轮完成（done）：那一轮结束时状态还是 running（部门指导设计说明第 3 节）
_NOT_A_NORMAL_ROUND_END = frozenset({"paused", "failed"})


def pending_product_input(projection: RunProjection, events: list[Event]) -> bool:
    """发给产品的输入里，还有没处理完的：质检放行等它处理完再裁决（部门指导设计说明第 2.1、3 节，工单 #561）。

    「处理完」只有一个说法：收到这条输入的那一轮主线工作正常结束了。输入进入模型输入时由这一轮的工作消息
    （部门输入事件）或者装配好的请求（上下文清单里的输入版本）记下，一轮正常结束时由轮结束事件接上；
    取消、暂停、上限与运行时间用完不算正常结束，事项已结束当作处理完。

    不用 ``processed_input_version``：它只在 PRD 被接纳时前进，产品决定不改 PRD 时永远不前进，
    放行会一直等。只看产品的输入：用户输入（``input_version``）与发给产品的指导（它的「已回答」读的是同一件事）。
    """
    if projection.status in TERMINAL_STATUSES:
        return False
    inputs = [item.version for item in projection.inputs]
    guidance = [item.id for item in projection.department_guidance if item.department == "product"]
    if not inputs and not guidance:
        return False
    branches = set(projection.branch_sessions)
    # 产品这一次主线工作收到的输入与指导：进入模型输入时的版本与指导编号，按激活归在一起
    entered: dict[str, tuple[int, set[str]]] = {}
    for event in events:
        if event.department != "product" or event.session_id in branches:
            continue
        payload = event.payload or {}
        activation_id = str(payload.get("activation_id") or "")
        if not activation_id:
            continue
        version, ids = entered.get(activation_id, (0, set()))
        if event.type in (EventType.DEPARTMENT_INPUT, EventType.CONTEXT_ASSEMBLED):
            version = max(version, int(payload.get("input_version") or 0))
        elif event.type == EventType.DEPARTMENT_GUIDANCE_APPLIED:
            ids = ids | {str(item) for item in payload.get("guidance_ids") or []}
        entered[activation_id] = (version, ids)
    processed_inputs = 0
    processed_guidance: set[str] = set()
    for event in events:
        if event.type != EventType.ACTIVATION_FINISHED or event.department != "product":
            continue
        if event.session_id in branches or event.state_after in _NOT_A_NORMAL_ROUND_END:
            continue
        payload = event.payload or {}
        version, ids = entered.get(str(payload.get("activation_id") or ""), (0, set()))
        processed_inputs = max(processed_inputs, version)
        processed_guidance |= ids
    return (any(version > processed_inputs for version in inputs)
            or any(item not in processed_guidance for item in guidance))


def marked_boundaries(spec: ProductSpec | None) -> list[str]:
    # 带标记的边界条目（工单 #346）：条目文字含标记串
    return [] if spec is None else [item for item in spec.boundaries if DESIGN_PENDING_MARK in item]


def _covers_marked_boundary(requirement: str, spec: ProductSpec | None) -> bool:
    # 结论指向的要求与某条带标记的边界条目是同一项能力：条目可以带说明文字，两者方向都可能是包含
    return any(item == requirement or item in requirement or requirement in item
               for item in marked_boundaries(spec))


def allowed_proposal_kinds(projection: RunProjection, department: str,
                           *, definitions: Definitions | None = None) -> set[str]:
    # 部门此刻能提交的提案种类：正在工作的部门、或者有新工作可以开始的部门，按调度算出来的种类。
    # 部门与种类都按交进来的那份定义算（工单 #1098）：事项所用定义里的部门与提案种类，
    # 不是模块加载时的那一份
    definition = in_force(definitions)
    if projection.status in TERMINAL_STATUSES or department not in definition.departments:
        return set()
    if is_working(projection, department) or has_new_work(projection, department):
        return proposal_kinds(department, projection.kind, definitions=definition)
    return set()


def tool_error(projection: RunProjection, department: str, name: str, args: dict[str, object],
               *, definitions: Definitions | None = None) -> str | None:
    # 这个工具是不是这个部门此刻能做的提交；「这个工具提交的是提案」也按事项所用的那份定义判（工单 #1098）
    kind = proposal_kind(name, definitions=definitions)
    if kind is not None and kind not in allowed_proposal_kinds(projection, department,
                                                              definitions=definitions):
        return "This proposal is not permitted in the current department work."
    return None


def _is_write(name: str, definitions: Definitions | None = None) -> bool:
    return tool_action(name, definitions=definitions) == "write"


def _is_release_submission(department: str, name: str, args: dict[str, object]) -> bool:
    # 只有质检的放行（submit_review，结论是 release）等输入处理完；质检提交缺陷记录不等（工单 #561）
    return department == "quality" and name == "submit_review" and args.get("verdict") == "release"


class WatchedOutputsTightening:
    # 成果驱动的收紧检查：默认路由（watched_outputs）的检查，换路由时整体换掉这一份
    CONTRACT_VERSION = tightening_contract.CURRENT_VERSION

    def kinds(self, request: TightenRequest) -> set[str]:
        # 这个部门此刻能提交的提案种类。产品在回答一次询问时可以修订 PRD（循环结构第 4.3 节）；
        # 同时运行的会话让待回答的询问不止一条（工单 #557）：看的是还有哪些询问等着产品回答
        projection, department = request.state, request.department
        allowed = allowed_proposal_kinds(projection, department, definitions=request.definitions)
        if department == "product" and any(ask.get("recipient") == "product" for ask in projection.ask_stack):
            allowed = allowed | {"product_spec"}
        return allowed

    def offered(self, request: TightenRequest) -> list[str]:
        # 请求中提供给模型的工具：按这一轮的工作与询问分支取舍，再按调用目标的输入方式去掉需要图像输入的工具
        projection, department = request.state, request.department
        definitions = request.definitions
        available = tools_for(department, projection.kind, definitions=definitions)
        if projection.ask_by_branch(request.session_id) is not None:
            # 询问分支里：可以回答；层数允许时可以回问；不能写工作区、不能提交提案（工单 #473）
            chain_allowed, _ = ask_chain_decision(projection.ask_position(request.session_id), ask_chain_max_depth())
            nested = ["ask"] if chain_allowed else []
            if department == "product":
                return ["answer"] + nested
            allowed = [name for name in available
                       if name != "ask" and not _is_write(name, definitions)
                       and proposal_kind(name, definitions=definitions) is None]
            return allowed + ["answer"] + nested
        result = [name for name in offers_with_input(available, request.input_modalities, definitions=definitions)
                  if tool_error(projection, department, name, {}, definitions=definitions) is None]
        return result

    def tool(self, request: TightenRequest) -> Tightened:
        # 一次工具调用的收紧检查：输入版本、询问分支、部门此刻能交的种类、放行等输入处理完
        projection, department = request.state, request.department
        definitions = request.definitions
        call = request.tool or {}
        name = call.get("name")
        args = call.get("args") or {}
        if proposal_kind(name, definitions=definitions) is not None and request.basis is not None \
                and projection.input_version != request.basis.input_version:
            # 正式成果要等模型看见新输入以后再提交（工单 #964）：模型还没有看到这条输入，这次提交推迟到下一步
            return Tightened(reason=(
                "new user input arrived and has not entered this session's model input yet; "
                "this proposal is not accepted now. Read the work_notification of the next step, then submit again"
            ), deferred=True)
        branch = self._branch_permission(projection, request.session_id, department, name, definitions)
        if branch is not None:
            return branch
        reason = tool_error(projection, department, name, args, definitions=definitions)
        if reason:
            return Tightened(reason=reason)
        # 放行要等发给产品的输入处理完（部门指导设计说明第 2.1 节，工单 #561）：还有没处理完的输入时，
        # 这一次调用在安全节点上等，醒来以后按此刻的 PRD 与交付重新做许可。只有质检的放行等，缺陷记录不等；
        # 还没有交付的预测性探索也不等：没有可以放行的交付，这次提交本来就只会被拒绝
        if (_is_release_submission(department, name, args) and projection.delivery_spec is not None
                and pending_product_input(projection, list(request.events))):
            return Tightened(wait=True)
        return Tightened()

    def _branch_permission(self, projection: RunProjection, session_id: str | None, department: str,
                           name: str, definitions: Definitions | None = None) -> Tightened | None:
        # 分支会话的许可按会话判定：这个会话是不是某个询问的分支（工单 #473 的嵌套询问）。
        # 同一个部门的主线会话与分支会话是两回事，只有分支会话受分支的约束。
        if projection.ask_by_branch(session_id) is None:
            if name == "answer":
                return Tightened(reason=ANSWER_ONLY_IN_BRANCH)
            return None
        if name == "answer":
            return Tightened(permitted=True)
        if name == "ask":
            # 回问：在被问部门那里另开一个询问分支，层数不超过上限（工单 #473）
            if projection.ask_by_origin(session_id) is not None:
                # 这个会话自己那次询问还没结束：继续这一层，不新开一层
                return None
            allowed, reason = ask_chain_decision(projection.ask_position(session_id), ask_chain_max_depth())
            return None if allowed else Tightened(reason=reason)
        if department == "product":
            return Tightened(reason=PRODUCT_BRANCH_ANSWER_ONLY)
        if _is_write(name, definitions):
            return Tightened(reason=BRANCH_CANNOT_WRITE)
        if name == "submit_delivery":
            return Tightened(reason=BRANCH_CANNOT_DELIVER)
        if name == "submit_review":
            return Tightened(reason=BRANCH_CANNOT_REVIEW)
        if proposal_kind(name, definitions=definitions) is not None:
            return Tightened(reason=f"The branch session cannot submit proposal {name}")
        return None

    # 这一版路由自己组装的成果种类：其余种类（第二种路由带来的新种类）只按提案的参数当内容，
    # 形状由带它来的那份定义给出，这里不判（S2c，工单 #1098，设计说明第 5.5 节）
    BUILDERS = {
        "product_spec": "_product_spec",
        "product_decision": "_product_decision",
        "delivery_spec": "_delivery",
        "qa_review": "_review",
        "structure": "_structure",
        "baseline_review": "_baseline_review",
    }

    def submission(self, request: TightenRequest) -> Tightened:
        # 一次提案提交的检查与内容组装（S2c，工单 #1098，设计说明第 5.5 节「成果的内容由路由组装」）：
        # 先按种类查提案的形状，再按成果的内容判、把成果的内容组装出来。路由不组装的种类不给内容——
        # 内核按提案的参数当内容，照常写通用的接纳事件。内核不再按成果种类写分支
        proposal = request.proposal
        if not isinstance(proposal, dict):
            return Tightened()
        name = self.BUILDERS.get(str(proposal.get("kind")))
        if name is None:
            return Tightened()
        errors = _schema_errors(str(proposal.get("kind")), proposal)
        if errors:
            return Tightened(errors=tuple(errors))
        return getattr(self, name)(request)

    def _conditions(self, kind: str, request: TightenRequest) -> ConditionOutcome:
        # 提案合同里的通用条件：条件是内核的数据与核对（evaluate_conditions），由这里在需要的地方问一次，
        # 结果既是拒绝的理由，也是组装内容时要用的检查回执（设计说明第 5.5 节）
        return evaluate_conditions(kind, department=request.department, proposal=request.proposal or {},
                                   minimal=request.minimal, facts=request.facts,
                                   definitions=request.definitions)

    def _product_spec(self, request: TightenRequest) -> Tightened:
        # 输入版本、修订说明、有效决定逐条处置都是成果驱动的检查：PRD 是读内容才能判断的对象（第 5.5 节）。
        # 输入版本最先判（新输入还没进产品这一轮时只报这一条），修订说明与有效决定排在通用条件之后，
        # 与搬动以前各条报错的先后一致。输入版本是成果的内容，不进最小投影，由这里并进内容给回（S1d）
        projection = request.state
        proposal = request.proposal or {}
        if projection.input_version != projection.product_work_input_version:
            return Tightened(errors=(FieldError(
                "input_version", "new user input must enter product work before requirements can be accepted"),))
        outcome = self._conditions("product_spec", request)
        if outcome.errors:
            return Tightened(errors=tuple(outcome.errors))
        errors: list[FieldError] = []
        if projection.product_spec is not None and proposal.get("change_record") is None:
            errors.append(FieldError("change_record", "a revised ProductSpec must explain changed, retained, and retired "
                                                      "behavior and its rationale"))
        # 有效决定逐条处置：每条当前有效的决定都要在这一版里明确保留、并入或退役一次
        active_hashes = {item.content_hash for item in projection.effective_decisions}
        declared = [item["decision_hash"] for item in proposal.get("decision_changes", [])]
        if set(declared) != active_hashes or len(declared) != len(active_hashes):
            errors.append(FieldError("decision_changes", "explicitly retain, integrate, or retire every current product "
                                                          "decision exactly once"))
        if errors:
            return Tightened(errors=tuple(errors))
        # PRD 被接纳以后由关注的成果决定下一个谁工作（工单 #556）：这里不再写阶段迁移
        return Tightened(content={**_product_payload(proposal), "input_version": int(projection.input_version)})

    def _product_decision(self, request: TightenRequest) -> Tightened:
        if request.minimal.artifact("product_spec") is None:
            return Tightened(errors=(FieldError(
                "product_spec", "a product decision requires an active ProductSpec"),))
        outcome = self._conditions("product_decision", request)
        if outcome.errors:
            return Tightened(errors=tuple(outcome.errors))
        # 产品决定按内容去重：内容与摘要都由通用条件给出，内核不重算（工单 #1098）
        return Tightened(content=dict(outcome.content or {}), content_hash=outcome.content_hash)

    def _delivery(self, request: TightenRequest) -> Tightened:
        minimal, facts = request.minimal, request.facts
        proposal = request.proposal or {}
        spec_hash = minimal.artifact_hash("product_spec")
        if spec_hash is None:
            return Tightened(errors=(FieldError("product_spec", "no active ProductSpec"),))
        contract_hash = minimal.artifact_hash("contract")
        if contract_hash is None:
            return Tightened(errors=(FieldError(
                "effective_contract", "delivery requires a current effective contract"),))
        # 依据版本与检查回执由合同里的通用条件核对：绑定当前 ProductSpec 与合同、来自这一轮
        outcome = self._conditions("delivery_spec", request)
        if outcome.errors:
            return Tightened(errors=tuple(outcome.errors))
        # 交付的文件清单由主机从封存的交付快照得出：公开树的全部文件，按路径排序（工单 #677）。
        # 工程不再填清单——三份真实交付的清单只写了「这次改的那个文件」，用户按清单下载拿不全成果。
        files = sorted(item.replace("\\", "/") for item in facts.files)
        checks = [outcome.receipts[name] for name in proposal["check_names"] if name in outcome.receipts]
        return Tightened(content={
            "summary": proposal["summary"].strip(),
            "files": files,
            "check_names": list(proposal["check_names"]),
            "checks": checks,
            "known_risks": [item.strip() for item in proposal.get("known_risks", [])],
            "product_spec_hash": spec_hash,
            "effective_contract_hash": contract_hash,
            "code_tree_digest": facts.digest,
        })

    def _review(self, request: TightenRequest) -> Tightened:
        # 质检的结论是对当前交付的核验（循环结构第 3.1 节）：这一轮开始时没有交付就没有可以核验的对象；
        # 放行要用当前的质检测试材料；提交事务里再判一次输入有没有处理完（工具许可之后、提交之前新输入到达）
        minimal, facts = request.minimal, request.facts
        projection = request.state
        proposal = request.proposal or {}
        spec_hash = minimal.artifact_hash("product_spec")
        if spec_hash is None:
            return Tightened(errors=(FieldError("product_spec", "no active ProductSpec"),))
        # 预测性探索的一轮（工单 #557）没有交付，提交结论在这里被拒绝
        if projection.department_bases.get("quality") is not None \
                and projection.department_delivery_bases.get("quality") is None:
            return Tightened(errors=(FieldError("delivery_spec", "this work has no delivery to review"),))
        delivery_hash = minimal.artifact_hash("delivery_spec")
        if delivery_hash is None:
            return Tightened(errors=(FieldError("delivery_spec", "no active DeliverySpec"),))
        contract_hash = minimal.artifact_hash("contract")
        if contract_hash is None:
            return Tightened(errors=(FieldError(
                "effective_contract", "quality review requires a current contract"),))
        # 依据版本、交付绑定的当前版本、工作区的树与检查回执都由合同里的通用条件核对（设计说明第 5.5 节），
        # 提出评价的部门与交付的作者部门分开也由通用条件核对（基础规则 3）
        outcome = self._conditions("qa_review", request)
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
            # 放行要用当前的质检测试材料：材料摘要的比较读的是内容
            if any(item.get("qa_tests_hash") != projection.qa_tests_hash for item in bound_checks):
                errors.append(FieldError("checks", "测试材料已经改变，用当前的测试材料重新运行检查"))
        # 逐条结论（验证的独立性设计说明第 7、7.1 节，工单 #151）在前面这些检查通过以后才判：
        # 覆盖当前 ProductSpec 的全部验收条件、可执行检验的 passed 至少一个本轮质检回执、放行的三条规则
        criteria: list[dict[str, Any]] = []
        if not errors:
            criteria, criteria_errors = _qa_criteria(proposal)
            errors.extend(criteria_errors)
            if not errors:
                errors.extend(_criteria_coverage_errors(criteria, projection, outcome.receipts))
                errors.extend(_criteria_evidence_errors(criteria))
                if verdict == "release":
                    errors.extend(_release_criteria_errors(criteria))
                if verdict == "cannot_verify":
                    errors.extend(_cannot_verify_criteria_errors(criteria))
        defects, defect_errors = _qa_defects(proposal)
        errors.extend(defect_errors)
        if errors:
            return Tightened(errors=tuple(errors))
        # 放行要等发给产品的输入处理完（部门指导设计说明第 2.1 节，工单 #561）：在提交事务里再判一次
        if request.commit and verdict == "release" and pending_product_input(projection, list(request.events)):
            return Tightened(wait=True)
        # 只有放行结束事项（工单 #556）：缺陷记录让工程开始一轮返工，返工的结论由下一个谁工作决定
        return Tightened(content={
            "product_spec_hash": spec_hash,
            "effective_contract_hash": contract_hash,
            "delivery_spec_hash": delivery_hash,
            "code_snapshot_hash": facts.digest,
            "verdict": verdict,
            "rationale": proposal["rationale"].strip(),
            "checks": bound_checks,
            "defects": defects,
            "criteria": criteria,
            # 放行记录一次算好三个数（第 7.1 节第 4 点）：查询与画面读这个数，不重新计算
            "coverage": coverage_report(criteria),
            "open_criteria": open_criteria(criteria),
            # 逐条结论引用的检查回执身份：那次 run_check 的输出工件引用（说明工件的引用由接纳时补在它前面）
            "evidence_refs": _check_evidence_refs(criteria, request.events),
        }, ends_run=verdict == "release")

    def _structure(self, request: TightenRequest) -> Tightened:
        # 现有结构说明（docs/design/existing-project-onboarding.md 第 4.4 节）：构建与测试的每一项都要有本次
        # 激活中绑定当前快照与当前初始 PRD 的 run_check 回执，退出状态照实记录（不要求为 0）；建档中工作区的树不变。
        # 树与回执由合同里的通用条件核对（设计说明第 5.5 节）
        minimal, facts = request.minimal, request.facts
        proposal = request.proposal or {}
        spec_hash = minimal.artifact_hash("product_spec")
        if spec_hash is None:
            return Tightened(errors=(FieldError("product_spec", "no active ProductSpec"),))
        outcome = self._conditions("structure", request)
        errors: list[FieldError] = list(outcome.errors)
        for index, item in enumerate(proposal["modules"]):
            errors.extend(_location_errors(f"modules[{index}].path", [item["path"]], facts))
        for index, item in enumerate(proposal["entry_points"]):
            errors.extend(_location_errors(f"entry_points[{index}].path", [item["path"]], facts))
        for index, item in enumerate(proposal["requirement_locations"]):
            errors.extend(_location_errors(f"requirement_locations[{index}].locations", item["locations"], facts))
        # 每条要求覆盖一次读的是 PRD 的内容
        errors.extend(_requirement_location_errors(request))
        if errors:
            return Tightened(errors=tuple(errors))
        build_and_test = []
        for item in proposal["build_and_test"]:
            name = item["name"].strip()
            build_and_test.append({**item, "name": name, "purpose": item["purpose"].strip(),
                                   "command": item["command"].strip(), "receipt": outcome.receipts[name]})
        return Tightened(content={
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
        })

    def _baseline_review(self, request: TightenRequest) -> Tightened:
        # 基线核验（docs/design/existing-project-onboarding.md 第 4.5 节）：逐条结论覆盖初始 PRD 的每条要求，
        # 基线检查绑定当前快照与当前 ProductSpec，退出状态不为 0 的检查都有说明；这里不使用普通事项的放行规则。
        # 结构说明对应当前 PRD、工作区的树与检查回执由合同里的通用条件核对（设计说明第 5.5 节）
        minimal, facts = request.minimal, request.facts
        proposal = request.proposal or {}
        spec_hash = minimal.artifact_hash("product_spec")
        if spec_hash is None:
            return Tightened(errors=(FieldError("product_spec", "no active ProductSpec"),))
        structure = minimal.artifact("structure")
        outcome = self._conditions("baseline_review", request)
        errors: list[FieldError] = list(outcome.errors)
        check_names, name_errors = _qa_check_names(proposal)
        errors.extend(name_errors)
        bound: dict[str, dict[str, Any]] = {name: outcome.receipts[name] for name in check_names
                                            if name in outcome.receipts}
        conclusions, conclusion_errors = _baseline_conclusions(proposal, bound, facts)
        errors.extend(conclusion_errors)
        # 标「设计中，未实施」的边界不是现有行为，不能记为现有缺陷，逐条结论覆盖每条要求：都读 PRD 的内容
        errors.extend(_baseline_requirement_errors(request))
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
            return Tightened(errors=tuple(errors))
        # 基线核验的一致结论结束建档事项；要求产品修改时产品开始一轮工作（工单 #556）
        return Tightened(content={
            "verdict": verdict,
            "conclusions": conclusions,
            "omissions": omissions,
            "checks": [bound[name] for name in check_names],
            "other_failures": [{"check": item["check"].strip(), "reason": item["reason"].strip()}
                               for item in proposal.get("other_failures", [])],
            "product_spec_hash": spec_hash,
            "structure_hash": None if structure is None else structure.content_hash,
            "code_snapshot_hash": facts.digest,
        }, ends_run=verdict == "consistent")


def _requirement_location_errors(request: TightenRequest) -> list[FieldError]:
    # 现有结构说明的每条要求都来自当前 PRD，各记一次（读 PRD 内容）
    spec = request.state.product_spec
    if spec is None:
        return []
    requirements = [item.strip() for item in spec.requirements]
    declared = [item["requirement"].strip() for item in (request.proposal or {}).get("requirement_locations", [])]
    errors: list[FieldError] = []
    if len(declared) != len(set(declared)):
        errors.append(FieldError("requirement_locations", "each requirement may be recorded only once"))
    if set(declared) != set(requirements):
        missing = [item for item in requirements if item not in declared]
        extra = [item for item in declared if item not in requirements]
        errors.append(FieldError("requirement_locations",
                                 "requirement_locations must record every requirement of the current ProductSpec "
                                 f"exactly once; missing: {missing or 'none'}; "
                                 f"not in the current ProductSpec: {extra or 'none'}"))
    return errors


def _baseline_requirement_errors(request: TightenRequest) -> list[FieldError]:
    # 带标记的边界条目不是现有行为（设计第 4.3 节）：要求文档描述而代码尚未实现的能力不记为现有缺陷；
    # 逐条结论覆盖初始 PRD 的每条要求，不许多也不重复——两条都读 PRD 的内容（S1d 从内核搬来，工单 #860）
    spec = request.state.product_spec
    if spec is None:
        return []
    errors: list[FieldError] = []
    conclusions = [item for item in (request.proposal or {}).get("conclusions", []) if isinstance(item, dict)]
    requirements = [item.strip() for item in spec.requirements]
    declared = [str(item.get("requirement", "")).strip() for item in conclusions]
    missing = [item for item in requirements if item not in declared]
    extra = [item for item in declared if item not in requirements]
    if set(declared) != set(requirements):
        errors.append(FieldError(
            "conclusions",
            "conclusions must cover every requirement of the current ProductSpec exactly once; "
            f"missing: {missing or 'none'}; not in the current ProductSpec: {extra or 'none'}",
        ))
    for index, item in enumerate(conclusions):
        if item.get("status") != "existing_defect":
            continue
        if _covers_marked_boundary(str(item.get("requirement", "")).strip(), spec):
            errors.append(FieldError(f"conclusions[{index}].status",
                                     f"a boundary entry marked {DESIGN_PENDING_MARK} is not existing behavior and "
                                     "cannot be an existing_defect; write it into the initial PRD boundaries with "
                                     "that mark"))
    return errors


WATCHED_OUTPUTS = WatchedOutputsTightening()



# ---------------------------------------------------------------------------
# 六种成果驱动的形状检查、按内容的检查与内容组装的辅助函数（S2c，工单 #1098，从 validation.py 搬来）。
# 它们只读提案的内容、最小投影与工作区事实，内核不再调用它们：内核只做通用检查、盖统一字段、算内容摘要。


def _schema_errors(kind: str, proposal: dict[str, Any]) -> list[FieldError]:
    if kind == "product_decision":
        return _require_text(proposal, "statement") + _require_text(proposal, "rationale")
    if kind == "product_spec":
        return _require_text(proposal, "goal") + _require_string_list(proposal, "requirements", min_items=1) + _require_string_list(
            proposal, "acceptance_criteria", min_items=1
        ) + _optional_string_list(proposal, "boundaries") + _optional_string_list(proposal, "constraints") + _optional_string_list(
            proposal, "fatal_conditions"
        ) + _optional_string_list(proposal, "non_goals") + _decision_change_errors(proposal) + _change_record_errors(proposal) + \
        _requirement_mapping_errors(proposal)
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
        errors.extend(_qa_criteria_errors(proposal))
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


def _product_payload(proposal: dict[str, Any]) -> dict[str, Any]:
    return {
        "goal": proposal["goal"].strip(),
        "requirements": [item.strip() for item in proposal["requirements"]],
        "boundaries": [item.strip() for item in proposal.get("boundaries", [])],
        "constraints": [item.strip() for item in proposal.get("constraints", [])],
        "acceptance_criteria": [item.strip() for item in proposal["acceptance_criteria"]],
        "requirement_mapping": _requirement_mapping(proposal)[0],
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


# 验收条件的引用形式（浏览器与 computer use 设计说明第 8.1 节）：AC<序号>，序号是它在 ProductSpec 里的位置
_CRITERION_ID = re.compile(r"^AC[1-9][0-9]*$")
# 逐条结论一项的字段（独立性说明第 7.1 节、浏览器说明第 8.3 节）：封闭，多写的字段报错
_QA_CRITERION_FIELDS = frozenset({"criterion", "method", "result", "checks", "trial_cases", "note"})


def _qa_criteria_errors(proposal: dict[str, Any]) -> list[FieldError]:
    return _qa_criteria(proposal)[1]


def _qa_criteria(proposal: dict[str, Any]) -> tuple[list[dict[str, Any]], list[FieldError]]:
    # 逐条结论的结构：每条验收条件一项，criterion 是 AC<序号>，method 是六种检验方式之一，
    # result 是 passed、failed、unverified 之一；checks 是本次激活的质检检查名，trial_cases 在 #1180 之前为空
    raw = proposal.get("criteria")
    if raw is None or not isinstance(raw, list) or not raw:
        return [], [FieldError("criteria", "criteria must list one entry per acceptance criterion of the current ProductSpec")]
    rows: list[dict[str, Any]] = []
    errors: list[FieldError] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            errors.append(FieldError(f"criteria[{index}]", "a criterion must be an object"))
            continue
        errors.extend(FieldError(f"criteria[{index}].{key}", "unknown field")
                      for key in sorted(set(item) - _QA_CRITERION_FIELDS))
        criterion = item.get("criterion")
        if not isinstance(criterion, str) or not _CRITERION_ID.match(criterion.strip()):
            errors.append(FieldError(f"criteria[{index}].criterion",
                                     "criterion must be AC<position>, the acceptance criterion's position in the current ProductSpec"))
            continue
        method = item.get("method")
        if method not in QA_METHODS:
            errors.append(FieldError(f"criteria[{index}].method", "method must be one of " + ", ".join(QA_METHODS)))
        result = item.get("result")
        if result not in QA_RESULTS:
            errors.append(FieldError(f"criteria[{index}].result", "result must be passed, failed, or unverified"))
        checks_raw = item.get("checks", [])
        checks: list[str] = []
        if not isinstance(checks_raw, list):
            errors.append(FieldError(f"criteria[{index}].checks", "checks must be a list of check names"))
        else:
            for position, name in enumerate(checks_raw):
                if not isinstance(name, str) or not name.strip():
                    errors.append(FieldError(f"criteria[{index}].checks[{position}]", "check name must be a non-empty string"))
                    continue
                checks.append(name.strip())
        trial_cases = item.get("trial_cases", [])
        if not isinstance(trial_cases, list) or any(not isinstance(name, str) for name in trial_cases):
            errors.append(FieldError(f"criteria[{index}].trial_cases", "trial_cases must be a list of trial case ids"))
        elif trial_cases:
            # 试用用例由 #1180 接上：在那之前这一项必须为空
            errors.append(FieldError(f"criteria[{index}].trial_cases", "trial cases are not accepted yet; leave trial_cases empty"))
        note = item.get("note")
        if note is not None and not isinstance(note, str):
            errors.append(FieldError(f"criteria[{index}].note", "note must be a string"))
        if method in QA_METHODS and result in QA_RESULTS:
            rows.append({"criterion": criterion.strip(), "method": method, "result": result,
                         "checks": checks, "trial_cases": [], "note": (note or "").strip()})
    return rows, errors


def _criteria_coverage_errors(criteria: list[dict[str, Any]], projection: RunProjection,
                              receipts: dict[str, Any]) -> list[FieldError]:
    # 覆盖当前 ProductSpec 的全部验收条件，按位置一一对应：缺一条、多一条、重复一条都报在 criteria 上；
    # 每条引用的检查名必须是本次激活里绑定当前快照、ProductSpec 与交付的质检回执（工程的回执不在 receipts 里）
    errors: list[FieldError] = []
    spec = projection.product_spec
    expected = [f"AC{position}" for position in range(1, len(spec.acceptance_criteria) + 1)] if spec is not None else []
    seen = [row["criterion"] for row in criteria]
    missing = [item for item in expected if item not in seen]
    extra = sorted({item for item in seen if item not in expected})
    if missing:
        errors.append(FieldError("criteria", "criteria must cover every acceptance criterion of the current ProductSpec; missing "
                                 + ", ".join(missing)))
    if extra:
        errors.append(FieldError("criteria", "criteria reference acceptance criteria the current ProductSpec does not have: "
                                 + ", ".join(extra)))
    if len(seen) != len(set(seen)):
        errors.append(FieldError("criteria", "criteria list the same acceptance criterion twice"))
    for index, row in enumerate(criteria):
        unknown = [name for name in row["checks"] if name not in receipts]
        if unknown:
            errors.append(FieldError(f"criteria[{index}].checks",
                                     "checks must name quality run_check receipts bound to the current snapshot, ProductSpec and "
                                     "delivery in this activation: " + ", ".join(unknown)))
    return errors


def _criteria_evidence_errors(criteria: list[dict[str, Any]]) -> list[FieldError]:
    # 可执行检验（check、trial、measure）的 passed 至少一个证据：本次激活的质检检查回执
    errors: list[FieldError] = []
    for index, row in enumerate(criteria):
        if row["result"] == "passed" and method_is_executable(row["method"]) and not row["checks"]:
            errors.append(FieldError(f"criteria[{index}].checks",
                                     "a passed executable criterion needs at least one quality check receipt"))
    return errors


def _release_criteria_errors(criteria: list[dict[str, Any]]) -> list[FieldError]:
    # 放行（第 7.1 节第 3 点）：没有 failed；可执行检验的验收条件都是 passed。
    # 不可执行检验的条件可以是 unverified，列进放行记录的开环明细
    errors: list[FieldError] = []
    for index, row in enumerate(criteria):
        if row["result"] == "failed":
            errors.append(FieldError(f"criteria[{index}].result", "release cannot carry a failed acceptance criterion"))
        elif method_is_executable(row["method"]) and row["result"] != "passed":
            errors.append(FieldError(f"criteria[{index}].result", "release requires executable criteria to be passed"))
    return errors


def _cannot_verify_criteria_errors(criteria: list[dict[str, Any]]) -> list[FieldError]:
    # 无法核验（浏览器与 computer use 设计说明第 8.4 节，工单 #1179）：没有 failed 的条目，
    # 至少一条 unverified，每条 unverified 都写明原因。不满足时按无法核验提交会被拒绝
    errors: list[FieldError] = []
    for index, row in enumerate(criteria):
        if row["result"] == "failed":
            errors.append(FieldError(f"criteria[{index}].result",
                                     "cannot_verify cannot carry a failed acceptance criterion"))
        elif row["result"] == "unverified" and not str(row.get("note") or "").strip():
            errors.append(FieldError(f"criteria[{index}].note",
                                     "cannot_verify requires a reason for every unverified criterion"))
    if not errors and not any(row["result"] == "unverified" for row in criteria):
        errors.append(FieldError("criteria", "cannot_verify requires at least one unverified acceptance criterion"))
    return errors


def _check_evidence_refs(criteria: list[dict[str, Any]], events: tuple[Event, ...] | list[Event]) -> list[dict[str, Any]]:
    # 逐条结论引用的检查回执身份：那次 run_check 的输出工件引用。说明工件（结论原文）的引用由接纳时补在前面
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in criteria:
        for name in row["checks"]:
            ref = _check_output_ref(events, name)
            if ref is None or ref.get("content_hash") in seen:
                continue
            seen.add(ref["content_hash"])
            refs.append(ref)
    return refs


def _check_output_ref(events: tuple[Event, ...] | list[Event], name: str) -> dict[str, Any] | None:
    for event in reversed(list(events)):
        if event.type != EventType.TOOL_CALLED:
            continue
        payload = event.payload or {}
        if payload.get("name") != "run_check" or (payload.get("args") or {}).get("name") != name:
            continue
        ref = payload.get("output_ref")
        if isinstance(ref, dict) and ref.get("content_hash"):
            return dict(ref)
    return None


_REQUIREMENT_MAPPING_FIELDS = frozenset({"requirement", "criteria", "gap"})


def _requirement_mapping_errors(proposal: dict[str, Any]) -> list[FieldError]:
    return _requirement_mapping(proposal)[1]


def _requirement_mapping(proposal: dict[str, Any]) -> tuple[list[dict[str, Any]], list[FieldError]]:
    # 要求与验收标准的对应声明（工单 #1178，验证的独立性设计说明第 7 节第 1 点）：每条要求一条，
    # requirement 是要求在 requirements 里的位置（从 1 起），criteria 是它对应的验收标准（AC<序号>，约定见 #151），
    # 写不出验收标准时用 gap 写明原因。每条要求要么有至少一条验收标准，要么有显式标注
    requirements = proposal.get("requirements")
    acceptance = proposal.get("acceptance_criteria")
    requirement_count = len(requirements) if isinstance(requirements, list) else 0
    criterion_count = len(acceptance) if isinstance(acceptance, list) else 0
    raw = proposal.get("requirement_mapping")
    if raw is None:
        return [], [FieldError("requirement_mapping",
                               "requirement_mapping must give one entry per requirement: "
                               + ", ".join(f"requirement {position}" for position in range(1, requirement_count + 1)))]
    if not isinstance(raw, list) or not raw:
        return [], [FieldError("requirement_mapping", "requirement_mapping must be a non-empty list, one entry per requirement")]
    rows: list[dict[str, Any]] = []
    errors: list[FieldError] = []
    seen: list[int] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            errors.append(FieldError(f"requirement_mapping[{index}]", "a requirement mapping must be an object"))
            continue
        errors.extend(FieldError(f"requirement_mapping[{index}].{key}", "unknown field")
                      for key in sorted(set(item) - _REQUIREMENT_MAPPING_FIELDS))
        position = item.get("requirement")
        if type(position) is not int or position < 1:
            errors.append(FieldError(f"requirement_mapping[{index}].requirement",
                                     "requirement must be the 1-based position of a requirement"))
            continue
        seen.append(position)
        criteria = item.get("criteria")
        if criteria is None:
            criteria = []
        if not isinstance(criteria, list) or any(not isinstance(value, str) for value in criteria):
            errors.append(FieldError(f"requirement_mapping[{index}].criteria",
                                     "criteria must be a list of AC<position> strings"))
            continue
        criteria = [value.strip() for value in criteria]
        gap = item.get("gap")
        if gap is not None and (not isinstance(gap, str) or not gap.strip()):
            errors.append(FieldError(f"requirement_mapping[{index}].gap", "gap must be a non-empty reason"))
            gap = None
        if criteria and gap is not None:
            errors.append(FieldError(f"requirement_mapping[{index}]",
                                     "a requirement has either acceptance criteria or a gap note, not both"))
        if not criteria and gap is None:
            errors.append(FieldError(f"requirement_mapping[{index}]",
                                     f"requirement {position} has no acceptance criterion and no gap note"))
        for offset, value in enumerate(criteria):
            if not _CRITERION_ID.match(value):
                errors.append(FieldError(f"requirement_mapping[{index}].criteria[{offset}]",
                                         "criterion must be AC<position>, the acceptance criterion's position"))
            elif int(value[2:]) > criterion_count:
                errors.append(FieldError(f"requirement_mapping[{index}].criteria[{offset}]",
                                         f"{value} does not exist; the ProductSpec has {criterion_count} acceptance criteria"))
        rows.append({"requirement": position, "criteria": criteria,
                     "gap": None if gap is None else gap.strip()})
    missing = [position for position in range(1, requirement_count + 1) if position not in seen]
    if missing:
        errors.append(FieldError("requirement_mapping",
                                 "requirement_mapping must cover every requirement; missing "
                                 + ", ".join(f"requirement {position}" for position in missing)))
    unexpected = sorted({position for position in seen if position > requirement_count})
    if unexpected:
        errors.append(FieldError("requirement_mapping",
                                 "requirement_mapping references requirements the ProductSpec does not have: "
                                 + ", ".join(str(position) for position in unexpected)))
    if len(seen) != len(set(seen)):
        errors.append(FieldError("requirement_mapping", "requirement_mapping lists the same requirement twice"))
    return rows, errors


def _require_text(payload: dict[str, Any], field: str) -> list[FieldError]:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        return [FieldError(field, f"{field} must be a non-empty string")]
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
