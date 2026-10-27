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

from __future__ import annotations

from .adjudication import ask_chain_decision, ask_chain_max_depth
from .watched_outputs import has_new_work, is_working
from .models import DEPARTMENTS, TERMINAL_STATUSES, Event, EventType, ProductSpec, RunProjection
from .tools import offers_with_input, proposal_kind, proposal_kinds, tool_action, tools_for
from . import tightening_contract
from .validation import FieldError, TightenRequest, Tightened

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


def allowed_proposal_kinds(projection: RunProjection, department: str) -> set[str]:
    # 部门此刻能提交的提案种类：正在工作的部门、或者有新工作可以开始的部门，按调度算出来的种类
    if projection.status in TERMINAL_STATUSES or department not in DEPARTMENTS:
        return set()
    if is_working(projection, department) or has_new_work(projection, department):
        return proposal_kinds(department, projection.kind)
    return set()


def tool_error(projection: RunProjection, department: str, name: str, args: dict[str, object]) -> str | None:
    # 这个工具是不是这个部门此刻能做的提交
    kind = proposal_kind(name)
    if kind is not None and kind not in allowed_proposal_kinds(projection, department):
        return "This proposal is not permitted in the current department work."
    return None


def _is_write(name: str) -> bool:
    return tool_action(name) == "write"


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
        allowed = allowed_proposal_kinds(projection, department)
        if department == "product" and any(ask.get("recipient") == "product" for ask in projection.ask_stack):
            allowed = allowed | {"product_spec"}
        return allowed

    def offered(self, request: TightenRequest) -> list[str]:
        # 请求中提供给模型的工具：按这一轮的工作与询问分支取舍，再按调用目标的输入方式去掉需要图像输入的工具
        projection, department = request.state, request.department
        available = tools_for(department, projection.kind)
        if projection.ask_by_branch(request.session_id) is not None:
            # 询问分支里：可以回答；层数允许时可以回问；不能写工作区、不能提交提案（工单 #473）
            chain_allowed, _ = ask_chain_decision(projection.ask_position(request.session_id), ask_chain_max_depth())
            nested = ["ask"] if chain_allowed else []
            if department == "product":
                return ["answer"] + nested
            allowed = [name for name in available
                       if name != "ask" and not _is_write(name) and proposal_kind(name) is None]
            return allowed + ["answer"] + nested
        result = [name for name in offers_with_input(available, request.input_modalities)
                  if tool_error(projection, department, name, {}) is None]
        return result

    def tool(self, request: TightenRequest) -> Tightened:
        # 一次工具调用的收紧检查：输入版本、询问分支、部门此刻能交的种类、放行等输入处理完
        projection, department = request.state, request.department
        call = request.tool or {}
        name = call.get("name")
        args = call.get("args") or {}
        if proposal_kind(name) is not None and request.basis is not None \
                and projection.input_version != request.basis.input_version:
            # 正式成果要等模型看见新输入以后再提交（工单 #964）：模型还没有看到这条输入，这次提交推迟到下一步
            return Tightened(reason=(
                "new user input arrived and has not entered this session's model input yet; "
                "this proposal is not accepted now. Read the work_notification of the next step, then submit again"
            ), deferred=True)
        branch = self._branch_permission(projection, request.session_id, department, name)
        if branch is not None:
            return branch
        reason = tool_error(projection, department, name, args)
        if reason:
            return Tightened(reason=reason)
        # 放行要等发给产品的输入处理完（部门指导设计说明第 2.1 节，工单 #561）：还有没处理完的输入时，
        # 这一次调用在安全节点上等，醒来以后按此刻的 PRD 与交付重新做许可。只有质检的放行等，缺陷记录不等；
        # 还没有交付的预测性探索也不等：没有可以放行的交付，这次提交本来就只会被拒绝
        if (_is_release_submission(department, name, args) and projection.delivery_spec is not None
                and pending_product_input(projection, list(request.events))):
            return Tightened(wait=True)
        return Tightened()

    def submission(self, request: TightenRequest) -> Tightened:

        # 一次提案提交的收紧检查：按提案的种类分开检查，读的都是成果的当前内容与应用状态
        proposal = request.proposal
        if not isinstance(proposal, dict):
            return Tightened()
        if proposal.get("kind") == "product_spec":
            return self._product_spec(request)
        if proposal.get("kind") == "qa_review":
            return self._review(request)
        if proposal.get("kind") == "structure":
            return self._structure(request)
        if proposal.get("kind") == "baseline_review":
            return self._baseline_review(request)
        return Tightened()

    def _branch_permission(self, projection: RunProjection, session_id: str | None, department: str,
                           name: str) -> Tightened | None:
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
        if _is_write(name):
            return Tightened(reason=BRANCH_CANNOT_WRITE)
        if name == "submit_delivery":
            return Tightened(reason=BRANCH_CANNOT_DELIVER)
        if name == "submit_review":
            return Tightened(reason=BRANCH_CANNOT_REVIEW)
        if proposal_kind(name) is not None:
            return Tightened(reason=f"The branch session cannot submit proposal {name}")
        return None

    def _product_spec(self, request: TightenRequest) -> Tightened:
        # 输入版本、修订说明、有效决定逐条处置：PRD 是读内容才能判断的对象（设计说明第 5.5 节）
        projection = request.state
        proposal = request.proposal or {}
        errors: list[FieldError] = []
        if projection.input_version != projection.product_work_input_version:
            errors.append(FieldError("input_version",
                                     "new user input must enter product work before requirements can be accepted"))
        elif projection.product_spec is not None and proposal.get("change_record") is None:
            errors.append(FieldError("change_record", "a revised ProductSpec must explain changed, retained, and retired "
                                                      "behavior and its rationale"))
        active_hashes = {item.content_hash for item in projection.effective_decisions}
        changes = proposal.get("decision_changes", [])
        declared = [item["decision_hash"] for item in changes]
        if set(declared) != active_hashes or len(declared) != len(active_hashes):
            errors.append(FieldError("decision_changes", "explicitly retain, integrate, or retire every current product "
                                                          "decision exactly once"))
        # 输入版本是成果的内容，不进最小投影：内核组装 PRD 的内容时需要它，通过这里一并给回（S1d，工单 #860）
        return Tightened(errors=tuple(errors), facts={"input_version": projection.input_version})

    def _review(self, request: TightenRequest) -> Tightened:
        # 质检的结论是对当前交付的核验：探索轮没有交付，提交结论被拒绝；放行要用当前的质检测试材料；
        # 提交事务里再判一次输入有没有处理完（工具许可之后、提交之前新输入到达，工单 #561）
        projection = request.state
        errors: list[FieldError] = []
        if projection.department_bases.get("quality") is not None \
                and projection.department_delivery_bases.get("quality") is None:
            errors.append(FieldError("delivery_spec", "this work has no delivery to review"))
        if errors:
            return Tightened(errors=tuple(errors))
        if any(item.get("qa_tests_hash") != projection.qa_tests_hash for item in request.evidence):
            errors.append(FieldError("checks", "测试材料已经改变，用当前的测试材料重新运行检查"))
        if request.commit and (request.proposal or {}).get("verdict") == "release" \
                and pending_product_input(projection, list(request.events)):
            return Tightened(wait=True)
        return Tightened(errors=tuple(errors))

    def _structure(self, request: TightenRequest) -> Tightened:
        # 现有结构说明的每条要求都来自当前 PRD，各记一次（读 PRD 内容）
        spec = request.state.product_spec
        if spec is None:
            return Tightened()
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
        return Tightened(errors=tuple(errors))

    def _baseline_review(self, request: TightenRequest) -> Tightened:
        # 带标记的边界条目不是现有行为（设计第 4.3 节）：要求文档描述而代码尚未实现的能力不记为现有缺陷；
        # 逐条结论覆盖初始 PRD 的每条要求，不许多也不重复——两条都读 PRD 的内容（S1d 从内核搬来，工单 #860）
        spec = request.state.product_spec
        if spec is None:
            return Tightened()
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
        return Tightened(errors=tuple(errors))


WATCHED_OUTPUTS = WatchedOutputsTightening()
