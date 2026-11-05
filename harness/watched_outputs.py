# 成果驱动的路由实现（应用层；工单 #825，骨架与应用设计说明「路由契约」、三部门的循环结构）。
#
# 调度住在这里：谁在等、谁能开工、一轮以什么结束、事项以什么结束。它由内核的 collaboration.py（S1d 之前列在内核清单里）
# 与流程编排的对应部分搬来，行为不变，事件序列基准不变。
#
# 它读运行流的投影（从事件日志折叠而来）与组织定义里写明的关注关系，不保存事件之外的状态，不读最小投影，
# 不写事件、不调模型、不核对边界、不执行工具（docs/design/skeleton-and-application.md「路由契约」）。换一种路由（任务池）时整体换掉这一份，
# 内核不改：名称写在组织定义的 routing 里，实现在模块加载时用 routing_contract.register 登记，启动时按名称接上。
#
# 每个部门在组织定义里写明关注的成果；这里只有一条通用规则：关注的成果有了新东西、部门在等待工作时，它开始一轮工作。
# 关注关系来自定义，代码里不按部门写死。「有新东西」按成果的种类分别判断，判断的是成果本身与它上一次被处理到的版本，
# 不记录额外的状态：项目推算进度时读的是同一批成果。

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import routing_contract
from .contracts import artifact_hash
from .definitions import DEFINITIONS
from .models import (OPEN_LOOP_STOP_REASON, PRD_REVISION_FIELDS, Event, EventType, RunProjection,
                     new_id)

# 组织定义 organization.json 的 routing 里写这个名称
ROUTING_NAME = "watched_outputs"

# 成果驱动的一份定义（routings.json 的那个条目，工单 #861）：部门、成果种类、提议方式、路由自己的上限与
# 结束原因都按名称写在那里，内容就是现有的定义文件，不搬动。内核只核对那份定义的结构，内容由下面的
# check_definition 自己校验。事项结束用的那个原因写在它的定义里，属于那份定义版本的封闭清单
ITEM_END_REASON = "no_new_work"
# 提议方式：提交类工具。这一轮记下了其中一次的调用，就是「这一轮交上了正式成果」这件事
_PROPOSAL_METHODS = frozenset(DEFINITIONS.routing_definition().proposal_methods)


def routing_departments(definitions: Any | None = None) -> tuple[str, ...]:
    """这个路由的部门清单：它自己的一份定义里写的（docs/design/skeleton-and-application.md「其他路由：骨架要满足的条件」）。

    一次询问只能问清单里的部门；清单随定义变，不在这里写死（工单 #1391）。
    """
    definition = DEFINITIONS if definitions is None else definitions
    declared = routing_contract.definition_of(definition, ROUTING_NAME)
    return () if declared is None else tuple(declared.departments)


def input_department(definitions: Any | None = None) -> str:
    """收用户输入的部门（工单 #1455）：定义里事项的来源写明的那个部门。

    不再看谁关注用户输入：关注用户输入是另一件事，留在关注关系里。部门的名称从定义取，代码里不写
    （工单 #1391）：新输入分派给它，发给它的指导也由它的处理算完。
    """
    definition = DEFINITIONS if definitions is None else definitions
    return definition.input_department()


def proposal_kinds_for(department: str, kind: str = "change", definitions: Any | None = None) -> set[str]:
    """部门在这种事项里能交的提案种类：按定义里的提案合同，部门名不写在代码里（工单 #1391）。

    提案合同给出了这个部门此刻能交的成果种类；谁能交要求（PRD）、谁能在回答询问时顺带修订要求，
    都按它判断，不按部门名判断。
    """
    definition = DEFINITIONS if definitions is None else definitions
    if department not in definition.departments:
        return set()
    contract = definition.proposal_contract(department, kind)
    return set(contract.get("kinds") or ())

