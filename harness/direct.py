# 直做的路由实现与它的收紧检查（工单 #1395；形态与核验角色设计说明「直做」「开环完成」
# 「形态随事项冻结」；骨架与应用设计说明第 5.1、5.4、5.5 节；总图第一节「轮转方式」、第四节「路由」缝）。
#
# 形状（形态与核验角色设计说明「直做」）：定义写明角色清单、每一种事项的来源由哪个角色接、谁能交完成、
# 成果种类与提案合同。事项开始时接这个来源的角色开始第一轮；之后没有在工作的角色收到指导或询问时开始一轮；
# 角色之间靠询问交流，询问照现有规矩嵌在一轮里（询问分支的判断与成果驱动同一个口径）。定义里指定的角色
# 交了完成，事项结束：没有核验角色核验它，结束原因是开环完成——路由按事项创建事件里记下的开环标记给出
# （工单 #1394 的做法），薄驱动只把它写进事实。
#
# 一轮工作在交完成以前可以有很多轮：可以交完成、还没有交的那些角色一直可以开始下一轮，直到交了完成
# （事项结束）或者内核的时间、轮次与步数上限把它停下（设计说明第 5.4 节第 7 条：一定会停靠内核的上限）。
#
# 建档（工单 #1510，接入已有项目设计说明第 4.1 节）：同一个路由也跑建档事项。接「建档」这一来源的角色交初始
# PRD 与现有结构说明，然后交完成；这份形态没有核验角色，建档没有基线核验这一步，交完成以后以开环完成结束，
# 项目层照常提出初始 PRD 候选并请用户确认（确认请求写明这份基线没有经过基线核验）。
#
# 直做加核验角色（交完成以后等核验结论、打回则再做一轮）归 #1396：这一版定义了核验角色核验交完成的，
# 加载时整份拒绝——不把没有人核验的完成记成放行（check_definition 的最后两条）。
#
# 本模块不导入别的路由实现（设计说明第 4.1 节：路由之间不互相导入）：询问分支、一轮怎么结束这些规矩
# 在这里自成一份，与成果驱动的那一份同口径。

from __future__ import annotations

from typing import Any

from . import routing_contract, tightening_contract
from .adjudication import ask_chain_decision, ask_chain_max_depth
from .definitions import DEFINITIONS
from .models import OPEN_LOOP_STOP_REASON, Event, EventType, RunProjection, TERMINAL_STATUSES, new_id
from .tools import in_force, offers_with_input, proposal_kind, tool_action, tools_for
from .validation import FieldError, TightenRequest, Tightened, evaluate_conditions

# 组织定义 organization.json 的 routing 里写这个名称（设计说明第 5.1 节「选择」）
ROUTING_NAME = "direct"

# 单角色直做形态的名字（harness/runtime.py 的形态登记处、harness/definitions/forms/single_role_direct/）
SINGLE_ROLE_DIRECT = "single_role_direct"

# 交完成这种成果的种类：这份路由的最后采纳是它（routings.json 的 final_outcome）。直做下的完成说明
# 就是事项最后采纳的那一份，交完成的事件由通用的成果接纳写法写下（S2c，工单 #1098）
COMPLETION_KIND = "completion"

# 建档的两份产物（工单 #1510，接入已有项目设计说明第 4.1 节）：直做下接建档的那个角色既写初始 PRD，
# 也写现有结构说明。没有核验角色的形态没有基线核验这一步，交完成为止；两份产物由定义里给的提交工具提交，
# 内容按内核的通用条件组装（内核不认识具体有哪几种成果，工单 #1456）
PRODUCT_SPEC_KIND = "product_spec"
STRUCTURE_KIND = "structure"

# 一份直做定义必须写明事项结束用的那一个原因：它的定义里声明的封闭清单中的一条
ITEM_END_REASON = "no_open_work"

# 一轮没有正常结束的两种状态：暂停与失败（与成果驱动同一个口径，设计说明第 5.3 节输出）
_NOT_A_NORMAL_ROUND_END = frozenset({"paused", "failed"})

