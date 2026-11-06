# 步骤驱动：一次激活内的步骤循环，以异步方式执行。每一步先在安全节点得到继续或停止，经上下文装配（P）取得请求，
# 经 Provider 的异步接口调用模型，失败时按重试参数安排重试并在安全节点等待；回答中的工具调用逐个取得工具许可（U）
# 以后执行：主机工具（提交）由步骤驱动执行，环境工具作为动作交给执行环境；压缩请求的回答经 P 生成检查点；
# 提交提案时结束。所有记录经过记录接口；需要核对运行状态的记录在写入口的一个事务中读取运行状态、判断并写入，
# 其间另一方的写入使提交被拒绝时按写入以后的状态重新判断。
# 流程编排只调用开始（StepDriver.start）、取消（cancel）与取得结果（result：这一轮写下的事件范围与停止原因）；
# 步骤驱动向上只经过安全节点接口（SafeNode）。
# 这一份是执行契约第三版（execution_contract）的实现：它声明 CONTRACT_VERSION，薄驱动在开始一轮工作之前核对；
# 接口（开始一轮工作的请求、安全节点、上下限、结果）在契约模块里，这里只实现。结果的种类不写死：
# 这一轮算不算结束、结束成什么，由薄驱动问路由（工单 #861）。按部门取模型与提示词随开始一轮工作的请求
# 交进来（第三版，工单 #1511），不再经安全节点问薄驱动。

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from collections.abc import Callable, Sequence
from contextlib import aclosing
from dataclasses import asdict, dataclass, replace
from threading import Event
from typing import Any

from .actions import (
    Action,
    ActionReceipt,
    FactsQuery,
    Preconditions,
    TreeFacts,
    WorkspaceFacts,
    snapshot_payload,
)
from .adapters.base import ModelAdapter, ModelRequest, ProviderError
from .adjudication import ToolPermission, facts_query, tool_permission
from .artifacts import ArtifactStore
from .assembly import ContextAssembly, StepFrame, StepRequest, model_limits
from .watched_outputs import watched_new_work
from .compaction import CompactionError
from .contracts import artifact_hash
from .definitions import DEFINITIONS, Definitions
from .deltas import DeltaChannel, DeltaScope
from .environment import LocalEnvironment, qa_tests_digest
from .event_store import run_stream
from . import execution_contract
from .execution_contract import ActivationScope, Judgment, RoundRequest, RoundResult, SafeNode, StepLimits
from .write_path import Transaction, WritePath
from .models import (PRD_REVISION_FIELDS, TERMINAL_STATUSES, ArtifactRef, DepartmentPrompt, Event, EventType,
                     RunProjection, TrialCase, json_dumps, new_id)
from .public_tree import UnrepresentableWorkspace
from .providers import ProviderFacade
from .providers.call import ModelResponse
from .providers.resolve import (CALL_TARGET_FIELDS, CALL_TARGET_REQUIRED_STRINGS, decision_call_target,
                                 event_call_target)
from .recording import StepRecorder
from .tools import (in_force, proposal_kind, proposal_kinds, tool_action, tool_cancellable, tool_kind,
                    tool_verification, writes_check_materials)
from .validation import AdjudicationView, Tightening, evaluate_proposal
from .tree_archive import store_tree
from .trial_sessions import TRIAL_TOOLS, resolve_trial_call

# 试用用例的两个主机工具（浏览器与 computer use 设计说明「试用用例」，工单 #1180）：质检用 trial_case_begin
# 打开一个用例、按计划在浏览器里操作，用 trial_case_end 给出结论。用例打开到结束之间本部门在同一会话中的
# 浏览器与屏幕动作由运行状态投影记为它的步骤（按动作身份）；会话结束或中断时打开的用例结束为中断。
# 两个工具都不交给执行环境：输入核对、结论核对与事件在控制这一侧完成
TRIAL_CASE_BEGIN = "trial_case_begin"
TRIAL_CASE_END = "trial_case_end"
TRIAL_CASE_TOOLS = frozenset({TRIAL_CASE_BEGIN, TRIAL_CASE_END})
# 结论的三种取值；'interrupted' 由主机在会话结束时记下，质检不能自己交
TRIAL_CASE_RESULTS = ("passed", "failed", "unverified")
# 结束试用会话的三个工具：执行完以后看打开的用例是不是随会话结束了
TRIAL_SESSION_TOOLS = frozenset({"trial_start", "trial_open", "trial_stop"})
# 引用验收条件的形式（浏览器与 computer use 设计说明「验收条件的引用」）：AC<序号>，序号是它在 ProductSpec 里的位置
_CRITERION_ID = re.compile(r"^AC[1-9][0-9]*$")

# 整理请求使用的请求档位：Provider 按模型声明限制，最低支持档位即为实际发送的档位
COMPACTION_REQUEST_TIER = "minimal"

# 整理请求使用的请求档位：Provider 按模型声明限制，最低支持档位即为实际发送的档位
COMPACTION_REQUEST_TIER = "minimal"

# 整理请求自己失败时不按「这一次压缩不生效」处理的原因（工单 #1213）：未压缩的
# 历史放不进窗口是停下来的一条；取消与运行时间到、模型步数用完在决定是否重试的那一处先判定
_COMPACTION_STOP_REASONS = frozenset({"context_overflow"})


# 放行等输入处理完（工单 #561）：在安全节点等待时最多等这么久，醒来以后重新做工具许可。
# 产品那一轮结束、提交被写入时会唤醒它；没有收到唤醒（例如那一轮以文字回答结束）时也按这个间隔重新核对。
# 等待计入运行时间，运行时间用完时安全节点照常结束等待并停止这一轮
RELEASE_WAIT_INTERVAL_SEC = 0.5


def tool_call_required_text(count: int, limit: int | None = None) -> str:
    # limit 是这个 run 冻结的 tool_call_required_limit（工单 #1189）；不给时用定义里的初始值，
    # 只有不涉及某个 run 的调用方这样用（例如按定义核对提示文字的用例）
    if limit is None:
        limit = int(DEFINITIONS.rule_value("tool_call_required_limit"))
    return (
        f"上一次回复没有调用工具（连续第 {count} 次，最多 {limit} 次）。"
        "只回复文字不会推进工作，也不会结束本次激活。"
        "工作没有完成时，调用下一个需要的工具；工作已经完成时，用本部门的提交工具提交提案。"
        f"连续第 {limit + 1} 次仍然没有调用工具时，运行暂停，等待用户处理。"
    )


def _guidance_only_round(projection: RunProjection, scope: ActivationScope,
                         definitions: Definitions | None = None) -> bool:
    # 一轮开始时只有指导是新的工作，而且这段指导是这一轮收到的：这一轮没有要做的工作，
    # 模型不调用工具的文字回复就是回答用户（部门指导设计说明「处理结果与来源」，工单 #1037）。
    # 询问分支不是部门的一轮工作，它的文字回复仍按「要求调用工具」处理。
    # 关注关系按这个事项所用的那份定义取（工单 #1509）：不给时是进程加载的那一份
    if not scope.guidance_ids or scope.session_id in projection.branch_sessions:
        return False
    return watched_new_work(projection, scope.department, definitions) == ["guidance"]


def _text_reply(response: ModelResponse) -> bool:
    # 回复里给用户看的文字：输出条目 content 里的文本。空回复没有回答用户，仍按没有工具调用的回复处理
    for item in response.output:
        content = item.get("content")
        if isinstance(content, str) and content.strip():
            return True
        if isinstance(content, list) and any(
                isinstance(part, dict) and str(part.get("text") or "").strip() for part in content):
            return True
    return False


def product_spec_revision_error(department: str, definitions: Definitions | None = None) -> str | None:
    """回答里带 PRD 修订时这个角色的拒绝说明；空表示它能交这一种成果（工单 #1390）。

    能不能交按它的提案合同判断，不看部门名：把产品改名的定义里，改名后的角色得到与产品相同的回答。
    """
    if "product_spec" in proposal_kinds(department, definitions=definitions):
        return None
    return f"{department} cannot submit product_spec"


@dataclass(frozen=True)
class _Unassembled:
    # 这一步的请求没有装配成：停止原因与原来的错误。事务提交以后以这个原因停止
    reason: str
    error: Exception


