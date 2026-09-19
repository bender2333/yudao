from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from threading import Event, Lock
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from anthropic import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
)

from .errors import CancelledError, ProviderError
from .invoke import InvokeResult, Observer, ProviderInput
from .presets import build_identity_headers
from .resolve import FrozenTarget
from .responses import (
    _CompletionDeadline,
    _TransportTrace,
    _diagnostic_code,
    _error_code,
    _has_nonretryable_connection_cause,
    _is_context_overflow,
    _nonretryable_http_error,
    _retry_after,
    _retryable_code,
    _retryable_http_status,
    _sdk_json,
    _transport_diagnostics,
)


# Anthropic Messages 单次调用：系统指令独立传参，工具配对按 tool_use/tool_result
@dataclass
class _MessagesInvocation:
    frozen_target: FrozenTarget
    provider_input: ProviderInput
    session_id: str
    attempt_id: str
    abort_event: Event
    observer: Observer


class MessagesExecutionScope:
    # 一次同步运行内按端点与认证句柄复用 Messages 客户端
    def __init__(self) -> None:
        self._runner = asyncio.Runner()
        self._clients: dict[tuple[str, str, float, str], AsyncAnthropic] = {}
        self._closed = False

    def __enter__(self) -> "MessagesExecutionScope":
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self.close()

    def run(self, awaitable: Any) -> Any:
        if self._closed:
            raise RuntimeError("Messages execution scope is closed")
        return self._runner.run(awaitable)

    async def client_for(self, frozen_target: FrozenTarget) -> AsyncAnthropic:
        if self._closed:
            raise RuntimeError("Messages execution scope is closed")
        key = (frozen_target.provider_id, frozen_target.base_url,
               float(frozen_target.timeout_sec), frozen_target.api_key)
        client = self._clients.get(key)
        if client is None:
            client = AsyncAnthropic(
                api_key=frozen_target.api_key,
                base_url=anthropic_base_url(frozen_target.base_url),
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


def anthropic_base_url(base_url: str) -> str:
    # 服务方案给的是到 /v1 的地址，Anthropic SDK 自己会补 /v1/messages，
    # 这里去掉重复的 /v1，避免出现 /v1/v1/messages
    parts = urlsplit(base_url)
    path = parts.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[: -len("/v1")]
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def invoke_messages(
    frozen_target: FrozenTarget,
    provider_input: ProviderInput,
    session_id: str,
    attempt_id: str,
    abort_event: Event,
    observer: Observer,
    *,
    execution_scope: MessagesExecutionScope | None = None,
) -> InvokeResult:
    # 单次 Messages 调用，工具由内核执行
    _check_availability(frozen_target)
    limit = provider_input.max_output_tokens
    if limit is None:
        # 协议要求 max_tokens，缺项在请求前拒绝，不编造默认值
        raise ProviderError("Messages protocol requires max_output_tokens", reason="provider_protocol")
    if abort_event.is_set():
        raise CancelledError()
    invocation = _MessagesInvocation(
        frozen_target=frozen_target, provider_input=provider_input,
        session_id=session_id, attempt_id=attempt_id,
        abort_event=abort_event, observer=observer,
    )
    invoker = _MessagesInvoker(execution_scope=execution_scope)
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
        diagnostics.update(_diagnostic_code(code, "http_status"))
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


class _MessagesInvoker:
    def __init__(self, *, execution_scope: MessagesExecutionScope | None = None) -> None:
        self.execution_scope = execution_scope
        self._lock = Lock()
        self._active: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Task]] = {}

    async def complete(self, invocation: _MessagesInvocation) -> InvokeResult:
        loop = asyncio.get_running_loop()
        trace = _TransportTrace()
        deadline = _CompletionDeadline()
        with self._lock:
            if invocation.attempt_id in self._active:
                raise ProviderError("Messages invocation already active for this attempt")
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
    async def _watch_abort(invocation: _MessagesInvocation, task: asyncio.Task) -> None:
        while not task.done():
            if invocation.abort_event.is_set():
                task.cancel()
                return
            await asyncio.sleep(0.02)

    async def _stream_once(self, invocation: _MessagesInvocation, trace: _TransportTrace,
                           deadline: _CompletionDeadline) -> InvokeResult:
        started = time.monotonic()
        target = invocation.frozen_target
        params = _messages_request_params(invocation, target)
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
        if self.execution_scope is not None:
            client = await self.execution_scope.client_for(target)
            return await self._stream_with_client(invocation, trace, client, params, headers, started, deadline)
        async with AsyncAnthropic(
            api_key=target.api_key, base_url=anthropic_base_url(target.base_url),
            timeout=target.timeout_sec, max_retries=0,
            default_headers=headers or None,
        ) as client:
            return await self._stream_with_client(invocation, trace, client, params, headers, started, deadline)

    async def _stream_with_client(self, invocation: _MessagesInvocation, trace: _TransportTrace,
                                  client: AsyncAnthropic, params: dict[str, Any],
                                  headers: dict[str, str], started: float,
                                  deadline: _CompletionDeadline) -> InvokeResult:
        stream = await client.messages.create(
            **(params | ({"extra_headers": headers} if headers else {})),
        )
        text_parts: list[str] = []
        tool_blocks: dict[int, dict[str, Any]] = {}
        usage_raw: dict[str, Any] = {}
        response_id: str | None = None
        actual_model: str | None = None
        stop_reason: str | None = None
        terminal = False
        event_index = 0
        async for event in stream:
            if invocation.abort_event.is_set():
                raise CancelledError()
            payload = _sdk_json(event, secrets=(invocation.frozen_target.api_key,))
            invocation.observer.on_event({
                "kind": "stream_event",
                "id": f"{_observation_id(invocation)}:stream-{event_index}",
                "session_id": invocation.session_id,
                "attempt_id": invocation.attempt_id,
                "provider": invocation.frozen_target.provider_id,
                "model": payload.get("message", {}).get("model") if isinstance(payload.get("message"), dict) else payload.get("model"),
                "source": "sdk_decoded_stream",
                "sequence": event_index,
                "payload": payload,
            })
            event_index += 1
            event_type = payload.get("type")
            if event_type == "message_start":
                message = payload.get("message") or {}
                response_id = message.get("id") or response_id
                actual_model = message.get("model") or actual_model
                usage = message.get("usage")
                if isinstance(usage, dict):
                    usage_raw.update(usage)
            elif event_type == "content_block_start":
                block = payload.get("content_block") or {}
                if block.get("type") == "tool_use":
                    tool_blocks[int(payload.get("index", 0))] = {
                        "id": str(block.get("id") or ""),
                        "name": str(block.get("name") or ""),
                        "arguments": "",
                    }
            elif event_type == "content_block_delta":
                delta = payload.get("delta") or {}
                if delta.get("type") == "text_delta":
                    text_parts.append(str(delta.get("text") or ""))
                elif delta.get("type") == "input_json_delta":
                    entry = tool_blocks.setdefault(int(payload.get("index", 0)),
                                                   {"id": "", "name": "", "arguments": ""})
                    entry["arguments"] += str(delta.get("partial_json") or "")
            elif event_type == "message_delta":
                delta = payload.get("delta") or {}
                stop_reason = delta.get("stop_reason") or stop_reason
                usage = payload.get("usage")
                if isinstance(usage, dict):
                    usage_raw.update(usage)
            elif event_type == "message_stop":
                terminal = True
        if not terminal:
            # 完整结束事件缺失即视为不完整流，保留为可重试失败
            raise ProviderError(
                "Messages stream ended before a terminal event",
                retryable=True,
                diagnostics=_transport_diagnostics("stream_incomplete", None, trace),
            )
        text = "".join(text_parts)
        output = _messages_output(text, tool_blocks)
        usage = _messages_usage(usage_raw, started)
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
            "payload": {"text": text, "tool_uses": list(tool_blocks.values())},
        })
        deadline.stop()
        return InvokeResult(
            output=output, text=text, usage=usage,
            finish_reason=("tool_use" if tool_blocks else (stop_reason or "completed")),
            provider=invocation.frozen_target.provider_id,
            model=actual_model or invocation.frozen_target.model,
            response_id=response_id, protocol="messages",
            actual_model=actual_model,
            wire_evidence={"request": params, "response_id": response_id, "stop_reason": stop_reason},
        )


