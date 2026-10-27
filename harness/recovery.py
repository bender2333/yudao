# 动作核实与恢复（工单 #17、#18、#307，恢复契约第 1、4 节）。动作的身份是（激活、步骤、模型给出的调用编号）三元组：
# tool_started 在工具许可允许以后、执行之前写入，tool_called/tool_skipped 在执行以后写入。根据这两类事件、
# 以及保存的模型响应中尚未得到处置的工具调用，把每个动作分成三类：未发送、已完成、结果未知。
# 恢复观察状态（工单 #18）由 run 的事实与未回答的决定请求得出，不读取时钟、不调用模型。
# 启动时继续一个未结束的 run 也在这一层（`RunRecovery`，S4c 工单 #863 从薄驱动搬来）：核对定义版本、
# 核实结果未知的动作、取得执行权。

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from .actions import FactsQuery
from .decisions import DEFINITIONS_CHANGED, blocks_run
from .definitions import DEFINITIONS
from .event_store import run_stream
from .models import TERMINAL_STATUSES, ArtifactRef, DecisionRequest, Event, EventType, hash_bytes, json_dumps
from .streams import RUN_EVENT_VERSION
from .write_path import NewEvent, Transaction

# 动作的三类处置（恢复契约第 4 节）：completed 已有结果；unknown 已经发出但结果没有得到确认，必须核实或
# 交给用户；还有一类是没有发出任何事件的调用，由步骤驱动按保存的模型响应补执行，见 engine 的补执行。
ACTION_COMPLETED = "completed"
ACTION_UNKNOWN = "unknown"

# 恢复观察状态（工单 #18，v8 设计说明第 7.2 节）：运行中、中断、待恢复，以及四种结束方式。
# 结束方式分开是工单 #747 的口径：正常完成并被采纳的事项不是「已终止」，被取消的事项也不是。
OBSERVATION_RUNNING = "running"
OBSERVATION_INTERRUPTED = "interrupted"
OBSERVATION_WAITING_RESUME = "waiting_resume"
OBSERVATION_COMPLETED = "completed"
OBSERVATION_PAUSED = "paused"
OBSERVATION_CANCELLED = "cancelled"
OBSERVATION_STOPPED = "stopped"

# 运行级待恢复的决定种类（工单 #16、#18）：模型引用无法使用与定义版本不同，都要用户先回答再继续
RESUME_KINDS = frozenset({"model_unavailable", "definitions_changed"})

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
        payload = event.payload or {}
        result = results.get(identity)
        actions[identity] = {
            "identity": identity,
            "status": ACTION_COMPLETED if result is not None else ACTION_UNKNOWN,
            "tool": _tool_name(event),
            "step_id": payload.get("step_id"),
            "activation_id": payload.get("activation_id"),
            "action_id": str(payload.get("id") or ""),

            "started_event": event,
            "result_event": result,
        }
    return actions



def _tool_name(event: Event) -> str:
    return str((event.payload or {}).get("name") or "")


FILE_ACTION_TOOLS = ("write_file", "edit_range", "delete_file", "move_file")


def _snapshot_entries(snapshot: Mapping[str, Any] | None) -> dict[str, str] | None:
    # 动作前后的公开树快照（工单 #308）：路径到内容哈希的对照。快照缺字段时按不可比对处理，调用方判 unclear
    if not isinstance(snapshot, Mapping):
        return None
    entries = snapshot.get("entries")
    if not isinstance(entries, list):
        return None
    result: dict[str, str] = {}
    for item in entries:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            return None
        path, content_hash = item
        if not isinstance(path, str) or not isinstance(content_hash, str):
            return None
        result[path] = content_hash
    return result


