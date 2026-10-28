# 契约的公开名称与版本（S6a，工单 #829；骨架与应用设计说明第 3.2、5、9 节；总图第二节第二环「契约」）：
# 每道契约带版本号，实现声明它实现哪一版，薄驱动在一个发布里同时接受当前版与上一版；
# 契约模块的公开名称有快照——删掉或改掉一个已有名称而版本没有提高时这里失败，信息写明是哪一个名称。
#
# 与 test_contract_modules.py 的分工：那一个核对契约模块的导入方向、实现声明的版本被薄驱动接受，
# 这一个把「公开名称」与「版本」两样东西钉成快照，守的是兼容：删名称要提版，提版要有新的快照。
#
# 读模块的源码（抽象语法树）与模块自己的常量，不开数据库、不用子进程、不用网络，属于单元层。
# 守第 13 节的 R2（第二环的合同：契约的公开名称与版本）。

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
        "version": 2,
        "names": (
            "ActivationScope", "CURRENT_VERSION", "Judgment", "PREVIOUS_VERSION", "RoundRequest",
            "RoundResult", "SafeNode", "StepDriver", "StepLimits", "accept",
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
            "CURRENT_VERSION", "InvalidRoutingDefinition", "ItemEnd", "PREVIOUS_VERSION", "RoundEnd",
            "Routing", "UnavailableRouting", "accept", "definition_of", "register", "registered",
            "select",
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
    # 每道契约带版本号（第 3.2、5 节）：没有版本号，薄驱动就无从判断实现声明的是哪一版
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
