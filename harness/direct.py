# 直做的路由实现与它的收紧检查（工单 #1395；形态与核验角色设计说明「直做」「开环完成」
# 「形态随事项冻结」；骨架与应用设计说明「路由契约」、「其他路由：骨架要满足的条件」、「裁决的分工：内核的通用检查与路由的收紧检查」；总图第一节「轮转方式」、第四节「路由」缝）。
#
# 形状（形态与核验角色设计说明「直做」）：定义写明角色清单、每一种事项的来源由哪个角色接、谁能交完成、
# 成果种类与提案合同。事项开始时接这个来源的角色开始第一轮；之后没有在工作的角色收到指导或询问时开始一轮；
# 角色之间靠询问交流，询问照现有规矩嵌在一轮里（询问分支的判断与成果驱动同一个口径）。定义里指定的角色
# 交了完成，事项结束：没有核验角色核验它，结束原因是开环完成——路由按事项创建事件里记下的开环标记给出
# （工单 #1394 的做法），薄驱动只把它写进事实。
#
# 一轮工作在交完成以前可以有很多轮：可以交完成、还没有交的那些角色一直可以开始下一轮，直到交了完成
# （事项结束）或者内核的时间、轮次与步数上限把它停下（：一定会停靠内核的上限）。
#
# 建档（工单 #1510，接入已有项目设计说明「总体」）：同一个路由也跑建档事项。接「建档」这一来源的角色交初始
# PRD 与现有结构说明，然后交完成；这份形态没有核验角色，建档没有基线核验这一步，交完成以后以开环完成结束，
# 项目层照常提出初始 PRD 候选并请用户确认（确认请求写明这份基线没有经过基线核验）。
#
# 直做加核验角色（#1396，设计说明「直做」第 3 条、「核验角色」）：定义里声明了核验角色核验交完成的那一份时，
# 交完成以后事项不结束——等核验角色对**当前这一版**的结论：放行则事项以放行结束，打回则交完成的角色再开始
# 一轮；交出新的一版以后，对上一版的结论不再作数（结论绑定它核验的那一版的内容摘要）。几个核验角色核验同一份
# 时，每一个都放行才算放行，任何一个打回就返工；核验角色不能核验自己（被核验的角色给自己下结论同样拒绝）。
#
# 核验本身不在这里写：写入范围、独立副本与检查回执归定义与执行层，这一版直做的路由
# **只问结论**——从运行流的事件折出当前这一版的完成与各核验角色对它的结论（通用的成果接纳事件，S2c 工单 #1098）。
# 折事件要有事件的入口，所以本模块声明契约第三版的可选方法 `use_facts`（工单 #1164，与任务池同一个做法）：
# 组装处 select 接上它以后把事件库的只读读取器交给它。收紧检查拿的是这一次提交的事务里的事件，不用它。
#
# 本模块不导入别的路由实现（：路由之间不互相导入）：询问分支、一轮怎么结束这些规矩
# 在这里自成一份，与成果驱动的那一份同口径。

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import routing_contract, tightening_contract
from .adjudication import ask_chain_decision, ask_chain_max_depth
from .definitions import DEFINITIONS
from .models import OPEN_LOOP_STOP_REASON, Event, EventType, RunProjection, TERMINAL_STATUSES, new_id
from .tools import in_force, offers_with_input, proposal_kind, tool_action, tools_for
from .validation import FieldError, TightenRequest, Tightened, evaluate_conditions

# 组织定义 organization.json 的 routing 里写这个名称（docs/design/skeleton-and-application.md「路由契约」「选择」）
ROUTING_NAME = "direct"

# 单角色直做形态的名字（harness/runtime.py 的形态登记处、harness/definitions/forms/single_role_direct/）
SINGLE_ROLE_DIRECT = "single_role_direct"