def verify_file_action(tool: str, args: Mapping[str, Any] | None, *,
                       before_snapshot: Mapping[str, Any] | None,
                       current_entries: Sequence[Sequence[str]]) -> dict[str, Any]:
    # 文件工具的结果核实（工单 #308，恢复契约第 4 节第 1 步）：把动作前快照、动作参数与当前公开树对比。
    # 三种处置：没有变化返回 not_happened；只有目标路径变成目标内容返回 completed；其余返回 unclear。
    # 3.2C 的远程动作后来按同样的方式使用这个函数，不在各处重写。调用方在恢复的事务之内使用，不在这里读写事件
    before = _snapshot_entries(before_snapshot)
    current: dict[str, str] = {}
    for item in current_entries:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            return {"verdict": "unclear", "detail": {"reason": "当前公开树的形状无法解析"}}
        path, content_hash = item
        if not isinstance(path, str) or not isinstance(content_hash, str):
            return {"verdict": "unclear", "detail": {"reason": "当前公开树的形状无法解析"}}
        current[path] = content_hash
    if before is None:
        return {"verdict": "unclear", "detail": {"reason": "动作前的快照缺失或形状不对"}}
    arguments = args if isinstance(args, Mapping) else {}
    if tool == "write_file":
        return _verify_write(arguments, before=before, current=current)
    if tool == "edit_range":
        return _verify_edit(arguments, before=before, current=current)
    if tool == "delete_file":
        return _verify_delete(arguments, before=before, current=current)
    if tool == "move_file":
        return _verify_move(arguments, before=before, current=current)
    return {"verdict": "unclear", "detail": {"reason": f"不是文件工具：{tool}"}}


def file_action_comparisons(events: Sequence[Event], *, artifacts: Any, run_id: str,
                            current_entries: Sequence[Sequence[str]]) -> dict[str, dict[str, Any]]:
    # 结果未知的文件动作逐个核实（工单 #308）：动作前快照按 tool_started 记下的引用取回，
    # 与动作参数、当前公开树按 verify_file_action 对比。恢复与自动重新执行走同一个函数。
    # 没有引用、引用取不到或看不懂的动作不在结论里，调用方按通常路径发决定请求
    results: dict[str, dict[str, Any]] = {}
    for info in classify_actions(events).values():
        started = info["started_event"]
        if (info["status"] != ACTION_UNKNOWN or started is None
                or info["tool"] not in FILE_ACTION_TOOLS):
            continue
        ref = (started.payload or {}).get("before_snapshot_ref")
        if not isinstance(ref, Mapping):
            continue
        before_snapshot = json.loads(artifacts.get_for_run(run_id, ArtifactRef(**ref)))
        if not isinstance(before_snapshot, Mapping):
            continue
        result = verify_file_action(info["tool"], (started.payload or {}).get("args"),
                                    before_snapshot=before_snapshot, current_entries=current_entries)
        results[info["action_id"]] = {"tool": info["tool"], "args": (started.payload or {}).get("args"),
                                      "before_snapshot_event": started.event_id,
                                      "verdict": str(result["verdict"]), "detail": result["detail"]}
    return results


def _verify_write(arguments: Mapping[str, Any], *, before: dict[str, str],
                  current: dict[str, str]) -> dict[str, Any]:
    # 写入（环境按全文件内容落盘）：目标内容是参数 content 的字节；路径用执行环境落盘时的二进制口径核对
    path = arguments.get("path")
    content = arguments.get("content")
    if not isinstance(path, str) or not isinstance(content, str):
        return {"verdict": "unclear", "detail": {"reason": "动作参数缺失或形状不对"}}
    return _compare_single_target(path=path, target=hash_bytes(content.encode("utf-8")),
                                  before=before, current=current)


def _verify_edit(arguments: Mapping[str, Any], *, before: dict[str, str],
                 current: dict[str, str]) -> dict[str, Any]:
    # 编辑的快照只存哈希，离线算不出合并以后的确切字节：用间接判据——目标路径内容已变、其它路径都没变。
    # 判据在 detail 写明，供决定请求与核实依据引用
    path = arguments.get("path")
    if not isinstance(path, str):
        return {"verdict": "unclear", "detail": {"reason": "动作参数缺失或形状不对"}}
    if path not in before:
        return {"verdict": "unclear", "detail": {"reason": f"动作前的快照没有目标路径：{path}"}}
    detail = {"path": path, "changed": current.get(path) != before.get(path),
              "others_unchanged": all(current.get(key) == value for key, value in before.items()
                                      if key != path)
              and all(key in before or key == path for key in current)}
    changed = current.get(path)
    if changed is None or changed == before.get(path):
        if current == before:
            return {"verdict": "not_happened", "detail": {**detail, "reason": "公开树与动作前相同"}}
        return {"verdict": "unclear", "detail": {**detail, "reason": "目标内容与动作前相同，但另有改动"}}
    if detail["others_unchanged"]:
        return {"verdict": "completed", "detail": {**detail, "reason": "只有目标路径内容变化"}}
    return {"verdict": "unclear", "detail": {**detail, "reason": "目标路径已变，但另有改动"}}


