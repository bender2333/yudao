# Loop System 领域对象：工件、事件与阶段。停止原因的清单在定义中（definitions/stop_reasons.json）

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .definitions import DEFINITIONS, DefinitionError

# 部门来自定义中的组织
DEPARTMENTS = DEFINITIONS.departments

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
# 基线核验逐条结论的状态（工单 #134，docs/design/existing-project-onboarding.md 第 4.5 节）
BASELINE_STATUSES = ("verified", "read_only", "existing_defect", "unsupported")
# 提案种类：定义中提交类工具提交的种类
PROPOSAL_KINDS = tuple(tool.proposal for tool in DEFINITIONS.tools.values() if tool.proposal is not None)


class EventType:
    RUN_CREATED = "run_created"
    USER_INPUT_RECEIVED = "user_input_received"
    PRODUCT_INPUT_ASSIGNED = "product_input_assigned"
    DEPARTMENT_GUIDANCE_RECEIVED = "department_guidance_received"
    DEPARTMENT_GUIDANCE_APPLIED = "department_guidance_applied"
    DEPARTMENT_GUIDANCE_RESPONDED = "department_guidance_responded"
    DEPARTMENT_ACTIVATED = "department_activated"
    DEPARTMENT_INPUT = "department_input"
    TOOL_CALL_REQUIRED = "tool_call_required"
    ACTIVATION_FINISHED = "activation_finished"
    CONTEXT_ASSEMBLED = "context_assembled"
    MODEL_REQUEST_SERIALIZED = "model_request_serialized"
    MODEL_REASONING = "model_reasoning"
    MODEL_MESSAGE = "model_message"
    MODEL_REQUESTED = "model_requested"
    MODEL_STREAM_PROGRESS = "model_stream_progress"
    MODEL_ATTEMPT_FINISHED = "model_attempt_finished"
    MODEL_ATTEMPT_FAILED = "model_attempt_failed"
    MODEL_RETRY_SCHEDULED = "model_retry_scheduled"
    COMPACTION_RECORDED = "compaction_recorded"
    TOOL_CALLED = "tool_called"
    TOOL_STARTED = "tool_started"
    TOOL_SKIPPED = "tool_skipped"
    ACTION_VERIFIED = "action_verified"
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
    STRUCTURE_ACCEPTED = "structure_accepted"
    BASELINE_REVIEW_ACCEPTED = "baseline_review_accepted"
    LESSON_CANDIDATE_RECORDED = "lesson_candidate_recorded"
    TRANSITION = "transition"
    RUN_DONE = "run_done"
    RUN_PAUSED = "run_paused"
    RUN_FAILED = "run_failed"
    RUN_RESUMED = "run_resumed"
    RUN_CONTINUED = "run_continued"
    DECISION_REQUESTED = "decision_requested"
    DECISION_ANSWERED = "decision_answered"
    DECISION_WITHDRAWN = "decision_withdrawn"


class ProjectEventType:
    PROJECT_REGISTERED = "project_registered"
    PROJECT_RENAMED = "project_renamed"
    PROJECT_GOAL_CHANGED = "project_goal_changed"
    PROJECT_PINNED = "project_pinned"
    PROJECT_ARCHIVED = "project_archived"
    PROJECT_RESTORED = "project_restored"
    WORK_ITEM_CREATED = "work_item_created"
    WORK_ITEM_START_FAILED = "work_item_start_failed"
    DELIVERABLE_ADOPTED = "deliverable_adopted"
    ADOPTION_HELD = "adoption_held"
    # 项目部门设置的三项写成同一种事件；事件种类字符串跨版本保持 department_prompt_configured（ADR-0019），
    # 只增加字段（provider_id、model_id、requested_tier）
    DEPARTMENT_SETTINGS_CONFIGURED = "department_prompt_configured"
    COMMAND_CONFIGURED = "command_configured"
    MATERIAL_RECORDED = "material_recorded"
    SOURCE_DIRECTORY_CONFIGURED = "source_directory_configured"
    # 建档 run 结束以后提出的初始 PRD 候选（工单 #136，设计第 3.2 节）：记下候选的引用与核验结论
    INITIAL_PRD_PROPOSED = "initial_prd_proposed"
    # 项目流中的决定请求、回答与撤回：确认初始 PRD 可能等待数天，run 已经结束，
    # 请求与回答记在项目流（设计第 3.2 节），字段与 run 流的三种决定事件相同
    PROJECT_DECISION_REQUESTED = "project_decision_requested"
    PROJECT_DECISION_ANSWERED = "project_decision_answered"
    PROJECT_DECISION_WITHDRAWN = "project_decision_withdrawn"
    # 用户提出修改：项目流记下这一轮的依据，启动时据此补建缺少的 run（设计第 3.3、6 节）
    ONBOARDING_REVISION_STARTED = "onboarding_revision_started"
    # 用户确认初始 PRD：这个成果成为项目的建档基线（设计第 3.2 节）
    BASELINE_ADOPTED = "baseline_adopted"
    # 项目级参数（迭代底座 B3，工单 #351）：检查时限与建档的单轮上限按项目设置，写在项目流中；
    # 事件种类字符串跨版本保持 project_parameter_set，与目录流的 parameter_set 是两个不同流的种类。
    # 没有项目级取值时使用全局的当前值
    PARAMETER_SET = "project_parameter_set"


