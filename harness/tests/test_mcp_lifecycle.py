# MCP 服务器的生命周期（工单 #1176；网络与 MCP 设计说明「运行规则」、「调用与结果」、「恢复契约」、「应用层接口」；恢复契约「动作分类与处置」
# 「动作分类与处置」；总图第四节「动作」缝：每个动作有回执，结果未知时有核实办法）。
#
# 验收一：run 结束时关闭这个 run 的服务器实例，整个进程树结束，run 流里的生命周期事件齐全
# （mcp_server_started 带服务器名称、传输、进程标识与创建时间；mcp_server_closed；启动失败时 mcp_server_failed）。
# 验收二：MCP 工具调用进行中终止真实的 Yudao 进程，重新启动以后这次调用作为工具结果交还发出它的会话
# （resolution="handed_back"，写明执行被中断、结果未知），没有自动重新执行、也没有决定请求；没有关闭记录的
# 服务器在启动时结束并补写 mcp_server_closed。
# 验收三：调用超时先取消，stdio 结束整个进程树、HTTP 关闭会话，回执写明取消能否确认（stdio 为能、HTTP 为不能），
# 然后按结果未知交还发出它的会话。
#
# 层：集成层（真实 MCP 子进程与进程树、真实进程中断与重启、真实本机端口）。
# 守 R2（生命周期事件的种类与交换字段：服务器名称、传输、进程标识与创建时间、关闭原因；结果未知动作交还的
# 交换字段）与 R3（阶段二：MCP 服务器的生命周期与恢复处置，经真实进程与真实事件流检查）。
# 中断与重启这一条自己起子进程（python -m harness.tests.test_mcp_lifecycle --child），样板是
# harness/tests/process_kill.py：先终止 Yudao 进程本身并等它退出，再观察它留下的服务器进程。

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import psutil

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.artifacts import ArtifactRef
from harness.models import EventType
from harness.proposals import product_spec, product_spec_turn
from harness.projects import normalize_mcp_servers
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.tests.helpers import explore_turn
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

REPO_ROOT = Path(__file__).resolve().parents[2]
GOAL = "做一个可以长期演进的逐行文本处理工具。"
SERVER_NAME = "lifecycle"
ECHO = "mcp__lifecycle__echo"
HANG = "mcp__lifecycle__hang"
SLOW = "mcp__http_slow__slow"
HANG_CALL = "call-hang"
ECHO_CALL = "call-echo"
# 调用超时用的小时限：设置里可以改（docs/design/network-and-mcp.md「运行规则」），默认 120 秒不适合用例
SHORT_CALL_TIMEOUT_SEC = 2

# 测试用的 MCP 服务器（官方 SDK 写的真实进程）：`echo` 正常回应，`hang` 写下标记以后一直不回应
# （调用停在飞行中，父进程按这个标记终止 Yudao）。进程启动时自己起一个子进程，并把自己的进程标识与
# 子进程的进程标识写进标记目录：关闭服务器、超时取消与遗留清理都要结束整棵进程树。
LIFECYCLE_SERVER = '''
import json
import os
import subprocess
import sys
import time

from mcp.server.mcpserver import MCPServer

MARKER_DIR = os.environ.get("YUDAO_TEST_MARKER_DIR", "")
CHILD = subprocess.Popen([sys.executable, "-c", "import time\\nwhile True: time.sleep(0.2)"])

if MARKER_DIR:
    with open(os.path.join(MARKER_DIR, "server.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"server": os.getpid(), "child": CHILD.pid}))

server = MCPServer("yudao-test-lifecycle", version="0.0.1")


@server.tool()
def echo(text: str) -> str:
    return text


@server.tool()
def hang() -> str:
    if MARKER_DIR:
        with open(os.path.join(MARKER_DIR, "called"), "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"server": os.getpid(), "child": CHILD.pid}))
    while True:
        time.sleep(0.2)
    return "done"


if __name__ == "__main__":
    server.run("stdio")
'''

ECHO_TOOL = {"name": "echo", "description": "原样交回文本",
             "input_schema": {"type": "object", "properties": {"text": {"type": "string"}},
                              "required": ["text"]}}
HANG_TOOL = {"name": "hang", "description": "写下标记以后一直不回应",
             "input_schema": {"type": "object", "properties": {}}}
