# 项目与事项的命令（应用层与接口层设计说明第 3.2 节，工单 #74）。
# 命令处理在写入口的一个事务中完成：登记命令身份、读取保存的投影、核对基准版本与对象状态、判断、追加事件；
# 需要继续执行的工作（运行事项）由流程编排在接口进程的事件循环中作为任务运行，结果以后续事件出现（第 7.2 节）。
# 基准版本按第 3.1 节分四类：新建类不核对；修改类要求相等，否则 stale_base；追加与控制类只记录依据，不要求相等；
# 回答类要求相等。

from __future__ import annotations

from typing import TYPE_CHECKING

from ..event_store import Command
from ..models import DEPARTMENTS, TERMINAL_PHASES, Event, ProjectEvent
from ..interactions import RunTerminalError
from ..projection import RunNotFoundError
from ..providers.errors import CatalogValidationError
from ..providers.selection import ModelSelection
from ..projects import (
    CommandConfigConflict, DepartmentSettingConflict, ProjectArchivedError, ProjectNotFoundError,
    SourceDirectoryConflict, WorkItemInProgressError,
)
from .commands import Rejection
from .contracts import CommandRequest, Contract, NoRefs, Text
from .registry import CommandDefinition

if TYPE_CHECKING:
    from .application import Application


# ---------------------------------------------------------------------------
# 项目的修改类命令（第 3.2 节「项目」）：基准版本是项目基本信息版本，要求相等

def _project_version(application: "Application", project_id: str) -> int:
    try:
        return application.system.projects.projection(project_id).stream_version
    except ProjectNotFoundError as missing:
        raise Rejection("not_found", "没有这个项目，请重新读取以后提交") from missing


def _require_current(application: "Application", project_id: str, base_version: int) -> None:
    current = _project_version(application, project_id)
    if base_version != current:
        raise Rejection("stale_base", "项目已经被修改，请重新读取以后提交", current_version=current)


class ProjectRename(CommandRequest):
    base_version: int
    project_id: str
    name: Text


async def _rename_project(application: "Application", command: Command, request: ProjectRename) -> None:
    _require_current(application, request.project_id, request.base_version)
    try:
        application.system.projects.rename(request.project_id, request.name, command=command)
    except ProjectNotFoundError as missing:
        raise Rejection("not_found", "没有这个项目，请重新读取以后提交") from missing
    except ProjectArchivedError as archived:
        raise Rejection("project_archived", "项目已归档，恢复以后才能修改") from archived


class ProjectSetGoal(CommandRequest):
    base_version: int
    project_id: str
    goal: Text


async def _set_project_goal(application: "Application", command: Command, request: ProjectSetGoal) -> None:
    _require_current(application, request.project_id, request.base_version)
    try:
        application.system.projects.set_goal(request.project_id, request.goal, command=command)
    except ProjectNotFoundError as missing:
        raise Rejection("not_found", "没有这个项目，请重新读取以后提交") from missing
    except ProjectArchivedError as archived:
        raise Rejection("project_archived", "项目已归档，恢复以后才能修改") from archived


class ProjectPin(CommandRequest):
    base_version: int
    project_id: str
    pinned: bool


async def _pin_project(application: "Application", command: Command, request: ProjectPin) -> None:
    _require_current(application, request.project_id, request.base_version)
    try:
        application.system.projects.pin(request.project_id, request.pinned, command=command)
    except ProjectNotFoundError as missing:
        raise Rejection("not_found", "没有这个项目，请重新读取以后提交") from missing
    except ProjectArchivedError as archived:
        raise Rejection("project_archived", "项目已归档，恢复以后才能修改") from archived


class ProjectArchive(CommandRequest):
    base_version: int
    project_id: str


async def _archive_project(application: "Application", command: Command, request: ProjectArchive) -> None:
    _require_current(application, request.project_id, request.base_version)
    try:
        application.system.projects.archive(request.project_id, command=command)
    except ProjectNotFoundError as missing:
        raise Rejection("not_found", "没有这个项目，请重新读取以后提交") from missing
    except WorkItemInProgressError as busy:
        raise Rejection("work_item_in_progress", "项目有事项正在进行，结束以后才能归档") from busy


class ProjectRestore(CommandRequest):
    base_version: int
    project_id: str


