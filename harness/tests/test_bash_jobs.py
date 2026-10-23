# bash 后台任务与按编号读取/结束：
# 后台启动、端口访问、跨激活读取与结束、多部门会话隔离、
# 检查工作区重建清理后台任务、LoopSystem 终态（放行/暂停/取消）清理进程树、
# 重启后旧编号 ended。
# 真实子进程与端口监听，登记为集成层。
from __future__ import annotations
import json
import re
import socket
import sys
import time
from pathlib import Path

from harness.collaboration import has_new_work
from harness.models import ArtifactRef, EventType
from harness.proposals import delivery_turn, product_spec, review_turn
from harness.providers.call import ModelCall, ModelResponse
from harness.adapters.fake import FakeAdapter
from harness.environment import BackgroundJobTable, LocalEnvironment
from harness.runtime import LoopSystem
from harness.tests.helpers import happy_script, perform, wait_for_file, wait_until_stopped, quality_turns
from harness.workspace import Workspace


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


def test_cross_activation_read_output_stop_job_and_department_isolation(tmp_path: Path):
    from harness.proposals import product_spec
    system = LoopSystem.for_testing(tmp_path / "system", FakeAdapter([product_spec()]))
    run_id = system.create_run("cross activation test")
    # 推进到工程阶段，使工程持有运行工作区
    proj = system.activate_once(run_id)
    assert has_new_work(proj, "engineering")

    # 激活 1：持有运行工作区的工程获取环境并启动持续输出的后台命令
    env1 = system.orchestrator._environment_for(run_id, "engineering", refresh=True)
    server_cmd = (
        f'"{_python()}" -c "import time\nfor i in range(600):\n    print(\'tick %d\' % i, flush=True)\n    time.sleep(0.1)"'
    )
    start_receipt = perform(env1, "bash", {"command": server_cmd, "background": True})
    assert start_receipt.ok is True
    job_id = start_receipt.output["job_id"]

    # 激活 2：再取一次，得到新的 LocalEnvironment 实例
    env2 = system.orchestrator._environment_for(run_id, "engineering", refresh=True)
    assert env2 is not env1

    # 用这个编号 read_output 读到新的输出
    for _ in range(50):
        time.sleep(0.1)
        read_receipt = perform(env2, "read_output", {"job_id": job_id})
        assert read_receipt.ok is True
        if "tick" in (read_receipt.output.get("output") or ""):
            break
    assert "tick" in read_receipt.output["output"]
    assert read_receipt.output["status"] == "running"

    # 另一个部门（质检）的会话用该编号 read_output 与 stop_job 得到 ended，进程不受影响
    env_qa = system.orchestrator._environment_for(run_id, "quality", refresh=True)
    qa_read = perform(env_qa, "read_output", {"job_id": job_id})
    assert qa_read.ok is True and qa_read.output["status"] == "ended"
    assert qa_read.output["output"] == ""

    qa_stop = perform(env_qa, "stop_job", {"job_id": job_id})
    assert qa_stop.ok is True and qa_stop.output["status"] == "ended"

    # 工程依然能够读取新输出并结束进程
    time.sleep(0.1)
    read_again = perform(env2, "read_output", {"job_id": job_id})
    assert read_again.ok is True
    assert "tick" in read_again.output["output"]

    # stop_job 以后进程树不存在
    stop_res = perform(env2, "stop_job", {"job_id": job_id})
    assert stop_res.ok is True and stop_res.output["status"] == "stopped"


def test_inspection_workspace_rebuild_stops_jobs_and_returns_ended(tmp_path: Path):
    system = LoopSystem.for_testing(tmp_path / "system", FakeAdapter([]))
    run_id = system.create_run("qa inspection test")

    env_qa1 = system.orchestrator._environment_for(run_id, "quality", refresh=True)
    marker = tmp_path / "started_qa"
    receipt = perform(env_qa1, "bash", {"command": _tree_command(str(marker)), "background": True})
    assert receipt.ok is True
    job_id = receipt.output["job_id"]
    wait_for_file(marker)

    read_res = perform(env_qa1, "read_output", {"job_id": job_id})
    child_pid = _grandchild(read_res.output["output"])

    # 编排器重建这个检查工作区
    env_qa2 = system.orchestrator._new_inspection_environment(run_id, "quality")
    assert env_qa2 is not None

    # 重建成功，进程树不存在
    assert wait_until_stopped(child_pid)

    # 编号回答 ended
    read_after = perform(env_qa2, "read_output", {"job_id": job_id})
    assert read_after.ok is True and read_after.output["status"] == "ended"

    stop_after = perform(env_qa2, "stop_job", {"job_id": job_id})
    assert stop_after.ok is True and stop_after.output["status"] == "ended"


