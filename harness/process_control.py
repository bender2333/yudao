"""Run argv-only subprocesses with cross-platform process-tree timeouts."""

from __future__ import annotations

import math
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessResult:
    returncode: int | None
    timed_out: bool
    duration_ms: int


def _validate(argv: object, cwd: object, env: object, timeout_seconds: object, stdout_path: object, stderr_path: object) -> tuple[list[str], str, dict[str, str], float, Path, Path]:
    if type(argv) is not list or not argv or any(type(arg) is not str or not arg or "\0" in arg for arg in argv):
        raise ValueError("argv must be a non-empty exact list of non-empty strings without NUL")
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be a finite positive number")
    if not isinstance(cwd, (str, os.PathLike)):
        raise TypeError("cwd must be a path")
    cwd_source = os.path.abspath(os.fspath(cwd))
    if os.path.islink(cwd_source) or getattr(os.path, "isjunction", lambda _path: False)(cwd_source):
        raise ValueError("cwd must be a real directory")
    cwd_path = os.path.realpath(cwd_source)
    if not os.path.isdir(cwd_path):
        raise ValueError("cwd must be a real directory")
    if type(env) is not dict or any(type(key) is not str or type(value) is not str or "\0" in key or "\0" in value for key, value in env.items()):
        raise ValueError("env must be an exact dict of strings without NUL")
    stdout = Path(stdout_path)
    stderr = Path(stderr_path)
    same_output = os.path.normcase(os.path.abspath(stdout)) == os.path.normcase(os.path.abspath(stderr))
    if not same_output and stdout.exists() and stderr.exists():
        same_output = os.path.samefile(stdout, stderr)
    if same_output:
        raise ValueError("stdout_path and stderr_path must be different")
    for label, path in (("stdout_path", stdout), ("stderr_path", stderr)):
        if not path.parent.is_dir():
            raise ValueError(f"{label} parent must be an existing directory")
    return list(argv), cwd_path, dict(env), float(timeout_seconds), stdout, stderr


def _terminate_tree(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
        if not system_root:
            process.kill()
            process.wait()
            raise RuntimeError("SystemRoot/WINDIR unavailable; cannot guarantee process-tree cleanup")
        taskkill = os.path.join(system_root, "System32", "taskkill.exe")
        cleanup_error: BaseException | None = None
        try:
            completed = subprocess.run(
                [taskkill, "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
                shell=False,
            )
            if completed.returncode != 0:
                cleanup_error = RuntimeError(f"taskkill failed with exit {completed.returncode}")
        except (OSError, subprocess.TimeoutExpired) as error:
            cleanup_error = RuntimeError(f"taskkill failed: {error}")
        finally:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if cleanup_error is not None:
            raise cleanup_error
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_process_tree(
    argv: list[str],
    *,
    cwd: str | os.PathLike[str],
    env: dict[str, str],
    timeout_seconds: float,
    stdout_path: str | os.PathLike[str],
    stderr_path: str | os.PathLike[str],
) -> ProcessResult:
    """Run a process in its own group and kill the full group on timeout."""
    command, working_dir, child_env, timeout, stdout, stderr = _validate(
        argv, cwd, env, timeout_seconds, stdout_path, stderr_path
    )
    start = time.monotonic()
    timed_out = False
    popen_options = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    with stdout.open("wb") as stdout_file, stderr.open("wb") as stderr_file:
        process = subprocess.Popen(
            command,
            cwd=working_dir,
            env=child_env,
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            shell=False,
            **popen_options,
        )
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_tree(process)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    return ProcessResult(process.returncode, timed_out, max(0, int((time.monotonic() - start) * 1000)))
