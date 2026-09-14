"""Evidence-pack records: identities, rounds, observations, and derived trajectory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models import QA_VERDICTS
from ..public_tree import CapturedTree


PROTOCOL = "yudao-evidence-pack-v1"
EVALUATOR = "yudao-host-text-v1"
COMPARISON_RULES = "yudao-text-newline-v1"
ANALYZER = "yudao-trajectory-v1"

MATERIAL_SOURCES = ("calibration", "provider_declaration", "trusted_capture")
TERMINATIONS = ("completed", "timeout", "launch_failure")
TEXT_STATUSES = ("utf8", "undecodable")
MAX_ROUNDS = 32
MAX_FILES = 256
MAX_FILE_BYTES = 1_048_576
MAX_REPEATS = 8

PAYLOAD_ROOT = "rounds"
MANIFEST_NAME = "manifest.json"
ANALYSIS_DIR = "analysis"
ANALYSIS_FILE = "analysis/trajectory.json"


class EvidenceError(ValueError):
    """An evidence pack is incomplete, inconsistent, or not a closed readable record."""


@dataclass(frozen=True)
class MaterialDeclaration:
    id: str
    source: str
    calibration: bool
    family: str | None = None
    project_id: str | None = None
    work_item_id: str | None = None
    run_id: str | None = None


@dataclass(frozen=True)
class ReviewIdentity:
    id: str
    evaluator: str
    comparison_rules: str
    analyzer: str
    model_requests: int | None = None
    check_seconds: float | None = None
    elapsed_seconds: float | None = None


@dataclass(frozen=True)
class Requirement:
    id: str
    version: str
    text: str


@dataclass(frozen=True)
class Check:
    id: str
    requirement_id: str
    stdin: bytes
    expected_stdout: bytes
    expected_exit_code: int
    repeats: int = 1
    timeout_sec: float | None = None


@dataclass(frozen=True)
class Environment:
    interpreter: str
    executor: str
    comparison_rules: str
    notes: str | None = None


@dataclass(frozen=True)
class QARecord:
    decision: str
    source: str
    reviewed_requirement_ids: tuple[str, ...]
    delivery_digest: str | None
    summary: str


@dataclass(frozen=True)
class ObservationInput:
    check_id: str
    termination: str
    stdin: bytes
    stdout: bytes
    stderr: bytes
    stdout_text_status: str = "utf8"
    exit_code: int | None = None
    duration_sec: float | None = None


@dataclass(frozen=True)
class RoundInput:
    id: str
    delivery: CapturedTree
    requirements: tuple[Requirement, ...]
    checks: tuple[Check, ...]
    observations: tuple[ObservationInput, ...]
    environment: Environment
    qa: QARecord | None = None


@dataclass(frozen=True)
class Observation:
    check_id: str
    termination: str
    stdin_path: str
    stdout_path: str
    stderr_path: str
    stdout_text_status: str
    stdin: bytes
    stdout: bytes
    stderr: bytes
    verdict: str
    exit_code: int | None = None
    duration_sec: float | None = None


@dataclass(frozen=True)
class LoadedRound:
    id: str
    delivery: CapturedTree
    delivery_path: str
    requirements: tuple[Requirement, ...]
    checks: tuple[Check, ...]
    observations: tuple[Observation, ...]
    environment: Environment
    qa: QARecord | None


@dataclass(frozen=True)
class TrajectoryPoint:
    round_id: str
    check_id: str
    verdict: str
    stdin_path: str
    stdout_path: str
    stderr_path: str
    exit_code: int | None
    termination: str


@dataclass(frozen=True)
class Issue:
    requirement_id: str
    status: str
    points: tuple[TrajectoryPoint, ...]


@dataclass(frozen=True)
class QAContrast:
    round_id: str
    decision: str
    confirmed_false_release: bool
    counterexamples: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class Trajectory:
    analyzer: str
    issues: tuple[Issue, ...]
    qa_contrasts: tuple[QAContrast, ...]


@dataclass(frozen=True)
class VerifiedPack:
    protocol: str
    content_digest: str
    material: MaterialDeclaration
    review: ReviewIdentity
    rounds: tuple[LoadedRound, ...]
    trajectory: Trajectory
    analysis_mismatch: bool
    root: Any


@dataclass(frozen=True)
class VerifyReceipt:
    protocol: str
    content_digest: str
    material_id: str
    review_id: str
    source: str
    trajectory: Trajectory
    analysis_mismatch: bool