# 交完成这种成果的种类：这份路由的最后采纳是它（routings.json 的 final_outcome）。直做下的完成说明
# 就是事项最后采纳的那一份，交完成的事件由通用的成果接纳写法写下（S2c，工单 #1098）
COMPLETION_KIND = "completion"

# 建档的两份产物（工单 #1510，接入已有项目设计说明「总体」）：直做下接建档的那个角色既写初始 PRD，
# 也写现有结构说明。没有核验角色的形态没有基线核验这一步，交完成为止；两份产物由定义里给的提交工具提交，
# 内容按内核的通用条件组装（内核不认识具体有哪几种成果，工单 #1456）
PRODUCT_SPEC_KIND = "product_spec"
STRUCTURE_KIND = "structure"

# 核验结论的成果种类与它的两个取值（工单 #1396）：直做加核验角色时，核验角色对当前这一版的完成给
# 放行或打回。结论由主机绑定提交时当前的那一版（内容摘要），新的一版让旧结论不再作数。
# 与交完成一样，这个名称是这份路由实现认得的一种成果（定义里按名称列出它，代码里不认识别的写法）
REVIEW_KIND = "completion_review"
RELEASE_VERDICT = "release"
REWORK_VERDICT = "rework"

# 一份直做定义必须写明事项结束用的那一个原因：它的定义里声明的封闭清单中的一条
ITEM_END_REASON = "no_open_work"

# 一轮没有正常结束的两种状态：暂停与失败（与成果驱动同一个口径，输出）
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
    """这个路由的部门清单：它自己的一份定义里写的（docs/design/skeleton-and-application.md「其他路由：骨架要满足的条件」中「每种路由有自己的一份定义」）。"""
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

    直做下事项以「交完成的那一份」结束（docs/design/forms-and-verifier-role.md「定义的校验」中「开环的标记」、routings.json 的 final_outcome），
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
# 核验结论：从事件折出当前这一版的完成与各核验角色对它的结论（工单 #1396，设计说明「核验角色」）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AcceptedOutcomes:
    """运行流里通用的成果接纳事件折出来的现状：交完成的各版与核验结论（按接纳的先后）。

    路由只问结论，不自己写核验（docs/design/forms-and-verifier-role.md「核验角色」「路由不写核验，只问核验」）：交完成与核验结论都是通用的
    成果接纳事件（S2c，工单 #1098），种类与作者部门在载荷的统一字段里，内容由各自的收紧检查组装。
    """

    completions: tuple[dict[str, Any], ...] = ()
    reviews: tuple[dict[str, Any], ...] = ()

    def latest_completion(self) -> dict[str, Any] | None:
        # 当前这一版的完成：最后一次被接纳的那一版（交出新的一版以后，旧结论按内容摘要对不上它）
        return self.completions[-1] if self.completions else None

    def verdict(self, verifier: str, completion_hash: Any) -> dict[str, Any] | None:
        # 这个核验角色对那一版给出的结论：同一版给了多次时以后一次为准；还没有结论时为空
        for review in reversed(self.reviews):
            if (review.get("artifact_issuer") == verifier
                    and review.get("completion") == completion_hash):
                return review
        return None


# 没有给出成果接纳事件时按空处理：只看定义、不看事实的调用（例如按部门列工具的装配）用这一份
NO_OUTCOMES = AcceptedOutcomes()


def fold(events: list[Event]) -> AcceptedOutcomes:
    """从运行流的事件折出直做要看的两种成果（输入：路由自己折要用的状态）。"""
    completions: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    for event in events:
        if event.type != EventType.ARTIFACT_ACCEPTED:
            continue
        payload = dict(event.payload or {})
        kind = payload.get("artifact_kind")
        if kind == COMPLETION_KIND:
            completions.append(payload)
        elif kind == REVIEW_KIND:
            reviews.append(payload)
    return AcceptedOutcomes(completions=tuple(completions), reviews=tuple(reviews))


def _final_outcome(definitions: Any | None = None) -> str | None:
    declared = routing_definition(definitions)
    return None if declared is None else declared.final_outcome


