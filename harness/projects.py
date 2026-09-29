# 项目层：登记、事项创建、采纳结算、继承恢复、部门 Prompt 项目配置、项目材料与项目读模型。
# 只通过 Orchestrator.create_run 与运行内核交互，且只在事项创建时；只读 run 投影（project_run）与 run 工件，
# 不生成运行事实、不改 run 流、不调用模型。项目事件经过写入口追加到项目流。

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any

from .artifacts import ArtifactStore
from .definitions import DEFINITIONS
from .department_prompts import save_department_prompt
from .event_store import Command, EventStore, project_stream
from .materials import save_text_material
from .models import (
    Adoption,
    ArtifactRef,
    DEPARTMENTS,
    Event,
    EventType,
    HeldCandidate,
    ProjectEvent,
    ProjectEventType,
    ProjectProjection,
    PromptConfig,
    RegisteredCommand,
    RunProjection,
    SourceDirectory,
    TERMINAL_PHASES,
    WorkItem,
    department_for_phase,
    new_id,
)
from .projection import RunNotFoundError, project_run, saved_project
from .write_path import NewProjectEvent, Transaction, WritePath
from .snapshot import ingest_snapshot
from .tools import validate_registered_command
from .streams import PRIORITY_UPGRADE_RESTART, PRIORITY_USER
from .tree_archive import load_tree

TITLE_LIMIT = 40
RECENT_LIMIT = 20
RECENT_RUN_EVENTS = frozenset({EventType.TRANSITION, EventType.RUN_DONE, EventType.RUN_FAILED, EventType.RUN_PAUSED})
REWORK_VERDICTS = frozenset({"rework_product", "rework_engineering"})


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


class SourceDirectoryConflict(Exception):
    """所编辑的源目录登记版本已过期；`current` 是该项目当前源目录登记的读取体。"""
    def __init__(self, current: dict[str, Any]) -> None:
        super().__init__("source directory changed since base_version")
        self.current = current


def project_projection(store: EventStore, artifacts: ArtifactStore, project_id: str, *,
                       include_history: bool = True) -> ProjectProjection:
    # 项目的读取模型：保存的项目投影，加上没有配置过的部门的默认 Prompt，以及由所属 run 的投影派生的事项状态。
    # include_history 为假时不再读取所属 run 的事件历史（交接与返工记录）：应用层的查询用读取模型提供它们
    state = saved_project(store, project_id)
    if state is None:
        raise ProjectNotFoundError(project_id)
    return _compose(store, state, include_history=include_history)


def _compose(store: EventStore, state: ProjectProjection, *, include_history: bool = True) -> ProjectProjection:
    # 在给出的项目投影上补齐默认 Prompt 与事项状态
    project_id = state.project_id
    _default_prompts(state)
    adopted = {item.run_id: item for item in state.adoptions}
    held = {item.run_id: item for item in state.held}
    for item in state.work_items:
        _derive_work_item(store, item, adopted, held, project_id, include_history=include_history)
    state.active_work_item_id = next((item.work_item_id for item in state.work_items if item.status == "in_progress"), None)
    return state


def _default_prompts(state: ProjectProjection) -> ProjectProjection:
    # 没有配置过的部门使用默认 Prompt
    for department in DEPARTMENTS:
        state.prompt_configs.setdefault(department, PromptConfig(
            department=department, version=0, text=DEFINITIONS.role(department).prompt, source="default",
        ))
    return state


