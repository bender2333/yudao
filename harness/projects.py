# 项目层：登记、事项创建、采纳结算、继承恢复、部门 Prompt 项目配置、项目材料与项目读模型。
# 只通过 Orchestrator.create_run 与运行内核交互，且只在事项创建时；只读 run 投影（project_run）与 run 工件，
# 不生成运行事实、不改 run 流、不调用模型。项目事件经过写入口追加到项目流。

from __future__ import annotations

from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any

from .artifacts import ArtifactStore
from .definitions import DEFINITIONS
from .department_prompts import save_department_prompt
from .event_store import Command, EventStore, catalog_stream, project_stream, run_stream
from .materials import save_text_material
from .models import (
    ArtifactRef,
    DEPARTMENTS,
    Event,
    EventType,
    ProjectEvent,
    ProjectEventType,
    RunProjection,
    TERMINAL_STATUSES,
    new_id,
)
from .project_projection import (
    Adoption,
    DepartmentSetting,
    HeldCandidate,
    InitialPrdCandidate,
    ProjectProjection,
    SourceDirectory,
    WorkItem,
    replay_project,
    saved_project,
)
from .projection import RunNotFoundError, project_run, replay_run
from .providers.selection import ModelSelection
from .write_path import NewProjectEvent, Transaction, WritePath
from .snapshot import ingest_snapshot
from .decisions import INITIAL_PRD, KERNEL_MODIFICATION
from .path_guard import changed_paths, kernel_diff, kernel_hits, kernel_manifest_paths
from .streams import DRAIN_FINISHED, DRAIN_STARTED, PRIORITY_UPGRADE_RESTART, PRIORITY_USER, classify_startup_runs, last_drain_event
from .tree_archive import artifact_run, load_tree

TITLE_LIMIT = 40
RECENT_LIMIT = 20
RECENT_RUN_EVENTS = frozenset({EventType.DELIVERY_ACCEPTED, EventType.QA_SUBMITTED, EventType.RUN_DONE,
                               EventType.RUN_FAILED, EventType.RUN_PAUSED})
REWORK_VERDICTS = frozenset({"rework_engineering"})
# 用户自己让事项停下的两种停止原因：结束事件里写的是这次决定（"run cancelled"，
# "run cancelled by user command"），不是让事项自己停下的错误，因此不带停止说明（工单 #1162）
USER_STOP_REASONS = frozenset({"cancelled", "user_cancelled"})


class ProjectNotFoundError(KeyError):
    pass


class ProjectArchivedError(ValueError):
    """归档项目只读：写命令被拒绝。"""


class WorkItemInProgressError(ValueError):
    """有进行中事项时不能归档或记录材料。"""

class OnboardingNotAllowedError(ValueError):
    """重新开始建档不满足条件：项目不是接入已有项目建立的、已有基线或已有进行中的建档事项。"""

class SourceDirectoryNotFoundError(KeyError):
    """登记名对应的源目录不存在。"""

class DepartmentSettingConflict(Exception):
    """所编辑的项目部门设置版本已过期；`current` 是项目当前设置的读取体。"""
    def __init__(self, current: dict[str, Any]) -> None:
        super().__init__("department setting changed since base_version")
        self.current = current


class SourceDirectoryConflict(Exception):
    """所编辑的源目录登记版本已过期；`current` 是该项目当前源目录登记的读取体。"""
    def __init__(self, current: dict[str, Any]) -> None:
        super().__init__("source directory changed since base_version")
        self.current = current


def _adoption_payload(delivery: Any, release: Any, run: Any, item: WorkItem) -> dict[str, Any]:
    # 采纳交付的载荷（工单 #354）：照常采纳与批准以后采纳写的是同一份内容，由结算与被批准的请求共用
    return {
        "adoption_id": new_id("adopt"), "work_item_id": item.work_item_id, "run_id": run.run_id,
        "delivery_event_id": delivery.created_event_id, "qa_event_id": release.created_event_id,
        "tree_ref": asdict(delivery.tree_ref), "code_tree_digest": delivery.code_tree_digest,
        "summary": delivery.summary, "files": list(delivery.files), "check_names": list(delivery.check_names),
        "known_risks": list(delivery.known_risks),
        # 批准时按批准当时的当前采纳重写：请求可能等了很久，此刻的值才是对的
        "previous_adoption_id": None,
    }


def project_projection(store: EventStore, artifacts: ArtifactStore, project_id: str, *,
                       include_history: bool = True, through: int | None = None) -> ProjectProjection:
    # 项目的读取模型：保存的项目投影，加上没有配置过的部门的默认 Prompt，以及由所属 run 的投影派生的事项状态。
    # include_history 为假时不再读取所属 run 的事件历史（交接与返工记录）：应用层的查询用读取模型提供它们。
    # through 给出全局位置的上界时按位置读取：项目与所属 run 的投影都从事件重放到该位置（工单 #127）
    state = saved_project(store, project_id) if through is None else replay_project(store, project_id, through=through)
    if state is None:
        raise ProjectNotFoundError(project_id)
    return _compose(store, state, include_history=include_history, through=through)


def _compose(store: EventStore, state: ProjectProjection, *, include_history: bool = True,
             through: int | None = None) -> ProjectProjection:
    # 在给出的项目投影上补齐默认 Prompt 与事项状态
    project_id = state.project_id
    _default_settings(state)
    adopted = {item.run_id: item for item in state.adoptions}
    held = {item.run_id: item for item in state.held}
    awaiting, withdrawn = _initial_prd_requests(store, state.project_id, through)
    for item in state.work_items:
        _derive_work_item(store, item, adopted, held, project_id, include_history=include_history,
                          through=through, awaiting_initial_prd=item.work_item_id in awaiting,
                          withdrawn_initial_prd=item.work_item_id in withdrawn)
    state.active_work_item_id = next((item.work_item_id for item in state.work_items if item.status == "in_progress"), None)
    return state


def _initial_prd_requests(store: EventStore, project_id: str, through: int | None) -> tuple[set[str], set[str]]:
    # 建档事项在 initial_prd 请求上的两种状态（工单 #136，设计第 3.4 节）：
    # 还没有回答的请求所属的事项在等待确认（算作进行中）；被撤销的请求所属的事项已停止
    events = store.list_project_events(project_id, through_position=through)
    open_requests = {event.event_id: event for event in events
                     if event.type == ProjectEventType.PROJECT_DECISION_REQUESTED
                     and event.payload.get("kind") == INITIAL_PRD.name}
    withdrawn: set[str] = set()
    for event in events:
        if event.type == ProjectEventType.PROJECT_DECISION_ANSWERED:
            open_requests.pop(event.payload["decision_id"], None)
        if event.type == ProjectEventType.PROJECT_DECISION_WITHDRAWN:
            open_requests.pop(event.payload["decision_id"], None)
            withdrawn.add(event.payload["work_item_id"])
    return ({event.payload["work_item_id"] for event in open_requests.values()},
            {work_item_id for work_item_id in withdrawn
             if work_item_id not in {event.payload["work_item_id"] for event in open_requests.values()}})




def _default_settings(state: ProjectProjection) -> ProjectProjection:
    # 没有配置过的部门使用内置默认 Prompt（版本 0），模型与请求档位都跟随部门默认
    for department in DEPARTMENTS:
        state.department_settings.setdefault(department, DepartmentSetting(
            department=department, version=0, text=DEFINITIONS.role(department).prompt, source="default",
        ))
    return state


