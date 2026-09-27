from __future__ import annotations

import asyncio
import email.utils
import json
import math
import platform
import re
import time
import typing
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx
import pydantic
# openai 在第一次请求时才导入资源模块；随 Provider 模块导入，这项一次性工作在服务启动时完成（D09）
import openai.resources.responses
from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    DefaultAsyncHttpxClient,
)
from openai.types.responses import ResponseStreamEvent

from .errors import CancelledError, ProviderError
from .invoke import Emit, InvokeResult, ProviderInput
from .presets import build_identity_headers
from .resolve import FrozenTarget


def _build_sdk_models(root: Any) -> None:
    # SDK 的一次性初始化在服务启动时完成（D09）：openai 与 anthropic 的 pydantic 模型推迟到第一次解析时才构建，
    # 第一次请求解析流事件时要构建几百个模型。协议模块导入时（服务启动）从流事件的类型出发全部构建：
    # 先构建字段中出现的模型，再构建引用它们的模型，后者直接使用前者已经构建的结果
    order: list[type[pydantic.BaseModel]] = []
    _collect_models(root, set(), order)
    for model in order:
        model.model_rebuild(force=True)


def _collect_models(annotation: Any, seen: set[type], order: list[type[pydantic.BaseModel]]) -> None:
    if isinstance(annotation, type) and issubclass(annotation, pydantic.BaseModel):
        if annotation in seen:
            return
        seen.add(annotation)
        for model_field in annotation.model_fields.values():
            _collect_models(model_field.annotation, seen, order)
        order.append(annotation)
        return
    for argument in typing.get_args(annotation):
        _collect_models(argument, seen, order)


_build_sdk_models(ResponseStreamEvent)

# 两个 SDK 在每个客户端的第一次请求之前识别平台（platform.system 与 platform.platform），进程内第一次识别要查询
# 系统信息；服务启动时先识别一次，之后读取标准库的缓存
platform.platform()

# 各次调用的客户端共用一个 SSL 上下文。httpx 为每个客户端新建上下文并加载证书，本机负载高时每次约 1 秒，
# 而 Chat Completions 与 Messages 每次调用都新建客户端
_SSL_CONTEXT = httpx.create_ssl_context()


@dataclass(frozen=True)
class ResponsesConfig:
    model: str = ""
    api_key: str = field(default="", repr=False)
    provider: str = "openai"
    base_url: str = "https://api.openai.com/v1"
    timeout_sec: float = 600.0
    # 跨协议统一请求身份（真实客户端 User-Agent、会话标识），不进日志与证据正文
    identity_headers: Mapping[str, str] = field(default_factory=dict, repr=False, compare=False)


@dataclass
class _InvokeRequest:
    frozen_target: FrozenTarget
    provider_input: ProviderInput
    session_id: str
    attempt_id: str
    emit: Emit
    config: ResponsesConfig


class _TransportTrace:
    # 只保留安全的传输阶段事实，不记录正文与凭据
    def __init__(self) -> None:
        self._last_event: dict[str, str | None] | None = None
        self._failure_event: dict[str, str | None] | None = None

    async def __call__(self, name: str, info: dict[str, Any]) -> None:
        failure_type = None
        if name.endswith(".failed") and isinstance(info, dict):
            exception = info.get("exception")
            if exception is not None:
                failure_type = type(exception).__name__
        event = {"name": str(name)[:120], "failure_type": failure_type}
        self._last_event = event
        if name.endswith(".failed"):
            self._failure_event = event

    def snapshot(self) -> dict[str, Any]:
        failure = self._failure_event
        selected = failure or self._last_event
        event_name = selected["name"] if selected is not None else "unknown"
        return {
            "trace_available": self._last_event is not None,
            "transport_phase": _trace_phase(event_name),
            "transport_event": event_name,
            "trace_cause_type": failure["failure_type"] if failure is not None else None,
        }


