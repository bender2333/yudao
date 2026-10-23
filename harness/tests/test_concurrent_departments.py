# 一个事项里多个会话同时运行（工单 #557）：PRD 被接纳以后工程与质检各开始一轮工作，各自一个会话；
# 质检在预测性探索里按 PRD 起草测试用例，交付到达以后开始新一轮工作，核验并放行。
# 取消与暂停作用于事项的全部会话。

import uuid
from pathlib import Path

from harness.adapters.fake import FakeAdapter, FakeTurn, prompt_part
from harness.environment import QA_TESTS_DIR
from harness.event_store import Command
from harness.models import EventType, json_dumps
from harness.projection import saved_decisions
from harness.proposals import delivery, delivery_turn, product_spec, review, review_turn
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem

CHECKS = {"smoke": {"command": "python -c \"print('smoke ok')\""}}
ECHO = "import sys\nprint(sys.argv[1])\n"
TEST_FILE = f"{QA_TESTS_DIR}/test_echo.py"
TEST_CONTENT = "import sys\nprint('QA_TEST_DRAFTED')\nsys.exit(0)\n"


def _call(identity: str, name: str, arguments: dict) -> dict:
    return {"id": identity, "call_id": identity, "type": "function_call", "name": name,
            "arguments": json_dumps(arguments)}


def _explore() -> FakeTurn:
    # 质检的预测性探索：按 PRD 起草测试用例，写进质检自己的测试材料；
    # 这一轮没有交付可以核验，提交的结论被拒绝
    return FakeTurn(
        writes={TEST_FILE: TEST_CONTENT},
        proposal=review("release", "按 PRD 起草了测试用例；还没有交付可以核验"),
    )


def _release():
    # 放行按请求里装配好的当前交付声明依据版本（工单 #471）
    return review_turn("release", "checks passed on the current snapshot", checks=CHECKS)


def _events(system: LoopSystem, run_id: str) -> list:
    return system.store.list_events(run_id)


def _position(events: list, event_type: str, department: str, *, name: str | None = None) -> int:
    for event in events:
        if event.type != event_type or event.department != department:
            continue
        if name is not None and (event.payload or {}).get("name") != name:
            continue
        return event.position
    raise AssertionError(f"no {event_type} event for {department}")


def test_engineering_and_quality_work_at_the_same_time(tmp_path: Path) -> None:
    # 交付到达以后质检核验并放行；工程写入与质检起草测试用例的事件交错出现
    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn(files={"src/echo.py": ECHO}, checks=CHECKS)],
        "quality": [_explore(), _release()],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build an echo CLI")
    projection = system.run_until_stop(run_id)
    assert projection.status == "done"

    events = _events(system, run_id)
    sessions = {event.session_id for event in events if event.type == EventType.DEPARTMENT_ACTIVATED}
    # 三个部门各有一个会话
    assert len(sessions) == 3
    # 质检的预测性探索与工程的写入交错：质检写测试材料在工程写文件之后、工程提交交付之前
    engineering_write = _position(events, EventType.TOOL_CALLED, "engineering", name="write_file")
    quality_write = _position(events, EventType.TOOL_CALLED, "quality", name="write_file")
    delivery = _position(events, EventType.DELIVERY_ACCEPTED, "engineering")
    assert engineering_write < quality_write < delivery
    # 交付到达以后质检开始新一轮工作：质检有两个激活（预测性探索与核验）
    quality_activations = [event for event in events
                            if event.type == EventType.DEPARTMENT_ACTIVATED and event.department == "quality"]
    assert len(quality_activations) == 2
    # 质检核验并放行
    assert [event.type for event in events if event.type == EventType.QA_SUBMITTED]
    assert projection.stop_reason == "released"


def test_predictive_exploration_reads_the_project_start_not_the_delivery(tmp_path: Path) -> None:
    # 第一份交付还不存在时，质检的检查工作区来自事项开始时的项目起点：
    # 读不到工程尚未交付的修改；质检写的测试保存为测试材料的一个版本
    def explore(call):
        # 先读工程写的文件：质检的检查工作区里没有它
        raw = prompt_part(call, "current_delivery_spec")
        return ModelResponse(output=[
            _call("read-1", "read_file", {"path": "src/echo.py"}),
            _call("write-1", "write_file", {"path": TEST_FILE, "content": TEST_CONTENT}),
            _call("submit-1", "submit_review", {
                "verdict": "release", "rationale": "按 PRD 起草了测试用例；还没有交付可以核验",
                "checks": ["smoke"], "defects": [], "basis_delivery_spec_hash": None}),
        ])

    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn(files={"src/echo.py": ECHO}, checks=CHECKS)],
        "quality": [explore, _release()],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build an echo CLI")
    projection = system.run_until_stop(run_id)
    assert projection.status == "done"

    events = _events(system, run_id)
    read = next(event for event in events
                if event.type == EventType.TOOL_CALLED and event.department == "quality"
                and (event.payload or {}).get("name") == "read_file")
    assert read.payload.get("ok") is False, "质检的检查工作区里没有工程尚未交付的文件"
    # 质检写的测试保存为测试材料的一个版本
    saved = [event for event in events if event.type == EventType.QA_TESTS_SAVED]
    assert len(saved) == 1
    assert saved[0].payload["version"] == 1
    assert saved[0].payload["content_hash"]


