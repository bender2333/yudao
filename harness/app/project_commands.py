# 项目的命令（设计说明第 3.2 节「项目」）。

from __future__ import annotations

from typing import TYPE_CHECKING

from ..event_store import Command
from ..models import Event, ProjectEvent
from .contracts import CommandRequest, Contract, Text
from .registry import CommandDefinition

if TYPE_CHECKING:
    from .application import Application


class ProjectCreate(CommandRequest):
    # 新建项目：新建类命令，没有依据的对象
    base_version: None = None
    name: Text
    goal: Text


class ProjectRefs(Contract):
    project_id: str


async def _create_project(application: Application, command: Command, request: ProjectCreate) -> None:
    application.system.projects.register(request.name, request.goal, command=command)


def _project_refs(events: list[Event | ProjectEvent]) -> ProjectRefs:
    return ProjectRefs(project_id=events[0].project_id)


PROJECT_CREATE = CommandDefinition(
    name="project.create", request=ProjectCreate, refs=ProjectRefs, handle=_create_project,
    derive_refs=_project_refs,
)
