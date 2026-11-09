# 薄驱动（可信内核）：只连接。循环与调度问路由该谁开始一轮工作、问边界能不能开始、等待与唤醒；
# 开始一轮工作、取派发编号、把结果经写入口写回，以及事项结束时写停止原因与核对流版本也在这里；
# 计时读最小投影里的已结算量加上当前这一段的起点（骨架与应用 docs/design/skeleton-and-application.md「最小投影」的
# 「驱动的计时读投影」）；安全节点回答步骤驱动继续还是停止。
# 要做的事经下面的钩子协议交给应用：一轮工作的准备、询问分支、提案的取舍、事项的入口与命令、MCP 与试用会话
# 都在应用一侧的流程编排里，薄驱动不导入它，构造时由它把自己交进来（骨架与应用 docs/design/skeleton-and-application.md「薄驱动」）。
#
# 本模块只导入内核模块、契约模块、标准库与 pydantic：导入由 harness/tests/test_thin_driver_imports.py 核对；
# 部门标识与成果种类不在这个文件里：检索由 harness/tests/test_thin_driver_names.py 覆盖。
#
# 薄驱动自己只读最小投影；运行视图、路由实现、定义与应用的会话状态是应用的东西，经钩子取得，
# 读应用投影的判断也在应用一侧。部门与成果的名称一律从定义取。

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from threading import Event
from typing import Any, Protocol

from . import assembly_contract, execution_contract
from .bounds import TIME_BOUND, time_left_sec, time_limit_message, time_used_up
from .event_store import run_stream
from .kernel_events import TERMINAL_STATUSES, SkeletonEventType
from .minimal_projection import MinimalProjection, SessionState
from .write_path import NewEvent, Transaction, WritePath


class DriverHooks(Protocol):
    # 薄驱动交给应用做的事：应用一侧的流程编排实现这个协议，构造薄驱动时把自己交进来。
    # 薄驱动只读最小投影，运行视图、路由与定义经这些方法取得；写入经薄驱动自己交给写入口，
    # 薄驱动把判断与结果交给应用收尾。

    # 运行视图、路由与定义
    def project(self, run_id: str) -> Any:
        # 这个 run 的运行视图（应用从事件折叠的那一份）
        ...

    def read_run(self, run_id: str) -> Any:
        # 这个 run 的只读快照：运行视图与还没回答的决定请求；run 不存在时抛出应用的错误
        ...

    def item_form_available(self, run_id: str) -> bool:
        # 这个事项创建时冻结的形态在发布里
        ...

    def routing(self, run_id: str) -> Any:
        # 这个事项用的路由实现（骨架与应用 docs/design/skeleton-and-application.md「路由契约」）
        ...

    def waiting_departments(self, run_id: str) -> set[str]:
        # 这个进程里在等待工作的部门：由应用按会话状态给出，路由据此判断谁该开始一轮工作
        ...

    def definitions(self, run_id: str) -> Any:
        # 这个事项冻结的那份定义：停止原因与部门按它核对
        ...

    def guidance_version(self, projection: Any, department: str) -> int:
        # 这个部门指导当前这一版的编号（指导是应用的数据，最小投影里没有它）
        ...

    def user_events(self) -> frozenset[str]:
        # 用户提出的事件种类（输入与指导）：停止判断核对流版本时用
        ...

    # 取消与结算
    def aborted(self, run_id: str) -> bool:
        # 事项自己被中止（用户取消）：之后的核对都得到停止
        ...

    def settled(self, run_id: str) -> Any:
        # 激活与运行循环结束时交回的运行状态：等正在进行的取消结束，必要时写入取消
        ...

    def await_cancellers(self, run_id: str) -> None:
        # 有正在进行的取消时等它结束（取消的写入排在激活收尾之前）
        ...

    def close_run(self, run_id: str) -> None:
        # 事项结束（事务提交以后）：关闭会话并清理检查工作区
        ...

    def session_idle(self, run_id: str, department: str) -> None:
        # 这一轮结束了：这个部门的会话回到等待工作
        ...

    # 一轮工作的准备、开始与收尾
    def prepare_round(self, run_id: str, transaction: Transaction, connections: Any,
                      department: str) -> Any:
        # 准备这个部门的一轮工作（检查能不能开始、取模型与提示词、会话），交回这一轮的身份与依据；
        # 不开始新的工作时交出 None。开始事件与派发编号由薄驱动在同一个事务里写
        ...

    def round_environment(self, round_work: Any) -> tuple[Any, Any]:
        # 这一轮用哪份工作区并绑定它；准备不了时交回 (None, RoundFailure)，由薄驱动按停止原因收尾
        ...

    def round_dependencies(self, round_work: Any, environment: Any) -> Any:
        # 开始一轮工作时交给执行实现的依赖（执行契约的 dependencies，由应用按这一轮备好）
        ...

    def round_failure(self, exc: Exception) -> Any:
        # 应用认得的异常翻成停止原因；不认得时为空，由薄驱动按执行失败或主机保存失败结束
        ...

    def apply_round_result(self, round_work: Any, result: Any, current: Any) -> None:
        # 一轮正常结束以后问路由这一轮以什么结束，再经写入口提交提案（提案的取舍在应用一侧）
        ...

    def after_round_finished(self, transaction: Transaction, round_work: Any, happened: list[Any]) -> None:
        # 一轮工作的结果（激活结束事件）写入以后：写这一轮已回答的指导，与激活结束在同一个事务里
        ...

    async def _invoke_activation(self, round_work: Any) -> None:
        # 跑完这一轮工作：薄驱动的连接在 `invoke_round` 里，应用这一层保留同名转交，
        # 让应用与测试能在这一轮结束的时刻做收尾（工单 #1513）
        ...

    def new_connections(self) -> Any:
        # 一次运行期间复用的模型连接
        ...

    def flush_trial_events(self, run_id: str) -> None:
        # run 结束时写排队中的试用会话结束事件
        ...

    async def close_mcp_sessions(self, run_id: str) -> None:
        # run 结束时关闭它的 MCP 会话
        ...

    # 事项结束
    def await_model(self, transaction: Transaction, round_work: Any, reason: str, message: str, *,
                    target: dict[str, Any] | None = None) -> None:
        # 模型引用无法使用（或整理连续没有推进）：发待恢复的决定请求，不结束运行
        ...

    def resume_after_pause(self, transaction: Transaction, reason: str, department: str,
                           message: str | None, facts: list[str]) -> None:
        # 暂停以后可以继续时发出决定请求（哪些停止原因可以继续由定义与这一层决定）
        ...

    def record_lesson_candidate(self, transaction: Transaction, reason: str, source_event: Any,
                                projection: Any) -> None:
        # 运行失败时记下教训候选（取消不算）
        ...

    # 安全节点上的动作
    def transact_run(self, run_id: str, decide: Callable[[Transaction], Any], **options: Any) -> Any:
        # 在这个 run 的事件流上读、判断、写入一个事务（应用补上按事项定义核对的选项）
        ...

    def assign_new_inputs(self, transaction: Transaction) -> Any:
        # 在调用方的事务中分派新输入，交回事务中当前的运行视图
        ...

    async def execute_ask(self, round_work: Any, scope: Any, call: dict[str, Any]) -> tuple[
            bool, Any, str | None, str | None, int]:
        # 询问分支由应用跑完一轮工作，交回 (ok, output, error, new_contract_hash, branch_steps)
        ...

    def blocks_run(self, decisions: Iterable[Any]) -> bool:
        # 有未回答的、阻塞 run 的决定请求
        ...

    def blocked_by_other_session(self, decisions: Iterable[Any], department: str) -> bool:
        # 别的会话已经写下待恢复的决定请求
        ...


