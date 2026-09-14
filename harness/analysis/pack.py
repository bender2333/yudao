"""Write, load, and verify a movable self-contained evidence directory."""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..models import QA_VERDICTS, canonical_hash, json_dumps
from ..public_tree import (
    CapturedTree,
    TreeError,
    capture_public_tree,
    materialize_tree,
    validate_public_path,
    verify_public_tree,
)
from .records import (
    ANALYSIS_DIR,
    ANALYSIS_FILE,
    ANALYZER,
    COMPARISON_RULES,
    Check,
    Environment,
    EVALUATOR,
    EvidenceError,
    LoadedRound,
    MANIFEST_NAME,
    MATERIAL_SOURCES,
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_REPEATS,
    MAX_ROUNDS,
    MaterialDeclaration,
    Observation,
    ObservationInput,
    PAYLOAD_ROOT,
    PROTOCOL,
    QARecord,
    Requirement,
    ReviewIdentity,
    RoundInput,
    TEXT_STATUSES,
    TERMINATIONS,
    VerifiedPack,
    VerifyReceipt,
)
from .trajectory import recompute_trajectory


def write_evidence_pack(
    destination: str | Path,
    *,
    material: MaterialDeclaration,
    review: ReviewIdentity,
    rounds: tuple[RoundInput, ...] | list[RoundInput],
) -> Path:
    """Save already-finished rounds. Never executes a delivery or starts a model."""
    target = Path(destination)
    if target.exists():
        raise EvidenceError(f"Evidence destination already exists: {target}")
    items = _validated_rounds(tuple(rounds))
    _validate_material(material)
    _validate_review(review)
    target.mkdir(parents=True)
    _write_payload(target, items)
    payload = _capture_payload(target)
    identity = _core_identity(material, review, items, payload)
    manifest = {
        "protocol": PROTOCOL,
        "content_digest": canonical_hash(identity),
        "material": _material_payload(material),
        "review": _review_payload(review),
        "rounds": [_round_payload(item) for item in items],
        "payload": payload.manifest,
    }
    _write_bytes(target / MANIFEST_NAME, json_dumps(manifest).encode("utf-8"))
    loaded = load_evidence_pack(target)
    if loaded.content_digest != manifest["content_digest"]:
        raise EvidenceError("Written evidence pack did not pass read-back verification")
    _write_analysis(target, loaded.trajectory)
    return target


def load_evidence_pack(directory: str | Path) -> VerifiedPack:
    """Read-only load. Never executes delivery files or recorded commands."""
    root = Path(directory)
    if not root.is_dir():
        raise EvidenceError(f"Evidence directory does not exist: {root}")
    raw = _read_manifest_bytes(root)
    payload_json = _strict_json(raw)
    _validate_manifest_shape(payload_json)
    material = _load_material(payload_json["material"])
    review = _load_review(payload_json["review"])
    try:
        verify_public_tree(root / PAYLOAD_ROOT, payload_json["payload"])
        payload = capture_public_tree(root / PAYLOAD_ROOT)
    except TreeError as exc:
        raise EvidenceError(str(exc)) from exc
    if payload.manifest != payload_json["payload"]:
        raise EvidenceError("Evidence payload does not match the complete recorded listing")
    _enforce_payload_limits(payload)
    rounds = tuple(_load_round(root, item, payload) for item in payload_json["rounds"])
    identity = _core_identity(material, review, rounds, payload)
    digest = canonical_hash(identity)
    if digest != payload_json["content_digest"]:
        raise EvidenceError("Evidence content digest does not match the verified records")
    trajectory = recompute_trajectory(rounds)
    return VerifiedPack(
        protocol=PROTOCOL,
        content_digest=digest,
        material=material,
        review=review,
        rounds=rounds,
        trajectory=trajectory,
        analysis_mismatch=_analysis_mismatch(root, trajectory),
        root=root,
    )


def verify_evidence_pack(directory: str | Path) -> VerifyReceipt:
    loaded = load_evidence_pack(directory)
    return VerifyReceipt(
        protocol=loaded.protocol,
        content_digest=loaded.content_digest,
        material_id=loaded.material.id,
        review_id=loaded.review.id,
        source=loaded.material.source,
        trajectory=loaded.trajectory,
        analysis_mismatch=loaded.analysis_mismatch,
    )


