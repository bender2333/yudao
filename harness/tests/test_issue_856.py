# 停下其余会话只停这个会话（工单 #856）：事项被未回答的决定请求挡住时，运行循环停下其余会话，
# 停下不再打开整个事项的取消开关。回答「继续」以后事项接着工作并照常完成；
# 用户取消事项仍然让全部会话停下、事项以 cancelled 结束。

import json
import sys
import uuid
from pathlib import Path

from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.event_store import Command
from harness.models import EventType, json_dumps
from harness.projection import saved_decisions
from harness.proposals import delivery_turn, product_spec, review_turn
from harness.providers.call import ModelStreamEvent
from harness.runtime import LoopSystem
from harness.tests.helpers import after_event, from_another_thread

ECHO = "import sys\nprint(sys.argv[1])\n"
CHECKS = {"smoke": {"command": "python -c \"print('smoke ok')\""}}
# 一项要几秒的检查：另一个部门在工作的时候用它确定地占住那个会话
SLOW_CHECK = {"command": f'"{sys.executable.replace(chr(92), "/")}" -c "import time; time.sleep(3)"'}
UNAVAILABLE = "Missing configuration: provider credential"


def _events(system: LoopSystem, run_id: str) -> list:
    return system.store.list_events(run_id)


def _answer(system: LoopSystem, option: str = "continue") -> str:
    # 经公开接口回答一个决定请求（阻塞整个 run 的那种）
    _position, decisions = saved_decisions(system.store, statuses=("open",))
    assert len(decisions) == 1, [decision.decision_id for decision in decisions]
    [decision] = decisions
    command = Command(str(uuid.uuid4()), "decision.answer", f"sha256:{option}:1", "user:local")
    system.orchestrator.answer_decision(decision.decision_id, option, None,
                                        base_version=decision.version, command=command)
    return decision.decision_id


def _requests(adapter: FakeAdapter, department: str) -> list:
    return [call for call in adapter.invocations if call.department == department]


def _outputs(call) -> list[dict]:
    return [item for item in call.input_items
            if isinstance(item, dict) and item.get("type") == "function_call_output"]


def _tool_result(event) -> dict:
    # 一次工具调用的结果（回执写在工具结果里）
    return json.loads(event.payload["input_item"]["output"])["output"]


def _position_of_cancelled(events: list) -> int:
    # 事项以取消结束的那条事件的位置
    failed = [event for event in events if event.type == EventType.RUN_FAILED]
    assert failed, "事项没有以失败结束"
    return failed[0].position


def test_answering_continue_after_a_pause_keeps_the_item_working(tmp_path: Path) -> None:
    # 工程暂停（连续只回复文字）时质检正在跑一项要几秒的检查：
    # 回答「继续」以后事项接着工作并照常完成，没有 run_failed cancelled；
    # 两个部门都从各自的历史接着工作
    state = {"quality_check_started": False}

    def note_check_started(event) -> None:
        if event.department == "quality" and (event.payload or {}).get("name") == "run_check":
            state["quality_check_started"] = True

    def text_after_quality_started(call):
        # 等质检的检查确实开始以后再只回复文字：暂停发生时质检确定在工作（不靠时序碰运气）
        for _ in range(600):
            if state["quality_check_started"]:
                break
            yield ModelStreamEvent(kind="stream_event", id="evt-wait")
        return FakeTurn(transcript="我先想想。")

    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [text_after_quality_started] * 4
                       + [delivery_turn(files={"src/echo.py": ECHO}, checks=CHECKS)],
        "quality": [FakeTurn(checks={"slow": SLOW_CHECK}),
                    review_turn("release", "checks passed on the current snapshot", checks=CHECKS)],
    }, stream_gap_sec=0.01)
    system = LoopSystem.for_testing(tmp_path, adapter)
    after_event(system, EventType.TOOL_STARTED, note_check_started)
    run_id = system.create_run("build an echo CLI")

    paused = system.run_until_stop(run_id)
    assert (paused.status, paused.stop_reason) == ("paused", "no_tool_call")
    events = _events(system, run_id)
    # 暂停不是取消：事项没有以 cancelled 结束
    assert not [event for event in events if event.type == EventType.RUN_FAILED]
    # 停下的会话已经收尾（工单 #856 验收第 5 条）：不再是进行中
    assert paused.sessions["quality"].status != "active", paused.sessions["quality"].status
    # 质检的检查确实被停下：回执记着取消
    cancelled = [event for event in events
                 if event.type == EventType.TOOL_CALLED and event.department == "quality"
                 and (event.payload or {}).get("name") == "run_check"]
    assert cancelled, "质检没有跑检查"
    assert _tool_result(cancelled[0])["exit_code"] == 130, _tool_result(cancelled[0])

    _answer(system, "continue")
    finished = system.run_until_stop(run_id)
    assert finished.status == "done", finished.stop_reason
    events = _events(system, run_id)
    assert not [event for event in events if event.type == EventType.RUN_FAILED]
    assert [event for event in events if event.type == EventType.RUN_CONTINUED]
    assert [event for event in events if event.type == EventType.DELIVERY_ACCEPTED]
    released = [event for event in events if event.type == EventType.QA_SUBMITTED]
    assert released and released[0].payload.get("verdict") == "release"

    # 两个部门都从各自的历史接着工作：继续以后的请求里带着各自以前那一步的结果
    engineering = _requests(adapter, "engineering")
    assert len(engineering) >= 2
    texts = [item.get("content") for item in engineering[-1].input_items
             if isinstance(item, dict) and item.get("type") == "message"]
    assert any("我先想想" in json_dumps(item) for item in texts), "工程没有从自己的历史接着"
    quality = _requests(adapter, "quality")
    assert len(quality) >= 2
    assert _outputs(quality[-1]), "质检的下一次请求里没有自己以前那一步的结果"


