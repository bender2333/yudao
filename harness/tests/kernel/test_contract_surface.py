# 契约的公开名称与版本（S6a，工单 #829；骨架与应用 docs/design/skeleton-and-application.md「契约」、「三道缝的契约」、「对外合同的兼容」；总图第二节第二环「契约」）：
# 每道契约带版本号，实现声明它实现哪一版，薄驱动在一个发布里同时接受当前版与上一版；
# 契约模块的公开名称有快照——删掉或改掉一个已有名称而版本没有提高时这里失败，信息写明是哪一个名称。
#
# 与 test_contract_modules.py 的分工：那一个核对契约模块的导入方向、实现声明的版本被薄驱动接受，
# 这一个把「公开名称」与「版本」两样东西钉成快照，守的是兼容：删名称要提版，提版要有新的快照。
#
# 读模块的源码（抽象语法树）与模块自己的常量，不开数据库、不用子进程、不用网络，属于单元层。
# 守 docs/design/test-pyramid.md「测试按三环留」的 R2（第二环的合同：契约的公开名称与版本）。

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from harness import (
    assembly_contract,
    contract_versions,
    execution_contract,
    routing_contract,
    tightening_contract,
)

HARNESS = Path(__file__).resolve().parents[2]

MODULES = {
    "contract_versions": contract_versions,
    "execution_contract": execution_contract,
    "assembly_contract": assembly_contract,
    "tightening_contract": tightening_contract,
    "routing_contract": routing_contract,
}

# 三道缝的契约（路由、装配、执行）与收紧检查的契约：每一道都有自己的版本号。
# contract_versions 是它们共用的版本核对，没有自己的版本号，只核对名称
SEAM_CONTRACTS = ("execution_contract", "assembly_contract", "tightening_contract", "routing_contract")

# 放出 S6a 时的公开名称（模块自己定义的类、函数与赋值，不含从别处导入的名字）与版本号
SNAPSHOT: dict[str, dict] = {
    "contract_versions": {
        "version": None,
        "names": ("ContractVersionError", "accepted_versions", "require_version"),
    },
    "execution_contract": {
        # 第三版（工单 #1511）：加 `DepartmentSettings`（按部门取模型与提示词的来源，随开始一轮工作的请求
        # 交给执行实现）与 `PreviousSafeNode`（第二版的安全节点，`SafeNode` 之外还带着那两个按部门的方法，留一版）
        "version": 3,
        "names": (
            "ActivationScope", "CURRENT_VERSION", "DepartmentSettings", "Judgment", "PREVIOUS_VERSION",
            "PreviousSafeNode", "RoundRequest", "RoundResult", "SafeNode", "StepDriver", "StepLimits",
            "accept",
        ),
    },
    "assembly_contract": {
        "version": 1,
        "names": (
            "CURRENT_VERSION", "ContextAssembly", "ModelLimits", "PREVIOUS_VERSION", "StepFrame",
            "accept",
        ),
    },
    "tightening_contract": {
        "version": 1,
        "names": ("CURRENT_VERSION", "PREVIOUS_VERSION", "accept"),
    },
    "routing_contract": {
        "version": 2,
        "names": (
            "AskBranch", "AskLimits", "AskOutcome", "AskRejection", "AskRoundResult",
            "CURRENT_VERSION", "CompletionReason", "InvalidRoutingDefinition", "ItemEnd",
            "PREVIOUS_VERSION", "RoundEnd", "Routing", "UnavailableRouting", "accept",
            "definition_of", "register", "registered", "select",
        ),
    },
}


def _public_names(module_name: str) -> list[str]:
    # 模块自己定义的公开名称：顶层下划线开头的名字是内部的（契约圈内部使用的辅助函数不进公开面）
    tree = ast.parse((HARNESS / f"{module_name}.py").read_text(encoding="utf-8"))
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                names.append(node.name)
        elif isinstance(node, ast.Assign):
            names.extend(target.id for target in node.targets
                         if isinstance(target, ast.Name) and not target.id.startswith("_"))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if not node.target.id.startswith("_"):
                names.append(node.target.id)
    return sorted(names)


def _version(module_name: str) -> int | None:
    return getattr(MODULES[module_name], "CURRENT_VERSION", None)


@pytest.mark.parametrize("module_name", SEAM_CONTRACTS)
def test_every_seam_contract_declares_a_version(module_name: str) -> None:
    # 每道契约带版本号（docs/design/skeleton-and-application.md「契约」）：没有版本号，薄驱动就无从判断实现声明的是哪一版
    version = _version(module_name)
    assert type(version) is int and version >= 1, f"{module_name} 没有给出整数的 CURRENT_VERSION：{version!r}"
    previous = getattr(MODULES[module_name], "PREVIOUS_VERSION", None)
    assert previous is None or type(previous) is int, f"{module_name} 的 PREVIOUS_VERSION 不是整数：{previous!r}"
    if previous is not None:
        assert previous < version, f"{module_name} 的 PREVIOUS_VERSION {previous} 不低于当前版 {version}"


@pytest.mark.parametrize("module_name", sorted(SNAPSHOT))
def test_the_public_names_match_the_snapshot(module_name: str) -> None:
    # 快照是放出这一版时的公开面：名称有增减时更新快照；删改已有名称还要提高版本（下面一条）
    expected = list(SNAPSHOT[module_name]["names"])
    current = _public_names(module_name)
    removed = [name for name in expected if name not in current]
    added = [name for name in current if name not in expected]
    assert not removed and not added, (
        f"{module_name} 的公开名称与快照不同：删掉或改了 {removed}，加了 {added}。"
        f"契约只增：删改已有名称要先把 CURRENT_VERSION 提高，再更新 "
        f"harness/tests/kernel/test_contract_surface.py 的快照"
    )


