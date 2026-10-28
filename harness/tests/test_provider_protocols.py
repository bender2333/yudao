from __future__ import annotations

import json
import threading
from threading import Event

import pytest

from harness.watched_outputs import has_new_work
from harness.definitions import DEFINITIONS
from harness.engine import StepLimits
from harness.models import ArtifactRef, EventType
from harness.providers import CredentialChain, ProviderFacade
from harness.providers.errors import ProviderError
from harness.tests.helpers import FAST_RETRIES
from harness.tests.protocol_helpers import (
    ScriptedProvider,
    bound_target,
    chat_responder,
    facade_with,
    invoke,
    messages_responder,
    model_call,
    preset_base_urls,
    provider_system,
    responses_responder,
    send_reply,
    serve,
    sse,
)
from harness.tests.provider_replies import (
    BROKEN_STREAMS,
    PARTIAL_OUTPUT,
    empty_reply,
    product_spec_reply,
)

HI = [{"role": "user", "content": "hi"}]


def _call_with_tool(*, follow_up_result: str | None = None):
    items = [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "请写文件"}]},
        {"type": "function_call", "call_id": "call-1", "name": "write_file",
         "arguments": '{"path": "a.txt"}'},
    ]
    if follow_up_result is not None:
        items.append({"type": "function_call_output", "call_id": "call-1", "output": follow_up_result})
    return model_call(items, [{"name": "write_file", "description": "写文件",
                               "parameters": {"type": "object", "properties": {}}}],
                      max_output_tokens=1024, session_id="run-1:engineering", attempt_id="a1")


def test_chat_wire_format_tool_round_trip_and_identity_headers():
    server, capture, base = serve(chat_responder)
    with preset_base_urls(base + "/v1"):
        try:
            facade = facade_with(base + "/v1", protocol="chat_completions",
                                 preset_id="opencode-go")
            result = invoke(facade, bound_target(facade), _call_with_tool())
        finally:
            server.shutdown()
            server.server_close()
    body = capture.requests[0]
    assert capture.paths[0].endswith("/chat/completions")
    assert body["model"] == "target-model"
    assert body["stream"] is True
    assert body["messages"][0] == {"role": "user", "content": "请写文件"}
    assert body["tools"][0]["function"]["name"] == "write_file"
    headers = capture.headers[0]
    assert headers["x-opencode-session"] == "run-1:engineering"
    assert headers["user-agent"].startswith("Yudao-Loop-System/")
    call = next(item for item in result.output if item["type"] == "function_call")
    assert call["call_id"] == "call-1"
    assert call["name"] == "write_file"
    assert json.loads(call["arguments"]) == {"path": "a.txt"}
    assert result.model == "target-model"
    assert result.usage.reported is True
    assert result.usage.input_tokens == 10
    assert result.usage.cache_read_tokens == 2
    assert result.usage.output_tokens == 5


def test_messages_wire_format_system_split_tool_round_trip_and_usage():
    server, capture, base = serve(messages_responder)
    with preset_base_urls(base + "/v1"):
        try:
            facade = facade_with(base + "/v1", protocol="messages", preset_id="opencode-go")
            input_items = [
                {"type": "message", "role": "system", "content": [{"type": "input_text", "text": "部门指令"}]},
                {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "请写文件"}]},
                {"type": "function_call", "call_id": "call-1", "name": "write_file",
                 "arguments": '{"path": "a.txt"}'},
                {"type": "function_call_output", "call_id": "call-1", "output": "已写入"},
            ]
            call = model_call(input_items, [{"name": "write_file", "description": "写文件",
                                             "parameters": {"type": "object"}}],
                              max_output_tokens=1024, session_id="run-1:product", attempt_id="a1")
            result = invoke(facade, bound_target(facade), call)
        finally:
            server.shutdown()
            server.server_close()
    body = capture.requests[0]
    assert capture.paths[0] == "/v1/messages"
    assert body["system"] == "部门指令"
    assert all(message["role"] != "system" for message in body["messages"])
    assert body["max_tokens"] == 1024
    assert body["tools"][0]["input_schema"] == {"type": "object"}
    tool_use = body["messages"][1]["content"][0]
    assert tool_use["type"] == "tool_use"
    assert tool_use["id"] == "call-1"
    tool_result = body["messages"][2]["content"][0]
    assert tool_result == {"type": "tool_result", "tool_use_id": "call-1", "content": "已写入"}
    call = next(item for item in result.output if item["type"] == "function_call")
    assert call["call_id"] == "toolu-1"
    assert json.loads(call["arguments"]) == {"path": "a.txt"}
    assert capture.headers[0]["x-opencode-session"] == "run-1:product"
    assert result.usage.input_tokens == 11
    assert result.usage.cache_read_tokens == 3
    assert result.usage.cache_write_tokens == 2


