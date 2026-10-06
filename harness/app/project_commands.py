# 项目的命令（设计说明第 3.2 节「项目」）。

from __future__ import annotations

from typing import TYPE_CHECKING

from ..event_store import Command
from ..models import Event, ProjectEvent
from ..projects import (
    OnboardingNotAllowedError,
    ProjectArchivedError,
    ProjectNotFoundError,
    SourceDirectoryNotFoundError,
    WorkItemInProgressError,
)
from ..public_tree import TreeError
from .commands import Rejection
from .contracts import CommandRequest, Contract, Text
from .registry import CommandDefinition

if TYPE_CHECKING:
    from .application import Application

class ProjectCreate(CommandRequest):
    # 新建项目：新建类命令，没有依据的对象
    # initial_directory 是可选的起点文件夹（控制主机上的文件夹路径，工单 #321）：
    # 它的快照成为项目的起点文件，不建档，项目来源仍是 idea；不可读或含宿主私有路径时以 source_invalid 拒绝
    base_version: None = None
    name: Text
    goal: Text
    initial_directory: Text | None = None

class ProjectRefs(Contract):
    project_id: str

async def _create_project(application: Application, command: Command, request: ProjectCreate) -> None:
    try:
        application.system.projects.register(request.name, request.goal,
                                            initial_directory=request.initial_directory, command=command)
    except TreeError as invalid:
        raise Rejection("source_invalid", str(invalid)) from invalid

def _project_refs(events: list[Event | ProjectEvent]) -> ProjectRefs:
    return ProjectRefs(project_id=events[0].project_id)


class ProjectOnboard(CommandRequest):
    # 接入已有项目：新建项目、登记源目录、采集代码快照、开始建档事项（3.8 第 3.1 节）
    base_version: None = None
    name: Text
    goal: Text
    source_name: Text
    source_path: Text

class OnboardRefs(Contract):
    project_id: str
    work_item_id: str
    run_id: str

def _onboard_refs(events: list[Event | ProjectEvent]) -> OnboardRefs:
    # 这个命令在一个项目流事务中追加 project_registered、source_directory_configured 与 work_item_created
    registered, _directory, created = events[:3]
    return OnboardRefs(
        project_id=registered.project_id, work_item_id=created.payload["work_item_id"],
        run_id=created.payload["run_id"])

async def _onboard_project(application: Application, command: Command, request: ProjectOnboard) -> None:
    system = application.system
    # 3.4A 之前只有一个执行槽位：已有事项在执行时拒绝（与 work_item.create 相同）
    if system.orchestrator.busy():
        raise Rejection("busy", "已有事项正在执行，等它结束以后才能接入项目")
    status = system.provider_status()
    if not status.get("available", False):
        raise Rejection("provider_unavailable", status.get("message") or "模型调用目标不可用")
    try:
        _project_id, _work_item_id, run_id = system.projects.onboard(
            request.name, request.goal, request.source_name, request.source_path, command=command)
    except TreeError as invalid:
        raise Rejection("source_invalid", str(invalid)) from invalid
    # 建档 run 由流程编排在接口进程的事件循环中作为任务运行
    system.orchestrator.start_work_item(run_id)

class OnboardingRestart(CommandRequest):
    # 重新开始建档：从登记的源目录重新采集快照，开始新的建档事项（3.8 第 3.1 节）
    base_version: None = None
    project_id: str
    source_name: Text

def _restart_refs(events: list[Event | ProjectEvent]) -> OnboardRefs:
    created = events[0]
    return OnboardRefs(project_id=created.project_id, work_item_id=created.payload["work_item_id"],
                       run_id=created.payload["run_id"])

async def _restart_onboarding(application: Application, command: Command, request: OnboardingRestart) -> None:
    system = application.system
    if system.orchestrator.busy():
        raise Rejection("busy", "已有事项正在执行，等它结束以后才能重新开始建档")
    status = system.provider_status()
    if not status.get("available", False):
        raise Rejection("provider_unavailable", status.get("message") or "模型调用目标不可用")
    try:
        _work_item_id, run_id = system.projects.restart_onboarding(
            request.project_id, request.source_name, command=command)
    except ProjectNotFoundError as missing:
        raise Rejection("not_found", "没有这个项目，请重新读取以后提交") from missing
    except ProjectArchivedError as archived:
        raise Rejection("project_archived", "项目已归档，恢复以后才能重新开始建档") from archived
    except SourceDirectoryNotFoundError as missing:
        raise Rejection("not_found", "没有这个源目录登记，请重新读取以后提交") from missing
    except WorkItemInProgressError as busy:
        raise Rejection("not_allowed", "项目正在建档，结束或取消以后才能重新开始") from busy
    except OnboardingNotAllowedError as invalid:
        raise Rejection("not_allowed", str(invalid)) from invalid
    except TreeError as invalid:
        raise Rejection("source_invalid", str(invalid)) from invalid
    system.orchestrator.start_work_item(run_id)

PROJECT_CREATE = CommandDefinition(
    name="project.create", request=ProjectCreate, refs=ProjectRefs, handle=_create_project,
    derive_refs=_project_refs, reasons=("source_invalid",),
)
PROJECT_ONBOARD = CommandDefinition(
    name="project.onboard", request=ProjectOnboard, refs=OnboardRefs, handle=_onboard_project,
    derive_refs=_onboard_refs, reasons=("source_invalid", "busy", "provider_unavailable"))
ONBOARDING_RESTART = CommandDefinition(
    name="onboarding.restart", request=OnboardingRestart, refs=OnboardRefs, handle=_restart_onboarding,
    derive_refs=_restart_refs,
    reasons=("not_found", "project_archived", "not_allowed", "source_invalid", "busy", "provider_unavailable"))
