import asyncio
import json
import re
import sqlite3
import sys
import time
import uuid

from concurrent.futures import ThreadPoolExecutor

import pytest

from harness.adapters.fake import FakeAdapter, prompt_part
from harness.app.application import Application
from harness.models import ArtifactRef, EventType, ProjectEventType, json_dumps
from harness.projects import CommandConfigConflict
from harness.proposals import delivery_turn, product_spec, review_turn
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.actions import Preconditions
from harness.recovery import action_repeatable
from harness.environment import _OUTPUT_LIMIT, _TRUNCATED_MARKER, LocalEnvironment
from harness.tests.api_helpers import running_api
from harness.tests.helpers import (action, happy_script, perform, recorded_context,
                                   run_tree_command, wait_for_file, wait_until_stopped)
from harness.definitions import DEFINITIONS
from harness.workspace import Workspace

GOAL = "做一个可以长期演进的逐行文本处理工具。"
SECRET_NAME = "YUDAO_TEST_API_KEY"
SECRET_VALUE = "credential-value-12345678"

# bash 命令串里的本机解释器路径：Windows 上用正斜杠，与 helpers.run_tree_command 同一写法
_PY = sys.executable.replace(chr(92), "/")

def test_unregistered_name_and_out_of_allowlist_args_rejected_before_execution(tmp_path):
    # 原用例证明 run_command 的未登记名与超范围参数在执行前被拒（工单 #484 删除登记体系）。
    # 现在证明 bash 的参数校验：命令缺失或为空在执行前被拒，拒绝时不启动进程、不写回执
    workspace = Workspace(tmp_path / "ws")
    workspace.write_file("marker.py", "from pathlib import Path\nPath('ran.txt').write_text('ran')\n")
    environment = LocalEnvironment(workspace)
    missing = perform(environment, "bash", {})
    assert missing.ok is False
    assert missing.error == "bash requires a non-empty command string"
    blank = perform(environment, "bash", {"command": "   "})
    assert blank.ok is False
    assert blank.error == "bash requires a non-empty command string"
    # 任一拒绝都没有执行：标记文件不存在
    assert not (workspace.root / "ran.txt").exists()
    assert workspace.receipts() == []
    allowed = perform(environment, "bash", {"command": f'"{_PY}" marker.py'})
    assert allowed.ok is True
    assert allowed.output["exit_code"] == 0
    assert allowed.output["status"] == "ok"
    assert (workspace.root / "ran.txt").read_text() == "ran"

def test_command_does_not_run_when_the_tree_changed_after_the_permission(tmp_path):
    # 前置条件：工具许可所依据的公开树摘要与执行之前的摘要不同时不执行
    workspace = Workspace(tmp_path / "ws")
    workspace.write_file("marker.py", "from pathlib import Path\nPath('ran.txt').write_text('ran')\n")
    environment = LocalEnvironment(workspace)
    permitted = workspace.digest()
    workspace.write_file("later.py", "changed after the permission\n")
    stale = action("bash", {"command": f'"{_PY}" marker.py'},
                   preconditions=Preconditions(tree_digest=permitted))
    result = asyncio.run(environment.perform(stale))
    assert result.status == "failed" and result.ok is False
    assert result.error == "the workspace changed after the tool permission; call bash again"
    assert not (workspace.root / "ran.txt").exists()
    current = action("bash", {"command": f'"{_PY}" marker.py'},
                     preconditions=Preconditions(tree_digest=workspace.digest()))
    finished = asyncio.run(environment.perform(current))
    assert (finished.status == "completed" and finished.output["status"] == "ok"
            and finished.output["exit_code"] == 0)