def test_model_test_sends_reasoning_parameters_at_the_default_level():
    # 模型测试按该模型的默认档位发送推理参数（设计说明第 4.3、7.5 节）
    server, capture, base = serve(chat_responder)
    try:
        facade = facade_with(base + "/v1", protocol="chat_completions",
                             reasoning_levels=["low", "medium"], default_reasoning_level="medium",
                             reasoning_mode="effort")
        result = facade.model_test("go", "m-go")
    finally:
        server.shutdown()
        server.server_close()
    assert result["ok"] is True and result["admitted"] is True
    assert capture.requests[0]["reasoning_effort"] == "medium"


def test_chat_completions_sends_reasoning_effort_for_the_sent_tier():
    server, capture, base = serve(chat_responder)
    try:
        facade = facade_with(base + "/v1", protocol="chat_completions",
                             reasoning_levels=["low", "medium"], default_reasoning_level="low",
                             reasoning_mode="effort")
        target = bound_target(facade, requested_tier="minimal")
        invoke(facade, target, model_call(HI, max_output_tokens=64, session_id="s", attempt_id="a"))
    finally:
        server.shutdown()
        server.server_close()
    # 请求档位 minimal 没有不高于它的支持档位，取最低支持档位 low
    assert capture.requests[0]["reasoning_effort"] == "low"

def test_messages_adaptive_sends_thinking_and_output_config():
    server, capture, base = serve(messages_responder)
    try:
        facade = facade_with(base + "/v1", protocol="messages",
                             reasoning_levels=["low", "high"], default_reasoning_level="low",
                             reasoning_mode="adaptive")
        target = bound_target(facade, requested_tier="high")
        invoke(facade, target, model_call(HI, max_output_tokens=4096, session_id="s", attempt_id="a"))
    finally:
        server.shutdown()
        server.server_close()
    body = capture.requests[0]
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"] == {"effort": "high"}


def test_messages_budget_caps_tokens_at_output_limit_minus_reserve():
    # 预算不超过本次输出上限减 4000（设计说明第 7.4 节）
    server, capture, base = serve(messages_responder)
    try:
        facade = facade_with(base + "/v1", protocol="messages",
                             reasoning_levels=["high"], default_reasoning_level="high",
                             reasoning_mode="budget")
        target = bound_target(facade, requested_tier="high")
        invoke(facade, target, model_call(HI, max_output_tokens=10000, session_id="s", attempt_id="a"))
    finally:
        server.shutdown()
        server.server_close()
    assert capture.requests[0]["thinking"] == {"type": "enabled", "budget_tokens": 6000}

def test_messages_budget_is_not_sent_when_the_output_limit_cannot_hold_it():
    # 输出上限减 4000 以后容不下最低思考预算时不发送思考参数，交给上游按自身默认推理
    server, capture, base = serve(messages_responder)
    try:
        facade = facade_with(base + "/v1", protocol="messages",
                             reasoning_levels=["minimal"], default_reasoning_level="minimal",
                             reasoning_mode="budget")
        target = bound_target(facade, requested_tier="minimal")
        invoke(facade, target, model_call(HI, max_output_tokens=3000, session_id="s", attempt_id="a"))
    finally:
        server.shutdown()
        server.server_close()
    assert "thinking" not in capture.requests[0]

def test_undeclared_model_sends_no_reasoning_parameters():
    # 没有声明推理档位的模型，三种协议都不带推理参数
    for protocol, responder in (("responses", responses_responder),
                                ("chat_completions", chat_responder),
                                ("messages", messages_responder)):
        server, capture, base = serve(responder)
        try:
            facade = facade_with(base + "/v1", protocol=protocol)
            target = bound_target(facade, requested_tier="high")
            invoke(facade, target, model_call(HI, max_output_tokens=64, session_id="s", attempt_id="a"))
        finally:
            server.shutdown()
            server.server_close()
        body = capture.requests[0]
        assert "reasoning" not in body and "reasoning_effort" not in body and "thinking" not in body, protocol