async def _restore_project(application: "Application", command: Command, request: ProjectRestore) -> None:
    _require_current(application, request.project_id, request.base_version)
    try:
        application.system.projects.restore(request.project_id, command=command)
    except ProjectNotFoundError as missing:
        raise Rejection("not_found", "没有这个项目，请重新读取以后提交") from missing


# ---------------------------------------------------------------------------
# 记录原文（新建类：不核对基准版本）

class MaterialRecord(CommandRequest):
    base_version: None = None
    project_id: str
    text: Text
    department: str | None = None


def _material_department(request: MaterialRecord) -> None:
    if request.department is not None and request.department not in DEPARTMENTS:
        raise Rejection("not_allowed", "部门不存在")


async def _record_material(application: "Application", command: Command, request: MaterialRecord) -> None:
    _material_department(request)
    try:
        application.system.projects.record_material(
            request.project_id, request.text, department=request.department, command=command)
    except ProjectNotFoundError as missing:
        raise Rejection("not_found", "没有这个项目，请重新读取以后提交") from missing
    except ProjectArchivedError as archived:
        raise Rejection("project_archived", "项目已归档，恢复以后才能记录原文") from archived
    except WorkItemInProgressError as busy:
        raise Rejection("work_item_in_progress", "项目有事项正在进行，结束以后才能记录原文") from busy


# ---------------------------------------------------------------------------
# 事项（新建与控制）

class WorkItemCreate(CommandRequest):
    base_version: None = None
    project_id: str
    text: Text
    title: Text | None = None


class WorkItemRefs(Contract):
    work_item_id: str
    run_id: str


def _work_item_refs(events: list[Event | ProjectEvent]) -> WorkItemRefs:
    # work_item_created 写在项目流中，是这次命令追加的第一条事件
    [created] = events[:1]
    return WorkItemRefs(work_item_id=created.payload["work_item_id"], run_id=created.payload["run_id"])


async def _create_work_item(application: "Application", command: Command, request: WorkItemCreate) -> None:
    system = application.system
    try:
        project = system.projects.projection(request.project_id)
    except ProjectNotFoundError as missing:
        raise Rejection("not_found", "没有这个项目，请重新读取以后提交") from missing
    if project.archived:
        raise Rejection("project_archived", "项目已归档，恢复以后才能新建事项")
    # 建档之前的事项（3.8 第 2 节）：接入已有项目还没有基线时，普通事项不能开始
    onboarding = [item for item in project.work_items if item.kind == "onboarding"]
    if project.source == "existing" and project.current_adoption is None and onboarding:
        if any(item.status in ("in_progress", "awaiting_initial_prd") for item in onboarding):
            raise Rejection("work_item_in_progress", "项目正在建档，结束以后才能新建事项")
        raise Rejection("not_allowed", "项目还没有完成建档，请重新开始建档")
    # 排空期间（3.1，ADR-0019）：Yudao 停止开始新事项，新建的事项排队不开始
    if system.drain.state != "idle":
        system.projects.queue_work_item(request.project_id, request.text, title=request.title, command=command)
        return
    # 3.4A 之前只有一个执行槽位：已有事项在执行时新建被拒绝
    if system.orchestrator.busy():
        raise Rejection("busy", "已有事项正在执行，等它结束以后才能新建")
    status = system.provider_status()
    if not status.get("available", False):
        raise Rejection("provider_unavailable", status.get("message") or "模型调用目标不可用")
    # 新建事项前按该项目的设置对三个部门解析：任何一个无法解析时拒绝，说明部门与具体项（设计说明第 5.5 节）
    failure = _unresolved_department(application, request.project_id)
    if failure is not None:
        department, item, message = failure
        raise Rejection("provider_unavailable", f"部门 {department} 的{item}无法解析：{message}")
    try:
        work_item_id, run_id = system.projects.start_work_item(
            request.project_id, request.text, title=request.title, command=command)
    except ProjectNotFoundError as missing:
        raise Rejection("not_found", "没有这个项目，请重新读取以后提交") from missing
    except ProjectArchivedError as archived:
        raise Rejection("project_archived", "项目已归档，恢复以后才能新建事项") from archived
    except WorkItemInProgressError as busy:
        raise Rejection("busy", "已有事项正在执行，等它结束以后才能新建") from busy
    # 事项已经登记、run 已经创建；由流程编排在接口进程的事件循环中作为任务运行
    system.orchestrator.start_work_item(run_id)


