# 事件载荷的合同（设计说明第 5.2 节）：现有每个事件种类一个 pydantic 类型，字段与控制核心写入的载荷逐一对应，
# 不接受类型之外的字段。工件以引用出现，原文由查询取得。控制核心新增或修改载荷字段时同时修改这里，
# 事件序列对照与项目流程的测试核对每条写入的事件都符合这里的类型。

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..definitions import DEFINITIONS
from ..models import DEPARTMENTS, PHASES, CatalogEventType, EventType, ProjectEventType

Department = Literal[DEPARTMENTS]
Phase = Literal[PHASES]
Purpose = Literal["work", "compaction"]


def _stop_reasons(outcome: str) -> Any:
    # 定义中以这种方式结束运行的停止原因
    return Literal[tuple(name for name, reason in DEFINITIONS.stop_reasons.items() if reason.outcome == outcome)]


ReleasedReason = _stop_reasons("done")
PausedReason = _stop_reasons("paused")
FailedReason = _stop_reasons("failed")
StopReason = Literal[tuple(DEFINITIONS.stop_reasons)]


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------------------
# 载荷中反复出现的结构


class ArtifactRef(Payload):
    # 工件引用：按内容摘要寻址，原文由查询按引用取得
    kind: str
    content_hash: str
    path: str
    media_type: str | None


class GitVersion(Payload):
    commit: str
    parent_commit: str | None
    tree: str


class CheckReceipt(Payload):
    # 检查回执：检查名称、退出状态与它所绑定的快照和规范版本
    activation_id: str | None
    delivery_spec_hash: str | None
    exit_code: int
    name: str
    product_spec_hash: str | None
    effective_contract_hash: str | None
    engineering_plan_hash: str | None
    snapshot_hash: str
    summary: str


class YieldedWork(Payload):
    # 部门为回应指导让出的工作与让出时的依据
    phase: Phase
    effective_contract_hash: str | None
    engineering_plan_hash: str | None
    delivery_spec_hash: str | None


class Baseline(Payload):
    # 事项的代码基线：继承的采纳版本
    adoption_id: str
    source_run_id: str
    delivery_event_id: str
    tree_ref: ArtifactRef
    code_tree_digest: str


class CodeSnapshot(Payload):
    # 事项的代码快照来源：从源目录读取的公开树
    source: str
    tree_digest: str
    files: list[str]
    directories: list[str]
    tree_ref: ArtifactRef


class InputRecord(Payload):
    # 一次用户输入：原文、它在原始意图中的字节范围与 Git 版本；
    # base_version 是用户提交时看到的事项输入版本，作为这次追加的依据（追加类命令不要求相等）
    id: str
    version: int
    text: str
    kind: Literal["text", "command"]
    input_ref: ArtifactRef
    intend_ref: ArtifactRef
    byte_start: int
    byte_end: int
    git_version: GitVersion
    base_version: int | None = None


class PromptRecord(Payload):
    department: Department
    version: int
    text: str
    prompt_ref: ArtifactRef


class FrozenCommand(Payload):
    # 事项创建时冻结的登记命令
    argv: list[str]
    args: list[str]
    timeout_sec: int
    output_limit: int


class Usage(Payload):
    # 提供方上报的用量；没有上报的项为空
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    total_tokens: int
    cost: float | None
    currency: str | None
    cost_source: str | None
    latency_ms: int | None
    reported: bool


class CollectionScope(Payload):
    # 调用尝试保存了哪些内容
    request: str
    response: str
    events: str
    credentials: str


class FunctionCallOutput(Payload):
    # 工具结果进入部门历史时的条目
    type: Literal["function_call_output"]
    call_id: str
    output: str


# 各种模型与工具记录共有的字段组


class Versions(Payload):
    # 激活所用的输入版本、部门 Prompt 版本与指导
    input_version: int
    prompt_version: int
    prompt_hash: str | None
    guidance_ids: list[str]
    guidance_only: bool