@pytest.mark.parametrize("module_name", sorted(SNAPSHOT))
def test_a_removed_or_renamed_name_needs_a_version_bump(module_name: str) -> None:
    # 删掉或改掉一个已有名称而版本没有提高：使用这一版契约的实现会不认识它，这里失败并写明是哪一个
    snapshot = SNAPSHOT[module_name]
    current = _public_names(module_name)
    removed = [name for name in snapshot["names"] if name not in current]
    version = _version(module_name)
    bumped = (version is not None and snapshot["version"] is not None and version > snapshot["version"])
    assert not removed or bumped, (
        f"{module_name} 删掉或改掉了公开名称 {removed}，而 CURRENT_VERSION 没有提高"
        f"（快照是 {snapshot['version']}，现在是 {version}）：契约的公开名称只增，"
        f"删改已有名称要显式提高版本，让薄驱动仍然接受上一版"
    )
    if version is not None and snapshot["version"] is not None:
        assert version >= snapshot["version"], (
            f"{module_name} 的 CURRENT_VERSION 从 {snapshot['version']} 降到了 {version}：版本号只增"
        )


def test_accepted_versions_returns_current_alone_or_with_previous() -> None:
    # 守护 docs/design/test-pyramid.md「测试按三环留」的 R2（第二环合同：docs/design/skeleton-and-application.md「契约」「三道缝的契约」）：
    # 省略上一版或显式传入空值时仅返回当前版单元素元组，给出上一版整数时按顺序返回当前版与上一版
    assert contract_versions.accepted_versions(1) == (1,)
    assert contract_versions.accepted_versions(3, None) == (3,)
    assert contract_versions.accepted_versions(2, 1) == (2, 1)
    assert contract_versions.accepted_versions(3, 2) == (3, 2)


def test_require_version_returns_declared_int_for_current_or_previous_version() -> None:
    # 守护 docs/design/test-pyramid.md「测试按三环留」的 R2（第二环合同：docs/design/skeleton-and-application.md「契约」「三道缝的契约」）：
    # 薄驱动在一个发布周期内同时接受当前版与上一版实现，返回声明的精确整数版本号；公开异常继承自 RuntimeError
    assert issubclass(contract_versions.ContractVersionError, RuntimeError)

    class FirstImpl:
        CONTRACT_VERSION = 1

    accepted_default = contract_versions.require_version(FirstImpl, component="probe", current=1)
    assert type(accepted_default) is int and accepted_default == 1

    accepted_none = contract_versions.require_version(FirstImpl, component="probe", current=1, previous=None)
    assert type(accepted_none) is int and accepted_none == 1

    class CurrentImpl:
        CONTRACT_VERSION = 3

    class PreviousImpl:
        CONTRACT_VERSION = 2

    accepted_current = contract_versions.require_version(CurrentImpl, component="probe", current=3, previous=2)
    accepted_previous = contract_versions.require_version(PreviousImpl, component="probe", current=3, previous=2)
    assert type(accepted_current) is int and accepted_current == 3
    assert type(accepted_previous) is int and accepted_previous == 2


def test_require_version_rejects_missing_non_int_and_unaccepted_versions() -> None:
    # 守护 docs/design/test-pyramid.md「测试按三环留」的 R1 与 R2（第一环不变式与第二环合同：docs/design/skeleton-and-application.md「契约」）：
    # 缺失 CONTRACT_VERSION、声明值为非精确整数类型（含布尔值、浮点数、字符串、空值）或声明的整数不在允许集合内时抛出 ContractVersionError
    class UndeclaredImpl:
        pass

    class NoneVersionImpl:
        CONTRACT_VERSION = None

    class TrueVersionImpl:
        CONTRACT_VERSION = True

    class FalseVersionImpl:
        CONTRACT_VERSION = False

    class FloatVersionImpl:
        CONTRACT_VERSION = 1.0

    class StringVersionImpl:
        CONTRACT_VERSION = "1"

    class BlankVersionImpl:
        CONTRACT_VERSION = " "

    for invalid_impl in (
        UndeclaredImpl,
        NoneVersionImpl,
        TrueVersionImpl,
        FalseVersionImpl,
        FloatVersionImpl,
        StringVersionImpl,
        BlankVersionImpl,
    ):
        with pytest.raises(contract_versions.ContractVersionError):
            contract_versions.require_version(invalid_impl, component="probe", current=1)
        with pytest.raises(contract_versions.ContractVersionError):
            contract_versions.require_version(invalid_impl, component="probe", current=1, previous=0)

    class ZeroVersionImpl:
        CONTRACT_VERSION = 0

    class NegativeVersionImpl:
        CONTRACT_VERSION = -1

    class OldVersionImpl:
        CONTRACT_VERSION = 1

    class FutureVersionImpl:
        CONTRACT_VERSION = 3

    for unaccepted_when_no_previous in (ZeroVersionImpl, NegativeVersionImpl, OldVersionImpl, FutureVersionImpl):
        with pytest.raises(contract_versions.ContractVersionError):
            contract_versions.require_version(unaccepted_when_no_previous, component="probe", current=2)
        with pytest.raises(contract_versions.ContractVersionError):
            contract_versions.require_version(
                unaccepted_when_no_previous, component="probe", current=2, previous=None
            )

    for unaccepted_with_previous in (ZeroVersionImpl, NegativeVersionImpl, FutureVersionImpl):
        with pytest.raises(contract_versions.ContractVersionError):
            contract_versions.require_version(unaccepted_with_previous, component="probe", current=2, previous=1)

