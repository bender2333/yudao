from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit

# anthropic 在第一次请求时才导入资源模块；随 Provider 模块导入，这项一次性工作在服务启动时完成（D09）
import anthropic.resources.messages
from anthropic import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
    DefaultAsyncHttpxClient,
)
from anthropic.types import RawMessageStreamEvent

from .call import ModelDelta
from .errors import CancelledError, ProviderError
from .invoke import Emit, InvokeResult, ProviderInput
from .presets import build_identity_headers
from .resolve import FrozenTarget
from .responses import (
    _ProviderClock,
    _TransportTrace,
    _attach_transport_trace,
    _build_sdk_models,
    _connection_error,
    _created_stream,
    _diagnostic_code,
    _error_object,
    _http_status_reason,
    _is_context_overflow,
    _provider_events,
    _retry_after,
    _retryable_code,
    _retryable_http_status,
    _sdk_json,
    _transport_diagnostics,
)
from .tls import ssl_context

_build_sdk_models(RawMessageStreamEvent)


# Anthropic Messages 单次调用：系统指令独立传参，工具配对按 tool_use/tool_result
@dataclass
class _MessagesInvocation:
    frozen_target: FrozenTarget
    provider_input: ProviderInput
    session_id: str
    attempt_id: str
    emit: Emit
    # 输出片段（设计说明第 5.6 节）：按通道保存已发出的字数，作为下一段的起始位置
    channel_offsets: dict[str, int] = field(default_factory=dict)


def anthropic_base_url(base_url: str) -> str:
    # 服务方案给的是到 /v1 的地址，Anthropic SDK 自己会补 /v1/messages，
    # 这里去掉重复的 /v1，避免出现 /v1/v1/messages
    parts = urlsplit(base_url)
    path = parts.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[: -len("/v1")]
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


async def invoke_messages(
    frozen_target: FrozenTarget,
    provider_input: ProviderInput,
    session_id: str,
    attempt_id: str,
    emit: Emit,
) -> InvokeResult:
    # 单次 Messages 调用，工具由内核执行
    _check_availability(frozen_target)
    limit = provider_input.max_output_tokens
    if limit is None:
        # 协议要求 max_tokens，缺项在请求前拒绝，不编造默认值
        raise ProviderError("Messages protocol requires max_output_tokens", reason="provider_protocol")
    invocation = _MessagesInvocation(
        frozen_target=frozen_target, provider_input=provider_input,
        session_id=session_id, attempt_id=attempt_id, emit=emit,
    )
    try:
        return await _MessagesInvoker().complete(invocation)
    except ProviderError:
        raise
    except (TimeoutError, APITimeoutError) as exc:
        raise ProviderError("Model request timed out", reason="provider_timeout", retryable=True,
                            diagnostics=_transport_diagnostics("timeout", exc)) from exc
    except APIStatusError as exc:
        code = _error_type(exc.body)
        status_reason = _http_status_reason(exc.status_code)
        reason = status_reason or ("context_overflow" if _is_context_overflow(code) else "provider_error")
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
            retryable=False if status_reason is not None else _retryable_http_status(exc.status_code, code),
            diagnostics=diagnostics,
        ) from exc
    except APIConnectionError as exc:
        raise _connection_error(exc, frozen_target.base_url) from exc
    except APIError as exc:
        code = _error_type(exc.body)
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


def _error_type(body: Any) -> str | None:
    # Anthropic 的错误码是 error.type（overloaded_error、invalid_request_error 等）
    error_type = _error_object(body).get("type")
    return error_type if isinstance(error_type, str) else None


def _stream_error(body: Any) -> ProviderError:
    # 流中的 event: error 按错误的 type 分类：过载与服务端错误可以重试，认证、参数与内容错误不重试
    code = _error_type(body)
    return ProviderError("Model provider reported a stream error", retryable=_retryable_code(code),
                         diagnostics=_diagnostic_code(code, "stream_error"))


def _event_stage(payload: dict[str, Any]) -> str:
    # Messages 流事件的进度阶段
    event_type = payload.get("type")
    if event_type == "message_start":
        return "response_created"
    if event_type in {"content_block_start", "content_block_delta"}:
        return "output"
    if event_type == "content_block_stop":
        return "output_item_done"
    if event_type == "message_stop":
        return "completed"
    if event_type == "error":
        return "error"
    return "event"


def _event_deltas(payload: dict[str, Any], offsets: dict[str, int]) -> list[ModelDelta]:
    # 这一条流事件里的文字片段：回答文字进 output，推理进 reasoning，工具调用的参数进 tool_arguments
    delta = payload.get("delta") or {}
    kind = delta.get("type")
    if kind == "text_delta":
        return [_delta("output", str(delta.get("text") or ""), offsets)]
    if kind == "thinking_delta":
        return [_delta("reasoning", str(delta.get("thinking") or ""), offsets)]
    if kind == "input_json_delta":
        return [_delta("tool_arguments", str(delta.get("partial_json") or ""), offsets)]
    return []

