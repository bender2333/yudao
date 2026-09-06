import json
import os
import sys
import time
from pathlib import Path

import pytest

from harness.tools import ToolRuntime
from harness.workspace import Workspace


def test_run_check_executes_host_process_and_ignores_self_reported_exit_code(tmp_path):
    workspace = Workspace(tmp_path)
    runtime = ToolRuntime(workspace)
    workspace.write_file("ok.py", "raise SystemExit(3)\n")
    result = runtime.execute(
        "engineering",
        "run_check",
        {"name": "smoke", "argv": ["python", "ok.py"], "exit_code": 0},
    )
    assert result.ok is True
    assert result.output["exit_code"] == 3
    assert result.output["executor"] == "host"
    receipt = workspace.snapshot().latest_check("engineering", "smoke")
    assert receipt is not None
    assert receipt.exit_code == 3
    assert "host-executed" in receipt.summary


def test_run_check_requires_command(tmp_path):
    runtime = ToolRuntime(Workspace(tmp_path))
    result = runtime.execute("engineering", "run_check", {"name": "smoke", "exit_code": 0})
    assert result.ok is False
    assert "argv" in (result.error or "") or "command" in (result.error or "")


def test_agent_cannot_read_or_write_checks(tmp_path):
    workspace = Workspace(tmp_path)
    runtime = ToolRuntime(workspace)
    written = runtime.execute(
        "engineering",
        "write_file",
        {"path": ".checks/receipts.jsonl", "content": "forged\n"},
    )
    assert written.ok is False
    read = runtime.execute("engineering", "read_file", {"path": ".checks/receipts.jsonl"})
    assert read.ok is False
    assert ".checks" not in runtime.execute("engineering", "list_files", {}).output


def test_check_cannot_persist_forged_receipt(tmp_path):
    workspace = Workspace(tmp_path)
    runtime = ToolRuntime(workspace)
    workspace.write_file(
        "forge.py",
        "from pathlib import Path\nPath('.checks/receipts.jsonl').write_text('forged\\n')\n",
    )
    result = runtime.execute("engineering", "run_check", {"name": "smoke", "argv": ["python", "forge.py"]})
    assert result.ok is True
    text = (tmp_path / ".checks" / "receipts.jsonl").read_text(encoding="utf-8")
    assert text.strip() != "forged"
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    assert rows
    assert all(row["name"] == "smoke" and row["department"] == "engineering" for row in rows)
    assert workspace.snapshot().latest_check("engineering", "smoke") is not None


def test_check_does_not_keep_workspace_mutations(tmp_path):
    workspace = Workspace(tmp_path)
    runtime = ToolRuntime(workspace)
    workspace.write_file("src/echo.py", "print('ok')\n")
    workspace.write_file("mutate.py", "from pathlib import Path\nPath('hacked.txt').write_text('x')\n")
    runtime.execute("quality", "run_check", {"name": "smoke", "argv": ["python", "mutate.py"]})
    assert "hacked.txt" not in workspace.list_files()
    assert workspace.read_file("src/echo.py") == "print('ok')\n"


def test_check_subprocess_does_not_inherit_provider_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("BLACKROUTER_API_KEY", "super-secret-value-123456")
    workspace = Workspace(tmp_path)
    runtime = ToolRuntime(workspace)
    workspace.write_file(
        "env.py",
        "import os, sys\n"
        "print('has' if os.environ.get('BLACKROUTER_API_KEY') else 'missing')\n"
        "raise SystemExit(0)\n",
    )
    result = runtime.execute("engineering", "run_check", {"name": "env", "argv": [sys.executable, "env.py"]})
    assert result.ok is True
    assert "missing" in result.output["summary"]
    assert "super-secret-value-123456" not in result.output["summary"]


def test_mutating_check_does_not_bind_pass_to_original_snapshot(tmp_path):
    workspace = Workspace(tmp_path)
    runtime = ToolRuntime(workspace)
    workspace.write_file("app.py", "BROKEN = True\n")
    workspace.write_file(
        "fix.py",
        "from pathlib import Path\n"
        "p = Path('app.py')\n"
        "p.write_text('FIXED = True\\n')\n"
        "assert 'FIXED' in p.read_text()\n",
    )
    original = workspace.digest()
    result = runtime.execute("engineering", "run_check", {"name": "smoke", "argv": ["python", "fix.py"]})
    assert result.ok is True
    assert result.output["exit_code"] == 0
    assert workspace.read_file("app.py") == "BROKEN = True\n"
    assert workspace.digest() == original
    assert result.output["snapshot_hash"] != original
    assert result.output["tree_changed"] is True
    assert workspace.snapshot().latest_check("engineering", "smoke") is None


