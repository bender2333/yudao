# MCP 客户端模块的集成层用例（工单 #69；网络与 MCP 设计说明第 7.1 至 7.3 节、第 8 节「取消能否确认停止」）。
# 守 R2（MCP 客户端的交换形状：会话、工具清单、结果里的各类内容、取消能否确认）与
# R3（阶段二：MCP 工具经真实进程与真实本机端口调用）。真实子进程、进程树与系统环境变量都在用，
# 按测试分层设计说明第 2 节登记为集成层。
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import psutil
import pytest

from harness.mcp_client import (McpClient, McpStartupError, ServerLaunch, StdioServer, read_stderr_tail,
                                redact, server_environment, terminate_legacy_process)

SERVERS = Path(__file__).resolve().parent / "mcp_servers"
STDIO_SERVER = SERVERS / "stdio_server.py"
SECRET = "mcp-secret-value"


def _launch(tmp_path, *, args=None, env=None, secrets=(SECRET,), call_timeout=30.0):
    return ServerLaunch(
        name="test-stdio",
        stdio=StdioServer(command=sys.executable,
                          args=tuple(args if args is not None else [str(STDIO_SERVER)]),
                          env=dict(env or {})),
        startup_timeout_sec=60.0,
        call_timeout_sec=call_timeout,
        stderr_log_path=str(tmp_path / "mcp-stderr.log"),
        secrets=tuple(secrets),
    )


def _alive(pid):
    return psutil.pid_exists(pid) and psutil.Process(pid).is_running()


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


def test_a_legacy_process_is_ended_by_identity():
    process = psutil.Popen([sys.executable, "-c", "import time\nwhile True: time.sleep(0.2)"])
    try:
        created = process.create_time()
        assert terminate_legacy_process(process.pid, created)
        process.wait(timeout=15)
        assert not terminate_legacy_process(process.pid, created)
        assert not terminate_legacy_process(process.pid, created + 60)
    finally:
        if process.poll() is None:
            process.kill()


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
