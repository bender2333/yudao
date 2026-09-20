from __future__ import annotations

from threading import Lock
from typing import Any, Mapping

from ..models import Usage
from ..providers import (
    FrozenTarget,
    ProviderFacade,
    ProviderInput,
    ProviderMessage,
    ToolResult,
    ToolSpec,
    check_target_availability,
)
from ..providers.errors import ProviderError as FacadeProviderError
from .base import Availability, ModelObservation, ModelRequest, ModelResponse, ProviderError


class FacadeAdapter:
    # 内核侧薄桥接：把引擎的模型请求转交独立 Provider 模块，不直连 SDK
    name = "facade"

    def __init__(self, facade: ProviderFacade, target: FrozenTarget,
                 *, execution_scope: Any | None = None) -> None:
        self.facade = facade
        self.target = target
        self.execution_scope = execution_scope
        self.model = target.model or "unconfigured"
        self._attempts: dict[str, str] = {}
        self._lock = Lock()

    def availability(self) -> Availability:
        # 协议差异由 Provider 模块处理，桥接层不做 Responses 专属判断
        result = check_target_availability(self.target)
        if result["available"]:
            return Availability(True)
        return Availability(False, result["reason"], result["message"])

    def abort(self, session_id: str) -> None:
        # 取消只作用于本次调用尝试，按 attempt 隔离
        with self._lock:
            attempt_id = self._attempts.get(str(session_id))
        if attempt_id is not None:
            self.facade.cancel(attempt_id)

    def complete(self, request: ModelRequest) -> ModelResponse:
        availability = self.availability()
        if not availability.available:
            raise ProviderError(availability.message, reason=availability.reason)
        if request.abort_flag.is_set():
            raise ProviderError("Model request cancelled", reason="cancelled")
        attempt_id = request.attempt_id or (
            f"{request.request_id or request.activation_id}:{request.step_id}:attempt-{request.attempt}"
        )
        request.attempt_id = attempt_id
        with self._lock:
            self._attempts[str(request.session_id)] = attempt_id
        provider_input = _to_provider_input(request)
        observer = _BridgeObserver(request)
        try:
            result = self.facade.invoke_once(
                self.target, provider_input,
                session_id=request.session_id, attempt_id=attempt_id,
                abort_event=request.abort_flag, observer=observer,
                execution_scope=self.execution_scope,
            )
        except FacadeProviderError as exc:
            raise ProviderError(str(exc), reason=exc.reason,
                                retryable=exc.retryable,
                                diagnostics=dict(exc.diagnostics) if exc.diagnostics else None) from exc
        finally:
            with self._lock:
                self._attempts.pop(str(request.session_id), None)
        return ModelResponse(
            output=result.output,
            usage=_to_usage(result.usage),
            provider=result.provider,
            # 只记录服务实际返回的模型，未返回保持未知，不拿请求模型冒充
            model=result.actual_model or "",
            response_id=result.response_id,
            sdk_response=dict(result.wire_evidence),
        )


