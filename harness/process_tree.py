# 一次命令启动的整棵进程树，收在一个可以一次终止的容器里（工单 #1215）。
#
# 进程超时不等于整棵进程树已经停止（local-tools.md 第 4 节最后两条）：按直接子进程的进程号去结束
# 打不到两处——直接子进程已经退出、它起的子进程被重新挂到别处；子进程自己又派生了下一层。所以
# 启动时就把整棵树收进一个容器，结束时一次停掉容器里的全部进程，不按进程号一棵一棵找：
#   Windows：作业对象（CreateJobObject + KILL_ON_JOB_CLOSE）。子进程先以挂起状态创建，挂上作业对象
#            以后再放行，命令自己起的子进程因此从一开始就在里面，不存在「先跑起来再挂上」的空档；
#   POSIX：新会话（setsid）的进程组，整组 SIGKILL。
#
# 这个模块只管容器：启动选项、挂上、整棵停掉、还剩不剩进程、等它真正停下。输出怎么读、回执怎么写
# 在执行环境那一层（environment.py）。

from __future__ import annotations

import os
import signal
import subprocess
import time
from typing import Any

# 等一整棵树真正停下的上限（秒）：停不下来时如实交回，不在这里无限等
STOP_LIMIT_SEC = 5.0
# 等它停下的轮询间隔（秒）
_POLL_SEC = 0.02

# 启动子进程时用的创建选项（user32/kernel32 的常量，两个平台各自取用）
_CREATE_SUSPENDED = 0x00000004
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001
_PROCESS_SUSPEND_RESUME = 0x0800
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")

    class _BasicLimit(ctypes.Structure):
        # JOBOBJECT_BASIC_LIMIT_INFORMATION 的字段与顺序
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _IoCounters(ctypes.Structure):
        _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong)]

    class _ExtendedLimit(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _BasicLimit),
                    ("IoInfo", _IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    class _BasicAccounting(ctypes.Structure):
        # JOBOBJECT_BASIC_ACCOUNTING_INFORMATION：ActiveProcesses 是容器里还在运行的进程数
        _fields_ = [("TotalUserTime", ctypes.c_longlong),
                    ("TotalKernelTime", ctypes.c_longlong),
                    ("ThisPeriodTotalUserTime", ctypes.c_longlong),
                    ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                    ("TotalPageFaultCount", wintypes.DWORD),
                    ("TotalProcesses", wintypes.DWORD),
                    ("ActiveProcesses", wintypes.DWORD),
                    ("TotalTerminatedProcesses", wintypes.DWORD)]

    def _active_processes(job: int) -> int | None:
        # 容器里还在运行的进程数；查不出来时交回 None（调用方按「无法确认」处理）
        info = _BasicAccounting()
        ok = _kernel32.QueryInformationJobObject(
            job, _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION, ctypes.byref(info), ctypes.sizeof(info), None)
        return int(info.ActiveProcesses) if ok else None

    def _pid_is_active(pid: int) -> bool:
        handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        code = wintypes.DWORD()
        ok = _kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        _kernel32.CloseHandle(handle)
        return bool(ok) and code.value == _STILL_ACTIVE

    def _create_job() -> int | None:
        # 关掉最后一个句柄时容器里的进程一起结束：Yudao 自己被终止时留下的后台进程不会活过它
        job = _kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = _kernel32.SetInformationJobObject(
            job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info))
        if not ok:
            _kernel32.CloseHandle(job)
            return None
        return job


