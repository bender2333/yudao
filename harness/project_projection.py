# 项目投影与目录投影：不由裁决读取的两个投影及其折叠规则。
# 它们是事件的同一种折叠结果，但控制核心的裁决（工具许可、提案校验、停止原因、边界）不读取它们，
# 因此放在内核文件以外（可信内核设计说明第 3 节）；写入口按流的处理者把它们与 run 投影一视同仁地折叠与保存。

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import TypeAdapter

from .definitions import DEFINITIONS
from .event_store import EventStore, SavedProjection, is_catalog_stream, is_run_stream, project_stream
from .models import CatalogEvent, CatalogEventType, ProjectEvent, ProjectEventType, json_dumps
from .projection import StreamHandler, run_handler


def _plain(value: Any) -> Any:
    return json.loads(json_dumps(value))


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
    writeback_enabled: bool = False
    remote: str = ""
    target_branch: str = ""
    check_commands: list[str] = field(default_factory=list)
    credential_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass
class WritebackRecord:
    status: str
    work_item_id: str
    run_id: str
    adoption_id: str
    target_commit: str
    reason: str | None = None
    branch: str | None = None
    final_tree_digest: str | None = None
    check_receipts: list[dict[str, Any]] = field(default_factory=list)
    pull_request: dict[str, Any] | None = None
    conflict_ref: dict[str, Any] | None = None
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    verified_fact: dict[str, Any] | None = None
    stream_version: int = 0
    event_id: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


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
    writeback: WritebackRecord | None = None

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
    materials: list[Material] = field(default_factory=list)
    source_directories: dict[str, SourceDirectory] = field(default_factory=dict)
    source_directory_history: list[SourceDirectory] = field(default_factory=list)
    writebacks: list[WritebackRecord] = field(default_factory=list)
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


# 保存的投影以 JSON 存放，由 pydantic 按数据类的类型序列化与还原
_PROJECT_STATE = TypeAdapter(ProjectProjection)
_CATALOG_STATE = TypeAdapter(CatalogProjection)


def saved_project(store: EventStore, project_id: str) -> ProjectProjection | None:
    # 读取保存的项目投影；项目不存在时为空
    saved = store.projection(project_stream(project_id))
    return None if saved is None else _PROJECT_STATE.validate_json(saved.state)


def replay_project(store: EventStore, project_id: str, *, through: int | None = None) -> ProjectProjection | None:
    # 从项目流的第一条事件重放项目投影：只用于重建、核对与按位置读取（through 给出全局位置的上界）
    events = store.list_project_events(project_id, through_position=through)
    if not events:
        return None
    state = ProjectProjection()
    for event in events:
        apply_project_event(state, event)
    return state


