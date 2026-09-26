import json
import time
from dataclasses import dataclass
from typing import Any, Callable

import pytest

from harness.adapters.base import ModelResponse, ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.engine import StepLimits
from harness.models import DEPARTMENTS, json_dumps
from harness.proposals import (
    collaboration_request, delivery, delivery_turn, engineering_plan, guidance_response, plan_turn,
    product_spec, response_turn, review, review_turn,
)
from harness.providers import CredentialChain, ProviderFacade
from harness.runtime import LoopSystem
from harness.tests.event_sequence import compare_with_baseline, normalized_run
from harness.tests.helpers import FAST_RETRIES
from harness.tests.protocol_helpers import serve, sse

# 每个场景用 FakeAdapter 脚本（或测试内启动的真实 HTTP 服务）驱动 LoopSystem，把规整后的事件序列与
# harness/tests/event_sequences/<场景名>.json 比较；规整规则与基准文件的结构见 event_sequence.py。
# SCENARIOS 中每一项的第一段文字（也写进基准文件的 covers 字段）说明这个场景覆盖的行为。
# 基准与当前运行不一致说明行为改变：修正代码，不更新基准。只有架构师确认的有意改变才用
# python -m pytest harness/tests/test_event_sequence.py --write-event-baselines 重写基准，并在提交说明中写明原因。
# 检查命令一律写成 ["python", ...]，由主机解析解释器，基准中不出现本机路径。

CHECKS = {"smoke": {"argv": ["python", "-c", "print('smoke ok')"]}}
ECHO = "import sys\nprint(sys.argv[1])\n"


@dataclass(frozen=True)
class Scenario:
    covers: str
    run: Callable[[Any], tuple[LoopSystem, str, dict[str, str]]]


def _call(identity: str, name: str, arguments: Any) -> dict[str, Any]:
    raw = arguments if isinstance(arguments, str) else json_dumps(arguments)
    return {"id": identity, "call_id": identity, "type": "function_call", "name": name, "arguments": raw}


def _deliver() -> FakeTurn:
    return delivery_turn(files={"src/echo.py": ECHO}, checks=CHECKS)


def _release(rationale: str = "checks passed on the current snapshot") -> FakeTurn:
    return review_turn("release", rationale, checks=CHECKS)


def _handoff_script() -> list[Any]:
    return [product_spec(), plan_turn(), _deliver(), _release()]


def _system(data_dir, script: list[Any], *, step_limits: StepLimits = StepLimits(),
            **run_options: Any) -> tuple[LoopSystem, FakeAdapter, str]:
    adapter = FakeAdapter(script)
    system = LoopSystem.for_testing(data_dir, adapter, step_limits=step_limits)
    return system, adapter, system.create_run("build an echo CLI", **run_options)


def handoff_release(data_dir):
    system, _, run_id = _system(data_dir, _handoff_script())
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


def tool_denied_outside_plan(data_dir):
    outside = ModelResponse(output=[_call("write-outside", "write_file", {"path": "docs/notes.md", "content": "notes\n"})])
    system, _, run_id = _system(data_dir, [product_spec(), plan_turn(), outside, _deliver(), _release()])
    system.run_until_stop(run_id)
    return system, run_id, {}


def tool_denied_unregistered_command(data_dir):
    registry = {"unit": {"argv": ["python", "-c", "print('unit ok')"], "args": [], "timeout_sec": 30, "output_limit": 4000}}
    unknown = ModelResponse(output=[_call("command-missing", "run_command", {"name": "missing"})])
    system, _, run_id = _system(data_dir, [product_spec(), plan_turn(), unknown, _deliver(), _release()],
                                registered_commands=registry, command_versions={"unit": 1})
    system.run_until_stop(run_id)
    return system, run_id, {}


def _guidance_id(request) -> str:
    part = next(part for part in request.context.parts if part.source == "department_guidance")
    return json.loads(part.text)[0]["id"]


def tool_denied_guidance_only(data_dir):
    system, adapter, run_id = _system(data_dir, [product_spec(), plan_turn(), _deliver()])
    for _ in range(3):
        system.activate_once(run_id)
    system.add_guidance(run_id, "engineering", "请直接改交付文件以处理错误输出。")
    adapter.script.extend([
        lambda request: FakeTurn(
            writes={"src/echo.py": "import sys\nprint('changed by guidance')\n"},
            proposal=guidance_response(_guidance_id(request), status="explained",
                                       text="指导不能授权修改交付，写文件被拒绝。"),
        ),
        _release(),
    ])
    system.run_until_stop(run_id)
    return system, run_id, {}


