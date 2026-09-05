import sys

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
    assert "forged" not in text
    assert '"name":"smoke"' in text.replace(" ", "")
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