class WorkBasis(Payload):
    # 激活开始时的有效合同、工程计划与协作请求
    effective_contract_hash: str | None
    engineering_plan_hash: str | None
    request_id: str | None


class CallTarget(Payload):
    # 调用目标：这次请求解析出的连接、协议与模型，凭据只有引用与版本；原始请求档位与实际发送的档位
    provider_config_id: str | None
    model_id: str | None
    provider_name: str
    protocol: str
    base_url: str | None
    requested_provider: str
    requested_protocol: str
    requested_model: str
    credential_ref: str | None
    credential_version: str | None
    context_window: int | None
    configured_max_output_tokens: int | None
    # 模型访问定义声明的是否接受要求调用工具；模型尚未解析时为空
    accepts_required_tool_call: bool | None
    selection_source: str | None
    requested_tier: str | None
    sent_tier: str | None


class AttemptIdentity(Payload):
    # 调用尝试的身份
    attempt_id: str
    logical_call_id: str
    collaboration_request_id: str | None
    context_event_id: str


class AttemptOutcome(AttemptIdentity, Versions, CallTarget):
    # 调用尝试结束时的记录（成功与失败共有）
    activation_id: str
    step_id: int
    root_step_id: int
    retry_of_step_id: int | None
    attempt: int
    purpose: Purpose
    started_at: str
    finished_at: str
    duration_ms: int | None
    duration_source: Literal["monotonic"]
    provider_response_id: str | None
    actual_provider: str | None
    actual_model: str | None
    response_ref: ArtifactRef | None
    stream_events_ref: ArtifactRef | None
    stream_event_count: int
    stream_first_observed_at: str | None
    stream_first_output_at: str | None
    stream_last_stage: str | None
    collection_scope: CollectionScope
    usage: Usage | None
    raw_usage_ref: ArtifactRef | None


class ToolRecord(AttemptIdentity, WorkBasis, Versions, CallTarget):
    # 工具执行或跳过的记录共有的字段
    id: str
    name: str
    step_id: int
    input_item: FunctionCallOutput
    activation_id: str
    purpose: Purpose


# ---------------------------------------------------------------------------
# run 事件


class RunCreatedPayload(Payload):
    task: str
    initial_input: InputRecord
    department_prompts: dict[Department, PromptRecord]
    intend_ref: ArtifactRef
    git_version: GitVersion
    intend_path: str
    max_cycles: int
    run_time_limit_sec: int
    context_window: int
    provider: str
    adapter: str
    sessions: dict[Department, str]
    project_id: str | None
    work_item_id: str | None
    baseline: Baseline | None
    snapshot: CodeSnapshot | None
    workspace_digest: str
    project_context_ref: ArtifactRef | None
    prompt_config_versions: dict[Department, int]
    registered_commands: dict[str, FrozenCommand]
    command_versions: dict[str, int]
    # 事项所用定义的版本（全部定义文件内容的摘要）
    definitions_version: str


class UserInputReceivedPayload(InputRecord):
    pass


class ProductInputAssignedPayload(Payload):
    through_version: int


class DepartmentPromptUpdatedPayload(PromptRecord):
    pass


class DepartmentGuidanceReceivedPayload(Payload):
    id: str
    department: Department
    version: int
    text: str
    guidance_ref: ArtifactRef
    status: Literal["received"]
    # base_version 是用户提交时看到的该部门的指导版本，作为这次指导的依据（追加类命令不要求相等）
    base_version: int | None = None


class DepartmentGuidanceAppliedPayload(Payload):
    guidance_ids: list[str]
    activation_id: str
    context_event_id: str | None
    input_version: int


class DepartmentGuidanceRespondedPayload(Payload):
    guidance_id: str
    guidance_version: int
    guidance_created_event_id: str
    department: Department
    status: Literal["explained", "completed", "declined", "needs_work"]
    text: str
    result_event_ids: list[str]
    kind: Literal["department_guidance_response"]
    issuer: Department
    content_hash: str


