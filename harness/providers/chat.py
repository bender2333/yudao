from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from threading import Event, Lock
from typing import Any

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
)

from .errors import CancelledError, ProviderError
from .invoke import InvokeResult, Observer, ProviderInput
from .presets import build_identity_headers
from .resolve import FrozenTarget
from .responses import (
    _CompletionDeadline,
    _RETRYABLE_HTTP_ERRORS,
    _TransportTrace,
    _attach_transport_trace,
    _diagnostic_code,
    _error_code,
    _has_nonretryable_connection_cause,
    _is_context_overflow,
    _nonretryable_http_error,
    _provider_events,
    _retry_after,
    _retryable_code,
    _retryable_http_status,
    _sdk_json,
    _transport_diagnostics,
    _transport_provider_error,
)


# Chat Completions 单次调用：SDK 内部重试关闭，错误分类与 Responses 共用同一套码表
@dataclass
class _ChatInvocation:
    frozen_target: FrozenTarget
    provider_input: ProviderInput
    session_id: str
    attempt_id: str
    abort_event: Event
    observer: Observer


class ChatExecutionScope:
    # 一次同步运行内按端点与认证句柄复用 Chat 客户端
    def __init__(self) -> None:
        self._runner = asyncio.Runner()
        self._clients: dict[tuple[str, str, float, str], AsyncOpenAI] = {}
        self._closed = False

    def __enter__(self) -> "ChatExecutionScope":
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self.close()

    def run(self, awaitable: Any) -> Any:
        if self._closed:
            raise RuntimeError("Chat execution scope is closed")
        return self._runner.run(awaitable)

    async def client_for(self, frozen_target: FrozenTarget) -> AsyncOpenAI:
        if self._closed:
            raise RuntimeError("Chat execution scope is closed")
        key = (frozen_target.provider_id, frozen_target.base_url,
               float(frozen_target.timeout_sec), frozen_target.api_key)
        client = self._clients.get(key)
        if client is None:
            client = AsyncOpenAI(
                api_key=frozen_target.api_key,
                base_url=frozen_target.base_url,
                timeout=frozen_target.timeout_sec,
                max_retries=0,
            )
            self._clients[key] = client
        return client

    async def _close_clients(self) -> None:
        clients = tuple(self._clients.values())
        self._clients.clear()
        if clients:
            await asyncio.gather(*(client.close() for client in clients), return_exceptions=False)

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._runner.run(self._close_clients())
        finally:
            self._closed = True
            self._runner.close()


def invoke_chat(
    frozen_target: FrozenTarget,
    provider_input: ProviderInput,
    session_id: str,
    attempt_id: str,
    abort_event: Event,
    observer: Observer,
    *,
    execution_scope: ChatExecutionScope | None = None,
) -> InvokeResult:
    # 单次 Chat Completions 调用，工具由内核执行
    _check_availability(frozen_target)
    if abort_event.is_set():
        raise CancelledError()
    invocation = _ChatInvocation(
        frozen_target=frozen_target, provider_input=provider_input,
        session_id=session_id, attempt_id=attempt_id,
        abort_event=abort_event, observer=observer,
    )
    invoker = _ChatInvoker(execution_scope=execution_scope)
    try:
        if execution_scope is None:
            return asyncio.run(invoker.complete(invocation))
        return execution_scope.run(invoker.complete(invocation))
    except ProviderError:
        raise
    except (TimeoutError, APITimeoutError) as exc:
        raise ProviderError("Model request timed out", reason="provider_timeout", retryable=True,
                            diagnostics=_transport_diagnostics("timeout", exc)) from exc
    except APIStatusError as exc:
        code = _error_code(exc.body)
        reason = "context_overflow" if _is_context_overflow(code) else "provider_error"
        diagnostics = {
            "status_code": exc.status_code,
            "request_observation_id": _observation_id(invocation),
        }
        safe = _diagnostic_code(code, "http_status")
        diagnostics.update(safe)
        retry_after = _retry_after(getattr(getattr(exc, "response", None), "headers", None))
        if retry_after is not None:
            diagnostics["retry_after_sec"] = retry_after
        raise ProviderError(
            f"Model provider returned HTTP {exc.status_code}", reason=reason,
            retryable=_retryable_http_status(exc.status_code, code),
            diagnostics=diagnostics,
        ) from exc
    except APIConnectionError as exc:
        if _has_nonretryable_connection_cause(exc):
            raise _nonretryable_http_error() from exc
        raise ProviderError("Model provider connection failed", retryable=True,
                            diagnostics=_transport_diagnostics("connection", exc)) from exc
    except APIError as exc:
        code = _error_code(exc.body)
        reason = "context_overflow" if _is_context_overflow(code) else "provider_error"
        raise ProviderError(
            "Model provider returned an invalid API response", reason=reason,
            retryable=reason != "context_overflow" and _retryable_code(code),
            diagnostics=_diagnostic_code(code, "provider_response"),
        ) from exc
    except json.JSONDecodeError as exc:
        raise ProviderError("Model provider returned malformed stream JSON") from exc


