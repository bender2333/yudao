from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import aclosing

from ..providers import FrozenTarget, ProviderConnections, ProviderFacade, check_target_availability
from ..providers.call import ModelCall, ModelResponse, ModelStreamEvent
from ..providers.errors import ProviderError as FacadeProviderError
from .base import Availability, ProviderError


class FacadeAdapter:
    # 内核侧薄桥接：把部门循环的模型调用交给独立 Provider 模块，Provider 的错误换成内核的 ProviderError。
    # 编排器每次激活创建一个，随激活结束释放
    name = "facade"

    def __init__(self, facade: ProviderFacade, target: FrozenTarget,
                 *, connections: ProviderConnections | None = None) -> None:
        self.facade = facade
        self.target = target
        self.connections = connections
        self.model = target.model or "unconfigured"
        # 本次激活内收到取消的调用尝试；取消到达时尝试还没有开始，Provider 在尝试开始时据此立即取消
        self._cancelled: set[str] = set()

    def availability(self) -> Availability:
        # 协议差异由 Provider 模块处理，桥接层不做 Responses 专属判断
        result = check_target_availability(self.target)
        if result["available"]:
            return Availability(True)
        return Availability(False, result["reason"], result["message"])

    def cancel(self, attempt_id: str) -> None:
        # 取消只作用于这次调用尝试。先记下再通知 Provider：尝试正在进行时 Provider 立即取消，还没有开始时开始时取消
        self._cancelled.add(attempt_id)
        self.facade.cancel(attempt_id)

    async def stream(self, call: ModelCall) -> AsyncIterator[ModelStreamEvent | ModelResponse]:
        availability = self.availability()
        if not availability.available:
            raise ProviderError(availability.message, reason=availability.reason)
        try:
            async with aclosing(self.facade.stream(self.target, call, connections=self.connections,
                                                   cancelled=self._cancelled)) as items:
                async for item in items:
                    yield item
        except FacadeProviderError as exc:
            raise ProviderError(str(exc), reason=exc.reason,
                                retryable=exc.retryable,
                                diagnostics=dict(exc.diagnostics) if exc.diagnostics else None) from exc
