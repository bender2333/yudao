from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from harness.supervisor import SupervisorResult, main, supervise_command


def _command(run_dir: Path, *, summary: str | None = None, returncode: int = 0) -> list[str]:
    script = "import pathlib,sys; p=pathlib.Path(sys.argv[1]); p.mkdir();"
    if summary is not None:
        script += "(p/'summary.json').write_text(sys.argv[2],encoding='utf-8');"
    script += f"raise SystemExit({returncode})"
    argv = [sys.executable, "-c", script, str(run_dir)]
    if summary is not None:
        argv.append(summary)
    return argv


def _read_record(run_dir: Path) -> dict:
    return json.loads((run_dir / "supervisor.json").read_text(encoding="utf-8"))


def test_completed_reads_object_summary_and_writes_atomic_record(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    summary = {"outcome": "done", "value": [1, "two"]}

    result = supervise_command(
        _command(run_dir, summary=json.dumps(summary)),
        run_dir=run_dir,
        timeout_seconds=5,
        env=os.environ.copy(),
    )

    assert result == SupervisorResult(0, False, "completed", result.duration_ms, summary)
    assert _read_record(run_dir) == {
        "schema_version": 1,
        "returncode": 0,
        "timed_out": False,
        "stop_reason": "completed",
        "duration_ms": result.duration_ms,
        "summary": summary,
    }
    assert not (run_dir / "supervisor.json.tmp").exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["run"]


@pytest.mark.parametrize(
    ("summary", "returncode", "reason"),
    [
        (None, 0, "summary_missing"),
        ('{"partial":', 0, "summary_invalid"),
        ("1", 0, "summary_invalid"),
        ("[]", 0, "summary_invalid"),
        ('{"ignored":true}', 7, "process_failed"),
    ],
)
def test_failure_classification_is_recorded(
    tmp_path: Path, summary: str | None, returncode: int, reason: str
) -> None:
    run_dir = tmp_path / "run"

    result = supervise_command(
        _command(run_dir, summary=summary, returncode=returncode),
        run_dir=run_dir,
        timeout_seconds=5,
        env=os.environ.copy(),
    )

    assert result.stop_reason == reason
    assert result.summary is None
    assert _read_record(run_dir)["stop_reason"] == reason
    assert _read_record(run_dir)["summary"] is None


def test_oversize_summary_is_invalid(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    script = (
        "import pathlib,sys;p=pathlib.Path(sys.argv[1]);p.mkdir();"
        "(p/'summary.json').write_bytes(b'x'*(16*1024*1024+1))"
    )
    result = supervise_command(
        [sys.executable, "-c", script, str(run_dir)],
        run_dir=run_dir,
        timeout_seconds=20,
        env=os.environ.copy(),
    )
    assert result.stop_reason == "summary_invalid"


def test_timeout_kills_descendants_and_records_failure(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    sentinel = tmp_path / "child-survived.txt"
    child = (
        "import time,pathlib,sys;time.sleep(1);"
        "pathlib.Path(sys.argv[1]).write_text('bad',encoding='utf-8')"
    )
    parent = (
        "import pathlib,subprocess,sys,time;pathlib.Path(sys.argv[1]).mkdir();"
        "subprocess.Popen([sys.executable,'-c',sys.argv[3],sys.argv[2]]);time.sleep(60)"
    )

    result = supervise_command(
        [sys.executable, "-c", parent, str(run_dir), str(sentinel), child],
        run_dir=run_dir,
        timeout_seconds=0.2,
        env=os.environ.copy(),
    )

    time.sleep(1.2)
    assert result.timed_out is True
    assert result.stop_reason == "hard_timeout"
    assert result.summary is None
    assert not sentinel.exists()
    assert _read_record(run_dir)["stop_reason"] == "hard_timeout"


@pytest.mark.parametrize(
    ("argv", "run_dir", "timeout", "env"),
    [
        (("python",), Path("run"), 1, {}),
        ([], Path("run"), 1, {}),
        ([""], Path("run"), 1, {}),
        (["a\0b"], Path("run"), 1, {}),
        (["python"], "run", 1, {}),
        (["python"], Path("run"), True, {}),
        (["python"], Path("run"), float("inf"), {}),
        (["python"], Path("run"), 0, {}),
        (["python"], Path("run"), 1, []),
        (["python"], Path("run"), 1, {1: "x"}),
        (["python"], Path("run"), 1, {"X": "a\0b"}),
    ],
)
def test_rejects_invalid_low_level_inputs(
    tmp_path: Path, argv: object, run_dir: object, timeout: object, env: object
) -> None:
    actual_run_dir = tmp_path / run_dir if isinstance(run_dir, Path) else run_dir
    with pytest.raises((TypeError, ValueError)):
        supervise_command(argv, run_dir=actual_run_dir, timeout_seconds=timeout, env=env)  # type: ignore[arg-type]


def test_rejects_existing_run_dir(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with pytest.raises(FileExistsError):
        supervise_command([sys.executable, "-c", "pass"], run_dir=run_dir, timeout_seconds=1, env={})


def test_main_builds_only_selected_runner_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[tuple[list[str], Path, float, dict[str, str]]] = []

    def fake(argv: list[str], *, run_dir: Path, timeout_seconds: float, env: dict[str, str]) -> SupervisorResult:
        calls.append((argv, run_dir, timeout_seconds, env))
        return SupervisorResult(0, False, "completed", 12, {"ok": True})

    monkeypatch.setattr("harness.supervisor.supervise_command", fake)
    run_dir = tmp_path / "run"
    exit_code = main([
        "team", "do it", "--task-id", "T1", "--run-dir", str(run_dir),
        "--seed-dir", "seed", "--checks-file", "checks.json", "--max-reworks", "4",
        "--max-steps", "30", "--max-calls", "40", "--max-tokens", "500",
        "--max-seconds", "60", "--provider-path", "provider.md", "--hard-timeout", "70",
    ])

    assert exit_code == 0
    assert calls[0][0] == [
        sys.executable, "-m", "harness.run_team", "do it", "--task-id", "T1",
        "--run-dir", str(run_dir), "--seed-dir", "seed", "--checks-file", "checks.json",
        "--max-steps", "30", "--max-calls", "40", "--max-tokens", "500",
        "--max-seconds", "60.0", "--provider-path", "provider.md", "--max-reworks", "4",
    ]
    assert calls[0][1:3] == (run_dir, 70.0)
    assert "PYTHONUTF8" in calls[0][3]
    assert json.loads(capsys.readouterr().out)["stop_reason"] == "completed"


def test_main_solo_failure_exits_one(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: list[list[str]] = []

    def fake(argv: list[str], **_: object) -> SupervisorResult:
        captured.append(argv)
        return SupervisorResult(2, False, "process_failed", 1, None)

    monkeypatch.setattr("harness.supervisor.supervise_command", fake)
    exit_code = main([
        "solo", "task", "--task-id", "S1", "--run-dir", str(tmp_path / "run"),
        "--seed-dir", "seed", "--checks-file", "checks.json",
    ])
    assert exit_code == 1
    assert captured[0][2:4] == ["harness.run_solo", "task"]
    assert "--max-reworks" not in captured[0]