class DepartmentActivatedPayload(Versions, WorkBasis):
    activation_id: str
    cycle: int
    yielded_work: YieldedWork | None
    guidance_version: int


class DepartmentInputPayload(Versions, WorkBasis):
    activation_id: str
    step_id: int
    input_ref: ArtifactRef


class ToolCallRequiredPayload(Versions, WorkBasis):
    activation_id: str
    step_id: int
    attempt_id: str
    context_event_id: str
    purpose: Purpose
    count: int
    limit: int
    input_ref: ArtifactRef


class ActivationFinishedPayload(Versions):
    activation_id: str
    latency_ms: int
    stop_reason: str | None


class ContextSource(Payload):
    source: str
    version: str | None
    tokens: int
    digest: str | None


class ContextExclusion(Payload):
    source: str
    reason: str


class ContextAssembledPayload(Versions, WorkBasis, CallTarget):
    # 上下文清单与这次请求的身份
    session_id: str
    department: Department
    activation_id: str
    injected: list[ContextSource]
    excluded: list[ContextExclusion]
    token_estimate: int
    budget: int
    digest: str
    truncated: bool
    step_id: int
    request_ref: ArtifactRef
    admitted: bool
    source_event_id: str | None
    purpose: Purpose
    max_output_tokens: int | None
    compaction_event_id: str | None
    input_token_estimate: int
    output_reserve_tokens: int
    parts_ref: ArtifactRef
    run_id: str
    tokens_charged: int
    attempt: int
    root_step_id: int
    retry_of_step_id: int | None
    effective_context_window: int
    snapshot_hash: str
    attempt_id: str
    logical_call_id: str
    collaboration_request_id: str | None


class ModelRequestSerializedPayload(AttemptIdentity, WorkBasis, Versions, CallTarget):
    activation_id: str
    step_id: int
    attempt: int
    root_step_id: int
    retry_of_step_id: int | None
    purpose: Purpose
    request_ref: ArtifactRef
    request_digest: str
    serialization: Literal["sdk_request_json_object"]


class ModelMessagePayload(AttemptIdentity, WorkBasis, Versions, CallTarget):
    # 模型输出的一个条目
    message_ref: ArtifactRef
    message_index: int
    response_id: str | None
    stop_reason: str | None
    summary: str
    activation_id: str
    step_id: int
    purpose: Purpose


class ModelRequestedPayload(AttemptIdentity, WorkBasis, Versions, CallTarget):
    activation_id: str
    step_id: int
    attempt: int
    max_attempts: int
    root_step_id: int
    retry_of_step_id: int | None
    started_at: str
    attempted: bool
    purpose: Purpose
    effective_context_window: int
    max_output_tokens: int | None
    # 是否要求调用工具：最后一次主机提示之后的工作请求为 required；声明不接受时为 auto（#102）
    tool_choice: Literal["auto", "required"]
    definitions_version: str


class ModelStreamProgressPayload(AttemptIdentity, Versions):
    activation_id: str
    step_id: int
    attempt: int
    root_step_id: int
    purpose: Purpose
    source: Literal["sdk_decoded_stream"]
    stage: Literal["response_created", "output", "output_item_done", "completed", "error", "event"]
    event_type: str | None
    sequence: int | None
    observed_at: str
    first_observed_at: str
    first_output_at: str | None
    summary: str


class ModelAttemptFinishedPayload(AttemptOutcome):
    status: Literal["completed"]


class ModelAttemptFailedPayload(AttemptOutcome, WorkBasis):
    status: Literal["failed", "cancelled"]
    max_attempts: int
    reason: str
    retryable: bool
    will_retry: bool
    # 提供方或步骤驱动给出的诊断，键随错误种类不同
    diagnostics: dict[str, Any]


class ModelRetryScheduledPayload(AttemptIdentity, WorkBasis, Versions, CallTarget):
    activation_id: str
    step_id: int
    attempt: int
    max_attempts: int
    root_step_id: int
    retry_of_step_id: int | None
    next_step_id: int
    next_attempt: int
    purpose: Purpose
    reason: str
    retryable: bool
    delay_sec: float


