# 内核事件模块（S5a，工单 #828）：事件日志的信封、骨架事件的种类与数据结构、骨架事件的登记表。
#
# 规则（设计说明第 7 节）：内核写入或读取的事件是骨架事件，种类与字段只增，停用不删除，事件一经写入不重新解释；
# 其余 run 流里的事件是应用事件，由应用登记自己的种类，增加一种不改这个文件（第 5.4 节第 1 条）。
# 项目流与目录流的事件全部是骨架事件：它们是长期事实，跨版本保存（ADR-0019）。
#
# 这个文件只导入标准库与 pydantic（这里没有用到 pydantic），是内核清单里 kind 为 module 的一行：
# 内核模块只从它导入事件信封与骨架事件，`models.py` 与 `projection.py` 留给应用，不在内核清单里。

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol
from uuid import uuid4


# ---------------------------------------------------------------------------
# 事件信封里的取值：流的状态、种类，以及信封与载荷的序列化

# run 的状态：进行中与三个终态（工单 #556）。状态写在事件信封的 state_before 与 state_after 上，
# 这两个字段是信封的一部分，所以取值也在这里
RUN_STATUSES = ("running", "done", "paused", "failed")

TERMINAL_STATUSES = frozenset({"done", "paused", "failed"})

# 骨架事件载荷里的封闭取值，只增：qa_submitted 的结论，baseline_review_accepted 逐条结论的状态
QA_VERDICTS = ("rework_engineering", "release")
BASELINE_STATUSES = ("verified", "read_only", "existing_defect", "unsupported")


class SkeletonEventType:
    # 骨架事件（run 流）：内核写入或读取的种类，只增不删（设计说明第 7 节）。清单由这个类给出，
    # 应用事件的种类在应用里声明（第 5.4 节第 1 条），不在这里
    RUN_CREATED = "run_created"
    DEPARTMENT_ACTIVATED = "department_activated"
    ACTIVATION_FINISHED = "activation_finished"
    TOOL_CALLED = "tool_called"
    TOOL_STARTED = "tool_started"
    PROPOSAL_SUBMITTED = "proposal_submitted"
    PROPOSAL_REJECTED = "proposal_rejected"
    SPEC_ACCEPTED = "spec_accepted"
    SPEC_SUPERSEDED = "spec_superseded"
    CONTRACT_ACCEPTED = "contract_accepted"
    PRODUCT_DECISION_ACCEPTED = "product_decision_accepted"
    # 成果失效（S1b，工单 #858）：哪一种成果的哪一版因为什么失效。投影只折叠这一条，
    # 不再从工具调用与其他接纳事件推出失效
    ARTIFACT_INVALIDATED = "artifact_invalidated"
    DELIVERY_ACCEPTED = "delivery_accepted"
    QA_SUBMITTED = "qa_submitted"
    STRUCTURE_ACCEPTED = "structure_accepted"
    BASELINE_REVIEW_ACCEPTED = "baseline_review_accepted"
    # 通用的成果接纳（S2c，工单 #1098）：路由带来新种类时内核写这一条，载荷是收紧检查给出的内容加统一字段。
    # 成果驱动的六种成果与契约仍写各自的接纳事件，已经写入的事件不重新解释
    ARTIFACT_ACCEPTED = "artifact_accepted"
    # 第 4 节 2026-10-25 第 1 条：模型步数按「模型请求」事件一条条数，内核的最小投影读它，
    # 所以它从此是骨架事件，只加字段（第 7 节的表把 model_* 列在应用事件里，按这一条据以修正）
    MODEL_REQUESTED = "model_requested"
    RUN_DONE = "run_done"
    RUN_PAUSED = "run_paused"
    RUN_FAILED = "run_failed"
    RUN_RESUMED = "run_resumed"
    RUN_CONTINUED = "run_continued"
    DECISION_REQUESTED = "decision_requested"
    DECISION_ANSWERED = "decision_answered"
    DECISION_WITHDRAWN = "decision_withdrawn"


class ProjectEventType:
    # 项目流的事件全部是骨架事件：项目的长期事实，跨版本保存
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
    # 部门设置事件跨版本保持 department_prompt_configured（ADR-0019）
    DEPARTMENT_SETTINGS_CONFIGURED = "department_prompt_configured"
    MATERIAL_RECORDED = "material_recorded"
    SOURCE_DIRECTORY_CONFIGURED = "source_directory_configured"
    # 建档候选（设计第 3.2 节）：记下候选引用与核验结论
    INITIAL_PRD_PROPOSED = "initial_prd_proposed"
    # 确认初始 PRD 可能等待数天，run 已结束，请求与回答记在项目流，字段与 run 流相同
    PROJECT_DECISION_REQUESTED = "project_decision_requested"
    PROJECT_DECISION_ANSWERED = "project_decision_answered"
    PROJECT_DECISION_WITHDRAWN = "project_decision_withdrawn"
    # 用户提出修改：项目流记下这一轮依据，启动时据此补建缺少的 run（设计第 3.3、6 节）
    ONBOARDING_REVISION_STARTED = "onboarding_revision_started"
    # 用户确认初始 PRD：这个成果成为项目的建档基线（设计第 3.2 节）
    BASELINE_ADOPTED = "baseline_adopted"
    # 项目级参数（迭代底座 B3，工单 #351）：project_parameter_set
    PARAMETER_SET = "project_parameter_set"
    WRITEBACK_COMPLETED = "writeback_completed"
    WRITEBACK_STOPPED = "writeback_stopped"
    WRITEBACK_NOT_NEEDED = "writeback_not_needed"
    WRITEBACK_HELD = "writeback_held"
    WRITEBACK_VERIFIED = "writeback_verified"


