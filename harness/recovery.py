# 动作核实与恢复（工单 #17、#18、#307，恢复契约第 1、4 节）。动作的身份是（激活、步骤、模型给出的调用编号）三元组：
# tool_started 在工具许可允许以后、执行之前写入，tool_called/tool_skipped 在执行以后写入。根据这两类事件、
# 以及保存的模型响应中尚未得到处置的工具调用，把每个动作分成三类：未发送、已完成、结果未知。
# 契约声明可以重复的结果未知动作自动重新执行一次：重新执行是同一个逻辑动作的新尝试，记一条 tool_started，
# 它的 auto_retry_of 写明它取代的那次 tool_started 的事件编号。这条链就是「同一个逻辑动作只自动重新执行一次」的依据，
# 计数取自事件日志，重启以后仍然成立。
# 恢复观察状态（工单 #18）由 run 的事实与未回答的决定请求得出，不读取时钟、不调用模型。

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .decisions import UNKNOWN_ACTION
from .definitions import DEFINITIONS
from .models import DecisionRequest, Event, EventType

# 动作的三类处置（恢复契约第 4 节）：completed 已有结果；unknown 已经发出但结果没有得到确认，必须核实或
# 交给用户；还有一类是没有发出任何事件的调用，由步骤驱动按保存的模型响应补执行，见 engine 的补执行。
ACTION_COMPLETED = "completed"
ACTION_UNKNOWN = "unknown"

# 恢复观察状态（工单 #18，v8 设计说明第 7.2 节）：运行中、中断、待核实、待恢复、已终止。
OBSERVATION_RUNNING = "running"
OBSERVATION_INTERRUPTED = "interrupted"
OBSERVATION_PENDING_VERIFICATION = "pending_verification"
OBSERVATION_WAITING_RESUME = "waiting_resume"
OBSERVATION_TERMINATED = "terminated"

# 运行级待恢复的决定种类（工单 #16、#18）：模型引用无法使用与定义版本不同，都要用户先回答再继续
RESUME_KINDS = frozenset({"model_unavailable", "definitions_changed"})

def action_identity(event: Event) -> tuple[str, int | None, str]:
    # 动作的身份：激活、步骤与模型给出的调用编号。tool_started 与 tool_called 由同一次工具调用写入，
    # 三元组相同；不同步骤或不同激活的调用编号即使相同也不互相覆盖
    payload = event.payload or {}
    step_id = payload.get("step_id")
    return (str(payload.get("activation_id") or ""), step_id if isinstance(step_id, int) else None,
            str(payload.get("id") or event.event_id))

def retry_chain_successors(events: Iterable[Event]) -> dict[str, Event]:
    # 自动重新执行的链（工单 #307）：重新执行的那一次尝试记一条 tool_started，auto_retry_of 写明它取代的
    # 上一次 tool_started 的事件编号。返回「被取代的那次事件编号 → 取代它的尝试」。
    successors: dict[str, Event] = {}
    for event in events:
        source = (event.payload or {}).get("auto_retry_of") if event.type == EventType.TOOL_STARTED else None
        if isinstance(source, str) and source:
            successors.setdefault(source, event)
    return successors

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
    successors = retry_chain_successors(events)
    results = _result_events(events)
    for event in events:
        if event.type != EventType.TOOL_STARTED:
            continue
        identity = action_identity(event)
        payload = event.payload or {}
        result = results.get(identity)
        actions[identity] = {
            "identity": identity,
            "status": ACTION_COMPLETED if result is not None else ACTION_UNKNOWN,
            "tool": _tool_name(event),
            "step_id": payload.get("step_id"),
            "activation_id": payload.get("activation_id"),
            "action_id": str(payload.get("id") or ""),
            # 这一次尝试取代的上一次尝试（自动重新执行时记被取代的 tool_started 事件编号，首次尝试为空）
            "auto_retry_of": payload.get("auto_retry_of"),
            # 这个逻辑动作还有没有自动重新执行的机会（一次的上限，工单 #307）：链尾那一次尝试带着
            # auto_retry_of，说明这个逻辑动作已经用掉机会；已被取代的那一次由新的尝试接手
            "auto_retry_available": event.event_id not in successors and not payload.get("auto_retry_of"),
            # 这一次尝试有没有被后来的尝试取代：被取代的那一次不再等待核实
            "superseded": event.event_id in successors,
            "started_event": event,
            "result_event": result,
        }
    return actions



