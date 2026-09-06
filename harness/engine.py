"""Native model/tool loop for one department activation."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .adapters.base import ModelAdapter, ModelRequest, ModelResponse, ProviderError
from .models import json_dumps
from .tools import SUBMIT_KINDS, ToolResult, ToolRuntime

MAX_MODEL_STEPS = 32
MAX_PROVIDER_ATTEMPTS = 3
RETRY_BUDGET_SEC = 1805.0
RETRY_INITIAL_DELAY_SEC = 1.0
RETRY_MAX_DELAY_SEC = 60.0


@dataclass(frozen=True)
class DepartmentSubmission:
    proposal: dict[str, Any]
    response: ModelResponse


@dataclass(frozen=True)
class ToolAdmission:
    stopped: bool = False
    error: str | None = None


def run_department(
    adapter: ModelAdapter,
    runtime: ToolRuntime,
    *,
    prepare_step: Callable[[int, int, int, int | None], ModelRequest | None],
    record_response: Callable[[ModelResponse], None],
    record_tool: Callable[[dict[str, Any]], None],
    record_skipped_tool: Callable[[dict[str, Any]], None],
    begin_tool: Callable[[dict[str, Any]], ToolAdmission],
    begin_request: Callable[[ModelRequest], bool],
    finish_compaction: Callable[[ModelResponse], None],
    record_attempt_failed: Callable[[ModelRequest, ProviderError, bool], None],
    record_retry_scheduled: Callable[[ModelRequest, ProviderError, float, int], bool],
    stopped: Callable[[], bool],
) -> DepartmentSubmission | None:
    attempt = 1
    root_step_id = 1
    retry_of_step_id = None
    logical_request_started_at: float | None = None
    for step_id in range(1, MAX_MODEL_STEPS + 1):
        if stopped():
            return None
        if retry_of_step_id is None:
            logical_request_started_at = time.monotonic()
        request = prepare_step(step_id, attempt, root_step_id, retry_of_step_id)
        if request is None or not begin_request(request):
            return None
        try:
            response = adapter.complete(request)
            _validate_response(response)
        except ProviderError as exc:
            delay = _retry_delay(exc, attempt)
            elapsed = (time.monotonic() - logical_request_started_at
                       if logical_request_started_at is not None else 0.0)
            can_retry = (
                exc.retryable
                and attempt < MAX_PROVIDER_ATTEMPTS
                and step_id < MAX_MODEL_STEPS
                and elapsed + delay < RETRY_BUDGET_SEC
            )
            will_retry = can_retry and not stopped()
            record_attempt_failed(request, exc, will_retry)
            if stopped():
                return None
            if not will_retry:
                if exc.retryable and step_id >= MAX_MODEL_STEPS:
                    raise ProviderError(
                        "department reached the model step limit during provider retries",
                        reason="model_steps_exhausted",
                    ) from exc
                diagnostics = dict(exc.diagnostics or {})
                diagnostics.update(attempts=attempt, max_attempts=MAX_PROVIDER_ATTEMPTS)
                raise ProviderError(str(exc), reason=exc.reason, diagnostics=diagnostics) from exc
            if not record_retry_scheduled(request, exc, delay, step_id + 1):
                return None
            if not _wait_for_retry(delay, stopped):
                return None
            attempt += 1
            retry_of_step_id = step_id
            continue
        record_response(response)
        attempt = 1
        root_step_id = step_id + 1
        retry_of_step_id = None
        if stopped():
            _skip_calls(response.output, step_id, record_skipped_tool,
                        "Not executed because this activation ended or its input changed during the model request.")
            return None
        if request.purpose == "compaction":
            finish_compaction(response)
            continue
        for index, item in enumerate(response.output):
            if item.get("type") != "function_call":
                continue
            if stopped():
                _skip_calls(response.output[index:], step_id, record_skipped_tool,
                            "Not executed because this activation ended or its input changed before these tools started.")
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
                admission = begin_tool({"id": identity, "name": name, "args": args, "step_id": step_id})
                if admission.stopped:
                    _skip_calls(response.output[index:], step_id, record_skipped_tool,
                                "Not executed because the current activation can no longer start tools.")
                    return None
                result = (ToolResult(name, False, None, admission.error) if admission.error
                          else runtime.execute(request.department, name, args))
            input_item = {"type": "function_call_output", "call_id": identity,
                          "output": json_dumps({"ok": result.ok, "output": result.output, "error": result.error})}
            call = {"id": identity, "name": name, "args": args, "ok": result.ok,
                    "output": result.output, "error": result.error, "step_id": step_id, "input_item": input_item}
            record_tool(call)
            if stopped():
                _skip_calls(response.output[index + 1:], step_id, record_skipped_tool,
                            "Not executed because this activation ended or its input changed after the current tool.")
                return None
            if name in SUBMIT_KINDS:
                _skip_calls(response.output[index + 1:], step_id, record_skipped_tool,
                            "Not executed because the department already submitted its proposal.")
                proposal = result.output if result.ok else {**args, "kind": SUBMIT_KINDS[name]}
                return DepartmentSubmission(proposal, response)
    raise ProviderError("department reached the model step limit without submitting a proposal", reason="model_steps_exhausted")


def _retry_delay(error: ProviderError, attempt: int) -> float:
    retry_after = (error.diagnostics or {}).get("retry_after_sec")
    if isinstance(retry_after, (int, float)) and retry_after > 0:
        return min(float(retry_after), RETRY_MAX_DELAY_SEC)
    return min(RETRY_INITIAL_DELAY_SEC * (2 ** (attempt - 1)), RETRY_MAX_DELAY_SEC)


def _validate_response(response: ModelResponse) -> None:
    """Reject malformed provider responses before they can enter effective history."""
    if not isinstance(response, ModelResponse):
        raise ProviderError("model adapter returned an invalid response", diagnostics={"error_type": "protocol"})
    if response.finish_reason != "completed":
        reason = {"aborted": "cancelled", "overflow": "context_overflow",
                  "unavailable": "provider_unavailable"}.get(response.finish_reason, "provider_error")
        raise ProviderError(
            response.error or f"model response {response.finish_reason}",
            reason=reason,
            diagnostics={"error_type": "protocol", "finish_reason": response.finish_reason},
        )
    if not isinstance(response.output, list):
        raise ProviderError("model response output must be an array",
                            diagnostics={"error_type": "protocol"})
    output_ids: list[str] = []
    call_ids: list[str] = []
    for item in response.output:
        if not isinstance(item, dict):
            raise ProviderError("model response output item must be an object",
                                diagnostics={"error_type": "protocol"})
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            raise ProviderError("model output item has no identity",
                                diagnostics={"error_type": "protocol"})
        output_ids.append(item_id)
        item_type = item.get("type")
        if not isinstance(item_type, str) or not item_type:
            raise ProviderError("model output item has no type",
                                diagnostics={"error_type": "protocol"})
        if item_type != "function_call":
            continue
        call_id = item.get("call_id")
        name = item.get("name")
        if not isinstance(call_id, str) or not call_id:
            raise ProviderError("model tool call has no valid call_id",
                                diagnostics={"error_type": "protocol"})
        if not isinstance(name, str) or not name:
            raise ProviderError("model tool call has no valid name",
                                diagnostics={"error_type": "protocol"})
        arguments = item.get("arguments")
        if not isinstance(arguments, str):
            raise ProviderError("model tool call arguments must be a JSON object",
                                diagnostics={"error_type": "protocol"})
        try:
            parsed = json.loads(arguments)
        except (TypeError, ValueError) as exc:
            raise ProviderError("model tool call arguments must be valid JSON",
                                diagnostics={"error_type": "protocol"}) from exc
        if not isinstance(parsed, dict):
            raise ProviderError("model tool call arguments must be a JSON object",
                                diagnostics={"error_type": "protocol"})
        call_ids.append(call_id)
    if len(output_ids) != len(set(output_ids)):
        raise ProviderError("model response contains duplicate output item id values",
                            diagnostics={"error_type": "protocol"})
    if len(call_ids) != len(set(call_ids)):
        raise ProviderError("model response contains duplicate tool call_id values",
                            diagnostics={"error_type": "protocol"})


def _wait_for_retry(delay: float, stopped: Callable[[], bool]) -> bool:
    deadline = time.monotonic() + delay
    while True:
        if stopped():
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        time.sleep(min(0.02, remaining))


def _skip_calls(output: list[dict[str, Any]], step_id: int, record: Callable[[dict[str, Any]], None], error: str) -> None:
    for item in output:
        if item.get("type") != "function_call":
            continue
        record({"id": item["call_id"], "name": item["name"], "ok": False, "output": None,
                "error": error, "step_id": step_id,
                "input_item": {"type": "function_call_output", "call_id": item["call_id"],
                               "output": json_dumps({"ok": False, "output": None, "error": error})}})
