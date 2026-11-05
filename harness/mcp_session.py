# MCP 工具在事项定义里的形状（网络与 MCP 设计说明第 5.1 节）：名称规则与原名反查。
#
# 事项固定的工具清单快照给出每个工具的原名（可能含点号、大写、连字符等 MCP 允许、静态定义不允许的字符）；
# 模型看到的工具名、事项定义里的键与许可判断用的是同一个**标识**（小写字母、数字与下划线，字母开头），
# 原名只在调用时按映射还原（工单 #1175 第 2 轮，设计说明第 5.1 节）。
# 冲突（与内置或动态工具重名、或两个不同的工具收敛成同一个别名）在装配时拒绝。
# 第 7 节的会话部分也在这里（工单 #1175 第 8 轮）：`McpSessions` 管每个 run 每台服务器一个会话实例，
# 从冻结的设置文档（item_definitions 读的同一份）组出启动参数，`call` 经客户端调用并交回已脱敏的结果；
# run 之间与跨 run 的生命周期（持久化生命周期事件、遗留进程、取消后的结果未知处理）归工单 #1176。

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from .definitions import DepartmentWork, Role, Tool, WorkItemKind, WorkItems
from .mcp_client import McpClient, McpStartupError, ServerLaunch, terminate_legacy_process
from .models import EventType

TOOL_PREFIX = "mcp__"
# 模型接口与静态定义对工具名的长度上限；超过它时改用确定性别名
TOOL_NAME_MAX = 64
# 别名里保留的名称前缀长度：64 - 1（下划线）- 12（摘要）
ALIAS_PREFIX_LENGTH = 51
ALIAS_SUFFIX_LENGTH = 12
# 静态定义里的标识（`harness/definitions/__init__.py` 的 Identifier 是同一个字符集）
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
_DISALLOWED = re.compile(r"[^a-z0-9_]")
# MCP 动作在执行环境里的分派键（environment.py 的 _PROCESSES["mcp"]）：分派按动作类别进入这里，
# 再按这个键取处理方法；静态定义里没有任何环境工具用这个名字，冲突不可能发生
MCP_DISPATCH_TOOL = "mcp"
# 轮询取消信号与调用时限的间隔（秒）：取消从另一条线程的 Event 到达，轮询把它转给客户端的取消
_CANCEL_POLL_SEC = 0.1
# 调用超时或取消以后的错误码：这一次尝试没有完整结果，按结果未知交还发出它的会话（设计说明第 7.3、8 节）
CANCELLED_CODE = "cancelled"
# 会话关闭的原因（写进 mcp_server_closed 的载荷）：run 收尾、超时或取消以后关闭、启动时结束遗留进程
CLOSE_ON_RUN_END = "closed"
CLOSE_AFTER_CANCEL = "cancelled"
CLOSE_LEFTOVER = "leftover"
# 生命周期事件写到 run 流的接口：种类与载荷，由装配一方给出写入口（orchestrator 的 run 流）
EventSink = Callable[[str, dict[str, Any]], None]


class ToolAliasConflict(Exception):
    # 与内置或动态工具重名，或两个不同的工具收敛成同一个别名：拒绝保存（第 5.1 节）
    pass


class UnknownToolAlias(Exception):
    # 别名不在这个事项的名称表里：工具许可拒绝，原因作为工具结果返回（第 5.2 节）
    pass


class McpRefused(Exception):
    # 这次 MCP 调用被拒绝（别名不在冻结设置带来的名称表里）：原因作为工具结果交回模型（第 5.2 节）
    pass


@dataclass(frozen=True)
class McpOutcome:
    # 一次 MCP 调用的结果（第 7.3 节）：回执与保存外部来源工件要用的两部分。
    # result_text 已把凭据值替换为星号（客户端一侧），调用目标的模型直接读它；
    # is_error 的调用记为已完成的动作，错误文本在 result_text 里
    result_text: str
    is_error: bool
    error_code: str | None
    structured: object
    elapsed_ms: int
    server: str
    tool: str
    transport: str


def alias_suffix(server: str, tool: str) -> str:
    # 服务器名与原工具名组成的规范 JSON 的 SHA-256 前 12 个十六进制字符：
    # 键序与空白不影响结果（ensure_ascii=False 保留原名里的非 ASCII 字符）
    canonical = json.dumps([server, tool], ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:ALIAS_SUFFIX_LENGTH]


