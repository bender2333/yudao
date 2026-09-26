import asyncio
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from harness.adapters.fake import FakeAdapter, prompt_part
from harness.models import ArtifactRef, EventType, json_dumps
from harness.projects import CommandConfigConflict
from harness.proposals import delivery_turn, engineering_plan, plan_turn, product_spec, review_turn
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.actions import Preconditions
from harness.environment import LocalEnvironment
from harness.tests.helpers import (LONG_RUNNING_TREE, action, happy_script, perform, recorded_context,
                                   wait_for_file, wait_until_stopped)
from harness.tests.test_web import get_json, request, running_server
from harness.tools import CHECK_OUTPUT_LIMIT, CHECK_TIMEOUT_SEC, TOOL_SCHEMAS
from harness.workspace import Workspace

GOAL = "做一个可以长期演进的逐行文本处理工具。"
SECRET_NAME = "YUDAO_TEST_API_KEY"
SECRET_VALUE = "credential-value-12345678"


def test_unregistered_name_and_out_of_allowlist_args_rejected_before_execution(tmp_path):
    workspace = Workspace(tmp_path / "ws")
    workspace.write_file("marker.py", "from pathlib import Path\nPath('ran.txt').write_text('ran')\n")
    environment = LocalEnvironment(workspace, registered_commands={
        "mark": {"argv": ["python", "marker.py"], "args": ["--fast"], "timeout_sec": 30, "output_limit": 4000},
    })
    unknown = perform(environment, "run_command", {"name": "missing"})
    assert unknown.ok is False
    assert "unknown registered command" in (unknown.error or "")
    smuggled = perform(environment, "run_command", {"name": "mark", "args": ["--evil"]})
    assert smuggled.ok is False
    assert "allowlist" in (smuggled.error or "")
    # 任一拒绝都没有执行：标记文件不存在
    assert not (workspace.root / "ran.txt").exists()
    assert workspace.receipts() == []
    allowed = perform(environment, "run_command", {"name": "mark", "args": ["--fast"]})
    assert allowed.ok is True
    assert allowed.output["attempt"] == 1
    assert (workspace.root / "ran.txt").read_text() == "ran"
    again = perform(environment, "run_command", {"name": "mark", "args": ["--fast"]})
    assert again.ok is True
    assert again.output["attempt"] == 2


def test_command_does_not_run_when_the_tree_changed_after_the_permission(tmp_path):
    # 前置条件：工具许可所依据的公开树摘要与执行之前的摘要不同时不执行
    workspace = Workspace(tmp_path / "ws")
    workspace.write_file("marker.py", "from pathlib import Path\nPath('ran.txt').write_text('ran')\n")
    environment = LocalEnvironment(workspace, registered_commands={
        "mark": {"argv": ["python", "marker.py"], "args": [], "timeout_sec": 30, "output_limit": 4000},
    })
    permitted = workspace.digest()
    workspace.write_file("later.py", "changed after the permission\n")
    stale = action("run_command", {"name": "mark"}, preconditions=Preconditions(tree_digest=permitted))
    result = asyncio.run(environment.perform(stale))
    assert result.status == "failed" and result.ok is False
    assert result.error == "the workspace changed after the tool permission; call run_command again"
    assert not (workspace.root / "ran.txt").exists()
    current = action("run_command", {"name": "mark"}, preconditions=Preconditions(tree_digest=workspace.digest()))
    finished = asyncio.run(environment.perform(current))
    assert finished.status == "completed" and finished.output["status"] == "ok" and finished.output["attempt"] == 1


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
    environment = LocalEnvironment(workspace, registered_commands={
        "env": {"argv": ["python", "env.py"], "args": [], "timeout_sec": 30, "output_limit": 4000},
    })
    result = perform(environment, "run_command", {"name": "env"})
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
    environment = LocalEnvironment(workspace, registered_commands={
        "fail": {"argv": ["python", "fail.py"], "args": [], "timeout_sec": 30, "output_limit": 4000},
        "noisy": {"argv": ["python", "noisy.py"], "args": [], "timeout_sec": 30, "output_limit": 500},
    })
    failed = perform(environment, "run_command", {"name": "fail"})
    assert failed.ok is True
    assert failed.output["exit_code"] == 7
    assert failed.output["status"] == "failed"
    assert failed.output["truncated"] is False
    assert failed.output["executor"] == "host"
    overflow = perform(environment, "run_command", {"name": "noisy"})
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
    environment = LocalEnvironment(workspace, registered_commands={
        "hang": {"argv": ["python", "spawn.py"], "args": [], "timeout_sec": 3, "output_limit": 4000},
    })
    started = time.monotonic()
    result = perform(environment, "run_command", {"name": "hang"})
    assert time.monotonic() - started < 20
    assert result.ok is True and result.status == "timeout"
    assert result.output["status"] == "timeout"
    assert result.output["exit_code"] == 124
    assert result.output["output"].endswith("command timed out after 3s; the process tree was stopped")
    match = re.search(r"child=(\d+)", result.output["output"])
    assert match is not None
    # 子进程必须确实停止，不残留
    assert wait_until_stopped(int(match.group(1)))


