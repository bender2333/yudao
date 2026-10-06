from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

# openai 在第一次请求时才导入资源模块；随 Provider 模块导入，这项一次性工作在服务启动时完成（D09）
import openai.resources.chat
from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    DefaultAsyncHttpxClient,
)
from openai.types.chat import ChatCompletionChunk

from .call import ModelDelta
from .errors import CancelledError, ProviderError
from .invoke import Emit, InvokeResult, ProviderInput
from .presets import build_identity_headers
from .reasoning import chat_reasoning_effort, ReasoningOutput
from .resolve import FrozenTarget
from .responses import (
    _ProviderClock,
    _TransportTrace,
    _attach_transport_trace,
    _build_sdk_models,
    _connection_error,
    _created_stream,
    _diagnostic_code,
    _empty_output_error,
    _error_code,
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

_build_sdk_models(ChatCompletionChunk)


# Chat Completions 单次调用：SDK 内部重试关闭，错误分类与 Responses 共用同一套码表
@dataclass
class _ChatInvocation:
    frozen_target: FrozenTarget
    provider_input: ProviderInput
    session_id: str
    attempt_id: str
    emit: Emit


async def invoke_chat(
    frozen_target: FrozenTarget,
    provider_input: ProviderInput,
    session_id: str,
    attempt_id: str,
    emit: Emit,
) -> InvokeResult:
    # 单次 Chat Completions 调用，工具由内核执行
    _check_availability(frozen_target)
    invocation = _ChatInvocation(
        frozen_target=frozen_target, provider_input=provider_input,
        session_id=session_id, attempt_id=attempt_id, emit=emit,
    )
    try:
        return await _ChatInvoker().complete(invocation)
    except ProviderError:
        raise
    except (TimeoutError, APITimeoutError) as exc:
        raise ProviderError("Model request timed out", reason="provider_timeout", retryable=True,
                            diagnostics=_transport_diagnostics("timeout", exc)) from exc
    except APIStatusError as exc:
        code = _error_code(exc.body)
        status_reason = _http_status_reason(exc.status_code)
        reason = status_reason or ("context_overflow" if _is_context_overflow(code) else "provider_error")
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
            retryable=False if status_reason is not None else _retryable_http_status(exc.status_code, code),
            diagnostics=diagnostics,
        ) from exc
    except APIConnectionError as exc:
        raise _connection_error(exc, frozen_target.base_url) from exc
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
    async def complete(self, invocation: _ChatInvocation) -> InvokeResult:
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

    async def _stream_once(self, invocation: _ChatInvocation, trace: _TransportTrace,
                           clock: _ProviderClock) -> InvokeResult:
        started = time.monotonic()
        target = invocation.frozen_target
        params = _chat_request_params(invocation, target)
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
        params["_request_headers"] = headers
        async with AsyncOpenAI(
            api_key=target.api_key, base_url=target.base_url,
            timeout=target.timeout_sec, max_retries=0,
            default_headers=headers or None,
            http_client=DefaultAsyncHttpxClient(timeout=target.timeout_sec, verify=ssl_context(), event_hooks={
                "request": [trace.attach, clock.request_sent], "response": [clock.response_started]}),
        ) as client:
            return await self._stream_with_client(invocation, trace, client, params, started)

    async def _stream_with_client(self, invocation: _ChatInvocation, trace: _TransportTrace,
                                  client: AsyncOpenAI, params: dict[str, Any], started: float) -> InvokeResult:
        call_params = dict(params)
        headers = call_params.pop("_request_headers", {})
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: dict[str, dict[str, Any]] = {}
        usage_raw: dict[str, Any] | None = None
        response_id: str | None = None
        actual_model: str | None = None
        terminal = False
        # 结束原因（工单 #305）：流正常结束而没有输出项时按它诊断，这个值原先被丢掉
        finish_reason: str | None = None
        stream = await _created_stream(client.chat.completions.create(
            **(call_params | ({"extra_headers": headers} if headers else {})),
        ), trace)
        event_index = 0
        # 输出片段（设计说明第 5.6 节）：按通道记录已发出的字数作为下一段的起始位置
        channel_offsets: dict[str, int] = {}
        async for chunk in _provider_events(stream, trace):
            payload = _sdk_json(chunk, secrets=(invocation.frozen_target.api_key,))
            await invocation.emit({
                "kind": "stream_event",
                "id": f"{_observation_id(invocation)}:stream-{event_index}",
                "session_id": invocation.session_id,
                "attempt_id": invocation.attempt_id,
                "provider": invocation.frozen_target.provider_id,
                "model": payload.get("model"),
                "source": "sdk_decoded_stream",
                "sequence": event_index,
                "payload": payload,
                "stage": _chunk_stage(payload),
                "response_id": _chunk_id(payload),
                "deltas": _chunk_deltas(payload, channel_offsets),
            })
            event_index += 1
            response_id = _chunk_id(payload) or response_id
            actual_model = payload.get("model") or actual_model
            if isinstance(payload.get("usage"), dict):
                usage_raw = payload["usage"]
            for choice in payload.get("choices") or []:
                delta = choice.get("delta") or {}
                content = delta.get("content")
                if isinstance(content, str) and content:
                    text_parts.append(content)
                # 推理内容（设计说明第 7.6 节）：Chat Completions 的 reasoning_content，逐块累加
                reasoning_content = delta.get("reasoning_content")
                if isinstance(reasoning_content, str) and reasoning_content:
                    reasoning_parts.append(reasoning_content)
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
                    finish_reason = str(choice["finish_reason"])
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
        reasoning = _chat_reasoning(reasoning_parts)
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
        if not output:
            # 流正常结束却没有任何输出项（只有推理内容同样算）：按失败处理并交给内核重试（工单 #305）
            raise _empty_output_error(finish_reason=finish_reason, usage=usage,
                                      max_output_tokens=invocation.provider_input.max_output_tokens,
                                      reasoning=reasoning is not None)

        return InvokeResult(
            output=output, text=text, usage=usage, finish_reason="completed",
            provider=invocation.frozen_target.provider_id, model=actual_model or invocation.frozen_target.model,
            response_id=response_id, protocol="chat_completions",
            actual_model=actual_model, reasoning=reasoning,
            wire_evidence={"request": {key: value for key, value in params.items() if not key.startswith("_")},
                           "response_id": response_id},
        )


