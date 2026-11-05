# 契约模块的导入方向与版本（工单 #826；骨架与应用设计说明第 3.2、5 节；总图第二节第二环「契约」）：
# 契约模块只导入内核、标准库与契约圈自己；实现声明它实现的版本，薄驱动在一个发布里接受当前版与上一版，
# 版本不合格时在开始一轮工作之前失败并写明原因。守的是 R2：契约的公开名称与版本。

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

from harness import assembly_contract, contract_versions, execution_contract, routing_contract, tightening_contract

HARNESS = Path(__file__).resolve().parents[1]
MANIFEST = HARNESS / "definitions" / "kernel-manifest.json"
# 契约圈的五个模块：它们属于总图第二节的第二环，彼此可以互相导入
CONTRACT_MODULES = ("contract_versions", "execution_contract", "assembly_contract", "tightening_contract",
                    "routing_contract")


def _kernel_modules() -> set[str]:
    # 可信内核清单里 kind 为 module 的路径（相对仓库根）
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {entry["path"] for entry in data["paths"] if entry["kind"] == "module"}


def _imported_targets(source: Path) -> set[str]:
    # 模块里的导入：相对导入换成 harness 下的模块名，绝对导入保留顶层名
    tree = ast.parse(source.read_text(encoding="utf-8"))
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if not node.level:
                targets.add(node.module or "")
            elif node.level == 1 and node.module is None:
                # from . import x：x 是这个包里的模块
                targets.update(f"harness.{alias.name}" for alias in node.names)
            elif node.level == 1:
                # from .x import y：导入的是 harness.x
                targets.add(f"harness.{node.module}")
            else:
                # 比 harness 更高一层的相对导入不属于契约圈
                targets.add(".." * (node.level - 1) + (node.module or ""))
    return targets


def _module_paths(target: str) -> tuple[str, str]:
    # 一个 harness 下的模块名对应的两种路径写法：单文件和包的入口
    base = "harness/" + target[len("harness."):].replace(".", "/")
    return base + ".py", base + "/__init__.py"


def test_the_contract_modules_import_only_the_kernel_the_standard_library_and_one_another():
    kernel = _kernel_modules()
    contract = {f"harness.{name}" for name in CONTRACT_MODULES}
    for name in CONTRACT_MODULES:
        source = HARNESS / f"{name}.py"
        assert source.exists(), f"契约模块 {source} 不存在"
        for target in _imported_targets(source):
            if target.startswith("harness."):
                module, package = _module_paths(target)
                assert target in contract or module in kernel or package in kernel, (
                    f"{source.name} 导入了 {target}：它既不是内核模块也不是契约圈的模块"
                )
            else:
                assert target.split(".")[0] in sys.stdlib_module_names, (
                    f"{source.name} 导入了 {target}：契约模块只能导入标准库"
                )


def test_each_implementation_declares_the_version_the_thin_driver_accepts():
    from harness.assembly import ContextAssembly
    from harness.engine import StepDriver
    from harness.tightening import WATCHED_OUTPUTS
    from harness.watched_outputs import ROUTING

    assert StepDriver.CONTRACT_VERSION == execution_contract.CURRENT_VERSION
    assert ContextAssembly.CONTRACT_VERSION == assembly_contract.CURRENT_VERSION
    assert WATCHED_OUTPUTS.CONTRACT_VERSION == tightening_contract.CURRENT_VERSION
    assert ROUTING.CONTRACT_VERSION == routing_contract.CURRENT_VERSION
    # 薄驱动接受四个实现声明的版本
    assert execution_contract.accept(StepDriver) == execution_contract.CURRENT_VERSION
    assert assembly_contract.accept(ContextAssembly) == assembly_contract.CURRENT_VERSION
    assert tightening_contract.accept(WATCHED_OUTPUTS) == tightening_contract.CURRENT_VERSION
    assert routing_contract.accept(ROUTING) == routing_contract.CURRENT_VERSION


def test_a_version_the_thin_driver_does_not_accept_fails_and_says_why():
    class Future:
        CONTRACT_VERSION = execution_contract.CURRENT_VERSION + 1

    with pytest.raises(contract_versions.ContractVersionError) as execution:
        execution_contract.accept(Future)
    message = str(execution.value)
    assert "the execution implementation" in message
    assert str(Future.CONTRACT_VERSION) in message
    assert f"current {execution_contract.CURRENT_VERSION}" in message

    class Undeclared:
        pass

    with pytest.raises(contract_versions.ContractVersionError) as assembly:
        assembly_contract.accept(Undeclared)
    assert "the assembly implementation" in str(assembly.value)
    assert "None" in str(assembly.value)


def test_the_thin_driver_accepts_the_current_and_the_previous_version():
    assert contract_versions.accepted_versions(1) == (1,)
    assert contract_versions.accepted_versions(2, 1) == (2, 1)

    class Previous:
        CONTRACT_VERSION = 1

    assert contract_versions.require_version(
        Previous, component="probe", current=2, previous=1) == 1

    class Current:
        CONTRACT_VERSION = 2

    assert contract_versions.require_version(
        Current, component="probe", current=2, previous=1) == 2

    class TooOld:
        CONTRACT_VERSION = 0

    with pytest.raises(contract_versions.ContractVersionError):
        contract_versions.require_version(TooOld, component="probe", current=2, previous=1)
