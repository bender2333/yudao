"""Drive a multi-round trusted-Python review from an explicit JSON material manifest."""

from __future__ import annotations

import json
import math
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from ..models import QA_VERDICTS
from ..path_rules import TreeError
from ..public_tree import CapturedTree, capture_public_tree, materialize_tree
from ..redact import sanitized_env
from .pack import write_evidence_pack
from .records import (
    ANALYZER,
    COMPARISON_RULES,
    EVALUATOR,
    Check,
    Environment,
    EvidenceError,
    MaterialDeclaration,
    MAX_REPEATS,
    MAX_ROUNDS,
    MATERIAL_SOURCES,
    ObservationInput,
    QARecord,
    Requirement,
    ReviewIdentity,
    RoundInput,
)

MATERIAL_PROTOCOL = "yudao-material-manifest-v1"
EXECUTOR = "trusted-local-python"
ENTRY = "src/main.py"
DEFAULT_TIMEOUT_SEC = 30.0


@dataclass(frozen=True)
class _ParsedRound:
    id: str
    delivery: Path | None
    requirements: tuple[Requirement, ...]
    checks: tuple[Check, ...]
    qa: QARecord | None


@dataclass(frozen=True)
class _ParsedManifest:
    material: MaterialDeclaration
    review_id: str
    rounds: tuple[_ParsedRound, ...]


def review_from_manifest(manifest_path: str | Path, destination: str | Path) -> Path:
    """Parse a JSON manifest, run trusted local Python on isolated copies, write an L1 pack.

    Structural and reference errors fail before any delivery program is started.
    """
    parsed = _parse_manifest(Path(manifest_path))
    target = Path(destination)
    _reject_destination(target, parsed)
    started = time.perf_counter()
    rounds = tuple(_execute_round(item) for item in parsed.rounds)
    elapsed = time.perf_counter() - started
    measured = [
        observation.duration_sec
        for item in rounds
        for observation in item.observations
        if observation.duration_sec is not None
    ]
    review = ReviewIdentity(
        parsed.review_id,
        EVALUATOR,
        COMPARISON_RULES,
        ANALYZER,
        model_requests=None,
        check_seconds=sum(measured) if measured else None,
        elapsed_seconds=elapsed,
    )
    return write_evidence_pack(target, material=parsed.material, review=review, rounds=rounds)


def _parse_manifest(source: Path) -> _ParsedManifest:
    if not source.is_file():
        raise EvidenceError(f"Material manifest does not exist: {source}")
    payload = _strict_json(source.read_bytes())
    if set(payload) != {"protocol", "review_id", "material", "rounds"}:
        raise EvidenceError("Invalid material manifest fields")
    if payload["protocol"] != MATERIAL_PROTOCOL:
        raise EvidenceError("Unsupported material manifest protocol")
    material = _parse_material(payload["material"])
    review_id = payload["review_id"]
    _identity(review_id, "review id")
    raw_rounds = _nonempty_list(payload["rounds"], "rounds")
    if len(raw_rounds) > MAX_ROUNDS:
        raise EvidenceError(f"Material manifest exceeds {MAX_ROUNDS} rounds")
    errors: list[str] = []
    rounds: list[_ParsedRound] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_rounds):
        try:
            item = _parse_round(raw, source.parent)
        except EvidenceError as exc:
            errors.append(f"rounds[{index}]: {exc}")
            continue
        if item.id in seen:
            errors.append(f"Duplicate round id: {item.id}")
            continue
        seen.add(item.id)
        rounds.append(item)
    if errors:
        raise EvidenceError("; ".join(errors))
    return _ParsedManifest(material=material, review_id=review_id, rounds=tuple(rounds))


def _parse_material(payload: Any) -> MaterialDeclaration:
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
    _identity(material.id, "material id")
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
            _identity(value, name)
    return material


def _parse_round(payload: Any, base: Path) -> _ParsedRound:
    if not isinstance(payload, dict) or set(payload) != {"id", "delivery", "requirements", "checks", "qa"}:
        raise EvidenceError("Invalid round fields")
    round_id = payload["id"]
    _identity(round_id, "round id")
    delivery = _parse_delivery(payload["delivery"], base)
    requirements = _parse_requirements(payload["requirements"])
    checks = _parse_checks(payload["checks"], requirements)
    qa = None if payload["qa"] is None else _parse_qa(payload["qa"], requirements)
    return _ParsedRound(round_id, delivery, requirements, checks, qa)


