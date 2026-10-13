# 本机执行环境：run 的工作区所在的环境。控制核心经合同与它往来（actions.py），不直接读写工作区文件：
# establish 从封存快照建立工作区，open 打开已经建立的工作区，perform 执行环境工具的动作并交回回执，
# cancel 按动作身份取消，query 提供工作区事实的只读查询，snapshot 交回交付封存所需的带文件内容的公开树，
# verify_tree 核对当前公开树仍与判断所依据的快照一致。
# 进程类动作（检查、bash 命令）以异步方式启动与等待；超时或取消时结束整个进程树，回执带截至结束时的输出；
# 取消在动作开始之前到达时不启动进程。

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from .actions import Action, ActionReceipt, FactsQuery, PathFacts, WorkspaceFacts
from .models import hash_bytes, json_dumps
from .public_tree import CapturedTree, UnrepresentableWorkspace, capture_public_tree, materialize_tree
from .definitions import DEFINITIONS, DefinitionError
from .path_rules import TreeError, is_private_path
from .redact import redact_text, sanitized_env
from .workspace import CHECKS_DIR, Workspace, WorkspaceSnapshot

# 一次工具结果的输出上限，取规则登记中的现值
_OUTPUT_LIMIT = DEFINITIONS.rule_value("tool_output_limit")
# 单页默认命中数；单页输出同样受 _OUTPUT_LIMIT 约束
SEARCH_DEFAULT_PAGE = 50
# 单行过长时保留的片段长度，避免一行占满整页输出
SEARCH_SNIPPET_LIMIT = 1000
# 超时与取消的退出码：124 与 timeout 命令相同，130 是被中断的进程的惯例
TIMEOUT_EXIT_CODE = 124
CANCELLED_EXIT_CODE = 130

_BASH_TIMEOUT_DEFAULT = DEFINITIONS.rule_value("bash_timeout_default_sec")
_BASH_TIMEOUT_MAX = DEFINITIONS.rule_value("bash_timeout_max_sec")
_PYTHON_NAMES = {"python", "python3", "py", "python.exe", "python3.exe"}

_BASH_PATH: str | None = None
_BASH_OUTPUT_SUBDIR = "tool-output"
_SAFE_OUTPUT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.json")
_TRUNCATED_MARKER = (
    f"\n...output truncated at {_OUTPUT_LIMIT} chars; the full output is saved, "
    "pass \"next_cursor\" back to bash as \"cursor\" to read the rest"
)


def _safe_output_name(action_id: str) -> str:
    # 存档文件名只留安全字符：游标回读时按同规则核对，防止路径穿越
    return re.sub(r"[^A-Za-z0-9_.-]", "_", action_id)[:80] or "output"


def _bash_slice(full: str, start: int) -> tuple[str, int | None]:
    # 从字符偏移 start 取一页：尽量在 _OUTPUT_LIMIT 个字符内不断行；
    # 取完返回 (剩余全文, None)，否则返回 (页, 下一页的字符偏移)
    end = start + _OUTPUT_LIMIT
    if end >= len(full):
        return full[start:], None
    newline = full.rfind("\n", start, end)
    cut = newline + 1 if newline > start else end
    return full[start:cut], cut


def _resolve_bash() -> str:
    # 找到可执行的 bash：Windows 上先看 Git 安装目录，再看 PATH；POSIX 上只认 /bin/bash。
    # 找不到就直接报错，不回退到 cmd 或 PowerShell。
    global _BASH_PATH
    if _BASH_PATH is not None:
        return _BASH_PATH
    if os.name == "nt":
        candidates = [
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\bin\bash.exe"),
            shutil.which("bash.exe"),
            shutil.which("bash"),
        ]
        for candidate in candidates:
            if candidate and os.path.isfile(candidate):
                _BASH_PATH = candidate
                return candidate
        raise FileNotFoundError("Git for Windows bash not found; install Git for Windows or add bash.exe to PATH")
    posix = "/bin/bash"
    if os.path.isfile(posix):
        _BASH_PATH = posix
        return posix
    raise FileNotFoundError(f"bash not found at {posix}")

# 环境工具与执行它的方法：直接执行的工具，与以进程执行、可以超时与取消的工具
_HANDLERS = {
    "read_file": "_read_file",
    "list_files": "_list_files",
    "search": "_search",
    "read_range": "_read_range",
    "write_file": "_write_file",
    "edit_range": "_edit_range",
    "delete_file": "_delete_file",
    "move_file": "_move_file",
}
_PROCESSES = {"run_check": "_run_check", "bash": "_bash"}