class CatalogEventType:
    # 模型目录与凭据的事件（应用层与接口层设计说明第 10 节第 1 项）。
    # 内容仍由 Provider 模块保存；事件只带修订号、变化与结果，不含 Key
    CATALOG_REVISED = "catalog_revised"
    CATALOG_CANDIDATES_COLLECTED = "catalog_candidates_collected"
    CATALOG_TEST_FINISHED = "catalog_test_finished"
    CREDENTIAL_CHANGED = "credential_changed"
    # 排空与强制升级（3.1）：与目录事件同在一份流中，是控制主机这一份部署的长期事实（ADR-0019）
    RUNTIME_DRAIN_STARTED = "runtime_drain_started"
    RUNTIME_FORCE_UPGRADE_REQUESTED = "runtime_force_upgrade_requested"
    # 用户查看过的全局位置（界面工作线，工单 #127）：控制主机上只有一个，随部署长期保存
    HOME_SEEN = "home_seen"
    # 参数修改（迭代底座 B3，工单 #349）：参数是全局的，事件写进目录流，随部署长期保存
    PARAMETER_SET = "parameter_set"


GIT_VERSION_EVENTS = frozenset({
    EventType.RUN_CREATED, EventType.USER_INPUT_RECEIVED, EventType.SPEC_ACCEPTED,
    EventType.PRODUCT_DECISION_ACCEPTED, EventType.CONTRACT_ACCEPTED, EventType.PLAN_ACCEPTED,
    EventType.DELIVERY_ACCEPTED, EventType.QA_SUBMITTED, EventType.STRUCTURE_ACCEPTED,
    EventType.BASELINE_REVIEW_ACCEPTED,
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
class DepartmentGuidance:
    id: str
    run_id: str
    department: str
    version: int
    text: str
    guidance_ref: ArtifactRef
    created_event_id: str
    status: str
    applied_activation_id: str | None = None
    applied_context_event_id: str | None = None
    response_event_id: str | None = None
    response_status: str | None = None
    response_text: str | None = None


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
    # 发问方与回答方：旧版本的保存投影没有这两个字段，缺省为 None（未知），读取时按 request_id 查找对应请求
    requester: str | None = None
    recipient: str | None = None


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
    guidance_ids: list[str] = field(default_factory=list)
    guidance_only: bool = False


@dataclass
class Event:
    # run 流中的一条事件。position、stream、stream_version 是它在事件日志中的全局位置、所属的流与流内版本；
    # project_id、work_item_id、department 是日志为范围读取保存的列；epoch 是写入方的执行权编号；
    # command_id 是写入它的命令，不是由命令写入时为空；actor 是提出者：命令写入的事件为命令的提出者，
    # 其余事件为写入方声明的提出者，没有声明时为空
    event_id: str
    run_id: str
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
    position: int
    stream: str
    stream_version: int
    project_id: str | None
    work_item_id: str | None
    department: str | None
    epoch: int | None = None
    command_id: str | None = None
    actor: str | None = None

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
class ProjectEvent:
    # 项目流中的一条事件，与 run 事件在同一份事件日志中；日志中的位置与范围列同 Event
    event_id: str
    project_id: str
    type: str
    payload: dict[str, Any]
    created_at: str
    position: int
    stream: str
    stream_version: int
    work_item_id: str | None
    run_id: str | None
    department: str | None
    epoch: int | None = None
    command_id: str | None = None
    actor: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CatalogEvent:
    # 目录流中的一条事件。目录不属于项目或 run，范围列为空；日志中的位置与命令列同项目事件
    event_id: str
    type: str
    payload: dict[str, Any]
    created_at: str
    position: int
    stream: str
    stream_version: int
    project_id: str | None = None
    work_item_id: str | None = None
    run_id: str | None = None
    department: str | None = None
    epoch: int | None = None
    command_id: str | None = None
    actor: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CatalogProjection:
    # 目录流的投影：只记最后一条事件与最后一条 catalog_revised 的修订号。
    # 目录内容与凭据仍由 Provider 模块保存，这里不复制。
    # last_seen_position 是用户查看过的全局位置（工单 #127），控制主机上只有一个
    last_event_id: str | None = None
    stream_version: int = 0
    updated_at: str | None = None
    revision: int = 0
    last_seen_position: int | None = None
    last_seen_at: str | None = None


@dataclass
class DecisionRequest:
    # 一个等待用户回答的决定请求（总体架构第 7.4 节），由请求、回答与撤销三种事件折叠而成，是控制核心另外保存的投影。
    # 身份是请求事件的编号；request 是请求事件的载荷（种类、阻塞范围、选项与说明、事实引用与种类自己的内容）；
    # version 是请求的版本，回答命令的基准版本与它核对；status 为 open、answered 或 withdrawn
    decision_id: str
    stream: str
    run_id: str | None
    project_id: str | None
    work_item_id: str | None
    requested_at: str
    request: dict[str, Any]
    version: int = 1
    status: str = "open"
    answer: dict[str, Any] | None = None
    withdrawal: dict[str, Any] | None = None

    @property
    def kind(self) -> str:
        return self.request["kind"]

    @property
    def blocks(self) -> str:
        return self.request["blocks"]


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
    department_guidance: list[DepartmentGuidance] = field(default_factory=list)
    yielded_work: dict[str, Any] | None = None
    phase: str = "CREATED"
    active_department: str | None = None
    waiting_reason: str | None = None
    max_cycles: int = DEFINITIONS.rule_value("max_cycles")
    run_time_limit_sec: int = DEFINITIONS.rule_value("run_time_limit_sec")
    context_window: int = 32_000
    # 这个 run 中检查的时限（迭代底座 B3，工单 #351）：创建时按项目级取值与全局现值冻结，运行中不跟随修改
    check_timeout_sec: int = DEFINITIONS.rule_value("check_timeout_sec")
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
    model_requests: list[dict[str, Any]] = field(default_factory=list)
    # 每个部门最近一次请求解析出的调用目标公开部分（含选择来源），界面与审计读取这里
    department_call_targets: dict[str, dict[str, Any]] = field(default_factory=dict)
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
    # 事项种类（工单 #134）：普通事项为 change，建档事项为 onboarding；旧 run 的事件没有这个字段时为 change
    kind: str = "change"
    # 建档事项的产出：仓库概况与现有结构的工件引用（设计第 4.1、4.2 节）
    overview_ref: dict[str, Any] | None = None
    structure: dict[str, Any] | None = None
    baseline_review: dict[str, Any] | None = None
    # 建档修改轮的依据（工单 #136，设计第 3.3 节）：上一轮建档候选的事件编号与修改意见的工件引用；
    # 建档第一轮与普通事项没有这个字段
    onboarding_basis: dict[str, Any] | None = None
    # 建档的轮次（工单 #136）：第一轮为 1，修改轮逐轮加一；普通事项与旧 run 为 0
    round: int = 0
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
    structures: list[dict[str, Any]] = field(default_factory=list)
    baseline_reviews: list[dict[str, Any]] = field(default_factory=list)
    lesson_candidates: list[LessonCandidate] = field(default_factory=list)
    effective_decisions: list[ProductDecision] = field(default_factory=list)
    manifests: list[ContextManifest] = field(default_factory=list)
    compactions: list[dict[str, Any]] = field(default_factory=list)
    transitions: list[str] = field(default_factory=list)
    rejections: list[dict[str, Any]] = field(default_factory=list)
    pending_feedback: dict[str, dict[str, Any]] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    last_activations: dict[str, str] = field(default_factory=dict)
    project_id: str | None = None
    work_item_id: str | None = None
    baseline: dict[str, Any] | None = None
    snapshot: dict[str, Any] | None = None
    workspace_digest: str = ""
    project_context_ref: dict[str, Any] | None = None
    prompt_config_versions: dict[str, int] = field(default_factory=dict)
    registered_commands: dict[str, Any] = field(default_factory=dict)
    command_versions: dict[str, int] = field(default_factory=dict)
    last_event_id: str | None = None
    # 投影所反映的 run 流版本
    stream_version: int = 0
    # 创建这个 run 时记录的 run 事件版本（ADR-0019）；旧 run 没有这个字段时为 0，与当前版本不同
    run_event_version: int = 0
    # 创建这个 run 时记录的定义版本（ADR-0014）：恢复继续旧事项时与当前加载的版本比较（工单 #16）
    definitions_version: str = ""
    # 创建这个 run 时冻结的参数版本（工单 #349）：运行中不跟随参数修改
    parameters_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json_dumps(self))

    def canonical_state(self) -> dict[str, Any]:
        data = self.to_dict()
        data.pop("last_event_id", None)
        return data

    @property
    def provider_bindings(self) -> dict[str, dict[str, Any]]:
        # 每个部门最近一次请求解析出的调用目标；还没有请求时为空
        return self.department_call_targets


# ---------------------------------------------------------------------------
# 项目投影：由项目流的事件折叠而成；事项的状态等字段在读取时由所属 run 的投影派生，不保存


@dataclass
class Adoption:
    adoption_id: str
    work_item_id: str
    run_id: str
    delivery_event_id: str
    qa_event_id: str
    tree_ref: dict[str, Any]
    code_tree_digest: str
    summary: str
    files: list[str]
    check_names: list[str]
    known_risks: list[str]
    previous_adoption_id: str | None
    adopted_at: str
    stream_version: int
    event_id: str
    # 建档基线特有的三项（工单 #136，设计第 5 节）：被确认的初始 PRD、现有结构说明与代码快照。
    # 普通事项的交付采纳没有这三项，它们为空
    prd_ref: dict[str, Any] | None = None
    product_spec_hash: str | None = None
    structure_ref: dict[str, Any] | None = None
    snapshot: dict[str, Any] | None = None
    # 建档基线中状态为 existing_defect 的结论（工单 #136）：现有缺陷数按它计数，
    # known_risks 还包含未被结论覆盖的其他失败
    existing_defects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)