def test_one_preset_connections_keep_their_own_credentials_and_identity():
    # 同一服务方案下两份连接：请求地址都取该方案按协议的基址（模型管理设计说明第 4.2 节），凭据与会话身份各自独立
    server, capture, base = serve(responses_responder)
    with preset_base_urls(base + "/v1"):
        try:
            facade = ProviderFacade(credentials=CredentialChain(
                overrides={"GO_KEY_A": "key-a", "GO_KEY_B": "key-b"}, use_env=False))
            facade.store_document({
                "providers": [
                    {"id": "go-a", "name": "Go 个人", "base_url": "http://127.0.0.1:1/v1",
                     "credential_ref": "GO_KEY_A", "timeout_sec": 20.0, "preset_id": "opencode-go"},
                    {"id": "go-b", "name": "Go 团队", "base_url": "http://127.0.0.1:1/v1",
                     "credential_ref": "GO_KEY_B", "timeout_sec": 20.0, "preset_id": "opencode-go"},
                ],
                "models": [
                    {"id": "m-a", "provider_id": "go-a", "model": "model-x",
                     "protocol": "responses",
                     "context_window": 32000, "max_output_tokens": 2048},
                    {"id": "m-b", "provider_id": "go-b", "model": "model-x",
                     "protocol": "responses",
                     "context_window": 32000, "max_output_tokens": 2048},
                ],
                "bindings": {},
            })
            snapshot = facade.resolve_snapshot([
                {"key": "a", "provider_id": "go-a", "model_id": "m-a"},
                {"key": "b", "provider_id": "go-b", "model_id": "m-b"},
            ])
            for key in ("a", "b"):
                invoke(facade, snapshot.target(key),
                       model_call(HI, session_id=f"session-{key}", attempt_id=f"attempt-{key}"))
        finally:
            server.shutdown()
            server.server_close()
    assert len(capture.requests) == 2
    assert {item["authorization"] for item in capture.headers} == {"Bearer key-a", "Bearer key-b"}
    assert {item["x-opencode-session"] for item in capture.headers} == {"session-a", "session-b"}
    assert capture.headers[0]["user-agent"].startswith("Yudao-Loop-System/")


def test_concurrent_model_tests_of_one_model_both_admit():
    # Web 服务是多线程的：同一个模型的第一次模型测试还在等待提供方时发起第二次，两次都通过并记录准入
    first_held = Event()
    release = Event()

    def gated(body: dict):
        if not first_held.is_set():
            first_held.set()
            release.wait(60)
        return responses_responder(body)

    server, capture, base = serve(gated)
    results: dict[str, dict] = {}
    try:
        facade = facade_with(base + "/v1", protocol="responses")
        worker = threading.Thread(target=lambda: results.setdefault("first", facade.model_test("go", "m-go")))
        worker.start()
        assert first_held.wait(30)
        results["second"] = facade.model_test("go", "m-go")
        release.set()
        worker.join(60)
        assert not worker.is_alive()
    finally:
        release.set()
        server.shutdown()
        server.server_close()
    assert [results[key]["ok"] for key in ("first", "second")] == [True, True], results
    assert [results[key]["admitted"] for key in ("first", "second")] == [True, True]
    assert len(capture.requests) == 2
    # 两次测试都通过，准入记录只有一份且与目录分开保存（工单 #86）
    stored = next(item for item in facade.model_admissions() if item["model_id"] == "m-go")
    assert stored["admitted_at"] is not None
    assert stored["admitted"] is True
    assert len(facade.model_admissions()) == 1