SLOW_TOOL = {"name": "slow", "description": "一直等到被取消",
             "input_schema": {"type": "object", "properties": {"seconds": {"type": "number"}},
                              "required": ["seconds"]}}


# ---------------------------------------------------------------------------
# 设置文档、模型脚本与系统

def _server_script(tmp_path: Path) -> Path:
    # 测试服务器的脚本写进临时目录：它是真实进程，扫描的是本文件里的源码
    path = tmp_path / "lifecycle_server.py"
    if not path.exists():
        path.write_text(LIFECYCLE_SERVER, encoding="utf-8")
    return path


def _stdio_document(tmp_path: Path, *, tools, call_timeout_sec: int = 120,
                    command: str | None = None, args: list[str] | None = None) -> dict:
    # 一台 stdio 服务器：命令是本机解释器加测试服务器脚本，标记目录按固定文本传进子进程的环境变量
    #。工具清单快照的摘要与归一化配置算出的同一份。
    # 可以使用的部门写上产品与工程：这两处各有一条用例按它们自己的会话调用工具
    server = {"name": SERVER_NAME, "transport": "stdio", "command": command or sys.executable,
              "args": list(args) if args is not None else [str(_server_script(tmp_path))],
              "departments": ["product", "engineering"],
              "call_timeout_sec": call_timeout_sec,
              "env": {"YUDAO_TEST_MARKER_DIR": {"kind": "text", "value": str(tmp_path)}}}
    document = normalize_mcp_servers({SERVER_NAME: server})
    digest = document["servers"][SERVER_NAME]["config_digest"]
    document["servers"][SERVER_NAME]["tool_snapshot"] = {
        "config_digest": digest,
        "server_info": {"name": "yudao-test-lifecycle", "version": "0.0.1",
                        "protocol_version": "2025-06-18"},
        "tools": list(tools),
    }
    return document


def _http_document(url: str) -> dict:
    # 一台 streamable HTTP 服务器：没有进程，超时以后关闭会话（取消无法确认，docs/design/network-and-mcp.md「恢复契约」）。
    # 名称只能用字母、数字与连字符（projects.normalize_mcp_servers），别名里的连字符收敛成下划线
    server = {"name": "http-slow", "transport": "http", "url": url, "departments": ["engineering"],
              "call_timeout_sec": SHORT_CALL_TIMEOUT_SEC}
    document = normalize_mcp_servers({"http-slow": server})
    digest = document["servers"]["http-slow"]["config_digest"]
    document["servers"]["http-slow"]["tool_snapshot"] = {
        "config_digest": digest,
        "server_info": {"name": "yudao-test-http", "version": "0.0.1", "protocol_version": "2025-06-18"},
        "tools": [SLOW_TOOL],
    }
    return document


def _mcp_turn(alias: str, arguments: dict, identity: str) -> ModelResponse:
    return ModelResponse(output=[{"id": identity, "call_id": identity, "type": "function_call",
                                  "name": alias, "arguments": json.dumps(arguments)}])


def _lifecycle_script(alias: str, arguments: dict, identity: str) -> dict:
    # 产品先提交规格；工程调一次 MCP 工具，交回结果以后这一轮结束；质检只探索
    return {"product": [product_spec_turn()],
            "engineering": [_mcp_turn(alias, arguments, identity), FakeTurn(transcript="调用完成")],
            "quality": [explore_turn(), explore_turn(), explore_turn()]}


def _system(tmp_path: Path, script) -> LoopSystem:
    return LoopSystem.for_testing(tmp_path, FakeAdapter(script), resume_on_startup=False)


def _project_with_server(system: LoopSystem, document: dict) -> str:
    project_id = system.projects.register("MCP 生命周期", GOAL)
    system.projects.configure_mcp_servers(project_id, document["servers"], base_version=0)
    return project_id


def _work_item_run(system: LoopSystem, project_id: str) -> str:
    _item, run_id = system.projects.start_work_item(project_id, GOAL)
    return run_id


def _events(system: LoopSystem, run_id: str, event_type: str | None = None) -> list[Any]:
    items = system.store.list_events(run_id)
    return items if event_type is None else [item for item in items if item.type == event_type]


def _payloads(system: LoopSystem, run_id: str, event_type: str) -> list[dict]:
    return [dict(event.payload or {}) for event in _events(system, run_id, event_type)]