class _ProviderClock:
    # 单次请求的时限只计算等待模型提供方的时间（D09）：请求发出时开始走时，收到回复头时暂停，之后只在读取回复体的
    # 每一段时走时；SDK 解析流事件、主机处理与交回观察（调用方记录）都不计入。收到终态以后停止；
    # 各段等待累计到时限时请求超时。两个方法作为 httpx 的请求钩子与回复钩子挂在调用使用的客户端上
    def __init__(self, timeout: asyncio.Timeout, limit_sec: float) -> None:
        self._timeout = timeout
        self._remaining = float(limit_sec)
        self._stopped = False

    def resume(self) -> None:
        timeout = self._timeout
        if self._stopped or timeout.expired() or timeout.when() is not None:
            return
        timeout.reschedule(asyncio.get_running_loop().time() + self._remaining)

    def pause(self) -> None:
        timeout = self._timeout
        when = timeout.when()
        if timeout.expired() or when is None:
            return
        self._remaining = max(0.0, when - asyncio.get_running_loop().time())
        timeout.reschedule(None)

    def stop(self) -> None:
        self.pause()
        self._stopped = True

    async def request_sent(self, _request: httpx.Request) -> None:
        self.resume()

    async def response_started(self, response: httpx.Response) -> None:
        self.pause()
        response.stream = _ClockedBody(response.stream, self)


class _ClockedBody(httpx.AsyncByteStream):
    # 回复体：读取每一段期间计时
    def __init__(self, stream: httpx.AsyncByteStream, clock: _ProviderClock) -> None:
        self._stream = stream
        self._clock = clock

    async def __aiter__(self):
        chunks = self._stream.__aiter__()
        while True:
            self._clock.resume()
            try:
                chunk = await chunks.__anext__()
            except StopAsyncIteration:
                return
            finally:
                self._clock.pause()
            yield chunk

    async def aclose(self) -> None:
        await self._stream.aclose()


@dataclass
class _RequestContext:
    invocation: _InvokeRequest
    trace: _TransportTrace
    observation_errors: list[BaseException]
    clock: _ProviderClock


class ProviderConnections:
    # 同一个事件循环内按端点与认证句柄复用 Responses 客户端，认证句柄只在内存中隔离；
    # 只能在创建客户端的事件循环中使用，用完调用 aclose。Chat Completions 与 Messages 每次调用新建客户端。
    # drain_timeout_sec：收到终态以后读完回复剩余部分的时限，读完的连接才能复用；不计入请求时限
    def __init__(self, *, drain_timeout_sec: float = 0.1) -> None:
        self.drain_timeout_sec = drain_timeout_sec
        self._clients: dict[tuple[Any, ...], AsyncOpenAI] = {}
        self._request_context: ContextVar[_RequestContext | None] = ContextVar(
            "yudao_providers_responses_request_context", default=None,
        )
        self._closed = False

    async def client_for(self, config: ResponsesConfig) -> AsyncOpenAI:
        if self._closed:
            raise RuntimeError("Provider connections are closed")
        # The credential is an in-memory connection identity only; it is never logged or persisted.
        identity = tuple(sorted(dict(config.identity_headers).items()))
        key = (config.provider, config.base_url, float(config.timeout_sec), config.api_key, identity)
        client = self._clients.get(key)
        if client is None:
            http_client = DefaultAsyncHttpxClient(
                timeout=config.timeout_sec, verify=_SSL_CONTEXT,
                event_hooks={"request": [self._observe_request], "response": [self._observe_response]},
            )
            client = AsyncOpenAI(
                api_key=config.api_key,
                base_url=config.base_url,
                timeout=config.timeout_sec,
                max_retries=0,
                http_client=http_client,
                default_headers=dict(config.identity_headers) or None,
            )
            self._clients[key] = client
        return client

    def bind(self, context: _RequestContext) -> Any:
        return self._request_context.set(context)

    def reset(self, token: Any) -> None:
        self._request_context.reset(token)

    async def _observe_request(self, http_request: httpx.Request) -> None:
        context = self._context()
        http_request.extensions["trace"] = context.trace
        await _emit_request(context.invocation, http_request, context.observation_errors, context.clock)

    async def _observe_response(self, response: httpx.Response) -> None:
        await self._context().clock.response_started(response)

    def _context(self) -> _RequestContext:
        context = self._request_context.get()
        if context is None:
            raise ProviderError("Provider request context is unavailable", reason="provider_protocol")
        return context

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        clients = tuple(self._clients.values())
        self._clients.clear()
        if clients:
            await asyncio.gather(*(client.close() for client in clients), return_exceptions=False)


