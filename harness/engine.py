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
from collections.abc import Mapping, Sequence
from contextlib import aclosing
from dataclasses import asdict, dataclass, field, replace
from threading import Event
from typing import Any, Protocol

from .actions import Action, ActionReceipt, FactsQuery, Preconditions, TreeFacts, WorkspaceFacts
from .adapters.base import ModelAdapter, ModelRequest, ProviderError
from .adjudication import ToolPermission, facts_query, tool_permission
from .artifacts import ArtifactStore
from .assembly import ContextAssembly, StepFrame, StepRequest, model_limits
from .compaction import CompactionError
from .definitions import DEFINITIONS
from .deltas import DeltaChannel, DeltaScope
from .environment import LocalEnvironment, QA_TESTS_DIR, qa_tests_digest
from .event_store import run_stream
from .write_path import Transaction, WritePath
from .models import TERMINAL_PHASES, ArtifactRef, DepartmentPrompt, EventType, RunProjection, json_dumps
from .public_tree import UnrepresentableWorkspace
from .providers import ProviderFacade
from .providers.call import ModelResponse
from .providers.resolve import (CALL_TARGET_FIELDS, CALL_TARGET_REQUIRED_STRINGS, decision_call_target,
                                 event_call_target)
from .providers.selection import ModelSelection
from .recording import ActivationScope, StepRecorder
from .tools import proposal_kind, tool_action, tool_kind
from .validation import PRD_REVISION_FIELDS, evaluate_proposal
from .tree_archive import store_tree

# 整理请求使用的请求档位（设计说明第 7.5 节）：Provider 按模型声明限制，最低支持档位即为实际发送的档位
COMPACTION_REQUEST_TIER = "minimal"

# 整理请求使用的请求档位（设计说明第 7.5 节）：Provider 按模型声明限制，最低支持档位即为实际发送的档位
COMPACTION_REQUEST_TIER = "minimal"


@dataclass(frozen=True)
class Judgment:
    # 安全节点的回答：是否继续，以及作出判断时 run 流的版本
    proceed: bool
    version: int


class SafeNode(Protocol):
    # 安全节点接口：步骤驱动在安全节点调用它，流程编排在这里分派新输入、关闭因此过时的协作请求，回答继续还是停止。
    # 这是唯一一处由下层调用上层的接口，按依赖倒置处理：接口在步骤驱动一侧定义，流程编排实现并在开始时交给步骤驱动，
    # 步骤驱动不引用流程编排

    def proceed(self) -> Judgment:
        # 分派新输入，回答是否继续
        ...

    def settle(self, transaction: Transaction) -> RunProjection:
        # 在调用方的事务中分派新输入并关闭过时的协作请求，返回事务中当前的运行状态；调用方随后判断并写入
        ...

    async def wait(self, seconds: float) -> Judgment:
        # 在安全节点等待至多 seconds 秒，其间有新输入、指导或取消时提前回答；回答是否继续
        ...

    def end(self, transaction: Transaction, reason: str, message: str) -> None:
        # 以停止原因结束运行：运行的结束与调用方在同一事务中刚写下的记录一起提交
        ...

    def department_selection(self, department: str) -> ModelSelection | None:
        # 设置来源（项目层）：本次请求该项目该部门的项目部门设置中的模型选择；
        # 不属于项目的运行时为空，全部使用部门默认（设计说明第 6 节）
        ...

    def department_prompt(self, department: str) -> DepartmentPrompt:
        # 部门 Prompt 每次请求从项目部门设置读取；没有写入时使用内置默认 Prompt（版本 0）
        ...
    async def ask(self, scope: ActivationScope, call: dict[str, Any]) -> tuple[bool, Any, str | None, str | None, int]:
        # 开一个询问分支，等待分支回答，返回 (ok, output, error, new_contract_hash, branch_steps)
        ...



@dataclass(frozen=True)
class StepLimits:
    # 步骤驱动的重试与步数参数；默认值取规则登记中的现值，正式运行使用默认值
    retry_initial_delay_sec: float = DEFINITIONS.rule_value("retry_initial_delay_sec")
    retry_max_delay_sec: float = DEFINITIONS.rule_value("retry_max_delay_sec")
    max_provider_attempts: int = DEFINITIONS.rule_value("max_provider_attempts")
    max_model_steps: int = DEFINITIONS.rule_value("max_model_steps")
    department_max_model_steps: Mapping[str, int] = field(default_factory=dict)


