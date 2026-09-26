from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import aclosing

from ..providers import FrozenTarget, ProviderConnections, ProviderFacade, check_target_availability
from ..providers.call import ModelCall, ModelResponse, ModelStreamEvent
from ..providers.errors import ProviderError as FacadeProviderError
from .base import Availability, ProviderError


class FacadeAdapter:
    # 内核侧薄桥接：把部门循环的模型调用交给独立 Provider 模块，Provider 的错误换成内核的 ProviderError
    name = "facade"

    def __init__(self, facade: ProviderFacade, target: FrozenTarget,
                 *, connections: ProviderConnections | None = None) -> None:
        self.facade = facade
        self.target = target
        self.connections = connections
        self.model = target.model or "unconfigured"

    def availability(self) -> Availability:
        # 协议差异由 Provider 模块处理，桥接层不做 Responses 专属判断
        result = check_target_availability(self.target)
        if result["available"]:
            return Availability(True)
        return Availability(False, result["reason"], result["message"])

    def cancel(self, attempt_id: str) -> None:
        # 取消只作用于这次调用尝试
        self.facade.cancel(attempt_id)

    async def stream(self, call: ModelCall) -> AsyncIterator[ModelStreamEvent | ModelResponse]:
        availability = self.availability()
        if not availability.available:
            raise ProviderError(availability.message, reason=availability.reason)
        try:
            async with aclosing(self.facade.stream(self.target, call, connections=self.connections)) as items:
                async for item in items:
                    yield item
        except FacadeProviderError as exc:
            raise ProviderError(str(exc), reason=exc.reason,
                                retryable=exc.retryable,
                                diagnostics=dict(exc.diagnostics) if exc.diagnostics else None) from exc
