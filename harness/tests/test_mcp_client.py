# MCP 客户端模块的集成层用例（工单 #69；网络与 MCP 设计说明第 7.1 至 7.3 节、第 8 节「取消能否确认停止」）。
# 守 R2（MCP 客户端的交换形状：会话、工具清单、结果里的各类内容、取消能否确认）与
# R3（阶段二：MCP 工具经真实进程与真实本机端口调用）。真实子进程、进程树、本机端口与系统环境变量都在用，
# 按测试分层设计说明第 2 节登记为集成层。
import asyncio
import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from harness.mcp_client import (HttpServer, McpCallError, McpClient, McpStartupError, ServerLaunch, StdioServer,
                                read_stderr_tail, redact, server_environment, terminate_legacy_process)

SERVERS = Path(__file__).resolve().parent / "mcp_servers"
STDIO_SERVER = SERVERS / "stdio_server.py"
HTTP_SERVER = SERVERS / "http_server.py"
SECRET = "mcp-secret-value"

# 只说 JSON-RPC 的服务器：握手正常，工具调用一律用协议错误回答（验收第 2 条「协议错误」）
PROTOCOL_ERROR_SERVER = """
import json, sys

def send(message):
    sys.stdout.write(json.dumps(message) + "\\n")
    sys.stdout.flush()

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": request["id"], "result": {
            "protocolVersion": request["params"]["protocolVersion"], "capabilities": {"tools": {}},
            "serverInfo": {"name": "protocol-error", "version": "0"}}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": request["id"], "result": {"tools": [
            {"name": "boom", "description": "", "inputSchema": {"type": "object", "properties": {}}}]}})
    elif method == "tools/call":
        send({"jsonrpc": "2.0", "id": request["id"],
              "error": {"code": -32602, "message": "invalid arguments from server"}})
    elif request.get("id") is not None:
        send({"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32601, "message": "unknown method"}})
"""



def _launch(tmp_path, *, args=None, env=None, secrets=(SECRET,), call_timeout=30.0, command=None,
            startup_timeout=60.0):
    return ServerLaunch(
        name="test-stdio",
        stdio=StdioServer(command=command or sys.executable,
                          args=tuple(args if args is not None else [str(STDIO_SERVER)]),
                          env=dict(env or {})),
        startup_timeout_sec=startup_timeout,
        call_timeout_sec=call_timeout,
        stderr_log_path=str(tmp_path / "mcp-stderr.log"),
        secrets=tuple(secrets),
    )


def _http_launch(url, *, call_timeout=30.0):
    return ServerLaunch(name="test-http", http=HttpServer(url=url),
                        startup_timeout_sec=60.0, call_timeout_sec=call_timeout)


def _alive(pid):
    return psutil.pid_exists(pid) and psutil.Process(pid).is_running()


def _gone(pid, *, timeout=20.0):
    # 结束进程是异步的：等到它真的不在了，最多等 timeout 秒
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return not _alive(pid)


