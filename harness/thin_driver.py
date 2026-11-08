# 薄驱动（可信内核）：只连接。循环与调度问路由该谁开始一轮工作、问边界能不能开始、等待与唤醒；
# 计时读最小投影里的已结算量加上当前这一段的起点（骨架与应用 docs/design/skeleton-and-application.md「最小投影」的
# 「驱动的计时读投影」）；安全节点回答步骤驱动继续还是停止。
# 要做的事经下面的钩子协议交给应用：开始一轮工作、结算、结束事项、询问分支都在应用一侧的流程编排里，
# 薄驱动不导入它，构造时由它把自己交进来（骨架与应用 docs/design/skeleton-and-application.md「薄驱动」）。
#
# 本模块只导入内核模块、契约模块、标准库与 pydantic：导入由 harness/tests/test_thin_driver_imports.py 核对；
# 部门标识与成果种类不在这个文件里：检索由 harness/tests/test_thin_driver_names.py 覆盖。
#
# 薄驱动自己只读最小投影；运行视图、路由实现、定义与应用的会话状态是应用的东西，经钩子取得。
# 部门与成果的名称一律从定义取。

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterable
from typing import Any, Protocol

from . import execution_contract
from .bounds import time_left_sec, time_used_up
from .event_store import run_stream
from .kernel_events import TERMINAL_STATUSES
from .minimal_projection import MinimalProjection, SessionState
from .write_path import Transaction, WritePath


class DriverHooks(Protocol):
    # 薄驱动交给应用做的事：应用一侧的流程编排实现这个协议，构造薄驱动时把自己交进来。
    # 薄驱动只读最小投影，运行视图、路由与定义经这些方法取得；写入仍经薄驱动交给写入口，
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

    # 取消与结算
    def aborted(self, run_id: str) -> bool:
        # 事项自己被中止（用户取消）：之后的核对都得到停止
        ...

    def settled(self, run_id: str) -> Any:
        # 激活与运行循环结束时交回的运行状态：等正在进行的取消结束，必要时写入取消
        ...

    def activations(self, run_id: str) -> dict[str, Any]:
        # 这个 run 正在进行的激活，按部门：停会话与唤醒都要用
        ...

    def cancel_activation(self, activation: Any) -> None:
        # 停下这个会话：打开它自己的停止开关，取消正在进行的步骤，并唤醒在安全节点等待的那一轮
        ...

    # 开始一轮工作与收尾
    async def activate_department(self, run_id: str, department: str, connections: Any) -> Any:
        # 准备并跑这个部门的一轮工作，交回停止时的运行视图
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

    # 安全节点上的动作
    def transact_run(self, run_id: str, decide: Callable[[Transaction], Any]) -> Any:
        # 在这个 run 的事件流上读、判断、写入一个事务（应用补上按事项定义核对的选项）
        ...

    def assign_new_inputs(self, transaction: Transaction) -> Any:
        # 在调用方的事务中分派新输入，交回事务中当前的运行视图
        ...

    def fail(self, transaction: Transaction, reason: str, message: str) -> None:
        # 以停止原因结束运行：写失败事件、撤销待回答的决定请求
        ...

    def end(self, transaction: Transaction, reason: str, message: str) -> None:
        # 按定义中停止原因规定的方式暂停或结束运行
        ...

    async def execute_ask(self, activation: Any, scope: Any, call: dict[str, Any]) -> tuple[
            bool, Any, str | None, str | None, int]:
        # 询问分支由应用跑完一轮工作，交回 (ok, output, error, new_contract_hash, branch_steps)
        ...

    def blocks_run(self, decisions: Iterable[Any]) -> bool:
        # 有未回答的、阻塞 run 的决定请求
        ...

    def blocked_by_other_session(self, decisions: Iterable[Any], department: str) -> bool:
        # 别的会话已经写下待恢复的决定请求
        ...