@dataclass
class RoundPreparation:
    # 应用准备好的一轮工作（一轮工作的准备在应用一侧）：身份、提示、适配器、按部门取模型与提示词的来源、
    # 采用的依据与这一轮的提供方名称。薄驱动据此写这一轮的开始事件、取得派发编号
    session_id: str
    activation_id: str
    prompt: Any
    adapter: Any
    settings: Any
    basis: Any
    guidance_ids: tuple[str, ...]
    provider: str


@dataclass
class RoundDependencies:
    # 开始一轮工作时交给执行契约实现的依赖（执行契约的 dependencies，由应用按这一轮备好）：
    # 薄驱动只经契约把它们交过去，不解释其中的读数与工作区政策
    execution: Any
    assembly: Any
    artifacts: Any
    facade: Any
    deltas: Any
    tightening: Any
    definitions: Any
    environment: Any
    limits: Any
    work_ref: Any
    refresh_workspace: Any
    mcp_sessions: Any = None


@dataclass
class RoundFailure:
    # 应用把自己的异常翻成的停止原因与说明：薄驱动按它经写入口结束运行
    reason: str
    message: str
    facts: list[str] | None = None


@dataclass
class RoundWork:
    # 一轮工作：身份与依据（scope）、提示、这个会话自己的停止开关、适配器、开始时的流版本，以及执行实现交出的驱动。
    # 询问分支也是薄驱动记下的一轮（应用经 `start_execution` 接上执行）；停止开关是每个会话自己的（工单 #856）
    scope: Any
    prompt: Any
    stop_flag: Any
    adapter: Any
    version: int | None
    driver: Any = None
    wakeup: tuple[asyncio.AbstractEventLoop, asyncio.Event] | None = None
    deadline: float | None = None
    settings: Any = None

    @property
    def run_id(self) -> str:
        return self.scope.run_id

    @property
    def department(self) -> str:
        return self.scope.department

    @property
    def round_id(self) -> str:
        # 这一轮工作的派发身份：事件的字段名仍是 activation_id（已经写进日志的字段不改，工单 #1513）
        return self.scope.activation_id

    @property
    def activation_id(self) -> str:
        # 旧名留一版（工单 #1513）：新的代码用 round_id
        return self.round_id