# 询问分支里的两条拒绝理由与成果驱动那一份相同（工具回执上的说明，用户看得到）
ANSWER_ONLY_IN_BRANCH = "answer tool is only available in an ask branch session"
BRANCH_CANNOT_WRITE = "The branch session cannot modify files in the running workspace"
# 分支这一轮没能回答的两种原因：一步也走不了、跑完这一轮还是没交上回答
_STEP_LIMIT_REASON = "department reached the model step limit without submitting a proposal"
_BRANCH_FAILED_REASON = "branch failed to answer"


# ---------------------------------------------------------------------------
# 定义里写明的东西：部门、谁能交完成、成果种类
# ---------------------------------------------------------------------------


def routing_definition(definitions: Any | None = None) -> Any:
    # 这份路由自己的一份定义（routings.json 的那一条）；加载时核对过它在
    definition = DEFINITIONS if definitions is None else definitions
    return routing_contract.definition_of(definition, ROUTING_NAME)


def routing_departments(definitions: Any | None = None) -> tuple[str, ...]:
    """这个路由的部门清单：它自己的一份定义里写的（设计说明第 5.4 节第 2 条）。"""
    declared = routing_definition(definitions)
    return () if declared is None else tuple(declared.departments)


def proposal_kinds_for(department: str, kind: str, definitions: Any | None = None) -> set[str]:
    """部门在这种事项里能交的提案种类：按定义里的提案合同，部门名不写在代码里（工单 #1391）。"""
    definition = in_force(definitions)
    if department not in definition.departments:
        return set()
    return set(definition.proposal_contract(department, kind).get("kinds") or ())


def completing_departments(definitions: Any | None = None, kind: str = "change") -> tuple[str, ...]:
    """能交完成的部门：提案合同里有这份路由最后采纳的那种成果的那些（定义里指定的角色）。

    直做下事项以「交完成的那一份」结束（设计说明第 4.7 节第 4 条、routings.json 的 final_outcome），
    能交它的角色就是会交完成的人；没有核验角色时它交了完成，事项以开环完成结束。能交完成的角色可以
    一轮接一轮地工作，直到交了完成或者内核的上限把它停下。
    """
    declared = routing_definition(definitions)
    if declared is None or declared.final_outcome is None:
        return ()
    definition = in_force(definitions)
    return tuple(department for department in definition.departments
                 if declared.final_outcome in proposal_kinds_for(department, kind, definition))


# ---------------------------------------------------------------------------
# 谁能开工（设计说明「直做」第 2 条）
# ---------------------------------------------------------------------------


def is_working(projection: RunProjection, department: str) -> bool:
    """这个角色这一轮正在工作：主线会话的记录是「工作中」，或它在回答一个询问。

    询问分支是主线之外的另一条会话（工单 #473），分支里的角色也在工作。
    """
    session = projection.sessions.get(department)
    if session is not None and session.status == "active":
        return True
    ask = projection.active_ask
    return bool(ask and ask.get("recipient") == department)


def is_waiting(projection: RunProjection, department: str) -> bool:
    """这个角色在等待工作：它这一轮已经结束（或还没开始过）。"""
    return not is_working(projection, department)


def waiting_departments(statuses: dict[str, str | None],
                        definitions: Any | None = None) -> set[str]:
    """在等待工作的角色：这个进程里没有正在工作的会话的那些（工单 #16 的恢复口径）。

    statuses 没有列出的角色按等待处理。角色清单按这份形态的定义取（工单 #1509）。
    """
    definition = in_force(definitions)
    return {department for department in definition.departments if statuses.get(department) != "active"}


def _has_new_user_input(projection: RunProjection) -> bool:
    """还有没被处理完的用户输入。"""
    return projection.input_version > projection.processed_input_version


def has_new_input(projection: RunProjection, department: str, definitions: Any | None = None) -> bool:
    """接这个事项来源的角色还有没处理完的输入：事项开始时与新的输入到达时，先是它的一轮工作。

    哪个角色接取自定义（工单 #1455）：来源由事项的种类给出（建档或你的输入）。
    """
    definition = in_force(definitions)
    if department != definition.source_department(definition.item_source(projection.kind)):
        return False
    return _has_new_user_input(projection)


def has_new_guidance(projection: RunProjection, department: str) -> bool:
    """发给这个角色的指导：还没有进入它的一轮工作的（部门指导设计说明第 3 节）。"""
    return any(item.department == department and item.status == "received"
               for item in projection.department_guidance)


