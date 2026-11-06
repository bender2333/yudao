# 工具登记查询（工单 #1177，网络与 MCP docs/design/network-and-mcp.md「应用层接口」「查询 tools.registry」、docs/design/network-and-mcp.md「系统「工具与扩展」页」；总图第四节「接口」缝）。
# 返回各项目最近的取回记录与各项目的 MCP 服务器（设置、最近一次探测的状态、工具清单），以及内置工具一节
# （工单 #152：Playwright MCP 的版本、浏览器工具与恢复契约、每个工具是否需要图像输入）。
#
# 数据来源（2026-11-03，main 6ad1fd3e；两个前置都已合并）：
# - MCP 服务器的设置、版本与工具清单快照读项目投影的 mcp_servers（工单 #236 的 mcp_servers_configured）。
# - 最近一次探测的状态读项目流事件 tool_server_probe_finished（工单 #1174），按服务器名称取最后一次：
#   投影只留项目里最后一次探测，多台服务器时前面几台的状态会丢，所以按事件读。
# - 取回记录读 run 流的 tool_called 里名称为 fetch_url 的那些（工单 #68 的取回动作）：每个项目的取回动作
#   各占一条，最近的在前。
# - 内置工具一节取自定义（工具与恢复契约）与浏览器模块的版本常量（find_program 只接受这一版，工单 #152）。
#
# 查询只读取：项目流保存的投影与按条件读取的事件，不写入任何内容。结果是快照：position 是这份快照
# 已经包含的最大全局位置，事件流从它之后续上。

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any

from ..browser import MCP_PACKAGE, MCP_VERSION
from ..definitions import DEFINITIONS
from ..models import EventType, ProjectEventType
from ..projects import project_projection
from .contracts import Contract, Snapshot
from .project_queries import McpServerSettingView  # re-export：tools.registry 的服务器视图与 project.settings 同一份口径
from .registry import QueryDefinition

if TYPE_CHECKING:
    from .application import Application

# 每个项目最多给出多少条取回记录。docs/design/network-and-mcp.md「系统「工具与扩展」页」只说要「最近的取回记录」，没有写条数：这一页是只读的
# 汇总，取最近 20 条足够看出近期取回的结果分布，也不让一条长跑的项目把这一页撑大
FETCH_RECORD_LIMIT = 20

# 按位置分批读取事件时每批的条数：与其他查询读事件的做法相同（project_queries._tool_events、
# home._events_in_range 都是 500 或 1000 一批）
_BATCH = 500

# 探测成功时事件载荷里的状态值（mcp_commands._probe_event）
_PROBE_OK = "ok"


class ToolsRegistryProbeState(Contract):
    # 一台 MCP 服务器最近一次探测的状态（docs/design/network-and-mcp.md「读取工具清单（探测）」、docs/design/network-and-mcp.md「系统「工具与扩展」页」）：还没有探测过时
    # 三项都为空。config_digest 是那次探测绑定的配置摘要，与服务器当前的 config_digest 不同时这次结果已经过期
    # （docs/design/network-and-mcp.md「读取工具清单（探测）」：旧结果保留供查询，不得覆盖新配置的可用状态）
    finished_at: str | None = None
    ok: bool | None = None
    error: str | None = None
    config_digest: str = ""


class ToolsRegistryServerView(McpServerSettingView):
    # tools.registry 里的服务器条目：project.settings 的同一份非秘密设置加最近一次探测的状态。
    # 继承保证两边字段一致（名称、传输、对应传输的参数、可以使用的部门、时限与输出上限、
    # 工具清单快照与配置摘要）；凭据只出现名称
    probe: ToolsRegistryProbeState = ToolsRegistryProbeState()


class ToolsRegistryFetchRecord(Contract):
    # 一条取回记录（时间、地址、项目、结果）。项目由它所在的条目给出：at 是取回动作
    # 的时间，url 是动作请求的地址，ok 为假时 error 写明原因（取回失败，或被地址规则与工具许可拒绝）
    at: str = ""
    url: str = ""
    ok: bool | None = None
    error: str | None = None


