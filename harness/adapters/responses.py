"""A single stateless Responses request; department and tool execution live above it."""

from __future__ import annotations

import asyncio
import email.utils
import json
import math
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any
from urllib.parse import urlsplit

import httpx
from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    DefaultAsyncHttpxClient,
)

from ..models import Usage
from .base import Availability, ModelObservation, ModelRequest, ModelResponse, ProviderError


@dataclass(frozen=True)
class ResponsesConfig:
    model: str = ""
    api_key: str = field(default="", repr=False)
    provider: str = "openai"
    base_url: str = "https://api.openai.com/v1"
    timeout_sec: float = 600.0


class _TransportTrace:
    """Keep only safe transport phase facts for one model request."""

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


class ResponsesAdapter:
    name = "responses"

    def __init__(self, config: ResponsesConfig) -> None:
        self.config = config
        self.model = self.config.model or "unconfigured"
        self._lock = Lock()
        self._active: tuple[str, asyncio.AbstractEventLoop, asyncio.Task] | None = None

    def availability(self) -> Availability:
        missing = []
        if not self.config.api_key:
            missing.append("provider credential")
        if not self.config.model:
            missing.append("model")
        if missing:
            return Availability(False, "provider_unavailable", "Missing configuration: " + ", ".join(missing))
        try:
            url = urlsplit(self.config.base_url)
            valid_url = url.scheme in {"https", "http"} and bool(url.hostname) and not url.username and not url.password
        except ValueError:
            valid_url = False
        if not valid_url:
            return Availability(False, "provider_unavailable", "Invalid provider base URL")
        if not math.isfinite(self.config.timeout_sec) or self.config.timeout_sec <= 0:
            return Availability(False, "provider_unavailable", "Provider timeout must be positive and finite")
        if not self.config.provider:
            return Availability(False, "provider_unavailable", "Provider identity must not be empty")
        return Availability(True)

    def abort(self, session_id: str) -> None:
        with self._lock:
            if self._active is not None and self._active[0] == session_id:
                _, loop, task = self._active
                loop.call_soon_threadsafe(task.cancel)

    def complete(self, request: ModelRequest) -> ModelResponse:
        availability = self.availability()
        if not availability.available:
            raise ProviderError(availability.message, reason=availability.reason)
        if request.abort_flag.is_set():
            raise ProviderError("Model request cancelled", reason="cancelled")
        try:
            return asyncio.run(self._complete(request))
        except ProviderError:
            raise
        except (TimeoutError, APITimeoutError) as exc:
            raise ProviderError("Model request timed out", reason="provider_timeout", retryable=True,
                                diagnostics=_transport_diagnostics("timeout", exc)) from exc
        except APIStatusError as exc:
            code = _error_code(exc.body)
            reason = "context_overflow" if _is_context_overflow(code) else "provider_error"
            # Provider error bodies may echo input or credentials; retain only status.
            diagnostics: dict[str, Any] = {"status_code": exc.status_code}
            safe_code = _safe_error_code(code)
            if safe_code is not None:
                diagnostics["error_code"] = safe_code
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
                diagnostics=_diagnostic_code(code, "provider_response"),
            ) from exc
        except json.JSONDecodeError as exc:
            raise ProviderError("Model provider returned malformed stream JSON") from exc

    async def _complete(self, request: ModelRequest) -> ModelResponse:
        loop = asyncio.get_running_loop()
        trace = _TransportTrace()
        with self._lock:
            if self._active is not None:
                raise ProviderError("Responses adapter already has an active model request")
            task = asyncio.create_task(self._stream_once(request, trace))
            self._active = (request.session_id, loop, task)
        watcher = asyncio.create_task(self._watch_abort(request, task))
        try:
            async with asyncio.timeout(self.config.timeout_sec):
                return await task
        except asyncio.CancelledError as exc:
            raise ProviderError("Model request cancelled", reason="cancelled") from exc
        except Exception as exc:
            _attach_transport_trace(exc, trace.snapshot())
            raise
        finally:
            with self._lock:
                self._active = None
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)

    @staticmethod
    async def _watch_abort(request: ModelRequest, task: asyncio.Task) -> None:
        while not task.done():
            if request.abort_flag.is_set():
                task.cancel()
                return
            await asyncio.sleep(0.02)

    async def _stream_once(self, request: ModelRequest, trace: _TransportTrace) -> ModelResponse:
        started = time.monotonic()
        seen_items: set[str] = set()
        observation_errors: list[BaseException] = []
        async def observe_request(http_request: httpx.Request) -> None:
            http_request.extensions["trace"] = trace
            try:
                body = _request_body(http_request)
                request.observe(ModelObservation(
                    id=_request_observation_id(request),
                    kind="request",
                    payload=body,
                    provider=self.config.provider,
                    model=self.config.model,
                ))
            except BaseException as exc:
                observation_errors.append(exc)
                raise

        http_client = DefaultAsyncHttpxClient(
            timeout=self.config.timeout_sec,
            event_hooks={"request": [observe_request]},
        )
        async with AsyncOpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.timeout_sec,
            max_retries=0,
            http_client=http_client,
        ) as client:
            output_limit = {} if request.max_output_tokens is None else {"max_output_tokens": request.max_output_tokens}
            try:
                stream = await client.responses.create(
                    model=self.config.model,
                    input=request.input_items,
                    tools=request.tools,
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
            async with stream:
                async for event in _provider_events(stream, trace):
                    if request.abort_flag.is_set():
                        raise ProviderError("Model request cancelled", reason="cancelled")
                    if event.type == "response.output_item.done":
                        self._observe_item(request, event.item.model_dump(mode="json", exclude_unset=True), seen_items)
                    elif event.type in {"response.completed", "response.incomplete", "response.failed"}:
                        response = event.response
                        actual_model = _actual_model(response)
                        output = [item.model_dump(mode="json", exclude_unset=True) for item in (response.output or [])]
                        for item in output:
                            self._observe_item(request, item, seen_items, actual_model=actual_model)
                        raw_usage = response.usage.model_dump(mode="json", exclude_unset=True) if response.usage else None
                        usage = _usage(raw_usage, started)
                        request.observe(ModelObservation(
                            id=response.id, kind="usage",
                            payload={"response_id": response.id, "usage": raw_usage},
                            usage=usage, provider=self.config.provider, model=response.model,
                        ))
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
                        return ModelResponse(
                            output=output, usage=usage, provider=self.config.provider,
                            model=actual_model or "", response_id=response.id,
                        )
                    elif event.type == "error":
                        reason = "context_overflow" if _is_context_overflow(event.code) else "provider_error"
                        raise ProviderError(
                            "Model provider reported a stream error", reason=reason,
                            retryable=reason != "context_overflow" and _retryable_code(event.code),
                            diagnostics=_diagnostic_code(event.code, "stream_error"),
                        )
        raise ProviderError(
            "Model response stream ended before a terminal response",
            retryable=True,
            diagnostics=_transport_diagnostics("stream_incomplete", None, trace),
        )

    def _observe_item(
        self,
        request: ModelRequest,
        item: dict[str, Any],
        seen: set[str],
        *,
        actual_model: str | None = None,
    ) -> None:
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
        request.observe(ModelObservation(
            id=item_id, kind="message", payload=item, text=text,
            provider=self.config.provider,
            model=_actual_model(item) or actual_model,
        ))


def _error_code(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None
    error = body.get("error", body)
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) else None


def _actual_model(value: Any) -> str | None:
    """读取服务实际返回的模型；配置中的请求模型不是返回模型证据。"""

    model = getattr(value, "model", None)
    if model is None and isinstance(value, dict):
        model = value.get("model")
    return model.strip() if isinstance(model, str) and model.strip() else None


def _request_observation_id(request: ModelRequest) -> str:
    root = request.request_id or request.activation_id
    return f"{root}:{request.step_id}:attempt-{request.attempt}"


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
    "timeout", "rate_limit_exceeded", "too_many_requests",
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


def _usage(raw: dict[str, Any] | None, started: float) -> Usage:
    latency = int((time.monotonic() - started) * 1000)
    if raw is None:
        return Usage(latency_ms=latency, reported=False)
    cached = (raw.get("input_tokens_details") or {}).get("cached_tokens", 0)
    return Usage(
        input_tokens=max(0, raw["input_tokens"] - cached),
        output_tokens=raw["output_tokens"],
        total_tokens=raw["total_tokens"],
        cache_read_tokens=cached,
        latency_ms=latency,
        reported=True,
    )