def verified_outcome(department: str, definitions: Any | None = None) -> bool:
    """这个角色交出的最后采纳的那一份有没有核验角色核验：有，它交了完成以后事项不结束（工单 #1396）。"""
    final = _final_outcome(definitions)
    return final is not None and bool(in_force(definitions).verifiers_of(department, final))


def verification_of_current(artifacts: AcceptedOutcomes | None = None,
                            definitions: Any | None = None) -> tuple[tuple[str, dict[str, Any] | None], ...]:
    """当前这一版完成的核验角色与各自的结论（按核验声明里的顺序）：没有交完成、或者交的人没有核验角色时为空。"""
    definition = in_force(definitions)
    final = _final_outcome(definition)
    artifacts = NO_OUTCOMES if artifacts is None else artifacts
    completion = artifacts.latest_completion()
    if completion is None or final is None or completion.get("artifact_kind") != final:
        return ()
    author = completion.get("artifact_issuer")
    if not isinstance(author, str):
        return ()
    return tuple((verifier, artifacts.verdict(verifier, completion.get("content_hash")))
                 for verifier in definition.verifiers_of(author, final))


def _all_released(current: tuple[tuple[str, dict[str, Any] | None], ...]) -> bool:
    return bool(current) and all(verdict is not None and verdict.get("verdict") == RELEASE_VERDICT
                                 for _verifier, verdict in current)


def awaiting_verdict(artifacts: AcceptedOutcomes | None = None,
                     definitions: Any | None = None) -> bool:
    """交完成以后还在等结论：当前这一版还有核验角色没给结论，也没有人打回它。

    有核验角色时，交完成以后事项不结束（设计说明「直做」第 3 条）：等每一个核验角色对当前这一版的结论，
    全部放行才算放行；任何一个打回就返工，那时不再等（交完成的角色重新开工）。
    """
    current = verification_of_current(artifacts, definitions)
    if not current or _all_released(current):
        return False
    return not rework_requested(artifacts, definitions)


def rework_requested(artifacts: AcceptedOutcomes | None = None,
                     definitions: Any | None = None) -> bool:
    """当前这一版被打回：交完成的角色要再做一轮（交出新的一版，旧结论随之失效）。"""
    return any(verdict is not None and verdict.get("verdict") == REWORK_VERDICT
               for _verifier, verdict in verification_of_current(artifacts, definitions))


def waiting_verifiers(artifacts: AcceptedOutcomes | None = None,
                      definitions: Any | None = None) -> set[str]:
    """当前这一版还没有给结论、并且现在就该给的那些核验角色：它们在等结论时开工（返工时不再开工）。"""
    if not awaiting_verdict(artifacts, definitions):
        return set()
    return {verifier for verifier, verdict in verification_of_current(artifacts, definitions)
            if verdict is None}


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
    """发给这个角色的指导：还没有进入它的一轮工作的（部门指导设计说明「处理结果与来源」）。"""
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
                      definitions: Any | None = None,
                      artifacts: AcceptedOutcomes | None = None) -> list[str]:
    """现在可以开始一轮工作的角色（按定义顺序）。

    三种情形成立它就开工：有还没处理完的输入（接这个来源的角色）、有待处理的指导，或者它是能交完成的
    角色——交完成以前它可以一轮接一轮地工作（设计说明「直做」第 2、3 条）。还没回答的询问让提问方的
    会话接着跑（同一个口径）。同时运行（工单 #557）：一个角色同一时刻最多一轮工作。

    有核验角色时（工单 #1396）：交了完成以后，能交完成的角色不再开工——它等结论；还没给结论的核验角色
    这时开工。放行到齐时事项已经结束（放行那一次提交结束它）；打回以后交完成的角色重新开工，交出新的一版。
    """
    definition = in_force(definitions)
    if projection.status in TERMINAL_STATUSES:
        return []
    asking = pending_ask_department(projection)
    completing = set(completing_departments(definition, projection.kind))
    current = verification_of_current(artifacts, definition)
    rework = rework_requested(artifacts, definition)
    # 交了完成、还没有人打回：交完成的角色等着（全部放行的情形事项已经结束，也不再有谁开工）。
    # 这期间到达的输入与指导排着队，等结论到了、或者打回以后再进入它的一轮
    waiting_for_conclusion = bool(current) and not rework
    verifiers_at_work = waiting_verifiers(artifacts, definition)
    ready: list[str] = []
    for department in definition.departments:
        if not _free(projection, waiting, department):
            continue
        if waiting_for_conclusion and department in completing:
            continue
        if (department == asking
                or department in completing
                or department in verifiers_at_work
                or has_new_input(projection, department, definition)
                or has_new_guidance(projection, department)):
            if department not in ready:
                ready.append(department)
    return ready


