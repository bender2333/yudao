# MCP 工具在事项定义里的名称规则（网络与 MCP 设计说明第 5.1 节，工单 #1175）。
# 守 R2：别名是模型接口看到的工具名，也是静态定义里的键与许可判断用的名字——三者是同一个标识
#       （小写字母、数字与下划线，字母开头），规则确定、可反查，冲突必须拒绝而不是静默改名。
# 守 R3：第 5.1 节写明的拼接、收敛、超长前缀与摘要规则，原名只在调用时还原。

import harness.mcp_session as mcp_session


def test_allowed_names_keep_the_server_and_tool_name():
    assert mcp_session.tool_alias("fs", "read_file") == "mcp__fs__read_file"
    assert mcp_session.tool_alias("mcp", "list_items") == "mcp__mcp__list_items"


def test_uppercase_dots_and_hyphens_converge_to_an_identifier():
    alias = mcp_session.tool_alias("my-server", "Read.File")
    assert alias == "mcp__my_server__read_file"
    assert mcp_session.IDENTIFIER.match(alias), alias


def test_every_alias_is_an_identifier():
    for server, tool in (("srv", "do it"), ("Srv-2", "Read.File"), ("服务", "工具"), ("a.b", "c/d")):
        alias = mcp_session.tool_alias(server, tool)
        assert mcp_session.IDENTIFIER.match(alias), (server, tool, alias)
        assert len(alias) <= mcp_session.TOOL_NAME_MAX


def test_long_names_use_the_prefix_and_suffix_rule():
    tool = "t" * 80
    alias = mcp_session.tool_alias("server", tool)
    full = ("mcp__server__" + tool).lower()
    assert alias == full[:mcp_session.ALIAS_PREFIX_LENGTH] + "_" + mcp_session.alias_suffix("server", tool)
    assert len(alias) == mcp_session.TOOL_NAME_MAX
    assert mcp_session.IDENTIFIER.match(alias), alias


def test_two_long_names_sharing_the_prefix_get_different_aliases():
    first = mcp_session.tool_alias("server", "a" * 80)
    second = mcp_session.tool_alias("server", "a" * 79 + "b")
    assert first != second
    assert first[:mcp_session.ALIAS_PREFIX_LENGTH] == second[:mcp_session.ALIAS_PREFIX_LENGTH]


def test_the_same_tool_always_gets_the_same_alias():
    assert mcp_session.tool_alias("fs", "Read.File") == mcp_session.tool_alias("fs", "Read.File")
    # 原名不同、收敛以后不同名的两个工具仍然不同
    assert mcp_session.tool_alias("fs", "read_file") != mcp_session.tool_alias("fs", "read-file-2")


def test_aliases_look_up_the_server_and_original_tool():
    aliases = mcp_session.ToolAliases(reserved=("write_file", "run_check"))
    alias = aliases.add("fs", "Read.File")
    assert alias == "mcp__fs__read_file"
    assert aliases.original(alias) == ("fs", "Read.File")
    assert aliases.aliases() == {alias: ("fs", "Read.File")}


def test_adding_the_same_tool_twice_is_idempotent():
    aliases = mcp_session.ToolAliases()
    assert aliases.add("fs", "read_file") == aliases.add("fs", "read_file")
    assert len(aliases.aliases()) == 1


def test_two_tools_that_converge_to_the_same_alias_are_rejected():
    aliases = mcp_session.ToolAliases()
    aliases.add("fs", "read.file")
    try:
        aliases.add("fs", "read-file")
    except mcp_session.ToolAliasConflict as conflict:
        assert "不能再给" in str(conflict)
    else:
        raise AssertionError("两个不同的工具收敛成同一个别名时没有拒绝")


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