class ThinDriver:
    # 薄驱动：循环、调度、计时、一轮工作的开始与写回、事项结束与安全节点。它只经钩子协议与应用说话，
    # 写入经写入口，边界的核对与最小投影从内核模块取。
    def __init__(self, writes: WritePath, hooks: DriverHooks, *,
                 run_clock: Callable[[], float] | None = None) -> None:
        self._writes = writes
        self._hooks = hooks
        # 运行时间读的时钟：默认是单调时钟。测试交进受控的时钟，把「运行时间用完」安排在它选定的时点
        self._run_clock: Callable[[], float] = time.monotonic if run_clock is None else run_clock
        # 运行时间的计时：已经结算的量读最小投影，正在跑的那一段只有驱动知道，所以驱动只记这一段从什么时候
        # 开始（单调时钟）。等待期间段计时暂停，等待的时间不计入：停表时把这一段折进 segment_ms，
        # 醒来重新记起点；这一轮结束、累计量写进事件以后，投影给出已结算量，这一段清零
        self.segment_ms: dict[str, int] = {}
        self._segment_start: dict[str, float] = {}
        # 每个会话这一段的起点（run 的已用毫秒）：会话自己的累计已用时间读最小投影的会话一级用量，
        # 这一段用掉多少由这个起点算
        self._session_base_ms: dict[tuple[str, str], int] = {}
        # 运行到停止的循环在等会话时同时等新工作：run 编号 → (循环, 事件)。
        # 没有会话在跑而新输入、指导或取消提交时，由 wake 打开它，循环醒来重新找可以开始的部门
        self._run_wakeups: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Event]] = {}
        # 正在进行的轮次：同一个 run 的同一个部门只占一次（准备之前先占住），_active 是这些轮次本身。
        # 停会话、唤醒与「还有别的会话在工作时计时继续」都读它
        self._running: dict[tuple[str, str], object] = {}
        self._active: dict[str, dict[str, RoundWork]] = {}

    # 计时读投影：已结算的量加当前这一段 ------------------------------------------------------

    def elapsed_sec(self, run_id: str) -> float:
        # 这个 run 已经用的运行时间（秒）：已持久化的累计加上当前运行段
        return self.elapsed_ms(run_id) / 1000.0

    def elapsed_ms(self, run_id: str) -> int:
        # 这个 run 已经用的运行时间（毫秒）：最小投影里已结算的那一部分加上当前这一段
        total_ms = self._writes.minimal(run_stream(run_id)).used.settled_ms + self.segment_ms.get(run_id, 0)
        started = self._segment_start.get(run_id)
        if started is not None:
            total_ms += max(0, int((self._run_clock() - started) * 1000))
        return total_ms

    def session_used(self, run_id: str, session_id: str) -> SessionState:
        # 一个会话的已用量：读最小投影，不各自从事件数一遍；没有激活过的会话在投影里没有条目，按全零处理
        return self._writes.minimal(run_stream(run_id)).sessions.get(session_id, SessionState())

    def start_session_segment(self, run_id: str, session_id: str) -> None:
        # 会话这一段工作的起点：记下 run 此刻的累计已用时间
        self._session_base_ms[(run_id, session_id)] = self.elapsed_ms(run_id)

    def settle_session_segment(self, run_id: str, session_id: str, run_elapsed_ms: int) -> int:
        # 会话这一段工作用掉的毫秒数：run 的累计已用时间减去这一段的起点，加上投影里已结算的那一部分。
        # 一个部门会话包含它等待的分支会话的时间（用量计入提问方），因此各会话的用时之和可以大于事项的用时
        key = (run_id, session_id)
        settled = self.session_used(run_id, session_id).settled_ms
        base = self._session_base_ms.pop(key, None)
        if base is None:
            return settled
        return settled + max(0, run_elapsed_ms - base)

    def session_elapsed_sec(self, run_id: str, session_id: str) -> float:
        # 这个会话已经用的运行时间（秒）：投影里已结算的那一部分加上当前这一段
        total = self.session_used(run_id, session_id).settled_ms
        base = self._session_base_ms.get((run_id, session_id))
        if base is not None:
            total += max(0, self.elapsed_ms(run_id) - base)
        return total / 1000.0

    def pause_run_clock(self, run_id: str, exclude: str | None = None) -> None:
        # 暂停这个 run 的段计时：进入等待时调用，等待的时间不计入运行时间。
        # 同时运行：还有别的会话在工作时计时继续
        active = self.activations(run_id)
        if any(key != exclude for key in active):
            return
        started = self._segment_start.pop(run_id, None)
        if started is not None:
            self.segment_ms[run_id] = self.segment_ms.get(run_id, 0) + max(
                0, int((self._run_clock() - started) * 1000))

    def resume_run_clock(self, run_id: str) -> None:
        # 等待结束以后重新开始段计时
        self._segment_start.setdefault(run_id, self._run_clock())

    def settle_run_segment(self, run_id: str, department: str | None = None) -> int:
        # 激活结束：把当前运行段也写入累计；还有其他会话工作时，提交以后从新的起点继续计时。
        # 当前段必须在 rebase_run_clock 重设起点以前结算，保留同时运行的会话已经用掉的时间
        self.pause_run_clock(run_id, exclude=department)
        return self.elapsed_ms(run_id)

    def rebase_run_clock(self, run_id: str) -> None:
        # 一轮工作的累计量写进事件以后：已结算量改由投影给出，停过表的那些段清零；
        # 别的会话还在工作时这一段的起点从这里重新记，不把已经结算的那一段时间再算一遍
        self.segment_ms[run_id] = 0
        if run_id in self._segment_start:
            self._segment_start[run_id] = self._run_clock()

    def time_left(self, run_id: str) -> float:
        # 剩余运行时间读最小投影
        return time_left_sec(self._writes.minimal(run_stream(run_id)), self.elapsed_sec(run_id))

    # 一轮工作：开始、跑完、结果写回 ---------------------------------------------------------

    def activations(self, run_id: str) -> dict[str, RoundWork]:
        # 这个 run 正在进行的轮次，按部门：停会话、唤醒与计时都要用
        return self._active.get(run_id, {})

    def cancel_round(self, round_work: RoundWork) -> None:
        # 停下这个会话：打开它自己的停止开关，取消正在进行的步骤，并唤醒在安全节点等待的那一轮。
        # 只停这个会话，不改变事项的状态（工单 #856）
        round_work.stop_flag.set()
        try:
            if round_work.driver is not None:
                round_work.driver.cancel()
        finally:
            self.wake(round_work.run_id, restart=True)

    async def activate_department(self, run_id: str, department: str, connections: Any) -> Any:
        # 这个部门的一轮工作：准备、取派发编号、写开始事件、跑执行、把结果写回。
        # 同时运行（工单 #557）：一个 run 里不同部门的会话各自一个任务，同一个部门同时只有一轮
        claim = object()
        key = (run_id, department)
        if self._running.setdefault(key, claim) is not claim:
            raise RuntimeError("department already has an active department invocation")
        try:
            round_work = self._hooks.transact_run(
                run_id, lambda transaction: self.begin_round(transaction, run_id, department, connections))
            if round_work is None:
                # 没有开始新的轮次（等待用户回答、已经结束、达到上限或这个部门已经别人的工作）：
                # 这段不计入运行时间，累计保留在内存里，下次激活从事件恢复时继续
                self.pause_run_clock(run_id)
                return await asyncio.to_thread(self._hooks.settled, run_id)
            self._active.setdefault(run_id, {})[department] = round_work
            started = time.monotonic()
            try:
                await self._hooks._invoke_activation(round_work)
            finally:
                # 激活进行中开始的取消先写入，再记录激活结束：结束事件按取消以后的运行状态关闭会话
                await asyncio.to_thread(self._hooks.await_cancellers, run_id)
                self.finish_round(round_work, started)
                # 这一轮的累计量已经写进事件：已结算量改由投影给出，停过表的段清零（S1e 工单 #1015）
                self.rebase_run_clock(run_id)
                self._hooks.session_idle(run_id, department)
                active = self._active.get(run_id)
                if active is not None:
                    active.pop(department, None)
                    if not active:
                        self._active.pop(run_id, None)
            return await asyncio.to_thread(self._hooks.settled, run_id)
        finally:
            self._running.pop(key, None)

    def begin_round(self, transaction: Transaction, run_id: str, department: str,
                    connections: Any) -> RoundWork | None:
        # 一轮工作的开始（骨架与应用「薄驱动」第 6 条；总图第三节「重派与迟到的结果」）：
        # 应用准备这一轮，薄驱动在这个事务里取派发编号、写这一轮的开始事件，把身份与依据交给执行
        prepared = self._hooks.prepare_round(run_id, transaction, connections, department)
        if prepared is None:
            return None
        projection = transaction.projection
        session_id = prepared.session_id
        # 派发编号：开始一轮工作时写一条事件取得编号，这一轮写入的事件都带它；重派先写事件、编号加一，
        # 旧编号交回的结果只记录、不改变事项的状态
        transaction.claim_dispatch_number(session_id)
        parent = transaction.append(NewEvent(
            SkeletonEventType.DISPATCH_NUMBER_ACQUIRED, actor="system", department=department,
            state_before=projection.status, state_after=projection.status, session_id=session_id,
            payload={"activation_id": prepared.activation_id, "cycle": projection.cycle_count + 1},
        ), NewEvent(
            SkeletonEventType.DEPARTMENT_ACTIVATED, actor="system", department=department,
            state_before=projection.status, state_after=projection.status, session_id=session_id,
            provider=prepared.provider,
            payload={"activation_id": prepared.activation_id, "cycle": projection.cycle_count + 1,
                     "effective_contract_hash": prepared.basis.effective_contract_hash,
                     "guidance_ids": list(prepared.guidance_ids),
                     "guidance_version": prepared.basis.guidance_version,
                     "input_version": prepared.basis.input_version,
                     "prompt_version": prepared.prompt.version,
                     "prompt_hash": prepared.prompt.prompt_ref.content_hash},
        ))[1]
        scope = execution_contract.ActivationScope(
            run_id, department, session_id, prepared.activation_id, parent.event_id,
            prompt_version=prepared.prompt.version, prompt_hash=prepared.prompt.prompt_ref.content_hash,
            guidance_ids=prepared.guidance_ids, basis=prepared.basis, provider=prepared.provider,
            dispatch_number=parent.dispatch_number or 0,
        )
        # 会话这一段工作的起点（工单 #475）：这一段用掉的时间算到这个会话的累计已用时间里
        self.start_session_segment(run_id, session_id)
        # 这个会话自己的停止开关（工单 #856）：停这个会话只停这个会话，不改变事项的状态
        return RoundWork(scope, prepared.prompt, Event(), prepared.adapter,
                         transaction.projection.stream_version, settings=prepared.settings)

    def start_execution(self, round_work: RoundWork, request: execution_contract.RoundRequest,
                        dependencies: RoundDependencies) -> Any:
        # 按执行契约开始一轮工作：核对两个实现声明的版本，把应用备好的依赖交给执行实现，交回它交出的驱动。
        # 询问分支也走这里（它的请求与依赖由应用按路由的请求备好，工单 #862）
        declared = execution_contract.accept(dependencies.execution)
        assembly_contract.accept(dependencies.assembly)
        round_work.driver = dependencies.execution.start(
            request, writes=self._writes, artifacts=dependencies.artifacts,
            assembly=dependencies.assembly, adapter=round_work.adapter, facade=dependencies.facade,
            environment=dependencies.environment, nodes=self.safe_node(round_work, declared),
            cancelled=round_work.stop_flag, deltas=dependencies.deltas,
            tightening=dependencies.tightening, refresh_workspace=dependencies.refresh_workspace,
            definitions=dependencies.definitions, mcp_sessions=dependencies.mcp_sessions,
        )
        return round_work.driver

    async def invoke_round(self, round_work: RoundWork) -> None:
        # 按执行契约开始这一轮工作，等它的结果，经写入口写回（骨架与应用「薄驱动」第 2、4 条）：
        # 工作区由应用准备；执行实现与依赖经钩子取；这一轮算不算结束、结束成什么由应用问路由（钩子）
        scope = round_work.scope
        run_id = scope.run_id
        environment, failure = self._hooks.round_environment(round_work)
        if failure is not None:
            self.end_run(round_work, failure.reason, failure.message, round_work.version, facts=failure.facts)
            return
        try:
            dependencies = self._hooks.round_dependencies(round_work, environment)
            request = execution_contract.RoundRequest(
                scope=scope, prompt=round_work.prompt, limits=dependencies.limits,
                work_ref=dependencies.work_ref, department_settings=round_work.settings,
            )
            self.start_execution(round_work, request, dependencies)
            result = await round_work.driver.result()
        except Exception as exc:
            # 步骤驱动没有开始或这一轮出错：依据是轮次开始时的运行状态
            failure = self.round_failure(exc, default="provider_error")
            self.end_run(round_work, failure.reason, failure.message, round_work.version, facts=failure.facts)
            return
        # 一轮工作的结果只剩这一轮写下的事件范围与停止原因（骨架与应用「执行契约」，#861）：
        # 有停止原因的是这个会话停下或失败，按原因暂停或结束运行
        if result.stop_reason is not None:
            self.end_run(round_work, result.stop_reason, result.message, result.version,
                         target=result.target, facts=list(result.facts) or None,
                         stalled_compaction=result.stalled_compaction)
            return
        current = self._hooks.project(run_id)
        if current.status in TERMINAL_STATUSES:
            return
        if result.submission is None:
            # 这一轮没有经提议方式交上东西（在安全节点停下，或只有文字回答）：按当时的运行状态收尾
            elapsed = self.elapsed_sec(run_id)
            minimal = self._writes.minimal(run_stream(run_id))
            if time_used_up(minimal, elapsed):
                self.end_run(round_work, TIME_BOUND, time_limit_message(minimal, elapsed), result.version)
            return
        # 一轮正常结束：问路由这一轮以什么结束，再经写入口提交（提案的取舍在应用一侧，工单 #861）
        try:
            self._hooks.apply_round_result(round_work, result, current)
        except Exception as exc:
            failure = self.round_failure(exc, default="host_commit_error")
            self.end_run(round_work, failure.reason, failure.message, None, facts=failure.facts)

    def round_failure(self, exc: Exception, *, default: str) -> RoundFailure:
        # 应用认得的异常由应用翻成停止原因；其余按执行失败或主机保存失败结束
        failure = self._hooks.round_failure(exc)
        if failure is not None:
            return failure
        return RoundFailure(default, f"{type(exc).__name__}: {exc}")

    def finish_round(self, round_work: RoundWork, started: float) -> None:
        # 一轮工作的结果写回（骨架与应用「薄驱动」第 4 条）：激活结束事件与这一轮的用量写进事实。
        # 这一轮的指导在这一轮正常结束时由应用在同一个事务里写已回答（部门指导「处理结果与来源」，工单 #1039）
        scope = round_work.scope

        def finish(transaction: Transaction) -> None:
            current = transaction.projection
            elapsed_ms = self.settle_run_segment(scope.run_id, scope.department)
            happened = transaction.events()
            # 这一轮结束时的已用量读最小投影（S1e 工单 #1015）：事项一级与会话一级的激活次数与
            # 模型步数都由投影折出来，不在这里从事件数一遍。会话的已用时间含当前这一段，
            # 投影要等这条事件写进去才结算，所以由驱动算好写进事件
            measured = transaction.minimal()
            session = measured.sessions.get(scope.session_id, SessionState())
            session_elapsed_ms = self.settle_session_segment(scope.run_id, scope.session_id, elapsed_ms)
            transaction.append(NewEvent(
                SkeletonEventType.ACTIVATION_FINISHED,
                actor="system",
                department=scope.department,
                parent_event_id=scope.parent_event_id,
                state_before=current.status,
                state_after=current.status,
                session_id=scope.session_id,
                payload={
                    "activation_id": scope.activation_id,
                    **scope.versions(),
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "elapsed_ms": elapsed_ms,
                    "activations": measured.used.activations,
                    "model_steps": measured.used.model_steps,
                    "session_elapsed_ms": session_elapsed_ms,
                    "session_activations": session.activations,
                    "session_model_steps": session.model_steps,
                    "stop_reason": current.stop_reason,
                },
            ))
            self._hooks.after_round_finished(transaction, round_work, happened)

        # 这一轮的事件都带它的派发编号：旧编号交回的结果只记录，不改变事项的状态
        self._hooks.transact_run(scope.run_id, finish, dispatch_number=scope.dispatch_number or None)

    # 事项结束：写停止原因、核对流版本 ------------------------------------------------------

    def end_run(self, round_work: RoundWork, reason: str, message: str, version: int | None,
                *, target: dict[str, Any] | None = None, facts: list[str] | None = None,
                stalled_compaction: bool = False) -> None:
        # 在一个事务中按停止原因暂停或结束运行；模型引用无法使用（provider_unavailable）与整理连续没有推进
        # 达到上限（compaction_failed，工单 #1238）时 run 进入待恢复。
        # version 是作出停止判断时 run 流的版本：同一事务中核对此后有没有用户的命令或输入写入；有写入、并且写入
        # 改变了这次激活的依据（输入或指导）时，停止判断已经过期，按安全节点停止处理，运行继续，由下一次激活处理
        # 新的输入或指导。运行时间用完不因此改变；已经结束（例如已经取消）的运行不再写入。
        # target 是这次失败对应的调用目标公开部分，写进待恢复的请求
        def end(transaction: Transaction) -> None:
            if version is not None and reason != TIME_BOUND and self.superseded(transaction, round_work, version):
                return
            if reason == "provider_unavailable" or (reason == "compaction_failed" and stalled_compaction):
                # 整理连续没有推进（模型管理「失败处理」最后一条）：停在这次整理之前，等用户决定换模型
                # 继续还是停止事项；已收下的交付与已完成的工作都留在投影里
                self._hooks.await_model(transaction, round_work, reason, message, target=target)
                return
            self.end(transaction, reason, message, facts=facts)

        self._hooks.transact_run(round_work.run_id, end)

    def superseded(self, transaction: Transaction, round_work: RoundWork, version: int) -> bool:
        # 停止判断过期：这次激活的工作期间有新的用户输入或指导到达，停止判断不再适用：
        # 这一轮按安全节点结束，运行继续，由下一次激活处理新的输入（工单 #964，循环结构「工作中途要求变化」「指导」）。
        # 输入到达不再结束部门当前这一轮：它作为通知在这个会话的下一步送达，部门接着工作
        projection = transaction.projection
        basis = round_work.scope.basis
        if projection.input_version != basis.input_version:
            return True
        # 新的指导在停止判断以后到达：同样过期，由下一次激活处理
        if not any(event.type in self._hooks.user_events() for event in transaction.events_after(version)):
            return False
        return self._hooks.guidance_version(projection, round_work.department) > basis.guidance_version

    def end(self, transaction: Transaction, reason: str, message: str,
            *, facts: list[str] | None = None) -> None:
        # 按定义中停止原因规定的方式暂停或结束运行；已经结束的运行不再写入。完成（放行或基线核验）只由接纳写入。
        # 暂停与失败同样带停止说明（message）：例如 workspace_unrepresentable 的说明列出相对路径。
        # facts 是暂停决定请求要带的事实引用（workspace_unrepresentable 为条目在工作区内的相对路径）
        outcome = self.stop_reason(transaction, reason).outcome
        if outcome == "paused":
            self.pause(transaction, reason, message, facts=facts)
        elif outcome == "failed":
            self.fail(transaction, reason, message)
        else:
            raise ValueError(f"stop reason {reason} ends a run as completed, which only an accepted final proposal records")

    def stop_reason(self, transaction: Transaction, reason: str):
        # 停止原因按这个事项冻结的形态的那份定义核对（工单 #1392）：路由自己的结束原因也在它那份清单里
        return self._hooks.definitions(transaction.projection.run_id).stop_reason(reason)

    def pause(self, transaction: Transaction, reason: str, message: str | None = None,
              *, facts: list[str] | None = None) -> None:
        projection = transaction.projection
        if projection.status in TERMINAL_STATUSES:
            return
        department = projection.active_department
        self.withdraw_decisions(transaction, reason)
        transaction.append(NewEvent(
            SkeletonEventType.RUN_PAUSED, actor="system", department=department,
            state_before=projection.status, state_after="paused", stop_reason=reason,
            error=message,
            provider=projection.provider, model=projection.model,
            payload={
                "stop_reason": reason,
                "human_action": self.stop_reason(transaction, reason).human_action,
                **({"message": message} if message else {}),
                "cycle_count": projection.cycle_count,
                "max_cycles": projection.max_cycles,
                "token_used": projection.token_used,
            },
        ))
        # 因不调用工具或工作区无法表示而暂停时由应用发出决定请求（D09，工单 #204）：阻塞整个 run，
        # 选项为「处理以后继续执行」与「停止事项」；哪些停止原因可以继续由定义与这一层决定
        self._hooks.resume_after_pause(transaction, reason, department, message, facts or [])
        transaction.on_commit(lambda: self._hooks.close_run(projection.run_id))

    def fail(self, transaction: Transaction, reason: str, message: str,
             *, input_save_failure: dict[str, str] | None = None) -> None:
        human = self.stop_reason(transaction, reason).human_action
        projection = transaction.projection
        if projection.status in TERMINAL_STATUSES:
            return
        department = projection.active_department
        self.withdraw_decisions(transaction, reason)
        source_event = transaction.append(NewEvent(
            SkeletonEventType.RUN_FAILED, actor="system", department=department,
            state_before=projection.status, state_after="failed", stop_reason=reason, error=message,
            provider=projection.provider, model=projection.model,
            payload={"stop_reason": reason, "human_action": human, "message": message,
                     **({"input_save_failure": input_save_failure} if input_save_failure is not None else {})},
        ))[0]
        transaction.on_commit(lambda: self._hooks.close_run(projection.run_id))
        self._hooks.record_lesson_candidate(transaction, reason, source_event, projection)

    def withdraw_decisions(self, transaction: Transaction, reason: str) -> None:
        # 运行结束：撤销未回答的决定请求，reason 是结束运行的停止原因
        projection = transaction.projection
        for decision in list(transaction.decisions.values()):
            if decision.status != "open":
                continue
            transaction.append(NewEvent(
                SkeletonEventType.DECISION_WITHDRAWN, actor="system",
                department=decision.request["department"],
                parent_event_id=decision.decision_id, state_before=projection.status,
                state_after=projection.status,
                payload={"decision_id": decision.decision_id, "reason": reason},
            ))

    # 安全节点 ---------------------------------------------------------------------------

    def at_safe_node(self, round_work: RoundWork) -> execution_contract.Judgment:
        # 安全节点：激活没有中止、运行时间没有用完时先分派新输入，再作停止判断；回答是否继续与判断时的流版本
        def judge(transaction: Transaction) -> execution_contract.Judgment:
            projection = transaction.projection
            if not (round_work.stop_flag.is_set()
                    or self._hooks.aborted(round_work.run_id)
                    or (round_work.deadline is not None and time.monotonic() >= round_work.deadline)
                    or time_used_up(transaction.minimal(), self.elapsed_sec(round_work.run_id))):
                projection = self._hooks.assign_new_inputs(transaction)
            decisions = list(transaction.decisions.values())
            stop = self.stop_requested(round_work, projection, transaction.minimal(), decisions)
            # 别的会话已经写下待恢复的决定请求：这个会话照常停下（事项的状态不变）；
            # 它自己也被挡住时（这次的模型请求发不出去），它要写下自己的那一条，各写明自己的部门、模型与问题
            blocked = self._hooks.blocked_by_other_session(decisions, round_work.department)
            return execution_contract.Judgment(not stop, projection.stream_version, blocked)

        return self._hooks.transact_run(round_work.run_id, judge)

    def stop_requested(self, round_work: RoundWork, projection: Any, minimal: MinimalProjection,
                       decisions: Iterable[Any]) -> bool:
        # 停止判断：这个会话自己的停止开关、事项被中止、运行时间用完、终态、有未回答的阻塞 run 的决定请求；
        # 只读取，不写入。会话自己的开关与事项的开关都看：停下一个会话只停这个会话，用户取消事项时全部会话都停。
        # 有效合同、指导与用户输入变了都不再停止：它们作为通知送达，部门接着工作，一轮工作因此不结束。
        # 输入仍然分派给产品部门处理：产品在自己的那一轮处理它
        return (round_work.stop_flag.is_set()
                or self._hooks.aborted(round_work.run_id)
                or (round_work.deadline is not None and time.monotonic() >= round_work.deadline)
                or time_used_up(minimal, self.elapsed_sec(round_work.run_id))
                or projection.status in TERMINAL_STATUSES or self._hooks.blocks_run(decisions))

    def safe_node(self, round_work: RoundWork, declared: int) -> execution_contract.SafeNode:
        # 交给执行实现的安全节点按它声明的契约版本给：当前版拿到设计说明写的五样；
        # 声明上一版（第二版）的实现还会问按部门取模型与提示词，那一版留一版
        if declared == execution_contract.PREVIOUS_VERSION:
            return _SafeNodeV2(self, round_work)
        return _SafeNode(self, round_work)

    async def wait_at_safe_node(self, round_work: RoundWork, seconds: float) -> execution_contract.Judgment:
        # 重试等待：在安全节点等待至多 seconds 秒；新输入、指导或取消到达时由 wake 唤醒，运行时间用完时
        # 结束等待，醒来以后回到安全节点判断。唤醒在判断之前登记：判断之后才提交的改变，提交方调用 wake 时
        # 一定看到这次登记。重试退避不在不计入运行时间的等待清单里，这一段照常计入，段计时不停表，
        # 否则 min(remaining, time_left) 的等待上限永远不会缩短，运行时间用完无法在等待期间结束运行
        loop = asyncio.get_running_loop()
        deadline = loop.time() + seconds
        try:
            while True:
                changed = asyncio.Event()
                round_work.wakeup = (loop, changed)
                judgment = self.at_safe_node(round_work)
                if not judgment.proceed:
                    return judgment
                left = self.time_left(round_work.run_id)
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return judgment
                try:
                    await asyncio.wait_for(changed.wait(), max(0.0, min(remaining, left)))
                except TimeoutError:
                    pass
        finally:
            round_work.wakeup = None

    # 循环与调度 -------------------------------------------------------------------------

    async def run_until_stop(self, run_id: str) -> Any:
        # 运行到终态，或者到 run 被未回答的决定请求阻塞、等待用户回答为止。
        # 一次运行期间的模型调用复用同一组连接，连接只在这个事件循环中使用。
        # 同时运行：等待工作的部门各开始一轮工作，各自一个会话，这个循环等全部会话结束或事项到终态。
        # 等会话的同时也等唤醒：新输入、指导与取消提交以后，即使没有会话结束，这个循环也醒过来重新找一遍
        # 可以开始的部门；部门的判断本身不变。停下其余会话只停这些会话，不改变事项的状态：
        # 停下以后重新读取再交回，交回的投影里被停下的会话已经收尾。
        # 事项冻结的形态不在发布里时：这个 run 停在原处，不写事件、不换一份定义顶替；
        # 换回带那一份形态的发布以后从停住的地方接着跑
        if not self._hooks.item_form_available(run_id):
            return self._hooks.project(run_id)
        connections = self._hooks.new_connections()
        tasks: dict[str, asyncio.Task[Any]] = {}
        loop = asyncio.get_running_loop()
        changed = asyncio.Event()
        # 唤醒在寻找部门之前登记：登记之后提交的改变，提交方调用 wake 时一定看到这次登记
        self._run_wakeups[run_id] = (loop, changed)
        try:
            while True:
                changed.clear()
                snapshot = self._hooks.read_run(run_id)
                projection = snapshot.projection
                if projection.status in TERMINAL_STATUSES:
                    await self.stop_sessions(run_id, tasks)
                    return self._hooks.project(run_id)
                if self._hooks.aborted(run_id):
                    await self.stop_sessions(run_id, tasks)
                    return await asyncio.to_thread(self._hooks.settled, run_id)
                if self._hooks.blocks_run(snapshot.decisions.values()):
                    await self.stop_sessions(run_id, tasks)
                    return self._hooks.project(run_id)
                for department in self.ready_departments(run_id):
                    task = tasks.get(department)
                    if task is not None and not task.done():
                        continue
                    tasks[department] = loop.create_task(
                        self.activate_department(run_id, department, connections))
                pending = [task for task in tasks.values() if not task.done()]
                if not pending:
                    # 没有部门在工作，也没有可以开始的部门：没有新的工作
                    return await self.no_new_work(run_id)
                waiter = loop.create_task(changed.wait())
                try:
                    done, _pending = await asyncio.wait(
                        [*pending, waiter], return_when=asyncio.FIRST_COMPLETED)
                finally:
                    waiter.cancel()
                    await asyncio.gather(waiter, return_exceptions=True)
                for task in done:
                    if task is not waiter:
                        task.result()
        finally:
            self._run_wakeups.pop(run_id, None)
            await self.stop_sessions(run_id, tasks)
            # run 进入终态时结束的试用会话在这里补写结束事件：结束本身在应用的收尾里做完，
            # 那时在终态事件的提交之后的效果里，不能再写事件；这里已经在事务之外，写进来的事件位置接在终态事件后面
            self._hooks.flush_trial_events(run_id)
            # 这个 run 的 MCP 会话随运行一起关闭：到达终态、被决定请求阻塞、中止或没有新工作，
            # 运行都从这一条退出；会话表清空，继续同一个 run 时按同一台服务器重新建立
            await self._hooks.close_mcp_sessions(run_id)
            await connections.aclose()

    def ready_departments(self, run_id: str) -> list[str]:
        # 现在可以开始一轮工作的部门：等待工作、关注的成果有了新东西的那些。判断归路由实现
        projection = self._hooks.project(run_id)
        return self._hooks.routing(run_id).ready_departments(
            projection, waiting=self._hooks.waiting_departments(run_id))

    async def stop_sessions(self, run_id: str, tasks: dict[str, asyncio.Task[Any]]) -> None:
        # 事项到终态或被未回答的决定请求阻塞：其余会话停止并收尾。
        # 只停这些会话，不改变事项的状态：事项自己的开关只有用户取消才打开
        pending = [task for task in tasks.values() if not task.done()]
        if not pending:
            return
        for round_work in list(self.activations(run_id).values()):
            try:
                self.cancel_round(round_work)
            except Exception:
                pass
        await asyncio.gather(*pending, return_exceptions=True)

    async def no_new_work(self, run_id: str) -> Any:
        # 没有部门可以开始一轮工作：事项以什么结束由路由判断，薄驱动只把它的判断写成停止
        def end(transaction: Transaction) -> None:
            judgment = self._hooks.routing(run_id).item_end(transaction.projection)
            if judgment is None:
                return
            self.fail(transaction, judgment.stop_reason, judgment.message)

        self._hooks.transact_run(run_id, end)
        return await asyncio.to_thread(self._hooks.settled, run_id)

    def wake(self, run_id: str, *, restart: bool = False) -> None:
        # 在安全节点等待重试的激活立即回到安全节点判断；在改变提交以后调用。
        # 同时运行：这个 run 的每一个会话都醒过来
        for round_work in list(self.activations(run_id).values()):
            wakeup = round_work.wakeup
            if wakeup is not None:
                loop, changed = wakeup
                loop.call_soon_threadsafe(changed.set)
        if not restart:
            return
        # 运行到停止的循环也在等：新输入、指导或取消可能在没有会话运行时带来可以开始的部门，由它醒来重新找一遍。
        # 部门提交提案时不叫醒它：那时正在工作的部门还没结束这一轮，这时重新判断会把别的工作切在半途
        waiting = self._run_wakeups.get(run_id)
        if waiting is not None:
            loop, changed = waiting
            loop.call_soon_threadsafe(changed.set)