class ThinDriver:
    # 薄驱动：循环、调度、计时与安全节点。它只经钩子协议与应用说话，写入经写入口，
    # 边界的核对与最小投影从内核模块取。
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
        active = self._hooks.activations(run_id)
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

    # 安全节点 ---------------------------------------------------------------------------

    def at_safe_node(self, activation: Any) -> execution_contract.Judgment:
        # 安全节点：激活没有中止、运行时间没有用完时先分派新输入，再作停止判断；回答是否继续与判断时的流版本
        def judge(transaction: Transaction) -> execution_contract.Judgment:
            projection = transaction.projection
            if not (activation.stop_flag.is_set()
                    or self._hooks.aborted(activation.run_id)
                    or (activation.deadline is not None and time.monotonic() >= activation.deadline)
                    or time_used_up(transaction.minimal(), self.elapsed_sec(activation.run_id))):
                projection = self._hooks.assign_new_inputs(transaction)
            decisions = list(transaction.decisions.values())
            stop = self.stop_requested(activation, projection, transaction.minimal(), decisions)
            # 别的会话已经写下待恢复的决定请求：这个会话照常停下（事项的状态不变）；
            # 它自己也被挡住时（这次的模型请求发不出去），它要写下自己的那一条，各写明自己的部门、模型与问题
            blocked = self._hooks.blocked_by_other_session(decisions, activation.department)
            return execution_contract.Judgment(not stop, projection.stream_version, blocked)

        return self._hooks.transact_run(activation.run_id, judge)

    def stop_requested(self, activation: Any, projection: Any, minimal: MinimalProjection,
                       decisions: Iterable[Any]) -> bool:
        # 停止判断：这个会话自己的停止开关、事项被中止、运行时间用完、终态、有未回答的阻塞 run 的决定请求；
        # 只读取，不写入。会话自己的开关与事项的开关都看：停下一个会话只停这个会话，用户取消事项时全部会话都停。
        # 有效合同、指导与用户输入变了都不再停止：它们作为通知送达，部门接着工作，一轮工作因此不结束。
        # 输入仍然分派给产品部门处理：产品在自己的那一轮处理它
        return (activation.stop_flag.is_set()
                or self._hooks.aborted(activation.run_id)
                or (activation.deadline is not None and time.monotonic() >= activation.deadline)
                or time_used_up(minimal, self.elapsed_sec(activation.run_id))
                or projection.status in TERMINAL_STATUSES or self._hooks.blocks_run(decisions))

    def safe_node(self, activation: Any, declared: int) -> execution_contract.SafeNode:
        # 交给执行实现的安全节点按它声明的契约版本给：当前版拿到设计说明写的五样；
        # 声明上一版（第二版）的实现还会问按部门取模型与提示词，那一版留一版
        if declared == execution_contract.PREVIOUS_VERSION:
            return _SafeNodeV2(self, activation)
        return _SafeNode(self, activation)

    async def wait_at_safe_node(self, activation: Any, seconds: float) -> execution_contract.Judgment:
        # 重试等待：在安全节点等待至多 seconds 秒；新输入、指导或取消到达时由 wake 唤醒，运行时间用完时
        # 结束等待，醒来以后回到安全节点判断。唤醒在判断之前登记：判断之后才提交的改变，提交方调用 wake 时
        # 一定看到这次登记。重试退避不在不计入运行时间的等待清单里，这一段照常计入，段计时不停表，
        # 否则 min(remaining, time_left) 的等待上限永远不会缩短，运行时间用完无法在等待期间结束运行
        loop = asyncio.get_running_loop()
        deadline = loop.time() + seconds
        try:
            while True:
                changed = asyncio.Event()
                activation.wakeup = (loop, changed)
                judgment = self.at_safe_node(activation)
                if not judgment.proceed:
                    return judgment
                left = self.time_left(activation.run_id)
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return judgment
                try:
                    await asyncio.wait_for(changed.wait(), max(0.0, min(remaining, left)))
                except TimeoutError:
                    pass
        finally:
            activation.wakeup = None

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
                        self._hooks.activate_department(run_id, department, connections))
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
        for activation in list(self._hooks.activations(run_id).values()):
            try:
                self._hooks.cancel_activation(activation)
            except Exception:
                pass
        await asyncio.gather(*pending, return_exceptions=True)

    async def no_new_work(self, run_id: str) -> Any:
        # 没有部门可以开始一轮工作：事项以什么结束由路由判断，薄驱动只把它的判断写成停止
        def end(transaction: Transaction) -> None:
            judgment = self._hooks.routing(run_id).item_end(transaction.projection)
            if judgment is None:
                return
            self._hooks.fail(transaction, judgment.stop_reason, judgment.message)

        self._hooks.transact_run(run_id, end)
        return await asyncio.to_thread(self._hooks.settled, run_id)

    def wake(self, run_id: str, *, restart: bool = False) -> None:
        # 在安全节点等待重试的激活立即回到安全节点判断；在改变提交以后调用。
        # 同时运行：这个 run 的每一个会话都醒过来
        for activation in list(self._hooks.activations(run_id).values()):
            wakeup = activation.wakeup
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
    def __init__(self, driver: ThinDriver, activation: Any) -> None:
        self._driver = driver
        self._activation = activation

    def proceed(self) -> execution_contract.Judgment:
        return self._driver.at_safe_node(self._activation)

    def settle(self, transaction: Transaction) -> Any:
        return self._driver._hooks.assign_new_inputs(transaction)

    async def wait(self, seconds: float) -> execution_contract.Judgment:
        return await self._driver.wait_at_safe_node(self._activation, seconds)

    def end(self, transaction: Transaction, reason: str, message: str) -> None:
        self._driver._hooks.end(transaction, reason, message)

    async def ask(self, scope: Any, call: dict[str, Any]) -> tuple[bool, Any, str | None, str | None, int]:
        return await self._driver._hooks.execute_ask(self._activation, scope, call)


class _SafeNodeV2(_SafeNode):
    # 第二版的安全节点：按第二版写的执行实现还会问按部门取模型与提示词。
    # 这两个方法已经从安全节点移出，只给声明第二版的实现留一版；值从开始一轮工作时交进来的那份来源读，
    # 薄驱动不自己查。一版之后连同本类一起去掉
    def __init__(self, driver: ThinDriver, activation: Any) -> None:
        super().__init__(driver, activation)
        self._settings = activation.settings

    def department_selection(self, department: str) -> Any | None:
        return self._settings.department_selection(department)

    def department_prompt(self, department: str) -> Any:
        return self._settings.department_prompt(department)
