"""Hard-timeout supervisor for harness runner process trees."""

from __future__ import annotations

import argparse
import json
import math
import os
import stat
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from .artifacts import write_json_atomic
from .local_tools import _safe_env
from .process_control import ProcessResult, run_process_tree
from .workspace import _is_link_or_junction

_MAX_SUMMARY_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class SupervisorResult:
    returncode: int | None
    timed_out: bool
    stop_reason: str
    duration_ms: int
    summary: dict | None


def _validate(
    argv: object, run_dir: object, timeout_seconds: object, env: object
) -> tuple[list[str], Path, float, dict[str, str]]:
    if type(argv) is not list or not argv or any(
        type(arg) is not str or not arg or "\0" in arg for arg in argv
    ):
        raise ValueError("argv must be a non-empty exact list of non-empty strings without NUL")
    if type(run_dir) is not type(Path()):
        raise TypeError("run_dir must be an exact platform Path")
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be a finite positive number")
    if type(env) is not dict or any(
        type(key) is not str or type(value) is not str or "\0" in key or "\0" in value
        for key, value in env.items()
    ):
        raise ValueError("env must be an exact dict of strings without NUL")
    if os.path.lexists(run_dir):
        raise FileExistsError(run_dir)
    parent = run_dir.parent
    if not parent.is_dir() or _is_link_or_junction(parent):
        raise ValueError("run_dir parent must be a real existing directory")
    return list(argv), run_dir, float(timeout_seconds), dict(env)


def _read_summary(path: Path) -> dict | None:
    try:
        if _is_link_or_junction(path) or not stat.S_ISREG(path.lstat().st_mode):
            return None
        if path.stat().st_size > _MAX_SUMMARY_BYTES:
            return None
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if type(value) is dict else None


def _safe_run_dir(run_dir: Path) -> None:
    if not os.path.lexists(run_dir):
        run_dir.mkdir()
    if _is_link_or_junction(run_dir) or not stat.S_ISDIR(run_dir.lstat().st_mode):
        raise ValueError("child run_dir must be a real directory")


def _write_result(run_dir: Path, result: SupervisorResult) -> None:
    write_json_atomic(
        run_dir / "supervisor.json",
        {"schema_version": 1, **asdict(result)},
    )


def supervise_command(
    argv: list[str],
    *,
    run_dir: Path,
    timeout_seconds: float,
    env: dict[str, str],
) -> SupervisorResult:
    command, target, timeout, child_env = _validate(argv, run_dir, timeout_seconds, env)
    token = uuid.uuid4().hex
    stdout = target.parent / f".{target.name}-{token}.supervisor.stdout.log"
    stderr = target.parent / f".{target.name}-{token}.supervisor.stderr.log"
    started = time.monotonic()
    try:
        try:
            process = run_process_tree(
                command,
                cwd=os.getcwd(),
                env=child_env,
                timeout_seconds=timeout,
                stdout_path=stdout,
                stderr_path=stderr,
            )
        except Exception:
            process = ProcessResult(None, False, max(0, int((time.monotonic() - started) * 1000)))
        _safe_run_dir(target)
        summary: dict | None = None
        if process.timed_out:
            reason = "hard_timeout"
        elif process.returncode != 0:
            reason = "process_failed"
        elif not os.path.lexists(target / "summary.json"):
            reason = "summary_missing"
        else:
            summary = _read_summary(target / "summary.json")
            reason = "completed" if summary is not None else "summary_invalid"
        result = SupervisorResult(
            process.returncode, process.timed_out, reason, process.duration_ms, summary
        )
        _write_result(target, result)
        return result
    finally:
        for path in (stdout, stderr):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness.supervisor")
    subparsers = parser.add_subparsers(dest="mode", required=True)
    for mode in ("team", "solo"):
        child = subparsers.add_parser(mode)
        child.add_argument("task")
        child.add_argument("--task-id", required=True)
        child.add_argument("--run-dir", required=True, type=Path)
        child.add_argument("--seed-dir", required=True)
        child.add_argument("--checks-file", required=True)
        child.add_argument("--max-steps", type=int, default=40 if mode == "team" else 200)
        child.add_argument("--max-calls", type=int, default=200)
        child.add_argument("--max-tokens", type=int)
        child.add_argument("--max-seconds", type=float, default=5400)
        child.add_argument("--provider-path", default="provider.md")
        child.add_argument("--hard-timeout", type=float, default=5700)
        if mode == "team":
            child.add_argument("--max-reworks", type=int, default=8)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    command = [
        sys.executable,
        "-m",
        f"harness.run_{args.mode}",
        args.task,
        "--task-id",
        args.task_id,
        "--run-dir",
        str(args.run_dir),
        "--seed-dir",
        args.seed_dir,
        "--checks-file",
        args.checks_file,
        "--max-steps",
        str(args.max_steps),
        "--max-calls",
        str(args.max_calls),
    ]
    if args.max_tokens is not None:
        command.extend(("--max-tokens", str(args.max_tokens)))
    command.extend((
        "--max-seconds",
        str(args.max_seconds),
        "--provider-path",
        args.provider_path,
    ))
    if args.mode == "team":
        command.extend(("--max-reworks", str(args.max_reworks)))
    result = supervise_command(
        command,
        run_dir=args.run_dir,
        timeout_seconds=args.hard_timeout,
        env=_safe_env(),
    )
    print(json.dumps({"schema_version": 1, **asdict(result)}, ensure_ascii=False))
    return 0 if result.stop_reason == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