def _messages_request_params(invocation: _MessagesInvocation, target: FrozenTarget) -> dict[str, Any]:
    system, messages = _messages_input(invocation.provider_input)
    params: dict[str, Any] = {
        "model": target.model,
        "max_tokens": int(invocation.provider_input.max_output_tokens or 0),
        "messages": messages,
        "stream": True,
    }
    if system:
        params["system"] = system
    tools = _messages_tools(invocation.provider_input)
    if tools:
        params["tools"] = tools
    return params


def _messages_input(provider_input: ProviderInput) -> tuple[str, list[dict[str, Any]]]:
    # 系统指令独立传参，不把用户材料提升为系统指令；工具配对保持 tool_use/tool_result
    raw = provider_input.raw_request or {}
    items = raw.get("input") if isinstance(raw, dict) else None
    system_parts: list[str] = []
    messages: list[dict[str, Any]] = []
    if isinstance(items, list) and items:
        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "function_call":
                messages.append({
                    "role": "assistant",
                    "content": [{
                        "type": "tool_use",
                        "id": str(item.get("call_id") or item.get("id") or ""),
                        "name": str(item.get("name") or ""),
                        "input": _parse_arguments(item.get("arguments")),
                    }],
                })
                continue
            if item_type == "function_call_output":
                messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": str(item.get("call_id") or ""),
                        "content": str(item.get("output") or ""),
                    }],
                })
                continue
            if item_type == "message" or item_type is None:
                role = str(item.get("role") or "user")
                text = _message_text(item.get("content"))
                if role in {"system", "developer"}:
                    system_parts.append(text)
                    continue
                messages.append({"role": "assistant" if role == "assistant" else "user", "content": text})
    else:
        for message in provider_input.messages:
            if message.role in {"system", "developer"}:
                system_parts.append(message.content)
                continue
            messages.append({
                "role": "assistant" if message.role == "assistant" else "user",
                "content": message.content,
            })
    for result in provider_input.tool_results:
        messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": result.call_id,
                "content": result.output,
            }],
        })
    return "\n".join(part for part in system_parts if part), messages