@dataclass(frozen=True)
class _CompactionOutcome:
    # 一次压缩的结果：没有推进时的原因（推进时为空）、这次压缩覆盖的范围摘要，
    # 以及整理请求自己失败时要做的处理——这一步的工作请求按未压缩的历史照常发出，下一步再次整理（工单 #1155）
    stalled: str | None = None
    covered_digest: str | None = None
    retry_as_work: bool = False


class _LiveScope:
    # 记录器读到的工作依据：始终指向步骤驱动当前采用的激活范围（工单 #840）。
    # 询问带回新合同以后只改步骤驱动那一份，记录器、装配与请求自动用同一份，
    # 不再另外保存一份需要同步的副本
    def __init__(self, driver: "StepDriver") -> None:
        self._driver = driver

    def __getattr__(self, name: str) -> Any:
        if name == "_driver":
            raise AttributeError(name)
        return getattr(self._driver.scope, name)

@dataclass(frozen=True)
class _RecoveredCall:
    # 补执行上一次激活里没有处置的工具调用、以及自动重新执行结果未知的动作时用的请求身份（工单 #17、#307）。
    # 两个场合都沿用中断时那次响应的逻辑动作身份，使补执行与重新执行的记录和原来那次响应对应得上
    run_id: str
    department: str
    session_id: str
    activation_id: str
    step_id: int
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
    # 一次激活的步骤驱动，执行契约第一版的实现。cancelled 是这次激活的取消信号，由流程编排持有；
    # cancel() 可以从任何线程调用。薄驱动在开始一轮工作之前核对下面这一版
    CONTRACT_VERSION = execution_contract.CURRENT_VERSION

    @classmethod
    def start(cls, request: RoundRequest, *, writes: WritePath,
              artifacts: ArtifactStore, assembly: ContextAssembly, adapter: ModelAdapter,
              facade: ProviderFacade | None, environment: LocalEnvironment, nodes: SafeNode,
              cancelled: Event, deltas: DeltaChannel, tightening: Tightening,
              refresh_workspace: Callable[[], LocalEnvironment | None] | None = None,
              definitions: Definitions | None = None,
              mcp_sessions: Any | None = None) -> StepDriver:
        # 在当前事件循环中开始这次激活的步骤循环
        driver = cls(request, writes=writes, artifacts=artifacts, assembly=assembly,
                     adapter=adapter, facade=facade, environment=environment, nodes=nodes,
                     cancelled=cancelled, deltas=deltas, tightening=tightening,
                     refresh_workspace=refresh_workspace, definitions=definitions,
                     mcp_sessions=mcp_sessions)
        driver._task = asyncio.get_running_loop().create_task(driver._run())
        return driver

    def __init__(self, request: RoundRequest, *, writes: WritePath,
                 artifacts: ArtifactStore, assembly: ContextAssembly, adapter: ModelAdapter,
                 facade: ProviderFacade | None, environment: LocalEnvironment, nodes: SafeNode,
                 cancelled: Event, deltas: DeltaChannel, tightening: Tightening,
                 refresh_workspace: Callable[[], LocalEnvironment | None] | None = None,
                 definitions: Definitions | None = None,
                 mcp_sessions: Any | None = None) -> None:
        scope, prompt, limits = request.scope, request.prompt, request.limits
        self._scope = scope
        basis = scope.basis
        # 按部门取模型与提示词的来源（执行契约第三版，工单 #1511）：随开始一轮工作交进来，不再经安全节点问
        # 薄驱动。开始一轮工作的这一轮必须有它，每次逻辑调用从它读一次（见 `_department_settings_of`）
        self._department_settings = request.department_settings
        # 这个事项所用的那份定义（工单 #1098）：工具许可与提案校验按它的部门、工具与提案种类判，
        # 没有交的时候是当前加载的那一份；装配也按这一份取（工单 #1175 第 7 轮的契约 v2）
        self._definitions = in_force(definitions)
        # 这一步交给装配的输入：身份、提示、采用的版本、这一份定义，以及路由的工作引用（原样带过去，
        #）
        self._frame = StepFrame(scope.department, scope.session_id, scope.activation_id, prompt,
                                basis.effective_contract_hash, basis.input_version,
                                definitions=self._definitions, work_ref=request.work_ref)
        self._stream = run_stream(scope.run_id)
        self._writes = writes
        self._artifacts = artifacts
        self._assembly = assembly
        # 记录器读到的是步骤驱动当前采用的激活范围（工单 #840）：询问带回新合同以后自动跟着变
        self._recorder = StepRecorder(writes, artifacts, _LiveScope(self), max_attempts=limits.max_provider_attempts,
                                      definitions=self._definitions)
        self._adapter = adapter
        self._facade = facade
        self._environment = environment
        self._nodes = nodes
        self._cancelled = cancelled
        self._limits = limits
        self._deltas = deltas
        self._tightening = tightening
        # 这一轮只有指导、没有要做的工作：模型不调用工具的文字回复就是回答用户，这一轮正常结束。
        # 判断在轮开始时做一次，轮内保持，不因为指导随后进入模型输入或有了别的新工作而重算。
        # shortcut: 这个判断不持久化；进程重新启动以后同一轮由新会话接着做的，丢掉它并退回要求调用工具，
        # 这是可以接受的限制（工单 #1037）
        opened = writes.read(run_stream(scope.run_id))
        self._text_reply_answers = _guidance_only_round(opened.projection, scope, self._definitions)
        # 这个 run 的 MCP 会话表（网络与 MCP 设计说明「运行规则」，工单 #1175）：编排层按 run 持有，
        # 会话结束（run 关闭）时由它关闭。检查工作区按会话保留会换掉环境对象，会话表重新接上
        self._mcp_sessions = mcp_sessions
        if mcp_sessions is not None:
            environment.mcp_sessions = mcp_sessions
        # 这一轮写下的事件范围从这个版本往后算（工单 #861）：结果里的范围由它确定
        self._start_version = opened.version
        # 检查工作区按会话保留（工单 #558）：新交付封存以后质检的检查工作区要重建，
        # 由编排层给出重建好的工作区，这里只接着用
        self._refresh_workspace = refresh_workspace
        self._request: ModelRequest | None = None
        self._action: Action | None = None
        self._step: StepRequest | None = None
        # 这次逻辑调用读取的部门 Prompt；每次新的逻辑调用从项目部门设置重新读取
        self._prompt: DepartmentPrompt = prompt
        self._task: asyncio.Task[RoundResult] | None = None
        # 这次逻辑调用在 Provider 模块保留的句柄与公开部分；重试沿用，调用结束以后丢弃
        self._call_handle: str | None = None
        self._call_key: str | None = None
        self._call_public: dict[str, Any] | None = None
        # 最后一次核对运行状态时 run 流的版本，随停止结果交回
        self._version = 0
        # 压缩有没有在推进：连续没有推进的次数、上一次的原因、上一次压缩的覆盖范围与当时的有效合同
        self._compaction_stalls = 0
        self._compaction_reason = ""
        self._compaction_coverage: str | None = None
        self._compaction_contract: str | None = None
        # 整理请求刚失败过：这一步的请求按未压缩的历史装配，不另发整理请求；工作请求装配好以后清掉（工单 #1155）
        self._compaction_deferred = False
        # 停止原因是「整理连续没有推进达到上限」（工单 #1238）：这一次停下的原因交给薄驱动按待恢复处理，
        # 与整理请求本身装不进窗口的 compaction_failed 分开；同时记下这次整理请求的调用目标，
        # 待恢复的决定请求要写明部门与模型
        self._compaction_stalled_out = False
        self._compaction_stalled_target: dict[str, Any] | None = None

    def _transact(self, decide: Callable[[Transaction], Any]) -> Any:
        # 执行层写 run 流的事件：部门与停止原因按这个事项所用的那份定义核对（工单 #1509）。
        # 驱动在开始一轮工作时拿到的是事项冻结的那份定义，写入口不给时默认只认进程加载的那一份，
        # 换一份把部门改了名的定义以后第一个事件就会被拒
        return self._writes.transact(self._stream, decide, definitions=self._definitions,
                                     dispatch_number=self._scope.dispatch_number or None)

    @property
    def scope(self) -> ActivationScope:
        # 这次激活当前采用的工作依据：询问带回新合同以后换成新的那一份（工单 #840）
        return self._scope

    def _adopt_contract(self, contract_hash: str) -> None:
        # 询问带回新合同以后，引擎、装配与记录器用同一份工作依据（工单 #840）：
        # 步骤驱动这一份是唯一的来源，记录器读到的是它的当前值，记录器写的事件因此带新合同
        self._scope = replace(self._scope, basis=replace(self._scope.basis, effective_contract_hash=contract_hash))
        self._frame = replace(self._frame, effective_contract_hash=contract_hash)
        projection = self._writes.read(self._stream).projection
        self._environment.bind_check(
            activation_id=self._scope.activation_id,
            product_spec_hash=None if projection.product_spec is None else projection.product_spec.content_hash,
            delivery_spec_hash=None if projection.delivery_spec is None else projection.delivery_spec.content_hash,
            effective_contract_hash=contract_hash,
        )

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

    async def result(self) -> RoundResult:
        return await self._task

    async def _run(self) -> RoundResult:
        try:
            result = await self._steps()
        except ProviderError as exc:
            # 整理的调用目标在发起这条请求时已经释放（成功以后不再保留凭据材料），所以达到上限那一条
            # 用停下时记下的目标
            target = self._compaction_stalled_target or self._call_public or {}
            result = RoundResult(stop_reason=exc.reason, message=str(exc),
                                 target=decision_call_target(target), facts=tuple(exc.facts),
                                 stalled_compaction=self._compaction_stalled_out)
        except UnrepresentableWorkspace as exc:
            # 工作区在记录或其他主机工作中出现无法表示的条目：以 workspace_unrepresentable 暂停
            result = RoundResult(stop_reason="workspace_unrepresentable", message=str(exc),
                                 facts=tuple(exc.paths))
        except Exception as exc:
            # 其余异常（记录或执行环境出错等）按 provider_error 停止，说明写明异常的种类
            result = RoundResult(stop_reason="provider_error", message=f"{type(exc).__name__}: {exc}")
        finally:
            self._release_call()
            self._recorder.close()
        # 一轮工作的结果（docs/design/skeleton-and-application.md「执行契约」输出）：这一轮写下的事件范围、停止判断时的版本与停止原因。
        # 这一轮算不算结束、结束成什么，由薄驱动问路由（工单 #861）
        return replace(result, version=self._version, events=self._written())

    def _written(self) -> tuple[Event, ...]:
        # 这一轮写下的事件范围：这一轮开始以来 run 流上新增的那些。别的会话同时写入的也在范围里，
        # 按会话分开由路由自己做（路由按会话判断一轮的事件）
        return tuple(event for event in self._writes.read(self._stream).events()
                     if event.stream_version > self._start_version)

    def _department_settings_of(self, department: str) -> tuple[Any, DepartmentPrompt]:
        # 按部门取模型与提示词（执行契约第三版，工单 #1511）：从开始一轮工作时一起交进来的那份来源读，
        # 每次逻辑调用读一次。来源是开始一轮工作的一份，没交是接入错了（例如直接构造请求却漏了这个字段）：
        # 不替它写兜底，按薄驱动的通用异常处理收尾
        settings = self._department_settings
        return settings.department_selection(department), settings.department_prompt(department)

    def _begin_call(self, requested_tier: str | None = None) -> RoundResult | None:
        # 新的逻辑调用：从开始一轮工作交进来的那份来源读该项目该部门当前的部门设置（模型选择与部门 Prompt），
        # 交 Provider 解析调用目标；请求档位与模型访问定义按同一顺序取第一个写入了的
        # 给出请求档位时按它解析，实际发送的档位由 Provider 按模型声明限制。
        # 选择来源是提供模型访问定义的那一层。失败时不发送请求，交回待恢复的停止结果
        self._release_call()
        if self._facade is None:
            raise ProviderError("model calls require the provider facade", reason="provider_error")
        project, self._prompt = self._department_settings_of(self._scope.department)
        self._frame = replace(self._frame, prompt=self._prompt)
        resolution = self._facade.resolve_department_default(
            self._scope.department, requested_tier, project=project)
        if not resolution.available:
            return RoundResult(version=self._version, stop_reason=resolution.reason,
                               message=resolution.message, target=decision_call_target(resolution.public))
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

    def _proceed(self) -> Judgment:
        judgment = self._nodes.proceed()
        self._version = judgment.version
        return judgment

    def _stop_now(self, judgment: Judgment) -> RoundResult:
        # 这个会话停下。别的会话已经写下待恢复的决定请求时，它照常停下（事项的状态不变，工单 #856）；
        # 它自己也被挡住时（这次的模型请求发不出去），它写下自己的那一条决定请求，
        # 各写明自己的部门、模型与问题（模型管理设计说明「引用无法使用时」）。
        # 写下以后由流程编排走待恢复那一条路，与它自己走到被挡住那一步时写下的完全一样
        if judgment.blocked_by_other_session and self._facade is not None:
            unavailable = self._begin_call()
            if unavailable is not None:
                return unavailable
        return RoundResult(version=judgment.version)

    async def _wait(self, seconds: float) -> bool:
        judgment = await self._nodes.wait(seconds)
        self._version = judgment.version
        return judgment.proceed

    def _settle(self, transaction: Transaction) -> RunProjection:
        # 在这个事务中分派新输入；随后的判断依据这时的运行状态
        projection = self._nodes.settle(transaction)
        self._version = projection.stream_version
        return projection

    async def _steps(self) -> RoundResult:
        limits = self._limits
        self._consumed_steps = 0
        # 工单 #17：上一次激活的完整模型响应里还有没执行的合法动作时，先补执行这些动作，不重新调用模型
        # （恢复契约「动作分类与处置」、「角色任务的恢复」）。补执行以后照常进入步骤循环，下一次模型请求带上这些工具结果
        await self._continue_unexecuted_calls()
        attempt = 1
        root_step_id = 1
        retry_of_step_id = None
        replies_without_tool_call = 0
        step_id = 0
        while self._consumed_steps < limits.max_model_steps:
            step_id += 1
            self._consumed_steps += 1
            judgment = self._proceed()
            if not judgment.proceed:
                return self._stop_now(judgment)
            self._adopt_current_contract()
            self._refresh_workspace_now()
            prepared = self._prepare(step_id, attempt, root_step_id, retry_of_step_id,
                                     replies_without_tool_call)
            if isinstance(prepared, RoundResult):
                return prepared
            request = prepared
            if request is None or not self._start_request(request):
                return RoundResult(version=self._version)
            request.attempt_started_monotonic = time.monotonic()
            try:
                response = await self._call_model(request)
                _validate_response(response)
                request.attempt_finished_monotonic = time.monotonic()
                undeclared = _undeclared_tool_calls(request, response)
                # 整理请求没有声明工具、回应里却带了工具调用：回应里有文字时，文字照常经校验作为整理结果，
                # 工具调用不执行、不进入有效历史（工单 #1155，docs/design/model-management.md「失败处理」）
                summary_with_tool_calls = bool(undeclared) and request.purpose == "compaction" \
                    and _text_reply(response)
                if undeclared and not summary_with_tool_calls:
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
                will_retry = can_retry and self._proceed().proceed
                self._recorder.attempt_failed(request, retry_error, will_retry)
                if not self._proceed().proceed:
                    return RoundResult(version=self._version)
                if not will_retry:
                    if retry_error.retryable and self._consumed_steps >= limits.max_model_steps:
                        raise ProviderError(
                            "department reached the model step limit during provider retries",
                            reason="model_steps_exhausted",
                        ) from retry_error
                    if request.purpose == "compaction" and retry_error.reason not in _COMPACTION_STOP_REASONS:
                        # 整理请求失败（尝试次数用完）：这一次压缩不生效，不写检查点。这一步的工作请求按
                        # 未压缩的历史照常发送，下一步再次尝试压缩；连续没有推进的次数达到上限时在这里
                        # 以压缩失败停止（第一条，工单 #1155、#1213）。失败的原因不限：
                        # 空响应、上游故障与连接失败都走这一条；未压缩的历史放不进窗口（context_overflow，
                        #第三条）照旧停止；取消与运行时间到、模型步数用完在上面先判定
                        self._compaction_request_failed(request, f"整理请求失败：{retry_error}")
                        self._compaction_deferred = True
                        attempt = 1
                        root_step_id = step_id + 1
                        retry_of_step_id = None
                        self._release_call()
                        continue
                    diagnostics = dict(retry_error.diagnostics or {})
                    diagnostics.update(attempts=attempt, max_attempts=limits.max_provider_attempts)
                    raise ProviderError(
                        str(retry_error),
                        reason=_exhausted_stop_reason(retry_error.reason),
                        diagnostics=diagnostics,
                    ) from retry_error
                if not self._schedule_retry(request, retry_error, delay, step_id + 1):
                    return RoundResult(version=self._version)
                if not await self._wait(delay):
                    return RoundResult(version=self._version)
                attempt += 1
                retry_of_step_id = step_id
                continue
            try:
                # 截断流产生的无效参数不得进入有效历史，否则下次回放即被上游拒绝；
                # 工具循环仍用原始输出，保证具体参数错误回传模型且不启动工具。
                # 整理请求的回应带未声明的工具调用时原样记录：丢掉了哪些工具调用要能从事件里查到（工单 #1155）
                self._recorder.response(request, response if summary_with_tool_calls
                                        else _sanitized_response(response))
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
            # 上一次整理请求失败换来的这一次工作请求已经发出去了：下一步重新排整理请求（工单 #1155）
            self._compaction_deferred = False
            # 这次逻辑调用成功，凭据材料不再保留；下一次逻辑调用重新解析
            self._release_call()
            if not self._proceed().proceed:
                self._skip(request, response.output,
                           "Not executed because this activation ended or its input changed during the model request.")
                return RoundResult(version=self._version)
            if request.purpose == "compaction":
                outcome = self._finish_compaction(request, response)
                if outcome is not None and outcome.retry_as_work:
                    # 整理请求自己失败：这一次压缩不生效，不写检查点。这一步的工作请求按未压缩的历史
                    # 照常发送（放不进窗口时装配那一步以 context_overflow 结束），下一步再次尝试压缩
                    self._compaction_deferred = True
                continue
            if not any(item.get("type") == "function_call" for item in response.output):
                # 这一轮只有指导、没有要做的工作：文字回复就是对用户的回答，这一轮在这里正常结束。
                # 不追加提醒，也不写 tool_call_required；回复的文字已经记在模型消息里，不另存（工单 #1037）
                if self._text_reply_answers and _text_reply(response):
                    return RoundResult(version=self._version)
                # 回复已记入历史；追加一条 user 消息，下一次请求不以助手消息结尾
                replies_without_tool_call += 1
                if replies_without_tool_call > self._limits.tool_call_required_limit:
                    raise ProviderError(
                        f"department replied {replies_without_tool_call} times in a row without calling a tool",
                        reason="no_tool_call",
                    )
                self._recorder.tool_call_required(
                    request,
                    {"role": "user",
                     "content": tool_call_required_text(replies_without_tool_call,
                                                       self._limits.tool_call_required_limit)},
                    replies_without_tool_call,
                    self._limits.tool_call_required_limit,
                )
                continue
            replies_without_tool_call = 0
            for index, item in enumerate(response.output):
                if item.get("type") != "function_call":
                    continue
                if not self._proceed().proceed:
                    self._skip(request, response.output[index:],
                               "Not executed because this activation ended or its input changed before these tools started.")
                    return RoundResult(version=self._version)
                identity = str(item.get("call_id") or "")
                name = str(item.get("name") or "")
                raw_args = item.get("arguments")
                after_snapshot = None
                qa_tests_saved = None
                trial_case_draft = None
                deferred = False
                # 动作被拒绝的原因（工具许可或取回时的地址规则）：进入事件载荷，界面按「被拒绝」显示
                refused_reason = None
                try:
                    args = json.loads(raw_args)
                    if not isinstance(args, dict):
                        raise ValueError("tool arguments must be an object")
                except (TypeError, ValueError) as exc:
                    args = {"invalid_arguments": raw_args}
                    ok, output, error = False, None, f"invalid tool arguments: {exc}"
                else:
                    try:
                        permission, facts = await self._begin_tool_waiting_for_input(
                            request, {"id": identity, "name": name, "args": args, "step_id": step_id})
                    except UnrepresentableWorkspace as exc:
                        # 工具许可需要工作区事实时发现无法表示的条目：以 workspace_unrepresentable 暂停运行
                        raise ProviderError(str(exc), reason="workspace_unrepresentable", facts=list(exc.paths)) from exc
                    if permission.stopped:
                        self._skip(request, response.output[index:],
                                   "Not executed because the current activation can no longer start tools.")
                        return RoundResult(version=self._version)
                    if not permission.allowed:
                        # 工具许可拒绝：动作不交给执行环境，回执照常带动作身份、被拒绝标记与原因；
                        # 交给模型的工具结果保持原来的三项（ok、output、error），不带被拒绝标记（工单 #1275）
                        receipt = ActionReceipt.refusal(f"{request.activation_id}:{step_id}:{identity}",
                                                        permission.reason)
                        ok, output, error = receipt.ok, receipt.output, receipt.error
                        refused_reason = permission.reason
                        deferred = permission.deferred
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
                            self._adopt_contract(new_contract_hash)
                    elif name == "answer":
                        # 工程回答质检时回答分两部分：facts 是事实部分，explanation 是解释部分（工单 #554）
                        text = args.get("answer") or args.get("text") or args.get("facts") or ""
                        if not isinstance(text, str) or not text.strip():
                            ok, output, error = False, None, "answer must be a non-empty string"
                        elif any(args.get(field) is not None for field in PRD_REVISION_FIELDS):
                            # 回答里带 PRD 修订：这个角色能不能交这一种成果，按它的提案合同判断（工单 #1390），
                            # 交不了时照旧拒绝；提案带交它的角色
                            refusal = product_spec_revision_error(request.department, self._definitions)
                            if refusal is not None:
                                ok, output, error = False, None, refusal
                            else:
                                snapshot = self._writes.read(self._stream)
                                projection = snapshot.projection
                                spec_proposal = {
                                    **{k: v for k, v in args.items()
                                       if k not in ("answer", "text", "facts", "explanation") and v is not None},
                                    "kind": "product_spec",
                                    "issuer": request.department,
                                }
                                facts = self._environment.query(FactsQuery(tree=True)).tree
                                events = snapshot.events()
                                decision = evaluate_proposal(
                                    AdjudicationView(minimal=snapshot.minimal(), state=projection),
                                    department=request.department,
                                    proposal=spec_proposal,
                                    facts=facts,
                                    tightening=self._tightening,
                                    events=events,
                                    definitions=self._definitions,
                                )
                                if not decision.accepted:
                                    ok, output, error = False, None, "; ".join(e.message for e in decision.errors)
                                else:
                                    ok, output, error = True, text, None
                        else:
                            ok, output, error = True, text, None
                    elif name in TRIAL_CASE_TOOLS:
                        # 试用用例的两个主机工具（工单 #1180）：不交给执行环境，结果与用例事件一起写
                        outcome = self._trial_case_call(name, args)
                        ok, output, error = outcome.ok, outcome.output, outcome.error
                        trial_case_draft = self._trial_case_draft(outcome)
                    elif tool_kind(name, definitions=self._definitions) == "host":
                        ok, output, error = True, _run_host_tool(name, args, self._definitions), None
                    else:
                        # 环境工具：一次动作，前置条件是工具许可所依据的公开树摘要；
                        # 执行后立即核对（例如登记命令结束后的读取）发现无法表示的条目时暂停运行
                        try:
                            receipt = await self._perform(Action(
                                action_id=f"{request.activation_id}:{step_id}:{identity}",
                                kind=tool_action(name, definitions=self._definitions),
                                tool=name, department=request.department, input=args,
                                verification=tool_verification(name, definitions=self._definitions),
                                cancellable=tool_cancellable(name, definitions=self._definitions),
                                preconditions=Preconditions(tree_digest=None if facts.tree is None else facts.tree.digest),
                            ))
                        except UnrepresentableWorkspace as exc:
                            raise ProviderError(str(exc), reason="workspace_unrepresentable",
                                                facts=list(exc.paths)) from exc
                        ok, output, error = receipt.ok, receipt.output, receipt.error
                        refused_reason = receipt.refused_reason if receipt.refused else None
                        # 动作后的公开树快照：与动作前快照、动作参数一起构成核实的依据
                        try:
                            after_snapshot = _tree_snapshot(self._environment.query(FactsQuery(tree=True)).tree)
                        except UnrepresentableWorkspace:
                            after_snapshot = None
                        qa_tests_saved = self._save_qa_tests_if_changed(request)
                        if name in TRIAL_SESSION_TOOLS:
                            # 会话结束或中断时打开的用例结束为中断（工单 #1180）：用例的结论事件与这次会话
                            # 结束的工具结果写在同一个事务里
                            trial_case_draft = self._interrupted_trial_case()
                input_item = tool_result_item(identity, ok, output, error,
                                              input_modalities=tool_input_modalities(request))
                call = {"id": identity, "name": name, "args": args, "ok": ok,
                        "output": output, "error": error, "step_id": step_id, "input_item": input_item}
                if refused_reason is not None:
                    call["refused"] = True
                    call["refused_reason"] = refused_reason
                self._recorder.tool_called(request, call, after_snapshot=after_snapshot,
                                           qa_tests_saved=qa_tests_saved, trial_case=trial_case_draft)
                # 登记命令结束后主机核对公开树发现无法表示的条目：回执已记录，运行在这里暂停
                if isinstance(output, dict) and output.get("workspace_unrepresentable"):
                    failure = output["workspace_unrepresentable"]
                    raise ProviderError(failure["message"], reason="workspace_unrepresentable",
                                        facts=list(failure.get("paths", [])))
                if not self._proceed().proceed:
                    self._skip(request, response.output[index + 1:],
                               "Not executed because this activation ended or its input changed after the current tool.")
                    return RoundResult(version=self._version)
                kind = proposal_kind(name, definitions=self._definitions)
                if kind is not None:
                    if deferred:
                        # 这次提交推迟：模型还没有看见新的用户输入，通知在下一步送达，
                        # 部门没有提交正式成果，这一轮不结束（工单 #964）
                        continue
                    self._skip(request, response.output[index + 1:],
                               "Not executed because the department already submitted its proposal.")
                    proposal = output if ok else {**args, "kind": kind}
                    return RoundResult(version=self._version, submission=proposal, response=response,
                                       transcript=self._recorder.transcript)
                if name == "answer" and ok:
                    self._skip(request, response.output[index + 1:],
                               "Not executed because the branch session already submitted its answer.")
                    return RoundResult(version=self._version, submission=args, response=response,
                                       transcript=self._recorder.transcript)
        raise ProviderError("department reached the model step limit without submitting a proposal",
                            reason="model_steps_exhausted")

    async def _continue_unexecuted_calls(self) -> None:
        # 工单 #17（恢复契约「动作分类与处置」、「角色任务的恢复」）：上一次激活的完整模型响应里，有 Function Call 既没有 tool_started，
        # 也没有 tool_called 或 tool_skipped——进程在把整个响应执行完之前退出。这里补执行这些动作，
        # 每个都照常经过工具许可与执行环境，写好 tool_called；不重新调用模型，也不整批重发已经执行过的动作
        calls, request = self._unexecuted_calls()
        for call in calls:
            if not self._proceed().proceed:
                return
            await self._execute_call(request, call)

    def _unexecuted_calls(self) -> tuple[list[dict[str, Any]], _RecoveredCall | None]:
        # 最近一次进入历史的完整模型响应里，没有得到处置的工具调用。每一条 MODEL_MESSAGE 事件保存响应中的一个
        # 输出条目（function_call / message），同一次响应的事件共享（激活、步骤）：按这一组收集，再排除已经
        # 处置的（tool_started/tool_called/tool_skipped）。压缩请求的回答不是工作响应，跳过
        # 收集范围是这次激活自己的会话（工单 #473）：主线会话与分支会话是两条会话，
        # 分支不接手主线没有处置完的调用，同一个部门的两个会话各管各的
        events = self._writes.read(self._stream).events()
        dispositioned: set[str] = set()
        responses: dict[tuple[str, int], list[Any]] = {}
        order: list[tuple[str, int]] = []
        for event in events:
            payload = event.payload or {}
            if event.session_id != self._scope.session_id or payload.get("purpose") == "compaction":
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
            context_event_id=payload.get("context_event_id"),
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
        trial_case_draft = None
        try:
            args = json.loads(raw_args)
            if not isinstance(args, dict):
                raise ValueError("tool arguments must be an object")
        except (TypeError, ValueError) as exc:
            args = {"invalid_arguments": raw_args}
            ok, output, error = False, None, f"invalid tool arguments: {exc}"
        else:
            call = {"id": identity, "name": name, "args": args, "step_id": request.step_id}
            permission, facts = await self._begin_tool_waiting_for_input(request, call)
            if permission.stopped or not permission.allowed:
                return
            if name == "ask":
                ask_call = {
                    "id": identity,
                    "name": name,
                    "args": args,
                    "step_id": request.step_id,
                    "remaining_steps": max(0, self._limits.max_model_steps - self._consumed_steps),
                }
                ask_ok, ask_output, ask_error, new_contract_hash, branch_steps = await self._nodes.ask(self._scope, ask_call)
                self._consumed_steps += branch_steps
                ok, output, error = ask_ok, ask_output, ask_error
                if ok and new_contract_hash is not None:
                    self._adopt_contract(new_contract_hash)
            elif name in TRIAL_CASE_TOOLS:
                outcome = self._trial_case_call(name, args)
                ok, output, error = outcome.ok, outcome.output, outcome.error
                trial_case_draft = self._trial_case_draft(outcome)
            elif tool_kind(name, definitions=self._definitions) == "host":
                ok, output, error = True, _run_host_tool(name, args, self._definitions), None
            else:
                receipt = await self._perform(Action(
                    action_id=f"{request.activation_id}:recovered:{identity}",
                    kind=tool_action(name, definitions=self._definitions),
                    tool=name, department=request.department, input=args,
                    verification=tool_verification(name, definitions=self._definitions),
                    cancellable=tool_cancellable(name, definitions=self._definitions),
                    preconditions=Preconditions(tree_digest=None if facts.tree is None else facts.tree.digest),
                ))
                ok, output, error = receipt.ok, receipt.output, receipt.error
                try:
                    after_snapshot = _tree_snapshot(self._environment.query(FactsQuery(tree=True)).tree)
                except UnrepresentableWorkspace:
                    after_snapshot = None
                qa_tests_saved = self._save_qa_tests_if_changed(request)
        input_item = tool_result_item(identity, ok, output, error,
                                      input_modalities=tool_input_modalities(request))
        self._recorder.tool_called(request,
                                   {"id": identity, "name": name, "args": args, "ok": ok, "output": output,
                                    "error": error, "step_id": request.step_id, "input_item": input_item},
                                   after_snapshot=after_snapshot,
                                   qa_tests_saved=qa_tests_saved,
                                   trial_case=trial_case_draft)

    def _save_qa_tests_if_changed(self, request: ModelRequest | _RecoveredCall) -> dict[str, Any] | None:
        # 检查材料只由写入范围是检查材料的角色保存（docs/design/forms-and-verifier-role.md「核验角色」中「写入范围是检查材料」，工单 #1390）
        if not writes_check_materials(request.department, definitions=self._definitions):
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
                and replies_without_tool_call >= self._limits.tool_call_required_limit
                and declaration is not False):
            return "required"
        return "auto"

    def _prepare(self, step_id: int, attempt: int, root_step_id: int,
                 retry_of_step_id: int | None,
                 replies_without_tool_call: int) -> RoundResult | ModelRequest | None:
        # 由 P 装配这一步；装配失败的原因换成停止原因。激活第一步的部门工作消息先写成事件，部门历史再从事件读出。
        # 装配失败时，分派新输入与关闭协作请求的记录照常提交，然后停止。
        # 新的逻辑调用按「项目部门设置、部门默认」合并后解析（Provider 在同一把锁内读取，
        # 并按当前模型声明的支持档位限制）；重试沿用该逻辑调用已经解析的目标与句柄
        scope = self._scope
        if retry_of_step_id is None:
            unavailable = self._begin_call()
            if unavailable is not None:
                return unavailable
        # 上一步的整理请求失败过：这一步不另发整理请求，按未压缩的历史装配工作请求（工单 #1155）
        deferred = self._compaction_deferred

        def prepare(transaction: Transaction) -> tuple[ModelRequest, StepRequest] | _Unassembled | None:
            projection = transaction.projection
            if projection.status in TERMINAL_STATUSES or self._cancelled.is_set():
                return None
            projection = self._settle(transaction)
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
                step = self._assembly.request(pinned, history, defer_compaction=deferred)
            except UnrepresentableWorkspace as exc:
                return _Unassembled("workspace_unrepresentable", exc)
            except CompactionError as exc:
                return _Unassembled("context_overflow" if pinned.fills_window else "compaction_failed", exc)
            except (ValueError, FileNotFoundError) as exc:
                # 按未压缩的历史装配工作请求时放不下：按上下文超限结束（docs/design/model-management.md「失败处理」，工单 #1155）
                return _Unassembled("context_overflow" if (deferred or pinned.fills_window)
                                    else "compaction_failed", exc)
            assembled = step.context
            # 用户追加的输入在这个会话的下一步作为通知送达（工单 #964，循环结构「工作中途要求变化」与「指导」）：
            # 这个会话采用新的输入版本并接着工作，一轮工作不因此结束。
            # 采用以后模型就看见了这一版输入，正式成果才能按它提交。
            self._adopt_input_version(assembled.manifest.input_version)
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

        prepared = self._transact(prepare)
        if isinstance(prepared, _Unassembled):
            facts = list(prepared.error.paths) if isinstance(prepared.error, UnrepresentableWorkspace) else []
            raise ProviderError(str(prepared.error), reason=prepared.reason, facts=facts) from prepared.error
        if prepared is None:
            return None
        self._request, self._step = prepared
        return self._request

    def _start_request(self, request: ModelRequest) -> bool:
        def start(transaction: Transaction) -> bool:
            projection = self._settle(transaction)
            if projection.status in TERMINAL_STATUSES or self._cancelled.is_set():
                return False
            self._recorder.request_started(transaction, request)
            return True

        return self._transact(start)

    async def _call_model(self, request: ModelRequest) -> ModelResponse:
        # 流式输出逐条记录完成以后才取下一条（请求记录以后才发出请求），最后一条是这次调用尝试的结果；
        # 每条观察里的文字片段同时发布到控制核心的输出片段通道，转发给 live=1 的连接
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
        def schedule(transaction: Transaction) -> bool:
            projection = self._settle(transaction)
            if projection.status in TERMINAL_STATUSES or self._cancelled.is_set():
                return False
            self._recorder.retry_scheduled(transaction, request, error, delay, next_step_id)
            return True

        return self._transact(schedule)

    def _finish_compaction(self, request: ModelRequest, response: ModelResponse) -> _CompactionOutcome | None:
        # 整理请求的回答生成检查点。请求没有声明工具，回应里的工具调用不执行、不进入有效历史；
        # 文字才经 finish_compaction 校验（工单 #1155）
        summary_items = [item for item in response.output if item.get("type") != "function_call"]

        def finish(transaction: Transaction) -> _CompactionOutcome | None:
            # 压缩请求的回答生成检查点。这次压缩不生效或者覆盖范围没有往前走时，
            # 结果里写明没有推进的原因；连续没有推进的次数由调用方在事务提交以后判断
            projection = transaction.projection
            self._version = projection.stream_version
            if projection.status in TERMINAL_STATUSES or self._cancelled.is_set():
                return None
            try:
                result = self._assembly.finish_compaction(self._step, summary_items)
            except CompactionError as exc:
                # 回应不是摘要文字：这一次压缩不生效，不写检查点。这一步的工作请求按未压缩的历史照常
                # 发送，下一次再整理；与「整理不生效」计入同一个连续不推进的次数（工单 #1155）
                return _CompactionOutcome(stalled=f"整理没有通过校验：{exc}", retry_as_work=True)
            if result is None:
                # 摘要为空或超过上限：这次压缩不生效，下一步还会再压同一段历史
                return _CompactionOutcome(stalled="整理没有生效：摘要为空或超过上限")
            self._recorder.compaction(transaction, request, result, response)
            return _CompactionOutcome(covered_digest=result.checkpoint.covered_digest)

        outcome = self._transact(finish)
        message = self._advance_compaction(outcome)
        if message is not None:
            self._compaction_stalled_target = dict(request.call_target or {})
            raise ProviderError(message, reason="compaction_failed")
        return outcome

    def _compaction_request_failed(self, request: ModelRequest, reason: str) -> None:
        # 整理请求自己失败（尝试次数用完）：这一次压缩不生效，不写检查点。它与「整理不生效」「覆盖范围
        # 没有往前走」计入同一个连续不推进的次数，达到上限时以 compaction_failed 停下，由薄驱动按待恢复
        # 处理（docs/design/model-management.md「失败处理」，工单 #1155、#1238）
        message = self._advance_compaction(_CompactionOutcome(stalled=reason, retry_as_work=True))
        if message is not None:
            self._compaction_stalled_target = dict(request.call_target or {})
            raise ProviderError(message, reason="compaction_failed")

    def _advance_compaction(self, outcome: _CompactionOutcome | None) -> str | None:
        # 压缩连续没有推进时计数，达到上限时交出停止说明（docs/design/model-management.md「失败处理」，工单 #840、#1238）。
        # 没有推进有三种：整理请求自己失败（尝试次数用完，或回应不是摘要文字），整理不生效
        # （摘要为空或超过上限），或者这一次压缩的覆盖范围与上一次相同（下一次压缩没有被上一次接上）。
        # 合同变了以后检查点作废、从原始记录重建是现在的行为，不算没有推进。
        # 返回停止说明（写明连续的次数与最后一次的原因），没有达到上限时返回空
        if outcome is None:
            return None
        contract = self._scope.basis.effective_contract_hash
        if outcome.stalled is not None:
            self._compaction_stalls += 1
            self._compaction_reason = outcome.stalled
        elif self._compaction_coverage is not None and self._compaction_contract == contract \
                and outcome.covered_digest == self._compaction_coverage:
            self._compaction_stalls += 1
            self._compaction_reason = "覆盖范围没有往前走：这一次压缩与上一次覆盖同一段历史"
        else:
            self._compaction_stalls = 0
            self._compaction_reason = ""
            self._compaction_coverage = outcome.covered_digest
            self._compaction_contract = contract
        limit = self._limits.compaction_stalled_limit
        if self._compaction_stalls >= limit:
            # 达到上限：这次停下按待恢复处理（docs/design/model-management.md「失败处理」最后一条，工单 #1238）。说明只写事实，
            # 「结束还是等用户回答」不写在这里：用户答「停止事项」时同一段文字作为停止说明
            self._compaction_stalled_out = True
            return (f"压缩连续 {self._compaction_stalls} 次没有推进（{self._compaction_reason}），"
                    f"达到 compaction.stalled_limit={limit}。")
        return None

    def _adopt_current_contract(self) -> None:
        # PRD 有了新版本：这个会话在下一步收到通知（新版本与改动），采用新的有效合同并接着工作，
        # 这一轮不因此结束（工单 #558，循环结构「工作中途要求变化」）。采用以后检查回执绑定新的合同，
        # 部门按新版本重做的检查才能被交付与放行认下。
        projection = self._writes.read(self._stream).projection
        current = artifact_hash(projection.effective_contract)
        if current == self._scope.basis.effective_contract_hash:
            return
        self._adopt_contract(current)

    def _adopt_input_version(self, version: int) -> None:
        # 用户追加了输入：这次请求的上下文里已经有这条输入的通知（工单 #964，
        # 循环结构「工作中途要求变化」与「指导」）。这个会话采用这一版输入版本并接着工作，一轮工作不因此结束；
        # 采用以后模型就看见了这一版输入，正式成果才能按它提交。
        if version == self._scope.basis.input_version:
            return
        self._scope = replace(self._scope, basis=replace(self._scope.basis, input_version=version))
        # 整理检查点按这一版输入绑定（与合同同理，工单 #840）
        self._frame = replace(self._frame, input_version=version)

    def _refresh_workspace_now(self) -> None:
        # 检查工作区按会话保留（工单 #558）：检查工作区只在会话建立时与新交付封存以后重建，
        # 询问与通知都不重建。新的交付封存以后，质检的会话在下一步从这份交付重建（docs/design/local-tools.md「工作区」）。
        if self._refresh_workspace is None:
            return
        refreshed = self._refresh_workspace()
        if refreshed is not None:
            # 换掉的只是工作区对象：MCP 会话表属于这个 run（每台服务器一个实例），重新接上
            if self._mcp_sessions is not None:
                refreshed.mcp_sessions = self._mcp_sessions
            self._environment = refreshed

    def _begin_tool(self, request: ModelRequest, call: dict[str, Any]) -> tuple[ToolPermission, WorkspaceFacts]:
        # 工具许可依据的工作区事实向执行环境查询，作为输入交给 U；同一份事实是动作的前置条件
        scope = self._scope

        def begin(transaction: Transaction) -> tuple[ToolPermission, WorkspaceFacts]:
            projection = self._settle(transaction)
            facts = self._environment.query(facts_query(call, definitions=self._definitions))
            permission = tool_permission(
                AdjudicationView(minimal=transaction.minimal(), state=projection), call,
                department=scope.department, session_id=scope.session_id,
                basis=scope.basis, aborted=self._cancelled.is_set(), facts=facts,
                tightening=self._tightening, events=transaction.events(), definitions=self._definitions,
            )
            if permission.allowed and call["name"] in TRIAL_TOOLS:
                # 试用会话的启动方式（浏览器与 computer use 设计说明「启动方式」、「试用工具」，工单 #1182）：
                # 质检的 trial_open 按当前交付说明的名称解析，工程的 trial_start 用它给出的启动方式；
                # 解析不了的按工具许可拒绝交回，动作不交给执行环境，也不写工具开始事件
                _launch, reason = resolve_trial_call(call["name"], call["args"], projection.delivery_spec)
                if reason is not None:
                    permission = ToolPermission(reason=reason)
            if permission.allowed:
                already_started = any(
                    e.type == EventType.TOOL_STARTED and (e.payload or {}).get("id") == call["id"]
                    for e in transaction.events()
                )
                if not already_started:
                    if tool_kind(call["name"], definitions=self._definitions) != "host":
                        tree = facts.tree
                        if tree is None:
                            tree = self._environment.query(FactsQuery(tree=True)).tree
                        before_snapshot = _tree_snapshot(tree)
                    else:
                        before_snapshot = None
                    self._recorder.tool_started(transaction, request, call,
                                                before_snapshot=before_snapshot)
            return permission, facts

        return self._transact(begin)

    async def _begin_tool_waiting_for_input(
        self, request: ModelRequest | _RecoveredCall, call: dict[str, Any]
    ) -> tuple[ToolPermission, WorkspaceFacts]:
        # 工具许可：质检提交放行时还有没处理完的输入，就在安全节点上等到处理完再重新做一次许可
        # （部门指导设计说明「放行怎么等」，工单 #561）。等待发生在 tool_started 写入之前，这一次调用不返回模型、
        # 不写事件、不占步数；重新启动以后没有处置的工具调用照常重新执行，重新进入同一个等待。
        # 取消、暂停、运行时间用完照常生效：安全节点回答停止时这一段按停止结果交回
        while True:
            permission, facts = self._begin_tool(request, call)
            if not permission.wait_for_input:
                return permission, facts
            if not await self._wait(RELEASE_WAIT_INTERVAL_SEC):
                return ToolPermission(stopped=True), facts

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

    def _trial_session(self) -> dict[str, Any] | None:
        # 这个部门进行中的试用会话（身份与试用副本的树摘要）：用例打开时记下它，放行时按它核对当前交付
        session = self._environment.trial_session(self._scope.department)
        if session is None or session.get("status") != "running":
            return None
        return {"session_id": str(session["session_id"]), "tree_digest": str(session["tree_digest"])}

    def _trial_case_call(self, name: str, args: dict[str, Any]) -> TrialCaseOutcome:
        # 试用用例的两个主机工具：输入与结论在控制这一侧核对，读的是当前的运行状态投影与本部门的会话
        projection = self._writes.read(self._stream).projection
        scope = self._scope
        if name == TRIAL_CASE_BEGIN:
            return trial_case_begin(args, projection=projection, department=scope.department,
                                    session_id=scope.session_id or "", activation_id=scope.activation_id,
                                    session=self._trial_session())
        return trial_case_end(args, projection=projection, department=scope.department,
                              session_id=scope.session_id or "", session=self._trial_session())

    def _trial_case_draft(self, outcome: TrialCaseOutcome) -> Any:
        # 用例事件与触发它的工具结果写在同一个事务里（工单 #1180）：两件事要么一起写进去，要么都不写
        if outcome.event_type is None or outcome.payload is None:
            return None
        return self._recorder.trial_case_event(outcome.event_type, outcome.payload)

    def _interrupted_trial_case(self) -> Any:
        # 会话结束或中断时打开的用例结束为中断（浏览器与 computer use 设计说明「试用用例」，工单 #1180）：
        # 会话的结束已经由执行环境写好，这里补一条用例的结论；用例的投影在会话结束时已经记为中断
        scope = self._scope
        projection = self._writes.read(self._stream).projection
        case = next((item for item in projection.trial_cases
                     if item.status == "open" and item.department == scope.department), None)
        if case is None:
            return None
        current = self._trial_session()
        if current is not None and current["session_id"] == case.trial_session_id:
            return None
        return self._recorder.trial_case_event(EventType.TRIAL_CASE_CONCLUDED, {
            "case_id": case.case_id,
            "session_id": case.trial_session_id,
            "department": scope.department,
            "result": "interrupted",
            "observed": case.observed,
            "evidence_steps": [],
            "reason": "session_ended",
        })

    def _skip(self, request: ModelRequest, output: list[dict[str, Any]], error: str) -> None:
        for item in output:
            if item.get("type") != "function_call":
                continue
            self._recorder.tool_skipped(request, {
                "id": item["call_id"], "name": item["name"], "ok": False, "output": None,
                "error": error, "step_id": request.step_id,
                "input_item": tool_result_item(item["call_id"], False, None, error,
                                               input_modalities=tool_input_modalities(request))})


