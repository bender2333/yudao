# bash 后台任务与按编号读取/结束：
# 后台启动、端口访问、跨激活读取与结束、多部门会话隔离、
# 检查工作区重建清理后台任务、LoopSystem 终态（放行/暂停/取消）清理进程树、
# 重启后旧编号 ended。
# 真实子进程与端口监听，登记为集成层。
from __future__ import annotations
import re
import socket
import sys
import time
from pathlib import Path

from harness.actions import ActionReceipt
from harness.watched_outputs import has_new_work
from harness.adapters.fake import FakeAdapter
from harness.environment import BackgroundJobTable, LocalEnvironment
from harness.runtime import LoopSystem
from harness.tests.helpers import happy_script, perform, wait_for_file, wait_until_stopped
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC
from harness.workspace import Workspace

WAIT_LIMIT = WAIT_FOR_HOST_WORK_SEC
POLL_INTERVAL_SEC = 0.02


def _environment(path: Path, **kwargs) -> LocalEnvironment:
    kwargs.setdefault("session_id", "test-session")
    kwargs.setdefault("jobs", BackgroundJobTable())
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


def _wait_for_output(
    environment: LocalEnvironment,
    job_id: str,
    *expected: str,
    timeout_sec: float = WAIT_LIMIT,
) -> tuple[ActionReceipt, str]:
    # 在截止时间内轮询 read_output 并累积增量片段，预期文本全部出现后立即返回
    deadline = time.monotonic() + timeout_sec
    collected = ""
    while True:
        receipt = perform(environment, "read_output", {"job_id": job_id})
        assert receipt.ok is True and receipt.status == "completed"
        collected += receipt.output.get("output") or ""
        if all(item in collected for item in expected):
            return receipt, collected
        status = receipt.output.get("status")
        if status != "running":
            raise AssertionError(
                f"job {job_id} ended with status={status!r} before producing {expected!r}; "
                f"collected={collected!r}"
            )
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"timed out after {timeout_sec:.1f}s waiting for {expected!r} from job {job_id}; "
                f"collected={collected!r}"
            )
        time.sleep(POLL_INTERVAL_SEC)


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

    try:
        # 等待端口就绪并访问
        probe_deadline = time.monotonic() + WAIT_LIMIT
        while True:
            probe = perform(
                environment, "bash",
                {"command": f'"{_python()}" -c "import urllib.request; print(urllib.request.urlopen(\'http://127.0.0.1:{port}\').read().decode())"'},
            )
            if probe.ok and "PONG" in (probe.output.get("output") or ""):
                break
            if time.monotonic() >= probe_deadline:
                raise AssertionError(
                    f"timed out after {WAIT_LIMIT:.1f}s waiting for HTTP server on port {port}: {probe.output!r}"
                )
            time.sleep(0.05)
        assert probe.ok and "PONG" in probe.output["output"]

        # read_output 累积读到新的输出与运行状态
        read_receipt, read_text = _wait_for_output(environment, job_id, "server_ready", "handled_one_request")
        assert "server_ready" in read_text
        assert "handled_one_request" in read_text
        assert read_receipt.output["status"] == "running"
        assert read_receipt.output["exit_code"] is None
    finally:
        # stop_job 结束后台进程树
        stop_receipt = perform(environment, "stop_job", {"job_id": job_id})
    assert stop_receipt.ok is True and stop_receipt.status == "completed"
    assert stop_receipt.output["status"] == "stopped"


def test_cross_activation_read_output_stop_job_and_department_isolation(tmp_path: Path):
    from harness.proposals import product_spec
    system = LoopSystem.for_testing(tmp_path / "system", FakeAdapter([product_spec()]))
    try:
        run_id = system.create_run("cross activation test")
        # 推进到工程阶段，使工程持有运行工作区
        proj = system.activate_once(run_id)
        assert has_new_work(proj, "engineering")

        # 工程第一次取得环境并启动持续输出的后台命令
        env1 = system.orchestrator._workspaces.environment_for(run_id, "engineering", refresh=True)
        server_cmd = (
            f'"{_python()}" -c "import time\nfor i in range(600):\n    print(\'tick %d\' % i, flush=True)\n    time.sleep(0.1)"'
        )
        start_receipt = perform(env1, "bash", {"command": server_cmd, "background": True})
        assert start_receipt.ok is True
        job_id = start_receipt.output["job_id"]

        # 工程再次取得新的 LocalEnvironment 实例
        env2 = system.orchestrator._workspaces.environment_for(run_id, "engineering", refresh=True)
        assert env2 is not env1

        # 用这个编号跨实例轮询 read_output 读到首个增量输出
        read_receipt, first_output = _wait_for_output(env2, job_id, "tick 0\n")
        assert "tick 0\n" in first_output
        assert read_receipt.output["status"] == "running"
        seen_ticks = [int(m) for m in re.findall(r"tick (\d+)\n", first_output)]
        assert seen_ticks and seen_ticks[0] == 0

        # 质检职能的会话用该编号调用 read_output 与 stop_job 得到 ended，原进程不受影响
        env_qa = system.orchestrator._workspaces.environment_for(run_id, "quality", refresh=True)
        qa_read = perform(env_qa, "read_output", {"job_id": job_id})
        assert qa_read.ok is True and qa_read.output["status"] == "ended"
        assert qa_read.output["output"] == ""

        qa_stop = perform(env_qa, "stop_job", {"job_id": job_id})
        assert qa_stop.ok is True and qa_stop.output["status"] == "ended"

        # 工程继续轮询 read_output 读到后续增量输出且序号连续，确认已读偏移与运行状态保持完整
        expected_next = f"tick {seen_ticks[-1] + (1 if first_output.endswith('\n') else 2)}\n"
        read_again, second_output = _wait_for_output(env2, job_id, expected_next)
        assert expected_next in second_output
        assert read_again.output["status"] == "running"
        all_ticks = [int(m) for m in re.findall(r"tick (\d+)\n", first_output + second_output)]
        assert len(all_ticks) >= 2 and all_ticks == list(range(len(all_ticks)))

        # stop_job 以后进程树结束
        stop_res = perform(env2, "stop_job", {"job_id": job_id})
        assert stop_res.ok is True and stop_res.output["status"] == "stopped"
    finally:
        system.close()


