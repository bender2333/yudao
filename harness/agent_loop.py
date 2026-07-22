"""agent_loop — the core primitive.

while: llm.chat -> classify provider stop -> record assistant turn
       -> dispatch tool calls or classify the terminal finish reason
Emits an event per step. Events never contain the API key.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from .llm import (
    BudgetAccountingError,
    BudgetExhausted,
    ContextOverflow,
    LlmClient,
    ProviderProtocolError,
    ProviderUnavailable,
)
from .tools import dispatch

_TRUNC = 2000


def _truncate(s: str, n: int = _TRUNC) -> str:
    if s is None:
        return ""
    return s if len(s) <= n else s[:n] + f"...[truncated {len(s) - n} chars]"


def _dispatch_with_extras(name, args, handlers_ctx, extra_handlers):
    """Extra handlers (llm/workspace-bound closures, e.g. cross-stage consults)
    take precedence; otherwise fall back to the standard stateless dispatch."""
    if extra_handlers and name in extra_handlers:
        try:
            return extra_handlers[name](**args)
        except (
            BudgetAccountingError,
            BudgetExhausted,
            ContextOverflow,
            ProviderProtocolError,
            ProviderUnavailable,
        ):
            raise
        except Exception as e:  # a consult must never crash the caller's loop
            return f"Error: {type(e).__name__}: {e}"
    return dispatch(name, args, handlers_ctx)


def _serialize_tool_calls(tool_calls: list) -> list:
    """Serialize raw tool_call objects for the assistant message re-feed."""
    out = []
    for tc in tool_calls:
        out.append(
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
        )
    return out


@dataclass
class LoopResult:
    final_text: str
    steps: int
    stopped_reason: str
    tool_invocations: int
    terminal_call: dict | None = None  # args of the terminal tool that stopped the loop
    events: list = field(default_factory=list)
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    duration_ms: int = 0
    content_filter_retries: int = 0


@dataclass
class AgentSession:
    """单个角色在一次 run 内独占的会话历史。"""

    role: str
    system: str
    tools: list
    messages: list[dict] = field(default_factory=list, init=False)
    activates: int = 0

    def __post_init__(self) -> None:
        if not self.messages:
            self.messages.append({"role": "system", "content": self.system})


def activate(
    session: AgentSession,
    user_turn: str,
    *,
    llm: LlmClient,
    handlers_ctx: str,
    max_steps: int = 40,
    on_event=None,
    terminal_tools: set | None = None,
    on_stop=None,
    extra_handlers: dict | None = None,
    keep_history: bool = True,
) -> LoopResult:
    """追加本轮交接，并在同一角色历史上续跑。"""
    if not keep_history:
        session.messages[:] = [{"role": "system", "content": session.system}]
    session.activates += 1
    return run_agent_loop(
        llm=llm,
        system=session.system,
        user=user_turn,
        tools=session.tools,
        handlers_ctx=handlers_ctx,
        max_steps=max_steps,
        on_event=on_event,
        terminal_tools=terminal_tools,
        on_stop=on_stop,
        extra_handlers=extra_handlers,
        accounting_role=session.role,
        messages=session.messages,
    )


def run_agent_loop(
    llm: LlmClient,
    system: str,
    user: str,
    tools: list,
    handlers_ctx: str,
    max_steps: int = 40,
    on_event=None,
    terminal_tools: set | None = None,
    on_stop=None,
    extra_handlers: dict | None = None,
    *,
    accounting_role: str | None = None,
    messages: list[dict] | None = None,
) -> LoopResult:
    allowed_tools = {tool["function"]["name"] for tool in tools}
    started = time.monotonic()
    calls_before = llm.calls_made
    prompt_tokens_before = llm.prompt_tokens_total
    completion_tokens_before = llm.completion_tokens_total
    reasoning_tokens_before = llm.reasoning_tokens_total
    if messages is None:
        messages = [{"role": "system", "content": system}]
    messages.append({"role": "user", "content": user})
    events: list = []

    def emit(event: dict) -> None:
        events.append(event)
        if on_event is not None:
            on_event(event)

    steps = 0
    tool_invocations = 0
    final_text = ""
    stopped_reason = "max_steps"
    terminal_call = None
    content_filter_retries = 0
    content_filter_retry_available = True
    pending_content_filter_retry = False

    while True:
        if steps >= max_steps:
            stopped_reason = "max_steps"
            emit({"type": "stop", "reason": "max_steps", "step": steps})
            break

        try:
            result = llm.chat(messages, tools, accounting_role=accounting_role)
        except (BudgetAccountingError, BudgetExhausted) as exc:
            stopped_reason = (
                "budget_accounting_error"
                if isinstance(exc, BudgetAccountingError)
                else "budget_exhausted"
            )
            emit({"type": "stop", "reason": stopped_reason, "step": steps})
            break
        except (ProviderUnavailable, ProviderProtocolError, ContextOverflow) as exc:
            if pending_content_filter_retry:
                content_filter_retries += 1
                pending_content_filter_retry = False
                emit(
                    {
                        "type": "provider_retry",
                        "reason": "content_filter",
                        "step": steps + 1,
                    }
                )
            if isinstance(exc, ProviderUnavailable):
                stopped_reason = "provider_unavailable"
            elif isinstance(exc, ContextOverflow):
                stopped_reason = "context_overflow"
            else:
                stopped_reason = "provider_protocol_error"
            emit(
                {
                    "type": "provider_error",
                    "reason": stopped_reason,
                    "error_type": type(exc).__name__,
                    "step": steps,
                }
            )
            emit({"type": "stop", "reason": stopped_reason, "step": steps})
            break
        if pending_content_filter_retry:
            content_filter_retries += 1
            pending_content_filter_retry = False
            emit(
                {
                    "type": "provider_retry",
                    "reason": "content_filter",
                    "step": steps + 1,
                }
            )
        steps += 1
        emit(
            {
                "type": "llm_call",
                "step": steps,
                "finish_reason": result.finish_reason,
                "has_tool_calls": bool(result.tool_calls),
                "text": _truncate(result.text),
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "reasoning_tokens": result.reasoning_tokens,
                "duration_ms": result.duration_ms,
                "stopped_reason": result.stopped_reason,
            }
        )

        if (
            result.stopped_reason is not None
            and result.finish_reason == "content_filter"
        ):
            final_text = result.text
            stopped_reason = result.stopped_reason
            emit(
                {
                    "type": "stop",
                    "reason": stopped_reason,
                    "detail": result.stop_detail,
                    "step": steps,
                }
            )
            break

        if result.finish_reason == "content_filter":
            if content_filter_retry_available:
                content_filter_retry_available = False
                pending_content_filter_retry = True
                continue
            stopped_reason = "provider_blocked"
            emit({"type": "stop", "reason": stopped_reason, "step": steps})
            break

        if (
            result.stopped_reason is None
            and result.tool_calls
            and result.finish_reason != "tool_calls"
        ):
            final_text = result.text
            stopped_reason = (
                "output_truncated"
                if result.finish_reason == "length"
                else "provider_protocol_error"
            )
            emit({"type": "stop", "reason": stopped_reason, "step": steps})
            break

        # Record assistant turn (spec §2 re-feed protocol).
        assistant_msg = {
            "role": "assistant",
            "content": result.text or None,
        }
        if result.tool_calls:
            assistant_msg["tool_calls"] = _serialize_tool_calls(result.tool_calls)
        messages.append(assistant_msg)

        if result.stopped_reason is not None:
            final_text = result.text
            stopped_reason = result.stopped_reason
            emit(
                {
                    "type": "stop",
                    "reason": stopped_reason,
                    "detail": result.stop_detail,
                    "step": steps,
                }
            )
            break

        if not result.tool_calls:
            final_text = result.text
            if result.finish_reason in {"stop", ""}:
                stopped_reason = "natural"
                # The hook may turn a natural conclusion into a routed terminal call.
                if on_stop is not None:
                    try:
                        hooked = on_stop(final_text, messages)
                        if hooked is not None:
                            terminal_call = hooked
                    except (BudgetAccountingError, BudgetExhausted) as exc:
                        stopped_reason = (
                            "budget_accounting_error"
                            if isinstance(exc, BudgetAccountingError)
                            else "budget_exhausted"
                        )
            elif result.finish_reason == "length":
                stopped_reason = "output_truncated"
            else:
                stopped_reason = "provider_protocol_error"
            emit({"type": "stop", "reason": stopped_reason, "step": steps})
            break

        # Execute every tool_call; feed each result back.
        stop_after = False
        forced_stop_reason = None
        for tc in result.tool_calls:
            name = tc.function.name
            raw_args = tc.function.arguments
            try:
                args = json.loads(raw_args) if raw_args else {}
                if not isinstance(args, dict):
                    args = {}
            except json.JSONDecodeError:
                args = {}
            if name not in allowed_tools:
                output = f"Error: tool not available in this stage: {name}"
            else:
                check_budget = getattr(llm, "check_budget", None)
                if check_budget is not None:
                    try:
                        check_budget()
                    except BudgetExhausted:
                        output = "Error: run budget exhausted"
                        forced_stop_reason = "budget_exhausted"
                if forced_stop_reason is None:
                    try:
                        output = _dispatch_with_extras(
                            name, args, handlers_ctx, extra_handlers
                        )
                    except BudgetExhausted:
                        output = "Error: run budget exhausted"
                        forced_stop_reason = "budget_exhausted"
                    except BudgetAccountingError:
                        output = "Error: token usage unavailable"
                        forced_stop_reason = "budget_accounting_error"
                    except (
                        ProviderUnavailable,
                        ProviderProtocolError,
                        ContextOverflow,
                    ) as exc:
                        if isinstance(exc, ProviderUnavailable):
                            forced_stop_reason = "provider_unavailable"
                        elif isinstance(exc, ContextOverflow):
                            forced_stop_reason = "context_overflow"
                        else:
                            forced_stop_reason = "provider_protocol_error"
                        output = f"Error: {forced_stop_reason.replace('_', ' ')}"
                        emit(
                            {
                                "type": "provider_error",
                                "reason": forced_stop_reason,
                                "error_type": type(exc).__name__,
                                "step": steps,
                            }
                        )
            if forced_stop_reason is None:
                check_budget = getattr(llm, "check_budget", None)
                if check_budget is not None:
                    try:
                        check_budget()
                    except BudgetExhausted:
                        forced_stop_reason = "budget_exhausted"
            tool_invocations += 1
            emit(
                {
                    "type": "tool_call",
                    "step": steps,
                    "name": name,
                    "args": _truncate(json.dumps(args, ensure_ascii=False)),
                    "output": _truncate(output),
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": output,
                }
            )
            if forced_stop_reason is not None:
                break
            # Terminal tool: stop only if the handler accepted it (no Error回执).
            if (
                terminal_tools
                and name in terminal_tools
                and not output.startswith("Error:")
            ):
                terminal_call = {"name": name, "args": args}
                final_text = result.text or ""
                stop_after = True

        if forced_stop_reason is not None:
            stopped_reason = forced_stop_reason
            emit({"type": "stop", "reason": stopped_reason, "step": steps})
            break
        if stop_after:
            stopped_reason = "terminal"
            emit({"type": "stop", "reason": "terminal", "step": steps})
            break

        content_filter_retry_available = True

    return LoopResult(
        final_text=final_text,
        steps=steps,
        stopped_reason=stopped_reason,
        tool_invocations=tool_invocations,
        terminal_call=terminal_call,
        events=events,
        content_filter_retries=content_filter_retries,
        calls=llm.calls_made - calls_before,
        prompt_tokens=llm.prompt_tokens_total - prompt_tokens_before,
        completion_tokens=llm.completion_tokens_total - completion_tokens_before,
        reasoning_tokens=llm.reasoning_tokens_total - reasoning_tokens_before,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