def _tree_snapshot(tree: TreeFacts | None) -> dict[str, Any] | None:
    # 公开树的动作前后快照（工单 #17）：摘要用于比对效果是否发生，entries 给出动作前后每个文件的内容哈希，
    # 中断以后按它与动作参数核对实际效果（工单 #308）；不含文件内容，只是依据。内容由动作合同给出
    # （工单 #1398）：回执里的终点快照引用指向的是同一份内容，读回执的一方不用再来这里取
    if tree is None:
        return None
    return snapshot_payload(tree)


# 动作回执的输出里带图像的写法：键 images 是一串图像工件引用（浏览器与 computer use 设计说明
# 「保存与绑定」：截图存成工件，工具结果带它的引用）
TOOL_IMAGE_KEY = "images"
TOOL_IMAGE_FIELDS = ("kind", "content_hash", "path", "media_type")


def tool_output_images(output: Any) -> tuple[dict[str, Any], ...]:
    # 从动作回执的输出里取出图像的工件引用；输出没有图像时为空
    if not isinstance(output, dict) or TOOL_IMAGE_KEY not in output:
        return ()
    images = output[TOOL_IMAGE_KEY]
    if not isinstance(images, list):
        raise ProviderError("tool result images must be a list of artifact references", reason="provider_protocol")
    result = []
    for image in images:
        if not isinstance(image, dict) or not all(
                isinstance(image.get(key), str) and image.get(key) for key in TOOL_IMAGE_FIELDS):
            raise ProviderError("tool result image must be an artifact reference", reason="provider_protocol")
        result.append({key: image[key] for key in TOOL_IMAGE_FIELDS})
    return tuple(result)


