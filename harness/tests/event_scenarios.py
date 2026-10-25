# 事件序列场景表：每个场景用 FakeAdapter 脚本（或测试内启动的真实 HTTP 服务）驱动 LoopSystem，
# 返回它的控制核心、run 身份与规整时要替换的规则。test_event_sequence.py 用它把规整后的事件序列与
# harness/tests/event_sequences/<场景名>.json 比对；其他测试也按名字取一个场景跑完整序列。
# 每一项的第一段文字（也写进基准文件的 covers 字段）说明这个场景覆盖的行为。
# 检查命令一律写成 ["python", ...]，由主机解析解释器，基准中不出现本机路径。

import json
import threading
import time
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from typing import Any, Callable, Sequence

import pytest

from harness.adapters.base import Availability, ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn, prompt_part
from harness.collaboration import has_new_work
from harness.decisions import DecisionClosed
from harness.engine import StepLimits
from harness.environment import QA_TESTS_DIR
from harness.event_store import Command
from harness.models import EventType, Usage, json_dumps
from harness.providers.call import ModelCall, ModelResponse
from harness.proposals import (
    answer_turn, ask_turn,
    delivery_turn, guidance_response,
    product_spec, review, review_turn,
)
from harness.projection import saved_decisions
from harness.runtime import LoopSystem
from harness.tests.helpers import FAST_RETRIES, pinned_input_tokens
from harness.tests.protocol_helpers import ScriptedProvider, provider_system, send_reply, serve
from harness.tests.provider_replies import (
    BROKEN_STREAMS,
    HTTP_REPLIES,
    http_script,
    http_error as _http_error,
    messages_credential_rejected as _messages_credential_rejected,
    product_spec_reply,
    reply_index,
    request_department,
)


CHECKS = {"smoke": {"command": "python -c \"print('smoke ok')\""}}
ECHO = "import sys\nprint(sys.argv[1])\n"


@dataclass(frozen=True)
class Scenario:
    covers: str
    run: Callable[[Any], tuple[LoopSystem, str, dict[str, str]]]


def _call(identity: str, name: str, arguments: Any) -> dict[str, Any]:
    raw = arguments if isinstance(arguments, str) else json_dumps(arguments)
    return {"id": identity, "call_id": identity, "type": "function_call", "name": name, "arguments": raw}


def _current_spec_hash(call: ModelCall) -> str | None:
    raw = prompt_part(call, "current_product_spec")
    return json.loads(raw).get("content_hash") if raw else None


def _deliver() -> Callable[[ModelCall], FakeTurn]:
    return delivery_turn(files={"src/echo.py": ECHO}, checks=CHECKS)


def _release(rationale: str = "checks passed on the current snapshot") -> Callable[[ModelCall], FakeTurn]:
    return review_turn("release", rationale, checks=CHECKS)


def _explore(name: str = "test_echo.py") -> FakeTurn:
    # 质检的预测性探索（循环结构第 3.1 节、工单 #557）：PRD 被接纳以后还没有交付，
    # 质检按 PRD 起草测试用例，写进质检自己的测试材料。这一轮没有交付可以核验，
    # 提交的结论被拒绝，这一轮到这里结束；交付到达以后质检开始新一轮工作。
    return FakeTurn(
        writes={f"{QA_TESTS_DIR}/{name}": "import sys\nprint('QA_TEST_DRAFTED')\nsys.exit(0)\n"},
        proposal=review("release", "按 PRD 起草了测试用例；还没有交付可以核验"),
    )


def _handoff_script() -> list[Any]:
    return [product_spec(), _deliver(), _release()]


def _system(data_dir, script: list[Any] | dict[str, list[Any]], *, step_limits: StepLimits = StepLimits(),
            **run_options: Any) -> tuple[LoopSystem, FakeAdapter, str]:
    # 脚本两种给法：一个队列按请求先后取用；按部门给的每个部门一份，各自取用自己的（#469）
    adapter = FakeAdapter(script)
    system = LoopSystem.for_testing(data_dir, adapter, step_limits=step_limits)
    return system, adapter, system.create_run("build an echo CLI", **run_options)


def handoff_release(data_dir):
    # 按部门给出的脚本：产品一份、工程一份（交付）、质检两份（预测性探索与放行）
    # （#469 验收 1；计划已随 #470 删除；工单 #557 增加质检的预测性探索）
    system, _, run_id = _system(data_dir, {
        "product": [product_spec()],
        "engineering": [_deliver()],
        "quality": [_explore(), _release()],
    })
    system.run_until_stop(run_id)
    return system, run_id, {}


