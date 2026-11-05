# 基础规则第六条的前半：每个 run 以封闭清单里的原因结束或进入等待。
#
# 到终态的 run 必有一条带封闭清单原因的结束事件（run_done、run_paused 或 run_failed），
# 等待中的 run 必有一条 run_waiting 之外的在途状态：决定请求（decision_requested）
# 或尚未收尾的激活。停止原因是 stop_reasons.json 这份封闭清单，写入口按它核对
# （write_path._check_stop_reason），清单以外的原因写不进去。
#
# 对全部事件序列基准执行（44 个场景）：基准是真实运行录下来的事件序列，读静态文件，
# 不重跑运行，属于单元层。
#
# 封闭清单是**事项所用的那份定义**里的（工单 #1165）：第二种路由在它自己那份定义的 routings.json 里
# 声明自己的结束原因（docs/design/skeleton-and-application.md「其他路由：骨架要满足的条件」），事项创建时冻结定义版本，写入口核对停止原因与部门时
# 读的就是这一份；不交定义时读模块加载的那一份，与以前相同。后半的三条用例自己造定义、经写入口写入
# 一个结束事件来核对这一点：不开数据库、不用子进程与临时目录。

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from harness import write_path
from harness.definitions import DEFINITIONS, Definitions, RoutingEndReason, UnknownStopReason
from harness.event_store import run_stream
from harness.models import TERMINAL_STATUSES

BASELINE_DIR = Path(__file__).resolve().parents[1] / "event_sequences"
STOP_REASONS = Path(__file__).resolve().parents[3] / "harness" / "definitions" / "stop_reasons.json"
_STOP_EVENTS = ("run_done", "run_paused", "run_failed")
# 非终态的场景：录制在 run 结束以前停止，尾部是未收尾的激活，投影不在终态
_PREFIX_SCENARIOS = {
    "compaction_success",
    "http_chat_stream_broken_then_success",
    "http_messages_stream_broken_then_success",
    "http_responses_retry_after_then_success",
    "http_responses_server_error_then_success",
    "http_responses_stream_broken_then_success",
    "http_responses_timeout_then_success",
    "invalid_tool_arguments",
    "retry_then_success",
    "text_only_reply",
}


def _reasons() -> dict:
    return json.loads(STOP_REASONS.read_text(encoding="utf-8"))