@pytest.mark.parametrize(("protocol", "responder"), [
    ("chat_completions", chat_responder),
    ("messages", messages_responder),
])
def test_cancel_stops_only_the_active_attempt(protocol, responder):
    # 取消作用于进行中的这一次调用尝试；随后同一目标的新尝试照常完成
    held = Event()
    release = Event()

    def gated(body: dict):
        if body.get("max_tokens") == 7:
            held.set()
            release.wait(10)
        return responder(body)

    server, capture, base = serve(gated)
    outcome: dict[str, str] = {}
    try:
        facade = facade_with(base + "/v1", protocol=protocol)
        target = bound_target(facade)

        def held_call() -> None:
            try:
                invoke(facade, target, model_call([{"role": "user", "content": "hold"}], max_output_tokens=7,
                                                  session_id="s", attempt_id="held"))
            except ProviderError as exc:
                outcome["reason"] = exc.reason

        worker = threading.Thread(target=held_call)
        worker.start()
        assert held.wait(5)
        assert facade.cancel("held") is True
        worker.join(5)
        assert not worker.is_alive()
        result = invoke(facade, target, model_call([{"role": "user", "content": "next"}], max_output_tokens=64,
                                                   session_id="s", attempt_id="next"))
    finally:
        release.set()
        server.shutdown()
        server.server_close()
    assert outcome == {"reason": "cancelled"}
    assert any(item["type"] == "function_call" for item in result.output)


@pytest.mark.parametrize(("protocol", "first_event"), [
    ("chat_completions", 'data: {"id":"c","object":"chat.completion.chunk","created":1,"model":"m",'
                         '"choices":[{"index":0,"delta":{"content":"par"},"finish_reason":null}]}\n\n'),
    ("messages", 'event: message_start\ndata: {"type":"message_start","message":{"id":"m","usage":{"input_tokens":1}}}\n\n'),
])
def test_stream_without_terminal_event_is_a_retryable_failure(protocol, first_event):
    # 流在结束事件前断开：报可重试失败，不把部分输出当作完成
    server, _capture, base = serve(lambda body: (200, "text/event-stream", [sse(first_event)]))
    try:
        facade = facade_with(base + "/v1", protocol=protocol)
        with pytest.raises(ProviderError) as exc_info:
            invoke(facade, bound_target(facade), model_call(HI, max_output_tokens=64, session_id="s", attempt_id="a"))
    finally:
        server.shutdown()
        server.server_close()
    assert exc_info.value.retryable is True
    assert exc_info.value.diagnostics["error_type"] == "stream_incomplete"


# 接收回复体时连接中途断开：三种协议的诊断相同，写明实际的传输阶段与事件
BROKEN_BODY_DIAGNOSTICS = {
    "error_type": "connection", "trace_available": True, "transport_phase": "receive_response_body",
    "transport_event": "http11.receive_response_body.failed", "cause_type": "RemoteProtocolError",
}

# 断开的流与之后成功的回复中，提供方给出的回答身份
BROKEN_RESPONSE_IDS = {"responses": "resp-broken", "chat_completions": "chat-broken", "messages": "msg-broken"}
REPLY_RESPONSE_IDS = {"responses": "resp-1", "chat_completions": "chat-1", "messages": "msg-1"}


@pytest.mark.parametrize("protocol", ["responses", "chat_completions", "messages"])
def test_stream_broken_midway_is_a_retryable_connection_failure_and_the_retry_succeeds(protocol, data_dir):
    # 流式回复送出一段输出之后连接中途断开（D17）：尝试记为可重试的连接失败，诊断写明传输阶段与事件，安排重试，
    # 第二次成功；已收到的部分输出只在失败尝试的审计记录中，不进入重试请求。
    # 失败与成功的尝试都记录提供方回答身份与第一次输出的时间
    provider = ScriptedProvider([BROKEN_STREAMS[protocol], product_spec_reply(protocol)])
    try:
        system, run_id = provider_system(data_dir, provider.base, protocol, step_limits=FAST_RETRIES)
        try:
            result = system.activate_once(run_id)
            events = system.store.list_events(run_id)
            failed = [event for event in events if event.type == EventType.MODEL_ATTEMPT_FAILED]
            finished = [event for event in events if event.type == EventType.MODEL_ATTEMPT_FINISHED]
            scheduled = [event for event in events if event.type == EventType.MODEL_RETRY_SCHEDULED]
            audits = [system.artifacts.get_for_run(run_id, ArtifactRef(**event.payload["stream_events_ref"]))
                      .decode("utf-8") for event in failed]
        finally:
            system.close()
    finally:
        provider.close()
    assert has_new_work(result, "engineering"), result.error
    assert [event.error for event in failed] == ["Model provider connection failed"]
    assert failed[0].payload["reason"] == "provider_error"
    assert failed[0].payload["retryable"] is True and failed[0].payload["will_retry"] is True
    assert failed[0].payload["diagnostics"] == BROKEN_BODY_DIAGNOSTICS
    assert failed[0].payload["provider_response_id"] == BROKEN_RESPONSE_IDS[protocol]
    assert failed[0].payload["stream_first_output_at"] is not None
    assert len(finished) == 1
    assert finished[0].payload["provider_response_id"] == REPLY_RESPONSE_IDS[protocol]
    assert finished[0].payload["stream_first_output_at"] is not None
    assert len(scheduled) == 1
    assert PARTIAL_OUTPUT in audits[0]
    assert len(provider.requests) == 2
    assert PARTIAL_OUTPUT not in json.dumps(provider.requests[1])