class CatalogEventType:
    # 目录流的事件全部是骨架事件：控制主机的长期事实，随部署保存
    # 模型目录与凭据事件（设计第 10 节）：内容由 Provider 保存，事件不含 Key
    CATALOG_REVISED = "catalog_revised"
    CATALOG_CANDIDATES_COLLECTED = "catalog_candidates_collected"
    CATALOG_TEST_FINISHED = "catalog_test_finished"
    CREDENTIAL_CHANGED = "credential_changed"
    # 排空与强制升级（3.1）：与目录事件同流，是控制主机长期事实（ADR-0019）
    RUNTIME_DRAIN_STARTED = "runtime_drain_started"
    # 排空结束：升级完成（换了版本）以后记下，此后这个实例重新开始新事项（工单 #731）
    RUNTIME_DRAIN_FINISHED = "runtime_drain_finished"
    RUNTIME_FORCE_UPGRADE_REQUESTED = "runtime_force_upgrade_requested"
    # 用户查看过的全局位置（界面工作线，工单 #127）：控制主机上只有一个，随部署长期保存
    HOME_SEEN = "home_seen"
    # 参数修改（迭代底座 B3，工单 #349）：参数是全局的，事件写进目录流，随部署长期保存
    PARAMETER_SET = "parameter_set"
    # 实例升级的决定请求（工单 #355）：升级已安装的实例是一次用户决定，随部署长期保存
    INSTANCE_UPGRADE_REQUESTED = "instance_upgrade_requested"
    INSTANCE_UPGRADE_ANSWERED = "instance_upgrade_answered"
    INSTANCE_UPGRADE_WITHDRAWN = "instance_upgrade_withdrawn"


def _kinds(declaration: type) -> frozenset[str]:
    # 一份种类声明里的全部取值；声明可以继承（应用的事件种类在骨架事件上接着声明）
    return frozenset(
        value
        for declaration_class in reversed(declaration.__mro__)
        for name, value in vars(declaration_class).items()
        if not name.startswith("_") and isinstance(value, str)
    )


# 骨架事件的登记表：三份种类声明各自是一个流，合起来是内核写入或读取的全部种类。
# 应用事件的种类由应用登记（register_application_event_types），不在这张表里
SKELETON_RUN_EVENTS = _kinds(SkeletonEventType)
SKELETON_PROJECT_EVENTS = _kinds(ProjectEventType)
SKELETON_CATALOG_EVENTS = _kinds(CatalogEventType)
SKELETON_EVENTS = SKELETON_RUN_EVENTS | SKELETON_PROJECT_EVENTS | SKELETON_CATALOG_EVENTS

# 应用登记的事件种类与登记它的应用（第 5.4 节第 1 条）：只是登记，内核不解释它们的内容
_APPLICATION_EVENTS: dict[str, str] = {}


def register_application_event_types(owner: str, kinds: Iterable[str]) -> None:
    # 应用登记自己的事件种类：增加一种应用事件不改内核文件。骨架事件不由应用登记（它们的种类只由内核给出），
    # 同一个种类由两个应用以不同的登记名登记时拒绝
    declared = tuple(kinds)
    clash = sorted(kind for kind in declared if kind in SKELETON_EVENTS)
    if clash:
        raise ValueError(f"骨架事件的种类由内核给出，应用不能登记：{clash}")
    for kind in declared:
        previous = _APPLICATION_EVENTS.get(kind)
        if previous is not None and previous != owner:
            raise ValueError(f"{kind} 已经由 {previous} 登记")
    if not owner.strip():
        raise ValueError("登记应用事件种类要写明是哪个应用")
    for kind in declared:
        _APPLICATION_EVENTS[kind] = owner


def application_event_types() -> dict[str, str]:
    # 已经登记的应用事件种类，按种类给出登记它的应用
    return dict(_APPLICATION_EVENTS)