def tool_input_modalities(request: Any) -> tuple[str, ...]:
    # 这次调用请求的调用目标的输入方式（模型管理设计说明「模型访问定义与准入」）：工具结果里的截图是否进入请求按它决定
    return tuple((getattr(request, "call_target", None) or {}).get("input_modalities") or ())


def tool_result_item(identity: str, ok: bool, output: Any, error: str | None, *,
                     input_modalities: tuple[str, ...]) -> dict[str, Any]:
    # 工具结果进入部门历史的条目。调用目标包含图像时，回执里的截图作为工件引用随结果进入历史，
    # 由上下文装配按「最近 3 张」放进请求（设计说明「反事实回放（做了，但这批模型上**没有区分力**）」）；不含图像时截图只保存为证据，
    # 工具结果里既没有图像，也没有占位文字。条目就是回执的三项，模型输入审计按事件里的结果重新装配它
    images = tool_output_images(output)
    if isinstance(output, dict) and TOOL_IMAGE_KEY in output:
        output = {key: value for key, value in output.items() if key != TOOL_IMAGE_KEY}
    result: dict[str, Any] = {"ok": ok, "output": output, "error": error}
    item: dict[str, Any] = {"type": "function_call_output", "call_id": identity,
                            "output": json_dumps(result)}
    if images and "image" in input_modalities:
        item["images"] = [dict(image) for image in images]
    return item