def _check_availability(target: FrozenTarget) -> None:
    if not target.api_key:
        raise ProviderError("Missing provider credential", reason="provider_unavailable")
    if not target.model:
        raise ProviderError("Missing model", reason="provider_unavailable")
    if not target.base_url:
        raise ProviderError("Missing provider base URL", reason="provider_unavailable")


class _ChatInvoker:
    def __init__(self, *, execution_scope: ChatExecutionScope | None = None) -> None:
        self.execution_scope = execution_scope
        self._lock = Lock()
        self._active: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Task]] = {}

    async def complete(self, invocation: _ChatInvocation) -> InvokeResult:
        loop = asyncio.get_running_loop()
        trace = _TransportTrace()
        deadline = _CompletionDeadline()
        with self._lock:
            if invocation.attempt_id in self._active:
                raise ProviderError("Chat invocation already active for this attempt")
            task = asyncio.create_task(self._stream_once(invocation, trace, deadline))
            self._active[invocation.attempt_id] = (loop, task)
        watcher = asyncio.create_task(self._watch_abort(invocation, task))
        try:
            async with asyncio.timeout(invocation.frozen_target.timeout_sec) as timeout:
                deadline.bind(timeout)
                return await task
        except asyncio.CancelledError as exc:
            raise CancelledError() from exc
        finally:
            with self._lock:
                self._active.pop(invocation.attempt_id, None)
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)

    @staticmethod
    async def _watch_abort(invocation: _ChatInvocation, task: asyncio.Task) -> None:
        while not task.done():
            if invocation.abort_event.is_set():
                task.cancel()
                return
            await asyncio.sleep(0.02)

    async def _stream_once(self, invocation: _ChatInvocation, trace: _TransportTrace,
                           deadline: _CompletionDeadline) -> InvokeResult:
        started = time.monotonic()
        target = invocation.frozen_target
        params = _chat_request_params(invocation, target)
        invocation.observer.on_event({
            "kind": "request",
            "id": _observation_id(invocation),
            "session_id": invocation.session_id,
            "attempt_id": invocation.attempt_id,
            "provider": target.provider_id,
            "model": target.model,
            "payload": params,
            "evidence_source": "constructed_request_params",
        })
        headers = build_identity_headers(target.header_profile, invocation.session_id)
        params["_request_headers"] = headers
        if self.execution_scope is not None:
            client = await self.execution_scope.client_for(target)
            return await self._stream_with_client(invocation, trace, client, params, started, deadline)
        async with AsyncOpenAI(
            api_key=target.api_key, base_url=target.base_url,
            timeout=target.timeout_sec, max_retries=0,
            default_headers=headers or None,
        ) as client:
            return await self._stream_with_client(invocation, trace, client, params, started, deadline)

    async def _stream_with_client(self, invocation: _ChatInvocation, trace: _TransportTrace,
                                  client: AsyncOpenAI, params: dict[str, Any], started: float,
                                  deadline: _CompletionDeadline) -> InvokeResult:
        call_params = dict(params)
        headers = call_params.pop("_request_headers", {})
        text_parts: list[str] = []
        tool_calls: dict[str, dict[str, Any]] = {}
        usage_raw: dict[str, Any] | None = None
        response_id: str | None = None
        actual_model: str | None = None
        terminal = False
        try:
            stream = await client.chat.completions.create(
                **(call_params | ({"extra_headers": headers} if headers else {})),
            )
        except Exception as exc:
            if isinstance(exc, _RETRYABLE_HTTP_ERRORS):
                raise _transport_provider_error(exc, trace=trace) from exc
            raise
        event_index = 0
        async for chunk in _provider_events(stream, trace):
            if invocation.abort_event.is_set():
                raise CancelledError()
            payload = _sdk_json(chunk, secrets=(invocation.frozen_target.api_key,))
            invocation.observer.on_event({
                "kind": "stream_event",
                "id": f"{_observation_id(invocation)}:stream-{event_index}",
                "session_id": invocation.session_id,
                "attempt_id": invocation.attempt_id,
                "provider": invocation.frozen_target.provider_id,
                "model": payload.get("model"),
                "source": "sdk_decoded_stream",
                "sequence": event_index,
                "payload": payload,
            })
            event_index += 1
            response_id = payload.get("id") or response_id
            actual_model = payload.get("model") or actual_model
            if isinstance(payload.get("usage"), dict):
                usage_raw = payload["usage"]
            for choice in payload.get("choices") or []:
                delta = choice.get("delta") or {}
                content = delta.get("content")
                if isinstance(content, str) and content:
                    text_parts.append(content)
                for call in delta.get("tool_calls") or []:
                    index = str(call.get("index", len(tool_calls)))
                    entry = tool_calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    if call.get("id"):
                        entry["id"] = str(call["id"])
                    function = call.get("function") or {}
                    if function.get("name"):
                        entry["name"] = str(function["name"])
                    if function.get("arguments"):
                        entry["arguments"] += str(function["arguments"])
                if choice.get("finish_reason"):
                    terminal = True
        if not terminal:
            # 缺少结束块或用量块即视为不完整流，保留为可重试失败
            raise ProviderError(
                "Chat stream ended before a terminal chunk",
                retryable=True,
                diagnostics=_transport_diagnostics("stream_incomplete", None, trace),
            )
        text = "".join(text_parts)
        output = _chat_output(text, tool_calls)
        usage = _chat_usage(usage_raw, started)
        invocation.observer.on_event({
            "kind": "usage",
            "id": response_id or _observation_id(invocation),
            "session_id": invocation.session_id,
            "attempt_id": invocation.attempt_id,
            "provider": invocation.frozen_target.provider_id,
            "model": actual_model,
            "payload": {"response_id": response_id, "usage": usage_raw},
            "usage": usage,
        })
        invocation.observer.on_event({
            "kind": "message",
            "id": response_id or _observation_id(invocation),
            "session_id": invocation.session_id,
            "attempt_id": invocation.attempt_id,
            "provider": invocation.frozen_target.provider_id,
            "model": actual_model,
            "text": text,
            "payload": {"text": text, "tool_calls": list(tool_calls.values())},
        })
        deadline.stop()
        return InvokeResult(
            output=output, text=text, usage=usage, finish_reason="completed",
            provider=invocation.frozen_target.provider_id, model=actual_model or invocation.frozen_target.model,
            response_id=response_id, protocol="chat_completions",
            actual_model=actual_model,
            wire_evidence={"request": {key: value for key, value in params.items() if not key.startswith("_")},
                           "response_id": response_id},
        )