def test_fixed_cwd_and_sanitized_env(tmp_path, monkeypatch):
    # 环境契约（#479/#480）：bash 进程继承 Yudao 进程的完整环境，凭据会传给子进程；
    # 保护改为回执脱敏——secret 的值不出现在回执里（见 test_bash.py 的同一断言）。
    # 因此这里断言固定 cwd、PYTHONDONTWRITEBYTECODE=1 与脱敏，不再断言凭据被剥离
    monkeypatch.setenv(SECRET_NAME, SECRET_VALUE)
    workspace = Workspace(tmp_path / "ws")
    workspace.write_file(
        "env.py",
        "import os\n"
        "print('CWD=' + os.getcwd())\n"
        "print('CRED=' + ('has' if os.environ.get('YUDAO_TEST_API_KEY') else 'missing'))\n"
        "print('PWB=' + os.environ.get('PYTHONDONTWRITEBYTECODE', 'unset'))\n",
    )
    environment = LocalEnvironment(workspace)
    result = perform(environment, "bash", {"command": f'"{_PY}" env.py'})
    assert result.ok is True
    assert result.output["status"] == "ok"
    assert f"CWD={workspace.root}" in result.output["output"]
    assert "PWB=1" in result.output["output"]
    # 回执脱敏：secret 的值不进入模型可见的输出
    assert SECRET_VALUE not in result.output["output"]
    assert SECRET_VALUE not in json_dumps(result.output)

def test_exit_failure_and_output_overflow_have_real_states(tmp_path):
    workspace = Workspace(tmp_path / "ws")
    workspace.write_file("fail.py", "raise SystemExit(7)\n")
    workspace.write_file("noisy.py", "print('y' * 20000)\n")
    environment = LocalEnvironment(workspace)
    failed = perform(environment, "bash", {"command": f'"{_PY}" fail.py'})
    assert failed.ok is True
    assert failed.output["exit_code"] == 7
    assert failed.output["status"] == "failed"
    assert failed.output["truncated"] is False
    assert failed.output["executor"] == "host"
    overflow = perform(environment, "bash", {"command": f'"{_PY}" noisy.py'})
    assert overflow.ok is True
    assert overflow.output["exit_code"] == 0
    assert overflow.output["status"] == "ok"
    assert overflow.output["truncated"] is True
    # 输出上限与截断标记取自现行定义：run_command 的 output_limit 配置已不存在
    assert len(overflow.output["output"]) <= _OUTPUT_LIMIT + len(_TRUNCATED_MARKER)
    assert _TRUNCATED_MARKER.strip() in overflow.output["output"]

def test_timeout_kills_the_whole_process_tree(tmp_path):
    workspace = Workspace(tmp_path / "ws")
    workspace.write_file(
        "spawn.py",
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "print(f'child={child.pid}', flush=True)\n"
        "time.sleep(30)\n",
    )
    environment = LocalEnvironment(workspace)
    started = time.monotonic()
    result = perform(environment, "bash", {"command": f'"{_PY}" spawn.py', "timeout_sec": 3})
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
    # bash 运行中取消：结束整个进程树，回执记为已取消，带截至结束时的输出
    workspace = Workspace(tmp_path / "ws")
    marker = tmp_path / "started"
    environment = LocalEnvironment(workspace)
    request = action("bash", {"command": run_tree_command(marker), "timeout_sec": 60})
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
    environment = LocalEnvironment(workspace)
    # 模型自报 exit_code=0：bash 的契约不读这个字段，回执里的退出码由主机执行产生
    result = perform(environment, "bash", {"command": f'"{_PY}" exiter.py', "exit_code": 0})
    assert result.ok is True
    assert result.output["exit_code"] == 3
    assert result.output["status"] == "failed"
    assert result.output["executor"] == "host"

def _command_only(request):
    # 只执行 bash 命令、不提交提案：同一次工程激活继续走下一步，由后面的 delivery_turn 收尾
    return ModelResponse(
        output=[
            {"id": "cmd-1", "call_id": "cmd-1", "type": "function_call", "name": "bash",
             "arguments": json_dumps({"command": f'"{_PY}" -c "print(\'probe-ok\')"'})},
        ],
        provider="fake",
        model="fake-script",
    )

