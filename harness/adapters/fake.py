"""Deterministic model responses; all tools are executed by the native engine."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..models import Usage, json_dumps
from ..tools import SUBMIT_KINDS
from .base import ModelResponse, Availability, ModelRequest, ProviderError

TurnFactory = Callable[[ModelRequest], "FakeTurn | dict[str, Any] | ModelResponse"]
TurnSpec = "FakeTurn | dict[str, Any] | ModelResponse | TurnFactory | BaseException"


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
        self.invocations: list[ModelRequest] = []
        self._aborted: set[str] = set()

    def availability(self) -> Availability:
        return Availability(True)

    def abort(self, session_id: str) -> None:
        self._aborted.add(session_id)

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.invocations.append(request)
        if request.abort_flag.is_set() or request.session_id in self._aborted:
            return ModelResponse(finish_reason="aborted", error="aborted", provider=self.name, model=self.model)
        if not self.script:
            raise ProviderError("fake adapter script exhausted")
        item = self.script.pop(0)
        if callable(item):
            item = item(request)
        if request.abort_flag.is_set() or request.session_id in self._aborted:
            return ModelResponse(finish_reason="aborted", error="aborted", provider=self.name, model=self.model)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, ModelResponse):
            return item
        if isinstance(item, dict):
            item = FakeTurn(proposal=item)
        if not isinstance(item, FakeTurn):
            raise ProviderError(f"unsupported fake turn: {type(item)!r}")
        if item.raise_error is not None:
            raise item.raise_error
        output: list[dict[str, Any]] = []
        if item.transcript:
            output.append({"id": f"message-{request.activation_id}-{request.step_id}", "type": "message", "role": "assistant",
                           "content": [{"type": "output_text", "text": item.transcript}]})
        usage = item.usage or Usage(reported=False)
        if usage.total_tokens == 0:
            usage.total_tokens = usage.input_tokens + usage.output_tokens + usage.cache_read_tokens + usage.cache_write_tokens
        def call(name: str, args: dict[str, Any]) -> None:
            identity = f"call-{request.activation_id}-{request.step_id}-{len(output) + 1}"
            output.append({"id": identity, "call_id": identity, "type": "function_call", "name": name,
                           "arguments": json_dumps(args)})

        for path, content in item.writes.items():
            call("write_file", {"path": path, "content": content})
        for name, spec in item.checks.items():
            payload = _fake_check_payload(name, spec)
            tool_name = "collect_evidence" if request.department == "quality" else "run_check"
            call(tool_name, payload)
        proposal = None if item.proposal is None else dict(item.proposal)
        if proposal:
            proposal.pop("_writes", None)
            proposal.pop("_checks", None)
            submit_name = _submit_tool_for(proposal.get("kind"))
            if submit_name:
                call(submit_name, {key: value for key, value in proposal.items() if key != "kind"})
            else:
                raise ProviderError(f"unsupported fake proposal kind: {proposal.get('kind')}")
        return ModelResponse(
            output=output,
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