def _write_payload(root: Path, rounds: tuple[RoundInput, ...]) -> None:
    for item in rounds:
        delivery = root / PAYLOAD_ROOT / item.id / "delivery"
        delivery.parent.mkdir(parents=True)
        try:
            materialize_tree(item.delivery, delivery)
        except TreeError as exc:
            raise EvidenceError(str(exc)) from exc
        for observation in item.observations:
            base = root / PAYLOAD_ROOT / item.id / "observations" / observation.check_id
            base.mkdir(parents=True)
            _write_bytes(base / "stdin", observation.stdin)
            _write_bytes(base / "stdout", observation.stdout)
            _write_bytes(base / "stderr", observation.stderr)


def _write_analysis(root: Path, trajectory) -> None:
    directory = root / ANALYSIS_DIR
    directory.mkdir()
    _write_bytes(directory / "trajectory.json", json_dumps(_trajectory_payload(trajectory)).encode("utf-8"))


def _write_bytes(path: Path, data: bytes) -> None:
    if len(data) > MAX_FILE_BYTES:
        raise EvidenceError(f"Evidence file exceeds {MAX_FILE_BYTES} bytes: {path}")
    with path.open("xb") as handle:
        handle.write(data)


def _capture_payload(root: Path) -> CapturedTree:
    try:
        payload = capture_public_tree(root / PAYLOAD_ROOT)
    except TreeError as exc:
        raise EvidenceError(str(exc)) from exc
    _enforce_payload_limits(payload)
    return payload


def _enforce_payload_limits(payload: CapturedTree) -> None:
    if len(payload.files) > MAX_FILES:
        raise EvidenceError(f"Evidence payload exceeds {MAX_FILES} files")
    for item in payload.files:
        if len(item.data) > MAX_FILE_BYTES:
            raise EvidenceError(f"Evidence file exceeds {MAX_FILE_BYTES} bytes: {item.path}")


def _validated_rounds(rounds: tuple[RoundInput, ...]) -> tuple[RoundInput, ...]:
    if not rounds:
        raise EvidenceError("Evidence pack requires at least one round")
    if len(rounds) > MAX_ROUNDS:
        raise EvidenceError(f"Evidence pack exceeds {MAX_ROUNDS} rounds")
    seen = set()
    validated = []
    for item in rounds:
        if not isinstance(item, RoundInput):
            raise EvidenceError("Each round must be a RoundInput")
        _path_component(item.id, "round id")
        if item.id in seen:
            raise EvidenceError(f"Duplicate round id: {item.id}")
        seen.add(item.id)
        if not isinstance(item.delivery, CapturedTree):
            raise EvidenceError("Each round requires a captured delivery tree")
        requirements = _validated_requirements(item.requirements)
        checks = _validated_checks(item.checks, requirements)
        observations = _validated_observations(item.observations, checks)
        _validate_environment(item.environment)
        qa = _validated_qa(item.qa, requirements, item.delivery)
        validated.append(
            RoundInput(
                id=item.id,
                delivery=item.delivery,
                requirements=requirements,
                checks=checks,
                observations=observations,
                environment=item.environment,
                qa=qa,
            )
        )
    return tuple(validated)


def _validated_requirements(requirements: tuple[Requirement, ...]) -> tuple[Requirement, ...]:
    if not requirements:
        raise EvidenceError("Each round requires at least one requirement")
    seen = set()
    items = []
    for item in requirements:
        if not isinstance(item, Requirement):
            raise EvidenceError("Invalid requirement")
        _path_component(item.id, "requirement id")
        if not _nonempty_str(item.version) or not _nonempty_str(item.text):
            raise EvidenceError("Requirement version and text are required")
        if item.id in seen:
            raise EvidenceError(f"Duplicate requirement id: {item.id}")
        seen.add(item.id)
        items.append(item)
    return tuple(items)


