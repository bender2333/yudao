"""Adapter 协议。控制层只接受结构化提案；adapter 不能改任务状态。"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
from typing import Any, Protocol

from ..context import AssembledContext
from ..models import Usage
from ..workspace import Workspace


class ProviderError(Exception):
    def __init__(
        self,
        message: str,
        *,
        reason: str = "provider_error",
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.diagnostics = diagnostics


@dataclass(frozen=True)
class Availability:
    available: bool
    reason: str = ""
    message: str = ""


@dataclass
class InvokeRequest:
    run_id: str
    department: str
    session_id: str
    activation_id: str
    context: AssembledContext
    tools: list[str]
    workspace: Workspace
    abort_flag: Event


@dataclass
class AdapterResult:
    proposal: dict[str, Any] | None
    transcript: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    finish_reason: str = "completed"
    error: str | None = None
    provider: str = "fake"
    model: str = "fake-script"
    diagnostics: dict[str, Any] | None = None


class DepartmentAdapter(Protocol):
    name: str
    model: str

    def availability(self) -> Availability: ...

    def invoke(self, request: InvokeRequest) -> AdapterResult: ...

    def abort(self, session_id: str) -> None: ...