class CompactionCheckpoint(Payload):
    summary: str
    covered_through_event_id: str | None
    covered_digest: str
    partial_event_id: str | None
    partial_offset: int
    boundary: bool


class CompactionSource(Payload):
    event_id: str
    seq: int
    activation_id: str
    step_id: int
    item_digest: str
    start_offset: int
    end_offset: int
    material_digest: str
    total_chars: int
    text_digest: str


class CompactionRecordedPayload(Versions, WorkBasis, CallTarget):
    run_id: str
    department: Department
    activation_id: str
    step_id: int
    purpose: Literal["compaction"]
    checkpoint: CompactionCheckpoint
    source_refs: list[CompactionSource]
    summary_ref: ArtifactRef
    plan_ref: ArtifactRef
    summary_token_limit: int
    max_output_tokens: int
    previous_compaction_event_id: str | None


class ToolCallResult(ToolRecord):
    # 工具执行的结果；args 是模型给出的参数（不是合法 JSON 时为 {"invalid_arguments": 原文}），output_ref 在有输出时出现
    args: dict[str, Any]
    ok: bool
    error: str | None
    output_ref: ArtifactRef | None = None


class UsageCharge(Versions, CallTarget):
    # 一次激活的用量记账
    name: Literal["provider_usage"]
    ok: Literal[True]
    activation_id: str
    step_id: int
    purpose: Purpose
    accounting: Literal["activation_total_with_charge_delta"]
    scope: Literal["observable_main_dialogue"]
    source: Literal["reported", "unreported"]
    cost_reported: bool
    raw_usage_ref: ArtifactRef | None
    tokens_charged: int
    total_tokens: int
    input_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    input_total_tokens: int
    output_tokens: int
    cost: float
    total_cost: float


class ToolStartedPayload(AttemptIdentity, Versions, WorkBasis):
    # registered_name、registered_argv 与 snapshot_hash 只在登记命令获准执行时出现
    id: str
    name: str
    args: dict[str, Any]
    step_id: int
    activation_id: str
    attempt: int
    registered_name: str | None = None
    registered_argv: list[str] | None = None
    snapshot_hash: str | None = None


class ToolSkippedPayload(ToolRecord):
    ok: Literal[False]
    error: str


class ProposalSubmittedPayload(Payload):
    kind: str | None
    transcript_ref: ArtifactRef | None
    raw_keys: list[str]
    input_version: int
    definitions_version: str


class FieldError(Payload):
    field: str
    message: str


class ProposalRejectedPayload(Payload):
    errors: list[FieldError]
    transcript_ref: ArtifactRef | None
    kind: str | None
    input_version: int
    definitions_version: str


class SpecSupersededPayload(Payload):
    content_hash: str
    revision: int
    request_id: str | None


class DecisionChange(Payload):
    decision_hash: str
    disposition: Literal["retain", "integrate", "retire"]
    rationale: str


class ChangeRecord(Payload):
    changed: list[str]
    retained: list[str]
    retired: list[str]
    rationale: str


class SpecAcceptedPayload(Payload):
    goal: str
    requirements: list[str]
    boundaries: list[str]
    constraints: list[str]
    acceptance_criteria: list[str]
    fatal_conditions: list[str]
    non_goals: list[str]
    decision_changes: list[DecisionChange]
    change_record: ChangeRecord | None
    input_version: int
    kind: Literal["product_spec"]
    issuer: Literal["product"]
    parent_hash: str | None
    revision: int
    status: Literal["active"]
    content_hash: str
    id: str
    request_id: str | None
    git_version: GitVersion


class ContractAcceptedPayload(Payload):
    product_spec_hash: str
    decision_hashes: list[str]
    input_version: int
    content_hash: str
    revision: int
    prd_ref: ArtifactRef
    request_id: str | None
    git_version: GitVersion


