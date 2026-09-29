from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..context import AssembledContext
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
class ModelRequest:
    # 步骤驱动为一步准备的请求：装配结果与身份；交给模型接入的只是由它生成的模型调用合同
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
    # 这次调用所属的项目与事项：取自准备请求时的运行状态，供输出片段的范围使用（设计说明第 5.6 节）
    project_id: str | None = None
    work_item_id: str | None = None
    # 这次逻辑调用解析出的调用目标（公开部分，不含密钥）：只进入记录，适配器不读它
    call_target: dict[str, Any] | None = None
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
    # 步骤驱动看到的模型接入：一次调用尝试逐条交回流式输出，最后交回 ModelResponse；取消按调用尝试的身份生效
    name: str
    model: str

    def availability(self) -> Availability: ...

    def stream(self, call: ModelCall) -> AsyncIterator[ModelStreamEvent | ModelResponse]: ...

    def cancel(self, attempt_id: str) -> None: ...