@dataclass
class InitialPrdCandidate:
    # 一个建档候选（工单 #136，设计第 3.3 节）：建档 run 结束以后提出的初始 PRD 及其依据。
    # prd、structure、baseline_review 是这一轮三份产物的事件编号、内容哈希与工件引用；
    # overview_ref 是仓库概况的工件引用；snapshot 是这一轮建档使用的代码快照；
    # revision_note_ref 是上一轮用户的修改意见（第二轮起）
    work_item_id: str
    run_id: str
    round: int
    prd: dict[str, Any]
    structure: dict[str, Any]
    baseline_review: dict[str, Any]
    overview_ref: dict[str, Any]
    snapshot: dict[str, Any]
    proposed_at: str
    stream_version: int
    event_id: str
    revision_note_ref: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass
class HeldCandidate:
    work_item_id: str
    run_id: str
    delivery_event_id: str
    code_tree_digest: str
    reason: str
    expected_adoption_id: str | None
    current_adoption_id: str | None
    held_at: str
    stream_version: int
    event_id: str

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass
class DepartmentSetting:
    # 项目部门设置：模型访问定义引用、请求档位与部门 Prompt 三项，都可以不写入；
    # 三项一起保存、一个版本（设计说明第 5.2 节）。没有写入的项使用部门默认，部门 Prompt 没有写入时使用内置默认 Prompt。
    department: str
    version: int
    text: str
    source: str
    provider_id: str | None = None
    model_id: str | None = None
    requested_tier: str | None = None
    configured_prompt: bool = False
    prompt_ref: dict[str, Any] | None = None
    base_version: int | None = None
    updated_at: str | None = None
    event_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass
