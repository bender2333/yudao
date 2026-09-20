"""项目层：登记、事项创建、采纳结算、继承恢复、部门 Prompt 项目配置、项目材料与项目读模型。

只通过 `Orchestrator.create_run(...)` 与运行内核交互，且只在事项创建时；
只读 run 投影（`project_run`）与 run 工件，不生成运行事实、不改 run 流、不调用模型。
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from typing import Any

from .artifacts import ArtifactStore
from .department_prompts import DEFAULT_PROMPTS, save_department_prompt
from .event_store import EventStore
from .materials import save_text_material
from .models import (
    ArtifactRef,
    DEPARTMENTS,
    Event,
    EventType,
    ProjectEvent,
    RunProjection,
    TERMINAL_PHASES,
    department_for_phase,
    json_dumps,
    new_id,
)
from .projection import RunNotFoundError, project_run
from .snapshot import ingest_snapshot
from .tools import validate_registered_command
from .tree_archive import load_tree

TITLE_LIMIT = 40
RECENT_LIMIT = 20
RECENT_RUN_EVENTS = frozenset({EventType.TRANSITION, EventType.RUN_DONE, EventType.RUN_FAILED, EventType.RUN_PAUSED})
REWORK_VERDICTS = frozenset({"rework_product", "rework_engineering"})


class ProjectEventType:
    PROJECT_REGISTERED = "project_registered"
    PROJECT_RENAMED = "project_renamed"
    PROJECT_PINNED = "project_pinned"
    PROJECT_ARCHIVED = "project_archived"
    PROJECT_RESTORED = "project_restored"
    WORK_ITEM_CREATED = "work_item_created"
    WORK_ITEM_START_FAILED = "work_item_start_failed"
    DELIVERABLE_ADOPTED = "deliverable_adopted"
    ADOPTION_HELD = "adoption_held"
    DEPARTMENT_PROMPT_CONFIGURED = "department_prompt_configured"
    COMMAND_CONFIGURED = "command_configured"
    MATERIAL_RECORDED = "material_recorded"


class ProjectNotFoundError(KeyError):
    pass


class ProjectArchivedError(ValueError):
    """归档项目只读：写命令被拒绝。"""


class WorkItemInProgressError(ValueError):
    """有进行中事项时不能归档或记录材料。"""


class PromptConfigConflict(Exception):
    """所编辑的配置版本已过期；`current` 是项目当前配置的读取体。"""
    def __init__(self, current: dict[str, Any]) -> None:
        super().__init__("department prompt configuration changed since base_version")
        self.current = current


class CommandConfigConflict(Exception):
    """所编辑的命令版本已过期；`current` 是项目当前命令的读取体。"""
    def __init__(self, current: dict[str, Any]) -> None:
        super().__init__("registered command changed since base_version")
        self.current = current


# ---------------------------------------------------------------------------
# 读模型


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
    seq: int
    event_id: str

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
    seq: int
    event_id: str

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass
class PromptConfig:
    department: str
    version: int
    text: str
    source: str
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
    seq: int
    event_id: str

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

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    def frozen(self) -> dict[str, Any]:
        # 事项创建时冻结进 run 的执行形态：只有固定参数与限额，没有版本管理字段
        return {"argv": list(self.argv), "args": list(self.args),
                "timeout_sec": self.timeout_sec, "output_limit": self.output_limit}


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
    context_window: int
    created_at: str
    seq: int
    event_id: str
    snapshot: dict[str, Any] | None = None
    start_error: str | None = None
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
    work_items: list[WorkItem] = field(default_factory=list)
    current_adoption: Adoption | None = None
    adoptions: list[Adoption] = field(default_factory=list)
    held: list[HeldCandidate] = field(default_factory=list)
    prompt_configs: dict[str, PromptConfig] = field(default_factory=dict)
    prompt_config_history: list[PromptConfig] = field(default_factory=list)
    commands: dict[str, RegisteredCommand] = field(default_factory=dict)
    command_history: list[RegisteredCommand] = field(default_factory=list)
    materials: list[Material] = field(default_factory=list)
    active_work_item_id: str | None = None
    updated_at: str = ""
    last_seq: int = 0
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


def project_projection(store: EventStore, artifacts: ArtifactStore, project_id: str) -> ProjectProjection:
    """仅由 `project_events` 与所属 run 的 `project_run` 重建，不读任何派生缓存。"""
    events = store.list_project_events(project_id)
    if not events:
        raise ProjectNotFoundError(project_id)
    state = ProjectProjection()
    for event in events:
        apply_project_event(state, event)
    for department in DEPARTMENTS:
        state.prompt_configs.setdefault(department, PromptConfig(
            department=department, version=0, text=DEFAULT_PROMPTS[department], source="default",
        ))
    adopted = {item.run_id: item for item in state.adoptions}
    held = {item.run_id: item for item in state.held}
    for item in state.work_items:
        _derive_work_item(store, item, adopted, held, project_id)
    state.active_work_item_id = next((item.work_item_id for item in state.work_items if item.status == "in_progress"), None)
    return state


def apply_project_event(state: ProjectProjection, event: ProjectEvent) -> None:
    payload = event.payload
    etype = event.type
    state.last_event_id = event.event_id
    state.last_seq = event.seq
    state.updated_at = event.created_at
    if etype == ProjectEventType.PROJECT_REGISTERED:
        state.project_id = event.project_id
        state.name = payload["name"]
        state.goal = payload["goal"]
        state.goal_ref = payload["goal_ref"]
        state.source = payload["source"]
        state.created_at = event.created_at
        return
    if etype == ProjectEventType.PROJECT_RENAMED:
        state.name = payload["name"]
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
            command_versions=dict(payload.get("command_versions") or {}),
            max_cycles=int(payload["max_cycles"]),
            context_window=int(payload["context_window"]), created_at=event.created_at, seq=event.seq,
            event_id=event.event_id, snapshot=payload.get("snapshot"),
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
            adopted_at=event.created_at, seq=event.seq, event_id=event.event_id,
        )
        state.adoptions.append(adoption)
        state.current_adoption = adoption
        return
    if etype == ProjectEventType.ADOPTION_HELD:
        state.held.append(HeldCandidate(
            work_item_id=payload["work_item_id"], run_id=payload["run_id"],
            delivery_event_id=payload["delivery_event_id"], code_tree_digest=payload["code_tree_digest"],
            reason=payload["reason"], expected_adoption_id=payload["expected_adoption_id"],
            current_adoption_id=payload["current_adoption_id"], held_at=event.created_at, seq=event.seq,
            event_id=event.event_id,
        ))
        return
    if etype == ProjectEventType.DEPARTMENT_PROMPT_CONFIGURED:
        config = PromptConfig(
            department=payload["department"], version=int(payload["version"]), text=payload["text"],
            source="configured", prompt_ref=payload["prompt_ref"], base_version=payload["base_version"],
            updated_at=event.created_at, event_id=event.event_id,
        )
        state.prompt_configs[config.department] = config
        state.prompt_config_history.append(config)
        return
    if etype == ProjectEventType.COMMAND_CONFIGURED:
        command = RegisteredCommand(
            name=payload["name"], version=int(payload["version"]), argv=list(payload["argv"]),
            args=list(payload["args"]), timeout_sec=int(payload["timeout_sec"]),
            output_limit=int(payload["output_limit"]), base_version=payload["base_version"],
            updated_at=event.created_at, event_id=event.event_id,
        )
        state.commands[command.name] = command
        state.command_history.append(command)
        return
    if etype == ProjectEventType.MATERIAL_RECORDED:
        state.materials.append(Material(
            material_id=payload["material_id"], text=payload["text"], material_ref=payload["material_ref"],
            department=payload["department"], recorded_at=event.created_at, seq=event.seq, event_id=event.event_id,
        ))
        return


def _derive_work_item(store: EventStore, item: WorkItem, adopted: dict[str, Adoption],
                      held: dict[str, HeldCandidate], project_id: str) -> None:
    try:
        run = project_run(store, item.run_id)
    except RunNotFoundError:
        item.status = "not_started"
        return
    if run.project_id != project_id or run.work_item_id != item.work_item_id:
        item.status = "not_started"
        return
    events = store.list_events(item.run_id)
    item.phase = run.phase
    item.stop_reason = run.stop_reason
    item.human_action = run.human_action
    item.cycle_count = run.cycle_count
    item.department = None if run.phase in TERMINAL_PHASES else department_for_phase(run.phase)
    if run.run_id in adopted:
        item.status = "adopted"
        item.adoption_id = adopted[run.run_id].adoption_id
    elif run.run_id in held:
        item.status = "held"
    elif run.phase == "DONE":
        item.status = "released_unsettled"
    elif run.phase in TERMINAL_PHASES:
        item.status = "stopped"
    else:
        item.status = "in_progress"
    handoffs = work_item_handoffs(events)
    item.last_handoff = handoffs[-1] if handoffs else None
    item.rework = [
        {"verdict": event.payload["verdict"], "seq": event.seq, "at": event.created_at,
         "summary": event.payload.get("rationale", "")}
        for event in events
        if event.type == EventType.QA_SUBMITTED and event.payload.get("verdict") in REWORK_VERDICTS
    ]
    if run.pending_request is not None:
        item.pending_question = run.pending_request.question
    elif run.phase in TERMINAL_PHASES:
        item.pending_question = run.human_action
    else:
        item.pending_question = run.waiting_reason


def work_item_handoffs(events: list[Event]) -> list[dict[str, Any]]:
    return [
        {"from": event.state_before, "to": event.state_after, "seq": event.seq, "at": event.created_at}
        for event in events if event.type == EventType.TRANSITION
    ]


def project_event_card(event: ProjectEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "project_id": event.project_id,
        "seq": event.seq,
        "type": event.type,
        "created_at": event.created_at,
        "work_item_id": event.payload.get("work_item_id"),
        "run_id": event.payload.get("run_id"),
        "payload": event.payload,
    }


def project_overview(store: EventStore, project: ProjectProjection) -> dict[str, Any]:
    """概览：目标、当前采用成果、待决、近期动态（项目事件与所属 run 的关键事件合并倒序）。"""
    recent = [
        {"kind": "project", "type": event.type, "at": event.created_at, "seq": event.seq, "event_id": event.event_id,
         "work_item_id": event.payload.get("work_item_id"), "run_id": event.payload.get("run_id"),
         "summary": _project_event_summary(event)}
        for event in store.list_project_events(project.project_id)
    ]
    for item in project.work_items:
        for event in store.list_events(item.run_id):
            if event.type not in RECENT_RUN_EVENTS:
                continue
            recent.append({
                "kind": "loop", "type": event.type, "at": event.created_at, "seq": event.seq, "event_id": event.event_id,
                "work_item_id": item.work_item_id, "run_id": item.run_id,
                "summary": (f"{event.state_before}->{event.state_after}" if event.type == EventType.TRANSITION
                            else event.stop_reason or event.type),
            })
    recent.sort(key=lambda entry: (entry["at"], entry["seq"]), reverse=True)
    pending = [
        {"work_item_id": item.work_item_id, "title": item.title, "status": item.status,
         "question": item.pending_question, "human_action": item.human_action}
        for item in project.work_items if item.pending_question
    ]
    return {
        "goal": project.goal,
        "current_adoption": None if project.current_adoption is None else project.current_adoption.to_dict(),
        "pending": pending,
        "recent": recent[:RECENT_LIMIT],
    }


def _project_event_summary(event: ProjectEvent) -> str:
    payload = event.payload
    return str(
        payload.get("title") or payload.get("summary") or payload.get("name") or payload.get("reason")
        or payload.get("error") or (payload.get("department") if event.type == ProjectEventType.DEPARTMENT_PROMPT_CONFIGURED else None)
        or event.type
    )


# ---------------------------------------------------------------------------
# 项目上下文材料（钉住部件 `project`）


def project_context_text(project: ProjectProjection, title: str,
                         source_run: RunProjection | None = None) -> str:
    """确定性 Markdown：同输入同字节。顺序固定，无则写"无"。"""
    adoption = project.current_adoption
    if adoption is None:
        current = "无（这是项目的第一个事项）"
    else:
        source = project.work_item(adoption.work_item_id)
        source_title = adoption.work_item_id if source is None else source.title
        current = (
            f"来自事项「{source_title}」（run {adoption.run_id}，采纳 {adoption.adoption_id}）：{adoption.summary}；"
            f"文件：{_join(adoption.files)}；检查：{_join(adoption.check_names)}；已知风险：{_join(adoption.known_risks)}。"
            f"本 run 工作区已从该成果的完整封存恢复，digest {adoption.code_tree_digest}。"
        )
    if project.adoptions:
        adopted_lines = ["已采纳事项："]
        for index, item in enumerate(project.adoptions, start=1):
            source = project.work_item(item.work_item_id)
            source_title = item.work_item_id if source is None else source.title
            adopted_lines.append(f'{index}. "{source_title}" — {item.summary}')
        adopted = "\n".join(adopted_lines)
    else:
        adopted = "已采纳事项：无"
    return "\n".join([
        f"项目：{project.name}",
        f"长期目标：{project.goal}",
        f"当前采用成果：{current}",
        adopted,
        _effective_decisions_section(adoption, source_run),
        f"本事项：{title}",
    ])


def _effective_decisions_section(adoption: Adoption | None, source_run: RunProjection | None) -> str:
    if adoption is None:
        return "仍有效的决定：无"
    spec = None if source_run is None else source_run.product_spec
    if spec is None or spec.status != "active":
        return "仍有效的决定：无"
    if source_run.effective_decisions:
        decision_lines = ["有效决定："]
        for index, item in enumerate(source_run.effective_decisions, start=1):
            decision_lines.append(f'{index}. "{item.statement}" — {item.rationale}')
        decisions = "\n".join(decision_lines)
    else:
        decisions = "有效决定：无"
    return "\n".join([
        "仍有效的决定：",
        f"产品合同 r{spec.revision} hash {spec.content_hash}",
        f"目标：{spec.goal}",
        f"要求：{_join(spec.requirements)}",
        f"边界：{_join(spec.boundaries)}",
        f"约束：{_join(spec.constraints)}",
        f"验收：{_join(spec.acceptance_criteria)}",
        f"致命条件：{_join(spec.fatal_conditions)}",
        f"非目标：{_join(spec.non_goals)}",
        decisions,
    ])


def _join(values: list[str]) -> str:
    return "、".join(values) if values else "无"


def work_item_title(text: str) -> str:
    first = next((line.strip() for line in text.splitlines() if line.strip()), text.strip())
    return first[:TITLE_LIMIT]


# ---------------------------------------------------------------------------
# 命令


class ProjectService:
    def __init__(self, store: EventStore, artifacts: ArtifactStore, orchestrator: Any) -> None:
        self.store = store
        self.artifacts = artifacts
        self.orchestrator = orchestrator
        self._lock = threading.RLock()

    # 读

    def projection(self, project_id: str) -> ProjectProjection:
        return project_projection(self.store, self.artifacts, project_id)

    def list_projects(self, *, include_archived: bool = False) -> list[ProjectProjection]:
        projects = [self.projection(project_id) for project_id in self.store.list_project_ids()]
        if not include_archived:
            projects = [item for item in projects if not item.archived]
        # 置顶优先、再按 updated_at 倒序：两次稳定排序。
        projects.sort(key=lambda item: item.updated_at, reverse=True)
        projects.sort(key=lambda item: not item.pinned)
        return projects

    def read_prompt(self, project_id: str, department: str) -> dict[str, Any]:
        if department not in DEPARTMENTS:
            raise ValueError("unknown department")
        return _prompt_view(self.projection(project_id).prompt_configs[department])

    def read_commands(self, project_id: str) -> list[dict[str, Any]]:
        return [_command_view(config) for _, config in sorted(self.projection(project_id).commands.items())]

    def read_command(self, project_id: str, name: str) -> dict[str, Any]:
        config = self.projection(project_id).commands.get(name)
        if config is None:
            raise ValueError(f"unknown registered command: {name}")
        return _command_view(config)

    # 项目登记与状态

    def register(self, name: str, goal: str) -> str:
        _require_text("name", name)
        _require_text("goal", goal)
        project_id = new_id("proj")
        goal_ref = self.artifacts.put(project_id, "project_goal", goal, media_type="text/markdown")
        with self._lock:
            self.store.append_project(project_id, ProjectEventType.PROJECT_REGISTERED, {
                "name": name, "goal": goal, "goal_ref": asdict(goal_ref), "source": "idea",
            })
        return project_id

    def rename(self, project_id: str, name: str) -> None:
        _require_text("name", name)
        with self._lock:
            self._writable(project_id)
            self.store.append_project(project_id, ProjectEventType.PROJECT_RENAMED, {"name": name})

    def pin(self, project_id: str, pinned: bool) -> None:
        if not isinstance(pinned, bool):
            raise ValueError("pinned must be a boolean")
        with self._lock:
            self._writable(project_id)
            self.store.append_project(project_id, ProjectEventType.PROJECT_PINNED, {"pinned": pinned})

    def archive(self, project_id: str) -> None:
        with self._lock:
            project = self.projection(project_id)
            if project.archived:
                return
            _reject_in_progress(project)
            self.store.append_project(project_id, ProjectEventType.PROJECT_ARCHIVED, {})

    def restore(self, project_id: str) -> None:
        with self._lock:
            if self.projection(project_id).archived:
                self.store.append_project(project_id, ProjectEventType.PROJECT_RESTORED, {})

    # 事项

    def start_work_item(self, project_id: str, text: str, *, title: str | None = None,
                        max_cycles: int = 8, context_window: int = 32_000) -> tuple[str, str]:
        _require_text("text", text)
        with self._lock:
            self._writable(project_id)
            self.settle_pending(project_id)
            project = self.projection(project_id)
            baseline = None
            initial_tree = None
            source_run = None
            if project.current_adoption is not None:
                adoption = project.current_adoption
                source_run = project_run(self.store, adoption.run_id)
                if source_run.project_id != project_id:
                    raise ValueError("source run does not belong to this project")
                baseline = {
                    "adoption_id": adoption.adoption_id, "source_run_id": adoption.run_id,
                    "delivery_event_id": adoption.delivery_event_id, "tree_ref": adoption.tree_ref,
                    "code_tree_digest": adoption.code_tree_digest,
                }
                initial_tree = load_tree(self.artifacts, adoption.run_id, ArtifactRef(**adoption.tree_ref))
                if initial_tree.digest != adoption.code_tree_digest:
                    raise ValueError("archived tree does not match the adopted deliverable digest")
            return self._emit_work_item(
                project, text, title=title, max_cycles=max_cycles, context_window=context_window,
                baseline=baseline, initial_tree=initial_tree, snapshot=None, source_run=source_run,
            )

    def start_work_item_from_snapshot(self, project_id: str, source_dir: str, text: str, *,
                                      title: str | None = None, max_cycles: int = 8,
                                      context_window: int = 32_000) -> tuple[str, str]:
        # 可信代码快照接入：源目录只读采集，事项在独立工作区开始，源目录不被改写
        _require_text("text", text)
        if not isinstance(source_dir, str) or not source_dir.strip():
            raise ValueError("source_dir must be a non-empty string")
        with self._lock:
            self._writable(project_id)
            self.settle_pending(project_id)
            project = self.projection(project_id)
            work_item_id, run_id = new_id("wi"), new_id("run")
            tree, snapshot = ingest_snapshot(source_dir, self.artifacts, run_id)
            return self._emit_work_item(
                project, text, title=title, max_cycles=max_cycles, context_window=context_window,
                baseline=None, initial_tree=tree, snapshot=snapshot, source_run=None,
                work_item_id=work_item_id, run_id=run_id,
            )

    def _emit_work_item(self, project: ProjectProjection, text: str, *, title: str | None,
                        max_cycles: int, context_window: int, baseline: dict[str, Any] | None,
                        initial_tree: Any, snapshot: dict[str, Any] | None,
                        source_run: Any, work_item_id: str | None = None,
                        run_id: str | None = None) -> tuple[str, str]:
        if title is not None and (not isinstance(title, str) or not title.strip()):
            raise ValueError("title must be a non-empty string when given")
        title = work_item_title(text) if title is None else title
        department_prompts = {department: project.prompt_configs[department].text for department in DEPARTMENTS}
        prompt_config_versions = {department: project.prompt_configs[department].version for department in DEPARTMENTS}
        # 登记命令在事项创建时冻结：之后项目再改注册表，不影响已创建事项的执行依据
        frozen_commands = {name: config.frozen() for name, config in project.commands.items()}
        command_versions = {name: config.version for name, config in project.commands.items()}
        context_text = project_context_text(project, title, source_run)
        work_item_id, run_id = work_item_id or new_id("wi"), run_id or new_id("run")
        # 项目上下文是该 run 的模型输入，按 run 作用域存放；内核创建 run 时会写出同一份工件。
        context_ref = self.artifacts.put(run_id, "project_context", context_text, media_type="text/markdown")
        self.store.append_project(project.project_id, ProjectEventType.WORK_ITEM_CREATED, {
            "work_item_id": work_item_id, "title": title, "text": text, "run_id": run_id, "baseline": baseline,
            "snapshot": snapshot,
            "project_context_ref": asdict(context_ref), "prompt_config_versions": prompt_config_versions,
            "command_versions": command_versions,
            "max_cycles": max_cycles, "context_window": context_window,
        })
        try:
            self.orchestrator.create_run(
                text, run_id=run_id, max_cycles=max_cycles, context_window=context_window,
                project_id=project.project_id, work_item_id=work_item_id, baseline=baseline, initial_tree=initial_tree,
                code_snapshot=snapshot,
                project_context=context_text, department_prompts=department_prompts,
                prompt_config_versions=prompt_config_versions,
                registered_commands=frozen_commands, command_versions=command_versions,
            )
        except Exception as exc:
            self.store.append_project(project.project_id, ProjectEventType.WORK_ITEM_START_FAILED, {
                "work_item_id": work_item_id, "run_id": run_id, "error": str(exc) or type(exc).__name__,
            })
            raise
        return work_item_id, run_id

    # 结算

    def settle(self, run_id: str) -> ProjectEvent | None:
        """幂等：run 非 DONE、不属于事项或已结算时无事件。"""
        with self._lock:
            try:
                run = project_run(self.store, run_id)
            except RunNotFoundError:
                return None
            if run.project_id is None or run.work_item_id is None:
                return None
            return self._settle_run(self.projection(run.project_id), run)

    def settle_pending(self, project_id: str) -> list[ProjectEvent]:
        """补跑结算：覆盖进程在 RUN_DONE 与结算之间中断的情形。"""
        with self._lock:
            project = self.projection(project_id)
            written: list[ProjectEvent] = []
            for item in project.work_items:
                if item.status != "released_unsettled":
                    continue
                event = self._settle_run(project, project_run(self.store, item.run_id))
                if event is not None:
                    written.append(event)
                    project = self.projection(project_id)
            return written

    def _settle_run(self, project: ProjectProjection, run: RunProjection) -> ProjectEvent | None:
        if run.phase != "DONE":
            return None
        if any(item.run_id == run.run_id for item in project.adoptions) or any(item.run_id == run.run_id for item in project.held):
            return None
        item = project.work_item_for_run(run.run_id)
        if item is None or item.work_item_id != run.work_item_id:
            return None
        if not run.delivery_specs:
            return None
        delivery = run.delivery_specs[-1]
        release = next((review for review in reversed(run.reviews) if review.verdict == "release"), None)
        if release is None:
            return None
        expected = None if item.baseline is None else item.baseline["adoption_id"]
        current = None if project.current_adoption is None else project.current_adoption.adoption_id
        if expected != current:
            return self.store.append_project(project.project_id, ProjectEventType.ADOPTION_HELD, {
                "work_item_id": item.work_item_id, "run_id": run.run_id,
                "delivery_event_id": delivery.created_event_id, "code_tree_digest": delivery.code_tree_digest,
                "reason": "baseline_changed", "expected_adoption_id": expected, "current_adoption_id": current,
            })
        return self.store.append_project(project.project_id, ProjectEventType.DELIVERABLE_ADOPTED, {
            "adoption_id": new_id("adopt"), "work_item_id": item.work_item_id, "run_id": run.run_id,
            "delivery_event_id": delivery.created_event_id, "qa_event_id": release.created_event_id,
            "tree_ref": asdict(delivery.tree_ref), "code_tree_digest": delivery.code_tree_digest,
            "summary": delivery.summary, "files": list(delivery.files), "check_names": list(delivery.check_names),
            "known_risks": list(delivery.known_risks), "previous_adoption_id": current,
        })

    # 部门 Prompt 项目配置

    def configure_prompt(self, project_id: str, department: str, text: str, base_version: int) -> dict[str, Any]:
        if department not in DEPARTMENTS:
            raise ValueError("unknown department")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("prompt text must be a non-empty string")
        if type(base_version) is not int or base_version < 0:
            raise ValueError("base_version must be a non-negative integer")
        with self._lock:
            project = self._writable(project_id)
            current = project.prompt_configs[department]
            if base_version != current.version:
                raise PromptConfigConflict(_prompt_view(current))
            if text == current.text:
                return {**_prompt_view(current), "unchanged": True}
            ref = save_department_prompt(self.artifacts, project_id, department, text)
            self.store.append_project(project_id, ProjectEventType.DEPARTMENT_PROMPT_CONFIGURED, {
                "department": department, "version": current.version + 1, "text": text,
                "prompt_ref": asdict(ref), "base_version": base_version,
            })
            return {**self.read_prompt(project_id, department), "unchanged": False}

    # 项目登记命令（3.2A 本地命令：只有登记的命令与参数范围可以执行）

    def configure_command(self, project_id: str, name: str, argv: list[str], *,
                          args: list[str] | None = None, timeout_sec: int | None = None,
                          output_limit: int | None = None, base_version: int = 0) -> dict[str, Any]:
        if type(base_version) is not int or base_version < 0:
            raise ValueError("base_version must be a non-negative integer")
        with self._lock:
            project = self._writable(project_id)
            current = project.commands.get(name)
            current_version = 0 if current is None else current.version
            if base_version != current_version:
                raise CommandConfigConflict({} if current is None else _command_view(current))
            normalized = validate_registered_command(name, {
                "argv": argv, "args": [] if args is None else args,
                **({} if timeout_sec is None else {"timeout_sec": timeout_sec}),
                **({} if output_limit is None else {"output_limit": output_limit}),
            })
            if current is not None and current.frozen() == normalized:
                return {**_command_view(current), "unchanged": True}
            self.store.append_project(project_id, ProjectEventType.COMMAND_CONFIGURED, {
                "name": name, "version": current_version + 1, **normalized, "base_version": base_version,
            })
            return {**self.read_command(project_id, name), "unchanged": False}

    # 材料（D-H：无活跃事项时记录原文）

    def record_material(self, project_id: str, text: str, *, department: str | None = None) -> str:
        _require_text("text", text)
        if department is not None and department not in DEPARTMENTS:
            raise ValueError("unknown department")
        with self._lock:
            project = self._writable(project_id)
            _reject_in_progress(project)
            ref = save_text_material(self.artifacts, project_id, "project_material", text)
            material_id = new_id("material")
            self.store.append_project(project_id, ProjectEventType.MATERIAL_RECORDED, {
                "material_id": material_id, "text": text, "material_ref": asdict(ref), "department": department,
            })
            return material_id

    def _writable(self, project_id: str) -> ProjectProjection:
        project = self.projection(project_id)
        if project.archived:
            raise ProjectArchivedError(f"project is archived: {project_id}")
        return project


def _reject_in_progress(project: ProjectProjection) -> None:
    if any(item.status == "in_progress" for item in project.work_items):
        raise WorkItemInProgressError(f"work item in progress: {project.project_id}")


def _prompt_view(config: PromptConfig) -> dict[str, Any]:
    return {
        "department": config.department,
        "text": config.text,
        "default_text": DEFAULT_PROMPTS[config.department],
        "version": config.version,
        "updated_at": config.updated_at,
        "source": config.source,
    }


def _command_view(config: RegisteredCommand) -> dict[str, Any]:
    return {
        "name": config.name,
        "argv": list(config.argv),
        "args": list(config.args),
        "timeout_sec": config.timeout_sec,
        "output_limit": config.output_limit,
        "version": config.version,
        "updated_at": config.updated_at,
    }


def _require_text(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
