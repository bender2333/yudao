from __future__ import annotations

import json
import threading
from threading import Event
from urllib.parse import urlsplit, urlunsplit

import pytest

from harness.models import ArtifactRef, EventType
from harness.providers import (
    CredentialChain,
    ProviderFacade,
    anthropic_base_url,
    get_preset,
)
from harness.providers.errors import ProviderError
from harness.tests.helpers import FAST_RETRIES
from harness.tests.protocol_helpers import (
    ScriptedProvider,
    bound_target,
    chat_responder,
    complete,
    facade_with,
    invoke,
    messages_responder,
    model_call,
    provider_system,
    responses_responder,
    send_reply,
    serve,
    sse,
)
from harness.tests.test_event_sequence import BROKEN_STREAMS, PARTIAL_OUTPUT, product_spec_reply

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
    try:
        facade = facade_with(base + "/v1", protocol="chat_completions")
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


def test_chat_chunk_identity_that_is_not_a_string_is_not_recorded():
    # OpenAI 兼容服务给出数字形式的块 id：SDK 不校验字段类型，调用照常完成，不记录回答身份
    def numeric_identity(body: dict):
        status, content_type, chunks = chat_responder(body)
        return status, content_type, [chunk.replace(b'"id": "chat-1"', b'"id": 7') for chunk in chunks]

    server, _capture, base = serve(numeric_identity)
    events = []
    try:
        facade = facade_with(base + "/v1", protocol="chat_completions")
        result = invoke(facade, bound_target(facade), _call_with_tool(), observe=events.append)
    finally:
        server.shutdown()
        server.server_close()
    streamed = [event for event in events if event.kind == "stream_event"]
    assert streamed and all(event.payload["id"] == 7 and event.response_id is None for event in streamed)
    assert result.response_id is None
    assert any(item["type"] == "function_call" for item in result.output)


def test_chat_sends_tool_result_paired_by_tool_call_id():
    server, capture, base = serve(chat_responder)
    try:
        facade = facade_with(base + "/v1", protocol="chat_completions")
        invoke(facade, bound_target(facade), _call_with_tool(follow_up_result="已写入 a.txt"))
    finally:
        server.shutdown()
        server.server_close()
    messages = capture.requests[0]["messages"]
    assert messages[-1] == {"role": "tool", "tool_call_id": "call-1", "content": "已写入 a.txt"}


def test_messages_wire_format_system_split_tool_round_trip_and_usage():
    server, capture, base = serve(messages_responder)
    try:
        facade = facade_with(base + "/v1", protocol="messages")
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


def test_messages_requires_max_output_tokens_before_connecting():
    server, capture, base = serve(messages_responder)
    try:
        facade = facade_with(base + "/v1", protocol="messages")
        with pytest.raises(ProviderError) as exc_info:
            invoke(facade, bound_target(facade), model_call(HI, max_output_tokens=None, session_id="s", attempt_id="a"))
        assert exc_info.value.reason == "provider_protocol"
        assert capture.requests == []
    finally:
        server.shutdown()
        server.server_close()


def test_responses_requests_carry_identity_headers():
    server, capture, base = serve(responses_responder)
    try:
        facade = facade_with(base + "/v1", protocol="responses")
        result = invoke(facade, bound_target(facade), model_call(HI, session_id="run-2:quality", attempt_id="a1"))
    finally:
        server.shutdown()
        server.server_close()
    assert capture.headers[0]["x-opencode-session"] == "run-2:quality"
    assert capture.headers[0]["user-agent"].startswith("Yudao-Loop-System/")
    assert result.output[0]["content"][0]["text"] == "ok"


def test_facade_adapter_accepts_chat_targets():
    # 桥接层不能只认 Responses：Chat 与 Messages 目标同样可用；目标由公开解析入口登记
    from harness.tests.protocol_helpers import bound_adapter

    server, _capture, base = serve(chat_responder)
    try:
        facade = facade_with(base + "/v1", protocol="chat_completions")
        adapter = bound_adapter(facade)
        assert adapter.availability().available is True
        response = complete(adapter, model_call(HI, max_output_tokens=64, session_id="s", attempt_id="a"))
    finally:
        server.shutdown()
        server.server_close()
    assert [item["name"] for item in response.output] == ["write_file"]


def test_model_test_admits_a_chat_model():
    server, _capture, base = serve(chat_responder)
    try:
        facade = facade_with(base + "/v1", protocol="chat_completions")
        result = facade.model_test("go", "m-go")
    finally:
        server.shutdown()
        server.server_close()
    assert result["ok"] is True
    assert result["admitted"] is True
    assert result["protocol"] == "chat_completions"
    stored = next(item for item in facade.providers_view()["models"] if item["id"] == "m-go")
    assert stored["admitted_revision"] == result["revision"]


