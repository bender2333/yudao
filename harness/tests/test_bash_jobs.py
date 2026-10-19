# bash 后台任务与按编号读取/结束：
# 后台启动、端口访问、输出读取、任务结束、进程树清理、新环境旧编号 ended。
# 真实子进程与端口监听，登记为集成层。
from __future__ import annotations

import asyncio
import os
import re
import socket
import sys
import time
from pathlib import Path

import pytest

from harness.definitions import DEFINITIONS
from harness.environment import LocalEnvironment
from harness.sessions import DepartmentSession, SessionFactory
from harness.tests.helpers import action, perform, wait_for_file, wait_until_stopped
from harness.workspace import Workspace


def _environment(path: Path, **kwargs) -> LocalEnvironment:
    return LocalEnvironment(Workspace(path / "ws"), **kwargs)


def _python() -> str:
    return sys.executable.replace("\\", "/")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _tree_command(marker: str) -> str:
    program = (
        "import subprocess,sys,time,pathlib;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        f"print('started child=%d' % child.pid,flush=True);"
        f"pathlib.Path(r'{marker}').write_text('running',encoding='utf-8');"
        "time.sleep(60)"
    )
    return f'"{_python()}" -c "{program}"'


def _grandchild(output: str) -> int:
    match = re.search(r"started child=(\d+)", output)
    assert match is not None, f"grandchild pid not found in output: {output!r}"
    return int(match.group(1))


def test_background_job_port_access_read_output_and_stop(tmp_path: Path):
    environment = _environment(tmp_path)
    port = _free_port()
    server_code = (
        "import http.server, sys\n"
        f"port = {port}\n"
        "class Handler(http.server.BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        self.send_response(200)\n"
        "        self.end_headers()\n"
        "        self.wfile.write(b'PONG')\n"
        "    def log_message(self, format, *args):\n"
        "        sys.stdout.write((format % args) + '\\n')\n"
        "        sys.stdout.flush()\n"
        "server = http.server.HTTPServer(('127.0.0.1', port), Handler)\n"
        "print('server_ready on port %d' % port, flush=True)\n"
        "server.handle_request()\n"
        "print('handled_one_request', flush=True)\n"
        "server.handle_request()\n"
        "print('handled_second_request', flush=True)\n"
    )
    start_receipt = perform(
        environment, "bash",
        {"command": f'"{_python()}" -c "{server_code}"', "background": True},
    )
    assert start_receipt.ok is True and start_receipt.status == "completed"
    job_id = start_receipt.output.get("job_id")
    assert job_id and isinstance(job_id, str)
    assert start_receipt.output.get("status") == "running"

    # 等待端口就绪并访问
    for _ in range(50):
        probe = perform(
            environment, "bash",
            {"command": f'"{_python()}" -c "import urllib.request; print(urllib.request.urlopen(\'http://127.0.0.1:{port}\').read().decode())"'},
        )
        if probe.ok and "PONG" in (probe.output.get("output") or ""):
            break
        time.sleep(0.1)
    assert probe.ok and "PONG" in probe.output["output"]

    # read_output 读到新的输出与运行状态
    read_receipt = perform(environment, "read_output", {"job_id": job_id})
    assert read_receipt.ok is True and read_receipt.status == "completed"
    assert "server_ready" in read_receipt.output["output"]
    assert "handled_one_request" in read_receipt.output["output"]
    assert read_receipt.output["status"] == "running"
    assert read_receipt.output["exit_code"] is None

    # stop_job 结束后台进程树
    stop_receipt = perform(environment, "stop_job", {"job_id": job_id})
    assert stop_receipt.ok is True and stop_receipt.status == "completed"
    assert stop_receipt.output["status"] == "stopped"

    # 停止后无法再连接
    with pytest.raises(Exception):
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            pass


def test_session_close_stops_background_process_tree(tmp_path: Path):
    marker = tmp_path / "started"
    session = DepartmentSession(session_id="ses_test", run_id="run_1", department="engineering")
    environment = _environment(tmp_path)
    session.attach_environment(environment)

    receipt = perform(
        environment, "bash",
        {"command": _tree_command(str(marker)), "background": True},
    )
    assert receipt.ok is True
    job_id = receipt.output["job_id"]
    wait_for_file(marker)

    read_res = perform(environment, "read_output", {"job_id": job_id})
    child_pid = _grandchild(read_res.output["output"])

    # 会话关闭时结束后台命令整个进程树
    session.close("closed")
    assert wait_until_stopped(child_pid)


def test_factory_close_run_on_pause_and_cancel_stops_jobs(tmp_path: Path):
    # 模拟事项暂停与取消时的清理路径：Orchestrator._on_close_run 统一调用 factory.close_run(run_id)
    factory = SessionFactory(tmp_path)
    sessions = factory.create_run_sessions("run_test")
    session = sessions["engineering"]

    run_root = tmp_path / "run_test"
    environment = LocalEnvironment.establish(run_root, None)
    session.attach_environment(environment)

    marker = tmp_path / "started"
    receipt = perform(
        environment, "bash",
        {"command": _tree_command(str(marker)), "background": True},
    )
    job_id = receipt.output["job_id"]
    wait_for_file(marker)

    read_res = perform(environment, "read_output", {"job_id": job_id})
    child_pid = _grandchild(read_res.output["output"])

    # 暂停/取消调用 close_run
    errors = factory.close_run("run_test")
    assert errors == []
    assert wait_until_stopped(child_pid)


def test_new_environment_returns_ended_for_old_job_id(tmp_path: Path):
    env1 = _environment(tmp_path)
    receipt = perform(env1, "bash", {"command": "echo test_old_job", "background": True})
    job_id = receipt.output["job_id"]

    # 在同一个数据目录上新建执行环境
    env2 = _environment(tmp_path)
    read_receipt = perform(env2, "read_output", {"job_id": job_id})
    assert read_receipt.ok is True and read_receipt.status == "completed"
    assert read_receipt.output["status"] == "ended"
    assert read_receipt.output["output"] == ""
    assert read_receipt.output["exit_code"] is None

    stop_receipt = perform(env2, "stop_job", {"job_id": job_id})
    assert stop_receipt.ok is True and stop_receipt.status == "completed"
    assert stop_receipt.output["status"] == "ended"

    # 清理 env1
    env1.stop_jobs()
