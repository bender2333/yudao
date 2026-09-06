"""A single stateless Responses request; department and tool execution live above it."""

from __future__ import annotations

import asyncio
import json
import math
import os
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any
from urllib.parse import urlsplit

from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, AsyncOpenAI

from ..models import Usage
from .base import Availability, ModelObservation, ModelRequest, ModelResponse, ProviderError


@dataclass(frozen=True)
class ResponsesConfig:
    model: str = ""
    api_key: str = field(default="", repr=False)
    provider: str = "openai"
    base_url: str = "https://api.openai.com/v1"
    timeout_sec: float = 600.0

    @classmethod
    def from_env(cls) -> ResponsesConfig:
        try:
            timeout = float(os.environ.get("YUDAO_MODEL_TIMEOUT_SEC", "600"))
        except ValueError:
            timeout = 0.0
        return cls(
            model=os.environ.get("YUDAO_MODEL_NAME", "").strip(),
            api_key=os.environ.get("YUDAO_MODEL_API_KEY", "").strip(),
            provider=os.environ.get("YUDAO_MODEL_PROVIDER", "openai").strip(),
            base_url=os.environ.get("YUDAO_MODEL_BASE_URL", "https://api.openai.com/v1").strip(),
            timeout_sec=timeout,
        )


class ResponsesAdapter:
    name = "responses"

    def __init__(self, config: ResponsesConfig | None = None) -> None:
        self.config = config if config is not None else ResponsesConfig.from_env()
        self.model = self.config.model or "unconfigured"
        self._lock = Lock()
        self._active: tuple[str, asyncio.AbstractEventLoop, asyncio.Task] | None = None

    def availability(self) -> Availability:
        missing = []
        if not self.config.api_key:
            missing.append("YUDAO_MODEL_API_KEY")
        if not self.config.model:
            missing.append("YUDAO_MODEL_NAME")
        if missing:
            return Availability(False, "provider_unavailable", "Missing configuration: " + ", ".join(missing))
        try:
            url = urlsplit(self.config.base_url)
            valid_url = url.scheme in {"https", "http"} and bool(url.hostname) and not url.username and not url.password
        except ValueError:
            valid_url = False
        if not valid_url:
            return Availability(False, "provider_unavailable", "Invalid YUDAO_MODEL_BASE_URL")
        if not math.isfinite(self.config.timeout_sec) or self.config.timeout_sec <= 0:
            return Availability(False, "provider_unavailable", "YUDAO_MODEL_TIMEOUT_SEC must be positive and finite")
        if not self.config.provider:
            return Availability(False, "provider_unavailable", "YUDAO_MODEL_PROVIDER must not be empty")
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
            raise ProviderError("Model request timed out") from exc
        except APIStatusError as exc:
            code = _error_code(exc.body)
            reason = "context_overflow" if code == "context_length_exceeded" else "provider_error"
            # Provider error bodies may echo input or credentials; retain only status.
            raise ProviderError(f"Model provider returned HTTP {exc.status_code}", reason=reason) from exc
        except APIConnectionError as exc:
            raise ProviderError("Model provider connection failed") from exc
        except APIError as exc:
            reason = "context_overflow" if _error_code(exc.body) == "context_length_exceeded" else "provider_error"
            raise ProviderError("Model provider returned an invalid API response", reason=reason) from exc
        except json.JSONDecodeError as exc:
            raise ProviderError("Model provider returned malformed stream JSON") from exc

    async def _complete(self, request: ModelRequest) -> ModelResponse:
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._active is not None:
                raise ProviderError("Responses adapter already has an active model request")
            task = asyncio.create_task(self._stream(request))
            self._active = (request.session_id, loop, task)
        watcher = asyncio.create_task(self._watch_abort(request, task))
        try:
            async with asyncio.timeout(self.config.timeout_sec):
                return await task
        except asyncio.CancelledError as exc:
            raise ProviderError("Model request cancelled", reason="cancelled") from exc
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

    async def _stream(self, request: ModelRequest) -> ModelResponse:
        started = time.monotonic()
        seen_items: set[str] = set()
        async with AsyncOpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.timeout_sec,
            max_retries=0,
        ) as client:
            output_limit = {} if request.max_output_tokens is None else {"max_output_tokens": request.max_output_tokens}
            stream = await client.responses.create(
                model=self.config.model,
                input=request.input_items,
                tools=request.tools,
                store=False,
                stream=True,
                **output_limit,
            )
            async with stream:
                async for event in stream:
                    if request.abort_flag.is_set():
                        raise ProviderError("Model request cancelled", reason="cancelled")
                    if event.type == "response.output_item.done":
                        self._observe_item(request, event.item.model_dump(mode="json", exclude_unset=True), seen_items)
                    elif event.type in {"response.completed", "response.incomplete", "response.failed"}:
                        response = event.response
                        output = [item.model_dump(mode="json", exclude_unset=True) for item in (response.output or [])]
                        for item in output:
                            self._observe_item(request, item, seen_items)
                        raw_usage = response.usage.model_dump(mode="json", exclude_unset=True) if response.usage else None
                        usage = _usage(raw_usage, started)
                        request.observe(ModelObservation(
                            id=response.id, kind="usage",
                            payload={"response_id": response.id, "usage": raw_usage},
                            usage=usage, provider=self.config.provider, model=response.model,
                        ))
                        if event.type != "response.completed" or response.status != "completed":
                            code = getattr(response.error, "code", None) if response.error else None
                            reason = "context_overflow" if code == "context_length_exceeded" else "provider_error"
                            detail = "incomplete" if event.type == "response.incomplete" else "failed"
                            raise ProviderError(f"Model response {detail}", reason=reason)
                        if response.output is None:
                            raise ProviderError("Completed model response has no output array")
                        return ModelResponse(
                            output=output, usage=usage, provider=self.config.provider,
                            model=response.model, response_id=response.id,
                        )
                    elif event.type == "error":
                        reason = "context_overflow" if event.code == "context_length_exceeded" else "provider_error"
                        raise ProviderError("Model provider reported a stream error", reason=reason)
        raise ProviderError("Model response stream ended before a terminal response")

    def _observe_item(self, request: ModelRequest, item: dict[str, Any], seen: set[str]) -> None:
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
            provider=self.config.provider, model=self.model,
        ))


def _error_code(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None
    error = body.get("error", body)
    return error.get("code") if isinstance(error, dict) else None


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
