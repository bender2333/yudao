"""Native model/tool loop for one department activation."""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from .adapters.base import ModelAdapter, ModelRequest, ProviderError
from .adjudication import ToolPermission
from .models import json_dumps
from .providers import ProviderConnections
from .providers.call import ModelCall, ModelResponse, ModelStreamEvent
from .tools import SUBMIT_KINDS, ToolResult, ToolRuntime

# 连续没有调用工具的回复最多追加这么多次说明，再出现一次就结束激活（次数取自 OMP）
TOOL_CALL_REQUIRED_LIMIT = 3

_Result = TypeVar("_Result")


class ModelCallLoop:
    # 部门循环自己的事件循环：一次运行期间的模型调用都在这里执行，同一个事件循环内复用提供方的连接
    def __init__(self) -> None:
        self._runner = asyncio.Runner()
        self.connections = ProviderConnections()

    def __enter__(self) -> ModelCallLoop:
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self.close()

    def run(self, awaitable: Awaitable[_Result]) -> _Result:
        return self._runner.run(awaitable)

    def close(self) -> None:
        try:
            self._runner.run(self.connections.aclose())
        finally:
            self._runner.close()


class SafeNode(Protocol):
    # 流程编排提供的安全节点接口：部门循环在每个安全节点调用它，流程编排在这里分派新输入，回答继续还是停止
    def proceed(self) -> bool: ...


@dataclass(frozen=True)
class StepLimits:
    # 部门循环的重试与步数参数；默认值是正式运行使用的值
    retry_initial_delay_sec: float = 1.0
    retry_max_delay_sec: float = 60.0
    max_provider_attempts: int = 3
    max_model_steps: int = 999_999


def tool_call_required_text(count: int) -> str:
    return (
        f"上一次回复没有调用工具（连续第 {count} 次，最多 {TOOL_CALL_REQUIRED_LIMIT} 次）。"
        "只回复文字不会推进工作，也不会结束本次激活。"
        "工作没有完成时，调用下一个需要的工具；工作已经完成时，用本部门的提交工具提交提案。"
        f"连续第 {TOOL_CALL_REQUIRED_LIMIT + 1} 次仍然没有调用工具时，运行暂停，等待用户处理。"
    )


@dataclass(frozen=True)
class DepartmentSubmission:
    proposal: dict[str, Any]
    response: ModelResponse


