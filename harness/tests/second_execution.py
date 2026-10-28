# 第二种执行实现（工单 #979；只在测试里用，产品代码不导入它）。
#
# 执行契约第二版（`harness/execution_contract.py`；骨架与应用设计说明第 5.3 节；总图第四节「执行」缝）的
# 第二种实现。形状与真实现（`engine.py` 的 `StepDriver`）不同，行为最小：
#
# - 每一步先经安全节点问薄驱动继续或停止（契约里唯一一处下层调上层的接口）。
# - 它不调模型、不装配请求、不执行工具：只经写入口记一条「这一步」的事件。
# - 按契约交回一轮工作的结果 `RoundResult`：这一轮写下的事件范围与停止原因（上限用封闭清单里的编号）。
#   这一轮算不算结束、结束成什么由路由按事件判断，这里不写「提交了成果」这类种类。
#
# 它证明的是缝：换成这样一个实现，薄驱动照契约调 `start`、`cancel` 与 `result`，不认实现的名字与内部形状。

from __future__ import annotations

import asyncio
from dataclasses import asdict
from threading import Event
from typing import Any

from harness import execution_contract
from harness.event_store import run_stream
from harness.models import Event, EventType
from harness.write_path import NewEvent


class SecondExecution:
    # 执行契约第二版的第二种实现；薄驱动在开始一轮工作之前核对下面这一版
    CONTRACT_VERSION = execution_contract.CURRENT_VERSION

    @classmethod
    def start(cls, request: execution_contract.RoundRequest, *, nodes: execution_contract.SafeNode,
              cancelled: Event, **dependencies: Any) -> "SecondExecution":
        # 在当前事件循环中开始这次激活；写入口与工件库按实现自己的需要取用，不属于契约
        driver = cls(request, nodes=nodes, cancelled=cancelled,
                     writes=dependencies.get("writes"), artifacts=dependencies.get("artifacts"))
        driver._task = asyncio.get_running_loop().create_task(driver._run())
        return driver

    def __init__(self, request: execution_contract.RoundRequest, *, nodes: execution_contract.SafeNode,
                 cancelled: Event, writes: Any = None, artifacts: Any = None) -> None:
        self._request = request
        self._nodes = nodes
        self._cancelled = cancelled
        self._writes = writes
        self._artifacts = artifacts
        self._cancel_requested = False
        self._steps = 0
        self._task: asyncio.Task[execution_contract.RoundResult] | None = None

    def cancel(self) -> None:
        # 取消这一轮：之后的核对都得到停止。这一版没有在进行的动作与调用尝试，只记下取消
        self._cancel_requested = True

    async def result(self) -> execution_contract.RoundResult:
        assert self._task is not None, "start() creates the task"
        return await self._task

    async def _run(self) -> execution_contract.RoundResult:
        written: list[Event] = []
        version = 0
        while True:
            # 每一步先问安全节点，再决定做不做这一步
            judgment = self._nodes.proceed()
            version = judgment.version
            if self._cancel_requested or self._cancelled.is_set() or not judgment.proceed:
                # 在安全节点停下：没有停止原因，由薄驱动按当时的运行状态收尾
                return execution_contract.RoundResult(events=tuple(written), version=version)
            if self._steps >= self._request.limits.max_model_steps:
                return execution_contract.RoundResult(
                    events=tuple(written), version=version, stop_reason="model_steps_exhausted",
                    message="this round reached its model step limit")
            self._steps += 1
            written.extend(self._record_step())

    def _record_step(self) -> list[Event]:
        # 经写入口记一条「这一步」的事件：这一版只记录，不调模型。事件的载荷与记录接口写的同一种：
        # 这一步的工件引用加上激活采用的版本与工作依据
        scope = self._request.scope
        text = f"第二步执行实现：第 {self._steps} 步（只记录，不调模型）"
        ref = self._artifacts.put(scope.run_id, "second_execution_step", text, media_type="text/plain")

        def append(transaction: Any) -> list[Event]:
            status = transaction.projection.status
            return transaction.append(NewEvent(
                EventType.DEPARTMENT_INPUT,
                state_before=status, state_after=status,
                actor=f"department:{scope.department}", department=scope.department,
                parent_event_id=scope.parent_event_id, session_id=scope.session_id,
                artifact_hashes=[ref.content_hash],
                payload={"activation_id": scope.activation_id, "step_id": self._steps,
                         "input_ref": asdict(ref), **scope.versions(), **scope.work_basis()},
            ))

        return list(self._writes.transact(run_stream(scope.run_id), append))