def test_every_baseline_ends_with_a_reasoned_stop_event_or_waits():
    reasons = _reasons()
    # 封闭清单的项数：20 项（第 18 项是 user_cancelled，用户放弃建档，工单 #707，依据是决策记录
    # 「M0 走查问题的五项口径」第 2 项；第 20 项是 open_loop，开环完成，工单 #1394）
    assert len(reasons) == 20, f"停止原因的封闭清单有 {len(reasons)} 项"
    checked = 0
    for path in sorted(BASELINE_DIR.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        events = document["events"]
        assert events, f"{path.name} 没有录到事件"
        stops = [event for event in events if event["type"] in _STOP_EVENTS]
        status = document["projection"].get("status")
        if status in TERMINAL_STATUSES:
            assert stops, f"{path.name} 已到终态却没有结束事件"
            for stop in stops:
                reason = (stop.get("payload") or {}).get("stop_reason")
                assert reason in reasons, f"{path.name} 的停止原因 {reason!r} 不在封闭清单里"
                assert stop.get("stop_reason") == reason, f"{path.name} 的事件停止原因与载荷不一致"
                outcome = reasons[reason]["outcome"]
                assert stop["type"] == f"run_{outcome}", \
                    f"{path.name} 的原因 {reason!r} 的去向是 {outcome}，事件却是 {stop['type']}"
            checked += 1
        else:
            # 进入等待：要么在等用户的决定，要么录制停在未收尾的激活上
            waiting = [event for event in events if event["type"] == "decision_requested"]
            assert path.stem in _PREFIX_SCENARIOS or waiting, \
                f"{path.name} 非终态，既不在已知的前缀录制清单里，也没有在等决定"
    assert checked > 30, f"终态基准只有 {checked} 个"


def test_every_stop_reason_is_in_the_closed_list():
    # 写入口按这份清单核对结束事件（write_path._check_stop_reason），终止事件只能带清单里的原因
    reasons = _reasons()
    for path in sorted(BASELINE_DIR.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for event in document["events"]:
            if event["type"] in _STOP_EVENTS:
                assert event.get("stop_reason") in reasons, \
                    f"{path.name} 的结束事件带有清单外的停止原因 {event.get('stop_reason')!r}"

# ---------------------------------------------------------------------------
# 封闭清单是事项所用的那份定义的（工单 #1165）
# ---------------------------------------------------------------------------

# 第二种路由在自己那份定义里声明的一个结束原因：内核的停止原因清单（stop_reasons.json）里没有它，
# 它在 routings.json 那条路由的 end_reasons 里（docs/design/skeleton-and-application.md「其他路由：骨架要满足的条件」）
_ROUTING_END_REASON = "pool_drained"


def _with_end_reason(definition: Definitions, reason: str, outcome: str = "failed") -> Definitions:
    # 这份定义里，组织定义所选的那条路由多声明一个自己的结束原因。与工单 #1098 的内核用例同一个做法：
    # 只改「这份定义里有什么」这一件事，不动模块加载的那一份
    routing = definition.routing_definition()
    end_reasons = {**routing.end_reasons,
                   reason: RoutingEndReason(label="任务池里没有待办的任务", outcome=outcome,
                                            human_action="每一件任务都有了结论，这件事项到此结束。")}
    routings = tuple(item.model_copy(update={"end_reasons": end_reasons}) if item.id == routing.id else item
                     for item in definition.routings.routings)
    return definition.model_copy(
        update={"routings": definition.routings.model_copy(update={"routings": routings})})


def _without_department(definition: Definitions, department: str) -> Definitions:
    # 这份组织定义里没有这个部门
    organization = definition.organization
    departments = tuple(item for item in organization.departments if item.id != department)
    return definition.model_copy(
        update={"organization": organization.model_copy(update={"departments": departments})})


@dataclass
class _State:
    # 投影的替身：写入口给 run 事件盖上所属的项目与事项；这几条用例只判核对，投影不参与判断
    project_id: str | None = None
    work_item_id: str | None = None


class _Handler:
    # 流处理者的替身：折叠与保存都不参与这几条用例的判断
    def empty(self) -> _State:
        return _State()

    def load(self, saved: Any) -> _State:
        return _State()

    def fold(self, state: _State, event: Any) -> None:
        return None

    def dump(self, state: _State) -> str:
        return "{}"


class _Store:
    # 事件日志的替身：只记下提交的事件，不落盘。这几条用例判的是写入口的核对，不是存储
    def __init__(self) -> None:
        self.committed: list[Any] = []

    def projection(self, stream: str) -> None:
        return None

    def last_dispatch_number(self, stream: str, session_id: str | None = None) -> int:
        # 这几条用例不核对派发编号：这个流里还没有取得过编号
        return 0

    def commit(self, stream: str, expected_version: int, events: list[Any], state: str, *,
               epoch: int | None = None, command: Any = None, decisions: Any = ()) -> None:
        self.committed.extend(events)

    def notify(self, events: list[Any]) -> None:
        return None


def _writes() -> tuple[write_path.WritePath, _Store]:
    store = _Store()
    return write_path.WritePath(store, lambda _stream: _Handler()), store


def _ending(reason: str, *, event_type: str = "run_failed", department: str = "product") -> write_path.NewEvent:
    # 一条结束事件：带着停止原因、终态与载荷里的同一个原因（写入口按这三样核对）
    return write_path.NewEvent(event_type, state_before="running", state_after="failed", actor="system",
                               department=department, stop_reason=reason,
                               payload={"stop_reason": reason})


def test_the_open_loop_reason_ends_a_run_as_done():
    # R1：开环完成的结果是完成，去向是 run_done。写入口收下它，状态迁移与载荷里的原因与清单一致；
    # 写成暂停或失败被拒绝（原因规定的结束方式与事件对不上，工单 #1394）
    writes, _store = _writes()
    [event] = writes.append(run_stream("run_open_loop"), write_path.NewEvent(
        "run_done", state_before="running", state_after="done", actor="system", department="product",
        stop_reason="open_loop", payload={"stop_reason": "open_loop"}))
    assert (event.type, event.stop_reason, event.state_after) == ("run_done", "open_loop", "done")
    assert _reasons()["open_loop"]["outcome"] == "done"
    with pytest.raises(ValueError, match="open_loop"):
        writes.append(run_stream("run_open_loop_failed"), write_path.NewEvent(
            "run_failed", state_before="running", state_after="failed", actor="system", department="product",
            stop_reason="open_loop", payload={"stop_reason": "open_loop"}))


def test_the_write_path_takes_the_stop_reason_of_the_matter_definition():
    # 验收第 1 条（工单 #1165）：第二种路由在自己那份定义里声明的结束原因，事项用这份定义运行时
    # 经写入口写得进事件日志；模块加载的那份定义里仍然没有它
    definitions = _with_end_reason(DEFINITIONS, _ROUTING_END_REASON)
    writes, store = _writes()
    [event] = writes.append(run_stream("run_matter"), _ending(_ROUTING_END_REASON), definitions=definitions)
    assert event.stop_reason == _ROUTING_END_REASON
    assert event.payload["stop_reason"] == _ROUTING_END_REASON
    assert [item.event_id for item in store.committed] == [event.event_id]
    assert _ROUTING_END_REASON not in DEFINITIONS.stop_reasons


def test_the_same_write_fails_against_a_definition_without_that_reason():
    # 验收第 2 条（工单 #1165）：同样的写入，用一份没有声明这个原因的定义时失败，
    # 错误写明是哪一个原因与哪份定义（内核的停止原因清单与这条路由自己的结束原因两处）
    writes, store = _writes()
    with pytest.raises(UnknownStopReason) as raised:
        writes.append(run_stream("run_matter"), _ending(_ROUTING_END_REASON))
    message = str(raised.value)
    assert _ROUTING_END_REASON in message
    assert "stop_reasons.json" in message and "routings.json" in message
    assert DEFINITIONS.routing in message
    assert store.committed == []


def test_the_department_check_takes_the_matter_definition_and_defaults_to_the_loaded_one():
    # 验收第 3 条（工单 #1165）：不给定义参数时，写入口对停止原因与部门的核对与以前一样；
    # 交了定义时按它的部门核对（部门与停止原因同一个取法）
    narrowed = _without_department(DEFINITIONS, "quality")
    writes, _store = _writes()
    with pytest.raises(ValueError, match="unknown department 'quality'"):
        writes.append(run_stream("run_matter"), _ending("cancelled", department="quality"),
                      definitions=narrowed)
    [event] = writes.append(run_stream("run_matter"), _ending("cancelled", department="quality"))
    assert event.department == "quality" and event.stop_reason == "cancelled"