def _verify_delete(arguments: Mapping[str, Any], *, before: dict[str, str],
                   current: dict[str, str]) -> dict[str, Any]:
    # 删除的目标：路径在当前公开树消失；reason 写明存活还是另有改动
    path = arguments.get("path")
    if not isinstance(path, str):
        return {"verdict": "unclear", "detail": {"reason": "动作参数缺失或形状不对"}}
    if current == before:
        return {"verdict": "not_happened", "detail": {"reason": "公开树与动作前相同"}}
    if path not in before:
        return {"verdict": "unclear", "detail": {"reason": f"动作前的快照没有目标路径：{path}"}}
    if path in current:
        return {"verdict": "unclear", "detail": {"reason": f"目标路径仍然存在：{path}"}}
    others_before = {key: value for key, value in before.items() if key != path}
    others_current = {key: value for key, value in current.items() if key != path}
    if others_current == others_before:
        return {"verdict": "completed", "detail": {"reason": f"只有目标路径消失：{path}"}}
    return {"verdict": "unclear", "detail": {"reason": "目标路径消失，但另有改动"}}


def _verify_move(arguments: Mapping[str, Any], *, before: dict[str, str],
                 current: dict[str, str]) -> dict[str, Any]:
    # 移动的目标：来源消失，目标出现，且目标内容的哈希等于动作前来源的哈希（工作区只做改名，不改字节）
    source = arguments.get("source")
    destination = arguments.get("destination")
    if not isinstance(source, str) or not isinstance(destination, str):
        return {"verdict": "unclear", "detail": {"reason": "动作参数缺失或形状不对"}}
    if current == before:
        return {"verdict": "not_happened", "detail": {"reason": "公开树与动作前相同"}}
    if source not in before:
        return {"verdict": "unclear", "detail": {"reason": f"动作前的快照没有来源路径：{source}"}}
    if source in current:
        return {"verdict": "unclear", "detail": {"reason": f"来源路径仍然存在：{source}"}}
    if current.get(destination) != before.get(source):
        return {"verdict": "unclear", "detail": {"reason": "目标内容与动作前来源内容不符"}}
    others_before = {key: value for key, value in before.items() if key not in (source, destination)}
    others_current = {key: value for key, value in current.items() if key not in (source, destination)}
    if destination in before:
        return {"verdict": "unclear", "detail": {"reason": f"目标路径在动作前已经存在：{destination}"}}
    if others_current == others_before:
        return {"verdict": "completed", "detail": {"reason": "来源消失，目标出现且内容与来源相同"}}
    return {"verdict": "unclear", "detail": {"reason": "移动已经发生，但另有改动"}}


def _compare_single_target(path: str, target: str, *, before: dict[str, str],
                           current: dict[str, str]) -> dict[str, Any]:
    # 单个目标路径的对比：动作前后的差异恰好是「目标路径变成目标内容」，其余路径都没有变
    if current == before:
        return {"verdict": "not_happened", "detail": {"reason": "公开树与动作前相同"}}
    if current.get(path) != target:
        reason = f"目标路径不存在：{path}" if path not in current else f"目标内容不符：{path}"
        return {"verdict": "unclear", "detail": {"reason": reason}}
    others_before = {key: value for key, value in before.items() if key != path}
    others_current = {key: value for key, value in current.items() if key != path}
    if others_current == others_before:
        return {"verdict": "completed", "detail": {"reason": "只有目标路径变成目标内容"}}
    return {"verdict": "unclear", "detail": {"reason": "目标内容相符，但另有改动"}}



# ---------------------------------------------------------------------------
# 恢复观察状态（工单 #18）

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

def terminal_observation_state(status: str, stop_reason: str | None = None) -> str:
    # run 已经结束时的观察状态（工单 #747）：按结束的方式分开。
    # - 已完成：状态 done，这次运行正常完成（成果可能被采纳，采纳是另一件事）；
    # - 已取消：停止原因是 cancelled，用户取消这次运行；
    # - 已暂停：状态 paused，运行暂停等待用户处理；
    # - 已停止：其余结束方式（执行失败、因 Yudao 升级停止等）
    if status == "done":
        return OBSERVATION_COMPLETED
    if stop_reason == "cancelled":
        return OBSERVATION_CANCELLED
    if status == "paused":
        return OBSERVATION_PAUSED
    return OBSERVATION_STOPPED

