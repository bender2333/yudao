# 装配契约与执行契约的同一套契约检查（工单 #979；骨架与应用设计说明第 5.2、5.3、5.4 节；总图第四节
# 「装配」「执行」缝）。同一套参数化的检查各跑一遍真实实现与第二种实现：
# 真实装配是 `assembly.py` 的 `ContextAssembly`，第二种是 `second_assembly.SecondAssembly`；
# 真实执行是 `engine.py` 的 `StepDriver`，第二种是 `second_execution.SecondExecution`。
#
# 装配：输入输出的形状；装配好的请求与上下文清单都进日志；装配不写事实事件；路由的工作引用原样收到。
# 执行：每一步先问安全节点；取消与上限时停下，停止原因取自封闭清单；结果的种类里没有成果驱动的种类。
#
# 层：模块层（一次部门激活、事件库与工作区）。守 R2（各缝的交换字段与版本）与 R3（阶段一：一轮工作的
# 每一步仍先经安全节点，工作引用原样交给装配）。

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from threading import Event

import pytest

from harness import assembly_contract, execution_contract
from harness.definitions import DEFINITIONS
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.assembly import ContextAssembly, model_limits
from harness.engine import StepDriver, StepLimits
from harness.event_store import run_stream
from harness.models import EventType, new_id
from harness.proposals import product_spec
from harness.providers.call import ModelStreamEvent
from harness.runtime import LoopSystem
from harness.tests import second_assembly, second_execution
from harness.tests.helpers import work_basis
from harness.tightening import WATCHED_OUTPUTS

REPO_ROOT = Path(__file__).resolve().parents[2]
STOP_REASONS = REPO_ROOT / "harness" / "definitions" / "stop_reasons.json"
ROUTINGS = REPO_ROOT / "harness" / "definitions" / "routings.json"

# 两种实现的名称：参数化的检查对它们各跑一遍
ASSEMBLIES = ["the real assembly", "the second assembly"]
EXECUTIONS = ["the real execution", "the second execution"]


def _serialized_request_then_text():
    # 假模型的一条脚本：先交回一条「已经序列化的请求」的观察（提供方在真实调用里就是这么做的那一步），
    # 再交回一条只有文字的回复。装配好的请求与上下文清单两者因此都进日志
    def build(call):
        def events():
            yield ModelStreamEvent(kind="request", id=f"serialized-{call.activation_id}-{call.step_id}",
                                   payload={"model": "fake-script", "input": [], "tools": []})
            return FakeTurn(transcript="这一轮跑过一步，没有提交任何东西。")
        return events()
    return build


@pytest.fixture
def round_system(tmp_path):
    # 一个已经跑过一轮的事项：确定性适配器的调用目标因此登记进目录（与真实激活开始时同一步），
    # 契约检查这一轮用的脚本是给「产品」会话的第二条
    adapter = FakeAdapter({"product": [product_spec(), _serialized_request_then_text()]})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("print the argument in uppercase")
    system.activate_once(run_id)
    return system, adapter, run_id


def _round_request(system, run_id, work_ref=None):
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


def _frame(system, run_id, work_ref=None):
    # 装配契约的输入：身份、这一轮采用的提示与版本，以及路由原样交给装配的工作引用
    request = _round_request(system, run_id, work_ref)
    prompt = request.prompt
    return assembly_contract.StepFrame(
        department="product", session_id=request.scope.session_id,
        activation_id=request.scope.activation_id, prompt=prompt,
        effective_contract_hash=request.scope.basis.effective_contract_hash,
        input_version=request.scope.basis.input_version, definitions=DEFINITIONS,
        work_ref=work_ref)


def _assembly(name, system):
    if name == ASSEMBLIES[0]:
        return system.orchestrator.assembly
    return second_assembly.SecondAssembly()


class _ThinDriver:
    # 测试里的薄驱动一侧：安全节点问它继续还是停止
    def __init__(self, projection, prompt, *, steps_allowed: int) -> None:
        self._projection = projection
        self._prompt = prompt
        self._steps_allowed = steps_allowed
        self.asked = 0

    def proceed(self):
        self.asked += 1
        return execution_contract.Judgment(self.asked <= self._steps_allowed, self._projection.stream_version)

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
    # 装配实现的代理：照旧交给被检查的实现，记下每一步交来的输入（装配契约的输入是 StepFrame）
    CONTRACT_VERSION = assembly_contract.CURRENT_VERSION

    def __init__(self, inner) -> None:
        self.inner = inner
        self.frames = []

    def department_history(self, *args, **kwargs):
        return self.inner.department_history(*args, **kwargs)

    def pin(self, projection, frame, limits, **kwargs):
        self.frames.append(frame)
        return self.inner.pin(projection, frame, limits, **kwargs)

    def request(self, pinned, history, **kwargs):
        return self.inner.request(pinned, history, **kwargs)

    def finish_compaction(self, step, output):
        return self.inner.finish_compaction(step, output)


