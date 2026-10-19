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
    BASELINE_STATUSES,
    DEPARTMENTS,
    PROPOSAL_KINDS,
    QA_VERDICTS,
    Event,
    ProductSpec,
    canonical_hash,
    spec_content_hash,
)
from .actions import TreeFacts
from .definitions import DEFINITIONS
from .projection import RunProjection

# 建档初始 PRD 的边界条目用它标明「设计与需求文档描述而代码尚未实现」（设计第 4.2、4.3 节）。
# 这样的条目不是现有行为：质检不把它记为现有缺陷。
DESIGN_PENDING_MARK = "设计中，未实施"


def marked_boundaries(spec: ProductSpec | None) -> list[str]:
    # 带标记的边界条目（工单 #346）：条目文字含标记串
    return [] if spec is None else [item for item in spec.boundaries if DESIGN_PENDING_MARK in item]


def _covers_marked_boundary(requirement: str, spec: ProductSpec | None) -> bool:
    # 结论指向的要求与某条带标记的边界条目是同一项能力：条目可以带说明文字，两者方向都可能是包含
    return any(item == requirement or item in requirement or requirement in item
               for item in marked_boundaries(spec))


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
    facts: TreeFacts,
    events: list[Event] | None = None,
) -> ProposalDecision:
    try:
        return _evaluate_proposal(
            phase=phase,
            department=department,
            proposal=proposal,
            projection=projection,
            facts=facts,
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
    facts: TreeFacts,
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
    if kind == "collaboration_request":
        return _accept_request(proposal, projection, department)
    if kind == "collaboration_response":
        return _accept_response(proposal, projection, department, events, facts)
    if kind == "department_guidance_response":
        return _accept_guidance_response(proposal, projection, department, events, facts)
    if kind == "product_decision":
        return _accept_product_decision(proposal, projection)
    if kind == "delivery_spec":
        return _accept_delivery(proposal, projection, facts)
    if kind == "qa_review":
        return _accept_review(proposal, projection, facts)
    if kind == "structure":
        return _accept_structure(proposal, projection, facts)
    if kind == "baseline_review":
        return _accept_baseline_review(proposal, projection, facts)
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
    if kind == "structure":
        return _structure_schema_errors(proposal)
    if kind == "baseline_review":
        return _baseline_review_schema_errors(proposal)
    return [FieldError("kind", "unknown kind")]




def _structure_schema_errors(proposal: dict[str, Any]) -> list[FieldError]:
    # submit_structure 的参数形状（definitions/tools.json）：五组必填，约定与注意事项可省略
    allowed = {"kind", "overall", "modules", "entry_points", "build_and_test", "requirement_locations", "conventions"}
    errors = [FieldError(str(key), "unknown field") for key in proposal if key not in allowed]
    errors.extend(_require_text(proposal, "overall"))
    errors.extend(_record_list_errors(proposal, "modules", {"path", "responsibility"}, ("path", "responsibility")))
    entry_errors = _record_list_errors(proposal, "entry_points", {"kind", "path", "how_to_run"}, ("kind", "path", "how_to_run"))
    for index, item in enumerate(proposal.get("entry_points", [])):
        if isinstance(item, dict) and item.get("kind") not in {"program", "command_line", "service"}:
            entry_errors.append(FieldError(f"entry_points[{index}].kind", "kind must be program, command_line, or service"))
    errors.extend(entry_errors)
    errors.extend(_record_list_errors(proposal, "build_and_test", {"name", "command", "purpose"}, ("name", "purpose")))
    for index, item in enumerate(proposal.get("build_and_test", [])):
        if isinstance(item, dict):
            errors.extend(FieldError(f"build_and_test[{index}].command", error.message)
                          for error in _require_text(item, "command"))
    errors.extend(_record_list_errors(proposal, "requirement_locations", {"requirement", "locations"},
                                      ("requirement",)))
    for index, item in enumerate(proposal.get("requirement_locations", [])):
        if isinstance(item, dict):
            errors.extend(FieldError(f"requirement_locations[{index}].{error.field}", error.message)
                          for error in _require_string_list(item, "locations", min_items=1))
    for field in ("modules", "entry_points", "build_and_test", "requirement_locations"):
        value = proposal.get(field)
        if isinstance(value, list) and not value:
            errors.append(FieldError(field, f"{field} must contain at least one entry"))
    return errors + _optional_string_list(proposal, "conventions")


def _baseline_review_schema_errors(proposal: dict[str, Any]) -> list[FieldError]:
    # submit_baseline_review 的参数形状（definitions/tools.json）：结论必填，遗漏与其他失败可省略
    allowed = {"kind", "verdict", "conclusions", "omissions", "checks", "other_failures"}
    errors = [FieldError(str(key), "unknown field") for key in proposal if key not in allowed]
    if proposal.get("verdict") not in {"consistent", "rework_product"}:
        errors.append(FieldError("verdict", "verdict must be consistent or rework_product"))
    errors.extend(_record_list_errors(proposal, "conclusions", {"requirement", "status", "evidence"},
                                     ("requirement", "status", "evidence")))
    for index, item in enumerate(proposal.get("conclusions", [])):
        if isinstance(item, dict) and item.get("status") not in BASELINE_STATUSES:
            errors.append(FieldError(f"conclusions[{index}].status",
                                     "status must be verified, read_only, existing_defect, or unsupported"))
    conclusions = proposal.get("conclusions")
    if isinstance(conclusions, list) and not conclusions:
        errors.append(FieldError("conclusions", "conclusions must cover every requirement of the initial PRD"))
    errors.extend(_qa_check_name_errors(proposal))
    errors.extend(_record_list_errors(proposal, "omissions", {"capability", "location"}, ("capability", "location"),
                                      required_field=False))
    errors.extend(_record_list_errors(proposal, "other_failures", {"check", "reason"}, ("check", "reason"),
                                      required_field=False))
    return errors


def _record_list_errors(proposal: dict[str, Any], field: str, allowed: set[str], texts: tuple[str, ...],
                       *, required_field: bool = True) -> list[FieldError]:
    # 对象清单的通用形状校验：多余的字段名、必填的文字字段；argv 与 locations 这类字符串清单由调用方另行校验
    value = proposal.get(field)
    if value is None and not required_field:
        if field in proposal:
            proposal[field] = []
        return []
    if not isinstance(value, list):
        return [FieldError(field, f"{field} must be a list of objects")]
    errors: list[FieldError] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(FieldError(f"{field}[{index}]", f"{field} items must be objects"))
            continue
        errors.extend(FieldError(f"{field}[{index}].{key}", "unknown field")
                      for key in item if key not in allowed)
        for name in texts:
            errors.extend(FieldError(f"{field}[{index}].{error.field}", error.message)
                          for error in _require_text(item, name))
    return errors


def _unchanged_tree_errors(projection: RunProjection, facts: TreeFacts) -> list[FieldError]:
    # 建档事项中部门没有写入工具，工作区的树摘要必须始终等于快照摘要（设计第 4.1、10 节第 6 项）
    snapshot = projection.snapshot
    if snapshot is None:
        return [FieldError("snapshot", "an onboarding proposal requires the code snapshot recorded when the run was created")]
    if facts.digest != snapshot["tree_digest"]:
        return [FieldError("code_snapshot_hash",
                           f"the workspace tree {facts.digest} no longer matches the snapshot {snapshot['tree_digest']}")]
    return []


def _location_errors(field: str, values: list[Any], facts: TreeFacts) -> list[FieldError]:
    # 结构说明里写出的位置必须是工作区公开树中真实存在的路径（文件或目录前缀）
    errors: list[FieldError] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            errors.append(FieldError(field, "locations must be non-empty workspace-relative strings"))
            continue
        try:
            relative = normalize_scope(value)
        except ValueError:
            errors.append(FieldError(field, f"invalid workspace location: {value!r}"))
            continue
        errors.extend([] if _location_known(relative, facts) else
                      [FieldError(field, f"unknown workspace location: {value!r}")])
    return errors


def _location_known(relative: str, facts: TreeFacts) -> bool:
    if relative == ".":
        return True
    if relative.endswith("/"):
        return any(item.startswith(relative) for item in facts.files)
    return any(item == relative or item.startswith(relative + "/") for item in facts.files)


def _baseline_conclusions(proposal: dict[str, Any], spec: ProductSpec, bound: dict[str, dict[str, Any]],
                         facts: TreeFacts) -> tuple[list[dict[str, str]], list[FieldError]]:
    # 逐条结论覆盖初始 PRD 的每条要求，不许多也不重复；依据按状态检查（设计第 4.5 节）
    requirements = [item.strip() for item in spec.requirements]
    declared = [item["requirement"].strip() for item in proposal["conclusions"]]
    errors: list[FieldError] = []
    if len(declared) != len(set(declared)):
        errors.append(FieldError("conclusions", "each requirement may carry only one conclusion"))
    if set(declared) != set(requirements):
        missing = [item for item in requirements if item not in declared]
        extra = [item for item in declared if item not in requirements]
        errors.append(FieldError(
            "conclusions",
            "conclusions must cover every requirement of the current ProductSpec exactly once; "
            f"missing: {missing or 'none'}; not in the current ProductSpec: {extra or 'none'}",
        ))
    conclusions: list[dict[str, str]] = []
    for index, item in enumerate(proposal["conclusions"]):
        requirement, status, evidence = item["requirement"].strip(), item["status"], item["evidence"].strip()
        field = f"conclusions[{index}].evidence"
        if status == "verified":
            errors.extend(_check_evidence_error(field, evidence, bound, expect_exit=0,
                                                label="verified requires evidence naming a passing baseline check"))
        elif status == "read_only":
            if not _location_known(evidence.replace("\\", "/"), facts):
                errors.append(FieldError(field, "read_only requires evidence naming a location in the snapshot"))
        elif status == "existing_defect":
            # 带标记的边界条目不是现有行为（设计第 4.3 节）：要求文档描述而代码尚未实现的能力不记为现有缺陷
            if _covers_marked_boundary(requirement, spec):
                errors.append(FieldError(f"conclusions[{index}].status",
                                         f"a boundary entry marked {DESIGN_PENDING_MARK} is not existing behavior and cannot "
                                         "be an existing_defect; write it into the initial PRD boundaries with that mark"))
                continue
            errors.extend(_check_evidence_error(field, evidence, bound, expect_exit=None,
                                                label="existing_defect requires evidence naming a failing baseline check"))
        elif status == "unsupported":
            if evidence in bound:
                errors.append(FieldError(field, "unsupported must not name a baseline check; it states that nothing supports "
                                                "the requirement"))
            elif evidence.lower() in {"none", "n/a", "no basis", ""}:
                errors.append(FieldError(field, "unsupported must state why code, documentation and tests none of them support "
                                                 "the requirement"))
        conclusions.append({"requirement": requirement, "status": status, "evidence": evidence})
    return conclusions, errors


def _check_evidence_error(field: str, evidence: str, bound: dict[str, dict[str, Any]], *, expect_exit: int | None,
                         label: str) -> list[FieldError]:
    # 结论的依据指向本次激活中真实运行过的基线检查；verified 要求退出状态为 0，existing_defect 要求不为 0
    if evidence not in bound:
        if expect_exit is None:
            return [FieldError(field, "existing_defect requires evidence naming a baseline check run in this activation")]
        return [FieldError(field, label)]
    exit_code = bound[evidence]["exit_code"]
    if expect_exit is not None and exit_code != expect_exit:
        return [FieldError(field, f"check {evidence} exited {exit_code}; {label}")]
    if expect_exit is None and exit_code == 0:
        return [FieldError(field, f"check {evidence} exited 0; {label}")]
    return []


def _baseline_omission_records(proposal: dict[str, Any], facts: TreeFacts) -> tuple[list[dict[str, str]], list[FieldError]]:
    # 遗漏必须写出仓库中真实存在的所在
    errors: list[FieldError] = []
    records: list[dict[str, str]] = []
    for index, item in enumerate(proposal.get("omissions", [])):
        capability, location = item["capability"].strip(), item["location"].strip()
        records.append({"capability": capability, "location": location})
        errors.extend(_location_errors(f"omissions[{index}].location", [location], facts))
    return records, errors



def _accept_guidance_response(proposal: dict[str, Any], projection: RunProjection,
                              department: str, events: list[Event],
                              facts: TreeFacts) -> ProposalDecision:
    guidance = next((item for item in projection.department_guidance
                     if item.id == proposal.get("guidance_id")), None)
    if guidance is None or guidance.department != department:
        return ProposalDecision(False, [FieldError("guidance_id", "guidance must belong to the current department and run")])
    if guidance.status not in {"received", "in_input"}:
        return ProposalDecision(False, [FieldError("guidance_id", "guidance has already been responded to")])
    text = proposal.get("text")
    if not isinstance(text, str) or not text.strip():
        return ProposalDecision(False, [FieldError("text", "text must be a non-empty string")])
    errors = guidance_response_errors(proposal, projection, department, events, snapshot_hash=facts.digest)
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
            proposal, projection, department, events, snapshot_hash=facts.digest, guidance=guidance,
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
    current_hash = None if projection.product_spec is None else projection.product_spec.content_hash
    basis_errors = _basis_hash_errors(proposal, "basis_product_spec_hash", current_hash)
    if basis_errors:
        return ProposalDecision(False, basis_errors)
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
                     events: list[Event], facts: TreeFacts) -> ProposalDecision:
    errors = response_errors(proposal, projection, department, events, snapshot_hash=facts.digest)
    if errors:
        return ProposalDecision(False, [FieldError(**item) for item in errors])
    phase, valid = resume_phase(projection.pending_request, projection, events, snapshot_hash=facts.digest)
    # 发问方与回答方从对应请求取出，与请求里的值相同（工单 #275）
    payload = {"requester": projection.pending_request.requester, "recipient": projection.pending_request.recipient,
               "request_id": projection.pending_request.id, "status": proposal["status"], "text": proposal["text"].strip(),
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


def _accept_delivery(proposal: dict[str, Any], projection: RunProjection, facts: TreeFacts) -> ProposalDecision:
    if projection.product_spec is None:
        return ProposalDecision(False, [FieldError("product_spec", "no active ProductSpec")])
    contract = projection.effective_contract
    if contract is None:
        return ProposalDecision(False, [FieldError("effective_contract", "delivery requires a current effective contract")])
    errors: list[FieldError] = []
    errors.extend(_basis_hash_errors(proposal, "basis_product_spec_hash", projection.product_spec.content_hash))
    files = [item.replace("\\", "/") for item in proposal["files"]]
    for rel in files:
        if not facts.has_file(rel):
            errors.append(FieldError("files", f"missing workspace file: {rel}"))
    checks = []
    for name in proposal["check_names"]:
        receipt = facts.latest_check(
            "engineering",
            name,
            product_spec_hash=projection.product_spec.content_hash,
            effective_contract_hash=contract.content_hash,
            activation_id=projection.last_activations.get("engineering"),
        )
        if receipt is None:
            errors.append(
                FieldError(
                    "check_names",
                    f"no run_check receipt named {name} in this activation for the current snapshot and effective contract. "
                    f"Call run_check with the name {name} on the current workspace, then submit_delivery again; "
                    "bash results are action receipts and do not count as check receipts.",
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
        "code_tree_digest": facts.digest,
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


def _accept_review(proposal: dict[str, Any], projection: RunProjection, facts: TreeFacts) -> ProposalDecision:
    if projection.product_spec is None:
        return ProposalDecision(False, [FieldError("product_spec", "no active ProductSpec")])
    if projection.delivery_spec is None:
        return ProposalDecision(False, [FieldError("delivery_spec", "no active DeliverySpec")])
    contract = projection.effective_contract
    if contract is None:
        return ProposalDecision(False, [FieldError("effective_contract", "quality review requires a current contract")])
    errors: list[FieldError] = []
    errors.extend(_basis_hash_errors(proposal, "basis_delivery_spec_hash", projection.delivery_spec.content_hash))
    if projection.delivery_spec.product_spec_hash != projection.product_spec.content_hash:
        errors.append(FieldError("product_spec_hash", "delivery is not bound to the current ProductSpec"))
    if projection.delivery_spec.effective_contract_hash != contract.content_hash:
        errors.append(FieldError("effective_contract_hash", "delivery is not bound to the current effective contract"))
    if projection.delivery_spec.code_tree_digest != facts.digest:
        errors.append(FieldError("code_snapshot_hash", "workspace snapshot no longer matches the current delivery"))
    check_names, name_errors = _qa_check_names(proposal)
    errors.extend(name_errors)
    bound_checks = []
    for name in check_names:
        receipt = facts.latest_check(
            "quality",
            name,
            product_spec_hash=projection.product_spec.content_hash,
            effective_contract_hash=contract.content_hash,
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
        if any(item.get("qa_tests_hash") != projection.qa_tests_hash for item in bound_checks):
            errors.append(FieldError("checks", "测试材料已经改变，用当前的测试材料重新运行检查"))
    defects, defect_errors = _qa_defects(proposal)
    errors.extend(defect_errors)
    if errors:
        return ProposalDecision(False, errors)
    parent = projection.last_review.content_hash if projection.last_review else None
    revision = (projection.last_review.revision + 1) if projection.last_review else 1
    payload = {
        "product_spec_hash": projection.product_spec.content_hash,
        "effective_contract_hash": contract.content_hash,
        "delivery_spec_hash": projection.delivery_spec.content_hash,
        "code_snapshot_hash": facts.digest,
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


def _accept_structure(proposal: dict[str, Any], projection: RunProjection, facts: TreeFacts) -> ProposalDecision:
    # 现有结构说明（docs/design/existing-project-onboarding.md 第 4.4 节）：构建与测试的每一项都要有本次激活中
    # 绑定当前快照与当前初始 PRD 的 run_check 回执，退出状态照实记录（不要求为 0）；建档中工作区的树不变
    spec = projection.product_spec
    if spec is None:
        return ProposalDecision(False, [FieldError("product_spec", "no active ProductSpec")])
    errors = _unchanged_tree_errors(projection, facts)
    for index, item in enumerate(proposal["modules"]):
        errors.extend(_location_errors(f"modules[{index}].path", [item["path"]], facts))
    for index, item in enumerate(proposal["entry_points"]):
        errors.extend(_location_errors(f"entry_points[{index}].path", [item["path"]], facts))
    for index, item in enumerate(proposal["requirement_locations"]):
        errors.extend(_location_errors(f"requirement_locations[{index}].locations", item["locations"], facts))
    requirements = [item.strip() for item in spec.requirements]
    declared = [item["requirement"].strip() for item in proposal["requirement_locations"]]
    if len(declared) != len(set(declared)):
        errors.append(FieldError("requirement_locations", "each requirement may be recorded only once"))
    if set(declared) != set(requirements):
        missing = [item for item in requirements if item not in declared]
        extra = [item for item in declared if item not in requirements]
        errors.append(FieldError("requirement_locations",
                                 "requirement_locations must record every requirement of the current ProductSpec exactly once; "
                                 f"missing: {missing or 'none'}; not in the current ProductSpec: {extra or 'none'}"))
    activation_id = projection.last_activations.get("engineering")
    build_and_test = []
    for index, item in enumerate(proposal["build_and_test"]):
        receipt = facts.latest_check("engineering", item["name"].strip(), product_spec_hash=spec.content_hash,
                                     activation_id=activation_id)
        if receipt is None:
            errors.append(FieldError(
                f"build_and_test[{index}].name",
                f"no run_check receipt named {item['name'].strip()} in this activation bound to the current snapshot and "
                "ProductSpec; call run_check with this name, then submit_structure again",
            ))
            continue
        build_and_test.append({**item, "name": item["name"].strip(), "purpose": item["purpose"].strip(),
                               "command": item["command"].strip(),
                               "receipt": _receipt_evidence(receipt)})
    if errors:
        return ProposalDecision(False, errors)
    previous = projection.structures[-1] if projection.structures else None
    parent = previous["content_hash"] if previous else None
    revision = (previous["revision"] + 1) if previous else 1
    payload = {
        "overall": proposal["overall"].strip(),
        "modules": [{"path": item["path"].strip(), "responsibility": item["responsibility"].strip()}
                    for item in proposal["modules"]],
        "entry_points": [{"kind": item["kind"], "path": item["path"].strip(), "how_to_run": item["how_to_run"].strip()}
                         for item in proposal["entry_points"]],
        "build_and_test": build_and_test,
        "requirement_locations": [{"requirement": item["requirement"].strip(),
                                   "locations": [path.strip() for path in item["locations"]]}
                                  for item in proposal["requirement_locations"]],
        "conventions": [item.strip() for item in proposal.get("conventions", [])],
        "product_spec_hash": spec.content_hash,
        "code_tree_digest": facts.digest,
    }
    artifact = {
        **payload,
        "kind": "structure",
        "issuer": "engineering",
        "parent_hash": parent,
        "revision": revision,
        "status": "active",
        "content_hash": spec_content_hash("structure", payload, parent_hash=parent, revision=revision),
    }
    return ProposalDecision(True, artifact=artifact,
                            transitions=[tuple(item) for item in DEFINITIONS.transitions(projection.kind, "structure", "accepted")])


def _accept_baseline_review(proposal: dict[str, Any], projection: RunProjection, facts: TreeFacts) -> ProposalDecision:
    # 基线核验（docs/design/existing-project-onboarding.md 第 4.5 节）：逐条结论覆盖初始 PRD 的每条要求，
    # 基线检查绑定当前快照与当前 ProductSpec，退出状态不为 0 的检查都有说明；这里不使用普通事项的放行规则
    spec = projection.product_spec
    if spec is None:
        return ProposalDecision(False, [FieldError("product_spec", "no active ProductSpec")])
    structure = projection.structure
    if structure is None or structure["product_spec_hash"] != spec.content_hash:
        return ProposalDecision(False, [FieldError("structure", "the baseline review requires a structure description of the current ProductSpec")])
    errors = _unchanged_tree_errors(projection, facts)
    check_names, name_errors = _qa_check_names(proposal)
    errors.extend(name_errors)
    activation_id = projection.last_activations.get("quality")
    bound: dict[str, dict[str, Any]] = {}
    for name in check_names:
        receipt = facts.latest_check("quality", name, product_spec_hash=spec.content_hash, activation_id=activation_id)
        if receipt is None:
            errors.append(FieldError(
                "checks",
                f"quality must run {name} against the current snapshot and ProductSpec in this activation; "
                "prior receipts and engineering receipts are not reused",
            ))
            continue
        bound[name] = _receipt_evidence(receipt)
    conclusions, conclusion_errors = _baseline_conclusions(proposal, spec, bound, facts)
    errors.extend(conclusion_errors)
    omissions, omission_errors = _baseline_omission_records(proposal, facts)
    errors.extend(omission_errors)
    failed = sorted(name for name, receipt in bound.items() if receipt["exit_code"] != 0)
    referenced = {item["evidence"] for item in conclusions if item["status"] == "existing_defect"}
    explained = {item["check"] for item in proposal.get("other_failures", []) if isinstance(item, dict)}
    for item in proposal.get("other_failures", []):
        name = item.get("check") if isinstance(item, dict) else None
        if name not in bound:
            errors.append(FieldError("other_failures", f"other_failures must name a baseline check: {name!r}"))
        elif bound[name]["exit_code"] == 0:
            errors.append(FieldError("other_failures", f"check {name} exited 0; only failing checks need an explanation"))
    unexplained = [name for name in failed if name not in referenced and name not in explained]
    if unexplained:
        errors.append(FieldError("checks", "every failing check must be referenced by an existing_defect conclusion or explained "
                                           f"in other_failures: {unexplained}"))
    verdict = proposal["verdict"]
    unsupported = [item["requirement"] for item in conclusions if item["status"] == "unsupported"]
    if verdict == "consistent" and (unsupported or omissions):
        errors.append(FieldError("verdict", f"consistent requires no unsupported conclusion and no omission; got "
                                           f"{len(unsupported)} unsupported and {len(omissions)} omission(s)"))
    if verdict == "rework_product" and not unsupported and not omissions:
        errors.append(FieldError("verdict", "rework_product requires at least one unsupported conclusion or one omission"))
    if errors:
        return ProposalDecision(False, errors)
    previous = projection.baseline_reviews[-1] if projection.baseline_reviews else None
    parent = previous["content_hash"] if previous else None
    revision = (previous["revision"] + 1) if previous else 1
    payload = {
        "verdict": verdict,
        "conclusions": conclusions,
        "omissions": omissions,
        "checks": [bound[name] for name in check_names],
        "other_failures": [{"check": item["check"].strip(), "reason": item["reason"].strip()}
                           for item in proposal.get("other_failures", [])],
        "product_spec_hash": spec.content_hash,
        "structure_hash": structure["content_hash"],
        "code_snapshot_hash": facts.digest,
    }
    artifact = {
        **payload,
        "kind": "baseline_review",
        "issuer": "quality",
        "parent_hash": parent,
        "revision": revision,
        "status": "active",
        "content_hash": spec_content_hash("baseline_review", payload, parent_hash=parent, revision=revision),
    }
    return ProposalDecision(True, artifact=artifact,
                            transitions=[tuple(item) for item in DEFINITIONS.transitions(projection.kind, "baseline_review", verdict)])


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
        "snapshot_hash": receipt.snapshot_hash,
        "summary": receipt.summary,
        "qa_tests_hash": getattr(receipt, "qa_tests_hash", None),
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


# 提交者声明的依据版本（工单 #471）：每个正式成果都要写明它依据的版本；与当前 host 端有效版本的
# content_hash 不一致时整次提交被拒绝，错误指向声明的字段，消息给出实际当前版本，便于模型重试
def _basis_hash_errors(proposal: dict[str, Any], field: str, current_hash: str | None) -> list[FieldError]:
    if field not in proposal:
        return [FieldError(field, f"{field} is required; declare the version this artifact is based on")]
    value = proposal[field]
    if value is not None and (not isinstance(value, str) or not value.strip()):
        return [FieldError(field, f"{field} must be a content hash string or null")]
    if current_hash is None:
        if value is not None:
            return [FieldError(field, f"{field} must be null when no current version exists; current value is {value!r}")]
        return []
    if value != current_hash:
        return [FieldError(field, f"submitted artifact is based on {value!r}; current version is {current_hash!r}. Read the current version and submit again.")]
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