# 一轮没有正常结束的两种状态：暂停与失败（取消、上限、运行时间用完都落在这两种里）。
# 正常结束包括事项随这一轮完成（done）：那一轮结束时状态还是 running（部门指导设计说明「处理结果与来源」）。
# 这两种不算正常结束，这一轮不写指导的已回答、也没有结束结果（工单 #1039、#825）：暂停以后继续的是同一轮，
# 它在继续以后正常结束时才算。
_NOT_A_NORMAL_ROUND_END = frozenset({"paused", "failed"})


# ---------------------------------------------------------------------------
# 谁能开工
# ---------------------------------------------------------------------------


def is_working(projection: RunProjection, department: str) -> bool:
    """部门这一轮正在工作：它主线会话的记录是「工作中」，或它在回答一个询问。

    询问分支是部门主线之外的另一条会话（工单 #473），分支里的部门也在工作。
    """
    session = projection.sessions.get(department)
    if session is not None and session.status == "active":
        return True
    ask = projection.active_ask
    return bool(ask and ask.get("recipient") == department)


def is_waiting(projection: RunProjection, department: str) -> bool:
    """部门在等待工作：它这一轮已经结束（或还没开始过）。"""
    return not is_working(projection, department)


def waiting_departments(statuses: Mapping[str, str | None],
                        definitions: Any | None = None) -> set[str]:
    """在等待工作的部门：这个进程里没有正在工作的会话的那些。

    会话状态是薄驱动的事实（它在进程里持有会话），判断归路由：进程中断以后会话是新开的，
    投影里那条「工作中」的记录不再算数（工单 #16 的恢复口径），这时还没有会话的部门同样在等待，
    它可以被重新激活。statuses 没有列出的部门按等待处理。部门清单按这份形态的定义取（工单 #1509）。
    """
    definition = DEFINITIONS if definitions is None else definitions
    return {department for department in definition.departments if statuses.get(department) != "active"}


def _has_new_user_input(projection: RunProjection) -> bool:
    """用户的输入：还有没被处理完的输入（按输入交上的成果被接纳才算处理完）。"""
    return projection.input_version > projection.processed_input_version


def _has_new_input(projection: RunProjection, department: str, definition: Any) -> bool:
    """接这个事项来源的部门还有没处理完的输入：事项开始时与新的输入到达时，先是它的一轮工作。

    哪个部门接取自定义（工单 #1455）：来源由事项的种类给出（建档或你的输入），不按关注用户输入判断。
    「处理完」只有一个说法：按输入交上的成果被接纳，processed_input_version 前进——与旧的行为相同。
    """
    if department != definition.source_department(definition.item_source(projection.kind)):
        return False
    return _has_new_user_input(projection)


def _has_new_guidance(projection: RunProjection, department: str) -> bool:
    """发给这个部门的指导：还没有进入它的一轮工作的。

    指导是部门关注的成果，控制核心让它以这段指导开始一轮工作（循环结构「指导」）；
    它进入这一轮的模型输入以后（assembly.PENDING_GUIDANCE 的两种状态由那一轮送出），这一轮就是
    它的处理，不再算新的工作。一轮正常结束时主机为它写已回答事件（部门指导设计说明「处理结果与来源」，
    工单 #1039）。没有这一个收窄，收到指导的部门在主机写已回答以前会一轮接一轮地重新开始。
    """
    return any(item.department == department and item.status == "received"
               for item in projection.department_guidance)


def latest_delivery(projection: RunProjection):
    """最近一份交付（被取代的也算）：缺陷记录与新交付都以它为准。"""
    if projection.delivery_specs:
        return projection.delivery_specs[-1]
    return projection.delivery_spec


def _latest_engineering_basis(projection: RunProjection) -> str | None:
    """工程最近一次成果所依据的 PRD 版本：普通事项的交付与建档的结构说明都算。"""
    delivery = latest_delivery(projection)
    if delivery is not None:
        return delivery.product_spec_hash
    structure = projection.structure
    if structure is not None:
        basis = structure.get("product_spec_hash")
        return basis if isinstance(basis, str) else None
    return None


