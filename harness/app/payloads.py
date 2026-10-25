# 事件载荷的合同（设计说明第 5.2 节）：现有每个事件种类一个 pydantic 类型，字段与控制核心写入的载荷逐一对应，
# 不接受类型之外的字段。工件以引用出现，原文由查询取得。控制核心新增或修改载荷字段时同时修改这里，
# 事件序列对照与项目流程的测试核对每条写入的事件都符合这里的类型。

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..definitions import DEFINITIONS
from ..models import DEPARTMENTS, CatalogEventType, EventType, ProjectEventType
from ..streams import PRIORITY_USER

Department = Literal[DEPARTMENTS]
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
    snapshot_hash: str
    summary: str
    qa_tests_hash: str | None = None


class YieldedWork(Payload):
    # 部门为回应指导让出的工作与让出时的依据
    effective_contract_hash: str | None
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
    # 快照的 git 来源：提交、分支与是否有未提交的修改；源目录不是 git 仓库或旧事件没有这个字段时为空
    provenance: dict[str, Any] | None = None
    # 快照所有公开文件的总字节数；旧事件没有这个字段时为空（ADR-0019）
    bytes: int | None = None


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
    # 激活开始时的有效合同
    effective_contract_hash: str | None


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
    # 模型访问定义声明的输入方式（设计说明第 4.3 节）；模型尚未解析时为空列表
    input_modalities: list[str]
    selection_source: str | None
    requested_tier: str | None
    sent_tier: str | None
    # 模型访问定义声明的推理档位（#87）：支持档位、默认档位与推理参数方式，未声明时为空
    reasoning_levels: list[str]
    default_reasoning_level: str | None
    reasoning_mode: str | None


class AttemptIdentity(Payload):
    # 调用尝试的身份
    attempt_id: str
    logical_call_id: str
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


class OnboardingBasis(Payload):
    # 建档修改轮的依据（工单 #136，设计第 3.3 节）：上一轮建档候选的事件编号、这一轮的轮次与修改意见的工件引用。
    # 产品据此以上一轮初始 PRD 与修改意见为依据写出新的 ProductSpec；修改意见为空时这一轮没有意见
    candidate_event_id: str
    round: int
    note_ref: ArtifactRef | None = None


class RunCreatedPayload(Payload):
    task: str
    # 事项种类（工单 #134）：普通事项为 change，建档事项为 onboarding；旧事件缺省为 change
    kind: str = "change"
    initial_input: InputRecord
    intend_ref: ArtifactRef
    git_version: GitVersion
    intend_path: str
    max_cycles: int
    run_time_limit_sec: int
    # 这个 run 中检查的时限（迭代底座 B3，工单 #351）：创建时按项目级取值与全局现值冻结；
    # 旧事件没有这个字段时按当时的全局现值处理
    check_timeout_sec: int = 600
    provider: str
    adapter: str
    sessions: dict[Department, str]
    project_id: str | None
    work_item_id: str | None
    baseline: Baseline | None
    snapshot: CodeSnapshot | None
    # 建档事项的仓库概况工件引用；普通事项没有概况
    overview_ref: ArtifactRef | None = None
    workspace_digest: str
    project_context_ref: ArtifactRef | None
    prompt_config_versions: dict[Department, int]
    # 事项所用定义的版本（全部定义文件内容的摘要）
    definitions_version: str
    # 创建这个 run 时冻结的参数版本（全部参数现值的内容摘要，工单 #349）
    parameters_version: str
    # 创建这个 run 时的 run 事件版本：run 流跟随应用版本，版本不同的未结束 run 按因升级停止处理（ADR-0019）
    run_event_version: int
    # 建档修改轮的依据（工单 #136，设计第 3.3 节）：上一轮候选事件与修改意见的工件引用。
    # 普通事项与建档第一轮没有这个字段，读取时按没有上一轮处理
    onboarding_basis: OnboardingBasis | None = None
    # 建档的轮次（工单 #136）：第一轮为 1；普通事项与旧事件没有这个字段，读取时按 0 处理
    round: int = 0


class UserInputReceivedPayload(InputRecord):
    pass


class ProductInputAssignedPayload(Payload):
    through_version: int


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
    # 这次激活结束时这个 run 累计的已用量（工单 #350）：重启时从事件恢复，连续累计
    elapsed_ms: int
    activations: int
    model_steps: int
    # 这个会话自己累计的已用量（工单 #475）：重新启动以后从事件恢复，连续累计。
    # 旧事件没有这些字段，按 0 处理
    session_elapsed_ms: int = 0
    session_activations: int = 0
    session_model_steps: int = 0
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