def _result_text(system: LoopSystem, run_id: str, call_id: str) -> str:
    # 一次调用的工具结果正文：回执的输出引用指向这个 run 的外部来源工件（docs/design/network-and-mcp.md「调用与结果」）。
    # 结果按 read_external_source 的同一套分页交回，正文在 lines 里
    output = _result_output(system, run_id, call_id)
    lines = output.get("lines") or []
    text = "\n".join(str(line.get("text", "")) for line in lines)
    return text if text.strip() else json.dumps(output, ensure_ascii=False)


def _result_output(system: LoopSystem, run_id: str, call_id: str) -> dict:
    # 回执的输出引用指向这个 run 的外部来源工件：读出来是行页与回执字段（docs/design/network-and-mcp.md「调用与结果」的交换字段）
    called = next(event for event in _events(system, run_id, EventType.TOOL_CALLED)
                  if (event.payload or {}).get("id") == call_id)
    output_ref = (called.payload or {}).get("output_ref")
    assert output_ref is not None, "这次调用没有保存结果工件"
    raw = system.artifacts.get_for_run(run_id, ArtifactRef(**output_ref))
    return json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)


def _server_pids(tmp_path: Path) -> tuple[int, int]:
    # 测试服务器启动时写下的两个进程标识：（服务器，它自己的子进程）
    report = json.loads((tmp_path / "server.json").read_text(encoding="utf-8"))
    return int(report["server"]), int(report["child"])


def _alive(pid: int) -> bool:
    return psutil.pid_exists(pid) and psutil.Process(pid).is_running()


# 真实的一条进程树：父进程起一个子进程，交出子进程的标识以后父子都一直活着
LEFT_OVER_TREE = ("import subprocess, sys, time\n"
                  "child = subprocess.Popen([sys.executable, '-c', 'import time\\nwhile True: time.sleep(0.2)'])\n"
                  "print(child.pid, flush=True)\n"
                  "while True: time.sleep(0.2)\n")


def _append_started(system: LoopSystem, run_id: str, *, pid: int, create_time: float) -> None:
    # 一条没有关闭记录的服务器启动（上一次进程崩溃时事件日志停在这里）：形状与真实会话写下的一样
    from harness.event_store import run_stream
    from harness.write_path import NewEvent

    def decide(transaction) -> None:
        status = transaction.projection.status
        transaction.append(NewEvent(
            EventType.MCP_SERVER_STARTED, state_before=status, state_after=status, actor="system",
            payload={"server": SERVER_NAME, "transport": "stdio", "pid": pid, "create_time": create_time}))

    system.writes.transact(run_stream(run_id), decide)


def _gone(pid: int, *, timeout: float = 20.0) -> bool:
    # 结束进程是异步的：等到它真的不在了，最多等 timeout 秒
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return not _alive(pid)


# ---------------------------------------------------------------------------
# 验收一：run 结束时关闭实例，进程树全部结束，事件齐全


def test_a_run_end_closes_the_server_ends_its_process_tree_and_records_the_events(tmp_path):
    system = _system(tmp_path, _lifecycle_script(ECHO, {"text": "生命周期"}, ECHO_CALL))
    project_id = _project_with_server(system, _stdio_document(tmp_path, tools=[ECHO_TOOL, HANG_TOOL]))
    run_id = _work_item_run(system, project_id)
    system.run_until_stop(run_id)

    started = _payloads(system, run_id, EventType.MCP_SERVER_STARTED)
    closed = _payloads(system, run_id, EventType.MCP_SERVER_CLOSED)
    # 一台服务器一次会话：启动一条、关闭一条
    assert len(started) == 1 and len(closed) == 1
    assert started[0]["server"] == SERVER_NAME and started[0]["transport"] == "stdio"
    # 启动事件带着进程标识与创建时间：启动时结束遗留进程要靠这两项（docs/design/network-and-mcp.md「运行规则」）
    assert isinstance(started[0]["pid"], int) and isinstance(started[0]["create_time"], float)
    assert closed[0]["reason"] == "closed" and closed[0]["server"] == SERVER_NAME
    # 先后由事件的位置决定：调用之前启动，run 收尾时关闭
    started_event = _events(system, run_id, EventType.MCP_SERVER_STARTED)[0]
    called_event = next(event for event in _events(system, run_id, EventType.TOOL_CALLED)
                        if (event.payload or {}).get("id") == ECHO_CALL)
    closed_event = _events(system, run_id, EventType.MCP_SERVER_CLOSED)[0]
    assert started_event.position < called_event.position < closed_event.position

    # 整个进程树都结束了：服务器与它自己起的子进程。记录下来的进程标识是客户端启动的那一个进程
    # （Windows 的 venv 里它是转交给真正解释器的启动器），服务器是它的子进程
    server_pid, child_pid = _server_pids(tmp_path)
    assert started[0]["pid"] is not None
    assert _gone(int(started[0]["pid"]))
    assert _gone(server_pid) and _gone(child_pid)

    # 结果照常交回模型，动作记为已完成（docs/design/network-and-mcp.md「调用与结果」：工具失败以外都是已完成的动作）
    assert called_event.payload["ok"] is True
    assert "生命周期" in _result_text(system, run_id, ECHO_CALL)
    assert _payloads(system, run_id, EventType.MCP_SERVER_FAILED) == []
    system.close()