def _run_host_tool(name: str, args: dict[str, Any],
                   definitions: Definitions | None = None) -> dict[str, Any]:
    # 主机工具由控制核心执行。现在只有提交类工具：提交的内容就是提案，模型自报的 exit_code 不是证据
    payload = dict(args)
    payload["kind"] = proposal_kind(name, definitions=definitions)
    payload.pop("exit_code", None)
    return payload


@dataclass(frozen=True)
class TrialCaseOutcome:
    # 一次试用用例工具的结果：交给模型的回执，以及要写进同一个事务的用例事件
    ok: bool
    output: dict[str, Any] | None = None
    error: str | None = None
    event_type: str | None = None
    payload: dict[str, Any] | None = None


def _text_field(value: Any, field: str) -> tuple[str, str | None]:
    if not isinstance(value, str) or not value.strip():
        return "", f"{field} must be a non-empty string"
    return value.strip(), None


def trial_case_begin(args: dict[str, Any], *, projection: RunProjection, department: str,
                     session_id: str, activation_id: str,
                     session: dict[str, Any] | None) -> TrialCaseOutcome:
    """打开一个试用用例（浏览器与 computer use 设计说明「试用用例」，工单 #1180）。

    主机的核对：本部门有进行中的试用会话；没有另一个打开的用例；引用的验收条件存在于当前 ProductSpec。
    """
    if session is None:
        return TrialCaseOutcome(False, error="trial_case_begin requires a running trial session; "
                                             "start one with trial_open first")
    open_case = next((case for case in projection.trial_cases
                      if case.status == "open" and case.department == department), None)
    if open_case is not None:
        return TrialCaseOutcome(False, error=f"trial case {open_case.case_id} is still open; "
                                             "end it with trial_case_end first")
    spec = projection.product_spec
    if spec is None:
        return TrialCaseOutcome(False, error="trial_case_begin requires a current ProductSpec")
    raw_criteria = args.get("criteria")
    if not isinstance(raw_criteria, list) or not raw_criteria:
        return TrialCaseOutcome(False, error="criteria must list at least one AC<position>")
    criteria: list[str] = []
    for item in raw_criteria:
        if not isinstance(item, str) or not _CRITERION_ID.match(item.strip()):
            return TrialCaseOutcome(False, error=f"criterion {item!r} must be AC<position>, the acceptance "
                                                 "criterion's position in the current ProductSpec")
        position = int(item.strip()[2:])
        if position > len(spec.acceptance_criteria):
            return TrialCaseOutcome(False, error=f"{item.strip()} is not an acceptance criterion of the current "
                                                 "ProductSpec")
        criteria.append(item.strip())
    title, error = _text_field(args.get("title"), "title")
    if error is not None:
        return TrialCaseOutcome(False, error=error)
    expected, error = _text_field(args.get("expected"), "expected")
    if error is not None:
        return TrialCaseOutcome(False, error=error)
    raw_plan = args.get("steps", [])
    if not isinstance(raw_plan, list) or any(not isinstance(item, str) for item in raw_plan):
        return TrialCaseOutcome(False, error="steps must be a list of planned operations")
    plan = [item.strip() for item in raw_plan if item.strip()]
    case_id = new_id("case")
    payload = {
        "case_id": case_id,
        # 部门会话与试用会话：前者决定哪些动作是它的步骤，后者结束或中断时用例结束为中断
        "session_id": session_id,
        "trial_session_id": session["session_id"],
        "department": department,
        "activation_id": activation_id,
        "product_spec_hash": spec.content_hash,
        # 所在会话的试用副本的树摘要：放行时按它核对用例属于当前交付（docs/design/browser-and-computer-use.md「QAReview 的逐条结论与放行」）
        "tree_digest": session["tree_digest"],
        "criteria": criteria,
        "title": title,
        "plan": plan,
        "expected": expected,
    }
    return TrialCaseOutcome(True, {"case_id": case_id, "status": "open", "criteria": criteria,
                                   "session_id": session["session_id"], "tree_digest": session["tree_digest"]},
                            None, EventType.TRIAL_CASE_OPENED, payload)