def test_model_unavailable_while_another_department_works(tmp_path: Path) -> None:
    # 模型不可用进入待恢复时另一个部门正在工作：那个部门停下，待恢复的决定请求照常写出；
    # 回答「继续执行」以后事项接着进行
    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [FakeTurn(checks={"slow": SLOW_CHECK}),
                        delivery_turn(files={"src/echo.py": ECHO}, checks=CHECKS)],
        "quality": [ProviderError(UNAVAILABLE, reason="provider_unavailable"),
                    review_turn("release", "checks passed on the current snapshot", checks=CHECKS)],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build an echo CLI")

    blocked = system.run_until_stop(run_id)
    # 待恢复：事项本身没有结束，决定请求照常写出
    assert blocked.status == "running", blocked.status
    _position, decisions = saved_decisions(system.store, statuses=("open",))
    assert len(decisions) == 1
    [decision] = decisions
    assert (decision.request["kind"], decision.request["blocks"]) == ("model_unavailable", "run")
    assert decision.request["department"] == "quality"
    # 停下的会话已经收尾（工单 #856 验收第 5 条）
    assert blocked.sessions["engineering"].status == "idle", blocked.sessions["engineering"].status

    _answer(system, "continue")
    finished = system.run_until_stop(run_id)
    assert finished.status == "done", finished.stop_reason
    events = _events(system, run_id)
    assert not [event for event in events if event.type == EventType.RUN_FAILED]
    assert [event for event in events if event.type == EventType.DELIVERY_ACCEPTED]


def test_two_sessions_blocked_by_model_problems_in_turn(tmp_path: Path) -> None:
    # 两个会话先后被模型问题挡住：各有一条决定请求，都回答以后事项继续，不会以「已取消」结束
    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [ProviderError(UNAVAILABLE, reason="provider_unavailable"),
                        delivery_turn(files={"src/echo.py": ECHO}, checks=CHECKS)],
        "quality": [FakeTurn(checks={"slow": SLOW_CHECK}),
                    ProviderError(UNAVAILABLE, reason="provider_unavailable"),
                    review_turn("release", "checks passed on the current snapshot", checks=CHECKS)],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build an echo CLI")

    first = system.run_until_stop(run_id)
    assert first.status == "running", first.status
    _position, decisions = saved_decisions(system.store, statuses=("open",))
    assert len(decisions) == 1
    assert decisions[0].request["department"] == "engineering"
    _answer(system, "continue")

    second = system.run_until_stop(run_id)
    assert second.status == "running", second.status
    _position, decisions = saved_decisions(system.store, statuses=("open",))
    assert len(decisions) == 1
    assert decisions[0].request["department"] == "quality"
    _answer(system, "continue")

    finished = system.run_until_stop(run_id)
    assert finished.status == "done", finished.stop_reason
    events = _events(system, run_id)
    assert not [event for event in events if event.type == EventType.RUN_FAILED]
    # 各有一条待恢复的决定请求：两个部门各一条
    requested = [event for event in events if event.type == EventType.DECISION_REQUESTED]
    assert [event.department for event in requested] == ["engineering", "quality"]
    released = [event for event in events if event.type == EventType.QA_SUBMITTED]
    assert released and released[0].payload.get("verdict") == "release"


def test_user_cancel_stops_every_session_and_ends_the_item_as_cancelled(tmp_path: Path) -> None:
    # 用户取消事项：全部会话停下，事项以 cancelled 结束（工单 #856 验收第 4 条）
    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [FakeTurn(checks={"slow": SLOW_CHECK})],
        "quality": [FakeTurn(checks={"slow": SLOW_CHECK})],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build an echo CLI")
    operation = {}

    def cancel_when_working(event) -> None:
        # 工程的检查确实在跑的时候取消事项（另一个线程里做，与界面上发命令同一条路）
        if event.department == "engineering" and (event.payload or {}).get("name") == "run_check":
            operation["result"] = from_another_thread(lambda: system.cancel(run_id))

    after_event(system, EventType.TOOL_STARTED, cancel_when_working)
    finished = system.run_until_stop(run_id)
    assert (finished.status, finished.stop_reason) == ("failed", "cancelled")
    assert not operation["result"].errors, operation["result"].errors
    events = _events(system, run_id)
    # 已经开始的会话都结束了，没有一个会话还在进行
    assert {event.session_id for event in events if event.type == EventType.ACTIVATION_FINISHED} == {
        event.session_id for event in events if event.type == EventType.DEPARTMENT_ACTIVATED}
    # 取消以后结束的会话都记着取消这个原因
    assert all(event.payload.get("stop_reason") == "cancelled"
               for event in events if event.type == EventType.ACTIVATION_FINISHED
               and event.department != "product")
    # 取消以后不再有模型请求
    assert not [event for event in events
                if event.type == EventType.MODEL_REQUESTED
                and event.position > _position_of_cancelled(events)]