def _messages_stream_error(error_type: str):
    # Messages 的流送出 message_start 之后送出 event: error（Anthropic 的错误以 type 区分）
    def reply(_provider: ScriptedProvider, handler) -> None:
        start = {"type": "message_start", "message": {
            "id": "msg-stream-error", "type": "message", "role": "assistant", "model": "scenario-model-actual",
            "content": [], "usage": {"input_tokens": 100, "output_tokens": 1}}}
        error = {"type": "error", "error": {"type": error_type, "message": "scenario stream error"}}
        body = sse(f"event: message_start\ndata: {json.dumps(start)}\n\n",
                   f"event: error\ndata: {json.dumps(error)}\n\n")
        send_reply(handler, 200, "text/event-stream", body)

    return reply


@pytest.mark.parametrize(("error_type", "retryable"), [
    ("overloaded_error", True),
    ("api_error", True),
    ("invalid_request_error", False),
    ("authentication_error", False),
])
def test_messages_stream_error_event_is_classified_by_its_type(error_type, retryable, data_dir):
    # Anthropic SDK 把流中的 event: error 转换成状态码为 200 的错误：按错误的 type 分类，过载与服务端错误可以重试，
    # 与 Responses 流中的 server_is_overloaded 相同；参数与认证错误不重试。错误事件同样记入流式记录
    provider = ScriptedProvider([_messages_stream_error(error_type), product_spec_reply("messages")])
    try:
        system, run_id = provider_system(data_dir, provider.base, "messages", step_limits=FAST_RETRIES)
        try:
            result = system.activate_once(run_id)
            events = system.store.list_events(run_id)
            failed = [event for event in events if event.type == EventType.MODEL_ATTEMPT_FAILED]
            scheduled = [event for event in events if event.type == EventType.MODEL_RETRY_SCHEDULED]
        finally:
            system.close()
    finally:
        provider.close()
    assert [event.error for event in failed] == ["Model provider reported a stream error"]
    assert failed[0].payload["reason"] == "provider_error"
    assert failed[0].payload["retryable"] is retryable
    assert failed[0].payload["will_retry"] is retryable
    assert failed[0].payload["diagnostics"] == {"error_code": error_type}
    assert failed[0].payload["provider_response_id"] == "msg-stream-error"
    assert failed[0].payload["stream_last_stage"] == "error"
    if retryable:
        assert has_new_work(result, "engineering"), result.error
        assert len(scheduled) == 1
        assert len(provider.requests) == 2
    else:
        assert scheduled == []
        assert len(provider.requests) == 1


@pytest.mark.parametrize("protocol", ["responses", "chat_completions", "messages"])
@pytest.mark.parametrize("status", [401, 403])
def test_credential_rejection_is_unavailable_and_never_retried(protocol, status):
    # 上游拒绝凭据（HTTP 401、403）：状态本身就是凭据拒绝事实，错误体不可信只做诊断；
    # 记为不可重试的 provider_unavailable，上游修复凭据后由待恢复继续
    secret = "credential-that-provider-echoed"

    def rejected(_provider: ScriptedProvider, handler) -> None:
        body = json.dumps({"error": {"code": "server_error", "type": "server_error",
                                     "message": secret, "param": "store"}})
        send_reply(handler, status, "application/json", body.encode("utf-8"))

    provider = ScriptedProvider([rejected])
    key = "local-secret"
    try:
        facade = facade_with(provider.base + "/v1", protocol=protocol)
        target = bound_target(facade)
        key = target.api_key
        with pytest.raises(ProviderError) as caught:
            invoke(facade, target, model_call(HI, max_output_tokens=64, session_id="s", attempt_id="a"))
    finally:
        provider.close()
    error = caught.value
    assert error.reason == "provider_unavailable"
    assert error.retryable is False
    assert f"HTTP {status}" in str(error)
    assert secret not in str(error) and secret not in json.dumps(error.diagnostics, ensure_ascii=False)
    assert key not in str(error) and key not in json.dumps(error.diagnostics, ensure_ascii=False)
    assert error.diagnostics["status_code"] == status
    assert error.diagnostics["request_observation_id"] == "a"
    assert len(provider.requests) == 1


