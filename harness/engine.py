"""Native model/tool loop for one department activation."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .adapters.base import ModelAdapter, ModelRequest, ModelResponse, ProviderError
from .models import json_dumps
from .tools import SUBMIT_KINDS, ToolResult, ToolRuntime

MAX_MODEL_STEPS = 32


@dataclass(frozen=True)
class DepartmentSubmission:
    proposal: dict[str, Any]
    response: ModelResponse


def run_department(
    adapter: ModelAdapter,
    runtime: ToolRuntime,
    *,
    prepare_step: Callable[[int], ModelRequest | None],
    record_response: Callable[[ModelResponse], None],
    record_tool: Callable[[dict[str, Any]], None],
    record_skipped_tool: Callable[[dict[str, Any]], None],
    begin_tool: Callable[[dict[str, Any]], bool],
    begin_request: Callable[[ModelRequest], bool],
    stopped: Callable[[], bool],
) -> DepartmentSubmission | None:
    for step_id in range(1, MAX_MODEL_STEPS + 1):
        if stopped():
            return None
        request = prepare_step(step_id)
        if request is None or not begin_request(request):
            return None
        response = adapter.complete(request)
        record_response(response)
        if stopped():
            return None
        if response.finish_reason != "completed":
            reason = {"aborted": "cancelled", "overflow": "context_overflow",
                      "unavailable": "provider_unavailable"}.get(response.finish_reason, "provider_error")
            raise ProviderError(response.error or f"model response {response.finish_reason}", reason=reason)
        call_ids = [item.get("call_id") for item in response.output if item.get("type") == "function_call"]
        if any(not isinstance(identity, str) or not identity for identity in call_ids):
            raise ProviderError("model tool call has no valid call_id")
        if len(call_ids) != len(set(call_ids)):
            raise ProviderError("model response contains duplicate tool call_id values")
        output_ids = [item["id"] for item in response.output if item.get("id")]
        if len(output_ids) != len(set(output_ids)):
            raise ProviderError("model response contains duplicate output item id values")
        for index, item in enumerate(response.output):
            if item.get("type") != "function_call":
                continue
            if stopped():
                return None
            identity = str(item.get("call_id") or "")
            name = str(item.get("name") or "")
            raw_args = item.get("arguments", "{}")
            try:
                args = json.loads(raw_args)
                if not isinstance(args, dict):
                    raise ValueError("tool arguments must be an object")
            except (TypeError, ValueError) as exc:
                args = {"invalid_arguments": raw_args}
                result = ToolResult(name, False, None, f"invalid tool arguments: {exc}")
            else:
                if not begin_tool({"id": identity, "name": name, "args": args, "step_id": step_id}):
                    return None
                result = runtime.execute(request.department, name, args)
            input_item = {"type": "function_call_output", "call_id": identity,
                          "output": json_dumps({"ok": result.ok, "output": result.output, "error": result.error})}
            call = {"id": identity, "name": name, "args": args, "ok": result.ok,
                    "output": result.output, "error": result.error, "step_id": step_id, "input_item": input_item}
            record_tool(call)
            if stopped():
                return None
            if name in SUBMIT_KINDS:
                for skipped in response.output[index + 1:]:
                    if skipped.get("type") != "function_call":
                        continue
                    error = "Not executed because the department already submitted its proposal."
                    record_skipped_tool({
                        "id": skipped["call_id"], "name": skipped["name"], "ok": False, "output": None,
                        "error": error, "step_id": step_id,
                        "input_item": {"type": "function_call_output", "call_id": skipped["call_id"],
                                       "output": json_dumps({"ok": False, "output": None, "error": error})},
                    })
                proposal = result.output if result.ok else {**args, "kind": SUBMIT_KINDS[name]}
                return DepartmentSubmission(proposal, response)
    raise ProviderError("department reached the model step limit without submitting a proposal", reason="model_steps_exhausted")