async def _emit_request(invocation: _InvokeRequest, http_request: httpx.Request,
                        observation_errors: list[BaseException], clock: _ProviderClock) -> None:
    # 请求在发送之前交给调用方记录，记录完成以后发出并开始计时；请求体无法解析时保留原始错误，不让 SDK 改写成连接错误
    try:
        body = _request_body(http_request)
    except BaseException as exc:
        observation_errors.append(exc)
        raise
    await invocation.emit({
        "kind": "request",
        "id": _request_observation_id(invocation),
        "session_id": invocation.session_id,
        "attempt_id": invocation.attempt_id,
        "provider": invocation.config.provider,
        "model": invocation.config.model,
        "payload": body,
    })
    await clock.request_sent(http_request)


async def invoke_responses(
    frozen_target: FrozenTarget,
    provider_input: ProviderInput,
    session_id: str,
    attempt_id: str,
    emit: Emit,
    *,
    connections: ProviderConnections | None = None,
) -> InvokeResult:
    # 单次 Responses 调用，SDK 内部重试关闭
    config = ResponsesConfig(
        model=frozen_target.model,
        api_key=frozen_target.api_key,
        provider=frozen_target.provider_id,
        base_url=frozen_target.base_url,
        timeout_sec=frozen_target.timeout_sec,
        identity_headers=build_identity_headers(frozen_target.header_profile, session_id),
    )
    invocation = _InvokeRequest(
        frozen_target=frozen_target, provider_input=provider_input,
        session_id=session_id, attempt_id=attempt_id, emit=emit, config=config,
    )
    availability = check_availability(config)
    if not availability["available"]:
        raise ProviderError(availability["message"], reason=availability["reason"])
    try:
        return await _ResponsesInvoker(connections=connections).complete(invocation)
    except ProviderError:
        raise
    except (TimeoutError, APITimeoutError) as exc:
        raise ProviderError("Model request timed out", reason="provider_timeout", retryable=True,
                            diagnostics=_transport_diagnostics("timeout", exc)) from exc
    except APIStatusError as exc:
        code = _error_code(exc.body)
        reason = "context_overflow" if _is_context_overflow(code) else "provider_error"
        diagnostics = _http_status_diagnostics(exc, _request_observation_id(invocation), secrets=(config.api_key,))
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


def check_availability(config: ResponsesConfig) -> dict[str, Any]:
    # 发送前可用性检查，不触网
    missing = []
    if not config.api_key:
        missing.append("provider credential")
    if not config.model:
        missing.append("model")
    if missing:
        return {"available": False, "reason": "provider_unavailable",
                "message": "Missing configuration: " + ", ".join(missing)}
    try:
        url = urlsplit(config.base_url)
        valid_url = url.scheme in {"https", "http"} and bool(url.hostname) and not url.username and not url.password
    except ValueError:
        valid_url = False
    if not valid_url:
        return {"available": False, "reason": "provider_unavailable", "message": "Invalid provider base URL"}
    if not math.isfinite(config.timeout_sec) or config.timeout_sec <= 0:
        return {"available": False, "reason": "provider_unavailable",
                "message": "Provider timeout must be positive and finite"}
    if not config.provider:
        return {"available": False, "reason": "provider_unavailable",
                "message": "Provider identity must not be empty"}
    return {"available": True, "reason": "", "message": ""}


