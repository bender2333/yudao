"""提案 schema、权限、前置条件和绑定校验。控制层普通代码，不调用模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import current_contract_hash, normalize_scope
from .models import (
    DEPARTMENTS,
    PROPOSAL_KINDS,
    QA_VERDICTS,
    REACTION_DECISIONS,
    spec_content_hash,
)
from .projection import RunProjection
from .workspace import WorkspaceSnapshot

KIND_BY_DEPARTMENT = {
    "product": {"product_spec", "product_reaction"},
    "engineering": {"engineering_plan", "ask_request", "delivery_spec"},
    "quality": {"qa_review"},
}

PHASE_KINDS = {
    "PRODUCT_SPEC": {"product_spec"},
    "REWORK_PRODUCT": {"product_spec"},
    "PRODUCT_REACT": {"product_reaction"},
    "ASK_PRODUCT": {"product_reaction"},
    "ENGINEERING": {"engineering_plan", "ask_request", "delivery_spec"},
    "REWORK_ENGINEERING": {"engineering_plan", "ask_request", "delivery_spec"},
    "QUALITY": {"qa_review"},
}


@dataclass
class FieldError:
    field: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "message": self.message}


@dataclass
class ProposalDecision:
    accepted: bool
    errors: list[FieldError] = field(default_factory=list)
    artifact: dict[str, Any] | None = None
    transitions: list[tuple[str, str]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def error_dicts(self) -> list[dict[str, str]]:
        return [item.to_dict() for item in self.errors]


def evaluate_proposal(
    *,
    phase: str,
    department: str,
    proposal: dict[str, Any] | None,
    projection: RunProjection,
    snapshot: WorkspaceSnapshot,
) -> ProposalDecision:
    try:
        return _evaluate_proposal(
            phase=phase,
            department=department,
            proposal=proposal,
            projection=projection,
            snapshot=snapshot,
        )
    except Exception as exc:
        return ProposalDecision(
            False,
            [FieldError("proposal", f"invalid proposal payload: {type(exc).__name__}: {exc}")],
        )


def _evaluate_proposal(
    *,
    phase: str,
    department: str,
    proposal: dict[str, Any] | None,
    projection: RunProjection,
    snapshot: WorkspaceSnapshot,
) -> ProposalDecision:
    if not proposal or not isinstance(proposal, dict):
        return ProposalDecision(False, [FieldError("proposal", "structured proposal is required; natural language cannot change state")])
    kind = proposal.get("kind")
    if kind not in PROPOSAL_KINDS:
        return ProposalDecision(False, [FieldError("kind", f"unknown proposal kind: {kind!r}")])
    if department not in DEPARTMENTS:
        return ProposalDecision(False, [FieldError("issuer", f"unknown department: {department}")])
    if kind not in KIND_BY_DEPARTMENT[department]:
        return ProposalDecision(False, [FieldError("kind", f"{department} cannot issue {kind}")])
    allowed = PHASE_KINDS.get(phase, set())
    if kind not in allowed:
        return ProposalDecision(False, [FieldError("kind", f"{kind} is not valid in phase {phase}")])

    errors = _validate_schema(kind, proposal)
    if errors:
        return ProposalDecision(False, errors)

    if kind == "product_spec":
        return _accept_product_spec(phase, proposal, projection)
    if kind == "engineering_plan":
        return _accept_plan(proposal, projection)
    if kind == "ask_request":
        return _accept_ask(proposal, projection)
    if kind == "product_reaction":
        return _accept_reaction(proposal, projection)
    if kind == "delivery_spec":
        return _accept_delivery(proposal, projection, snapshot)
    if kind == "qa_review":
        return _accept_review(proposal, projection, snapshot)
    return ProposalDecision(False, [FieldError("kind", "unhandled kind")])


def _validate_schema(kind: str, proposal: dict[str, Any]) -> list[FieldError]:
    if kind == "engineering_plan":
        return _plan_schema_errors(proposal)
    if kind == "product_spec":
        return _require_text(proposal, "goal") + _require_string_list(proposal, "requirements", min_items=1) + _require_string_list(
            proposal, "acceptance_criteria", min_items=1
        ) + _optional_string_list(proposal, "boundaries") + _optional_string_list(proposal, "constraints") + _optional_string_list(
            proposal, "fatal_conditions"
        ) + _optional_string_list(proposal, "non_goals")
    if kind == "ask_request":
        errors = (
            _require_text(proposal, "question")
            + _require_text(proposal, "background")
            + _require_text(proposal, "impact")
            + _require_text(proposal, "recommendation")
            + _require_string_list(proposal, "options", min_items=1)
            + _require_string_list(proposal, "decide_fields", min_items=1)
        )
        return errors
    if kind == "product_reaction":
        errors = _require_text(proposal, "rationale")
        decision = proposal.get("decision")
        if decision not in REACTION_DECISIONS:
            errors.append(FieldError("decision", "decision must be accept, reply, or reject"))
        spec_update = proposal.get("spec_update")
        if spec_update == {}:
            spec_update = None
            proposal["spec_update"] = None
        if spec_update is not None:
            if not isinstance(spec_update, dict):
                errors.append(FieldError("spec_update", "spec_update must be an object"))
            else:
                nested = dict(spec_update)
                nested.setdefault("kind", "product_spec")
                errors.extend(_validate_schema("product_spec", nested))
        return errors
    if kind == "delivery_spec":
        return (
            _require_text(proposal, "summary")
            + _require_string_list(proposal, "files", min_items=1)
            + _require_string_list(proposal, "check_names", min_items=1)
            + _optional_string_list(proposal, "known_risks")
        )
    if kind == "qa_review":
        errors = _require_text(proposal, "rationale")
        verdict = proposal.get("verdict")
        if verdict not in QA_VERDICTS:
            errors.append(FieldError("verdict", "verdict must be rework_product, rework_engineering, or release"))
        errors.extend(_qa_defects_errors(proposal))
        errors.extend(_qa_check_name_errors(proposal))
        defects = [] if "defects" not in proposal else proposal.get("defects")
        if verdict == "release" and isinstance(defects, list) and defects:
            errors.append(FieldError("defects", "release requires an empty defect list"))
        if verdict in {"rework_product", "rework_engineering"} and isinstance(defects, list) and not defects:
            errors.append(FieldError("defects", "rework requires at least one defect"))
        return errors
    return [FieldError("kind", "unknown kind")]


def _plan_schema_errors(proposal: dict[str, Any]) -> list[FieldError]:
    errors = (_require_text(proposal, "effective_contract_hash") + _require_text(proposal, "objective")
              + _require_string_list(proposal, "scope", min_items=1)
              + _optional_string_list(proposal, "refactoring"))
    tasks = proposal.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        errors.append(FieldError("tasks", "at least one ordered task is required"))
    else:
        for index, task in enumerate(tasks):
            if not isinstance(task, dict):
                errors.append(FieldError(f"tasks[{index}]", "task must be an object"))
                continue
            task_errors = (_require_text(task, "title") + _require_string_list(task, "outputs", min_items=1)
                           + _require_text(task, "verification"))
            errors.extend(FieldError(f"tasks[{index}].{item.field}", item.message) for item in task_errors)
    assumptions = proposal.get("assumptions", [])
    if not isinstance(assumptions, list):
        errors.append(FieldError("assumptions", "assumptions must be a list"))
    else:
        for index, item in enumerate(assumptions):
            if not isinstance(item, dict):
                errors.append(FieldError(f"assumptions[{index}]", "assumption must record a decision and its basis"))
                continue
            errors.extend(FieldError(f"assumptions[{index}].{error.field}", error.message)
                          for error in _require_text(item, "decision") + _require_text(item, "basis"))
    if not isinstance(proposal.get("reason", ""), str):
        errors.append(FieldError("reason", "reason must be a string"))
    return errors


def _accept_plan(proposal: dict[str, Any], projection: RunProjection) -> ProposalDecision:
    contract_hash = current_contract_hash(projection)
    if contract_hash is None or proposal["effective_contract_hash"] != contract_hash:
        return ProposalDecision(False, [FieldError("effective_contract_hash", "plan must reference the current effective contract")])
    previous = projection.engineering_plans[-1] if projection.engineering_plans else None
    reason = proposal.get("reason", "").strip()
    if previous is not None and not reason:
        return ProposalDecision(False, [FieldError("reason", "an adjusted plan must explain the change from the previous plan")])
    try:
        scope = list(dict.fromkeys(normalize_scope(item) for item in proposal["scope"]))
    except ValueError as exc:
        return ProposalDecision(False, [FieldError("scope", str(exc))])
    payload = {
        "effective_contract_hash": contract_hash, "objective": proposal["objective"].strip(), "scope": scope,
        "tasks": [{"title": task["title"].strip(), "outputs": [item.strip() for item in task["outputs"]],
                   "verification": task["verification"].strip()} for task in proposal["tasks"]],
        "refactoring": [item.strip() for item in proposal.get("refactoring", [])],
        "assumptions": [{"decision": item["decision"].strip(), "basis": item["basis"].strip()}
                        for item in proposal.get("assumptions", [])], "reason": reason,
    }
    parent = previous.content_hash if previous else None
    revision = len(projection.engineering_plans) + 1
    return ProposalDecision(True, artifact={
        **payload, "kind": "engineering_plan", "issuer": "engineering", "parent_hash": parent,
        "revision": revision, "status": "active",
        "content_hash": spec_content_hash("engineering_plan", payload, parent_hash=parent, revision=revision),
    })


def _accept_product_spec(phase: str, proposal: dict[str, Any], projection: RunProjection) -> ProposalDecision:
    parent = projection.product_spec.content_hash if projection.product_spec else None
    revision = (projection.product_spec.revision + 1) if projection.product_spec else 1
    payload = _product_payload(proposal)
    artifact = {
        **payload,
        "kind": "product_spec",
        "issuer": "product",
        "parent_hash": parent,
        "revision": revision,
        "status": "active",
        "content_hash": spec_content_hash("product_spec", payload, parent_hash=parent, revision=revision),
    }
    if phase in {"PRODUCT_SPEC", "REWORK_PRODUCT"}:
        transitions = [(phase, "ENGINEERING")]
        return ProposalDecision(True, artifact=artifact, transitions=transitions)
    return ProposalDecision(False, [FieldError("kind", "product_spec not expected")])


def _accept_ask(proposal: dict[str, Any], projection: RunProjection) -> ProposalDecision:
    if projection.product_spec is None or projection.effective_contract is None:
        return ProposalDecision(False, [FieldError("effective_contract", "no active effective contract")])
    if projection.pending_ask is not None:
        return ProposalDecision(False, [FieldError("ask", "an AskRequest is already pending")])
    parent = projection.asks[-1].content_hash if projection.asks else None
    revision = len(projection.asks) + 1
    payload = {
        "question": proposal["question"].strip(),
        "background": proposal["background"].strip(),
        "options": [item.strip() for item in proposal["options"]],
        "impact": proposal["impact"].strip(),
        "recommendation": proposal["recommendation"].strip(),
        "decide_fields": [item.strip() for item in proposal["decide_fields"]],
        "product_spec_hash": projection.product_spec.content_hash,
        "effective_contract_hash": projection.effective_contract.content_hash,
    }
    artifact = {
        **payload,
        "kind": "ask_request",
        "issuer": "engineering",
        "parent_hash": parent,
        "revision": revision,
        "status": "open",
        "content_hash": spec_content_hash("ask_request", payload, parent_hash=parent, revision=revision),
    }
    from_phase = projection.phase if projection.phase in {"ENGINEERING", "REWORK_ENGINEERING"} else "ENGINEERING"
    return ProposalDecision(
        True,
        artifact=artifact,
        transitions=[(from_phase, "ASK_PRODUCT"), ("ASK_PRODUCT", "PRODUCT_REACT")],
    )


def _accept_reaction(proposal: dict[str, Any], projection: RunProjection) -> ProposalDecision:
    if projection.pending_ask is None:
        return ProposalDecision(False, [FieldError("ask", "no pending AskRequest")])
    if projection.pending_ask.effective_contract_hash != current_contract_hash(projection):
        return ProposalDecision(False, [FieldError("effective_contract_hash", "the pending request refers to an obsolete effective contract")])
    spec_update = proposal.get("spec_update")
    if spec_update == {}:
        spec_update = None
    new_spec = None
    if spec_update:
        nested = dict(spec_update)
        nested["kind"] = "product_spec"
        new_spec = _accept_product_spec("PRODUCT_SPEC", nested, projection).artifact
    payload = {
        "ask_id": projection.pending_ask.id,
        "ask_hash": projection.pending_ask.content_hash,
        "decision": proposal["decision"],
        "rationale": proposal["rationale"].strip(),
        "produces_new_spec": new_spec is not None,
        "new_spec_hash": None if new_spec is None else new_spec["content_hash"],
    }
    parent = projection.reactions[-1].content_hash if projection.reactions else None
    revision = len(projection.reactions) + 1
    artifact = {
        **payload,
        "kind": "product_reaction",
        "issuer": "product",
        "parent_hash": parent,
        "revision": revision,
        "status": "active",
        "content_hash": spec_content_hash("product_reaction", payload, parent_hash=parent, revision=revision),
        "spec_update": new_spec,
    }
    return ProposalDecision(
        True,
        artifact=artifact,
        transitions=[("PRODUCT_REACT", "ENGINEERING")],
        extra={"new_spec": new_spec},
    )


def _accept_delivery(proposal: dict[str, Any], projection: RunProjection, snapshot: WorkspaceSnapshot) -> ProposalDecision:
    if projection.product_spec is None:
        return ProposalDecision(False, [FieldError("product_spec", "no active ProductSpec")])
    contract = projection.effective_contract
    plan = projection.engineering_plan
    if contract is None or plan is None or plan.effective_contract_hash != contract.content_hash:
        return ProposalDecision(False, [FieldError("engineering_plan", "delivery requires an accepted plan for the current effective contract")])
    errors: list[FieldError] = []
    files = [item.replace("\\", "/") for item in proposal["files"]]
    for rel in files:
        if not snapshot.has_file(rel):
            errors.append(FieldError("files", f"missing workspace file: {rel}"))
    checks = []
    for name in proposal["check_names"]:
        receipt = snapshot.latest_check(
            "engineering",
            name,
            product_spec_hash=projection.product_spec.content_hash,
            effective_contract_hash=contract.content_hash,
            engineering_plan_hash=plan.content_hash,
            activation_id=projection.last_activations.get("engineering"),
        )
        if receipt is None:
            errors.append(
                FieldError(
                    "check_names",
                    f"no engineering check receipt for {name} bound to the current snapshot, effective contract, plan, and activation",
                )
            )
            continue
        checks.append(_receipt_evidence(receipt))
    if errors:
        return ProposalDecision(False, errors)
    previous = projection.delivery_specs[-1] if projection.delivery_specs else None
    parent = previous.content_hash if previous else None
    revision = (previous.revision + 1) if previous else 1
    payload = {
        "summary": proposal["summary"].strip(),
        "files": files,
        "check_names": list(proposal["check_names"]),
        "checks": checks,
        "known_risks": [item.strip() for item in proposal.get("known_risks", [])],
        "product_spec_hash": projection.product_spec.content_hash,
        "effective_contract_hash": contract.content_hash,
        "engineering_plan_hash": plan.content_hash,
        "code_tree_digest": snapshot.digest,
    }
    artifact = {
        **payload,
        "kind": "delivery_spec",
        "issuer": "engineering",
        "parent_hash": parent,
        "revision": revision,
        "status": "active",
        "content_hash": spec_content_hash("delivery_spec", payload, parent_hash=parent, revision=revision),
        "file_refs": [],
    }
    from_phase = projection.phase if projection.phase in {"ENGINEERING", "REWORK_ENGINEERING"} else "ENGINEERING"
    return ProposalDecision(
        True,
        artifact=artifact,
        transitions=[(from_phase, "DELIVERY"), ("DELIVERY", "QUALITY")],
    )


def _accept_review(proposal: dict[str, Any], projection: RunProjection, snapshot: WorkspaceSnapshot) -> ProposalDecision:
    if projection.product_spec is None:
        return ProposalDecision(False, [FieldError("product_spec", "no active ProductSpec")])
    if projection.delivery_spec is None:
        return ProposalDecision(False, [FieldError("delivery_spec", "no active DeliverySpec")])
    contract = projection.effective_contract
    plan = projection.engineering_plan
    if contract is None or plan is None:
        return ProposalDecision(False, [FieldError("effective_contract", "quality review requires a current contract and plan")])
    errors: list[FieldError] = []
    if projection.delivery_spec.product_spec_hash != projection.product_spec.content_hash:
        errors.append(FieldError("product_spec_hash", "delivery is not bound to the current ProductSpec"))
    if projection.delivery_spec.effective_contract_hash != contract.content_hash:
        errors.append(FieldError("effective_contract_hash", "delivery is not bound to the current effective contract"))
    if projection.delivery_spec.engineering_plan_hash != plan.content_hash:
        errors.append(FieldError("engineering_plan_hash", "delivery is not bound to the current engineering plan"))
    if projection.delivery_spec.code_tree_digest != snapshot.digest:
        errors.append(FieldError("code_snapshot_hash", "workspace snapshot no longer matches the current delivery"))
    check_names, name_errors = _qa_check_names(proposal)
    errors.extend(name_errors)
    bound_checks = []
    for name in check_names:
        receipt = snapshot.latest_check(
            "quality",
            name,
            product_spec_hash=projection.product_spec.content_hash,
            effective_contract_hash=contract.content_hash,
            engineering_plan_hash=plan.content_hash,
            delivery_spec_hash=projection.delivery_spec.content_hash,
            activation_id=projection.last_activations.get("quality"),
        )
        if receipt is None:
            errors.append(
                FieldError(
                    "checks",
                    f"quality must run {name} against the current snapshot, ProductSpec, and DeliverySpec in this activation; prior receipts are not reused",
                )
            )
            continue
        bound_checks.append(_receipt_evidence(receipt))
    verdict = proposal["verdict"]
    if verdict == "release":
        if any(item["exit_code"] != 0 for item in bound_checks):
            errors.append(FieldError("checks", "release requires all quality checks to exit 0"))
        if not bound_checks:
            errors.append(FieldError("checks", "release requires quality-run evidence bound to the current snapshot"))
    defects, defect_errors = _qa_defects(proposal)
    errors.extend(defect_errors)
    if errors:
        return ProposalDecision(False, errors)
    parent = projection.last_review.content_hash if projection.last_review else None
    revision = (projection.last_review.revision + 1) if projection.last_review else 1
    payload = {
        "product_spec_hash": projection.product_spec.content_hash,
        "effective_contract_hash": contract.content_hash,
        "engineering_plan_hash": plan.content_hash,
        "delivery_spec_hash": projection.delivery_spec.content_hash,
        "code_snapshot_hash": snapshot.digest,
        "verdict": verdict,
        "rationale": proposal["rationale"].strip(),
        "checks": bound_checks,
        "defects": defects,
        "evidence_refs": [],
    }
    artifact = {
        **payload,
        "kind": "qa_review",
        "issuer": "quality",
        "parent_hash": parent,
        "revision": revision,
        "status": "active",
        "content_hash": spec_content_hash("qa_review", payload, parent_hash=parent, revision=revision),
    }
    if verdict == "release":
        transitions = [("QUALITY", "DONE")]
    elif verdict == "rework_product":
        transitions = [("QUALITY", "REWORK_PRODUCT"), ("REWORK_PRODUCT", "PRODUCT_SPEC")]
    else:
        transitions = [("QUALITY", "REWORK_ENGINEERING"), ("REWORK_ENGINEERING", "ENGINEERING")]
    return ProposalDecision(True, artifact=artifact, transitions=transitions)


def _product_payload(proposal: dict[str, Any]) -> dict[str, Any]:
    return {
        "goal": proposal["goal"].strip(),
        "requirements": [item.strip() for item in proposal["requirements"]],
        "boundaries": [item.strip() for item in proposal.get("boundaries", [])],
        "constraints": [item.strip() for item in proposal.get("constraints", [])],
        "acceptance_criteria": [item.strip() for item in proposal["acceptance_criteria"]],
        "fatal_conditions": [item.strip() for item in proposal.get("fatal_conditions", [])],
        "non_goals": [item.strip() for item in proposal.get("non_goals", [])],
    }


def _receipt_evidence(receipt: Any) -> dict[str, Any]:
    return {
        "activation_id": receipt.activation_id,
        "delivery_spec_hash": receipt.delivery_spec_hash,
        "exit_code": receipt.exit_code,
        "name": receipt.name,
        "product_spec_hash": receipt.product_spec_hash,
        "effective_contract_hash": receipt.effective_contract_hash,
        "engineering_plan_hash": receipt.engineering_plan_hash,
        "snapshot_hash": receipt.snapshot_hash,
        "summary": receipt.summary,
    }


def _qa_check_name_errors(proposal: dict[str, Any]) -> list[FieldError]:
    return _qa_check_names(proposal)[1]


def _qa_check_names(proposal: dict[str, Any]) -> tuple[list[str], list[FieldError]]:
    raw = proposal["checks"] if "checks" in proposal else proposal.get("check_names", [])
    if raw is None or not isinstance(raw, list):
        return [], [FieldError("checks", "checks must be a list of names")]
    if not raw:
        return [], [FieldError("checks", "at least one check name is required")]
    names: list[str] = []
    errors: list[FieldError] = []
    for index, item in enumerate(raw):
        if not isinstance(item, str) or not item.strip():
            errors.append(FieldError(f"checks[{index}]", "check name must be a non-empty string"))
            continue
        names.append(item.strip())
    return names, errors


def _qa_defects_errors(proposal: dict[str, Any]) -> list[FieldError]:
    return _qa_defects(proposal)[1]


def _qa_defects(proposal: dict[str, Any]) -> tuple[list[dict[str, str]], list[FieldError]]:
    if "defects" not in proposal:
        return [], []
    raw = proposal.get("defects")
    if raw is None or not isinstance(raw, list):
        return [], [FieldError("defects", "defects must be a list")]
    defects: list[dict[str, str]] = []
    errors: list[FieldError] = []
    for index, defect in enumerate(raw):
        if not isinstance(defect, dict):
            errors.append(FieldError(f"defects[{index}]", "defect must be an object"))
            continue
        summary = defect.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            errors.append(FieldError(f"defects[{index}].summary", "defect summary is required"))
        severity = defect.get("severity")
        if severity not in {"blocker", "major", "minor"}:
            errors.append(FieldError(f"defects[{index}].severity", "severity must be blocker, major, or minor"))
        if isinstance(summary, str) and summary.strip() and severity in {"blocker", "major", "minor"}:
            defects.append({"severity": severity, "summary": summary.strip()})
    return defects, errors


def _require_text(payload: dict[str, Any], field: str) -> list[FieldError]:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        return [FieldError(field, f"{field} must be a non-empty string")]
    return []


def _require_string_list(payload: dict[str, Any], field: str, *, min_items: int) -> list[FieldError]:
    value = payload.get(field)
    if not isinstance(value, list) or len(value) < min_items:
        return [FieldError(field, f"{field} must contain at least {min_items} item(s)")]
    if any(not isinstance(item, str) or not item.strip() for item in value):
        return [FieldError(field, f"{field} items must be non-empty strings")]
    return []


def _optional_string_list(payload: dict[str, Any], field: str) -> list[FieldError]:
    if field not in payload or payload[field] is None:
        payload[field] = []
        return []
    value = payload[field]
    if not isinstance(value, list):
        return [FieldError(field, f"{field} must be a list")]
    if any(not isinstance(item, str) or not item.strip() for item in value):
        return [FieldError(field, f"{field} items must be non-empty strings")]
    return []
