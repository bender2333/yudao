import asyncio
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from harness.adapters.fake import FakeAdapter
from harness.environment import LocalEnvironment
from harness.models import EventType, json_dumps
from harness.proposals import delivery_turn, product_spec
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.tests.helpers import action, perform, run_tree_command, wait_for_file, wait_until_stopped
from harness.definitions import DEFINITIONS
from harness.tools import tools_for
from harness.workspace import Workspace

TOOLS = DEFINITIONS.tools

def _call(identity, name, **arguments):
    return {"id": identity, "call_id": identity, "type": "function_call", "name": name,
            "arguments": json_dumps(arguments)}

def test_quality_checks_only_through_run_check(tmp_path):
    assert [name for name in tools_for("quality") if TOOLS[name].action == "check"] == ["run_check"]
    workspace = Workspace(tmp_path)
    workspace.write_file("ok.py", "raise SystemExit(0)\n")
    result = perform(LocalEnvironment(workspace), "run_check", {"name": "smoke", "command": "python ok.py"},
                     department="quality")
    assert result.ok is True and result.output["executor"] == "host"
    assert workspace.snapshot().facts.latest_check("quality", "smoke").exit_code == 0
    assert workspace.snapshot().facts.latest_check("engineering", "smoke") is None


def test_actions_and_receipts_are_serializable_contracts(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.write_file("a.txt", "a\n")
    request = action("read_file", {"path": "a.txt"}, department="quality")
    assert type(request).model_validate_json(request.model_dump_json()) == request
    assert request.kind == "read" and request.tool == "read_file"
    receipt = asyncio.run(LocalEnvironment(workspace).perform(request))
    assert receipt.action_id == request.action_id and receipt.status == "completed" and receipt.output == "a\n"
    assert type(receipt).model_validate_json(receipt.model_dump_json()) == receipt

def test_run_check_executes_host_process_and_ignores_self_reported_exit_code(tmp_path):
    workspace = Workspace(tmp_path)
    environment = LocalEnvironment(workspace)
    workspace.write_file("ok.py", "raise SystemExit(3)\n")
    result = perform(environment, "run_check", {"name": "smoke", "command": "python ok.py", "exit_code": 0})
    assert result.ok is True
    assert result.status == "completed"
    assert result.output["exit_code"] == 3
    assert result.output["executor"] == "host"
    receipt = workspace.snapshot().facts.latest_check("engineering", "smoke")
    assert receipt is not None
    assert receipt.exit_code == 3
    assert "host-executed" in receipt.summary


def test_agent_cannot_read_or_write_checks(tmp_path):
    environment = LocalEnvironment(Workspace(tmp_path))
    written = perform(environment, "write_file", {"path": ".checks/receipts.jsonl", "content": "forged\n"})
    assert written.ok is False
    read = perform(environment, "read_file", {"path": ".checks/receipts.jsonl"})
    assert read.ok is False
    assert ".checks" not in perform(environment, "list_files", {}).output

def test_check_cannot_persist_forged_receipt(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.write_file(
        "forge.py",
        "from pathlib import Path\nPath('.checks/receipts.jsonl').write_text('forged\\n')\n",
    )
    result = perform(LocalEnvironment(workspace), "run_check", {"name": "smoke", "command": "python forge.py"})
    assert result.ok is True
    text = (tmp_path / ".checks" / "receipts.jsonl").read_text(encoding="utf-8")
    assert text.strip() != "forged"
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    assert rows
    assert all(row["name"] == "smoke" and row["department"] == "engineering" for row in rows)
    assert workspace.snapshot().facts.latest_check("engineering", "smoke") is not None


def test_check_subprocess_inherits_environment_and_redacts_secrets(tmp_path, monkeypatch):
    # 检查继承 Yudao 进程的全部环境变量（与 bash 相同），输出里只脱敏不删除
    monkeypatch.setenv("BLACKROUTER_API_KEY", "super-secret-value-123456")
    workspace = Workspace(tmp_path)
    workspace.write_file(
        "env.py",
        "import os, sys\n"
        "print('has' if os.environ.get('BLACKROUTER_API_KEY') else 'missing')\n"
        "print(os.environ.get('BLACKROUTER_API_KEY'))\n"
        "raise SystemExit(0)\n",
    )
    result = perform(LocalEnvironment(workspace), "run_check", {"name": "env", "command": "python env.py"})
    assert result.ok is True
    assert "has" in result.output["summary"]
    assert "super-secret-value-123456" not in result.output["summary"]
    assert "${BLACKROUTER_API_KEY}" in result.output["summary"]

def test_mutating_check_does_not_bind_pass_to_original_snapshot(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.write_file("app.py", "BROKEN = True\n")
    workspace.write_file(
        "fix.py",
        "from pathlib import Path\n"
        "p = Path('app.py')\n"
        "p.write_text('FIXED = True\\n')\n"
        "assert 'FIXED' in p.read_text()\n",
    )
    original = workspace.digest()
    result = perform(LocalEnvironment(workspace), "run_check", {"name": "smoke", "command": "python fix.py"})
    assert result.ok is True
    assert result.output["exit_code"] == 0
    assert workspace.read_file("app.py") == "BROKEN = True\n"
    assert workspace.digest() == original
    assert result.output["snapshot_hash"] != original
    assert result.output["tree_changed"] is True
    assert workspace.snapshot().facts.latest_check("engineering", "smoke") is None


def test_timed_out_check_records_timeout_exit_code_and_stops_the_process_tree(tmp_path):
    workspace = Workspace(tmp_path / "ws")
    environment = LocalEnvironment(workspace, check_timeout_sec=2)
    marker = tmp_path / "started"
    started = time.monotonic()
    result = perform(environment, "run_check",
                     {"name": "smoke", "command": run_tree_command(marker)})
    assert time.monotonic() - started < 20
    assert result.ok is True and result.status == "timeout"
    assert result.output["exit_code"] == 124
    assert result.output["summary"].splitlines()[1] == "check timed out after 2s"
    child = int(re.search(r"started child=(\d+)", result.output["summary"]).group(1))
    assert wait_until_stopped(child)
    receipt = workspace.snapshot().facts.latest_check("engineering", "smoke")
    assert receipt is not None
    assert receipt.exit_code == 124
    assert "timed out" in receipt.summary

def test_cancel_stops_a_running_check_and_its_receipt_is_cancelled(tmp_path):
    # 检查运行中取消：结束整个进程树，回执记为已取消，带截至结束时的输出，检查回执的退出码是 130
    workspace = Workspace(tmp_path / "ws")
    environment = LocalEnvironment(workspace)
    marker = tmp_path / "started"
    request = action("run_check", {"name": "smoke", "command": run_tree_command(marker)})
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, environment.perform(request))
        wait_for_file(marker)
        started = time.monotonic()
        environment.cancel(request.action_id)
        result = future.result(timeout=20)
    assert time.monotonic() - started < 10
    assert result.ok is True and result.status == "cancelled"
    assert result.output["exit_code"] == 130
    lines = result.output["summary"].splitlines()
    assert lines[1] == "check cancelled; the process tree was stopped"
    child = int(re.search(r"started child=(\d+)", lines[2]).group(1))
    assert wait_until_stopped(child)
    [receipt] = workspace.receipts()
    assert receipt.exit_code == 130 and receipt.summary == result.output["summary"]

def test_cancel_before_the_action_starts_does_not_start_the_process(tmp_path):
    workspace = Workspace(tmp_path / "ws")
    environment = LocalEnvironment(workspace)
    marker = tmp_path / "started"
    request = action("run_check", {"name": "smoke", "command": run_tree_command(marker)})
    environment.cancel(request.action_id)
    result = asyncio.run(environment.perform(request))
    assert result.status == "cancelled" and result.ok is False and result.output is None
    assert result.error == "The action was cancelled before it started."
    assert not marker.exists()
    assert workspace.receipts() == []

@pytest.fixture
def check_copy_base(tmp_path, monkeypatch):
    base = tmp_path / "check-copies"
    base.mkdir()
    monkeypatch.setattr("harness.workspace.tempfile.tempdir", str(base))
    return base


@pytest.mark.parametrize("department", ["product", "quality"])
def test_departments_without_write_tools_cannot_change_files(tmp_path, department):
    # 部门的工具范围由工具许可核对：没有写入工具的部门调用写入、编辑、删除、移动都被拒绝，文件不变
    calls = ModelResponse(output=[
        _call("write", "write_file", path="src/echo.py", content="x"),
        _call("edit", "edit_range", path="src/echo.py", start_line=1, end_line=1,
              expected_text="import sys", new_text="x"),
        _call("delete", "delete_file", path="src/echo.py", reason="remove replaced implementation"),
        _call("move", "move_file", source="src/echo.py", destination="src/moved.py", reason="organize module"),
    ])
    if department == "product":
        # 事项没有走到 PRD 被接纳以后（工单 #878）：这条脚本只有产品一个部门取用
        script = [calls]
    else:
        # 脚本按部门给出（工单 #878：PRD 被接纳以后工程与质检同时工作，
        # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）：
        # 交付是工程的活，这组写入调用是质检的活
        script = {"product": [product_spec()], "engineering": [delivery_turn()], "quality": [calls]}
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(script))
    run_id = system.create_run("echo")
    workspace = system.workspace(run_id)
    if department == "product":
        workspace.write_file("src/echo.py", "original\n")
    system.run_until_stop(run_id)
    before = workspace.read_file("src/echo.py")
    events = system.store.list_events(run_id)
    for identity, tool in (("write", "write_file"), ("edit", "edit_range"), ("delete", "delete_file"),
                           ("move", "move_file")):
        called = next(event for event in events if event.type == EventType.TOOL_CALLED and event.payload.get("id") == identity)
        assert called.department == department
        assert not called.payload["ok"] and called.payload["error"] == f"{department} cannot use {tool}"
        assert not any(event.type == EventType.TOOL_STARTED and event.payload["id"] == identity for event in events)
    assert workspace.read_file("src/echo.py") == before != "x"
    assert not (workspace.root / "src" / "moved.py").exists()


def test_check_copy_uses_previously_captured_bytes(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.write_file("app.py", "original\n")
    snapshot = workspace.snapshot()
    workspace.write_file("app.py", "new\n")
    workspace.write_file("extra.py", "new\n")
    with workspace.check_copy(snapshot.tree) as copy_root:
        assert (copy_root / "app.py").read_text() == "original\n"
        assert not (copy_root / "extra.py").exists()

def test_check_records_source_workspace_change(tmp_path):
    # 检查进程在运行中改写了源工作区（路径由参数给出）：回执记为树已改变，不绑定到原来的快照
    workspace = Workspace(tmp_path / "ws")
    workspace.write_file(
        "app.py",
        "import sys\nfrom pathlib import Path\nprint('checked original')\n"
        "Path(sys.argv[1]).write_text('changed after the check\\n')\nraise SystemExit(7)\n",
    )
    result = perform(LocalEnvironment(workspace), "run_check", {
        "name": "source", "command": 'python app.py "' + str(workspace.root / "app.py") + '"',
    })
    assert result.ok and result.output["exit_code"] == 7
    assert result.output["tree_changed"] is True
    assert "checked original" in result.output["summary"]
    assert "source workspace changed" in result.output["summary"]
    assert len(workspace.receipts()) == 1
    assert workspace.snapshot().facts.latest_check("engineering", "source") is None