class _ResponsesInvoker:
    def __init__(self, *, connections: ProviderConnections | None = None) -> None:
        self.connections = connections

    async def complete(self, invocation: _InvokeRequest) -> InvokeResult:
        # 取消由调用所在的任务传入：任务被取消时这里得到 asyncio.CancelledError，换成本次尝试已取消
        trace = _TransportTrace()
        try:
            async with asyncio.timeout(None) as timeout:
                clock = _ProviderClock(timeout, invocation.config.timeout_sec)
                return await self._stream_once(invocation, trace, clock)
        except asyncio.CancelledError as exc:
            raise CancelledError() from exc
        except TimeoutError as exc:
            _attach_transport_trace(exc, trace.snapshot())
            raise
        except Exception as exc:
            _attach_transport_trace(exc, trace.snapshot())
            raise

    async def _stream_once(
        self,
        invocation: _InvokeRequest,
        trace: _TransportTrace,
        clock: _ProviderClock,
    ) -> InvokeResult:
        started = time.monotonic()
        observation_errors: list[BaseException] = []
        if self.connections is not None:
            context = _RequestContext(invocation, trace, observation_errors, clock)
            token = self.connections.bind(context)
            try:
                client = await self.connections.client_for(invocation.config)
                return await self._stream_with_client(
                    invocation, trace, observation_errors, client, started, clock,
                )
            finally:
                self.connections.reset(token)

        async def observe_request(http_request: httpx.Request) -> None:
            http_request.extensions["trace"] = trace
            await _emit_request(invocation, http_request, observation_errors, clock)

        http_client = DefaultAsyncHttpxClient(
            timeout=invocation.config.timeout_sec, verify=_SSL_CONTEXT,
            event_hooks={"request": [observe_request], "response": [clock.response_started]},
        )
        async with AsyncOpenAI(
            api_key=invocation.config.api_key,
            base_url=invocation.config.base_url,
            timeout=invocation.config.timeout_sec,
            max_retries=0,
            http_client=http_client,
            default_headers=dict(invocation.config.identity_headers) or None,
        ) as client:
            return await self._stream_with_client(
                invocation, trace, observation_errors, client, started, clock,
            )

    async def _observed_events(self, invocation: _InvokeRequest, event_source: Any):
        event_index = 0
        async for event in event_source:
            event_payload = _sdk_json(event, secrets=(invocation.config.api_key,))
            await invocation.emit({
                "kind": "stream_event",
                "id": f"{_request_observation_id(invocation)}:stream-{event_index}",
                "session_id": invocation.session_id,
                "attempt_id": invocation.attempt_id,
                "provider": invocation.config.provider,
                "model": _actual_model(event_payload) or _actual_model(event_payload.get("response")),
                "source": "sdk_decoded_stream",
                "sequence": event_index,
                "payload": event_payload,
            })
            event_index += 1
            yield event

    async def _stream_with_client(
        self,
        invocation: _InvokeRequest,
        trace: _TransportTrace,
        observation_errors: list[BaseException],
        client: AsyncOpenAI,
        started: float,
        clock: _ProviderClock,
    ) -> InvokeResult:
        provider_input = invocation.provider_input
        output_limit = {} if provider_input.max_output_tokens is None else {"max_output_tokens": provider_input.max_output_tokens}
        try:
            stream = await client.responses.create(
                model=invocation.config.model,
                input=_responses_input_items(provider_input),
                tools=_responses_tools(provider_input),
                store=False,
                stream=True,
                **output_limit,
            )
        except Exception as exc:
            if observation_errors:
                raise observation_errors[0]
            if isinstance(exc, _RETRYABLE_HTTP_ERRORS):
                raise _transport_provider_error(exc, trace=trace) from exc
            if isinstance(exc, httpx.HTTPError):
                raise _nonretryable_http_error() from exc
            raise
        if observation_errors:
            raise observation_errors[0]
        seen_items: set[str] = set()
        completed_response: InvokeResult | None = None
        async with stream:
            event_source = self._observed_events(invocation, _provider_events(stream, trace))
            async for event in event_source:
                if event.type == "response.output_item.done":
                    await self._observe_item(
                        invocation,
                        event.item.model_dump(mode="json", exclude_unset=True),
                        seen_items,
                    )
                elif event.type in {"response.completed", "response.incomplete", "response.failed"}:
                    response = event.response
                    actual_model = _actual_model(response)
                    raw_response = _sdk_json(response, secrets=(invocation.config.api_key,))
                    await invocation.emit({
                        "kind": "response",
                        "id": str(raw_response.get("id") or _request_observation_id(invocation)),
                        "session_id": invocation.session_id,
                        "attempt_id": invocation.attempt_id,
                        "provider": invocation.config.provider,
                        "model": actual_model,
                        "source": "sdk_response",
                        "payload": raw_response,
                    })
                    output = [
                        _redact_sdk_json(
                            item.model_dump(mode="json", exclude_unset=True),
                            secrets=(invocation.config.api_key,),
                        )
                        for item in (response.output or [])
                    ]
                    for item in output:
                        await self._observe_item(invocation, item, seen_items, actual_model=actual_model)
                    raw_usage = (
                        _redact_sdk_json(
                            response.usage.model_dump(mode="json", exclude_unset=True),
                            secrets=(invocation.config.api_key,),
                        )
                        if response.usage else None
                    )
                    usage = _usage(raw_usage, started)
                    await invocation.emit({
                        "kind": "usage",
                        "id": response.id,
                        "session_id": invocation.session_id,
                        "attempt_id": invocation.attempt_id,
                        "provider": invocation.config.provider,
                        "model": response.model,
                        "payload": {"response_id": response.id, "usage": raw_usage},
                        "usage": usage,
                    })
                    if event.type != "response.completed" or response.status != "completed":
                        code = getattr(response.error, "code", None) if response.error else None
                        reason = "context_overflow" if _is_context_overflow(code) else "provider_error"
                        detail = "incomplete" if event.type == "response.incomplete" else "failed"
                        incomplete_reason = getattr(response.incomplete_details, "reason", None)
                        retryable = (
                            reason != "context_overflow"
                            and (
                                _retryable_code(code)
                                or _retryable_code(incomplete_reason)
                            )
                        )
                        diagnostics = _diagnostic_code(code, "terminal_response")
                        if "error_code" not in diagnostics:
                            diagnostics = _diagnostic_code(incomplete_reason, "terminal_response")
                        raise ProviderError(
                            f"Model response {detail}", reason=reason, retryable=retryable,
                            diagnostics=diagnostics,
                        )
                    if response.output is None:
                        raise ProviderError("Completed model response has no output array")
                    text = "\n".join(
                        part.get("text", "") for item in output for part in (item.get("content") or [])
                        if isinstance(part, dict) and part.get("type") == "output_text"
                    )
                    completed_response = InvokeResult(
                        output=output, text=text, usage=usage,
                        finish_reason="completed",
                        provider=invocation.config.provider,
                        model=invocation.config.model,
                        response_id=response.id, protocol="responses",
                        actual_model=actual_model or "",
                        wire_evidence={"response_id": response.id, "attempt_id": invocation.attempt_id},
                    )
                    clock.stop()
                    break
                elif event.type == "error":
                    reason = "context_overflow" if _is_context_overflow(event.code) else "provider_error"
                    raise ProviderError(
                        "Model provider reported a stream error", reason=reason,
                        retryable=reason != "context_overflow" and _retryable_code(event.code),
                        diagnostics=_diagnostic_code(event.code, "stream_error"),
                    )
            if completed_response is not None:
                if self.connections is not None:
                    await _drain_completed_stream(event_source, self.connections.drain_timeout_sec)
                return completed_response
        raise ProviderError(
            "Model response stream ended before a terminal response",
            retryable=True,
            diagnostics=_transport_diagnostics("stream_incomplete", None, trace),
        )

    async def _observe_item(
        self,
        invocation: _InvokeRequest,
        item: dict[str, Any],
        seen: set[str],
        *,
        actual_model: str | None = None,
    ) -> None:
        item = _redact_sdk_json(item, secrets=(invocation.config.api_key,))
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            raise ProviderError("Model output item has no identity")
        if item_id in seen:
            return
        seen.add(item_id)
        text = "\n".join(
            part.get("text", "") for part in (item.get("content") or [])
            if isinstance(part, dict) and part.get("type") == "output_text"
        )
        await invocation.emit({
            "kind": "message",
            "id": item_id,
            "session_id": invocation.session_id,
            "attempt_id": invocation.attempt_id,
            "provider": invocation.config.provider,
            "model": _actual_model(item) or actual_model,
            "text": text,
            "payload": item,
        })