def resolved_by_decision(events: Sequence[Event], decisions: Iterable[Any]) -> set[tuple[str, int | None, str]]:
    # 已经被回答的「核实结果未知的动作」请求覆盖的动作：只有选择「按当前实际状态继续」才算确认完毕。
    # 覆盖的范围包括这一次逻辑动作的全部尝试（按逻辑动作编号判断），因此不再重复发出请求
    accepted: set[str] = set()
    for decision in decisions:
        if (decision.kind == UNKNOWN_ACTION.name and decision.status == "answered"
                and (decision.answer or {}).get("option") == "continue"):
            accepted.add(str(decision.request.get("action_id")))
    if not accepted:
        return set()
    return {identity for identity, info in classify_actions(events).items()
            if info["status"] == ACTION_UNKNOWN and info["action_id"] in accepted}

def _tool_name(event: Event) -> str:
    return str((event.payload or {}).get("name") or "")

def action_repeatable(tool: str, args: Mapping[str, Any] | None = None, *,
                      registered_commands: Mapping[str, Any] | None = None) -> bool:
    # 一个动作能否重复执行（恢复契约第 4 节，工单 #242）：唯一的判断入口，后面三张工单共用。
    # 读取、搜索与检查由工具契约各自声明 repeatable；登记的本地命令取这个 run 中固定的登记里的声明
    # （登记时声明「可以重新执行」，缺省为否）；没有定义或没有声明的工具为否
    definition = DEFINITIONS.tools.get(tool)
    if definition is None:
        return False
    if definition.action == "command":
        name = (args or {}).get("name")
        if not isinstance(name, str):
            return False
        entry = (registered_commands or {}).get(name)
        return bool(entry is not None and entry.get("repeatable"))
    return definition.repeatable

def auto_retry_actions(events: Sequence[Event], decisions: Iterable[Any], *,
                       registered_commands: Mapping[str, Any] | None = None,
                       department: str | None = None) -> list[dict[str, Any]]:
    # 恢复契约第 4 节第 2 步（工单 #307）：要自动重新执行的结果未知动作，按事件日志的先后顺序给出。判据有四条：
    # - 这一次尝试的结果未知（有 tool_started、没有结果或核实记录），没有被后来的尝试取代，也没有被
    #   已经回答的「按当前实际状态继续」覆盖；
    # - 这个逻辑动作还没有用掉自动重新执行的一次机会（重新执行链上还没有带 auto_retry_of 的尝试）；
    # - 契约声明可以重复（读取、搜索、检查，以及登记时声明可以重新执行的命令），入口是 action_repeatable；
    # - 给出 department 时只取这个部门的动作。
    # 返回的是 classify_actions 的那一条，started_event 是这一次尝试的 tool_started 事件
    resolved = resolved_by_decision(events, decisions)
    return [info for identity, info in classify_actions(events).items()
            if info["status"] == ACTION_UNKNOWN and info["started_event"] is not None
            and not info["superseded"] and identity not in resolved and info["auto_retry_available"]
            and (department is None or info["started_event"].department == department)
            and action_repeatable(info["tool"], (info["started_event"].payload or {}).get("args"),
                                  registered_commands=registered_commands)]


def resolution_options(tool: str, args: Mapping[str, Any] | None = None, *,
                       registered_commands: Mapping[str, Any] | None = None) -> list[dict[str, str]]:
    # 「核实结果未知的动作」给出的选项：「重新执行」只在契约声明可以重复的动作上提供，
    # 「按当前实际状态继续」与「停止事项」始终可选（应用层与接口层设计说明第 3.3 节）
    repeatable = action_repeatable(tool, args, registered_commands=registered_commands)
    return [{"id": option.id, "label": option.label} for option in UNKNOWN_ACTION.options
            if option.id != "reexecute" or repeatable]


