# MCP 工具在事项定义里的形状（网络与 MCP 设计说明第 5.1 节）：名称规则与原名反查。
#
# 事项固定的工具清单快照给出每个工具的原名（可能含点号、大写、连字符等 MCP 允许、静态定义不允许的字符）；
# 模型看到的工具名、事项定义里的键与许可判断用的是同一个**标识**（小写字母、数字与下划线，字母开头），
# 原名只在调用时按映射还原（工单 #1175 第 2 轮，设计说明第 5.1 节）。
# 冲突（与内置或动态工具重名、或两个不同的工具收敛成同一个别名）在装配时拒绝。
# 会话与调用按第 7 节放进本模块的 MCP 会话部分（下一轮），这里只放名称规则与名称表。

import hashlib
import json
import re
from collections.abc import Iterable

from .definitions import DepartmentWork, Role, Tool, WorkItemKind, WorkItems

TOOL_PREFIX = "mcp__"
# 模型接口与静态定义对工具名的长度上限；超过它时改用确定性别名
TOOL_NAME_MAX = 64
# 别名里保留的名称前缀长度：64 - 1（下划线）- 12（摘要）
ALIAS_PREFIX_LENGTH = 51
ALIAS_SUFFIX_LENGTH = 12
# 静态定义里的标识（`harness/definitions/__init__.py` 的 Identifier 是同一个字符集）
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
_DISALLOWED = re.compile(r"[^a-z0-9_]")


class ToolAliasConflict(Exception):
    # 与内置或动态工具重名，或两个不同的工具收敛成同一个别名：拒绝保存（第 5.1 节）
    pass


class UnknownToolAlias(Exception):
    # 别名不在这个事项的名称表里：工具许可拒绝，原因作为工具结果返回（第 5.2 节）
    pass


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