def _has_new_product_spec(projection: RunProjection, department: str,
                          definitions: Any | None = None) -> bool:
    """PRD 的新版本，或者决定改了有效合同。

    交要求的部门关注的是 PRD 与它最近一次成果依据的版本不同（还没有成果时为真）；PRD 没有新版本时，
    它最近一份交付依据的合同不是当前有效合同也算新工作：一个决定只重算合同、不产生新的 PRD
    版本，过期的交付要按新合同重新交付（部门指导设计说明「放行怎么等」第 2 点、工单 #1079）。
    核验角色关注的是「PRD 被接纳」：当前有效合同与它上一次工作的依据不同，并且还没有交付要核验
    （有交付时它核验交付，预测性探索在交付到达以前做，循环结构「各部门在什么时候工作」）。谁核验谁取自定义里的
    核验声明，不按部门名判断（工单 #1391）；取哪一份定义由这份形态决定（工单 #1509）。
    """
    definition = DEFINITIONS if definitions is None else definitions
    if projection.product_spec is None:
        return False
    contract = artifact_hash(projection.effective_contract)
    if definition.is_verifier(department):
        if contract is None:
            return False
        if projection.department_bases.get(department) == contract:
            return False
        return not _has_new_delivery(projection)
    basis = _latest_engineering_basis(projection)
    if basis is None:
        return True
    if basis != projection.product_spec.content_hash:
        return True
    # 建档的结构说明与还没有成果的情形不变：只有交付记着它依据的合同
    delivery = latest_delivery(projection)
    if delivery is None or contract is None:
        return False
    return delivery.effective_contract_hash != contract


def _has_new_defect_record(projection: RunProjection) -> bool:
    """针对最新交付的缺陷记录：这份交付上质检记了缺陷记录。"""
    delivery = latest_delivery(projection)
    if delivery is None:
        return False
    return any(review.delivery_spec_hash == delivery.content_hash and review.verdict == "rework_engineering"
               for review in projection.reviews)


def _has_new_delivery(projection: RunProjection) -> bool:
    """新的交付：最近一份交付还没有质检的结论。

    质检无法核验的结论（cannot_verify）不算核验过（工单 #1179）：用户回答「重新核验」以后
    质检要以新的激活重新检查同一份交付，这一条决定它会不会被重新激活。
    """
    delivery = latest_delivery(projection)
    if delivery is None:
        return False
    return not any(review.delivery_spec_hash == delivery.content_hash
                   and review.verdict != "cannot_verify" for review in projection.reviews)


def _has_new_structure(projection: RunProjection) -> bool:
    """新的现有结构说明（建档）：工程提交了当前 PRD 的结构说明，最新的基线核验还没有覆盖它。"""
    structure = projection.structure
    spec = projection.product_spec
    if structure is None or spec is None:
        return False
    if structure.get("product_spec_hash") != spec.content_hash:
        # 结构说明不是当前 PRD 的：工程重新提交以后质检才继续
        return False
    review = projection.baseline_review
    if review is None:
        return True
    return review.get("product_spec_hash") != spec.content_hash


def has_new_baseline_review(projection: RunProjection) -> bool:
    """新的基线核验结论（建档）：质检要求产品修改，产品还没有修订 PRD。"""
    review = projection.baseline_review
    if review is None or review.get("verdict") != "rework_product":
        return False
    spec = projection.product_spec
    return spec is not None and review.get("product_spec_hash") == spec.content_hash


_WATCHED_CHECKS = {
    # user_input 不在这里：用户输入由接这个事项来源的部门开始，不再由关注它的部门开始（工单 #1455）
    "guidance": lambda projection, department, definitions: _has_new_guidance(projection, department),
    "product_spec": _has_new_product_spec,
    "defect_record": lambda projection, department, definitions: _has_new_defect_record(projection),
    "delivery": lambda projection, department, definitions: _has_new_delivery(projection),
    "structure": lambda projection, department, definitions: _has_new_structure(projection),
    "baseline_review": lambda projection, department, definitions: has_new_baseline_review(projection),
}


