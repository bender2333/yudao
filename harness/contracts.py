"""Effective contract identity and its host-owned Markdown representations."""

from __future__ import annotations

import os
from typing import Any

from .models import RunProjection, canonical_hash
from .public_tree import validate_public_path


def contract_payload(projection: RunProjection) -> dict[str, Any]:
    spec = projection.product_spec
    if spec is None or spec.status != "active":
        raise ValueError("an active ProductSpec is required")
    basis = {
        "product_spec_hash": spec.content_hash,
        "decision_hashes": [item.reaction_hash for item in projection.effective_decisions],
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
             f"ProductSpec: {spec.content_hash}", "", "## Goal", "", spec.goal]
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
        lines.extend([f"### {index}. {decision.question}", "", f"Decision: {decision.decision}",
                      "", f"Background: {decision.background}", "", "Options:"])
        lines.extend(f"- {item}" for item in decision.options)
        lines.extend(["", f"Recommendation: {decision.recommendation}", "", f"Impact: {decision.impact}",
                      "", "Decision fields:"])
        lines.extend(f"- {item}" for item in decision.decide_fields)
        lines.extend(["", f"Rationale: {decision.rationale}", "", f"Source: {decision.reaction_hash}", ""])
    if not projection.effective_decisions:
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