def _start_driver(name, system, adapter, request, node, cancelled, *, assembly=None):
    if name == EXECUTIONS[0]:
        return StepDriver.start(
            request, writes=system.writes, artifacts=system.artifacts,
            assembly=assembly or system.orchestrator.assembly, adapter=adapter, facade=system.facade,
            environment=system.orchestrator._workspaces.environment_for(
                request.scope.run_id, request.scope.department, refresh=True),
            nodes=node, cancelled=cancelled, deltas=system.deltas, tightening=WATCHED_OUTPUTS,
        )
    # 第二种执行只取它自己需要的那两样：写入口与工件库（契约里的 dependencies 由实现自己取用）
    return second_execution.SecondExecution.start(
        request, nodes=node, cancelled=cancelled,
        writes=system.writes, artifacts=system.artifacts)


def _drive(name, system, adapter, request, node, *, cancel=False, assembly=None):
    async def run():
        driver = _start_driver(name, system, adapter, request, node, Event(), assembly=assembly)
        if cancel:
            driver.cancel()
        return await driver.result()

    return asyncio.run(run())


# ———————————————————————— 装配契约 ————————————————————————


@pytest.mark.parametrize("name", ASSEMBLIES)
def test_each_assembly_implementation_declares_a_version_the_thin_driver_accepts(name, round_system):
    system, _adapter, _run_id = round_system
    assert assembly_contract.accept(_assembly(name, system)) == assembly_contract.CURRENT_VERSION


@pytest.mark.parametrize("name", ASSEMBLIES)
def test_each_assembly_implementation_assembles_a_request_and_a_context_list(name, round_system):
    system, _adapter, run_id = round_system
    implementation = _assembly(name, system)
    projection = system.orchestrator.project(run_id)
    frame = _frame(system, run_id, work_ref={"task": "T-17"})
    events = system.store.list_events(run_id)
    limits = model_limits(32_000, 4_096)

    # 输入：事件日志里这个部门与会话的历史、定义里的提示、调用目标的窗口与输出上限
    history = implementation.department_history(events, "product", session_id=frame.session_id)
    pinned = implementation.pin(projection, frame, limits, step_id=1, events=events,
                                snapshot_hash="0" * 64, call_target={"context_window": 32_000})
    step = implementation.request(pinned, history)

    # 输出：装配好的请求与上下文清单。形状由实现自己定，下面这几样是执行实现要读的
    assert step.payload["input"], "装配好的请求里没有要发给模型的内容"
    assert isinstance(step.payload["tools"], list)
    assert isinstance(step.parts, list) and step.parts
    assert all({"source", "text", "digest"} <= set(part) for part in step.parts)
    assert isinstance(step.admitted, bool)
    assert isinstance(step.input_token_estimate, int) and isinstance(step.output_reserve_tokens, int)
    # 上下文清单逐段记下来源与摘要，清单与请求的估算与摘要都写在这里
    manifest = step.context.manifest
    assert [item.source for item in manifest.injected] == [part["source"] for part in step.parts]
    assert manifest.digest and manifest.token_estimate > 0
    assert manifest.department == "product" and manifest.activation_id == frame.activation_id
    # 第一步把这一轮的工作消息交给部门历史；固定的部分占满窗口时由执行实现按装配失败处理
    assert isinstance(pinned.department_input, dict) and pinned.department_input["role"] == "user"
    assert pinned.fills_window is False


@pytest.mark.parametrize("name", ASSEMBLIES)
def test_each_assembly_implementation_writes_no_fact_events(name, round_system):
    system, _adapter, run_id = round_system
    implementation = _assembly(name, system)
    projection = system.orchestrator.project(run_id)
    frame = _frame(system, run_id)
    events = system.store.list_events(run_id)
    before = len(events)

    implementation.request(
        implementation.pin(projection, frame, model_limits(32_000, 4_096), step_id=1, events=events,
                           snapshot_hash="0" * 64),
        implementation.department_history(events, "product"))

    # 装配不改事实：它自己一条事件都不写，事项的状态与流版本照旧
    after = system.store.list_events(run_id)
    assert len(after) == before
    assert system.orchestrator.project(run_id).stream_version == projection.stream_version
    assert system.orchestrator.project(run_id).status == projection.status