def test_check_copy_does_not_follow_hardlink_into_external_file(tmp_path):
    workspace = Workspace(tmp_path / "ws")
    runtime = ToolRuntime(workspace)
    outside = tmp_path / "outside.txt"
    outside.write_text("EXTERNAL", encoding="utf-8")
    target = workspace.root / "target.txt"
    try:
        os.link(outside, target)
    except OSError:
        pytest.skip("hard links are not available")
    workspace.write_file("poke.py", "from pathlib import Path\nPath('target.txt').write_text('HACKED')\n")
    result = runtime.execute("engineering", "run_check", {"name": "smoke", "argv": ["python", "poke.py"]})
    assert result.ok is False
    assert "hard-linked" in result.error.lower()
    assert workspace.receipts() == []
    assert outside.read_text(encoding="utf-8") == "EXTERNAL"
    assert target.read_text(encoding="utf-8") != "HACKED"


def test_failed_check_records_real_exit_code(tmp_path):
    workspace = Workspace(tmp_path)
    runtime = ToolRuntime(workspace)
    workspace.write_file("fail.py", "raise SystemExit(7)\n")
    result = runtime.execute("engineering", "run_check", {"name": "smoke", "argv": ["python", "fail.py"]})
    assert result.ok is True
    assert result.output["exit_code"] == 7
    receipt = workspace.snapshot().latest_check("engineering", "smoke")
    assert receipt is not None
    assert receipt.exit_code == 7
    assert receipt.snapshot_hash == workspace.digest()


def test_timed_out_check_records_timeout_exit_code(tmp_path, monkeypatch):
    monkeypatch.setattr("harness.tools.CHECK_TIMEOUT_SEC", 1)
    workspace = Workspace(tmp_path)
    runtime = ToolRuntime(workspace)
    workspace.write_file("hang.py", "import time\ntime.sleep(30)\n")
    started = time.monotonic()
    result = runtime.execute("engineering", "run_check", {"name": "smoke", "argv": ["python", "hang.py"]})
    assert time.monotonic() - started < 10
    assert result.ok is True
    assert result.output["exit_code"] == 124
    receipt = workspace.snapshot().latest_check("engineering", "smoke")
    assert receipt is not None
    assert receipt.exit_code == 124
    assert "timed out" in receipt.summary


@pytest.fixture
def check_copy_base(tmp_path, monkeypatch):
    base = tmp_path / "check-copies"
    base.mkdir()
    monkeypatch.setattr("harness.workspace.tempfile.tempdir", str(base))
    return base


def test_missing_check_command_does_not_leave_a_copy(tmp_path, check_copy_base):
    workspace = Workspace(tmp_path / "workspace")
    runtime = ToolRuntime(workspace)
    workspace.write_file("ok.py", "print('ok')\n")
    result = runtime.execute("engineering", "run_check", {"name": "smoke", "argv": ["missing.py"]})
    assert result.ok is False
    assert "missing.py" in (result.error or "")
    assert list(check_copy_base.iterdir()) == []


def test_failed_check_copy_does_not_leave_a_copy(tmp_path, monkeypatch, check_copy_base):
    workspace = Workspace(tmp_path / "workspace")
    runtime = ToolRuntime(workspace)
    workspace.write_file("ok.py", "print('ok')\n")
    def fail_copy(tree, target):
        target.mkdir()
        raise OSError("copy failed")

    monkeypatch.setattr("harness.workspace.materialize_tree", fail_copy)
    result = runtime.execute("engineering", "run_check", {"name": "smoke", "argv": ["python", "ok.py"]})
    assert result.ok is False
    assert "copy failed" in (result.error or "")
    assert list(check_copy_base.iterdir()) == []


def test_successful_and_failed_checks_do_not_leave_copies(tmp_path, check_copy_base):
    workspace = Workspace(tmp_path / "workspace")
    runtime = ToolRuntime(workspace)
    workspace.write_file("ok.py", "print('ok')\n")
    workspace.write_file("fail.py", "raise SystemExit(7)\n")
    with workspace.check_copy(workspace.snapshot().tree) as copy_root:
        assert copy_root.parent.parent == check_copy_base
        assert not copy_root.is_relative_to(workspace.root)
    ok = runtime.execute("engineering", "run_check", {"name": "ok", "argv": ["python", "ok.py"]})
    failed = runtime.execute("engineering", "run_check", {"name": "fail", "argv": ["python", "fail.py"]})
    assert ok.ok is True
    assert ok.output["exit_code"] == 0
    assert failed.ok is True
    assert failed.output["exit_code"] == 7
    assert workspace.read_file("ok.py") == "print('ok')\n"
    assert list(check_copy_base.iterdir()) == []


def test_product_cannot_write(tmp_path):
    runtime = ToolRuntime(Workspace(tmp_path))
    result = runtime.execute("product", "write_file", {"path": "src/echo.py", "content": "x"})
    assert result.ok is False


