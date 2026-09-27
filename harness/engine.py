# 步骤驱动：一次激活内的步骤循环，以异步方式执行。每一步先在安全节点得到继续或停止，经上下文装配（P）取得请求，
# 经 Provider 的异步接口调用模型，失败时按重试参数安排重试并在安全节点等待；回答中的工具调用逐个取得工具许可（U）
# 以后执行：主机工具（提交）由步骤驱动执行，环境工具作为动作交给执行环境；压缩请求的回答经 P 生成检查点；
# 提交提案时结束。所有记录经过记录接口；需要核对运行状态的记录在写入口的一个事务中读取运行状态、判断并写入，
# 其间另一方的写入使提交被拒绝时按写入以后的状态重新判断。
# 流程编排只调用开始（StepDriver.start）、取消（cancel）与取得结果（result：提交或停止原因）；
# 步骤驱动向上只经过安全节点接口（SafeNode）。

from __future__ import annotations

import asyncio
import json
import math
import time
from contextlib import aclosing
from dataclasses import dataclass
from threading import Event
from typing import Any, Protocol

from .actions import Action, ActionReceipt, FactsQuery, Preconditions, WorkspaceFacts
from .adapters.base import ModelAdapter, ModelRequest, ProviderError
from .adjudication import ToolPermission, facts_query, tool_permission
from .artifacts import ArtifactStore
from .assembly import ContextAssembly, StepFrame, StepRequest, model_limits
from .compaction import CompactionError
from .environment import LocalEnvironment
from .event_store import run_stream
from .write_path import Transaction, WritePath
from .models import TERMINAL_PHASES, DepartmentPrompt, RunProjection, json_dumps
from .providers.call import ModelResponse
from .providers.resolve import FrozenTarget
from .recording import ActivationScope, StepRecorder
from .tools import SUBMIT_KINDS, TOOL_DEFS

# 连续没有调用工具的回复最多追加这么多次说明，再出现一次就结束激活（次数取自 OMP）
TOOL_CALL_REQUIRED_LIMIT = 3


class SafeNode(Protocol):
    # 安全节点接口：步骤驱动在安全节点调用它，流程编排在这里分派新输入、关闭因此过时的协作请求，回答继续还是停止。
    # 这是唯一一处由下层调用上层的接口，按依赖倒置处理：接口在步骤驱动一侧定义，流程编排实现并在开始时交给步骤驱动，
    # 步骤驱动不引用流程编排

    def proceed(self) -> bool:
        # 分派新输入，回答是否继续
        ...

    def settle(self, transaction: Transaction) -> RunProjection:
        # 在调用方的事务中分派新输入并关闭过时的协作请求，返回事务中当前的运行状态；调用方随后判断并写入
        ...

    async def wait(self, seconds: float) -> bool:
        # 在安全节点等待至多 seconds 秒，其间有新输入、指导或取消时提前回答；回答是否继续
        ...

    def end(self, transaction: Transaction, reason: str, message: str) -> None:
        # 以停止原因结束运行：运行的结束与调用方在同一事务中刚写下的记录一起提交
        ...


@dataclass(frozen=True)
class StepLimits:
    # 步骤驱动的重试与步数参数；默认值是正式运行使用的值
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
class Submitted:
    # 部门提交了提案：提案、带来提案的这次回答，以及本次激活成功步骤中模型的发言
    proposal: dict[str, Any]
    response: ModelResponse
    transcript: str


@dataclass(frozen=True)
class Stopped:
    # 步骤驱动停止。reason 为空：在安全节点停止（中止、运行时间用完、终态、输入或依据改变），由流程编排按当时的
    # 运行状态收尾；否则是停止原因与说明，由流程编排暂停或结束运行
    reason: str | None = None
    message: str = ""


StepResult = Submitted | Stopped


@dataclass(frozen=True)
class _Unassembled:
    # 这一步的请求没有装配成：停止原因与原来的错误。事务提交以后以这个原因停止
    reason: str
    error: Exception