def retry_then_success(data_dir):
    system, _, run_id = _system(data_dir, [
        ProviderError("temporary connection failure", retryable=True, diagnostics={"error_type": "connection"}),
        product_spec(),
    ], step_limits=FAST_RETRIES)
    system.activate_once(run_id)
    return system, run_id, {}


def retry_exhausted(data_dir):
    system, _, run_id = _system(data_dir, [ProviderError("temporary", retryable=True) for _ in range(3)],
                                step_limits=FAST_RETRIES)
    system.run_until_stop(run_id)
    return system, run_id, {}


def retry_after_too_long(data_dir):
    system, _, run_id = _system(data_dir, [
        ProviderError("rate limited", retryable=True, diagnostics={"retry_after_sec": 60.1}),
        product_spec(),
    ])
    system.run_until_stop(run_id)
    return system, run_id, {}


def _summary(request, text="Product memory: the large file was read; keep the original requirements."):
    return {"id": f"summary-{request.activation_id}-{request.step_id}", "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": text}]}


def _compaction_system(data_dir, summary: Callable[[Any], ModelResponse], *, step_limits: StepLimits = StepLimits()):
    reads: set[str] = set()

    def respond(request):
        if request.purpose == "compaction":
            return summary(request)
        if request.activation_id not in reads:
            reads.add(request.activation_id)
            identity = f"read-{request.activation_id}-{request.step_id}"
            return ModelResponse(output=[_call(identity, "read_file", {"path": "large.txt"})])
        return product_spec()

    system, _, run_id = _system(data_dir, [respond] * 20, step_limits=step_limits, context_window=6000)
    system.workspace(run_id).write_file("large.txt", "LARGE_TOOL_OUTPUT " * 2200)
    return system, run_id


def compaction_success(data_dir):
    system, run_id = _compaction_system(data_dir, lambda request: ModelResponse(output=[_summary(request)]))
    system.activate_once(run_id)
    return system, run_id, {}


def compaction_failed(data_dir):
    def undeclared(request):
        identity = f"corrupt-{request.activation_id}-{request.step_id}"
        return ModelResponse(output=[_call(identity, "list_files", {})])

    system, run_id = _compaction_system(data_dir, undeclared, step_limits=FAST_RETRIES)
    system.run_until_stop(run_id)
    return system, run_id, {}


def invalid_tool_arguments(data_dir):
    system, _, run_id = _system(data_dir, [
        ModelResponse(output=[_call("call-truncated", "search", '{"pattern": "def add", "path": ')]),
        product_spec(),
    ])
    system.activate_once(run_id)
    return system, run_id, {}


    system.run_until_stop(run_id)
    return system, run_id, {}


def _guidance_id(call) -> str:
    return json.loads(prompt_part(call, "department_guidance"))[0]["id"]


def ask_answer_with_spec_revision(data_dir):
    system, _, run_id = _system(data_dir, {
        "product": [product_spec()],
        "engineering": [
            ask_turn("product", "Should output be uppercase?", background="Clarification needed", expected="Specification update"),
            _deliver(),
        ],
        "product:ask": [
            answer_turn("Yes, print in uppercase.",
                        requirements=["print the given argument in uppercase to stdout"],
                        change_record={"changed": ["print the given argument in uppercase to stdout"],
                                       "retained": ["single file implementation"]}),
        ],
        "quality": [_explore(), _release()],
    })
    system.run_until_stop(run_id)
    return system, run_id, {}


def ask_branch_exhausted(data_dir):
    system, _, run_id = _system(data_dir, {
        "product": [product_spec()],
        "engineering": [
            ask_turn("product", "Should output be uppercase?", background="Clarification needed", expected="Specification update"),
            _deliver(),
        ],
        "product:ask": [
            ModelResponse(output=[_call("ans-err", "answer", {"answer": ""})]),
        ],
        "quality": [_explore(), _release()],
    }, step_limits=StepLimits(max_model_steps=4, department_max_model_steps={"product": 1}))
    system.run_until_stop(run_id)
    return system, run_id, {}


def guidance_response_explained(data_dir):
    system, adapter, run_id = _system(data_dir, {"product": [product_spec()],
                                                 "engineering": [], "quality": []})
    system.activate_once(run_id)
    system.add_guidance(run_id, "engineering", "请说明当前错误输出边界，无需改文件。")
    adapter.scripts["engineering"].extend([
        lambda request: FakeTurn(proposal=guidance_response(
            _guidance_id(request), status="explained", text="当前合同已覆盖该边界，无需变更。")),
        _deliver(),
    ])
    adapter.scripts["quality"].extend([_explore(), _release()])
    system.run_until_stop(run_id)
    return system, run_id, {}