class Material:
    material_id: str
    text: str
    material_ref: dict[str, Any]
    department: str | None
    recorded_at: str
    stream_version: int
    event_id: str

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass
class SourceDirectory:
    # 项目登记的源目录：名称是登记名，路径是控制主机上的路径；
    # 版本是该条登记的版本，作为 source_directory.save 的基准版本
    name: str
    path: str
    version: int
    base_version: int | None = None
    updated_at: str | None = None
    event_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass
class RegisteredCommand:
    name: str
    version: int
    argv: list[str]
    args: list[str]
    timeout_sec: int
    output_limit: int
    base_version: int | None = None
    updated_at: str | None = None
    event_id: str | None = None
    # 登记时声明「可以重新执行」（恢复契约第 4 节，工单 #242）；旧事件没有这个字段时为否
    repeatable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    def frozen(self) -> dict[str, Any]:
        # 事项创建时冻结进 run 的执行形态：只有固定参数与限额，没有版本管理字段
        return {"argv": list(self.argv), "args": list(self.args),
                "timeout_sec": self.timeout_sec, "output_limit": self.output_limit,
                "repeatable": self.repeatable}


@dataclass
class WorkItem:
    work_item_id: str
    title: str
    text: str
    run_id: str
    baseline: dict[str, Any] | None
    project_context_ref: dict[str, Any]
    prompt_config_versions: dict[str, int]
    max_cycles: int
    run_time_limit_sec: int
    context_window: int
    created_at: str
    stream_version: int
    event_id: str
    snapshot: dict[str, Any] | None = None
    start_error: str | None = None
    # 事项种类：普通事项为 change，建档事项为 onboarding；旧事件缺省为 change
    kind: str = "change"
    command_versions: dict[str, int] = field(default_factory=dict)
    # 以下字段由所属 run 的投影派生，不存事件。
    status: str = "not_started"
    department: str | None = None
    phase: str | None = None
    stop_reason: str | None = None
    human_action: str | None = None
    cycle_count: int = 0
    last_handoff: dict[str, Any] | None = None
    rework: list[dict[str, Any]] = field(default_factory=list)
    pending_question: str | None = None
    adoption_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass
