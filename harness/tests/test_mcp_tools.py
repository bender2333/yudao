# MCP 工具在事项定义里的名称规则（网络与 MCP 设计说明第 5.1 节，工单 #1175）。
# 守 R2：别名是模型接口看到的工具名，规则确定、可反查，冲突必须拒绝而不是静默改名。
# 守 R3：第 5.1 节写明的拼接、替换、超长前缀与摘要规则。

import harness.mcp_session as mcp_session


def test_allowed_names_keep_the_server_and_tool_name():
    assert mcp_session.tool_alias("fs", "read_file") == "mcp__fs__read_file"
    assert mcp_session.tool_alias("my-server", "list-items") == "mcp__my-server__list-items"


def test_disallowed_characters_are_replaced_and_get_a_deterministic_suffix():
    tool = "read.file"
    alias = mcp_session.tool_alias("fs", tool)
    assert len(alias) <= mcp_session.TOOL_NAME_MAX
    full = "mcp__fs__read_file"
    assert alias == full[:mcp_session.ALIAS_PREFIX_LENGTH] + "_" + mcp_session.alias_suffix("fs", tool)
    # 同一个（服务器、工具）总是得到同一个别名；不替换的名称不受影响
    assert alias == mcp_session.tool_alias("fs", tool)
    assert mcp_session.tool_alias("other", "read_file") == "mcp__other__read_file"


def test_long_names_use_the_prefix_and_suffix_rule():
    tool = "t" * 80
    alias = mcp_session.tool_alias("server", tool)
    full = ("mcp__server__" + tool)[:mcp_session.ALIAS_PREFIX_LENGTH]
    assert alias == full + "_" + mcp_session.alias_suffix("server", tool)
    assert len(alias) == mcp_session.TOOL_NAME_MAX


def test_two_long_names_sharing_the_prefix_get_different_aliases():
    first = mcp_session.tool_alias("server", "a" * 80)
    second = mcp_session.tool_alias("server", "a" * 79 + "b")
    assert first != second
    assert first[:mcp_session.ALIAS_PREFIX_LENGTH] == second[:mcp_session.ALIAS_PREFIX_LENGTH]


def test_aliases_look_up_the_server_and_original_tool():
    aliases = mcp_session.ToolAliases(reserved=("write_file", "run_check"))
    alias = aliases.add("fs", "read.file")
    assert alias == mcp_session.tool_alias("fs", "read.file")
    assert aliases.original(alias) == ("fs", "read.file")
    assert aliases.aliases() == {alias: ("fs", "read.file")}


def test_adding_the_same_tool_twice_is_idempotent():
    aliases = mcp_session.ToolAliases()
    assert aliases.add("fs", "read_file") == aliases.add("fs", "read_file")
    assert len(aliases.aliases()) == 1


def test_a_conflicting_builtin_name_is_rejected():
    aliases = mcp_session.ToolAliases(reserved=("mcp__fs__read_file",))
    try:
        aliases.add("fs", "read_file")
    except mcp_session.ToolAliasConflict as conflict:
        assert "内置工具" in str(conflict)
    else:
        raise AssertionError("与内置工具重名时没有拒绝")


def test_an_unknown_alias_is_reported():
    aliases = mcp_session.ToolAliases()
    try:
        aliases.original("mcp__fs__read_file")
    except mcp_session.UnknownToolAlias as unknown:
        assert "不在这个事项" in str(unknown)
    else:
        raise AssertionError("不存在的别名没有被拒绝")