def apply_project_event(state: ProjectProjection, event: ProjectEvent) -> None:
    payload = event.payload
    etype = event.type
    state.last_event_id = event.event_id
    state.stream_version = event.stream_version
    state.updated_at = event.created_at
    if etype == ProjectEventType.PROJECT_REGISTERED:
        state.project_id = event.project_id
        state.name = payload["name"]
        state.goal = payload["goal"]
        state.goal_ref = payload["goal_ref"]
        state.source = payload["source"]
        state.initial_snapshot = payload.get("initial_snapshot")
        state.created_at = event.created_at
        return
    if etype == ProjectEventType.PROJECT_RENAMED:
        state.name = payload["name"]
        return
    if etype == ProjectEventType.PROJECT_GOAL_CHANGED:
        state.goal = payload["goal"]
        state.goal_ref = payload["goal_ref"]
        return
    if etype == ProjectEventType.PROJECT_PINNED:
        state.pinned = bool(payload["pinned"])
        return
    if etype == ProjectEventType.PROJECT_ARCHIVED:
        state.archived = True
        return
    if etype == ProjectEventType.PROJECT_RESTORED:
        state.archived = False
        return
    if etype == ProjectEventType.WORK_ITEM_CREATED:
        state.work_items.append(WorkItem(
            work_item_id=payload["work_item_id"], title=payload["title"], text=payload["text"], run_id=payload["run_id"],
            baseline=payload["baseline"], project_context_ref=payload["project_context_ref"],
            prompt_config_versions=dict(payload["prompt_config_versions"]),
            max_cycles=int(payload["max_cycles"]),
            run_time_limit_sec=int(payload["run_time_limit_sec"]),
            # 项目流的字段按 ADR-0019 保留：它是这个事项声明的窗口，现在只给测试适配器用
            context_window=int(payload["context_window"]), created_at=event.created_at,
            stream_version=event.stream_version, event_id=event.event_id, snapshot=payload.get("snapshot"),
            kind=payload.get("kind", "change"),
        ))
        return
    if etype == ProjectEventType.WORK_ITEM_START_FAILED:
        item = state.work_item(payload["work_item_id"])
        if item is not None:
            item.start_error = payload["error"]
        return
    if etype == ProjectEventType.DELIVERABLE_ADOPTED:
        adoption = Adoption(
            adoption_id=payload["adoption_id"], work_item_id=payload["work_item_id"], run_id=payload["run_id"],
            delivery_event_id=payload["delivery_event_id"], qa_event_id=payload["qa_event_id"],
            tree_ref=payload["tree_ref"], code_tree_digest=payload["code_tree_digest"], summary=payload["summary"],
            files=list(payload["files"]), check_names=list(payload["check_names"]),
            known_risks=list(payload["known_risks"]), previous_adoption_id=payload["previous_adoption_id"],
            adopted_at=event.created_at, stream_version=event.stream_version, event_id=event.event_id,
        )
        state.adoptions.append(adoption)
        state.current_adoption = adoption
        return
    if etype == ProjectEventType.ADOPTION_HELD:
        state.held.append(HeldCandidate(
            work_item_id=payload["work_item_id"], run_id=payload["run_id"],
            delivery_event_id=payload["delivery_event_id"], code_tree_digest=payload["code_tree_digest"],
            reason=payload["reason"], expected_adoption_id=payload["expected_adoption_id"],
            current_adoption_id=payload["current_adoption_id"], held_at=event.created_at,
            stream_version=event.stream_version, event_id=event.event_id,
        ))
        return
    if etype == ProjectEventType.DEPARTMENT_SETTINGS_CONFIGURED:
        department = payload["department"]
        # 旧版本的事件只带 text（部门 Prompt），新版本带 department_prompt 与模型、请求档位（ADR-0019）
        if "department_prompt" in payload:
            configured_prompt = payload["department_prompt"]
            prompt_ref = payload.get("department_prompt_ref")
        else:
            configured_prompt = payload.get("text")
            prompt_ref = payload.get("prompt_ref")
        text = configured_prompt if configured_prompt is not None else DEFINITIONS.role(department).prompt
        setting = DepartmentSetting(
            department=department, version=int(payload["version"]), text=text, source="configured",
            provider_id=payload.get("provider_id"), model_id=payload.get("model_id"),
            requested_tier=payload.get("requested_tier"), configured_prompt=configured_prompt is not None,
            prompt_ref=prompt_ref, base_version=payload.get("base_version"),
            updated_at=event.created_at, event_id=event.event_id,
        )
        state.department_settings[department] = setting
        state.department_setting_history.append(setting)
        return
    if etype == ProjectEventType.MATERIAL_RECORDED:
        state.materials.append(Material(
            material_id=payload["material_id"], text=payload["text"], material_ref=payload["material_ref"],
            department=payload["department"], recorded_at=event.created_at, stream_version=event.stream_version,
            event_id=event.event_id,
        ))
        return
    if etype == ProjectEventType.SOURCE_DIRECTORY_CONFIGURED:
        directory = SourceDirectory(
            name=payload["name"], path=payload["path"], version=int(payload["version"]),
            base_version=payload.get("base_version"), updated_at=event.created_at, event_id=event.event_id,
            writeback_enabled=bool(payload.get("writeback_enabled", False)),
            remote=str(payload.get("remote") or ""),
            target_branch=str(payload.get("target_branch") or ""),
            check_commands=list(payload.get("check_commands") or []),
            credential_ref=payload.get("credential_ref"),
        )
        state.source_directories[directory.name] = directory
        state.source_directory_history.append(directory)
        return
    if etype == ProjectEventType.INITIAL_PRD_PROPOSED:
        # 建档候选（工单 #136）：记下这一轮的三份产物与快照，等待用户确认
        state.initial_prd_candidates.append(InitialPrdCandidate(
            work_item_id=payload["work_item_id"], run_id=payload["run_id"], round=int(payload["round"]),
            prd=dict(payload["prd"]), structure=dict(payload["structure"]),
            baseline_review=dict(payload["baseline_review"]), overview_ref=dict(payload["overview_ref"]),
            snapshot=dict(payload["snapshot"]), revision_note_ref=payload.get("revision_note_ref"),
            proposed_at=event.created_at, stream_version=event.stream_version, event_id=event.event_id,
        ))
        return
    if etype == ProjectEventType.ONBOARDING_REVISION_STARTED:
        # 建档修改轮（工单 #136）：同一个建档事项开始新一轮 run，事项的 run 改为这一轮的 run
        item = state.work_item(payload["work_item_id"])
        if item is not None:
            item.run_id = payload["run_id"]
            item.status = "not_started"
            item.start_error = None
        return
    if etype == ProjectEventType.BASELINE_ADOPTED:
        # 采纳建档基线（工单 #136）：第一次采纳的成果是快照本身，与 deliverable_adopted 并列成为当前采纳成果
        adoption = Adoption(
            adoption_id=payload["adoption_id"], work_item_id=payload["work_item_id"], run_id=payload["run_id"],
            delivery_event_id=payload["candidate_event_id"], qa_event_id=payload["candidate_event_id"],
            tree_ref=payload["tree_ref"], code_tree_digest=payload["code_tree_digest"], summary=payload["summary"],
            files=list(payload["files"]), check_names=list(payload["check_names"]),
            known_risks=list(payload["known_risks"]), previous_adoption_id=payload["previous_adoption_id"],
            adopted_at=event.created_at, stream_version=event.stream_version, event_id=event.event_id,
            prd_ref=payload["prd_ref"], product_spec_hash=payload["product_spec_hash"],
            structure_ref=payload["structure_ref"], snapshot=payload.get("snapshot"),
            existing_defects=list(payload.get("existing_defects") or []),
        )
        state.adoptions.append(adoption)
        state.current_adoption = adoption
        return
    if etype == ProjectEventType.WRITEBACK_COMPLETED:
        rec = WritebackRecord(
            status="completed", work_item_id=payload["work_item_id"], run_id=payload["run_id"],
            adoption_id=payload["adoption_id"], target_commit=payload["target_commit"],
            branch=payload.get("branch"), final_tree_digest=payload.get("final_tree_digest"),
            check_receipts=list(payload.get("check_receipts") or []),
            pull_request=payload.get("pull_request"), stream_version=event.stream_version,
            event_id=event.event_id, created_at=event.created_at,
        )
        state.writebacks.append(rec)
        item = state.work_item(payload["work_item_id"])
        if item is not None:
            item.writeback = rec
        return
    if etype == ProjectEventType.WRITEBACK_STOPPED:
        rec = WritebackRecord(
            status="stopped", work_item_id=payload["work_item_id"], run_id=payload["run_id"],
            adoption_id=payload["adoption_id"], target_commit=payload["target_commit"],
            reason=payload["reason"], final_tree_digest=payload.get("final_tree_digest"),
            conflict_ref=payload.get("conflict_ref"), conflicts=list(payload.get("conflicts") or []),
            check_receipts=list(payload.get("check_receipts") or []),
            stream_version=event.stream_version, event_id=event.event_id, created_at=event.created_at,
        )
        state.writebacks.append(rec)
        item = state.work_item(payload["work_item_id"])
        if item is not None:
            item.writeback = rec
        return
    if etype == ProjectEventType.WRITEBACK_NOT_NEEDED:
        rec = WritebackRecord(
            status="not_needed", work_item_id=payload["work_item_id"], run_id=payload["run_id"],
            adoption_id=payload["adoption_id"], target_commit=payload["target_commit"],
            reason=payload.get("reason", "changes_already_present"),
            stream_version=event.stream_version, event_id=event.event_id, created_at=event.created_at,
        )
        state.writebacks.append(rec)
        item = state.work_item(payload["work_item_id"])
        if item is not None:
            item.writeback = rec
        return
    if etype == ProjectEventType.WRITEBACK_HELD:
        rec = WritebackRecord(
            status="held", work_item_id=payload["work_item_id"], run_id=payload["run_id"],
            adoption_id=payload["adoption_id"], target_commit=payload["target_commit"],
            reason=payload.get("reason", "waiting_previous_adoption"),
            stream_version=event.stream_version, event_id=event.event_id, created_at=event.created_at,
        )
        state.writebacks.append(rec)
        item = state.work_item(payload["work_item_id"])
        if item is not None:
            item.writeback = rec
        return
    if etype == ProjectEventType.WRITEBACK_VERIFIED:
        rec = WritebackRecord(
            status="verified", work_item_id=payload["work_item_id"], run_id=payload["run_id"],
            adoption_id=payload["adoption_id"], target_commit=payload["target_commit"],
            branch=payload.get("branch"), verified_fact=payload.get("verified_fact"),
            stream_version=event.stream_version, event_id=event.event_id, created_at=event.created_at,
        )
        state.writebacks.append(rec)
        item = state.work_item(payload["work_item_id"])
        if item is not None:
            item.writeback = rec
        return


