import asyncio
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from harness.adapters.fake import FakeAdapter
from harness.environment import LocalEnvironment, _display_argv
from harness.models import EventType, json_dumps
from harness.public_tree import UnrepresentableWorkspace
from harness.proposals import delivery_turn, plan_turn, product_spec
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.tests.helpers import LONG_RUNNING_TREE, action, perform, wait_for_file, wait_until_stopped
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
    result = perform(LocalEnvironment(workspace), "run_check", {"name": "smoke", "argv": ["python", "ok.py"]},
                     department="quality")
    assert result.ok is True and result.output["executor"] == "host"
    assert workspace.snapshot().facts.latest_check("quality", "smoke").exit_code == 0
    assert workspace.snapshot().facts.latest_check("engineering", "smoke") is None



def test_write_file_creates_parents_and_replaces_the_whole_file(tmp_path):
    workspace = Workspace(tmp_path)
    environment = LocalEnvironment(workspace)
    assert perform(environment, "write_file", {"path": "src/deep/a.py", "content": "first\nsecond\n"}).ok
    assert perform(environment, "write_file", {"path": "src/deep/a.py", "content": "only\n"}).ok
    assert workspace.read_file("src/deep/a.py") == "only\n"


def test_read_file_returns_the_whole_file_without_line_numbers_and_rejects_non_utf8(tmp_path):
    description = TOOLS["read_file"].description
    assert "entire content" in description and "without line numbers or truncation" in description
    assert "Files that are not valid UTF-8 are rejected." in description
    assert "Use read_range for large files" in description and "content_hash" in description
    workspace = Workspace(tmp_path)
    environment = LocalEnvironment(workspace)
    # 超过 read_range 单页上限的文件由 read_file 完整返回
    text = "".join(f"line {index} " + "x" * 80 + "\n" for index in range(200))
    workspace.write_file("big.txt", text)
    assert len(text) > 4000
    assert perform(environment, "read_file", {"path": "big.txt"}, department="quality").output == text
    (tmp_path / "latin1.txt").write_bytes(b"caf\xe9\n")
    unreadable = perform(environment, "read_file", {"path": "latin1.txt"}, department="quality")
    assert unreadable.ok is False and unreadable.status == "failed"


def test_list_files_is_recursive_and_prefix_is_a_plain_string_prefix(tmp_path):
    description = TOOLS["list_files"].description
    assert "recursively" in description and '"src2/a.py"' in description
    assert "end it with / to limit the list to one directory" in (
        TOOLS["list_files"].parameters["properties"]["prefix"]["description"])
    workspace = Workspace(tmp_path)
    environment = LocalEnvironment(workspace)
    for path in ("src/a.py", "src/deep/b.py", "src2/a.py", "top.txt"):
        workspace.write_file(path, "x\n")
    assert sorted(perform(environment, "list_files", {}).output) == [
        "src/a.py", "src/deep/b.py", "src2/a.py", "top.txt"]
    assert sorted(perform(environment, "list_files", {"prefix": "src/"}).output) == ["src/a.py", "src/deep/b.py"]
    assert sorted(perform(environment, "list_files", {"prefix": "src"}).output) == [
        "src/a.py", "src/deep/b.py", "src2/a.py"]


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
    result = perform(environment, "run_check", {"name": "smoke", "argv": ["python", "ok.py"], "exit_code": 0})
    assert result.ok is True
    assert result.status == "completed"
    assert result.output["exit_code"] == 3
    assert result.output["executor"] == "host"
    receipt = workspace.snapshot().facts.latest_check("engineering", "smoke")
    assert receipt is not None
    assert receipt.exit_code == 3
    assert "host-executed" in receipt.summary



def test_check_receipt_shows_a_workspace_program_as_its_own_path(tmp_path):
    # 不是主机解释器的程序原样显示，工作区里的路径不换写法
    workspace = Workspace(tmp_path)
    workspace.write_file("tools/echo.py", "raise SystemExit(0)\n")
    script = str(workspace.root / "tools" / "echo.py")
    assert _display_argv([script]) == json_dumps([script])
    assert _display_argv([sys.executable, script]) == json_dumps(["python", script])


def test_run_check_requires_command(tmp_path):
    result = perform(LocalEnvironment(Workspace(tmp_path)), "run_check", {"name": "smoke", "exit_code": 0})
    assert result.ok is False
    assert "argv" in (result.error or "") or "command" in (result.error or "")


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
    result = perform(LocalEnvironment(workspace), "run_check", {"name": "smoke", "argv": ["python", "forge.py"]})
    assert result.ok is True
    text = (tmp_path / ".checks" / "receipts.jsonl").read_text(encoding="utf-8")
    assert text.strip() != "forged"
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    assert rows
    assert all(row["name"] == "smoke" and row["department"] == "engineering" for row in rows)
    assert workspace.snapshot().facts.latest_check("engineering", "smoke") is not None