@pytest.mark.parametrize(("protocol", "responder", "official"), [
    ("responses", responses_responder, "https://opencode.ai/zen/go/v1/responses"),
    ("chat_completions", chat_responder, "https://opencode.ai/zen/go/v1/chat/completions"),
    ("messages", messages_responder, "https://opencode.ai/zen/go/v1/messages"),
])
def test_go_preset_base_url_reaches_the_official_protocol_path(protocol, responder, official):
    # 预置表按协议给出请求基址，适配器拼接协议路径后与官方端点一致
    base = get_preset("opencode-go")["base_urls"][protocol]
    server, capture, local = serve(responder)
    try:
        local_base = urlunsplit(urlsplit(base)._replace(scheme="http", netloc=urlsplit(local).netloc))
        facade = facade_with(local_base, protocol=protocol)
        invoke(facade, bound_target(facade), model_call(HI, max_output_tokens=64, session_id="s", attempt_id="a"))
    finally:
        server.shutdown()
        server.server_close()
    assert urlsplit(base).scheme == "https"
    assert urlsplit(base).netloc == urlsplit(official).netloc
    assert capture.paths[0] == urlsplit(official).path


def test_one_preset_supports_independent_connections_with_own_address_and_key():
    # 同一服务方案下两份连接：地址与凭据各自独立，都带该方案要求的身份头
    server_a, capture_a, base_a = serve(responses_responder)
    server_b, capture_b, base_b = serve(responses_responder)
    try:
        facade = ProviderFacade(credentials=CredentialChain(
            overrides={"GO_KEY_A": "key-a", "GO_KEY_B": "key-b"}, use_env=False))
        facade.store_document({
            "providers": [
                {"id": "go-a", "name": "Go 个人", "protocol": "responses", "base_url": base_a + "/v1",
                 "credential_ref": "GO_KEY_A", "timeout_sec": 20.0, "preset_id": "opencode-go"},
                {"id": "go-b", "name": "Go 团队", "protocol": "responses", "base_url": base_b + "/v1",
                 "credential_ref": "GO_KEY_B", "timeout_sec": 20.0, "preset_id": "opencode-go"},
            ],
            "models": [
                {"id": "m-a", "provider_id": "go-a", "model": "model-x",
                 "context_window": 32000, "max_output_tokens": 2048},
                {"id": "m-b", "provider_id": "go-b", "model": "model-x",
                 "context_window": 32000, "max_output_tokens": 2048},
            ],
            "bindings": {},
        })
        snapshot = facade.resolve_snapshot([
            {"key": "a", "provider_id": "go-a", "model_id": "m-a"},
            {"key": "b", "provider_id": "go-b", "model_id": "m-b"},
        ])
        for key in ("a", "b"):
            invoke(facade, snapshot.target(key), model_call(HI, session_id=f"session-{key}", attempt_id=f"attempt-{key}"))
    finally:
        for server in (server_a, server_b):
            server.shutdown()
            server.server_close()
    assert len(capture_a.requests) == 1 and len(capture_b.requests) == 1
    assert capture_a.headers[0]["authorization"] == "Bearer key-a"
    assert capture_b.headers[0]["authorization"] == "Bearer key-b"
    assert capture_a.headers[0]["x-opencode-session"] == "session-a"
    assert capture_b.headers[0]["x-opencode-session"] == "session-b"
    assert capture_a.headers[0]["user-agent"].startswith("Yudao-Loop-System/")


def test_model_test_uses_its_own_diagnostic_session():
    # 模型测试使用独立诊断会话，不借用任何任务部门的会话身份
    server, capture, base = serve(messages_responder)
    try:
        facade = facade_with(base + "/v1", protocol="messages")
        result = facade.model_test("go", "m-go")
    finally:
        server.shutdown()
        server.server_close()
    assert result["ok"] is True
    assert capture.headers[0]["x-opencode-session"] == "diagnostic:go:m-go"


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
    stored = next(item for item in facade.providers_view()["models"] if item["id"] == "m-go")
    assert stored["admitted_at"] is not None
    assert stored["admitted_revision"] == max(results[key]["revision"] for key in ("first", "second"))


def test_anthropic_base_url_does_not_duplicate_v1():
    assert anthropic_base_url("https://opencode.ai/zen/go/v1") == "https://opencode.ai/zen/go"
    assert anthropic_base_url("https://api.anthropic.com") == "https://api.anthropic.com"
    assert anthropic_base_url("https://gateway.example/anthropic/") == "https://gateway.example/anthropic"


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