class ModelReasoningPayload(AttemptIdentity, WorkBasis, Versions, CallTarget):
    # 上游返回的一条推理内容（设计说明第 7.6 节）；产生它的连接、协议与上游模型随调用目标记录
    reasoning_ref: ArtifactRef
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
    parameters_version: str


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
    # 动作后的公开树快照（工单 #17）：与事件 tool_started 上的动作前快照、动作参数一起构成核实依据
    after_snapshot_ref: ArtifactRef | None = None


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
    id: str
    name: str
    args: dict[str, Any]
    step_id: int
    activation_id: str
    attempt: int
    # 动作前的公开树快照（工单 #17）：许可以后、执行之前写入，中断后按它与动作参数核对实际效果
    before_snapshot_ref: ArtifactRef | None = None
    # 自动重新执行（工单 #307）：旧事件保留，新版本不再写
    auto_retry_of: str | None = None
    # 自动重新执行的依据（工单 #308）：旧事件保留，新版本不再写
    verification_reason: Literal["not_happened"] | None = None


class ToolSkippedPayload(ToolRecord):
    ok: Literal[False]
    error: str


class FileActionComparison(Payload):
    # 文件动作的自动核实依据（工单 #308）：动作前的公开树快照、动作参数与当前公开树的对比。
    # verdict 为 completed 表示只有目标路径变成参数里的目标内容、其它路径都没有变；not_happened 表示
    # 公开树与动作前相同，动作没有发生；unclear 表示另有改动或目标内容不符，交给用户决定
    tool: str
    args: dict[str, Any]
    before_snapshot_event: str
    verdict: Literal["completed", "not_happened", "unclear"]
    detail: dict[str, Any]


class ActionVerifiedPayload(Payload):
    # 核实一个结果未知的动作产生的核实记录（工单 #17，恢复契约第 4 节）：不改写原来的观察。
    # resolution 为 continue 表示用户选择按当前实际状态继续（旧事件保留，新版本不再写，工单 #582）；
    # handed_back 表示交还会话由模型处置（工单 #581）；
    # auto_verify 表示自动核实确认动作已经完成（工单 #308）。
    # 两次尝试分别记录，不补造原来那次尝试的 tool_called 回执
    # input_item 让这条结果进入部门历史，模型据此继续
    id: str
    name: str
    step_id: int | None = None
    activation_id: str | None = None
    purpose: Purpose = "work"
    input_item: FunctionCallOutput
    ok: bool
    error: str | None = None
    resolution: Literal["auto_verify", "continue", "handed_back"]
    # 自动重新执行（工单 #307）：旧事件保留，新版本不再写
    auto_retry_of: str | None = None
    # 自动核实的依据（工单 #308）：动作前快照、动作参数与当前公开树的对比结论
    verification: FileActionComparison | None = None
    note: str | None = None
    decision_id: str | None = None

class ProposalSubmittedPayload(Payload):
    kind: str | None
    transcript_ref: ArtifactRef | None
    raw_keys: list[str]
    input_version: int
    definitions_version: str
    parameters_version: str


class FieldError(Payload):
    field: str
    message: str


class ProposalRejectedPayload(Payload):
    errors: list[FieldError]
    transcript_ref: ArtifactRef | None
    kind: str | None
    input_version: int
    definitions_version: str
    parameters_version: str


class SpecSupersededPayload(Payload):
    content_hash: str
    revision: int


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
    git_version: GitVersion


class ContractAcceptedPayload(Payload):
    product_spec_hash: str
    decision_hashes: list[str]
    input_version: int
    content_hash: str
    revision: int
    prd_ref: ArtifactRef
    git_version: GitVersion


class ProductDecisionAcceptedPayload(Payload):
    # git_version 在同一次接纳改变了有效合同时出现
    statement: str
    rationale: str
    product_spec_hash: str
    kind: Literal["product_decision"]
    content_hash: str
    id: str
    git_version: GitVersion | None = None


class AskStartedPayload(Payload):
    requester: Department
    recipient: Department
    question: str = ""
    branch_session_id: str
    background: str | None = None
    expected: str | None = None
    # 工程询问质检时问题与背景分成的两部分（工单 #554）：facts 是事实部分，explanation 是解释部分
    facts: str | None = None
    explanation: str | None = None


class AskAnsweredPayload(Payload):
    requester: Department
    recipient: Department
    status: Literal["answered", "unable"]
    answer: str = ""
    reason: str = ""
    with_spec_revision: bool = False
    revision: int | None = None
    # 工程回答质检时回答分成的两部分（工单 #554）
    facts: str | None = None
    explanation: str | None = None



class DeliveryAcceptedPayload(Payload):
    summary: str
    files: list[str]
    check_names: list[str]
    checks: list[CheckReceipt]
    known_risks: list[str]
    product_spec_hash: str
    effective_contract_hash: str
    code_tree_digest: str
    kind: Literal["delivery_spec"]
    issuer: Literal["engineering"]
    parent_hash: str | None
    revision: int
    status: Literal["active"]
    content_hash: str
    id: str
    tree_ref: ArtifactRef
    git_version: GitVersion


class Defect(Payload):
    severity: Literal["blocker", "major", "minor"]
    summary: str


class QaSubmittedPayload(Payload):
    product_spec_hash: str
    effective_contract_hash: str
    delivery_spec_hash: str
    code_snapshot_hash: str
    verdict: Literal["rework_engineering", "release"]
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
    git_version: GitVersion