def pending_ask_department(projection: RunProjection) -> str | None:
    """还没回答的询问：提问方的那一轮要继续，回答在分支里（进程中断以后接着同一次询问）。"""
    for ask in projection.ask_stack:
        origin = ask.get("origin_session_id")
        for session in projection.sessions.values():
            if session.session_id == origin:
                return session.department
    return None


def _free(projection: RunProjection, waiting: set[str] | None, department: str) -> bool:
    return department in waiting if waiting is not None else is_waiting(projection, department)


def ready_departments(projection: RunProjection, waiting: set[str] | None = None,
                      definitions: Any | None = None) -> list[str]:
    """现在可以开始一轮工作的角色（按定义顺序）。

    三种情形成立它就开工：有还没处理完的输入（接这个来源的角色）、有待处理的指导，或者它是能交完成的
    角色——交完成以前它可以一轮接一轮地工作（设计说明「直做」第 2、3 条）。还没回答的询问让提问方的
    会话接着跑（同一个口径）。同时运行（工单 #557）：一个角色同一时刻最多一轮工作。
    """
    definition = in_force(definitions)
    if projection.status in TERMINAL_STATUSES:
        return []
    asking = pending_ask_department(projection)
    completing = set(completing_departments(definition, projection.kind))
    ready: list[str] = []
    for department in definition.departments:
        if not _free(projection, waiting, department):
            continue
        if (department == asking or department in completing
                or has_new_input(projection, department, definition)
                or has_new_guidance(projection, department)):
            if department not in ready:
                ready.append(department)
    return ready


def next_department(projection: RunProjection, waiting: set[str] | None = None,
                    definitions: Any | None = None) -> str | None:
    """下一个开始一轮工作的角色：按定义顺序取第一个（单步入口用一次一个）。"""
    ready = ready_departments(projection, waiting, definitions)
    return ready[0] if ready else None


def department_ready(projection: RunProjection, department: str, waiting: set[str] | None = None,
                     definitions: Any | None = None) -> bool:
    """这个角色现在可以开始一轮工作：准备激活的事务里由薄驱动再问一次（同时运行，工单 #557）。"""
    return department in ready_departments(projection, waiting, definitions)


# ---------------------------------------------------------------------------
# 一轮以什么结束、事项以什么结束
# ---------------------------------------------------------------------------


def _proposal_methods(definitions: Any | None = None) -> frozenset[str]:
    # 这份路由的提议方式：提交类工具的名称（定义里写的），这一轮记下了其中一次的调用就是交了东西
    declared = routing_definition(definitions)
    return frozenset() if declared is None else frozenset(declared.proposal_methods)


def _round_outcome(events: list[Event], session_id: str | None, activation_id: str,
                   proposals: frozenset[str]) -> str:
    """这一轮怎么结束的：提交被接纳记 proposal_accepted，其余正常结束记 text_reply（载荷只有这两个取值）。

    判据是这一轮写下的事件：提交经写入口写入时看提交与拒绝的事件；提交还没有写入时（薄驱动拿到一轮结果
    以后先问路由这一轮以什么结束，再经写入口提交），看这一轮记下的提议方式——提交类工具的调用。
    """
    started = None
    for index, event in enumerate(events):
        if (event.type == EventType.DEPARTMENT_ACTIVATED and event.session_id == session_id
                and (event.payload or {}).get("activation_id") == activation_id):
            started = index
            break
    submitted = False
    for event in ([] if started is None else events[started + 1:]):
        if event.session_id != session_id:
            continue
        if event.type == EventType.PROPOSAL_SUBMITTED:
            submitted = True
        elif event.type == EventType.PROPOSAL_REJECTED:
            submitted = False
        elif (event.type == EventType.TOOL_CALLED
              and (event.payload or {}).get("name") in proposals):
            submitted = True
    return "proposal_accepted" if submitted else "text_reply"


def round_end(projection: RunProjection, events: list[Event], *, department: str, session_id: str | None,
              activation_id: str, definitions: Any | None = None) -> routing_contract.RoundEnd | None:
    """这一轮以什么结束：正常结束的一轮交出结果；暂停与失败不算正常结束（同一个口径）。"""
    if projection.status in _NOT_A_NORMAL_ROUND_END:
        return None
    return routing_contract.RoundEnd(
        outcome=_round_outcome(events, session_id, activation_id, _proposal_methods(definitions)))