def _derive_work_item(store: EventStore, item: WorkItem, adopted: dict[str, Adoption],
                      held: dict[str, HeldCandidate], project_id: str, *, include_history: bool = True) -> None:
    try:
        run = project_run(store, item.run_id)
    except RunNotFoundError:
        item.status = "not_started"
        return
    if run.project_id != project_id or run.work_item_id != item.work_item_id:
        item.status = "not_started"
        return
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
    if include_history:
        events = store.list_events(item.run_id)
        handoffs = work_item_handoffs(events)
        item.last_handoff = handoffs[-1] if handoffs else None
        item.rework = [
            {"verdict": event.payload["verdict"], "seq": event.stream_version, "at": event.created_at,
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
        {"from": event.state_before, "to": event.state_after, "seq": event.stream_version, "at": event.created_at}
        for event in events if event.type == EventType.TRANSITION
    ]


def project_event_card(event: ProjectEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "project_id": event.project_id,
        "position": event.position,
        "seq": event.stream_version,
        "type": event.type,
        "created_at": event.created_at,
        "work_item_id": event.payload.get("work_item_id"),
        "run_id": event.payload.get("run_id"),
        "payload": event.payload,
    }


def project_overview(store: EventStore, project: ProjectProjection) -> dict[str, Any]:
    """概览：目标、当前采用成果、待决、近期动态（项目事件与所属 run 的关键事件按全局位置倒序）。"""
    recent = [
        {"kind": "project", "type": event.type, "at": event.created_at, "position": event.position,
         "event_id": event.event_id, "work_item_id": event.payload.get("work_item_id"),
         "run_id": event.payload.get("run_id"), "summary": _project_event_summary(event)}
        for event in store.list_project_events(project.project_id)
    ]
    for item in project.work_items:
        for event in store.list_events(item.run_id):
            if event.type not in RECENT_RUN_EVENTS:
                continue
            recent.append({
                "kind": "loop", "type": event.type, "at": event.created_at, "position": event.position,
                "event_id": event.event_id, "work_item_id": item.work_item_id, "run_id": item.run_id,
                "summary": (f"{event.state_before}->{event.state_after}" if event.type == EventType.TRANSITION
                            else event.stop_reason or event.type),
            })
    recent.sort(key=lambda entry: entry["position"], reverse=True)
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
    # 项目的命令：每一次「读取项目投影、判断、追加」是写入口在项目流上的一个事务
    def __init__(self, store: EventStore, writes: WritePath, artifacts: ArtifactStore, orchestrator: Any) -> None:
        self.store = store
        self.writes = writes
        self.artifacts = artifacts
        self.orchestrator = orchestrator
        # 每个项目正在开始的事项：事项已经登记、它的 run 还没有创建时，事项的状态看起来是没有开始，
        # 归档与记录材料按这里判断有事项进行中
        self._starting: dict[str, set[object]] = {}

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

    def register(self, name: str, goal: str, *, command: Command | None = None) -> str:
        # command 是引起登记的命令：同一命令身份已经登记时写入口在判断之前拒绝（DuplicateCommand、CommandIdReused），
        # 不保存目标原文，也不新建项目
        _require_text("name", name)
        _require_text("goal", goal)
        project_id = new_id("proj")

        def register(transaction: Transaction) -> None:
            goal_ref = self.artifacts.put(project_id, "project_goal", goal, media_type="text/markdown")
            transaction.append(NewProjectEvent(ProjectEventType.PROJECT_REGISTERED, {
                "name": name, "goal": goal, "goal_ref": asdict(goal_ref), "source": "idea",
            }))

        self.writes.transact(project_stream(project_id), register, expected_version=0, command=command)
        return project_id

    def rename(self, project_id: str, name: str, *, command: Command | None = None) -> None:
        _require_text("name", name)

        def rename(transaction: Transaction) -> None:
            self._writable_in(transaction, project_id)
            transaction.append(NewProjectEvent(ProjectEventType.PROJECT_RENAMED, {"name": name}))

        self.writes.transact(project_stream(project_id), rename, command=command)

    def pin(self, project_id: str, pinned: bool, *, command: Command | None = None) -> None:
        if not isinstance(pinned, bool):
            raise ValueError("pinned must be a boolean")

        def pin(transaction: Transaction) -> None:
            self._writable_in(transaction, project_id)
            transaction.append(NewProjectEvent(ProjectEventType.PROJECT_PINNED, {"pinned": pinned}))

        self.writes.transact(project_stream(project_id), pin, command=command)

    def archive(self, project_id: str, *, command: Command | None = None) -> None:
        def archive(transaction: Transaction) -> None:
            if self._saved_in(transaction, project_id).archived:
                return
            self._reject_in_progress(transaction, project_id)
            transaction.append(NewProjectEvent(ProjectEventType.PROJECT_ARCHIVED))

        self.writes.transact(project_stream(project_id), archive, command=command)

    def restore(self, project_id: str, *, command: Command | None = None) -> None:
        def restore(transaction: Transaction) -> None:
            if self._saved_in(transaction, project_id).archived:
                transaction.append(NewProjectEvent(ProjectEventType.PROJECT_RESTORED))

        self.writes.transact(project_stream(project_id), restore, command=command)

    # 事项

    def start_work_item(self, project_id: str, text: str, *, title: str | None = None,
                        max_cycles: int = DEFINITIONS.limits.max_cycles,
                        run_time_limit_sec: int = DEFINITIONS.limits.run_time_limit_sec,
                        context_window: int = 32_000, command: Command | None = None) -> tuple[str, str]:
        _require_text("text", text)
        _require_title(title)
        self._writable(project_id)
        self.settle_pending(project_id)
        work_item_id, run_id = new_id("wi"), new_id("run")

        def create(transaction: Transaction) -> _NewWorkItem:
            # 事项的基线、Prompt 与登记命令取自事务中的项目投影
            project = _default_prompts(deepcopy(self._writable_in(transaction, project_id)))
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
            return self._work_item_created(
                transaction, project, text, title=title, max_cycles=max_cycles,
                run_time_limit_sec=run_time_limit_sec, context_window=context_window,
                baseline=baseline, initial_tree=initial_tree, snapshot=None, source_run=source_run,
                work_item_id=work_item_id, run_id=run_id,
            )

        return self._start(project_id, create, command=command)

    def start_work_item_from_snapshot(self, project_id: str, source_dir: str, text: str, *,
                                      title: str | None = None,
                                      max_cycles: int = DEFINITIONS.limits.max_cycles,
                                      run_time_limit_sec: int = DEFINITIONS.limits.run_time_limit_sec,
                                      context_window: int = 32_000) -> tuple[str, str]:
        # 可信代码快照接入：源目录只读采集，事项在独立工作区开始，源目录不被改写
        _require_text("text", text)
        _require_title(title)
        if not isinstance(source_dir, str) or not source_dir.strip():
            raise ValueError("source_dir must be a non-empty string")
        self._writable(project_id)
        self.settle_pending(project_id)
        work_item_id, run_id = new_id("wi"), new_id("run")
        tree, snapshot = ingest_snapshot(source_dir, self.artifacts, run_id)

        def create(transaction: Transaction) -> _NewWorkItem:
            project = _default_prompts(deepcopy(self._writable_in(transaction, project_id)))
            return self._work_item_created(
                transaction, project, text, title=title, max_cycles=max_cycles,
                run_time_limit_sec=run_time_limit_sec, context_window=context_window,
                baseline=None, initial_tree=tree, snapshot=snapshot, source_run=None,
                work_item_id=work_item_id, run_id=run_id,
            )

        return self._start(project_id, create)

    def _work_item_created(self, transaction: Transaction, project: ProjectProjection, text: str, *,
                           title: str | None, max_cycles: int, run_time_limit_sec: int, context_window: int,
                           baseline: dict[str, Any] | None, initial_tree: Any, snapshot: dict[str, Any] | None,
                           source_run: Any, work_item_id: str, run_id: str,
                           priority: str = PRIORITY_USER) -> _NewWorkItem:
        # 在事务中追加 work_item_created，交回创建 run 需要的内容
        title = work_item_title(text) if title is None else title
        department_prompts = {department: project.prompt_configs[department].text for department in DEPARTMENTS}
        prompt_config_versions = {department: project.prompt_configs[department].version for department in DEPARTMENTS}
        # 登记命令在事项创建时冻结：之后项目再改注册表，不影响已创建事项的执行依据
        frozen_commands = {name: config.frozen() for name, config in project.commands.items()}
        command_versions = {name: config.version for name, config in project.commands.items()}
        context_text = project_context_text(project, title, source_run)
        # 项目上下文是该 run 的模型输入，按 run 作用域存放；内核创建 run 时会写出同一份工件。
        context_ref = self.artifacts.put(run_id, "project_context", context_text, media_type="text/markdown")
        transaction.append(NewProjectEvent(ProjectEventType.WORK_ITEM_CREATED, {
            "work_item_id": work_item_id, "title": title, "text": text, "run_id": run_id, "baseline": baseline,
            "snapshot": snapshot,
            "project_context_ref": asdict(context_ref), "prompt_config_versions": prompt_config_versions,
            "command_versions": command_versions,
            "max_cycles": max_cycles, "run_time_limit_sec": run_time_limit_sec, "context_window": context_window,
            "definitions_version": DEFINITIONS.version,
            # 事项在队列中的优先级：因升级重新开始的事项排在队列最前面（顺序由 3.4A 的 #19 实现）
            "priority": priority,
        }))
        return _NewWorkItem(
            work_item_id=work_item_id, run_id=run_id, text=text,
            run_options=dict(
                max_cycles=max_cycles, run_time_limit_sec=run_time_limit_sec, context_window=context_window,
                project_id=project.project_id, work_item_id=work_item_id, baseline=baseline,
                initial_tree=initial_tree, code_snapshot=snapshot, project_context=context_text,
                department_prompts=department_prompts, prompt_config_versions=prompt_config_versions,
                registered_commands=frozen_commands, command_versions=command_versions,
            ),
        )

    def _start(self, project_id: str, create: Callable[[Transaction], _NewWorkItem], *,
               command: Command | None = None) -> tuple[str, str]:
        # 在项目流登记事项，再创建它的 run；创建失败时在项目流记下失败的原因。
        # 从登记之前到 run 创建完成，这个项目算作有事项正在开始
        token = object()
        self._starting.setdefault(project_id, set()).add(token)
        try:
            item = self.writes.transact(project_stream(project_id), create, command=command)
            try:
                self.orchestrator.create_run(item.text, run_id=item.run_id, **item.run_options)
            except Exception as exc:
                self.writes.append(project_stream(project_id), NewProjectEvent(
                    ProjectEventType.WORK_ITEM_START_FAILED,
                    {"work_item_id": item.work_item_id, "run_id": item.run_id, "error": str(exc) or type(exc).__name__},
                ))
                raise
        finally:
            self._starting[project_id].discard(token)
        return item.work_item_id, item.run_id

    def restart_work_item_for_upgrade(self, run_id: str, *, command: Command | None = None) -> tuple[str, str] | None:
        # 因升级重新开始（ADR-0019，工单 #126）：run 事件版本与当前不同的未结束 run 由流程编排记为因升级停止，
        # 这里在项目流上以项目当前的采纳成果为基线为同一个事项登记新的 run，并记下「因升级重新开始」的优先级。
        # 没有对应的事项时为空；项目还没有采纳成果时新 run 没有基线
        try:
            run = project_run(self.store, run_id)
        except RunNotFoundError:
            return None
        if run.project_id is None or run.work_item_id is None:
            return None

        def restart(transaction: Transaction) -> _NewWorkItem | None:
            project = _default_prompts(deepcopy(self._writable_in(transaction, run.project_id)))
            item = project.work_item_for_run(run_id)
            if item is None:
                return None
            baseline, initial_tree, source_run = None, None, None
            adoption = project.current_adoption
            if adoption is not None:
                source = project_run(self.store, adoption.run_id)
                if source.project_id != run.project_id:
                    raise ValueError("source run does not belong to this project")
                baseline = {
                    "adoption_id": adoption.adoption_id, "source_run_id": adoption.run_id,
                    "delivery_event_id": adoption.delivery_event_id, "tree_ref": adoption.tree_ref,
                    "code_tree_digest": adoption.code_tree_digest,
                }
                initial_tree = load_tree(self.artifacts, adoption.run_id, ArtifactRef(**adoption.tree_ref))
                if initial_tree.digest != adoption.code_tree_digest:
                    raise ValueError("archived tree does not match the adopted deliverable digest")
                source_run = source
            return self._work_item_created(
                transaction, project, item.text, title=item.title, max_cycles=item.max_cycles,
                run_time_limit_sec=item.run_time_limit_sec, context_window=item.context_window,
                baseline=baseline, initial_tree=initial_tree, snapshot=None, source_run=source_run,
                work_item_id=new_id("wi"), run_id=new_id("run"), priority=PRIORITY_UPGRADE_RESTART,
            )

        created = self.writes.transact(project_stream(run.project_id), restart, command=command)
        if created is None:
            return None
        try:
            self.orchestrator.create_run(created.text, run_id=created.run_id, **created.run_options)
        except Exception as exc:
            self.writes.append(project_stream(run.project_id), NewProjectEvent(
                ProjectEventType.WORK_ITEM_START_FAILED,
                {"work_item_id": created.work_item_id, "run_id": created.run_id,
                 "error": str(exc) or type(exc).__name__},
            ))
            raise
        return created.work_item_id, created.run_id

    # 结算

    def settle(self, run_id: str) -> ProjectEvent | None:
        """幂等：run 非 DONE、不属于事项或已结算时无事件。"""
        try:
            run = project_run(self.store, run_id)
        except RunNotFoundError:
            return None
        if run.project_id is None or run.work_item_id is None:
            return None
        return self.writes.transact(project_stream(run.project_id),
                                    lambda transaction: self._settle_run(transaction, run))

    def settle_pending(self, project_id: str) -> list[ProjectEvent]:
        """补跑结算：覆盖进程在 RUN_DONE 与结算之间中断的情形。"""
        written: list[ProjectEvent] = []
        for item in self.projection(project_id).work_items:
            if item.status != "released_unsettled":
                continue
            event = self.settle(item.run_id)
            if event is not None:
                written.append(event)
        return written

    def settle_pending_on_startup(self) -> list[ProjectEvent]:
        """服务启动时由流程编排补做未完成的结算（应用层与接口层设计说明第 7.2 节）。"""
        written: list[ProjectEvent] = []
        for project_id in self.store.list_project_ids():
            written.extend(self.settle_pending(project_id))
        return written

    def starting(self) -> bool:
        # 有事项正在开始（已经登记、run 还没有创建）时占用执行槽位
        return any(items for items in self._starting.values())

    @staticmethod
    def _settle_run(transaction: Transaction, run: RunProjection) -> ProjectEvent | None:
        project = transaction.projection
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
            return transaction.append(NewProjectEvent(ProjectEventType.ADOPTION_HELD, {
                "work_item_id": item.work_item_id, "run_id": run.run_id,
                "delivery_event_id": delivery.created_event_id, "code_tree_digest": delivery.code_tree_digest,
                "reason": "baseline_changed", "expected_adoption_id": expected, "current_adoption_id": current,
            }))[0]
        return transaction.append(NewProjectEvent(ProjectEventType.DELIVERABLE_ADOPTED, {
            "adoption_id": new_id("adopt"), "work_item_id": item.work_item_id, "run_id": run.run_id,
            "delivery_event_id": delivery.created_event_id, "qa_event_id": release.created_event_id,
            "tree_ref": asdict(delivery.tree_ref), "code_tree_digest": delivery.code_tree_digest,
            "summary": delivery.summary, "files": list(delivery.files), "check_names": list(delivery.check_names),
            "known_risks": list(delivery.known_risks), "previous_adoption_id": current,
        }))[0]

    # 部门 Prompt 项目配置

    def configure_prompt(self, project_id: str, department: str, text: str, base_version: int, *,
                         command: Command | None = None) -> dict[str, Any]:
        if department not in DEPARTMENTS:
            raise ValueError("unknown department")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("prompt text must be a non-empty string")
        if type(base_version) is not int or base_version < 0:
            raise ValueError("base_version must be a non-negative integer")

        def configure(transaction: Transaction) -> dict[str, Any] | None:
            current = _default_prompts(deepcopy(self._writable_in(transaction, project_id))).prompt_configs[department]
            if base_version != current.version:
                raise PromptConfigConflict(_prompt_view(current))
            if text == current.text:
                return {**_prompt_view(current), "unchanged": True}
            ref = save_department_prompt(self.artifacts, project_id, department, text)
            transaction.append(NewProjectEvent(ProjectEventType.DEPARTMENT_PROMPT_CONFIGURED, {
                "department": department, "version": current.version + 1, "text": text,
                "prompt_ref": asdict(ref), "base_version": base_version,
            }))
            return None

        unchanged = self.writes.transact(project_stream(project_id), configure, command=command)
        return unchanged or {**self.read_prompt(project_id, department), "unchanged": False}

    # 项目登记命令（3.2A 本地命令：只有登记的命令与参数范围可以执行）

    def configure_command(self, project_id: str, name: str, argv: list[str], *,
                          args: list[str] | None = None, timeout_sec: int | None = None,
                          output_limit: int | None = None, base_version: int = 0,
                          command: Command | None = None) -> dict[str, Any]:
        if type(base_version) is not int or base_version < 0:
            raise ValueError("base_version must be a non-negative integer")

        def configure(transaction: Transaction) -> dict[str, Any] | None:
            current = self._writable_in(transaction, project_id).commands.get(name)
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
            transaction.append(NewProjectEvent(ProjectEventType.COMMAND_CONFIGURED, {
                "name": name, "version": current_version + 1, **normalized, "base_version": base_version,
            }))
            return None

        unchanged = self.writes.transact(project_stream(project_id), configure, command=command)
        return unchanged or {**self.read_command(project_id, name), "unchanged": False}

    # 源目录登记（#74）

    def configure_source_directory(self, project_id: str, name: str, path: str, *,
                                   base_version: int, command: Command | None = None) -> dict[str, Any]:
        # 登记与修改本项目的源目录：名称是登记名，路径是控制主机上的路径；
        # 基准版本是该项目源目录登记的版本（初次登记为 0），不相等时拒绝并返回当前版本
        _require_text("name", name)
        _require_text("path", path)
        if type(base_version) is not int or base_version < 0:
            raise ValueError("base_version must be a non-negative integer")

        def configure(transaction: Transaction) -> None:
            current = self._writable_in(transaction, project_id).source_directories.get(name)
            current_version = 0 if current is None else current.version
            if base_version != current_version:
                raise SourceDirectoryConflict({} if current is None else _source_directory_view(current))
            transaction.append(NewProjectEvent(ProjectEventType.SOURCE_DIRECTORY_CONFIGURED, {
                "name": name, "path": path, "version": current_version + 1, "base_version": base_version,
            }))

        self.writes.transact(project_stream(project_id), configure, command=command)
        return self.read_source_directory(project_id, name)

    def read_source_directory(self, project_id: str, name: str) -> dict[str, Any]:
        directory = self.projection(project_id).source_directories.get(name)
        if directory is None:
            raise ValueError(f"unknown source directory: {name}")
        return _source_directory_view(directory)

    # 材料（D-H：无活跃事项时记录原文）

    def record_material(self, project_id: str, text: str, *, department: str | None = None,
                        command: Command | None = None) -> str:
        _require_text("text", text)
        if department is not None and department not in DEPARTMENTS:
            raise ValueError("unknown department")

        def record(transaction: Transaction) -> str:
            self._writable_in(transaction, project_id)
            self._reject_in_progress(transaction, project_id)
            ref = save_text_material(self.artifacts, project_id, "project_material", text)
            material_id = new_id("material")
            transaction.append(NewProjectEvent(ProjectEventType.MATERIAL_RECORDED, {
                "material_id": material_id, "text": text, "material_ref": asdict(ref), "department": department,
            }))
            return material_id

        return self.writes.transact(project_stream(project_id), record, command=command)

    def _writable(self, project_id: str) -> ProjectProjection:
        project = self.projection(project_id)
        if project.archived:
            raise ProjectArchivedError(f"project is archived: {project_id}")
        return project

    @staticmethod
    def _saved_in(transaction: Transaction, project_id: str) -> ProjectProjection:
        # 事务中保存的项目投影（只有项目事件折叠出的内容）；不要修改它
        if transaction.version == 0:
            raise ProjectNotFoundError(project_id)
        return transaction.projection

    def _writable_in(self, transaction: Transaction, project_id: str) -> ProjectProjection:
        project = self._saved_in(transaction, project_id)
        if project.archived:
            raise ProjectArchivedError(f"project is archived: {project_id}")
        return project

    def _reject_in_progress(self, transaction: Transaction, project_id: str) -> None:
        # 有事项进行中（包括正在开始、run 还没有创建的事项）时拒绝；事项状态由所属 run 的投影派生
        project = _compose(self.store, deepcopy(self._saved_in(transaction, project_id)))
        if self._starting.get(project_id) or any(item.status == "in_progress" for item in project.work_items):
            raise WorkItemInProgressError(f"work item in progress: {project_id}")


@dataclass(frozen=True)
class _NewWorkItem:
    # 已经在项目流登记的事项与创建它的 run 需要的内容
    work_item_id: str
    run_id: str
    text: str
    run_options: dict[str, Any]


def _require_title(title: str | None) -> None:
    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise ValueError("title must be a non-empty string when given")


def _prompt_view(config: PromptConfig) -> dict[str, Any]:
    return {
        "department": config.department,
        "text": config.text,
        "default_text": DEFINITIONS.role(config.department).prompt,
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


def _source_directory_view(config: SourceDirectory) -> dict[str, Any]:
    return {
        "name": config.name,
        "path": config.path,
        "version": config.version,
        "updated_at": config.updated_at,
    }


def _require_text(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