def _messages_tools(provider_input: ProviderInput) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": dict(tool.parameters) or {"type": "object", "properties": {}},
        }
        for tool in provider_input.tools
        if tool.name
    ]


def _parse_arguments(raw: Any) -> Any:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") in {"output_text", "input_text", "text"}:
                parts.append(str(part.get("text") or ""))
        return "".join(parts)
    return ""


def _messages_output(text: str, tool_blocks: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    # 统一输出规范为内核使用的 Responses 形状
    output: list[dict[str, Any]] = []
    if text:
        output.append({
            "id": "messages-text-0", "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": text}],
        })
    for index, block in sorted(tool_blocks.items()):
        output.append({
            "id": block["id"] or f"messages-call-{index}",
            "type": "function_call",
            "call_id": block["id"] or f"messages-call-{index}",
            "name": block["name"],
            "arguments": block["arguments"] or "{}",
        })
    return output


def _messages_usage(raw: dict[str, Any], started: float) -> dict[str, Any]:
    latency_ms = int((time.monotonic() - started) * 1000)
    if not raw:
        return {"reported": False, "latency_ms": latency_ms}
    return {
        "reported": True,
        "input_tokens": _count(raw.get("input_tokens")),
        "output_tokens": _count(raw.get("output_tokens")),
        "total_tokens": _count(raw.get("input_tokens")) + _count(raw.get("output_tokens")),
        "cache_read_tokens": _count(raw.get("cache_read_input_tokens")),
        "cache_write_tokens": _count(raw.get("cache_creation_input_tokens")),
        "latency_ms": latency_ms,
    }


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _observation_id(invocation: _MessagesInvocation) -> str:
    # 内核传入的 attempt_id 已是本次调用尝试的规范身份
    return invocation.attempt_id


__all__ = ["MessagesExecutionScope", "anthropic_base_url", "invoke_messages"]
