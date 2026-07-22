from __future__ import annotations

import inspect
import json
import math
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.artifacts import EventWriter, write_json_atomic
from harness.contracts import verify_ticket
from harness.run_solo import run_solo
from harness.run_team import run_team_cli

from harness.runner_common import RunnerSetup, finalize_artifacts

FAKE_KEY = "sk-runner-secret"


def _call(call_id, name, arguments):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def _response(calls, *, usage=True):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="", tool_calls=calls),
                finish_reason="tool_calls",
            )
        ],
        usage=(
            SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                completion_tokens_details=SimpleNamespace(reasoning_tokens=2),
            )
            if usage
            else None
        ),
    )


class _Completions:
    def __init__(self, responses):
        self.responses = list(responses)

    def create(self, **_kwargs):
        return self.responses.pop(0)


def _client(responses):
    return SimpleNamespace(
        chat=SimpleNamespace(completions=_Completions(responses))
    )


def _acceptance():
    return {
        "summary": "implement VALUE",
        "requirements": [
            {"id": "R-001", "behavior": "write VALUE=42", "evidence": "public_tests"}
        ],
        "edge_cases": [
            {"id": "E-001", "behavior": "imports", "evidence": "public_tests"}
        ],
        "regressions_to_avoid": [
            {"id": "G-001", "behavior": "keep files", "evidence": "public_tests"}
        ],
        "fatal_conditions": [
            {"id": "F-001", "behavior": "tests unchanged", "evidence": "tree"}
        ],
        "constraints": ["stdlib"],
        "non_goals": ["none"],
        "clarification_responses": [],
    }


def _delivery():
    return {
        "changed_files": ["answer.py"],
        "requirement_mapping": [{"requirement_id": "R-001", "files": ["answer.py"]}],
        "check_names": ["public_tests"],
        "known_risks": [],
    }


def _release():
    return {
        "verified_requirements": ["R-001", "E-001", "G-001", "F-001"],
        "check_names": ["public_tests"],
        "closed_defects": [],
        "decision": "release",
    }


def _done():
    return {"changed_files": ["answer.py"], "check_names": ["public_tests"], "known_risks": []}