def tool_alias(server: str, tool: str) -> str:
    """先拼 `mcp__server__tool`，再收敛成标识：小写，不在 `[a-z0-9_]` 里的字符换成下划线。

    收敛以后超过 64 个字符时，取前 51 个字符、加下划线、追加 `alias_suffix(server, tool)`；
    结果总是标识（前缀 `mcp__` 以字母开头），且同一个（服务器、工具）总是得到同一个别名。
    两个不同的工具收敛成同一个别名时不在这里改名：由 `ToolAliases.add` 拒绝（第 5.1 节）。
    """
    name = _DISALLOWED.sub("_", (TOOL_PREFIX + server + "__" + tool).lower())
    if len(name) > TOOL_NAME_MAX:
        name = name[:ALIAS_PREFIX_LENGTH] + "_" + alias_suffix(server, tool)
    return name


class ToolAliases:
    """一个事项里 MCP 工具的名称表：别名到（服务器、原工具名）的映射。

    内置与动态工具的名称在开始时登记为保留名；加入 MCP 工具时按名称规则生成别名，
    与保留名重名、或两个不同的工具收敛成同一个别名时抛 `ToolAliasConflict`（拒绝保存）。
    """

    def __init__(self, reserved: Iterable[str] = ()) -> None:
        self._reserved = set(reserved)
        self._aliases: dict[str, tuple[str, str]] = {}

    def add(self, server: str, tool: str) -> str:
        alias = tool_alias(server, tool)
        existing = self._aliases.get(alias)
        if existing is not None:
            if existing != (server, tool):
                raise ToolAliasConflict(
                    f"别名 {alias} 已经是 {existing[0]} 的 {existing[1]}，不能再给 {server} 的 {tool}")
            return alias
        if alias in self._reserved:
            raise ToolAliasConflict(f"别名 {alias}（{server} 的 {tool}）与内置工具重名，拒绝保存")
        self._aliases[alias] = (server, tool)
        return alias

    def original(self, alias: str) -> tuple[str, str]:
        try:
            return self._aliases[alias]
        except KeyError:
            raise UnknownToolAlias(f"工具 {alias} 不在这个事项的工具定义里") from None

    def aliases(self) -> dict[str, tuple[str, str]]:
        return dict(self._aliases)


def item_definitions(base, document):
    """把事项冻结的 MCP 设置叠加到当前定义上，得到这个事项的定义副本。

    document 是 
un_created 里冻结的那份 MCP 设置（非秘密设置与凭据引用的整份文档，
    见设计说明第 4.3 节），ase 是当前定义。规则（第 5.1 节）：

    - 只用工具清单快照，且快照的配置摘要必须与这台服务器的配置摘要一致；没有快照或摘要不符的
      服务器不提供工具（本函数不探测）。
    - 每个工具按名称规则得到标识别名，作为工具定义的键；原名只在调用时经 ToolAliases.original 还原。
      工具的动作类别是 mcp：核实方法是 
one，取消能否确认停止按传输方式（stdio 能确认）。
    - 只给服务器设置里写明的部门：别名追加到这些部门的角色工具清单与每一种事项种类的工具清单，
      其他部门看不到它。
    - 没有 MCP 设置、或没有可用快照时返回 ase 本身（副本与当前定义等价，第 4.3 节「旧事项按空设置读取」）。
    """
    servers = (document or {}).get("servers") or {}
    aliases = ToolAliases(reserved=tuple(base.tools))
    tools = dict(base.tools)
    additions: dict[str, list[str]] = {}
    for key, server in servers.items():
        snapshot = server.get("tool_snapshot") or {}
        if not snapshot or snapshot.get("config_digest") != server.get("config_digest", ""):
            continue
        server_name = str(server.get("name") or key)
        for spec in snapshot.get("tools") or []:
            alias = aliases.add(server_name, str(spec.get("name") or ""))
            tools[alias] = Tool(kind="environment", action="mcp", verification="none",
                                cancellable=str(server.get("transport") or "stdio") == "stdio",
                                description=str(spec.get("description") or alias),
                                parameters=spec.get("input_schema") or {})
            for department in server.get("departments") or []:
                additions.setdefault(str(department), []).append(alias)
    if not additions:
        return base
    roles = {name: Role(**{**role.model_dump(), "tools": tuple(role.tools) + tuple(additions.get(name, ()))}) 
             for name, role in base.roles.items()}
    kinds = {}
    for kind_name, kind in base.work_items.kinds.items():
        departments = {}
        changed = False
        for department, work in kind.departments.items():
            extra = tuple(additions.get(department, ()))
            if extra:
                changed = True
                departments[department] = DepartmentWork(**{**work.model_dump(), "tools": tuple(work.tools) + extra})
            else:
                departments[department] = work
        kinds[kind_name] = (WorkItemKind(**{**kind.model_dump(), "departments": departments})
                            if changed else kind)
    work_items = WorkItems(**{**base.work_items.model_dump(), "kinds": kinds})
    fields = {name: getattr(base, name) for name in type(base).model_fields}
    fields.update({"tools": tools, "roles": roles, "work_items": work_items})
    return type(base)(**fields)