@pytest.mark.parametrize("name", ASSEMBLIES)
def test_each_assembly_implementation_gets_the_route_work_reference_and_both_records_land_in_the_log(
        name, round_system):
    system, adapter, run_id = round_system
    work_ref = {"task": "T-17", "queue": ["write the spec"]}
    request = _round_request(system, run_id, work_ref)
    recording = _RecordingAssembly(_assembly(name, system))
    node = _ThinDriver(system.orchestrator.project(run_id), request.prompt, steps_allowed=1)

    _drive(EXECUTIONS[0], system, adapter, request, node, assembly=recording)

    # 工作引用原样到达装配的输入（第 5.4 节第 4 条）
    assert recording.frames, "这一轮没有装配任何一步"
    assert recording.frames[0].work_ref is work_ref
    # 装配好的请求与上下文清单都记进日志：context_assembled 指向两者各自的工件，提供方交回的
    # 序列化请求另记一条 model_request_serialized
    events = system.store.list_events(run_id)
    assembled = [event for event in events if event.type == EventType.CONTEXT_ASSEMBLED]
    assert assembled, "装配好的请求没有被记录"
    assert assembled[-1].payload["request_ref"] and assembled[-1].payload["parts_ref"]
    serialized = [event for event in events if event.type == EventType.MODEL_REQUEST_SERIALIZED]
    assert serialized, "序列化的请求没有被记录"


# ———————————————————————— 执行契约 ————————————————————————


@pytest.mark.parametrize("name", EXECUTIONS)
def test_each_execution_implementation_declares_a_version_the_thin_driver_accepts(name):
    implementation = StepDriver if name == EXECUTIONS[0] else second_execution.SecondExecution
    assert execution_contract.accept(implementation) == execution_contract.CURRENT_VERSION


@pytest.mark.parametrize("name", EXECUTIONS)
def test_each_execution_implementation_asks_the_safe_node_before_doing_anything(name, round_system):
    system, adapter, run_id = round_system
    request = _round_request(system, run_id)
    node = _ThinDriver(system.orchestrator.project(run_id), request.prompt, steps_allowed=0)
    before = len(system.store.list_events(run_id))

    result = _drive(name, system, adapter, request, node)

    # 安全节点说不继续：这一轮一步也没做，没有停止原因（由薄驱动按当时的运行状态收尾）
    assert node.asked == 1
    assert result.events == ()
    assert result.stop_reason is None
    assert len(system.store.list_events(run_id)) == before


@pytest.mark.parametrize("name", EXECUTIONS)
def test_each_execution_implementation_stops_when_cancelled(name, round_system):
    system, adapter, run_id = round_system
    request = _round_request(system, run_id)
    node = _ThinDriver(system.orchestrator.project(run_id), request.prompt, steps_allowed=99)

    result = _drive(name, system, adapter, request, node, cancel=True)

    # 取消以后这一轮停下：没有停止原因，也没有写下什么
    assert result.events == ()
    assert result.stop_reason is None


@pytest.mark.parametrize("name", EXECUTIONS)
def test_each_execution_implementation_stops_at_the_step_limit_with_a_closed_reason(name, round_system):
    system, adapter, run_id = round_system
    request = _round_request(system, run_id)
    # 这一轮一步都不许走：上限为零
    request = execution_contract.RoundRequest(request.scope, request.prompt,
                                             execution_contract.StepLimits(max_model_steps=0),
                                             work_ref=request.work_ref)
    node = _ThinDriver(system.orchestrator.project(run_id), request.prompt, steps_allowed=99)

    result = _drive(name, system, adapter, request, node)

    closed = json.loads(STOP_REASONS.read_text(encoding="utf-8"))
    assert result.stop_reason in closed, f"停止原因 {result.stop_reason!r} 不在封闭清单里"
    assert result.stop_reason == "model_steps_exhausted"


@pytest.mark.parametrize("name", EXECUTIONS)
def test_each_execution_implementations_result_carries_no_outcome_kind(name, round_system):
    system, adapter, run_id = round_system
    request = _round_request(system, run_id)
    request = execution_contract.RoundRequest(request.scope, request.prompt,
                                             execution_contract.StepLimits(max_model_steps=0),
                                             work_ref=request.work_ref)
    node = _ThinDriver(system.orchestrator.project(run_id), request.prompt, steps_allowed=99)

    result = _drive(name, system, adapter, request, node)

    # 结果是一轮工作写下的事件范围与停止原因（第 5.3 节输出）；这一轮算不算结束、结束成什么由路由按事件判断
    assert isinstance(result, execution_contract.RoundResult)
    assert isinstance(result.events, tuple)
    kinds = []
    for routing in json.loads(ROUTINGS.read_text(encoding="utf-8"))["routings"]:
        for kind in routing["outcome_kinds"]:
            if kind not in kinds:
                kinds.append(kind)
    assert kinds, "路由自己的定义里没有成果种类，这条检查无从判断"
    # 结果的种类里没有成果驱动的种类：字段名与契约源码里都不出现路由定义的成果种类
    fields = set(execution_contract.RoundResult.__dataclass_fields__)
    assert not (fields & set(kinds)), f"结果的种类里出现了成果种类：{sorted(fields & set(kinds))}"
    source = Path(execution_contract.__file__).read_text(encoding="utf-8")
    assert not [kind for kind in kinds if kind in source], (
        "执行契约的源码里出现了路由定义的成果种类：结果种类应当由路由按事件判断")
