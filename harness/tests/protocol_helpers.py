from __future__ import annotations

import math
from typing import Any

from harness.adapters.base import Availability, ModelAdapter, ModelRequest, ModelResponse, ProviderError
from harness.adapters.facade_adapter import FacadeAdapter
from harness.providers import (
    CredentialChain,
    ProviderFacade,
    ResponsesConfig,
    ResponsesExecutionScope,
    check_availability,
)


# 测试装配：协议实现只有 harness/providers/responses.py 一份，这里只把测试需要的
# 适配器调用形状接到独立 Provider 模块，不复制任何请求或错误分类逻辑。
class ResponsesAdapter:
    name = "responses"

    def __init__(self, config: ResponsesConfig, *,
                 execution_scope: ResponsesExecutionScope | None = None) -> None:
        self.config = config
        self.model = config.model or "unconfigured"
        self.execution_scope = execution_scope
        self._delegate = _build_delegate(config, execution_scope)

    def availability(self) -> Availability:
        result = check_availability(self.config)
        if not result["available"]:
            return Availability(False, result["reason"], result["message"])
        return Availability(True)

    def abort(self, session_id: str) -> None:
        if self._delegate is not None:
            self._delegate.abort(session_id)

    def complete(self, request: ModelRequest) -> ModelResponse:
        availability = self.availability()
        if not availability.available:
            raise ProviderError(availability.message, reason=availability.reason)
        if self._delegate is None:
            raise ProviderError("Provider target is not resolvable", reason="provider_unavailable")
        return self._delegate.complete(request)


def _build_delegate(config: ResponsesConfig,
                    execution_scope: ResponsesExecutionScope | None) -> ModelAdapter | None:
    # 配置本身不可用时返回空实现，由 availability()/complete() 报同样的错误，
    # 与旧适配器“构造不校验、可用性检查才报错”的行为一致
    if not config.api_key or not config.model or not config.base_url:
        return None
    timeout = config.timeout_sec
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
        return None
    if not math.isfinite(float(timeout)) or float(timeout) <= 0:
        return None
    overrides: dict[str, Any] = {}
    if config.api_key:
        overrides["TEST_CREDENTIAL"] = config.api_key
    facade = ProviderFacade(credentials=CredentialChain(overrides=overrides, use_env=False))
    facade.store_document({
        "providers": [{
            "id": config.provider or "test-provider", "name": config.provider or "test-provider",
            "base_url": config.base_url, "credential_ref": "TEST_CREDENTIAL",
            "timeout_sec": float(config.timeout_sec),
        }],
        "models": [{
            "id": "test-model", "provider_id": config.provider or "test-provider",
            "model": config.model, "protocol": "responses",
            "context_window": 128000, "max_output_tokens": 4096,
        }],
        "bindings": {},
    })
    snapshot = facade.resolve_snapshot([{
        "key": "test", "provider_id": config.provider or "test-provider", "model_id": "test-model",
    }])
    return FacadeAdapter(facade, snapshot.target("test"), execution_scope=execution_scope)


__all__ = ["ResponsesAdapter"]