def _chat_request_params(invocation: _ChatInvocation, target: FrozenTarget) -> dict[str, Any]:
    params: dict[str, Any] = {
        "model": target.model,
        "messages": _chat_messages(invocation.provider_input),
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    tools = _chat_tools(invocation.provider_input)
    if tools:
        params["tools"] = tools
        params["tool_choice"] = "auto"
    limit = invocation.provider_input.max_output_tokens
    if limit is not None:
        params["max_tokens"] = int(limit)
    return params


def _chat_messages(provider_input: ProviderInput) -> list[dict[str, Any]]:
    # 把已装配的 Responses 形状输入翻译为 Chat 形状，保留顺序与工具配对
    raw = provider_input.raw_request or {}
    items = raw.get("input") if isinstance(raw, dict) else None
    messages: list[dict[str, Any]] = []
    if isinstance(items, list) and items:
        pending_calls: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "function_call":
                pending_calls.append({
                    "id": str(item.get("call_id") or item.get("id") or ""),
                    "type": "function",
                    "function": {
                        "name": str(item.get("name") or ""),
                        "arguments": str(item.get("arguments") or "{}"),
                    },
                })
                continue
            _flush_tool_calls(messages, pending_calls)
            if item_type == "function_call_output":
                messages.append({
                    "role": "tool",
                    "tool_call_id": str(item.get("call_id") or ""),
                    "content": str(item.get("output") or ""),
                })
                continue
            if item_type == "message" or item_type is None:
                role = str(item.get("role") or "user")
                messages.append({"role": role, "content": _message_text(item.get("content"))})
        _flush_tool_calls(messages, pending_calls)
    else:
        for message in provider_input.messages:
            entry: dict[str, Any] = {"role": message.role, "content": message.content}
            if message.name:
                entry["name"] = message.name
            messages.append(entry)
    for result in provider_input.tool_results:
        messages.append({
            "role": "tool",
            "tool_call_id": result.call_id,
            "content": result.output,
        })
    return messages


def _flush_tool_calls(messages: list[dict[str, Any]], pending: list[dict[str, Any]]) -> None:
    if not pending:
        return
    messages.append({"role": "assistant", "content": None, "tool_calls": list(pending)})
    pending.clear()


def _chat_tools(provider_input: ProviderInput) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": dict(tool.parameters) or {"type": "object", "properties": {}},
            },
        }
        for tool in provider_input.tools
        if tool.name
    ]


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") in {"output_text", "input_text"}:
                parts.append(str(part.get("text") or ""))
        return "".join(parts)
    return ""