def item_end(projection: RunProjection) -> routing_contract.ItemEnd | None:
    """事项以什么结束：没有角色可以开始一轮工作时，事项以这份路由定义里声明的原因结束。

    能交完成的角色还在等时它一直可以开工，所以走到这里意味着既没有输入、指导，也没有还没交完成的人：
    这件事停在没有新的工作上（设计说明第 5.4 节第 7 条：结束原因写在路由自己的定义里）。
    """
    return routing_contract.ItemEnd(stop_reason=ITEM_END_REASON, message="no role has new work")


def recorded_open_loop(events: list[Event]) -> bool:
    """事项创建事件里记下的开环标记（工单 #1394，形态与核验角色设计说明「定义的校验」第 4 条）。

    标记由薄驱动在创建事项时按冻结的定义算出并记下；路由与重放都读这条记录，不按定义重新算。
    旧事件没有这一项时读作不是开环。这条读法与成果驱动的那一份相同（两份路由不互相导入）。
    """
    for event in events:
        if event.type == EventType.RUN_CREATED:
            return bool((event.payload or {}).get("open_loop", False))
    return False


def completion_reason(projection: RunProjection,
                      events: list[Event]) -> routing_contract.CompletionReason | None:
    """事项完成时的结束原因：创建时记下的开环标记为真时是开环完成，其余不给原因（薄驱动按事项种类取）。

    这一条判断归路由（设计说明第 5.1 节输出、第 4.7 节第 4 条）：事项最后采纳交完成的那一份，没有核验
    角色核验它时以开环完成结束，不写成放行。薄驱动进入完成状态时问一次，只把这里给的原因写进事实。
    """
    if recorded_open_loop(events):
        return routing_contract.CompletionReason(stop_reason=OPEN_LOOP_STOP_REASON)
    return None


def work_reference(projection: RunProjection, department: str) -> Any:
    """这一轮工作的路由自己的工作引用（设计说明第 5.1 节输出、第 5.4 节第 4 条）：直做不用它，为空。"""
    return None


# ---------------------------------------------------------------------------
# 询问分支：询问的开始、回问、这一轮的上限、答没答出来
# ---------------------------------------------------------------------------


def _answered_branch(events: list[Event], session_id: str) -> dict[str, Any] | None:
    """这一层询问已经写下的回答：重新启动以后接着同一次询问时读它，不再跑一轮（工单 #473）。"""
    for event in reversed(events):
        if event.type == EventType.ASK_ANSWERED and event.session_id == session_id:
            return event.payload or {}
    return None


def ask_branch(projection: RunProjection, events: list[Event], *, requester: str, session_id: str,
               call: dict[str, Any], limits: routing_contract.AskLimits,
               definitions: Any | None = None):
    """提问方这个会话的这次询问：开一轮分支工作、直接给出结果，还是这次调用不合法。

    询问照现有规矩（设计说明「直做」第 2 条）：这个会话自己那次没结束的询问接着那一层，不新开一层；
    新开一层时回复的部门要在这个路由自己的部门清单里、不是提问方自己，问题与背景至少给一份。
    这一轮的上限取被问角色的声明量与提问方这一步剩下的量里小的那个；已经用掉的量由薄驱动扣。
    """
    args = call.get("args") or {}
    pending = projection.ask_by_origin(session_id)
    if pending is not None:
        branch_session_id = str(pending["branch_session_id"])
        recipient = str(pending["recipient"])
        start = None
    else:
        recipient = args.get("recipient")
        question = args.get("question")
        facts = args.get("facts") or ""
        if recipient not in routing_departments(definitions) or recipient == requester:
            return routing_contract.AskRejection(message=f"invalid recipient {recipient}")
        if not (isinstance(question, str) and question.strip()) \
                and not (isinstance(facts, str) and facts.strip()):
            return routing_contract.AskRejection(message="question must be a non-empty string")
        branch_session_id = new_id(f"ses_ask_{recipient[:3]}")
        start = {
            "requester": requester,
            "recipient": recipient,
            "question": question or "",
            "background": args.get("background", ""),
            "expected": args.get("expected", ""),
            "facts": args.get("facts") or None,
            "explanation": args.get("explanation") or None,
            "branch_session_id": branch_session_id,
        }
    answered = _answered_branch(events, branch_session_id)
    if answered is not None:
        return routing_contract.AskOutcome(
            status=str(answered.get("status") or "unable"),
            session_id=branch_session_id,
            answer=str(answered.get("answer") or ""),
            reason=str(answered.get("reason") or "branch unable to answer"),
            recorded=True,
        )
    remaining = call.get("remaining_steps")
    if remaining is None:
        remaining = limits.max_model_steps
    declared_steps = limits.department_max_model_steps.get(recipient, limits.max_model_steps)
    declared_time = limits.department_max_time_sec.get(recipient, float(projection.run_time_limit_sec))
    return routing_contract.AskBranch(
        recipient=recipient,
        session_id=branch_session_id,
        max_model_steps=min(declared_steps, remaining),
        max_time_sec=float(declared_time),
        start=start,
        work_ref={"ask": {"branch_session_id": branch_session_id, "requester": requester,
                          "recipient": recipient}},
    )