# 定义中的每个环境工具都要在这里有执行方法，否则启动失败
_UNIMPLEMENTED = sorted(name for name, tool in DEFINITIONS.tools.items()
                        if tool.kind == "environment" and name not in _HANDLERS and name not in _PROCESSES)
if _UNIMPLEMENTED:
    raise DefinitionError([("tools.json", name, "执行环境没有这个环境工具的实现") for name in _UNIMPLEMENTED])


@dataclass(frozen=True)
class _Finished:
    # 一个进程的结束：completed、timeout 或 cancelled，以及截至结束时的输出
    status: str
    returncode: int
    stdout: str
    stderr: str


class LocalEnvironment:
    def __init__(self, workspace: Workspace,
                 check_timeout_sec: int = DEFINITIONS.rule_value("check_timeout_sec"),
                 registered_commands: dict[str, Any] | None = None) -> None:
        # registered_commands 已不再使用：bash 替代 run_command 后登记命令没有执行入口；参数仅为兼容
        # orchestrator 等调用方，#484 删除注册体系时一并移除。传入值被忽略。
        self.workspace = workspace
        self._check_timeout_sec = check_timeout_sec
        # 正在进行的动作与它的停止信号；取消在动作开始之前到达时先记下，开始时不执行
        self._lock = Lock()
        self._running: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Event]] = {}
        self._cancelled: set[str] = set()
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            name: getattr(self, method) for name, method in _HANDLERS.items()}
        self._processes: dict[str, Callable[[Action, asyncio.Event], Awaitable[tuple[Any, str]]]] = {
            name: getattr(self, method) for name, method in _PROCESSES.items()}

    @classmethod
    def establish(cls, root: str | Path, tree: CapturedTree | None, *,
                  check_timeout_sec: int = DEFINITIONS.rule_value("check_timeout_sec")) -> LocalEnvironment:
        # 从封存快照建立工作区：快照给出时按它的内容新建目录并核对，没有快照时建立空的工作区
        if tree is not None:
            Path(root).parent.mkdir(parents=True, exist_ok=True)
            materialize_tree(tree, root)
        return cls(Workspace(root), check_timeout_sec=check_timeout_sec)

    @classmethod
    def open(cls, root: str | Path,
             check_timeout_sec: int = DEFINITIONS.rule_value("check_timeout_sec"),
             registered_commands: dict[str, Any] | None = None) -> LocalEnvironment:
        # 打开已经建立的工作区（registered_commands 兼容 #484 前的调用方，传入值被忽略）
        return cls(Workspace(root), check_timeout_sec=check_timeout_sec)
    def bind_check(self, *, activation_id: str | None, product_spec_hash: str | None,
                   delivery_spec_hash: str | None, effective_contract_hash: str | None = None) -> None:
        # 这次激活的运行状态身份随检查回执记录，供 U 判断回执是否属于当前有效的合同与快照
        self.workspace.bind_check(
            activation_id=activation_id, product_spec_hash=product_spec_hash,
            delivery_spec_hash=delivery_spec_hash, effective_contract_hash=effective_contract_hash,
        )

    def verify_tree(self, snapshot: WorkspaceSnapshot) -> None:
        # 交付核对：当前公开树仍与判断所依据的快照一致
        if self.workspace.snapshot().tree.manifest != snapshot.tree.manifest:
            raise TreeError("Public tree does not match the complete recorded manifest")

    async def perform(self, action: Action) -> ActionReceipt:
        # 工具的执行出错时回执为 failed，错误说明交回模型；工作区出现公开树无法表示的条目时
        # （UnrepresentableWorkspace），按原样传出，由步骤驱动以 workspace_unrepresentable 暂停运行
        process = self._processes.get(action.tool)
        handler = None if process is not None else self._handlers[action.tool]
        stop = asyncio.Event()
        with self._lock:
            if action.action_id in self._cancelled:
                self._cancelled.discard(action.action_id)
                return ActionReceipt(action_id=action.action_id, status="cancelled",
                                     error="The action was cancelled before it started.")
            self._running[action.action_id] = (asyncio.get_running_loop(), stop)
        try:
            if process is not None:
                result = await process(action, stop)
                # 登记命令结束后主机立即取得的公开树核对结果随回执交回：附在回执上，步骤驱动在
                # 回执照常记录之后按它以 workspace_unrepresentable 暂停
                output, status, workspace_error = result if len(result) == 3 else (*result, None)
                if workspace_error is not None:
                    output = {**output, "workspace_unrepresentable": workspace_error}
            else:
                output, status = handler(action.input), "completed"
        except UnrepresentableWorkspace:
            raise
        except Exception as exc:
            return ActionReceipt(action_id=action.action_id, status="failed", error=str(exc))
        finally:
            with self._lock:
                self._running.pop(action.action_id, None)
        return ActionReceipt(action_id=action.action_id, status=status, output=output)

    def cancel(self, action_id: str) -> None:
        # 可以从任何线程调用。在锁内安排停止：登记在动作结束时于它的事件循环中移除，持有锁期间事件循环一定仍在运行
        with self._lock:
            running = self._running.get(action_id)
            if running is None:
                self._cancelled.add(action_id)
                return
            loop, stop = running
            loop.call_soon_threadsafe(stop.set)

    def query(self, query: FactsQuery) -> WorkspaceFacts:
        tree = self.workspace.snapshot().facts if query.tree else None
        return WorkspaceFacts(tree=tree, paths={path: self._path(path) for path in query.paths})

    def snapshot(self) -> WorkspaceSnapshot:
        # 带文件内容的公开树与检查回执：提交交付时封存这份内容，判断使用同一次读取的事实（snapshot().facts）
        return self.workspace.snapshot()

    def _path(self, rel: str) -> PathFacts:
        # 规范形式：按公开树规则解析以后在工作区中的相对路径；私有、逃逸、链接与歧义的名称给出原因
        try:
            target = self.workspace.resolve(rel)
            canonical = target.relative_to(self.workspace.root).as_posix()
            kind = ("missing" if not os.path.lexists(target)
                    else "directory" if target.is_dir() else "file")
        except (OSError, ValueError) as exc:
            return PathFacts(error=str(exc))
        return PathFacts(canonical=canonical, kind=kind)

    def _read_file(self, args: dict[str, Any]) -> str:
        return self.workspace.read_file(str(args["path"]))

    def _list_files(self, args: dict[str, Any]) -> list[str]:
        prefix = args.get("prefix")
        return self.workspace.list_files(None if prefix in (None, "") else str(prefix))

    def _search(self, args: dict[str, Any]) -> dict[str, Any]:
        pattern = args.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            raise ValueError("search requires a non-empty pattern")
        compiled = re.compile(pattern)
        scope = args.get("path")
        scope_rel = None if scope in (None, "") else str(scope).rstrip("/")
        page_size = _page_size(args.get("max_results"))
        offset = 0
        cursor_arg = args.get("cursor")
        cursor: dict[str, Any] | None = None
        if cursor_arg not in (None, ""):
            cursor = _decode_cursor(str(cursor_arg), kind="search")
            if cursor.get("pattern") != pattern or cursor.get("path") != scope_rel or cursor.get("page_size") != page_size:
                raise ValueError("cursor does not match the current search arguments")
            offset = cursor["offset"]
        snapshot = self.workspace.snapshot()
        digest = snapshot.digest
        if cursor is not None and cursor.get("digest") != digest:
            raise ValueError("workspace changed since the cursor was issued; start a new search")
        if scope_rel is None:
            files = list(snapshot.tree.files)
        else:
            # 作用域同样走公开路径校验，私有、逃逸、链接与歧义路径直接报错
            target = self.workspace.resolve(scope_rel)
            if not os.path.lexists(target):
                raise FileNotFoundError(f"search scope not found: {scope_rel}")
            if target.is_dir():
                files = [item for item in snapshot.tree.files
                         if item.path == scope_rel or item.path.startswith(scope_rel + "/")]
            else:
                files = [item for item in snapshot.tree.files if item.path == scope_rel]
                if not files:
                    raise FileNotFoundError(f"search scope not found: {scope_rel}")
        matches: list[dict[str, Any]] = []
        for item in files:
            # 二进制内容按替换字符解码后同样参与匹配，作用域内不静默跳过任何文件
            for number, line in enumerate(item.data.decode("utf-8", errors="replace").splitlines(), 1):
                if compiled.search(line):
                    matches.append({"path": item.path, "line": number, "snippet": _clip_snippet(line)})
        page = matches[offset:offset + page_size]
        truncated = offset + len(page) < len(matches)
        page, truncated = _fit_match_page(page, truncated)
        return {
            "pattern": pattern,
            "path": scope_rel,
            "digest": digest,
            "matches": page,
            "total_matches": len(matches),
            "truncated": truncated,
            "next_cursor": _encode_cursor({
                "kind": "search", "pattern": pattern, "path": scope_rel,
                "page_size": page_size, "offset": offset + len(page), "digest": digest,
            }) if truncated else None,
        }

    def _read_range(self, args: dict[str, Any]) -> dict[str, Any]:
        rel = args.get("path")
        if not isinstance(rel, str) or not rel:
            raise ValueError("read_range requires a path")
        start = args.get("start_line")
        if type(start) is not int or start < 1:
            raise ValueError("start_line must be an integer >= 1")
        end = args.get("end_line")
        if end is not None and (type(end) is not int or end < start):
            raise ValueError("end_line must be an integer >= start_line")
        offset = start
        cursor: dict[str, Any] | None = None
        cursor_arg = args.get("cursor")
        if cursor_arg not in (None, ""):
            cursor = _decode_cursor(str(cursor_arg), kind="read_range")
            if cursor.get("path") != rel or cursor.get("start_line") != start or cursor.get("end_line") != end:
                raise ValueError("cursor does not match the current read_range arguments")
            offset = cursor["offset"]
        self.workspace.resolve_readable(rel)
        snapshot = self.workspace.snapshot()
        digest = snapshot.digest
        if cursor is not None and cursor.get("digest") != digest:
            raise ValueError("workspace changed since the cursor was issued; start a new read")
        raw = next((item.data for item in snapshot.tree.files if item.path == rel), None)
        if raw is None:
            raise FileNotFoundError(f"file not found: {rel}")
        # 与 read_file 一致使用严格解码，二进制内容直接报错而不猜测
        numbered = list(enumerate(raw.decode("utf-8").splitlines(), 1))
        total = len(numbered)
        wanted = [(number, text) for number, text in numbered if number >= offset and (end is None or number <= end)]
        entries, consumed = _fit_line_entries(wanted)
        truncated = consumed < len(wanted)
        next_offset = offset + consumed
        last = offset + consumed - 1
        return {
            "path": rel,
            "digest": digest,
            "content_hash": hash_bytes(raw),
            "start_line": offset,
            "end_line": last if consumed else min(total, offset - 1),
            "total_lines": total,
            "lines": entries,
            "truncated": truncated,
            "next_cursor": _encode_cursor({
                "kind": "read_range", "path": rel, "start_line": start, "end_line": end,
                "offset": next_offset, "digest": digest,
            }) if truncated else None,
        }

    def _write_file(self, args: dict[str, Any]) -> str:
        return self.workspace.write_file(str(args["path"]), str(args["content"]))

    def _edit_range(self, args: dict[str, Any]) -> dict[str, Any]:
        rel = args.get("path")
        if not isinstance(rel, str) or not rel:
            raise ValueError("edit_range requires a path")
        start = args.get("start_line")
        if type(start) is not int or start < 1:
            raise ValueError("start_line must be an integer >= 1")
        end = args.get("end_line")
        if type(end) is not int or end < start:
            raise ValueError("end_line must be an integer >= start_line")
        expected = args.get("expected_text")
        if not isinstance(expected, str) or not expected:
            raise ValueError("expected_text must be a non-empty string")
        new_text = args.get("new_text")
        if not isinstance(new_text, str):
            raise ValueError("new_text must be a string")
        expected_digest = args.get("expected_digest")
        if expected_digest is not None and (not isinstance(expected_digest, str) or not expected_digest):
            raise ValueError("expected_digest must be a file content hash string when given")
        for label, value in (("expected_text", expected), ("new_text", new_text)):
            try:
                value.encode("utf-8", errors="strict")
            except (UnicodeEncodeError, ValueError) as exc:
                raise ValueError(f"encoding difference: {label} cannot be encoded as UTF-8 identically") from exc
        # 路径校验复用公开树规则，私有、逃逸、链接与歧义名称直接报错；被忽略规则排除的路径拒绝编辑
        target = self.workspace.resolve_writable(rel)
        if not os.path.lexists(target):
            raise FileNotFoundError(f"file not found: {rel}")
        if not target.is_file():
            raise ValueError(f"edit_range requires an existing regular file: {rel}")
        snapshot = self.workspace.snapshot()
        raw = next((item.data for item in snapshot.tree.files if item.path == rel), None)
        if raw is None:
            raise FileNotFoundError(f"file not found: {rel}")
        # 文件级摘要只绑定目标文件，其它文件的改动不影响本次核对
        if expected_digest is not None and hash_bytes(raw) != expected_digest:
            raise ValueError("file changed since the read; re-read the span before editing")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError(f"encoding difference: {rel} is not valid UTF-8; re-read and use matching bytes") from exc
        # 与 read_range 一致按通用换行分行，落盘时保留原换行格式
        crlf = "\r\n" in text
        normalized = text.replace("\r\n", "\n")
        ends_newline = normalized.endswith(("\n", "\r"))
        # 与 read_range 同一切分口径，尾换行不计为一行
        file_lines = normalized.splitlines()
        total = len(file_lines)
        if end > total:
            raise ValueError(f"target span {start}-{end} does not exist in {rel} with {total} lines")
        current_span = "\n".join(file_lines[start - 1:end])
        if current_span != expected:
            raise ValueError("file changed since the read; re-read the span before editing")
        occurrences = normalized.count(expected)
        if occurrences != 1:
            raise ValueError(f"expected text matches {occurrences} times in {rel}; the span is ambiguous, re-read with a unique span")
        new_lines = new_text.split("\n")
        merged = file_lines[:start - 1] + new_lines + file_lines[end:]
        if not merged:
            new_raw = b""
        else:
            joined = "\n".join(merged)
            if crlf:
                joined = joined.replace("\n", "\r\n")
            new_raw = (joined + ("\r\n" if crlf else "\n") if ends_newline else joined).encode("utf-8")
        # 全部核对通过后才落盘；任一拒绝都不触碰文件字节
        self.workspace.resolve(rel).write_bytes(new_raw)
        final = self.workspace.snapshot()
        return {
            "path": rel,
            "start_line": start,
            "end_line": start + len(new_lines) - 1,
            "total_lines": len(merged),
            "digest": final.digest,
            "content_hash": hash_bytes(new_raw),
        }

    def _delete_file(self, args: dict[str, Any]) -> str:
        _require_reason(args)
        return self.workspace.delete_file(args["path"])

    def _move_file(self, args: dict[str, Any]) -> dict[str, str]:
        _require_reason(args)
        return self.workspace.move_file(args["source"], args["destination"])

    async def _bash(self, action: Action, stop: asyncio.Event) -> tuple[dict[str, Any], str, str | None]:
        args = action.input
        cursor_arg = args.get("cursor")
        if cursor_arg not in (None, ""):
            # 继续取回上次截断的完整输出：只读主机私有的存档，不启动新进程，不核对公开树
            return self._bash_continuation(str(cursor_arg)), "completed", None
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("bash requires a non-empty command string")
        timeout_sec = args.get("timeout_sec")
        if timeout_sec is None:
            timeout_sec = _BASH_TIMEOUT_DEFAULT
        else:
            if type(timeout_sec) is not int or timeout_sec < 1:
                raise ValueError("timeout_sec must be a positive integer")
            timeout_sec = min(timeout_sec, _BASH_TIMEOUT_MAX)
        # 模型自报 exit_code 不是证据：这里只读主机执行结果，从不读取该字段
        snapshot = self.workspace.snapshot()
        # 前置条件：工具许可所依据的公开树没有改变
        expected = action.preconditions.tree_digest
        if expected is not None and snapshot.digest != expected:
            raise ValueError("the workspace changed after the tool permission; call bash again")
        # 每次调用都是新进程，不保留 shell 状态；进程继承 Yudao 进程的完整环境。
        # 不用 -l：登录 shell 会读用户 profile，环境不可复现。
        finished = await _run_process(
            [_resolve_bash(), "-c", command], self.workspace.root,
            {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout_sec, stop,
        )
        text = "\n".join(part for part in (finished.stdout.strip(), finished.stderr.strip()) if part)
        if finished.status == "timeout":
            exit_code, status = TIMEOUT_EXIT_CODE, "timeout"
            text = ((text + "\n") if text else "") + f"command timed out after {timeout_sec}s; the process tree was stopped"
        elif finished.status == "cancelled":
            exit_code, status = CANCELLED_EXIT_CODE, "cancelled"
            text = ((text + "\n") if text else "") + "command cancelled; the process tree was stopped"
        else:
            exit_code = finished.returncode
            status = "ok" if exit_code == 0 else "failed"
        text = redact_text(text)
        meta = {"command": command, "exit_code": exit_code, "status": status,
                "snapshot_hash": snapshot.digest, "executor": "host"}
        output, truncated, next_cursor = self._bash_page(action.action_id, meta, text)
        # 命令结束后主机立即取的公开树核对。命令留下无法表示的条目（例如链接）时，核对结果随回执
        # 交回，步骤驱动在回执照常记录之后以 workspace_unrepresentable 暂停；被忽略的条目不进入
        # 公开树，核对通过
        workspace_error = None
        try:
            self.workspace.snapshot()
        except UnrepresentableWorkspace as exc:
            workspace_error = {"message": str(exc), "paths": list(exc.paths)}
        return {**meta, "output": output, "truncated": truncated, "next_cursor": next_cursor}, finished.status, workspace_error

    def _bash_page(self, action_id: str, meta: dict[str, Any], full: str) -> tuple[str, bool, str | None]:
        # 完整输出的第一页：超限时全文存主机私有的存档（公开树之外，不进入快照与交付），
        # 回执只带截断页与继续取回的游标；各页按字符直接拼接与原文逐字相等
        if len(full) <= _OUTPUT_LIMIT:
            return full, False, None
        directory = self.workspace.root / CHECKS_DIR / _BASH_OUTPUT_SUBDIR
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (_safe_output_name(action_id) + ".json")
        path.write_bytes(json.dumps({**meta, "full": full}, ensure_ascii=False).encode("utf-8"))
        page, next_start = _bash_slice(full, 0)
        if next_start is None:
            return page, False, None
        cursor = _encode_cursor({"kind": "bash_output", "name": path.name, "offset": next_start})
        return page + _TRUNCATED_MARKER, True, cursor

    def _bash_continuation(self, cursor: str) -> dict[str, Any]:
        payload = _decode_cursor(cursor, kind="bash_output")
        name = payload.get("name")
        offset = payload.get("offset")
        if (not isinstance(name, str) or not _SAFE_OUTPUT_NAME.fullmatch(name)
                or type(offset) is not int or offset < 0):
            raise ValueError("invalid bash output cursor")
        path = self.workspace.root / CHECKS_DIR / _BASH_OUTPUT_SUBDIR / name
        try:
            saved = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"saved bash output is no longer available: {name}") from exc
        full = saved.get("full")
        if not isinstance(full, str) or offset >= len(full):
            raise ValueError(f"saved bash output is no longer available: {name}")
        meta = {key: saved[key] for key in ("command", "exit_code", "status", "snapshot_hash", "executor")}
        page, next_start = _bash_slice(full, offset)
        if next_start is None:
            return {**meta, "output": page, "truncated": False, "next_cursor": None}
        next_cursor = _encode_cursor({"kind": "bash_output", "name": name, "offset": next_start})
        return {**meta, "output": page + _TRUNCATED_MARKER, "truncated": True, "next_cursor": next_cursor}

    async def _run_check(self, action: Action, stop: asyncio.Event) -> tuple[dict[str, Any], str]:
        args = action.input
        name = str(args.get("name") or "").strip()
        if not name:
            raise ValueError("check name is required")
        argv = _argv_from_args(args)
        snapshot = self.workspace.snapshot()
        original_digest = snapshot.digest
        with self.workspace.check_copy(snapshot.tree) as copy_root:
            resolved = _resolve_argv(self.workspace, argv, cwd=copy_root)
            finished = await _run_process(
                resolved, copy_root, {**sanitized_env(), "PYTHONDONTWRITEBYTECODE": "1"},
                self._check_timeout_sec, stop,
            )
            if finished.status == "completed":
                exit_code = finished.returncode
                output = _summarize_output(finished.stdout, finished.stderr)
            else:
                if finished.status == "timeout":
                    exit_code, output = TIMEOUT_EXIT_CODE, f"check timed out after {self._check_timeout_sec}s"
                else:
                    exit_code, output = CANCELLED_EXIT_CODE, "check cancelled; the process tree was stopped"
                if finished.stdout:
                    output += "\n" + finished.stdout
                if finished.stderr:
                    output += "\n" + finished.stderr
            snapshot_hash = original_digest
            verification_errors = []
            # A process result remains evidence even when its tested bytes cannot be verified.
            # 两处读取都按项目的忽略规则取得公开树；说明文字只出现标签，主机路径不进入模型可见的回执
            for label, root in (("tested tree", copy_root), ("source workspace", self.workspace.root)):
                try:
                    observed_digest = capture_public_tree(root, True).digest
                    if label == "tested tree":
                        snapshot_hash = observed_digest
                    if observed_digest != original_digest:
                        verification_errors.append(f"{label} changed")
                except Exception as exc:
                    verification_errors.append(f"{label} could not be verified: {exc}")
            tree_changed = bool(verification_errors)
            if tree_changed:
                output = (output + "\n" if output else "") + "; ".join(verification_errors)
                output += "; pass is not bound to the original snapshot"
            summary = redact_text(
                f"host-executed argv={_display_argv(resolved)} exit={exit_code}\n{output}".strip()
            )
            receipt = self.workspace.record_check(
                action.department,
                name,
                exit_code,
                summary,
                snapshot_hash=snapshot_hash,
                tree_changed=tree_changed,
            )
            return {
                "name": receipt.name,
                "exit_code": receipt.exit_code,
                "summary": receipt.summary,
                "snapshot_hash": receipt.snapshot_hash,
                "executor": "host",
                "tree_changed": receipt.tree_changed,
                "activation_id": receipt.activation_id,
                "product_spec_hash": receipt.product_spec_hash,
                "delivery_spec_hash": receipt.delivery_spec_hash,
                "effective_contract_hash": receipt.effective_contract_hash,
            }, finished.status


