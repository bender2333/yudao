# MCP 工具在事项定义里的形状（网络与 MCP 设计说明第 5.1 节）：名称规则与原名反查。
#
# 事项固定的工具清单快照给出每个工具的原名（可能含点号等 MCP 允许、模型接口不允许的字符），
# 模型接口看到的是带服务器范围的别名 `mcp__服务器名__工具名`；调用时按别名反查服务器与原工具名
# （工单 #1175）。冲突（与内置或动态工具重名、或两个不同的工具落到同一个别名）在装配时拒绝。
# 会话与调用按第 7 节放进本模块的 MCP 会话部分（下一轮），这里只放名称规则与名称表。

import hashlib
import json
from collections.abc import Iterable

TOOL_PREFIX = "mcp__"
# 模型接口对工具名的长度上限；发生替换或超过它时改用确定性别名
TOOL_NAME_MAX = 64
# 别名里保留的完整名称前缀长度：64 - 1（下划线）- 12（摘要）
ALIAS_PREFIX_LENGTH = 51
ALIAS_SUFFIX_LENGTH = 12
_ALLOWED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")


class ToolAliasConflict(Exception):
    # 名称与内置或动态工具重名，或两个不同的工具落到同一个别名：拒绝保存（第 5.1 节）
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
    """先拼 `mcp__server__tool`，再把不在 `[A-Za-z0-9_-]` 里的字符换成下划线。

    发生替换或完整名称超过 64 个字符时，取拼好名称的前 51 个字符，加下划线，再追加
    `alias_suffix(server, tool)`；两种情况下结果都不超过 64 个字符，且同一个（服务器、工具）
    总是得到同一个别名（第 5.1 节）。
    """
    full = TOOL_PREFIX + server + "__" + tool
    replaced = "".join(char if char in _ALLOWED else "_" for char in full)
    if replaced == full and len(full) <= TOOL_NAME_MAX:
        return full
    return replaced[:ALIAS_PREFIX_LENGTH] + "_" + alias_suffix(server, tool)


class ToolAliases:
    """一个事项里 MCP 工具的名称表：别名到（服务器、原工具名）的映射。

    内置与动态工具的名称在开始时登记为保留名；加入 MCP 工具时按名称规则生成别名，
    与保留名重名、或两个不同的工具落到同一个别名时抛 `ToolAliasConflict`（拒绝保存）。
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