def ask_outcome(projection: RunProjection, *, branch: routing_contract.AskBranch,
                result: routing_contract.AskRoundResult,
                definitions: Any | None = None) -> routing_contract.AskOutcome:
    """分支这一轮以什么结束：把回答交回提问方，还是没能回答与原因。

    直做下回答不附带成果（交完成只能在自己的那一轮里交）；原因按这一轮的实际情形取。
    """
    if result.submission is None:
        if result.steps_left <= 0:
            reason = _STEP_LIMIT_REASON
        elif result.time_exhausted:
            reason = "department reached the time limit without submitting an answer"
        elif result.message:
            reason = result.message
        elif result.stop_reason:
            reason = result.stop_reason
        else:
            reason = _BRANCH_FAILED_REASON
        return routing_contract.AskOutcome(status="unable", session_id=branch.session_id, reason=reason)
    args = result.submission
    return routing_contract.AskOutcome(
        status="answered",
        session_id=branch.session_id,
        answer=args.get("answer") or args.get("text") or args.get("facts") or "",
        facts=args.get("facts") or None,
        explanation=args.get("explanation") or None,
    )


# ---------------------------------------------------------------------------
# 定义的内容：由路由自己校验（设计说明第 5.4 节第 2 条）
# ---------------------------------------------------------------------------


def check_definition(definitions: Any) -> None:
    """校验直做这份定义的内容：内核只核对结构，内容归路由自己。

    部门、成果种类与提议方式按名称引用这份定义，几种名称互相对得上；路由自己的结束原因不能与内核的
    停止原因同名，事项结束用的那一个要声明；事项最后采纳的那一份必须是这份路由认得、由提议方式提交、
    并且没有核验角色核验的成果——这一版还没有「交完成以后等核验结论」的路（#1396），定义了就在加载时
    拒绝，不把没有人核验的完成记成放行。不合格时抛出 InvalidRoutingDefinition，逐项写明是哪一项。
    """
    declared = routing_definition(definitions)
    if declared is None:
        raise routing_contract.InvalidRoutingDefinition(ROUTING_NAME, ["routings.json：没有这一种路由的定义"])
    issues: list[str] = []
    departments = tuple(item.id for item in definitions.organization.departments)
    for index, department in enumerate(declared.departments):
        if department not in departments:
            issues.append(f"departments[{index}]：部门 {department} 不在组织定义里")
    for department in departments:
        if department not in declared.departments:
            issues.append(f"departments：组织定义里的部门 {department} 没有列进路由的部门清单")
    for index, method in enumerate(declared.proposal_methods):
        if method not in definitions.tools or definitions.tools[method].proposal is None:
            issues.append(f"proposal_methods[{index}]：工具 {method} 不是定义里的提交类工具")
    outcomes = definitions.outcomes_of(ROUTING_NAME)
    submitted = {definitions.tools[method].proposal for method in declared.proposal_methods
                 if method in definitions.tools and definitions.tools[method].proposal is not None}
    for index, kind in enumerate(outcomes):
        if kind not in submitted:
            issues.append(f"outcomes[{index}]：成果种类 {kind} 没有由这里列出的提议方式提交")
    for kind in [tool.proposal for tool in definitions.tools.values() if tool.proposal is not None]:
        if kind not in outcomes:
            issues.append(f"outcomes：提交类工具提交的成果种类 {kind} 没有列进成果种类")
    for reason in declared.end_reasons:
        if reason in definitions.stop_reasons:
            issues.append(f"end_reasons.{reason}：与内核的停止原因同名")
    if ITEM_END_REASON not in declared.end_reasons:
        issues.append(f"end_reasons：没有声明事项结束用的原因 {ITEM_END_REASON}")
    # 事项最后采纳的那一份（工单 #1394）：直做的定义必须写明它，开环的标记按它判断
    final = declared.final_outcome
    if final is None:
        issues.append("final_outcome：直做的定义要写明事项最后采纳的成果种类（交完成那一份）")
    elif final not in outcomes:
        issues.append(f"final_outcome：成果种类 {final} 不是这份路由认得的成果种类")
    else:
        # 这一版还没有核验角色的路（#1396）：定义了核验角色核验最后采纳的那一份时整份拒绝
        if definitions.verified_by(final):
            issues.append(f"final_outcome：成果种类 {final} 由核验角色核验，而这一版直做还没有"
                          "「交完成以后等核验结论」的路（#1396）")
        if not any(final in proposal_kinds_for(department, kind, definitions)
                   for department in departments for kind in definitions.work_items.kinds):
            issues.append(f"final_outcome：没有角色能交 {final}，事项交不了完成")
    if issues:
        raise routing_contract.InvalidRoutingDefinition(ROUTING_NAME, issues)


