# Loop System 应用侧的领域对象：工件、成果、投影与阶段。停止原因的清单在定义中（definitions/stop_reasons.json）
#
# 事件信封与骨架事件在内核事件模块（harness/kernel_events.py，S5a 工单 #828）：它们由内核写入与读取，
# 种类与字段只增。这个文件把信封、骨架事件的种类与算摘要的辅助从这里转出，应用的导入照旧；
# 与 projection.py 一起，S5a 起它们不再算内核（不再列入 harness/definitions/kernel-manifest.json），
# 产品的 17 个模块与 45 个测试文件继续按原样导入它们。

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any

from .actions import CheckReceipt
from .definitions import DEFINITIONS, UnknownStopReason
from .kernel_events import (
    BASELINE_STATUSES,
    RUN_STATUSES,
    TERMINAL_STATUSES,
    CatalogEvent,
    CatalogEventType,
    DecisionRequest,
    Event,
    ProjectEvent,
    ProjectEventType,
    QA_VERDICTS,
    SkeletonEventType,
    canonical_hash,
    json_dumps,
    new_id,
    spec_content_hash,
    utc_now,
)

# 部门来自定义中的组织
DEPARTMENTS = DEFINITIONS.departments

# run 的状态与骨架事件载荷里的封闭取值都由内核事件模块给出（它们是事件信封与骨架事件的一部分），
# 这里随其他导入一起转出给应用用

# 提案种类的清单不再在这里算（S2c，工单 #1098）：工具许可与提案校验按这个事项所用的那份定义读，
# 读法在 harness/tools.py 的 proposal_kinds_of；模块加载时算好的那份清单会让第二种路由带来的种类看不到


class EventType(SkeletonEventType):
    # run 流的事件种类：骨架事件的种类由内核事件模块给出（SkeletonEventType），这里接着声明应用事件的部分。
    # 应用事件由应用登记（设计说明第 5.4 节第 1 条，S5a 工单 #828），骨架事件不在这里重复写一遍
    USER_INPUT_RECEIVED = "user_input_received"
    PRODUCT_INPUT_ASSIGNED = "product_input_assigned"
    DEPARTMENT_GUIDANCE_RECEIVED = "department_guidance_received"
    DEPARTMENT_GUIDANCE_APPLIED = "department_guidance_applied"
    DEPARTMENT_GUIDANCE_RESPONDED = "department_guidance_responded"
    DEPARTMENT_INPUT = "department_input"
    TOOL_CALL_REQUIRED = "tool_call_required"
    CONTEXT_ASSEMBLED = "context_assembled"
    MODEL_REQUEST_SERIALIZED = "model_request_serialized"
    MODEL_REASONING = "model_reasoning"
    MODEL_MESSAGE = "model_message"
    MODEL_STREAM_PROGRESS = "model_stream_progress"
    MODEL_ATTEMPT_FINISHED = "model_attempt_finished"
    MODEL_ATTEMPT_FAILED = "model_attempt_failed"
    MODEL_RETRY_SCHEDULED = "model_retry_scheduled"
    COMPACTION_RECORDED = "compaction_recorded"
    TOOL_SKIPPED = "tool_skipped"
    ACTION_VERIFIED = "action_verified"
    ASK_STARTED = "ask_started"
    ASK_ANSWERED = "ask_answered"
    QA_TESTS_SAVED = "qa_tests_saved"
    LESSON_CANDIDATE_RECORDED = "lesson_candidate_recorded"

# ProjectEventType 与 CatalogEventType 由内核事件模块给出：项目流与目录流的事件全部是骨架事件

GIT_VERSION_EVENTS = frozenset({
    EventType.RUN_CREATED, EventType.USER_INPUT_RECEIVED, EventType.SPEC_ACCEPTED,
    EventType.PRODUCT_DECISION_ACCEPTED, EventType.CONTRACT_ACCEPTED,
    EventType.DELIVERY_ACCEPTED, EventType.QA_SUBMITTED, EventType.STRUCTURE_ACCEPTED,
    EventType.BASELINE_REVIEW_ACCEPTED,
})



