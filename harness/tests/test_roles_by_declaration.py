"""工单 #1390：写入范围与提案合同按定义里角色的声明判断，不按部门名。

一份把核验角色改名、一份把产品改名的测试定义：改名后的角色得到与默认三部门同一种待遇——
写检查材料以外的文件被拒绝，拒绝原因与默认定义下的质检逐字相同、原因里没有部门名，它的检查材料照常保存
（`tools.writes_check_materials` 是保存与检查副本共用的那个读数），它能在回答里修订要求；
不是这些角色的角色不受这些限制。

守 R2（定义的格式：定义是数据，部门名不进代码，换一份定义不改代码）与 R3（形态随事项冻结、核验角色是
角色的性质：写入范围是内核认识的通用权限，核验角色只是取了这一种）。改名的那份定义要落在临时目录里
（`load_definitions` 读文件），所以整个文件属于模块层。

检查副本那一半（跑一次检查，材料要进副本）在 `test_qa_test_materials.py`：它要起子进程，属于集成层。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness import adjudication, tools
from harness.actions import WorkspaceFacts
from harness.definitions import DEFINITIONS, DEFINITIONS_DIR, load_definitions
from harness.environment import check_material_paths
from harness.minimal_projection import fold_events
from harness.models import RunProjection
from harness.path_rules import CHECK_MATERIALS_DIR
from harness.tightening import WATCHED_OUTPUTS
from harness.validation import AdjudicationView

# 改名后的角色编号：都不是默认定义里的名字
RENAMED_VERIFIER = "inspection"
RENAMED_PRODUCT = "requirements"


def _renamed(value: Any, old: str, new: str) -> Any:
    # 定义文件里表示部门的那个字符串全部换掉，其余内容照旧；规则登记的条目名按部门分段，一起换
    if isinstance(value, dict):
        return {_renamed_key(key, old, new): _renamed(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_renamed(item, old, new) for item in value]
    return new if value == old else value


def _renamed_key(key: Any, old: str, new: str) -> Any:
    if not isinstance(key, str):
        return key
    return ".".join(new if part == old else part for part in key.split("."))


def renamed_definitions(tmp_path: Path, names: dict[str, str]) -> Any:
    """发布的那份定义的一份副本：按 names 把部门编号换成新的（与 test_watched_outputs_renamed.py 同一做法）。"""
    directory = tmp_path / "definitions"
    directory.mkdir()
    for path in DEFINITIONS_DIR.glob("*.json"):
        content = json.loads(path.read_text(encoding="utf-8"))
        for old, new in names.items():
            content = _renamed(content, old, new)
        (directory / path.name).write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_definitions(directory)


def _write(definitions: Any, department: str, path: str):
    # 一次写工具调用的许可判断：只用得到定义、部门与目标路径
    return adjudication.tool_permission(
        AdjudicationView(minimal=fold_events([]), state=RunProjection()),
        {"name": "write_file", "id": "call-1", "args": {"path": path, "content": "print('x')\n"}},
        department=department, tightening=WATCHED_OUTPUTS,
        basis=adjudication.WorkBasis(effective_contract_hash=None, input_version=0, guidance_version=0),
        aborted=False, facts=WorkspaceFacts(), definitions=definitions)


def test_a_renamed_verifier_writes_only_its_check_materials(tmp_path: Path) -> None:
    # 验收第 2 条：把核验角色改名的定义里，改名后的角色写检查材料以外的文件被拒绝，
    # 拒绝原因与今天质检的一样、原因里没有部门名；写检查材料照常放行
    renamed = renamed_definitions(tmp_path, {"quality": RENAMED_VERIFIER})
    assert tools.writes_check_materials(RENAMED_VERIFIER, definitions=renamed)
    assert not tools.writes_check_materials("engineering", definitions=renamed)
    assert check_material_paths(renamed) == {RENAMED_VERIFIER: (CHECK_MATERIALS_DIR,)}
    outside = _write(renamed, RENAMED_VERIFIER, "src/echo.py")
    assert not outside.allowed and not outside.stopped
    assert outside.reason == _write(DEFINITIONS, "quality", "src/echo.py").reason
    assert CHECK_MATERIALS_DIR in outside.reason
    for name in ("product", "engineering", "quality", RENAMED_VERIFIER):
        assert name not in outside.reason, outside.reason
    assert _write(renamed, RENAMED_VERIFIER, f"{CHECK_MATERIALS_DIR}/test_echo.py").allowed
    # 不是核验角色的角色不受这个限制：工程照旧写交付文件
    assert _write(renamed, "engineering", "src/echo.py").allowed


def test_a_renamed_product_revises_the_prd_in_an_answer(tmp_path: Path) -> None:
    # 验收第 3 条：把产品改名的定义里，改名后的角色能修订 PRD（回答里带 PRD 修订的那一支按提案合同判断，
    # 引擎读的就是这里这个读数），别的角色不能
    renamed = renamed_definitions(tmp_path, {"product": RENAMED_PRODUCT})
    assert "product_spec" in tools.proposal_kinds(RENAMED_PRODUCT, definitions=renamed)
    for other in ("engineering", "quality"):
        assert "product_spec" not in tools.proposal_kinds(other, definitions=renamed)
    # 默认定义下同一条规则：只有产品能交这一种成果
    assert "product_spec" in tools.proposal_kinds("product")
    for other in ("engineering", "quality"):
        assert "product_spec" not in tools.proposal_kinds(other)