def run_department(
    adapter: ModelAdapter,
    runtime: ToolRuntime,
    *,
    limits: StepLimits,
    model_loop: ModelCallLoop,
    prepare_step: Callable[[int, int, int, int | None], ModelRequest | None],
    record_stream: Callable[[ModelStreamEvent], None],
    record_response: Callable[[ModelResponse], None],
    record_tool: Callable[[dict[str, Any]], None],
    record_skipped_tool: Callable[[dict[str, Any]], None],
    begin_tool: Callable[[dict[str, Any]], ToolPermission],
    begin_request: Callable[[ModelRequest], bool],
    finish_compaction: Callable[[ModelResponse], None],
    record_attempt_finished: Callable[[ModelRequest, ModelResponse], None],
    record_attempt_failed: Callable[[ModelRequest, ProviderError, bool], None],
    record_retry_scheduled: Callable[[ModelRequest, ProviderError, float, int], bool],
    require_tool_call: Callable[[ModelRequest, dict[str, Any], int], None],
    nodes: SafeNode,
) -> DepartmentSubmission | None:
    attempt = 1
    root_step_id = 1
    retry_of_step_id = None
    replies_without_tool_call = 0
    for step_id in range(1, limits.max_model_steps + 1):
        if not nodes.proceed():
            return None
        request = prepare_step(step_id, attempt, root_step_id, retry_of_step_id)
        if request is None or not begin_request(request):
            return None
        request.attempt_started_monotonic = time.monotonic()
        try:
            response = model_loop.run(_call_model(adapter, request.model_call(), record_stream))
            _validate_response(response)
            request.attempt_finished_monotonic = time.monotonic()
            undeclared = _undeclared_tool_calls(request, response)
            if undeclared:
                # Provider-side corruption: tool calls arrived although the request declared no
                # tools. Keep the output as audit evidence (failed steps never enter effective
                # history) and treat the attempt as a retryable failure; nothing executes.
                record_response(response)
                raise ProviderError(
                    "model returned tool calls although the request declared no tools",
                    reason="compaction_failed" if request.purpose == "compaction" else "provider_error",
                    retryable=True,
                    diagnostics={"error_type": "undeclared_tool_call", "tool_names": undeclared},
                )
        except Exception as exc:
            if not isinstance(exc, ProviderError):
                exc = ProviderError(
                    f"model adapter failed: {type(exc).__name__}",
                    reason="provider_error",
                    retryable=False,
                    diagnostics={"error_type": "adapter_failure"},
                )
            retry_error = _retry_after_error(exc, limits)
            delay = _retry_delay(retry_error, attempt, limits)
            can_retry = (
                retry_error.retryable
                and attempt < limits.max_provider_attempts
                and step_id < limits.max_model_steps
            )
            will_retry = can_retry and nodes.proceed()
            record_attempt_failed(request, retry_error, will_retry)
            if not nodes.proceed():
                return None
            if not will_retry:
                if retry_error.retryable and step_id >= limits.max_model_steps:
                    raise ProviderError(
                        "department reached the model step limit during provider retries",
                        reason="model_steps_exhausted",
                    ) from retry_error
                diagnostics = dict(retry_error.diagnostics or {})
                diagnostics.update(attempts=attempt, max_attempts=limits.max_provider_attempts)
                raise ProviderError(str(retry_error), reason=retry_error.reason, diagnostics=diagnostics) from retry_error
            if not record_retry_scheduled(request, retry_error, delay, step_id + 1):
                return None
            if not _wait_for_retry(delay, nodes):
                return None
            attempt += 1
            retry_of_step_id = step_id
            continue
        try:
            # 截断流产生的无效参数不得进入有效历史，否则下次回放即被上游拒绝；
            # 工具循环仍用原始输出，保证具体参数错误回传模型且不启动工具
            record_response(_sanitized_response(response))
        except Exception as exc:
            host_error = ProviderError(
                f"model observation persistence failed: {type(exc).__name__}",
                reason="provider_error",
                retryable=False,
                diagnostics={"error_type": "observation_persistence"},
            )
            record_attempt_failed(request, host_error, False)
            raise host_error from exc
        record_attempt_finished(request, response)
        attempt = 1
        root_step_id = step_id + 1
        retry_of_step_id = None
        if not nodes.proceed():
            _skip_calls(response.output, step_id, record_skipped_tool,
                        "Not executed because this activation ended or its input changed during the model request.")
            return None
        if request.purpose == "compaction":
            finish_compaction(response)
            continue
        if not any(item.get("type") == "function_call" for item in response.output):
            # 回复已记入历史；追加一条 user 消息，下一次请求不以助手消息结尾
            replies_without_tool_call += 1
            if replies_without_tool_call > TOOL_CALL_REQUIRED_LIMIT:
                raise ProviderError(
                    f"department replied {replies_without_tool_call} times in a row without calling a tool",
                    reason="no_tool_call",
                )
            require_tool_call(
                request,
                {"role": "user", "content": tool_call_required_text(replies_without_tool_call)},
                replies_without_tool_call,
            )
            continue
        replies_without_tool_call = 0
        for index, item in enumerate(response.output):
            if item.get("type") != "function_call":
                continue
            if not nodes.proceed():
                _skip_calls(response.output[index:], step_id, record_skipped_tool,
                            "Not executed because this activation ended or its input changed before these tools started.")
                return None
            identity = str(item.get("call_id") or "")
            name = str(item.get("name") or "")
            raw_args = item.get("arguments")
            try:
                args = json.loads(raw_args)
                if not isinstance(args, dict):
                    raise ValueError("tool arguments must be an object")
            except (TypeError, ValueError) as exc:
                args = {"invalid_arguments": raw_args}
                result = ToolResult(name, False, None, f"invalid tool arguments: {exc}")
            else:
                permission = begin_tool({"id": identity, "name": name, "args": args, "step_id": step_id})
                if permission.stopped:
                    _skip_calls(response.output[index:], step_id, record_skipped_tool,
                                "Not executed because the current activation can no longer start tools.")
                    return None
                result = (runtime.execute(request.department, name, args) if permission.allowed
                          else ToolResult(name, False, None, permission.reason))
            input_item = {"type": "function_call_output", "call_id": identity,
                          "output": json_dumps({"ok": result.ok, "output": result.output, "error": result.error})}
            call = {"id": identity, "name": name, "args": args, "ok": result.ok,
                    "output": result.output, "error": result.error, "step_id": step_id, "input_item": input_item}
            record_tool(call)
            if not nodes.proceed():
                _skip_calls(response.output[index + 1:], step_id, record_skipped_tool,
                            "Not executed because this activation ended or its input changed after the current tool.")
                return None
            if name in SUBMIT_KINDS:
                _skip_calls(response.output[index + 1:], step_id, record_skipped_tool,
                            "Not executed because the department already submitted its proposal.")
                proposal = result.output if result.ok else {**args, "kind": SUBMIT_KINDS[name]}
                return DepartmentSubmission(proposal, response)
    raise ProviderError("department reached the model step limit without submitting a proposal", reason="model_steps_exhausted")