def proposal_rejected(data_dir):
    system, _, run_id = _system(data_dir, {
        "product": [{"kind": "product_spec", "goal": "", "requirements": ["print the argument"],
                     "acceptance_criteria": ["prints it"]}],
        "engineering": [_deliver()],
        "quality": [_explore(), _release()],
    })
    system.run_until_stop(run_id)
    return system, run_id, {}


def quality_rework(data_dir):
    system, _, run_id = _system(data_dir, {
        "product": [product_spec()],
        "engineering": [
            _deliver(),
            delivery_turn("handled arguments with spaces", files={"src/echo.py": "import sys\nprint(' '.join(sys.argv[1:]))\n"},
                          checks=CHECKS),
        ],
        "quality": [
            _explore(),
            review_turn("rework_engineering", "the output misses a trailing newline check", checks=CHECKS,
                        defects=[{"severity": "major", "summary": "no check covers an argument with spaces"}]),
            _release("the rework passed the checks"),
        ],
    })
    system.run_until_stop(run_id)
    return system, run_id, {}


def stop_command(data_dir):
    system, _, run_id = _system(data_dir, _handoff_script())
    system.activate_once(run_id)
    system.add_input(run_id, "/stop")
    system.run_until_stop(run_id)
    return system, run_id, {}


def cancel_during_model_call(data_dir):
    holder: dict[str, Any] = {}

    def cancel_then_deliver(request):
        holder["system"].cancel(request.run_id)
        return _deliver()

    system, _, run_id = _system(data_dir, {"product": [product_spec()],
                                           "engineering": [cancel_then_deliver],
                                           "quality": [_explore()]})
    holder["system"] = system
    system.run_until_stop(run_id)
    return system, run_id, {}


def time_limit(data_dir):
    # 限制留出 3 秒，请求之前的装配在负载高时也不会用完它；模型调用本身等待到限制之后
    def slow_spec(request):
        time.sleep(3.2)
        return product_spec()

    system, _, run_id = _system(data_dir, {"product": [slow_spec],
                                           "engineering": [_deliver()],
                                           "quality": [_explore(), _release()]},
                                run_time_limit_sec=3)
    system.run_until_stop(run_id)
    return system, run_id, {}


def model_steps_exhausted(data_dir):
    def list_files(request):
        identity = f"list-{request.activation_id}-{request.step_id}"
        return ModelResponse(output=[_call(identity, "list_files", {})])

    system, _, run_id = _system(data_dir, [list_files] * 3, step_limits=StepLimits(max_model_steps=3))
    system.run_until_stop(run_id)
    return system, run_id, {}


def context_overflow(data_dir):
    system, _, run_id = _system(data_dir, [product_spec()], context_window=1500)
    system.run_until_stop(run_id)
    return system, run_id, {}


def history_exceeds_the_window(data_dir):
    # 固定材料放得下；激活第一步的部门工作消息再次带上整段原始意图，加上部门历史以后超过窗口，
    # 摘要请求也放不下，运行以 compaction_failed 结束，没有模型调用。
    # 窗口按固定材料的实测 token 数加余量推出，不写死数字（测试分层设计第 10 节第 3 条）。
    # 余量的可行区间由实测确定：低于下界时错误变成「固定材料放不下摘要」，
    # 高于上界时摘要请求放得下，运行会真的调用模型（适配器脚本耗尽）。
    task = "build an echo CLI. " + "Keep the requirement text. " * 370
    adapter = FakeAdapter([product_spec()])
    system = LoopSystem.for_testing(data_dir, adapter)
    measure_id = system.create_run(task, context_window=1_000_000)
    # 测量 run 与真实 run 共用同一个 data_dir：调用目标按事项窗口逐次安装（orchestrator.py:1162），
    # 后建的 run 用自己 create_run 时声明的窗口，两者互不影响。
    pinned = pinned_input_tokens(system, measure_id)
    run_id = system.create_run(task, context_window=pinned + 2048)
    system.run_until_stop(run_id)
    return system, run_id, {}


def no_tool_call_pause(data_dir):
    replies = [FakeTurn(transcript=f"第 {index} 次只回复文字") for index in range(1, 5)]
    system, _, run_id = _system(data_dir, replies)
    system.run_until_stop(run_id)
    return system, run_id, {}