def trial_case_end(args: dict[str, Any], *, projection: RunProjection, department: str, session_id: str,
                   session: dict[str, Any] | None) -> TrialCaseOutcome:
    """结束一个试用用例并给出结论（浏览器与 computer use 设计说明「试用用例」，工单 #1180）。

    主机的核对：证据步骤属于这个用例；passed 时用例中没有结果未知的步骤；unverified 必须写明理由。
    """
    if session is None:
        return TrialCaseOutcome(False, error="trial_case_end requires a running trial session; "
                                             "start one with trial_open first")
    case: TrialCase | None = next((item for item in projection.trial_cases
                                   if item.status == "open" and item.department == department
                                   and item.session_id == session_id), None)
    if case is None:
        return TrialCaseOutcome(False, error="there is no open trial case in this session; "
                                             "open one with trial_case_begin first")
    result = args.get("result")
    if result not in TRIAL_CASE_RESULTS:
        return TrialCaseOutcome(False, error="result must be passed, failed, or unverified")
    observed, error = _text_field(args.get("observed"), "observed")
    if error is not None:
        return TrialCaseOutcome(False, error=error)
    raw_evidence = args.get("evidence_steps", [])
    if not isinstance(raw_evidence, list) or any(not isinstance(item, str) or not item.strip()
                                                 for item in raw_evidence):
        return TrialCaseOutcome(False, error="evidence_steps must be the action identities of steps of this case")
    evidence = [item.strip() for item in raw_evidence]
    for identity in evidence:
        if case.step(identity) is None:
            return TrialCaseOutcome(False, error=f"evidence step {identity} is not a step of trial case {case.case_id}")
    reason = args.get("reason")
    reason = reason.strip() if isinstance(reason, str) else ""
    if result in ("passed", "failed") and not evidence:
        return TrialCaseOutcome(False, error=f"result {result} requires at least one evidence step")
    if result == "unverified" and not reason:
        return TrialCaseOutcome(False, error="result unverified requires a reason")
    if result == "passed" and case.has_unknown_step():
        return TrialCaseOutcome(False, error=f"trial case {case.case_id} has a step whose result is unknown; "
                                             "it cannot end as passed. Run the case again")
    payload = {
        "case_id": case.case_id,
        "session_id": case.session_id,
        "department": department,
        "result": result,
        "observed": observed,
        "evidence_steps": evidence,
        "reason": reason,
    }
    return TrialCaseOutcome(True, {"case_id": case.case_id, "status": "concluded", "result": result,
                                   "evidence_steps": evidence}, None,
                            EventType.TRIAL_CASE_CONCLUDED, payload)


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