# ---------------------------------------------------------------------------
# MCP 会话（第 7.2、7.3 节，工单 #1175 第 8 轮）：一个 run 一张表，每台服务器一个会话实例。
#


@dataclass(frozen=True)
class _ServerLaunchPlan:
    # 一台服务器的一次启动参数：从冻结设置组出的启动参数与它的凭据值（已按名称解析）。
    # launch.secrets 带着这些值：错误文本与结果在客户端一侧替换为星号，值不进入事件与日志
    launch: ServerLaunch


class McpSessions:
    """一个 run 的 MCP 会话表（第 7.2 节）：每台服务器一个实例，第一次调用时启动。

    document 是 run_created 里冻结的那份 MCP 设置（与 `item_definitions` 读同一份）；
    credentials 是控制主机的凭据来源（调用时按名称取值），stderr_dir 放标准错误输出的日志文件。
    关闭（run 结束、暂停或停止）之前建立的会话一直复用；已经关闭过的会话按同一台服务器重新建立。
    run 之间、项目之间不共享：一张表只属于一个 run。
    """

    def __init__(self, document: dict | None, *, credentials, stderr_dir,
                 events: EventSink | None = None) -> None:
        self._document = document or {}
        self._credentials = credentials
        self._stderr_dir = str(stderr_dir)
        self._sessions: dict[str, McpClient] = {}
        # 生命周期事件的写入方（工单 #1176）：没有给时只维护会话表，不写事件（单一模块的用例）；
        # 写入口一侧负责把写入失败记下来，不打断会话的建立与关闭
        self._events = events

    def server_names(self) -> list[str]:
        # 冻结设置里的服务器名称（非秘密的名称，可以有）
        return sorted(str(server.get("name") or key) for key, server in (self._document.get("servers") or {}).items())

    def original(self, alias: str) -> tuple[str, str]:
        # 别名反查（服务器、原工具名）：按冻结设置里的可用快照重建名称表（与 item_definitions
        # 叠加定义副本用的是同一条名称规则，第 5.1 节）。没有冻结设置、或别名不在其中
        # （例如别的工具名）时抛 UnknownToolAlias，执行环境据此拒绝
        aliases = ToolAliases()
        for server in (self._document.get("servers") or {}).values():
            snapshot = server.get("tool_snapshot") or {}
            if not snapshot or snapshot.get("config_digest") != server.get("config_digest", ""):
                continue
            server_name = str(server.get("name") or "")
            for spec in snapshot.get("tools") or []:
                try:
                    aliases.add(server_name, str(spec.get("name") or ""))
                except ToolAliasConflict:
                    # 名称冲突在事项创建叠加定义副本时已经拒绝：这里跳过坏项，让可用的工具仍可反查
                    continue
        return aliases.original(alias)

    @property
    def open(self) -> bool:
        return bool(self._sessions)

    def sessions(self) -> dict[str, McpClient]:
        return dict(self._sessions)

    async def call(self, alias: str, server: str, tool: str, arguments: dict | None,
                   *, stop=None) -> McpOutcome:
        # 一次 MCP 调用（第 7.2、7.3 节）：按原名调这台服务器的工具，工具失败（is_error）交回错误文本，
        # 动作记为已完成；协议错误与启动失败是失败的动作，原因写明（凭据值已替换为星号）。
        # stop 是执行环境的取消信号：到达时取消这次调用（进程已结束时能确认停止）。
        # 超时与取消没有完整结果：先取消，再按结果未知交还发出它的会话（第 8 节，工单 #1176）
        try:
            client = await self._session_for(server)
        except McpRefused as refusal:
            # 服务器不在这份冻结设置里、或缺凭据等组装失败：失败的动作，原因交回模型，
            # 生命周期记一条 mcp_server_failed（这一次会话没有建立）
            transport = self._transport_of(server)
            self._record_failed(server, transport, str(refusal))
            return self._failure_outcome(alias, server, transport, str(refusal), "startup_failed")
        except McpStartupError as failure:
            # 启动失败的 mcp_server_failed 由 _session_for 写下（它知道这次会话用的传输）
            return self._failure_outcome(alias, server, self._transport_of(server), str(failure),
                                         "startup_failed")
        try:
            return await self._call_once(client, alias, server, tool, arguments, stop=stop)
        except McpStartupError as failure:
            return self._failure_outcome(alias, server, client.launch.transport,
                                         str(failure), "startup_failed")
        except Exception as exc:  # 协议错误与其他调用失败：失败的动作，原因写明
            reason = _redacted(str(exc) or exc.__class__.__name__, client.launch.secrets)
            code = getattr(exc, "code", None)
            return self._failure_outcome(alias, server, client.launch.transport,
                                         reason, str(code) if code is not None else "call_failed")

    async def close(self) -> None:
        # run 结束、暂停或停止时关闭全部会话（stdio 先关标准输入，SDK 等待以后结束进程树；HTTP 关闭会话），
        # 每关闭一台写一条 mcp_server_closed（第 7.2 节）：关闭以后调用方在事件里读得到这件事
        sessions, self._sessions = self._sessions, {}
        for name, client in sessions.items():
            try:
                await client.close()
            finally:
                self._record_closed(name, client, CLOSE_ON_RUN_END)

    # ---- 内部 ----

    def _record(self, event_type: str, payload: dict[str, Any]) -> None:
        # 生命周期事件（第 7.2 节）：种类与载荷交给装配一方给出的写入方。
        # 没有给写入方时什么也不写（单一模块的用例按会话表本身核对行为）
        if self._events is None:
            return
        self._events(event_type, payload)

    def _record_closed(self, server_name: str, client: McpClient, reason: str, *,
                       ended: bool = False) -> None:
        self._record(EventType.MCP_SERVER_CLOSED, {
            "server": server_name, "transport": client.launch.transport, "reason": reason,
            "pid": client.pid, "create_time": client.process_create_time, "ended": ended,
        })

    def _record_failed(self, server_name: str, transport: str, error: str) -> None:
        self._record(EventType.MCP_SERVER_FAILED, {
            "server": server_name, "transport": transport, "error": error,
        })

    def _plan(self, server_name: str) -> _ServerLaunchPlan:
        # 冻结设置里这台服务器的启动参数：凭据按名称在开始时取值，值只进客户端的脱敏清单
        servers = self._document.get("servers") or {}
        match = next((server for server in servers.values()
                      if str(server.get("name") or "") == server_name), None)
        if match is None:
            raise McpRefused(f"MCP 服务器 {server_name} 不在这个事项冻结的设置里")
        from .mcp_probe import launch_for, stderr_log_path_for

        try:
            launch = launch_for(match, credentials=self._credentials,
                                stderr_log_path=stderr_log_path_for(self._stderr_dir, server_name))
        except McpStartupError as failure:
            raise McpRefused(str(failure)) from failure
        return _ServerLaunchPlan(launch=launch)

    def _transport_of(self, server_name: str) -> str:
        # 冻结设置里这台服务器的传输（启动失败时客户端还没有建立，事件里照样要写传输）
        for server in (self._document.get("servers") or {}).values():
            if str(server.get("name") or "") == server_name:
                return str(server.get("transport") or "stdio")
        return "stdio"

    async def _session_for(self, server_name: str) -> McpClient:
        client = self._sessions.get(server_name)
        if client is not None:
            return client
        plan = self._plan(server_name)
        try:
            client = await McpClient.start(plan.launch)
        except McpStartupError as failure:
            # 启动或连接失败：写 mcp_server_failed，原因带标准错误输出的末尾部分（凭据值已替换为星号）
            self._record_failed(server_name, plan.launch.transport, str(failure))
            raise
        self._sessions[server_name] = client
        self._record(EventType.MCP_SERVER_STARTED, {
            "server": server_name, "transport": client.launch.transport,
            "pid": client.pid, "create_time": client.process_create_time,
        })
        return client

    async def _call_once(self, client: McpClient, alias: str, server: str, tool: str,
                         arguments: dict | None, *, stop) -> McpOutcome:
        # 调用在**这个任务**里进行（工单 #1176）：SDK 的会话由建立它的任务关闭，超时或取消以后
        # 客户端会关闭会话（`_cancelled_result`），换一个任务关闭会在 anyio 的取消范围上报错、
        # 并把调用方一起取消掉。取消信号因此不取消这个任务，而是交给客户端的 `cancel()`
        # （它取消 SDK 的调用任务，SDK 发出取消通知），本任务照常等到取消结果
        watcher = None if stop is None else asyncio.ensure_future(_cancel_when_stopped(client, stop))
        try:
            result = await client.call_tool(tool, arguments or {})
        finally:
            if watcher is not None and not watcher.done():
                watcher.cancel()
        # 结果文本与结构化输出都把凭据值替换为星号再保存（设计说明第 4.4 节：
        # 「保存的标准错误输出、错误文本与结果文本在写入之前，把已取得的凭据值替换为星号」）
        if result.cancelled:
            # 超时或被取消：客户端已经先发取消通知、等应答最多 10 秒，stdio 随后结束整个进程树，
            # HTTP 关闭会话（第 7.2、8 节，工单 #1176）。这一次没有完整结果：按结果未知交还发出它的
            # 会话，回执写明取消能否确认。会话已经关闭，从表里去掉，下一次调用按同一台服务器重新建立
            self._sessions.pop(server, None)
            self._close_after_cancel(server, client)
            text = _cancelled_text(server, tool, bool(result.cancel_confirmed),
                                   _redacted(result.text, client.launch.secrets))
            return McpOutcome(result_text=text, is_error=True, error_code=CANCELLED_CODE,
                              structured=None, elapsed_ms=result.elapsed_ms, server=server,
                              tool=tool, transport=client.launch.transport)
        text = _redacted(result.text, client.launch.secrets)
        structured = _redacted_value(result.structured_content, client.launch.secrets)
        if isinstance(structured, (dict, list)) and structured:
            text = text + "\n" + json.dumps(structured, ensure_ascii=False) if text else json.dumps(
                structured, ensure_ascii=False)
        return McpOutcome(result_text=text, is_error=bool(result.is_error),
                          error_code=result.error_code, structured=structured,
                          elapsed_ms=result.elapsed_ms, server=server, tool=tool,
                          transport=client.launch.transport)

    def _close_after_cancel(self, server: str, client: McpClient) -> None:
        # 客户端关闭会话时已经结束了进程树（stdio，进程已不在）或终止了会话（HTTP，服务器那边无法确认）：
        # 补写关闭事件，原因写明这一次是超时或取消以后关闭的
        self._record_closed(server, client, CLOSE_AFTER_CANCEL,
                            ended=client.launch.transport == "stdio")

    def _failure_outcome(self, alias: str, server: str, transport: str,
                         reason: str, code: str) -> McpOutcome:
        started = time.monotonic()
        return McpOutcome(result_text=reason, is_error=True, error_code=code, structured=None,
                          elapsed_ms=0, server=server, tool=alias, transport=transport)