def bash_is_not_a_check_receipt(data_dir):
    argv = ["python", "src/echo.py", "hello"]

    def submit(call, identity):
        return _call(identity, "submit_delivery",
                     {"summary": "echo CLI", "check_names": ["unit-tests"],
                      "basis_product_spec_hash": _current_spec_hash(call)})

    def first(call):
        return ModelResponse(output=[_call("write-1", "write_file", {"path": "src/echo.py", "content": ECHO}),
                                     _call("command-1", "bash", {"command": "python src/echo.py hello"}),
                                     submit(call, "submit-1")])

    def second(call):
        return ModelResponse(output=[_call("check-2", "run_check", {"name": "unit-tests", "command": "python src/echo.py hello"}),
                                     _call("write-2", "write_file", {"path": "src/echo.py", "content": ECHO + "\n"}),
                                     submit(call, "submit-2")])

    def third(call):
        return ModelResponse(output=[_call("check-3", "run_check", {"name": "unit-tests", "command": "python src/echo.py hello"}),
                                     submit(call, "submit-3")])

    system, _, run_id = _system(data_dir, {
        "product": [product_spec()],
        "engineering": [first, second, third],
        "quality": [_explore(), _release("verified the delivered echo CLI")],
    })
    system.run_until_stop(run_id)
    return system, run_id, {}


def _running(label: str, *, delay_sec: float = 0.0) -> str:
    # 运行中的进程（argv 的一项）：输出一行，在第一个参数给出的位置写下标记文件以后一直等待
    # delay_sec 大于零时先等这么久再写标记：取消因此落在别的会话这一轮工作结束以后，
    # 事件序列不依赖取消落在别的会话的哪一步（工单 #557）
    # 等的时间要够慢的运行机上一个会话走完一轮（那一轮里有一次 Git 提交），这里取 5 秒
    return (f"import pathlib, sys, time; print('{label} started', flush=True); "
            f"time.sleep({delay_sec}); "
            "pathlib.Path(sys.argv[1]).write_text('running'); time.sleep(60)")


def _cancel_when_running(system: LoopSystem, run_id: str, marker) -> threading.Thread:
    # 进程写下标记文件（确实在运行）以后，另一个线程取消运行
    def cancel() -> None:
        for _ in range(1200):
            if marker.exists():
                break
            time.sleep(0.05)
        system.cancel(run_id)

    canceller = threading.Thread(target=cancel)
    canceller.start()
    return canceller


def cancel_while_check_runs(data_dir):
    # 标记文件的路径写成正斜杠形式，规整以后各平台相同
    # 标记文件在检查开始一秒以后写下：取消发生在质检那一轮工作结束以后，
    # 事件序列不依赖取消落在别的会话的哪一步（工单 #557，与 cancel_while_bash_runs 同一做法）
    marker = (data_dir / "check-running").as_posix()
    command = f'python -c "{_running("check", delay_sec=5)}" "{marker}"'
    def deliver(call):
        return ModelResponse(output=[_call("write-1", "write_file", {"path": "src/echo.py", "content": ECHO}),
                                     _call("check-1", "run_check", {"name": "smoke", "command": command}),
                                     _call("submit-1", "submit_delivery",
                                           {"summary": "echo CLI", "check_names": ["smoke"],
                                            "basis_product_spec_hash": _current_spec_hash(call)})])
    system, _, run_id = _system(data_dir, {
        "product": [product_spec()],
        "engineering": [deliver],
        "quality": [_explore()],
    })
    canceller = _cancel_when_running(system, run_id, data_dir / "check-running")
    system.run_until_stop(run_id)
    canceller.join(60)
    return system, run_id, {}


def cancel_while_bash_runs(data_dir):
    marker = (data_dir / "command-running").as_posix()
    # 标记文件在命令开始五秒以后写下：取消发生在别的会话这一轮工作结束以后，
    # 事件序列不依赖取消落在别的会话的哪一步（工单 #557，与 cancel_while_check_runs 同一做法；
    # 五秒要够慢的运行机上一个会话走完一轮）
    command = f"echo command started; sleep 5; printf running > \"{marker}\"; sleep 60"
    def deliver(call):
        return ModelResponse(output=[_call("command-1", "bash", {"command": command}),
                                     _call("submit-1", "submit_delivery",
                                           {"summary": "echo CLI", "check_names": ["smoke"],
                                            "basis_product_spec_hash": _current_spec_hash(call)})])
    system, _, run_id = _system(data_dir, {
        "product": [product_spec()],
        "engineering": [deliver],
        "quality": [_explore()],
    })
    canceller = _cancel_when_running(system, run_id, data_dir / "command-running")
    system.run_until_stop(run_id)
    canceller.join(60)
    return system, run_id, {}