def test_quality_cannot_write_into_the_runtime_workspace(tmp_path: Path) -> None:
    # 质检在预测性探索中写入运行工作区被拒绝：它只能写自己的测试材料
    def explore(call):
        return ModelResponse(output=[
            _call("write-runtime", "write_file", {"path": "src/echo.py", "content": ECHO}),
            _call("write-tests", "write_file", {"path": TEST_FILE, "content": TEST_CONTENT}),
            _call("submit-1", "submit_review", {
                "verdict": "release", "rationale": "按 PRD 起草了测试用例；还没有交付可以核验",
                "checks": ["smoke"], "defects": [], "basis_delivery_spec_hash": None}),
        ])

    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn(files={"src/echo.py": ECHO}, checks=CHECKS)],
        "quality": [explore, _release()],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build an echo CLI")
    system.run_until_stop(run_id)

    events = _events(system, run_id)
    writes = {event.payload.get("id"): event for event in events
              if event.type == EventType.TOOL_CALLED and event.department == "quality"
              and (event.payload or {}).get("name") == "write_file"}
    assert set(writes) == {"write-runtime", "write-tests"}
    # 写入运行工作区被拒绝；写自己的测试材料被允许
    assert writes["write-runtime"].payload.get("ok") is False, "质检写入运行工作区被拒绝"
    assert writes["write-tests"].payload.get("ok") is True
    # 工程写的交付文件没有被质检改掉
    projection = system.project(run_id)
    assert projection.delivery_spec is not None


def test_cancel_stops_every_session(tmp_path: Path) -> None:
    # 取消事项时全部会话停止
    def explore(call):
        return ModelResponse(output=[
            _call("write-1", "write_file", {"path": TEST_FILE, "content": TEST_CONTENT}),
        ])

    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn(files={"src/echo.py": ECHO}, checks=CHECKS)],
        "quality": [explore],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build an echo CLI")
    system.activate_once(run_id)
    cancelled = system.cancel(run_id)
    assert (cancelled.status, cancelled.stop_reason) == ("failed", "cancelled")
    events = _events(system, run_id)
    finished = [event for event in events if event.type == EventType.ACTIVATION_FINISHED]
    # 已经开始的会话都结束了，没有一个会话还在进行
    assert {event.session_id for event in finished} == {event.session_id for event in events
                                                        if event.type == EventType.DEPARTMENT_ACTIVATED}
    # 取消以后结束的会话都记着取消这个原因
    assert all(event.payload.get("stop_reason") == "cancelled"
               for event in finished if event.department != "product")


def test_pause_and_continue_lets_each_session_resume_where_it_stopped(tmp_path: Path) -> None:
    # 暂停以后继续，各会话从停下的位置接着工作（工单 #557 验收第 8 条）：
    # 工程的会话连续只回复文字，运行以 no_tool_call 暂停；用户回答「继续」以后，
    # 工程从停下的位置接着工作——它下一步的请求里已经有暂停以前做过的步骤，
    # 交付里也有暂停以前写下的文件
    def text_only(call):
        return FakeTurn(transcript="我先想想。")

    adapter = FakeAdapter({
        "product": [product_spec()],
        # 先写文件，再连续只回复文字（运行因此暂停），继续以后交付
        "engineering": [
            FakeTurn(writes={"src/echo.py": ECHO}),
            text_only, text_only, text_only, text_only,
            delivery_turn(files={"src/echo.py": ECHO}, checks=CHECKS),
        ],
        "quality": [_explore(), _release()],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build an echo CLI")
    paused = system.run_until_stop(run_id)
    assert (paused.status, paused.stop_reason) == ("paused", "no_tool_call")

    events = _events(system, run_id)
    # 暂停以前工程写过文件：这一步的结果在这个会话的历史里
    written = [event for event in events
               if event.type == EventType.TOOL_CALLED and event.department == "engineering"
               and (event.payload or {}).get("name") == "write_file"]
    assert written, "暂停以前工程没有写文件"
    write_call_id = written[0].payload.get("id")

    # 用户回答「处理以后继续执行」
    _position, decisions = saved_decisions(system.store, statuses=("open",))
    assert len(decisions) == 1, [decision.decision_id for decision in decisions]
    [decision] = decisions
    assert decision.request["kind"] == "no_tool_call"
    command = Command(str(uuid.uuid4()), "decision.answer", "sha256:continue:1", "user:local")
    system.orchestrator.answer_decision(decision.decision_id, "continue", None,
                                        base_version=decision.version, command=command)
    projection = system.run_until_stop(run_id)
    assert projection.status == "done", projection.stop_reason

    events = _events(system, run_id)
    continued = next(event for event in events if event.type == EventType.RUN_CONTINUED)
    # 继续以后工程又发了请求：这个请求里有暂停以前那一步的结果（会话从停下的位置接着工作）
    resumed = [event for event in events
               if event.type == EventType.MODEL_REQUESTED and event.department == "engineering"
               and event.position > continued.position]
    assert resumed, "继续以后工程没有接着工作"
    request = next(call for call in adapter.invocations
                   if call.department == "engineering"
                   and call.activation_id == resumed[0].payload["activation_id"]
                   and call.step_id == resumed[0].payload["step_id"])
    outputs = [item for item in request.input_items
               if isinstance(item, dict) and item.get("type") == "function_call_output"
               and item.get("call_id") == write_call_id]
    assert outputs, "继续以后的请求里没有暂停以前那一步的结果"
    # 交付在继续以后到达，交付的内容是暂停以前写下的文件
    accepted = [event for event in events if event.type == EventType.DELIVERY_ACCEPTED]
    assert accepted, "继续以后没有交付"
    assert accepted[0].position > continued.position
    released = [event for event in events if event.type == EventType.QA_SUBMITTED]
    assert released and released[0].payload.get("verdict") == "release"