def _chat_output(text: str, tool_calls: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    # 统一输出规范为内核使用的 Responses 形状
    output: list[dict[str, Any]] = []
    if text:
        output.append({
            "id": "chat-message-0", "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": text}],
        })
    for index, call in sorted(tool_calls.items(), key=lambda item: item[0]):
        output.append({
            "id": call["id"] or f"chat-call-{index}",
            "type": "function_call",
            "call_id": call["id"] or f"chat-call-{index}",
            "name": call["name"],
            "arguments": call["arguments"] or "{}",
        })
    return output


def _chat_usage(raw: dict[str, Any] | None, started: float) -> dict[str, Any]:
    latency_ms = int((time.monotonic() - started) * 1000)
    if not isinstance(raw, dict):
        return {"reported": False, "latency_ms": latency_ms}
    details = raw.get("prompt_tokens_details")
    cached = details.get("cached_tokens") if isinstance(details, dict) else 0
    return {
        "reported": True,
        "input_tokens": _count(raw.get("prompt_tokens")) - _count(cached),
        "output_tokens": _count(raw.get("completion_tokens")),
        "total_tokens": _count(raw.get("total_tokens")),
        "cache_read_tokens": _count(cached),
        "cache_write_tokens": 0,
        "latency_ms": latency_ms,
    }


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _observation_id(invocation: _ChatInvocation) -> str:
    # 内核传入的 attempt_id 已是本次调用尝试的规范身份
    return invocation.attempt_id


__all__ = ["ChatExecutionScope", "invoke_chat"]
