from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import aclosing

from ..providers import ProviderConnections, ProviderFacade
from ..providers.call import ModelCall, ModelResponse, ModelStreamEvent
from ..providers.errors import ProviderError as FacadeProviderError
from .base import Availability, ProviderError


class FacadeAdapter:
    # 内核侧薄桥接：把步骤驱动的模型调用交给独立 Provider 模块，Provider 的错误换成内核的 ProviderError。
    # 不保存调用目标与凭据。执行调用时按这次逻辑调用的身份向 Provider 取句柄
    name = "facade"
    model = "unconfigured"

    def __init__(self, facade: ProviderFacade, *, connections: ProviderConnections | None = None) -> None:
        self.facade = facade
        self.connections = connections
        self._cancelled: set[str] = set()

    def availability(self) -> Availability:
        # 解析发生在步骤驱动的每次逻辑调用之前。激活开始时桥接层不持有目标，不做可用性判断
        return Availability(True)

    def cancel(self, attempt_id: str) -> None:
        # 取消只作用于这次调用尝试。先记下再通知 Provider：尝试正在进行时 Provider 立即取消，还没有开始时开始时取消
        self._cancelled.add(attempt_id)
        self.facade.cancel(attempt_id)

    async def stream(self, call: ModelCall) -> AsyncIterator[ModelStreamEvent | ModelResponse]:
        try:
            async with aclosing(self.facade.stream_handle(
                call.logical_call_id, call, connections=self.connections, cancelled=self._cancelled,
            )) as items:
                async for item in items:
                    yield item
        except FacadeProviderError as exc:
            raise ProviderError(str(exc), reason=exc.reason,
                                retryable=exc.retryable,
                                diagnostics=dict(exc.diagnostics) if exc.diagnostics else None) from exc