def _kept_delivery(store: EventStore, run: RunProjection, status: str, *,
                   through: int | None = None) -> dict[str, Any] | None:
    # 事项停止时已经收下的那一版交付：版本取自收下它的那份成果，时间取自收下它的那条事件的提交时间。
    # 只看停止的事项：放行完成的事项走正常的进度，不重复写这一句（工单 #1239）
    if status != "stopped":
        return None
    if through is not None:
        # 按位置读取：收下交付的那条事件也在位置之内才算
        accepted = [event for event in store.list_events(run.run_id, through_position=through)
                    if event.type == EventType.DELIVERY_ACCEPTED]
        if not accepted:
            return None
        return {"version": int(accepted[-1].payload["revision"]), "accepted_at": accepted[-1].created_at}
    if not run.delivery_specs:
        return None
    delivery = run.delivery_specs[-1]
    event = store.get_event(delivery.created_event_id)
    if event is None:
        return None
    return {"version": delivery.revision, "accepted_at": event.created_at}


def _derive_work_item(store: EventStore, item: WorkItem, adopted: dict[str, Adoption],
                      held: dict[str, HeldCandidate], project_id: str, *, include_history: bool = True,
                      through: int | None = None, awaiting_initial_prd: bool = False,
                      withdrawn_initial_prd: bool = False) -> None:
    try:
        run = project_run(store, item.run_id) if through is None else replay_run(store, item.run_id, through=through)
    except RunNotFoundError:
        item.status = "not_started"
        return
    if run.project_id != project_id or run.work_item_id != item.work_item_id:
        item.status = "not_started"
        return
    item.status = run.status
    item.stop_reason = run.stop_reason
    item.human_action = run.human_action
    item.cycle_count = run.cycle_count
    item.department = None if run.status in TERMINAL_STATUSES else run.active_department
    if run.run_id in adopted:
        item.status = "adopted"
        item.adoption_id = adopted[run.run_id].adoption_id
    elif run.run_id in held:
        item.status = "held"
    elif withdrawn_initial_prd:
        # 用户在等待确认时取消了这个建档事项：请求被撤销，事项已停止，项目保持没有基线（工单 #136）。
        # 停止原因写「用户已取消」，不抄 run 的结束原因——run 成功结束与事项被用户放弃是两件事（工单 #707）
        item.status = "stopped"
        item.stop_reason = "user_cancelled"
        item.human_action = DEFINITIONS.stop_reason("user_cancelled").human_action
    elif run.status == "done":
        # 建档 run 结束以后等待用户确认初始 PRD：事项还没有采纳成果，状态是等待确认（工单 #136）
        item.status = "awaiting_initial_prd" if awaiting_initial_prd else "released_unsettled"
    elif run.status in TERMINAL_STATUSES:
        item.status = "stopped"
    else:
        item.status = "in_progress"
    # 停止说明（工单 #1162）：停止的事项写让事项停下的那条错误的原文，取自事项结束的事件（run 投影的 error）；
    # 询问分支的失败原因不是事项结束的原因，留在询问记录里，不进这里。用户自己让事项停下不是错误，不写
    item.stop_note = (run.error if item.status == "stopped" and item.stop_reason not in USER_STOP_REASONS
                      else None)
    # 已收下的交付（工单 #1239）：事项停止时，把「这个 run 里已经收下一版交付」这件事写在停止说明旁边，
    # 否则页面上只有一句失败原因，看不出这件事已经有一份可用的交付。用户自己取消时也写，交付仍然在
    item.kept_delivery = _kept_delivery(store, run, item.status, through=through)
    if include_history:
        events = store.list_events(item.run_id, through_position=through)
        item.rework = [
            {"verdict": event.payload["verdict"], "seq": event.stream_version, "at": event.created_at,
             "summary": event.payload.get("rationale", "")}
            for event in events
            if event.type == EventType.QA_SUBMITTED and event.payload.get("verdict") in REWORK_VERDICTS
        ]
    if withdrawn_initial_prd:
        # 被放弃的事项也要有一句「接下来该做什么」：与取消的情形对齐（工单 #707）
        item.pending_question = item.human_action
    elif awaiting_initial_prd:
        item.pending_question = f"等待你确认第 {run.round} 轮的初始 PRD"
    elif run.status in TERMINAL_STATUSES:
        item.pending_question = run.human_action
    else:
        item.pending_question = run.waiting_reason


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
                "summary": event.stop_reason or event.type,
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
        or payload.get("error") or (payload.get("department") if event.type == ProjectEventType.DEPARTMENT_SETTINGS_CONFIGURED else None)
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
    elif adoption.prd_ref is not None:
        current = _onboarding_baseline(project, adoption)
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