async def _cancel_when_stopped(client: McpClient, stop) -> None:
    # 取消信号到达：交给客户端的 cancel（它取消 SDK 的调用任务，SDK 发出取消通知并等应答）。
    # 这里不取消调用所在的任务：会话的关闭必须发生在建立它的那个任务里（工单 #1176）
    while not stop.is_set():
        await asyncio.sleep(_CANCEL_POLL_SEC)
    await client.cancel()


def _cancelled_text(server: str, tool: str, confirmable: bool, client_text: str) -> str:
    # 超时或取消以后的工具结果（设计说明第 8 节，工单 #1176）：写明已经先取消、取消能否确认服务器停止，
    # 以及这一次尝试执行被中断、结果未知；由发出这次调用的会话决定是否重新调用（没有自动重试）
    confirmation = ("能确认服务器已停止（stdio 服务器随后结束整个进程树）" if confirmable
                    else "不能确认服务器已停止（HTTP 会话已关闭，服务器端已处理的请求无法撤回）")
    lines = [f"MCP 调用没有完整结果：服务器 {server} 的工具 {tool} 超时或被取消。",
             f"已发出取消通知，等服务器应答最多 10 秒；取消{confirmation}。",
             "执行被中断，结果未知：这次尝试没有保存为外部来源工件的结果，由发出这次调用的会话决定是否重新调用。"]
    if client_text.strip():
        lines.append(client_text.strip())
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 遗留的服务器进程（第 7.2 节，工单 #1176）：Yudao 启动时结束没有关闭记录的进程，补写 mcp_server_closed。