class QaTestsSavedPayload(Payload):
    version: int
    content_hash: str
    archive_ref: ArtifactRef
    activation_id: str

class StructureModule(Payload):
    # 现有结构说明中的一个模块
    path: str
    responsibility: str


class StructureEntryPoint(Payload):
    kind: Literal["program", "command_line", "service"]
    path: str
    how_to_run: str


class StructureBuildItem(Payload):
    # 构建与测试的一条命令，带本次激活中绑定当前快照的执行回执
    name: str
    command: str
    purpose: str
    receipt: CheckReceipt


class StructureRequirementLocation(Payload):
    requirement: str
    locations: list[str]


class StructureAcceptedPayload(Payload):
    overall: str
    modules: list[StructureModule]
    entry_points: list[StructureEntryPoint]
    build_and_test: list[StructureBuildItem]
    requirement_locations: list[StructureRequirementLocation]
    conventions: list[str]
    product_spec_hash: str
    code_tree_digest: str
    kind: Literal["structure"]
    issuer: Literal["engineering"]
    parent_hash: str | None
    revision: int
    status: Literal["active"]
    content_hash: str
    id: str
    structure_ref: ArtifactRef
    git_version: GitVersion


class BaselineConclusion(Payload):
    # 基线核验中对一条初始 PRD 要求的结论
    requirement: str
    status: Literal["verified", "read_only", "existing_defect", "unsupported"]
    evidence: str


class BaselineOmission(Payload):
    capability: str
    location: str


class BaselineOtherFailure(Payload):
    check: str
    reason: str


class BaselineReviewAcceptedPayload(Payload):
    verdict: Literal["consistent", "rework_product"]
    conclusions: list[BaselineConclusion]
    omissions: list[BaselineOmission]
    checks: list[CheckReceipt]
    other_failures: list[BaselineOtherFailure]
    product_spec_hash: str
    structure_hash: str
    code_snapshot_hash: str
    kind: Literal["baseline_review"]
    issuer: Literal["quality"]
    parent_hash: str | None
    revision: int
    status: Literal["active"]
    content_hash: str
    id: str
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


class RunDonePayload(Payload):
    stop_reason: ReleasedReason


class RunPausedPayload(Payload):
    # message 在停止说明与通用人工处理说明不同时出现（例如 workspace_unrepresentable 列出相对路径）
    stop_reason: PausedReason
    human_action: str
    message: str | None = None
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
    # 说明必填的标记（原型选项的标记，工单 #136）：为真时选项必须附说明，
    # 空说明的回答由服务端以 not_allowed 拒绝；旧事件没有这个字段时按不必填理解
    note_required: bool = False

class InitialPrdProposal(Payload):
    # 候选中的初始 PRD：接纳它的事件编号、ProductSpec 的内容哈希与 PRD.md 的工件引用；
    # summary 是给用户看的 PRD 摘要（原型 v8 的 materials.prd_summary）
    event_id: str
    content_hash: str
    prd_ref: ArtifactRef
    summary: str | None = None


class StructureProposal(Payload):
    # 候选中的现有结构说明：接纳它的事件编号、内容哈希、STRUCTURE.md 的工件引用与它所描述的树摘要
    event_id: str
    content_hash: str
    structure_ref: ArtifactRef
    code_tree_digest: str


class BaselineCheck(Payload):
    # 基线检查（工单 #136，设计第 4.6 节）：质检在快照上运行的检查回执，随建档基线一起记入项目流，
    # 以后的事项据此区分原有的失败与新引入的失败。command 与 summary 取自工程结构说明中的同名构建检查与
    # 检查回执的输出摘要；snapshot_hash 是它绑定的快照摘要
    name: str
    command: str
    exit_code: int
    summary: str
    snapshot_hash: str


class BaselineReviewProposal(Payload):
    # 候选中的基线核验：接纳它的事件编号、内容哈希、逐条结论、遗漏的能力、失败的检查与其他失败
    event_id: str
    content_hash: str
    conclusions: list[BaselineConclusion]
    omissions: list[BaselineOmission]
    checks: list[BaselineCheck]
    other_failures: list[BaselineOtherFailure]


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


class DefinitionsChangedRequested(Payload):
    # 继续旧事项时事项记录的定义版本与当前加载的不同（ADR-0014，工单 #16、#894；设计说明第 3.3 节、
    # 总体架构第 7.4 节）：回答之前这个 run 不推进。recorded_definitions_version 是事项开始时记录的版本
    # （旧事项没有记录时为空），current_definitions_version 是当前加载的版本；reason 恒为
    # definitions_version_changed；facts 为空，请求不引用事实
    kind: Literal["definitions_changed"]
    blocks: Literal["run"]
    options: list[DecisionOption]
    facts: list[str]
    department: Department
    reason: Literal["definitions_version_changed"]
    recorded_definitions_version: str
    current_definitions_version: str
    description: str


