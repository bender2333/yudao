from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Container
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Mapping, Sequence

from .call import ModelCall
from .errors import CancelledError, ProviderError, UnsupportedProtocolError
from .reasoning import ReasoningOutput
from .resolve import FrozenTarget
from .store import SUPPORTED_PROTOCOLS

# 协议实现把一条观察交给调用方；调用方处理完这一条之后才返回
Emit = Callable[[dict[str, Any]], Awaitable[None]]


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
    # 内核装配的原始请求：{"input": [...], "tools": [...]}。Responses 编码时原样直传，保证实际发送与审计
    # 记录一致；Chat 与 Messages 按原顺序翻译。统一输入仍填写，用于没有原始请求的诊断调用与 fake 回显
    raw_request: Mapping[str, Any] | None = None
    tool_choice: str = "auto"

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
    # 这次回答里上游返回的推理内容，带产生它的连接、协议与上游模型（设计说明第 7.6 节）；
    # 与 output 分开保存，不进入协议无关的部门历史条目列表
    reasoning: ReasoningOutput | None = None
    wire_evidence: dict[str, Any] = field(default_factory=dict)


class CancelRegistry:
    # 正在进行的调用尝试：按 attempt_id 找到这次调用的任务，可以从任何线程取消。
    # 只登记正在进行的尝试；调用开始之前收到的取消由调用方记下，随调用交给 stream_invocation
    def __init__(self) -> None:
        self._active: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Task]] = {}
        self._lock = Lock()

    def register(self, attempt_id: str, loop: asyncio.AbstractEventLoop, task: asyncio.Task) -> None:
        with self._lock:
            if attempt_id in self._active:
                # 同一次调用尝试不允许并发执行，避免两个请求共享取消身份
                raise ProviderError("Model invocation already has an active attempt", reason="provider_error")
            self._active[attempt_id] = (loop, task)

    def discard(self, attempt_id: str, task: asyncio.Task) -> None:
        with self._lock:
            if self._active.get(attempt_id, (None, None))[1] is task:
                del self._active[attempt_id]

    def cancel(self, attempt_id: str) -> bool:
        # 返回是否找到正在进行的这次尝试；找不到时不留下记录。
        # 在锁内安排取消：登记在调用结束时于它的事件循环中移除，持有锁期间事件循环一定仍在运行
        with self._lock:
            entry = self._active.get(attempt_id)
            if entry is None:
                return False
            loop, task = entry
            loop.call_soon_threadsafe(task.cancel)
            return True


def check_target_availability(frozen_target: FrozenTarget) -> dict[str, Any]:
    # 发送前的通用可用性检查：凭据、模型、地址与超时，不触网，按协议同规则
    from math import isfinite
    from urllib.parse import urlsplit

    missing = []
    if frozen_target.protocol != "fake" and not frozen_target.api_key:
        missing.append("provider credential")
    if not frozen_target.model:
        missing.append("model")
    if missing:
        return {"available": False, "reason": "provider_unavailable",
                "message": "Missing configuration: " + ", ".join(missing)}
    if frozen_target.protocol != "fake":
        try:
            url = urlsplit(frozen_target.base_url or "")
            valid_url = url.scheme in {"https", "http"} and bool(url.hostname) \
                and url.username is None and url.password is None
        except ValueError:
            valid_url = False
        if not valid_url:
            return {"available": False, "reason": "provider_unavailable",
                    "message": "Invalid provider base URL"}
        timeout = frozen_target.timeout_sec
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) \
                or not isfinite(float(timeout)) or float(timeout) <= 0:
            return {"available": False, "reason": "provider_unavailable",
                    "message": "Provider timeout must be positive and finite"}
    return {"available": True, "reason": "", "message": ""}