def test_check_does_not_keep_workspace_mutations(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.write_file("src/echo.py", "print('ok')\n")
    workspace.write_file("mutate.py", "from pathlib import Path\nPath('hacked.txt').write_text('x')\n")
    perform(LocalEnvironment(workspace), "run_check", {"name": "smoke", "argv": ["python", "mutate.py"]},
            department="quality")
    assert "hacked.txt" not in workspace.list_files()
    assert workspace.read_file("src/echo.py") == "print('ok')\n"


def test_check_subprocess_does_not_inherit_provider_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("BLACKROUTER_API_KEY", "super-secret-value-123456")
    workspace = Workspace(tmp_path)
    workspace.write_file(
        "env.py",
        "import os, sys\n"
        "print('has' if os.environ.get('BLACKROUTER_API_KEY') else 'missing')\n"
        "raise SystemExit(0)\n",
    )
    result = perform(LocalEnvironment(workspace), "run_check", {"name": "env", "argv": [sys.executable, "env.py"]})
    assert result.ok is True
    assert "missing" in result.output["summary"]
    assert "super-secret-value-123456" not in result.output["summary"]


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
    result = perform(LocalEnvironment(workspace), "run_check", {"name": "smoke", "argv": ["python", "fix.py"]})
    assert result.ok is True
    assert result.output["exit_code"] == 0
    assert workspace.read_file("app.py") == "BROKEN = True\n"
    assert workspace.digest() == original
    assert result.output["snapshot_hash"] != original
    assert result.output["tree_changed"] is True
    assert workspace.snapshot().facts.latest_check("engineering", "smoke") is None


def test_check_copy_does_not_follow_hardlink_into_external_file(tmp_path):
    workspace = Workspace(tmp_path / "ws")
    outside = tmp_path / "outside.txt"
    outside.write_text("EXTERNAL", encoding="utf-8")
    target = workspace.root / "target.txt"
    try:
        os.link(outside, target)
    except OSError:
        pytest.skip("hard links are not available")
    workspace.write_file("poke.py", "from pathlib import Path\nPath('target.txt').write_text('HACKED')\n")
    # 工作区已有公开树无法表示的条目：检查不开始，由步骤驱动以 workspace_unrepresentable 暂停运行
    with pytest.raises(UnrepresentableWorkspace, match="Hard-linked files are not supported: target.txt"):
        perform(LocalEnvironment(workspace), "run_check", {"name": "smoke", "argv": ["python", "poke.py"]})
    assert workspace.receipts() == []
    assert outside.read_text(encoding="utf-8") == "EXTERNAL"
    assert target.read_text(encoding="utf-8") != "HACKED"


def test_failed_check_records_real_exit_code(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.write_file("fail.py", "raise SystemExit(7)\n")
    result = perform(LocalEnvironment(workspace), "run_check", {"name": "smoke", "argv": ["python", "fail.py"]})
    assert result.ok is True
    assert result.output["exit_code"] == 7
    receipt = workspace.snapshot().facts.latest_check("engineering", "smoke")
    assert receipt is not None
    assert receipt.exit_code == 7
    assert receipt.snapshot_hash == workspace.digest()


def test_timed_out_check_records_timeout_exit_code_and_stops_the_process_tree(tmp_path):
    workspace = Workspace(tmp_path / "ws")
    environment = LocalEnvironment(workspace, check_timeout_sec=2)
    marker = tmp_path / "started"
    started = time.monotonic()
    result = perform(environment, "run_check", {"name": "smoke", "argv": ["python", "-c", LONG_RUNNING_TREE, str(marker)]})
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
    request = action("run_check", {"name": "smoke", "argv": ["python", "-c", LONG_RUNNING_TREE, str(marker)]})
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
    request = action("run_check", {"name": "smoke", "argv": ["python", "-c", LONG_RUNNING_TREE, str(marker)]})
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


def test_missing_check_command_does_not_leave_a_copy(tmp_path, check_copy_base):
    workspace = Workspace(tmp_path / "workspace")
    workspace.write_file("ok.py", "print('ok')\n")
    result = perform(LocalEnvironment(workspace), "run_check", {"name": "smoke", "argv": ["missing.py"]})
    assert result.ok is False
    assert "missing.py" in (result.error or "")
    assert list(check_copy_base.iterdir()) == []


def test_failed_check_copy_does_not_leave_a_copy(tmp_path, monkeypatch, check_copy_base):
    workspace = Workspace(tmp_path / "workspace")
    workspace.write_file("ok.py", "print('ok')\n")
    def fail_copy(tree, target):
        target.mkdir()
        raise OSError("copy failed")

    monkeypatch.setattr("harness.workspace.materialize_tree", fail_copy)
    result = perform(LocalEnvironment(workspace), "run_check", {"name": "smoke", "argv": ["python", "ok.py"]})
    assert result.ok is False
    assert "copy failed" in (result.error or "")
    assert list(check_copy_base.iterdir()) == []


def test_successful_and_failed_checks_do_not_leave_copies(tmp_path, check_copy_base):
    workspace = Workspace(tmp_path / "workspace")
    environment = LocalEnvironment(workspace)
    workspace.write_file("ok.py", "print('ok')\n")
    workspace.write_file("fail.py", "raise SystemExit(7)\n")
    with workspace.check_copy(workspace.snapshot().tree) as copy_root:
        assert copy_root.parent.parent == check_copy_base
        assert not copy_root.is_relative_to(workspace.root)
    ok = perform(environment, "run_check", {"name": "ok", "argv": ["python", "ok.py"]})
    failed = perform(environment, "run_check", {"name": "fail", "argv": ["python", "fail.py"]})
    assert ok.ok is True
    assert ok.output["exit_code"] == 0
    assert failed.ok is True
    assert failed.output["exit_code"] == 7
    assert workspace.read_file("ok.py") == "print('ok')\n"
    assert list(check_copy_base.iterdir()) == []


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
    script = [calls] if department == "product" else [product_spec(), plan_turn(), delivery_turn(), calls]
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


def test_module_import_check_preserves_complete_tree(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.write_file("helper.py", "VALUE = 42\n")
    workspace.write_file("main.py", "from helper import VALUE\nprint(VALUE)\nassert VALUE == 42\n")
    result = perform(LocalEnvironment(workspace), "run_check", {"name": "imports", "argv": ["python", "main.py"]})
    assert result.ok and result.output["exit_code"] == 0
    assert result.output["tree_changed"] is False
    assert "42" in result.output["summary"]
    assert workspace.snapshot().facts.latest_check("engineering", "imports") is not None
    assert workspace.list_files() == ["helper.py", "main.py"]


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
        "name": "source", "argv": ["python", "app.py", str(workspace.root / "app.py")],
    })
    assert result.ok and result.output["exit_code"] == 7
    assert result.output["tree_changed"] is True
    assert "checked original" in result.output["summary"]
    assert "source workspace changed" in result.output["summary"]
    assert len(workspace.receipts()) == 1
    assert workspace.snapshot().facts.latest_check("engineering", "source") is None


@pytest.mark.parametrize("failed_root", ["copy", "source"])
def test_check_keeps_process_evidence_when_postcheck_capture_fails(tmp_path, failed_root):
    # 检查进程在被检查的副本或源工作区中留下硬链接，检查以后读取公开树失败：进程的结果仍然记为证据
    workspace = Workspace(tmp_path / "ws")
    workspace.write_file(
        "app.py",
        "import os, sys\nroot = sys.argv[1] if len(sys.argv) > 1 else '.'\n"
        "os.link(os.path.join(root, 'app.py'), os.path.join(root, 'linked.py'))\n"
        "print('observed output')\nraise SystemExit(9)\n",
    )
    argv = ["python", "app.py"] + ([str(workspace.root)] if failed_root == "source" else [])
    result = perform(LocalEnvironment(workspace), "run_check", {"name": "unverified", "argv": argv})
    assert result.ok and result.output["exit_code"] == 9
    assert result.output["tree_changed"] is True
    assert "observed output" in result.output["summary"]
    label = "source workspace" if failed_root == "source" else "tested tree"
    assert f"{label} could not be verified" in result.output["summary"]
    [receipt] = workspace.receipts()
    assert receipt.tree_changed is True


@pytest.mark.parametrize("reason", [None, "", " ", 2])
def test_refactoring_tools_require_explained_reason(tmp_path, reason):
    workspace = Workspace(tmp_path)
    workspace.write_file("old.py", "original\n")
    environment = LocalEnvironment(workspace)
    for tool, args in (("delete_file", {"path": "old.py"}),
                       ("move_file", {"source": "old.py", "destination": "new.py"})):
        result = perform(environment, tool, {**args, "reason": reason})
        assert result.ok is False
        assert "reason" in result.error
        assert workspace.read_file("old.py") == "original\n"


def test_refactoring_tools_move_and_delete_regular_files(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.write_file("old.py", "original\n")
    environment = LocalEnvironment(workspace)
    moved = perform(environment, "move_file", {
        "source": "old.py", "destination": "src/new.py", "reason": "organize module",
    })
    assert moved.ok and moved.output == {"source": "old.py", "destination": "src/new.py"}
    assert not (workspace.root / "old.py").exists()
    assert workspace.read_file("src/new.py") == "original\n"
    deleted = perform(environment, "delete_file", {
        "path": "src/new.py", "reason": "remove replaced module",
    })
    assert deleted.ok and deleted.output == "src/new.py"
    assert workspace.list_files() == []