def next_department(projection: RunProjection, waiting: set[str] | None = None,
                    definitions: Any | None = None,
                    artifacts: AcceptedOutcomes | None = None) -> str | None:
    """下一个开始一轮工作的角色：按定义顺序取第一个（单步入口用一次一个）。"""
    ready = ready_departments(projection, waiting, definitions, artifacts)
    return ready[0] if ready else None


def department_ready(projection: RunProjection, department: str, waiting: set[str] | None = None,
                     definitions: Any | None = None,
                     artifacts: AcceptedOutcomes | None = None) -> bool:
    """这个角色现在可以开始一轮工作：准备激活的事务里由薄驱动再问一次（同时运行，工单 #557）。"""
    return department in ready_departments(projection, waiting, definitions, artifacts)


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


def item_end(projection: RunProjection, definitions: Any | None = None,
             artifacts: AcceptedOutcomes | None = None) -> routing_contract.ItemEnd | None:
    """事项以什么结束：没有角色可以开始一轮工作时，事项以这份路由定义里声明的原因结束。

    能交完成的角色还在等时它一直可以开工，所以走到这里意味着既没有输入、指导，也没有还没交完成的人：
    这件事停在没有新的工作上（docs/design/skeleton-and-application.md「其他路由：骨架要满足的条件」中「一定会停对任何路由都成立」：结束原因写在路由自己的定义里）。

    还在等核验结论时不结束（工单 #1396）：这不是没有新的工作，是等着核验角色对当前这一版下结论
    （核验角色正在工作时由它的会话接着跑；这里守着的是它还没被排上时的这一刻）。
    """
    if awaiting_verdict(artifacts, definitions):
        return None
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

    这一条判断归路由（输出、docs/design/forms-and-verifier-role.md「定义的校验」中「开环的标记」）：事项最后采纳交完成的那一份，没有核验
    角色核验它时以开环完成结束，不写成放行。薄驱动进入完成状态时问一次，只把这里给的原因写进事实。
    """
    if recorded_open_loop(events):
        return routing_contract.CompletionReason(stop_reason=OPEN_LOOP_STOP_REASON)
    return None


def work_reference(projection: RunProjection, department: str) -> Any:
    """这一轮工作的路由自己的工作引用（docs/design/skeleton-and-application.md「路由契约」输出、docs/design/skeleton-and-application.md「其他路由：骨架要满足的条件」）：直做不用它，为空。"""
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
# 定义的内容：由路由自己校验
# ---------------------------------------------------------------------------


def check_definition(definitions: Any) -> None:
    """校验直做这份定义的内容：内核只核对结构，内容归路由自己。

    部门、成果种类与提议方式按名称引用这份定义，几种名称互相对得上；路由自己的结束原因不能与内核的
    停止原因同名，事项结束用的那一个要声明；事项最后采纳的那一份必须是这份路由认得、由提议方式提交的
    成果。有核验角色核验它时（工单 #1396），核验的双方都要交得出自己的那一样：被核验的角色交得了那一份
    完成，核验角色交得了核验结论（`completion_review`）——交不出时事项要么永远等不到放行，要么放行了
    没有结论，都在加载时整份拒绝。不合格时抛出 InvalidRoutingDefinition，逐项写明是哪一项。
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
        can_complete = tuple(
            department for department in departments
            if any(final in proposal_kinds_for(department, kind, definitions)
                   for kind in definitions.work_items.kinds))
        if not can_complete:
            issues.append(f"final_outcome：没有角色能交 {final}，事项交不了完成")
        # 核验角色（工单 #1396）：核验的双方都交得出自己的那一样；谁能拒绝谁无环（角色核验自己）由
        # 定义的加载核对，与路由无关
        pairs = {(verifier, verified) for verifier, verified, kind in definitions.rejection_edges()
                 if kind == final}
        for verifier, verified in sorted(pairs):
            if verified not in can_complete:
                issues.append(f"verification：核验角色 {verifier} 核验的 {verified} 交不了 {final}，"
                              "它永远没有可以核验的那一版")
            if not any(REVIEW_KIND in proposal_kinds_for(verifier, kind, definitions)
                       for kind in definitions.work_items.kinds):
                issues.append(f"verification：核验角色 {verifier} 交不了核验结论 {REVIEW_KIND}，"
                              f"事项交完成以后等不到放行")
    if issues:
        raise routing_contract.InvalidRoutingDefinition(ROUTING_NAME, issues)