def observation_state(events: Sequence[Event], decisions: Iterable[DecisionRequest], *,
                      status: str, stop_reason: str | None = None) -> str:
    # 一个 run 的恢复观察状态（v8 设计说明第 7.2 节）：运行中、中断、待恢复，以及四种结束方式。
    # 判据只取持久事件、决定请求与投影中的终态，不读时钟，不调用模型：
    # - 已完成、已暂停、已取消、已停止：run 已经结束（完成、暂停、取消、失败）；由状态与停止原因给出；
    # - 待恢复：有未回答、阻塞整个 run 的待恢复请求（模型引用无法使用或定义版本不同）；
    # - 运行中：进程正在执行（有一次没有结束的激活）；
    # - 中断：其余情况，进程在步骤之间退出，等待启动时自动继续
    decision_list = list(decisions)
    if status in TERMINAL_STATUSES:
        return terminal_observation_state(status, stop_reason)
    if open_resume_decisions(decision_list):
        return OBSERVATION_WAITING_RESUME
    if _live_activation(events):
        return OBSERVATION_RUNNING
    return OBSERVATION_INTERRUPTED


# ---------------------------------------------------------------------------
# 启动时继续一个未结束的 run（恢复契约第 5.2 节，工单 #16、#17、#581）
#
# 这一块从薄驱动搬来（S4c 工单 #863）：薄驱动只把它接上并转交（`Orchestrator.resume_incomplete_run`），
# 自己不再写「核对定义版本、核实结果未知的动作、取得执行权」这三步。这里用到的薄驱动只有三件事：
# 读运行状态投影、读运行工作区、唤醒等待的会话；其余是写入口、工件库与事件。
#
# 定义版本不同时发出的决定请求留在这里：它只在继续一个 run 的时候发（ADR-0014），
# 与决定请求的处理（应用层 `decision_flow.py`，工单 #827）不是同一件事。
# ---------------------------------------------------------------------------


