# bash 与检查的整棵进程树（工单 #1215）：命令自己留下后台子进程、子进程接住输出管道时，调用仍然按时
# 返回；超时、取消、停止后台作业与会话结束四条路都一次结束整棵树，包括「直接子进程已经退出、它起的
# 子进程还在」这一种。命令自己正常结束时留下的子进程随这次调用一起结束，回执写明这件事。
# 这些结论要真实子进程与监听端口，登记为集成层（test-pyramid.md 第 2 节只允许集成层用子进程）。
from __future__ import annotations

import asyncio
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from harness.adapters.fake import FakeAdapter
from harness.environment import BackgroundJobTable, LocalEnvironment
from harness.runtime import LoopSystem
from harness.tests.helpers import action, perform, pid_alive, wait_for_file, wait_until_stopped
from harness.workspace import Workspace


def _environment(path: Path, **kwargs) -> LocalEnvironment:
    kwargs.setdefault("session_id", "test-session")
    kwargs.setdefault("jobs", BackgroundJobTable())
    return LocalEnvironment(Workspace(path / "ws"), **kwargs)


def _python() -> str:
    return sys.executable.replace("\\", "/")


def _leftover_program(seconds: int, marker: Path) -> str:
    # 一段自己留后台子进程的程序：子进程接住输出管道（调用结束时管道应该还开着），并把自己的进程号写进标记
    return ("import pathlib,subprocess,sys,time;"
            "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(%d)']);"
            "print('left a child running: %%d' %% child.pid,flush=True);"
            "pathlib.Path(r'%s').write_text(str(child.pid),encoding='utf-8')" % (seconds, marker))


def _leaves_a_child(marker: Path, *, seconds: int = 300, tail: str = "sleep 300") -> str:
    # 在子 shell 里把上面那段程序放到后台，再让直接子进程（bash）继续跑 tail：
    # 后台子进程与 bash 不在同一棵「父进程链」上，直接子进程退出以后它还在，且输出管道仍然开着
    return f'({_python()} -c "{_leftover_program(seconds, marker)}" &) ; {tail}'


def _server_program(port: int, marker: Path) -> str:
    # 一个真的监听端口、留下自己的进程号的服务：用来核对「取消以后机器上不留进程与监听端口」
    return ("import http.server,os,pathlib;"
            "pathlib.Path(r'%s').write_text(str(os.getpid()),encoding='utf-8');"
            "http.server.HTTPServer(('127.0.0.1',%d),http.server.SimpleHTTPRequestHandler).serve_forever()"
            % (marker, port))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _wait_listening(port: int) -> None:
    for _ in range(400):
        if _listening(port):
            return
        time.sleep(0.05)
    raise AssertionError(f"the service never listened on port {port}")


def _wait_not_listening(port: int) -> bool:
    for _ in range(200):
        if not _listening(port):
            return True
        time.sleep(0.05)
    return False


def _read_pid(marker: Path) -> int:
    wait_for_file(marker)
    return int(marker.read_text(encoding="utf-8").strip())


def test_timeout_returns_and_stops_a_command_that_leaves_a_background_child(tmp_path):
    # 验收第 1 条：命令留下接住输出管道的后台子进程时，调用在时限附近返回，回执写超时与进程树已停止，
    # 那个子进程不在（修改之前：管道一直开着，communicate 等不到，调用永远不返回）
    environment = _environment(tmp_path)
    marker = tmp_path / "child.pid"
    request = action("bash", {"command": _leaves_a_child(marker), "timeout_sec": 2})
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, environment.perform(request))
        child = _read_pid(marker)
        result = future.result(timeout=90)
    elapsed = time.monotonic() - started
    assert elapsed < 30, f"the call took {elapsed:.1f}s with a 2s time limit"
    assert result.ok is True and result.status == "timeout"
    assert result.output["status"] == "timeout" and result.output["exit_code"] == 124
    assert "command timed out after 2s" in result.output["output"]
    assert "the process tree was stopped" in result.output["output"]
    assert wait_until_stopped(child)