# ---------------------------------------------------------------------------
# 收紧检查（docs/design/skeleton-and-application.md「裁决的分工：内核的通用检查与路由的收紧检查」「路由提供收紧检查」）
# ---------------------------------------------------------------------------


def _is_write(name: str, definitions: Any | None = None) -> bool:
    return tool_action(name, definitions=definitions) == "write"


def _allowed_now(projection: RunProjection, department: str, definitions: Any | None = None,
                 artifacts: AcceptedOutcomes | None = None) -> set[str]:
    # 这个角色此刻能交的提案种类：它在工作、或者可以开始一轮工作时，按提案合同给出的种类。
    # 有核验角色时再按「交完成以后等结论」收窄（工单 #1396）：等结论时交完成的角色交不了新的完成，
    # 核验角色只在当前这一版还没有它的结论时交得了结论。没有给出成果接纳事件时（装配按部门列工具）
    # 不做这一层收窄：那一刻不看事实，提交时再由内核带着事件问一次
    definition = in_force(definitions)
    if projection.status in TERMINAL_STATUSES or department not in definition.departments:
        return set()
    if not (is_working(projection, department)
            or department_ready(projection, department, None, definition, artifacts)):
        return set()
    kinds = proposal_kinds_for(department, projection.kind, definition)
    if artifacts is None:
        return kinds
    if awaiting_verdict(artifacts, definition) \
            and department in completing_departments(definition, projection.kind):
        kinds.discard(COMPLETION_KIND)
    if REVIEW_KIND in kinds and department not in waiting_verifiers(artifacts, definition):
        kinds.discard(REVIEW_KIND)
    return kinds


def _tool_error(projection: RunProjection, department: str, name: str,
                definitions: Any | None = None, artifacts: AcceptedOutcomes | None = None) -> str | None:
    # 这个工具是不是这个角色此刻能做的提交：能交完成的角色在自己的那一轮里交完成，等结论时交不了
    kind = proposal_kind(name, definitions=definitions)
    if kind is not None and kind not in _allowed_now(projection, department, definitions, artifacts):
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


