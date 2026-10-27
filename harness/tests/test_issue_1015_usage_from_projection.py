# 工单 #1015（S1e）：用量只在最小投影里算一次，驱动计时与恢复页读数改读它。
#
# 守 R1（第三环的不变式）与 R2（第二环的合同）：
# - R1：中断的那一轮用掉的步数不给回来——一个会话在一轮中间中断（有「模型请求」事件、没有一轮结束事件），
#   重新启动以后它剩下的步数与中断前一致，不多给；因此「一定会停」在重启以后仍然成立。
# - R2：恢复页（run.recovery）的激活次数、模型步数与执行权，与同一组事件折叠出的最小投影一致。
#
# 读事件日志、写数据目录、用一次部门激活，属于模块层（test-pyramid 第 2 节）。

import asyncio
import json
from typing import Any

import pytest

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.app.project_queries import RunRecovery
from harness.engine import StepLimits
from harness.minimal_projection import fold_events
from harness.models import EventType
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.tests.helpers import after_event

# 这一轮的上限：中断前用掉几个步数，重启以后只剩这么多个可以用
MAX_MODEL_STEPS = 3
# 中断点：第几个模型请求提交以后让这一轮再也写不下结束事件
INTERRUPT_AT = 2


def _call(identity: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"id": identity, "call_id": identity, "type": "function_call", "name": name,
            "arguments": json.dumps(arguments)}


def _list_files(request: Any) -> ModelResponse:
    # 只读工作区的一步：不提交提案，这一轮可以一直走下去，直到步数上限
    identity = f"list-{request.activation_id}-{request.step_id}"
    return ModelResponse(output=[_call(identity, "list_files", {})])


def _system(data_dir: Any, *, resume_on_startup: bool = True) -> LoopSystem:
    adapter = FakeAdapter({"product": [_list_files] * MAX_MODEL_STEPS})
    return LoopSystem.for_testing(data_dir, adapter, step_limits=StepLimits(max_model_steps=MAX_MODEL_STEPS),
                                  resume_on_startup=resume_on_startup)


def _product_session(system: LoopSystem, run_id: str) -> str:
    return system.project(run_id).sessions["product"].session_id


def _interrupted(data_dir: Any) -> tuple[LoopSystem, str, str]:
    # 一轮工作在中途中断：第 INTERRUPT_AT 个模型请求提交以后，这一轮再也写不下任何事件，
    # 这一轮因此没有结束事件。留下的事实与进程在一轮中间死掉相同：
    # 有「模型请求」事件、没有一轮结束事件
    system = _system(data_dir)
    run_id = system.create_run("build echo")
    session_id = _product_session(system, run_id)
    seen = {"requests": 0}

    def dead(*_: Any, **__: Any) -> Any:
        raise RuntimeError("这一轮写不下任何事件了：进程在这一点上死掉")

    def cut_the_round_here(event: Any) -> None:
        if event.session_id != session_id:
            return
        seen["requests"] += 1
        if seen["requests"] >= INTERRUPT_AT:
            system.writes.transact = dead

    after_event(system, EventType.MODEL_REQUESTED, cut_the_round_here)
    with pytest.raises(RuntimeError):
        asyncio.run(system.orchestrator.activate_once(run_id))
    return system, run_id, session_id


def test_a_round_interrupted_in_the_middle_keeps_its_remaining_steps(tmp_path):
    system, run_id, session_id = _interrupted(tmp_path / "data")
    try:
        before = system.store.list_events(run_id)
        requested = [event for event in before
                     if event.type == EventType.MODEL_REQUESTED and event.session_id == session_id]
        assert len(requested) == INTERRUPT_AT, len(requested)
        # 中断的那一轮没有结束事件：它的时间与步数都还没有结算
        assert not [event for event in before if event.type == EventType.ACTIVATION_FINISHED]
        # 中断前这个会话剩下的步数：上限减去这一轮已经用掉的步数（读最小投影）
        session = fold_events(before).sessions[session_id]
        remaining_before = MAX_MODEL_STEPS - (session.model_steps - session.settled_steps)
        assert remaining_before == MAX_MODEL_STEPS - INTERRUPT_AT, remaining_before
    finally:
        system.close()

    # 重新启动：同一份数据目录上开一个新的控制核心，这一轮接着走
    restarted = _system(tmp_path / "data", resume_on_startup=False)
    try:
        asyncio.run(restarted.orchestrator.activate_once(run_id))
        after = restarted.store.list_events(run_id)
        requested_after = [event for event in after
                           if event.type == EventType.MODEL_REQUESTED and event.session_id == session_id]
        # 这一轮一共只用掉上限那么多步：重启以后剩下的步数与中断前一致，没有多给
        assert len(requested_after) == MAX_MODEL_STEPS, len(requested_after)
    finally:
        restarted.close()


def test_the_recovery_page_reads_its_numbers_from_the_minimal_projection(tmp_path):
    # 先中断一轮，再重新打开数据目录并且走启动恢复：这一轮会被重新领取执行权、接着走，
    # 因此恢复页上的执行权与已用量都不是零
    data_dir = tmp_path / "data"
    system, run_id, _session_id = _interrupted(data_dir)
    system.close()

    restarted = _system(data_dir, resume_on_startup=True)
    try:
        asyncio.run(restarted.orchestrator.activate_once(run_id))
        events = restarted.store.list_events(run_id)
        minimal = fold_events(events)
        recovery = Application(restarted).query("run.recovery", RunRecovery(run_id=run_id)).data

        # 激活次数与模型步数：与同一组事件折叠出的最小投影一致（设计说明第 4 节第 4 条）
        assert recovery.limits.activations == minimal.used.activations, recovery.limits.activations
        assert recovery.limits.model_steps == minimal.used.model_steps, recovery.limits.model_steps
        assert recovery.limits.activations >= 1 and recovery.limits.model_steps >= 1

        # 执行权：编号是投影里的执行权编号；取得的时间来自记下这一次取得的那个事件
        assert recovery.owner is not None, "重新领取执行权以后恢复页上没有执行者"
        assert recovery.owner.epoch == minimal.execution_right, (recovery.owner.epoch, minimal.execution_right)
        resumed = [event for event in events
                   if event.type == EventType.RUN_RESUMED
                   and int((event.payload or {}).get("acquired_epoch") or 0) == minimal.execution_right]
        assert len(resumed) == 1
        assert recovery.owner.since == resumed[0].created_at

        # 重试次数不是上限、不进最小投影：仍按事件数（这里没有重试）
        assert recovery.limits.retries == 0
    finally:
        restarted.close()