# ---------------------------------------------------------------------------
# 收紧检查（设计说明第 5.5 节「路由提供收紧检查」）
# ---------------------------------------------------------------------------


def _is_write(name: str, definitions: Any | None = None) -> bool:
    return tool_action(name, definitions=definitions) == "write"


def _allowed_now(projection: RunProjection, department: str, definitions: Any | None = None) -> set[str]:
    # 这个角色此刻能交的提案种类：它在工作、或者可以开始一轮工作时，按提案合同给出的种类
    definition = in_force(definitions)
    if projection.status in TERMINAL_STATUSES or department not in definition.departments:
        return set()
    if not (is_working(projection, department) or department_ready(projection, department, None, definition)):
        return set()
    return proposal_kinds_for(department, projection.kind, definition)


def _tool_error(projection: RunProjection, department: str, name: str,
                definitions: Any | None = None) -> str | None:
    # 这个工具是不是这个角色此刻能做的提交：能交完成的角色在自己的那一轮里交完成
    kind = proposal_kind(name, definitions=definitions)
    if kind is not None and kind not in _allowed_now(projection, department, definitions):
        return "This proposal is not permitted in the current department work."
    return None


def _completion_errors(proposal: dict[str, Any]) -> list[FieldError]:
    # 交完成的形状：说明必填，拿不准的地方与已知风险可选，都是逐条写明的字符串
    errors: list[FieldError] = []
    summary = proposal.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        errors.append(FieldError("summary", "summary must be a non-empty string"))
    for field in ("uncertain", "known_risks"):
        value = proposal.get(field)
        if value is None:
            continue
        if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
            errors.append(FieldError(field, f"{field} must be a list of non-empty strings"))
    return errors