def _unresolved_department(application: "Application", project_id: str) -> tuple[str, str, str] | None:
    # 按该项目的设置解析三个部门（模型访问定义与请求档位分别继承），返回第一个无法解析的部门与具体项。
    # 没有写入任何项目部门设置的项目按部门默认检查（设计说明第 5.5 节最后一段）
    system = application.system
    if system.orchestrator.test_adapter_factory is not None:
        # 确定性测试与演示的适配器在激活时按 fake 协议登记目标，这里不重复解析目录（#45 答复第 6 条）
        return None
    for department in DEPARTMENTS:
        setting = system.projects.read_projection_setting(project_id, department)
        project_selection = ModelSelection(
            provider_id=None if setting is None else setting.provider_id,
            model_id=None if setting is None else setting.model_id,
            requested_tier=None if setting is None else setting.requested_tier,
        )
        resolution = system.facade.resolve_department_default(department, project=project_selection)
        if not resolution.available:
            return department, "模型访问定义", resolution.message
    return None

class WorkItemAppendInput(CommandRequest):
    # 追加需求：基准版本是事项的输入版本，写入事件作为依据，不要求相等
    base_version: int | None = None
    work_item_id: str
    text: Text


def _run_id_for(application: "Application", work_item_id: str) -> str:
    # 事项与它的 run 在项目流中一一对应；从所有项目的事件里找这个事项
    for project_id in application.system.store.list_project_ids():
        item = application.system.projects.projection(project_id).work_item(work_item_id)
        if item is not None:
            return item.run_id
    raise Rejection("not_found", "没有这个事项，请重新读取以后提交")


async def _append_input(application: "Application", command: Command, request: WorkItemAppendInput) -> None:
    run_id = _run_id_for(application, request.work_item_id)
    try:
        application.system.orchestrator.add_input(
            run_id, request.text, base_version=request.base_version, command=command)
    except RunTerminalError as terminal:
        raise Rejection("run_terminal", "事项已经结束，不能再追加需求") from terminal
    except RunNotFoundError as missing:
        raise Rejection("not_found", "没有这个事项，请重新读取以后提交") from missing


class WorkItemCancel(CommandRequest):
    # 取消事项：基准版本是事项版本，写入事件作为依据，不要求相等
    base_version: int | None = None
    work_item_id: str


async def _cancel_work_item(application: "Application", command: Command, request: WorkItemCancel) -> None:
    system = application.system
    run_id = _run_id_for(application, request.work_item_id)
    try:
        projection = system.orchestrator.project(run_id)
    except RunNotFoundError as missing:
        raise Rejection("not_found", "没有这个事项，请重新读取以后提交") from missing
    if projection.phase in TERMINAL_PHASES:
        # 建档 run 已结束、正在等待确认初始 PRD 时，取消撤销项目流中的决定请求（工单 #136，设计第 3.1 节）
        withdrawn = system.projects.withdraw_waiting_initial_prd(request.work_item_id, command=command)
        if withdrawn:
            return
        raise Rejection("run_terminal", "事项已经结束，不能再取消")
    system.orchestrator.cancel(run_id, command=command)


class GuidanceSend(CommandRequest):
    # 发送部门指导：基准版本是该部门的指导版本，写入事件作为依据，不要求相等
    base_version: int | None = None
    work_item_id: str
    department: str
    text: Text


def _guidance_department(request: GuidanceSend) -> None:
    if request.department not in DEPARTMENTS:
        raise Rejection("not_allowed", "部门不存在")


async def _send_guidance(application: "Application", command: Command, request: GuidanceSend) -> None:
    _guidance_department(request)
    run_id = _run_id_for(application, request.work_item_id)
    try:
        application.system.orchestrator.add_guidance(
            run_id, request.department, request.text, base_version=request.base_version, command=command)
    except RunTerminalError as terminal:
        raise Rejection("run_terminal", "事项已经结束，不能再发送指导") from terminal
    except RunNotFoundError as missing:
        raise Rejection("not_found", "没有这个事项，请重新读取以后提交") from missing