class ProductDecisionAcceptedPayload(Payload):
    # git_version 在同一次接纳改变了有效合同时出现
    statement: str
    rationale: str
    product_spec_hash: str
    request_id: str | None
    kind: Literal["product_decision"]
    content_hash: str
    id: str
    git_version: GitVersion | None = None


class PlanTask(Payload):
    title: str
    outputs: list[str]
    verification: str


class PlanAssumption(Payload):
    decision: str
    basis: str


class PlanAcceptedPayload(Payload):
    effective_contract_hash: str
    objective: str
    scope: list[str]
    tasks: list[PlanTask]
    refactoring: list[str]
    assumptions: list[PlanAssumption]
    reason: str
    kind: Literal["engineering_plan"]
    issuer: Literal["engineering"]
    parent_hash: str | None
    revision: int
    status: Literal["active"]
    content_hash: str
    id: str
    plan_ref: ArtifactRef
    request_id: str | None
    git_version: GitVersion


class CollaborationBasis(Payload):
    intend_hash: str
    effective_contract_hash: str | None
    engineering_plan_hash: str | None
    delivery_spec_hash: str | None
    phase: Phase


class CollaborationRequestedPayload(Payload):
    requester: Department
    recipient: Department
    request_type: Literal["consultation", "action"]
    action: Literal["inspect", "check", "revise_requirements", "revise_delivery"] | None
    question: str
    background: str
    expected_result: str
    basis: CollaborationBasis
    return_phase: Phase
    status: Literal["open"]
    kind: Literal["collaboration_request"]
    content_hash: str
    id: str


class CollaborationRespondedPayload(Payload):
    request_id: str
    status: Literal["answered", "declined", "needs_work", "completed"]
    text: str
    result_event_ids: list[str]
    return_phase: Phase
    return_work_valid: bool
    kind: Literal["collaboration_response"]
    content_hash: str
    id: str


class CollaborationClosedPayload(Payload):
    request_id: str
    status: Literal["superseded", "stopped", "cancelled", "timed_out"]
    reason: str
    return_phase: Phase
    return_work_valid: bool


class DeliveryAcceptedPayload(Payload):
    summary: str
    files: list[str]
    check_names: list[str]
    checks: list[CheckReceipt]
    known_risks: list[str]
    product_spec_hash: str
    effective_contract_hash: str
    engineering_plan_hash: str
    code_tree_digest: str
    kind: Literal["delivery_spec"]
    issuer: Literal["engineering"]
    parent_hash: str | None
    revision: int
    status: Literal["active"]
    content_hash: str
    id: str
    tree_ref: ArtifactRef
    request_id: str | None
    git_version: GitVersion


class Defect(Payload):
    severity: Literal["blocker", "major", "minor"]
    summary: str


class QaSubmittedPayload(Payload):
    product_spec_hash: str
    effective_contract_hash: str
    engineering_plan_hash: str
    delivery_spec_hash: str
    code_snapshot_hash: str
    verdict: Literal["rework_product", "rework_engineering", "release"]
    rationale: str
    checks: list[CheckReceipt]
    defects: list[Defect]
    evidence_refs: list[ArtifactRef]
    kind: Literal["qa_review"]
    issuer: Literal["quality"]
    parent_hash: str | None
    revision: int
    status: Literal["active"]
    content_hash: str
    id: str
    request_id: str | None
    git_version: GitVersion


class ReviewObservation(Payload):
    # 教训候选来自质检退回
    verdict: str
    rationale: str
    defects: list[Defect]


class FailureObservation(Payload):
    # 教训候选来自运行失败
    stop_reason: str | None
    message: str | None


class LessonCandidateRecordedPayload(Payload):
    kind: Literal["lesson_candidate"]
    id: str
    status: Literal["unverified"]
    source_event_id: str
    source_type: Literal["qa_submitted", "run_failed"]
    observation: ReviewObservation | FailureObservation
    suggestion: str
    product_spec_hash: str | None
    delivery_spec_hash: str | None
    checks: list[CheckReceipt]
    evidence_refs: list[ArtifactRef]