def apply_catalog_event(state: CatalogProjection, event: CatalogEvent) -> None:
    # 目录投影只记最后一条事件与最后一条 catalog_revised 的修订号；目录内容仍由 Provider 模块保存。
    # home_seen 另记用户查看过的全局位置与时间（工单 #127），控制主机上只有一个
    state.last_event_id = event.event_id
    state.stream_version = event.stream_version
    state.updated_at = event.created_at
    if event.type == CatalogEventType.CATALOG_REVISED:
        state.revision = int(event.payload["revision"])
    elif event.type == CatalogEventType.HOME_SEEN:
        state.last_seen_position = int(event.payload["position"])
        state.last_seen_at = event.created_at


# 写入口按流取处理者（projection.StreamHandler）：run 流的处理者在内核里，这两个由写入口的执行环境注入


class _ProjectHandler:
    def empty(self) -> ProjectProjection:
        return ProjectProjection()

    def load(self, saved: SavedProjection) -> ProjectProjection:
        return _PROJECT_STATE.validate_json(saved.state)

    def dump(self, state: ProjectProjection) -> str:
        return _PROJECT_STATE.dump_json(state).decode("utf-8")

    def fold(self, state: ProjectProjection, event: ProjectEvent) -> None:
        apply_project_event(state, event)

    def replay(self, stream: str, events: list[ProjectEvent]) -> ProjectProjection:
        state = ProjectProjection()
        for event in events:
            apply_project_event(state, event)
        return state


class _CatalogHandler:
    def empty(self) -> CatalogProjection:
        return CatalogProjection()

    def load(self, saved: SavedProjection) -> CatalogProjection:
        return _CATALOG_STATE.validate_json(saved.state)

    def dump(self, state: CatalogProjection) -> str:
        return _CATALOG_STATE.dump_json(state).decode("utf-8")

    def fold(self, state: CatalogProjection, event: CatalogEvent) -> None:
        apply_catalog_event(state, event)

    def replay(self, stream: str, events: list[CatalogEvent]) -> CatalogProjection:
        state = CatalogProjection()
        for event in events:
            apply_catalog_event(state, event)
        return state


def project_handler() -> StreamHandler:
    return _ProjectHandler()




def catalog_handler() -> StreamHandler:
    return _CatalogHandler()


def handler_for(stream: str) -> StreamHandler:
    # 按流给出它的投影的处理者：run 流的处理者在内核里，另两个在本模块
    if is_run_stream(stream):
        return run_handler()
    if is_catalog_stream(stream):
        return _CatalogHandler()
    return _ProjectHandler()