class RunRecovery:
    """恢复的零件：继续一个因进程中断而未结束的 run。

    依赖按职责分开给：`view` 读运行状态投影、`run_environment` 打开运行工作区（核对结果未知的
    文件动作要读当前公开树）、`wake` 唤醒等待的会话；事实与写入经 `writes` 与 `store`。
    """

    def __init__(self, *, writes: Any, store: Any, view: Callable[[str], Any], artifacts: Any,
                 run_environment: Callable[[str], Any], wake: Callable[[str], None]) -> None:
        self._writes = writes
        self._store = store
        self._view = view
        self._artifacts = artifacts
        self._run_environment = run_environment
        self._wake = wake

    def resume(self, run_id: str) -> tuple[int, Any] | None:
        # 启动时自动继续一个因进程中断而未结束的 run（ADR-0018、恢复契约第 5.2 节）：
        # run 事件版本与当前不同的 run 在启动序列里已经按强制升级处理（工单 #322），这里核对事项记录的
        # 定义版本，与当前不同就发出 definitions_changed 决定请求交给用户（ADR-0014，总体架构第 7.4 节），
        # 用户选择「按新版本继续」以前不取得执行权；核对通过以后原子取得这个 run 的执行权，
        # 记下中断位置与继续的依据，再从已提交的状态继续运行到终态。
        # 已经结束的 run 不取得执行权、不写事件；有未回答、阻塞整个 run 的决定请求时不继续，交给用户回答
        projection = self._view(run_id)
        if projection.status in TERMINAL_STATUSES:
            return None
        decisions = self._writes.read(run_stream(run_id)).decisions.values()
        if blocks_run(decisions):
            return None
        if projection.definitions_version != DEFINITIONS.version:
            self.await_definitions(run_id)
            return None
        # 工单 #17：检查是否有未确认的动作，为结果未知的动作写核实记录
        self.await_unknown_actions(run_id)
        return self.claim_and_resume(run_id)

    def await_definitions(self, run_id: str) -> None:
        # 事项记录的定义版本与当前加载的版本不同（ADR-0014，#48 登记的架构问题的处理）：
        # 发出一个阻塞整个 run 的决定请求，选项为「按新版本继续」与「停止事项」；选择写入事件。
        # 选择「按新版本继续」以后，这个 run 照常取得执行权并继续运行，后续事件记录新版本；
        # 请求只发一次：已经有过一个定义版本不同的请求时不重复
        def request(transaction: Transaction) -> None:
            current = transaction.projection
            if current.status in TERMINAL_STATUSES or blocks_run(transaction.decisions.values()):
                return
            if any(decision.request.get("kind") == DEFINITIONS_CHANGED.name
                   for decision in transaction.decisions.values()):
                return
            transaction.append(NewEvent(
                EventType.DECISION_REQUESTED, actor="system", department=current.active_department,
                state_before=current.status, state_after=current.status,
                payload={
                    "kind": DEFINITIONS_CHANGED.name, "blocks": DEFINITIONS_CHANGED.blocks,
                    "options": [{"id": option.id, "label": option.label} for option in DEFINITIONS_CHANGED.options],
                    "facts": [], "department": current.active_department,
                    "reason": "definitions_version_changed",
                    "recorded_definitions_version": current.definitions_version,
                    "current_definitions_version": DEFINITIONS.version,
                    "description": (
                        f"事项使用的定义版本 {current.definitions_version or '（未记录）'} 与当前加载的版本 "
                        f"{DEFINITIONS.version} 不同。按新版本继续以后，后续的模型请求与裁决记录新版本；"
                        "选择停止事项则运行结束。"),
                },
            ))
            transaction.on_commit(lambda: self._wake(run_id))

        self._writes.transact(run_stream(run_id), request)

    def await_unknown_actions(self, run_id: str) -> None:
        # 工单 #581（ADR-0038，恢复契约第 4 节）：恢复时找出结果未知的动作。
        # 文件动作（写入、编辑、删除、移动）先按动作前的公开树快照与当前公开树自动核实：
        # 已经完成的记一条 resolution="auto_verify" 的核实记录；没有发生的记一条 resolution="handed_back"
        # 的核实记录，说明核实确认没有发生；unclear 或无法核实的按非文件动作处理。
        # 其余结果未知的动作（命令、检查、读取等）记一条 resolution="handed_back" 的核实记录交还会话，
        # 说明执行被中断、结果未知，由模型检查后决定是否重新执行。
        # 不再发出任何 unknown_action 决定请求，事项直接继续。
        def request(transaction: Transaction) -> None:
            projection = transaction.projection
            if projection.status in TERMINAL_STATUSES:
                return
            for decision in transaction.decisions.values():
                if decision.status == "open" and decision.kind == "unknown_action":
                    transaction.append(NewEvent(
                        EventType.DECISION_WITHDRAWN,
                        actor="system",
                        department=decision.request.get("department") or projection.active_department,
                        parent_event_id=decision.decision_id,
                        state_before=projection.status,
                        state_after=projection.status,
                        payload={
                            "decision_id": decision.decision_id,
                            "reason": "superseded_by_hand_back",
                        },
                    ))
            events = transaction.events()
            actions = classify_actions(events)
            # 文件动作的对比结论一次算完（工单 #308）：当前公开树在这一个事务里读一次
            comparisons: dict[str, dict[str, Any]] = {}
            if any(info["status"] == ACTION_UNKNOWN and info["tool"] in FILE_ACTION_TOOLS
                   and info["started_event"] is not None for info in actions.values()):
                tree = self._run_environment(run_id).query(FactsQuery(tree=True)).tree
                if tree is not None:
                    comparisons = file_action_comparisons(
                        events, artifacts=self._artifacts, run_id=run_id,
                        current_entries=list(zip(tree.files, tree.hashes)))
            for identity, info in actions.items():
                started = info["started_event"]
                if info["status"] != ACTION_UNKNOWN or started is None:
                    continue
                if info["tool"] == "ask":
                    continue
                action_id = identity[2]
                comparison = comparisons.get(action_id)
                if comparison is not None and comparison["verdict"] == "completed":
                    transaction.append(self._auto_verified(started, projection.status, comparison))
                    continue
                if comparison is not None and comparison["verdict"] == "not_happened":
                    transaction.append(self._handed_back_action(
                        started, projection.status,
                        error="执行被中断，核实确认没有发生",
                        comparison=comparison,
                    ))
                    continue
                transaction.append(self._handed_back_action(
                    started, projection.status,
                    error="执行被中断，结果未知，由模型检查以后决定是否重新执行；没有收到输出",
                    comparison=comparison,
                ))

        self._writes.transact(run_stream(run_id), request)

    def _handed_back_action(self, started: Any, status: str, *,
                            error: str,
                            comparison: dict[str, Any] | None = None) -> NewEvent:
        # 结果未知的动作交还会话（工单 #581）：写一条 resolution="handed_back" 的核实记录，
        # input_item 带原动作的调用编号进入部门历史，模型下一次运行时读到并决定如何处理
        payload = started.payload or {}
        action_id = str(payload.get("id") or "")
        result = {"ok": False, "output": None, "error": error}
        input_item = {"type": "function_call_output", "call_id": action_id, "output": json_dumps(result)}
        event_payload: dict[str, Any] = {
            "id": action_id,
            "name": str(payload.get("name") or ""),
            "step_id": payload.get("step_id"),
            "activation_id": payload.get("activation_id"),
            "purpose": payload.get("purpose", "work"),
            "input_item": input_item,
            "ok": False,
            "error": error,
            "resolution": "handed_back",
        }
        if comparison is not None:
            event_payload["verification"] = comparison
        # 交还给发出这个动作的会话（工单 #475）：会话编号取自发这个动作的 tool_started，
        # 核实记录因此进入那个会话的历史（分支会话的核实结果不进入部门主线）
        return NewEvent(
            EventType.ACTION_VERIFIED, actor="system", department=started.department,
            state_before=status, state_after=status, parent_event_id=started.event_id,
            session_id=started.session_id,
            payload=event_payload,
        )

    def _auto_verified(self, started: Any, status: str, comparison: dict[str, Any]) -> NewEvent:
        # 自动核实（工单 #308）：对比确认动作已经完成时记一条核实记录，不补造原来的 tool_called 回执。
        # 结果进入部门历史：input_item 按原来的动作编号给出，与同一条结果的其它记录共享这个编号
        payload = started.payload or {}
        action_id = str(payload.get("id") or "")
        result = {"ok": True, "output": {"resolved": "auto_verify", "verification": comparison}, "error": None}
        input_item = {"type": "function_call_output", "call_id": action_id, "output": json_dumps(result)}
        return NewEvent(
            EventType.ACTION_VERIFIED, actor="system", department=started.department,
            state_before=status, state_after=status, parent_event_id=started.event_id,
            session_id=started.session_id,
            payload={"id": action_id, "name": str(payload.get("name") or ""), "step_id": payload.get("step_id"),
                     "activation_id": payload.get("activation_id"),
                     "purpose": payload.get("purpose", "work"), "input_item": input_item,
                     "ok": True, "resolution": "auto_verify", "verification": comparison},
        )

    def claim_and_resume(self, run_id: str) -> tuple[int, Any]:
        # 取得执行权并写入 run_resumed：中断位置与继续的依据取自取得执行权时的投影。
        # 恢复不写限额与计数字段（激活次数、模型步数、重试与已用运行时间保持中断时的值），
        # 也不新增部门激活：之后开始的激活由激活本身写入
        def claim(transaction: Transaction) -> int:
            projection = transaction.projection
            previous = self._store.projection(run_stream(run_id))
            # 执行权编号在写入口以已记录的编号加一确定；另一方先取得时流版本同时改变，
            # 这里的依据过期，事务因版本不符重新判断，因此这个编号与写入口确定的编号相同
            transaction.append(NewEvent(
                EventType.RUN_RESUMED, department=projection.active_department, actor="system",
                state_before=projection.status, state_after=projection.status,
                parent_event_id=projection.last_event_id,
                payload={
                    "basis": {
                        "interrupted_at_status": projection.status,
                        "interrupted_at_version": projection.stream_version,
                        "interrupted_at_event_id": projection.last_event_id,
                        "recorded_run_event_version": projection.run_event_version,
                        "current_run_event_version": RUN_EVENT_VERSION,
                    },
                    "acquired_epoch": (0 if previous is None or previous.epoch is None else previous.epoch) + 1,
                    "previous_epoch": None if previous is None else previous.epoch,
                },
            ))
            return (0 if previous is None or previous.epoch is None else previous.epoch) + 1

        epoch, _ = self._writes.claim_execution_right(run_stream(run_id), claim)
        return epoch, self._view(run_id)