class _BridgeObserver:
    # 把模块事件映射为引擎观测，记录形状与原 Responses 适配器一致
    def __init__(self, request: ModelRequest) -> None:
        self._request = request

    def confirm_request(self, evidence: Mapping[str, Any]) -> bool:
        # 内核已在装配与请求事件中持久化上下文与尝试身份，确认可发送
        _ = evidence
        return True

    def on_event(self, event: Mapping[str, Any]) -> None:
        kind = event.get("kind")
        payload = event.get("payload")
        payload = dict(payload) if isinstance(payload, Mapping) else {}
        provider = event.get("provider")
        provider = str(provider) if provider is not None else None
        model = event.get("model")
        model = str(model) if model is not None else None
        identifier = event.get("id")
        identifier = str(identifier) if identifier is not None else ""
        if kind == "request":
            self._request.observe(ModelObservation(
                identifier, "request", payload, provider=provider, model=model))
        elif kind == "stream_event":
            self._request.observe_raw(ModelObservation(
                identifier, "stream_event", payload, provider=provider, model=model,
                source="sdk_decoded_stream", sequence=event.get("sequence")))
        elif kind == "response":
            self._request.observe_raw(ModelObservation(
                identifier, "response", payload, provider=provider, model=model,
                source="sdk_response"))
        elif kind == "usage":
            # 优先使用协议适配已经归一化的用量（缓存字段不重复计入输入），
            # payload.usage 只是原始证据，原子字段直接相加会重复统计
            mapped = event.get("usage")
            raw = mapped if isinstance(mapped, Mapping) else payload.get("usage")
            raw = raw if isinstance(raw, Mapping) else {}
            self._request.observe(ModelObservation(
                identifier, "usage", payload, usage=_to_usage(raw),
                provider=provider, model=model))
        elif kind == "message":
            text = event.get("text")
            text = str(text) if text is not None else ""
            self._request.observe(ModelObservation(
                identifier, "message", payload, text, provider=provider, model=model))
        # 未知事件忽略，不进入有效历史


def _to_provider_input(request: ModelRequest) -> ProviderInput:
    # 统一输入供证据与回显使用，原始请求原样直传保证实际发送与审计一致
    messages: list[ProviderMessage] = []
    call_names: dict[str, str] = {}
    for item in request.input_items:
        if isinstance(item, Mapping) and item.get("type") == "function_call":
            call_id = item.get("call_id")
            name = item.get("name")
            if isinstance(call_id, str) and isinstance(name, str):
                call_names[call_id] = name
    tool_results: list[ToolResult] = []
    for item in request.input_items:
        if not isinstance(item, Mapping):
            continue
        item_type = item.get("type")
        if item_type == "function_call":
            continue
        if item_type == "function_call_output":
            call_id = item.get("call_id")
            output = item.get("output")
            tool_results.append(ToolResult(
                call_id=str(call_id) if call_id is not None else "",
                name=call_names.get(str(call_id), ""),
                output=str(output) if output is not None else "",
            ))
            continue
        if item_type == "message":
            role = item.get("role")
            messages.append(ProviderMessage(
                role=str(role) if isinstance(role, str) else "assistant",
                content=_message_text(item.get("content")),
            ))
            continue
        if item_type is None:
            role = item.get("role")
            content = item.get("content")
            if isinstance(role, str) and isinstance(content, str):
                messages.append(ProviderMessage(role=role, content=content,
                                                name=item.get("name")))
    tools: list[ToolSpec] = []
    for item in request.tools:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue
        description = item.get("description")
        parameters = item.get("parameters")
        tools.append(ToolSpec(
            name=name,
            description=str(description) if isinstance(description, str) else "",
            parameters=dict(parameters) if isinstance(parameters, Mapping) else {},
        ))
    return ProviderInput(
        messages=tuple(messages), tools=tuple(tools),
        tool_results=tuple(tool_results),
        max_output_tokens=request.max_output_tokens,
        raw_request={"input": list(request.input_items), "tools": list(request.tools)},
    )


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, Mapping) and part.get("type") == "output_text":
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


def _to_usage(raw: Mapping[str, Any] | dict[str, Any] | None) -> Usage:
    # 用量只做只读记录，未上报保持未知，不估算
    if not isinstance(raw, Mapping):
        return Usage(reported=False)
    def _count(key: str) -> int:
        value = raw.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0
    latency = raw.get("latency_ms")
    return Usage(
        input_tokens=_count("input_tokens"),
        output_tokens=_count("output_tokens"),
        total_tokens=_count("total_tokens"),
        latency_ms=latency if isinstance(latency, int) and not isinstance(latency, bool) else 0,
        cache_read_tokens=_count("cache_read_tokens"),
        cache_write_tokens=_count("cache_write_tokens"),
        reported=bool(raw.get("reported", False)),
    )
