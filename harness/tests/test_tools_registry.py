# 查询 tools.registry（工单 #1177；网络与 MCP 设计说明第 10 节、第 11.3 节；总图第四节「接口」缝）。
# 这个文件查四件事：
# 1. 能力清单列出这个查询与改变它结果的事件种类；调用前后事件日志末尾位置与保存的投影不变（验收 2）；
# 2. 两个项目各写明不同的服务器时，查询内容与各自设置一致（验收 1 的 MCP 一半）；
# 3. 保存了工具清单快照的服务器，查询原样给出快照；没有服务器的项目给出空字典；
#    取回记录与探测状态留空位（#68 与 #1174 合并以后填充）。
# 第 4 件事（接口合同：OpenAPI 快照与生成的客户端类型有这一条查询）由 test_openapi_snapshot.py
# 与 test_api.py 的能力清单核对覆盖，不在这里重复（测试分层第 13 节 D3）。
#
# 依赖状态（2026-10-31，main 67ee4da0）：#236 已合并，MCP 服务器读项目投影；#1174（探测）与 #68（取回）
# 未合并，最近一次探测（probe）与取回记录（fetch_records）留合同空位、恒为空，不造数据；
# 探测记录待 #1174 合并后由它填充，取回记录待 #68 合并后由它填充。
#
# 层：模块层（真实 SQLite 事件库与项目投影，不出激活、不用网络，测试分层设计说明第 2 节）。
# 守 R2（第二环的合同：查询的结果字段、能力清单登记、只读保证）。

from __future__ import annotations

import json

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.event_store import project_stream
from harness.runtime import LoopSystem

GOAL = "做一个可以长期演进的逐行文本处理工具。"

STDIO_SERVER = {
    "time": {
        "name": "time", "transport": "stdio",
        "command": "uvx", "args": ["mcp-server-time"],
        "env": {"API_KEY": {"kind": "credential", "credential_ref": "MCP_TIME_KEY"}},
        "departments": ["product", "engineering", "quality"],
    },
}
HTTP_SERVER = {
    "search": {
        "name": "search", "transport": "http", "url": "https://mcp.example.com/mcp",
        "headers": {"Authorization": {"kind": "credential", "credential_ref": "EXA_KEY"}},
        "departments": ["product"],
    },
}


def _system(tmp_path) -> LoopSystem:
    return LoopSystem.for_testing(tmp_path, FakeAdapter([]))


def _tools(application):
    # 无参数查询（同 catalog）：请求为 None
    return application.query("tools.registry", None).data


def test_the_registry_lists_the_query_with_its_change_kinds_and_reads_nothing(tmp_path):
    # 验收 2（R2）：能力清单列出 tools.registry 与改变它结果的事件种类；调用前后事件日志末尾
    # 与保存的投影不变（查询只读取）
    system = _system(tmp_path)
    application = Application(system)
    try:
        capabilities = application.capabilities("", access="local")
        query = next(item for item in capabilities.queries if item.name == "tools.registry")
        assert sorted(query.changed_by) == ["mcp_servers_configured", "project_registered", "project_renamed",
                                            "tool_called", "tool_started"]
        assert query.replayable is False

        store = system.store
        project_id = system.projects.register("只读", GOAL)
        system.projects.configure_mcp_servers(project_id, STDIO_SERVER, base_version=0)
        streams = [project_stream(pid) for pid in store.list_project_ids()]
        end = store.end_position()
        saved = [store.projection(stream) for stream in streams]

        _tools(application)

        assert store.end_position() == end
        assert [store.projection(stream) for stream in streams] == saved
    finally:
        system.close()


def test_two_projects_with_different_servers_each_match_their_own_settings(tmp_path):
    # 验收 1（R2）：两个项目各写明不同的服务器，查询内容与各自设置一致；凭据只出现名称；
    # 设置与 project.settings 读回的同一份非秘密文档一致
    system = _system(tmp_path)
    application = Application(system)
    try:
        first = system.projects.register("服务器甲", GOAL)
        second = system.projects.register("服务器乙", GOAL)
        system.projects.configure_mcp_servers(first, STDIO_SERVER, base_version=0)
        system.projects.configure_mcp_servers(second, HTTP_SERVER, base_version=0)

        data = _tools(application)
        assert [item.project_id for item in data.projects] == [second, first]  # 最近写入的在前
        by_id = {item.project_id: item for item in data.projects}

        assert by_id[first].name == "服务器甲"
        server = by_id[first].mcp_servers["time"]
        assert server.transport == "stdio" and server.command == "uvx"
        assert server.args == ["mcp-server-time"]
        assert server.env["API_KEY"] == {"kind": "credential", "value": "", "credential_ref": "MCP_TIME_KEY"}
        assert server.departments == ["product", "engineering", "quality"]
        assert server.probe.ok is None and server.probe.finished_at is None  # 探测待 #1174 填充
        assert by_id[first].fetch_records == []  # 取回记录待 #68 填充

        assert by_id[second].name == "服务器乙"
        other = by_id[second].mcp_servers["search"]
        assert other.transport == "http" and other.url == "https://mcp.example.com/mcp"
        assert other.headers["Authorization"]["credential_ref"] == "EXA_KEY"
        assert other.departments == ["product"]
        assert set(by_id[second].mcp_servers) == {"search"}

        # 与 project.settings 读回的同一份设置一致（同一个投影来源）
        from harness.app.project_queries import ProjectSettings
        settings = application.query("project.settings", ProjectSettings(project_id=first)).data
        assert settings.mcp_servers.servers["time"].command == by_id[first].mcp_servers["time"].command
        assert settings.mcp_servers.servers["time"].config_digest == by_id[first].mcp_servers["time"].config_digest
    finally:
        system.close()


def test_a_saved_tool_snapshot_is_returned_and_projects_without_servers_are_empty(tmp_path):
    # 验收 1（工具清单）与边界：随设置保存的工具清单快照原样给出（探测完成以前，快照只能由保存携带）；
    # 没有写明服务器的项目给出空字典，不省略这个项目
    system = _system(tmp_path)
    application = Application(system)
    try:
        with_snapshot = system.projects.register("快照", GOAL)
        without = system.projects.register("无服务器", GOAL)
        # 快照必须带与本台服务器配置一致的摘要（工单 #236 的规则）：先按不带快照的配置算摘要，再附加快照保存
        from harness.projects import normalize_mcp_servers
        digest = normalize_mcp_servers({"time": STDIO_SERVER["time"]})["servers"]["time"]["config_digest"]
        probed = json.loads(json.dumps(STDIO_SERVER["time"]))
        probed["tool_snapshot"] = {"config_digest": digest, "tools": [{"name": "now"}]}
        system.projects.configure_mcp_servers(with_snapshot, {"time": probed}, base_version=0)

        data = _tools(application)
        by_id = {item.project_id: item for item in data.projects}
        assert set(by_id[with_snapshot].mcp_servers) == {"time"}
        snapshot = by_id[with_snapshot].mcp_servers["time"].tool_snapshot
        assert snapshot is not None and snapshot["config_digest"] == digest
        assert [tool["name"] for tool in snapshot["tools"]] == ["now"]
        assert by_id[without].mcp_servers == {} and by_id[without].fetch_records == []
    finally:
        system.close()