def _validated_checks(checks: tuple[Check, ...], requirements: tuple[Requirement, ...]) -> tuple[Check, ...]:
    if not checks:
        raise EvidenceError("Each round requires at least one check")
    known = {item.id for item in requirements}
    seen = set()
    items = []
    for item in checks:
        if not isinstance(item, Check):
            raise EvidenceError("Invalid check")
        _path_component(item.id, "check id")
        if item.requirement_id not in known:
            raise EvidenceError(f"Check {item.id} does not refer to a round requirement")
        if item.id in seen:
            raise EvidenceError(f"Duplicate check id: {item.id}")
        if not isinstance(item.stdin, bytes) or not isinstance(item.expected_stdout, bytes):
            raise EvidenceError("Check stdin and expected stdout must be bytes")
        try:
            item.stdin.decode("utf-8")
            item.expected_stdout.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise EvidenceError("Check stdin and expected stdout must be UTF-8") from exc
        if type(item.expected_exit_code) is not int:
            raise EvidenceError("Check expected exit code must be an integer")
        if type(item.repeats) is not int or item.repeats < 1 or item.repeats > MAX_REPEATS:
            raise EvidenceError("Check repeats must be an integer from 1 to 8")
        _optional_seconds(item.timeout_sec, "timeout")
        seen.add(item.id)
        items.append(item)
    return tuple(items)


def _validated_observations(
    observations: tuple[ObservationInput, ...],
    checks: tuple[Check, ...],
) -> tuple[ObservationInput, ...]:
    by_id = {item.id: item for item in checks}
    seen = set()
    items = []
    for item in observations:
        if not isinstance(item, ObservationInput):
            raise EvidenceError("Invalid observation")
        if item.check_id not in by_id:
            raise EvidenceError(f"Observation does not refer to a round check: {item.check_id}")
        if item.check_id in seen:
            raise EvidenceError(f"Duplicate observation for check: {item.check_id}")
        if item.termination not in TERMINATIONS:
            raise EvidenceError(f"Unknown observation termination: {item.termination}")
        if item.stdout_text_status not in TEXT_STATUSES:
            raise EvidenceError(f"Unknown stdout text status: {item.stdout_text_status}")
        if not isinstance(item.stdin, bytes) or not isinstance(item.stdout, bytes) or not isinstance(item.stderr, bytes):
            raise EvidenceError("Observation stdin, stdout, and stderr must be bytes")
        check = by_id[item.check_id]
        if item.stdin != check.stdin:
            raise EvidenceError(f"Observation stdin does not match check {item.check_id}")
        if check.repeats != 1:
            raise EvidenceError("L1 observations support a single recorded attempt per check")
        _optional_exit(item.exit_code, item.termination)
        _optional_seconds(item.duration_sec, "duration")
        seen.add(item.check_id)
        items.append(item)
    if seen != set(by_id):
        raise EvidenceError("Each check must have exactly one observation")
    return tuple(items)


def _validated_qa(qa: QARecord | None, requirements: tuple[Requirement, ...], delivery: CapturedTree) -> QARecord | None:
    if qa is None:
        return None
    if not isinstance(qa, QARecord):
        raise EvidenceError("Invalid QA record")
    if qa.decision not in QA_VERDICTS:
        raise EvidenceError(f"Unknown QA decision: {qa.decision}")
    if qa.source not in MATERIAL_SOURCES:
        raise EvidenceError(f"Unknown QA source: {qa.source}")
    if not _nonempty_str(qa.summary):
        raise EvidenceError("QA summary is required")
    known = {item.id for item in requirements}
    seen = set()
    for requirement_id in qa.reviewed_requirement_ids:
        if requirement_id not in known:
            raise EvidenceError(f"QA reviewed requirement is not in this round: {requirement_id}")
        if requirement_id in seen:
            raise EvidenceError(f"Duplicate QA reviewed requirement: {requirement_id}")
        seen.add(requirement_id)
    if qa.delivery_digest is not None and qa.delivery_digest != delivery.digest:
        raise EvidenceError("QA delivery digest does not match this round's delivery")
    return qa


def _validate_environment(environment: Environment) -> None:
    if not isinstance(environment, Environment):
        raise EvidenceError("Each round requires an environment record")
    if not _nonempty_str(environment.interpreter) or not _nonempty_str(environment.executor):
        raise EvidenceError("Environment interpreter and executor are required historical text")
    if environment.comparison_rules != COMPARISON_RULES:
        raise EvidenceError("Unsupported comparison rules")
    if environment.notes is not None and not isinstance(environment.notes, str):
        raise EvidenceError("Environment notes must be text when present")


