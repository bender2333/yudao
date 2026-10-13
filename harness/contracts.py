"""Effective contract identity and its host-owned Markdown representations."""

from __future__ import annotations

import os
from typing import Any

from .models import RunProjection, canonical_hash
from .path_rules import validate_public_path


def contract_payload(projection: RunProjection) -> dict[str, Any]:
    spec = projection.product_spec
    if spec is None or spec.status != "active":
        raise ValueError("an active ProductSpec is required")
    basis = {
        "product_spec_hash": spec.content_hash,
        "decision_hashes": [item.content_hash for item in projection.effective_decisions],
        "input_version": spec.input_version,
    }
    return {**basis, "content_hash": canonical_hash(basis)}


def current_contract_hash(projection: RunProjection) -> str | None:
    contract = projection.effective_contract
    return None if contract is None else contract.content_hash


def current_plan_hash(projection: RunProjection) -> str | None:
    plan = projection.engineering_plan
    return None if plan is None else plan.content_hash


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


def render_prd(projection: RunProjection, contract: dict[str, Any]) -> str:
    spec = projection.product_spec
    if spec is None:
        raise ValueError("PRD requires an active ProductSpec")
    lines = ["# PRD", "", f"Effective contract: {contract['content_hash']}",
             f"ProductSpec: {spec.content_hash}", f"Accepted user input through version: {spec.input_version}",
             "", "## Goal", "", spec.goal]
    for title, values in (
        ("Requirements", spec.requirements), ("Boundaries", spec.boundaries),
        ("Constraints and recorded defaults", spec.constraints), ("Acceptance Criteria", spec.acceptance_criteria),
        ("Fatal Conditions", spec.fatal_conditions), ("Non-goals", spec.non_goals),
    ):
        lines.extend(["", f"## {title}", ""])
        lines.extend(f"- {item}" for item in values)
        if not values:
            lines.append("None.")
    lines.extend(["", "## Effective Product Decisions", ""])
    for index, decision in enumerate(projection.effective_decisions, 1):
        lines.extend([f"### {index}. {decision.statement}", "", f"Rationale: {decision.rationale}",
                      "", f"Source: {decision.content_hash}", f"Original ProductSpec: {decision.product_spec_hash}", ""])
    if not projection.effective_decisions:
        lines.append("None.")
    if spec.decision_changes:
        lines.extend(["", "## Treatment of Earlier Decisions", ""])
        lines.extend(f"- {item['decision_hash']}: {item['disposition']}. {item['rationale']}" for item in spec.decision_changes)
    if spec.change_record is not None:
        lines.extend(["", "## Requirement Changes", "", f"Previous ProductSpec: {spec.parent_hash}",
                      f"Rationale: {spec.change_record['rationale']}"])
        for field in ("changed", "retained", "retired"):
            lines.extend(["", f"### {field.title()}", ""])
            lines.extend(f"- {item}" for item in spec.change_record[field])
            if not spec.change_record[field]:
                lines.append("None.")
    return "\n".join(lines).rstrip() + "\n"


def render_plan(plan: dict[str, Any]) -> str:
    lines = ["# Engineering Plan", "", f"Plan: {plan['content_hash']}",
             f"Effective contract: {plan['effective_contract_hash']}", "", "## Objective", "", plan["objective"],
             "", "## Change Scope", ""]
    lines.extend(f"- {item}" for item in plan["scope"])
    lines.extend(["", "## Ordered Tasks", ""])
    for index, task in enumerate(plan["tasks"], 1):
        lines.extend([f"### {index}. {task['title']}", "", "Outputs:"])
        lines.extend(f"- {item}" for item in task["outputs"])
        lines.extend(["", f"Verification: {task['verification']}", ""])
    lines.extend(["## Necessary Refactoring", ""])
    lines.extend(f"- {item}" for item in plan["refactoring"])
    if not plan["refactoring"]:
        lines.append("None.")
    lines.extend(["", "## Defaults and Basis", ""])
    lines.extend(f"- {item['decision']}\n  Basis: {item['basis']}" for item in plan["assumptions"])
    if not plan["assumptions"]:
        lines.append("None.")
    if plan["reason"]:
        lines.extend(["", "## Adjustment Reason", "", plan["reason"]])
    return "\n".join(lines).rstrip() + "\n"


def render_structure(structure: dict[str, Any]) -> str:
    # 现有结构说明的材料（docs/design/existing-project-onboarding.md 第 4.4 节）：主机由接纳结果生成
    lines = ["# 现有结构说明", "",
             f"结构说明：{structure['content_hash']}",
             f"初始 PRD：{structure['product_spec_hash']}",
             f"所描述的代码树摘要：{structure['code_tree_digest']}", "",
             "## 总体说明", "", structure["overall"], "", "## 模块", ""]
    lines.extend(f"- `{item['path']}`：{item['responsibility']}" for item in structure["modules"])
    lines.extend(["", "## 入口", ""])
    lines.extend(f"- {item['kind']}：`{item['path']}`，运行方式：{item['how_to_run']}"
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