def test_cancel_stops_the_whole_tree_and_leaves_no_listening_port(tmp_path):
    # 验收第 2 条：同一类命令在取消以后返回 cancelled，机器上不留这个会话起的进程与监听端口
    environment = _environment(tmp_path)
    marker = tmp_path / "server.pid"
    port = _free_port()
    command = f'({_python()} -c "{_server_program(port, marker)}" &) ; sleep 300'
    request = action("bash", {"command": command})
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, environment.perform(request))
        _wait_listening(port)
        started = time.monotonic()
        environment.cancel(request.action_id)
        result = future.result(timeout=90)
    elapsed = time.monotonic() - started
    assert elapsed < 30, f"the call took {elapsed:.1f}s after being cancelled"
    assert result.ok is True and result.status == "cancelled"
    assert result.output["status"] == "cancelled" and result.output["exit_code"] == 130
    assert "command cancelled" in result.output["output"]
    assert "the process tree was stopped" in result.output["output"]
    assert wait_until_stopped(_read_pid(marker))
    assert _wait_not_listening(port), f"port {port} is still being served"


def test_stop_job_stops_a_background_service_whose_direct_child_already_exited(tmp_path):
    # 验收第 3 条上半：后台作业里直接子进程已经退出、孙进程还在时，stop_job 让整棵树停下
    environment = _environment(tmp_path)
    marker = tmp_path / "child.pid"
    receipt = perform(environment, "bash",
                      {"command": _leaves_a_child(marker, tail="sleep 2"), "background": True})
    assert receipt.ok is True and receipt.status == "completed"
    job_id = receipt.output["job_id"]
    child = _read_pid(marker)
    assert pid_alive(child), "the background child should still be running"
    for _ in range(200):
        if perform(environment, "read_output", {"job_id": job_id}).output["status"] == "exited":
            break
        time.sleep(0.05)
    assert perform(environment, "read_output", {"job_id": job_id}).output["status"] == "exited"
    assert pid_alive(child), "the child is still running after the direct child exited"

    stopped = perform(environment, "stop_job", {"job_id": job_id})
    assert stopped.ok is True and stopped.status == "completed"
    assert stopped.output["status"] == "exited"
    assert "the processes it left behind were stopped" in stopped.output["output"]
    assert wait_until_stopped(child)


def test_session_end_stops_a_background_service_whose_direct_child_already_exited(tmp_path):
    # 验收第 3 条下半：会话结束这条路同样让整棵树停下
    system = LoopSystem.for_testing(tmp_path / "system", FakeAdapter([]))
    run_id = system.create_run("session end stops the tree")
    environment = system.orchestrator._workspaces.environment_for(run_id, "engineering")
    marker = tmp_path / "child.pid"
    receipt = perform(environment, "bash",
                      {"command": _leaves_a_child(marker, tail="sleep 2"), "background": True})
    assert receipt.ok is True
    child = _read_pid(marker)
    job_id = receipt.output["job_id"]
    for _ in range(200):
        if perform(environment, "read_output", {"job_id": job_id}).output["status"] == "exited":
            break
        time.sleep(0.05)
    assert pid_alive(child), "the child is still running after the direct child exited"

    system.orchestrator.sessions.close_run(run_id)
    assert wait_until_stopped(child)
    system.close()


def test_a_finished_command_does_not_leave_its_children_running(tmp_path):
    # 验收第 4 条的另一面：命令自己正常结束、留下了子进程时，调用照样按时返回（不等那根管道），
    # 留下的子进程随这次调用一起结束，回执写明；要长期运行的服务用 background
    environment = _environment(tmp_path)
    marker = tmp_path / "child.pid"
    started = time.monotonic()
    result = perform(environment, "bash", {"command": _leaves_a_child(marker, tail="sleep 2")})
    assert time.monotonic() - started < 30
    assert result.ok is True and result.status == "completed"
    assert result.output["status"] == "ok" and result.output["exit_code"] == 0
    assert "the command left processes running" in result.output["output"]
    assert wait_until_stopped(_read_pid(marker))