def _free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _wait_for_port(port, *, timeout=60.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise AssertionError(f"测试服务器没有在 {timeout} 秒内开始监听 127.0.0.1:{port}")


@contextlib.contextmanager
def _streamable_http_server(tmp_path):
    # 起一个真实的 streamable HTTP 测试服务器（真实进程与真实本机端口），交出它的地址
    port = _free_port()
    log = (tmp_path / "http-stderr.log").open("wb")
    process = subprocess.Popen([sys.executable, str(HTTP_SERVER), str(port)],
                               stdout=subprocess.DEVNULL, stderr=log)
    try:
        _wait_for_port(port)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        process.kill()
        process.wait(timeout=15)
        log.close()



def test_a_stdio_server_lists_its_tools_and_answers_calls(tmp_path):
    async def scenario():
        client = await McpClient.start(_launch(tmp_path))
        try:
            assert client.info is not None and client.info.name == "yudao-test-stdio"
            assert "echo" in {tool.name for tool in await client.list_tools()}
            assert (await client.call_tool("echo", {"text": "你好"})).text == "你好"
            structured = await client.call_tool("structured", {"answer": 7})
            assert structured.structured_content == {"answer": 7}
            image = await client.call_tool("image")
            block = next(block for block in image.content if block.kind == "image")
            assert block.media_type == "image/png" and block.data
            assert len((await client.call_tool("big", {"chars": 200_000})).text) == 200_000
            assert client.pid is not None and client.process_create_time is not None
        finally:
            await client.close()

    asyncio.run(scenario())


def test_a_tool_error_is_a_completed_result_with_its_error_code(tmp_path):
    async def scenario():
        client = await McpClient.start(_launch(tmp_path))
        try:
            failed = await client.call_tool("failing_tool")
            assert failed.is_error and failed.error_code == "tool_error"
        finally:
            await client.close()

    asyncio.run(scenario())


def test_a_timeout_cancels_the_call_and_reports_that_it_is_confirmed(tmp_path):
    async def scenario():
        client = await McpClient.start(_launch(tmp_path, call_timeout=2.0))
        try:
            child_pid = json.loads((await client.call_tool("spawn_child")).text)["pid"]
            started = time.monotonic()
            cancelled = await client.call_tool("slow", {"seconds": 120})
            assert time.monotonic() - started < 60
            assert cancelled.cancelled and cancelled.cancel_confirmed is True
            assert not _alive(child_pid)
        finally:
            await client.close()

    asyncio.run(scenario())


def test_closing_a_stdio_server_ends_its_whole_process_tree(tmp_path):
    async def scenario():
        client = await McpClient.start(_launch(tmp_path))
        server_pid = client.pid
        child_pid = json.loads((await client.call_tool("spawn_child")).text)["pid"]
        await client.close()
        assert server_pid is not None and not _alive(server_pid)
        assert not _alive(child_pid)

    asyncio.run(scenario())


def test_a_legacy_process_tree_is_really_ended_by_identity(tmp_path):
    # 遗留进程的清理要真的把后台那一棵树结束：父进程自己再起一个子进程，两项都对得上时一起结束；
    # 创建时间对不上时不结束（防误杀复用了同一个进程标识的别的进程）
    script = ("import subprocess, sys, time\n"
              "child = subprocess.Popen([sys.executable, '-c', 'import time\\nwhile True: time.sleep(0.2)'])\n"
              "print(child.pid, flush=True)\n"
              "while True: time.sleep(0.2)\n")
    parent = psutil.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
    try:
        child_pid = int(parent.stdout.readline().strip())
        created = parent.create_time()
        assert _alive(parent.pid) and _alive(child_pid)
        assert terminate_legacy_process(parent.pid, created + 120) is False
        assert _alive(parent.pid)
        assert terminate_legacy_process(parent.pid, created) is True
        assert _gone(parent.pid) and _gone(child_pid)
        assert terminate_legacy_process(parent.pid, created) is False
    finally:
        if parent.poll() is None:
            parent.kill()
        for child in psutil.Process(parent.pid).children(recursive=True) if psutil.pid_exists(parent.pid) else []:
            child.kill()


def test_a_streamable_http_server_lists_its_tools_and_answers_calls(tmp_path):
    # HTTP 传输：同一个客户端模块经真实本机端口连一个 streamable HTTP 服务器
    async def scenario(url):
        client = await McpClient.start(_http_launch(url))
        try:
            assert client.info is not None and client.info.name == "yudao-test-http"
            assert "echo" in {tool.name for tool in await client.list_tools()}
            assert (await client.call_tool("echo", {"text": "你好"})).text == "你好"
            return client.info.name
        finally:
            await client.close()

    with _streamable_http_server(tmp_path) as url:
        assert asyncio.run(scenario(url)) == "yudao-test-http"


def test_an_http_timeout_reports_that_the_cancel_cannot_be_confirmed(tmp_path):
    # HTTP 一侧：超时以后关闭会话，无法确认服务器已停止（设计说明第 8 节）
    async def scenario(url):
        client = await McpClient.start(_http_launch(url, call_timeout=2.0))
        try:
            started = time.monotonic()
            cancelled = await client.call_tool("slow", {"seconds": 120})
            assert time.monotonic() - started < 60
            assert cancelled.cancelled and cancelled.cancel_confirmed is False
        finally:
            await client.close()

    with _streamable_http_server(tmp_path) as url:
        asyncio.run(scenario(url))


def test_an_unknown_tool_is_reported_as_a_tool_failure(tmp_path):
    # 服务器把认不出的工具当成工具失败回答（is_error）：动作记为已完成，错误文本交回模型（设计说明第 7.3 节）
    async def scenario():
        client = await McpClient.start(_launch(tmp_path))
        try:
            result = await client.call_tool("no_such_tool")
            assert result.is_error and result.error_code == "tool_error"
        finally:
            await client.close()

    asyncio.run(scenario())


def test_a_protocol_error_carries_the_error_code(tmp_path):
    # 协议错误（JSON-RPC 的 error 应答）不是工具失败：抛出带错误码的 McpCallError（设计说明第 7.3 节）
    async def scenario():
        client = await McpClient.start(_launch(tmp_path, args=["-c", PROTOCOL_ERROR_SERVER]))
        try:
            with pytest.raises(McpCallError) as failure:
                await client.call_tool("boom")
            assert failure.value.code == "-32602"
        finally:
            await client.close()

    asyncio.run(scenario())


def test_a_windows_command_shell_starts_like_npx(tmp_path):
    # npx 这类命令在 Windows 上是不带扩展名的 .cmd 外壳：SDK 补全扩展名，客户端按它启动
    if os.name != "nt":
        pytest.skip("这一条验证的是 Windows 上的 .cmd 外壳")
    shim = tmp_path / "fake-mcp.cmd"
    shim.write_text(f'@echo off\r\n"{sys.executable}" "{STDIO_SERVER}" %*\r\n', encoding="utf-8")

    async def scenario():
        client = await McpClient.start(_launch(tmp_path, command=str(shim.with_suffix(""))))
        try:
            assert "echo" in {tool.name for tool in await client.list_tools()}
            assert (await client.call_tool("echo", {"text": "外壳"})).text == "外壳"
        finally:
            await client.close()

    asyncio.run(scenario())


def test_the_official_mcp_server_time_starts_through_uvx(tmp_path):
    # 验收第 1 条：官方的 mcp-server-time 经 uvx 启动（stdio），列出工具并调用一次。
    # 取不到包（没有 uvx、没有网络或缓存里没有）时跳过，并写明缺什么
    uvx = shutil.which("uvx")
    if uvx is None:
        pytest.skip("缺 uvx：PATH 上没有 uvx，取不到官方 mcp-server-time")

    async def scenario():
        try:
            client = await McpClient.start(ServerLaunch(
                name="mcp-server-time",
                stdio=StdioServer(command=uvx, args=("mcp-server-time",)),
                startup_timeout_sec=300.0, call_timeout_sec=120.0,
                stderr_log_path=str(tmp_path / "time-stderr.log")))
        except McpStartupError as failure:
            pytest.skip(f"取不到官方 mcp-server-time（uvx 启动失败）：{failure}")
        try:
            assert "get_current_time" in {tool.name for tool in await client.list_tools()}
            result = await client.call_tool("get_current_time", {"timezone": "Asia/Shanghai"})
            assert "2026-" in result.text or "2027-" in result.text
            return result.text
        finally:
            await client.close()

    assert asyncio.run(scenario())


def test_the_child_gets_the_passed_variables_and_the_base_ones_only(tmp_path):
    secret_key = "MCP_TEST_SECRET"

    async def scenario():
        client = await McpClient.start(_launch(tmp_path, env={"YUDAO_MCP_TEST": "passed", secret_key: SECRET}))
        try:
            report = json.loads((await client.call_tool("environment")).text)
        finally:
            await client.close()
        return report

    report = asyncio.run(scenario())
    environment = report["env"]
    assert environment["YUDAO_MCP_TEST"] == "passed"
    assert environment[secret_key] == SECRET
    assert "PATH" in environment and "SYSTEMROOT" in environment
    # 没有传给它的变量不出现：调用方的整个环境变量不进入子进程（本模块自己的语义，设计说明第 7.2 节）
    for name in os.environ:
        if name not in server_environment({"YUDAO_MCP_TEST": "passed", secret_key: SECRET}):
            assert name not in environment


def test_a_startup_failure_reports_the_stderr_tail_with_the_secret_redacted(tmp_path):
    script = ("import os, sys\n"
              "print('STARTUP FAILURE ' + os.environ.get('MCP_TEST_SECRET', ''), file=sys.stderr)\n"
              "sys.exit(3)\n")

    async def scenario():
        with pytest.raises(McpStartupError) as failure:
            await McpClient.start(_launch(tmp_path, args=["-c", script], env={"MCP_TEST_SECRET": SECRET}))
        return str(failure.value)

    message = asyncio.run(scenario())
    assert "STARTUP FAILURE" in message
    assert SECRET not in message and "***" in message


def test_the_stderr_tail_is_bounded_and_redacted(tmp_path):
    log = tmp_path / "stderr.log"
    log.write_text("y" * 6000 + "\n凭据 " + SECRET + " 出现在这里\n", encoding="utf-8")
    tail = read_stderr_tail(str(log), secrets=(SECRET,))
    assert SECRET not in tail and "***" in tail
    assert len(tail) <= 4000
    assert redact(f"a {SECRET} b", (SECRET,)) == "a *** b"


def test_the_child_environment_holds_the_base_variables():
    environment = server_environment({"YUDAO_MCP_TEST": "passed"})
    assert environment["YUDAO_MCP_TEST"] == "passed"
    assert "PATH" in environment
    if os.name == "nt":
        assert "COMSPEC" in environment and "WINDIR" in environment