def _responses_input_items(provider_input: ProviderInput) -> list[dict[str, Any]]:
    # 统一消息按原顺序编码，不提升用户材料为系统指令
    raw = provider_input.raw_request
    if isinstance(raw, dict):
        raw_input = raw.get("input")
        if isinstance(raw_input, list):
            # 过渡期桥接：内核仍按原 Responses 形状组装上下文，桥接层把整份
            # input 原样放入 raw_request，保证实际发送与审计持久化逐字节一致
            return [dict(item) if isinstance(item, dict) else item for item in raw_input]
    items: list[dict[str, Any]] = []
    for message in provider_input.messages:
        item: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.name:
            item["name"] = message.name
        items.append(item)
    for result in provider_input.tool_results:
        items.append({
            "type": "function_call_output",
            "call_id": result.call_id,
            "output": result.output,
        })
    return items


def _responses_tools(provider_input: ProviderInput) -> list[dict[str, Any]]:
    raw = provider_input.raw_request
    if isinstance(raw, dict):
        raw_tools = raw.get("tools")
        if isinstance(raw_tools, list):
            # 同上，工具 schema 原样直传，不丢弃 strict 等协议字段
            return [dict(item) if isinstance(item, dict) else item for item in raw_tools]
    tools: list[dict[str, Any]] = []
    for tool in provider_input.tools:
        tools.append({
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.parameters),
        })
    return tools


