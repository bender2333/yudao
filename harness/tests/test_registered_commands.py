import json
import os
import re
import sys
import time

import pytest

from harness.adapters.base import ModelResponse
from harness.adapters.fake import FakeAdapter
from harness.models import ArtifactRef, EventType, json_dumps
from harness.projects import CommandConfigConflict
from harness.proposals import delivery_turn, engineering_plan, product_spec, review_turn
from harness.runtime import LoopSystem
from harness.tests.helpers import happy_script
from harness.tests.test_web import get_json, request, running_server
from harness.tools import CHECK_OUTPUT_LIMIT, CHECK_TIMEOUT_SEC, ToolRuntime
from harness.workspace import Workspace

GOAL = "做一个可以长期演进的逐行文本处理工具。"
SECRET_NAME = "YUDAO_TEST_API_KEY"
SECRET_VALUE = "credential-value-12345678"


def _runtime(root, registry):
    return ToolRuntime(Workspace(root), registry)


def _pid_alive(pid):
    # 跨平台存活检查：只读探测，不改进程状态
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_unregistered_name_and_out_of_allowlist_args_rejected_before_execution(tmp_path):
    workspace = Workspace(tmp_path / "ws")
    workspace.write_file("marker.py", "from pathlib import Path\nPath('ran.txt').write_text('ran')\n")
    runtime = ToolRuntime(workspace, {
        "mark": {"argv": ["python", "marker.py"], "args": ["--fast"], "timeout_sec": 30, "output_limit": 4000},
    })
    unknown = runtime.execute("engineering", "run_command", {"name": "missing"})
    assert unknown.ok is False
    assert "unknown registered command" in (unknown.error or "")
    smuggled = runtime.execute("engineering", "run_command", {"name": "mark", "args": ["--evil"]})
    assert smuggled.ok is False
    assert "allowlist" in (smuggled.error or "")
    for department in ("product", "quality"):
        denied = runtime.execute(department, "run_command", {"name": "mark", "args": ["--fast"]})
        assert denied.ok is False
        assert "cannot use run_command" in (denied.error or "")
    # 任一拒绝都没有执行：标记文件不存在
    assert not (workspace.root / "ran.txt").exists()
    assert workspace.receipts() == []
    allowed = runtime.execute("engineering", "run_command", {"name": "mark", "args": ["--fast"]})
    assert allowed.ok is True
    assert allowed.output["attempt"] == 1
    assert (workspace.root / "ran.txt").read_text() == "ran"
    again = runtime.execute("engineering", "run_command", {"name": "mark", "args": ["--fast"]})
    assert again.ok is True
    assert again.output["attempt"] == 2


def test_fixed_cwd_and_sanitized_env(tmp_path, monkeypatch):
    monkeypatch.setenv(SECRET_NAME, SECRET_VALUE)
    workspace = Workspace(tmp_path / "ws")
    workspace.write_file(
        "env.py",
        "import os\n"
        "print('CWD=' + os.getcwd())\n"
        "print('CRED=' + ('has' if os.environ.get('YUDAO_TEST_API_KEY') else 'missing'))\n"
        "print('PWB=' + os.environ.get('PYTHONDONTWRITEBYTECODE', 'unset'))\n",
    )
    runtime = ToolRuntime(workspace, {
        "env": {"argv": ["python", "env.py"], "args": [], "timeout_sec": 30, "output_limit": 4000},
    })
    result = runtime.execute("engineering", "run_command", {"name": "env"})
    assert result.ok is True
    assert result.output["status"] == "ok"
    assert f"CWD={workspace.root}" in result.output["output"]
    assert "CRED=missing" in result.output["output"]
    assert "PWB=1" in result.output["output"]
    assert SECRET_VALUE not in result.output["output"]


