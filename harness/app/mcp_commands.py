# MCP 服务器设置的命令（工单 #236，网络与 MCP 设计说明第 4.3 节、第 10 节）：
# mcp_servers.save 保存整份设置，带基准版本；版本过期时拒绝并提示重新读取。
# tool_server.probe 读取一台服务器的工具清单（工单 #1174，第 4.2 节）：接受以后作为任务进行，
# 结果以项目流事件 tool_server_probe_finished 出现；探测绑定请求所带的非秘密服务器配置，
# 与保存用同一个归一化与配置摘要（projects.normalize_mcp_servers）。
# 凭据值不进入命令的请求与事件：设置里只写凭据名称（取值时读取当前的凭据来源）。

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..event_store import Command, project_stream
from ..models import Event, ProjectEvent, ProjectEventType
from ..mcp_probe import ProbeOutcome, probe, stderr_log_path_for
from ..projects import (
    McpServersConflict, McpServersInvalid, ProjectArchivedError, ProjectNotFoundError,
    normalize_mcp_servers,
)
from ..write_path import NewProjectEvent
from .commands import Rejection
from .contracts import CommandRequest, Contract, NoRefs
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


# ---------------------------------------------------------------------------
# tool_server.probe（工单 #1174）


class ToolServerProbe(CommandRequest):
    # 探测一台 MCP 服务器（保存前也可以探测）：server 是这台服务器的设置内容（非秘密设置与凭据引用），
    # name 是它在设置里的名称。请求带的配置经与保存同一个归一化，探测绑定归一化后的配置摘要
    project_id: str
    name: str
    server: dict[str, Any]


def _probe_refs(events: list[Event | ProjectEvent]) -> NoRefs:
    return NoRefs()


def _probe_event(name: str, server: dict[str, Any], outcome: ProbeOutcome) -> dict[str, Any]:
    # 探测结果事件的载荷：成功带服务器信息与工具清单快照，失败带原因（已脱敏）。
    # config_digest 是归一化配置的摘要（凭据引用参加，凭据值不参加）
    return {
        "server_name": str(server["name"]), "status": "ok" if outcome.error == "" else "failed",
        "config_digest": str(server["config_digest"]), "server_info": outcome.server_info,
        "tools": list(outcome.tools), "error": outcome.error,
    }


def _probe_snapshot(server: dict[str, Any], outcome: ProbeOutcome) -> dict[str, Any]:
    # 成功探测的工具清单快照（写回设置里这台服务器）：带它绑定的配置摘要，
    # 与待保存配置摘要一致的成功结果才能成为可用快照（设计说明第 4.2 节）
    return {"config_digest": str(server["config_digest"]), "server_info": outcome.server_info,
            "tools": list(outcome.tools)}


def _append_probe_result(application: "Application", project_id: str, payload: dict[str, Any]) -> None:
    # 任务结果：不由命令写入，提出者记为系统（与目录测试事件同一做法）
    application.system.writes.transact(
        project_stream(project_id),
        lambda transaction: transaction.append(
            NewProjectEvent(ProjectEventType.TOOL_SERVER_PROBE_FINISHED, payload, actor="system")))


async def _probe_server(application: "Application", command: Command, request: ToolServerProbe) -> None:
    system = application.system
    try:
        system.projects.projection(request.project_id)
    except ProjectNotFoundError as missing:
        raise Rejection("not_found", "没有这个项目，请重新读取以后提交") from missing
    try:
        document = normalize_mcp_servers({request.name: request.server})
    except McpServersInvalid as invalid:
        raise Rejection("not_allowed", str(invalid)) from invalid
    server = document["servers"][request.name]
    # 结果以后以事件出现的命令：先登记命令身份（与目录的连接测试同一做法，这里登记在项目流），
    # 探测作为任务在服务的事件循环里进行（设计说明第 4.2 节「接受以后作为任务进行」），命令立即接受
    application.system.writes.transact(project_stream(request.project_id), lambda _t: None, command=command)
    application.schedule(_probe_task(application, request.project_id, request.name, server))


async def _probe_task(application: "Application", project_id: str, name: str, server: dict[str, Any]) -> None:
    system = application.system
    outcome = await probe(server, credentials=system.facade.credential_chain(),
                          stderr_log_path=stderr_log_path_for(system.data_dir, name))
    _append_probe_result(application, project_id, _probe_event(name, server, outcome))
    if outcome.error == "":
        # 成功探测把工具清单快照写回设置里这台服务器；设置在探测期间被修改时写回中止，
        # 探测结果只保留在事件里，不得覆盖新配置的可用状态（设计说明第 4.2 节）
        system.projects.record_tool_snapshot(project_id, name, _probe_snapshot(server, outcome))


TOOL_SERVER_PROBE = CommandDefinition(
    name="tool_server.probe", request=ToolServerProbe, refs=NoRefs, handle=_probe_server,
    derive_refs=_probe_refs, reasons=("not_found", "project_archived", "not_allowed"))
