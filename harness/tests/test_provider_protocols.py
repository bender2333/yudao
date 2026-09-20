from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event

import pytest

from harness.providers import (
    CredentialChain,
    ProviderFacade,
    ProviderInput,
    ProviderMessage,
    ToolSpec,
    anthropic_base_url,
    to_provider_input,
)
from harness.providers.errors import ProviderError


# 本地捕获服务：记录真实请求体与请求头，按协议回放流式响应
class _Capture:
    def __init__(self, responder) -> None:
        self.responder = responder
        self.requests: list[dict] = []
        self.headers: list[dict] = []
        self.paths: list[str] = []


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError):
            body = {"_raw": raw.decode("latin-1")}
        capture = self.server.capture
        capture.requests.append(body)
        capture.headers.append({key.lower(): value for key, value in self.headers.items()})
        capture.paths.append(self.path)
        status, content_type, chunks = capture.responder(body)
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.end_headers()
        for chunk in chunks:
            self.wfile.write(chunk)
            self.wfile.flush()


def _serve(responder):
    capture = _Capture(responder)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.capture = capture
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, capture, f"http://127.0.0.1:{server.server_address[1]}"


def _sse(*events: str) -> bytes:
    return "".join(events).encode("utf-8")


def _chat_responder(body: dict):
    model = body.get("model") or "gpt-x"
    def chunk(payload: dict) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    events = [
        chunk({"id": "chat-1", "object": "chat.completion.chunk", "created": 1, "model": model,
               "choices": [{"index": 0, "delta": {"tool_calls": [
                   {"index": 0, "id": "call-1", "type": "function",
                    "function": {"name": "write_file", "arguments": '{"path":'}}]}, "finish_reason": None}]}),
        chunk({"id": "chat-1", "object": "chat.completion.chunk", "created": 1, "model": model,
               "choices": [{"index": 0, "delta": {"tool_calls": [
                   {"index": 0, "function": {"arguments": ' "a.txt"}'}}]}, "finish_reason": "tool_calls"}]}),
        chunk({"id": "chat-1", "object": "chat.completion.chunk", "created": 1, "model": model,
               "choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17,
                                        "prompt_tokens_details": {"cached_tokens": 2}}}),
        "data: [DONE]\n\n",
    ]
    return 200, "text/event-stream", [_sse(*events)]


def _messages_responder(body: dict):
    model = body.get("model") or "claude-x"
    def event(kind: str, payload: dict) -> str:
        return f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
    events = [
        event("message_start", {"type": "message_start", "message": {
            "id": "msg-1", "type": "message", "role": "assistant", "model": model, "content": [],
            "usage": {"input_tokens": 11, "output_tokens": 1,
                      "cache_read_input_tokens": 3, "cache_creation_input_tokens": 2}}}),
        event("content_block_start", {"type": "content_block_start", "index": 0,
                                      "content_block": {"type": "tool_use", "id": "toolu-1",
                                                        "name": "write_file", "input": {}}}),
        event("content_block_delta", {"type": "content_block_delta", "index": 0,
                                      "delta": {"type": "input_json_delta",
                                                "partial_json": '{"path": "a.txt"}'}}),
        event("content_block_stop", {"type": "content_block_stop", "index": 0}),
        event("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use"},
                                "usage": {"output_tokens": 7}}),
        event("message_stop", {"type": "message_stop"}),
    ]
    return 200, "text/event-stream", [_sse(*events)]


def _responses_responder(body: dict):
    model = body.get("model") or "gpt-x"
    def event(kind: str, payload: dict) -> str:
        return f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
    item = {"id": "msg-1", "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": "ok"}]}
    events = [
        event("response.output_item.done", {"type": "response.output_item.done", "item": item}),
        event("response.completed", {"type": "response.completed", "response": {
            "id": "resp-1", "model": model, "status": "completed", "output": [item],
            "usage": {"input_tokens": 9, "output_tokens": 2, "total_tokens": 11}}}),
    ]
    return 200, "text/event-stream", [_sse(*events)]