def _inputs(tmp_path):
    seed = tmp_path / "seed"
    seed.mkdir()
    checks = tmp_path / "checks-manifest.json"
    checks.write_text(
        json.dumps(
            {
                "protected_paths": [],
                "checks": {
                    "public_tests": {
                        "argv": [sys.executable, "-c", "import answer; assert answer.VALUE == 42"],
                        "timeout_seconds": 5,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return seed, checks


def _provider(tmp_path):
    path = tmp_path / "provider.md"
    path.write_text("key: fake\nurl: https://provider.invalid\nmodel: test-model\n", encoding="utf-8")
    return path


def _patch_provider(monkeypatch, module, responses):
    monkeypatch.setattr(module, "load_provider", lambda _path: {
        "key": FAKE_KEY,
        "url": "https://provider.invalid",
        "model": "test-model",
    })
    monkeypatch.setattr(module, "make_client", lambda _cfg: _client(responses))


def _jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _assert_common(run_dir, summary, treatment, roles):
    assert json.loads((run_dir / "summary.json").read_text(encoding="utf-8")) == summary
    assert summary["schema_version"] == 1
    assert summary["treatment"] == treatment
    assert set(summary["per_role"]) == set(roles)
    assert summary["calls"] == sum(item["calls"] for item in summary["per_role"].values())
    events = _jsonl(run_dir / "events.jsonl")
    assert summary["calls"] == sum(event["type"] == "llm_call" for event in events)
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert summary["final_tree"] == json.loads((run_dir / "final_tree.json").read_text(encoding="utf-8"))
    assert (run_dir / "checks").is_dir()
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in run_dir.rglob("*")
        if path.is_file()
    )
    assert FAKE_KEY not in text
    assert "checks-manifest.json" not in text
    assert "judge/" not in text


def test_fixed_runner_signatures():
    assert str(inspect.signature(run_team_cli)) == "(task: 'str', task_id: 'str', run_dir: 'str', seed_dir: 'str', checks_file: 'str', max_steps: 'int' = 40, max_reworks: 'int' = 8, max_calls: 'int' = 200, max_tokens: 'int | None' = None, max_seconds: 'float' = 5400, provider_path: 'str' = 'provider.md') -> 'dict'"
    assert str(inspect.signature(run_solo)) == "(task: 'str', task_id: 'str', run_dir: 'str', seed_dir: 'str', checks_file: 'str', max_steps: 'int' = 200, max_calls: 'int' = 200, max_tokens: 'int | None' = None, max_seconds: 'float' = 5400, provider_path: 'str' = 'provider.md') -> 'dict'"


def test_existing_run_dir_fails_before_provider_load(tmp_path, monkeypatch):
    import harness.run_solo as solo_module
    import harness.run_team as team_module

    existing = tmp_path / "existing"
    existing.mkdir()
    called = []
    monkeypatch.setattr(solo_module, "load_provider", lambda _path: called.append("solo"))
    monkeypatch.setattr(team_module, "load_provider", lambda _path: called.append("team"))
    seed, checks = _inputs(tmp_path)

    for runner in (run_solo, run_team_cli):
        with pytest.raises(FileExistsError):
            runner("task", "task-1", str(existing), str(seed), str(checks))
    assert called == []


def test_solo_offline_done_writes_complete_artifacts(tmp_path, monkeypatch):
    import harness.run_solo as module

    seed, checks = _inputs(tmp_path)
    _patch_provider(
        monkeypatch,
        module,
        [
            _response(
                [
                    _call("w", "write_file", {"path": "answer.py", "content": "VALUE = 42\n"}),
                    _call("c", "run_check", {"name": "public_tests"}),
                    _call("d", "submit_done", _done()),
                ]
            )
        ],
    )
    run_dir = tmp_path / "solo"

    summary = run_solo("implement VALUE", "task-1", str(run_dir), str(seed), str(checks), provider_path=str(_provider(tmp_path)))

    assert summary["outcome"] == "done"
    assert summary["completion"]["kind"] == "solo_done"
    assert {path.name for path in (run_dir / "sessions").iterdir()} == {"solo.jsonl"}
    assert list((run_dir / "tickets").iterdir()) == []
    _assert_common(run_dir, summary, "S", ["solo"])


def test_team_offline_done_writes_complete_artifacts(tmp_path, monkeypatch):
    import harness.run_team as module

    seed, checks = _inputs(tmp_path)
    _patch_provider(
        monkeypatch,
        module,
        [
            _response([_call("a", "submit_acceptance", _acceptance())]),
            _response(
                [
                    _call("w", "write_file", {"path": "answer.py", "content": "VALUE = 42\n"}),
                    _call("c1", "run_check", {"name": "public_tests"}),
                    _call("d", "submit_delivery", _delivery()),
                ]
            ),
            _response(
                [
                    _call("c2", "run_check", {"name": "public_tests"}),
                    _call("r", "submit_release", _release()),
                ]
            ),
        ],
    )
    run_dir = tmp_path / "team"

    summary = run_team_cli("implement VALUE", "task-1", str(run_dir), str(seed), str(checks), provider_path=str(_provider(tmp_path)))

    assert summary["outcome"] == "done"
    assert summary["tickets"] == ["A-0001", "L-0001", "R-0001"]
    assert {path.name for path in (run_dir / "sessions").iterdir()} == {
        "requirements.jsonl", "engineering.jsonl", "quality.jsonl"
    }
    for ticket_id in summary["tickets"]:
        ticket = json.loads((run_dir / "tickets" / f"{ticket_id}.json").read_text(encoding="utf-8"))
        verify_ticket(ticket)
    _assert_common(run_dir, summary, "T", ["requirements", "engineering", "quality"])


def test_atomic_writers_reject_stale_files_and_control_sequence(tmp_path):
    target = tmp_path / "value.json"
    target.write_text("old", encoding="utf-8")
    stale = tmp_path / "value.json.tmp"
    stale.write_text("stale", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_json_atomic(target, {"new": True})
    assert target.read_text(encoding="utf-8") == "old"
    assert stale.read_text(encoding="utf-8") == "stale"

    events = tmp_path / "events.jsonl"
    writer = EventWriter(events)
    writer.append({"type": "x", "seq": 999})
    writer.close()
    writer.close()
    assert _jsonl(events) == [{"type": "x", "seq": 1}]


def test_event_writer_commits_sequence_only_after_serialized_flushed_write(tmp_path):
    events = tmp_path / "events.jsonl"
    writer = EventWriter(events)
    with pytest.raises(TypeError):
        writer.append({"type": "bad", "value": object()})
    writer.append({"type": "ok"})
    writer.close()
    assert _jsonl(events) == [{"type": "ok", "seq": 1}]
    with pytest.raises(RuntimeError, match="^event writer is closed$"):
        writer.append({"type": "late"})


def test_event_writer_flush_failure_permanently_poisons_stream(tmp_path):
    class FailingFlush:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.fail = True

        def write(self, line):
            return self.wrapped.write(line)

        def flush(self):
            if self.fail:
                self.fail = False
                raise OSError("flush failed")
            return self.wrapped.flush()

        def fileno(self):
            return self.wrapped.fileno()

        def close(self):
            return self.wrapped.close()

    events = tmp_path / "events.jsonl"
    writer = EventWriter(events)
    writer._file = FailingFlush(writer._file)
    with pytest.raises(OSError, match="flush failed"):
        writer.append({"type": "failed"})
    assert writer.failed
    with pytest.raises(RuntimeError, match="^event writer failed$"):
        writer.append({"type": "second"})
    writer.close()
    writer.close()

    rows = _jsonl(events)
    assert len(rows) <= 1
    assert [row["seq"] for row in rows] == list(range(1, len(rows) + 1))
    assert all(row["type"] != "second" for row in rows)


def test_event_writer_close_fsyncs_closes_and_preserves_fsync_error(tmp_path, monkeypatch):
    events = tmp_path / "events.jsonl"
    writer = EventWriter(events)
    writer.append({"type": "ok"})
    closed = []
    original_close = writer._file.close
    monkeypatch.setattr(os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("fsync failed")))
    writer._file.close = lambda: (closed.append(True), original_close())[1]
    with pytest.raises(OSError, match="fsync failed"):
        writer.close()
    assert closed == [True]
    writer.close()


@pytest.mark.parametrize("runner_name", ["solo", "team"])
def test_event_flush_failure_escapes_runner_without_summary(tmp_path, monkeypatch, runner_name):
    import harness.run_solo as solo_module
    import harness.run_team as team_module

    class FailingFlush:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.fail = True

        def write(self, line):
            return self.wrapped.write(line)

        def flush(self):
            if self.fail:
                self.fail = False
                raise OSError("flush failed")
            return self.wrapped.flush()

        def fileno(self):
            return self.wrapped.fileno()

        def close(self):
            return self.wrapped.close()

    original_init = EventWriter.__init__

    def failing_init(self, path):
        original_init(self, path)
        self._file = FailingFlush(self._file)

    monkeypatch.setattr(EventWriter, "__init__", failing_init)
    seed, checks = _inputs(tmp_path)
    run_dir = tmp_path / runner_name
    module = solo_module if runner_name == "solo" else team_module
    _patch_provider(monkeypatch, module, [])
    runner = run_solo if runner_name == "solo" else run_team_cli

    with pytest.raises(RuntimeError, match="^event log write failed$"):
        runner(
            "task", "task-1", str(run_dir), str(seed), str(checks),
            provider_path=str(_provider(tmp_path)),
        )

    rows = _jsonl(run_dir / "events.jsonl")
    assert len(rows) <= 1
    assert [row["seq"] for row in rows] == list(range(1, len(rows) + 1))
    assert not (run_dir / "summary.json").exists()
    assert not (run_dir / "summary.json.tmp").exists()




def test_atomic_writer_rejects_target_links_and_cleans_racing_temp(tmp_path, monkeypatch):
    victim = tmp_path / "victim.json"
    victim.write_text("victim", encoding="utf-8")
    target = tmp_path / "linked.json"
    try:
        target.symlink_to(victim)
    except OSError:
        monkeypatch.setattr("harness.artifacts._is_link_or_junction", lambda path: path == target)
        target.write_text("old", encoding="utf-8")
    with pytest.raises((FileExistsError, ValueError)):
        write_json_atomic(target, {"new": True})
    assert victim.read_text(encoding="utf-8") == "victim"

    race = tmp_path / "race.json"
    original_link = os.link
    def create_racer(source, destination):
        Path(destination).write_text("racer", encoding="utf-8")
        return original_link(source, destination)
    monkeypatch.setattr(os, "link", create_racer)
    with pytest.raises(FileExistsError):
        write_json_atomic(race, {"new": True})
    assert race.read_text(encoding="utf-8") == "racer"
    assert not (tmp_path / "race.json.tmp").exists()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_steps": 0}, {"max_steps": True}, {"max_calls": math.inf},
        {"max_seconds": math.nan}, {"max_tokens": 1.5}, {"task": ""},
    ],
)
def test_invalid_runner_prerequisites_leave_no_run_dir(tmp_path, monkeypatch, kwargs):
    import harness.run_solo as module
    seed, checks = _inputs(tmp_path)
    _patch_provider(monkeypatch, module, [])
    arguments = dict(task="task", task_id="task-1", run_dir=str(tmp_path / "run"), seed_dir=str(seed), checks_file=str(checks), provider_path=str(_provider(tmp_path)))
    arguments.update(kwargs)
    with pytest.raises((TypeError, ValueError)):
        run_solo(**arguments)
    assert not (tmp_path / "run").exists()


def test_missing_setup_inputs_leave_no_run_dir(tmp_path):
    seed, checks = _inputs(tmp_path)
    cases = [
        {"seed_dir": str(tmp_path / "missing-seed"), "checks_file": str(checks), "provider_path": "missing-provider"},
        {"seed_dir": str(seed), "checks_file": str(tmp_path / "missing-checks"), "provider_path": "missing-provider"},
    ]
    for index, case in enumerate(cases):
        run_dir = tmp_path / f"run-{index}"
        with pytest.raises((FileNotFoundError, ValueError)):
            run_solo("task", "task-1", str(run_dir), **case)
        assert not run_dir.exists()


def test_finalize_conflict_preserves_existing_artifact_and_writes_no_summary(tmp_path):
    from harness.workspace import Workspace

    root = tmp_path / "run"
    workspace = Workspace(str(root / "workspace"))
    (root / "sessions").mkdir()
    (root / "tickets").mkdir()
    (root / "sessions" / "solo.jsonl").write_text("old", encoding="utf-8")
    setup = RunnerSetup(root, {"model": "test"}, object(), workspace, object(), object())
    result = SimpleNamespace(
        outcome="done", stopped_reason="done", calls=0, prompt_tokens=0,
        completion_tokens=0, reasoning_tokens=0, transient_retry_attempts=0,
        content_filter_retries=0, tool_invocations=0, duration_ms=0,
        per_role={"solo": {"calls": 0, "llm_duration_ms": 0}},
    )
    with pytest.raises(FileExistsError):
        finalize_artifacts(
            setup, result, task_id="task-1", treatment="S", limits={},
            sessions={"solo": []}, tickets=[], extras={"completion": None},
        )
    assert (root / "sessions" / "solo.jsonl").read_text(encoding="utf-8") == "old"
    assert not (root / "summary.json").exists()


def test_summary_is_last_atomic_json_artifact(tmp_path, monkeypatch):
    import harness.run_solo as module

    seed, checks = _inputs(tmp_path)
    _patch_provider(monkeypatch, module, [_response([], usage=True), _response([], usage=True)])
    import harness.runner_common as common
    original = common.write_json_atomic
    paths = []

    def record(path, value):
        paths.append(path.name)
        original(path, value)

    monkeypatch.setattr(common, "write_json_atomic", record)
    run_dir = tmp_path / "ordered"
    summary = run_solo("task", "task-1", str(run_dir), str(seed), str(checks), provider_path=str(_provider(tmp_path)))

    assert summary["outcome"] == "failed"
    assert paths[-1] == "summary.json"
    assert not (run_dir / "summary.json.tmp").exists()


def test_missing_usage_is_controlled_and_unexpected_crash_has_no_summary(tmp_path, monkeypatch):
    import harness.run_solo as module

    seed, checks = _inputs(tmp_path)
    _patch_provider(
        monkeypatch,
        module,
        [_response([_call("d", "submit_done", _done())], usage=False)],
    )
    controlled = tmp_path / "controlled"
    summary = run_solo(
        "task", "task-1", str(controlled), str(seed), str(checks),
        max_tokens=100, provider_path=str(_provider(tmp_path)),
    )
    assert summary["outcome"] == "failed"
    assert summary["stopped_reason"] == "budget_accounting_error"
    assert summary["calls"] == 1

    _patch_provider(monkeypatch, module, [])
    monkeypatch.setattr(module, "run_solo_loop", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    crashed = tmp_path / "crashed"
    with pytest.raises(RuntimeError, match="boom"):
        run_solo("task", "task-1", str(crashed), str(seed), str(checks), provider_path=str(_provider(tmp_path)))
    assert (crashed / "events.jsonl").exists()
    assert not (crashed / "summary.json").exists()
    assert not (crashed / "summary.json.tmp").exists()