def test_cancel_stops_a_running_command_and_its_receipt_is_cancelled(tmp_path):
    # 登记命令运行中取消：结束整个进程树，回执记为已取消，带截至结束时的输出
    workspace = Workspace(tmp_path / "ws")
    marker = tmp_path / "started"
    environment = LocalEnvironment(workspace, registered_commands={
        "serve": {"argv": ["python", "-c", LONG_RUNNING_TREE, str(marker)], "args": [], "timeout_sec": 60,
                  "output_limit": 4000},
    })
    request = action("run_command", {"name": "serve"})
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, environment.perform(request))
        wait_for_file(marker)
        started = time.monotonic()
        environment.cancel(request.action_id)
        result = future.result(timeout=20)
    assert time.monotonic() - started < 10
    assert result.ok is True and result.status == "cancelled"
    assert result.output["status"] == "cancelled" and result.output["exit_code"] == 130
    lines = result.output["output"].splitlines()
    assert lines[-1] == "command cancelled; the process tree was stopped"
    child = int(re.search(r"started child=(\d+)", lines[0]).group(1))
    assert wait_until_stopped(child)


def test_model_reported_exit_code_is_not_evidence(tmp_path):
    workspace = Workspace(tmp_path / "ws")
    workspace.write_file("exiter.py", "raise SystemExit(3)\n")
    environment = LocalEnvironment(workspace, registered_commands={
        "exiter": {"argv": ["python", "exiter.py"], "args": [], "timeout_sec": 30, "output_limit": 4000},
    })
    result = perform(environment, "run_command", {"name": "exiter", "exit_code": 0})
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


def _call(identity, tool, **arguments):
    return {"id": identity, "call_id": identity, "type": "function_call", "name": tool,
            "arguments": json_dumps(arguments)}


def _submit(identity):
    return _call(identity, "submit_delivery", summary="echo CLI", files=["src/echo.py"], check_names=["unit-tests"])


def test_delivery_accepts_only_run_check_receipts_from_this_activation_on_the_current_workspace(data_dir):
    argv = ["python", "src/echo.py", "hello"]
    registry = {"unit-tests": {"argv": argv, "args": [], "timeout_sec": 30, "output_limit": 4000}}
    source = "import sys\nprint(sys.argv[1])\n"
    adapter = FakeAdapter([
        product_spec(),
        plan_turn(),
        # 登记命令在主机上成功运行，它的结果是动作回执
        ModelResponse(output=[_call("write-1", "write_file", path="src/echo.py", content=source),
                              _call("command-1", "run_command", name="unit-tests"), _submit("submit-1")]),
        # 检查之后又修改了文件，回执不再对应当前工作区
        ModelResponse(output=[_call("check-2", "run_check", name="unit-tests", argv=argv),
                              _call("write-2", "write_file", path="src/echo.py", content=source + "\n"),
                              _submit("submit-2")]),
        ModelResponse(output=[_call("check-3", "run_check", name="unit-tests", argv=argv), _submit("submit-3")]),
        review_turn("release", "verified the delivered echo CLI"),
    ])
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("命令与检查回执", registered_commands=registry, command_versions={"unit-tests": 1})
    projection = system.run_until_stop(run_id)
    assert projection.phase == "DONE", projection.error
    events = system.store.list_events(run_id)
    [command] = [event for event in events
                 if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "run_command"]
    assert command.payload["ok"] is True
    output = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**command.payload["output_ref"])))
    assert output["exit_code"] == 0 and output["output"] == "hello"
    rejected = [event for event in events if event.type == EventType.PROPOSAL_REJECTED]
    assert [event.payload["kind"] for event in rejected] == ["delivery_spec", "delivery_spec"]
    for event in rejected:
        [error] = event.payload["errors"]
        assert error["field"] == "check_names"
        assert "Call run_check with the name unit-tests on the current workspace" in error["message"]
        assert "run_command results are action receipts and do not count as check receipts" in error["message"]
    engineering = [item for item in adapter.invocations if item.department == "engineering"]
    for item in engineering:
        [tool] = [tool for tool in item.tools if tool["name"] == "submit_delivery"]
        assert tool["description"] == TOOL_SCHEMAS["submit_delivery"]["description"]
    # 每次拒绝的原因都进入工程部门下一次激活的请求
    feedback = [part for item in engineering for part in recorded_context(system, item).parts
                if part.source == "validation_feedback"]
    assert [part.version for part in feedback] == [event.event_id for event in rejected]
    assert all("Call run_check with the name unit-tests" in part.text for part in feedback)
    delivery = projection.delivery_spec
    assert delivery.check_names == ["unit-tests"]
    [check] = delivery.checks
    assert check["exit_code"] == 0 and check["snapshot_hash"] == delivery.code_tree_digest
    assert check["activation_id"] == engineering[-1].activation_id
    assert projection.canonical_state() == system.replay(run_id).canonical_state()


def test_engineering_request_separates_action_receipts_from_delivery_check_receipts(data_dir):
    registry = {"probe": {"argv": ["python", "-c", "print('probe-ok')"], "args": [],
                          "timeout_sec": 30, "output_limit": 4000}}
    adapter = FakeAdapter(happy_script())
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("回执说法", registered_commands=registry, command_versions={"probe": 1})
    assert system.run_until_stop(run_id).phase == "DONE"
    engineering = [item for item in adapter.invocations if item.department == "engineering"]
    assert engineering
    for item in engineering:
        [command] = [tool for tool in item.tools if tool["name"] == "run_command"]
        assert command["description"] == TOOL_SCHEMAS["run_command"]["description"]
        assert "run_command results are action receipts and cannot be listed in submit_delivery check_names" in command["description"]
        contract = json.loads(prompt_part(item, "proposal_contract"))
        bind = contract["kinds"]["delivery_spec"]["bind"]
        assert "run_check receipts from this activation on the current workspace" in bind
        assert not any("host check receipts" in entry for entry in bind)
        assert ("check_names 必须对应本次激活中在当前工作区上调用 run_check 的回执；"
                "run_command 的结果不能作为检查回执，模型自报的 exit_code 无效。") in contract["notes"]
        assert not any("主机回执" in note for note in contract["notes"])


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