def _facade_with(base_url: str, *, protocol: str, preset_id: str = "opencode-go",
                 model: str = "target-model") -> ProviderFacade:
    facade = ProviderFacade(credentials=CredentialChain(overrides={"GO_KEY": "local-secret"}))
    facade.store_document({
        "providers": [{
            "id": "go", "name": "Go", "base_url": base_url,
            "credential_ref": "GO_KEY", "timeout_sec": 20.0, "preset_id": preset_id,
        }],
        "models": [{
            "id": "m-go", "provider_id": "go", "model": model,
            "protocol": protocol, "context_window": 32000, "max_output_tokens": 2048,
            "capability_source": "preset-v1",
        }],
        "bindings": {},
    })
    return facade


def _target(facade: ProviderFacade):
    return facade.resolve_snapshot([{"key": "k", "provider_id": "go", "model_id": "m-go"}]).target("k")


def _input_with_tool(*, follow_up_result: str | None = None) -> ProviderInput:
    items = [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "请写文件"}]},
        {"type": "function_call", "call_id": "call-1", "name": "write_file",
         "arguments": '{"path": "a.txt"}'},
    ]
    if follow_up_result is not None:
        items.append({"type": "function_call_output", "call_id": "call-1", "output": follow_up_result})
    return ProviderInput(
        messages=(ProviderMessage(role="user", content="请写文件"),),
        tools=(ToolSpec(name="write_file", description="写文件",
                        parameters={"type": "object", "properties": {}}),),
        raw_request={"input": items, "tools": [{"name": "write_file", "description": "写文件",
                                                "parameters": {"type": "object", "properties": {}}}]},
        max_output_tokens=1024,
    )


def test_chat_wire_format_tool_round_trip_and_identity_headers():
    server, capture, base = _serve(_chat_responder)
    try:
        facade = _facade_with(base + "/v1", protocol="chat_completions")
        target = _target(facade)
        result = facade.invoke_once(
            target, _input_with_tool(), session_id="run-1:engineering", attempt_id="a1",
            abort_event=Event(),
        )
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
    assert result.actual_model == "target-model"
    assert result.usage["reported"] is True
    assert result.usage["input_tokens"] == 10
    assert result.usage["cache_read_tokens"] == 2
    assert result.usage["output_tokens"] == 5


def test_chat_sends_tool_result_paired_by_tool_call_id():
    server, capture, base = _serve(_chat_responder)
    try:
        facade = _facade_with(base + "/v1", protocol="chat_completions")
        facade.invoke_once(
            _target(facade), _input_with_tool(follow_up_result="已写入 a.txt"),
            session_id="run-1:engineering", attempt_id="a1", abort_event=Event(),
        )
    finally:
        server.shutdown()
        server.server_close()
    messages = capture.requests[0]["messages"]
    assert messages[-1] == {"role": "tool", "tool_call_id": "call-1", "content": "已写入 a.txt"}


def test_messages_wire_format_system_split_tool_round_trip_and_usage():
    server, capture, base = _serve(_messages_responder)
    try:
        facade = _facade_with(base + "/v1", protocol="messages")
        input_items = [
            {"type": "message", "role": "system", "content": [{"type": "input_text", "text": "部门指令"}]},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "请写文件"}]},
            {"type": "function_call", "call_id": "call-1", "name": "write_file",
             "arguments": '{"path": "a.txt"}'},
            {"type": "function_call_output", "call_id": "call-1", "output": "已写入"},
        ]
        provider_input = ProviderInput(
            messages=(ProviderMessage(role="user", content="请写文件"),),
            tools=(ToolSpec(name="write_file", description="写文件",
                            parameters={"type": "object"}),),
            raw_request={"input": input_items, "tools": [{"name": "write_file", "description": "写文件",
                                                          "parameters": {"type": "object"}}]},
            max_output_tokens=1024,
        )
        result = facade.invoke_once(
            _target(facade), provider_input, session_id="run-1:product",
            attempt_id="a1", abort_event=Event(),
        )
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
    assert result.usage["input_tokens"] == 11
    assert result.usage["cache_read_tokens"] == 3
    assert result.usage["cache_write_tokens"] == 2


