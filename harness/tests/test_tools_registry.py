# 查询 tools.registry（工单 #1177；网络与 MCP 设计说明「应用层接口」、「系统「工具与扩展」页」「系统『工具与扩展』页」；
# 总图第四节「接口」缝）。这个文件查五件事：
# 1. 能力清单里列出这个查询；调用前后事件日志末尾位置与保存的投影不变（验收 2 的只读一半）；
# 2. 两个项目各写明不同的服务器时，查询内容与各自设置一致（验收 1 的 MCP 一半）；
# 3. 保存了工具清单快照的服务器，查询原样给出快照；没有服务器的项目给出空字典；
# 4. 一次取回以后，这条记录出现在它自己项目的最近取回记录里，别的项目看不到（验收 1 的取回一半）；
# 5. 每台服务器给出自己最近一次探测的状态，过期的结果带当时的配置摘要（docs/design/network-and-mcp.md「读取工具清单（探测）」、「系统「工具与扩展」页」）。
# 第 6 件事（接口合同：OpenAPI 快照与生成的客户端类型有这一条查询）由 test_openapi_snapshot.py
# 与 test_api.py 的能力清单核对覆盖，不在这里重复（测试分层「测试按三环留」D3）。
#
# 数据来源（2026-11-03，main 6ad1fd3e）：#236（MCP 设置）、#1174（探测事件 tool_server_probe_finished）与
# #68（取回动作 fetch_url）都已合并，查询读项目投影与项目名下的两类事件。取回与探测各自的动作路径由
# #68 的 harness/tests/test_fetch.py 与 #1174 的 harness/tests/test_mcp_probe.py 在集成层核对，
# 这里核对的是查询读到这些事实以后给出什么。
#
# 层：模块层（真实 SQLite 事件库与项目投影，不出激活、不用网络，测试分层设计说明「三层的定义」）。
# 守 R2（第二环的合同：查询的结果字段、能力清单登记、只读保证）。

from __future__ import annotations

import json

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.event_store import project_stream, run_stream
from harness.models import EventType, ProjectEventType
from harness.runtime import LoopSystem
from harness.write_path import NewEvent, NewProjectEvent

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
BOTH_SERVERS = {**STDIO_SERVER, **HTTP_SERVER}


def _system(tmp_path) -> LoopSystem:
    return LoopSystem.for_testing(tmp_path, FakeAdapter([]))


def _tools(application):
    # 无参数查询（同 catalog）：请求为 None
    return application.query("tools.registry", None).data


def _record_fetch(system, run_id: str, *, url: str, ok: bool,
                  error: str | None = None, refused: str | None = None) -> None:
    # 一条取回动作的结果事件：与 #68 的动作写同一种事件（run 流的 tool_called，名字 fetch_url）
    payload: dict = {"id": f"fetch-{url}", "name": "fetch_url", "ok": ok, "args": {"url": url}}
    if error is not None:
        payload["error"] = error
    if refused is not None:
        payload["refused"] = True
        payload["refused_reason"] = refused
    system.writes.transact(run_stream(run_id), lambda transaction: transaction.append(NewEvent(
        EventType.TOOL_CALLED, actor="department:engineering", department="engineering",
        state_before=transaction.projection.status, state_after=transaction.projection.status,
        payload=payload)))


def _record_probe(system, project_id: str, *, server_name: str, ok: bool, config_digest: str,
                  error: str = "", tools: list[dict] | None = None) -> None:
    # 一次探测的结果事件：与 #1174 的探测写同一种项目流事件（tool_server_probe_finished）
    payload = {
        "server_name": server_name, "status": "ok" if ok else "failed", "config_digest": config_digest,
        "server_info": {"name": server_name} if ok else None, "tools": list(tools or []), "error": error,
    }
    system.writes.transact(project_stream(project_id), lambda transaction: transaction.append(
        NewProjectEvent(ProjectEventType.TOOL_SERVER_PROBE_FINISHED, payload, actor="system")))