class ProjectProjection:
    project_id: str = ""
    name: str = ""
    goal: str = ""
    goal_ref: dict[str, Any] | None = None
    source: str = "idea"
    created_at: str = ""
    pinned: bool = False
    archived: bool = False
    # 起始文件夹快照记录（工单 #321）：新建项目时给出的起点文件夹的只读采集结果，所属范围是项目。
    # 旧事件没有这个字段时缺省为没有起始文件夹（ADR-0019）
    initial_snapshot: dict[str, Any] | None = None
    work_items: list[WorkItem] = field(default_factory=list)
    current_adoption: Adoption | None = None
    adoptions: list[Adoption] = field(default_factory=list)
    held: list[HeldCandidate] = field(default_factory=list)
    # 各轮建档候选（工单 #136）：等待确认的与已被确认或提出修改的候选都在这里，按提出顺序
    initial_prd_candidates: list[InitialPrdCandidate] = field(default_factory=list)
    department_settings: dict[str, DepartmentSetting] = field(default_factory=dict)
    department_setting_history: list[DepartmentSetting] = field(default_factory=list)
    commands: dict[str, RegisteredCommand] = field(default_factory=dict)
    command_history: list[RegisteredCommand] = field(default_factory=list)
    materials: list[Material] = field(default_factory=list)
    source_directories: dict[str, SourceDirectory] = field(default_factory=dict)
    source_directory_history: list[SourceDirectory] = field(default_factory=list)
    active_work_item_id: str | None = None
    updated_at: str = ""
    # 投影所反映的项目流版本
    stream_version: int = 0
    last_event_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    def canonical_state(self) -> dict[str, Any]:
        data = self.to_dict()
        data.pop("last_event_id", None)
        return data

    def work_item(self, work_item_id: str) -> WorkItem | None:
        return next((item for item in self.work_items if item.work_item_id == work_item_id), None)

    def work_item_for_run(self, run_id: str) -> WorkItem | None:
        return next((item for item in self.work_items if item.run_id == run_id), None)