def test_messages_requires_max_output_tokens_before_connecting():
    server, capture, base = _serve(_messages_responder)
    try:
        facade = _facade_with(base + "/v1", protocol="messages")
        provider_input = ProviderInput(
            messages=(ProviderMessage(role="user", content="hi"),), max_output_tokens=None,
        )
        with pytest.raises(ProviderError) as exc_info:
            facade.invoke_once(
                _target(facade), provider_input, session_id="s", attempt_id="a",
                abort_event=Event(),
            )
        assert exc_info.value.reason == "provider_protocol"
        assert capture.requests == []
    finally:
        server.shutdown()
        server.server_close()


def test_responses_requests_carry_identity_headers():
    server, capture, base = _serve(_responses_responder)
    try:
        facade = _facade_with(base + "/v1", protocol="responses")
        result = facade.invoke_once(
            _target(facade), to_provider_input([{"role": "user", "content": "hi"}]),
            session_id="run-2:quality", attempt_id="a1", abort_event=Event(),
        )
    finally:
        server.shutdown()
        server.server_close()
    assert capture.headers[0]["x-opencode-session"] == "run-2:quality"
    assert capture.headers[0]["user-agent"].startswith("Yudao-Loop-System/")
    assert result.text == "ok"


def test_facade_adapter_accepts_chat_targets():
    # 桥接层不能只认 Responses：Chat 与 Messages 目标同样可用
    from harness.adapters.facade_adapter import FacadeAdapter

    server, _capture, base = _serve(_chat_responder)
    try:
        facade = _facade_with(base + "/v1", protocol="chat_completions")
        adapter = FacadeAdapter(facade, _target(facade))
        assert adapter.availability().available is True
    finally:
        server.shutdown()
        server.server_close()


def test_model_test_uses_the_matching_execution_scope_for_chat():
    server, _capture, base = _serve(_chat_responder)
    try:
        facade = _facade_with(base + "/v1", protocol="chat_completions")
        result = facade.model_test("go", "m-go")
    finally:
        server.shutdown()
        server.server_close()
    assert result["ok"] is True
    assert result["admitted"] is True
    assert result["protocol"] == "chat_completions"
    stored = next(item for item in facade.providers_view()["models"] if item["id"] == "m-go")
    assert stored["admitted_revision"] == result["revision"]


def test_anthropic_base_url_does_not_duplicate_v1():
    assert anthropic_base_url("https://opencode.ai/zen/go/v1") == "https://opencode.ai/zen/go"
    assert anthropic_base_url("https://api.anthropic.com") == "https://api.anthropic.com"
    assert anthropic_base_url("https://gateway.example/anthropic/") == "https://gateway.example/anthropic"


def test_partial_stream_is_retryable():
    def responder(body: dict):
        # 只发一个事件就断开，模拟不完整流
        events = ['event: message_start\ndata: {"type":"message_start","message":{"id":"m","usage":{"input_tokens":1}}}\n\n']
        return 200, "text/event-stream", [_sse(*events)]

    server, _capture, base = _serve(responder)
    try:
        facade = _facade_with(base + "/v1", protocol="messages")
        with pytest.raises(ProviderError) as exc_info:
            facade.invoke_once(
                _target(facade),
                ProviderInput(messages=(ProviderMessage(role="user", content="hi"),), max_output_tokens=64),
                session_id="s", attempt_id="a", abort_event=Event(),
            )
        assert exc_info.value.reason in {"provider_error", "provider_protocol", "provider_timeout"}
    finally:
        server.shutdown()
        server.server_close()
