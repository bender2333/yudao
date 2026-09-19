from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
from typing import Any, Mapping, Protocol, Sequence

from .errors import ProviderError, RequestNotPersistedError, UnsupportedProtocolError
from .resolve import FrozenTarget
from .store import SUPPORTED_PROTOCOLS


# Provider 自有统一消息，不依赖领域上下文
@dataclass(frozen=True)
class ProviderMessage:
    role: str
    content: str
    name: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str = ""
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    name: str
    output: str


@dataclass(frozen=True)
class ProviderInput:
    # 已装配的统一输入，顺序与配对由调用方保证
    messages: tuple[ProviderMessage, ...] = ()
    tools: tuple[ToolSpec, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()
    max_output_tokens: int | None = None
    # 过渡期桥接的原始请求：{"input": [...], "tools": [...]}，内核组装形状，
    # Responses 编码时原样直传，保证实际发送与审计持久化一致；统一输入仍填写，
    # 用于发送前证据、用量归因与 fake 回显
    raw_request: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "tools", tuple(self.tools))
        object.__setattr__(self, "tool_results", tuple(self.tool_results))
        raw = self.raw_request
        if raw is not None and not isinstance(raw, Mapping):
            raise TypeError("raw_request must be a mapping or None")
        # 原始请求只读引用，不做深拷贝，调用方保证当次调用内不变


@dataclass
class InvokeResult:
    output: list[dict[str, Any]]
    text: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    finish_reason: str = "completed"
    provider: str = ""
    model: str = ""
    response_id: str | None = None
    protocol: str = ""
    actual_model: str | None = None
    wire_evidence: dict[str, Any] = field(default_factory=dict)


class Observer(Protocol):
    # 请求证据发送前必须经确认回调持久化，无法保存不发送
    def confirm_request(self, evidence: Mapping[str, Any]) -> bool: ...
    def on_event(self, event: Mapping[str, Any]) -> None: ...


class NullObserver:
    def confirm_request(self, evidence: Mapping[str, Any]) -> bool:
        return True

    def on_event(self, event: Mapping[str, Any]) -> None:
        return None


class CancelRegistry:
    # 调用尝试级取消注册，按 attempt_id 隔离，支持多任务并发调用
    def __init__(self) -> None:
        from threading import Lock
        self._events: dict[str, Event] = {}
        self._lock = Lock()

    def register(self, attempt_id: str, event: Event) -> None:
        with self._lock:
            self._events[str(attempt_id)] = event

    def discard(self, attempt_id: str) -> None:
        with self._lock:
            self._events.pop(str(attempt_id), None)

    def contains(self, attempt_id: str) -> bool:
        with self._lock:
            return str(attempt_id) in self._events

    def cancel(self, attempt_id: str) -> bool:
        with self._lock:
            event = self._events.get(str(attempt_id))
        if event is None:
            return False
        event.set()
        return True


def build_request_evidence(
    frozen_target: FrozenTarget,
    provider_input: ProviderInput,
    session_id: str,
    attempt_id: str,
) -> dict[str, Any]:
    # 脱敏的发送前证据，不含 secret，只描述统一输入形状
    return {
        "target_key": frozen_target.target_key,
        "provider_id": frozen_target.provider_id,
        "model_id": frozen_target.model_id,
        "protocol": frozen_target.protocol,
        "model": frozen_target.model,
        "revision": frozen_target.revision,
        "session_id": session_id,
        "attempt_id": attempt_id,
        "message_count": len(provider_input.messages),
        "tool_count": len(provider_input.tools),
        "tool_result_count": len(provider_input.tool_results),
        "roles": [message.role for message in provider_input.messages],
        "tool_names": [tool.name for tool in provider_input.tools],
        "has_raw_request": provider_input.raw_request is not None,
    }