# 真实 Provider 模块：三个部门绑定同一个本机 HTTP 服务，服务按部门回放脚本中的工具调用
def _http_scenario(protocol: str):
    def run(data_dir):
        state = {"product": 0, "engineering": 0, "quality": 0}

        def responder(body):
            # 同时运行的会话各自取用自己的脚本（工单 #557）：按请求里的工具分派到部门，
            # 不按请求的先后顺序
            department = request_department(body)
            index = state[department]
            state[department] += 1
            calls = http_script(body)[department][index]
            return 200, "text/event-stream", [HTTP_REPLIES[protocol](reply_index(department, index), calls)]

        server, _capture, base = serve(responder)
        try:
            system, run_id = provider_system(data_dir, base, protocol)
            system.run_until_stop(run_id)
        finally:
            server.shutdown()
            server.server_close()
        return system, run_id, {base: "<provider>"}

    return run


# 真实 Provider 模块的失败、重试与取消：测试内启动的 HTTP 服务（ScriptedProvider）按请求顺序执行回复脚本
def _held(provider: ScriptedProvider, _handler: BaseHTTPRequestHandler) -> None:
    # 收到请求以后一直不回复，直到场景结束
    provider.held.set()
    provider.release.wait(60)


def _cancel_while_provider_holds(protocol: str):
    def run(data_dir):
        provider = ScriptedProvider([_held])
        try:
            system, run_id = provider_system(data_dir, provider.base, protocol)

            def cancel_when_held() -> None:
                provider.held.wait(60)
                system.cancel(run_id)

            canceller = threading.Thread(target=cancel_when_held)
            canceller.start()
            system.run_until_stop(run_id)
            canceller.join(60)
        finally:
            provider.close()
        return system, run_id, {provider.base: "<provider>"}

    return run


def _failure_then_success(protocol: str, first, *, timeout_sec: float = 20.0,
                          step_limits: StepLimits = FAST_RETRIES):
    def run(data_dir):
        provider = ScriptedProvider([first, product_spec_reply(protocol)])
        try:
            system, run_id = provider_system(data_dir, provider.base, protocol, timeout_sec=timeout_sec,
                                             step_limits=step_limits)
            system.activate_once(run_id)
        finally:
            provider.close()
        return system, run_id, {provider.base: "<provider>"}

    return run


_UNAVAILABLE_MESSAGE = "Missing configuration: provider credential"


def _answer_open_decision(system: LoopSystem, option: str) -> str:
    # 只经公开接口回答待恢复：按保存的投影列出未回答的决定请求，经流程编排的回答入口回答
    _position, decisions = saved_decisions(system.store, statuses=("open",))
    assert len(decisions) == 1, [decision.decision_id for decision in decisions]
    [decision] = decisions
    assert (decision.request["kind"], decision.request["blocks"]) == ("model_unavailable", "run")
    assert decision.request["reason"] == "provider_unavailable"
    command = Command(str(uuid.uuid4()), "decision.answer", f"sha256:{option}:1", "user:local")
    system.orchestrator.answer_decision(decision.decision_id, option, None, base_version=1, command=command)
    return decision.decision_id


def _request_time_unavailable_script() -> dict[str, list[Any]]:
    # 请求时模型引用不可用：产品规格被接纳以后工程部门的请求被提供方报告为不可用
    return {
        "product": [FakeTurn(proposal=product_spec(), usage=Usage(input_tokens=100, output_tokens=20))],
        "engineering": [ProviderError(_UNAVAILABLE_MESSAGE, reason="provider_unavailable"), _deliver()],
        "quality": [_explore(), _release()],
    }


def request_time_unavailable(data_dir):
    system, _, run_id = _system(data_dir, _request_time_unavailable_script())
    blocked = system.run_until_stop(run_id)
    assert blocked.status == "running"
    assert blocked.product_spec is not None
    # 不可用的请求来自工程：决定请求写明提出它的部门（不依赖部门激活的先后，工单 #557）
    _position, open_decisions = saved_decisions(system.store, statuses=("open",))
    assert [item.request["department"] for item in open_decisions] == ["engineering"]
    _answer_open_decision(system, "continue")
    assert system.run_until_stop(run_id).status == "done"
    return system, run_id, {}


def request_time_unavailable_stop(data_dir):
    system, _, run_id = _system(data_dir, _request_time_unavailable_script())
    blocked = system.run_until_stop(run_id)
    assert blocked.status == "running"
    _answer_open_decision(system, "stop")
    finished = system.run_until_stop(run_id)
    assert (finished.status, finished.stop_reason) == ("failed", "cancelled")
    events = system.store.list_events(run_id)
    assert [event.type for event in events[-2:]] == [EventType.DECISION_ANSWERED, EventType.RUN_FAILED]
    return system, run_id, {}


