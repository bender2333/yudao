# 动作核实与恢复（工单 #17，恢复契约第 4 节）。动作的身份是（激活、步骤、模型给出的调用编号）三元组：
# tool_started 在工具许可允许以后、执行之前写入，tool_called/tool_skipped 在执行以后写入。根据这两类事件、
# 以及保存的模型响应中尚未得到处置的工具调用，把每个动作分成三类：未发送、已完成、结果未知。

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from .decisions import UNKNOWN_ACTION
from .definitions import DEFINITIONS
from .models import Event, EventType

# 动作的三类处置（恢复契约第 4 节）：completed 已有结果；unknown 已经发出但结果没有得到确认，必须核实或
# 交给用户；还有一类是没有发出任何事件的调用，由步骤驱动按保存的模型响应补执行，见 engine 的补执行。
ACTION_COMPLETED = "completed"
ACTION_UNKNOWN = "unknown"

def action_identity(event: Event) -> tuple[str, int | None, str]:
    # 动作的身份：激活、步骤与模型给出的调用编号。tool_started 与 tool_called 由同一次工具调用写入，
    # 三元组相同；不同步骤或不同激活的调用编号即使相同也不互相覆盖
    payload = event.payload or {}
    step_id = payload.get("step_id")
    return (str(payload.get("activation_id") or ""), step_id if isinstance(step_id, int) else None,
            str(payload.get("id") or event.event_id))

def _result_events(events: Iterable[Event]) -> dict[tuple[str, int | None, str], Event]:
    # 已经有结果的动作：tool_called、tool_skipped 与核实记录都表示这次工具调用已经得到处置
    results: dict[tuple[str, int | None, str], Event] = {}
    for event in events:
        if event.type in (EventType.TOOL_CALLED, EventType.TOOL_SKIPPED, EventType.ACTION_VERIFIED):
            results.setdefault(action_identity(event), event)
    return results

def classify_actions(events: Sequence[Event]) -> dict[tuple[str, int | None, str], dict[str, Any]]:
    # 按已经持久化的工具事件分类：有 tool_started 且没有结果或核实记录的事件是 unknown；有结果的是
    # completed。没有 tool_started 的调用需要保存的模型响应才知道，由步骤驱动补执行，不在这里分类
    actions: dict[tuple[str, int | None, str], dict[str, Any]] = {}
    results = _result_events(events)
    for event in events:
        if event.type != EventType.TOOL_STARTED:
            continue
        identity = action_identity(event)
        result = results.get(identity)
        actions[identity] = {
            "identity": identity,
            "status": ACTION_COMPLETED if result is not None else ACTION_UNKNOWN,
            "tool": _tool_name(event),
            "step_id": event.payload.get("step_id"),
            "activation_id": event.payload.get("activation_id"),
            "started_event": event,
            "result_event": result,
        }
    return actions

def resolved_by_decision(events: Sequence[Event], decisions: Iterable[Any]) -> set[tuple[str, int | None, str]]:
    # 已经被回答的「核实结果未知的动作」请求覆盖的动作：选择了重新执行的动作等待补执行，选择按当前状态
    # 继续的动作已经有了核实记录。两种情况都不再当作结果未知，因此不再重复发出请求
    answered: set[str] = set()
    for decision in decisions:
        if decision.kind == UNKNOWN_ACTION.name and decision.status == "answered":
            answered.add(str(decision.request.get("action_id")))
    if not answered:
        return set()
    return {identity for identity, info in classify_actions(events).items()
            if info["status"] == ACTION_UNKNOWN and identity[2] in answered}

def _tool_name(event: Event) -> str:
    return str((event.payload or {}).get("name") or "")

def _repeatable(tool_name: str) -> bool:
    # 结果未知时这个动作能否重新执行（恢复契约第 4 节）：由工具契约声明
    tool = DEFINITIONS.tools.get(tool_name)
    return bool(tool is not None and tool.repeatable)

def resolution_options(tool_name: str) -> list[dict[str, str]]:
    # 「核实结果未知的动作」给出的选项：「重新执行」只在契约声明可以重复的动作上提供，
    # 「按当前实际状态继续」与「停止事项」始终可选（应用层与接口层设计说明第 3.3 节）
    return [{"id": option.id, "label": option.label} for option in UNKNOWN_ACTION.options
            if option.id != "reexecute" or _repeatable(tool_name)]

def build_unknown_action_request(*, action_id: str, tool: str, action_kind: str, department: str,
                                 facts: Sequence[str]) -> dict[str, Any]:
    # 发一个「核实结果未知的动作」决定请求：只阻塞这个动作（blocks=action），不阻塞整个 run。
    # 决定请求的身份是 DECISION_REQUESTED 事件的编号，不由这里给出
    return {
        "kind": UNKNOWN_ACTION.name,
        "blocks": UNKNOWN_ACTION.blocks,
        "options": resolution_options(tool),
        "description": (f"动作 {action_id}（{tool}）已经发出，结果没有得到确认。"
                        "重新执行只在这个动作的契约声明可以重复时提供；"
                        "按当前实际状态继续表示接受已经发生的效果；选择停止事项则运行结束。"),
        "facts": list(facts),
        "department": department,
        "action_id": action_id,
        "tool": tool,
        "action_kind": action_kind,
        "repeatable": _repeatable(tool),
    }