def _onboarding_baseline(project: ProjectProjection, adoption: Adoption) -> str:
    # 建档采纳的基线（工单 #136，设计第 5 节）：已有项目的代码快照、文件数、git 提交、
    # 基线检查与现有缺陷；不逐个列出快照中的文件
    snapshot = adoption.snapshot or {}
    provenance = snapshot.get("provenance") or {}
    if provenance.get("commit"):
        origin = f"git 提交 {provenance['commit']}（分支 {provenance.get('branch') or '未知'}"
        origin += "，有未提交的修改）" if provenance.get("dirty") else "）"
    else:
        origin = "没有 git 仓库，快照采集时的目录内容"
    return "\n".join([
        f"建档基线：已有项目的代码快照（run {adoption.run_id}，采纳 {adoption.adoption_id}）",
        f"快照来源：{snapshot.get('source') or '未记录'}；{origin}",
        f"文件数：{len(adoption.files)}；digest {adoption.code_tree_digest}",
        f"基线检查：{_join(adoption.check_names)}",
        f"现有缺陷：{_join(adoption.known_risks)}",
        f"初始 PRD：{adoption.product_spec_hash}",
        f"本 run 工作区已从该快照的完整封存恢复。",
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
    def _limit_values(self, max_cycles: int | None, run_time_limit_sec: int | None) -> tuple[int, int]:
        # 事项的两个限额：调用方显式给出时按给出值，否则取参数现值（工单 #349）。
        # 运行中的 run 已经按创建时的限额冻结，之后改参数不影响它
        from . import parameters as parameter_values

        values = parameter_values.current_values(self.store)
        return (values["max_cycles"] if max_cycles is None else max_cycles,
                values["run_time_limit_sec"] if run_time_limit_sec is None else run_time_limit_sec)

    def onboarding_round_limit(self, project_id: str | None, run_time_limit_sec: int | None = None) -> int:
        # 建档事项的单轮上限（迭代底座 B3，工单 #351）：项目设置过时用它，否则用全局现值；
        # 调用方显式给出时按给出值
        from . import parameters as parameter_values

        if run_time_limit_sec is not None:
            return run_time_limit_sec
        return parameter_values.value_for_project(
            self.store, project_id, "onboarding.round_time_limit_sec")

    # 读

    def projection(self, project_id: str) -> ProjectProjection:
        return project_projection(self.store, self.artifacts, project_id)

    def list_projects(self, *, include_archived: bool = False) -> list[ProjectProjection]:
        projects = [project_projection(self.store, self.artifacts, project_id, include_history=False)
                    for project_id in self.store.list_project_ids()]
        if not include_archived:
            projects = [item for item in projects if not item.archived]
        # 置顶优先、再按 updated_at 倒序：两次稳定排序。
        projects.sort(key=lambda item: item.updated_at, reverse=True)
        projects.sort(key=lambda item: not item.pinned)
        return projects

    def read_department_setting(self, project_id: str, department: str) -> dict[str, Any]:
        if department not in DEPARTMENTS:
            raise ValueError("unknown department")
        return _setting_view(self.projection(project_id).department_settings[department])

    def read_projection_setting(self, project_id: str, department: str) -> DepartmentSetting | None:
        # 运行层每次请求读取的当前设置：直接取保存的项目投影，不拼接事项状态（避免每次请求重算全部事项）。
        # 没有这个项目或部门不存在时为空，由调用方按内置默认 Prompt 处理
        if department not in DEPARTMENTS:
            return None
        state = saved_project(self.store, project_id)
        if state is None:
            return None
        _default_settings(state)
        return state.department_settings.get(department)

    # 项目登记与状态

    def register(self, name: str, goal: str, *, source: str = "idea",
                 initial_directory: str | None = None,
                 command: Command | None = None) -> str:
        # command 是引起登记的命令：同一命令身份已经登记时写入口在判断之前拒绝（DuplicateCommand、CommandIdReused），
        # 不保存目标原文，也不新建项目。source 为 idea（想法新建）或 existing（接入已有项目）
        # initial_directory 是新建项目时一次性的起点文件夹（工单 #321，设计第 3 节）：
        # 在事务之前与 project.onboard 相同的采集路径只读采集公开树，采集失败时命令被拒绝，
        # 不建立项目，不写入任何事件。采集的快照所属范围是项目（与 project_goal 工件相同），不属于任何 run
        _require_text("name", name)
        _require_text("goal", goal)
        project_id = new_id("proj")
        snapshot = None
        if initial_directory is not None:
            _tree, snapshot = ingest_snapshot(initial_directory, self.artifacts, project_id)

        def register(transaction: Transaction) -> None:
            goal_ref = self.artifacts.put(project_id, "project_goal", goal, media_type="text/markdown")
            transaction.append(NewProjectEvent(ProjectEventType.PROJECT_REGISTERED, {
                "name": name, "goal": goal, "goal_ref": asdict(goal_ref), "source": source,
                **({} if snapshot is None else {"initial_snapshot": snapshot}),
            }, actor="user:local"))

        self.writes.transact(project_stream(project_id), register, expected_version=0, command=command)
        return project_id

    def onboard(self, name: str, goal: str, source_name: str, source_path: str, *,
               max_cycles: int | None = None,
               run_time_limit_sec: int | None = None,
                context_window: int = 32_000,
                command: Command | None = None) -> tuple[str, str, str]:
        # 接入已有项目（3.8 第 3.1 节）：同一个项目流事务中登记项目（source 为 existing）、登记源目录、
        # 登记建档事项（kind 为 onboarding，带快照记录），随后创建建档 run。
        # 快照在事务之前采集：采集失败时命令被拒绝，不建立项目，不写入任何事件。
        # 调用方（应用层）先采集快照并把错误转成 source_invalid
        _require_text("name", name)
        _require_text("goal", goal)
        _require_text("source_name", source_name)
        _require_text("source_path", source_path)
        max_cycles, _default_limit = self._limit_values(max_cycles, None)
        run_time_limit_sec = self.onboarding_round_limit(None, run_time_limit_sec)
        project_id = new_id("proj")
        work_item_id, run_id = new_id("wi"), new_id("run")
        tree, snapshot = ingest_snapshot(source_path, self.artifacts, run_id)

        def onboard(transaction: Transaction) -> _NewWorkItem | None:
            goal_ref = self.artifacts.put(project_id, "project_goal", goal, media_type="text/markdown")
            transaction.append(NewProjectEvent(ProjectEventType.PROJECT_REGISTERED, {
                "name": name, "goal": goal, "goal_ref": asdict(goal_ref), "source": "existing",
            }, actor="user:local"))
            transaction.append(NewProjectEvent(ProjectEventType.SOURCE_DIRECTORY_CONFIGURED, {
                "name": source_name, "path": source_path, "version": 1, "base_version": 0,
            }, actor="user:local"))
            project = _default_settings(deepcopy(transaction.projection))
            return self._work_item_created(
                transaction, project, goal, title=name, max_cycles=max_cycles,
                run_time_limit_sec=run_time_limit_sec, context_window=context_window,
                baseline=None, initial_tree=tree, snapshot=snapshot, source_run=None,
                work_item_id=work_item_id, run_id=run_id, kind="onboarding",
            )

        item = self._start_in(project_id, onboard, command=command)
        return project_id, item.work_item_id, item.run_id

    def restart_onboarding(self, project_id: str, source_name: str, *,
                          max_cycles: int | None = None,
                          run_time_limit_sec: int | None = None,
                           context_window: int = 32_000,
                           command: Command | None = None) -> tuple[str, str]:
        # 重新开始建档（3.8 第 3.1 节）：从登记的源目录重新采集快照，开始新的建档事项。
        # 只在项目来源为已有项目、还没有基线采纳、没有进行中或等待确认的建档事项时可用
        _require_text("source_name", source_name)
        project = self._writable(project_id)
        if project.source != "existing":
            raise OnboardingNotAllowedError("项目不是接入已有项目建立的")
        if project.current_adoption is not None:
            raise OnboardingNotAllowedError("项目已经有基线采纳")
        if any(item.status in ("in_progress", "awaiting_initial_prd")
               for item in _compose(self.store, deepcopy(project)).work_items):
            raise WorkItemInProgressError(f"work item in progress: {project_id}")
        directory = project.source_directories.get(source_name)
        if directory is None:
            raise SourceDirectoryNotFoundError(f"unknown source directory: {source_name}")
        max_cycles, _default_limit = self._limit_values(max_cycles, None)
        run_time_limit_sec = self.onboarding_round_limit(project_id, run_time_limit_sec)
        work_item_id, run_id = new_id("wi"), new_id("run")
        tree, snapshot = ingest_snapshot(directory.path, self.artifacts, run_id)

        def restart(transaction: Transaction) -> _NewWorkItem | None:
            state = _default_settings(deepcopy(self._writable_in(transaction, project_id)))
            return self._work_item_created(
                transaction, state, state.goal, title=state.name, max_cycles=max_cycles,
                run_time_limit_sec=run_time_limit_sec, context_window=context_window,
                baseline=None, initial_tree=tree, snapshot=snapshot, source_run=None,
                work_item_id=work_item_id, run_id=run_id, kind="onboarding",
            )

        item = self._start_in(project_id, restart, command=command)
        return item.work_item_id, item.run_id

    def _start_in(self, project_id: str, create: Callable[[Transaction], _NewWorkItem | None], *,
                  command: Command | None = None) -> _NewWorkItem:
        # 在已有的项目流事务结果上创建 run；创建失败时在项目流记下失败的原因。
        # 从登记之前到 run 创建完成，这个项目算作有事项正在开始
        token = object()
        self._starting.setdefault(project_id, set()).add(token)
        try:
            item = self.writes.transact(project_stream(project_id), create, command=command)
            if item is None:
                raise ValueError("the work item transaction produced no work item")
            try:
                self.orchestrator.create_run(item.text, run_id=item.run_id, **item.run_options)
            except Exception as exc:
                self.writes.append(project_stream(project_id), NewProjectEvent(
                    ProjectEventType.WORK_ITEM_START_FAILED,
                    {"work_item_id": item.work_item_id, "run_id": item.run_id,
                     "error": str(exc) or type(exc).__name__},
                    actor="system",
                ))
                raise
        finally:
            self._starting[project_id].discard(token)
        return item

    def set_parameter(self, project_id: str, name: str, value: Any, *, reason: str, modified_by: str,
                      command: Command | None = None) -> None:
        # 设置项目级参数（迭代底座 B3，工单 #351）：只有检查时限与建档单轮上限可以按项目设置，
        # 取值按全局的界限核对；事件写进项目流，只作用于之后创建的 run
        from . import parameters as parameter_values

        _require_text("reason", reason)
        _require_text("modified_by", modified_by)
        new_value = parameter_values.check_project_parameter(name, value)
        old_value = parameter_values.value_for_project(self.store, project_id, name)

        def set_parameter(transaction: Transaction) -> None:
            self._writable_in(transaction, project_id)
            transaction.append(NewProjectEvent(ProjectEventType.PARAMETER_SET, {
                "name": name, "old_value": old_value, "new_value": new_value,
                "reason": reason, "modified_by": modified_by,
                "bounds": list(DEFINITIONS.rule(name).bounds),
            }, actor=modified_by))

        self.writes.transact(project_stream(project_id), set_parameter, command=command)

    def rename(self, project_id: str, name: str, *, command: Command | None = None) -> None:
        _require_text("name", name)

        def rename(transaction: Transaction) -> None:
            self._writable_in(transaction, project_id)
            transaction.append(NewProjectEvent(ProjectEventType.PROJECT_RENAMED, {"name": name}, actor="user:local"))

        self.writes.transact(project_stream(project_id), rename, command=command)

    def set_goal(self, project_id: str, goal: str, *, command: Command | None = None) -> None:
        # 修改长期目标：写成项目流事件，之后开始的事项使用新目标，进行中的事项按 run_created 记下的开始时的目标做完
        _require_text("goal", goal)

        def set_goal(transaction: Transaction) -> None:
            self._writable_in(transaction, project_id)
            goal_ref = self.artifacts.put(project_id, "project_goal", goal, media_type="text/markdown")
            transaction.append(NewProjectEvent(ProjectEventType.PROJECT_GOAL_CHANGED, {
                "goal": goal, "goal_ref": asdict(goal_ref),
            }, actor="user:local"))

        self.writes.transact(project_stream(project_id), set_goal, command=command)

    def pin(self, project_id: str, pinned: bool, *, command: Command | None = None) -> None:
        if not isinstance(pinned, bool):
            raise ValueError("pinned must be a boolean")

        def pin(transaction: Transaction) -> None:
            self._writable_in(transaction, project_id)
            transaction.append(NewProjectEvent(ProjectEventType.PROJECT_PINNED, {"pinned": pinned},
                                               actor="user:local"))

        self.writes.transact(project_stream(project_id), pin, command=command)

    def archive(self, project_id: str, *, command: Command | None = None) -> None:
        def archive(transaction: Transaction) -> None:
            if self._saved_in(transaction, project_id).archived:
                return
            self._reject_in_progress(transaction, project_id)
            transaction.append(NewProjectEvent(ProjectEventType.PROJECT_ARCHIVED, actor="user:local"))

        self.writes.transact(project_stream(project_id), archive, command=command)

    def restore(self, project_id: str, *, command: Command | None = None) -> None:
        def restore(transaction: Transaction) -> None:
            if self._saved_in(transaction, project_id).archived:
                transaction.append(NewProjectEvent(ProjectEventType.PROJECT_RESTORED, actor="user:local"))

        self.writes.transact(project_stream(project_id), restore, command=command)

    # 事项

    def start_work_item(self, project_id: str, text: str, *, title: str | None = None,
                        max_cycles: int | None = None,
                        run_time_limit_sec: int | None = None,
                        context_window: int = 32_000, command: Command | None = None) -> tuple[str, str]:
        # 限额不给时取参数现值（工单 #349）：新事项按当前参数建立，调用方显式给出时按给出值
        _require_text("text", text)
        _require_title(title)
        self._writable(project_id)
        self.settle_pending(project_id)
        values = self._limit_values(max_cycles, run_time_limit_sec)
        max_cycles, run_time_limit_sec = values

        work_item_id, run_id = new_id("wi"), new_id("run")

        def create(transaction: Transaction) -> _NewWorkItem:
            # 事项的基线、初始树、快照与登记命令取自事务中的项目投影
            project = _default_settings(deepcopy(self._writable_in(transaction, project_id)))
            point = self._work_item_start_point(project)
            return self._work_item_created(
                transaction, project, text, title=title, max_cycles=max_cycles,
                run_time_limit_sec=run_time_limit_sec, context_window=context_window,
                baseline=point.baseline, initial_tree=point.initial_tree, snapshot=point.snapshot,
                source_run=point.source_run, work_item_id=work_item_id, run_id=run_id,
            )

        return self._start(project_id, create, command=command)

    def _work_item_start_point(self, project: ProjectProjection) -> _StartPoint:
        # 事项的起点只在这里求出（工单 #321，设计第 2 节），按下面的顺序取第一个存在的：
        # 当前采纳成果的代码树、项目的起始文件夹快照（只在第一次采纳之前使用）、空树。
        # 开始事项、排空期间排队的事项、因升级重新开始的事项都调用它，不各写一遍
        if project.current_adoption is not None:
            adoption = project.current_adoption
            source_run = project_run(self.store, adoption.run_id)
            if source_run.project_id != project.project_id:
                raise ValueError("source run does not belong to this project")
            baseline = {
                "adoption_id": adoption.adoption_id, "source_run_id": adoption.run_id,
                "delivery_event_id": adoption.delivery_event_id, "tree_ref": adoption.tree_ref,
                "code_tree_digest": adoption.code_tree_digest,
            }
            initial_tree = load_tree(self.artifacts, artifact_run(adoption.tree_ref["path"]),
                                     ArtifactRef(**adoption.tree_ref))
            if initial_tree.digest != adoption.code_tree_digest:
                raise ValueError("archived tree does not match the adopted deliverable digest")
            return _StartPoint(baseline=baseline, initial_tree=initial_tree, source_run=source_run, snapshot=None)
        snapshot = project.initial_snapshot
        if snapshot:
            # 起始文件夹快照不是采纳成果：基线为空，事项种类仍是 change，
            # 快照记录随 work_item_created 写入，run 创建被中断时启动核对按这条记录建立缺少的 run
            initial_tree = load_tree(self.artifacts, artifact_run(snapshot["tree_ref"]["path"]),
                                     ArtifactRef(**snapshot["tree_ref"]))
            if initial_tree.digest != snapshot["tree_digest"]:
                raise ValueError("archived tree does not match the initial directory snapshot digest")
            return _StartPoint(baseline=None, initial_tree=initial_tree, source_run=None, snapshot=snapshot)
        return _StartPoint(baseline=None, initial_tree=None, source_run=None, snapshot=None)


    def _work_item_created(self, transaction: Transaction, project: ProjectProjection, text: str, *,
                           title: str, max_cycles: int, run_time_limit_sec: int, context_window: int,
                           baseline: dict[str, Any] | None, initial_tree: Any, snapshot: dict[str, Any] | None,
                           source_run: Any, work_item_id: str, run_id: str,
                           priority: str = PRIORITY_USER, kind: str = "change",
                           round: int | None = None, onboarding_basis: dict[str, Any] | None = None,
                           additional_input: str | None = None,
                           restarted_from_run_id: str | None = None) -> _NewWorkItem:
        # 在事务中追加 work_item_created，交回创建 run 需要的内容
        title = work_item_title(text) if title is None else title
        # 项目部门设置的版本随事项记下：部门 Prompt 与模型不在事项内留副本，每次请求从项目读取当前设置
        prompt_config_versions = {department: project.department_settings[department].version
                                  for department in DEPARTMENTS}
        context_text = project_context_text(project, title, source_run)
        # 项目上下文是该 run 的模型输入，按 run 作用域存放；内核创建 run 时会写出同一份工件。
        context_ref = self.artifacts.put(run_id, "project_context", context_text, media_type="text/markdown")
        transaction.append(NewProjectEvent(ProjectEventType.WORK_ITEM_CREATED, {
            "work_item_id": work_item_id, "title": title, "text": text, "run_id": run_id, "baseline": baseline,
            "snapshot": snapshot,
            "project_context_ref": asdict(context_ref), "prompt_config_versions": prompt_config_versions,
            "max_cycles": max_cycles, "run_time_limit_sec": run_time_limit_sec, "context_window": context_window,
            "definitions_version": DEFINITIONS.version,
            # 事项在队列中的优先级：因升级重新开始的事项排在队列最前面（顺序由 3.4A 的 #19 实现）
            "priority": priority,
            "kind": kind,
            # 因升级重新开始的事项记下它从哪一个旧 run 重新开始（工单 #1186）；其余事项不写这个字段
            **({} if restarted_from_run_id is None else {"restarted_from_run_id": restarted_from_run_id}),
        }, actor="user:local"))
        return _NewWorkItem(
            work_item_id=work_item_id, run_id=run_id, text=text,
            run_options=dict(
                max_cycles=max_cycles, run_time_limit_sec=run_time_limit_sec, context_window=context_window,
                project_id=project.project_id, work_item_id=work_item_id, baseline=baseline,
                initial_tree=initial_tree, code_snapshot=snapshot, project_context=context_text,
                prompt_config_versions=prompt_config_versions, kind=kind,
                round=(1 if kind == "onboarding" else 0) if round is None else round,
                onboarding_basis=onboarding_basis, additional_input=additional_input,
            ),
        )

    def _start(self, project_id: str, create: Callable[[Transaction], _NewWorkItem], *,
               command: Command | None = None) -> tuple[str, str]:
        # 在项目流登记事项，再创建它的 run；创建失败时在项目流记下失败的原因。
        # 从登记之前到 run 创建完成，这个项目算作有事项正在开始
        item = self._start_in(project_id, create, command=command)
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
            project = _default_settings(deepcopy(self._writable_in(transaction, run.project_id)))
            item = project.work_item_for_run(run_id)
            if item is None:
                return None
            if item.kind == "onboarding":
                return self._onboarding_restarted(transaction, project, item, run_id)
            point = self._work_item_start_point(project)
            return self._work_item_created(
                transaction, project, item.text, title=item.title, max_cycles=item.max_cycles,
                run_time_limit_sec=item.run_time_limit_sec, context_window=item.context_window,
                baseline=point.baseline, initial_tree=point.initial_tree, snapshot=point.snapshot,
                source_run=point.source_run,
                work_item_id=new_id("wi"), run_id=new_id("run"), priority=PRIORITY_UPGRADE_RESTART,
                restarted_from_run_id=run_id,
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

    def _onboarding_restarted(self, transaction: Transaction, project: ProjectProjection,
                              item: WorkItem, run_id: str) -> _NewWorkItem:
        # 建档事项因升级重新开始（设计第 6 节最后一行）：第一轮用建档事项记录的快照重建，与开始建档时同样
        # 从快照开始、种类为 onboarding、没有基线、轮次为 1；修改轮带上一轮候选与修改意见重新开始，与回答
        # 「提出修改」建立的 run 依据相同（轮次、上一轮候选的事件编号、修改意见原文）。
        # 登记的是同一个建档事项的新 run：事项编号沿用
        snapshot = item.snapshot
        if snapshot is None:
            raise ValueError(f"onboarding work item {item.work_item_id} has no source snapshot")
        ref = ArtifactRef(**snapshot["tree_ref"])
        tree = load_tree(self.artifacts, artifact_run(ref.path), ref)
        prior = project_run(self.store, run_id)
        basis = prior.onboarding_basis
        note = None if basis is None or basis.get("note_ref") is None else self.artifacts.get(
            ArtifactRef(**basis["note_ref"])).decode("utf-8")
        return self._work_item_created(
            transaction, project, item.text, title=item.title, max_cycles=item.max_cycles,
            run_time_limit_sec=item.run_time_limit_sec, context_window=item.context_window,
            baseline=None, initial_tree=tree, snapshot=snapshot, source_run=None,
            work_item_id=item.work_item_id, run_id=new_id("run"), priority=PRIORITY_UPGRADE_RESTART,
            kind="onboarding", round=prior.round, onboarding_basis=basis, additional_input=note,
            restarted_from_run_id=run_id,
        )

    def queue_work_item(self, project_id: str, text: str, *, title: str | None = None,
                        command: Command | None = None) -> str:
        # 排空期间新建的事项（3.1，ADR-0019）：在项目流按通常方式登记事项，但不创建它的 run，也不开始执行。
        # run 流为空，事项的状态因此是「还没有开始」；它排在队列里等升级完成以后开始（调度由 3.4A 的 #19 实现）
        _require_text("text", text)
        _require_title(title)
        self._writable(project_id)
        max_cycles, run_time_limit_sec = self._limit_values(None, None)
        work_item_id, run_id = new_id("wi"), new_id("run")

        def queue(transaction: Transaction) -> str:
            project = _default_settings(deepcopy(self._writable_in(transaction, project_id)))
            point = self._work_item_start_point(project)
            self._work_item_created(
                transaction, project, text, title=title, max_cycles=max_cycles,
                run_time_limit_sec=run_time_limit_sec, context_window=32_000,
                baseline=point.baseline, initial_tree=point.initial_tree, snapshot=point.snapshot,
                source_run=point.source_run, work_item_id=work_item_id, run_id=run_id, priority=PRIORITY_USER,
            )
            return work_item_id

        return self.writes.transact(project_stream(project_id), queue, command=command)

    # 结算

    def settle(self, run_id: str) -> ProjectEvent | None:
        """幂等：run 非 DONE、不属于事项或已结算时无事件。"""
        try:
            run = project_run(self.store, run_id)
        except RunNotFoundError:
            return None
        if run.project_id is None or run.work_item_id is None:
            return None
        settled = self.writes.transact(project_stream(run.project_id),
                                    lambda transaction: self._settle_run(transaction, run))
        if settled is not None and settled.type == ProjectEventType.DELIVERABLE_ADOPTED:
            self._trigger_writeback_if_enabled(run.project_id, settled.payload["adoption_id"])
        return settled

    def _trigger_writeback_if_enabled(self, project_id: str, adoption_id: str) -> None:
        # 采纳以后按源目录登记的写回设置执行写回（ADR-0034）：停止与冲突由写回自己记成事件，
        # 不在这里吞掉结果；异常表示写回没有产生事件，由用户重新发起
        # 写回目标不可用时（目标仓库不存在、那个路径不是 git 仓库、目标分支不存在），
        # 自动写回做不了，也不因此让这一次采纳失败：页面上这一次采纳仍是「还没有写回」，
        # 用户在项目设置页改好设置以后按「写回成果」重新发起，那时命令给出中文的理由（工单 #709）
        from .writeback import WritebackTargetUnavailable

        project = self.projection(project_id)
        if any(d.writeback_enabled for d in project.source_directories.values()):
            try:
                self.execute_writeback(project_id, adoption_id)
            except WritebackTargetUnavailable:
                return

    def execute_writeback(
        self,
        project_id: str,
        adoption_id: str | None = None,
        *,
        command: Command | None = None,
        simulate_unknown_push: bool = False,
    ) -> ProjectEvent | None:
        from .writeback import perform_writeback
        project = self._writable(project_id)
        if adoption_id is None:
            if project.current_adoption is None:
                return None
            adoption_id = project.current_adoption.adoption_id
        return perform_writeback(
            self,
            project_id,
            adoption_id,
            command=command,
            simulate_unknown_push=simulate_unknown_push,
        )
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

    def create_missing_revision_runs_on_startup(self) -> list[str]:
        # 启动时按 onboarding_revision_started 建立缺少的修改轮 run（工单 #136，设计第 6 节）。
        # 修改轮事件在答案的同一个项目流事务中写入，run 在事务提交以后创建：
        # 进程在两者之间中断时，这里按事件补建（run 流从版本 0 开始，重复创建被拒绝）
        created: list[str] = []
        for project_id in self.store.list_project_ids():
            state = self.projection(project_id)
            candidates = {entry.event_id: entry for entry in state.initial_prd_candidates}
            for event in self.store.list_project_events(project_id):
                if event.type != ProjectEventType.ONBOARDING_REVISION_STARTED:
                    continue
                run_id = event.payload["run_id"]
                if self.store.stream_events(run_stream(run_id), after_version=0):
                    continue
                candidate = candidates.get(event.payload["candidate_event_id"])
                item = state.work_item(event.payload["work_item_id"])
                if candidate is None or item is None:
                    continue
                self.orchestrator.create_revision_run(
                    project_id, candidate, run_id, int(event.payload["round"]), event.payload.get("note"))
                created.append(run_id)
        return created

    def create_missing_work_item_runs_on_startup(self) -> list[str]:
        # 启动时按 work_item_created 建立缺少的 run（工单 #321，设计第 7 节）：
        # 事项登记的事务已经提交、run 还没有创建时进程中断，事项的 run 流没有任何事件，
        # 这里按事项记录（基线或起始文件夹快照都在里面）补建。run 流从版本 0 开始，重复创建被拒绝。
        # 排空期间排队的事项同样没有 run，但它们按设计等升级完成以后才开始：排空还没有结束时这里不补建
        if self._draining():
            return []
        created: list[str] = []
        for project_id in self.store.list_project_ids():
            state = self.projection(project_id)
            # 事项创建时冻结的定义版本（工单 #1189）：与当前不同时不补建，保留事项记录与原始起点，
            # 交给定义版本差异的恢复决定处理；同一版本时按事项记录自动补建
            frozen_versions = {
                event.payload["run_id"]: str(event.payload.get("definitions_version", ""))
                for event in self.store.list_project_events(project_id)
                if event.type == ProjectEventType.WORK_ITEM_CREATED
            }
            for item in state.work_items:
                if item.kind == "onboarding":
                    continue
                if self.store.stream_events(run_stream(item.run_id), after_version=0):
                    continue
                item_definitions_version = frozen_versions.get(item.run_id, "")
                if item_definitions_version and item_definitions_version != DEFINITIONS.version:
                    continue
                snapshot = item.snapshot
                tree = None
                if snapshot:
                    # 起始文件夹快照的所属范围是项目：按 tree_ref 的第一段取得（工单 #321）
                    ref = ArtifactRef(**snapshot["tree_ref"])
                    tree = load_tree(self.artifacts, artifact_run(ref.path), ref)
                else:
                    baseline = item.baseline
                    if baseline is not None:
                        ref = ArtifactRef(**baseline["tree_ref"])
                        tree = load_tree(self.artifacts, artifact_run(ref.path), ref)
                self.orchestrator.create_run(
                    item.text, max_cycles=item.max_cycles, run_time_limit_sec=item.run_time_limit_sec,
                    context_window=item.context_window, run_id=item.run_id,
                    project_id=project_id, work_item_id=item.work_item_id,
                    baseline=item.baseline, initial_tree=tree, code_snapshot=snapshot,
                    project_context=self.artifacts.get(
                        ArtifactRef(**item.project_context_ref)).decode("utf-8"),
                    prompt_config_versions=dict(item.prompt_config_versions),
                    item_definitions_version=item_definitions_version or DEFINITIONS.version,
                )
                created.append(item.run_id)
        return created

    def _draining(self) -> bool:
        # 排空还没有结束（目录流里有开始排空的事件，还有未结束的 run）：
        # 排空期间排队的事项按设计等升级完成以后才开始，这里不补建它们的 run。
        # 升级完成（换了版本）以后排空结束，不再排空（工单 #731）
        last = last_drain_event(self.store.stream_events(catalog_stream()))
        if last is None or last.type == DRAIN_FINISHED:
            return False
        unfinished = classify_startup_runs(self.store)
        return bool(unfinished.same_version or unfinished.other_version)

    def withdraw_waiting_initial_prd(self, work_item_id: str, *, command: Command | None = None) -> bool:
        # 取消等待确认初始 PRD 的建档事项：撤销项目流中还没有回答的决定请求（工单 #136，设计第 3.1、6 节）。
        # 返回是否撤销了一个请求；没有等待中的请求时返回假，调用方按事项已结束处理
        found = self._waiting_initial_prd(work_item_id)
        if found is None:
            return False
        project_id, request = found

        # 写事务内重新核对请求仍然是打开的：与回答并发时不能把已回答的请求改写成已撤销，
        # 这种情况下什么也不写，按没有撤销处理
        withdrawn: list[bool] = []

        def withdraw(transaction: Transaction) -> None:
            current = transaction.decisions.get(request.event_id)
            withdrawn.append(current is not None and current.status == "open")
            if not withdrawn[-1]:
                return
            transaction.append(NewProjectEvent(ProjectEventType.PROJECT_DECISION_WITHDRAWN, {
                "decision_id": request.event_id, "reason": "user_cancelled",
                "work_item_id": work_item_id, "run_id": request.payload.get("run_id"),
            }, actor="user:local"))

        self.writes.transact(project_stream(project_id), withdraw, command=command)
        return withdrawn[0] if withdrawn else False

    def _waiting_initial_prd(self, work_item_id: str) -> tuple[str, ProjectEvent] | None:
        # 这个事项还没有回答的 initial_prd 请求（最后提出的那一个）：没有时返回空
        for project_id in self.store.list_project_ids():
            events = self.store.list_project_events(project_id)
            open_requests = {event.event_id: event for event in events
                             if event.type == ProjectEventType.PROJECT_DECISION_REQUESTED}
            for event in events:
                if event.type in (ProjectEventType.PROJECT_DECISION_ANSWERED,
                                  ProjectEventType.PROJECT_DECISION_WITHDRAWN):
                    open_requests.pop(event.payload["decision_id"], None)
            found = [event for event in open_requests.values()
                     if event.payload.get("work_item_id") == work_item_id
                     and event.payload.get("kind") == INITIAL_PRD.name]
            if found:
                return project_id, found[-1]
        return None

    def starting(self) -> bool:
        # 有事项正在开始（已经登记、run 还没有创建）时占用执行槽位
        return any(items for items in self._starting.values())

    def _accepted_event(self, run_id: str, event_type: EventType) -> Event | None:
        # run 投影保存的结构说明与基线核验是事件的原始载荷，不含事件编号，编号按事件种类从 run 流中取。
        # 编号由 run 自己写入：重放 run 流以前读不到，项目启动时补跑尚未写入的 run 的结算就走这一条
        events = self.store.list_events(run_id)
        return next((event for event in reversed(events) if event.type == event_type), None)

    def _quality_check_commands(self, run_id: str) -> dict[str, str]:
        # 质检自己在快照上运行的 run_check 调用的命令字符串（工单 #136，设计第 3.3、4.6 节）：
        # 按 run 事件里质检的 run_check 调用取，同一个检查以后一次调用为准
        commands: dict[str, str] = {}
        for event in self.store.list_events(run_id):
            if event.type != EventType.TOOL_CALLED or event.payload.get("name") != "run_check":
                continue
            args = event.payload.get("args") or {}
            if not isinstance(args, dict):
                continue
            name, command = args.get("name"), args.get("command")
            if isinstance(name, str) and isinstance(command, str):
                commands[name] = command
        return commands

    def _settle_run(self, transaction: Transaction, run: RunProjection) -> ProjectEvent | None:
        project = transaction.projection
        if run.status != "done":
            return None
        if any(item.run_id == run.run_id for item in project.adoptions) or any(item.run_id == run.run_id for item in project.held):
            return None
        item = project.work_item_for_run(run.run_id)
        if item is None or item.work_item_id != run.work_item_id:
            return None
        if run.kind == "onboarding":
            # 建档 run 以 baseline_verified 结束：提出初始 PRD 候选并请求用户确认（工单 #136，设计第 3.2、3.3 节）。
            # 建档 run 没有交付与放行评审，因此在这一支判断，不走下面的普通结算
            return self._propose_initial_prd(transaction, run, item)
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
            }, actor="system"))[0]
        adoption = _adoption_payload(delivery, release, run, item)
        blocked = self._guard_kernel_paths(transaction, run, item, delivery, adoption)
        if blocked is True:
            # 已经发出过内核修改请求：批准或拒绝以前不再采纳，也不重复请求
            return None
        if blocked is None:
            return transaction.append(NewProjectEvent(ProjectEventType.DELIVERABLE_ADOPTED,
                                                      dict(adoption, previous_adoption_id=current),
                                                      actor="system"))[0]
        return transaction.append(NewProjectEvent(
            ProjectEventType.PROJECT_DECISION_REQUESTED, blocked, actor="system"))[0]

    def _guard_kernel_paths(self, transaction: Transaction, run: RunProjection, item: WorkItem,
                            delivery: Any, adoption: dict[str, Any]) -> dict[str, Any] | bool:
        # 路径守卫（受控内核设计说明第 4.2 节，工单 #354）：把交付相对基线的改动路径与运行实例的内核清单
        # 比较，有交集时不自动采纳，请求用户批准，材料附改动的路径与差异；没有交集时返回空，照常采纳。
        # 已经发出过请求时返回真：请求待回答或已被拒绝，这个 run 都不再采纳，也不重复请求。
        # held_adoption 是批准以后要写入的采纳载荷，previous_adoption_id 在批准时按当时状态补上
        if any(decision.kind == KERNEL_MODIFICATION.name
               and decision.request.get("delivery_run_id") == run.run_id
               for decision in transaction.decisions.values()):
            return True
        baseline_tree = self._adopted_tree(transaction.projection, item)
        delivery_tree = load_tree(self.artifacts, artifact_run(delivery.tree_ref.path), delivery.tree_ref)
        hits = kernel_hits(changed_paths(baseline_tree, delivery_tree), kernel_manifest_paths())
        if not hits:
            return None
        return {
            "kind": KERNEL_MODIFICATION.name, "blocks": KERNEL_MODIFICATION.blocks,
            "options": [asdict(option) for option in KERNEL_MODIFICATION.options],
            "description": f"交付改动了内核清单里的 {len(hits)} 个路径，批准以后才采纳",
            "facts": [], "department": "engineering",
            "work_item_id": item.work_item_id, "delivery_run_id": run.run_id,
            "kernel_paths": hits, "diff": kernel_diff(baseline_tree, delivery_tree, hits),
            "held_adoption": adoption,
        }

    def _adopted_tree(self, project: ProjectProjection, item: WorkItem) -> Any:
        # 交付的基线树：事项基线的代码树，第一次采纳之前是项目起始文件夹快照的树（工单 #354）
        reference = item.baseline["tree_ref"] if item.baseline else None
        if reference is None and project.initial_snapshot:
            reference = project.initial_snapshot["tree_ref"]
        if reference is None:
            return None
        return load_tree(self.artifacts, artifact_run(reference["path"]), ArtifactRef(**reference))


    def _propose_initial_prd(self, transaction: Transaction, run: RunProjection,
                             item: WorkItem) -> ProjectEvent | None:
        # 提出初始 PRD 候选并请求用户确认：候选与决定请求在一个事务中写入（工单 #136，设计第 4.7 节）。
        # 幂等：这个 run 已经提出过候选时不再写入，也不会重复发出决定请求
        project = transaction.projection
        if any(entry.run_id == run.run_id for entry in project.initial_prd_candidates):
            return None
        if run.product_spec is None or run.structure is None or run.baseline_review is None:
            return None
        if run.stop_reason != "baseline_verified" or run.overview_ref is None:
            return None
        if run.effective_contract is None or run.effective_contract.prd_ref is None:
            return None
        snapshot = run.snapshot if run.snapshot is not None else item.snapshot
        if snapshot is None:
            return None
        structure_event = self._accepted_event(run.run_id, EventType.STRUCTURE_ACCEPTED)
        review_event = self._accepted_event(run.run_id, EventType.BASELINE_REVIEW_ACCEPTED)
        structure = run.structure if structure_event is None else {
            **run.structure, "event_id": structure_event.event_id}
        review = run.baseline_review if review_event is None else {
            **run.baseline_review, "event_id": review_event.event_id}
        round_number = run.round
        spec = run.product_spec
        prd_summary = f"目标：{spec.goal}；要求 {len(spec.requirements)} 条；边界 {len(spec.boundaries)} 条"
        candidate = {
            "work_item_id": item.work_item_id, "run_id": run.run_id, "round": round_number,
            "prd": {"event_id": run.product_spec.created_event_id, "content_hash": run.product_spec.content_hash,
                    "prd_ref": asdict(run.effective_contract.prd_ref), "summary": prd_summary},
            "structure": {"event_id": structure["event_id"], "content_hash": structure["content_hash"],
                          "structure_ref": structure["structure_ref"],
                          "code_tree_digest": structure["code_tree_digest"]},
            "baseline_review": {"event_id": review["event_id"], "content_hash": review["content_hash"],
                                "conclusions": list(review["conclusions"]), "omissions": list(review["omissions"]),
                                "checks": _baseline_checks(review["checks"], self._quality_check_commands(run.run_id)),
                                "other_failures": list(review["other_failures"])},
            "overview_ref": run.overview_ref, "snapshot": snapshot,
        }
        if run.onboarding_basis is not None and run.onboarding_basis.get("note_ref") is not None:
            candidate["revision_note_ref"] = run.onboarding_basis["note_ref"]
        [proposed] = transaction.append(NewProjectEvent(
            ProjectEventType.INITIAL_PRD_PROPOSED, candidate, actor="system"))
        transaction.append(NewProjectEvent(ProjectEventType.PROJECT_DECISION_REQUESTED, {
            "kind": INITIAL_PRD.name, "blocks": INITIAL_PRD.blocks,
            "options": [{"id": option.id, "label": option.label, "note_required": option.note_required}
                        for option in INITIAL_PRD.options],
            "description": f"确认第 {round_number} 轮建档的初始 PRD", "facts": [], "department": "product",
            "work_item_id": item.work_item_id, "candidate_run_id": run.run_id, "round": round_number,
            "prd": candidate["prd"], "structure": candidate["structure"],
            "baseline_review": candidate["baseline_review"], "overview_ref": run.overview_ref,
            "snapshot": snapshot, "revision_note_ref": candidate.get("revision_note_ref"),
        }, actor="system"))
        return proposed


    # 部门 Prompt 项目配置

    def configure_department_settings(self, project_id: str, department: str, selection: ModelSelection,
                                      base_version: int, *, command: Command | None = None,
                                      reminders: list[str] | None = None) -> dict[str, Any]:
        # 项目部门设置：模型访问定义引用、请求档位与部门 Prompt 三项，都可以不写入；三项一起保存、一个版本。
        # 并发修改时按版本拒绝后提交的修改（设计说明第 5.2 节）。选择「跟随部门默认」清除本项目的模型选择，
        # 档位选择「跟随」清除请求档位；部门 Prompt 为空表示没有写入，使用内置默认 Prompt。
        # reminders 是这次保存算出的建议能力提醒（设计说明第 5.6 节），随事件保存
        if department not in DEPARTMENTS:
            raise ValueError("unknown department")
        if type(base_version) is not int or base_version < 0:
            raise ValueError("base_version must be a non-negative integer")
        if selection.department_prompt is not None and not selection.department_prompt.strip():
            raise ValueError("department prompt must be a non-empty string when given")

        def configure(transaction: Transaction) -> dict[str, Any] | None:
            current = _default_settings(
                deepcopy(self._writable_in(transaction, project_id))).department_settings[department]
            if base_version != current.version:
                raise DepartmentSettingConflict(_setting_view(current))
            unchanged = (current.provider_id == selection.provider_id
                         and current.model_id == selection.model_id
                         and current.requested_tier == selection.requested_tier
                         and _current_prompt(current) == selection.department_prompt)
            if unchanged:
                return {**_setting_view(current), "unchanged": True}
            payload = selection.event_payload()
            if selection.department_prompt is not None:
                ref = save_department_prompt(self.artifacts, project_id, department, selection.department_prompt)
                payload["department_prompt_ref"] = asdict(ref)
            payload.update({"department": department, "version": current.version + 1,
                            "base_version": base_version, "reminders": list(reminders or ())})
            transaction.append(NewProjectEvent(ProjectEventType.DEPARTMENT_SETTINGS_CONFIGURED, payload,
                                              actor="user:local"))
            return None

        unchanged = self.writes.transact(project_stream(project_id), configure, command=command)
        return unchanged or {**self.read_department_setting(project_id, department), "unchanged": False}

    # 源目录登记（#74）

    def configure_source_directory(self, project_id: str, name: str, path: str, *,
                                   base_version: int,
                                   writeback_enabled: bool = False,
                                   remote: str = "",
                                   target_branch: str = "",
                                   check_commands: Sequence[str] = (),
                                   credential_ref: str | None = None,
                                   command: Command | None = None) -> dict[str, Any]:
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
                "writeback_enabled": bool(writeback_enabled),
                "remote": str(remote or ""),
                "target_branch": str(target_branch or ""),
                "check_commands": [str(c) for c in check_commands],
                "credential_ref": credential_ref,
            }, actor="user:local"))

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
            }, actor="user:local"))
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
        if self._starting.get(project_id) or any(
                item.status in ("in_progress", "awaiting_initial_prd") for item in project.work_items):
            raise WorkItemInProgressError(f"work item in progress: {project_id}")


