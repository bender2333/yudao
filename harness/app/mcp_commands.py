# MCP 服务器设置的命令（工单 #236，网络与 MCP 设计说明第 4.3 节、第 10 节）：
# mcp_servers.save 保存整份设置，带基准版本；版本过期时拒绝并提示重新读取。
# 凭据值不进入命令的请求与事件：设置里只写凭据名称（取值时读取当前的凭据来源）。

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..event_store import Command
from ..models import Event, ProjectEvent
from ..projects import McpServersConflict, McpServersInvalid, ProjectArchivedError, ProjectNotFoundError
from .commands import Rejection
from .contracts import CommandRequest, Contract
from .registry import CommandDefinition

if TYPE_CHECKING:
    from .application import Application


class McpServersSave(CommandRequest):
    # 保存项目设置里的 MCP 服务器：servers 是名称到服务器设置的整份文档（非秘密设置与凭据引用），
    # base_version 是这份设置的版本（第一次保存为 0）；过期时以 stale_base 拒绝并带当前版本
    project_id: str
    servers: dict[str, Any]


class McpServersSaveRefs(Contract):
    # 保存以后设置的版本与文档摘要：界面据此显示「已提交」，并在事件到达前更新本地的基准版本
    version: int
    document_digest: str


def _mcp_refs(events: list[Event | ProjectEvent]) -> McpServersSaveRefs:
    configured = events[-1]
    return McpServersSaveRefs(version=int(configured.payload["version"]),
                              document_digest=str(configured.payload["document_digest"]))


async def _save_mcp_servers(application: "Application", command: Command,
                            request: McpServersSave) -> None:
    try:
        application.system.projects.configure_mcp_servers(
            request.project_id, request.servers, base_version=request.base_version, command=command)
    except ProjectNotFoundError as missing:
        raise Rejection("not_found", "没有这个项目，请重新读取以后提交") from missing
    except ProjectArchivedError as archived:
        raise Rejection("project_archived", "项目已归档，恢复以后才能修改") from archived
    except McpServersConflict as conflict:
        current = conflict.current or {}
        raise Rejection("stale_base", "MCP 服务器设置已经被修改，请重新读取以后提交",
                        current_version=current.get("version", 0)) from conflict
    except McpServersInvalid as invalid:
        raise Rejection("not_allowed", str(invalid)) from invalid


MCP_SERVERS_SAVE = CommandDefinition(
    name="mcp_servers.save", request=McpServersSave, refs=McpServersSaveRefs, handle=_save_mcp_servers,
    derive_refs=_mcp_refs, reasons=("not_found", "stale_base", "project_archived", "not_allowed"))
