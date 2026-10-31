# MCP 工具在事项定义里的名称规则（网络与 MCP 设计说明第 5.1 节，工单 #1175）。
# 守 R2：别名是模型接口看到的工具名，也是静态定义里的键与许可判断用的名字——三者是同一个标识
#       （小写字母、数字与下划线，字母开头），规则确定、可反查，冲突必须拒绝而不是静默改名。
# 守 R3：第 5.1 节写明的拼接、收敛、超长前缀与摘要规则，原名只在调用时还原。

import asyncio

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


# 事项定义副本（工单 #1175 第 3 轮）：冻结的 MCP 设置叠加以后，MCP 工具只出现在写明部门的工具清单里，
# 没有设置或没有可用快照时副本就是当前定义本身。

from harness.definitions import DEFINITIONS  # noqa: E402 - 用例只读当前定义


def _document(departments=("engineering",), snapshot_digest="sha256:cfg", config_digest="sha256:cfg"):
    snapshot = None if snapshot_digest is None else {
        "config_digest": snapshot_digest,
        "tools": [{"name": "Read.File", "description": "读取一个文件",
                    "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}}}],
    }
    return {"version": 1, "document_digest": "sha256:doc",
            "servers": {"fs": {"name": "fs", "transport": "stdio", "config_digest": config_digest,
                                   "departments": list(departments), "tool_snapshot": snapshot}}}


def test_no_mcp_settings_keep_the_current_definitions():
    assert mcp_session.item_definitions(DEFINITIONS, None) is DEFINITIONS
    assert mcp_session.item_definitions(DEFINITIONS, {"version": 1, "document_digest": "", "servers": {}}) is DEFINITIONS


def test_mcp_tools_are_added_for_their_departments_only():
    item = mcp_session.item_definitions(DEFINITIONS, _document())
    tool = item.tools["mcp__fs__read_file"]
    assert tool.action == "mcp" and tool.verification == "none" and tool.cancellable is True
    assert tool.description == "读取一个文件"
    assert tool.parameters["properties"]["path"] == {"type": "string"}
    assert "mcp__fs__read_file" in item.tools_for("engineering")
    assert "mcp__fs__read_file" not in item.tools_for("product")
    assert "mcp__fs__read_file" not in item.tools_for("quality")
    # 原来的工具与角色清单不受影响
    assert set(DEFINITIONS.tools) < set(item.tools)
    assert set(DEFINITIONS.tools_for("product")) == set(item.tools_for("product"))


def test_a_server_without_a_snapshot_adds_no_tools():
    assert mcp_session.item_definitions(DEFINITIONS, _document(snapshot_digest=None)) is DEFINITIONS


def test_a_snapshot_with_a_different_digest_is_not_used():
    assert mcp_session.item_definitions(DEFINITIONS,
                                        _document(snapshot_digest="sha256:old")) is DEFINITIONS


# MCP 会话（工单 #1175 第 8 轮，网络与 MCP 设计说明第 7.2 节）：会话表的名称表来自冻结设置带来的定义副本，
# 每台服务器的启动参数从同一份冻结设置组出。会话实例的建立、复用与关闭、结果的凭据替换按真实 MCP 进程
# 核对（集成层，test_mcp_tools_integration.py）；缝层守名称表与启动参数这两段，
# 凭据来源用进程内的 CredentialChain（真实实现）。

from harness.mcp_client import ServerLaunch  # noqa: E402
from harness.providers.credentials import CredentialChain  # noqa: E402

CREDENTIAL_SECRET = "mcp-session-secret-1175"


def _settings_document(env=None):
    server = {"name": "fs", "transport": "stdio", "command": "uvx", "args": ["mcp-server-fs"],
              "departments": ["engineering"], "startup_timeout_sec": 60, "call_timeout_sec": 120}
    if env is not None:
        server["env"] = env
    return {"version": 1, "document_digest": "sha256:doc", "servers": {"fs": server}}


def test_the_session_table_resolves_aliases_from_the_item_definitions():
    # 名称表与定义副本读同一份冻结设置：别名在叠加进定义副本的同一批工具里，能反查原名与服务器
    item = mcp_session.item_definitions(DEFINITIONS, _document())
    table = mcp_session.McpSessions(_document(), credentials=CredentialChain(), stderr_dir=".")
    server, tool = table.original("mcp__fs__read_file")
    assert (server, tool) == ("fs", "Read.File")
    assert "mcp__fs__read_file" in item.tools_for("engineering")
    assert table.server_names() == ["fs"]


def test_an_alias_outside_the_table_is_refused():
    table = mcp_session.McpSessions(None, credentials=CredentialChain(), stderr_dir=".")
    try:
        table.original("mcp__fs__read_file")
    except mcp_session.UnknownToolAlias:
        pass
    else:
        raise AssertionError("没有冻结设置的会话表放过了别的工具名")


def test_a_call_against_an_unknown_server_is_refused():
    table = mcp_session.McpSessions(_document(), credentials=CredentialChain(), stderr_dir=".")

    async def call():
        return await table.call("mcp__other__read_file", "other", "read_file", {})

    outcome = asyncio.run(call())
    assert outcome.is_error and outcome.error_code == "startup_failed"
    assert "不在" in outcome.result_text
    assert not table.open and table.sessions() == {}


def test_the_launch_plan_carries_the_timeouts_and_the_redaction_list():
    # 启动参数按冻结设置组出：时限随设置、标准错误输出写到数据目录的 mcp-logs、
    # 凭据值按名称取值并进入脱敏清单（值不写进回执、事件与日志）
    document = _settings_document({"API_KEY": {"kind": "credential", "credential_ref": "MCP_SESSION_KEY"}})
    credentials = CredentialChain(overrides={"MCP_SESSION_KEY": CREDENTIAL_SECRET})
    table = mcp_session.McpSessions(document, credentials=credentials, stderr_dir="data")
    plan = table._plan("fs")
    assert isinstance(plan.launch, ServerLaunch)
    assert plan.launch.stdio.command == "uvx" and plan.launch.stdio.args == ("mcp-server-fs",)
    assert plan.launch.startup_timeout_sec == 60 and plan.launch.call_timeout_sec == 120
    assert plan.launch.stdio.env["API_KEY"] == CREDENTIAL_SECRET
    assert CREDENTIAL_SECRET in plan.launch.secrets
    assert "mcp-logs" in plan.launch.stderr_log_path and "fs.log" in plan.launch.stderr_log_path


def test_a_missing_credential_refuses_the_launch_with_the_credential_name():
    document = _settings_document({"API_KEY": {"kind": "credential", "credential_ref": "MCP_SESSION_KEY"}})
    table = mcp_session.McpSessions(document, credentials=CredentialChain(), stderr_dir=".")
    try:
        table._plan("fs")
    except mcp_session.McpRefused as refused:
        assert "MCP_SESSION_KEY" in str(refused)
    else:
        raise AssertionError("缺少凭据时没有拒绝启动")