class DirectTightening:
    # 直做的收紧检查（设计说明第 5.1 节：路由实现与它的收紧检查是同一条路由的两半）。
    # 一次工具调用、一份提案经这里判断；交完成通过时给出成果的内容并结束事项
    CONTRACT_VERSION = tightening_contract.CURRENT_VERSION

    def kinds(self, request: TightenRequest) -> set[str]:
        # 这个角色此刻能提交的提案种类
        return _allowed_now(request.state, request.department, request.definitions)

    def offered(self, request: TightenRequest) -> list[str]:
        # 请求中提供给模型的工具：按这一轮的工作与询问分支取舍，再按调用目标的输入方式去掉需要图像输入的工具
        projection, department = request.state, request.department
        definitions = in_force(request.definitions)
        available = tools_for(department, projection.kind, definitions=definitions)
        if projection.ask_by_branch(request.session_id) is not None:
            # 询问分支里：可以回答；层数允许时可以回问；不能写工作区、不能提交提案
            chain_allowed, _ = ask_chain_decision(projection.ask_position(request.session_id),
                                                  ask_chain_max_depth())
            nested = ["ask"] if chain_allowed else []
            allowed = [name for name in available
                       if name != "ask" and not _is_write(name, definitions)
                       and proposal_kind(name, definitions=definitions) is None]
            return allowed + ["answer"] + nested
        return [name for name in offers_with_input(available, request.input_modalities, definitions=definitions)
                if _tool_error(projection, department, name, definitions) is None]

    def tool(self, request: TightenRequest) -> Tightened:
        # 一次工具调用的收紧检查：输入版本、询问分支、这个角色此刻能交的种类
        projection, department = request.state, request.department
        definitions = in_force(request.definitions)
        call = request.tool or {}
        name = call.get("name")
        if (proposal_kind(name, definitions=definitions) is not None and request.basis is not None
                and projection.input_version != request.basis.input_version):
            # 正式成果要等模型看见新输入以后再提交（工单 #964）：这次提交推迟到下一步
            return Tightened(reason=(
                "new user input arrived and has not entered this session's model input yet; "
                "this proposal is not accepted now. Read the work_notification of the next step, then submit again"
            ), deferred=True)
        branch = self._branch_permission(projection, request.session_id, department, name, definitions)
        if branch is not None:
            return branch
        reason = _tool_error(projection, department, name, definitions)
        return Tightened() if reason is None else Tightened(reason=reason)

    def _branch_permission(self, projection: RunProjection, session_id: str | None, department: str,
                           name: str, definitions: Any) -> Tightened | None:
        # 询问分支的许可按会话判定（工单 #473）：分支里只能回答与回问，不能写工作区、不能交完成
        if projection.ask_by_branch(session_id) is None:
            if name == "answer":
                return Tightened(reason=ANSWER_ONLY_IN_BRANCH)
            return None
        if name == "answer":
            return Tightened(permitted=True)
        if name == "ask":
            if projection.ask_by_origin(session_id) is not None:
                return None
            allowed, reason = ask_chain_decision(projection.ask_position(session_id), ask_chain_max_depth())
            return None if allowed else Tightened(reason=reason)
        if _is_write(name, definitions):
            return Tightened(reason=BRANCH_CANNOT_WRITE)
        if proposal_kind(name, definitions=definitions) is not None:
            return Tightened(reason=f"The branch session cannot submit proposal {name}")
        return None

    def submission(self, request: TightenRequest) -> Tightened:
        # 一次提案提交的检查与内容组装：直做组装交完成（通过时结束事项，薄驱动按路由给的结束原因记成
        # 开环完成），以及建档的两份产物——初始 PRD 带上这一版覆盖到的输入版本，现有结构说明带上工作区的
        # 树摘要与当时的初始 PRD（工单 #1510，接入已有项目设计说明第 4.1 节）。其余种类照常由内核按提案合同
        # 核对，内容就是提案的参数
        proposal = request.proposal
        if not isinstance(proposal, dict):
            return Tightened()
        kind = str(proposal.get("kind"))
        if kind == STRUCTURE_KIND:
            return self._structure(request)
        if kind == PRODUCT_SPEC_KIND:
            return self._product_spec(request)
        if kind != COMPLETION_KIND:
            return Tightened()
        errors = _completion_errors(proposal)
        if errors:
            return Tightened(errors=tuple(errors))
        content = {
            "summary": str(proposal["summary"]).strip(),
            "uncertain": [str(item).strip() for item in proposal.get("uncertain") or ()],
            "known_risks": [str(item).strip() for item in proposal.get("known_risks") or ()],
        }
        return Tightened(content=content, ends_run=True)

    def _product_spec(self, request: TightenRequest) -> Tightened:
        # 初始 PRD 的内容：提案给出的字段，加上这一版覆盖到的用户输入版本（有效合同按它记下依据）。
        # 引用当前版本这类条件由提案合同给出，内核按名字核对（工单 #1456）
        proposal = request.proposal or {}
        outcome = evaluate_conditions(PRODUCT_SPEC_KIND, department=request.department, proposal=proposal,
                                      minimal=request.minimal, facts=request.facts,
                                      definitions=request.definitions)
        if outcome.errors:
            return Tightened(errors=tuple(outcome.errors))
        content = {key: value for key, value in proposal.items() if key != "kind"}
        content["input_version"] = int(request.state.input_version)
        return Tightened(content=content)

    def _structure(self, request: TightenRequest) -> Tightened:
        # 现有结构说明的内容：提案给出的字段，加上工作区的树摘要与当时的初始 PRD。构建与测试的每一项
        # 要带本次激活中绑定当前快照与当前 PRD 的 run_check 回执，由提案合同的通用条件取（设计说明第 5.5 节）
        proposal = request.proposal or {}
        spec_hash = request.minimal.artifact_hash(PRODUCT_SPEC_KIND)
        if spec_hash is None:
            return Tightened(errors=(FieldError(PRODUCT_SPEC_KIND, "no active ProductSpec"),))
        outcome = evaluate_conditions(STRUCTURE_KIND, department=request.department, proposal=proposal,
                                      minimal=request.minimal, facts=request.facts,
                                      definitions=request.definitions)
        if outcome.errors:
            return Tightened(errors=tuple(outcome.errors))
        build_and_test = [{**item, "name": str(item["name"]).strip(),
                           "receipt": outcome.receipts[str(item["name"]).strip()]}
                          for item in proposal.get("build_and_test") or ()]
        content = {key: value for key, value in proposal.items() if key != "kind"}
        content["build_and_test"] = build_and_test
        content["product_spec_hash"] = spec_hash
        content["code_tree_digest"] = request.facts.digest
        return Tightened(content=content)