async def _run_process(argv: list[str], cwd: Path, env: dict[str, str], timeout_sec: float,
                       stop: asyncio.Event) -> _Finished:
    # 进程在新的进程组（Windows）或新的会话（POSIX）中启动，超时或停止信号到达时结束整个进程树，
    # 输出读到管道关闭为止：结束以后是截至结束时的输出。标准输入接空设备：bash 调用与检查都不读输入，
    # 若继承服务进程的标准输入（一根打开但无人写入的管道），解释器启动时对该句柄取状态会一直等待
    spawn: dict[str, Any] = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                             else {"start_new_session": True})
    process = await asyncio.create_subprocess_exec(
        *argv, cwd=str(cwd), env=env, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **spawn,
    )
    communicate = asyncio.ensure_future(process.communicate())
    stopped = asyncio.ensure_future(stop.wait())
    try:
        done, _pending = await asyncio.wait({communicate, stopped}, timeout=timeout_sec,
                                            return_when=asyncio.FIRST_COMPLETED)
    finally:
        stopped.cancel()
    if communicate in done:
        status = "completed"
    else:
        status = "cancelled" if stopped in done else "timeout"
        await _kill_process_tree(process)
    stdout, stderr = await communicate
    return _Finished(status, process.returncode, _text(stdout), _text(stderr))