def _parse_delivery(value: Any, base: Path) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise EvidenceError("Round delivery must be a local directory or null")
    path = Path(value)
    if not path.is_absolute():
        path = base / path
    if not path.is_dir():
        raise EvidenceError(f"Delivery directory does not exist: {value}")
    return path


def _parse_requirements(payload: Any) -> tuple[Requirement, ...]:
    items = []
    seen: set[str] = set()
    for raw in _nonempty_list(payload, "requirements"):
        if not isinstance(raw, dict) or set(raw) != {"id", "version", "text"}:
            raise EvidenceError("Invalid requirement fields")
        item = Requirement(raw["id"], raw["version"], raw["text"])
        _identity(item.id, "requirement id")
        if not _nonempty_str(item.version) or not _nonempty_str(item.text):
            raise EvidenceError("Requirement version and text are required")
        if item.id in seen:
            raise EvidenceError(f"Duplicate requirement id: {item.id}")
        seen.add(item.id)
        items.append(item)
    return tuple(items)


def _parse_checks(payload: Any, requirements: tuple[Requirement, ...]) -> tuple[Check, ...]:
    known = {item.id for item in requirements}
    items = []
    seen: set[str] = set()
    for raw in _nonempty_list(payload, "checks"):
        if not isinstance(raw, dict) or set(raw) != {
            "id", "requirement_id", "stdin_utf8", "expected_stdout_utf8",
            "expected_exit_code", "repeats", "timeout_sec",
        }:
            raise EvidenceError("Invalid check fields")
        item = Check(
            id=raw["id"],
            requirement_id=raw["requirement_id"],
            stdin=_utf8_field(raw["stdin_utf8"], "check stdin"),
            expected_stdout=_utf8_field(raw["expected_stdout_utf8"], "check expected stdout"),
            expected_exit_code=raw["expected_exit_code"],
            repeats=raw["repeats"],
            timeout_sec=raw["timeout_sec"],
        )
        _identity(item.id, "check id")
        if item.requirement_id not in known:
            raise EvidenceError(f"Check {item.id} does not refer to a round requirement")
        if item.id in seen:
            raise EvidenceError(f"Duplicate check id: {item.id}")
        if type(item.expected_exit_code) is not int:
            raise EvidenceError("Check expected exit code must be an integer")
        if type(item.repeats) is not int or item.repeats < 1 or item.repeats > MAX_REPEATS:
            raise EvidenceError("Check repeats must be an integer from 1 to 8")
        if item.repeats != 1:
            raise EvidenceError("L2 observations support a single recorded attempt per check")
        _optional_seconds(item.timeout_sec, "timeout")
        seen.add(item.id)
        items.append(item)
    return tuple(items)


def _parse_qa(payload: Any, requirements: tuple[Requirement, ...]) -> QARecord:
    if not isinstance(payload, dict) or set(payload) != {
        "decision", "source", "reviewed_requirement_ids", "delivery_digest", "summary",
    }:
        raise EvidenceError("Invalid QA fields")
    reviewed = payload["reviewed_requirement_ids"]
    if not isinstance(reviewed, list) or any(not isinstance(item, str) for item in reviewed):
        raise EvidenceError("QA reviewed requirements must be a list of ids")
    qa = QARecord(
        payload["decision"],
        payload["source"],
        tuple(reviewed),
        payload["delivery_digest"],
        payload["summary"],
    )
    if qa.decision not in QA_VERDICTS:
        raise EvidenceError(f"Unknown QA decision: {qa.decision}")
    if qa.source not in MATERIAL_SOURCES:
        raise EvidenceError(f"Unknown QA source: {qa.source}")
    if not _nonempty_str(qa.summary):
        raise EvidenceError("QA summary is required")
    if qa.delivery_digest is not None and not _nonempty_str(qa.delivery_digest):
        raise EvidenceError("QA delivery digest must be text when present")
    known = {item.id for item in requirements}
    seen: set[str] = set()
    for requirement_id in qa.reviewed_requirement_ids:
        if requirement_id not in known:
            raise EvidenceError(f"QA reviewed requirement is not in this round: {requirement_id}")
        if requirement_id in seen:
            raise EvidenceError(f"Duplicate QA reviewed requirement: {requirement_id}")
        seen.add(requirement_id)
    return qa