def test_finished_receipt_binds_command_snapshot_status_output_and_attempt(data_dir):
    # 原断言绑定 run_command 的登记名/argv/attempt（工单 #484 已删除登记体系）；
    # 现在证明 bash 的回执绑定：执行前快照、退出码、状态、输出与执行者
    system = LoopSystem.for_testing(data_dir, FakeAdapter([
        product_spec(), _command_only, delivery_turn(), review_turn("release", "ok"),
    ]))
    run_id = system.create_run("命令回执")
    assert system.run_until_stop(run_id).phase == "DONE"
    events = system.store.list_events(run_id)
    started = next(event for event in events
                   if event.type == EventType.TOOL_STARTED and event.payload.get("name") == "bash")
    assert started.payload["args"] == {"command": f'"{_PY}" -c "print(\'probe-ok\')"'}
    # 执行前的公开树快照随事件写入（工单 #17）：摘要以 sha256: 开头，与回执绑定的是同一份
    before = json.loads(system.artifacts.get_for_run(
        run_id, ArtifactRef(**started.payload["before_snapshot_ref"])).decode("utf-8"))
    assert before["digest"].startswith("sha256:")
    called = next(event for event in events
                  if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "bash")
    assert called.payload["ok"] is True
    raw = system.artifacts.get_for_run(run_id, ArtifactRef(**called.payload["output_ref"])).decode("utf-8")
    output = json.loads(raw)
    assert output["command"] == f'"{_PY}" -c "print(\'probe-ok\')"'
    assert output["exit_code"] == 0
    assert output["status"] == "ok"
    assert output["output"] == "probe-ok"
    assert output["executor"] == "host"
    assert output["snapshot_hash"] == before["digest"]
    # 回执绑定的是执行前快照：后续交付写入后工作区摘要已经不同
    assert output["snapshot_hash"] != system.workspace(run_id).digest()

def _call(identity, tool, **arguments):
    return {"id": identity, "call_id": identity, "type": "function_call", "name": tool,
            "arguments": json_dumps(arguments)}

def _submit(call, identity):
    # 交付按依据版本声明（工单 #471）：从请求的当前 ProductSpec 取内容哈希
    raw = prompt_part(call, "current_product_spec")
    basis = json.loads(raw).get("content_hash") if raw else None
    return _call(identity, "submit_delivery", summary="echo CLI", files=["src/echo.py"],
                 check_names=["unit-tests"], basis_product_spec_hash=basis)

def test_delivery_accepts_only_run_check_receipts_from_this_activation_on_the_current_workspace(data_dir):
    # 原用例用 run_command 作为动作回执；现在用 bash：动作回执仍然不是检查回执
    command = "python src/echo.py hello"
    source = "import sys\nprint(sys.argv[1])\n"
    # bash 在主机上成功运行，它的结果是动作回执
    def first(call):
        return ModelResponse(output=[
            _call("write-1", "write_file", path="src/echo.py", content=source),
            _call("command-1", "bash", command=command), _submit(call, "submit-1")])

    # 检查之后又修改了文件，回执不再对应当前工作区
    def second(call):
        return ModelResponse(output=[
            _call("check-2", "run_check", name="unit-tests", command=command),
            _call("write-2", "write_file", path="src/echo.py", content=source + "\n"),
            _submit(call, "submit-2")])

    def third(call):
        return ModelResponse(output=[
            _call("check-3", "run_check", name="unit-tests", command=command), _submit(call, "submit-3")])

    adapter = FakeAdapter([product_spec(), first, second, third,
                           review_turn("release", "verified the delivered echo CLI")])
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("命令与检查回执")
    projection = system.run_until_stop(run_id)
    assert projection.phase == "DONE", projection.error
    events = system.store.list_events(run_id)
    [command_receipt] = [event for event in events
                         if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "bash"]
    assert command_receipt.payload["ok"] is True
    output = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**command_receipt.payload["output_ref"])))
    assert output["exit_code"] == 0 and output["output"] == "hello"
    rejected = [event for event in events if event.type == EventType.PROPOSAL_REJECTED]
    assert [event.payload["kind"] for event in rejected] == ["delivery_spec", "delivery_spec"]
    for event in rejected:
        [error] = event.payload["errors"]
        assert error["field"] == "check_names"
        assert "Call run_check with the name unit-tests on the current workspace" in error["message"]
        assert "bash results are action receipts and do not count as check receipts" in error["message"]
    engineering = [item for item in adapter.invocations if item.department == "engineering"]
    for item in engineering:
        [tool] = [tool for tool in item.tools if tool["name"] == "submit_delivery"]
        assert tool["description"] == DEFINITIONS.tools["submit_delivery"].description
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
    adapter = FakeAdapter(happy_script())
    system = LoopSystem.for_testing(data_dir, adapter)
    run_id = system.create_run("回执说法")
    assert system.run_until_stop(run_id).phase == "DONE"
    engineering = [item for item in adapter.invocations if item.department == "engineering"]
    assert engineering
    for item in engineering:
        [command] = [tool for tool in item.tools if tool["name"] == "bash"]
        assert command["description"] == DEFINITIONS.tools["bash"].description
        assert ("A bash result is an action receipt, not a check receipt: "
                "it cannot be listed in submit_delivery check_names") in command["description"]
        contract = json.loads(prompt_part(item, "proposal_contract"))
        bind = contract["kinds"]["delivery_spec"]["bind"]
        assert "run_check receipts from this activation on the current workspace" in bind
        assert not any("host check receipts" in entry for entry in bind)
        assert ("check_names 必须对应本次激活中在当前工作区上调用 run_check 的回执；"
                "bash 的结果不能作为检查回执，模型自报的 exit_code 无效。") in contract["notes"]
        assert not any("主机回执" in note for note in contract["notes"])