class ToolsRegistryProject(Contract):
    # 一个项目在工具登记里的条目
    project_id: str
    name: str
    mcp_servers: dict[str, ToolsRegistryServerView]
    # 最近的取回记录，最近的在前，最多 FETCH_RECORD_LIMIT 条
    fetch_records: list[ToolsRegistryFetchRecord] = []


class BuiltinToolView(Contract):
    # 一个内置的浏览器工具（工单 #152；浏览器与 computer use docs/design/browser-and-computer-use.md「提供的工具」、「工具定义的声明」）：恢复契约的核实方法
    # （verification）与取消能否确认停止（cancellable），以及这个工具是否需要图像输入——需要时调用目标
    # 不含图像的请求里不提供它
    name: str
    action: str
    verification: str | None = None
    cancellable: bool | None = None
    requires_image_input: bool = False


class PlaywrightMcpView(Contract):
    # 浏览器工具所用的 Playwright MCP：包名与版本。版本是 browser.find_program 核对的那一版，不另抄一份
    package: str
    version: str


class BuiltinToolsView(Contract):
    # 内置工具一节：Playwright MCP 的版本与浏览器工具清单。屏幕工具属于以后的 computer use 专题
    # （ADR-0026），这一版没有
    playwright_mcp: PlaywrightMcpView
    browser_tools: list[BuiltinToolView]


class ToolsRegistryResult(Contract):
    projects: list[ToolsRegistryProject]
    builtin: BuiltinToolsView


def _events_of(store: Any, project_id: str, types: tuple[str, ...]) -> list[Any]:
    # 一个项目名下指定种类的全部事件，按位置先后：按位置分批读到没有为止（与 project_queries._tool_events
    # 同一做法）。run 流的事件带 run_created 给出的项目，与项目流的事件一起按项目读到
    collected: list[Any] = []
    cursor = 0
    while True:
        batch = store.read(after=cursor, projects=(project_id,), limit=_BATCH, types=types)
        if not batch:
            break
        collected.extend(batch)
        cursor = batch[-1].position
    return collected


def _probe_states(store: Any, project_id: str) -> dict[str, ToolsRegistryProbeState]:
    # 每台服务器最近一次探测的状态：按 server_name 取最后一条 tool_server_probe_finished。
    # 探测成功与失败都留在这里；配置改过以后这一次的结果仍然给出，config_digest 让界面分辨它是否过期
    states: dict[str, ToolsRegistryProbeState] = {}
    for event in _events_of(store, project_id, (ProjectEventType.TOOL_SERVER_PROBE_FINISHED,)):
        payload = event.payload or {}
        error = str(payload.get("error") or "")
        states[str(payload.get("server_name") or "")] = ToolsRegistryProbeState(
            finished_at=event.created_at,
            ok=str(payload.get("status") or "") == _PROBE_OK,
            error=error or None,
            config_digest=str(payload.get("config_digest") or ""),
        )
    return states


def _recent_fetch_records(store: Any, project_id: str) -> list[ToolsRegistryFetchRecord]:
    # 这个项目最近的取回记录，最近的在前：只认名字是 fetch_url 的工具结果（工单 #68 的取回动作，
    # docs/design/network-and-mcp.md「应用层接口」的「事件（run 流）… 调用沿用 tool_started、tool_called」）。边读边丢最旧的，
    # 只留最后 FETCH_RECORD_LIMIT 条；只有开始、还没有结果的取回不在这里（结果未知的动作在 run.actions 里看）
    recent: deque[ToolsRegistryFetchRecord] = deque(maxlen=FETCH_RECORD_LIMIT)
    for event in _events_of(store, project_id, (EventType.TOOL_CALLED,)):
        payload = event.payload or {}
        if payload.get("name") != "fetch_url":
            continue
        recent.append(ToolsRegistryFetchRecord(
            at=event.created_at,
            url=str((payload.get("args") or {}).get("url") or ""),
            ok=bool(payload.get("ok")),
            error=_fetch_error(payload),
        ))
    return list(reversed(recent))


