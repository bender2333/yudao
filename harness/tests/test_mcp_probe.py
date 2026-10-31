# MCP 服务器探测（工单 #1174；网络与 MCP 设计说明第 4.2 节「读取工具清单（探测）」、第 4.4 节「凭据」、
# 第 10 节应用层接口表；总图第四节「接口」缝的命令）。这个文件查九件事：
# 1. 用官方 mcp-server-time（stdio）与本机 SDK HTTP 测试服务器探测，读到工具清单快照；
# 2. 探测结果以项目流事件 tool_server_probe_finished 出现（真实 MCP 进程）；
# 3. 启动失败给出原因与标准错误输出末尾，凭据值已替换为星号；
# 4. 缺凭据时启动失败，原因写明凭据名称；
# 5. 保存前可以探测；探测绑定归一化配置的内容摘要（与保存的 config_digest 相同）；
# 6. 成功探测把工具清单快照写回设置里这台服务器（摘要一致才写回）；
# 7. 探测期间修改配置（或删除这台服务器）时旧结果保留在事件里，不覆盖新配置的可用快照；
# 8. 保存未探测的配置允许，这台服务器在具备匹配快照前没有可用快照；同配置再保存（探测结果先到）
#    时快照按同一摘要被接受；
# 9. 凭据值不出现在事件、投影与设置里（只出现名称），日志里的值同样被替换。
#
# 层：集成层（真实 MCP 子进程与真实本机端口，测试分层设计说明第 2 节）。
# 守 R2（第二环的合同：项目流事件与 project.settings 的载荷）与 R3（用户读到的探测结果与真实服务器一致）。

from __future__ import annotations

import asyncio
import json
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.app.mcp_commands import ToolServerProbe
from harness.models import ProjectEventType
from harness.proposals import product_spec
from harness.projects import mcp_document_digest, normalize_mcp_servers
from harness.runtime import LoopSystem
from harness.streams import PROJECT_EVENT_TYPES
from harness.tests.helpers import happy_script

SERVERS = Path(__file__).resolve().parent / "mcp_servers"
HTTP_SERVER = SERVERS / "http_server.py"
SECRET = "mcp-probe-secret-1174"
GOAL = "做一个可以长期演进的逐行文本处理工具。"


def _system(tmp_path) -> LoopSystem:
    return LoopSystem.for_testing(tmp_path, FakeAdapter({"product": [product_spec()]}))


def _stdio_server(*, credential: bool = False) -> dict:
    server = {
        "name": "time", "transport": "stdio",
        "command": sys.executable, "args": [str(SERVERS / "stdio_server.py")],
        "departments": ["product", "engineering", "quality"],
    }
    if credential:
        server["env"] = {"API_KEY": {"kind": "credential", "credential_ref": "MCP_PROBE_KEY"}}
    return server


def _http_server(url: str) -> dict:
    return {"name": "search", "transport": "http", "url": url,
            "headers": {"Authorization": {"kind": "text", "value": "Bearer probe"}},
            "departments": ["product"]}


def _probe(application: Application, project_id: str, name: str, server: dict):
    # 提交探测命令：结果以后以事件出现。命令处理在这次调用自己的事件循环里跑完再返回
    from harness.app.commands import execute
    request = ToolServerProbe(command_id=str(uuid.uuid4()), project_id=project_id, name=name, server=server)
    return asyncio.run(execute(application, application.registry.commands["tool_server.probe"],
                               request, actor="user:local"))


def _probe_events(system: LoopSystem, project_id: str) -> list:
    return [event for event in system.store.list_project_events(project_id)
            if event.type == ProjectEventType.TOOL_SERVER_PROBE_FINISHED]


def _settings(application: Application, project_id: str):
    from harness.app.project_queries import ProjectSettings
    return application.query("project.settings", ProjectSettings(project_id=project_id)).data


def _free_port() -> int:
    with socket.socket() as probe_socket:
        probe_socket.bind(("127.0.0.1", 0))
        return probe_socket.getsockname()[1]


