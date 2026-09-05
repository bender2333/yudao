import json
import os
import sys
import time

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
    assert result.ok is True
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


def test_product_cannot_write(tmp_path):
    runtime = ToolRuntime(Workspace(tmp_path))
    result = runtime.execute("product", "write_file", {"path": "src/echo.py", "content": "x"})
    assert result.ok is False


def test_smoke_exit_code_does_not_accept_fake_or_missing_evidence():
    from harness.smoke import smoke_exit_code

    assert smoke_exit_code({"available": False}) == 2
    done = {
        "phase": "DONE",
        "stop_reason": "released",
        "replay_consistent": True,
        "context_isolated": True,
        "check_receipts": [{"name": "smoke"}],
        "fake_used": False,
        "ask_count": 1,
    }
    assert smoke_exit_code({"available": True, "scenarios": {"happy": done, "ask": done}}) == 0
    fake = dict(done, fake_used=True)
    assert smoke_exit_code({"available": True, "scenarios": {"happy": fake}}) == 2
    no_receipts = dict(done, check_receipts=[])
    assert smoke_exit_code({"available": True, "scenarios": {"happy": no_receipts}}) == 1