def test_loop_system_real_paths_stop_background_process_tree(tmp_path: Path):
    # 经过 LoopSystem 的真实路径：放行、事项暂停、事项取消三种情况下，后台命令的进程树都被结束

    # 1. 事项取消 (cancelled)
    sys_cancel = LoopSystem.for_testing(tmp_path / "sys_cancel", FakeAdapter([]))
    run_cancel = sys_cancel.create_run("cancel test")
    env_cancel = sys_cancel.orchestrator._environment_for(run_cancel, "engineering")
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
    env_pause = sys_pause.orchestrator._environment_for(run_pause, "engineering")
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
    env_release = sys_release.orchestrator._environment_for(run_release, "engineering")
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
    env1 = sys1.orchestrator._environment_for(run_id, "engineering")
    receipt = perform(env1, "bash", {"command": "echo test_old_job", "background": True})
    job_id = receipt.output["job_id"]
    sys1.close()

    # 在同一个数据目录上重新建立 LoopSystem（Yudao 重新启动）
    sys2 = LoopSystem.for_testing(data_dir, FakeAdapter([]), resume_on_startup=False)
    env2 = sys2.orchestrator._environment_for(run_id, "engineering")
    read_receipt = perform(env2, "read_output", {"job_id": job_id})
    assert read_receipt.ok is True and read_receipt.status == "completed"
    assert read_receipt.output["status"] == "ended"
    assert read_receipt.output["output"] == ""
    assert read_receipt.output["exit_code"] is None

    stop_receipt = perform(env2, "stop_job", {"job_id": job_id})
    assert stop_receipt.ok is True and stop_receipt.status == "completed"
    assert stop_receipt.output["status"] == "ended"
    sys2.close()


def test_environment_without_session_context_rejects_background_and_truncation(tmp_path: Path):
    # 只用于查询树的环境不带 session_id / jobs，启动后台命令或截断输出直接报错
    env = LocalEnvironment(Workspace(tmp_path / "ws"))
    bg_res = perform(env, "bash", {"command": "echo hi", "background": True})
    assert bg_res.ok is False
    assert "session context" in bg_res.error

    command = f'"{_python()}" -c "for i in range(2000): print(\'line-%05d-\' % i + \'x\' * 40)"'
    trunc_res = perform(env, "bash", {"command": command})
    assert trunc_res.ok is False
    assert "session context" in trunc_res.error


def test_stop_job_on_already_exited_process_preserves_exit_code_and_receipt_shape(tmp_path: Path):
    environment = _environment(tmp_path)
    receipt = perform(
        environment, "bash",
        {"command": f'"{_python()}" -c "import sys; sys.exit(3)"', "background": True},
    )
    assert receipt.ok is True
    job_id = receipt.output["job_id"]

    for _ in range(50):
        time.sleep(0.05)
        if environment._jobs and environment._jobs.get_status(job_id) == "exited":
            break

    stop_res = perform(environment, "stop_job", {"job_id": job_id})
    assert stop_res.ok is True and stop_res.status == "completed"
    assert stop_res.output["job_id"] == job_id
    assert stop_res.output["status"] == "exited"
    assert stop_res.output["exit_code"] == 3
    assert "exited" in stop_res.output["output"]
    assert "3" in stop_res.output["output"]

    # 再次调用 stop_job 依然返回 exited 与 exit_code
    again = perform(environment, "stop_job", {"job_id": job_id})
    assert again.ok is True and again.status == "completed"
    assert again.output["status"] == "exited"
    assert again.output["exit_code"] == 3


