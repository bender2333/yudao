from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


# 不可变校验问题，只携带定位与说明，不携带凭据内容
@dataclass(frozen=True)
class ValidationIssue:
    location: str
    message: str


class CatalogValidationError(ValueError):
    # 目录结构非法或选择逐项解析失败时抛出，逐项携带定位
    def __init__(self, issues: Iterable[ValidationIssue]) -> None:
        self.issues = tuple(issues)
        if not self.issues:
            self.issues = (ValidationIssue("catalog", "Provider 目录无效"),)
        super().__init__("；".join(f"{issue.location}: {issue.message}" for issue in self.issues))


class ProviderError(Exception):
    # 单次调用失败的统一形状，reason 供调用方分类，不做重试决策
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
        self.diagnostics = dict(diagnostics) if diagnostics is not None else None


class CancelledError(ProviderError):
    # 调用尝试被取消，只作用于本次 attempt_id
    def __init__(self, message: str = "Model request cancelled") -> None:
        super().__init__(message, reason="cancelled", retryable=False)


class UnsupportedProtocolError(ProviderError):
    # 请求前拒绝不支持的协议，不发送网络请求
    def __init__(self, protocol: str) -> None:
        super().__init__(
            f"unsupported provider protocol: {protocol}",
            reason="unsupported_protocol",
            retryable=False,
            diagnostics={"protocol": protocol},
        )


class RequestNotPersistedError(ProviderError):
    # 请求证据未经观察方持久化确认时拒绝发送
    def __init__(self, message: str = "Model request evidence was not persisted") -> None:
        super().__init__(message, reason="request_not_persisted", retryable=False)