_SAFE_ERROR_TOKEN = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
_SAFE_ERROR_PARAM = re.compile(r"^[a-z][a-z0-9_.\[\]]{0,63}$")


def _error_object(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {}
    error = body.get("error", body)
    return error if isinstance(error, dict) else {}


def _error_code(body: Any) -> str | None:
    code = _error_object(body).get("code")
    return code if isinstance(code, str) else None


def _sanitized_error_token(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    return normalized if _SAFE_ERROR_TOKEN.fullmatch(normalized) else None


def _sanitized_error_param(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    return normalized if _SAFE_ERROR_PARAM.fullmatch(normalized) else None


def _http_status_diagnostics(
    exc: APIStatusError,
    observation_id: str,
    *,
    secrets: tuple[str, ...] = (),
) -> dict[str, Any]:
    error = _error_object(exc.body)
    diagnostics: dict[str, Any] = {
        "status_code": exc.status_code,
        "request_observation_id": observation_id,
    }
    code = _safe_error_code(_error_code(exc.body)) or _sanitized_error_token(error.get("code"))
    if code is not None:
        diagnostics["error_code"] = code
    error_type = _sanitized_error_token(error.get("type")) or _sanitized_error_token(error.get("status"))
    if error_type is not None:
        diagnostics["error_type"] = error_type
    param = _sanitized_error_param(error.get("param"))
    if param is not None:
        diagnostics["param"] = param
    return _redact_sdk_json(diagnostics, secrets=secrets)


def _actual_model(value: Any) -> str | None:
    # 读取服务实际返回的模型，配置中的请求模型不是返回证据
    model = getattr(value, "model", None)
    if model is None and isinstance(value, dict):
        model = value.get("model")
    return model.strip() if isinstance(model, str) and model.strip() else None


def _sdk_json(value: Any, *, secrets: tuple[str, ...] = ()) -> dict[str, Any]:
    if isinstance(value, dict):
        payload = json.loads(json.dumps(value, ensure_ascii=False))
        return _redact_sdk_json(payload, secrets=secrets)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        payload = dump(mode="json", exclude_unset=True)
        if isinstance(payload, dict):
            return _redact_sdk_json(payload, secrets=secrets)
    raise ProviderError("Model provider returned an unserializable SDK object", reason="provider_protocol")


_SENSITIVE_SDK_KEYS = frozenset({
    "authorization", "api_key", "apikey", "access_token", "refresh_token",
    "client_secret", "password", "cookie", "set_cookie", "credential",
    "credentials", "headers", "proxy_authorization",
})


def _redact_sdk_json(value: Any, *, secrets: tuple[str, ...] = (), key: str | None = None) -> Any:
    # 敏感键与 secret 子串一律脱敏，不进入日志与事件
    normalized_key = key.casefold().replace("-", "_") if isinstance(key, str) else ""
    if normalized_key in _SENSITIVE_SDK_KEYS or normalized_key.endswith("_api_key"):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(child_key): _redact_sdk_json(child_value, secrets=secrets, key=str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_sdk_json(item, secrets=secrets, key=key) for item in value]
    if isinstance(value, str):
        result = value
        for secret in secrets:
            if secret:
                result = result.replace(secret, "[REDACTED]")
        return result
    return value


def _request_observation_id(invocation: _InvokeRequest) -> str:
    # 内核传入的 attempt_id 已是本次调用尝试的规范身份，直接作为观察身份
    return invocation.attempt_id


def _request_body(http_request: httpx.Request) -> dict[str, Any]:
    try:
        body = json.loads(http_request.content)
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError("Model request body was not valid JSON", reason="provider_protocol") from exc
    if not isinstance(body, dict):
        raise ProviderError("Model request body was not a JSON object", reason="provider_protocol")
    return body


def _retryable_status(status: int) -> bool:
    return status in {408, 409, 429} or status >= 500


def _retryable_http_status(status: int, code: Any) -> bool:
    safe_code = _safe_error_code(code)
    return _retryable_status(status) and safe_code not in _NONRETRYABLE_ERROR_CODES


def _retryable_code(code: Any) -> bool:
    return _safe_error_code(code) in _RETRYABLE_ERROR_CODES


_RETRYABLE_ERROR_CODES = frozenset({
    "server_error", "internal_server_error", "service_unavailable", "temporarily_unavailable",
    "timeout", "rate_limit_exceeded", "too_many_requests", "server_is_overloaded",
})

_KNOWN_ERROR_CODES = frozenset({
    "context_length_exceeded", *_RETRYABLE_ERROR_CODES,
    "invalid_api_key", "authentication_error", "permission_denied", "insufficient_quota",
    "model_not_found", "not_found", "bad_request", "invalid_request", "invalid_request_error",
    "content_policy_violation",
})

_NONRETRYABLE_ERROR_CODES = _KNOWN_ERROR_CODES - _RETRYABLE_ERROR_CODES

_RETRYABLE_HTTP_ERRORS = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)

_NONRETRYABLE_CONNECTION_ERRORS = (
    httpx.LocalProtocolError,
    httpx.UnsupportedProtocol,
    httpx.InvalidURL,
)


def _safe_error_code(code: Any) -> str | None:
    if not isinstance(code, str):
        return None
    normalized = code.casefold()
    return normalized if normalized in _KNOWN_ERROR_CODES else None


def _is_context_overflow(code: Any) -> bool:
    return _safe_error_code(code) == "context_length_exceeded"


def _diagnostic_code(code: Any, fallback: str) -> dict[str, str]:
    safe_code = _safe_error_code(code)
    return {"error_code": safe_code} if safe_code is not None else {"error_type": fallback}


def _trace_phase(event_name: str) -> str:
    known_phases = {
        "connect_tcp",
        "start_tls",
        "send_request_headers",
        "send_request_body",
        "receive_response_headers",
        "receive_response_body",
        "response_closed",
    }
    return next((part for part in str(event_name).split(".") if part in known_phases), "unknown")


def _attach_transport_trace(exc: BaseException, snapshot: dict[str, Any]) -> None:
    try:
        setattr(exc, "_yudao_transport_trace", snapshot)
    except Exception:
        pass


def _transport_diagnostics(
    error_type: str,
    exc: BaseException | None,
    trace: _TransportTrace | None = None,
) -> dict[str, Any]:
    snapshot = trace.snapshot() if trace is not None else getattr(exc, "_yudao_transport_trace", None)
    if not isinstance(snapshot, dict):
        snapshot = {}
    cause_type = snapshot.get("trace_cause_type") or (_safe_cause_type(exc) if exc is not None else None)
    return {
        "error_type": error_type,
        "trace_available": bool(snapshot.get("trace_available", False)),
        "transport_phase": snapshot.get("transport_phase", "unknown"),
        "transport_event": snapshot.get("transport_event", "unknown"),
        "cause_type": cause_type or "unknown",
    }


def _safe_cause_type(exc: BaseException) -> str | None:
    cause = exc.__cause__
    if cause is not None:
        return type(cause).__name__
    return type(exc).__name__


def _transport_provider_error(exc: BaseException, *, trace: _TransportTrace | None = None) -> ProviderError:
    error_type = "timeout" if isinstance(exc, httpx.TimeoutException) else "connection"
    return ProviderError(
        "Model request timed out" if error_type == "timeout" else "Model provider connection failed",
        reason="provider_timeout" if error_type == "timeout" else "provider_error",
        retryable=True,
        diagnostics=_transport_diagnostics(error_type, exc, trace),
    )


def _nonretryable_http_error() -> ProviderError:
    return ProviderError(
        "Model provider returned an invalid API response",
        reason="provider_error",
        diagnostics={"error_type": "provider_protocol"},
    )


def _has_nonretryable_connection_cause(exc: BaseException) -> bool:
    return isinstance(exc.__cause__, _NONRETRYABLE_CONNECTION_ERRORS)


async def _provider_events(stream: Any, trace: _TransportTrace | None = None):
    iterator = stream.__aiter__()
    while True:
        try:
            event = await iterator.__anext__()
        except StopAsyncIteration:
            return
        except _RETRYABLE_HTTP_ERRORS as exc:
            raise _transport_provider_error(exc, trace=trace) from exc
        except httpx.HTTPError as exc:
            raise _nonretryable_http_error() from exc
        yield event


async def _drain_completed_stream(event_source: Any, timeout_sec: float) -> None:
    # 完成后给 SDK 流一次短暂排空机会以复用连接；排空中的读取错误不改变已完成的结果，取消照常传出
    try:
        async with asyncio.timeout(timeout_sec):
            async for _event in event_source:
                pass
    except asyncio.CancelledError:
        raise
    except Exception:
        return


def _retry_after(headers: Any) -> float | None:
    if headers is None:
        return None
    raw = headers.get("retry-after-ms") if hasattr(headers, "get") else None
    if raw is not None:
        try:
            delay = float(raw) / 1000.0
        except (TypeError, ValueError):
            delay = None
        if delay is not None and 0 < delay and math.isfinite(delay):
            return delay
    raw = headers.get("retry-after") if hasattr(headers, "get") else None
    if not raw:
        return None
    try:
        delay = float(raw)
    except (TypeError, ValueError):
        try:
            date = email.utils.parsedate_to_datetime(str(raw))
            delay = date.timestamp() - time.time()
        except (TypeError, ValueError, OverflowError, OSError):
            return None
    return delay if 0 < delay and math.isfinite(delay) else None


def _usage(raw: dict[str, Any] | None, started: float) -> dict[str, Any]:
    # 用量只做只读记录，未上报保持未知，不估算
    latency = int((time.monotonic() - started) * 1000)
    if raw is None:
        return {"reported": False, "latency_ms": latency}
    details = raw.get("input_tokens_details")
    details = details if isinstance(details, dict) else {}
    input_tokens = raw.get("input_tokens", 0)
    output_tokens = raw.get("output_tokens", 0)
    total_tokens = raw.get("total_tokens", 0)
    cached = details.get("cached_tokens", 0)
    input_tokens = input_tokens if isinstance(input_tokens, int) and not isinstance(input_tokens, bool) else 0
    output_tokens = output_tokens if isinstance(output_tokens, int) and not isinstance(output_tokens, bool) else 0
    total_tokens = total_tokens if isinstance(total_tokens, int) and not isinstance(total_tokens, bool) else 0
    cached = cached if isinstance(cached, int) and not isinstance(cached, bool) else 0
    return {
        "input_tokens": max(0, input_tokens - cached),
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cache_read_tokens": cached,
        "latency_ms": latency,
        "reported": True,
    }