def test_a_server_that_cannot_start_is_recorded_as_failed_and_does_not_stop_the_item(tmp_path):
    # 启动失败仍然把原因作为工具结果交回部门（docs/design/network-and-mcp.md「运行规则」），生命周期记一条 mcp_server_failed。
    # 命令照常是解释器，脚本换成一开始就写下原因并退出的那一行
    failing = _stdio_document(
        tmp_path, tools=[ECHO_TOOL], command=sys.executable,
        args=["-c", "import sys; sys.stderr.write('BOOM\\n'); sys.exit(3)"])
    system = _system(tmp_path, _lifecycle_script(ECHO, {"text": "起不来"}, ECHO_CALL))
    project_id = _project_with_server(system, failing)
    run_id = _work_item_run(system, project_id)
    system.run_until_stop(run_id)

    failed = _payloads(system, run_id, EventType.MCP_SERVER_FAILED)
    assert len(failed) == 1 and failed[0]["server"] == SERVER_NAME
    assert failed[0]["transport"] == "stdio" and "BOOM" in failed[0]["error"]
    # 这一次会话没有建立：没有启动事件，也没有关闭事件
    assert _payloads(system, run_id, EventType.MCP_SERVER_STARTED) == []
    assert _payloads(system, run_id, EventType.MCP_SERVER_CLOSED) == []
    # 工具调用照常交回失败的原因（is_error），事项继续做到结束
    output = _result_output(system, run_id, ECHO_CALL)
    assert output["is_error"] is True and output["error_code"] == "startup_failed"
    assert "BOOM" in _result_text(system, run_id, ECHO_CALL)
    system.close()


def test_a_cancelled_run_cancels_the_call_closes_the_server_and_ends_its_tree(tmp_path):
    # 验收一的「停止」：运行中取消（用户停止）时，进行中的 MCP 调用先取消，会话关闭，
    # 进程树结束，run 流里有启动与关闭两条事件
    document = _stdio_document(tmp_path, tools=[ECHO_TOOL, HANG_TOOL])
    system = _system(tmp_path, _lifecycle_script(HANG, {}, HANG_CALL))
    project_id = _project_with_server(system, document)
    run_id = _work_item_run(system, project_id)
    marker = tmp_path / "called"

    def cancel_after_the_call_arrives() -> None:
        # 调用到达服务器（标记文件）以后再取消：这一刻调用确定在飞行中，取消总是落在它上面
        deadline = time.monotonic() + WAIT_FOR_HOST_WORK_SEC
        while time.monotonic() < deadline and not marker.exists():
            time.sleep(0.05)
        system.cancel(run_id)

    canceller = threading.Thread(target=cancel_after_the_call_arrives, daemon=True)
    canceller.start()
    try:
        projection = system.run_until_stop(run_id)
    finally:
        canceller.join(WAIT_FOR_HOST_WORK_SEC)
    assert projection.status == "failed" and projection.stop_reason == "cancelled"

    # 会话在停止时关闭：进程树全部结束，关闭事件写在 run 流里
    started = _payloads(system, run_id, EventType.MCP_SERVER_STARTED)
    closed = _payloads(system, run_id, EventType.MCP_SERVER_CLOSED)
    assert len(started) == 1 and len(closed) == 1
    assert closed[0]["reason"] in {"cancelled", "closed"}
    server_pid, child_pid = _server_pids(tmp_path)
    assert _gone(int(started[0]["pid"])) and _gone(server_pid) and _gone(child_pid)
    system.close()


