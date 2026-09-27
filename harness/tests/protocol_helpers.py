from __future__ import annotations

import asyncio
import json
import math
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from harness.adapters.base import Availability, ModelAdapter, ProviderError
from harness.adapters.facade_adapter import FacadeAdapter
from harness.engine import StepLimits
from harness.models import DEPARTMENTS
from harness.runtime import LoopSystem
from harness.providers import (
    CredentialChain,
    FrozenTarget,
    ModelCall,
    ModelResponse,
    ModelStreamEvent,
    ProviderConnections,
    ProviderFacade,
    ResponsesConfig,
    check_availability,
)


class ConnectionLoop:
    # 测试直接完成多次调用时使用的事件循环：同一个事件循环中的调用复用 Provider 的连接，关闭时释放连接
    def __init__(self, connections: ProviderConnections | None = None) -> None:
        self._runner = asyncio.Runner()
        self.connections = ProviderConnections() if connections is None else connections

    def __enter__(self) -> ConnectionLoop:
        return self

    def __exit__(self, *_exc_info: Any) -> None:
        self.close()

    def run(self, awaitable: Any) -> Any:
        return self._runner.run(awaitable)

    def close(self) -> None:
        try:
            self._runner.run(self.connections.aclose())
        finally:
            self._runner.close()


def model_call(input_items: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, *,
               max_output_tokens: int | None = None, session_id: str = "session",
               attempt_id: str = "activation:1:attempt-1", purpose: str = "work") -> ModelCall:
    # 测试直接构造的一次调用尝试；身份字段取固定值，便于核对观察身份
    return ModelCall(
        run_id="run", department="product", session_id=session_id, activation_id="activation", step_id=1,
        logical_call_id=attempt_id.rsplit(":attempt-", 1)[0], attempt=1, attempt_id=attempt_id,
        purpose=purpose, input_items=input_items, tools=list(tools or []), max_output_tokens=max_output_tokens,
    )


async def _consume(items: AsyncIterator[ModelStreamEvent | ModelResponse],
                   observe: Callable[[ModelStreamEvent], None] | None) -> ModelResponse:
    async with aclosing(items):
        async for item in items:
            if isinstance(item, ModelResponse):
                return item
            if observe is not None:
                observe(item)
    raise AssertionError("model call ended without a response")


def complete(adapter: ModelAdapter, call: ModelCall, *, observe: Callable[[ModelStreamEvent], None] | None = None,
             loop: ConnectionLoop | None = None) -> ModelResponse:
    # 测试直接完成一次调用：流式输出交给 observe；给出 loop 时在它的事件循环中执行（复用它的连接）
    if loop is not None:
        return loop.run(_consume(adapter.stream(call), observe))
    return asyncio.run(_consume(adapter.stream(call), observe))


def invoke(facade: ProviderFacade, target: FrozenTarget, call: ModelCall, *,
           observe: Callable[[ModelStreamEvent], None] | None = None) -> ModelResponse:
    # 测试直接经 Provider 模块完成一次调用，本次调用新建客户端
    return asyncio.run(_consume(facade.stream(target, call), observe))


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


class ScriptedProvider:
    # 测试内启动的 HTTP 服务：按请求顺序执行回复脚本，每一项自己写出这次请求的回复，可以保持不回复或在中途断开。
    # requests 记录收到的请求体；held：服务端收到一个保持不回复的请求；release：测试结束，保持的请求不再等待
    def __init__(self, replies: list[Callable[["ScriptedProvider", BaseHTTPRequestHandler], None]]) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []
        self.held = threading.Event()
        self.release = threading.Event()
        provider = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:
                return

            def do_POST(self) -> None:
                provider.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                if not provider.replies:
                    # 脚本之外的请求：明确的 HTTP 500，测试从 requests 的数量看到多出的请求
                    send_reply(self, 500, "application/json", b'{"error":{"message":"unexpected request"}}')
                    return
                reply = provider.replies.pop(0)
                try:
                    reply(provider, self)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


def send_reply(handler: BaseHTTPRequestHandler, status: int, content_type: str, body: bytes, *,
               headers: tuple[tuple[str, str], ...] = (), declared_length: int | None = None) -> None:
    # declared_length 大于实际长度时，回复送完 body 以后随请求处理结束而关闭连接，客户端读到的回复在中途断开
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body) if declared_length is None else declared_length))
    for name, value in headers:
        handler.send_header(name, value)
    handler.end_headers()
    handler.wfile.write(body)
    handler.wfile.flush()


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


def provider_system(data_dir: Path, base: str, protocol: str, *, timeout_sec: float = 20.0,
                    step_limits: StepLimits = StepLimits()) -> tuple[LoopSystem, str]:
    # 经真实 Provider 模块的系统：三个部门绑定同一个本机 HTTP 服务上的模型，模型已经记录准入
    facade = ProviderFacade(credentials=CredentialChain(overrides={"SCENARIO_KEY": "scenario-secret"}, use_env=False))
    facade.store_document({
        "providers": [{"id": "local", "name": "Local", "base_url": base + "/v1",
                       "credential_ref": "SCENARIO_KEY", "timeout_sec": timeout_sec}],
        "models": [{"id": "m-local", "provider_id": "local", "model": "scenario-model", "protocol": protocol,
                    "context_window": 32000, "max_output_tokens": 2048}],
        "bindings": {department: {"provider_id": "local", "model_id": "m-local"} for department in DEPARTMENTS},
    })
    facade.record_admission("local", "m-local", admitted_model="scenario-model")
    system = LoopSystem(data_dir, facade=facade, step_limits=step_limits)
    return system, system.create_run("build an echo CLI")


# 测试装配：协议实现只有 harness/providers/responses.py 一份，这里只把测试需要的
# 适配器调用形状接到独立 Provider 模块，不复制任何请求或错误分类逻辑。
class ResponsesAdapter:
    name = "responses"

    def __init__(self, config: ResponsesConfig, *, loop: ConnectionLoop | None = None) -> None:
        self.config = config
        self.model = config.model or "unconfigured"
        self.loop = loop
        self._delegate = _build_delegate(config, loop)

    def availability(self) -> Availability:
        result = check_availability(self.config)
        if not result["available"]:
            return Availability(False, result["reason"], result["message"])
        return Availability(True)

    def cancel(self, attempt_id: str) -> None:
        if self._delegate is not None:
            self._delegate.cancel(attempt_id)

    async def stream(self, call: ModelCall) -> AsyncIterator[ModelStreamEvent | ModelResponse]:
        availability = self.availability()
        if not availability.available:
            raise ProviderError(availability.message, reason=availability.reason)
        if self._delegate is None:
            raise ProviderError("Provider target is not resolvable", reason="provider_unavailable")
        async with aclosing(self._delegate.stream(call)) as items:
            async for item in items:
                yield item

    def complete(self, call: ModelCall, observe: Callable[[ModelStreamEvent], None] | None = None) -> ModelResponse:
        return complete(self, call, observe=observe, loop=self.loop)


def _build_delegate(config: ResponsesConfig, loop: ConnectionLoop | None) -> ModelAdapter | None:
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
    return FacadeAdapter(facade, snapshot.target("test"), connections=None if loop is None else loop.connections)


__all__ = [
    "Capture",
    "ConnectionLoop",
    "ResponsesAdapter",
    "ScriptedProvider",
    "bound_target",
    "chat_responder",
    "complete",
    "facade_with",
    "invoke",
    "messages_responder",
    "model_call",
    "provider_system",
    "responses_responder",
    "send_reply",
    "serve",
    "sse",
]