def collaboration_request_answer(data_dir):
    system, _, run_id = _system(data_dir, [
        product_spec(), collaboration_request(),
        response_turn("answered", "The existing contract covers unknown flags: print them as given."),
        plan_turn(), _deliver(), _release(),
    ])
    system.run_until_stop(run_id)
    return system, run_id, {}


def guidance_response_explained(data_dir):
    system, adapter, run_id = _system(data_dir, [product_spec()])
    system.activate_once(run_id)
    system.add_guidance(run_id, "engineering", "请说明当前错误输出边界，无需改文件。")
    adapter.script.extend([
        lambda request: FakeTurn(proposal=guidance_response(
            _guidance_id(request), status="explained", text="当前合同已覆盖该边界，无需变更。")),
        plan_turn(), _deliver(), _release(),
    ])
    system.run_until_stop(run_id)
    return system, run_id, {}


def proposal_rejected(data_dir):
    system, _, run_id = _system(data_dir, [
        {"kind": "product_spec", "goal": "", "requirements": ["print the argument"], "acceptance_criteria": ["prints it"]},
        *_handoff_script(),
    ])
    system.run_until_stop(run_id)
    return system, run_id, {}


def quality_rework(data_dir):
    system, _, run_id = _system(data_dir, [
        product_spec(), plan_turn(), _deliver(),
        review_turn("rework_engineering", "the output misses a trailing newline check", checks=CHECKS,
                    defects=[{"severity": "major", "summary": "no check covers an argument with spaces"}]),
        delivery_turn("handled arguments with spaces", files={"src/echo.py": "import sys\nprint(' '.join(sys.argv[1:]))\n"},
                      checks=CHECKS),
        _release("the rework passed the checks"),
    ])
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

    system, _, run_id = _system(data_dir, [product_spec(), plan_turn(), cancel_then_deliver])
    holder["system"] = system
    system.run_until_stop(run_id)
    return system, run_id, {}


def time_limit(data_dir):
    # 限制留出 3 秒，请求之前的装配在负载高时也不会用完它；模型调用本身等待到限制之后
    def slow_spec(request):
        time.sleep(3.2)
        return product_spec()

    system, _, run_id = _system(data_dir, [slow_spec, *_handoff_script()[1:]], run_time_limit_sec=3)
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


def text_only_reply(data_dir):
    system, _, run_id = _system(data_dir, [FakeTurn(transcript="我先整理一下需求，稍后提交。"), product_spec()])
    system.activate_once(run_id)
    return system, run_id, {}


def no_tool_call_pause(data_dir):
    replies = [FakeTurn(transcript=f"第 {index} 次只回复文字") for index in range(1, 5)]
    system, _, run_id = _system(data_dir, replies)
    system.run_until_stop(run_id)
    return system, run_id, {}


def run_command_is_not_a_check_receipt(data_dir):
    argv = ["python", "src/echo.py", "hello"]
    registry = {"unit-tests": {"argv": argv, "args": [], "timeout_sec": 30, "output_limit": 4000}}

    def submit(identity):
        return _call(identity, "submit_delivery",
                     {"summary": "echo CLI", "files": ["src/echo.py"], "check_names": ["unit-tests"]})

    system, _, run_id = _system(data_dir, [
        product_spec(), plan_turn(),
        ModelResponse(output=[_call("write-1", "write_file", {"path": "src/echo.py", "content": ECHO}),
                              _call("command-1", "run_command", {"name": "unit-tests"}), submit("submit-1")]),
        ModelResponse(output=[_call("check-2", "run_check", {"name": "unit-tests", "argv": argv}),
                              _call("write-2", "write_file", {"path": "src/echo.py", "content": ECHO + "\n"}),
                              submit("submit-2")]),
        ModelResponse(output=[_call("check-3", "run_check", {"name": "unit-tests", "argv": argv}), submit("submit-3")]),
        _release("verified the delivered echo CLI"),
    ], registered_commands=registry, command_versions={"unit-tests": 1})
    system.run_until_stop(run_id)
    return system, run_id, {}