def _reject_destination(target: Path, parsed: _ParsedManifest) -> None:
    if target.exists():
        raise EvidenceError(f"Evidence destination already exists: {target}")
    for item in parsed.rounds:
        if item.delivery is None:
            continue
        if _contained(target, item.delivery):
            raise EvidenceError("Evidence destination is inside a delivery")


def _execute_round(item: _ParsedRound) -> RoundInput:
    tree = _load_delivery(item.delivery)
    if tree is None:
        tree = CapturedTree((), ())
        observations = tuple(_unrun_observation(check, "launch_failure") for check in item.checks)
    else:
        observations = tuple(_run_check(tree, check) for check in item.checks)
    return RoundInput(
        id=item.id,
        delivery=tree,
        requirements=item.requirements,
        checks=item.checks,
        observations=observations,
        environment=Environment(sys.executable, EXECUTOR, COMPARISON_RULES),
        qa=item.qa,
    )


def _load_delivery(path: Path | None) -> CapturedTree | None:
    if path is None:
        return None
    try:
        return capture_public_tree(path)
    except (OSError, TreeError):
        return None


def _run_check(tree: CapturedTree, check: Check) -> ObservationInput:
    with TemporaryDirectory() as folder:
        copy = Path(folder) / "copy"
        try:
            materialize_tree(tree, copy)
        except TreeError:
            return _unrun_observation(check, "launch_failure")
        if not (copy / ENTRY).is_file():
            return _unrun_observation(check, "launch_failure")
        timeout = DEFAULT_TIMEOUT_SEC if check.timeout_sec is None else float(check.timeout_sec)
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                [sys.executable, ENTRY],
                cwd=str(copy),
                input=check.stdin,
                capture_output=True,
                timeout=timeout,
                check=False,
                env={**sanitized_env(), "PYTHONDONTWRITEBYTECODE": "1"},
            )
        except subprocess.TimeoutExpired as exc:
            return ObservationInput(
                check_id=check.id,
                termination="timeout",
                stdin=check.stdin,
                stdout=_bytes_output(exc.stdout),
                stderr=_bytes_output(exc.stderr),
                stdout_text_status=_stdout_status(_bytes_output(exc.stdout)),
                exit_code=None,
                duration_sec=time.perf_counter() - started,
            )
        except OSError:
            return _unrun_observation(check, "launch_failure", duration_sec=time.perf_counter() - started)
        stdout = completed.stdout
        return ObservationInput(
            check_id=check.id,
            termination="completed",
            stdin=check.stdin,
            stdout=stdout,
            stderr=completed.stderr,
            stdout_text_status=_stdout_status(stdout),
            exit_code=int(completed.returncode),
            duration_sec=time.perf_counter() - started,
        )


def _unrun_observation(check: Check, termination: str, duration_sec: float | None = None) -> ObservationInput:
    return ObservationInput(
        check_id=check.id,
        termination=termination,
        stdin=check.stdin,
        stdout=b"",
        stderr=b"",
        stdout_text_status="utf8",
        exit_code=None,
        duration_sec=duration_sec,
    )


def _bytes_output(value: bytes | str | None) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    return value.encode("utf-8", "replace")


def _stdout_status(raw: bytes) -> str:
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return "undecodable"
    return "utf8"


def _contained(path: Path, root: Path) -> bool:
    path_parts = tuple(part.casefold() for part in path.absolute().parts)
    root_parts = tuple(part.casefold() for part in root.absolute().parts)
    return len(path_parts) >= len(root_parts) and path_parts[: len(root_parts)] == root_parts


def _strict_json(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError("Material JSON is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise EvidenceError("Material JSON must be an object")
    return payload


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise EvidenceError(f"Non-finite value in material JSON: {value}")


def _nonempty_list(value: Any, name: str) -> list[Any]:
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


def _identity(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value or "/" in value or "\\" in value:
        raise EvidenceError(f"Invalid {name}: {value!r}")


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value)