def _delta(channel: str, text: str, offsets: dict[str, int]) -> ModelDelta:
    offset = offsets.get(channel, 0)
    offsets[channel] = offset + len(text)
    return ModelDelta(channel=channel, offset=offset, text=text)

def _event_response_id(payload: dict[str, Any]) -> str | None:
    # 提供方的回答身份在 message_start 的 message 中
    message = payload.get("message")
    identity = message.get("id") if isinstance(message, dict) else None
    return identity if isinstance(identity, str) and identity else None


class _MessagesInvoker:
    async def complete(self, invocation: _MessagesInvocation) -> InvokeResult:
        # 取消由调用所在的任务传入：任务被取消时这里得到 asyncio.CancelledError，换成本次尝试已取消
        trace = _TransportTrace()
        try:
            async with asyncio.timeout(None) as timeout:
                clock = _ProviderClock(timeout, invocation.frozen_target.timeout_sec)
                return await self._stream_once(invocation, trace, clock)
        except asyncio.CancelledError as exc:
            raise CancelledError() from exc
        except Exception as exc:
            _attach_transport_trace(exc, trace.snapshot())
            raise

    async def _stream_once(self, invocation: _MessagesInvocation, trace: _TransportTrace,
                           clock: _ProviderClock) -> InvokeResult:
        started = time.monotonic()
        target = invocation.frozen_target
        params = _messages_request_params(invocation, target)
        await invocation.emit({
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
        # anthropic 1.x 只接受 httpx2 的客户端；DefaultAsyncHttpxClient 是带 SDK 默认设置的 httpx2 客户端，
        # 挂上共用的 SSL 上下文与计时钩子
        async with AsyncAnthropic(
            api_key=target.api_key, base_url=anthropic_base_url(target.base_url),
            timeout=target.timeout_sec, max_retries=0,
            default_headers=headers or None,
            http_client=DefaultAsyncHttpxClient(timeout=target.timeout_sec, verify=ssl_context(), event_hooks={
                "request": [trace.attach, clock.request_sent], "response": [clock.response_started]}),
        ) as client:
            return await self._stream_with_client(invocation, trace, client, params, headers, started)

    async def _emit_stream_event(self, invocation: _MessagesInvocation, payload: dict[str, Any], index: int) -> None:
        message = payload.get("message")
        await invocation.emit({
            "kind": "stream_event",
            "id": f"{_observation_id(invocation)}:stream-{index}",
            "session_id": invocation.session_id,
            "attempt_id": invocation.attempt_id,
            "provider": invocation.frozen_target.provider_id,
            "model": message.get("model") if isinstance(message, dict) else payload.get("model"),
            "source": "sdk_decoded_stream",
            "sequence": index,
            "payload": payload,
            "stage": _event_stage(payload),
            "response_id": _event_response_id(payload),
            "deltas": _event_deltas(payload, invocation.channel_offsets),
        })

    async def _stream_with_client(self, invocation: _MessagesInvocation, trace: _TransportTrace,
                                  client: AsyncAnthropic, params: dict[str, Any],
                                  headers: dict[str, str], started: float) -> InvokeResult:
        stream = await _created_stream(client.messages.create(
            **(params | ({"extra_headers": headers} if headers else {})),
        ), trace)
        text_parts: list[str] = []
        tool_blocks: dict[int, dict[str, Any]] = {}
        usage_raw: dict[str, Any] = {}
        response_id: str | None = None
        actual_model: str | None = None
        stop_reason: str | None = None
        terminal = False
        event_index = 0
        try:
            async for event in _provider_events(stream, trace):
                payload = _sdk_json(event, secrets=(invocation.frozen_target.api_key,))
                await self._emit_stream_event(invocation, payload, event_index)
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
        except APIStatusError as exc:
            # SDK 把流中的 event: error 转换成状态码为 200 的错误：错误事件同样记入流式记录，再按错误的 type 分类
            if isinstance(exc.body, dict):
                await self._emit_stream_event(
                    invocation, _sdk_json(exc.body, secrets=(invocation.frozen_target.api_key,)), event_index)
            raise _stream_error(exc.body) from exc
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
        await invocation.emit({
            "kind": "usage",
            "id": response_id or _observation_id(invocation),
            "session_id": invocation.session_id,
            "attempt_id": invocation.attempt_id,
            "provider": invocation.frozen_target.provider_id,
            "model": actual_model,
            "payload": {"response_id": response_id, "usage": usage_raw},
            "usage": usage,
        })
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
        # 要求调用工具时 tool_choice 为 {"type": "any"}；自动时不发送（#102）
        if invocation.provider_input.tool_choice == "required":
            params["tool_choice"] = {"type": "any"}
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
        return "\n".join(part for part in system_parts if part), messages
    # 没有装配好的 input 时才由统一消息与工具结果组成请求；input 中的工具结果已按原位置翻译
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


__all__ = ["anthropic_base_url", "invoke_messages"]
