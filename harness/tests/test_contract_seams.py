# 执行契约与装配契约的接缝（工单 #826；骨架与应用设计说明第 5.2、5.3、5.4 节；总图第四节「执行」「装配」缝）：
# 路由的工作引用从开始一轮工作的请求原样到达装配的输入；版本不被薄驱动接受时这一轮不开始、说明写明原因。
# 守的是 R2（各缝的交换字段与版本）与 R3（阶段一：一轮工作的每一步仍先经安全节点，工作引用原样交给装配）。

from __future__ import annotations

import asyncio
from threading import Event

from harness import assembly_contract, execution_contract
from harness.adapters.fake import FakeAdapter
from harness.adjudication import WorkBasis
from harness.assembly import ContextAssembly
from harness.tests.helpers import work_basis
from harness.engine import StepDriver, StepLimits
from harness.models import EventType, new_id
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.tightening import WATCHED_OUTPUTS

# 测试里的薄驱动一侧：开始一轮工作，第一步继续、第二步停下；提供步骤驱动要问的两样设置
class _ThinDriver:
    def __init__(self, projection, prompt) -> None:
        self._projection = projection
        self._prompt = prompt
        self._asked = 0

    def proceed(self):
        self._asked += 1
        return execution_contract.Judgment(self._asked == 1, self._projection.stream_version)

    def settle(self, transaction):
        return transaction.projection

    async def wait(self, seconds):
        return execution_contract.Judgment(False, self._projection.stream_version)

    def end(self, transaction, reason, message):
        pass

    def department_selection(self, department):
        return None

    def department_prompt(self, department):
        return self._prompt

    async def ask(self, scope, call):
        raise AssertionError("this round does not ask")


class _RecordingAssembly:
    # 装配实现的代理：照旧交给真的装配实现，记下每一步交来的输入（装配契约的输入是 StepFrame）
    CONTRACT_VERSION = assembly_contract.CURRENT_VERSION

    def __init__(self, inner: ContextAssembly) -> None:
        self.inner = inner
        self.frames = []

    def department_history(self, *args, **kwargs):
        return self.inner.department_history(*args, **kwargs)

    def pin(self, projection, frame, limits, **kwargs):
        self.frames.append(frame)
        return self.inner.pin(projection, frame, limits, **kwargs)

    def request(self, pinned, history):
        return self.inner.request(pinned, history)

    def finish_compaction(self, step, output):
        return self.inner.finish_compaction(step, output)


def _round_request(system, run_id, work_ref):
    # 一次开始一轮工作的请求：身份、提示与上限取自当前运行状态，工作引用由调用方给出
    orchestrator = system.orchestrator
    projection = orchestrator.project(run_id)
    prompt = orchestrator._department_prompt(projection, "product")
    session_id = orchestrator.sessions.get(run_id, "product").session_id
    parent = system.store.list_events(run_id)[-1].event_id
    scope = execution_contract.ActivationScope(
        run_id, "product", session_id, new_id("act"), parent,
        prompt_version=prompt.version, prompt_hash=prompt.prompt_ref.content_hash, guidance_ids=(),
        basis=work_basis(projection, "product"), provider="test",
    )
    return execution_contract.RoundRequest(
        scope, prompt, StepLimits(max_model_steps=1), work_ref=work_ref)


def test_the_route_work_reference_reaches_the_assembly_input(tmp_path):
    adapter = FakeAdapter({"product": [product_spec(), product_spec()]})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("print the argument in uppercase")
    # 公开的入口先跑一轮：确定性适配器的调用目标因此登记进目录（与真实激活开始时同一步）
    system.activate_once(run_id)

    work_ref = {"task": "T-17", "queue": ["write the spec"]}
    request = _round_request(system, run_id, work_ref)
    recording = _RecordingAssembly(system.orchestrator.assembly)
    node = _ThinDriver(system.orchestrator.project(run_id), request.prompt)

    async def run():
        driver = StepDriver.start(
            request, writes=system.writes, artifacts=system.artifacts, assembly=recording,
            adapter=adapter, facade=system.facade,
            environment=system.orchestrator._workspaces.environment_for(run_id, "product", refresh=True),
            nodes=node, cancelled=Event(), deltas=system.deltas,
            tightening=WATCHED_OUTPUTS,
        )
        return await driver.result()

    asyncio.run(run())

    assert recording.frames, "这一轮没有装配任何一步"
    assert recording.frames[0].work_ref is work_ref


def test_a_version_the_thin_driver_does_not_accept_stops_the_round_and_says_why(tmp_path, monkeypatch):
    adapter = FakeAdapter({"product": [product_spec()]})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("print the argument in uppercase")
    monkeypatch.setattr(StepDriver, "CONTRACT_VERSION", execution_contract.CURRENT_VERSION + 1)

    projection = system.activate_once(run_id)

    assert projection.status == "failed"
    assert projection.stop_reason == "provider_error"
    failures = [event for event in system.store.list_events(run_id) if event.type == EventType.RUN_FAILED]
    message = str(failures[-1].payload)
    assert "contract version" in message
    assert str(StepDriver.CONTRACT_VERSION) in message
    assert f"current {execution_contract.CURRENT_VERSION}" in message
    # 模型没有被调用：版本不合时在这一轮开始之前就失败
    assert not adapter.invocations