class PauseRequested(Payload):
    # 暂停以后继续（D09，工单 #204）：模型连续多次没有调用工具，或者工作区出现无法表示的条目，
    # run 暂停并发出这个请求，回答之前这个 run 不推进。description 写明停止原因与人工处理说明；
    # workspace_unrepresentable 的 facts 是条目在工作区内的相对路径；department 是暂停时正在工作的部门
    kind: Literal["no_tool_call", "workspace_unrepresentable"]
    blocks: Literal["run"]
    options: list[DecisionOption]
    description: str
    facts: list[str]
    department: Department
    stop_reason: Literal["no_tool_call", "workspace_unrepresentable"]


class UnknownActionRequested(Payload):
    # 旧事件保留，新版本不再写（工单 #582）
    kind: Literal["unknown_action"]
    blocks: Literal["action"]
    options: list[DecisionOption]
    description: str
    facts: list[str]
    department: Department
    action_id: str
    tool: str
    action_kind: str
    repeatable: bool
    repeat_attempted: bool = False
    verification: FileActionComparison | None = None


# 确认接入已有项目的初始 PRD（工单 #136，接入已有项目设计说明第 3.2 节）：请求写在项目流中，
# 阻塞建档事项与同一项目中排在它后面的事项（blocks="work_item"），不属于任何 run。
# round 是这一轮建档的轮次（第一次为 1，每次提出修改以后加一）；department 恒为 product。
# prd、structure、baseline_review 是这一轮的三份产物，snapshot 与 overview_ref 是档案的来源与仓库概况；
# revision_note_ref 是上一轮用户的修改意见（第二轮起）
class InitialPrdRequested(Payload):
    kind: Literal["initial_prd"]
    blocks: Literal["work_item"]
    options: list[DecisionOption]
    description: str
    facts: list[str]
    department: Department
    work_item_id: str
    # 提出修改以后要继续的建档 run（候选所属的 run）；这个请求本身不属于任何 run
    candidate_run_id: str
    round: int
    prd: InitialPrdProposal
    structure: StructureProposal
    baseline_review: BaselineReviewProposal
    overview_ref: ArtifactRef
    snapshot: CodeSnapshot
    revision_note_ref: ArtifactRef | None = None

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


# 请求写在项目流中，阻塞范围是 run，回答之前交付不采纳。kernel_paths 是交付相对基线的改动路径中
# 落在运行实例内核清单里的那些；diff 是这些路径的差异全文；delivery_run_id 是交付所属的 run；
# held_adoption 是批准以后要写入的采纳载荷（与照常采纳时写的那一份相同）
class KernelModificationRequested(Payload):
    kind: Literal["kernel_modification"]
    blocks: Literal["run"]
    options: list[DecisionOption]
    description: str
    facts: list[str]
    department: Department
    work_item_id: str
    # 交付所属的 run；这个请求本身不属于任何 run，请求写在项目流中
    delivery_run_id: str
    kernel_paths: list[str]
    diff: str
    held_adoption: DeliverableAdoptedPayload

# 决定请求的载荷：以 kind 区分的各种决定请求（UnknownActionRequested 为旧事件保留，新版本不再写）
DecisionRequestedPayload = (ModelUnavailableRequested | DefinitionsChangedRequested | UnknownActionRequested
                            | PauseRequested | InitialPrdRequested)
# 项目流中的决定请求（工单 #136、#354）：写在项目流中的那几种，run 流中没有它们
ProjectDecisionRequestedPayload = InitialPrdRequested | KernelModificationRequested


class DecisionAnsweredPayload(Payload):
    # 用户的回答：所回答的请求、所选的选项、说明（可以为空）与回答所依据的请求版本
    decision_id: str
    option: str
    note: str | None
    base_version: int


DecisionWithdrawReason = StopReason | Literal["superseded_by_hand_back"]


class DecisionWithdrawnPayload(Payload):
    # 运行结束时撤销未回答的请求；reason 是结束运行的停止原因或交还模型
    decision_id: str
    reason: DecisionWithdrawReason

class RunResumedPayload(Payload):
    # 中断的 run 在启动时自动继续（工单 #16）：basis 记录中断位置与继续的依据，
    # acquired_epoch 是这次取得的执行权编号，previous_epoch 是之前记录的编号（第一次继续时为空）
    basis: dict[str, Any]
    acquired_epoch: int
    previous_epoch: int | None

class RunContinuedPayload(Payload):
    # 暂停的 run 在用户回答「处理以后继续执行」以后继续（D09，工单 #204）：decision_id 是被回答的决定请求，
    # stop_reason 是暂停时的停止原因；继续以后下一个谁工作由关注的成果决定（工单 #556）
    decision_id: str
    stop_reason: Literal["no_tool_call", "workspace_unrepresentable"]


# ---------------------------------------------------------------------------
# 项目事件


