from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import harness.supervisor as supervisor_module


from harness.supervisor import SupervisorResult, main, supervise_command


def _valid_summary(treatment: str = "S") -> dict:
    return {
        "treatment": treatment,
        "outcome": "done",
        "stopped_reason": "completed" if treatment == "S" else "done",
    }


def _command(run_dir: Path, *, summary: str | None = None, returncode: int = 0) -> list[str]:
    script = "import pathlib,sys; p=pathlib.Path(sys.argv[1]); p.mkdir();"
    if summary is not None:
        script += "(p/'summary.json').write_text(sys.argv[2],encoding='utf-8');"
    script += "sys.stdout.write('stdout evidence');sys.stderr.write('stderr evidence');"
    script += f"raise SystemExit({returncode})"
    argv = [sys.executable, "-c", script, str(run_dir)]
    if summary is not None:
        argv.append(summary)
    return argv


def _read_record(run_dir: Path) -> dict:
    return json.loads((run_dir / "supervisor.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("treatment", ["S", "T"])
def test_completed_requires_treatment_specific_runner_summary(
    tmp_path: Path, treatment: str
) -> None:
    run_dir = tmp_path / "run"
    summary = _valid_summary(treatment)

    result = supervise_command(
        _command(run_dir, summary=json.dumps(summary)),
        run_dir=run_dir,
        timeout_seconds=5,
        env=os.environ.copy(),
    )

    assert result == SupervisorResult(0, False, "completed", result.duration_ms, summary)
    assert _read_record(run_dir) == {"schema_version": 1, **result.__dict__}
    assert not (run_dir / "supervisor.json.tmp").exists()
    assert not (run_dir / "supervisor.stdout.log").exists()
    assert not (run_dir / "supervisor.stderr.log").exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["run"]


@pytest.mark.parametrize(
    "summary",
    [
        {"ok": True},
        {"outcome": "done"},
        {"treatment": {}, "outcome": "done", "stopped_reason": "completed"},
        {"treatment": "X", "outcome": "done", "stopped_reason": "completed"},
        {"treatment": "S", "outcome": "failed", "stopped_reason": "completed"},
        {"treatment": "S", "outcome": "done", "stopped_reason": "done"},
        {"treatment": "T", "outcome": "done", "stopped_reason": "completed"},
    ],
)
def test_false_completion_is_process_failed_and_preserves_summary(
    tmp_path: Path, summary: dict
) -> None:
    run_dir = tmp_path / "run"

    result = supervise_command(
        _command(run_dir, summary=json.dumps(summary)),
        run_dir=run_dir,
        timeout_seconds=5,
        env=os.environ.copy(),
    )

    assert result.stop_reason == "process_failed"
    assert result.returncode == 0
    assert result.summary == summary
    assert _read_record(run_dir)["summary"] == summary
    assert (run_dir / "supervisor.stderr.log").read_text(encoding="utf-8") == "stderr evidence"


@pytest.mark.parametrize("leaf_kind", ["file", "symlink"])
def test_child_supervisor_leaves_are_quarantined_before_authoritative_write(
    tmp_path: Path, leaf_kind: str
) -> None:
    run_dir = tmp_path / "run"
    outside = tmp_path / "outside"
    outside.write_text("victim", encoding="utf-8")
    summary = json.dumps(_valid_summary())
    child = (
        "import os,pathlib,sys;p=pathlib.Path(sys.argv[1]);p.mkdir();"
        "(p/'summary.json').write_text(sys.argv[2],encoding='utf-8');"
        "[(os.symlink(sys.argv[3],p/n) if sys.argv[4]=='symlink' else (p/n).write_text('{}',encoding='utf-8')) "
        "for n in ('supervisor.json','supervisor.json.tmp')]"
    )

    result = supervise_command(
        [sys.executable, "-c", child, str(run_dir), summary, str(outside), leaf_kind],
        run_dir=run_dir,
        timeout_seconds=5,
        env=os.environ.copy(),
    )

    assert result.stop_reason == "completed"
    assert _read_record(run_dir) == {"schema_version": 1, **result.__dict__}
    quarantines = list(run_dir.glob(".supervisor.json*.child-*"))
    assert len(quarantines) == 2
    assert outside.read_text(encoding="utf-8") == "victim"


def test_child_log_targets_are_quarantined_before_failure_logs(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    outside = tmp_path / "outside"
    outside.write_text("victim", encoding="utf-8")
    child = (
        "import os,pathlib,sys;p=pathlib.Path(sys.argv[1]);p.mkdir();"
        "os.symlink(sys.argv[2],p/'supervisor.stdout.log');"
        "(p/'supervisor.stderr.log').write_text('child',encoding='utf-8');"
        "sys.stdout.write('stdout evidence');sys.stderr.write('stderr evidence');raise SystemExit(7)"
    )

    result = supervise_command(
        [sys.executable, "-c", child, str(run_dir), str(outside)],
        run_dir=run_dir,
        timeout_seconds=5,
        env=os.environ.copy(),
    )

    assert result.stop_reason == "process_failed"
    assert (run_dir / "supervisor.stdout.log").read_text(encoding="utf-8") == "stdout evidence"
    assert (run_dir / "supervisor.stderr.log").read_text(encoding="utf-8") == "stderr evidence"
    assert len(list(run_dir.glob(".supervisor.*.log.child-*"))) == 2
    assert outside.read_text(encoding="utf-8") == "victim"


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
    assert (run_dir / "supervisor.stdout.log").read_text(encoding="utf-8") == "stdout evidence"
    assert (run_dir / "supervisor.stderr.log").read_text(encoding="utf-8") == "stderr evidence"


def test_oversize_summary_is_invalid_without_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"
    script = (
        "import pathlib,sys;p=pathlib.Path(sys.argv[1]);p.mkdir();"
        "(p/'summary.json').write_text('{\\\"padding\\\":\\\"'+'x'*(2*1024*1024)+'\\\"}',encoding='utf-8')"
    )
    loads = supervisor_module.json.loads
    calls = 0

    def spy(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return loads(*args, **kwargs)

    monkeypatch.setattr(supervisor_module.json, "loads", spy)
    result = supervise_command(
        [sys.executable, "-c", script, str(run_dir)],
        run_dir=run_dir,
        timeout_seconds=20,
        env=os.environ.copy(),
    )
    assert result.stop_reason == "summary_invalid"
    assert calls == 0


def test_summary_with_more_than_100000_nodes_is_invalid(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    script = (
        "import pathlib,sys;p=pathlib.Path(sys.argv[1]);p.mkdir();"
        "(p/'summary.json').write_text('{\\\"items\\\":['+'[],'*100000+'[]]}',encoding='utf-8')"
    )
    result = supervise_command(
        [sys.executable, "-c", script, str(run_dir)],
        run_dir=run_dir,
        timeout_seconds=20,
        env=os.environ.copy(),
    )
    assert result.stop_reason == "summary_invalid"


def test_infrastructure_failure_is_sanitized_and_preserves_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "run"

    def fail(*_args: object, **kwargs: object) -> object:
        Path(kwargs["stdout_path"]).write_text("stdout evidence", encoding="utf-8")  # type: ignore[arg-type]
        Path(kwargs["stderr_path"]).write_text("SECRET stderr", encoding="utf-8")  # type: ignore[arg-type]
        raise FileNotFoundError("SECRET")

    monkeypatch.setattr(supervisor_module, "run_process_tree", fail)
    result = supervise_command(
        [sys.executable, "-c", "pass"],
        run_dir=run_dir,
        timeout_seconds=5,
        env={},
    )

    assert result == SupervisorResult(
        None,
        False,
        "supervisor_error",
        result.duration_ms,
        {"error_type": "FileNotFoundError"},
    )
    record_text = (run_dir / "supervisor.json").read_text(encoding="utf-8")
    assert "SECRET" not in record_text
    assert json.loads(record_text) == {"schema_version": 1, **result.__dict__}
    assert (run_dir / "supervisor.stdout.log").read_text(encoding="utf-8") == "stdout evidence"
    assert (run_dir / "supervisor.stderr.log").read_text(encoding="utf-8") == "SECRET stderr"


@pytest.mark.parametrize("leaf_kind", ["file", "symlink", "junction"])
def test_invalid_child_run_leaf_is_quarantined_and_recorded(
    tmp_path: Path, leaf_kind: str
) -> None:
    run_dir = tmp_path / "run"
    outside = tmp_path / "outside"
    outside.mkdir()
    if leaf_kind == "file":
        child = "import pathlib,sys;pathlib.Path(sys.argv[1]).write_text('evidence',encoding='utf-8')"
    elif leaf_kind == "symlink":
        child = "import os,sys;os.symlink(sys.argv[2],sys.argv[1],target_is_directory=True)"
    else:
        child = (
            "import subprocess,sys;subprocess.run(['cmd','/c','mklink','/J',sys.argv[1],sys.argv[2]],"
            "check=True,stdout=subprocess.DEVNULL)"
        )

    result = supervise_command(
        [sys.executable, "-c", child, str(run_dir), str(outside)],
        run_dir=run_dir,
        timeout_seconds=5,
        env=os.environ.copy(),
    )

    assert result.stop_reason == "supervisor_error"
    assert result.summary == {"error_type": "InvalidRunDirectory"}
    assert _read_record(run_dir)["stop_reason"] == "supervisor_error"
    quarantine = list(tmp_path.glob(".run.invalid-*"))
    assert len(quarantine) == 1
    if leaf_kind == "file":
        assert quarantine[0].read_text(encoding="utf-8") == "evidence"
    else:
        assert os.path.islink(quarantine[0]) or getattr(os.path, "isjunction")(quarantine[0])
    assert not (outside / "supervisor.json").exists()


def test_rejects_linked_run_dir_ancestor_before_launch(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    sentinel = tmp_path / "executed"
    script = "import pathlib,sys;pathlib.Path(sys.argv[1]).write_text('bad',encoding='utf-8')"

    with pytest.raises(ValueError, match="link"):
        supervise_command(
            [sys.executable, "-c", script, str(sentinel)],
            run_dir=linked / "run",
            timeout_seconds=5,
            env=os.environ.copy(),
        )

    assert not sentinel.exists()
    assert not (outside / "run").exists()


@pytest.mark.parametrize(
    "summary",
    [
        '{"nested":{"value":NaN}}',
        '{"nested":[Infinity]}',
        '{"nested":' + "[" * 2000 + "0" + "]" * 2000 + "}",
    ],
    ids=["nested-nan", "nested-infinity", "deep-list"],
)
def test_non_strict_or_deep_summary_is_invalid(tmp_path: Path, summary: str) -> None:
    run_dir = tmp_path / "run"
    result = supervise_command(
        _command(run_dir, summary=summary),
        run_dir=run_dir,
        timeout_seconds=5,
        env=os.environ.copy(),
    )

    assert result.stop_reason == "summary_invalid"
    json.loads(
        (run_dir / "supervisor.json").read_text(encoding="utf-8"),
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )


def test_timeout_kills_ready_descendant_and_records_failure(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    ready = tmp_path / "child-ready.txt"
    sentinel = tmp_path / "child-survived.txt"
    child = (
        "import os,pathlib,sys,time;"
        "p=pathlib.Path(sys.argv[1]);t=p.with_suffix('.tmp');"
        "t.write_text('ready',encoding='utf-8');os.replace(t,p);"
        "time.sleep(3);pathlib.Path(sys.argv[2]).write_text('bad',encoding='utf-8')"
    )
    parent = (
        "import pathlib,subprocess,sys,time;pathlib.Path(sys.argv[1]).mkdir();"
        "subprocess.Popen([sys.executable,'-c',sys.argv[4],sys.argv[2],sys.argv[3]]);"
        "limit=time.monotonic()+5;"
        "exec(\"while not pathlib.Path(sys.argv[2]).exists():\\n"
        " if time.monotonic()>limit: raise SystemExit(9)\\n time.sleep(.01)\");"
        "time.sleep(60)"
    )

    result = supervise_command(
        [sys.executable, "-c", parent, str(run_dir), str(ready), str(sentinel), child],
        run_dir=run_dir,
        timeout_seconds=2,
        env=os.environ.copy(),
    )

    assert ready.exists()
    time.sleep(3.2)
    assert result.timed_out is True
    assert result.stop_reason == "hard_timeout"
    assert result.summary is None
    assert not sentinel.exists()
    assert _read_record(run_dir)["stop_reason"] == "hard_timeout"
    assert (run_dir / "supervisor.stdout.log").exists()
    assert (run_dir / "supervisor.stderr.log").exists()


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


def test_main_false_completion_exits_one(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake(*_args: object, **_kwargs: object) -> SupervisorResult:
        return SupervisorResult(0, False, "process_failed", 1, {"outcome": "failed"})

    monkeypatch.setattr("harness.supervisor.supervise_command", fake)
    exit_code = main([
        "solo", "task", "--task-id", "S1", "--run-dir", str(tmp_path / "run"),
        "--seed-dir", "seed", "--checks-file", "checks.json",
    ])
    assert exit_code == 1


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
