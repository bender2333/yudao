"""OMP RPC 子进程传输：独立读队列、stderr 排空、超时/中止/退出可判定。"""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, TextIO

from ..redact import redact_text
from .base import ProviderError

_STDOUT_CLOSED = object()
_STDERR_LIMIT = 16_384


class RpcAborted(ProviderError):
    def __init__(self, message: str = "OMP RPC aborted") -> None:
        super().__init__(message, reason="cancelled")


class RpcTimeout(ProviderError):
    def __init__(self, message: str = "OMP RPC timed out") -> None:
        super().__init__(message, reason="provider_error")


class RpcExited(ProviderError):
    def __init__(self, message: str, *, returncode: int | None = None) -> None:
        super().__init__(message, reason="provider_error")
        self.returncode = returncode


@dataclass
class RpcProcess:
    proc: subprocess.Popen[str]
    frames: queue.Queue[object]
    abort_flag: threading.Event
    _stderr_chunks: list[str]
    _stderr_lock: threading.Lock
    _stdout_thread: threading.Thread
    _stderr_thread: threading.Thread

    @classmethod
    def spawn(
        cls,
        command: list[str],
        *,
        cwd: str,
        env: dict[str, str] | None,
        abort_flag: threading.Event,
    ) -> RpcProcess:
        kwargs: dict[str, Any] = {}
        if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            env=env,
            bufsize=1,
            **kwargs,
        )
        frames: queue.Queue[object] = queue.Queue()
        stderr_chunks: list[str] = []
        stderr_lock = threading.Lock()
        stdout_thread = threading.Thread(target=_read_stdout, args=(proc, frames), daemon=True)
        stderr_thread = threading.Thread(
            target=_read_stderr, args=(proc, stderr_chunks, stderr_lock), daemon=True
        )
        stdout_thread.start()
        stderr_thread.start()
        return cls(
            proc=proc,
            frames=frames,
            abort_flag=abort_flag,
            _stderr_chunks=stderr_chunks,
            _stderr_lock=stderr_lock,
            _stdout_thread=stdout_thread,
            _stderr_thread=stderr_thread,
        )

    @property
    def stdin(self) -> TextIO:
        assert self.proc.stdin is not None
        return self.proc.stdin

    def send(self, obj: dict[str, Any]) -> None:
        try:
            self.stdin.write(json_line(obj))
            self.stdin.flush()
        except OSError as exc:
            raise ProviderError(f"OMP stdin closed: {exc}", reason="provider_error") from exc

    def wait_frame(self, deadline: float) -> dict[str, Any]:
        while True:
            if self.abort_flag.is_set():
                raise RpcAborted()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RpcTimeout(self._timeout_message())
            try:
                item = self.frames.get(timeout=min(0.1, remaining))
            except queue.Empty:
                code = self.proc.poll()
                if code is not None:
                    raise RpcExited(self._exit_message(code), returncode=code)
                continue
            if item is _STDOUT_CLOSED:
                code = self._wait_exit(timeout=0.25)
                raise RpcExited(self._exit_message(code), returncode=code)
            if isinstance(item, BaseException):
                raise ProviderError(f"OMP stdout reader failed: {item}", reason="provider_error") from item
            if not isinstance(item, dict):
                raise ProviderError("OMP stdout produced a non-object frame", reason="provider_error")
            return item

    def diagnostics(self) -> str:
        with self._stderr_lock:
            text = "".join(self._stderr_chunks)
        text = text.strip()
        if len(text) > 4000:
            text = text[-4000:]
        return redact_text(text)

    def close(self) -> None:
        if self.proc.stdin:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.kill()
        self._join_readers()

    def kill(self) -> None:
        if self.proc.poll() is None:
            try:
                self.proc.kill()
            except OSError:
                pass
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        self._join_readers()

    def _join_readers(self) -> None:
        self._stdout_thread.join(timeout=0.5)
        self._stderr_thread.join(timeout=0.5)

    def _wait_exit(self, timeout: float) -> int | None:
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return self.proc.poll()

    def _timeout_message(self) -> str:
        extra = self.diagnostics()
        suffix = f": {extra}" if extra else ""
        return f"OMP RPC timed out{suffix}"

    def _exit_message(self, code: int | None) -> str:
        extra = self.diagnostics()
        suffix = f": {extra}" if extra else ""
        return f"OMP RPC exited before agent_end (code={code}){suffix}"


def json_line(obj: dict[str, Any]) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False) + "\n"


def _read_stdout(proc: subprocess.Popen[str], frames: queue.Queue[object]) -> None:
    stdout = proc.stdout
    if stdout is None:
        frames.put(_STDOUT_CLOSED)
        return
    try:
        for raw in iter(stdout.readline, ""):
            line = raw.strip()
            if not line:
                continue
            try:
                import json

                frames.put(json.loads(line))
            except Exception as exc:  # noqa: BLE001 - reader must not die on one bad line
                frames.put(exc)
    except Exception as exc:  # noqa: BLE001
        frames.put(exc)
    finally:
        frames.put(_STDOUT_CLOSED)


def _read_stderr(proc: subprocess.Popen[str], chunks: list[str], lock: threading.Lock) -> None:
    stderr = proc.stderr
    if stderr is None:
        return
    try:
        while True:
            piece = stderr.readline()
            if not piece:
                return
            with lock:
                chunks.append(piece)
                size = sum(len(item) for item in chunks)
                while size > _STDERR_LIMIT and len(chunks) > 1:
                    size -= len(chunks.pop(0))
    except OSError:
        return