def _fetch_error(payload: dict[str, Any]) -> str | None:
    # 取回没有成功时的原因：被地址规则或工具许可拒绝时是拒绝的原因，其余是动作给出的错误
    refused = payload.get("refused_reason") if payload.get("refused") else None
    error = str(refused or payload.get("error") or "")
    return error or None


def _builtin_tools() -> BuiltinToolsView:
    # 内置工具有哪些、每个的恢复契约与是否需要图像输入，都取自定义（浏览器工具在 browser_tools.json 里）；
    # Playwright MCP 的版本取浏览器模块核对的那一版
    tools = [
        BuiltinToolView(
            name=name,
            action=str(tool.action),
            verification=tool.verification,
            cancellable=tool.cancellable,
            requires_image_input=tool.requires_image_input,
        )
        for name, tool in DEFINITIONS.tools.items() if tool.action == "browser"
    ]
    return BuiltinToolsView(
        playwright_mcp=PlaywrightMcpView(package=MCP_PACKAGE, version=MCP_VERSION),
        browser_tools=tools,
    )


def _tools_registry(application: Application, request: None) -> Snapshot[ToolsRegistryResult]:
    store = application.system.store
    position = store.end_position()
    projects: list[ToolsRegistryProject] = []
    for project_id in store.list_project_ids():
        state = project_projection(store, application.system.artifacts, project_id, include_history=False)
        probes = _probe_states(store, project_id)
        # 非秘密设置从 project.settings 同一来源透出：保存时冻结的工具清单快照与配置摘要原样给出；
        # 探测状态只挂在这个项目当前写明的服务器上（探测过但已经删掉的服务器不再列出）
        servers = {
            name: ToolsRegistryServerView(
                **{field: value for field, value in server.items() if field in McpServerSettingView.model_fields},
                probe=probes.get(name, ToolsRegistryProbeState()),
            )
            for name, server in state.mcp_servers.servers.items()
        }
        projects.append(ToolsRegistryProject(
            project_id=state.project_id, name=state.name, mcp_servers=servers,
            fetch_records=_recent_fetch_records(store, project_id),
        ))
    return Snapshot[ToolsRegistryResult](
        position=position,
        data=ToolsRegistryResult(projects=projects, builtin=_builtin_tools()),
    )


TOOLS_REGISTRY = QueryDefinition(
    name="tools.registry", request=None, result=ToolsRegistryResult, handle=_tools_registry,
    # project_registered 让登记里出现新的项目条目，project_renamed 改变条目里的项目名；
    # mcp_servers_configured 改变服务器的设置与清单；tool_server_probe_finished 改变最近一次探测的状态；
    # tool_started 与 tool_called 是取回动作（#68）的承载事件，结果只在 tool_called 时出现，
    # 两类都登记，开始以后到达的结果不必再改本查询的注册
    changed_by=(ProjectEventType.PROJECT_REGISTERED, ProjectEventType.PROJECT_RENAMED,
                ProjectEventType.MCP_SERVERS_CONFIGURED, ProjectEventType.TOOL_SERVER_PROBE_FINISHED,
                EventType.TOOL_STARTED, EventType.TOOL_CALLED),
)

__all__ = [
    "FETCH_RECORD_LIMIT",
    "BuiltinToolView",
    "BuiltinToolsView",
    "McpServerSettingView",
    "PlaywrightMcpView",
    "TOOLS_REGISTRY",
    "ToolsRegistryFetchRecord",
    "ToolsRegistryProject",
    "ToolsRegistryProbeState",
    "ToolsRegistryResult",
    "ToolsRegistryServerView",
    "_tools_registry",
]