def _chat_reasoning(parts: list[str]) -> ReasoningOutput | None:
    # Chat Completions 的推理内容是 assistant 消息上的 reasoning_content 字段，回放时原样发送
    content = "".join(parts)
    if not content:
        return None
    return ReasoningOutput(items=[{"type": "reasoning", "reasoning_content": content}])

def _chunk_deltas(payload: dict[str, Any], offsets: dict[str, int]) -> list[ModelDelta]:
    # 这一块里的文字片段：回答文字进 output，工具调用的参数进 tool_arguments；
    # offsets 按通道保存已发出的字数，作为每段的起始位置
    deltas: list[ModelDelta] = []
    for choice in payload.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta") or {}
        content = delta.get("content")
        if isinstance(content, str) and content:
            deltas.append(_delta("output", content, offsets))
        for call in delta.get("tool_calls") or []:
            function = (call or {}).get("function") or {}
            arguments = function.get("arguments")
            if isinstance(arguments, str) and arguments:
                deltas.append(_delta("tool_arguments", arguments, offsets))
    return deltas

def _delta(channel: str, text: str, offsets: dict[str, int]) -> ModelDelta:
    offset = offsets.get(channel, 0)
    offsets[channel] = offset + len(text)
    return ModelDelta(channel=channel, offset=offset, text=text)

def _chunk_stage(payload: dict[str, Any]) -> str:
    # Chat Completions 流式块的进度阶段：带文字或工具调用增量的块是输出；带结束原因的块与结束以后只带用量的块
    # （stream_options.include_usage，choices 为空）是完成；只带角色的块（第一块）是回答开始
    choices = [choice for choice in payload.get("choices") or [] if isinstance(choice, dict)]
    deltas = [choice.get("delta") or {} for choice in choices]
    if any(delta.get("content") or delta.get("tool_calls") for delta in deltas):
        return "output"
    if any(choice.get("finish_reason") for choice in choices) or (not choices and payload.get("usage")):
        return "completed"
    if any(delta.get("role") for delta in deltas):
        return "response_created"
    return "event"


def _chunk_id(payload: dict[str, Any]) -> str | None:
    # 提供方的回答身份：每个流式块都带着同一个 id；SDK 不校验字段类型，只接受字符串
    identity = payload.get("id")
    return identity if isinstance(identity, str) and identity else None


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
        # 要求调用工具时发送 tool_choice: required；自动时不发送（#102）
        if invocation.provider_input.tool_choice == "required":
            params["tool_choice"] = "required"
    limit = invocation.provider_input.max_output_tokens
    if limit is not None:
        params["max_tokens"] = int(limit)
    # 推理参数（#87）：effort 方式发送 reasoning_effort，档位是冻结目标里的实际发送档位
    effort = chat_reasoning_effort(target)
    if effort is not None:
        params["reasoning_effort"] = effort
    return params


def _chat_messages(provider_input: ProviderInput) -> list[dict[str, Any]]:
    # 把已装配的 Responses 形状输入翻译为 Chat 形状，保留顺序与工具配对
    raw = provider_input.raw_request or {}
    items = raw.get("input") if isinstance(raw, dict) else None
    messages: list[dict[str, Any]] = []
    if isinstance(items, list) and items:
        pending_calls: list[dict[str, Any]] = []
        pending_reasoning = ""
        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "reasoning":
                # 推理内容与消息、工具调用合并在 assistant 消息上，累积到下一次冲刷
                pending_reasoning = _reasoning_content(item)
                continue
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
            _flush_tool_calls(messages, pending_calls, pending_reasoning)
            if item_type == "function_call_output":
                pending_reasoning = ""
                messages.append({
                    "role": "tool",
                    "tool_call_id": str(item.get("call_id") or ""),
                    "content": str(item.get("output") or ""),
                })
                continue
            if item_type == "message" or item_type is None:
                role = str(item.get("role") or "user")
                entry: dict[str, Any] = {"role": role, "content": _message_text(item.get("content"))}
                # 推理内容挂在它伴随的 assistant 消息上；部门输入与用户消息消耗掉它
                if role == "assistant" and pending_reasoning:
                    entry["reasoning_content"] = pending_reasoning
                pending_reasoning = ""
                messages.append(entry)
        _flush_tool_calls(messages, pending_calls, pending_reasoning)
        return messages
    # 没有装配好的 input 时才由统一消息与工具结果组成请求；input 中的工具结果已按原位置翻译
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


def _flush_tool_calls(messages: list[dict[str, Any]], pending: list[dict[str, Any]],
                      reasoning_content: str = "") -> None:
    if not pending:
        return
    entry: dict[str, Any] = {"role": "assistant", "content": None, "tool_calls": list(pending)}
    if reasoning_content:
        entry["reasoning_content"] = reasoning_content
    messages.append(entry)
    pending.clear()

def _reasoning_content(item: dict[str, Any]) -> str:
    # 保存推理内容时原样留下上游字段名，回放时读回
    value = item.get("reasoning_content")
    return value if isinstance(value, str) else ""


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


__all__ = ["invoke_chat"]