def _plain(value: Any) -> Any:
    return json.loads(json_dumps(value))


def department_for_phase(phase: str) -> str | None:
    if phase in PRODUCT_ACTIVE:
        return "product"
    if phase in ENGINEERING_ACTIVE:
        return "engineering"
    if phase in QUALITY_ACTIVE:
        return "quality"
    return None


# 阶段迁移是控制核心的状态机，只为这些部门写了阶段；定义中的部门必须与它们相同，否则启动失败
_PHASE_DEPARTMENTS = [department_for_phase(phase) for phase in ("PRODUCT_SPEC", "ENGINEERING", "QUALITY")]
if list(DEPARTMENTS) != _PHASE_DEPARTMENTS:
    raise DefinitionError([("organization.json", "departments",
                            "控制核心的阶段迁移按顺序支持部门 " + "、".join(_PHASE_DEPARTMENTS))])


# 停止原因的中文名：等待说明与事件说明按中文写，机器标识不直接出现在给用户看的文字里
STOP_REASON_LABELS = {
    "released": "已完成并放行",
    "baseline_verified": "已完成基线核验",
    "max_cycles": "循环次数已达上限",
    "model_steps_exhausted": "部门步数已达上限",
    "no_tool_call": "部门连续多次没有调用工具",
    "workspace_unrepresentable": "工作区有无法表示的条目",
    "time_limit": "运行时间已达上限",
    "cancelled": "运行已被取消",
    "provider_error": "模型服务失败",
    "provider_timeout": "模型服务请求超时",
    "provider_protocol": "模型服务协议不符",
    "unsupported_protocol": "不支持的协议",
    "retry_after_too_long": "要求等待的时间过长",
    "context_overflow": "上下文超过窗口",
    "compaction_failed": "上下文压缩失败",
    "host_commit_error": "主机保存失败",
    "run_event_version_changed": "因 Yudao 升级停止",
}
if set(STOP_REASON_LABELS) != set(DEFINITIONS.stop_reasons):
    raise DefinitionError([("stop_reasons.json", "stop_reasons",
                            "停止原因的中文名必须与定义的停止原因相同：" + "、".join(STOP_REASON_LABELS))])


def stop_reason_name(reason: str | None) -> str:
    # 停止原因的中文名；没有登记的取值原样返回，说明里不丢掉这个事实
    return STOP_REASON_LABELS.get(reason or "", reason or "")


def waiting_reason_for(phase: str, stop_reason: str | None = None) -> str | None:
    if phase == "DONE":
        return None
    if phase in TERMINAL_PHASES:
        # 暂停与失败都带停止原因的中文名；没有停止原因时只写阶段，不猜具体原因
        reason = {"PAUSED": "已暂停", "FAILED": "未能完成"}[phase]
        return f"{reason}：{stop_reason_name(stop_reason)}" if stop_reason else reason
    return {
        "CREATED": "等待产品开始处理",
        "PRODUCT_SPEC": "产品正在整理有效需求",
        "ENGINEERING": "工程正在按有效需求实现",
        "DELIVERY": "交付已被接受，正在送到质检",
        "QUALITY": "质检正在独立核验交付",
        "REWORK_PRODUCT": "质检已退回产品",
        "REWORK_ENGINEERING": "质检已退回工程",
    }[phase]


def spec_content_hash(kind: str, payload: dict[str, Any], *, parent_hash: str | None, revision: int) -> str:
    return canonical_hash(
        {
            "kind": kind,
            "parent_hash": parent_hash,
            "payload": payload,
            "revision": revision,
        }
    )