class TransitionPayload(Payload):
    # yielded_work_resolved 与 yielded_work 在恢复让出的工作时出现
    model_config = ConfigDict(extra="forbid", frozen=True, serialize_by_alias=True)
    from_: Phase = Field(alias="from")
    to: Phase
    route: str
    yielded_work_resolved: bool | None = None
    yielded_work: YieldedWork | None = None


class RunDonePayload(Payload):
    stop_reason: ReleasedReason


class RunPausedPayload(Payload):
    # message 在停止说明与通用人工处理说明不同时出现（例如 workspace_unrepresentable 列出相对路径）
    stop_reason: PausedReason
    human_action: str
    message: str | None = None
    paused_at_phase: Phase
    cycle_count: int
    max_cycles: int
    token_used: int


class InputSaveFailure(Payload):
    text: str
    error_type: str
    message: str


class RunFailedPayload(Payload):
    # input_save_failure 在停止命令的原文没能保存时出现
    stop_reason: FailedReason
    human_action: str | None
    message: str
    input_save_failure: InputSaveFailure | None = None


# 用户决定（总体架构第 7.4 节）：决定请求的身份是请求事件的编号


class DecisionOption(Payload):
    id: str
    label: str


class ModelUnavailableRequested(Payload):
    # 待恢复：模型引用无法使用（模型管理设计说明第 5.5 节），回答之前整个 run 不推进。
    # description 写明部门、模型与具体问题；facts 是涉及的事实（失败的调用尝试等事件的编号）；
    # target 是调用目标的公开部分（没有找到调用目标时为空）；reason 与 message 是 Provider 或主机给出的原因与说明
    kind: Literal["model_unavailable"]
    blocks: Literal["run"]
    options: list[DecisionOption]
    description: str
    facts: list[str]
    department: Department
    target: CallTarget | None
    reason: str
    message: str


# 决定请求的载荷：以 kind 区分的各种决定请求
DecisionRequestedPayload = ModelUnavailableRequested


class DecisionAnsweredPayload(Payload):
    # 用户的回答：所回答的请求、所选的选项、说明（可以为空）与回答所依据的请求版本
    decision_id: str
    option: str
    note: str | None
    base_version: int


class DecisionWithdrawnPayload(Payload):
    # 运行结束时撤销未回答的请求；reason 是结束运行的停止原因
    decision_id: str
    reason: StopReason


# ---------------------------------------------------------------------------
# 项目事件


class ProjectRegisteredPayload(Payload):
    name: str
    goal: str
    goal_ref: ArtifactRef
    source: Literal["idea"]


class ProjectRenamedPayload(Payload):
    name: str


class ProjectPinnedPayload(Payload):
    pinned: bool


class ProjectArchivedPayload(Payload):
    pass


class ProjectRestoredPayload(Payload):
    pass


class WorkItemCreatedPayload(Payload):
    work_item_id: str
    title: str
    text: str
    run_id: str
    baseline: Baseline | None
    snapshot: CodeSnapshot | None
    project_context_ref: ArtifactRef
    prompt_config_versions: dict[Department, int]
    command_versions: dict[str, int]
    max_cycles: int
    run_time_limit_sec: int
    context_window: int
    definitions_version: str


class WorkItemStartFailedPayload(Payload):
    work_item_id: str
    run_id: str
    error: str


class DeliverableAdoptedPayload(Payload):
    adoption_id: str
    work_item_id: str
    run_id: str
    delivery_event_id: str
    qa_event_id: str
    tree_ref: ArtifactRef
    code_tree_digest: str
    summary: str
    files: list[str]
    check_names: list[str]
    known_risks: list[str]
    previous_adoption_id: str | None


class AdoptionHeldPayload(Payload):
    work_item_id: str
    run_id: str
    delivery_event_id: str
    code_tree_digest: str
    reason: Literal["baseline_changed"]
    expected_adoption_id: str | None
    current_adoption_id: str | None


