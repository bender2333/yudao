# 动作核实与恢复（工单 #17，恢复契约第 4 节）
from typing import Any
from .models import Event
from .decisions import Option, UNKNOWN_ACTION
from .definitions import DEFINITIONS


def classify_actions(events: list[Event]) -> dict[str, dict[str, Any]]:
    """
    分类所有动作的状态：
    - unsent: 意图已保存但未发出（有 tool_started 但无 tool_called）
    - completed: 已完成（有 tool_called）
    - unknown: 已发出但结果未知（有 tool_started 但无 tool_called，且动作不可重复）
    
    返回: {action_id: {"status": "unsent|completed|unknown", "tool": str, "started_event": Event, "called_event": Event|None}}
    """
    actions = {}
    
    # 收集所有 tool_started 和 tool_called 事件
    started = {}
    called = {}
    
    for event in events:
        if event.type == "tool_started":
            action_id = event.payload.get("action_id")
            if action_id:
                started[action_id] = event
        elif event.type == "tool_called":
            action_id = event.payload.get("action_id")
            if action_id:
                called[action_id] = event
    
    # 分类每个动作
    for action_id, started_event in started.items():
        tool_name = started_event.payload.get("tool")
        called_event = called.get(action_id)
        
        if called_event:
            # 有 tool_called，动作已完成
            actions[action_id] = {
                "status": "completed",
                "tool": tool_name,
                "started_event": started_event,
                "called_event": called_event
            }
        else:
            # 没有 tool_called，检查结果未知
            tool_def = DEFINITIONS.tools.get(tool_name)
            is_repeatable = tool_def.repeatable if tool_def else False
            
            if is_repeatable:
                # 可重复的动作，标记为 unsent（可以重新执行）
                actions[action_id] = {
                    "status": "unsent",
                    "tool": tool_name,
                    "started_event": started_event,
                    "called_event": None
                }
            else:
                # 不可重复的动作，标记为 unknown（需要用户决定）
                actions[action_id] = {
                    "status": "unknown",
                    "tool": tool_name,
                    "started_event": started_event,
                    "called_event": None
                }
    
    return actions


def blocking_action(actions: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """
    返回第一个阻塞的动作（status="unknown"），如果没有则返回 None
    """
    for action_id, info in actions.items():
        if info["status"] == "unknown":
            return {"action_id": action_id, **info}
    return None


def repeatable_action(tool_name: str) -> bool:
    """
    检查工具是否可重复执行
    """
    tool_def = DEFINITIONS.tools.get(tool_name)
    return tool_def.repeatable if tool_def else False


def build_unknown_action_request(
    decision_id: str,
    action_id: str,
    tool_name: str,
    run_id: str,
    version: int
) -> dict[str, Any]:
    """
    构建 unknown_action 决定请求的 payload
    
    选项根据工具的 repeatable 属性动态生成：
    - 如果 repeatable=true: 提供 reexecute, continue, stop
    - 如果 repeatable=false: 只提供 continue, stop
    """
    tool_def = DEFINITIONS.tools.get(tool_name)
    is_repeatable = tool_def.repeatable if tool_def else False
    
    options = []
    if is_repeatable:
        options.append({"id": "reexecute", "label": "重新执行"})
    options.append({"id": "continue", "label": "按当前实际状态继续"})
    options.append({"id": "stop", "label": "停止事项"})
    
    return {
        "decision_id": decision_id,
        "kind": "unknown_action",
        "blocks": "action",
        "status": "open",
        "run_id": run_id,
        "version": version,
        "request": {
            "action_id": action_id,
            "tool": tool_name,
            "options": options
        }
    }
