"""确定性 fake adapter，走与 OMP 相同的 invoke 接口。"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..models import Usage, estimate_tokens
from ..tools import SUBMIT_KINDS, ToolRuntime
from .base import AdapterResult, Availability, InvokeRequest, ProviderError

TurnFactory = Callable[[InvokeRequest], "FakeTurn | dict[str, Any] | AdapterResult"]
TurnSpec = "FakeTurn | dict[str, Any] | AdapterResult | TurnFactory | BaseException"


@dataclass
class FakeTurn:
    proposal: dict[str, Any] | None = None
    writes: dict[str, str] = field(default_factory=dict)
    checks: dict[str, int | dict[str, Any]] = field(default_factory=dict)
    transcript: str = ""
    usage: Usage | None = None
    finish_reason: str = "completed"
    error: str | None = None
    raise_error: ProviderError | None = None


class FakeAdapter:
    name = "fake"
    model = "fake-script"

    def __init__(self, script: Sequence[TurnSpec] | None = None) -> None:
        self.script = list(script or [])
        self.invocations: list[InvokeRequest] = []
        self._aborted: set[str] = set()

    def availability(self) -> Availability:
        return Availability(True)

    def abort(self, session_id: str) -> None:
        self._aborted.add(session_id)

    def invoke(self, request: InvokeRequest) -> AdapterResult:
        self.invocations.append(request)
        if request.abort_flag.is_set() or request.session_id in self._aborted:
            return AdapterResult(None, finish_reason="aborted", error="aborted", provider=self.name, model=self.model)
        if not self.script:
            raise ProviderError("fake adapter script exhausted")
        item = self.script.pop(0)
        if callable(item):
            item = item(request)
        if request.abort_flag.is_set() or request.session_id in self._aborted:
            return AdapterResult(None, finish_reason="aborted", error="aborted", provider=self.name, model=self.model)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, AdapterResult):
            return item
        if isinstance(item, dict):
            item = FakeTurn(proposal=item)
        if not isinstance(item, FakeTurn):
            raise ProviderError(f"unsupported fake turn: {type(item)!r}")
        if item.raise_error is not None:
            raise item.raise_error
        runtime = ToolRuntime(request.workspace)
        tool_calls: list[dict[str, Any]] = []
        for path, content in item.writes.items():
            result = runtime.execute(request.department, "write_file", {"path": path, "content": content})
            tool_calls.append({"name": "write_file", "ok": result.ok, "error": result.error, "args": {"path": path}})
            if not result.ok:
                raise ProviderError(result.error or "write_file failed")
        for name, spec in item.checks.items():
            payload = _fake_check_payload(name, spec)
            tool_name = "collect_evidence" if request.department == "quality" else "run_check"
            result = runtime.execute(request.department, tool_name, payload)
            tool_calls.append(
                {
                    "name": tool_name,
                    "ok": result.ok,
                    "error": result.error,
                    "args": {"name": name, "source": "fake_script_process"},
                    "output": result.output,
                }
            )
            if not result.ok:
                raise ProviderError(result.error or f"{tool_name} failed")
        usage = item.usage or Usage(
            input_tokens=estimate_tokens(request.context.prompt_text),
            output_tokens=estimate_tokens(item.transcript or "") + 32,
            total_tokens=0,
            latency_ms=1,
        )
        if usage.total_tokens == 0:
            usage.total_tokens = usage.input_tokens + usage.output_tokens
        proposal = None if item.proposal is None else dict(item.proposal)
        if proposal:
            proposal.pop("_writes", None)
            proposal.pop("_checks", None)
            submit_name = _submit_tool_for(proposal.get("kind"))
            if submit_name:
                submitted = runtime.execute(request.department, submit_name, {key: value for key, value in proposal.items() if key != "kind"})
                tool_calls.append({"name": submit_name, "ok": submitted.ok, "error": submitted.error, "args": {"kind": proposal.get("kind")}})
                if submitted.ok and isinstance(submitted.output, dict):
                    proposal = submitted.output
        return AdapterResult(
            proposal=proposal,
            transcript=item.transcript,
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=item.finish_reason,
            error=item.error,
            provider=self.name,
            model=self.model,
        )


def _fake_check_payload(name: str, spec: int | dict[str, Any]) -> dict[str, Any]:
    """Fake 只选择要跑的进程；exit_code 仍由主机执行产生。"""
    if isinstance(spec, dict) and (spec.get("argv") or spec.get("command")):
        payload = dict(spec)
        payload["name"] = name
        payload.pop("exit_code", None)
        payload["source"] = "fake_script_process"
        return payload
    code = int(spec if not isinstance(spec, dict) else spec.get("exit_code", 0))
    return {
        "name": name,
        "argv": [sys.executable, "-c", f"raise SystemExit({code})"],
        "source": "fake_script_process",
    }


def _submit_tool_for(kind: Any) -> str | None:
    for tool_name, mapped in SUBMIT_KINDS.items():
        if mapped == kind:
            return tool_name
    return None
