from __future__ import annotations

import json
import threading
from threading import Event
from urllib.parse import urlsplit, urlunsplit

import pytest

from harness.providers import (
    CredentialChain,
    ProviderFacade,
    anthropic_base_url,
    get_preset,
)
from harness.providers.errors import ProviderError
from harness.tests.protocol_helpers import (
    bound_target,
    chat_responder,
    facade_with,
    invoke,
    messages_responder,
    model_call,
    responses_responder,
    serve,
    sse,
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
    # 桥接层不能只认 Responses：Chat 与 Messages 目标同样可用
    from harness.adapters.facade_adapter import FacadeAdapter

    server, _capture, base = serve(chat_responder)
    try:
        facade = facade_with(base + "/v1", protocol="chat_completions")
        adapter = FacadeAdapter(facade, bound_target(facade))
        assert adapter.availability().available is True
    finally:
        server.shutdown()
        server.server_close()


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
                {"id": "go-a", "name": "Go 个人", "base_url": base_a + "/v1", "credential_ref": "GO_KEY_A",
                 "timeout_sec": 20.0, "preset_id": "opencode-go"},
                {"id": "go-b", "name": "Go 团队", "base_url": base_b + "/v1", "credential_ref": "GO_KEY_B",
                 "timeout_sec": 20.0, "preset_id": "opencode-go"},
            ],
            "models": [
                {"id": "m-a", "provider_id": "go-a", "model": "model-x", "protocol": "responses",
                 "context_window": 32000, "max_output_tokens": 2048},
                {"id": "m-b", "provider_id": "go-b", "model": "model-x", "protocol": "responses",
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
