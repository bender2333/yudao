"""压缩以后保留失败的尝试：主机从事件生成失败清单。

依据 docs/design/context-assembly.md「压缩以后保留失败的尝试」、R4 与「装入顺序与截断」，
docs/design/semantic-system.md「压缩与轨迹节录」（工单 #1405）。

这一段是事件上的纯函数：同样的事件与同样的两个上限得到逐字节相同的一段。它只读事件，不读时间、
随机数、文件与网络，也不交给模型整理——整理请求由角色自己写，失败的经过在摘要里最容易被省掉。
压缩生效以后这一段接在检查点的摘要之后；没有压缩过的会话不生成它（失败原文还在历史里，R4 也不折叠它们）。

收哪些失败（判据都在事件上，确定）：

1. 失败的工具结果（与 R4 同一种，结果里 `ok` 为假）：被拒绝的提案与工具许可的拒绝都写在这里，带拒绝原因；
2. 没有通过的检查回执（`run_check` 的结果状态不是通过）。

设计说明里的第 4 类「换用方法的尝试」现在没有来源（语义系统的尝试整理还没有实现），随尝试整理接入。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from .models import EventType, canonical_hash, estimate_tokens, json_dumps

# 这一段在历史里的样子：[failure_list] 加一行 JSON，与检查点摘要（[department_memory]）同一写法
FAILURE_LIST = "failure_list"
# 后来做成的失败在清单里的标记，以及超出上限时合并成的一行（设计说明的两句话）
RESOLVED = "后来已解决"
MERGED_RESOLVED = "另有 {count} 条失败后来已解决，可以查询"
MERGED_EARLIER = "另有 {count} 条更早的失败，可以查询"

# 失败的工具结果的三种事件：调用与它的结果、被跳过的调用、中断恢复时的核实记录
_TOOL_RESULT_TYPES = frozenset({
    EventType.TOOL_CALLED, EventType.TOOL_SKIPPED, EventType.ACTION_VERIFIED,
})
# 提案被接纳的事件种类：它们载荷里的 kind 就是提案种类，「同一种提案后来被接纳」按它判
_ACCEPTED_TYPES = frozenset({
    EventType.SPEC_ACCEPTED, EventType.DELIVERY_ACCEPTED, EventType.QA_SUBMITTED,
    EventType.CONTRACT_ACCEPTED, EventType.STRUCTURE_ACCEPTED,
    EventType.BASELINE_REVIEW_ACCEPTED, EventType.ARTIFACT_ACCEPTED,
})
_CHECK_TOOL = "run_check"


@dataclass(frozen=True)
class Failure:
    """一条失败：做了什么、怎么失败的（截到单条上限）、事件编号，与后来有没有做成。"""

    kind: str
    event_id: str
    did: str
    failure: str
    resolved: bool


@dataclass(frozen=True)
class FailureList:
    """压缩以后接在摘要之后的那一段：逐条列出的失败，加上合并掉的两类条数。"""

    failures: tuple[Failure, ...]
    merged_resolved: int
    merged_earlier: int
    item: dict[str, Any]

    @property
    def event_ids(self) -> tuple[str, ...]:
        # 这一段逐条列了哪些事件（合并成一行的事件不再逐条列出，按条数写明可以查询）
        return tuple(failure.event_id for failure in self.failures)


def failure_list(
    events: Iterable[Any],
    *,
    department: str,
    boundary_event_id: str | None,
    limit_tokens: int,
    entry_chars: int,
) -> FailureList | None:
    """这个角色在本事项里从开始到分界的全部失败；没有失败、或者还没有分界时返回 None。

    边界是这次压缩检查点覆盖到的最后一条历史记录：分界之后的失败留在近期回合里，这里不重复列。
    分界事件不在这份事件里时同样返回 None——宁可不列，也不把不该列的事件列一遍。
    """
    ordered = sorted(events, key=lambda event: event.position)
    boundary = None if boundary_event_id is None else _position_of(ordered, boundary_event_id)
    if boundary is None:
        return None
    failures = [
        failure for failure in (
            _failure(event, ordered, entry_chars=entry_chars)
            for event in ordered
            if event.department == department and event.position <= boundary
        ) if failure is not None
    ]
    if not failures:
        return None
    listed, merged_resolved, merged_earlier = _within(failures, limit_tokens)
    return FailureList(tuple(listed), merged_resolved, merged_earlier,
                       _render(listed, merged_resolved, merged_earlier))


def tool_result(event: Any) -> dict[str, Any] | None:
    """工具结果的三项（`ok`、`output`、`error`）：部门历史里的那一条就是事件的 `input_item`。"""
    item = (event.payload or {}).get("input_item")
    if not isinstance(item, dict) or not isinstance(item.get("output"), str):
        return None
    try:
        parsed = json.loads(item["output"])
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _within(failures: list[Failure], limit_tokens: int) -> tuple[list[Failure], int, int]:
    """超出清单上限时的合并顺序（设计说明）：先合并「后来已解决」的，再从最早的未解决失败开始合并。

    最新的未解决失败总留在清单里：它最可能被再犯，所以先留新的。
    """
    if _tokens(_render(failures, 0, 0)) <= limit_tokens:
        return failures, 0, 0
    resolved = sum(1 for failure in failures if failure.resolved)
    listed = failures
    if resolved:
        listed = [failure for failure in failures if not failure.resolved]
        if _tokens(_render(listed, resolved, 0)) <= limit_tokens:
            return listed, resolved, 0
    merged_earlier = 0
    while len(listed) > 1 and _tokens(_render(listed, resolved, merged_earlier)) > limit_tokens:
        listed = listed[1:]
        merged_earlier += 1
    return listed, resolved, merged_earlier


def _render(failures: list[Failure], merged_resolved: int, merged_earlier: int) -> dict[str, Any]:
    payload: dict[str, Any] = {"failures": [
        {"did": failure.did, "event_id": failure.event_id, "failure": failure.failure,
         "resolved": failure.resolved}
        for failure in failures
    ]}
    merged = [MERGED_RESOLVED.format(count=merged_resolved)] if merged_resolved else []
    if merged_earlier:
        merged.append(MERGED_EARLIER.format(count=merged_earlier))
    if merged:
        payload["merged"] = merged
    return {"role": "user", "content": f"[{FAILURE_LIST}]\n" + json_dumps(payload)}


def _tokens(item: dict[str, Any]) -> int:
    # 这一段占的用量：与请求里的其他条目同一套本地估算（序列化以后的 UTF-8 字节数除以 4）
    return estimate_tokens(json_dumps(item))


def _position_of(events: list[Any], event_id: str) -> int | None:
    for event in events:
        if event.event_id == event_id:
            return event.position
    return None


def _failure(event: Any, ordered: list[Any], *, entry_chars: int) -> Failure | None:
    payload = event.payload or {}
    if event.type in _TOOL_RESULT_TYPES:
        result = tool_result(event)
        if result is None:
            return None
        if result.get("ok") is False:
            return _entry(event, ordered, kind="tool", did=_tool_did(event),
                          failure=_result_text(result), entry_chars=entry_chars)
        receipt = _receipt(event, result)
        if receipt is not None and not _passed(receipt):
            return _entry(event, ordered, kind="check", did=f"检查 {_check_name(event, receipt)}",
                          failure=_check_text(receipt), entry_chars=entry_chars)
        return None
    if event.type == EventType.PROPOSAL_REJECTED:
        return _entry(event, ordered, kind="proposal", did=f"提案 {payload.get('kind') or '未命名'}",
                      failure=_rejection_text(payload), entry_chars=entry_chars)
    return None


def _entry(event: Any, ordered: list[Any], *, kind: str, did: str, failure: str,
           entry_chars: int) -> Failure:
    # 单条上限同时管「怎么失败的」与「做了什么」里的参数摘要：参数可能带整份文件内容，一样要截
    return Failure(kind=kind, event_id=event.event_id, did=_truncate(did, entry_chars),
                   failure=_truncate(failure, entry_chars),
                   resolved=_resolved(event, ordered, kind=kind))


def _tool_did(event: Any) -> str:
    # 做了什么：工具与参数摘要；参数取这次调用记下的取值，读不到时只写工具名
    payload = event.payload or {}
    name = str(payload.get("name") or "").strip() or "工具"
    args = payload.get("args")
    return name if args is None else f"{name} {json_dumps(args)}"


def _result_text(result: dict[str, Any]) -> str:
    # 怎么失败的：错误原文；没有错误文字时用输出本身（失败输出的开头，截到单条上限）
    error = result.get("error")
    if isinstance(error, str) and error.strip():
        return error
    output = result.get("output")
    if isinstance(output, str):
        return output
    return "" if output is None else json_dumps(output)


def _receipt(event: Any, result: dict[str, Any]) -> dict[str, Any] | None:
    # 检查回执：只有 run_check 的结果是检查回执，其余工具的输出不是
    if (event.payload or {}).get("name") != _CHECK_TOOL:
        return None
    output = result.get("output")
    if not isinstance(output, dict) or "exit_code" not in output:
        return None
    return output


def _check_name(event: Any, receipt: dict[str, Any]) -> str:
    name = receipt.get("name")
    if isinstance(name, str) and name.strip():
        return name
    args = (event.payload or {}).get("args")
    return str(args.get("name") or "") if isinstance(args, dict) else ""


def _passed(receipt: dict[str, Any]) -> bool:
    # 通过：退出码为 0，并且记录回执的树还是原快照（树变了的那次结果不算绑在这个快照上的通过）
    return receipt.get("exit_code") == 0 and not receipt.get("tree_changed")


def _check_text(receipt: dict[str, Any]) -> str:
    summary = receipt.get("summary")
    text = summary if isinstance(summary, str) else json_dumps(summary)
    return f"退出码 {receipt.get('exit_code')}：{text}".strip()


def _rejection_text(payload: dict[str, Any]) -> str:
    errors = payload.get("errors")
    if isinstance(errors, list):
        messages = [str(item.get("message")) for item in errors
                    if isinstance(item, dict) and item.get("message")]
        if messages:
            return "；".join(messages)
    return json_dumps(errors) if errors is not None else "被拒绝，没有给出原因"


def _truncate(text: str, chars: int) -> str:
    if chars < 1 or len(text) <= chars:
        return text
    return text[:chars]


def _resolved(event: Any, ordered: list[Any], *, kind: str) -> bool:
    later = [other for other in ordered if other.position > event.position]
    if kind == "proposal":
        proposal = (event.payload or {}).get("kind")
        return any(other.type in _ACCEPTED_TYPES and (other.payload or {}).get("kind") == proposal
                   for other in later)
    if kind == "check":
        receipt = _receipt(event, tool_result(event) or {})
        name = _check_name(event, receipt or {})
        snapshot = (receipt or {}).get("snapshot_hash")
        return any(_check_passed_later(other, name, snapshot) for other in later)
    return any(_call_succeeded_later(event, other) for other in later)


def _check_passed_later(other: Any, name: str, snapshot: Any) -> bool:
    # 同名的检查后来在较新的快照上通过
    if other.type != EventType.TOOL_CALLED or (other.payload or {}).get("name") != _CHECK_TOOL:
        return False
    result = tool_result(other)
    receipt = None if result is None else _receipt(other, result)
    if receipt is None or not _passed(receipt) or _check_name(other, receipt) != name:
        return False
    return snapshot is None or receipt.get("snapshot_hash") != snapshot


def _call_succeeded_later(event: Any, other: Any) -> bool:
    # 同一工具以同样的参数后来成功
    if other.type != EventType.TOOL_CALLED:
        return False
    if (other.payload or {}).get("name") != (event.payload or {}).get("name"):
        return False
    if canonical_hash((other.payload or {}).get("args")) != canonical_hash((event.payload or {}).get("args")):
        return False
    result = tool_result(other)
    return result is not None and result.get("ok") is True