# 这份路由认得的关注项（工单 #1456：名称写错要在加载时拒绝）：触发一轮工作的那些，加上不再触发
# 一轮工作、但旧定义里还写着的那一个。工单 #1455 起 user_input 由接来源的部门开始一轮，不由关注它的
# 部门开始；旧定义没有写 sources 时仍靠这个名称解释两种来源，写进定义的文件要照旧加载
_RECOGNIZED_WATCHED = ("user_input", *_WATCHED_CHECKS)


def watched_new_work(projection: RunProjection, department: str,
                      definitions: Any | None = None) -> list[str]:
    """部门现在的新工作（按定义的顺序）：接来源的部门收到输入，或者关注的成果有了新东西。

    输入那一项记作 user_input，但它是按来源的接部门给的，不看谁关注用户输入（工单 #1455）。
    关注关系与核验声明都从这份形态的定义取（工单 #1509）：没有交时读进程加载的那一份。
    """
    definition = DEFINITIONS if definitions is None else definitions
    kinds = [kind for kind in definition.watched_outputs(department)
             if kind in _WATCHED_CHECKS and _WATCHED_CHECKS[kind](projection, department, definition)]
    if _has_new_input(projection, department, definition):
        kinds.insert(0, "user_input")
    return kinds


def has_new_work(projection: RunProjection, department: str,
                 definitions: Any | None = None) -> bool:
    """部门现在有没有新的工作：接它的输入，或者关注的成果有了新东西。"""
    return bool(watched_new_work(projection, department, definitions))


def pending_ask_department(projection: RunProjection) -> str | None:
    """还没回答的询问：提问方的那一轮要继续，回答在分支里。

    进程中断以后分支由提问方的会话继续（工单 #473 的恢复口径）。
    """
    for ask in projection.ask_stack:
        origin = ask.get("origin_session_id")
        for session in projection.sessions.values():
            if session.session_id == origin:
                return session.department
    return None


def _free(projection: RunProjection, waiting: set[str] | None, department: str) -> bool:
    """部门在等待工作：waiting 给出时按它判断，没有给出时按投影里的会话记录判断。"""
    return department in waiting if waiting is not None else is_waiting(projection, department)


def department_ready(projection: RunProjection, department: str, waiting: set[str] | None = None,
                     definitions: Any | None = None) -> bool:
    """这个部门现在可以开始一轮工作：在等待工作，并且有新的工作。

    同时运行（工单 #557）：准备激活的事务里由薄驱动重新问一次，别的会话在这期间做完了就开始。
    """
    if not _free(projection, waiting, department):
        return False
    return has_new_work(projection, department, definitions)


def next_department(projection: RunProjection, waiting: set[str] | None = None,
                    definitions: Any | None = None) -> str | None:
    """下一个开始一轮工作的部门：先看还没回答的询问，再按定义里的部门顺序取第一个
    在等待且有新的工作的。

    一个部门同一时刻最多一轮工作（工单 #556）：这里一次只选一个部门。
    waiting 给出在等待的部门（进程中断以后会话是新开的，投影里那条「工作中」的记录不再算数）；
    没有给出时按投影里的会话记录判断。部门清单按这份形态的定义取（工单 #1509）。
    """
    definition = DEFINITIONS if definitions is None else definitions
    asking = pending_ask_department(projection)
    if asking is not None and _free(projection, waiting, asking):
        return asking
    for department in definition.departments:
        if _free(projection, waiting, department) and has_new_work(projection, department, definition):
            return department
    return None