def request_time_unavailable_cancel(data_dir):
    system, _, run_id = _system(data_dir, _request_time_unavailable_script())
    blocked = system.run_until_stop(run_id)
    assert blocked.status == "running"
    _position, decisions = saved_decisions(system.store, statuses=("open",))
    assert len(decisions) == 1
    cancelled = system.cancel(run_id)
    assert (cancelled.status, cancelled.stop_reason) == ("failed", "cancelled")
    events = system.store.list_events(run_id)
    assert [event.type for event in events[-2:]] == [EventType.DECISION_WITHDRAWN, EventType.RUN_FAILED]
    _position, withdrawn = saved_decisions(system.store, statuses=("withdrawn",))
    assert [decision.decision_id for decision in withdrawn] == [decisions[0].decision_id]
    end = system.store.end_position()
    command = Command(str(uuid.uuid4()), "decision.answer", "sha256:continue:1", "user:local")
    with pytest.raises(DecisionClosed):
        system.orchestrator.answer_decision(decisions[0].decision_id, "continue", None, base_version=1,
                                            command=command)
    assert system.store.end_position() == end
    _position, still_withdrawn = saved_decisions(system.store, statuses=("withdrawn",))
    assert [decision.decision_id for decision in still_withdrawn] == [decisions[0].decision_id]
    return system, run_id, {}


class _FlakyAvailabilityAdapter(FakeAdapter):
    # 激活开始时的可用性检查分支：先报告模型引用不可用，回答待恢复以后恢复可用
    def __init__(self, script: Sequence[Any] | None = None) -> None:
        super().__init__(script)
        self.flaky = True

    def availability(self) -> Availability:
        if self.flaky:
            return Availability(False, "provider_unavailable", _UNAVAILABLE_MESSAGE)
        return Availability(True)


def activation_start_unavailable(data_dir):
    adapter = _FlakyAvailabilityAdapter({"product": [product_spec()],
                                          "engineering": [_deliver()],
                                          "quality": [_explore(), _release()]})
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("build an echo CLI")
    blocked = system.run_until_stop(run_id)
    # 模型服务在激活开始时不可用：产品还没有开始一轮工作，它按关注的成果等着（工单 #556）
    assert (has_new_work(blocked, "product"), blocked.status) == (True, "running")
    assert len(adapter.invocations) == 0
    adapter.flaky = False
    _answer_open_decision(system, "continue")
    assert system.run_until_stop(run_id).status == "done"
    return system, run_id, {}


def _credential_rejected_then_continue(protocol: str, first):
    # 真实本地 Provider 上游拒绝凭据（HTTP 401）：第一次请求记为不可重试的 provider_unavailable 进入待恢复，
    # 回答继续执行以后走完交接与放行；成功回复按部门回放交接脚本（工单 #557：同时运行的会话各自取用自己的）
    def run(data_dir):
        replies = [first]
        counters = {"product": 0, "engineering": 0, "quality": 0}

        def after_rejection(provider, handler):
            # 提交依据的版本取自这次请求装配好的部门材料（ScriptedProvider 把请求正文挂在处理机上：
            # 同时运行的会话各自发请求，不能拿最后收到的请求当作这次请求）
            body = handler.body
            department = request_department(body)
            index = counters[department]
            counters[department] += 1
            calls = http_script(body)[department][index]
            send_reply(handler, 200, "text/event-stream",
                       HTTP_REPLIES[protocol](reply_index(department, index), calls))

        replies.extend(after_rejection for _ in range(4))
        provider = ScriptedProvider(replies)
        try:
            system, run_id = provider_system(data_dir, provider.base, protocol)
            blocked = system.run_until_stop(run_id)
            assert blocked.status == "running"
            _answer_open_decision(system, "continue")
            finished = system.run_until_stop(run_id)
            assert finished.status == "done"
        finally:
            provider.close()
        return system, run_id, {provider.base: "<provider>"}

    return run


def concurrent_departments(data_dir):
    # 一个事项里多个会话同时运行（工单 #557）：PRD 被接纳以后工程与质检各开始一轮工作，
    # 各自一个会话；工程写文件的同时质检按 PRD 起草测试用例，测试材料保存为一个版本；
    # 交付到达以后质检开始新一轮工作，从这份交付重建检查工作区，核验并放行。
    system, _, run_id = _system(data_dir, {
        "product": [product_spec()],
        "engineering": [_deliver()],
        "quality": [_explore(), _release()],
    })
    system.run_until_stop(run_id)
    return system, run_id, {}


