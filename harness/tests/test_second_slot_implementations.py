# 薄驱动接上第二种装配与第二种执行跑完一轮（工单 #979；骨架与应用设计说明第 3.1、5.2、5.3 节「接法」
# 与第 5.4 节「证明」；总图第四节「装配」「执行」缝）。
#
# 两道缝立住的样子：实现不是薄驱动自己造的、也不是按类名调的，而是由组装处经构造参数交进来；换一套
# 实现（`second_assembly.SecondAssembly` 与 `second_execution.SecondExecution`，都只在测试里用）以后，
# 薄驱动照契约把一轮跑完，骨架的其余代码一行不改。
#
# 这个文件查四件事：
# 1. 构造薄驱动时按契约核对两个实现声明的版本，不在接受范围时构造失败，说明写明是哪一道契约（两条）；
# 2. 薄驱动的源码里没有两个产品实现类的名字（一条）；
# 3. 薄驱动接上第二种装配与第二种执行时一轮能跑完：驱动拿到执行的结果并写回、停止原因在封闭清单里，
#    模型一次没有被调用（验收第 2 条）。
#
# 层：模块层（一次部门激活、事件库与工作区）。守 R2（各缝的交换字段与版本：装配与执行两个实现经构造
# 参数接上，版本不在接受范围时接不起来）与 R1（停止原因取自封闭清单）。

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from harness import assembly_contract, contract_versions, execution_contract
from harness.adapters.fake import FakeAdapter
from harness.engine import StepLimits
from harness.models import EventType
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.tests import second_assembly, second_execution

REPO_ROOT = Path(__file__).resolve().parents[2]
THIN_DRIVER = REPO_ROOT / "harness" / "orchestrator.py"
STOP_REASONS = REPO_ROOT / "harness" / "definitions" / "stop_reasons.json"

# 薄驱动源码里不该出现的两个产品实现类：它们由组装处（`runtime.py`）交进来，薄驱动只经契约调用
PRODUCT_IMPLEMENTATIONS = ("ContextAssembly", "StepDriver")


class _WiringRecorder(second_execution.SecondExecution):
    # 第二种执行的代理：记下薄驱动交给执行实现的依赖，其余原样交给第二种实现
    received: dict[str, Any] | None = None

    @classmethod
    def start(cls, request, *, nodes, cancelled, **dependencies):
        cls.received = dict(dependencies)
        return super().start(request, nodes=nodes, cancelled=cancelled, **dependencies)


class _UnacceptableVersionAssembly(second_assembly.SecondAssembly):
    # 声明的版本不在薄驱动接受的范围内（当前版与上一版）
    CONTRACT_VERSION = assembly_contract.CURRENT_VERSION + 1


class _UnacceptableVersionExecution(second_execution.SecondExecution):
    CONTRACT_VERSION = execution_contract.CURRENT_VERSION + 1


def test_the_thin_driver_runs_a_round_with_the_second_assembly_and_the_second_execution(tmp_path):
    assembly = second_assembly.SecondAssembly()
    _WiringRecorder.received = None
    adapter = FakeAdapter({"product": [product_spec()]})
    system = LoopSystem.for_testing(
        tmp_path, adapter,
        step_limits=StepLimits(max_model_steps=2),
        assembly=assembly, execution=_WiringRecorder,
    )
    run_id = system.create_run("print the argument in uppercase")

    projection = system.activate_once(run_id)

    # 薄驱动接上的是交进来的这两样：执行实现经依赖拿到那个装配实现（它不该认识它的类名）
    assert _WiringRecorder.received is not None, "第二种执行实现没有被接上"
    assert _WiringRecorder.received["assembly"] is assembly
    # 一轮跑完：执行实现经写入口把每一步写回事件日志，薄驱动拿到结果并按停止原因收尾
    steps = [event for event in system.store.list_events(run_id)
             if event.type == EventType.DEPARTMENT_INPUT and "step_id" in (event.payload or {})]
    assert [event.payload["step_id"] for event in steps] == [1, 2], "执行实现的每一步没有被写回"
    assert all(event.session_id and event.department for event in steps)
    # 停止原因在封闭清单里；步数用完属于暂停，不要求事项结束（结束只由接纳写入）
    closed = json.loads(STOP_REASONS.read_text(encoding="utf-8"))
    assert projection.stop_reason in closed, f"停止原因 {projection.stop_reason!r} 不在封闭清单里"
    assert projection.stop_reason == "model_steps_exhausted"
    assert projection.status == "paused"
    # 第二种执行每步只记录、不调模型：假模型一次也没有被调用
    assert adapter.invocations == [], "这一轮不该调用模型"


def test_an_assembly_version_outside_the_accepted_range_fails_at_construction(tmp_path):
    with pytest.raises(contract_versions.ContractVersionError) as raised:
        LoopSystem.for_testing(tmp_path, FakeAdapter({}), assembly=_UnacceptableVersionAssembly())

    # 失败信息写明是哪一道契约、它声明了哪一版、薄驱动接受哪几版
    message = str(raised.value)
    assert "the assembly implementation" in message
    assert str(_UnacceptableVersionAssembly.CONTRACT_VERSION) in message
    assert f"current {assembly_contract.CURRENT_VERSION}" in message


def test_an_execution_version_outside_the_accepted_range_fails_at_construction(tmp_path):
    # 执行实现是每轮开始一个驱动的工厂，这里就是那个类本身（与默认的 `StepDriver` 同一个位置）
    with pytest.raises(contract_versions.ContractVersionError) as raised:
        LoopSystem.for_testing(tmp_path, FakeAdapter({}), execution=_UnacceptableVersionExecution)

    message = str(raised.value)
    assert "the execution implementation" in message
    assert str(_UnacceptableVersionExecution.CONTRACT_VERSION) in message
    assert f"current {execution_contract.CURRENT_VERSION}" in message


def test_the_thin_driver_source_names_neither_product_implementation():
    # 薄驱动不认识实现的名字以外的东西：两个产品实现的类名不在它的源码里（交付说明附同一条 grep）
    source = THIN_DRIVER.read_text(encoding="utf-8")
    offenders = [name for name in PRODUCT_IMPLEMENTATIONS if name in source]
    assert offenders == [], f"薄驱动源码里出现了产品实现类的名字：{offenders}"