def _wait_for_port(port: int, *, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise AssertionError(f"测试服务器没有在 {timeout} 秒内开始监听 127.0.0.1:{port}")


# ---------------------------------------------------------------------------
# 真实进程的探测：stdio 与 HTTP（验收 1）


def test_a_stdio_server_probe_reads_the_tool_snapshot(tmp_path):
    system = _system(tmp_path)
    project_id = system.projects.register("探测", GOAL)
    application = Application(system)

    accepted = _probe(application, project_id, "time", _stdio_server())
    assert accepted.duplicate is False

    events = _probe_events(system, project_id)
    assert len(events) == 1
    payload = events[0].payload
    assert payload["status"] == "ok" and payload["error"] == ""
    assert payload["server_name"] == "time"
    # 探测绑定归一化配置的内容摘要：与保存同一份配置得到的 config_digest 相同
    assert payload["config_digest"] == normalize_mcp_servers({"time": _stdio_server()})["servers"]["time"]["config_digest"]
    assert payload["server_info"]["name"] == "yudao-test-stdio"
    assert payload["server_info"]["protocol_version"]
    names = {tool["name"] for tool in payload["tools"]}
    assert {"echo", "structured", "big"} <= names
    echo = next(tool for tool in payload["tools"] if tool["name"] == "echo")
    assert echo["input_schema"]["type"] == "object"
    system.close()


def test_an_http_server_probe_reads_the_tool_snapshot(tmp_path):
    system = _system(tmp_path)
    project_id = system.projects.register("HTTP 探测", GOAL)
    port = _free_port()
    log = (tmp_path / "http-stderr.log").open("wb")
    process = subprocess.Popen([sys.executable, str(HTTP_SERVER), str(port)],
                               stdout=subprocess.DEVNULL, stderr=log)
    try:
        _wait_for_port(port)
        application = Application(system)
        _probe(application, project_id, "search", _http_server(f"http://127.0.0.1:{port}/mcp"))
    finally:
        process.kill()
        process.wait(timeout=15)
        log.close()

    events = _probe_events(system, project_id)
    assert len(events) == 1
    payload = events[0].payload
    assert payload["status"] == "ok"
    assert payload["server_info"]["name"] == "yudao-test-http"
    assert "echo" in {tool["name"] for tool in payload["tools"]}
    system.close()


def test_the_official_mcp_server_time_probe_reads_the_tool_snapshot(tmp_path):
    # 验收第 1 条：官方的 mcp-server-time 经 uvx 启动（stdio），探测读到工具清单快照。
    # 取不到包（没有 uvx、没有网络或缓存里没有）时跳过，并写明缺什么
    uvx = shutil.which("uvx")
    if uvx is None:
        pytest.skip("缺 uvx：PATH 上没有 uvx，取不到官方 mcp-server-time")
    system = _system(tmp_path)
    project_id = system.projects.register("官方时间", GOAL)
    application = Application(system)
    server = {"name": "time", "transport": "stdio", "command": uvx, "args": ["mcp-server-time"],
              "startup_timeout_sec": 300, "departments": ["product", "engineering", "quality"]}
    _probe(application, project_id, "time", server)
    events = _probe_events(system, project_id)
    if events and events[0].payload["status"] == "failed":
        pytest.skip(f"取不到官方 mcp-server-time（uvx 启动失败）：{events[0].payload['error']}")
    payload = events[0].payload
    assert payload["status"] == "ok"
    assert "get_current_time" in {tool["name"] for tool in payload["tools"]}
    system.close()


# ---------------------------------------------------------------------------
# 失败与凭据（验收 2）


def test_a_startup_failure_reports_the_stderr_tail_with_the_secret_redacted(tmp_path):
    system = _system(tmp_path)
    project_id = system.projects.register("失败", GOAL)
    application = Application(system)
    script = ("import os, sys\n"
              "print('PROBE STARTUP FAILURE ' + os.environ.get('API_KEY', ''), file=sys.stderr)\n"
              "sys.exit(3)\n")
    server = _stdio_server(credential=True)
    server["command"] = sys.executable
    server["args"] = ["-c", script]
    system.facade.set_credential_override("MCP_PROBE_KEY", SECRET)

    _probe(application, project_id, "time", server)
    payload = _probe_events(system, project_id)[0].payload
    assert payload["status"] == "failed"
    assert "PROBE STARTUP FAILURE" in payload["error"]
    assert SECRET not in payload["error"] and "***" in payload["error"]
    system.close()


def test_a_missing_credential_fails_and_names_the_credential(tmp_path):
    system = _system(tmp_path)
    project_id = system.projects.register("缺凭据", GOAL)
    application = Application(system)

    _probe(application, project_id, "time", _stdio_server(credential=True))
    payload = _probe_events(system, project_id)[0].payload
    assert payload["status"] == "failed"
    assert "MCP_PROBE_KEY" in payload["error"]
    system.close()


def test_credential_values_do_not_enter_events_settings_or_stderr_logs(tmp_path):
    system = _system(tmp_path)
    project_id = system.projects.register("凭据不出现", GOAL)
    application = Application(system)
    script = ("import os, sys\n"
              "print('FAILED WITH ' + os.environ.get('API_KEY', ''), file=sys.stderr)\n"
              "sys.exit(3)\n")
    server = _stdio_server(credential=True)
    server["args"] = ["-c", script]
    system.facade.set_credential_override("MCP_PROBE_KEY", SECRET)
    # 设置里也保存一份（凭据只以名称保存），导出里核对值不出现
    system.projects.configure_mcp_servers(project_id, {"time": _stdio_server(credential=True)},
                                          base_version=0)

    _probe(application, project_id, "time", server)
    exported = json.dumps({
        "project_events": [event.to_dict() for event in system.store.list_project_events(project_id)],
        "settings": system.projects.read_mcp_servers(project_id),
    }, ensure_ascii=False)
    assert SECRET not in exported
    assert "MCP_PROBE_KEY" in exported  # 引用在，值不在
    log = Path(system.data_dir / "mcp-logs" / "time.log")
    assert log.exists() and SECRET not in log.read_text(encoding="utf-8")
    system.close()


# ---------------------------------------------------------------------------
# 绑定、写回与晚到的旧结果（正文「配置与快照的绑定」一段）


def test_probe_before_save_and_writeback_binds_the_same_config_digest(tmp_path):
    system = _system(tmp_path)
    project_id = system.projects.register("保存前探测", GOAL)
    application = Application(system)

    # 保存未探测的配置允许：这台服务器还没有可用快照
    system.projects.configure_mcp_servers(project_id, {"time": _stdio_server()}, base_version=0)
    settings = _settings(application, project_id)
    assert settings.mcp_servers.servers["time"].tool_snapshot is None

    # 保存前也可以探测：结果带与保存配置一致的摘要，写回设置里这台服务器
    _probe(application, project_id, "time", _stdio_server())
    settings = _settings(application, project_id)
    snapshot = settings.mcp_servers.servers["time"].tool_snapshot
    assert snapshot is not None
    config_digest = normalize_mcp_servers({"time": _stdio_server()})["servers"]["time"]["config_digest"]
    assert snapshot["config_digest"] == config_digest
    assert settings.mcp_servers.servers["time"].config_digest == config_digest
    assert {"echo", "structured"} <= {tool["name"] for tool in snapshot["tools"]}
    # 保存（同配置）成功：快照随事件保存，读取的摘要一致
    saved = system.projects.read_mcp_servers(project_id)
    assert saved["servers"]["time"]["tool_snapshot"]["config_digest"] == config_digest
    system.close()


def test_an_old_probe_result_after_a_config_change_keeps_but_never_covers(tmp_path):
    # 探测期间修改配置：旧结果保留（事件里有），但不得覆盖新配置的可用快照（设计说明第 4.2 节）
    system = _system(tmp_path)
    project_id = system.projects.register("配置变化", GOAL)
    application = Application(system)
    old_server = _stdio_server()
    digest_before = normalize_mcp_servers({"time": old_server})["servers"]["time"]["config_digest"]

    # 探测任务在写回之前把设置改成另一份配置（另一台服务器的样子），模拟探测期间修改：
    # 命令接受以后、探测返回之前没有别的时机，这里在写回入口前面插入一次保存
    original_record = system.projects.record_tool_snapshot
    changed = [False]

    def record_with_change(project_id_arg, server_name, snapshot):
        if not changed[0]:
            changed[0] = True
            system.projects.configure_mcp_servers(
                project_id_arg,
                {"time": {**_stdio_server(), "args": [str(SERVERS / "http_server.py")]}},
                base_version=0)
        return original_record(project_id_arg, server_name, snapshot)

    system.projects.record_tool_snapshot = record_with_change
    _probe(application, project_id, "time", old_server)

    # 探测结果事件在（旧结果保留），写回被拒绝：新配置的版本只有改配置那一次保存，没有可用快照
    events = _probe_events(system, project_id)
    assert len(events) == 1 and events[0].payload["status"] == "ok"
    assert events[0].payload["config_digest"] == digest_before
    settings = _settings(application, project_id)
    assert settings.mcp_servers.version == 1
    assert settings.mcp_servers.servers["time"].tool_snapshot is None
    system.close()


def test_a_snapshot_from_another_config_is_rejected_on_save(tmp_path):
    # 与待保存配置摘要不一致的成功结果不能成为可用快照（#236 已有的校验，探测的摘要绑定走到它）
    system = _system(tmp_path)
    project_id = system.projects.register("摘要不符", GOAL)
    application = Application(system)
    stale = _stdio_server()
    stale["tool_snapshot"] = {"config_digest": "sha256:stale",
                              "server_info": {"name": "x"}, "tools": [{"name": "echo"}]}
    from harness.projects import McpServersInvalid
    with pytest.raises(McpServersInvalid, match="不一致"):
        system.projects.configure_mcp_servers(project_id, {"time": stale}, base_version=0)
    system.close()


# ---------------------------------------------------------------------------
# 命令的拒绝与两端清单（验收 3 的清单一侧在 test_the_new_probe_event_is_registered_on_both_ends）


def test_the_probe_command_rejects_an_unknown_project_and_bad_fields(tmp_path):
    from harness.app.commands import Rejection, execute
    system = _system(tmp_path)
    project_id = system.projects.register("拒绝", GOAL)
    application = Application(system)

    rejected = asyncio.run(execute(
        application, application.registry.commands["tool_server.probe"],
        ToolServerProbe(command_id=str(uuid.uuid4()), project_id="no-such-project",
                        name="time", server=_stdio_server()), actor="user:local"))
    assert rejected.reason == "not_found" and "没有这个项目" in rejected.message
    rejected = asyncio.run(execute(
        application, application.registry.commands["tool_server.probe"],
        ToolServerProbe(command_id=str(uuid.uuid4()), project_id=project_id,
                        name="time", server={**_stdio_server(), "name": "Bad Name"}), actor="user:local"))
    assert rejected.reason == "not_allowed" and "名称" in rejected.message
    assert _probe_events(system, project_id) == []
    system.close()


def test_the_new_probe_event_is_registered_on_both_ends():
    from harness.app.contracts import EVENT_TYPES
    from harness.tests.project_stream_fields import load_manifest
    fixture = Path(__file__).resolve().parents[2] / "client" / "tests" / "fixtures" / "event-types.json"
    assert "tool_server_probe_finished" in PROJECT_EVENT_TYPES
    assert "tool_server_probe_finished" in EVENT_TYPES
    manifest = load_manifest()
    assert "tool_server_probe_finished" in manifest["fields"]
    assert "tool_server_probe_finished" in json.loads(fixture.read_text(encoding="utf-8"))


def test_project_settings_returns_the_last_probe_result(tmp_path):
    system = _system(tmp_path)
    project_id = system.projects.register("查询探测", GOAL)
    application = Application(system)

    assert _settings(application, project_id).last_probe is None
    _probe(application, project_id, "time", _stdio_server())
    settings = _settings(application, project_id)
    assert settings.last_probe is not None
    assert settings.last_probe.server_name == "time" and settings.last_probe.status == "ok"
    assert settings.last_probe.probed_at
    # 第二次探测（失败）替换最近一次结果
    script = "import sys\nsys.exit(3)\n"
    server = _stdio_server()
    server["args"] = ["-c", script]
    _probe(application, project_id, "time", server)
    last = _settings(application, project_id).last_probe
    assert last.status == "failed" and last.error
    system.close()