class DepartmentPromptConfiguredPayload(PromptRecord):
    base_version: int


class CommandConfiguredPayload(Payload):
    name: str
    version: int
    argv: list[str]
    args: list[str]
    timeout_sec: int
    output_limit: int
    base_version: int


class MaterialRecordedPayload(Payload):
    material_id: str
    text: str
    material_ref: ArtifactRef
    department: Department | None


class SourceDirectoryConfiguredPayload(Payload):
    # 项目登记的源目录：名称是登记名，路径是控制主机上的路径；
    # version 是该条登记的版本，base_version 是这次登记依据的版本
    name: str
    path: str
    version: int
    base_version: int


# 模型目录与凭据（应用层与接口层设计说明第 10 节第 1 项）：只含修订号、变化与结果，不含 Key

class CatalogRevisedPayload(Payload):
    # 目录内容（连接、访问定义、部门默认）或文件被外部修改与重读以后的修订号；
    # base_revision 是这次变化依据的修订号：命令写提交时用户看到的修订号，外部修改与启动补写取变化前的修订号
    revision: int
    base_revision: int | None
    operation: Literal["save_connection", "delete_connection", "save_document", "department_defaults",
                       "reload", "startup"]
    provider_id: str | None


class CatalogCandidatesCollectedPayload(Payload):
    # base_revision 是提交命令时依据的目录修订号（追加类命令记录依据，不要求等于当时的最新修订号）
    base_revision: int
    provider_id: str
    status: Literal["ok", "unknown"]
    source_url: str
    fetched_at: str
    # 候选逐条带上游模型 ID；上游列表返回窗口与输出上限时带这两项，其余候选只有上游模型 ID
    candidates: list[dict[str, Any]]
    candidate_ids: list[str]
    error: str | None


class CatalogTestFinishedPayload(Payload):
    # 连接测试不写准入（admitted 为空）；模型测试通过时带准入结果。
    # base_revision 是提交命令时依据的目录修订号
    base_revision: int
    kind: Literal["connection", "model"]
    provider_id: str
    model_id: str | None
    ok: bool
    protocol: str | None
    error: str | None
    actual_model: str | None
    elapsed_ms: int
    admitted: bool | None


class CredentialChangedPayload(Payload):
    # 只含引用、动作、来源与版本，不含 Key
    ref: str
    action: Literal["set", "clear_override", "remove_persisted"]
    source: str
    version: int
    persisted: bool