class ProjectRegisteredPayload(Payload):
    name: str
    goal: str
    goal_ref: ArtifactRef
    # 项目来源：想法新建为 idea，接入已有项目为 existing
    source: Literal["idea", "existing"]
    # 起始文件夹快照记录（工单 #321）：新建项目时给出的起点文件夹的只读采集结果。
    # 旧事件没有这个字段时缺省为没有起始文件夹（ADR-0019）
    initial_snapshot: CodeSnapshot | None = None


class ProjectRenamedPayload(Payload):
    name: str


class ProjectGoalChangedPayload(Payload):
    # 长期目标改为 goal；goal_ref 是目标原文的工件引用
    goal: str
    goal_ref: ArtifactRef


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
    max_cycles: int
    run_time_limit_sec: int
    context_window: int
    definitions_version: str
    # 事项在队列中的优先级：因升级重新开始的事项排在最前面；旧事件没有这个字段时按用户新要求处理（ADR-0019）
    priority: str = PRIORITY_USER
    # 事项种类：普通事项为 change，建档事项为 onboarding；旧事件缺省为 change
    kind: str = "change"


class WorkItemStartFailedPayload(Payload):
    work_item_id: str
    run_id: str
    error: str


class AdoptionHeldPayload(Payload):
    work_item_id: str
    run_id: str
    delivery_event_id: str
    code_tree_digest: str
    reason: Literal["baseline_changed"]
    expected_adoption_id: str | None
    current_adoption_id: str | None


class DepartmentSettingsConfiguredPayload(Payload):
    # 项目部门设置：模型访问定义引用、请求档位与部门 Prompt 三项，都可以不写入；三项一起保存、一个版本
    department: Department
    version: int
    base_version: int
    provider_id: str | None = None
    model_id: str | None = None
    requested_tier: str | None = None
    department_prompt: str | None = None
    department_prompt_ref: ArtifactRef | None = None
    # 这次保存写入的模型不具备该部门建议能力时的提醒（设计说明第 5.6 节「保存时」）；
    # 没有写入模型或模型具备建议能力时为空
    reminders: list[str] = []


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
    writeback_enabled: bool = False
    remote: str = ""
    target_branch: str = ""
    check_commands: list[str] = []
    credential_ref: str | None = None


class WritebackCompletedPayload(Payload):
    work_item_id: str
    run_id: str
    adoption_id: str
    source_tree_digest: str
    source_tree_ref: ArtifactRef
    adopted_tree_digest: str
    adopted_tree_ref: ArtifactRef
    target_commit: str
    target_tree_digest: str
    final_tree_digest: str
    final_tree_ref: ArtifactRef
    check_receipts: list[dict[str, Any]]
    branch: str
    pull_request: dict[str, Any] | None = None
    verified_external: bool = False


class WritebackStoppedPayload(Payload):
    # 写回停止（ADR-0034）：reason 的取值集合只增加（ADR-0019）。
    # source_tree_digest 在缺少起点依据时为空字符串：没有起点树就得出不了本事项的变更集
    work_item_id: str
    run_id: str
    adoption_id: str
    reason: Literal["conflict", "verification_failed", "target_changed", "unrepresentable_path",
                    "missing_source_reference"]
    target_commit: str
    source_tree_digest: str
    adopted_tree_digest: str
    target_tree_digest: str
    final_tree_digest: str | None = None
    conflict_ref: ArtifactRef | None = None
    conflicts: list[dict[str, Any]] = []
    check_receipts: list[dict[str, Any]] = []
    new_target_commit: str | None = None


class WritebackNotNeededPayload(Payload):
    work_item_id: str
    run_id: str
    adoption_id: str
    target_commit: str
    reason: str = "changes_already_present"
    source_tree_digest: str
    adopted_tree_digest: str
    target_tree_digest: str


class WritebackHeldPayload(Payload):
    work_item_id: str
    run_id: str
    adoption_id: str
    reason: Literal["waiting_previous_adoption"]
    previous_adoption_id: str
    target_commit: str


class WritebackVerifiedPayload(Payload):
    work_item_id: str
    run_id: str
    adoption_id: str
    action: Literal["push", "pull_request"]
    branch: str
    target_commit: str
    verified_fact: dict[str, Any]

class InitialPrdProposedPayload(Payload):
    # 建档候选（工单 #136，接入已有项目设计说明第 3.2、3.3 节）：建档 run 以 baseline_verified 结束以后，
    # 这一轮的三份产物与代码快照写进项目流，等待用户确认。round 是轮次（第一次为 1）；
    # revision_note_ref 是上一轮用户的修改意见（第二轮起）；snapshot 是这一轮建档使用的代码快照
    work_item_id: str
    run_id: str
    round: int
    prd: InitialPrdProposal
    structure: StructureProposal
    baseline_review: BaselineReviewProposal
    overview_ref: ArtifactRef
    snapshot: CodeSnapshot
    revision_note_ref: ArtifactRef | None = None


class ProjectDecisionAnsweredPayload(Payload):
    # 项目流中决定请求的回答（工单 #136）：与 run 流中的 decision_answered 同字段。
    # work_item_id 与 run_id 是请求所属的事项与 run（ProjectEvent 的这两个字段从载荷取得）
    decision_id: str
    option: str
    note: str | None
    base_version: int
    work_item_id: str
    run_id: str | None


