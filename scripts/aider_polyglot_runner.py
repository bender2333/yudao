#!/usr/bin/env python3
"""Aider Polyglot solo vs multi batch runner (no Docker).

Implements docs/native-harness/aider-polyglot-protocol.md §5–§7.

Example:
  python scripts/aider_polyglot_runner.py \\
    --batch-id pilot-001 \\
    --exercises-root third_party/polyglot-benchmark \\
    --tasklist docs/native-harness/aider-polyglot-tasklist.md \\
    --arms S,P --reps 1 \\
    --max-calls 60 --max-tokens 200000 --max-seconds 300

  # Offline pipeline check (no LLM): inject .meta/example.py solutions
  python scripts/aider_polyglot_runner.py --batch-id dry-1 ... --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Repo root = parent of scripts/
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.run_multi import run_multi_cli  # noqa: E402
from harness.run_solo import run_solo  # noqa: E402


# ── tasklist ──────────────────────────────────────────────


@dataclass
class TaskSpec:
    slug: str
    difficulty: str = ""
    notes: str = ""
    # relative paths under exercise dir; empty → infer from .meta/config.json
    solution_files: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)


def parse_tasklist(path: str | Path) -> list[TaskSpec]:
    """Parse markdown table rows: | slug | difficulty | notes | or | slug | only."""
    text = Path(path).read_text(encoding="utf-8")
    tasks: list[TaskSpec] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells or cells[0].lower() in {"slug", "----", "---"}:
            continue
        if set(cells[0]) <= {"-"}:
            continue
        slug = cells[0]
        if not slug or slug.startswith("("):
            continue
        difficulty = cells[1] if len(cells) > 1 else ""
        notes = cells[2] if len(cells) > 2 else ""
        tasks.append(TaskSpec(slug=slug, difficulty=difficulty, notes=notes))
    if not tasks:
        raise ValueError(f"no tasks parsed from {path}")
    return tasks


def load_exercise_config(exercise_dir: Path) -> dict[str, Any]:
    cfg_path = exercise_dir / ".meta" / "config.json"
    if not cfg_path.is_file():
        return {}
    return json.loads(cfg_path.read_text(encoding="utf-8"))


def resolve_file_lists(exercise_dir: Path, spec: TaskSpec) -> tuple[list[str], list[str]]:
    cfg = load_exercise_config(exercise_dir)
    files = cfg.get("files") or {}
    solutions = list(spec.solution_files) or list(files.get("solution") or [])
    tests = list(spec.test_files) or list(files.get("test") or [])
    if not solutions:
        # fallback: non-test *.py at top level
        solutions = [
            p.name
            for p in exercise_dir.glob("*.py")
            if not p.name.endswith("_test.py") and not p.name.startswith("test_")
        ]
    if not tests:
        tests = [p.name for p in exercise_dir.glob("*_test.py")]
        tests += [p.name for p in exercise_dir.glob("test_*.py")]
    if not solutions:
        raise FileNotFoundError(f"no solution files for {spec.slug} in {exercise_dir}")
    if not tests:
        raise FileNotFoundError(f"no test files for {spec.slug} in {exercise_dir}")
    return solutions, tests


def read_instructions(exercise_dir: Path) -> str:
    docs = exercise_dir / ".docs"
    parts: list[str] = []
    for name in ("introduction.md", "instructions.md", "instructions.append.md"):
        p = docs / name
        if p.is_file():
            parts.append(p.read_text(encoding="utf-8").strip())
    if parts:
        return "\n\n".join(parts)
    # fallback: blurb
    cfg = load_exercise_config(exercise_dir)
    blurb = (cfg.get("blurb") or "").strip()
    if blurb:
        return blurb
    return f"Complete the exercise in {exercise_dir.name}."


def build_task_prompt(instructions: str, solution_files: list[str]) -> str:
    targets = ", ".join(f"`{f}`" for f in solution_files)
    return (
        "你在独立工作区中完成一道编程练习。\n\n"
        "# 任务说明\n"
        f"{instructions.strip()}\n\n"
        "# 要求\n"
        f"- 实现工作区内的目标源文件（{targets}），使功能符合说明。\n"
        "- 可用工具读写文件、运行命令做自检。\n"
        "- 不要假设存在隐藏测试文件；以说明中的行为为准。\n"
        "- 完成后停止。\n"
    )


# ── filesystem helpers ────────────────────────────────────


def git_sha(repo: Path) -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def copytree(src: Path, dst: Path) -> None:
    if dst.exists():
        raise FileExistsError(str(dst))
    shutil.copytree(src, dst)


def is_test_path(rel: str, test_files: set[str]) -> bool:
    name = rel.replace("\\", "/").split("/")[-1]
    if name in test_files:
        return True
    if name.endswith("_test.py") or name.startswith("test_"):
        return True
    return False


def prepare_agent_seed(source_dir: Path, seed_dir: Path, test_files: list[str]) -> None:
    """Copy exercise into seed_dir excluding tests and .meta (keep .docs)."""
    if seed_dir.exists():
        raise FileExistsError(str(seed_dir))
    test_set = set(test_files)
    seed_dir.mkdir(parents=True)
    for dirpath, dirnames, filenames in os.walk(source_dir):
        rel_dir = os.path.relpath(dirpath, source_dir)
        # skip .meta entirely (example solutions must not leak)
        if rel_dir == ".meta" or rel_dir.startswith(".meta" + os.sep):
            dirnames[:] = []
            continue
        parts = Path(rel_dir).parts if rel_dir != "." else ()
        if parts and parts[0] == ".meta":
            dirnames[:] = []
            continue
        for name in filenames:
            rel = name if rel_dir == "." else str(Path(rel_dir) / name)
            rel_posix = rel.replace("\\", "/")
            if is_test_path(rel_posix, test_set):
                continue
            src = Path(dirpath) / name
            out = seed_dir / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out)


def sync_solutions_to_judge(
    agent_workspace: Path,
    judge_dir: Path,
    solution_files: list[str],
) -> tuple[list[str], list[str]]:
    """Copy solution files from agent workspace into judge. Returns (copied, missing)."""
    copied: list[str] = []
    missing: list[str] = []
    for rel in solution_files:
        src = agent_workspace / rel
        if not src.is_file():
            missing.append(rel)
            continue
        dst = judge_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(rel)
    return copied, missing


def run_pytest(judge_dir: Path, test_files: list[str], log_path: Path, timeout: int) -> int:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *test_files,
        "-q",
        "--tb=short",
    ]
    try:
        r = subprocess.run(
            cmd,
            cwd=str(judge_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
        )
        log_path.write_text(
            f"$ {' '.join(cmd)}\nexit={r.returncode}\n\nSTDOUT:\n{r.stdout}\n\nSTDERR:\n{r.stderr}\n",
            encoding="utf-8",
        )
        return r.returncode
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        err = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        log_path.write_text(
            f"$ {' '.join(cmd)}\nexit=timeout({timeout}s)\n\nSTDOUT:\n{out}\n\nSTDERR:\n{err}\n",
            encoding="utf-8",
        )
        return -9


# ── single run ────────────────────────────────────────────


def arm_label(arm: str) -> str:
    return arm.upper()


def session_model_for_arm(arm: str, default_p: str) -> str | None:
    a = arm.upper()
    if a == "S":
        return None
    if a == "P":
        return default_p
    if a == "C":
        return "cold"
    raise ValueError(f"unknown arm: {arm}")


def run_one(
    *,
    batch_dir: Path,
    exercises_root: Path,
    language: str,
    spec: TaskSpec,
    arm: str,
    rep: int,
    max_calls: int | None,
    max_tokens: int | None,
    max_seconds: float | None,
    max_steps: int,
    max_rounds: int,
    session_model_p: str,
    provider_path: str,
    pytest_timeout: int,
    dry_run: bool,
    polyglot_sha: str,
    harness_sha: str,
    fail_fast: bool,
) -> dict[str, Any]:
    slug = spec.slug
    arm_u = arm_label(arm)
    run_name = f"{arm_u}_r{rep}"
    task_root = batch_dir / "tasks" / slug
    run_root = task_root / run_name

    result: dict[str, Any] = {
        "batch_id": batch_dir.name,
        "task_slug": slug,
        "arm": arm_u,
        "rep": rep,
        "pass": False,
        "pytest_exit": None,
        "harness_outcome": None,
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "duration_ms": 0,
        "run_dir": str(run_root).replace("\\", "/"),
        "error": None,
        "polyglot_sha": polyglot_sha,
        "harness_sha": harness_sha,
        "solution_files": [],
        "test_files": [],
    }

    summary: dict[str, Any] | None = None
    try:
        if run_root.exists():
            raise FileExistsError(f"run dir exists (no reuse): {run_root}")

        exercise_src = exercises_root / language / "exercises" / "practice" / slug
        if not exercise_src.is_dir():
            # fixtures: exercises_root/<slug>
            alt = exercises_root / slug
            if alt.is_dir():
                exercise_src = alt
            else:
                raise FileNotFoundError(f"exercise not found: {exercise_src}")

        solution_files, test_files = resolve_file_lists(exercise_src, spec)
        result["solution_files"] = solution_files
        result["test_files"] = test_files
        instructions = read_instructions(exercise_src)
        task_prompt = build_task_prompt(instructions, solution_files)

        # source/ once per slug
        source_dir = task_root / "source"
        if not source_dir.exists():
            copytree(exercise_src, source_dir)

        run_root.mkdir(parents=True)
        seed_dir = run_root / "agent_seed"
        judge_dir = run_root / "judge"
        harness_run = run_root / "harness_run"

        prepare_agent_seed(source_dir, seed_dir, test_files)
        (seed_dir / "TASK.md").write_text(task_prompt, encoding="utf-8")

        copytree(source_dir, judge_dir)

        if dry_run:
            # Offline: seed harness workspace with stubs then inject example solutions
            harness_run.mkdir(parents=False)
            ws = harness_run / "workspace"
            shutil.copytree(seed_dir, ws)
            example = source_dir / ".meta" / "example.py"
            if len(solution_files) == 1 and example.is_file():
                shutil.copy2(example, ws / solution_files[0])
            else:
                # multi-file: try example only for single-file exercises
                for sol in solution_files:
                    ex = source_dir / ".meta" / "example.py"
                    if ex.is_file() and sol.endswith(".py"):
                        shutil.copy2(ex, ws / sol)
                        break
            summary = {
                "mode": "dry_run",
                "stopped_reason": "dry_run",
                "outcome": "dry_run",
                "calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "duration_ms": 0,
            }
            (harness_run / "summary.json").write_text(
                json.dumps(summary, indent=2), encoding="utf-8"
            )
        else:
            sm = session_model_for_arm(arm_u, session_model_p)
            if arm_u == "S":
                summary = run_solo(
                    task=task_prompt,
                    run_dir=str(harness_run),
                    max_steps=max_steps,
                    max_calls=max_calls,
                    max_tokens=max_tokens,
                    max_seconds=max_seconds,
                    provider_path=provider_path,
                    seed_dir=str(seed_dir),
                )
            else:
                summary = run_multi_cli(
                    task=task_prompt,
                    run_dir=str(harness_run),
                    max_rounds=max_rounds,
                    max_steps=max_steps,
                    max_calls=max_calls,
                    max_tokens=max_tokens,
                    max_seconds=max_seconds,
                    provider_path=provider_path,
                    session_model=sm or "persistent",
                    seed_dir=str(seed_dir),
                )

        summary_path = harness_run / "summary.json"
        if not summary_path.is_file():
            raise FileNotFoundError("summary.json missing after harness run")

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        result["calls"] = int(summary.get("calls") or 0)
        result["prompt_tokens"] = int(summary.get("prompt_tokens") or 0)
        result["completion_tokens"] = int(summary.get("completion_tokens") or 0)
        result["duration_ms"] = int(summary.get("duration_ms") or 0)
        result["harness_outcome"] = summary.get("outcome") or summary.get(
            "stopped_reason"
        )

        agent_ws = harness_run / "workspace"
        copied, missing = sync_solutions_to_judge(agent_ws, judge_dir, solution_files)
        result["synced_files"] = copied
        if missing:
            result["error"] = "missing_deliverable:" + ",".join(missing)
            result["pass"] = False
            result["pytest_exit"] = None
        else:
            log_path = run_root / "pytest.log"
            code = run_pytest(judge_dir, test_files, log_path, pytest_timeout)
            result["pytest_exit"] = code
            if code == -9:
                result["error"] = "pytest_timeout"
                result["pass"] = False
            else:
                result["pass"] = code == 0

    except Exception as exc:  # noqa: BLE001 — batch continues unless fail_fast
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["pass"] = False
        if fail_fast:
            raise

    out_path = run_root / "result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


# ── batch ─────────────────────────────────────────────────


def write_batch_outputs(batch_dir: Path, rows: list[dict[str, Any]]) -> None:
    jsonl = batch_dir / "results.jsonl"
    with jsonl.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    csv_path = batch_dir / "results.csv"
    fields = [
        "task_slug",
        "arm",
        "rep",
        "pass",
        "pytest_exit",
        "harness_outcome",
        "calls",
        "prompt_tokens",
        "completion_tokens",
        "duration_ms",
        "error",
        "run_dir",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k) for k in fields})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aider_polyglot_runner")
    parser.add_argument("--batch-id", required=True)
    parser.add_argument(
        "--exercises-root",
        default=str(REPO_ROOT / "third_party" / "polyglot-benchmark"),
    )
    parser.add_argument(
        "--tasklist",
        default=str(REPO_ROOT / "docs" / "native-harness" / "aider-polyglot-tasklist.md"),
    )
    parser.add_argument("--language", default="python")
    parser.add_argument("--arms", default="S,P", help="Comma-separated: S,P,C")
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--max-calls", type=int, default=60)
    parser.add_argument("--max-tokens", type=int, default=200_000)
    parser.add_argument("--max-seconds", type=float, default=300.0)
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument(
        "--session-model-p",
        default="persistent",
        choices=("cold", "persistent"),
        help="Session model for arm P",
    )
    parser.add_argument("--seed", type=int, default=42, help="Shuffle arms within each task")
    parser.add_argument(
        "--provider",
        default=str(REPO_ROOT / "provider.md"),
    )
    parser.add_argument("--pytest-timeout", type=int, default=60)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No LLM: inject .meta/example.py into workspace and only run pytest pipeline",
    )
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument(
        "--runs-root",
        default=str(REPO_ROOT / "runs" / "aider"),
    )
    args = parser.parse_args(argv)

    exercises_root = Path(args.exercises_root).resolve()
    if not exercises_root.is_dir():
        print(f"ERROR: exercises-root not found: {exercises_root}", file=sys.stderr)
        print("  git clone https://github.com/Aider-AI/polyglot-benchmark third_party/polyglot-benchmark", file=sys.stderr)
        return 2

    batch_dir = Path(args.runs_root).resolve() / args.batch_id
    if batch_dir.exists():
        print(f"ERROR: batch dir exists (no reuse): {batch_dir}", file=sys.stderr)
        return 2
    batch_dir.mkdir(parents=True)

    tasks = parse_tasklist(args.tasklist)
    arms = [a.strip().upper() for a in args.arms.split(",") if a.strip()]
    for a in arms:
        if a not in {"S", "P", "C"}:
            print(f"ERROR: invalid arm {a}", file=sys.stderr)
            return 2

    polyglot_sha = git_sha(exercises_root)
    harness_sha = git_sha(REPO_ROOT)
    rng = random.Random(args.seed)

    config = {
        "batch_id": args.batch_id,
        "exercises_root": str(exercises_root),
        "tasklist": str(Path(args.tasklist).resolve()),
        "language": args.language,
        "arms": arms,
        "reps": args.reps,
        "max_calls": args.max_calls,
        "max_tokens": args.max_tokens,
        "max_seconds": args.max_seconds,
        "max_steps": args.max_steps,
        "max_rounds": args.max_rounds,
        "session_model_p": args.session_model_p,
        "seed": args.seed,
        "dry_run": args.dry_run,
        "polyglot_sha": polyglot_sha,
        "harness_sha": harness_sha,
        "tasks": [t.slug for t in tasks],
        "provider": args.provider,
    }
    (batch_dir / "batch_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"batch_dir={batch_dir}")
    print(f"polyglot_sha={polyglot_sha} harness_sha={harness_sha}")
    print(f"tasks={len(tasks)} arms={arms} reps={args.reps} dry_run={args.dry_run}")

    rows: list[dict[str, Any]] = []
    t0 = time.time()

    for spec in tasks:
        order = list(arms)
        rng.shuffle(order)
        for rep in range(1, args.reps + 1):
            for arm in order:
                print(f"--- {spec.slug} {arm} r{rep} ---", flush=True)
                try:
                    row = run_one(
                        batch_dir=batch_dir,
                        exercises_root=exercises_root,
                        language=args.language,
                        spec=spec,
                        arm=arm,
                        rep=rep,
                        max_calls=None if args.dry_run else args.max_calls,
                        max_tokens=None if args.dry_run else args.max_tokens,
                        max_seconds=None if args.dry_run else args.max_seconds,
                        max_steps=args.max_steps,
                        max_rounds=args.max_rounds,
                        session_model_p=args.session_model_p,
                        provider_path=args.provider,
                        pytest_timeout=args.pytest_timeout,
                        dry_run=args.dry_run,
                        polyglot_sha=polyglot_sha,
                        harness_sha=harness_sha,
                        fail_fast=args.fail_fast,
                    )
                except Exception as exc:  # noqa: BLE001
                    row = {
                        "batch_id": args.batch_id,
                        "task_slug": spec.slug,
                        "arm": arm,
                        "rep": rep,
                        "pass": False,
                        "error": f"{type(exc).__name__}: {exc}",
                        "polyglot_sha": polyglot_sha,
                        "harness_sha": harness_sha,
                    }
                    if args.fail_fast:
                        rows.append(row)
                        write_batch_outputs(batch_dir, rows)
                        raise
                rows.append(row)
                status = "PASS" if row.get("pass") else "FAIL"
                print(
                    f"    -> {status} error={row.get('error')} "
                    f"pytest={row.get('pytest_exit')} calls={row.get('calls')}",
                    flush=True,
                )
                write_batch_outputs(batch_dir, rows)

    write_batch_outputs(batch_dir, rows)
    n_pass = sum(1 for r in rows if r.get("pass"))
    elapsed = time.time() - t0
    print(f"done: {n_pass}/{len(rows)} PASS in {elapsed:.1f}s")
    print(f"results: {batch_dir / 'results.csv'}")
    # dry-run: non-zero if any FAIL (pipeline regression). live: always 0 if batch finished.
    if args.dry_run:
        return 0 if n_pass == len(rows) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