# 事件种类到载荷类型；tool_called 有工具结果与用量记账两种载荷
PAYLOADS: dict[str, Any] = {
    EventType.RUN_CREATED: RunCreatedPayload,
    EventType.USER_INPUT_RECEIVED: UserInputReceivedPayload,
    EventType.PRODUCT_INPUT_ASSIGNED: ProductInputAssignedPayload,
    EventType.DEPARTMENT_PROMPT_UPDATED: DepartmentPromptUpdatedPayload,
    EventType.DEPARTMENT_GUIDANCE_RECEIVED: DepartmentGuidanceReceivedPayload,
    EventType.DEPARTMENT_GUIDANCE_APPLIED: DepartmentGuidanceAppliedPayload,
    EventType.DEPARTMENT_GUIDANCE_RESPONDED: DepartmentGuidanceRespondedPayload,
    EventType.DEPARTMENT_ACTIVATED: DepartmentActivatedPayload,
    EventType.DEPARTMENT_INPUT: DepartmentInputPayload,
    EventType.TOOL_CALL_REQUIRED: ToolCallRequiredPayload,
    EventType.ACTIVATION_FINISHED: ActivationFinishedPayload,
    EventType.CONTEXT_ASSEMBLED: ContextAssembledPayload,
    EventType.MODEL_REQUEST_SERIALIZED: ModelRequestSerializedPayload,
    EventType.MODEL_MESSAGE: ModelMessagePayload,
    EventType.MODEL_REQUESTED: ModelRequestedPayload,
    EventType.MODEL_STREAM_PROGRESS: ModelStreamProgressPayload,
    EventType.MODEL_ATTEMPT_FINISHED: ModelAttemptFinishedPayload,
    EventType.MODEL_ATTEMPT_FAILED: ModelAttemptFailedPayload,
    EventType.MODEL_RETRY_SCHEDULED: ModelRetryScheduledPayload,
    EventType.COMPACTION_RECORDED: CompactionRecordedPayload,
    EventType.TOOL_CALLED: ToolCallResult | UsageCharge,
    EventType.TOOL_STARTED: ToolStartedPayload,
    EventType.TOOL_SKIPPED: ToolSkippedPayload,
    EventType.PROPOSAL_SUBMITTED: ProposalSubmittedPayload,
    EventType.PROPOSAL_REJECTED: ProposalRejectedPayload,
    EventType.SPEC_ACCEPTED: SpecAcceptedPayload,
    EventType.SPEC_SUPERSEDED: SpecSupersededPayload,
    EventType.CONTRACT_ACCEPTED: ContractAcceptedPayload,
    EventType.PLAN_ACCEPTED: PlanAcceptedPayload,
    EventType.COLLABORATION_REQUESTED: CollaborationRequestedPayload,
    EventType.COLLABORATION_RESPONDED: CollaborationRespondedPayload,
    EventType.COLLABORATION_CLOSED: CollaborationClosedPayload,
    EventType.PRODUCT_DECISION_ACCEPTED: ProductDecisionAcceptedPayload,
    EventType.DELIVERY_ACCEPTED: DeliveryAcceptedPayload,
    EventType.QA_SUBMITTED: QaSubmittedPayload,
    EventType.LESSON_CANDIDATE_RECORDED: LessonCandidateRecordedPayload,
    EventType.TRANSITION: TransitionPayload,
    EventType.RUN_DONE: RunDonePayload,
    EventType.RUN_PAUSED: RunPausedPayload,
    EventType.RUN_FAILED: RunFailedPayload,
    EventType.DECISION_REQUESTED: DecisionRequestedPayload,
    EventType.DECISION_ANSWERED: DecisionAnsweredPayload,
    EventType.DECISION_WITHDRAWN: DecisionWithdrawnPayload,
    ProjectEventType.PROJECT_REGISTERED: ProjectRegisteredPayload,
    ProjectEventType.PROJECT_RENAMED: ProjectRenamedPayload,
    ProjectEventType.PROJECT_PINNED: ProjectPinnedPayload,
    ProjectEventType.PROJECT_ARCHIVED: ProjectArchivedPayload,
    ProjectEventType.PROJECT_RESTORED: ProjectRestoredPayload,
    ProjectEventType.WORK_ITEM_CREATED: WorkItemCreatedPayload,
    ProjectEventType.WORK_ITEM_START_FAILED: WorkItemStartFailedPayload,
    ProjectEventType.DELIVERABLE_ADOPTED: DeliverableAdoptedPayload,
    ProjectEventType.ADOPTION_HELD: AdoptionHeldPayload,
    ProjectEventType.DEPARTMENT_PROMPT_CONFIGURED: DepartmentPromptConfiguredPayload,
    ProjectEventType.COMMAND_CONFIGURED: CommandConfiguredPayload,
    ProjectEventType.MATERIAL_RECORDED: MaterialRecordedPayload,
    ProjectEventType.SOURCE_DIRECTORY_CONFIGURED: SourceDirectoryConfiguredPayload,
    CatalogEventType.CATALOG_REVISED: CatalogRevisedPayload,
    CatalogEventType.CATALOG_CANDIDATES_COLLECTED: CatalogCandidatesCollectedPayload,
    CatalogEventType.CATALOG_TEST_FINISHED: CatalogTestFinishedPayload,
    CatalogEventType.CREDENTIAL_CHANGED: CredentialChangedPayload,
}
