"""Effective contract identity and its host-owned Markdown representations."""

from __future__ import annotations

from typing import Any

from .path_rules import validate_public_path


def artifact_hash(artifact: Any) -> str | None:
    # 当前成果的版本摘要：最小投影里的成果与应用侧运行状态投影里的成果都读同名的字段
    return None if artifact is None else getattr(artifact, "content_hash", None)


def normalize_scope(value: str) -> str:
    relative = value.replace("\\", "/")
    if relative == ".":
        return relative
    validate_public_path(relative[:-1] if relative.endswith("/") else relative)
    return relative


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