def _validate_material(material: MaterialDeclaration) -> None:
    if not isinstance(material, MaterialDeclaration):
        raise EvidenceError("Material declaration is required")
    _path_component(material.id, "material id")
    if material.source not in MATERIAL_SOURCES:
        raise EvidenceError(f"Unknown material source: {material.source}")
    if type(material.calibration) is not bool:
        raise EvidenceError("Material calibration flag must be a boolean")
    for name, value in (
        ("family", material.family),
        ("project_id", material.project_id),
        ("work_item_id", material.work_item_id),
        ("run_id", material.run_id),
    ):
        if value is not None:
            _path_component(value, name)


def _validate_review(review: ReviewIdentity) -> None:
    if not isinstance(review, ReviewIdentity):
        raise EvidenceError("Review identity is required")
    _path_component(review.id, "review id")
    if review.evaluator != EVALUATOR:
        raise EvidenceError("Unsupported evaluator identity")
    if review.comparison_rules != COMPARISON_RULES:
        raise EvidenceError("Unsupported comparison rules")
    if review.analyzer != ANALYZER:
        raise EvidenceError("Unsupported analyzer version")
    if review.model_requests is not None and (type(review.model_requests) is not int or review.model_requests < 0):
        raise EvidenceError("Model request count must be a nonnegative integer or omitted")
    _optional_seconds(review.check_seconds, "check_seconds")
    _optional_seconds(review.elapsed_seconds, "elapsed_seconds")


def _load_round(root: Path, payload: dict[str, Any], tree: CapturedTree) -> LoadedRound:
    if not isinstance(payload, dict) or set(payload) != {
        "id", "delivery", "delivery_digest", "requirements", "checks", "observations", "environment", "qa",
    }:
        raise EvidenceError("Invalid round fields")
    round_id = payload["id"]
    _path_component(round_id, "round id")
    delivery_path = payload["delivery"]
    if delivery_path != f"{PAYLOAD_ROOT}/{round_id}/delivery":
        raise EvidenceError(f"Round delivery path is not the sealed location: {delivery_path}")
    _pack_path(delivery_path)
    try:
        delivery = capture_public_tree(root / delivery_path)
    except TreeError as exc:
        raise EvidenceError(str(exc)) from exc
    if delivery.digest != payload["delivery_digest"]:
        raise EvidenceError(f"Delivery digest does not match sealed bytes: {round_id}")
    requirements = _validated_requirements(
        tuple(_parse_requirement(item) for item in _list(payload["requirements"], "requirements"))
    )
    checks = _validated_checks(
        tuple(_parse_check(item) for item in _list(payload["checks"], "checks")),
        requirements,
    )
    environment = _load_environment(payload["environment"])
    observations = tuple(
        _load_observation(root, round_id, item, checks, tree)
        for item in _list(payload["observations"], "observations")
    )
    if [obs.check_id for obs in observations] != [check.id for check in checks]:
        raise EvidenceError("Each check must have exactly one observation in check order")
    qa = None if payload["qa"] is None else _load_qa(payload["qa"], requirements, delivery)
    return LoadedRound(
        id=round_id,
        delivery=delivery,
        delivery_path=delivery_path,
        requirements=requirements,
        checks=checks,
        observations=observations,
        environment=environment,
        qa=qa,
    )


def _parse_requirement(payload: dict[str, Any]) -> Requirement:
    if not isinstance(payload, dict) or set(payload) != {"id", "version", "text"}:
        raise EvidenceError("Invalid requirement fields")
    return Requirement(payload["id"], payload["version"], payload["text"])


def _parse_check(payload: dict[str, Any]) -> Check:
    if not isinstance(payload, dict) or set(payload) != {
        "id", "requirement_id", "stdin_utf8", "expected_stdout_utf8", "expected_exit_code", "repeats", "timeout_sec",
    }:
        raise EvidenceError("Invalid check fields")
    return Check(
        id=payload["id"],
        requirement_id=payload["requirement_id"],
        stdin=_utf8_field(payload["stdin_utf8"], "check stdin"),
        expected_stdout=_utf8_field(payload["expected_stdout_utf8"], "check expected stdout"),
        expected_exit_code=payload["expected_exit_code"],
        repeats=payload["repeats"],
        timeout_sec=payload["timeout_sec"],
    )


