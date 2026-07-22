from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.artifacts import EventWriter, write_json_atomic
from harness.contracts import verify_ticket
from harness.run_solo import run_solo
from harness.run_team import run_team_cli


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

    summary = run_solo("implement VALUE", "task-1", str(run_dir), str(seed), str(checks), provider_path="ignored")

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

    summary = run_team_cli("implement VALUE", "task-1", str(run_dir), str(seed), str(checks), provider_path="ignored")

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


def test_summary_is_last_atomic_json_artifact(tmp_path, monkeypatch):
    import harness.run_solo as module

    seed, checks = _inputs(tmp_path)
    _patch_provider(monkeypatch, module, [_response([], usage=True), _response([], usage=True)])
    original = module.write_json_atomic
    paths = []

    def record(path, value):
        paths.append(path.name)
        original(path, value)

    monkeypatch.setattr(module, "write_json_atomic", record)
    run_dir = tmp_path / "ordered"
    summary = run_solo("task", "task-1", str(run_dir), str(seed), str(checks), provider_path="ignored")

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
        max_tokens=100, provider_path="ignored",
    )
    assert summary["outcome"] == "failed"
    assert summary["stopped_reason"] == "budget_accounting_error"
    assert summary["calls"] == 1

    _patch_provider(monkeypatch, module, [])
    monkeypatch.setattr(module, "run_solo_loop", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    crashed = tmp_path / "crashed"
    with pytest.raises(RuntimeError, match="boom"):
        run_solo("task", "task-1", str(crashed), str(seed), str(checks), provider_path="ignored")
    assert (crashed / "events.jsonl").exists()
    assert not (crashed / "summary.json").exists()
    assert not (crashed / "summary.json.tmp").exists()
