"""Pure rules for department requests, result ownership, and work resumption."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .contracts import current_contract_hash
from .models import (
    DEPARTMENTS, TERMINAL_STATUSES, Event,
    EventType, RunProjection, hash_bytes, json_dumps,
)
from .definitions import DEFINITIONS
from .tools import proposal_kind, proposal_kinds


# 写入与检查的工具按定义中的动作类别；inspect 请求只认读取整个文件与列出文件这两种读取的结果
_MUTATIONS = frozenset(name for name, tool in DEFINITIONS.tools.items() if tool.action == "write")
_READS = frozenset({"read_file", "list_files"})
_CHECKS = frozenset(name for name, tool in DEFINITIONS.tools.items() if tool.action == "check")
_CLAIMABLE_TOOLS = _MUTATIONS | _CHECKS
_ACCEPTED_RESULTS = {
    EventType.SPEC_ACCEPTED, EventType.PRODUCT_DECISION_ACCEPTED, EventType.DELIVERY_ACCEPTED,
}
_GUIDANCE_ACCEPTED = _ACCEPTED_RESULTS
_GUIDANCE_RESPONSE_STATUSES = {"explained", "completed", "declined", "needs_work"}

# 指导还没处理完的两种状态（判定待处理指导的口径）
PENDING_GUIDANCE = ("received", "in_input")


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
    """发给这个部门的指导：还有没处理完的。"""
    return any(item.department == department and item.status in PENDING_GUIDANCE
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
    """PRD 的新版本。

    工程关注的是 PRD 与它最近一次成果依据的版本不同（还没有成果时为真）。
    质检关注的是「PRD 被接纳」：当前有效合同与质检上一次工作的依据不同，
    并且还没有交付要核验（有交付时质检核验交付，预测性探索在交付到达以前做，
    循环结构第 3.1 节）。
    """
    if projection.product_spec is None:
        return False
    if department == "quality":
        contract = current_contract_hash(projection)
        if contract is None:
            return False
        if projection.department_bases.get(department) == contract:
            return False
        return not _has_new_delivery(projection)
    basis = _latest_engineering_basis(projection)
    if basis is None:
        return True
    return basis != projection.product_spec.content_hash


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


def allowed_proposal_kinds(projection: RunProjection, department: str) -> set[str]:
    if projection.status in TERMINAL_STATUSES or department not in DEPARTMENTS:
        return set()
    has_guidance = _has_pending_guidance(projection, department)
    # 部门这一轮正在工作：它主线会话的记录是「工作中」，或它在回答一个询问
    if is_working(projection, department) or has_new_work(projection, department):
        # 本部门在这一轮工作：可提交的种类按定义给出（工单 #134）；普通事项与建档事项的清单不同
        allowed = proposal_kinds(department, projection.kind) - {"department_guidance_response"}
        if has_guidance:
            allowed.add("department_guidance_response")
        if projection.input_version > projection.processed_input_version:
            # 用户输入还没有被产品处理：只有产品能提交正式成果，其它部门只能回应指导（工单 #556）
            return allowed - {"product_decision"} if department == "product" else (
                allowed & {"department_guidance_response"})
        return allowed
    return set()


def tool_error(projection: RunProjection, department: str, name: str,
               args: dict[str, Any]) -> str | None:
    kind = proposal_kind(name)
    if kind is not None and kind not in allowed_proposal_kinds(projection, department):
        return "This proposal is not permitted in the current department work."
    return None


def guidance_response_errors(proposal: dict[str, Any], projection: RunProjection, department: str,
                             events: list[Event], *, snapshot_hash: str) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not isinstance(proposal.get("text"), str) or not proposal["text"].strip():
        errors.append(_error("text", "a response explanation is required"))
    status = proposal.get("status")
    if status not in _GUIDANCE_RESPONSE_STATUSES:
        errors.append(_error("status", "status must be explained, completed, declined, or needs_work"))
    references = proposal.get("result_event_ids")
    if not isinstance(references, list) or any(not isinstance(item, str) or not item for item in references):
        return errors + [_error("result_event_ids", "result_event_ids must be a list of event IDs")]
    if len(references) != len(set(references)):
        errors.append(_error("result_event_ids", "result event IDs must be unique"))
    guidance = next((item for item in projection.department_guidance
                     if item.id == proposal.get("guidance_id")), None)
    claimable_ids = {
        event.event_id
        for event in guidance_claimable_results(
            projection, department, events, snapshot_hash, guidance=guidance,
        )
    } if guidance is not None else set()
    if status == "completed":
        for reference in references:
            if reference not in claimable_ids:
                errors.append(_error(
                    "result_event_ids",
                    f"{reference} is not a result of this guidance's adopted work",
                ))
        if not claimable_ids:
            errors.append(_error(
                "result_event_ids",
                "completed requires a current host result produced after this guidance was adopted",
            ))
        return errors
    indexed = {event.event_id: event for event in events}
    owned = lambda item: _guidance_owned(item, projection, department)
    for reference in references:
        event = indexed.get(reference)
        if event is None or not owned(event):
            errors.append(_error("result_event_ids", f"{reference} is not a result of this department's current work"))
            continue
        if event.type == EventType.PROPOSAL_REJECTED:
            errors.append(_error("result_event_ids", f"{reference} is not an accepted result allowed by this guidance"))
    return errors


def guidance_claimable_results(projection: RunProjection, department: str, events: list[Event],
                               snapshot_hash: str, *, guidance: Any | None = None) -> list[Event]:
    items = [guidance] if guidance is not None else [
        item for item in projection.department_guidance
        if item.department == department and item.status in {"received", "in_input"}
    ]
    consumed = _consumed_guidance_result_ids(events, projection.run_id)
    found: list[Event] = []
    seen: set[str] = set()
    for item in items:
        if item is None:
            continue
        after_version = _event_version(events, item.created_event_id)
        if after_version is None:
            continue
        activation_ids: set[str] = set()
        current = projection.last_activations.get(department)
        if current:
            activation_ids.add(current)
        if item.applied_activation_id:
            activation_ids.add(item.applied_activation_id)
        activation_ids.update(_applied_activation_ids(item.id, projection, events))
        for event in _claimable_results_for_activations(
                projection, department, events, snapshot_hash, activation_ids):
            if event.stream_version <= after_version or event.event_id in consumed or event.event_id in seen:
                continue
            found.append(event)
            seen.add(event.event_id)
    return found


def guidance_bound_result_ids(proposal: dict[str, Any], projection: RunProjection, department: str,
                              events: list[Event], *, snapshot_hash: str, guidance: Any) -> list[str]:
    provided = [item for item in proposal.get("result_event_ids", []) if isinstance(item, str) and item]
    if proposal.get("status") != "completed":
        return list(dict.fromkeys(provided))
    return [
        event.event_id
        for event in guidance_claimable_results(
            projection, department, events, snapshot_hash, guidance=guidance,
        )
    ]


def guidance_result_summaries(projection: RunProjection, department: str, events: list[Event],
                              snapshot_hash: str) -> list[dict[str, Any]]:
    return [
        {
            "event_id": event.event_id,
            "type": event.type,
            "department": event.department,
            "name": event.payload.get("name"),
            "ok": event.payload.get("ok"),
            "content_hash": event.payload.get("content_hash"),
            "activation_id": event.payload.get("activation_id"),
        }
        for event in guidance_claimable_results(projection, department, events, snapshot_hash)
    ]


def _host_tool_result(event: Event, events: list[Event], *, owned: Callable[[Event], bool],
                      after_version: int) -> dict[str, Any] | None:
    payload = event.payload
    if not owned(event) or not all(payload.get(key) is not None for key in ("id", "name", "step_id", "activation_id")):
        return None
    started = [item for item in events if item.type == EventType.TOOL_STARTED
               and after_version < item.stream_version < event.stream_version and owned(item)
               and all(item.payload.get(key) == payload.get(key) for key in ("id", "name", "activation_id", "step_id"))]
    if len(started) != 1:
        return None
    item = payload.get("input_item")
    if not isinstance(item, dict) or item.get("type") != "function_call_output" or item.get("call_id") != payload["id"]:
        return None
    try:
        result = json.loads(item["output"])
    except (KeyError, TypeError, ValueError):
        return None
    if not isinstance(result, dict) or not isinstance(result.get("ok"), bool) or result["ok"] != payload.get("ok"):
        return None
    output_ref = payload.get("output_ref")
    if result.get("output") is not None:
        if not isinstance(output_ref, dict) or output_ref.get("content_hash") != hash_bytes(json_dumps(result["output"]).encode("utf-8")):
            return None
    return result


def _usable_tool_result(event: Event, result: dict[str, Any], projection: RunProjection,
                        snapshot_hash: str) -> bool:
    if not result["ok"]:
        return False
    if event.payload.get("name") not in _CHECKS:
        return event.payload.get("name") in _READS | _MUTATIONS
    output = result.get("output")
    if not isinstance(output, dict):
        return False
    return (output.get("executor") == "host" and output.get("tree_changed") is False
            and type(output.get("exit_code")) is int and output.get("snapshot_hash") == snapshot_hash
            and output.get("activation_id") == event.payload.get("activation_id")
            and output.get("effective_contract_hash") == _content_hash(projection.effective_contract)
            and output.get("delivery_spec_hash") == _content_hash(projection.delivery_spec)
            and output.get("product_spec_hash") == _content_hash(projection.product_spec))


def _guidance_owned(event: Event, projection: RunProjection, department: str) -> bool:
    return event.run_id == projection.run_id and event.department == department


def _event_version(events: list[Event], event_id: str | None) -> int | None:
    if not event_id:
        return None
    event = next((item for item in events if item.event_id == event_id), None)
    return None if event is None else event.stream_version


def _consumed_guidance_result_ids(events: list[Event], run_id: str) -> set[str]:
    consumed: set[str] = set()
    for event in events:
        if event.run_id != run_id or event.type != EventType.DEPARTMENT_GUIDANCE_RESPONDED:
            continue
        for item in event.payload.get("result_event_ids") or []:
            if isinstance(item, str) and item:
                consumed.add(item)
    return consumed


def _guidance_tool_current(event: Event, projection: RunProjection) -> bool:
    return event.payload.get("effective_contract_hash") == _content_hash(projection.effective_contract)


def _current_guidance_result(event: Event, projection: RunProjection, snapshot_hash: str) -> bool:
    payload = event.payload
    if event.type == EventType.SPEC_ACCEPTED:
        return projection.product_spec is not None and payload.get("content_hash") == projection.product_spec.content_hash
    if event.type == EventType.PRODUCT_DECISION_ACCEPTED:
        return any(item.content_hash == payload.get("content_hash") for item in projection.effective_decisions)
    if event.type == EventType.DELIVERY_ACCEPTED:
        delivery = projection.delivery_spec
        return bool(delivery and delivery.status == "active"
                    and payload.get("content_hash") == delivery.content_hash
                    and delivery.code_tree_digest == snapshot_hash
                    and delivery.effective_contract_hash == _content_hash(projection.effective_contract))


def _applied_activation_ids(guidance_id: str, projection: RunProjection, events: list[Event]) -> set[str]:
    return {
        str(event.payload.get("activation_id"))
        for event in events
        if event.type == EventType.DEPARTMENT_GUIDANCE_APPLIED and event.run_id == projection.run_id
        and guidance_id in event.payload.get("guidance_ids", []) and event.payload.get("activation_id")
    }


def _claimable_results_for_activations(projection: RunProjection, department: str, events: list[Event],
                                       snapshot_hash: str, activation_ids: set[str]) -> list[Event]:
    activation_ids = {item for item in activation_ids if item}
    starts = [event for event in events
              if event.type == EventType.DEPARTMENT_ACTIVATED and event.run_id == projection.run_id
              and event.department == department and event.payload.get("activation_id") in activation_ids]
    if not starts:
        return []
    windows: list[tuple[Event, int | None]] = []
    for start in starts:
        nxt = next((event for event in events
                    if event.type == EventType.DEPARTMENT_ACTIVATED and event.run_id == projection.run_id
                    and event.department == department and event.stream_version > start.stream_version), None)
        windows.append((start, None if nxt is None else nxt.stream_version))
    owned = lambda item: _guidance_owned(item, projection, department)
    found: list[Event] = []
    seen: set[str] = set()
    for event in events:
        if not owned(event) or event.event_id in seen:
            continue
        start = next((item for item, end in windows
                      if item.stream_version < event.stream_version
                      and (end is None or event.stream_version < end)), None)
        if start is None:
            continue
        if event.type == EventType.TOOL_CALLED:
            if (event.payload.get("activation_id") != start.payload.get("activation_id")
                    or event.payload.get("name") not in _CLAIMABLE_TOOLS):
                continue
            result = _host_tool_result(event, events, owned=owned, after_version=start.stream_version)
            if result is None or not result["ok"]:
                continue
            if event.payload.get("name") in _MUTATIONS and not _guidance_tool_current(event, projection):
                continue
            if event.payload.get("name") in _CHECKS and not _usable_tool_result(event, result, projection, snapshot_hash):
                continue
            found.append(event)
            seen.add(event.event_id)
        elif event.type in _GUIDANCE_ACCEPTED and _current_guidance_result(event, projection, snapshot_hash):
            found.append(event)
            seen.add(event.event_id)
    return found


def _has_pending_guidance(projection: RunProjection, department: str) -> bool:
    return any(item.department == department and item.status in {"received", "in_input"}
               for item in projection.department_guidance)


def _content_hash(value: Any) -> str | None:
    return None if value is None else value.content_hash


def _error(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}