def invoke_once(
    frozen_target: FrozenTarget,
    provider_input: ProviderInput,
    session_id: str,
    attempt_id: str,
    abort_event: Event | None = None,
    observer: Observer | None = None,
    *,
    execution_scope: Any | None = None,
) -> InvokeResult:
    # 单次调用，不重试、不执行工具、不决定问答归属
    active_observer: Observer = observer if observer is not None else NullObserver()
    event = abort_event if abort_event is not None else Event()
    if frozen_target.protocol not in SUPPORTED_PROTOCOLS:
        raise UnsupportedProtocolError(str(frozen_target.protocol))
    if event.is_set():
        from .errors import CancelledError
        raise CancelledError()
    if frozen_target.protocol == "messages":
        _check_max_output_tokens(frozen_target, provider_input)
    evidence = build_request_evidence(frozen_target, provider_input, session_id, attempt_id)
    confirmed = active_observer.confirm_request(evidence)
    if not confirmed:
        raise RequestNotPersistedError()
    if event.is_set():
        from .errors import CancelledError
        raise CancelledError()
    if frozen_target.protocol == "fake":
        return _invoke_fake(frozen_target, provider_input, session_id, attempt_id, event, active_observer)
    if frozen_target.protocol == "responses":
        from .responses import invoke_responses
        return invoke_responses(
            frozen_target, provider_input, session_id, attempt_id,
            event, active_observer, execution_scope=execution_scope,
        )
    if frozen_target.protocol == "chat_completions":
        from .chat import invoke_chat
        return invoke_chat(
            frozen_target, provider_input, session_id, attempt_id,
            event, active_observer, execution_scope=execution_scope,
        )
    if frozen_target.protocol == "messages":
        from .messages import invoke_messages
        return invoke_messages(
            frozen_target, provider_input, session_id, attempt_id,
            event, active_observer, execution_scope=execution_scope,
        )
    raise ProviderError("unreachable", reason="provider_error")


def _check_max_output_tokens(frozen_target: FrozenTarget, provider_input: ProviderInput) -> None:
    # 协议要求显式输出上限时在发送前拒绝，不编造默认值
    if provider_input.max_output_tokens is None:
        raise ProviderError(
            "Messages protocol requires max_output_tokens",
            reason="provider_protocol",
        )


def _invoke_fake(
    frozen_target: FrozenTarget,
    provider_input: ProviderInput,
    session_id: str,
    attempt_id: str,
    abort_event: Event,
    observer: Observer,
) -> InvokeResult:
    # 测试用确定性输出，不触网，取消只看本次 abort_event
    if abort_event.is_set():
        from .errors import CancelledError
        raise CancelledError()
    texts = [message.content for message in provider_input.messages if message.role == "user"]
    text = texts[-1] if texts else "fake-ok"
    output = [{
        "id": f"fake-{attempt_id}",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text}],
    }]
    observer.on_event({
        "kind": "message",
        "id": f"fake-{attempt_id}",
        "session_id": session_id,
        "attempt_id": attempt_id,
        "provider": frozen_target.provider_id,
        "model": frozen_target.model,
    })
    return InvokeResult(
        output=output, text=text,
        usage={"reported": False, "input_tokens": 0, "output_tokens": 0},
        finish_reason="completed",
        provider=frozen_target.provider_id, model=frozen_target.model,
        response_id=f"fake-{attempt_id}", protocol="fake",
        actual_model=frozen_target.model,
        wire_evidence={"protocol": "fake", "attempt_id": attempt_id},
    )


def to_provider_input(
    messages: Sequence[Mapping[str, Any]] | Sequence[ProviderMessage],
    tools: Sequence[Mapping[str, Any]] | Sequence[ToolSpec] = (),
    tool_results: Sequence[Mapping[str, Any]] | Sequence[ToolResult] = (),
    max_output_tokens: int | None = None,
) -> ProviderInput:
    normalized_messages: list[ProviderMessage] = []
    for item in messages:
        if isinstance(item, ProviderMessage):
            normalized_messages.append(item)
        else:
            normalized_messages.append(ProviderMessage(
                role=str(item.get("role", "user")),
                content=str(item.get("content", "")),
                name=item.get("name"),
            ))
    normalized_tools: list[ToolSpec] = []
    for item in tools:
        if isinstance(item, ToolSpec):
            normalized_tools.append(item)
        else:
            normalized_tools.append(ToolSpec(
                name=str(item.get("name", "")),
                description=str(item.get("description", "")),
                parameters=item.get("parameters", {}),
            ))
    normalized_results: list[ToolResult] = []
    for item in tool_results:
        if isinstance(item, ToolResult):
            normalized_results.append(item)
        else:
            normalized_results.append(ToolResult(
                call_id=str(item.get("call_id", "")),
                name=str(item.get("name", "")),
                output=str(item.get("output", "")),
            ))
    return ProviderInput(
        messages=tuple(normalized_messages), tools=tuple(normalized_tools),
        tool_results=tuple(normalized_results), max_output_tokens=max_output_tokens,
    )