def _review_tightened(request: TightenRequest, proposal: dict[str, Any],
                      outcomes: AcceptedOutcomes, definitions: Any) -> Tightened:
    """核验结论这一次提交的检查与内容组装（工单 #1396）：结论绑定提交时当前的那一版完成。

    核验对象是当前这一版的完成（作者写在载荷的统一字段上）；核验角色按定义里的声明判，不按部门名。
    被核验的角色给自己下结论同样拒绝（基础规则 3）：它是这一版的作者，不能给自己的成果下结论。
    全部核验角色对同一版的结论都到了、都是放行时，这一次提交结束事项（ends_run，设计说明「直做」第 3 条）。
    """
    department = request.department
    final = _final_outcome(definitions)
    completion = outcomes.latest_completion()
    if completion is None or final is None:
        return Tightened(reason="no completion is waiting for a conclusion")
    author = completion.get("artifact_issuer")
    if department == author:
        return Tightened(reason=(f"{department} handed in this completion and cannot conclude on it: "
                                 "the author of an outcome does not decide about it"))
    if not isinstance(author, str) or department not in definitions.verifiers_of(author, final):
        return Tightened(reason=f"{department} does not verify {author}'s {final}")
    if outcomes.verdict(department, completion.get("content_hash")) is not None:
        return Tightened(reason=("this version already carries your conclusion; "
                                 "a new version from the author needs a new conclusion"))
    verdict = proposal.get("verdict")
    if verdict not in (RELEASE_VERDICT, REWORK_VERDICT):
        return Tightened(errors=(FieldError("verdict", "verdict must be release or rework"),))
    rationale = proposal.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        return Tightened(errors=(FieldError("rationale", "rationale must be a non-empty string"),))
    # 每一个核验角色都放行才算放行：还有别人没有结论时这一次不结束事项，等它的结论
    others = [outcomes.verdict(verifier, completion.get("content_hash"))
              for verifier in definitions.verifiers_of(author, final) if verifier != department]
    releases = verdict == RELEASE_VERDICT and all(
        other is not None and other.get("verdict") == RELEASE_VERDICT for other in others)
    return Tightened(content={
        "completion": completion.get("content_hash"),
        "completion_issuer": author,
        "completion_version": completion.get("artifact_version"),
        "verdict": verdict,
        "rationale": rationale.strip(),
    }, ends_run=releases)


