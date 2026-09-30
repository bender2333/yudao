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
from ..projects import (
    CommandConfigConflict, ProjectArchivedError, ProjectNotFoundError, PromptConfigConflict,
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
    run_id = _run_id_for(application, request.work_item_id)
    try:
        projection = application.system.projects.orchestrator.project(run_id)
    except RunNotFoundError as missing:
        raise Rejection("not_found", "没有这个事项，请重新读取以后提交") from missing
    if projection.phase in TERMINAL_PHASES:
        raise Rejection("run_terminal", "事项已经结束，不能再取消")
    application.system.orchestrator.cancel(run_id, command=command)


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
    # 部门 Prompt 部分（模型与档位由 D24 确定）
    base_version: int
    project_id: str
    department: str
    text: Text


async def _save_department_settings(application: "Application", command: Command,
                                    request: DepartmentSettingsSave) -> None:
    if request.department not in DEPARTMENTS:
        raise Rejection("not_allowed", "部门不存在")
    try:
        application.system.projects.configure_prompt(
            request.project_id, request.department, request.text,
            base_version=request.base_version, command=command)
    except ProjectNotFoundError as missing:
        raise Rejection("not_found", "没有这个项目，请重新读取以后提交") from missing
    except ProjectArchivedError as archived:
        raise Rejection("project_archived", "项目已归档，恢复以后才能修改") from archived
    except PromptConfigConflict as conflict:
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


async def _save_command_registration(application: "Application", command: Command,
                                     request: CommandRegistrationSave) -> None:
    try:
        application.system.projects.configure_command(
            request.project_id, request.name, request.argv, args=request.args,
            timeout_sec=request.timeout_sec, output_limit=request.output_limit,
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
    reasons=("not_found", "project_archived", "busy", "provider_unavailable"))
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
    name="department_settings.save", request=DepartmentSettingsSave, refs=NoRefs, handle=_save_department_settings,
    derive_refs=_no_refs, reasons=("not_found", "stale_base", "project_archived", "not_allowed"))
COMMAND_REGISTRATION_SAVE = CommandDefinition(
    name="command_registration.save", request=CommandRegistrationSave, refs=NoRefs,
    handle=_save_command_registration, derive_refs=_no_refs,
    reasons=("not_found", "stale_base", "project_archived", "not_allowed"))
SOURCE_DIRECTORY_SAVE = CommandDefinition(
    name="source_directory.save", request=SourceDirectorySave, refs=NoRefs, handle=_save_source_directory,
    derive_refs=_no_refs, reasons=("not_found", "stale_base", "project_archived"))