# ---------------------------------------------------------------------------
# 项目设置（修改类：基准版本是各设置自身的版本，要求相等）

class DepartmentSettingsSave(CommandRequest):
    # 项目部门设置：模型访问定义引用、请求档位与部门 Prompt 三项，都可以不写入。
    # 模型选择「跟随部门默认」时 provider_id 与 model_id 都不给；档位选择「跟随」时 requested_tier 不给
    base_version: int
    project_id: str
    department: str
    provider_id: str | None = None
    model_id: str | None = None
    requested_tier: str | None = None
    department_prompt: Text | None = None

class DepartmentSettingsSaveRefs(Contract):
    # 保存以后该部门模型不具备建议能力时的提醒（设计说明第 5.6 节「保存时」）；具备或没有写入模型时为空
    reminders: list[str] = []


async def _save_department_settings(application: "Application", command: Command,
                                    request: DepartmentSettingsSave) -> None:
    if request.department not in DEPARTMENTS:
        raise Rejection("not_allowed", "部门不存在")
    if (request.provider_id is None) != (request.model_id is None):
        raise Rejection("not_allowed", "模型访问定义引用必须同时给出所属连接与定义")
    project_selection = ModelSelection(
        provider_id=request.provider_id, model_id=request.model_id,
        requested_tier=request.requested_tier, department_prompt=request.department_prompt,
    )
    # 写入的模型不具备该部门建议能力时的提醒（设计说明第 5.6 节「保存时」）：照常保存，提醒随接受结果返回
    notes = (application.system.facade.department_setting_reminders(request.department, project_selection)
             if project_selection.writes_model() else [])
    try:
        # 保存时校验所选定义已准入、请求档位属于保存时生效模型的支持档位（Provider 模块的检查）
        application.system.facade.validate_department_setting(request.department, project_selection)
        application.system.projects.configure_department_settings(
            request.project_id, request.department, project_selection,
            base_version=request.base_version, command=command, reminders=notes)
    except ProjectNotFoundError as missing:
        raise Rejection("not_found", "没有这个项目，请重新读取以后提交") from missing
    except ProjectArchivedError as archived:
        raise Rejection("project_archived", "项目已归档，恢复以后才能修改") from archived
    except CatalogValidationError as invalid:
        raise Rejection("not_allowed", str(invalid)) from invalid
    except DepartmentSettingConflict as conflict:
        current = conflict.current or {}
        raise Rejection("stale_base", "部门设置已经被修改，请重新读取以后提交",
                        current_version=current.get("version", 0)) from conflict


class CommandRegistrationSave(CommandRequest):
    base_version: int
    project_id: str
    name: Text
    argv: list[str]
    args: list[str] | None = None
    timeout_sec: int | None = None
    output_limit: int | None = None
    # 登记时声明「可以重新执行」（恢复契约第 4 节，工单 #242）：结果未知时「重新执行一次」的选项按这个声明提供
    repeatable: bool = False


async def _save_command_registration(application: "Application", command: Command,
                                     request: CommandRegistrationSave) -> None:
    try:
        application.system.projects.configure_command(
            request.project_id, request.name, request.argv, args=request.args,
            timeout_sec=request.timeout_sec, output_limit=request.output_limit,
            repeatable=request.repeatable,
            base_version=request.base_version, command=command)
    except ProjectNotFoundError as missing:
        raise Rejection("not_found", "没有这个项目，请重新读取以后提交") from missing
    except ProjectArchivedError as archived:
        raise Rejection("project_archived", "项目已归档，恢复以后才能修改") from archived
    except CommandConfigConflict as conflict:
        current = conflict.current or {}
        raise Rejection("stale_base", "登记命令已经被修改，请重新读取以后提交",
                        current_version=current.get("version", 0)) from conflict
    except ValueError as invalid:
        raise Rejection("not_allowed", str(invalid)) from invalid


class SourceDirectorySave(CommandRequest):
    # 登记与修改本项目的源目录：基准版本是该项目源目录登记的版本（初次登记为 0）
    base_version: int
    project_id: str
    name: Text
    path: Text


class SourceDirectoryRefs(Contract):
    name: str
    version: int


def _no_refs(events: list[Event | ProjectEvent]) -> "NoRefs":
    return NoRefs()