def _load_observation(
    root: Path,
    round_id: str,
    payload: dict[str, Any],
    checks: tuple[Check, ...],
    tree: CapturedTree,
) -> Observation:
    if not isinstance(payload, dict) or set(payload) != {
        "check_id", "termination", "exit_code", "duration_sec",
        "stdin", "stdout", "stderr", "stdout_text_status",
    }:
        raise EvidenceError("Invalid observation fields")
    check = next((item for item in checks if item.id == payload["check_id"]), None)
    if check is None:
        raise EvidenceError(f"Observation does not refer to a round check: {payload['check_id']}")
    base = f"{PAYLOAD_ROOT}/{round_id}/observations/{check.id}"
    for name in ("stdin", "stdout", "stderr"):
        if payload[name] != f"{base}/{name}":
            raise EvidenceError(f"Observation {name} path is not the sealed location: {payload[name]}")
    stdin = _read_payload_file(root, payload["stdin"], tree)
    stdout = _read_payload_file(root, payload["stdout"], tree)
    stderr = _read_payload_file(root, payload["stderr"], tree)
    if stdin != check.stdin:
        raise EvidenceError(f"Observation stdin does not match check {check.id}")
    status = payload["stdout_text_status"]
    if status not in TEXT_STATUSES:
        raise EvidenceError(f"Unknown stdout text status: {status}")
    termination = payload["termination"]
    if termination not in TERMINATIONS:
        raise EvidenceError(f"Unknown observation termination: {termination}")
    exit_code = payload["exit_code"]
    _optional_exit(exit_code, termination)
    duration = payload["duration_sec"]
    _optional_seconds(duration, "duration")
    verdict = _verdict(check, termination, exit_code, stdout, status)
    return Observation(
        check_id=check.id,
        termination=termination,
        stdin_path=payload["stdin"],
        stdout_path=payload["stdout"],
        stderr_path=payload["stderr"],
        stdout_text_status=status,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        verdict=verdict,
        exit_code=exit_code,
        duration_sec=duration,
    )


def _verdict(check: Check, termination: str, exit_code: int | None, stdout: bytes, status: str) -> str:
    decoded = _decode_stdout(stdout, status)
    if termination != "completed":
        return "unknown"
    if decoded is None:
        return "unknown"
    expected = check.expected_stdout.decode("utf-8")
    if exit_code == check.expected_exit_code and _normalize(decoded) == _normalize(expected):
        return "pass"
    return "fail"


def _decode_stdout(raw: bytes, status: str) -> str | None:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        if status != "undecodable":
            raise EvidenceError("Stdout bytes are not UTF-8 but were not recorded as undecodable")
        return None
    if status == "undecodable":
        raise EvidenceError("Valid UTF-8 stdout was recorded as undecodable")
    return text


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _load_environment(payload: dict[str, Any]) -> Environment:
    if not isinstance(payload, dict) or set(payload) != {"interpreter", "executor", "comparison_rules", "notes"}:
        raise EvidenceError("Invalid environment fields")
    environment = Environment(
        interpreter=payload["interpreter"],
        executor=payload["executor"],
        comparison_rules=payload["comparison_rules"],
        notes=payload["notes"],
    )
    _validate_environment(environment)
    return environment


def _load_qa(payload: dict[str, Any], requirements: tuple[Requirement, ...], delivery: CapturedTree) -> QARecord:
    if not isinstance(payload, dict) or set(payload) != {
        "decision", "source", "reviewed_requirement_ids", "delivery_digest", "summary",
    }:
        raise EvidenceError("Invalid QA fields")
    reviewed = payload["reviewed_requirement_ids"]
    if not isinstance(reviewed, list) or any(not isinstance(item, str) for item in reviewed):
        raise EvidenceError("QA reviewed requirements must be a list of strings")
    qa = QARecord(
        decision=payload["decision"],
        source=payload["source"],
        reviewed_requirement_ids=tuple(reviewed),
        delivery_digest=payload["delivery_digest"],
        summary=payload["summary"],
    )
    return _validated_qa(qa, requirements, delivery)


