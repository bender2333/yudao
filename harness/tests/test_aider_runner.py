"""Unit tests for scripts/aider_polyglot_runner helpers + dry-run pipeline."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "aider_polyglot_runner.py"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mini_exercise"


def _load_runner():
    spec = importlib.util.spec_from_file_location("aider_polyglot_runner", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # dataclasses need the module registered before class body runs
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def runner():
    return _load_runner()


def test_parse_tasklist(tmp_path, runner):
    p = tmp_path / "tl.md"
    p.write_text(
        "# t\n\n| slug | difficulty | notes |\n|---|---|---|\n| list-ops | med | x |\n| grade-school | hard | |\n",
        encoding="utf-8",
    )
    tasks = runner.parse_tasklist(p)
    assert [t.slug for t in tasks] == ["list-ops", "grade-school"]
    assert tasks[0].difficulty == "med"


def test_resolve_and_instructions(runner):
    solutions, tests = runner.resolve_file_lists(
        FIXTURE, runner.TaskSpec(slug="mini_exercise")
    )
    assert solutions == ["mini.py"]
    assert tests == ["mini_suite.py"]
    text = runner.read_instructions(FIXTURE)
    assert "add" in text.lower() or "Mini" in text


def test_prepare_agent_seed_strips_tests(tmp_path, runner):
    seed = tmp_path / "seed"
    runner.prepare_agent_seed(FIXTURE, seed, ["mini_suite.py"])
    assert (seed / "mini.py").is_file()
    assert not (seed / "mini_suite.py").exists()
    assert not (seed / ".meta").exists()
    assert (seed / ".docs" / "instructions.md").is_file()


def test_seed_workspace_into_dest(tmp_path):
    from harness.seed import seed_workspace

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("x=1\n", encoding="utf-8")
    dest = tmp_path / "dest"
    dest.mkdir()
    copied = seed_workspace(str(src), str(dest))
    assert copied == ["a.py"]
    assert (dest / "a.py").read_text(encoding="utf-8") == "x=1\n"


def test_dry_run_mini_pipeline(tmp_path, runner):
    """Full dry-run on fixture: example solution should pytest PASS."""
    tasklist = tmp_path / "tl.md"
    tasklist.write_text(
        "| slug | difficulty | notes |\n|---|---|---|\n| mini_exercise | easy | fixture |\n",
        encoding="utf-8",
    )
    runs_root = tmp_path / "runs"
    code = runner.main(
        [
            "--batch-id",
            "unit-dry",
            "--exercises-root",
            str(FIXTURE.parent),  # fixtures/; alt path = fixtures/mini_exercise
            "--tasklist",
            str(tasklist),
            "--arms",
            "S",
            "--reps",
            "1",
            "--dry-run",
            "--runs-root",
            str(runs_root),
        ]
    )
    # exercises_root/slug = fixtures/mini_exercise works via alt path
    assert code == 0
    batch = runs_root / "unit-dry"
    assert (batch / "results.csv").is_file()
    rows = [
        json.loads(line)
        for line in (batch / "results.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 1
    assert rows[0]["pass"] is True
    assert rows[0]["error"] is None
    # agent seed must not contain tests
    seed = batch / "tasks" / "mini_exercise" / "S_r1" / "agent_seed"
    assert not (seed / "mini_suite.py").exists()
    judge = batch / "tasks" / "mini_exercise" / "S_r1" / "judge"
    assert (judge / "mini_suite.py").is_file()