def spawn_options() -> dict[str, Any]:
    """启动命令用的创建选项：先挂上容器再放行（Windows），或另起一个会话（POSIX）。"""
    if os.name == "nt":
        return {"creationflags": _CREATE_SUSPENDED | _CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


class ProcessTree:
    """一次 `bash` 调用或一次检查启动的整棵进程树。

    用法：以 `spawn_options()` 启动子进程，紧接着 `attach(进程号)`，结束时 `stop()`，
    之后按需要问 `has_live_processes()` 与 `wait_stopped()`，最后 `close()`。
    """

    def __init__(self) -> None:
        self.pid: int | None = None
        # Windows：作业对象句柄与放行用的进程句柄；POSIX 不用
        self._job: int | None = None
        self._process: int | None = None
        # 挂上容器了没有；没挂上时退回到按进程树结束（taskkill /T），行为与改动前相同
        self.attached = False
        # POSIX：子进程是新会话的首进程，进程组号就是它的进程号
        self._pgid: int | None = None

    def attach(self, pid: int) -> None:
        """把刚启动的子进程收进容器。

        Windows 上子进程是以挂起状态创建的：这里先把它挂进作业对象，再放行。放行是必须做的，
        挂不上时照样放行——否则子进程永远不跑；那样就退回按进程树结束。
        """
        self.pid = pid
        if os.name == "nt":
            self._attach_windows(pid)
        else:
            self._pgid = pid
            self.attached = True

    def _attach_windows(self, pid: int) -> None:
        job = _create_job()
        if job is None:
            self._resume(pid)
            return
        handle = _kernel32.OpenProcess(
            _PROCESS_SET_QUOTA | _PROCESS_TERMINATE | _PROCESS_SUSPEND_RESUME, False, pid)
        if not handle:
            _kernel32.CloseHandle(job)
            self._resume(pid)
            return
        assigned = bool(_kernel32.AssignProcessToJobObject(job, handle))
        if assigned:
            self._job = job
            self._process = handle
            self.attached = True
        else:
            _kernel32.CloseHandle(job)
            self._process = handle
        self._resume_or_stop(handle)

    def _resume(self, pid: int) -> None:
        # 作业对象没建起来时走这里：没有容器可挂，照样要把子进程放行
        handle = _kernel32.OpenProcess(_PROCESS_SUSPEND_RESUME | _PROCESS_TERMINATE, False, pid)
        if not handle:
            self.stop()
            raise OSError(f"cannot resume the suspended command process {pid}")
        try:
            self._resume_or_stop(handle)
        finally:
            _kernel32.CloseHandle(handle)

    def _resume_or_stop(self, handle: int) -> None:
        # 放行不了就把整棵树结束掉再报错：不让一个挂起的子进程等一个永远不来的放行
        status = _ntdll.NtResumeProcess(handle)
        if status == 0:
            return
        self.stop()
        raise OSError(f"NtResumeProcess failed with status {status:#x}")

    def stop(self) -> None:
        """一次结束整棵进程树。已经停下的、本来就没有的都不算错。"""
        if os.name == "nt":
            if self._job is not None:
                # 容器里包括直接子进程已经退出以后留下的那些孙进程
                _kernel32.TerminateJobObject(self._job, 1)
            elif self.pid is not None:
                # 没挂上作业对象：按进程树结束，与改动前的做法相同
                subprocess.run(["taskkill", "/PID", str(self.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            return
        if self._pgid is not None:
            try:
                os.killpg(self._pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    def has_live_processes(self) -> bool:
        """容器里还有进程吗。直接子进程退出以后用它判断命令是否留下了子进程。"""
        if os.name == "nt":
            if self._job is not None:
                active = _active_processes(self._job)
                return True if active is None else active > 0
            return self.pid is not None and _pid_is_active(self.pid)
        if self._pgid is None:
            return False
        try:
            os.killpg(self._pgid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def stopped(self) -> bool:
        """容器里已经一个进程不剩。"""
        return not self.has_live_processes()

    def wait_stopped(self, limit: float = STOP_LIMIT_SEC) -> bool:
        """等一整棵树真正停下，最多等 limit 秒；到点还没停就交回 False。"""
        deadline = time.monotonic() + limit
        while True:
            if self.stopped():
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(_POLL_SEC)

    def close(self) -> None:
        """释放容器。Windows 上关掉作业对象的最后一个句柄会让容器里剩下的进程一起结束。"""
        if self._process is not None:
            _kernel32.CloseHandle(self._process)
            self._process = None
        if self._job is not None:
            _kernel32.CloseHandle(self._job)
            self._job = None

    def __enter__(self) -> "ProcessTree":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - 清理路径，正常走 close()
        try:
            self.close()
        except Exception:
            pass