def build_unknown_action_request(*, action_id: str, tool: str, action_kind: str, department: str,
                                 facts: Sequence[str], args: Mapping[str, Any] | None = None,
                                 registered_commands: Mapping[str, Any] | None = None,
                                 repeat_attempted: bool = False) -> dict[str, Any]:
    # 发一个「核实结果未知的动作」决定请求：只阻塞这个动作（blocks=action），不阻塞整个 run。
    # 决定请求的身份是 DECISION_REQUESTED 事件的编号，不由这里给出。
    # repeat_attempted 说明这个逻辑动作已经自动重新执行过一次（恢复契约第 4 节第 3 步）：
    # 新的尝试结果仍然未知时，材料写明连续两次结果未知，提醒用户可能正是这个动作导致中断
    repeatable = action_repeatable(tool, args, registered_commands=registered_commands)
    description = (f"动作 {action_id}（{tool}）已经发出，结果没有得到确认。"
                   "重新执行只在这个动作的契约声明可以重复时提供；"
                   "按当前实际状态继续表示接受已经发生的效果；选择停止事项则运行结束。")
    if repeat_attempted:
        description += ("这个逻辑动作已经自动重新执行过一次，新的尝试结果仍然未知，"
                        "连续两次结果未知；中断可能是这个动作本身导致的。")
    return {
        "kind": UNKNOWN_ACTION.name,
        "blocks": UNKNOWN_ACTION.blocks,
        "options": resolution_options(tool, args, registered_commands=registered_commands),
        "description": description,
        "facts": list(facts),
        "department": department,
        "action_id": action_id,
        "tool": tool,
        "action_kind": action_kind,
        "repeatable": repeatable,
        "repeat_attempted": repeat_attempted,
    }


# ---------------------------------------------------------------------------
# 恢复观察状态（工单 #18）

def unresolved_unknown_actions(events: Sequence[Event],
                               decisions: Iterable[DecisionRequest]) -> dict[tuple[str, int | None, str], dict[str, Any]]:
    # 还没有得到处置的结果未知动作：有 tool_started，既没有结果、也不在已经被回答的核实请求覆盖范围内。
    # 已经被后来的尝试取代的那一次不再列入（工单 #307）：它由新的尝试替代，取代关系由 auto_retry_of 记在
    # 事件日志里；否则它在每一次重新执行以后都仍然「结果未知」，运行会一直停在待核实。
    # 已经发出、仍等待回答的核实请求由调用方从决定请求中读取
    resolved = resolved_by_decision(events, decisions)
    return {identity: info for identity, info in classify_actions(events).items()
            if info["status"] == ACTION_UNKNOWN and not info["superseded"] and identity not in resolved}

def open_decisions(decisions: Iterable[DecisionRequest], *, kind: str | None = None) -> list[DecisionRequest]:
    # 未回答的决定请求；给出种类时只取该种类
    return [decision for decision in decisions
            if decision.status == "open" and (kind is None or decision.kind == kind)]

def open_resume_decisions(decisions: Iterable[DecisionRequest]) -> list[DecisionRequest]:
    # 未回答、阻塞整个 run 的待恢复请求：模型引用无法使用或定义版本不同，回答以前 run 不推进
    return [decision for decision in decisions
            if decision.status == "open" and decision.blocks == "run" and decision.kind in RESUME_KINDS]

def _live_activation(events: Sequence[Event]) -> bool:
    # 这次过程里仍有一次激活没有结束：DEPARTMENT_ACTIVATED 开启，ACTIVATION_FINISHED 结束。
    # 有未结束的激活表示进程正在执行这个 run；没有表示进程在步骤之间退出（中断）
    open_activations: set[str] = set()
    for event in events:
        payload = event.payload or {}
        activation_id = payload.get("activation_id")
        if not activation_id:
            continue
        if event.type == EventType.DEPARTMENT_ACTIVATED:
            open_activations.add(str(activation_id))
        elif event.type == EventType.ACTIVATION_FINISHED:
            open_activations.discard(str(activation_id))
    return bool(open_activations)

def observation_state(events: Sequence[Event], decisions: Iterable[DecisionRequest], *,
                      terminal: bool) -> str:
    # 一个 run 的恢复观察状态（v8 设计说明第 7.2 节）：已终止、待恢复、待核实、运行中、中断。
    # 判据只取持久事件、决定请求与投影中的终态，不读时钟，不调用模型：
    # - 已终止：run 已经结束（完成、暂停、失败）；由调用方从投影的 phase 给出；
    # - 待恢复：有未回答、阻塞整个 run 的待恢复请求（模型引用无法使用或定义版本不同）；
    # - 待核实：有结果未知的动作（有 tool_started、没有结果或核实记录）；
    # - 运行中：进程正在执行（有一次没有结束的激活）；
    # - 中断：其余情况，进程在步骤之间退出，等待启动时自动继续
    decision_list = list(decisions)
    if terminal:
        return OBSERVATION_TERMINATED
    if open_resume_decisions(decision_list):
        return OBSERVATION_WAITING_RESUME
    if unresolved_unknown_actions(events, decision_list):
        return OBSERVATION_PENDING_VERIFICATION
    if _live_activation(events):
        return OBSERVATION_RUNNING
    return OBSERVATION_INTERRUPTED