def test_exit_failure_and_output_overflow_have_real_states(tmp_path):
    workspace = Workspace(tmp_path / "ws")
    workspace.write_file("fail.py", "raise SystemExit(7)\n")
    workspace.write_file("noisy.py", "print('y' * 20000)\n")
    runtime = ToolRuntime(workspace, {
        "fail": {"argv": ["python", "fail.py"], "args": [], "timeout_sec": 30, "output_limit": 4000},
        "noisy": {"argv": ["python", "noisy.py"], "args": [], "timeout_sec": 30, "output_limit": 500},
    })
    failed = runtime.execute("engineering", "run_command", {"name": "fail"})
    assert failed.ok is True
    assert failed.output["exit_code"] == 7
    assert failed.output["status"] == "failed"
    assert failed.output["truncated"] is False
    assert failed.output["executor"] == "host"
    overflow = runtime.execute("engineering", "run_command", {"name": "noisy"})
    assert overflow.ok is True
    assert overflow.output["exit_code"] == 0
    assert overflow.output["status"] == "ok"
    assert overflow.output["truncated"] is True
    assert len(overflow.output["output"]) <= 500 + len("\n...truncated...")


def test_timeout_kills_the_whole_process_tree(tmp_path):
    workspace = Workspace(tmp_path / "ws")
    workspace.write_file(
        "spawn.py",
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "print(f'child={child.pid}', flush=True)\n"
        "time.sleep(30)\n",
    )
    runtime = ToolRuntime(workspace, {
        "hang": {"argv": ["python", "spawn.py"], "args": [], "timeout_sec": 3, "output_limit": 4000},
    })
    started = time.monotonic()
    result = runtime.execute("engineering", "run_command", {"name": "hang"})
    assert time.monotonic() - started < 20
    assert result.ok is True
    assert result.output["status"] == "timeout"
    assert result.output["exit_code"] == 124
    assert "process tree was stopped" in result.output["output"]
    match = re.search(r"child=(\d+)", result.output["output"])
    assert match is not None
    child_pid = int(match.group(1))
    # 子进程必须确实停止，不残留
    for _ in range(100):
        if not _pid_alive(child_pid):
            break
        time.sleep(0.1)
    assert not _pid_alive(child_pid)


def test_model_reported_exit_code_is_not_evidence(tmp_path):
    workspace = Workspace(tmp_path / "ws")
    workspace.write_file("exiter.py", "raise SystemExit(3)\n")
    runtime = ToolRuntime(workspace, {
        "exiter": {"argv": ["python", "exiter.py"], "args": [], "timeout_sec": 30, "output_limit": 4000},
    })
    result = runtime.execute("engineering", "run_command", {"name": "exiter", "exit_code": 0})
    assert result.ok is True
    assert result.output["exit_code"] == 3
    assert result.output["status"] == "failed"
    assert result.output["executor"] == "host"


def _command_then_plan(request):
    plan = engineering_plan()
    plan.pop("kind", None)
    return ModelResponse(
        output=[
            {"id": "cmd-1", "call_id": "cmd-1", "type": "function_call", "name": "run_command",
             "arguments": json_dumps({"name": "probe"})},
            {"id": "plan-1", "call_id": "plan-1", "type": "function_call", "name": "submit_plan",
             "arguments": json_dumps(plan)},
        ],
        provider="fake",
        model="fake-script",
    )


def test_finished_receipt_binds_command_snapshot_status_output_and_attempt(data_dir):
    registry = {"probe": {"argv": ["python", "-c", "print('probe-ok')"], "args": [],
                          "timeout_sec": 30, "output_limit": 4000}}
    system = LoopSystem.for_testing(data_dir, FakeAdapter([
        product_spec(), _command_then_plan, delivery_turn(), review_turn("release", "ok"),
    ]))
    run_id = system.create_run("命令回执", registered_commands=registry, command_versions={"probe": 1})
    assert system.run_until_stop(run_id).phase == "DONE"
    events = system.store.list_events(run_id)
    started = next(event for event in events
                   if event.type == EventType.TOOL_STARTED and event.payload.get("name") == "run_command")
    assert started.payload["args"] == {"name": "probe"}
    assert started.payload["registered_name"] == "probe"
    assert started.payload["registered_argv"] == ["python", "-c", "print('probe-ok')"]
    assert started.payload["snapshot_hash"].startswith("sha256:")
    called = next(event for event in events
                  if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "run_command")
    assert called.payload["ok"] is True
    raw = system.artifacts.get_for_run(run_id, ArtifactRef(**called.payload["output_ref"])).decode("utf-8")
    output = json.loads(raw)
    assert output["name"] == "probe"
    assert output["argv"] == started.payload["registered_argv"]
    assert output["exit_code"] == 0
    assert output["status"] == "ok"
    assert output["output"] == "probe-ok"
    assert output["snapshot_hash"] == started.payload["snapshot_hash"]
    assert output["executor"] == "host"
    assert output["attempt"] == 1
    # 回执绑定的是执行前快照：后续交付写入后工作区摘要已经不同
    assert output["snapshot_hash"] != system.workspace(run_id).digest()


