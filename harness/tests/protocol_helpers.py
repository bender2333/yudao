from __future__ import annotations

import json
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from harness.adapters.base import Availability, ModelAdapter, ModelRequest, ModelResponse, ProviderError
from harness.adapters.facade_adapter import FacadeAdapter
from harness.providers import (
    CredentialChain,
    FrozenTarget,
    ProviderFacade,
    ResponsesConfig,
    ResponsesExecutionScope,
    check_availability,
)


# 本地捕获服务：记录真实请求体与请求头，按协议回放流式响应
class Capture:
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


def serve(responder) -> tuple[ThreadingHTTPServer, Capture, str]:
    capture = Capture(responder)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.capture = capture
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, capture, f"http://127.0.0.1:{server.server_address[1]}"


def sse(*events: str) -> bytes:
    return "".join(events).encode("utf-8")


def chat_responder(body: dict):
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
    return 200, "text/event-stream", [sse(*events)]


def messages_responder(body: dict):
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
    return 200, "text/event-stream", [sse(*events)]


def responses_responder(body: dict):
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
    return 200, "text/event-stream", [sse(*events)]


def facade_with(base_url: str, *, protocol: str, preset_id: str = "opencode-go",
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


def bound_target(facade: ProviderFacade) -> FrozenTarget:
    return facade.resolve_snapshot([{"key": "k", "provider_id": "go", "model_id": "m-go"}]).target("k")


# 测试装配：协议实现只有 harness/providers/responses.py 一份，这里只把测试需要的
# 适配器调用形状接到独立 Provider 模块，不复制任何请求或错误分类逻辑。
class ResponsesAdapter:
    name = "responses"

    def __init__(self, config: ResponsesConfig, *,
                 execution_scope: ResponsesExecutionScope | None = None) -> None:
        self.config = config
        self.model = config.model or "unconfigured"
        self.execution_scope = execution_scope
        self._delegate = _build_delegate(config, execution_scope)

    def availability(self) -> Availability:
        result = check_availability(self.config)
        if not result["available"]:
            return Availability(False, result["reason"], result["message"])
        return Availability(True)

    def abort(self, session_id: str) -> None:
        if self._delegate is not None:
            self._delegate.abort(session_id)

    def complete(self, request: ModelRequest) -> ModelResponse:
        availability = self.availability()
        if not availability.available:
            raise ProviderError(availability.message, reason=availability.reason)
        if self._delegate is None:
            raise ProviderError("Provider target is not resolvable", reason="provider_unavailable")
        return self._delegate.complete(request)


def _build_delegate(config: ResponsesConfig,
                    execution_scope: ResponsesExecutionScope | None) -> ModelAdapter | None:
    # 配置本身不可用时返回空实现，由 availability()/complete() 报同样的错误，
    # 与旧适配器“构造不校验、可用性检查才报错”的行为一致
    if not config.api_key or not config.model or not config.base_url:
        return None
    timeout = config.timeout_sec
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
        return None
    if not math.isfinite(float(timeout)) or float(timeout) <= 0:
        return None
    overrides: dict[str, Any] = {}
    if config.api_key:
        overrides["TEST_CREDENTIAL"] = config.api_key
    facade = ProviderFacade(credentials=CredentialChain(overrides=overrides, use_env=False))
    facade.store_document({
        "providers": [{
            "id": config.provider or "test-provider", "name": config.provider or "test-provider",
            "base_url": config.base_url, "credential_ref": "TEST_CREDENTIAL",
            "timeout_sec": float(config.timeout_sec),
        }],
        "models": [{
            "id": "test-model", "provider_id": config.provider or "test-provider",
            "model": config.model, "protocol": "responses",
            "context_window": 128000, "max_output_tokens": 4096,
        }],
        "bindings": {},
    })
    snapshot = facade.resolve_snapshot([{
        "key": "test", "provider_id": config.provider or "test-provider", "model_id": "test-model",
    }])
    return FacadeAdapter(facade, snapshot.target("test"), execution_scope=execution_scope)


__all__ = [
    "Capture",
    "ResponsesAdapter",
    "bound_target",
    "chat_responder",
    "facade_with",
    "messages_responder",
    "responses_responder",
    "serve",
    "sse",
]