def hash_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def estimate_tokens(text: str) -> int:
    # 本地估算按 UTF-8 字节数除以 4（模型管理设计说明第 8.2 节）：中文一个字至少三个字节，
    # 按字符数除以 4 会把以中文为主的材料估成实际用量的一半以下。
    if not text:
        return 0
    return max(1, (len(text.encode("utf-8")) + 3) // 4)


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
    # 三种状态（部门指导设计说明第 3 节，工单 #1039）：received 已接收、in_input 已进入模型输入、
    # answered 已回答。已回答由主机在收到它的那一轮工作正常结束时写入，部门不提交（工单 #1038、#1039）
    status: str
    applied_activation_id: str | None = None
    applied_context_event_id: str | None = None
    answered_event_id: str | None = None
    answered_activation_id: str | None = None
    outcome: str | None = None


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
class ProductDecision:
    id: str
    run_id: str
    content_hash: str
    created_event_id: str
    product_spec_hash: str
    statement: str
    rationale: str


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
    delivery_spec_hash: str
    code_snapshot_hash: str
    verdict: str
    rationale: str
    checks: list[dict[str, Any]]
    defects: list[Defect]
    evidence_refs: list[ArtifactRef]
    # 逐条结论与放行记录里的三个数（验证的独立性设计说明第 7.1 节，工单 #151）：旧事件没有这几项
    criteria: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    open_criteria: list[str] = field(default_factory=list)


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
    input_version: int = 0
    prompt_version: int = 0
    prompt_hash: str | None = None
    input_token_estimate: int | None = None
    output_reserve_tokens: int = 0
    parts_ref: dict[str, Any] | None = None
    guidance_ids: list[str] = field(default_factory=list)


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
    # run 的状态（工单 #556）：进行中与三个终态。部门进行到哪一步不记在这里
    status: str = "running"
    active_department: str | None = None
    waiting_reason: str | None = None
    max_cycles: int = DEFINITIONS.rule_value("max_cycles")
    run_time_limit_sec: int = DEFINITIONS.rule_value("run_time_limit_sec")
    cycle_count: int = 0
    token_used: int = 0
    cost: float = 0.0
    latency_ms: int = 0
    tool_count: int = 0
    rework_count: int = 0
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
    stop_reason: str | None = None
    human_action: str | None = None
    error: str | None = None
    product_spec: ProductSpec | None = None
    effective_contract: EffectiveContract | None = None
    delivery_spec: DeliverySpec | None = None
    # 还没回答的询问：链上的每一层一个，最内层（正在被回答的那一层）在最后（工单 #473）。
    # 嵌套询问时外层还在等内层，内层回答以后回到外层。
    ask_stack: list[dict[str, Any]] = field(default_factory=list)
    # 开过的询问分支会话：分支是部门主线之外的另一条会话，
    # 它的激活不改部门主线的会话记录与最近激活（工单 #473）
    branch_sessions: list[str] = field(default_factory=list)
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
    # 每个部门上一次工作时采用的工作依据（有效合同的摘要）：部门关注的成果有了新版本时用它判断
    # 这个部门是不是已经看过当前这一版（工单 #557：质检关注「PRD 被接纳」）
    department_bases: dict[str, str] = field(default_factory=dict)
    # 每个部门这一轮开始时面对的交付（工单 #557）：质检的检查工作区由它建立，
    # 没有交付时这一轮没有可以核验的对象，提交结论被拒绝
    department_delivery_bases: dict[str, str] = field(default_factory=dict)
    product_specs: list[ProductSpec] = field(default_factory=list)
    effective_contracts: list[EffectiveContract] = field(default_factory=list)
    delivery_specs: list[DeliverySpec] = field(default_factory=list)
    product_decisions: list[ProductDecision] = field(default_factory=list)
    reviews: list[QAReview] = field(default_factory=list)
    structures: list[dict[str, Any]] = field(default_factory=list)
    baseline_reviews: list[dict[str, Any]] = field(default_factory=list)
    lesson_candidates: list[LessonCandidate] = field(default_factory=list)
    effective_decisions: list[ProductDecision] = field(default_factory=list)
    manifests: list[ContextManifest] = field(default_factory=list)
    compactions: list[dict[str, Any]] = field(default_factory=list)
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
    last_event_id: str | None = None
    # 投影所反映的 run 流版本
    stream_version: int = 0
    # 创建这个 run 时记录的 run 事件版本（ADR-0019）；旧 run 没有这个字段时为 0，与当前版本不同
    run_event_version: int = 0
    # 创建这个 run 时记录的定义版本（总体架构第 3 节第 7 条）：恢复继续旧事项时与当前加载的版本比较（工单 #16）
    definitions_version: str = ""
    # 创建这个 run 时冻结的参数版本（工单 #349）：运行中不跟随参数修改
    parameters_version: str = ""
    # 建 run 时冻结的参数快照（工单 #1189）：13 项取值、全局参数版本、项目覆盖来源、事项实限与定义版本。
    # 旧 run 的创建事件没有这个字段时为空，读取方按该事件所记录的定义版本的定义初值解释
    parameters: dict[str, Any] | None = None
    # 建 run 时冻结的 MCP 服务器设置（工单 #236）：运行投影只保存版本、文档摘要与服务器名称，
    # 不保存整份设置（设置在 run_created 与事项创建事实里）；旧 run 没有这个字段时为空设置
    mcp_servers_version: int = 0
    mcp_servers_digest: str = ""
    mcp_servers_names: list[str] = field(default_factory=list)
    qa_tests_version: int = 0
    qa_tests_hash: str | None = None
    qa_tests_archive_ref: dict[str, Any] | None = None

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

    @property
    def active_ask(self) -> dict[str, Any] | None:
        # 正在被回答的那一次询问：链上最内层的那一个（工单 #473 的嵌套询问）
        return self.ask_stack[-1] if self.ask_stack else None

    def ask_by_origin(self, session_id: str | None) -> dict[str, Any] | None:
        # 这个会话发出的、还没回答的询问：恢复时继续这一层，不新开一层（工单 #473）
        if not session_id:
            return None
        for ask in self.ask_stack:
            if ask.get("origin_session_id") == session_id:
                return ask
        return None

    def ask_by_branch(self, session_id: str | None) -> dict[str, Any] | None:
        # 这个会话是哪一个询问的分支：分支里的回答与回问都发生在这个会话上（工单 #473）
        if not session_id:
            return None
        for ask in self.ask_stack:
            if ask.get("branch_session_id") == session_id:
                return ask
        return None

    def ask_position(self, session_id: str | None) -> int:
        # 这个会话在询问链上的位置：主线是 0；分支是它回答的那一次询问的层号；
        # 发出询问的会话是它发出的那次询问的层号减一（工单 #473）
        if not session_id:
            return 0
        for index, ask in enumerate(self.ask_stack):
            if ask.get("origin_session_id") == session_id:
                return index
        for index, ask in enumerate(self.ask_stack):
            if ask.get("branch_session_id") == session_id:
                return index + 1
        return 0






# 停止原因的中文名与结束方式都在定义里：内核的清单在 stop_reasons.json，路由自己的结束原因在
# 它自己的一份定义里（routings.json，工单 #861），两者都按定义查，不在代码里另写一份
def stop_reason_name(reason: str | None) -> str:
    # 停止原因的中文名；没有登记的取值原样返回，说明里不丢掉这个事实
    try:
        return DEFINITIONS.stop_reason(reason or "").label
    except UnknownStopReason:
        return reason or ""


def waiting_reason_for(status: str, stop_reason: str | None = None) -> str | None:
    # run 停在等待上时给一句话：进行中没有单一阶段可写（进度从成果推算），只有终态有等待说明
    if status == "done":
        return None
    if status in TERMINAL_STATUSES:
        # 暂停与失败都带停止原因的中文名；没有停止原因时只写状态，不猜具体原因
        reason = {"paused": "已暂停", "failed": "未能完成"}[status]
        return f"{reason}：{stop_reason_name(stop_reason)}" if stop_reason else reason
    return None
