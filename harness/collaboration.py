"""Pure rules for department requests, result ownership, and work resumption."""

from __future__ import annotations

from .contracts import current_contract_hash
from .models import RunProjection
from .definitions import DEFINITIONS


# ---------------------------------------------------------------------------
# 部门按关注的成果开始一轮工作（循环结构第 2 节、ADR-0039）
#
# 每个部门在组织定义里写明关注的成果；这里只有一条通用规则：关注的成果有了新东西、
# 部门在等待工作时，它开始一轮工作。关注关系来自定义，代码里不按部门写死。
# 「有新东西」按成果的种类分别判断，判断的是成果本身与它上一次被处理到的版本，
# 不记录额外的状态：项目推算进度时读的是同一批成果。


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


def _has_new_user_input(projection: RunProjection) -> bool:
    """用户的输入：还有没被产品处理的输入。"""
    return projection.input_version > projection.processed_input_version


def _has_new_guidance(projection: RunProjection, department: str) -> bool:
    """发给这个部门的指导：还没有进入它的一轮工作的。

    指导是部门关注的成果，控制核心让它以这段指导开始一轮工作（循环结构第 6 节、ADR-0039）；
    它进入这一轮的模型输入以后（assembly.PENDING_GUIDANCE 的两种状态由那一轮送出），这一轮就是
    它的处理，不再算新的工作。一轮正常结束时主机为它写已回答事件（部门指导设计说明第 3 节，
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


def _has_new_product_spec(projection: RunProjection, department: str) -> bool:
    """PRD 的新版本，或者产品决定改了有效合同。

    工程关注的是 PRD 与它最近一次成果依据的版本不同（还没有成果时为真）；PRD 没有新版本时，
    它最近一份交付依据的合同不是当前有效合同也算新工作：产品决定只重算合同、不产生新的 PRD
    版本，过期的交付要按新合同重新交付（部门指导设计说明第 2.1 节第 2 点、工单 #1079）。
    质检关注的是「PRD 被接纳」：当前有效合同与质检上一次工作的依据不同，
    并且还没有交付要核验（有交付时质检核验交付，预测性探索在交付到达以前做，
    循环结构第 3.1 节）。
    """
    if projection.product_spec is None:
        return False
    contract = current_contract_hash(projection)
    if department == "quality":
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
    """新的交付：最近一份交付还没有质检的结论。"""
    delivery = latest_delivery(projection)
    if delivery is None:
        return False
    return not any(review.delivery_spec_hash == delivery.content_hash for review in projection.reviews)


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
    "user_input": lambda projection, department: _has_new_user_input(projection),
    "guidance": _has_new_guidance,
    "product_spec": _has_new_product_spec,
    "defect_record": lambda projection, department: _has_new_defect_record(projection),
    "delivery": lambda projection, department: _has_new_delivery(projection),
    "structure": lambda projection, department: _has_new_structure(projection),
    "baseline_review": lambda projection, department: has_new_baseline_review(projection),
}


def watched_new_work(projection: RunProjection, department: str) -> list[str]:
    """部门关注的成果里，现在有新东西的那些（按定义的顺序）。"""
    return [kind for kind in DEFINITIONS.watched_outputs(department)
            if _WATCHED_CHECKS[kind](projection, department)]


def has_new_work(projection: RunProjection, department: str) -> bool:
    """部门现在有没有新的工作：关注的成果有了新东西。"""
    return bool(watched_new_work(projection, department))


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


def next_department(projection: RunProjection, waiting: set[str] | None = None) -> str | None:
    """下一个开始一轮工作的部门：先看还没回答的询问，再按定义里的部门顺序取第一个
    在等待且有新的工作的。

    一个部门同一时刻最多一轮工作（工单 #556）：这里一次只选一个部门。
    waiting 给出在等待的部门（进程中断以后会话是新开的，投影里那条「工作中」的记录不再算数）；
    没有给出时按投影里的会话记录判断。
    """
    asking = pending_ask_department(projection)
    if asking is not None and _free(projection, waiting, asking):
        return asking
    for department in DEFINITIONS.departments:
        if _free(projection, waiting, department) and has_new_work(projection, department):
            return department
    return None


def ready_departments(projection: RunProjection, waiting: set[str] | None = None) -> list[str]:
    """现在可以开始一轮工作的部门（按定义顺序），各自一个会话同时运行（工单 #557）。

    关注的成果有了新版本、又在等待工作的部门都列出来：控制核心让它们同时开始，
    一个部门同一时刻最多一轮工作（循环结构第 3.2 节第 6 条）。

    指导与其他关注的成果一样：有待处理指导、又在等待工作的部门以这段指导开始一轮完整的
    工作（循环结构第 6 节，工单 #560），不为它另设一种只回应指导的轮次。
    还没回答的询问是另一类：提问方的会话要继续，在它自己的会话里跑。
    """
    ready: list[str] = []

    def take(department: str) -> None:
        if department not in ready:
            ready.append(department)

    asking = pending_ask_department(projection)
    if asking is not None and _free(projection, waiting, asking):
        take(asking)
    for department in DEFINITIONS.departments:
        if _free(projection, waiting, department) and has_new_work(projection, department):
            take(department)
    return ready