@dataclass(frozen=True)
class _StartPoint:
    # 事项的起点（工单 #321，设计第 2 节）：采纳成果的基线与初始树、起始文件夹快照记录、基线所属的 run。
    # 起始文件夹快照不是采纳成果：它的基线与 source_run 为空，snapshot 带快照记录，事项种类仍是 change
    baseline: dict[str, Any] | None
    initial_tree: Any
    source_run: Any
    snapshot: dict[str, Any] | None

@dataclass(frozen=True)
class _NewWorkItem:
    # 已经在项目流登记的事项与创建它的 run 需要的内容
    work_item_id: str
    run_id: str
    text: str
    run_options: dict[str, Any]



def _baseline_checks(receipts: list[dict[str, Any]], commands: dict[str, str]) -> list[dict[str, Any]]:
    # 基线核验里的检查回执（工单 #136，设计第 4.6 节）补上质检自己运行该检查时用的命令字符串：
    # 命令取自质检在本 run 中 run_check 的调用（按检查名绑定），质检没有记录时为空
    return [
        {"name": receipt["name"], "command": commands.get(receipt["name"], ""), "exit_code": int(receipt["exit_code"]),
         "summary": receipt["summary"], "snapshot_hash": receipt["snapshot_hash"]}
        for receipt in receipts
    ]

def _require_title(title: str | None) -> None:
    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise ValueError("title must be a non-empty string when given")


def _current_prompt(setting: DepartmentSetting) -> str | None:
    # 项目部门设置中写入的部门 Prompt；没有写入时为 None，读取模型补成内置默认 Prompt
    return setting.text if setting.configured_prompt else None

def _setting_view(setting: DepartmentSetting) -> dict[str, Any]:
    return {
        "department": setting.department,
        "text": setting.text,
        "default_text": DEFINITIONS.role(setting.department).prompt,
        "department_setting_configured": setting.configured_prompt,
        "provider_id": setting.provider_id,
        "model_id": setting.model_id,
        "requested_tier": setting.requested_tier,
        "version": setting.version,
        "updated_at": setting.updated_at,
        "source": setting.source,
    }


def _source_directory_view(config: SourceDirectory) -> dict[str, Any]:
    return {
        "name": config.name,
        "path": config.path,
        "version": config.version,
        "updated_at": config.updated_at,
        "writeback_enabled": config.writeback_enabled,
        "remote": config.remote,
        "target_branch": config.target_branch,
        "check_commands": list(config.check_commands),
        "credential_ref": config.credential_ref,
    }

def _require_text(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