async def _kill_process_tree(process: asyncio.subprocess.Process) -> None:
    # Windows 用 taskkill 按树结束；POSIX 结束整个会话的进程组，进程组已经不存在时没有需要结束的进程
    if os.name == "nt":
        killer = await asyncio.create_subprocess_exec(
            "taskkill", "/PID", str(process.pid), "/T", "/F",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await killer.wait()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _text(raw: bytes) -> str:
    # 与文本方式读取子进程输出相同：UTF-8 解码（无法解码的字节换成替换字符），换行统一为 \n
    return io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8", errors="replace", newline=None).read()


def _require_reason(args: dict[str, Any]) -> None:
    reason = args.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("a non-empty reason is required for deleting or moving files")


def _argv_from_args(args: dict[str, Any]) -> list[str]:
    if "argv" in args and args["argv"] not in (None, ""):
        argv = args["argv"]
        if not isinstance(argv, list) or not argv or any(not isinstance(item, str) or not item.strip() for item in argv):
            raise ValueError("argv must be a non-empty list of strings")
        return [item.strip() for item in argv]
    command = args.get("command")
    if isinstance(command, list):
        if not command or any(not isinstance(item, str) or not item.strip() for item in command):
            raise ValueError("command must be a non-empty list of strings")
        return [item.strip() for item in command]
    if isinstance(command, str) and command.strip():
        parts = shlex.split(command, posix=False)
        if not parts:
            raise ValueError("command is empty")
        return parts
    raise ValueError("run_check requires host-executed argv or command; exit_code is not evidence")


def _resolve_argv(workspace: Workspace, argv: list[str], *, cwd: Path | None = None) -> list[str]:
    for item in argv:
        if ".." in Path(item).parts or is_private_path(item):
            raise PermissionError("check argv cannot reference private or parent paths")
    prog = argv[0]
    name = Path(prog).name.lower()
    if name in _PYTHON_NAMES:
        return [sys.executable, *argv[1:]]
    if Path(prog).is_absolute():
        resolved = Path(prog).resolve()
        if resolved != Path(sys.executable).resolve():
            raise PermissionError("absolute executables other than the host python are not allowed")
        return [str(resolved), *argv[1:]]
    base = cwd if cwd is not None else workspace.root
    path = (base / prog)
    if not path.exists():
        raise FileNotFoundError(f"check program not in workspace: {prog}")
    return [str(path), *argv[1:]]


def _display_argv(argv: list[str]) -> str:
    shown = []
    for index, item in enumerate(argv):
        if index == 0 and Path(item).resolve() == Path(sys.executable).resolve():
            shown.append("python")
        else:
            shown.append(item)
    return json_dumps(shown)


def _summarize_output(stdout: str, stderr: str) -> str:
    text = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part)
    if len(text) > _OUTPUT_LIMIT:
        text = text[:_OUTPUT_LIMIT] + "\n...truncated..."
    return text