class ProjectDecisionWithdrawnPayload(Payload):
    # 项目流中决定请求的撤销（工单 #136）：reason 是撤销的原因（撤销建档事项时为 user_cancelled）
    decision_id: str
    reason: str
    work_item_id: str
    run_id: str | None


class OnboardingRevisionStartedPayload(Payload):
    # 建档修改轮（工单 #136，设计第 3.3 节）：用户提出修改以后开始新一轮建档 run。
    # candidate_event_id 是被提出修改的建档候选事件编号；round 是新一轮的轮次；
    # note 是修改意见原文，它按这一轮 run 的目录存成工件，引用记在 run_created 的 onboarding_basis 中，
    # 原文随事件写入供启动补建这一轮的 run（设计第 6 节）
    work_item_id: str
    run_id: str
    candidate_event_id: str
    round: int
    note: str


class BaselineAdoptedPayload(Payload):
    # 采纳建档基线（工单 #136，设计第 3.3、第 5 节）：确认初始 PRD 以后的采纳。第一次采纳的成果是快照本身，
    # tree_ref 与 code_tree_digest 就是建档采集的快照，previous_adoption_id 恒为空；
    # candidate_event_id 是被确认的建档候选事件编号；prd_ref 与 product_spec_hash 是被确认的初始 PRD；
    # known_risks 是基线核验中的现有缺陷与其他失败；checks 与 snapshot 是基线检查与快照来源
    adoption_id: str
    work_item_id: str
    run_id: str
    candidate_event_id: str
    tree_ref: ArtifactRef
    code_tree_digest: str
    summary: str
    prd_ref: ArtifactRef
    product_spec_hash: str
    structure_ref: ArtifactRef
    files: list[str] = []
    check_names: list[str] = []
    checks: list[BaselineCheck] = []
    known_risks: list[str] = []
    snapshot: CodeSnapshot | None = None
    # 基线核验中状态为 existing_defect 的结论；现有缺陷数按它计数（known_risks 还含其他失败）
    existing_defects: list[str] = []
    previous_adoption_id: str | None = None


# 模型目录与凭据（应用层与接口层设计说明第 10 节第 1 项）：只含修订号、变化与结果，不含 Key

class CatalogRevisedPayload(Payload):
    # 目录内容（连接、访问定义、部门默认）或文件被外部修改与重读以后的修订号；
    # base_revision 是这次变化依据的修订号：命令写提交时用户看到的修订号，外部修改与启动补写取变化前的修订号
    revision: int
    base_revision: int | None
    operation: Literal["save_connection", "delete_connection", "remove_model", "save_document",
                       "department_defaults", "reload", "startup"]
    provider_id: str | None
    # 部门默认保存以后各部门的建议能力提醒（设计说明第 5.6 节）；其他操作为空
    reminders: list[str] = []


class CatalogCandidatesCollectedPayload(Payload):
    # base_revision 是提交命令时依据的目录修订号（追加类命令记录依据，不要求等于当时的最新修订号）
    base_revision: int
    provider_id: str
    status: Literal["ok", "unknown"]
    source_url: str
    fetched_at: str
    # 候选逐条带上游模型 ID，以及预填值与来源（设计说明第 4.3 节）：窗口与输出上限先取上游模型列表、
    # 其次取模型能力表；输入方式取能力表；每个预填值带来源（models_url、capability_table 或 default）
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
    # 连接测试实际读取的模型列表地址；模型测试与没读到地址时为空
    source_url: str | None
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

class RuntimeDrainStartedPayload(Payload):
    # 开始排空：排空状态的版本与开始排空时还没有结束的 run
    version: int
    running_runs: int


class RuntimeDrainFinishedPayload(Payload):
    # 排空结束：服务下一次启动时记下，此后这个实例重新开始新事项（工单 #731，
    # 应用层与接口层设计说明第 3.2 节「升级」：排空在下一次启动时结束）
    version: int

class RuntimeForceUpgradeRequestedPayload(Payload):
    # 强制升级：排空状态的版本、因升级停止的 run 与用采纳成果重新开始的事项
    version: int
    stopped_runs: list[str]
    restarted_work_items: list[str]


class HomeSeenPayload(Payload):
    # 用户查看过的全局位置（工单 #127）：上一次查看的位置被这次的位置取代，控制主机上只有一个。
    # 位置的写入时间由事件的 created_at 给出
    position: int


class ParameterSetPayload(Payload):
    # 参数修改（工单 #349，设计第 3、5 节）：界内修改一次全局参数的现值。
    # old_value 与 new_value 是修改前后按定义界限核对过的取值；parameters_version 是修改以后的参数版本摘要
    name: str
    old_value: Any
    new_value: Any
    reason: str
    modified_by: str
    # 这次修改所依据的界限：修改以后界面仍能显示可调整范围
    bounds: list[Any]
    parameters_version: str


