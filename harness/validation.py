"""提案 schema、权限、前置条件和绑定校验。控制层普通代码，不调用模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import current_contract_hash, normalize_scope
from .collaboration import (
    allowed_proposal_kinds, guidance_bound_result_ids, guidance_response_errors, request_basis,
    request_errors, response_errors, resume_phase,
)
from .models import (
    DEPARTMENTS,
    PROPOSAL_KINDS,
    QA_VERDICTS,
    Event,
    canonical_hash,
    spec_content_hash,
)
from .projection import RunProjection
from .workspace import WorkspaceSnapshot

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
    events: list[Event] | None = None,
) -> ProposalDecision:
    try:
        return _evaluate_proposal(
            phase=phase,
            department=department,
            proposal=proposal,
            projection=projection,
            snapshot=snapshot,
            events=events or [],
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
    events: list[Event],
) -> ProposalDecision:
    if not proposal or not isinstance(proposal, dict):
        return ProposalDecision(False, [FieldError("proposal", "structured proposal is required; natural language cannot change state")])
    kind = proposal.get("kind")
    if kind not in PROPOSAL_KINDS:
        return ProposalDecision(False, [FieldError("kind", f"unknown proposal kind: {kind!r}")])
    if department not in DEPARTMENTS:
        return ProposalDecision(False, [FieldError("issuer", f"unknown department: {department}")])
    allowed = allowed_proposal_kinds(projection, department)
    if kind not in allowed:
        return ProposalDecision(False, [FieldError("kind", f"{department} cannot issue {kind} in the current work")])

    errors = _validate_schema(kind, proposal)
    if errors:
        return ProposalDecision(False, errors)

    if kind == "product_spec":
        return _accept_product_spec(phase, proposal, projection)
    if kind == "engineering_plan":
        return _accept_plan(proposal, projection)
    if kind == "collaboration_request":
        return _accept_request(proposal, projection, department)
    if kind == "collaboration_response":
        return _accept_response(proposal, projection, department, events, snapshot)
    if kind == "department_guidance_response":
        return _accept_guidance_response(proposal, projection, department, events, snapshot)
    if kind == "product_decision":
        return _accept_product_decision(proposal, projection)
    if kind == "delivery_spec":
        return _accept_delivery(proposal, projection, snapshot)
    if kind == "qa_review":
        return _accept_review(proposal, projection, snapshot)
    return ProposalDecision(False, [FieldError("kind", "unhandled kind")])


def _validate_schema(kind: str, proposal: dict[str, Any]) -> list[FieldError]:
    if kind in {"collaboration_request", "collaboration_response"}:
        return []
    if kind == "department_guidance_response":
        errors = _require_text(proposal, "guidance_id") + _require_text(proposal, "text")
        if proposal.get("status") not in {"explained", "completed", "declined", "needs_work"}:
            errors.append(FieldError("status", "status must be explained, completed, declined, or needs_work"))
        return errors
    if kind == "product_decision":
        return _require_text(proposal, "statement") + _require_text(proposal, "rationale")
    if kind == "engineering_plan":
        return _plan_schema_errors(proposal)
    if kind == "product_spec":
        return _require_text(proposal, "goal") + _require_string_list(proposal, "requirements", min_items=1) + _require_string_list(
            proposal, "acceptance_criteria", min_items=1
        ) + _optional_string_list(proposal, "boundaries") + _optional_string_list(proposal, "constraints") + _optional_string_list(
            proposal, "fatal_conditions"
        ) + _optional_string_list(proposal, "non_goals") + _decision_change_errors(proposal) + _change_record_errors(proposal)
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
    allowed = {"kind", "objective", "scope", "tasks", "refactoring", "assumptions", "reason"}
    errors = [FieldError(str(key), "unknown field") for key in proposal if key not in allowed]
    errors.extend(_require_text(proposal, "objective")
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
    if contract_hash is None:
        return ProposalDecision(False, [FieldError("effective_contract", "plan requires a current effective contract")])
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


def _accept_guidance_response(proposal: dict[str, Any], projection: RunProjection,
                              department: str, events: list[Event],
                              snapshot: WorkspaceSnapshot) -> ProposalDecision:
    guidance = next((item for item in projection.department_guidance
                     if item.id == proposal.get("guidance_id")), None)
    if guidance is None or guidance.department != department:
        return ProposalDecision(False, [FieldError("guidance_id", "guidance must belong to the current department and run")])
    if guidance.status not in {"received", "in_input"}:
        return ProposalDecision(False, [FieldError("guidance_id", "guidance has already been responded to")])
    text = proposal.get("text")
    if not isinstance(text, str) or not text.strip():
        return ProposalDecision(False, [FieldError("text", "text must be a non-empty string")])
    errors = guidance_response_errors(proposal, projection, department, events, snapshot_hash=snapshot.digest)
    if errors:
        return ProposalDecision(False, [FieldError(**item) for item in errors])
    payload = {
        "guidance_id": guidance.id,
        "guidance_version": guidance.version,
        "guidance_created_event_id": guidance.created_event_id,
        "department": department,
        "status": proposal["status"],
        "text": text.strip(),
        "result_event_ids": guidance_bound_result_ids(
            proposal, projection, department, events, snapshot_hash=snapshot.digest, guidance=guidance,
        ),
    }
    return ProposalDecision(True, artifact={
        **payload,
        "kind": "department_guidance_response",
        "issuer": department,
        "content_hash": canonical_hash(payload),
    })


def _accept_product_spec(phase: str, proposal: dict[str, Any], projection: RunProjection) -> ProposalDecision:
    if projection.input_version != projection.product_work_input_version:
        return ProposalDecision(False, [FieldError("input_version", "new user input must enter product work before requirements can be accepted")])
    if projection.product_spec is not None and proposal.get("change_record") is None:
        return ProposalDecision(False, [FieldError("change_record", "a revised ProductSpec must explain changed, retained, and retired behavior and its rationale")])
    active_hashes = {item.content_hash for item in projection.effective_decisions}
    changes = proposal.get("decision_changes", [])
    declared = [item["decision_hash"] for item in changes]
    if set(declared) != active_hashes or len(declared) != len(active_hashes):
        return ProposalDecision(False, [FieldError("decision_changes", "explicitly retain, integrate, or retire every current product decision exactly once")])
    parent = projection.product_spec.content_hash if projection.product_spec else None
    revision = (projection.product_spec.revision + 1) if projection.product_spec else 1
    payload = _product_payload(proposal)
    payload["input_version"] = projection.input_version
    artifact = {
        **payload,
        "kind": "product_spec",
        "issuer": "product",
        "parent_hash": parent,
        "revision": revision,
        "status": "active",
        "content_hash": spec_content_hash("product_spec", payload, parent_hash=parent, revision=revision),
    }
    if projection.pending_request is not None:
        return ProposalDecision(True, artifact=artifact)
    if phase in {"PRODUCT_SPEC", "REWORK_PRODUCT"}:
        transitions = [(phase, "ENGINEERING")]
        return ProposalDecision(True, artifact=artifact, transitions=transitions)
    has_product_guidance = any(
        item.department == "product" and item.status in {"received", "in_input"}
        for item in projection.department_guidance
    )
    if has_product_guidance:
        return ProposalDecision(True, artifact=artifact)
    return ProposalDecision(False, [FieldError("kind", "product_spec not expected")])


def _accept_request(proposal: dict[str, Any], projection: RunProjection, department: str) -> ProposalDecision:
    errors = request_errors(proposal, projection, department)
    if errors:
        return ProposalDecision(False, [FieldError(**item) for item in errors])
    payload = {"requester": department, "recipient": proposal["recipient"], "request_type": proposal["request_type"],
               "action": proposal.get("action"), "question": proposal["question"].strip(),
               "background": proposal["background"].strip(), "expected_result": proposal["expected_result"].strip(),
               "basis": request_basis(projection), "return_phase": projection.phase, "status": "open"}
    return ProposalDecision(True, artifact={**payload, "kind": "collaboration_request", "content_hash": canonical_hash(payload)})


def _accept_response(proposal: dict[str, Any], projection: RunProjection, department: str,
                     events: list[Event], snapshot: WorkspaceSnapshot) -> ProposalDecision:
    errors = response_errors(proposal, projection, department, events, snapshot_hash=snapshot.digest)
    if errors:
        return ProposalDecision(False, [FieldError(**item) for item in errors])
    phase, valid = resume_phase(projection.pending_request, projection, events, snapshot_hash=snapshot.digest)
    payload = {"request_id": projection.pending_request.id, "status": proposal["status"], "text": proposal["text"].strip(),
               "result_event_ids": list(proposal.get("result_event_ids", [])), "return_phase": phase, "return_work_valid": valid}
    return ProposalDecision(True, artifact={**payload, "kind": "collaboration_response", "content_hash": canonical_hash(payload)})


def _accept_product_decision(proposal: dict[str, Any], projection: RunProjection) -> ProposalDecision:
    if projection.product_spec is None:
        return ProposalDecision(False, [FieldError("product_spec", "a product decision requires an active ProductSpec")])
    payload = {"statement": proposal["statement"].strip(), "rationale": proposal["rationale"].strip(),
               "product_spec_hash": projection.product_spec.content_hash,
               "request_id": None if projection.pending_request is None else projection.pending_request.id}
    content_hash = canonical_hash(payload)
    if any(item.content_hash == content_hash for item in projection.product_decisions):
        return ProposalDecision(False, [FieldError("statement", "this product decision has already been accepted")])
    transitions = [] if projection.pending_request else [(projection.phase, "ENGINEERING")]
    return ProposalDecision(True, artifact={**payload, "kind": "product_decision", "content_hash": content_hash}, transitions=transitions)


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
    }
    from_phase = projection.phase if projection.phase in {"ENGINEERING", "REWORK_ENGINEERING"} else "ENGINEERING"
    return ProposalDecision(
        True,
        artifact=artifact,
        transitions=[] if projection.pending_request else [(from_phase, "DELIVERY"), ("DELIVERY", "QUALITY")],
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
        pending_guidance = [item.id for item in projection.department_guidance
                            if item.status in {"received", "in_input"}]
        if pending_guidance:
            errors.append(FieldError("guidance", "release requires all received department guidance to have a recorded response"))
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
        "decision_changes": [{"decision_hash": item["decision_hash"], "disposition": item["disposition"],
                              "rationale": item["rationale"].strip()} for item in proposal.get("decision_changes", [])],
        "change_record": None if proposal.get("change_record") is None else {
            **{field: [item.strip() for item in proposal["change_record"][field]] for field in ("changed", "retained", "retired")},
            "rationale": proposal["change_record"]["rationale"].strip(),
        },
    }


def _change_record_errors(proposal: dict[str, Any]) -> list[FieldError]:
    record = proposal.get("change_record")
    if record is None:
        return []
    if not isinstance(record, dict):
        return [FieldError("change_record", "change_record must describe changed, retained, and retired behavior and rationale")]
    errors = _require_text(record, "rationale")
    for field in ("changed", "retained", "retired"):
        errors.extend(_require_string_list(record, field, min_items=0))
    return [FieldError(f"change_record.{item.field}", item.message) for item in errors]


def _decision_change_errors(proposal: dict[str, Any]) -> list[FieldError]:
    changes = proposal.get("decision_changes", [])
    if not isinstance(changes, list):
        return [FieldError("decision_changes", "decision_changes must be a list")]
    errors = []
    for index, item in enumerate(changes):
        if not isinstance(item, dict):
            errors.append(FieldError(f"decision_changes[{index}]", "each earlier decision requires a disposition and rationale"))
            continue
        errors.extend(FieldError(f"decision_changes[{index}].{error.field}", error.message)
                      for error in _require_text(item, "decision_hash") + _require_text(item, "rationale"))
        if item.get("disposition") not in {"retain", "integrate", "retire"}:
            errors.append(FieldError(f"decision_changes[{index}].disposition", "disposition must be retain, integrate, or retire"))
    return errors


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