# ---------------------------------------------------------------------------
# 验收二：中断以后交还，遗留的服务器进程在启动时结束并补写关闭事件

def test_a_startup_ends_a_leftover_server_and_writes_the_close_event(tmp_path):
    # 上一次进程崩溃留下的样子：有启动事件、没有关闭记录，记录的进程还活着。
    # 下一个进程打开数据目录时按启动事件里的进程标识与创建时间结束整棵进程树，并补写 mcp_server_closed
    system = _system(tmp_path, {})
    project_id = _project_with_server(system, _stdio_document(tmp_path, tools=[ECHO_TOOL]))
    run_id = _work_item_run(system, project_id)
    # 真实的进程树（父进程 + 它自己起的子进程），进程标识与创建时间按服务器启动事件记下来。
    # 状态的构造与 test_issue_17_action_recovery 一样直接用写入口：进程崩溃时事件日志就停在这个样子
    tree = psutil.Popen([sys.executable, "-c", LEFT_OVER_TREE], stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, text=True)
    try:
        child_pid = int(tree.stdout.readline().strip())
        _append_started(system, run_id, pid=tree.pid, create_time=tree.create_time())
        assert _alive(tree.pid) and _alive(child_pid)
        system.store.close()

        restarted = LoopSystem.for_testing(tmp_path, FakeAdapter([]), resume_on_startup=False)
        try:
            closed = _payloads(restarted, run_id, EventType.MCP_SERVER_CLOSED)
            assert len(closed) == 1 and closed[0]["reason"] == "leftover"
            assert closed[0]["pid"] == tree.pid and closed[0]["ended"] is True
            # 整棵进程树都结束了
            assert _gone(tree.pid) and _gone(child_pid)
        finally:
            restarted.close()
    finally:
        if tree.poll() is None:
            tree.kill()
            tree.wait(timeout=30)


def test_a_killed_call_is_handed_back_and_the_restart_ends_the_leftover_server(tmp_path):
    # 验收二：调用进行中终止真实的 Yudao 进程，重新启动以后这次调用作为工具结果交还发出它的会话
    data_dir = tmp_path / "data"
    marker = tmp_path / "marker"
    marker.mkdir()
    log = tmp_path / "yudao.log"
    process = _spawn_child(data_dir, marker, log)
    try:
        _wait_for(marker / "called", process, log)
    finally:
        _kill(process)

    # 终止以后：工具开始事件在，结果事件不在；服务器启动了，还没有关闭记录
    observed = _observe(data_dir)
    run_id = observed["run_id"]
    assert [event.type for event in observed["events"] if event.type == EventType.TOOL_CALLED
            and (event.payload or {}).get("id") == HANG_CALL] == []
    started = [dict(event.payload or {}) for event in observed["events"]
               if event.type == EventType.MCP_SERVER_STARTED]
    assert len(started) == 1 and started[0]["server"] == SERVER_NAME
    assert [event for event in observed["events"]
            if event.type == EventType.MCP_SERVER_CLOSED] == [], "终止以前不应当有关闭记录"
    server_pid, child_pid = _server_pids(marker)

    restarted = _open_after_kill(data_dir)
    try:
        # 启动时结束遗留的服务器进程，补写关闭事件
        closed = _payloads(restarted, run_id, EventType.MCP_SERVER_CLOSED)
        assert len(closed) == 1 and closed[0]["reason"] == "leftover"
        assert closed[0]["pid"] == started[0]["pid"]
        assert _gone(server_pid) and _gone(child_pid)

        # 恢复：结果未知的调用交还发出它的会话，然后继续这个 run
        restarted.resume_startup_runs()
        verified = _events(restarted, run_id, EventType.ACTION_VERIFIED)
        [handed_back] = [event for event in verified if (event.payload or {}).get("id") == HANG_CALL]
        payload = handed_back.payload
        assert payload["resolution"] == "handed_back" and payload["ok"] is False
        assert "执行被中断" in payload["error"] and "结果未知" in payload["error"]
        started_event = [event for event in observed["events"] if event.type == EventType.TOOL_STARTED
                         and (event.payload or {}).get("id") == HANG_CALL]
        assert len(started_event) == 1, "终止以前应当有一条工具开始事件"
        assert handed_back.session_id == started_event[0].session_id

        # 没有自动重新执行（整个 run 里只有一次 tool_started）、没有决定请求、没有决定请求的撤回
        assert len([event for event in _events(restarted, run_id, EventType.TOOL_STARTED)
                    if (event.payload or {}).get("id") == HANG_CALL]) == 1
        assert [event for event in _events(restarted, run_id, EventType.DECISION_REQUESTED)
                if (event.payload or {}).get("kind") == "unknown_action"] == []
    finally:
        restarted.close()