def test_work_item_run_with_background_bash_port_access_read_output_and_stop(tmp_path: Path):
    port = _free_port()
    server_code = (
        "import http.server, sys\n"
        f"port = {port}\n"
        "class Handler(http.server.BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        self.send_response(200)\n"
        "        self.end_headers()\n"
        "        self.wfile.write(b'server_responded')\n"
        "    def log_message(self, format, *args):\n"
        "        sys.stdout.write((format % args) + '\\n')\n"
        "        sys.stdout.flush()\n"
        "server = http.server.HTTPServer(('127.0.0.1', port), Handler)\n"
        "print('server_ready on port %d' % port, flush=True)\n"
        "server.serve_forever()\n"
    )
    access_code = (
        "import urllib.request, time\n"
        "for _ in range(50):\n"
        "    try:\n"
        f"        with urllib.request.urlopen('http://127.0.0.1:{port}') as r:\n"
        "            print('ACCESS_OK:' + r.read().decode(), flush=True)\n"
        "            break\n"
        "    except Exception:\n"
        "        time.sleep(0.1)\n"
    )

    def _extract_job_id(call: ModelCall) -> str:
        for item in reversed(call.input_items):
            if item.get("type") == "function_call_output":
                try:
                    data = json.loads(item["output"])
                    if isinstance(data, dict) and data.get("ok"):
                        out = data.get("output")
                        if isinstance(out, dict) and "job_id" in out:
                            return out["job_id"]
                except Exception:
                    pass
        raise ValueError(f"job_id not found in input_items: {call.input_items}")

    def eng_step1(call: ModelCall) -> ModelResponse:
        identity = f"call-bg-start-{call.activation_id}"
        return ModelResponse(output=[{
            "id": identity, "call_id": identity, "type": "function_call",
            "name": "bash", "arguments": json.dumps({"command": f'"{_python()}" -c "{server_code}"', "background": True}),
        }])

    def eng_step2(call: ModelCall) -> ModelResponse:
        identity = f"call-bg-access-{call.activation_id}"
        return ModelResponse(output=[{
            "id": identity, "call_id": identity, "type": "function_call",
            "name": "bash", "arguments": json.dumps({"command": f'"{_python()}" -c "{access_code}"'}),
        }])

    def eng_step3(call: ModelCall) -> ModelResponse:
        job_id = _extract_job_id(call)
        identity = f"call-read-output-{call.activation_id}"
        return ModelResponse(output=[{
            "id": identity, "call_id": identity, "type": "function_call",
            "name": "read_output", "arguments": json.dumps({"job_id": job_id}),
        }])

    def eng_step4(call: ModelCall) -> ModelResponse:
        job_id = _extract_job_id(call)
        identity = f"call-stop-job-{call.activation_id}"
        return ModelResponse(output=[{
            "id": identity, "call_id": identity, "type": "function_call",
            "name": "stop_job", "arguments": json.dumps({"job_id": job_id}),
        }])

    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    script = {
        "product": [product_spec()],
        "engineering": [
            eng_step1,
            eng_step2,
            eng_step3,
            eng_step4,
            delivery_turn(files={"src/server.py": "print('ok')\n"}, checks={"smoke": 0}),
        ],
        "quality": quality_turns("release", "verified server delivery independently"),
    }

    system = LoopSystem.for_testing(tmp_path / "system", FakeAdapter(script))
    run_id = system.create_run("build server")
    result = system.run_until_stop(run_id)
    assert result.status == "done" and result.stop_reason == "released"

    events = system.store.list_events(run_id)
    tool_events = [e for e in events if e.type == EventType.TOOL_CALLED and e.payload.get("name") in {"bash", "read_output", "stop_job"}]
    assert len(tool_events) == 4

    # 1. bash background start
    bg_start = tool_events[0]
    assert bg_start.payload["name"] == "bash"
    assert bg_start.payload["args"].get("background") is True
    assert bg_start.payload["ok"] is True
    bg_start_out = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**bg_start.payload["output_ref"])))
    job_id = bg_start_out["job_id"]
    assert job_id and job_id.startswith("job_")
    assert bg_start_out["status"] == "running"

    # 2. bash access
    bg_access = tool_events[1]
    assert bg_access.payload["name"] == "bash"
    assert bg_access.payload["ok"] is True
    bg_access_out = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**bg_access.payload["output_ref"])))
    assert "ACCESS_OK:server_responded" in bg_access_out["output"]

    # 3. read_output
    read_ev = tool_events[2]
    assert read_ev.payload["name"] == "read_output"
    assert read_ev.payload["args"] == {"job_id": job_id}
    assert read_ev.payload["ok"] is True
    read_out = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**read_ev.payload["output_ref"])))
    assert read_out["job_id"] == job_id
    assert "server_ready" in read_out["output"]
    assert read_out["status"] in ("running", "exited")

    # 4. stop_job
    stop_ev = tool_events[3]
    assert stop_ev.payload["name"] == "stop_job"
    assert stop_ev.payload["args"] == {"job_id": job_id}
    assert stop_ev.payload["ok"] is True
    stop_out = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**stop_ev.payload["output_ref"])))
    assert stop_out["job_id"] == job_id
    assert stop_out["status"] == "stopped"

    system.close()
