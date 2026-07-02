"""agent_loop — the core primitive.

while: llm.chat -> record assistant turn -> if no tool_calls: stop(natural)
       else: for each tool_call: dispatch -> append role:tool message
Emits an event per step. Events never contain the API key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .llm import LlmClient
from .tools import dispatch

_TRUNC = 2000


def _truncate(s: str, n: int = _TRUNC) -> str:
    if s is None:
        return ""
    return s if len(s) <= n else s[:n] + f"...[truncated {len(s) - n} chars]"


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
    stopped_reason: str  # "natural" | "max_steps" | "terminal"
    tool_invocations: int
    terminal_call: dict | None = None  # args of the terminal tool that stopped the loop
    events: list = field(default_factory=list)
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    duration_ms: int = 0


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
) -> LoopResult:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
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

    while True:
        if steps >= max_steps:
            stopped_reason = "max_steps"
            emit({"type": "stop", "reason": "max_steps", "step": steps})
            break

        result = llm.chat(messages, tools)
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
            }
        )

        # Record assistant turn (spec §2 re-feed protocol).
        assistant_msg = {
            "role": "assistant",
            "content": result.text or None,
        }
        if result.tool_calls:
            assistant_msg["tool_calls"] = _serialize_tool_calls(result.tool_calls)
        messages.append(assistant_msg)

        # Stop condition: no tool_calls (only signal we trust for thinking models).
        if not result.tool_calls:
            final_text = result.text
            stopped_reason = "natural"
            emit({"type": "stop", "reason": "natural", "step": steps})
            # Stop hook: the stage ended naturally. The hook may inspect the
            # final text + transcript and return a routing/产出 dict, which we
            # surface as terminal_call so the orchestrator can consume it.
            if on_stop is not None:
                hooked = on_stop(final_text, messages)
                if hooked is not None:
                    terminal_call = hooked
            break

        # Execute every tool_call; feed each result back.
        stop_after = False
        for tc in result.tool_calls:
            name = tc.function.name
            raw_args = tc.function.arguments
            try:
                args = json.loads(raw_args) if raw_args else {}
                if not isinstance(args, dict):
                    args = {}
            except json.JSONDecodeError:
                args = {}
            output = dispatch(name, args, handlers_ctx)
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
            # Terminal tool: stop only if the handler accepted it (no Error回执).
            if (
                terminal_tools
                and name in terminal_tools
                and not output.startswith("Error:")
            ):
                terminal_call = {"name": name, "args": args}
                final_text = result.text or ""
                stop_after = True

        if stop_after:
            stopped_reason = "terminal"
            emit({"type": "stop", "reason": "terminal", "step": steps})
            break

    return LoopResult(
        final_text=final_text,
        steps=steps,
        stopped_reason=stopped_reason,
        tool_invocations=tool_invocations,
        terminal_call=terminal_call,
        events=events,
        calls=llm.calls_made,
        prompt_tokens=llm.prompt_tokens_total,
        completion_tokens=llm.completion_tokens_total,
        reasoning_tokens=llm.reasoning_tokens_total,
        duration_ms=sum(
            e.get("duration_ms", 0) for e in events if e.get("type") == "llm_call"
        ),
    )