def _page_size(value: Any) -> int:
    if value is None:
        return SEARCH_DEFAULT_PAGE
    if type(value) is not int or value < 1:
        raise ValueError("max_results must be an integer >= 1")
    return value


def _clip_snippet(line: str) -> str:
    if len(line) > SEARCH_SNIPPET_LIMIT:
        return line[:SEARCH_SNIPPET_LIMIT] + "\n...truncated..."
    return line


def _encode_cursor(payload: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json_dumps(payload).encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str, *, kind: str) -> dict[str, Any]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"invalid cursor: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("kind") != kind or type(payload.get("offset")) is not int:
        raise ValueError("invalid cursor")
    return payload


def _result_size(result: dict[str, Any]) -> int:
    return len(json_dumps(result))


def _fit_match_page(page: list[dict[str, Any]], truncated: bool) -> tuple[list[dict[str, Any]], bool]:
    # 按输出上限收缩本页，挤出去的命中留给下一页游标，不丢弃也不合并
    probe = {"matches": page}
    while len(page) > 1 and _result_size({**probe, "truncated": True}) > _OUTPUT_LIMIT:
        page = page[:-1]
        truncated = True
    if len(page) == 1 and _result_size({"matches": page, "truncated": True}) > _OUTPUT_LIMIT:
        only = dict(page[0])
        snippet = only["snippet"]
        while len(snippet) > 1 and _result_size({"matches": [{**only, "snippet": snippet}], "truncated": True}) > _OUTPUT_LIMIT:
            snippet = snippet[:len(snippet) // 2]
        only["snippet"] = snippet + "\n...truncated..."
        page = [only]
        truncated = True
    return page, truncated


def _fit_line_entries(wanted: list[tuple[int, str]]) -> tuple[list[dict[str, Any]], int]:
    # 逐行累加直到输出上限；单行超限则截断该行文本，保证每页至少返回一行或空
    entries: list[dict[str, Any]] = []
    for number, text in wanted:
        candidate = entries + [{"line": number, "text": text}]
        if _result_size({"lines": candidate, "truncated": True}) > _OUTPUT_LIMIT:
            break
        entries = candidate
    if not entries and wanted:
        number, text = wanted[0]
        clipped = text
        while len(clipped) > 1 and _result_size({"lines": [{"line": number, "text": clipped}], "truncated": True}) > _OUTPUT_LIMIT:
            clipped = clipped[:len(clipped) // 2]
        entries = [{"line": number, "text": clipped + "\n...truncated..."}]
        return entries, 1
    return entries, len(entries)
