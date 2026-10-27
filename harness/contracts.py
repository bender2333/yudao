"""Effective contract identity and its host-owned Markdown representations."""

from __future__ import annotations

import os
from typing import Any

from .minimal_projection import MinimalProjection
from .path_rules import validate_public_path


def artifact_hash(artifact: Any) -> str | None:
    # 当前成果的版本摘要：最小投影里的成果与应用侧运行状态投影里的成果都读同名的字段
    return None if artifact is None else getattr(artifact, "content_hash", None)


def current_contract_hash(projection: MinimalProjection) -> str | None:
    # 当前有效合同的版本摘要：裁决只读最小投影（设计说明第 4 节，S1d 工单 #860）。
    # 合同的身份由它记下的成果版本算出，读的是摘要不是内容，所以留在内核；
    # 合同的呈现（PRD 的 Markdown）读成果的内容，搬到应用侧（harness/submissions.py）
    return projection.artifact_hash("contract")


def normalize_scope(value: str) -> str:
    relative = value.replace("\\", "/")
    if relative == ".":
        return relative
    validate_public_path(relative[:-1] if relative.endswith("/") else relative)
    return relative


def path_in_scope(path: str, scope: list[str]) -> bool:
    try:
        relative = normalize_scope(path)
    except (AttributeError, ValueError):
        return False
    if relative == "." or relative.endswith("/"):
        return False
    if os.name == "nt":
        relative, scope = relative.casefold(), [item.casefold() for item in scope]
    return any(item == "." or relative == item or (item.endswith("/") and relative.startswith(item)) for item in scope)


def render_structure(structure: dict[str, Any]) -> str:
    # 现有结构说明的材料（docs/design/existing-project-onboarding.md 第 4.4 节）：主机由接纳结果生成
    lines = ["# 现有结构说明", "",
             f"结构说明：{structure['content_hash']}",
             f"初始 PRD：{structure['product_spec_hash']}",
             f"所描述的代码树摘要：{structure['code_tree_digest']}", "",
             "## 总体说明", "", structure["overall"], "", "## 模块", ""]
    lines.extend(f"- `{item['path']}`：{item['responsibility']}" for item in structure["modules"])
    lines.extend(["", "## 入口", ""])
    lines.extend(f"- {item['kind']}：`{item['path']}`，运行方式：`{item['how_to_run']}`"
                 for item in structure["entry_points"])
    lines.extend(["", "## 构建与测试", ""])
    for item in structure["build_and_test"]:
        lines.append(f"- {item['name']}（`{item['command']}`）：{item['purpose']}")
        receipt = item["receipt"]
        lines.append(f"  本次激活的回执：退出状态 {receipt['exit_code']}；{receipt['summary']}")
    lines.extend(["", "## 要求所在的位置", ""])
    for item in structure["requirement_locations"]:
        lines.append(f"- {item['requirement']}")
        lines.extend(f"  - `{path}`" for path in item["locations"])
    lines.extend(["", "## 约定与注意事项", ""])
    lines.extend(f"- {item}" for item in structure["conventions"])
    if not structure["conventions"]:
        lines.append("无。")
    return "\n".join(lines).rstrip() + "\n"