def ready_departments(projection: RunProjection, waiting: set[str] | None = None,
                      definitions: Any | None = None) -> list[str]:
    """现在可以开始一轮工作的部门（按定义顺序），各自一个会话同时运行（工单 #557）。

    有新的工作、又在等待的部门都列出来：控制核心让它们同时开始，
    一个部门同一时刻最多一轮工作（循环结构「同时运行的条件」）。

    指导与其他关注的成果一样：有待处理指导、又在等待工作的部门以这段指导开始一轮完整的
    工作（循环结构「指导」，工单 #560），不为它另设一种只回应指导的轮次。
    还没回答的询问是另一类：提问方的会话要继续，在它自己的会话里跑。部门清单按这份形态的定义取（工单 #1509）。
    """
    definition = DEFINITIONS if definitions is None else definitions
    ready: list[str] = []

    def take(department: str) -> None:
        if department not in ready:
            ready.append(department)

    asking = pending_ask_department(projection)
    if asking is not None and _free(projection, waiting, asking):
        take(asking)
    for department in definition.departments:
        if _free(projection, waiting, department) and has_new_work(projection, department, definition):
            take(department)
    return ready


# ---------------------------------------------------------------------------
# 一轮以什么结束、事项以什么结束
# ---------------------------------------------------------------------------