def test_loop_system_real_paths_stop_background_process_tree(tmp_path: Path):
    # 经过 LoopSystem 的真实路径：放行、事项暂停、事项取消三种情况下，后台命令的进程树都被结束

    # 1. 事项取消 (cancelled)
    sys_cancel = LoopSystem.for_testing(tmp_path / "sys_cancel", FakeAdapter([]))
    run_cancel = sys_cancel.create_run("cancel test")
    env_cancel = sys_cancel.orchestrator._workspaces.environment_for(run_cancel, "engineering")
    marker_cancel = tmp_path / "marker_cancel"
    rec_cancel = perform(env_cancel, "bash", {"command": _tree_command(str(marker_cancel)), "background": True})
    wait_for_file(marker_cancel)
    child_cancel = _grandchild(perform(env_cancel, "read_output", {"job_id": rec_cancel.output["job_id"]}).output["output"])

    res_cancel = sys_cancel.cancel(run_cancel)
    assert res_cancel.stop_reason == "cancelled"
    assert wait_until_stopped(child_cancel)
    sys_cancel.close()

    # 2. 事项暂停 (paused)
    sys_pause = LoopSystem.for_testing(tmp_path / "sys_pause", FakeAdapter(happy_script()))
    run_pause = sys_pause.create_run("pause test", max_cycles=1)
    env_pause = sys_pause.orchestrator._workspaces.environment_for(run_pause, "engineering")
    marker_pause = tmp_path / "marker_pause"
    rec_pause = perform(env_pause, "bash", {"command": _tree_command(str(marker_pause)), "background": True})
    wait_for_file(marker_pause)
    child_pause = _grandchild(perform(env_pause, "read_output", {"job_id": rec_pause.output["job_id"]}).output["output"])

    res_pause = sys_pause.run_until_stop(run_pause)
    assert res_pause.status == "paused" and res_pause.stop_reason == "max_cycles"
    assert wait_until_stopped(child_pause)
    sys_pause.close()

    # 3. 运行到放行 (released)
    sys_release = LoopSystem.for_testing(tmp_path / "sys_release", FakeAdapter(happy_script()))
    run_release = sys_release.create_run("release test")
    env_release = sys_release.orchestrator._workspaces.environment_for(run_release, "engineering")
    marker_release = tmp_path / "marker_release"
    rec_release = perform(env_release, "bash", {"command": _tree_command(str(marker_release)), "background": True})
    wait_for_file(marker_release)
    child_release = _grandchild(perform(env_release, "read_output", {"job_id": rec_release.output["job_id"]}).output["output"])

    res_release = sys_release.run_until_stop(run_release)
    assert res_release.status == "done" and res_release.stop_reason == "released"
    assert wait_until_stopped(child_release)
    sys_release.close()


def test_recreate_loop_system_returns_ended_for_old_job_id(tmp_path: Path):
    data_dir = tmp_path / "data_restart"
    sys1 = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    run_id = sys1.create_run("restart test")
    env1 = sys1.orchestrator._workspaces.environment_for(run_id, "engineering")
    receipt = perform(env1, "bash", {"command": "echo test_old_job", "background": True})
    job_id = receipt.output["job_id"]
    sys1.close()

    # 在同一个数据目录上重新建立 LoopSystem（Yudao 重新启动）
    sys2 = LoopSystem.for_testing(data_dir, FakeAdapter([]), resume_on_startup=False)
    env2 = sys2.orchestrator._workspaces.environment_for(run_id, "engineering")
    read_receipt = perform(env2, "read_output", {"job_id": job_id})
    assert read_receipt.ok is True and read_receipt.status == "completed"
    assert read_receipt.output["status"] == "ended"
    assert read_receipt.output["output"] == ""
    assert read_receipt.output["exit_code"] is None

    stop_receipt = perform(env2, "stop_job", {"job_id": job_id})
    assert stop_receipt.ok is True and stop_receipt.status == "completed"
    assert stop_receipt.output["status"] == "ended"
    sys2.close()