# 空输出（工单 #305）：流正常结束、没有任何可见输出项。结束原因按各协议自己的写法给出，
# Responses 走 completed 且 incomplete_details 为空，Chat 与 Messages 各用一个终态结束原因
EMPTY_OUTPUT_FINISH_REASONS = {"responses": "completed", "chat_completions": "length",
                               "messages": "max_tokens"}


@pytest.mark.parametrize("protocol", ["responses", "chat_completions", "messages"])
def test_reasoning_only_reply_counts_as_empty_output(protocol):
    # 只有推理内容的回复：推理不是可见输出，仍然按空输出处理，诊断写明出现过推理内容
    provider = ScriptedProvider([empty_reply(protocol, reasoning="先看代码再决定。")])
    try:
        facade = facade_with(provider.base + "/v1", protocol=protocol)
        with pytest.raises(ProviderError) as caught:
            invoke(facade, bound_target(facade),
                   model_call(HI, max_output_tokens=2048, session_id="s", attempt_id="a"))
    finally:
        provider.close()
    assert caught.value.reason == "empty_output"
    assert caught.value.diagnostics["has_reasoning"] is True
    assert caught.value.diagnostics["finish_reason"] == EMPTY_OUTPUT_FINISH_REASONS[protocol]


@pytest.mark.parametrize("protocol", ["responses", "chat_completions", "messages"])
def test_empty_output_is_retried_and_the_run_continues(protocol, data_dir):
    # 空输出按 D17 安排重试：第二次正常回复，事项照常推进到下一个部门
    provider = ScriptedProvider([empty_reply(protocol), product_spec_reply(protocol)])
    try:
        system, run_id = provider_system(data_dir, provider.base, protocol, step_limits=FAST_RETRIES)
        try:
            result = system.activate_once(run_id)
            events = system.store.list_events(run_id)
        finally:
            system.close()
    finally:
        provider.close()
    failed = [event for event in events if event.type == EventType.MODEL_ATTEMPT_FAILED]
    assert has_new_work(result, "engineering"), result.error
    assert len(failed) == 1
    assert failed[0].payload["reason"] == "empty_output"
    assert failed[0].payload["retryable"] is True and failed[0].payload["will_retry"] is True
    assert failed[0].payload["diagnostics"]["error_type"] == "empty_output"
    assert len(provider.requests) == 2


@pytest.mark.parametrize("protocol", ["responses", "chat_completions", "messages"])
def test_repeated_empty_output_stops_the_run_as_a_provider_failure_without_pausing(protocol, data_dir):
    # 空输出一直重试用完：沿用已有的模型服务故障处理，运行失败而不是以 no_tool_call 暂停
    # 停止原因清单（D09）不新增取值，empty_output 在重试用完之后按 provider_error 记
    provider = ScriptedProvider([empty_reply(protocol) for _ in range(DEFINITIONS.rule_value("max_provider_attempts"))])
    try:
        system, run_id = provider_system(data_dir, provider.base, protocol,
                                         step_limits=StepLimits(max_provider_attempts=1))
        try:
            result = system.activate_once(run_id)
            events = system.store.list_events(run_id)
        finally:
            system.close()
    finally:
        provider.close()
    assert result.status == "failed" and result.stop_reason == "provider_error"
    assert result.stop_reason in DEFINITIONS.stop_reasons
    failed = [event for event in events if event.type == EventType.MODEL_ATTEMPT_FAILED]
    assert len(failed) == 1
    assert failed[0].payload["reason"] == "empty_output"
    assert failed[0].payload["will_retry"] is False
    assert not [event for event in events if event.type == EventType.MODEL_RETRY_SCHEDULED]
    assert not [event for event in events if event.type == EventType.RUN_PAUSED]
    assert len(provider.requests) == 1