DIRECT_TIGHTENING = DirectTightening()


class Direct:
    # 直做的路由（设计说明第 5.1 节「选择」）：组织定义的 routing 写 direct。
    # 部门与成果种类按**这份形态自己的定义**取（工单 #1509）：组装处交给它这一份时就按这一份，
    # 没有交时读进程加载的那一份。一份形态一份实例，形态之间不共用
    NAME = ROUTING_NAME
    CONTRACT_VERSION = routing_contract.CURRENT_VERSION

    def __init__(self, definitions: Any | None = None) -> None:
        self._definitions = definitions

    def use_definitions(self, definitions: Any) -> "Direct":
        # 组装处的注入入口（契约第三版只增的可选方法，工单 #1509）：交出一份接上这一份定义的新实例
        return Direct(definitions)

    def check_definition(self, definitions: Any) -> None:
        check_definition(definitions)

    def ready_departments(self, view: RunProjection, *, waiting: set[str] | None = None) -> list[str]:
        return ready_departments(view, waiting, self._definitions)

    def next_department(self, view: RunProjection, *, waiting: set[str] | None = None) -> str | None:
        return next_department(view, waiting, self._definitions)

    def department_ready(self, view: RunProjection, *, department: str,
                         waiting: set[str] | None = None) -> bool:
        return department_ready(view, department, waiting, self._definitions)

    def work_reference(self, view: RunProjection, *, department: str) -> Any:
        return work_reference(view, department)

    def round_end(self, view: RunProjection, events: list[Event], *, department: str,
                  session_id: str | None, activation_id: str) -> routing_contract.RoundEnd | None:
        return round_end(view, events, department=department, session_id=session_id,
                         activation_id=activation_id, definitions=self._definitions)

    def item_end(self, view: RunProjection) -> routing_contract.ItemEnd | None:
        return item_end(view)

    def completion_reason(self, view: RunProjection,
                          events: list[Event]) -> routing_contract.CompletionReason | None:
        return completion_reason(view, events)

    def ask_branch(self, view: RunProjection, events: list[Event], *, requester: str, session_id: str,
                   call: dict[str, Any], limits: routing_contract.AskLimits):
        return ask_branch(view, events, requester=requester, session_id=session_id, call=call,
                          limits=limits, definitions=self._definitions)

    def ask_outcome(self, view: RunProjection, *, branch: routing_contract.AskBranch,
                    result: routing_contract.AskRoundResult) -> routing_contract.AskOutcome:
        return ask_outcome(view, branch=branch, result=result, definitions=self._definitions)


ROUTING = routing_contract.register(Direct())