def _load_material(payload: dict[str, Any]) -> MaterialDeclaration:
    if not isinstance(payload, dict) or set(payload) != {
        "id", "source", "calibration", "family", "project_id", "work_item_id", "run_id",
    }:
        raise EvidenceError("Invalid material fields")
    material = MaterialDeclaration(
        id=payload["id"],
        source=payload["source"],
        calibration=payload["calibration"],
        family=payload["family"],
        project_id=payload["project_id"],
        work_item_id=payload["work_item_id"],
        run_id=payload["run_id"],
    )
    _validate_material(material)
    return material


def _load_review(payload: dict[str, Any]) -> ReviewIdentity:
    if not isinstance(payload, dict) or set(payload) != {
        "id", "evaluator", "comparison_rules", "analyzer", "model_requests", "check_seconds", "elapsed_seconds",
    }:
        raise EvidenceError("Invalid review fields")
    review = ReviewIdentity(
        id=payload["id"],
        evaluator=payload["evaluator"],
        comparison_rules=payload["comparison_rules"],
        analyzer=payload["analyzer"],
        model_requests=payload["model_requests"],
        check_seconds=payload["check_seconds"],
        elapsed_seconds=payload["elapsed_seconds"],
    )
    _validate_review(review)
    return review


def _core_identity(material, review, rounds, payload: CapturedTree) -> dict[str, Any]:
    return {
        "protocol": PROTOCOL,
        "material": _material_payload(material),
        "review": _review_payload(review),
        "rounds": [_round_payload(item) for item in rounds],
        "payload": payload.manifest,
    }


def _material_payload(material: MaterialDeclaration) -> dict[str, Any]:
    return {
        "id": material.id,
        "source": material.source,
        "calibration": material.calibration,
        "family": material.family,
        "project_id": material.project_id,
        "work_item_id": material.work_item_id,
        "run_id": material.run_id,
    }


def _review_payload(review: ReviewIdentity) -> dict[str, Any]:
    return {
        "id": review.id,
        "evaluator": review.evaluator,
        "comparison_rules": review.comparison_rules,
        "analyzer": review.analyzer,
        "model_requests": review.model_requests,
        "check_seconds": review.check_seconds,
        "elapsed_seconds": review.elapsed_seconds,
    }


def _round_payload(item: RoundInput | LoadedRound) -> dict[str, Any]:
    delivery_path = f"{PAYLOAD_ROOT}/{item.id}/delivery"
    return {
        "id": item.id,
        "delivery": delivery_path,
        "delivery_digest": item.delivery.digest,
        "requirements": [_requirement_payload(req) for req in item.requirements],
        "checks": [_check_payload(check) for check in item.checks],
        "observations": [_observation_payload(item.id, obs) for obs in item.observations],
        "environment": {
            "interpreter": item.environment.interpreter,
            "executor": item.environment.executor,
            "comparison_rules": item.environment.comparison_rules,
            "notes": item.environment.notes,
        },
        "qa": None if item.qa is None else {
            "decision": item.qa.decision,
            "source": item.qa.source,
            "reviewed_requirement_ids": list(item.qa.reviewed_requirement_ids),
            "delivery_digest": item.qa.delivery_digest,
            "summary": item.qa.summary,
        },
    }


def _requirement_payload(item: Requirement) -> dict[str, Any]:
    return {"id": item.id, "version": item.version, "text": item.text}


def _check_payload(item: Check) -> dict[str, Any]:
    return {
        "id": item.id,
        "requirement_id": item.requirement_id,
        "stdin_utf8": item.stdin.decode("utf-8"),
        "expected_stdout_utf8": item.expected_stdout.decode("utf-8"),
        "expected_exit_code": item.expected_exit_code,
        "repeats": item.repeats,
        "timeout_sec": item.timeout_sec,
    }


def _observation_payload(round_id: str, item: ObservationInput | Observation) -> dict[str, Any]:
    base = f"{PAYLOAD_ROOT}/{round_id}/observations/{item.check_id}"
    return {
        "check_id": item.check_id,
        "termination": item.termination,
        "exit_code": item.exit_code,
        "duration_sec": item.duration_sec,
        "stdin": f"{base}/stdin",
        "stdout": f"{base}/stdout",
        "stderr": f"{base}/stderr",
        "stdout_text_status": item.stdout_text_status,
    }