def test_registry_freezes_at_work_item_creation(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter([*happy_script(), *happy_script()]))
    project_id = system.projects.register("Cmd", GOAL)
    first = system.projects.configure_command(project_id, "itest", ["python", "-c", "print(1)"], base_version=0)
    assert first["version"] == 1 and first["unchanged"] is False
    assert first["timeout_sec"] == CHECK_TIMEOUT_SEC and first["output_limit"] == CHECK_OUTPUT_LIMIT
    with pytest.raises(CommandConfigConflict):
        system.projects.configure_command(project_id, "itest", ["python", "-c", "print(9)"], base_version=0)
    with pytest.raises(ValueError):
        system.projects.configure_command(project_id, "bad name!", ["python", "-c", "print(1)"], base_version=0)
    with pytest.raises(ValueError):
        system.projects.configure_command(project_id, "empty", [], base_version=0)
    work_item_id, run_id = system.projects.start_work_item(project_id, "第一步")
    run = system.project(run_id)
    assert run.registered_commands == {
        "itest": {"argv": ["python", "-c", "print(1)"], "args": [],
                  "timeout_sec": CHECK_TIMEOUT_SEC, "output_limit": CHECK_OUTPUT_LIMIT},
    }
    assert run.command_versions == {"itest": 1}
    assert system.projects.projection(project_id).work_item(work_item_id).command_versions == {"itest": 1}
    assert system.run_until_stop(run_id).phase == "DONE"
    second = system.projects.configure_command(
        project_id, "itest", ["python", "-c", "print(2)"], args=["--fast"],
        timeout_sec=60, output_limit=8000, base_version=1)
    assert second["version"] == 2 and second["unchanged"] is False
    # 已创建事项不受影响：冻结仍是创建时的版本
    assert system.project(run_id).registered_commands["itest"]["argv"] == ["python", "-c", "print(1)"]
    assert system.project(run_id).command_versions == {"itest": 1}
    _work_item_2, run_2 = system.projects.start_work_item(project_id, "第二步")
    assert system.project(run_2).registered_commands["itest"]["argv"] == ["python", "-c", "print(2)"]
    assert system.project(run_2).command_versions == {"itest": 2}


def test_command_http_routes(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    with running_server(system) as (_server, host, port):
        status, raw, _ = request(host, port, "POST", "/api/projects", {"name": "Cmd", "goal": GOAL})
        assert status == 201, raw
        project_id = json.loads(raw)["project_id"]
        status, raw, _ = request(host, port, "PUT", f"/api/projects/{project_id}/commands/itest",
                                 {"argv": ["python", "-c", "print(1)"], "base_version": 0})
        assert status == 200, raw
        assert json.loads(raw)["version"] == 1
        listed = get_json(host, port, f"/api/projects/{project_id}/commands")
        assert [item["name"] for item in listed["commands"]] == ["itest"]
        detail = get_json(host, port, f"/api/projects/{project_id}/commands/itest")
        assert detail["argv"] == ["python", "-c", "print(1)"]
        status, raw, _ = request(host, port, "PUT", f"/api/projects/{project_id}/commands/itest",
                                 {"argv": ["python", "-c", "print(2)"], "base_version": 0})
        assert status == 409, raw
        assert json.loads(raw)["reason"] == "command_config_conflict"