def test_registry_freezes_at_work_item_creation(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter([*happy_script(), *happy_script()]))
    project_id = system.projects.register("Cmd", GOAL)
    first = system.projects.configure_command(project_id, "itest", ["python", "-c", "print(1)"], base_version=0)
    assert first["version"] == 1 and first["unchanged"] is False
    assert first["repeatable"] is False
    check_timeout_sec = DEFINITIONS.rule_value("check_timeout_sec")
    tool_output_limit = DEFINITIONS.rule_value("tool_output_limit")
    assert first["timeout_sec"] == check_timeout_sec and first["output_limit"] == tool_output_limit
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
                  "timeout_sec": check_timeout_sec, "output_limit": tool_output_limit,
                  "repeatable": False},
    }
    assert run.command_versions == {"itest": 1}
    assert system.projects.projection(project_id).work_item(work_item_id).command_versions == {"itest": 1}
    assert system.run_until_stop(run_id).phase == "DONE"
    second = system.projects.configure_command(
        project_id, "itest", ["python", "-c", "print(2)"], args=["--fast"],
        timeout_sec=60, output_limit=8000, repeatable=True, base_version=1)
    assert second["version"] == 2 and second["unchanged"] is False and second["repeatable"] is True
    # 已创建事项不受影响：冻结仍是创建时的版本与「可以重新执行」声明
    assert system.project(run_id).registered_commands["itest"]["argv"] == ["python", "-c", "print(1)"]
    assert system.project(run_id).registered_commands["itest"]["repeatable"] is False
    assert system.project(run_id).command_versions == {"itest": 1}
    _work_item_2, run_2 = system.projects.start_work_item(project_id, "第二步")
    assert system.project(run_2).registered_commands["itest"]["argv"] == ["python", "-c", "print(2)"]
    assert system.project(run_2).registered_commands["itest"]["repeatable"] is True
    assert system.project(run_2).command_versions == {"itest": 2}

