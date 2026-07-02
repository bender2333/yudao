"""Thin wrapper over the OpenAI chat completions API.

Implements the function-calling protocol pinned in spec §2, plus budget
accounting and backoff retries on transient errors.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError


class BudgetExhausted(Exception):
    """Raised when the configured max_calls budget is exceeded."""


# Transient errors worth retrying with backoff.
_RETRYABLE = (RateLimitError, InternalServerError, APITimeoutError, APIConnectionError)


@dataclass
class CallResult:
    text: str
    tool_calls: list  # raw tool_calls objects (for re-feeding / serialization)
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    duration_ms: int


@dataclass
class LlmClient:
    client: object
    model: str
    max_calls: int | None = None
    # cumulative accounting
    calls_made: int = field(default=0, init=False)
    prompt_tokens_total: int = field(default=0, init=False)
    completion_tokens_total: int = field(default=0, init=False)
    reasoning_tokens_total: int = field(default=0, init=False)

    def chat(self, messages: list, tools: list, max_completion_tokens: int = 8000) -> CallResult:
        if self.max_calls is not None and self.calls_made >= self.max_calls:
            raise BudgetExhausted(f"max_calls={self.max_calls} exceeded")

        started = time.monotonic()
        resp = self._create_with_retry(messages, tools, max_completion_tokens)
        duration_ms = int((time.monotonic() - started) * 1000)

        self.calls_made += 1

        choice = resp.choices[0]
        msg = choice.message
        finish_reason = choice.finish_reason or ""
        text = msg.content or ""
        tool_calls = list(msg.tool_calls or [])

        prompt_tokens = 0
        completion_tokens = 0
        reasoning_tokens = 0
        usage = getattr(resp, "usage", None)
        if usage is not None:
            prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
            completion_tokens = getattr(usage, "completion_tokens", 0) or 0
            details = getattr(usage, "completion_tokens_details", None)
            if details is not None:
                reasoning_tokens = getattr(details, "reasoning_tokens", 0) or 0

        self.prompt_tokens_total += prompt_tokens
        self.completion_tokens_total += completion_tokens
        self.reasoning_tokens_total += reasoning_tokens

        return CallResult(
            text=text,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            duration_ms=duration_ms,
        )

    def _create_with_retry(self, messages, tools, max_completion_tokens):
        last_exc = None
        for attempt in range(4):  # 1 try + up to 3 retries
            try:
                return self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    max_completion_tokens=max_completion_tokens,
                )
            except _RETRYABLE as exc:
                last_exc = exc
                if attempt == 3:
                    break
                time.sleep(min(2 ** attempt, 8))
        raise last_exc