@dataclass(frozen=True)
class LeftoverServer:
    # 一条没有关闭记录的启动：哪个 run 的哪台服务器，以及它记录的进程标识与创建时间（HTTP 没有进程）
    run_id: str
    server: str
    transport: str
    pid: int | None
    create_time: float | None


# 按（run、服务器名称）配对的两类事件：启动与关闭。启动以后的关闭记录一到就配成一对
_LEFTOVER_TYPES = (EventType.MCP_SERVER_STARTED, EventType.MCP_SERVER_CLOSED)
# 一次读多少条：按种类过滤、按位置翻页，不把全部事件读进内存
_LEFTOVER_PAGE = 1000


def leftover_servers(store, *, limit: int = _LEFTOVER_PAGE) -> list[LeftoverServer]:
    """有启动记录、没有关闭记录的服务器（按（run、服务器名称）配对，先启动先配对）。

    Yudao 启动时用这份清单结束遗留的服务器进程并补写关闭事件（设计说明第 7.2 节）：
    进程崩溃时关闭事件没有写下来，服务器进程可能还活着；同一台服务器在一个 run 里可以
    启动与关闭多次，所以按启动的先后一一配对，不按服务器名称去重。
    """
    open_starts: dict[tuple[str, str], list[dict[str, Any]]] = {}
    after = 0
    while True:
        batch = store.read(after, types=_LEFTOVER_TYPES, limit=limit)
        if not batch:
            break
        for event in batch:
            after = max(after, int(event.position))
            payload = event.payload or {}
            key = (str(event.run_id or ""), str(payload.get("server") or ""))
            if event.type == EventType.MCP_SERVER_STARTED:
                open_starts.setdefault(key, []).append(payload)
                continue
            pending = open_starts.get(key)
            if pending:
                pending.pop(0)
    return [LeftoverServer(run_id=run_id, server=server,
                           transport=str(payload.get("transport") or "stdio"),
                           pid=payload.get("pid"), create_time=payload.get("create_time"))
            for (run_id, server), pending in open_starts.items() for payload in pending]


def end_leftover_server(leftover: LeftoverServer) -> bool:
    """按进程标识与创建时间结束遗留的服务器进程；HTTP 没有进程标识，没有要结束的进程。

    两项都对得上才结束（进程标识可能已经被别的进程复用），整棵进程树一起结束。
    返回是否真的结束了仍然存活的进程。
    """
    if leftover.pid is None or leftover.create_time is None:
        return False
    return terminate_legacy_process(int(leftover.pid), float(leftover.create_time))


def _redacted(text: str, secrets) -> str:
    from .mcp_client import redact

    return redact(text, tuple(secrets or ()))


def _redacted_value(value: object, secrets) -> object:
    # 结构化输出里的凭据值递归替换为星号（与客户端对 structuredContent 的替换同一做法）
    if isinstance(value, str):
        return _redacted(value, secrets)
    if isinstance(value, dict):
        return {key: _redacted_value(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_redacted_value(item, secrets) for item in value]
    return value