class InstanceUpgradeReport(Payload):
    # 发布检查的结果（工单 #355，发布检查设计说明第 4.4 节）：被检查的提交与基准标签、内核清单里的
    # 改动路径与 Python 行数、是否通过，以及逐项不通过（检查项、说明与位置）
    repository: str
    pending_commit: str
    base_tag: str | None
    kernel_changes: list[str]
    kernel_python_lines: int
    python_lines_max: int
    passed: bool
    findings: list[dict[str, Any]]


class InstanceUpgradeRequested(Payload):
    # 决定请求「实例升级」（工单 #355）：发布检查的结果写进目录流，由用户批准或拒绝升级已安装的那一份。
    # blocks 恒为 instance，不属于任何 run 或项目；facts 是给人看的报告全文，report 是它的结构化结果
    kind: Literal["instance_upgrade"]
    blocks: Literal["instance"]
    options: list[DecisionOption]
    description: str
    facts: list[str]
    report: InstanceUpgradeReport


class InstanceUpgradeAnswered(Payload):
    # 实例升级决定请求的回答（工单 #355）：与 run 流中的 decision_answered 同字段。
    # 目录流中的请求不属于任何 run 或项目，回答只是记下用户的决定
    decision_id: str
    option: str
    note: str | None
    base_version: int


class InstanceUpgradeWithdrawn(Payload):
    # 实例升级决定请求的撤销（工单 #355）：reason 是撤销的原因，目录流中的决定不绑定 run，
    # reason 不是停止原因（参照项目流中的 project_decision_withdrawn）
    decision_id: str
    reason: str


class ProjectParameterSetPayload(Payload):
    # 项目级参数的修改（迭代底座 B3，工单 #351）：检查时限与建档单轮上限可以按项目设置。
    # old_value 是修改前这个项目的生效取值（没有设置过时是当时的全局现值），new_value 是界内核对过的新值
    name: str
    old_value: Any
    new_value: Any
    reason: str
    modified_by: str
    # 这次修改所依据的界限：修改以后界面仍能显示可调整范围
    bounds: list[Any]