class DirectTightening:
    # 直做的收紧检查（docs/design/skeleton-and-application.md「路由契约」：路由实现与它的收紧检查是同一条路由的两半）。
    # 一次工具调用、一份提案经这里判断；交完成通过时给出成果的内容并结束事项（有核验角色时交出的是核验
    # 结论，每一个核验角色都放行时结束事项）
    CONTRACT_VERSION = tightening_contract.CURRENT_VERSION

    def kinds(self, request: TightenRequest) -> set[str]:
        # 这个角色此刻能提交的提案种类：这一次提交带着运行流的事件，按当前这一版的完成收窄
        return _allowed_now(request.state, request.department, request.definitions,
                            fold(list(request.events)))

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
        reason = _tool_error(projection, department, name, definitions, fold(list(request.events)))
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
        # 一次提案提交的检查与内容组装：直做组装交完成（没有核验角色时通过即结束事项，薄驱动按路由给的
        # 结束原因记成开环完成），有核验角色时还有核验结论这一种（每一个核验角色都放行才结束事项）；
        # 建档的两份产物——初始 PRD 带上这一版覆盖到的输入版本，现有结构说明带上工作区的树摘要与当时的
        # 初始 PRD（工单 #1510，接入已有项目设计说明「总体」）。其余种类照常由内核按提案合同核对，
        # 内容就是提案的参数
        proposal = request.proposal
        if not isinstance(proposal, dict):
            return Tightened()
        kind = str(proposal.get("kind"))
        if kind == STRUCTURE_KIND:
            return self._structure(request)
        if kind == PRODUCT_SPEC_KIND:
            return self._product_spec(request)
        definitions = in_force(request.definitions)
        outcomes = fold(list(request.events))
        if kind == REVIEW_KIND:
            return _review_tightened(request, proposal, outcomes, definitions)
        if kind != COMPLETION_KIND:
            return Tightened()
        if awaiting_verdict(outcomes, definitions):
            # 交完成以后等结论（工单 #1396）：这时再交一版会让核验角色正在看的那一版作废，
            # 所以交完成的角色等结论——全部放行则事项结束，打回则它再交新的一版
            return Tightened(reason=("the current completion is waiting for the verifier's conclusion; "
                                     "a new version is handed in after a rework verdict"))
        errors = _completion_errors(proposal)
        if errors:
            return Tightened(errors=tuple(errors))
        content = {
            "summary": str(proposal["summary"]).strip(),
            "uncertain": [str(item).strip() for item in proposal.get("uncertain") or ()],
            "known_risks": [str(item).strip() for item in proposal.get("known_risks") or ()],
        }
        # 有核验角色时交完成不结束事项：等它对当前这一版的结论（放行那一次提交结束它）
        return Tightened(content=content, ends_run=not verified_outcome(request.department, definitions))

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
        # 要带本次激活中绑定当前快照与当前 PRD 的 run_check 回执，由提案合同的通用条件取
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
    # 直做的路由（docs/design/skeleton-and-application.md「路由契约」「选择」）：组织定义的 routing 写 direct。
    # 部门与成果种类按**这份形态自己的定义**取（工单 #1509）：组装处交给它这一份时就按这一份，
    # 没有交时读进程加载的那一份。一份形态一份实例，形态之间不共用。
    # 核验结论与交完成的各版在事件里（工单 #1396）：组装处把它的事件库的只读读取器交给它（use_facts，
    # 契约第三版的可选方法，工单 #1164），路由据此折出当前这一版的完成与各核验角色的结论
    NAME = ROUTING_NAME
    CONTRACT_VERSION = routing_contract.CURRENT_VERSION

    def __init__(self, definitions: Any | None = None) -> None:
        self._definitions = definitions
        self._facts: Any = None

    def use_definitions(self, definitions: Any) -> "Direct":
        # 组装处的注入入口（契约第三版只增的可选方法，工单 #1509）：交出一份接上这一份定义的新实例
        return Direct(definitions)

    def use_facts(self, reader: Any) -> None:
        # 组装处交给它的只读事件读取器（工单 #1164、#1396）：只有 list_events(run_id)，没有写事件的出路
        self._facts = reader

    def _accepted_outcomes(self, view: RunProjection) -> AcceptedOutcomes:
        # 当前这一版的完成与各核验角色的结论：从运行流的事件折出来。没有交事件库时没有已经交上来的成果
        # （只按定义判断的调用如此），有核验角色的形态在组装处一定拿到读取器
        if self._facts is None or not getattr(view, "run_id", None):
            return NO_OUTCOMES
        return fold(list(self._facts.list_events(view.run_id)))

    def check_definition(self, definitions: Any) -> None:
        check_definition(definitions)

    def ready_departments(self, view: RunProjection, *, waiting: set[str] | None = None) -> list[str]:
        return ready_departments(view, waiting, self._definitions, self._accepted_outcomes(view))

    def next_department(self, view: RunProjection, *, waiting: set[str] | None = None) -> str | None:
        return next_department(view, waiting, self._definitions, self._accepted_outcomes(view))

    def department_ready(self, view: RunProjection, *, department: str,
                         waiting: set[str] | None = None) -> bool:
        return department_ready(view, department, waiting, self._definitions, self._accepted_outcomes(view))

    def work_reference(self, view: RunProjection, *, department: str) -> Any:
        return work_reference(view, department)

    def round_end(self, view: RunProjection, events: list[Event], *, department: str,
                  session_id: str | None, activation_id: str) -> routing_contract.RoundEnd | None:
        return round_end(view, events, department=department, session_id=session_id,
                         activation_id=activation_id, definitions=self._definitions)

    def item_end(self, view: RunProjection) -> routing_contract.ItemEnd | None:
        return item_end(view, self._definitions, self._accepted_outcomes(view))

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
