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
from .contracts import canonical_json
from .local_tools import _safe_env
from .process_control import run_process_tree
from .workspace import _is_link_or_junction, _require_link_free_components

_MAX_SUMMARY_BYTES = 1024 * 1024
_MAX_SUMMARY_NODES = 100_000
_MAX_SUMMARY_DEPTH = 100
_MAX_SUMMARY_STRING_BYTES = 256 * 1024


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
    _require_link_free_components(os.fspath(run_dir.parent), "run_dir parent")
    if os.path.lexists(run_dir):
        raise FileExistsError(run_dir)
    parent = run_dir.parent
    if not parent.is_dir() or _is_link_or_junction(parent):
        raise ValueError("run_dir parent must be a real existing directory")
    return list(argv), run_dir, float(timeout_seconds), dict(env)


def _reject_constant(value: str) -> None:
    raise ValueError(value)


def _validate_summary_shape(value: object) -> None:
    nodes = 0
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > _MAX_SUMMARY_NODES or depth > _MAX_SUMMARY_DEPTH:
            raise ValueError("summary is too complex")
        if type(item) is str and len(item.encode("utf-8")) > _MAX_SUMMARY_STRING_BYTES:
            raise ValueError("summary string is too large")
        if type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is dict:
            pending.extend((child, depth + 1) for child in item.values())


def _read_summary(path: Path) -> dict | None:
    try:
        if _is_link_or_junction(path) or not stat.S_ISREG(path.lstat().st_mode):
            return None
        if path.stat().st_size > _MAX_SUMMARY_BYTES:
            return None
        value = json.loads(
            path.read_text(encoding="utf-8", errors="strict"),
            parse_constant=_reject_constant,
        )
        if type(value) is not dict:
            return None
        _validate_summary_shape(value)
        canonical_json(value)
        return value
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError, TypeError, ValueError):
        return None


def _summary_completed(summary: dict) -> bool:
    treatment = summary.get("treatment")
    return summary.get("outcome") == "done" and (
        (treatment == "S" and summary.get("stopped_reason") == "completed")
        or (treatment == "T" and summary.get("stopped_reason") == "done")
    )


def _ensure_record_dir(run_dir: Path) -> bool:
    if not os.path.lexists(run_dir):
        run_dir.mkdir()
        return True
    if not _is_link_or_junction(run_dir) and stat.S_ISDIR(run_dir.lstat().st_mode):
        return True
    os.replace(run_dir, run_dir.with_name(f".{run_dir.name}.invalid-{uuid.uuid4().hex}"))
    run_dir.mkdir()
    return False


def _quarantine_leaf(path: Path) -> None:
    if os.path.lexists(path):
        quarantine = path.with_name(f".{path.name}.child-{uuid.uuid4().hex}")
        os.replace(path, quarantine)


def _prepare_result_paths(run_dir: Path) -> None:
    target = run_dir / "supervisor.json"
    _quarantine_leaf(target)
    _quarantine_leaf(target.with_name(target.name + ".tmp"))


def _move_log(source: Path, target: Path) -> None:
    if not os.path.lexists(source):
        return
    _quarantine_leaf(target)
    os.link(source, target)
    try:
        source.unlink()
    except FileNotFoundError:
        pass


def _write_result(run_dir: Path, result: SupervisorResult) -> None:
    value = {"schema_version": 1, **asdict(result)}
    canonical_json(value)
    for attempt in range(2):
        _prepare_result_paths(run_dir)
        try:
            write_json_atomic(run_dir / "supervisor.json", value)
            return
        except FileExistsError:
            if attempt:
                raise


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
    preserve_logs = False
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
        except Exception as error:
            preserve_logs = True
            _ensure_record_dir(target)
            result = SupervisorResult(
                None,
                False,
                "supervisor_error",
                max(0, int((time.monotonic() - started) * 1000)),
                {"error_type": type(error).__name__},
            )
        else:
            if not _ensure_record_dir(target):
                preserve_logs = True
                result = SupervisorResult(
                    process.returncode,
                    process.timed_out,
                    "supervisor_error",
                    process.duration_ms,
                    {"error_type": "InvalidRunDirectory"},
                )
            else:
                summary: dict | None = None
                if process.timed_out:
                    reason = "hard_timeout"
                elif process.returncode != 0:
                    reason = "process_failed"
                elif not os.path.lexists(target / "summary.json"):
                    reason = "summary_missing"
                else:
                    summary = _read_summary(target / "summary.json")
                    if summary is None:
                        reason = "summary_invalid"
                    else:
                        reason = "completed" if _summary_completed(summary) else "process_failed"
                result = SupervisorResult(
                    process.returncode, process.timed_out, reason, process.duration_ms, summary
                )
        if result.stop_reason != "completed":
            try:
                _move_log(stdout, target / "supervisor.stdout.log")
                _move_log(stderr, target / "supervisor.stderr.log")
            except OSError:
                preserve_logs = True
                result = SupervisorResult(
                    result.returncode,
                    result.timed_out,
                    "supervisor_error",
                    result.duration_ms,
                    {"error_type": "LogPreservationError"},
                )
        _write_result(target, result)
        return result
    except BaseException:
        preserve_logs = True
        raise
    finally:
        if not preserve_logs:
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