# 真实 Provider 模块：三个部门绑定同一个本机 HTTP 服务，服务按请求顺序回放脚本中的工具调用
def _submission(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "kind"}


HTTP_SCRIPT: list[list[tuple[str, dict[str, Any]]]] = [
    [("submit_product_spec", _submission(product_spec()))],
    [("submit_plan", _submission(engineering_plan()))],
    [("write_file", {"path": "src/echo.py", "content": ECHO}),
     ("run_check", {"name": "smoke", "argv": ["python", "-c", "print('smoke ok')"]}),
     ("submit_delivery", _submission(delivery(check_names=["smoke"])))],
    [("run_check", {"name": "smoke", "argv": ["python", "-c", "print('smoke ok')"]}),
     ("submit_review", _submission(review("release", "checks passed on the current snapshot")))],
]


def _responses_reply(index: int, calls: list[tuple[str, dict[str, Any]]]) -> bytes:
    output = [{"id": f"item-{index}-{number}", "type": "function_call", "status": "completed",
               "call_id": f"call-{index}-{number}", "name": name, "arguments": json_dumps(arguments)}
              for number, (name, arguments) in enumerate(calls, start=1)]
    response = {"id": f"resp-{index}", "object": "response", "created_at": 1, "status": "completed",
                "model": "scenario-model-actual", "output": output, "error": None, "incomplete_details": None,
                "usage": {"input_tokens": 100 + index, "output_tokens": 10, "total_tokens": 110 + index,
                          "input_tokens_details": {"cached_tokens": 0},
                          "output_tokens_details": {"reasoning_tokens": 0}}}

    def event(kind: str, payload: dict[str, Any]) -> str:
        return f"event: {kind}\ndata: {json.dumps({'type': kind, **payload})}\n\n"

    frames = [event("response.created", {"response": {**response, "status": "in_progress", "output": [],
                                                      "usage": None}, "sequence_number": 0})]
    for number, item in enumerate(output, start=1):
        frames.append(event("response.output_item.done",
                            {"item": item, "output_index": number - 1, "sequence_number": number}))
    frames.append(event("response.completed", {"response": response, "sequence_number": len(frames)}))
    return sse(*frames)