def event_type_owner(kind: str) -> str | None:
    # 这个事件种类归谁：骨架事件返回 skeleton，应用事件返回登记它的应用，没登记过返回空
    if kind in SKELETON_EVENTS:
        return "skeleton"
    return _APPLICATION_EVENTS.get(kind)


# ---------------------------------------------------------------------------
# 信封与载荷的序列化：事件写进日志与算摘要都只经过这里，结果是确定的

def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)


def _json_default(value: Any) -> Any:
    # 数据类按它的字段写。元组不在这里处理：json 自己就把元组写成数组（搬过来时这里有一支元组分支，
    # 从来没有被调用过，models.py 里它历来也是没有覆盖的一行）
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError(f"not json serializable: {type(value)!r}")


def canonical_hash(value: Any) -> str:
    data = json_dumps(value).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def spec_content_hash(kind: str, payload: dict[str, Any], *, parent_hash: str | None, revision: int) -> str:
    # 提案内容的摘要：种类、上一版、载荷与版本一起算，载荷的键序不影响结果
    return canonical_hash(
        {
            "kind": kind,
            "parent_hash": parent_hash,
            "payload": payload,
            "revision": revision,
        }
    )


# ---------------------------------------------------------------------------
# 事件信封：run 流、项目流与目录流中的一条事件


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


# ---------------------------------------------------------------------------
# 决定请求：由骨架事件（请求、回答与撤销）折叠成的一份数据结构，每个决定请求另存一份投影，
# 与事件在同一个事务中更新（写入口）。它不属于任何应用：项目流与目录流的决定请求也由同一套折叠得出


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


def apply_decision_event(decisions: dict[str, DecisionRequest], event: Event | ProjectEvent) -> str | None:
    # 把一条事件并入这个流的决定请求，返回改变的决定请求的身份；不是决定事件时什么也不改变，返回空
    payload = event.payload
    if event.type == SkeletonEventType.DECISION_REQUESTED:
        decisions[event.event_id] = DecisionRequest(
            decision_id=event.event_id, stream=event.stream, run_id=event.run_id, project_id=event.project_id,
            work_item_id=event.work_item_id, requested_at=event.created_at, request=dict(payload),
        )
        return event.event_id
    if event.type in (SkeletonEventType.DECISION_ANSWERED, ProjectEventType.PROJECT_DECISION_ANSWERED,
                      CatalogEventType.INSTANCE_UPGRADE_ANSWERED):
        decision = decisions[payload["decision_id"]]
        decision.status = "answered"
        decision.answer = {"event_id": event.event_id, "option": payload["option"], "note": payload["note"],
                           "base_version": payload["base_version"], "actor": event.actor,
                           "command_id": event.command_id, "answered_at": event.created_at}
        return decision.decision_id
    if event.type in (SkeletonEventType.DECISION_WITHDRAWN, ProjectEventType.PROJECT_DECISION_WITHDRAWN,
                      CatalogEventType.INSTANCE_UPGRADE_WITHDRAWN):
        decision = decisions[payload["decision_id"]]
        decision.status = "withdrawn"
        decision.withdrawal = {"event_id": event.event_id, "reason": payload["reason"],
                               "withdrawn_at": event.created_at}
        return decision.decision_id
    if event.type == ProjectEventType.PROJECT_DECISION_REQUESTED:
        # 项目流中的决定请求（工单 #136）：不属于任何 run，run_id 为空，所属事项与候选 run 在载荷里
        decisions[event.event_id] = DecisionRequest(
            decision_id=event.event_id, stream=event.stream, run_id=None,
            project_id=event.project_id, work_item_id=payload.get("work_item_id"),
            requested_at=event.created_at, request=dict(payload),
        )
        return event.event_id
    if event.type == CatalogEventType.INSTANCE_UPGRADE_REQUESTED:
        # 目录流中的决定请求（工单 #355）：不属于任何项目或 run，范围列为空
        decisions[event.event_id] = DecisionRequest(
            decision_id=event.event_id, stream=event.stream, run_id=None, project_id=None, work_item_id=None,
            requested_at=event.created_at, request=dict(payload))
        return event.event_id
    return None


def replay_decisions(events: list[Event] | list[ProjectEvent]) -> dict[str, DecisionRequest]:
    decisions: dict[str, DecisionRequest] = {}
    for event in events:
        apply_decision_event(decisions, event)
    return decisions


class StreamHandler(Protocol):
    # 一种流的投影的处理者：空投影、保存的投影的还原与序列化、并入一条事件、从头重放。
    # run 流的处理者在内核里（projection.run_handler），项目流与目录流的处理者在内核以外，
    # 由写入口的构造者注入；写入口只按这个接口使用它们，不经由投影的具体类型
    def empty(self) -> Any: ...

    def load(self, saved: Any) -> Any: ...

    def dump(self, state: Any) -> str: ...

    def fold(self, state: Any, event: Any) -> None: ...

    def replay(self, stream: str, events: list[Any]) -> Any: ...