def test_command_registration_commands_and_stale_base(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    application = Application(system)
    with running_api(lambda: application) as client:
        created = client.post("/api/commands/project.create",
                              json={"command_id": str(uuid.uuid4()), "name": "Cmd", "goal": GOAL})
        assert created.status_code == 200, created.text
        project_id = created.json()["refs"]["project_id"]
        saved = client.post("/api/commands/command_registration.save", json={
            "command_id": str(uuid.uuid4()), "project_id": project_id, "name": "itest",
            "argv": ["python", "-c", "print(1)"], "base_version": 0})
        assert saved.status_code == 200, saved.text
        settings = client.get("/api/queries/project.settings", params={"project_id": project_id}).json()["data"]
        assert list(settings["commands"]) == ["itest"]
        assert settings["commands"]["itest"]["argv"] == ["python", "-c", "print(1)"]
        stale = client.post("/api/commands/command_registration.save", json={
            "command_id": str(uuid.uuid4()), "project_id": project_id, "name": "itest",
            "argv": ["python", "-c", "print(2)"], "base_version": 0})
        assert stale.status_code == 409, stale.text
        assert stale.json()["reason"] == "stale_base"

def test_registering_a_command_declares_whether_it_can_repeat(data_dir):
    # 登记时声明「可以重新执行」，经接口与事件日志读回为真；不声明时为否（工单 #242）
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    application = Application(system)
    with running_api(lambda: application) as client:
        created = client.post("/api/commands/project.create",
                              json={"command_id": str(uuid.uuid4()), "name": "Cmd", "goal": GOAL})
        project_id = created.json()["refs"]["project_id"]
        repeatable = client.post("/api/commands/command_registration.save", json={
            "command_id": str(uuid.uuid4()), "project_id": project_id, "name": "lint",
            "argv": ["python", "-m", "flake8"], "repeatable": True, "base_version": 0})
        assert repeatable.status_code == 200, repeatable.text
        plain = client.post("/api/commands/command_registration.save", json={
            "command_id": str(uuid.uuid4()), "project_id": project_id, "name": "deploy",
            "argv": ["python", "deploy.py"], "base_version": 0})
        assert plain.status_code == 200, plain.text
        settings = client.get("/api/queries/project.settings", params={"project_id": project_id}).json()["data"]
        assert settings["commands"]["lint"]["repeatable"] is True
        assert settings["commands"]["deploy"]["repeatable"] is False
        events = system.store.list_project_events(project_id)
        [configured] = [event for event in events if event.type == ProjectEventType.COMMAND_CONFIGURED
                        and event.payload["name"] == "lint"]
        assert configured.payload["repeatable"] is True
    system.close()

def _without_repeatable(data_dir):
    # 得到一份旧版本写入的数据目录：command_configured 事件里没有 repeatable 字段
    connection = sqlite3.connect(data_dir / "events.sqlite")
    try:
        rows = connection.execute(
            "SELECT event_id, payload_json FROM events WHERE type = ?",
            (ProjectEventType.COMMAND_CONFIGURED,)).fetchall()
        assert rows, "no command_configured events"
        for event_id, payload in rows:
            document = json.loads(payload)
            document.pop("repeatable", None)
            connection.execute("UPDATE events SET payload_json = ? WHERE event_id = ?",
                               (json.dumps(document, ensure_ascii=False, sort_keys=True), event_id))
        connection.execute("DELETE FROM projections")
        connection.commit()
    finally:
        connection.close()

def test_a_command_configured_event_without_the_field_reads_as_not_repeatable(data_dir):
    # 旧版本写入的 command_configured 事件没有 repeatable：重放以后按否处理（ADR-0019）
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    project_id = system.projects.register("Cmd", GOAL)
    system.projects.configure_command(project_id, "lint", ["python", "-m", "flake8"],
                                      repeatable=True, base_version=0)
    system.close()
    _without_repeatable(data_dir)

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    assert restarted.projects.read_commands(project_id)[0]["repeatable"] is False
    restarted.close()

def test_run_command_actions_repeat_by_the_registration_frozen_in_the_run(data_dir):
    # 判断入口读的是 run 中固定的登记：事项创建以后修改登记不改这个 run 的回答，新事项取新登记
    system = LoopSystem.for_testing(data_dir, FakeAdapter([*happy_script(), *happy_script()]))
    project_id = system.projects.register("Cmd", GOAL)
    system.projects.configure_command(project_id, "lint", ["python", "-m", "flake8"],
                                      repeatable=True, base_version=0)
    _work_item_id, first_run = system.projects.start_work_item(project_id, "第一步")
    assert action_repeatable("run_command", {"name": "lint"},
                             registered_commands=system.project(first_run).registered_commands) is True
    system.projects.configure_command(project_id, "lint", ["python", "-m", "flake8"],
                                      repeatable=False, base_version=1)
    assert action_repeatable("run_command", {"name": "lint"},
                             registered_commands=system.project(first_run).registered_commands) is True
    _work_item_2, second_run = system.projects.start_work_item(project_id, "第二步")
    assert action_repeatable("run_command", {"name": "lint"},
                             registered_commands=system.project(second_run).registered_commands) is False
    system.close()