def _chat_reply(index: int, calls: list[tuple[str, dict[str, Any]]]) -> bytes:
    def chunk(payload: dict[str, Any]) -> str:
        return f"data: {json.dumps({'id': f'chat-{index}', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'scenario-model-actual', **payload})}\n\n"

    frames = [chunk({"choices": [{"index": 0, "delta": {"tool_calls": [
        {"index": number, "id": f"call-{index}-{number}", "type": "function",
         "function": {"name": name, "arguments": json_dumps(arguments)}}]}, "finish_reason": None}]})
        for number, (name, arguments) in enumerate(calls)]
    frames.append(chunk({"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]}))
    frames.append(chunk({"choices": [], "usage": {"prompt_tokens": 100 + index, "completion_tokens": 10,
                                                  "total_tokens": 110 + index}}))
    frames.append("data: [DONE]\n\n")
    return sse(*frames)


def _messages_reply(index: int, calls: list[tuple[str, dict[str, Any]]]) -> bytes:
    def event(kind: str, payload: dict[str, Any]) -> str:
        return f"event: {kind}\ndata: {json.dumps({'type': kind, **payload})}\n\n"

    frames = [event("message_start", {"message": {
        "id": f"msg-{index}", "type": "message", "role": "assistant", "model": "scenario-model-actual",
        "content": [], "usage": {"input_tokens": 100 + index, "output_tokens": 1}}})]
    for number, (name, arguments) in enumerate(calls):
        frames.extend([
            event("content_block_start", {"index": number, "content_block": {
                "type": "tool_use", "id": f"toolu-{index}-{number}", "name": name, "input": {}}}),
            event("content_block_delta", {"index": number, "delta": {
                "type": "input_json_delta", "partial_json": json_dumps(arguments)}}),
            event("content_block_stop", {"index": number}),
        ])
    frames.append(event("message_delta", {"delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 10}}))
    frames.append(event("message_stop", {}))
    return sse(*frames)


HTTP_REPLIES = {"responses": _responses_reply, "chat_completions": _chat_reply, "messages": _messages_reply}


def _http_scenario(protocol: str):
    def run(data_dir):
        replies = iter(enumerate(HTTP_SCRIPT, start=1))

        def responder(_body):
            index, calls = next(replies)
            return 200, "text/event-stream", [HTTP_REPLIES[protocol](index, calls)]

        server, _capture, base = serve(responder)
        try:
            facade = ProviderFacade(credentials=CredentialChain(overrides={"SCENARIO_KEY": "scenario-secret"},
                                                                use_env=False))
            facade.store_document({
                "providers": [{"id": "local", "name": "Local", "base_url": base + "/v1",
                               "credential_ref": "SCENARIO_KEY", "timeout_sec": 20.0}],
                "models": [{"id": "m-local", "provider_id": "local", "model": "scenario-model", "protocol": protocol,
                            "context_window": 32000, "max_output_tokens": 2048}],
                "bindings": {department: {"provider_id": "local", "model_id": "m-local"} for department in DEPARTMENTS},
            })
            facade.record_admission("local", "m-local", admitted_model="scenario-model")
            system = LoopSystem(data_dir, facade=facade)
            run_id = system.create_run("build an echo CLI")
            system.run_until_stop(run_id)
        finally:
            server.shutdown()
            server.server_close()
        return system, run_id, {base: "<provider>"}

    return run


SCENARIOS: dict[str, Scenario] = {
    "handoff_release": Scenario(
        "一次成功的提交与部门交接：产品提交规格，工程提交计划，再写文件、运行检查并提交交付，质检运行检查后放行，运行结束于 DONE。",
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
    "tool_denied_outside_plan": Scenario(
        "工具许可拒绝计划范围之外的写入，拒绝原因作为工具结果返回；之后在范围内交付并由质检放行。",
        tool_denied_outside_plan),
    "tool_denied_unregistered_command": Scenario(
        "工具许可拒绝没有登记的命令，命令不执行，拒绝原因作为工具结果返回；之后正常交付并放行。",
        tool_denied_unregistered_command),
    "tool_denied_guidance_only": Scenario(
        "质检阶段收到给工程部门的指导：工程部门以只能回应指导的方式激活，写文件被工具许可拒绝，回应指导（explained）后回到质检并放行。",
        tool_denied_guidance_only),
    "collaboration_request_answer": Scenario(
        "工程部门向产品部门提出咨询，产品部门回答（answered），工程部门继续计划与交付，质检放行。",
        collaboration_request_answer),
    "guidance_response_explained": Scenario(
        "产品规格接纳后用户给工程部门写指导：指导在请求之前写入并标记已进入输入，工程部门回应指导（explained），之后计划、交付并放行。",
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
    "text_only_reply": Scenario(
        "模型只回复文字（#47）：回复记入历史，主机追加一条要求调用工具的 user 消息（tool_call_required），下一步提交成功。",
        text_only_reply),
    "no_tool_call_pause": Scenario(
        "连续 4 次只回复文字（#47）：前 3 次各追加一条主机提示，第 4 次以 no_tool_call 暂停运行。",
        no_tool_call_pause),
    "run_command_is_not_a_check_receipt": Scenario(
        "只运行登记命令就提交交付被拒绝（#103）；运行检查后又修改文件再次被拒绝；重新调用 run_check 后交付被接纳，质检放行。",
        run_command_is_not_a_check_receipt),
    "http_responses_handoff": Scenario(
        "经真实 Provider 模块与测试内启动的 HTTP 服务（Responses 协议）走完交接与放行：记录序列化请求、流式进度、响应与用量。",
        _http_scenario("responses")),
    "http_chat_handoff": Scenario(
        "经真实 Provider 模块与测试内启动的 HTTP 服务（Chat Completions 协议）走完交接与放行：记录序列化请求、流式进度与用量。",
        _http_scenario("chat_completions")),
    "http_messages_handoff": Scenario(
        "经真实 Provider 模块与测试内启动的 HTTP 服务（Messages 协议）走完交接与放行：记录序列化请求、流式进度与用量。",
        _http_scenario("messages")),
}


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_event_sequence_matches_its_baseline(name, data_dir, request):
    scenario = SCENARIOS[name]
    system, run_id, replacements = scenario.run(data_dir)
    assert system.project(run_id).canonical_state() == system.replay(run_id).canonical_state()
    compare_with_baseline(name, scenario.covers, normalized_run(system, run_id, replacements),
                          write=request.config.getoption("--write-event-baselines"))