def _trajectory_payload(trajectory) -> dict[str, Any]:
    return json.loads(json_dumps(asdict(trajectory)))


def _analysis_mismatch(root: Path, trajectory) -> bool:
    path = root / ANALYSIS_FILE
    if not path.is_file():
        return False
    recorded = _strict_json(path.read_bytes())
    return recorded != _trajectory_payload(trajectory)


def _read_manifest_bytes(root: Path) -> bytes:
    path = root / MANIFEST_NAME
    if not path.is_file():
        raise EvidenceError("Evidence pack is missing manifest.json")
    data = path.read_bytes()
    if len(data) > MAX_FILE_BYTES:
        raise EvidenceError("Evidence manifest exceeds the recorded size limit")
    return data


def _read_payload_file(root: Path, relative: str, tree: CapturedTree) -> bytes:
    payload_relative = _payload_relative(relative)
    match = next((item for item in tree.files if item.path == payload_relative), None)
    if match is None:
        raise EvidenceError(f"Observation path is not in the payload listing: {relative}")
    path = root / relative
    data = path.read_bytes()
    if data != match.data:
        raise EvidenceError(f"Observation bytes do not match the payload listing: {relative}")
    return data


def _payload_relative(relative: str) -> str:
    _pack_path(relative)
    prefix = PAYLOAD_ROOT + "/"
    if not relative.startswith(prefix) or relative == prefix:
        raise EvidenceError(f"Pack path must be inside {PAYLOAD_ROOT}/: {relative}")
    return relative[len(prefix):]


def _pack_path(relative: str) -> None:
    try:
        validate_public_path(relative)
    except TreeError as exc:
        raise EvidenceError(str(exc)) from exc


def _path_component(value: str, name: str) -> None:
    if not isinstance(value, str) or "/" in value:
        raise EvidenceError(f"Invalid {name}: {value!r}")
    try:
        validate_public_path(value)
    except TreeError as exc:
        raise EvidenceError(f"Invalid {name}: {value!r}") from exc


def _validate_manifest_shape(payload: dict[str, Any]) -> None:
    if set(payload) != {"protocol", "content_digest", "material", "review", "rounds", "payload"}:
        raise EvidenceError("Invalid evidence manifest fields")
    if payload["protocol"] != PROTOCOL:
        raise EvidenceError("Unsupported evidence pack protocol")
    if not isinstance(payload["content_digest"], str) or not payload["content_digest"].startswith("sha256:"):
        raise EvidenceError("Invalid evidence content digest")
    rounds = payload["rounds"]
    if not isinstance(rounds, list) or not rounds:
        raise EvidenceError("Evidence pack requires an ordered list of rounds")
    if len(rounds) > MAX_ROUNDS:
        raise EvidenceError(f"Evidence pack exceeds {MAX_ROUNDS} rounds")
    ids = []
    for item in rounds:
        if not isinstance(item, dict) or "id" not in item or not isinstance(item["id"], str):
            raise EvidenceError("Each round must have a string id")
        ids.append(item["id"])
    if len(set(ids)) != len(ids):
        raise EvidenceError("Duplicate round id in evidence manifest")


def _strict_json(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError("Evidence JSON is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise EvidenceError("Evidence JSON must be an object")
    return payload


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise EvidenceError(f"Non-finite value in evidence JSON: {value}")


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise EvidenceError(f"{name} must be a non-empty list")
    return value


def _utf8_field(value: Any, name: str) -> bytes:
    if not isinstance(value, str):
        raise EvidenceError(f"{name} must be a UTF-8 string")
    return value.encode("utf-8")


def _optional_seconds(value: Any, name: str) -> None:
    if value is None:
        return
    if type(value) is bool or type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise EvidenceError(f"{name} must be a nonnegative finite number or omitted")


def _optional_exit(value: Any, termination: str) -> None:
    if termination == "completed":
        if type(value) is not int:
            raise EvidenceError("Completed observations require an integer exit code")
        return
    if value is not None and type(value) is not int:
        raise EvidenceError("Exit code must be an integer when present")


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value)
