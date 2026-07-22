"""Thin wrapper over the OpenAI chat completions API.

Implements the function-calling protocol pinned in spec §2, plus budget
accounting and backoff retries on transient errors.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)


class BudgetExhausted(Exception):
    """Raised when the configured max_calls budget is exceeded."""


class BudgetAccountingError(Exception):
    """配置了 token 预算，但 provider 未返回可计量的 usage。"""


class ProviderUnavailable(Exception):
    """Transient provider retries were exhausted."""


class ProviderProtocolError(Exception):
    """The provider rejected or malformed the request protocol."""

    def __init__(
        self,
        message: str,
        *,
        call_recorded: bool = False,
        duration_ms: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        reasoning_tokens: int = 0,
    ):
        super().__init__(message)
        self.call_recorded = call_recorded
        self.duration_ms = duration_ms
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.reasoning_tokens = reasoning_tokens


class ContextOverflow(Exception):
    """The provider explicitly reported context_length_exceeded."""


# Transient errors worth retrying with backoff.
_RETRYABLE = (RateLimitError, InternalServerError, APITimeoutError, APIConnectionError)


_MISSING = object()


def _is_nonnegative_int(value) -> bool:
    return type(value) is int and value >= 0


@dataclass
class CallResult:
    text: str
    tool_calls: list  # raw tool_calls objects (for re-feeding / serialization)
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    duration_ms: int
    stopped_reason: str | None = None
    stop_detail: str | None = None


_FINISH_REASONS = frozenset({"stop", "length", "tool_calls", "content_filter"})


@dataclass
class LlmClient:
    client: object
    model: str
    max_calls: int | None = None
    max_tokens: int | None = None
    max_seconds: float | None = None
    # cumulative accounting
    calls_made: int = field(default=0, init=False)
    prompt_tokens_total: int = field(default=0, init=False)
    completion_tokens_total: int = field(default=0, init=False)
    reasoning_tokens_total: int = field(default=0, init=False)
    usage_by_role: dict = field(default_factory=dict, init=False)
    retry_attempts: int = field(default=0, init=False)
    _started_at: float = field(default_factory=time.monotonic, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_calls is not None and self.max_calls <= 0:
            raise ValueError("max_calls must be positive")
        if self.max_tokens is not None and self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if self.max_seconds is not None:
            if not math.isfinite(self.max_seconds) or self.max_seconds <= 0:
                raise ValueError("max_seconds must be positive and finite")

    def check_budget(self, *, before_call: bool = False) -> None:
        if before_call and self.max_calls is not None:
            if self.calls_made >= self.max_calls:
                raise BudgetExhausted(f"max_calls={self.max_calls} exceeded")

        total_tokens = self.prompt_tokens_total + self.completion_tokens_total
        if self.max_tokens is not None:
            exhausted = (
                total_tokens >= self.max_tokens
                if before_call
                else total_tokens > self.max_tokens
            )
            if exhausted:
                raise BudgetExhausted(
                    f"max_tokens={self.max_tokens} exceeded (used={total_tokens})"
                )

        if self.max_seconds is not None:
            elapsed = time.monotonic() - self._started_at
            if elapsed >= self.max_seconds:
                raise BudgetExhausted(
                    f"max_seconds={self.max_seconds} exceeded (elapsed={elapsed:.3f})"
                )

    def chat(
        self,
        messages: list,
        tools: list,
        max_completion_tokens: int = 8000,
        accounting_role: str | None = None,
    ) -> CallResult:
        self.check_budget(before_call=True)

        started = time.monotonic()
        resp = self._create_with_retry(messages, tools, max_completion_tokens)
        duration_ms = int((time.monotonic() - started) * 1000)

        self.calls_made += 1
        role_usage = None
        if accounting_role is not None:
            role_usage = self.usage_by_role.setdefault(
                accounting_role,
                {
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "reasoning_tokens": 0,
                    "llm_duration_ms": 0,
                },
            )
            role_usage["calls"] += 1
            role_usage["llm_duration_ms"] += duration_ms

        usage = getattr(resp, "usage", _MISSING)
        prompt_tokens = getattr(usage, "prompt_tokens", _MISSING)
        completion_tokens = getattr(usage, "completion_tokens", _MISSING)
        details = getattr(usage, "completion_tokens_details", None)
        reasoning_tokens = (
            0
            if details is None
            else getattr(details, "reasoning_tokens", _MISSING)
        )
        if reasoning_tokens is None:
            reasoning_tokens = 0
        if not (
            _is_nonnegative_int(prompt_tokens)
            and _is_nonnegative_int(completion_tokens)
            and _is_nonnegative_int(reasoning_tokens)
        ):
            return CallResult(
                text="",
                tool_calls=[],
                finish_reason="",
                prompt_tokens=0,
                completion_tokens=0,
                reasoning_tokens=0,
                duration_ms=duration_ms,
                stopped_reason="budget_accounting_error",
                stop_detail="provider response did not include valid token usage",
            )

        self.prompt_tokens_total += prompt_tokens
        self.completion_tokens_total += completion_tokens
        self.reasoning_tokens_total += reasoning_tokens
        if role_usage is not None:
            role_usage["prompt_tokens"] += prompt_tokens
            role_usage["completion_tokens"] += completion_tokens
            role_usage["reasoning_tokens"] += reasoning_tokens

        def malformed_response():
            return ProviderProtocolError(
                "malformed provider response",
                call_recorded=True,
                duration_ms=duration_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                reasoning_tokens=reasoning_tokens,
            )

        choices = getattr(resp, "choices", _MISSING)
        if not isinstance(choices, (list, tuple)) or not choices:
            raise malformed_response()
        choice = choices[0]
        msg = getattr(choice, "message", _MISSING)
        if msg is _MISSING or msg is None:
            raise malformed_response()

        finish_reason = getattr(choice, "finish_reason", _MISSING)
        content = getattr(msg, "content", _MISSING)
        tool_calls = getattr(msg, "tool_calls", _MISSING)
        if finish_reason not in _FINISH_REASONS:
            raise malformed_response()
        if content is _MISSING or not (
            content is None or isinstance(content, str)
        ):
            raise malformed_response()
        if tool_calls is None:
            tool_calls = []
        elif not isinstance(tool_calls, (list, tuple)):
            raise malformed_response()
        for tool_call in tool_calls:
            function = getattr(tool_call, "function", _MISSING)
            if (
                not isinstance(getattr(tool_call, "id", None), str)
                or function is _MISSING
                or not isinstance(getattr(function, "name", None), str)
                or not isinstance(getattr(function, "arguments", None), str)
            ):
                raise malformed_response()

        stopped_reason = None
        stop_detail = None
        try:
            self.check_budget()
        except BudgetExhausted as exc:
            stopped_reason = "budget_exhausted"
            stop_detail = str(exc)

        return CallResult(
            text=content or "",
            tool_calls=list(tool_calls),
            finish_reason=finish_reason,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            duration_ms=duration_ms,
            stopped_reason=stopped_reason,
            stop_detail=stop_detail,
        )

    def _create_with_retry(self, messages, tools, max_completion_tokens):
        last_exc = None
        for attempt in range(4):  # 1 try + up to 3 retries
            self.check_budget()
            if attempt:
                self.retry_attempts += 1
            try:
                return self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    max_completion_tokens=max_completion_tokens,
                )
            except BadRequestError as exc:
                if exc.code == "context_length_exceeded":
                    raise ContextOverflow("provider context length exceeded") from exc
                raise ProviderProtocolError("provider rejected request protocol") from exc
            except _RETRYABLE as exc:
                last_exc = exc
                if attempt == 3:
                    break
                delay = min(2 ** attempt, 8)
                if self.max_seconds is not None:
                    remaining = self.max_seconds - (time.monotonic() - self._started_at)
                    if remaining <= 0:
                        self.check_budget()
                    delay = min(delay, remaining)
                time.sleep(delay)
            except APIStatusError as exc:
                raise ProviderProtocolError("provider request failed") from exc

        self.check_budget()
        raise ProviderUnavailable("transient provider retries exhausted") from last_exc