def _round_outcome(events: list[Event], department: str, session_id: str | None, activation_id: str) -> str:
    """这一轮怎么结束的：提交被接纳记 proposal_accepted，其余正常结束记 text_reply（载荷只有这两个取值）。

    判据是这一轮写下的事件：提交经写入口写入时看提交与拒绝的事件；提交还没有写入时（薄驱动拿到一轮结果
    以后先问路由这一轮以什么结束，再经写入口提交），看这一轮记下的提议方式 —— 提交类工具的调用。
    提交以后被拒绝的这一轮，部门还没有交下正式成果，按文字回答记。
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
              and (event.payload or {}).get("name") in _PROPOSAL_METHODS):
            submitted = True
    return "proposal_accepted" if submitted else "text_reply"


def round_end(projection: RunProjection, events: list[Event], *, department: str, session_id: str | None,
              activation_id: str) -> routing_contract.RoundEnd | None:
    """这一轮以什么结束：正常结束的一轮交出结果（提交被接纳，或是文字回答）；暂停与失败不算正常结束。

    成果驱动只认这两种正常结束（docs/design/skeleton-and-application.md「路由契约」：一轮以提交正式成果或回答用户结束）。
    """
    if projection.status in _NOT_A_NORMAL_ROUND_END:
        return None
    return routing_contract.RoundEnd(
        outcome=_round_outcome(events, department, session_id, activation_id))


def item_end(projection: RunProjection) -> routing_contract.ItemEnd | None:
    """事项以什么结束：没有部门可以开始一轮工作时，成果驱动的事项没有新的工作，运行以路由自己声明的
    结束原因结束（docs/design/skeleton-and-application.md「其他路由：骨架要满足的条件」：路由自己的结束原因写在它自己的一份定义里，工单 #861）。
    """
    return routing_contract.ItemEnd(stop_reason=ITEM_END_REASON, message="no department has new work")


def recorded_open_loop(events: list[Event]) -> bool:
    """事项创建事件里记下的开环标记（工单 #1394，形态与核验角色设计说明「定义的校验」第 4 条）。

    标记由薄驱动在创建事项时按冻结的定义算出并记下，路由与重放都读这条记录，不按定义重新算。
    旧事件没有这一项时读作不是开环：那时的定义只有默认的三部门，事项最后采纳的成果有核验角色核验。
    """
    for event in events:
        if event.type == EventType.RUN_CREATED:
            return bool((event.payload or {}).get("open_loop", False))
    return False


def completion_reason(projection: RunProjection,
                      events: list[Event]) -> routing_contract.CompletionReason | None:
    """事项完成时的结束原因：创建时记下的开环标记为真时是开环完成，其余按事项种类取（返回 None）。

    这一条判断归路由（docs/design/skeleton-and-application.md「路由契约」输出、docs/design/department-loop.md「询问的记录与查询」）：薄驱动进入完成状态时问一次，
    只把这里给的原因写进事实。没标开环的事项不给原因，薄驱动照旧按事项种类取。
    """
    if recorded_open_loop(events):
        return routing_contract.CompletionReason(stop_reason=OPEN_LOOP_STOP_REASON)
    return None


def work_reference(projection: RunProjection, department: str) -> Any:
    """这一轮工作的路由自己的工作引用（设计说明「路由契约」输出、docs/design/skeleton-and-application.md「其他路由：骨架要满足的条件」）：成果驱动不用它，为空。"""
    return None


# ---------------------------------------------------------------------------
# 询问分支（工单 #862）：询问的开始、回问、这一轮的上限、答没答出来
# ---------------------------------------------------------------------------

# 分支没能回答的三种原因（写进回答事件的 reason，也作为这次工具调用的错误交回提问方）：
# 一步也走不了、时间用完、跑完这一轮还是没交上回答
_STEP_LIMIT_REASON = "department reached the model step limit without submitting a proposal"
_TIME_LIMIT_REASON = "department reached the time limit without submitting an answer"
_BRANCH_FAILED_REASON = "branch failed to answer"


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

    询问的开始归路由：这个会话自己那次没结束的询问接着那一层，不新开一层（工单 #473 的嵌套询问）；
    新开一层时回复的部门要在这个路由自己的部门清单里、不是提问方自己，问题与背景至少给一份（工单 #554）。
    这一轮的上限取被问部门的声明量与提问方这一步剩下的量里小的那个；已经用掉的量由薄驱动扣，
    路由不读最小投影（docs/design/skeleton-and-application.md「路由契约」）。部门清单按这份形态的定义取（工单 #1509）。
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
        # 工程询问质检时问题与背景分两部分：facts 与 explanation 至少给一份（工单 #554）
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
        # 这一层询问已经答过：结果照原样交回提问方，不再跑一轮（重新启动以后接着同一次询问）
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
        # 这一轮工作的路由自己的工作引用指向这次询问（设计说明「路由契约」输出、docs/design/skeleton-and-application.md「其他路由：骨架要满足的条件」）
        work_ref={"ask": {"branch_session_id": branch_session_id, "requester": requester,
                          "recipient": recipient}},
    )


def ask_outcome(projection: RunProjection, *, branch: routing_contract.AskBranch,
                result: routing_contract.AskRoundResult,
                definitions: Any | None = None) -> routing_contract.AskOutcome:
    """分支这一轮以什么结束：把回答交回提问方，还是没能回答与原因。

    回答的内容、回答同时交上的成果由路由组装（docs/design/skeleton-and-application.md「裁决的分工：内核的通用检查与路由的收紧检查」）：能交要求的部门在回答一次询问时
    可以修订 PRD（循环结构「回答能做什么」），修订的提案参数随结果交给薄驱动，由它经写入口提交。谁能交要求
    按提案合同判断，不在代码里写部门名（工单 #1391）；提案合同从这份形态的定义取（工单 #1509）。
    没能回答的原因按这一轮的实际情形取：一步也走不了、时间用完、这一轮的说明或停止原因、跑完没交上回答。
    """
    if result.submission is None:
        if result.steps_left <= 0:
            reason = _STEP_LIMIT_REASON
        elif result.time_exhausted:
            reason = _TIME_LIMIT_REASON
        elif result.message:
            reason = result.message
        elif result.stop_reason:
            reason = result.stop_reason
        else:
            reason = _BRANCH_FAILED_REASON
        return routing_contract.AskOutcome(status="unable", session_id=branch.session_id, reason=reason)
    args = result.submission
    revises = None
    if ("product_spec" in proposal_kinds_for(branch.recipient, projection.kind, definitions)
            and any(args.get(field) is not None for field in PRD_REVISION_FIELDS)):
        revises = {**{key: value for key, value in args.items()
                      if key not in ("answer", "text") and value is not None},
                   "kind": "product_spec", "issuer": branch.recipient}
    return routing_contract.AskOutcome(
        status="answered",
        session_id=branch.session_id,
        answer=args.get("answer") or args.get("text") or args.get("facts") or "",
        facts=args.get("facts") or None,
        explanation=args.get("explanation") or None,
        revises=revises,
    )


def check_definition(definitions: Any) -> None:
    """校验成果驱动这份定义的内容（docs/design/skeleton-and-application.md「其他路由：骨架要满足的条件」）：内核只核对结构，内容归路由自己。

    部门、成果种类与提议方式都是按名称引用现有定义的，几种名称互相对得上；路由自己的结束原因不能与内核的
    停止原因同名，事项结束用的那一个要声明。不合格时抛出 InvalidRoutingDefinition，逐项写明是哪一项。
    """
    declared = routing_contract.definition_of(definitions, ROUTING_NAME)
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
        # 关注的成果（工单 #1456）：组织定义里的名称由这一份路由实现认。内核只认字符串，
        # 名称的含义归路由——写错的名称要在这里拒绝，不能等到运行到 has_new_work 才抛 KeyError。
        # user_input 认得但不再触发一轮工作（工单 #1455），旧定义里写着它，不能因此拒绝整份定义
        for index, name in enumerate(definitions.watched_outputs(department)):
            if name not in _RECOGNIZED_WATCHED:
                issues.append(f"departments[{department}].watched[{index}]：关注的成果 {name} 没有这一种")
    submitted = [definitions.tools[method].proposal for index, method in enumerate(declared.proposal_methods)
                 if method in definitions.tools and definitions.tools[method].proposal is not None]
    for index, method in enumerate(declared.proposal_methods):
        if method not in definitions.tools or definitions.tools[method].proposal is None:
            issues.append(f"proposal_methods[{index}]：工具 {method} 不是定义里的提交类工具")
    # 这份路由认得的成果种类：它的定义按名称引用 outcome_kinds.json 里的一组（工单 #1456）
    outcomes = definitions.outcomes_of(ROUTING_NAME)
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
    # 事项最后采纳的成果种类（工单 #1394）：开环的标记按它判断，所以它必须是这份路由认得的成果种类之一；
    # 没写这一项不算错：这样的路由不标开环，结束原因由它自己给
    if declared.final_outcome is not None and declared.final_outcome not in outcomes:
        issues.append(f"final_outcome：成果种类 {declared.final_outcome} 不是这份路由认得的成果种类")
    if issues:
        raise routing_contract.InvalidRoutingDefinition(ROUTING_NAME, issues)


class WatchedOutputs:
    # 成果驱动的路由（docs/design/skeleton-and-application.md「路由契约」）：默认路由，组织定义的 routing 写 watched_outputs。
    # 实现在应用层；薄驱动只按契约的三个问题调用它。
    # 部门、关注关系与核验声明按**这份形态自己的定义**取（工单 #1509）：组装处交给它这一份时就按这一份，
    # 没有交时读进程加载的那一份。一份形态一份实例（routing_contract.select 每次选择给一份副本），
    # 形态之间不共用，所以一份形态的部门清单不会盖掉另一份
    NAME = ROUTING_NAME
    CONTRACT_VERSION = routing_contract.CURRENT_VERSION

    def __init__(self, definitions: Any | None = None) -> None:
        self._definitions = definitions

    def use_definitions(self, definitions: Any) -> "WatchedOutputs":
        # 组装处的注入入口（契约第三版只增的可选方法，工单 #1509）：交出一份接上这一份定义的新实例。
        # 一份形态一份实例，登记表里的那一个与其他形态的实例都不受影响
        return WatchedOutputs(definitions)

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
                         activation_id=activation_id)

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


ROUTING = routing_contract.register(WatchedOutputs())