def tool_call_required_text(count: int) -> str:
    limit = DEFINITIONS.rule_value("tool_call_required_limit")
    return (
        f"上一次回复没有调用工具（连续第 {count} 次，最多 {limit} 次）。"
        "只回复文字不会推进工作，也不会结束本次激活。"
        "工作没有完成时，调用下一个需要的工具；工作已经完成时，用本部门的提交工具提交提案。"
        f"连续第 {limit + 1} 次仍然没有调用工具时，运行暂停，等待用户处理。"
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
    # 运行状态收尾；否则是停止原因与说明，由流程编排暂停或结束运行。
    # version 是步骤驱动作出停止判断时（最后一次核对运行状态时）run 流的版本。
    # target 是这次失败对应的调用目标公开部分（不含密钥）：模型不可用时写进待恢复的决定请求。
    # facts 是停止原因要带给决定请求的事实引用（workspace_unrepresentable 的条目相对路径）
    version: int
    reason: str | None = None
    message: str = ""
    target: dict[str, Any] | None = None
    facts: list[str] | None = None
@dataclass(frozen=True)
class Answered:
    # 询问分支提交了回答：回答参数、带来回答的模型响应与发言
    args: dict[str, Any]
    response: ModelResponse
    transcript: str



StepResult = Submitted | Stopped | Answered


@dataclass(frozen=True)
class _Unassembled:
    # 这一步的请求没有装配成：停止原因与原来的错误。事务提交以后以这个原因停止
    reason: str
    error: Exception

@dataclass(frozen=True)
class _RecoveredCall:
    # 补执行上一次激活里没有处置的工具调用、以及自动重新执行结果未知的动作时用的请求身份（工单 #17、#307）。
    # 两个场合都沿用中断时那次响应的逻辑动作身份，使补执行与重新执行的记录和原来那次响应对应得上
    run_id: str
    department: str
    session_id: str
    activation_id: str
    step_id: int
    request_id: str | None
    context_event_id: str | None
    effective_contract_hash: str | None
    call_target: dict[str, Any]
    purpose: str = "work"
    attempt: int = 1
    attempt_id: str | None = None
    logical_call_id: str | None = None
    root_step_id: int | None = None
    retry_of_step_id: int | None = None
    input_version: int = 0
    max_output_tokens: int | None = None
    tool_choice: str = "auto"
    attempt_started_at: str | None = None
    attempt_started_monotonic: float | None = None
    attempt_finished_monotonic: float | None = None


def recovered_call_target(events: Sequence[Any], activation_id: str, step_id: int) -> dict[str, Any]:
    # 补执行与自动重新执行的调用目标（工单 #17、#307）：这两次尝试都没有新的模型请求，也不重新解析调用目标，
    # 因此照抄中断时那一步装配好的请求（context_assembled 的载荷带着解析出的公开部分与选择来源）。
    # 调用目标还没有解析出来时不能这样继续：tool_called 的载荷必须有完整的调用目标，缺少就立刻失败
    assembled = next((event for event in reversed(events)
                      if event.type == EventType.CONTEXT_ASSEMBLED
                      and str((event.payload or {}).get("activation_id")) == activation_id
                      and (event.payload or {}).get("step_id") == step_id), None)
    if assembled is None:
        raise ValueError(f"recovery needs the assembled request of step {activation_id}:{step_id}")
    basis = assembled.payload or {}
    missing = [key for key in CALL_TARGET_REQUIRED_STRINGS if not isinstance(basis.get(key), str)]
    if missing:
        raise ValueError("recovery needs a resolved call target; missing: " + ", ".join(missing))
    return {key: basis.get(key) for key in CALL_TARGET_FIELDS + ("selection_source",)}



class StepDriver:
    # 一次激活的步骤驱动。cancelled 是这次激活的取消信号，由流程编排持有；cancel() 可以从任何线程调用
    @classmethod
    def start(cls, scope: ActivationScope, prompt: DepartmentPrompt, *, writes: WritePath,
              artifacts: ArtifactStore, assembly: ContextAssembly, adapter: ModelAdapter,
              facade: ProviderFacade | None, environment: LocalEnvironment, nodes: SafeNode,
              cancelled: Event, limits: StepLimits, deltas: DeltaChannel) -> StepDriver:
        # 在当前事件循环中开始这次激活的步骤循环
        driver = cls(scope, prompt, writes=writes, artifacts=artifacts, assembly=assembly,
                     adapter=adapter, facade=facade, environment=environment, nodes=nodes,
                     cancelled=cancelled, limits=limits, deltas=deltas)
        driver._task = asyncio.get_running_loop().create_task(driver._run())
        return driver

    def __init__(self, scope: ActivationScope, prompt: DepartmentPrompt, *, writes: WritePath,
                 artifacts: ArtifactStore, assembly: ContextAssembly, adapter: ModelAdapter,
                 facade: ProviderFacade | None, environment: LocalEnvironment, nodes: SafeNode,
                 cancelled: Event, limits: StepLimits, deltas: DeltaChannel) -> None:
        self._scope = scope
        basis = scope.basis
        self._frame = StepFrame(scope.department, scope.session_id, scope.activation_id, prompt, scope.guidance_only,
                                basis.effective_contract_hash, basis.input_version)
        self._stream = run_stream(scope.run_id)
        self._writes = writes
        self._artifacts = artifacts
        self._assembly = assembly
        self._recorder = StepRecorder(writes, artifacts, scope, max_attempts=limits.max_provider_attempts)
        self._adapter = adapter
        self._facade = facade
        self._environment = environment
        self._nodes = nodes
        self._cancelled = cancelled
        self._limits = limits
        self._deltas = deltas
        self._request: ModelRequest | None = None
        self._action: Action | None = None
        self._step: StepRequest | None = None
        # 这次逻辑调用读取的部门 Prompt；每次新的逻辑调用从项目部门设置重新读取
        self._prompt: DepartmentPrompt = prompt
        self._task: asyncio.Task[StepResult] | None = None
        # 这次逻辑调用在 Provider 模块保留的句柄与公开部分；重试沿用，调用结束以后丢弃
        self._call_handle: str | None = None
        self._call_key: str | None = None
        self._call_public: dict[str, Any] | None = None
        # 最后一次核对运行状态时 run 流的版本，随停止结果交回
        self._version = 0

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
            return Stopped(self._version, exc.reason, str(exc),
                           decision_call_target(self._call_public or {}), list(exc.facts))
        except UnrepresentableWorkspace as exc:
            # 工作区在记录或其他主机工作中出现无法表示的条目：以 workspace_unrepresentable 暂停
            return Stopped(self._version, "workspace_unrepresentable", str(exc), None, list(exc.paths))
        except Exception as exc:
            # 其余异常（记录或执行环境出错等）按 provider_error 停止，说明写明异常的种类
            return Stopped(self._version, "provider_error", f"{type(exc).__name__}: {exc}")
        finally:
            self._release_call()
            self._recorder.close()

    def _begin_call(self, requested_tier: str | None = None) -> Stopped | None:
        # 新的逻辑调用：读取该项目该部门当前的部门设置（模型选择与部门 Prompt），交 Provider 解析调用目标；
        # 请求档位与模型访问定义按同一顺序取第一个写入了的（设计说明第 5.3 节），
        # 给出请求档位时按它解析，实际发送的档位由 Provider 按模型声明限制。
        # 选择来源是提供模型访问定义的那一层。失败时不发送请求，交回待恢复的停止结果
        self._release_call()
        if self._facade is None:
            raise ProviderError("model calls require the provider facade", reason="provider_error")
        project = self._nodes.department_selection(self._scope.department)
        self._prompt = self._nodes.department_prompt(self._scope.department)
        self._frame = replace(self._frame, prompt=self._prompt)
        resolution = self._facade.resolve_department_default(
            self._scope.department, requested_tier, project=project)
        if not resolution.available:
            return Stopped(self._version, resolution.reason, resolution.message,
                           decision_call_target(resolution.public))
        self._call_handle = resolution.handle_id
        self._call_public = event_call_target(resolution.public,
                                              selection_source=resolution.selection_source)
        return None

    def _bind_call(self, logical_call_id: str) -> None:
        # 把这次解析的目标挂到逻辑调用的身份上；重试与事务重新判断都沿用同一个句柄
        if self._call_key == logical_call_id:
            return
        if self._facade is None or self._call_handle is None:
            raise ProviderError("model calls require a resolved call target", reason="provider_error")
        self._facade.bind_call_key(self._call_handle, logical_call_id)
        self._call_key = logical_call_id

    def _release_call(self) -> None:
        # 逻辑调用结束（成功，或不再重试）以后丢弃它保留的凭据材料
        key = self._call_key or self._call_handle
        self._call_key = None
        self._call_handle = None
        self._call_public = None
        if key is not None and self._facade is not None:
            self._facade.release_call_handle(key)

    def _proceed(self) -> bool:
        judgment = self._nodes.proceed()
        self._version = judgment.version
        return judgment.proceed

    async def _wait(self, seconds: float) -> bool:
        judgment = await self._nodes.wait(seconds)
        self._version = judgment.version
        return judgment.proceed

    def _settle(self, transaction: Transaction) -> RunProjection:
        # 在这个事务中分派新输入并关闭过时的协作请求；随后的判断依据这时的运行状态
        projection = self._nodes.settle(transaction)
        self._version = projection.stream_version
        return projection

    async def _steps(self) -> StepResult:
        limits = self._limits
        self._consumed_steps = 0
        # 工单 #17：上一次激活的完整模型响应里还有没执行的合法动作时，先补执行这些动作，不重新调用模型
        # （恢复契约第 4、5 节）。补执行以后照常进入步骤循环，下一次模型请求带上这些工具结果
        await self._continue_unexecuted_calls()
        attempt = 1
        root_step_id = 1
        retry_of_step_id = None
        replies_without_tool_call = 0
        step_id = 0
        while self._consumed_steps < limits.max_model_steps:
            step_id += 1
            self._consumed_steps += 1
            if not self._proceed():
                return Stopped(self._version)
            prepared = self._prepare(step_id, attempt, root_step_id, retry_of_step_id,
                                     replies_without_tool_call)
            if isinstance(prepared, Stopped):
                return prepared
            request = prepared
            if request is None or not self._start_request(request):
                return Stopped(self._version)
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
                    and self._consumed_steps < limits.max_model_steps
                )
                will_retry = can_retry and self._proceed()
                self._recorder.attempt_failed(request, retry_error, will_retry)
                if not self._proceed():
                    return Stopped(self._version)
                if not will_retry:
                    if retry_error.retryable and self._consumed_steps >= limits.max_model_steps:
                        raise ProviderError(
                            "department reached the model step limit during provider retries",
                            reason="model_steps_exhausted",
                        ) from retry_error
                    diagnostics = dict(retry_error.diagnostics or {})
                    diagnostics.update(attempts=attempt, max_attempts=limits.max_provider_attempts)
                    raise ProviderError(
                        str(retry_error),
                        reason=_exhausted_stop_reason(retry_error.reason),
                        diagnostics=diagnostics,
                    ) from retry_error
                if not self._schedule_retry(request, retry_error, delay, step_id + 1):
                    return Stopped(self._version)
                if not await self._wait(delay):
                    return Stopped(self._version)
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
            # 这次逻辑调用成功，凭据材料不再保留；下一次逻辑调用重新解析
            self._release_call()
            if not self._proceed():
                self._skip(request, response.output,
                           "Not executed because this activation ended or its input changed during the model request.")
                return Stopped(self._version)
            if request.purpose == "compaction":
                self._finish_compaction(request, response)
                continue
            if not any(item.get("type") == "function_call" for item in response.output):
                # 回复已记入历史；追加一条 user 消息，下一次请求不以助手消息结尾
                replies_without_tool_call += 1
                if replies_without_tool_call > DEFINITIONS.rule_value("tool_call_required_limit"):
                    raise ProviderError(
                        f"department replied {replies_without_tool_call} times in a row without calling a tool",
                        reason="no_tool_call",
                    )
                self._recorder.tool_call_required(
                    request,
                    {"role": "user", "content": tool_call_required_text(replies_without_tool_call)},
                    replies_without_tool_call,
                    DEFINITIONS.rule_value("tool_call_required_limit"),
                )
                continue
            replies_without_tool_call = 0
            for index, item in enumerate(response.output):
                if item.get("type") != "function_call":
                    continue
                if not self._proceed():
                    self._skip(request, response.output[index:],
                               "Not executed because this activation ended or its input changed before these tools started.")
                    return Stopped(self._version)
                identity = str(item.get("call_id") or "")
                name = str(item.get("name") or "")
                raw_args = item.get("arguments")
                after_snapshot = None
                qa_tests_saved = None
                try:
                    args = json.loads(raw_args)
                    if not isinstance(args, dict):
                        raise ValueError("tool arguments must be an object")
                except (TypeError, ValueError) as exc:
                    args = {"invalid_arguments": raw_args}
                    ok, output, error = False, None, f"invalid tool arguments: {exc}"
                else:
                    try:
                        permission, facts = self._begin_tool(request, {"id": identity, "name": name, "args": args,
                                                                       "step_id": step_id})
                    except UnrepresentableWorkspace as exc:
                        # 工具许可需要工作区事实时发现无法表示的条目：以 workspace_unrepresentable 暂停运行
                        raise ProviderError(str(exc), reason="workspace_unrepresentable", facts=list(exc.paths)) from exc
                    if permission.stopped:
                        self._skip(request, response.output[index:],
                                   "Not executed because the current activation can no longer start tools.")
                        return Stopped(self._version)
                    if not permission.allowed:
                        ok, output, error = False, None, permission.reason
                    elif name == "ask":
                        ask_call = {
                            "id": identity,
                            "name": name,
                            "args": args,
                            "step_id": step_id,
                            "remaining_steps": max(0, limits.max_model_steps - self._consumed_steps),
                        }
                        ask_ok, ask_output, ask_error, new_contract_hash, branch_steps = await self._nodes.ask(self._scope, ask_call)
                        self._consumed_steps += branch_steps
                        ok, output, error = ask_ok, ask_output, ask_error
                        if ok and new_contract_hash is not None:
                            self._scope = replace(self._scope, basis=replace(self._scope.basis, effective_contract_hash=new_contract_hash))
                            self._frame = replace(self._frame, effective_contract_hash=new_contract_hash)
                            projection = self._writes.read(self._stream).projection
                            self._environment.bind_check(
                                activation_id=self._scope.activation_id,
                                product_spec_hash=None if projection.product_spec is None else projection.product_spec.content_hash,
                                delivery_spec_hash=None if projection.delivery_spec is None else projection.delivery_spec.content_hash,
                                effective_contract_hash=new_contract_hash,
                            )
                    elif name == "answer":
                        text = args.get("answer") or args.get("text") or ""
                        if not isinstance(text, str) or not text.strip():
                            ok, output, error = False, None, "answer must be a non-empty string"
                        elif any(args.get(field) is not None for field in PRD_REVISION_FIELDS):
                            if request.department != "product":
                                ok, output, error = False, None, "only product can revise product_spec"
                            else:
                                projection = self._writes.read(self._stream).projection
                                spec_proposal = {
                                    **{k: v for k, v in args.items() if k not in ("answer", "text") and v is not None},
                                    "kind": "product_spec",
                                    "issuer": "product",
                                }
                                facts = self._environment.query(FactsQuery(tree=True)).tree
                                events = self._writes.read(self._stream).events()
                                decision = evaluate_proposal(
                                    phase=projection.phase,
                                    department="product",
                                    proposal=spec_proposal,
                                    projection=projection,
                                    facts=facts,
                                    events=events,
                                )
                                if not decision.accepted:
                                    ok, output, error = False, None, "; ".join(e.message for e in decision.errors)
                                else:
                                    ok, output, error = True, text, None
                        else:
                            ok, output, error = True, text, None
                    elif tool_kind(name) == "host":
                        ok, output, error = True, _run_host_tool(name, args), None
                    else:
                        # 环境工具：一次动作，前置条件是工具许可所依据的公开树摘要；
                        # 执行后立即核对（例如登记命令结束后的读取）发现无法表示的条目时暂停运行
                        try:
                            receipt = await self._perform(Action(
                                action_id=f"{request.activation_id}:{step_id}:{identity}", kind=tool_action(name),
                                tool=name, department=request.department, input=args,
                                preconditions=Preconditions(tree_digest=None if facts.tree is None else facts.tree.digest),
                            ))
                        except UnrepresentableWorkspace as exc:
                            raise ProviderError(str(exc), reason="workspace_unrepresentable",
                                                facts=list(exc.paths)) from exc
                        ok, output, error = receipt.ok, receipt.output, receipt.error
                        # 动作后的公开树快照：与动作前快照、动作参数一起构成核实的依据
                        try:
                            after_snapshot = _tree_snapshot(self._environment.query(FactsQuery(tree=True)).tree)
                        except UnrepresentableWorkspace:
                            after_snapshot = None
                        qa_tests_saved = self._save_qa_tests_if_changed(request)
                input_item = {"type": "function_call_output", "call_id": identity,
                              "output": json_dumps({"ok": ok, "output": output, "error": error})}
                call = {"id": identity, "name": name, "args": args, "ok": ok,
                        "output": output, "error": error, "step_id": step_id, "input_item": input_item}
                self._recorder.tool_called(request, call, after_snapshot=after_snapshot, qa_tests_saved=qa_tests_saved)
                # 登记命令结束后主机核对公开树发现无法表示的条目：回执已记录，运行在这里暂停
                if isinstance(output, dict) and output.get("workspace_unrepresentable"):
                    failure = output["workspace_unrepresentable"]
                    raise ProviderError(failure["message"], reason="workspace_unrepresentable",
                                        facts=list(failure.get("paths", [])))
                if not self._proceed():
                    self._skip(request, response.output[index + 1:],
                               "Not executed because this activation ended or its input changed after the current tool.")
                    return Stopped(self._version)
                kind = proposal_kind(name)
                if kind is not None:
                    self._skip(request, response.output[index + 1:],
                               "Not executed because the department already submitted its proposal.")
                    proposal = output if ok else {**args, "kind": kind}
                    return Submitted(proposal, response, self._recorder.transcript)
                if name == "answer" and ok:
                    self._skip(request, response.output[index + 1:],
                               "Not executed because the branch session already submitted its answer.")
                    return Answered(args, response, self._recorder.transcript)
        raise ProviderError("department reached the model step limit without submitting a proposal",
                            reason="model_steps_exhausted")

    async def _continue_unexecuted_calls(self) -> None:
        # 工单 #17（恢复契约第 4、5 节）：上一次激活的完整模型响应里，有 Function Call 既没有 tool_started，
        # 也没有 tool_called 或 tool_skipped——进程在把整个响应执行完之前退出。这里补执行这些动作，
        # 每个都照常经过工具许可与执行环境，写好 tool_called；不重新调用模型，也不整批重发已经执行过的动作
        calls, request = self._unexecuted_calls()
        for call in calls:
            if not self._proceed():
                return
            await self._execute_call(request, call)

    def _unexecuted_calls(self) -> tuple[list[dict[str, Any]], _RecoveredCall | None]:
        # 最近一次进入历史的完整模型响应里，没有得到处置的工具调用。每一条 MODEL_MESSAGE 事件保存响应中的一个
        # 输出条目（function_call / message），同一次响应的事件共享（激活、步骤）：按这一组收集，再排除已经
        # 处置的（tool_started/tool_called/tool_skipped）。压缩请求的回答不是工作响应，跳过
        events = self._writes.read(self._stream).events()
        dispositioned: set[str] = set()
        responses: dict[tuple[str, int], list[Any]] = {}
        order: list[tuple[str, int]] = []
        for event in events:
            payload = event.payload or {}
            if event.department != self._scope.department or payload.get("purpose") == "compaction":
                continue
            if event.type in (EventType.TOOL_CALLED, EventType.TOOL_SKIPPED, EventType.ACTION_VERIFIED):
                identity = payload.get("id")
                if identity:
                    dispositioned.add(str(identity))
            elif event.type == EventType.TOOL_STARTED:
                if payload.get("name") != "ask":
                    identity = payload.get("id")
                    if identity:
                        dispositioned.add(str(identity))
            elif event.type == EventType.MODEL_MESSAGE and payload.get("message_ref"):
                key = (str(payload.get("activation_id") or ""), int(payload.get("step_id") or 0))
                if key not in responses:
                    responses[key] = []
                    order.append(key)
                responses[key].append(event)
        if not order:
            return [], None
        key = order[-1]
        group = responses[key]
        pending: list[dict[str, Any]] = []
        for event in group:
            ref = ArtifactRef(**event.payload["message_ref"])
            item = json.loads(self._artifacts.get_for_run(self._scope.run_id, ref))
            if not isinstance(item, dict) or item.get("type") != "function_call":
                continue
            identity = str(item.get("call_id") or item.get("id") or "")
            if identity and identity not in dispositioned:
                pending.append({"id": identity, "name": str(item.get("name") or ""),
                                "arguments": item.get("arguments")})
        if not pending:
            return [], None
        payload = group[0].payload
        return pending, _RecoveredCall(
            run_id=self._scope.run_id, department=self._scope.department, session_id=self._scope.session_id,
            activation_id=self._scope.activation_id, step_id=int(payload.get("step_id") or 0),
            request_id=payload.get("collaboration_request_id"), context_event_id=payload.get("context_event_id"),
            effective_contract_hash=self._scope.basis.effective_contract_hash,
            call_target=dict(self._call_public or {}), purpose="work",
        )

    async def _execute_call(self, request: "_RecoveredCall", item: dict[str, Any]) -> None:
        # 执行一个没有处置的工具调用并记录结果：与 _steps 的工具循环走同一条路径（工具许可、环境执行、记录）。
        identity = str(item.get("id") or "")
        name = str(item.get("name") or "")
        raw_args = item.get("arguments")
        after_snapshot = None
        qa_tests_saved = None
        try:
            args = json.loads(raw_args)
            if not isinstance(args, dict):
                raise ValueError("tool arguments must be an object")
        except (TypeError, ValueError) as exc:
            args = {"invalid_arguments": raw_args}
            ok, output, error = False, None, f"invalid tool arguments: {exc}"
        else:
            call = {"id": identity, "name": name, "args": args, "step_id": request.step_id}
            permission, facts = self._begin_tool(request, call)
            if permission.stopped or not permission.allowed:
                return
            if name == "ask":
                ask_call = {
                    "id": identity,
                    "name": name,
                    "args": args,
                    "step_id": request.step_id,
                    "remaining_steps": max(0, self._limits.max_model_steps - getattr(self, "_consumed_steps", 0)),
                }
                ask_ok, ask_output, ask_error, new_contract_hash, branch_steps = await self._nodes.ask(self._scope, ask_call)
                if hasattr(self, "_consumed_steps"):
                    self._consumed_steps += branch_steps
                ok, output, error = ask_ok, ask_output, ask_error
                if ok and new_contract_hash is not None:
                    self._scope = replace(self._scope, basis=replace(self._scope.basis, effective_contract_hash=new_contract_hash))
                    self._frame = replace(self._frame, effective_contract_hash=new_contract_hash)
                    projection = self._writes.read(self._stream).projection
                    self._environment.bind_check(
                        activation_id=self._scope.activation_id,
                        product_spec_hash=None if projection.product_spec is None else projection.product_spec.content_hash,
                        delivery_spec_hash=None if projection.delivery_spec is None else projection.delivery_spec.content_hash,
                        effective_contract_hash=new_contract_hash,
                    )
            elif tool_kind(name) == "host":
                ok, output, error = True, _run_host_tool(name, args), None
                receipt = await self._perform(Action(
                    action_id=f"{request.activation_id}:recovered:{identity}",
                    kind=tool_action(name),
                    tool=name, department=request.department, input=args,
                    preconditions=Preconditions(tree_digest=None if facts.tree is None else facts.tree.digest),
                ))
                ok, output, error = receipt.ok, receipt.output, receipt.error
                try:
                    after_snapshot = _tree_snapshot(self._environment.query(FactsQuery(tree=True)).tree)
                except UnrepresentableWorkspace:
                    after_snapshot = None
                qa_tests_saved = self._save_qa_tests_if_changed(request)
        input_item = {"type": "function_call_output", "call_id": identity,
                      "output": json_dumps({"ok": ok, "output": output, "error": error})}
        self._recorder.tool_called(request,
                                   {"id": identity, "name": name, "args": args, "ok": ok, "output": output,
                                    "error": error, "step_id": request.step_id, "input_item": input_item},
                                   after_snapshot=after_snapshot,
                                   qa_tests_saved=qa_tests_saved)

    def _save_qa_tests_if_changed(self, request: ModelRequest | _RecoveredCall) -> dict[str, Any] | None:
        if request.department != "quality":
            return None
        tree = self._environment.capture_qa_tests()
        digest = qa_tests_digest(tree)
        projection = self._writes.read(self._stream).projection
        if digest == projection.qa_tests_hash:
            return None
        if digest is None and projection.qa_tests_version == 0:
            return None
        ref = store_tree(self._artifacts, self._scope.run_id, tree)
        return {
            "version": projection.qa_tests_version + 1,
            "content_hash": digest,
            "archive_ref": asdict(ref),
            "activation_id": request.activation_id,
        }

    def _tool_choice(self, purpose: str, tools: list[dict[str, Any]], replies_without_tool_call: int) -> str:
        # 最后一次主机提示之后的工作请求要求调用工具；调用目标声明不接受时照常为自动（#102）
        declaration = (self._call_public or {}).get("accepts_required_tool_call", True)
        if (purpose == "work" and tools
                and replies_without_tool_call >= DEFINITIONS.rule_value("tool_call_required_limit")
                and declaration is not False):
            return "required"
        return "auto"

    def _prepare(self, step_id: int, attempt: int, root_step_id: int,
                 retry_of_step_id: int | None,
                 replies_without_tool_call: int) -> Stopped | ModelRequest | None:
        # 由 P 装配这一步；装配失败的原因换成停止原因。激活第一步的部门工作消息先写成事件，部门历史再从事件读出。
        # 装配失败时，分派新输入与关闭协作请求的记录照常提交，然后停止。
        # 新的逻辑调用按「项目部门设置、部门默认」合并后解析（Provider 在同一把锁内读取，
        # 并按当前模型声明的支持档位限制）；重试沿用该逻辑调用已经解析的目标与句柄
        scope = self._scope
        if retry_of_step_id is None:
            unavailable = self._begin_call()
            if unavailable is not None:
                return unavailable

        def prepare(transaction: Transaction) -> tuple[ModelRequest, StepRequest] | _Unassembled | None:
            projection = transaction.projection
            if projection.phase in TERMINAL_PHASES or self._cancelled.is_set():
                return None
            projection = self._settle(transaction)
            if scope.basis.changed(projection, scope.department):
                return None
            target = self._call_public or {}
            try:
                limits = model_limits(target["context_window"], target["configured_max_output_tokens"])
                snapshot_hash = self._environment.query(FactsQuery(tree=True)).tree.digest
                pinned = self._assembly.pin(projection, self._frame, limits, step_id=step_id,
                                            events=transaction.events(), snapshot_hash=snapshot_hash,
                                            call_target=target,
                                            input_modalities=tuple(target.get("input_modalities") or ()))
            except UnrepresentableWorkspace as exc:
                # 请求装配时发现工作区有公开树无法表示的条目：以 workspace_unrepresentable 暂停
                return _Unassembled("workspace_unrepresentable", exc)
            except ValueError as exc:
                return _Unassembled("context_overflow", exc)
            department_input = pinned.department_input
            if department_input is not None:
                self._recorder.department_input(transaction, step_id, department_input)
            history = self._assembly.department_history(transaction.events(), scope.department, session_id=scope.session_id)
            try:
                step = self._assembly.request(pinned, history)
            except UnrepresentableWorkspace as exc:
                return _Unassembled("workspace_unrepresentable", exc)
            except (CompactionError, ValueError, FileNotFoundError) as exc:
                return _Unassembled("context_overflow" if pinned.fills_window else "compaction_failed", exc)
            assembled = step.context
            logical_call_id = f"{scope.activation_id}:root-{root_step_id}:{assembled.manifest.purpose}"
            # 整理请求按最低支持档位解析：向 Provider 传「minimal」，它按模型声明取最低支持档位。
            # 用途只有装配以后才知道，如果这次逻辑调用用的请求档位不是它，重新解析一次
            # （重新解析会丢弃刚才还没有使用的句柄）；工作请求保持原来的解析
            if retry_of_step_id is None and assembled.manifest.purpose == "compaction" \
                    and (self._call_public or {}).get("requested_tier") != COMPACTION_REQUEST_TIER:
                unavailable = self._begin_call(COMPACTION_REQUEST_TIER)
                if unavailable is not None:
                    return unavailable
            self._bind_call(logical_call_id)
            request = ModelRequest(scope.run_id, scope.department, scope.session_id, scope.activation_id,
                                   step_id, assembled, assembled.tools,
                                   purpose=assembled.manifest.purpose,
                                   max_output_tokens=assembled.manifest.max_output_tokens,
                                   tool_choice=self._tool_choice(assembled.manifest.purpose, assembled.tools,
                                                                 replies_without_tool_call),
                                   effective_contract_hash=scope.basis.effective_contract_hash,
                                   request_id=scope.basis.request_id,
                                   attempt=attempt, root_step_id=root_step_id,
                                   retry_of_step_id=retry_of_step_id,
                                   attempt_id=f"{logical_call_id}:attempt-{attempt}",
                                   logical_call_id=logical_call_id,
                                   project_id=projection.project_id, work_item_id=projection.work_item_id,
                                   call_target=dict(target),
                                   guidance_version=scope.basis.guidance_version, **scope.versions())
            self._recorder.request_assembled(transaction, request, step, snapshot_hash)
            if not step.admitted:
                # 请求没有获准：运行的结束与请求的记录在同一个事务中提交
                self._nodes.end(transaction, "context_overflow", "model request exceeds context_window")
                return None
            return request, step

        prepared = self._writes.transact(self._stream, prepare)
        if isinstance(prepared, _Unassembled):
            facts = list(prepared.error.paths) if isinstance(prepared.error, UnrepresentableWorkspace) else []
            raise ProviderError(str(prepared.error), reason=prepared.reason, facts=facts) from prepared.error
        if prepared is None:
            return None
        self._request, self._step = prepared
        return self._request

    def _start_request(self, request: ModelRequest) -> bool:
        scope = self._scope

        def start(transaction: Transaction) -> bool:
            projection = self._settle(transaction)
            if projection.phase in TERMINAL_PHASES or self._cancelled.is_set():
                return False
            if scope.basis.changed(projection, scope.department):
                return False
            self._recorder.request_started(transaction, request)
            return True

        return self._writes.transact(self._stream, start)

    async def _call_model(self, request: ModelRequest) -> ModelResponse:
        # 流式输出逐条记录完成以后才取下一条（请求记录以后才发出请求），最后一条是这次调用尝试的结果；
        # 每条观察里的文字片段同时发布到控制核心的输出片段通道，转发给 live=1 的连接（设计说明第 5.6 节）
        attempt_id = request.attempt_id or ""
        try:
            async with aclosing(self._adapter.stream(request.model_call())) as items:
                async for item in items:
                    if isinstance(item, ModelResponse):
                        return item
                    self._recorder.stream(request, item)
                    if item.deltas:
                        self._deltas.publish(self._delta_scope(request), item.deltas)
        finally:
            if attempt_id:
                self._deltas.close_attempt(attempt_id)
        raise ProviderError("model call ended without a response", diagnostics={"error_type": "protocol"})

    def _delta_scope(self, request: ModelRequest) -> DeltaScope:
        return DeltaScope(
            attempt_id=request.attempt_id or "", logical_call_id=request.logical_call_id or "",
            run_id=self._scope.run_id, department=self._scope.department,
            project_id=request.project_id, work_item_id=request.work_item_id, role=None,
        )

    def _schedule_retry(self, request: ModelRequest, error: ProviderError, delay: float, next_step_id: int) -> bool:
        scope = self._scope

        def schedule(transaction: Transaction) -> bool:
            projection = self._settle(transaction)
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
            self._version = projection.stream_version
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
            projection = self._settle(transaction)
            facts = self._environment.query(facts_query(call))
            permission = tool_permission(
                projection, call, department=scope.department, guidance_only=scope.guidance_only,
                basis=scope.basis, aborted=self._cancelled.is_set(), facts=facts,
            )
            if not permission.allowed and scope.department == "quality" and call["name"] == "write_file":
                rel = str(call.get("args", {}).get("path") or "")
                if rel.replace("\\", "/").strip("/").split("/")[0] == QA_TESTS_DIR:
                    permission = ToolPermission()
            if permission.allowed:
                already_started = any(
                    e.type == EventType.TOOL_STARTED and (e.payload or {}).get("id") == call["id"]
                    for e in transaction.events()
                )
                if not already_started:
                    if tool_kind(call["name"]) != "host":
                        tree = facts.tree
                        if tree is None:
                            tree = self._environment.query(FactsQuery(tree=True)).tree
                        before_snapshot = _tree_snapshot(tree)
                    else:
                        before_snapshot = None
                    self._recorder.tool_started(transaction, request, call,
                                                before_snapshot=before_snapshot)
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


def _tree_snapshot(tree: TreeFacts | None) -> dict[str, Any] | None:
    # 公开树的动作前后快照（工单 #17）：摘要用于比对效果是否发生，entries 给出动作前后每个文件的内容哈希，
    # 中断以后按它与动作参数核对实际效果（工单 #308）；不含文件内容，只是依据
    if tree is None:
        return None
    return {"digest": tree.digest, "entries": [list(item) for item in zip(tree.files, tree.hashes)]}

def _run_host_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    # 主机工具由控制核心执行。现在只有提交类工具：提交的内容就是提案，模型自报的 exit_code 不是证据
    payload = dict(args)
    payload["kind"] = proposal_kind(name)
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


def _exhausted_stop_reason(reason: str) -> str:
    # 空输出是单次调用的失败分类（工单 #305），不在 D09 的停止原因清单里：重试用完以后沿用已有的模型服务故障处理
    return "provider_error" if reason == "empty_output" else reason


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
