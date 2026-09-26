from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..context import AssembledContext
from ..models import Usage
from ..providers.call import ModelCall, ModelResponse, ModelStreamEvent


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
    # 编排器记录的一条观察：模型调用交回的流式输出，或者工具执行与跳过的结果
    id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    usage: Usage | None = None
    provider: str | None = None
    model: str | None = None
    source: str = "provider_sdk"
    sequence: int | None = None

    @classmethod
    def from_stream(cls, event: ModelStreamEvent) -> ModelObservation:
        usage = None if event.usage is None else Usage(**event.usage.model_dump())
        return cls(event.id, event.kind, dict(event.payload), event.text, usage, event.provider,
                   event.model, event.source, event.sequence)


@dataclass
class ModelRequest:
    # 编排器为一步准备的请求：装配结果与身份；交给模型接入的只是由它生成的模型调用合同
    run_id: str
    department: str
    session_id: str
    activation_id: str
    step_id: int
    context: AssembledContext
    tools: list[dict[str, Any]]
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

    def model_call(self) -> ModelCall:
        return ModelCall(
            run_id=self.run_id, department=self.department, session_id=self.session_id,
            activation_id=self.activation_id, step_id=self.step_id,
            logical_call_id=self.logical_call_id, attempt=self.attempt, attempt_id=self.attempt_id,
            purpose=self.purpose, input_items=self.input_items, tools=self.tools,
            max_output_tokens=self.max_output_tokens,
        )


class ModelAdapter(Protocol):
    # 部门循环看到的模型接入：一次调用尝试逐条交回流式输出，最后交回 ModelResponse；取消按调用尝试的身份生效
    name: str
    model: str

    def availability(self) -> Availability: ...

    def stream(self, call: ModelCall) -> AsyncIterator[ModelStreamEvent | ModelResponse]: ...

    def cancel(self, attempt_id: str) -> None: ...
