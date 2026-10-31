# 工具登记查询（工单 #1177，网络与 MCP 设计说明第 10 节「查询 tools.registry」、第 11.3 节；总图第四节「接口」缝）。
# 返回各项目最近的取回记录与各项目的 MCP 服务器（设置、最近一次探测的状态、工具清单）。
#
# 依赖状态（2026-10-31，main 67ee4da0）：
# - #236 已合并：MCP 服务器读项目投影的 mcp_servers（设置、版本、摘要与随设置保存的工具清单快照）。
# - #1174（探测）未合并：事件种类 tool_server_probe_finished 不存在，最近一次探测在这里留合同空位（probe 恒为空），
#   探测记录待 #1174 合并后由它填充（届时补记本文件的查询面）。
# - #68（取回）未合并：工具 fetch_url 不存在，最近取回记录留合同空位（每个项目的 records 恒为空），
#   取回记录待 #68 合并后由它填充。
#
# 查询只读取：项目流保存的投影与按条件读取的事件，不写入任何内容。结果是快照：position 是这份快照
# 已经包含的最大全局位置，事件流从它之后续上。

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import EventType, ProjectEventType
from ..projects import project_projection
from .contracts import Contract, Snapshot
from .project_queries import McpServerSettingView  # re-export：tools.registry 的服务器视图与 project.settings 同一份口径
from .registry import QueryDefinition

if TYPE_CHECKING:
    from .application import Application


class ToolsRegistryProbeState(Contract):
    # 一台 MCP 服务器最近一次探测的状态（设计说明第 10 节「最近一次探测的结果」）：探测由工单 #1174 完成，
    # 合并以前恒为空
    finished_at: str | None = None
    ok: bool | None = None
    error: str | None = None


class ToolsRegistryServerView(McpServerSettingView):
    # tools.registry 里的服务器条目：project.settings 的同一份非秘密设置加最近一次探测的状态。
    # 继承保证两边字段一致（名称、传输、对应传输的参数、可以使用的部门、时限与输出上限、
    # 工具清单快照与配置摘要）；凭据只出现名称
    probe: ToolsRegistryProbeState = ToolsRegistryProbeState()


class ToolsRegistryFetchRecord(Contract):
    # 一条取回记录（设计说明第 11.3 节：时间、地址、项目、结果）。取回动作由工单 #68 完成，
    # 合并以前恒为空
    at: str = ""
    url: str = ""
    ok: bool | None = None


class ToolsRegistryProject(Contract):
    # 一个项目在工具登记里的条目
    project_id: str
    name: str
    mcp_servers: dict[str, ToolsRegistryServerView]
    # 最近的取回记录，最近的在前（#68 合并以前恒为空）
    fetch_records: list[ToolsRegistryFetchRecord] = []


class ToolsRegistryResult(Contract):
    projects: list[ToolsRegistryProject]


def _tools_registry(application: Application, request: None) -> Snapshot[ToolsRegistryResult]:
    store = application.system.store
    position = store.end_position()
    projects: list[ToolsRegistryProject] = []
    for project_id in store.list_project_ids():
        state = project_projection(store, application.system.artifacts, project_id, include_history=False)
        # 非秘密设置从 project.settings 同一来源透出：保存时冻结的工具清单快照与配置摘要原样给出
        servers = {
            name: ToolsRegistryServerView(
                **{field: value for field, value in server.items() if field in McpServerSettingView.model_fields},
                probe=ToolsRegistryProbeState(),
            )
            for name, server in state.mcp_servers.servers.items()
        }
        projects.append(ToolsRegistryProject(
            project_id=state.project_id, name=state.name, mcp_servers=servers,
            # 取回记录待 #68 合并后由它填充：取回动作经 tool_started/tool_called 写事件，这里按事件读取
            fetch_records=[],
        ))
    return Snapshot[ToolsRegistryResult](position=position, data=ToolsRegistryResult(projects=projects))


TOOLS_REGISTRY = QueryDefinition(
    name="tools.registry", request=None, result=ToolsRegistryResult, handle=_tools_registry,
    # project_registered 让登记里出现新的项目条目，project_renamed 改变条目里的项目名；
    # mcp_servers_configured 改变服务器的设置与清单；
    # tool_started 与 tool_called 是取回动作（#68）的承载事件：它们合并以后改变取回记录，
    # 这里先登记，#68 不必再改本查询的注册（#68 合并以前这两类到达只引起多余重查，结果不变）
    changed_by=(ProjectEventType.PROJECT_REGISTERED, ProjectEventType.PROJECT_RENAMED,
                ProjectEventType.MCP_SERVERS_CONFIGURED, EventType.TOOL_STARTED, EventType.TOOL_CALLED),
)

__all__ = [
    "McpServerSettingView",
    "TOOLS_REGISTRY",
    "ToolsRegistryFetchRecord",
    "ToolsRegistryProject",
    "ToolsRegistryProbeState",
    "ToolsRegistryResult",
    "ToolsRegistryServerView",
    "_tools_registry",
]