SCENARIOS: dict[str, Scenario] = {
    "concurrent_departments": Scenario(
        "一个事项里工程与质检同时运行：PRD 被接纳以后两个部门各开始一轮工作，工程写文件的同时质检起草测试用例；交付到达以后质检开始新一轮工作，核验并放行。",
        concurrent_departments),
    "handoff_release": Scenario(
        "一次成功的提交与部门交接：产品提交规格，工程直接写文件、运行检查并提交交付，质检运行检查后放行，运行结束于 DONE。",
        handoff_release),
    "retry_then_success": Scenario(
        "模型调用失败一次（可重试）：记录失败的尝试与重试安排，同一个逻辑调用的第二次尝试成功，产品规格被接纳。",
        retry_then_success),
    "retry_exhausted": Scenario(
        "可重试的失败连续三次，尝试次数用完，运行以 provider_error 失败。",
        retry_exhausted),
    "retry_after_too_long": Scenario(
        "提供方要求的 Retry-After（60.1 秒）超过最大等待（60 秒）：不等待、不重试，运行以 retry_after_too_long 失败。",
        retry_after_too_long),
    "compaction_success": Scenario(
        "读取大文件后上下文接近窗口：先发出没有工具的压缩请求，摘要记为压缩检查点，之后的工作请求带着摘要继续，产品规格被接纳。",
        compaction_success),
    "compaction_failed": Scenario(
        "压缩请求连续三次返回未声明的工具调用：每次作为可重试失败记录，工具不执行，尝试次数用完后运行以 compaction_failed 失败。",
        compaction_failed),
    "invalid_tool_arguments": Scenario(
        "模型给出无法解析的工具参数：工具不启动，错误作为工具结果返回模型，记入历史的参数换成 {}；下一步提交成功。",
        invalid_tool_arguments),
    "ask_answer_with_spec_revision": Scenario(
        "工程询问产品，产品在分支里修订 PRD 并回答，工程收到回答与 PRD 新版本，接着交付，质检放行。",
        ask_answer_with_spec_revision),
    "ask_branch_exhausted": Scenario(
        "分支达到上限时以没能回答结束（unable），提问方收到原因后接着工作，事项运行到放行。",
        ask_branch_exhausted),
    "guidance_response_explained": Scenario(
        "产品规格接纳后用户给工程部门写指导：指导在请求之前写入并标记已进入输入，工程部门回应指导（explained），之后交付并放行。",
        guidance_response_explained),
    "proposal_rejected": Scenario(
        "产品规格缺少目标被控制层拒绝，拒绝原因作为 validation_feedback 进入下一次激活，修正后接纳，走完交付与放行。",
        proposal_rejected),
    "quality_rework": Scenario(
        "质检以 rework_engineering 退回并附缺陷，工程部门重新交付，质检再次运行检查后放行。",
        quality_rework),
    "stop_command": Scenario(
        "产品规格接纳后用户输入 /stop：保存原文并取消运行（cancelled），不再激活部门。",
        stop_command),
    "cancel_during_model_call": Scenario(
        "工程部门的模型调用进行中用户取消运行：这次调用尝试记为已取消（cancelled），它的回答不进入历史，运行以 cancelled 结束，不再激活部门。",
        cancel_during_model_call),
    "time_limit": Scenario(
        "产品部门的模型调用期间运行时间用完（限制 3 秒）：已给出的工具调用记为跳过，运行以 time_limit 失败。",
        time_limit),
    "model_steps_exhausted": Scenario(
        "一次激活内模型步数用完（最大步数 3）：每一步都只调用只读工具而没有提交，运行以 model_steps_exhausted 暂停。",
        model_steps_exhausted),
    "context_overflow": Scenario(
        "固定材料超过上下文窗口（1500）：请求在发送之前判定超限，没有模型调用，运行以 context_overflow 失败。",
        context_overflow),
    "history_exceeds_the_window": Scenario(
        "固定材料放得下，加入部门历史以后超过上下文窗口（窗口由固定材料的实测 token 数加余量推出）："
        "摘要请求也放不下，运行以 compaction_failed 失败，没有模型调用"
        "（调用目标声明了输出上限，#45 起测试也走调用目标）。",
        history_exceeds_the_window),
    "no_tool_call_pause": Scenario(
        "连续 4 次只回复文字（#47）：前 3 次各追加一条主机提示，第 4 次以 no_tool_call 暂停运行。",
        no_tool_call_pause),
    "bash_is_not_a_check_receipt": Scenario(
        "只运行 bash 就提交交付被拒绝（#103）；运行检查后又修改文件再次被拒绝；重新调用 run_check 后交付被接纳，质检放行。",
        bash_is_not_a_check_receipt),
    "cancel_while_check_runs": Scenario(
        "工程部门的检查进程运行中另一个线程取消运行：运行以 cancelled 结束；检查的进程树结束，回执记为已取消"
        "（exit 130，带截至结束时的输出），之后的提交记为跳过，不再激活部门。",
        cancel_while_check_runs),
    "cancel_while_bash_runs": Scenario(
        "工程部门的 bash 命令运行中另一个线程取消运行：运行以 cancelled 结束；命令的进程树结束，回执记为已取消"
        "（status cancelled、exit 130，带截至结束时的输出），之后的提交记为跳过，不再激活部门。",
        cancel_while_bash_runs),
    "http_responses_handoff": Scenario(
        "经真实 Provider 模块与测试内启动的 HTTP 服务（Responses 协议）走完交接与放行：记录序列化请求、流式进度、响应与用量。",
        _http_scenario("responses")),
    "http_chat_handoff": Scenario(
        "经真实 Provider 模块与测试内启动的 HTTP 服务（Chat Completions 协议）走完交接与放行：记录序列化请求、流式进度与用量。",
        _http_scenario("chat_completions")),
    "http_messages_handoff": Scenario(
        "经真实 Provider 模块与测试内启动的 HTTP 服务（Messages 协议）走完交接与放行：记录序列化请求、流式进度与用量。",
        _http_scenario("messages")),
    "http_responses_cancel_while_provider_holds": Scenario(
        "经真实 Provider 模块（Responses 协议）：服务端收到产品部门的请求后一直不回复，另一个线程取消运行："
        "这次调用尝试记为已取消（cancelled），运行以 cancelled 结束，不再激活部门。",
        _cancel_while_provider_holds("responses")),
    "http_responses_stream_broken_then_success": Scenario(
        "经真实 Provider 模块（Responses 协议）：流式回复送出 response.created 与一条输出之后连接中途断开："
        "已收到的输出只作为审计记录，不进入重试请求，失败可重试，第二次尝试成功，产品规格被接纳。",
        _failure_then_success("responses", BROKEN_STREAMS["responses"])),
    "activation_start_unavailable": Scenario(
        "激活开始时模型引用不可用：可用性检查不通过时没有模型调用，run 停在这次请求之前进入待恢复；"
        "恢复可用以后回答继续执行，走完交接与放行。",
        activation_start_unavailable),
    "request_time_unavailable": Scenario(
        "请求时提供方报告模型引用不可用：工程部门的请求记为不可重试的 provider_unavailable 进入待恢复，"
        "run 停在这次请求之前；回答继续执行以后从这次请求接着进行，走完交付与放行。",
        request_time_unavailable),
    "http_responses_credential_rejected_then_continue": Scenario(
        "经真实 Provider 模块（Responses 协议）：第一次请求被上游拒绝凭据（HTTP 401）："
        "记为不可重试的 provider_unavailable 进入待恢复；回答继续执行以后走完交接与放行。",
        _credential_rejected_then_continue("responses", _http_error(401, "invalid_api_key"))),
    "http_chat_credential_rejected_then_continue": Scenario(
        "经真实 Provider 模块（Chat Completions 协议）：第一次请求被上游拒绝凭据（HTTP 401）："
        "记为不可重试的 provider_unavailable 进入待恢复；回答继续执行以后走完交接与放行。",
        _credential_rejected_then_continue("chat_completions", _http_error(401, "invalid_api_key"))),
    "http_messages_credential_rejected_then_continue": Scenario(
        "经真实 Provider 模块（Messages 协议）：第一次请求被上游拒绝凭据（HTTP 401）："
        "记为不可重试的 provider_unavailable 进入待恢复；回答继续执行以后走完交接与放行。",
        _credential_rejected_then_continue("messages", _messages_credential_rejected)),
    "request_time_unavailable_stop": Scenario(
        "请求时模型引用不可用进入待恢复以后回答停止事项：回答与运行结束在同一个事务中写入，"
        "运行以 cancelled 结束，不再调用模型。",
        request_time_unavailable_stop),
    "request_time_unavailable_cancel": Scenario(
        "请求时模型引用不可用进入待恢复以后取消运行：未回答的决定请求被撤销，运行以 cancelled 结束；"
        "此后的回答被拒绝，不再写入。",
        request_time_unavailable_cancel),
}

