"""Loop System 领域对象：工件、事件、阶段和停止原因。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

DEPARTMENTS = ("product", "engineering", "quality")

PHASES = (
    "CREATED",
    "PRODUCT_SPEC",
    "ENGINEERING",
    "DELIVERY",
    "QUALITY",
    "REWORK_PRODUCT",
    "REWORK_ENGINEERING",
    "DONE",
    "PAUSED",
    "FAILED",
)

TERMINAL_PHASES = frozenset({"DONE", "PAUSED", "FAILED"})

PRODUCT_ACTIVE = frozenset({"PRODUCT_SPEC", "REWORK_PRODUCT"})
ENGINEERING_ACTIVE = frozenset({"ENGINEERING", "REWORK_ENGINEERING"})
QUALITY_ACTIVE = frozenset({"QUALITY", "DELIVERY"})

QA_VERDICTS = ("rework_product", "rework_engineering", "release")
PROPOSAL_KINDS = (
    "product_spec",
    "engineering_plan",
    "collaboration_request",
    "collaboration_response",
    "product_decision",
    "delivery_spec",
    "qa_review",
)

PAUSED_REASONS = frozenset({"max_cycles", "model_steps_exhausted"})
FAILED_REASONS = frozenset(
    {
        "provider_error",
        "provider_timeout",
        "provider_unavailable",
        "provider_credentials_lost",
        "cancelled",
        "context_overflow",
        "compaction_failed",
        "host_commit_error",
    }
)

HUMAN_ACTIONS = {
    "model_steps_exhausted": "部门连续调用模型仍未提交有效提案。检查最后一次模型输出与工具回执后，调整任务并新建运行。",
    "max_cycles": "循环次数已达上限。检查最后一次部门输出与事件后，提高 max_cycles 并新建 run，或在当前阶段人工介入。",
}


class EventType:
    RUN_CREATED = "run_created"
    USER_INPUT_RECEIVED = "user_input_received"
    PRODUCT_INPUT_ASSIGNED = "product_input_assigned"
    DEPARTMENT_PROMPT_UPDATED = "department_prompt_updated"
    DEPARTMENT_ACTIVATED = "department_activated"
    DEPARTMENT_INPUT = "department_input"
    ACTIVATION_FINISHED = "activation_finished"
    CONTEXT_ASSEMBLED = "context_assembled"
    MODEL_REQUEST_SERIALIZED = "model_request_serialized"
    MODEL_MESSAGE = "model_message"
    MODEL_REQUESTED = "model_requested"
    MODEL_ATTEMPT_FINISHED = "model_attempt_finished"
    MODEL_ATTEMPT_FAILED = "model_attempt_failed"
    MODEL_RETRY_SCHEDULED = "model_retry_scheduled"
    COMPACTION_RECORDED = "compaction_recorded"
    TOOL_CALLED = "tool_called"
    TOOL_STARTED = "tool_started"
    TOOL_SKIPPED = "tool_skipped"
    PROPOSAL_SUBMITTED = "proposal_submitted"
    PROPOSAL_REJECTED = "proposal_rejected"
    SPEC_ACCEPTED = "spec_accepted"
    SPEC_SUPERSEDED = "spec_superseded"
    CONTRACT_ACCEPTED = "contract_accepted"
    PLAN_ACCEPTED = "plan_accepted"
    COLLABORATION_REQUESTED = "collaboration_requested"
    COLLABORATION_RESPONDED = "collaboration_responded"
    COLLABORATION_CLOSED = "collaboration_closed"
    PRODUCT_DECISION_ACCEPTED = "product_decision_accepted"
    DELIVERY_ACCEPTED = "delivery_accepted"
    QA_SUBMITTED = "qa_submitted"
    LESSON_CANDIDATE_RECORDED = "lesson_candidate_recorded"
    TRANSITION = "transition"
    RUN_DONE = "run_done"
    RUN_PAUSED = "run_paused"
    RUN_FAILED = "run_failed"


GIT_VERSION_EVENTS = frozenset({
    EventType.RUN_CREATED, EventType.USER_INPUT_RECEIVED, EventType.SPEC_ACCEPTED,
    EventType.PRODUCT_DECISION_ACCEPTED, EventType.CONTRACT_ACCEPTED, EventType.PLAN_ACCEPTED,
    EventType.DELIVERY_ACCEPTED, EventType.QA_SUBMITTED,
})


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)


def _json_default(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"not json serializable: {type(value)!r}")


def canonical_hash(value: Any) -> str:
    data = json_dumps(value).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def hash_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


@dataclass(frozen=True)
class ArtifactRef:
    kind: str
    content_hash: str
    path: str
    media_type: str | None = None


@dataclass(frozen=True)
class UserInput:
    id: str
    run_id: str
    version: int
    text: str
    kind: str
    input_ref: ArtifactRef
    intend_ref: ArtifactRef
    byte_start: int
    byte_end: int
    created_event_id: str


@dataclass(frozen=True)
class DepartmentPrompt:
    department: str
    version: int
    text: str
    prompt_ref: ArtifactRef
    created_event_id: str


@dataclass(frozen=True)
class CheckReceipt:
    name: str
    department: str
    exit_code: int
    summary: str
    snapshot_hash: str
    product_spec_hash: str | None = None
    delivery_spec_hash: str | None = None
    activation_id: str | None = None
    tree_changed: bool = False
    effective_contract_hash: str | None = None
    engineering_plan_hash: str | None = None


@dataclass(frozen=True)
class ProductSpec:
    id: str
    run_id: str
    revision: int
    parent_hash: str | None
    content_hash: str
    issuer: str
    status: str
    created_event_id: str
    goal: str
    requirements: list[str]
    boundaries: list[str]
    constraints: list[str]
    acceptance_criteria: list[str]
    fatal_conditions: list[str]
    non_goals: list[str]
    decision_changes: list[dict[str, str]]
    change_record: dict[str, Any] | None
    input_version: int


@dataclass(frozen=True)
class CollaborationRequest:
    id: str
    run_id: str
    content_hash: str
    created_event_id: str
    requester: str
    recipient: str
    request_type: str
    action: str | None
    question: str
    background: str
    expected_result: str
    basis: dict[str, Any]
    return_phase: str
    status: str


@dataclass(frozen=True)
class CollaborationResponse:
    id: str
    run_id: str
    content_hash: str
    created_event_id: str
    request_id: str
    status: str
    text: str
    result_event_ids: list[str]
    return_phase: str
    return_work_valid: bool


@dataclass(frozen=True)
class ProductDecision:
    id: str
    run_id: str
    content_hash: str
    created_event_id: str
    product_spec_hash: str
    statement: str
    rationale: str
    request_id: str | None


@dataclass(frozen=True)
class EffectiveContract:
    content_hash: str
    revision: int
    product_spec_hash: str
    input_version: int
    decision_hashes: list[str]
    created_event_id: str
    prd_ref: ArtifactRef


@dataclass(frozen=True)
class EngineeringPlan:
    id: str
    run_id: str
    content_hash: str
    revision: int
    parent_hash: str | None
    status: str
    created_event_id: str
    effective_contract_hash: str
    objective: str
    scope: list[str]
    tasks: list[dict[str, Any]]
    refactoring: list[str]
    assumptions: list[dict[str, str]]
    reason: str
    plan_ref: ArtifactRef


@dataclass(frozen=True)
class DeliverySpec:
    id: str
    run_id: str
    revision: int
    parent_hash: str | None
    content_hash: str
    issuer: str
    status: str
    created_event_id: str
    product_spec_hash: str
    effective_contract_hash: str
    engineering_plan_hash: str
    summary: str
    files: list[str]
    check_names: list[str]
    checks: list[dict[str, Any]]
    known_risks: list[str]
    code_tree_digest: str
    tree_ref: ArtifactRef
    invalidation_reason: str | None = None


@dataclass(frozen=True)
class Defect:
    severity: str
    summary: str


@dataclass(frozen=True)
class QAReview:
    id: str
    run_id: str
    revision: int
    parent_hash: str | None
    content_hash: str
    issuer: str
    status: str
    created_event_id: str
    product_spec_hash: str
    effective_contract_hash: str
    engineering_plan_hash: str
    delivery_spec_hash: str
    code_snapshot_hash: str
    verdict: str
    rationale: str
    checks: list[dict[str, Any]]
    defects: list[Defect]
    evidence_refs: list[ArtifactRef]


@dataclass(frozen=True)
class LessonCandidate:
    id: str
    run_id: str
    created_event_id: str
    source_event_id: str
    source_type: str
    observation: dict[str, Any]
    suggestion: str
    product_spec_hash: str | None
    delivery_spec_hash: str | None
    checks: list[dict[str, Any]]
    evidence_refs: list[ArtifactRef]
    status: str


@dataclass(frozen=True)
class ContextSource:
    source: str
    version: str | None
    tokens: int
    digest: str | None = None


@dataclass(frozen=True)
class ContextExclusion:
    source: str
    reason: str


@dataclass(frozen=True)
class ContextManifest:
    session_id: str
    department: str
    activation_id: str
    injected: list[ContextSource]
    excluded: list[ContextExclusion]
    token_estimate: int
    budget: int
    digest: str
    truncated: bool = False
    step_id: int = 1
    request_ref: dict[str, Any] | None = None
    admitted: bool = False
    source_event_id: str | None = None
    purpose: str = "work"
    max_output_tokens: int | None = None
    compaction_event_id: str | None = None
    effective_contract_hash: str | None = None
    engineering_plan_hash: str | None = None
    request_id: str | None = None
    input_version: int = 0
    prompt_version: int = 0
    prompt_hash: str | None = None
    input_token_estimate: int | None = None
    output_reserve_tokens: int = 0
    parts_ref: dict[str, Any] | None = None


@dataclass
class Event:
    event_id: str
    run_id: str
    seq: int
    type: str
    role: str | None
    parent_event_id: str | None
    state_before: str
    state_after: str
    payload: dict[str, Any]
    artifact_hashes: list[str]
    session_id: str | None
    provider: str | None
    model: str | None
    context_digest: str | None
    stop_reason: str | None
    error: str | None
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> dict[str, Any]:
        payload = self.payload
        brief = {
            "kind": payload.get("kind"),
            "decision": payload.get("decision"),
            "verdict": payload.get("verdict"),
            "goal": payload.get("goal"),
            "question": payload.get("question"),
            "summary": payload.get("summary"),
            "from": payload.get("from_phase") or payload.get("from"),
            "to": payload.get("to_phase") or payload.get("to"),
            "errors": payload.get("errors"),
            "human_action": payload.get("human_action"),
        }
        return {key: value for key, value in brief.items() if value not in (None, [], {})}


@dataclass
class SessionRecord:
    session_id: str
    department: str
    status: str
    activations: int = 0


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    latency_ms: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reported: bool = True
    cost_reported: bool = False

    def plus(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            cost=self.cost + other.cost,
            latency_ms=self.latency_ms + other.latency_ms,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            reported=self.reported and other.reported,
            cost_reported=self.cost_reported and other.cost_reported,
        )


@dataclass
class RunProjection:
    run_id: str = ""
    task: str = ""
    intend_ref: dict[str, Any] | None = None
    git_version: dict[str, str | None] | None = None
    git_versions: list[dict[str, Any]] = field(default_factory=list)
    input_version: int = 0
    product_work_input_version: int = 0
    processed_input_version: int = 0
    inputs: list[UserInput] = field(default_factory=list)
    department_prompts: dict[str, DepartmentPrompt] = field(default_factory=dict)
    prompt_versions: list[DepartmentPrompt] = field(default_factory=list)
    phase: str = "CREATED"
    active_department: str | None = None
    waiting_reason: str | None = None
    max_cycles: int = 8
    context_window: int = 32_000
    cycle_count: int = 0
    token_used: int = 0
    cost: float = 0.0
    latency_ms: int = 0
    tool_count: int = 0
    rework_count: int = 0
    request_count: int = 0
    provider: str = "fake"
    adapter: str = "fake"
    model: str | None = None
    provider_snapshot: dict[str, Any] = field(default_factory=dict)
    model_requests: list[dict[str, Any]] = field(default_factory=list)
    requested_provider: str | None = None
    requested_model: str | None = None
    actual_provider: str | None = None
    actual_model: str | None = None
    outcome: str = "running"
    stop_reason: str | None = None
    human_action: str | None = None
    error: str | None = None
    product_spec: ProductSpec | None = None
    effective_contract: EffectiveContract | None = None
    engineering_plan: EngineeringPlan | None = None
    delivery_spec: DeliverySpec | None = None
    pending_request: CollaborationRequest | None = None
    last_review: QAReview | None = None
    sessions: dict[str, SessionRecord] = field(default_factory=dict)
    product_specs: list[ProductSpec] = field(default_factory=list)
    effective_contracts: list[EffectiveContract] = field(default_factory=list)
    engineering_plans: list[EngineeringPlan] = field(default_factory=list)
    delivery_specs: list[DeliverySpec] = field(default_factory=list)
    requests: list[CollaborationRequest] = field(default_factory=list)
    responses: list[CollaborationResponse] = field(default_factory=list)
    request_results: list[dict[str, Any]] = field(default_factory=list)
    product_decisions: list[ProductDecision] = field(default_factory=list)
    reviews: list[QAReview] = field(default_factory=list)
    lesson_candidates: list[LessonCandidate] = field(default_factory=list)
    effective_decisions: list[ProductDecision] = field(default_factory=list)
    manifests: list[ContextManifest] = field(default_factory=list)
    compactions: list[dict[str, Any]] = field(default_factory=list)
    transitions: list[str] = field(default_factory=list)
    rejections: list[dict[str, Any]] = field(default_factory=list)
    pending_feedback: dict[str, dict[str, Any]] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    last_activations: dict[str, str] = field(default_factory=dict)
    last_event_id: str | None = None
    last_seq: int = 0

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json_dumps(self))

    def canonical_state(self) -> dict[str, Any]:
        data = self.to_dict()
        data.pop("last_event_id", None)
        return data

    @property
    def provider_bindings(self) -> dict[str, dict[str, Any]]:
        departments = self.provider_snapshot.get("departments")
        if not isinstance(departments, dict):
            return {}
        return departments


def department_for_phase(phase: str) -> str | None:
    if phase in PRODUCT_ACTIVE:
        return "product"
    if phase in ENGINEERING_ACTIVE:
        return "engineering"
    if phase in QUALITY_ACTIVE:
        return "quality"
    return None


def waiting_reason_for(phase: str, stop_reason: str | None = None) -> str | None:
    if phase == "DONE":
        return None
    if phase == "PAUSED":
        return f"paused:{stop_reason or 'unspecified'}"
    if phase == "FAILED":
        return f"failed:{stop_reason or 'unspecified'}"
    return {
        "CREATED": "waiting to start product spec",
        "PRODUCT_SPEC": "product is drafting ProductSpec",
        "ENGINEERING": "engineering is implementing against the current ProductSpec",
        "DELIVERY": "delivery accepted; routing to quality",
        "QUALITY": "quality is independently reviewing delivery",
        "REWORK_PRODUCT": "quality returned work to product",
        "REWORK_ENGINEERING": "quality returned work to engineering",
    }.get(phase, phase)


def spec_content_hash(kind: str, payload: dict[str, Any], *, parent_hash: str | None, revision: int) -> str:
    return canonical_hash(
        {
            "kind": kind,
            "parent_hash": parent_hash,
            "payload": payload,
            "revision": revision,
        }
    )
