# 事件日志里的信号（工单 #1431、#1621）：同时进行的两件事谁先谁后，由事件或信号决定，不用时长去赌
# （测试分层设计说明「测试的写法」第 7 条）。假模型的某次调用可以标上「先等一个信号」，信号来自本次运行
# 提交的事件；等待的上限只用来防止测试一直等（与 #1248 同口径，见 harness/tests/wait_limits.py），
# 到点以写明在等什么的失败结束。

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping

from harness.adapters.fake import FakeAdapter
from harness.models import Event
from harness.providers.call import ModelCall, ModelResponse, ModelStreamEvent
from harness.runtime import LoopSystem
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC


class Signals:
    """一组按名字取用的信号：订阅提交的事件，等到某个信号的那次模型调用被放行（工单 #1431）。

    订阅的一方在提交事件的一方所在的线程里认出要发哪个信号（committed 里按事件种类调 fire），
    等的一方在事件循环里等；信号先到也不丢，后来的 wait 立即返回。描述是等不到时写进失败里的话。
    """

    def __init__(self, descriptions: Mapping[str, str] | None = None) -> None:
        self._descriptions = dict(descriptions or {})
        self._fired: set[str] = set()
        self._waiters: dict[str, asyncio.Event] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self.failures: list[str] = []

    def watch(self, system: LoopSystem, committed: Callable[[Event], None]) -> None:
        # 一批事件提交以后逐条交给 committed：订阅方在提交这条事件的一方所在的线程里被调用
        system.store.subscribe(lambda events: [committed(event) for event in events])

    def fire(self, name: str) -> None:
        self._fired.add(name)
        waiter = self._waiters.get(name)
        if waiter is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if self._loop is not None and running is not self._loop:
            self._loop.call_soon_threadsafe(waiter.set)
        else:
            waiter.set()

    async def wait(self, name: str) -> None:
        if name in self._fired:
            return
        self._loop = asyncio.get_running_loop()
        waiter = self._waiters.setdefault(name, asyncio.Event())
        if name in self._fired:
            return
        try:
            await asyncio.wait_for(waiter.wait(), WAIT_FOR_HOST_WORK_SEC)
        except TimeoutError:
            message = f"等不到信号「{name}」：{self._descriptions.get(name, name)}"
            self.failures.append(message)
            raise AssertionError(message) from None


class SignallingAdapter(FakeAdapter):
    """按事件日志里的信号放行的假模型（工单 #1431）。

    waits 的键是（部门，这个部门第几次模型调用，从 0 起）：这一次调用先等键里的信号再交出回答。
    按部门数调用次数，询问分支的调用也计入；只标主线会话的调用时不要用带询问分支的脚本。
    信号由 watch 传进来的 committed 发；等不到信号时记在 wait_failures，用例据此以明确的失败结束。
    """

    def __init__(self, script, *, waits: dict[tuple[str, int], str] | None = None,
                 signals: Signals | None = None, **kwargs) -> None:
        super().__init__(script, **kwargs)
        self._waits = dict(waits or {})
        self._calls: dict[str, int] = {}
        self.signals = signals if signals is not None else Signals()

    def watch(self, system: LoopSystem, committed: Callable[[Event], None]) -> None:
        self.signals.watch(system, committed)

    @property
    def wait_failures(self) -> list[str]:
        return self.signals.failures

    async def stream(self, call: ModelCall) -> AsyncIterator[ModelStreamEvent | ModelResponse]:
        index = self._calls.get(call.department, 0)
        self._calls[call.department] = index + 1
        signal = self._waits.get((call.department, index))
        if signal is not None:
            await self.signals.wait(signal)
        async for item in super().stream(call):
            yield item