# 事件种类到载荷类型；tool_called 有工具结果与用量记账两种载荷
PAYLOADS: dict[str, Any] = {
    EventType.RUN_CREATED: RunCreatedPayload,
    EventType.USER_INPUT_RECEIVED: UserInputReceivedPayload,
    EventType.PRODUCT_INPUT_ASSIGNED: ProductInputAssignedPayload,
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
    EventType.MODEL_REASONING: ModelReasoningPayload,
    EventType.MODEL_REQUESTED: ModelRequestedPayload,
    EventType.MODEL_STREAM_PROGRESS: ModelStreamProgressPayload,
    EventType.MODEL_ATTEMPT_FINISHED: ModelAttemptFinishedPayload,
    EventType.MODEL_ATTEMPT_FAILED: ModelAttemptFailedPayload,
    EventType.MODEL_RETRY_SCHEDULED: ModelRetryScheduledPayload,
    EventType.COMPACTION_RECORDED: CompactionRecordedPayload,
    EventType.TOOL_CALLED: ToolCallResult | UsageCharge,
    EventType.TOOL_STARTED: ToolStartedPayload,
    EventType.TOOL_SKIPPED: ToolSkippedPayload,
    EventType.ACTION_VERIFIED: ActionVerifiedPayload,
    EventType.PROPOSAL_SUBMITTED: ProposalSubmittedPayload,
    EventType.PROPOSAL_REJECTED: ProposalRejectedPayload,
    EventType.SPEC_ACCEPTED: SpecAcceptedPayload,
    EventType.SPEC_SUPERSEDED: SpecSupersededPayload,
    EventType.CONTRACT_ACCEPTED: ContractAcceptedPayload,
    EventType.ASK_STARTED: AskStartedPayload,
    EventType.ASK_ANSWERED: AskAnsweredPayload,
    EventType.PRODUCT_DECISION_ACCEPTED: ProductDecisionAcceptedPayload,
    EventType.DELIVERY_ACCEPTED: DeliveryAcceptedPayload,
    EventType.QA_SUBMITTED: QaSubmittedPayload,
    EventType.QA_TESTS_SAVED: QaTestsSavedPayload,
    EventType.STRUCTURE_ACCEPTED: StructureAcceptedPayload,
    EventType.BASELINE_REVIEW_ACCEPTED: BaselineReviewAcceptedPayload,
    EventType.LESSON_CANDIDATE_RECORDED: LessonCandidateRecordedPayload,
    EventType.RUN_DONE: RunDonePayload,
    EventType.RUN_PAUSED: RunPausedPayload,
    EventType.RUN_FAILED: RunFailedPayload,
    EventType.RUN_RESUMED: RunResumedPayload,
    EventType.RUN_CONTINUED: RunContinuedPayload,
    EventType.DECISION_REQUESTED: DecisionRequestedPayload,
    EventType.DECISION_ANSWERED: DecisionAnsweredPayload,
    EventType.DECISION_WITHDRAWN: DecisionWithdrawnPayload,
    ProjectEventType.PROJECT_REGISTERED: ProjectRegisteredPayload,
    ProjectEventType.PROJECT_RENAMED: ProjectRenamedPayload,
    ProjectEventType.PROJECT_GOAL_CHANGED: ProjectGoalChangedPayload,
    ProjectEventType.PROJECT_PINNED: ProjectPinnedPayload,
    ProjectEventType.PROJECT_ARCHIVED: ProjectArchivedPayload,
    ProjectEventType.PROJECT_RESTORED: ProjectRestoredPayload,
    ProjectEventType.WORK_ITEM_CREATED: WorkItemCreatedPayload,
    ProjectEventType.WORK_ITEM_START_FAILED: WorkItemStartFailedPayload,
    ProjectEventType.DELIVERABLE_ADOPTED: DeliverableAdoptedPayload,
    ProjectEventType.ADOPTION_HELD: AdoptionHeldPayload,
    ProjectEventType.DEPARTMENT_SETTINGS_CONFIGURED: DepartmentSettingsConfiguredPayload,
    ProjectEventType.MATERIAL_RECORDED: MaterialRecordedPayload,
    ProjectEventType.SOURCE_DIRECTORY_CONFIGURED: SourceDirectoryConfiguredPayload,
    ProjectEventType.INITIAL_PRD_PROPOSED: InitialPrdProposedPayload,
    ProjectEventType.PROJECT_DECISION_REQUESTED: ProjectDecisionRequestedPayload,
    ProjectEventType.PROJECT_DECISION_ANSWERED: ProjectDecisionAnsweredPayload,
    ProjectEventType.PROJECT_DECISION_WITHDRAWN: ProjectDecisionWithdrawnPayload,
    ProjectEventType.ONBOARDING_REVISION_STARTED: OnboardingRevisionStartedPayload,
    ProjectEventType.BASELINE_ADOPTED: BaselineAdoptedPayload,
    ProjectEventType.PARAMETER_SET: ProjectParameterSetPayload,
    ProjectEventType.WRITEBACK_COMPLETED: WritebackCompletedPayload,
    ProjectEventType.WRITEBACK_STOPPED: WritebackStoppedPayload,
    ProjectEventType.WRITEBACK_NOT_NEEDED: WritebackNotNeededPayload,
    ProjectEventType.WRITEBACK_HELD: WritebackHeldPayload,
    ProjectEventType.WRITEBACK_VERIFIED: WritebackVerifiedPayload,
    CatalogEventType.CATALOG_REVISED: CatalogRevisedPayload,
    CatalogEventType.CATALOG_CANDIDATES_COLLECTED: CatalogCandidatesCollectedPayload,
    CatalogEventType.CATALOG_TEST_FINISHED: CatalogTestFinishedPayload,
    CatalogEventType.CREDENTIAL_CHANGED: CredentialChangedPayload,
    CatalogEventType.RUNTIME_DRAIN_STARTED: RuntimeDrainStartedPayload,
    CatalogEventType.RUNTIME_DRAIN_FINISHED: RuntimeDrainFinishedPayload,
    CatalogEventType.RUNTIME_FORCE_UPGRADE_REQUESTED: RuntimeForceUpgradeRequestedPayload,
    CatalogEventType.HOME_SEEN: HomeSeenPayload,
    CatalogEventType.PARAMETER_SET: ParameterSetPayload,
    CatalogEventType.INSTANCE_UPGRADE_REQUESTED: InstanceUpgradeRequested,
    CatalogEventType.INSTANCE_UPGRADE_ANSWERED: InstanceUpgradeAnswered,
    CatalogEventType.INSTANCE_UPGRADE_WITHDRAWN: InstanceUpgradeWithdrawn,
}


def _known_fields(model: Any) -> set[str]:
    # 一个事件种类的载荷类型：单个模型取它的字段名与别名，联合取各成员字段的并集
    if isinstance(model, type) and issubclass(model, BaseModel):
        names: set[str] = set()
        for name, field in model.model_fields.items():
            names.add(name)
            if field.alias:
                names.add(field.alias)
        return names
    fields: set[str] = set()
    for member in getattr(model, "__args__", ()):
        fields |= _known_fields(member)
    return fields


def payload_for_reading(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    # 读旧事件时宽容：事件日志里留着模型已经删掉的字段（ADR-0019），
    # 读的时候忽略它们，日志本身不改；一条读不懂的事件不能把整条历史事件流作废
    model = PAYLOADS.get(event_type)
    if model is None or not isinstance(payload, dict):
        return payload
    known = _known_fields(model)
    return {key: value for key, value in payload.items() if key in known}


def is_known_event_type(event_type: str) -> bool:
    # 这个事件种类现在还有载荷类型：已经被删掉的种类（旧版本的协作请求）读的时候跳过，
    # 事件日志里仍然留着，事件详情照旧能查
    return event_type in PAYLOADS