def test_module_import_check_preserves_complete_tree(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.write_file("helper.py", "VALUE = 42\n")
    workspace.write_file("main.py", "from helper import VALUE\nprint(VALUE)\nassert VALUE == 42\n")
    result = ToolRuntime(workspace).execute("engineering", "run_check", {
        "name": "imports", "argv": ["python", "main.py"],
    })
    assert result.ok and result.output["exit_code"] == 0
    assert result.output["tree_changed"] is False
    assert "42" in result.output["summary"]
    assert workspace.snapshot().latest_check("engineering", "imports") is not None
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


def test_check_records_source_workspace_change(tmp_path, monkeypatch):
    import harness.tools as tools

    workspace = Workspace(tmp_path)
    workspace.write_file("app.py", "print('checked original')\nraise SystemExit(7)\n")
    run = tools.subprocess.run

    def execute(*args, **kwargs):
        result = run(*args, **kwargs)
        workspace.write_file("app.py", "changed after the check\n")
        return result

    monkeypatch.setattr(tools.subprocess, "run", execute)
    result = ToolRuntime(workspace).execute("engineering", "run_check", {
        "name": "source", "argv": ["python", "app.py"],
    })
    assert result.ok and result.output["exit_code"] == 7
    assert result.output["tree_changed"] is True
    assert "checked original" in result.output["summary"]
    assert "source workspace changed" in result.output["summary"]
    assert len(workspace.receipts()) == 1
    assert workspace.snapshot().latest_check("engineering", "source") is None


@pytest.mark.parametrize("failed_root", ["copy", "source"])
def test_check_keeps_process_evidence_when_postcheck_capture_fails(tmp_path, monkeypatch, failed_root):
    import harness.tools as tools

    workspace = Workspace(tmp_path)
    workspace.write_file("app.py", "print('observed output')\nraise SystemExit(9)\n")
    capture = tools.capture_public_tree

    def verify(root):
        if (root == workspace.root) == (failed_root == "source"):
            raise OSError("tree read failed")
        return capture(root)

    monkeypatch.setattr(tools, "capture_public_tree", verify)
    result = ToolRuntime(workspace).execute("engineering", "run_check", {
        "name": "unverified", "argv": ["python", "app.py"],
    })
    assert result.ok and result.output["exit_code"] == 9
    assert result.output["tree_changed"] is True
    assert "observed output" in result.output["summary"]
    assert "could not be verified: tree read failed" in result.output["summary"]
    assert len(workspace.receipts()) == 1
    assert workspace.snapshot().latest_check("engineering", "unverified") is None


@pytest.mark.parametrize("department", ["product", "quality"])
@pytest.mark.parametrize("tool,args", [
    ("delete_file", {"path": "old.py", "reason": "remove replaced implementation"}),
    ("move_file", {"source": "old.py", "destination": "new.py", "reason": "organize module"}),
])
def test_refactoring_tools_require_engineering(tmp_path, department, tool, args):
    workspace = Workspace(tmp_path)
    workspace.write_file("old.py", "original\n")
    result = ToolRuntime(workspace).execute(department, tool, args)
    assert result.ok is False
    assert workspace.read_file("old.py") == "original\n"
    assert not (workspace.root / "new.py").exists()


@pytest.mark.parametrize("reason", [None, "", " ", 2])
def test_refactoring_tools_require_explained_reason(tmp_path, reason):
    workspace = Workspace(tmp_path)
    workspace.write_file("old.py", "original\n")
    runtime = ToolRuntime(workspace)
    for tool, args in (("delete_file", {"path": "old.py"}),
                       ("move_file", {"source": "old.py", "destination": "new.py"})):
        result = runtime.execute("engineering", tool, {**args, "reason": reason})
        assert result.ok is False
        assert "reason" in result.error
        assert workspace.read_file("old.py") == "original\n"


def test_refactoring_tools_move_and_delete_regular_files(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.write_file("old.py", "original\n")
    runtime = ToolRuntime(workspace)
    moved = runtime.execute("engineering", "move_file", {
        "source": "old.py", "destination": "src/new.py", "reason": "organize module",
    })
    assert moved.ok and moved.output == {"source": "old.py", "destination": "src/new.py"}
    assert not (workspace.root / "old.py").exists()
    assert workspace.read_file("src/new.py") == "original\n"
    deleted = runtime.execute("engineering", "delete_file", {
        "path": "src/new.py", "reason": "remove replaced module",
    })
    assert deleted.ok and deleted.output == "src/new.py"
    assert workspace.list_files() == []


def test_smoke_exit_code_does_not_accept_fake_or_missing_evidence():
    from harness.smoke import smoke_exit_code

    assert smoke_exit_code({"available": False}) == 2
    done = {
        "phase": "DONE",
        "stop_reason": "released",
        "replay_consistent": True,
        "context_isolated": True,
        "model_input_audit": {"status": "verified"},
        "check_receipts": [{"name": "smoke"}],
        "check_receipts_verified": True,
        "delivery_archive": {"status": "verified"},
        "fake_used": False,
        "request_count": 2,
        "collaboration_audit": {"status": "verified", "pre_spec_consultation": True, "requirements_action": True},
    }
    assert smoke_exit_code({"available": True, "scenarios": {"happy": done, "collaboration": done}}) == 0
    fake = dict(done, fake_used=True)
    assert smoke_exit_code({"available": True, "scenarios": {"happy": fake}}) == 2
    no_receipts = dict(done, check_receipts=[])
    assert smoke_exit_code({"available": True, "scenarios": {"happy": no_receipts}}) == 1
