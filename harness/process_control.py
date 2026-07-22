"""Run argv-only subprocesses with cross-platform process-tree timeouts."""

from __future__ import annotations

import ctypes
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


if os.name == "nt":
    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]


    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]


    class _THREADENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_uint32),
            ("cntUsage", ctypes.c_uint32),
            ("th32ThreadID", ctypes.c_uint32),
            ("th32OwnerProcessID", ctypes.c_uint32),
            ("tpBasePri", ctypes.c_long),
            ("tpDeltaPri", ctypes.c_long),
            ("dwFlags", ctypes.c_uint32),
        ]


    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]


    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    _kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    _kernel32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    _kernel32.SetInformationJobObject.restype = ctypes.c_int
    _kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    _kernel32.AssignProcessToJobObject.restype = ctypes.c_int
    _kernel32.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    _kernel32.TerminateJobObject.restype = ctypes.c_int
    _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    _kernel32.CloseHandle.restype = ctypes.c_int
    _kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    _kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    _kernel32.Thread32First.argtypes = [ctypes.c_void_p, ctypes.POINTER(_THREADENTRY32)]
    _kernel32.Thread32First.restype = ctypes.c_int
    _kernel32.Thread32Next.argtypes = [ctypes.c_void_p, ctypes.POINTER(_THREADENTRY32)]
    _kernel32.Thread32Next.restype = ctypes.c_int
    _kernel32.OpenThread.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    _kernel32.OpenThread.restype = ctypes.c_void_p
    _kernel32.ResumeThread.argtypes = [ctypes.c_void_p]
    _kernel32.ResumeThread.restype = ctypes.c_uint32


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
    if not same_output and os.path.lexists(stdout) and os.path.lexists(stderr):
        try:
            same_output = os.path.samefile(stdout, stderr)
        except OSError:
            pass
    if same_output:
        raise ValueError("stdout_path and stderr_path must be different")
    for label, path in (("stdout_path", stdout), ("stderr_path", stderr)):
        if not path.parent.is_dir():
            raise ValueError(f"{label} parent must be an existing directory")
    return list(argv), cwd_path, dict(env), float(timeout_seconds), stdout, stderr


def _assign_windows_job(job: int, process: subprocess.Popen[bytes]) -> None:
    if not _kernel32.AssignProcessToJobObject(job, int(process._handle)):
        raise _win_error("AssignProcessToJobObject")


def _resume_process_threads(pid: int) -> None:
    snapshot = _kernel32.CreateToolhelp32Snapshot(0x4, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise _win_error("CreateToolhelp32Snapshot")
    found = 0
    try:
        entry = _THREADENTRY32()
        entry.dwSize = ctypes.sizeof(entry)
        more = _kernel32.Thread32First(snapshot, ctypes.byref(entry))
        if not more:
            raise _win_error("Thread32First")
        while more:
            if entry.th32OwnerProcessID == pid:
                thread = _kernel32.OpenThread(0x0002, False, entry.th32ThreadID)
                if not thread:
                    raise _win_error("OpenThread")
                try:
                    previous = _kernel32.ResumeThread(thread)
                    if previous == 0xFFFFFFFF:
                        raise _win_error("ResumeThread")
                    if previous == 0:
                        raise RuntimeError("target process thread was not suspended")
                    found += 1
                finally:
                    _kernel32.CloseHandle(thread)
            more = _kernel32.Thread32Next(snapshot, ctypes.byref(entry))
        if not found:
            raise RuntimeError("target process has no resumable threads")
    finally:
        _kernel32.CloseHandle(snapshot)


def _win_error(operation: str) -> RuntimeError:
    error = ctypes.get_last_error()
    return RuntimeError(f"{operation} failed with Windows error {error}: {ctypes.FormatError(error)}")


def _create_job() -> int:
    job = _kernel32.CreateJobObjectW(None, None)
    if not job:
        raise _win_error("CreateJobObjectW")
    limits = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    limits.BasicLimitInformation.LimitFlags = 0x2000
    if not _kernel32.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        error = _win_error("SetInformationJobObject")
        _kernel32.CloseHandle(job)
        raise error
    return job


def _best_effort_kill(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
        if system_root:
            try:
                subprocess.run(
                    [os.path.join(system_root, "System32", "taskkill.exe"), "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=5, check=False, shell=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.kill()
    except (OSError, ProcessLookupError):
        pass
    try:
        process.wait(timeout=5)
    except BaseException:
        try:
            process.kill()
            process.wait()
        except BaseException:
            pass


def _terminate_tree(process: subprocess.Popen[bytes], job: int | None) -> None:
    if os.name == "nt" and job:
        if not _kernel32.TerminateJobObject(job, 1):
            raise _win_error("TerminateJobObject")
    elif os.name != "nt":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        _best_effort_kill(process)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run_process_tree(
    argv: list[str],
    *,
    cwd: str | os.PathLike[str],
    env: dict[str, str],
    timeout_seconds: float,
    stdout_path: str | os.PathLike[str],
    stderr_path: str | os.PathLike[str],
) -> ProcessResult:
    """Run a process in a contained tree and reap it on every exit path."""
    command, working_dir, child_env, timeout, stdout, stderr = _validate(
        argv, cwd, env, timeout_seconds, stdout_path, stderr_path
    )
    start = time.monotonic()
    timed_out = False
    job: int | None = None
    assigned = False
    process: subprocess.Popen[bytes] | None = None
    stdout_file = None
    stderr_file = None
    try:
        stdout_file = stdout.open("xb")
        try:
            stderr_file = stderr.open("xb")
        except BaseException:
            stdout_file.close()
            stdout_file = None
            try:
                stdout.unlink()
            except OSError:
                pass
            raise
        if os.name == "nt":
            job = _create_job()
        popen_options = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | 0x4}
            if os.name == "nt"
            else {"start_new_session": True}
        )
        process = subprocess.Popen(
            command, cwd=working_dir, env=child_env, stdin=subprocess.DEVNULL,
            stdout=stdout_file, stderr=stderr_file, shell=False, **popen_options,
        )
        if os.name == "nt":
            _assign_windows_job(job, process)
            assigned = True
            _resume_process_threads(process.pid)
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_tree(process, job)
        return ProcessResult(process.returncode, timed_out, max(0, int((time.monotonic() - start) * 1000)))
    except BaseException:
        if process is not None:
            try:
                if os.name == "nt" and not assigned:
                    process.kill()
                    process.wait()
                else:
                    _terminate_tree(process, job)
            except BaseException:
                _best_effort_kill(process)
        raise
    finally:
        if job:
            _kernel32.CloseHandle(job)
        if stderr_file is not None:
            stderr_file.close()
        if stdout_file is not None:
            stdout_file.close()