def test_the_registry_is_listed_as_a_query_and_reads_nothing(tmp_path):
    # 验收 2（R2）的只读一半：能力清单里有 tools.registry，调用前后事件日志末尾与保存的投影不变
    # （查询只读取）。改变它结果的事件种类由 test_capabilities.py 核对（能力清单的断言集中在那里）；
    # 接口合同（OpenAPI 快照与客户端类型）由 test_openapi_snapshot.py 核对
    system = _system(tmp_path)
    application = Application(system)
    try:
        capabilities = application.capabilities("", access="local")
        query = next(item for item in capabilities.queries if item.name == "tools.registry")
        assert query.replayable is False

        store = system.store
        project_id = system.projects.register("只读", GOAL)
        system.projects.configure_mcp_servers(project_id, STDIO_SERVER, base_version=0)
        _record_probe(system, project_id, server_name="time", ok=True, config_digest="sha256:digest")
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
    # 设置与 project.settings 读回的同一份非秘密文档一致；没有取回过的项目取回记录为空
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
        assert server.probe.ok is None and server.probe.finished_at is None  # 还没有探测过
        assert by_id[first].fetch_records == []

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


def test_a_fetch_appears_in_its_own_projects_recent_records_only(tmp_path):
    # 验收 1（R2）：一次取回之后，这条记录出现在它自己项目的最远近取回记录里，最近的在前；
    # 别的项目看不到；只认 fetch_url，别的工具不动这份记录
    system = _system(tmp_path)
    application = Application(system)
    try:
        fetched = system.projects.register("取回过的项目", GOAL)
        other = system.projects.register("没取回过的项目", GOAL)
        # 取回动作写在属于这个项目的事项的 run 流里（run 的项目取自 run_created）
        _work_item, run_id = system.projects.start_work_item(fetched, "取回一个网页")

        assert _tools(application).projects[0].fetch_records == []  # 还没有取回

        _record_fetch(system, run_id, url="https://example.com/manual", ok=True)
        # 别的工具不改变取回记录
        system.writes.transact(run_stream(run_id), lambda transaction: transaction.append(NewEvent(
            EventType.TOOL_CALLED, actor="department:engineering", department="engineering",
            state_before=transaction.projection.status, state_after=transaction.projection.status,
            payload={"id": "bash-1", "name": "bash", "ok": True, "args": {"command": "ls"}})))
        _record_fetch(system, run_id, url="http://127.0.0.1:8765/page", ok=False,
                      refused="it points at the Yudao service's own address and port")
        _record_fetch(system, run_id, url="https://example.com/broken", ok=False, error="连接被拒")

        by_id = {item.project_id: item for item in _tools(application).projects}
        records = by_id[fetched].fetch_records
        # 最近的在前：最后一个取回排第一
        assert [record.url for record in records] == [
            "https://example.com/broken", "http://127.0.0.1:8765/page", "https://example.com/manual"]
        assert [record.ok for record in records] == [False, False, True]
        assert records[0].error == "连接被拒"
        assert records[1].error == "it points at the Yudao service's own address and port"
        assert records[2].error is None
        assert all(record.at for record in records)  # 每条都带取回的时间
        assert by_id[other].fetch_records == []
    finally:
        system.close()


def test_each_server_shows_its_own_latest_probe_and_stale_results_keep_their_digest(tmp_path):
    # 验收 1（最近一次状态，R2）：每台服务器给出自己最近一次探测的状态，不是项目里最后一次探测；
    # 配置改过以后旧结果仍然给出（docs/design/network-and-mcp.md「读取工具清单（探测）」中「过期探测结果保留供查询」），带上它绑定的配置摘要；
    # 探测过但已经删掉的服务器不再列出
    system = _system(tmp_path)
    application = Application(system)
    try:
        project_id = system.projects.register("两台服务器", GOAL)
        system.projects.configure_mcp_servers(project_id, BOTH_SERVERS, base_version=0)
        time_digest = system.projects.read_mcp_servers(project_id)["servers"]["time"]["config_digest"]

        _record_probe(system, project_id, server_name="time", ok=True, config_digest=time_digest,
                      tools=[{"name": "now"}])
        _record_probe(system, project_id, server_name="search", ok=False, config_digest="sha256:old",
                      error="缺少凭据 EXA_KEY")
        # 同一台服务器再探测失败一次：取最后一次
        _record_probe(system, project_id, server_name="time", ok=False, config_digest="sha256:changed",
                      error="启动失败")
        # 探测过的服务器后来从设置里删掉：它不再出现在登记里
        _record_probe(system, project_id, server_name="gone", ok=True, config_digest="sha256:gone")

        servers = {item.project_id: item for item in _tools(application).projects}[project_id].mcp_servers
        assert set(servers) == {"time", "search"}
        assert servers["time"].probe.ok is False and servers["time"].probe.error == "启动失败"
        assert servers["time"].probe.config_digest == "sha256:changed"
        assert servers["time"].probe.finished_at
        assert servers["search"].probe.ok is False and servers["search"].probe.error == "缺少凭据 EXA_KEY"
    finally:
        system.close()