async def _call_model(adapter: ModelAdapter, call: ModelCall,
                      record_stream: Callable[[ModelStreamEvent], None]) -> ModelResponse:
    # 流式输出逐条记录以后再取下一条，最后一条是这次调用尝试的结果
    async with aclosing(adapter.stream(call)) as items:
        async for item in items:
            if isinstance(item, ModelResponse):
                return item
            record_stream(item)
    raise ProviderError("model call ended without a response", diagnostics={"error_type": "protocol"})


def _retry_delay(error: ProviderError, attempt: int, limits: StepLimits) -> float:
    retry_after = _retry_after_seconds(error)
    if retry_after is not None:
        return retry_after
    return min(limits.retry_initial_delay_sec * (2 ** (attempt - 1)), limits.retry_max_delay_sec)


def _retry_after_seconds(error: ProviderError) -> float | None:
    value = (error.diagnostics or {}).get("retry_after_sec")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if value > 0 and math.isfinite(value) else None


def _retry_after_error(error: ProviderError, limits: StepLimits) -> ProviderError:
    retry_after = _retry_after_seconds(error)
    limit = limits.retry_max_delay_sec
    if not error.retryable or retry_after is None or retry_after <= limit:
        return error
    diagnostics = dict(error.diagnostics or {})
    diagnostics["retry_after_sec"] = retry_after
    diagnostics["retry_after_limit_sec"] = limit
    diagnostics["underlying_reason"] = error.reason
    return ProviderError(
        f"Provider requested Retry-After of {retry_after:g} seconds, exceeding the {limit:g}-second limit",
        reason="retry_after_too_long",
        diagnostics=diagnostics,
    )


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
        call_ids.append(call_id)
    if len(output_ids) != len(set(output_ids)):
        raise ProviderError("model response contains duplicate output item id values",
                            diagnostics={"error_type": "protocol"})
    if len(call_ids) != len(set(call_ids)):
        raise ProviderError("model response contains duplicate tool call_id values",
                            diagnostics={"error_type": "protocol"})


def _valid_tool_arguments(raw: Any) -> bool:
    # 与工具循环同口径：能解析为对象才算有效
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return False
    return isinstance(parsed, dict)


def _sanitized_response(response: ModelResponse) -> ModelResponse:
    # 无效工具参数替换为有效 JSON 后再记入历史，具体错误仍经工具结果回传
    cleaned: list[dict[str, Any]] = []
    changed = False
    for item in response.output:
        if isinstance(item, dict) and item.get("type") == "function_call" \
                and not _valid_tool_arguments(item.get("arguments")):
            item = {**item, "arguments": "{}"}
            changed = True
        cleaned.append(item)
    if not changed:
        return response
    return response.model_copy(update={"output": cleaned})


def _undeclared_tool_calls(request: ModelRequest, response: ModelResponse) -> list[str]:
    """Tool call names in a response whose request offered no tools at all."""
    if request.tools:
        return []
    return [str(item.get("name")) for item in response.output if item.get("type") == "function_call"]


def _wait_for_retry(delay: float, nodes: SafeNode) -> bool:
    deadline = time.monotonic() + delay
    while True:
        if not nodes.proceed():
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