async def invoke(
    frozen_target: FrozenTarget,
    provider_input: ProviderInput,
    session_id: str,
    attempt_id: str,
    emit: Emit,
    *,
    connections: Any | None = None,
) -> InvokeResult:
    # 单次调用，不重试、不执行工具、不决定问答归属；观察逐条交给 emit
    if frozen_target.protocol not in SUPPORTED_PROTOCOLS:
        raise UnsupportedProtocolError(str(frozen_target.protocol))
    if frozen_target.protocol == "messages":
        _check_max_output_tokens(frozen_target, provider_input)
    if frozen_target.protocol == "fake":
        return await _invoke_fake(frozen_target, provider_input, session_id, attempt_id, emit)
    if frozen_target.protocol == "responses":
        from .responses import invoke_responses
        return await invoke_responses(
            frozen_target, provider_input, session_id, attempt_id, emit, connections=connections,
        )
    if frozen_target.protocol == "chat_completions":
        from .chat import invoke_chat
        return await invoke_chat(frozen_target, provider_input, session_id, attempt_id, emit)
    if frozen_target.protocol == "messages":
        from .messages import invoke_messages
        return await invoke_messages(frozen_target, provider_input, session_id, attempt_id, emit)
    raise ProviderError("unreachable", reason="provider_error")


async def stream_invocation(
    frozen_target: FrozenTarget,
    provider_input: ProviderInput,
    session_id: str,
    attempt_id: str,
    cancels: CancelRegistry,
    *,
    connections: Any | None = None,
    cancelled: Container[str] = (),
) -> AsyncIterator[dict[str, Any] | InvokeResult]:
    # 单次调用的流式结果：协议实现交出的每条观察先交给调用方，调用方取下一条时调用才继续；最后交出调用结果。
    # 调用在自己的任务中执行，按 attempt_id 登记，取消只作用于这次尝试。
    # cancelled 是调用方在尝试开始之前收到取消的尝试身份，这次尝试在其中时一开始就取消
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[dict[str, Any], asyncio.Future] | None] = asyncio.Queue()

    async def emit(event: dict[str, Any]) -> None:
        handled = loop.create_future()
        queue.put_nowait((event, handled))
        await handled

    task = loop.create_task(invoke(frozen_target, provider_input, session_id, attempt_id, emit,
                                   connections=connections))
    try:
        cancels.register(attempt_id, loop, task)
    except ProviderError:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise
    # 登记之后再看调用方记下的取消：调用方先记下再通知登记表，取消落在登记之前或之后都不会漏掉
    if attempt_id in cancelled:
        task.cancel()
    task.add_done_callback(lambda _task: queue.put_nowait(None))
    try:
        while (item := await queue.get()) is not None:
            event, handled = item
            yield event
            if not handled.done():
                handled.set_result(None)
        if task.cancelled():
            raise CancelledError()
        yield task.result()
    finally:
        cancels.discard(attempt_id, task)
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def provider_input_for(call: ModelCall) -> ProviderInput:
    # 由模型调用合同得到统一输入：原始请求原样直传，统一消息与工具结果供 fake 回显
    messages: list[ProviderMessage] = []
    call_names: dict[str, str] = {}
    for item in call.input_items:
        if item.get("type") == "function_call":
            call_id = item.get("call_id")
            name = item.get("name")
            if isinstance(call_id, str) and isinstance(name, str):
                call_names[call_id] = name
    tool_results: list[ToolResult] = []
    for item in call.input_items:
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
                messages.append(ProviderMessage(role=role, content=content, name=item.get("name")))
    tools: list[ToolSpec] = []
    for item in call.tools:
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
        messages=tuple(messages), tools=tuple(tools), tool_results=tuple(tool_results),
        max_output_tokens=call.max_output_tokens,
        raw_request={"input": list(call.input_items), "tools": list(call.tools)},
        tool_choice=call.tool_choice,
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


def _check_max_output_tokens(frozen_target: FrozenTarget, provider_input: ProviderInput) -> None:
    # 协议要求显式输出上限时在发送前拒绝，不编造默认值
    if provider_input.max_output_tokens is None:
        raise ProviderError(
            "Messages protocol requires max_output_tokens",
            reason="provider_protocol",
        )


async def _invoke_fake(
    frozen_target: FrozenTarget,
    provider_input: ProviderInput,
    session_id: str,
    attempt_id: str,
    emit: Emit,
) -> InvokeResult:
    # 测试用确定性输出，不触网
    texts = [message.content for message in provider_input.messages if message.role == "user"]
    text = texts[-1] if texts else "fake-ok"
    output = [{
        "id": f"fake-{attempt_id}",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text}],
    }]
    await emit({
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