class StepDriver:
    # 一次激活的步骤驱动。cancelled 是这次激活的取消信号，由流程编排持有；cancel() 可以从任何线程调用
    @classmethod
    def start(cls, scope: ActivationScope, prompt: DepartmentPrompt, *, writes: WritePath,
              artifacts: ArtifactStore, assembly: ContextAssembly, adapter: ModelAdapter,
              target: FrozenTarget | None, environment: LocalEnvironment, nodes: SafeNode,
              cancelled: Event, limits: StepLimits) -> StepDriver:
        # 在当前事件循环中开始这次激活的步骤循环
        driver = cls(scope, prompt, writes=writes, artifacts=artifacts, assembly=assembly,
                     adapter=adapter, target=target, environment=environment, nodes=nodes,
                     cancelled=cancelled, limits=limits)
        driver._task = asyncio.get_running_loop().create_task(driver._run())
        return driver

    def __init__(self, scope: ActivationScope, prompt: DepartmentPrompt, *, writes: WritePath,
                 artifacts: ArtifactStore, assembly: ContextAssembly, adapter: ModelAdapter,
                 target: FrozenTarget | None, environment: LocalEnvironment, nodes: SafeNode,
                 cancelled: Event, limits: StepLimits) -> None:
        self._scope = scope
        basis = scope.basis
        self._frame = StepFrame(scope.department, scope.session_id, scope.activation_id, prompt, scope.guidance_only,
                                basis.effective_contract_hash, basis.engineering_plan_hash, basis.input_version)
        self._stream = run_stream(scope.run_id)
        self._writes = writes
        self._assembly = assembly
        self._recorder = StepRecorder(writes, artifacts, scope, max_attempts=limits.max_provider_attempts)
        self._adapter = adapter
        self._target = target
        self._environment = environment
        self._nodes = nodes
        self._cancelled = cancelled
        self._limits = limits
        self._request: ModelRequest | None = None
        self._action: Action | None = None
        self._step: StepRequest | None = None
        self._task: asyncio.Task[StepResult] | None = None

    def cancel(self) -> None:
        # 之后的核对都得到停止；正在进行的动作按动作身份取消（进程类动作结束整个进程树，回执记为已取消）；
        # 这一步已经准备了请求时按尝试身份取消这次调用尝试，尝试还没有开始时开始即取消。
        # 取消落在正在进行的这一项上，步骤循环在下一个安全节点停止，记录与没有取消时走同一条路径
        self._cancelled.set()
        action = self._action
        if action is not None:
            self._environment.cancel(action.action_id)
        request = self._request
        if request is not None and request.attempt_id:
            self._adapter.cancel(request.attempt_id)

    async def result(self) -> StepResult:
        return await self._task

    async def _run(self) -> StepResult:
        try:
            return await self._steps()
        except ProviderError as exc:
            return Stopped(exc.reason, str(exc))
        finally:
            self._recorder.close()

    async def _steps(self) -> StepResult:
        limits = self._limits
        attempt = 1
        root_step_id = 1
        retry_of_step_id = None
        replies_without_tool_call = 0
        for step_id in range(1, limits.max_model_steps + 1):
            if not self._nodes.proceed():
                return Stopped()
            request = self._prepare(step_id, attempt, root_step_id, retry_of_step_id)
            if request is None or not self._start_request(request):
                return Stopped()
            request.attempt_started_monotonic = time.monotonic()
            try:
                response = await self._call_model(request)
                _validate_response(response)
                request.attempt_finished_monotonic = time.monotonic()
                undeclared = _undeclared_tool_calls(request, response)
                if undeclared:
                    # Provider-side corruption: tool calls arrived although the request declared no
                    # tools. Keep the output as audit evidence (failed steps never enter effective
                    # history) and treat the attempt as a retryable failure; nothing executes.
                    self._recorder.response(request, response)
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
                will_retry = can_retry and self._nodes.proceed()
                self._recorder.attempt_failed(request, retry_error, will_retry)
                if not self._nodes.proceed():
                    return Stopped()
                if not will_retry:
                    if retry_error.retryable and step_id >= limits.max_model_steps:
                        raise ProviderError(
                            "department reached the model step limit during provider retries",
                            reason="model_steps_exhausted",
                        ) from retry_error
                    diagnostics = dict(retry_error.diagnostics or {})
                    diagnostics.update(attempts=attempt, max_attempts=limits.max_provider_attempts)
                    raise ProviderError(str(retry_error), reason=retry_error.reason, diagnostics=diagnostics) from retry_error
                if not self._schedule_retry(request, retry_error, delay, step_id + 1):
                    return Stopped()
                if not await self._nodes.wait(delay):
                    return Stopped()
                attempt += 1
                retry_of_step_id = step_id
                continue
            try:
                # 截断流产生的无效参数不得进入有效历史，否则下次回放即被上游拒绝；
                # 工具循环仍用原始输出，保证具体参数错误回传模型且不启动工具
                self._recorder.response(request, _sanitized_response(response))
            except Exception as exc:
                host_error = ProviderError(
                    f"model observation persistence failed: {type(exc).__name__}",
                    reason="provider_error",
                    retryable=False,
                    diagnostics={"error_type": "observation_persistence"},
                )
                self._recorder.attempt_failed(request, host_error, False)
                raise host_error from exc
            self._recorder.attempt_finished(request, response)
            attempt = 1
            root_step_id = step_id + 1
            retry_of_step_id = None
            if not self._nodes.proceed():
                self._skip(request, response.output,
                           "Not executed because this activation ended or its input changed during the model request.")
                return Stopped()
            if request.purpose == "compaction":
                self._finish_compaction(request, response)
                continue
            if not any(item.get("type") == "function_call" for item in response.output):
                # 回复已记入历史；追加一条 user 消息，下一次请求不以助手消息结尾
                replies_without_tool_call += 1
                if replies_without_tool_call > TOOL_CALL_REQUIRED_LIMIT:
                    raise ProviderError(
                        f"department replied {replies_without_tool_call} times in a row without calling a tool",
                        reason="no_tool_call",
                    )
                self._recorder.tool_call_required(
                    request,
                    {"role": "user", "content": tool_call_required_text(replies_without_tool_call)},
                    replies_without_tool_call,
                    TOOL_CALL_REQUIRED_LIMIT,
                )
                continue
            replies_without_tool_call = 0
            for index, item in enumerate(response.output):
                if item.get("type") != "function_call":
                    continue
                if not self._nodes.proceed():
                    self._skip(request, response.output[index:],
                               "Not executed because this activation ended or its input changed before these tools started.")
                    return Stopped()
                identity = str(item.get("call_id") or "")
                name = str(item.get("name") or "")
                raw_args = item.get("arguments")
                try:
                    args = json.loads(raw_args)
                    if not isinstance(args, dict):
                        raise ValueError("tool arguments must be an object")
                except (TypeError, ValueError) as exc:
                    args = {"invalid_arguments": raw_args}
                    ok, output, error = False, None, f"invalid tool arguments: {exc}"
                else:
                    permission, facts = self._begin_tool(request, {"id": identity, "name": name, "args": args,
                                                                   "step_id": step_id})
                    if permission.stopped:
                        self._skip(request, response.output[index:],
                                   "Not executed because the current activation can no longer start tools.")
                        return Stopped()
                    if not permission.allowed:
                        ok, output, error = False, None, permission.reason
                    elif TOOL_DEFS[name]["kind"] == "host":
                        ok, output, error = True, _run_host_tool(name, args), None
                    else:
                        # 环境工具：一次动作，前置条件是工具许可所依据的公开树摘要
                        receipt = await self._perform(Action(
                            action_id=f"{request.activation_id}:{step_id}:{identity}", kind=TOOL_DEFS[name]["action"],
                            tool=name, department=request.department, input=args,
                            preconditions=Preconditions(tree_digest=None if facts.tree is None else facts.tree.digest),
                        ))
                        ok, output, error = receipt.ok, receipt.output, receipt.error
                input_item = {"type": "function_call_output", "call_id": identity,
                              "output": json_dumps({"ok": ok, "output": output, "error": error})}
                call = {"id": identity, "name": name, "args": args, "ok": ok,
                        "output": output, "error": error, "step_id": step_id, "input_item": input_item}
                self._recorder.tool_called(request, call)
                if not self._nodes.proceed():
                    self._skip(request, response.output[index + 1:],
                               "Not executed because this activation ended or its input changed after the current tool.")
                    return Stopped()
                if name in SUBMIT_KINDS:
                    self._skip(request, response.output[index + 1:],
                               "Not executed because the department already submitted its proposal.")
                    proposal = output if ok else {**args, "kind": SUBMIT_KINDS[name]}
                    return Submitted(proposal, response, self._recorder.transcript)
        raise ProviderError("department reached the model step limit without submitting a proposal",
                            reason="model_steps_exhausted")

    def _prepare(self, step_id: int, attempt: int, root_step_id: int,
                 retry_of_step_id: int | None) -> ModelRequest | None:
        # 由 P 装配这一步；装配失败的原因换成停止原因。激活第一步的部门工作消息先写成事件，部门历史再从事件读出。
        # 装配失败时，分派新输入与关闭协作请求的记录照常提交，然后停止
        scope = self._scope

        def prepare(transaction: Transaction) -> tuple[ModelRequest, StepRequest] | _Unassembled | None:
            projection = transaction.projection
            if projection.phase in TERMINAL_PHASES or self._cancelled.is_set():
                return None
            projection = self._nodes.settle(transaction)
            if scope.basis.changed(projection, scope.department):
                return None
            target = self._target
            try:
                limits = model_limits(projection.context_window,
                                      None if target is None else target.context_window,
                                      None if target is None else target.max_output_tokens)
                snapshot_hash = self._environment.query(FactsQuery(tree=True)).tree.digest
                pinned = self._assembly.pin(projection, self._frame, limits, step_id=step_id,
                                            events=transaction.events(), snapshot_hash=snapshot_hash)
            except ValueError as exc:
                return _Unassembled("context_overflow", exc)
            department_input = pinned.department_input
            if department_input is not None:
                self._recorder.department_input(transaction, step_id, department_input)
            history = self._assembly.department_history(transaction.events(), scope.department)
            try:
                step = self._assembly.request(pinned, history)
            except (CompactionError, ValueError, FileNotFoundError) as exc:
                return _Unassembled("context_overflow" if pinned.fills_window else "compaction_failed", exc)
            assembled = step.context
            logical_call_id = f"{scope.activation_id}:root-{root_step_id}:{assembled.manifest.purpose}"
            request = ModelRequest(scope.run_id, scope.department, scope.session_id, scope.activation_id,
                                   step_id, assembled, assembled.tools,
                                   purpose=assembled.manifest.purpose,
                                   max_output_tokens=assembled.manifest.max_output_tokens,
                                   effective_contract_hash=scope.basis.effective_contract_hash,
                                   engineering_plan_hash=scope.basis.engineering_plan_hash,
                                   request_id=scope.basis.request_id,
                                   attempt=attempt, root_step_id=root_step_id,
                                   retry_of_step_id=retry_of_step_id,
                                   attempt_id=f"{logical_call_id}:attempt-{attempt}",
                                   logical_call_id=logical_call_id,
                                   guidance_version=scope.basis.guidance_version, **scope.versions())
            self._recorder.request_assembled(transaction, request, step, snapshot_hash)
            if not step.admitted:
                # 请求没有获准：运行的结束与请求的记录在同一个事务中提交
                self._nodes.end(transaction, "context_overflow", "model request exceeds context_window")
                return None
            return request, step

        prepared = self._writes.transact(self._stream, prepare)
        if isinstance(prepared, _Unassembled):
            raise ProviderError(str(prepared.error), reason=prepared.reason) from prepared.error
        if prepared is None:
            return None
        self._request, self._step = prepared
        return self._request

    def _start_request(self, request: ModelRequest) -> bool:
        scope = self._scope

        def start(transaction: Transaction) -> bool:
            projection = self._nodes.settle(transaction)
            if projection.phase in TERMINAL_PHASES or self._cancelled.is_set():
                return False
            if scope.basis.changed(projection, scope.department):
                return False
            self._recorder.request_started(transaction, request)
            return True

        return self._writes.transact(self._stream, start)

    async def _call_model(self, request: ModelRequest) -> ModelResponse:
        # 流式输出逐条记录完成以后才取下一条（请求记录以后才发出请求），最后一条是这次调用尝试的结果
        async with aclosing(self._adapter.stream(request.model_call())) as items:
            async for item in items:
                if isinstance(item, ModelResponse):
                    return item
                self._recorder.stream(request, item)
        raise ProviderError("model call ended without a response", diagnostics={"error_type": "protocol"})

    def _schedule_retry(self, request: ModelRequest, error: ProviderError, delay: float, next_step_id: int) -> bool:
        scope = self._scope

        def schedule(transaction: Transaction) -> bool:
            projection = self._nodes.settle(transaction)
            if (projection.phase in TERMINAL_PHASES or self._cancelled.is_set()
                    or scope.basis.changed(projection, scope.department)):
                return False
            self._recorder.retry_scheduled(transaction, request, error, delay, next_step_id)
            return True

        return self._writes.transact(self._stream, schedule)

    def _finish_compaction(self, request: ModelRequest, response: ModelResponse) -> None:
        scope = self._scope

        def finish(transaction: Transaction) -> None:
            projection = transaction.projection
            if projection.phase in TERMINAL_PHASES or self._cancelled.is_set():
                return
            if scope.basis.changed(projection, scope.department):
                return
            try:
                result = self._assembly.finish_compaction(self._step, response.output)
            except CompactionError as exc:
                raise ProviderError(str(exc), reason="compaction_failed") from exc
            if result is None:
                return
            self._recorder.compaction(transaction, request, result, response)

        self._writes.transact(self._stream, finish)

    def _begin_tool(self, request: ModelRequest, call: dict[str, Any]) -> tuple[ToolPermission, WorkspaceFacts]:
        # 工具许可依据的工作区事实向执行环境查询，作为输入交给 U；同一份事实是动作的前置条件
        scope = self._scope

        def begin(transaction: Transaction) -> tuple[ToolPermission, WorkspaceFacts]:
            projection = self._nodes.settle(transaction)
            facts = self._environment.query(facts_query(call))
            permission = tool_permission(
                projection, call, department=scope.department, guidance_only=scope.guidance_only,
                basis=scope.basis, aborted=self._cancelled.is_set(), facts=facts,
            )
            if permission.allowed:
                self._recorder.tool_started(transaction, request, call, permission.command_basis)
            return permission, facts

        return self._writes.transact(self._stream, begin)

    async def _perform(self, action: Action) -> ActionReceipt:
        # 先登记正在进行的动作，再看取消信号：取消落在登记之前时在这里交给执行环境，动作不开始；
        # 落在登记之后时由 cancel() 交给执行环境
        self._action = action
        try:
            if self._cancelled.is_set():
                self._environment.cancel(action.action_id)
            return await self._environment.perform(action)
        finally:
            self._action = None

    def _skip(self, request: ModelRequest, output: list[dict[str, Any]], error: str) -> None:
        for item in output:
            if item.get("type") != "function_call":
                continue
            self._recorder.tool_skipped(request, {
                "id": item["call_id"], "name": item["name"], "ok": False, "output": None,
                "error": error, "step_id": request.step_id,
                "input_item": {"type": "function_call_output", "call_id": item["call_id"],
                               "output": json_dumps({"ok": False, "output": None, "error": error})}})


def _run_host_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    # 主机工具由控制核心执行。现在只有提交类工具：提交的内容就是提案，模型自报的 exit_code 不是证据
    payload = dict(args)
    payload["kind"] = SUBMIT_KINDS[name]
    payload.pop("exit_code", None)
    return payload


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
    # 格式不对的回答在进入有效历史之前拒绝
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
    # 请求没有提供任何工具时，回答中的工具调用名称
    if request.tools:
        return []
    return [str(item.get("name")) for item in response.output if item.get("type") == "function_call"]