# ---------------------------------------------------------------------------
# 验收三：调用超时先取消再交还，回执写明取消能否确认


def test_a_call_timeout_cancels_first_and_hands_the_result_back(tmp_path):
    document = _stdio_document(tmp_path, tools=[ECHO_TOOL, HANG_TOOL],
                               call_timeout_sec=SHORT_CALL_TIMEOUT_SEC)
    system = _system(tmp_path, _lifecycle_script(HANG, {}, HANG_CALL))
    project_id = _project_with_server(system, document)
    run_id = _work_item_run(system, project_id)
    system.run_until_stop(run_id)

    output = _result_output(system, run_id, HANG_CALL)
    assert output["is_error"] is True and output["error_code"] == "cancelled"
    text = _result_text(system, run_id, HANG_CALL)
    # 回执写明取消能否确认（stdio 为能），并写明执行被中断、结果未知
    assert "取消能确认服务器已停止" in text and "取消不能确认服务器已停止" not in text
    assert "执行被中断" in text and "结果未知" in text
    # 取消以后整个进程树结束：服务器与它自己起的子进程
    server_pid, child_pid = _server_pids(tmp_path)
    assert _gone(server_pid) and _gone(child_pid)
    # 会话在取消以后关闭，写了一条取消原因的关闭事件
    closed = _payloads(system, run_id, EventType.MCP_SERVER_CLOSED)
    assert len(closed) == 1 and closed[0]["reason"] == "cancelled"
    # 没有自动重新执行、没有决定请求
    assert len([event for event in _events(system, run_id, EventType.TOOL_STARTED)
                if (event.payload or {}).get("id") == HANG_CALL]) == 1
    assert [event for event in _events(system, run_id, EventType.DECISION_REQUESTED)
            if (event.payload or {}).get("kind") == "unknown_action"] == []
    system.close()


def test_an_http_call_timeout_reports_that_the_cancel_cannot_be_confirmed(tmp_path):
    with _streamable_http_server(tmp_path) as url:
        system = _system(tmp_path, _lifecycle_script(SLOW, {"seconds": 120}, HANG_CALL))
        project_id = _project_with_server(system, _http_document(url))
        run_id = _work_item_run(system, project_id)
        system.run_until_stop(run_id)

        output = _result_output(system, run_id, HANG_CALL)
        assert output["is_error"] is True and output["error_code"] == "cancelled"
        assert output["transport"] == "http"
        text = _result_text(system, run_id, HANG_CALL)
        # HTTP 关闭会话，无法确认服务器停止
        assert "取消不能确认服务器已停止" in text and "取消能确认服务器已停止" not in text
        assert "执行被中断" in text and "结果未知" in text
        started = _payloads(system, run_id, EventType.MCP_SERVER_STARTED)
        assert len(started) == 1 and started[0]["transport"] == "http" and started[0]["pid"] is None
        system.close()


# ---------------------------------------------------------------------------
# 中断与重启：子进程入口与父进程这一侧的辅助（样板 harness/tests/process_kill.py）

def _child_script() -> dict:
    # 子进程里的脚本：产品的一次回答就是那次 MCP 调用（进程在调用飞行中被终止），
    # 重启以后产品继续提交规格，其余部门照常
    return {"product": [_mcp_turn(HANG, {}, HANG_CALL)],
            "engineering": [{"proposal": {"kind": "delivery_spec"}}],
            "quality": [{"proposal": {"kind": "quality_auto"}}]}


def _child_tail_script() -> dict:
    return {"product": [{"proposal": product_spec()}],
            "engineering": [{"proposal": {"kind": "delivery_spec"}}],
            "quality": [{"proposal": {"kind": "quality_auto"}}]}