class _SafeNode:
    # 薄驱动为一次激活实现的安全节点接口（执行契约第三版）。接口由契约定义、步骤驱动在安全节点上调用，
    # 这里实现并在开始一轮工作时交给它（依赖倒置）：每一步先经这里问薄驱动继续还是停止。
    # 第三版只剩设计说明写的五样：按部门取模型与提示词不在其中，它们随开始一轮工作的请求一起交给执行实现
    def __init__(self, driver: ThinDriver, round_work: RoundWork) -> None:
        self._driver = driver
        self._round_work = round_work

    def proceed(self) -> execution_contract.Judgment:
        return self._driver.at_safe_node(self._round_work)

    def settle(self, transaction: Transaction) -> Any:
        return self._driver._hooks.assign_new_inputs(transaction)

    async def wait(self, seconds: float) -> execution_contract.Judgment:
        return await self._driver.wait_at_safe_node(self._round_work, seconds)

    def end(self, transaction: Transaction, reason: str, message: str) -> None:
        self._driver.end(transaction, reason, message)

    async def ask(self, scope: Any, call: dict[str, Any]) -> tuple[bool, Any, str | None, str | None, int]:
        return await self._driver._hooks.execute_ask(self._round_work, scope, call)


class _SafeNodeV2(_SafeNode):
    # 第二版的安全节点：按第二版写的执行实现还会问按部门取模型与提示词。
    # 这两个方法已经从安全节点移出，只给声明第二版的实现留一版；值从开始一轮工作时交进来的那份来源读，
    # 薄驱动不自己查。一版之后连同本类一起去掉
    def __init__(self, driver: ThinDriver, round_work: RoundWork) -> None:
        super().__init__(driver, round_work)
        self._settings = round_work.settings

    def department_selection(self, department: str) -> Any | None:
        return self._settings.department_selection(department)

    def department_prompt(self, department: str) -> Any:
        return self._settings.department_prompt(department)