def test_cancel_before_start_holds_only_within_the_activation():
    # 取消到达时尝试还没有开始：同一次激活（同一个适配器）内这次尝试一开始就被取消，请求不发出，其他尝试照常；
    # 取消记在随激活创建的适配器上，激活结束时没有开始的尝试不影响之后以同一身份开始的尝试
    from harness.adapters.base import ProviderError as KernelProviderError
    from harness.tests.protocol_helpers import bound_adapter

    server, capture, base = serve(responses_responder)
    try:
        facade = facade_with(base + "/v1", protocol="responses")
        cancelled = model_call(HI, session_id="s", attempt_id="activation:root-1:work:attempt-1")
        never_started = model_call(HI, session_id="s", attempt_id="activation:root-2:work:attempt-1")
        other = model_call(HI, session_id="s", attempt_id="activation:root-3:work:attempt-1")
        activation = bound_adapter(facade)
        activation.cancel(cancelled.attempt_id)
        with pytest.raises(KernelProviderError) as caught:
            complete(activation, cancelled)
        assert caught.value.reason == "cancelled"
        assert capture.requests == []
        activation.cancel(never_started.attempt_id)
        assert complete(activation, other).output
        assert complete(bound_adapter(facade), never_started).output
    finally:
        server.shutdown()
        server.server_close()
    assert len(capture.requests) == 2


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
    assert result.phase == "ENGINEERING", result.error
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


def _broken_error_reply(_provider: ScriptedProvider, handler) -> None:
    # HTTP 500 的错误回复体没有送完连接就关闭
    body = b'{"error": {"code": "server_error", "type": "server_error", "message": "partial'
    send_reply(handler, 500, "application/json", body, declared_length=len(body) + 4096)


@pytest.mark.parametrize("protocol", ["responses", "chat_completions", "messages"])
def test_error_reply_broken_while_the_request_is_created_is_a_retryable_connection_failure(protocol):
    # 创建请求时提供方回复 HTTP 500，SDK 读取错误回复体时连接中途断开：三种协议在创建请求阶段按同样的传输错误分类，
    # 记为可重试的连接失败，诊断写明传输阶段与事件
    provider = ScriptedProvider([_broken_error_reply])
    try:
        facade = facade_with(provider.base + "/v1", protocol=protocol)
        with pytest.raises(ProviderError) as caught:
            invoke(facade, bound_target(facade), model_call(HI, max_output_tokens=64, session_id="s", attempt_id="a"))
    finally:
        provider.close()
    assert str(caught.value) == "Model provider connection failed"
    assert caught.value.reason == "provider_error"
    assert caught.value.retryable is True
    assert caught.value.diagnostics == BROKEN_BODY_DIAGNOSTICS
    assert len(provider.requests) == 1


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
        assert result.phase == "ENGINEERING", result.error
        assert len(scheduled) == 1
        assert len(provider.requests) == 2
    else:
        assert scheduled == []
        assert len(provider.requests) == 1


def test_messages_http_error_code_is_read_from_the_anthropic_error_type():
    # Anthropic 的错误回复以 error.type 给出错误码
    def overloaded(_provider: ScriptedProvider, handler) -> None:
        body = json.dumps({"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})
        send_reply(handler, 529, "application/json", body.encode("utf-8"))

    provider = ScriptedProvider([overloaded])
    try:
        facade = facade_with(provider.base + "/v1", protocol="messages")
        with pytest.raises(ProviderError) as caught:
            invoke(facade, bound_target(facade), model_call(HI, max_output_tokens=64, session_id="s", attempt_id="a"))
    finally:
        provider.close()
    assert caught.value.retryable is True
    assert caught.value.diagnostics == {"status_code": 529, "request_observation_id": "a",
                                        "error_code": "overloaded_error"}


@pytest.mark.parametrize("protocol", ["responses", "chat_completions", "messages"])
def test_request_the_client_refuses_to_send_is_not_retryable(protocol):
    # 会话标识中的换行使请求头不合法，客户端在发出之前拒绝（LocalProtocolError）：openai 的客户端经 httpx、
    # anthropic 的客户端经 httpx2 报告，都记为不可重试的协议错误，请求没有到达服务
    server, capture, base = serve(lambda _body: (200, "text/event-stream", [b""]))
    try:
        facade = facade_with(base + "/v1", protocol=protocol)
        with pytest.raises(ProviderError) as caught:
            invoke(facade, bound_target(facade),
                   model_call(HI, max_output_tokens=64, session_id="run-1\nproduct", attempt_id="a"))
    finally:
        server.shutdown()
        server.server_close()
    assert caught.value.retryable is False
    assert caught.value.diagnostics == {"error_type": "provider_protocol"}
    assert capture.requests == []


def test_partial_stream_is_retryable():
    def responder(body: dict):
        # 只发一个事件就断开，模拟不完整流
        events = ['event: message_start\ndata: {"type":"message_start","message":{"id":"m","usage":{"input_tokens":1}}}\n\n']
        return 200, "text/event-stream", [sse(*events)]

    server, _capture, base = serve(responder)
    try:
        facade = facade_with(base + "/v1", protocol="messages")
        with pytest.raises(ProviderError) as exc_info:
            invoke(facade, bound_target(facade), model_call(HI, max_output_tokens=64, session_id="s", attempt_id="a"))
        assert exc_info.value.reason in {"provider_error", "provider_protocol", "provider_timeout"}
    finally:
        server.shutdown()
        server.server_close()


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