def _child_main(data_dir: Path, marker: Path) -> None:
    # 子进程入口：打开数据目录，让工程的这次工作调用一次一直不回应 MCP 工具，运行到停止（父进程在调用
    # 飞行中终止这个进程）。会话不关闭：进程被终止时连同数据目录一起停下
    system = LoopSystem.for_testing(data_dir, FakeAdapter(_child_script()), resume_on_startup=False)
    project_id = system.projects.register("MCP 生命周期", GOAL)
    document = _stdio_document(marker, tools=[ECHO_TOOL, HANG_TOOL])
    system.projects.configure_mcp_servers(project_id, document["servers"], base_version=0)
    _item, run_id = system.projects.start_work_item(project_id, GOAL)
    result = system.run_until_stop(run_id)
    print(json.dumps({"run_id": run_id, "status": result.status, "stop_reason": result.stop_reason,
                      "error": result.error}, ensure_ascii=False), flush=True)


def _spawn_child(data_dir: Path, marker: Path, log: Path) -> subprocess.Popen:
    environment = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    spawn = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    data_dir.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, "-m", "harness.tests.test_mcp_lifecycle", str(data_dir), str(marker)]
    with log.open("wb") as output:
        return subprocess.Popen(argv, cwd=REPO_ROOT, env=environment, stdout=output,
                                stderr=subprocess.STDOUT, **spawn)


def _wait_for(marker: Path, process: subprocess.Popen, log: Path) -> None:
    # 等到 MCP 服务器写下「调用已经到了」的标记；进程在此之前退出时报告它的日志
    deadline = time.monotonic() + WAIT_FOR_HOST_WORK_SEC
    while time.monotonic() < deadline:
        if marker.exists():
            return
        if process.poll() is not None:
            raise AssertionError(f"Yudao 进程在调用到达服务器以前就结束了：{_log(log)}")
        time.sleep(0.05)
    raise TimeoutError(f"调用没有到达 MCP 服务器：{_log(log)}")


def _kill(process: subprocess.Popen) -> None:
    # 先终止 Yudao 进程本身并等它退出（样板 process_kill._kill）：服务器进程的观察在它退出以后才有意义
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        process.kill()
    process.wait(WAIT_FOR_HOST_WORK_SEC)


def _log(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _observe(data_dir: Path) -> dict:
    # 只读地读出终止以后、任何系统打开它以前的事件：之后打开的系统会在启动时结束遗留进程并补写关闭事件
    from harness.event_store import EventStore

    deadline = time.monotonic() + WAIT_FOR_HOST_WORK_SEC
    while True:
        try:
            store = EventStore(data_dir / "events.sqlite", read_only=True)
            break
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.2)
    try:
        run_id = next(item for item in store.list_run_ids()
                      if any(event.type == EventType.RUN_CREATED for event in store.list_events(item)))
        return {"run_id": run_id, "events": store.list_events(run_id)}
    finally:
        store.close()


def _open_after_kill(data_dir: Path) -> LoopSystem:
    # 重新打开数据目录：启动时结束遗留的服务器进程并补写关闭事件。进程刚被终止时事件库的文件还会被
    # 短暂占用，打开失败按上限重试（样板 process_kill._open_system_after_kill）
    deadline = time.monotonic() + WAIT_FOR_HOST_WORK_SEC
    while True:
        try:
            return LoopSystem.for_testing(data_dir, FakeAdapter(_child_tail_script()), resume_on_startup=False)
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.2)


# ---------------------------------------------------------------------------
# 本机 HTTP 服务器（真实进程与真实端口）：slow 工具一直等到被取消

def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _wait_for_port(port: int, *, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise AssertionError(f"测试服务器没有在 {timeout} 秒内开始监听 127.0.0.1:{port}")


@contextlib.contextmanager
def _streamable_http_server(tmp_path: Path):
    # 起一个真实的 streamable HTTP 测试服务器（真实进程与真实本机端口），交出它的地址
    server_script = Path(__file__).resolve().parent / "mcp_servers" / "http_server.py"
    port = _free_port()
    log = (tmp_path / "http-server.log").open("wb")
    process = subprocess.Popen([sys.executable, str(server_script), str(port)],
                               stdout=subprocess.DEVNULL, stderr=log)
    try:
        _wait_for_port(port)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        process.kill()
        process.wait(timeout=30)
        log.close()


if __name__ == "__main__":
    # 子进程入口（见 _spawn_child）：python -m harness.tests.test_mcp_lifecycle <数据目录> <标记目录>
    _child_main(Path(sys.argv[1]), Path(sys.argv[2]))
