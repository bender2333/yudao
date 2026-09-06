"""Single model-call contract. Adapters cannot execute tools or advance departments."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
from typing import Any, Callable, Protocol

from ..context import AssembledContext
from ..models import Usage


class ProviderError(Exception):
    def __init__(
        self,
        message: str,
        *,
        reason: str = "provider_error",
        retryable: bool = False,
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.retryable = retryable
        self.diagnostics = diagnostics


@dataclass(frozen=True)
class Availability:
    available: bool
    reason: str = ""
    message: str = ""


@dataclass
class ModelObservation:
    id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    usage: Usage | None = None
    provider: str | None = None
    model: str | None = None
    source: str = "provider_sdk"
    sequence: int | None = None


@dataclass
class ModelRequest:
    run_id: str
    department: str
    session_id: str
    activation_id: str
    step_id: int
    context: AssembledContext
    tools: list[dict[str, Any]]
    abort_flag: Event
    on_observation: Callable[[ModelObservation], None] | None = None
    on_raw_observation: Callable[[ModelObservation], None] | None = None
    purpose: str = "work"
    max_output_tokens: int | None = None
    effective_contract_hash: str | None = None
    engineering_plan_hash: str | None = None
    request_id: str | None = None
    input_version: int = 0
    guidance_version: int = 0
    guidance_ids: list[str] = field(default_factory=list)
    guidance_only: bool = False
    prompt_version: int = 0
    prompt_hash: str | None = None
    attempt: int = 1
    root_step_id: int | None = None
    retry_of_step_id: int | None = None
    attempt_id: str | None = None
    logical_call_id: str | None = None
    context_event_id: str | None = None
    attempt_started_at: str | None = None
    attempt_started_monotonic: float | None = None
    attempt_finished_monotonic: float | None = None

    @property
    def input_items(self) -> list[dict[str, Any]]:
        return self.context.input_items

    def observe(self, observation: ModelObservation) -> None:
        if self.on_observation is not None:
            self.on_observation(observation)

    def observe_raw(self, observation: ModelObservation) -> None:
        if self.on_raw_observation is not None:
            self.on_raw_observation(observation)


@dataclass
class ModelResponse:
    output: list[dict[str, Any]] = field(default_factory=list)
    usage: Usage = field(default_factory=lambda: Usage(reported=False))
    finish_reason: str = "completed"
    error: str | None = None
    provider: str = "fake"
    model: str = "fake-script"
    response_id: str | None = None
    sdk_response: dict[str, Any] | None = None


class ModelAdapter(Protocol):
    name: str
    model: str

    def availability(self) -> Availability: ...

    def complete(self, request: ModelRequest) -> ModelResponse: ...

    def abort(self, session_id: str) -> None: ...