async def _save_source_directory(application: "Application", command: Command,
                                 request: SourceDirectorySave) -> None:
    try:
        application.system.projects.configure_source_directory(
            request.project_id, request.name, request.path,
            base_version=request.base_version, command=command)
    except ProjectNotFoundError as missing:
        raise Rejection("not_found", "没有这个项目，请重新读取以后提交") from missing
    except ProjectArchivedError as archived:
        raise Rejection("project_archived", "项目已归档，恢复以后才能修改") from archived
    except SourceDirectoryConflict as conflict:
        current = conflict.current or {}
        raise Rejection("stale_base", "源目录登记已经被修改，请重新读取以后提交",
                        current_version=current.get("version", 0)) from conflict


# ---------------------------------------------------------------------------
# 登记

PROJECT_RENAME = CommandDefinition(
    name="project.rename", request=ProjectRename, refs=NoRefs, handle=_rename_project, derive_refs=_no_refs,
    reasons=("not_found", "stale_base", "project_archived"))
PROJECT_SET_GOAL = CommandDefinition(
    name="project.set_goal", request=ProjectSetGoal, refs=NoRefs, handle=_set_project_goal, derive_refs=_no_refs,
    reasons=("not_found", "stale_base", "project_archived"))
PROJECT_PIN = CommandDefinition(
    name="project.pin", request=ProjectPin, refs=NoRefs, handle=_pin_project, derive_refs=_no_refs,
    reasons=("not_found", "stale_base", "project_archived"))
PROJECT_ARCHIVE = CommandDefinition(
    name="project.archive", request=ProjectArchive, refs=NoRefs, handle=_archive_project, derive_refs=_no_refs,
    reasons=("not_found", "stale_base", "work_item_in_progress"))
PROJECT_RESTORE = CommandDefinition(
    name="project.restore", request=ProjectRestore, refs=NoRefs, handle=_restore_project, derive_refs=_no_refs,
    reasons=("not_found", "stale_base"))
MATERIAL_RECORD = CommandDefinition(
    name="material.record", request=MaterialRecord, refs=NoRefs, handle=_record_material, derive_refs=_no_refs,
    reasons=("not_found", "project_archived", "work_item_in_progress", "not_allowed"))
WORK_ITEM_CREATE = CommandDefinition(
    name="work_item.create", request=WorkItemCreate, refs=WorkItemRefs, handle=_create_work_item,
    derive_refs=_work_item_refs,
    reasons=("not_found", "project_archived", "busy", "provider_unavailable",
             "work_item_in_progress", "not_allowed"))
WORK_ITEM_APPEND_INPUT = CommandDefinition(
    name="work_item.append_input", request=WorkItemAppendInput, refs=NoRefs, handle=_append_input,
    derive_refs=_no_refs, reasons=("not_found", "run_terminal"))
WORK_ITEM_CANCEL = CommandDefinition(
    name="work_item.cancel", request=WorkItemCancel, refs=NoRefs, handle=_cancel_work_item, derive_refs=_no_refs,
    reasons=("not_found", "run_terminal"))
GUIDANCE_SEND = CommandDefinition(
    name="guidance.send", request=GuidanceSend, refs=NoRefs, handle=_send_guidance, derive_refs=_no_refs,
    reasons=("not_found", "run_terminal", "not_allowed"))
DEPARTMENT_SETTINGS_SAVE = CommandDefinition(
    name="department_settings.save", request=DepartmentSettingsSave, refs=DepartmentSettingsSaveRefs,
    handle=_save_department_settings,
    derive_refs=lambda events: DepartmentSettingsSaveRefs(
        reminders=list(events[-1].payload.get("reminders") or ())),
    reasons=("not_found", "stale_base", "project_archived", "not_allowed"))
COMMAND_REGISTRATION_SAVE = CommandDefinition(
    name="command_registration.save", request=CommandRegistrationSave, refs=NoRefs,
    handle=_save_command_registration, derive_refs=_no_refs,
    reasons=("not_found", "stale_base", "project_archived", "not_allowed"))
SOURCE_DIRECTORY_SAVE = CommandDefinition(
    name="source_directory.save", request=SourceDirectorySave, refs=NoRefs, handle=_save_source_directory,
    derive_refs=_no_refs, reasons=("not_found", "stale_base", "project_archived"))
