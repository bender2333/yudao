"""部门工具白名单。Product/Quality 无写工具，Engineering 才有写工具。检查由主机执行。"""

from __future__ import annotations

import base64
import json
import os
import re
import shlex
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .models import hash_bytes, json_dumps
from .public_tree import capture_public_tree, is_private_path
from .redact import redact_text, sanitized_env
from .workspace import Workspace

CHECK_TIMEOUT_SEC = 30
CHECK_OUTPUT_LIMIT = 4000
# 单页默认命中数；单页输出同样受 CHECK_OUTPUT_LIMIT 约束
SEARCH_DEFAULT_PAGE = 50
# 单行过长时保留的片段长度，避免一行占满整页输出
SEARCH_SNIPPET_LIMIT = 1000

TOOL_DEFS = {
    "read_file": {"access": "read", "departments": ("product", "engineering", "quality")},
    "list_files": {"access": "read", "departments": ("product", "engineering", "quality")},
    "search": {"access": "read", "departments": ("product", "engineering", "quality")},
    "read_range": {"access": "read", "departments": ("product", "engineering", "quality")},
    "write_file": {"access": "write", "departments": ("engineering",)},
    "edit_range": {"access": "write", "departments": ("engineering",)},
    "delete_file": {"access": "write", "departments": ("engineering",)},
    "move_file": {"access": "write", "departments": ("engineering",)},
    "run_check": {"access": "check", "departments": ("product", "engineering", "quality")},
    "run_command": {"access": "check", "departments": ("engineering",)},
    "submit_product_spec": {"access": "submit", "departments": ("product",)},
    "submit_product_decision": {"access": "submit", "departments": ("product",)},
    "submit_request": {"access": "submit", "departments": ("product", "engineering", "quality")},
    "submit_response": {"access": "submit", "departments": ("product", "engineering", "quality")},
    "submit_guidance_response": {"access": "submit", "departments": ("product", "engineering", "quality")},
    "submit_plan": {"access": "submit", "departments": ("engineering",)},
    "submit_delivery": {"access": "submit", "departments": ("engineering",)},
    "submit_review": {"access": "submit", "departments": ("quality",)},
}

SUBMIT_KINDS = {
    "submit_product_spec": "product_spec",
    "submit_product_decision": "product_decision",
    "submit_request": "collaboration_request",
    "submit_response": "collaboration_response",
    "submit_guidance_response": "department_guidance_response",
    "submit_plan": "engineering_plan",
    "submit_delivery": "delivery_spec",
    "submit_review": "qa_review",
}

_PYTHON_NAMES = {"python", "python3", "py", "python.exe", "python3.exe"}

# 登记命令名只允许简单标识，避免路径与 shell 元字符进入注册表
_COMMAND_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
# 超时上限 10 分钟：登记命令是受信构建/测试入口，不是常驻服务
COMMAND_TIMEOUT_MAX_SEC = 600


def validate_registered_command(name: str, config: dict[str, Any]) -> dict[str, Any]:
    # 校验一条项目登记命令，返回冻结用的规范形态；任一非法直接报错
    if not isinstance(name, str) or not _COMMAND_NAME_PATTERN.fullmatch(name):
        raise ValueError("command name must match [A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
    if not isinstance(config, dict):
        raise ValueError(f"registered command {name} must be an object")
    argv = config.get("argv")
    if not isinstance(argv, list) or not argv or any(not isinstance(item, str) or not item for item in argv):
        raise ValueError(f"registered command {name} requires a non-empty argv list of strings")
    extra_args = config.get("args", [])
    if not isinstance(extra_args, list) or any(not isinstance(item, str) or not item for item in extra_args):
        raise ValueError(f"registered command {name} allowlist args must be a list of non-empty strings")
    timeout_sec = config.get("timeout_sec", CHECK_TIMEOUT_SEC)
    if type(timeout_sec) is not int or not 1 <= timeout_sec <= COMMAND_TIMEOUT_MAX_SEC:
        raise ValueError(f"registered command {name} timeout_sec must be an integer in 1..{COMMAND_TIMEOUT_MAX_SEC}")
    output_limit = config.get("output_limit", CHECK_OUTPUT_LIMIT)
    if type(output_limit) is not int or output_limit < 1:
        raise ValueError(f"registered command {name} output_limit must be an integer >= 1")
    return {"argv": list(argv), "args": list(extra_args), "timeout_sec": timeout_sec, "output_limit": output_limit}


def normalize_registered_commands(registry: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    # 冻结注册表逐条校验并规范化；空注册表表示本轮没有可用命令
    if registry is None:
        return {}
    if not isinstance(registry, dict):
        raise ValueError("registered_commands must be an object")
    return {name: validate_registered_command(name, config) for name, config in registry.items()}


@dataclass(frozen=True)
class ToolResult:
    name: str
    ok: bool
    output: Any
    error: str | None = None


def tools_for(department: str) -> list[str]:
    return [name for name, spec in TOOL_DEFS.items() if department in spec["departments"]]


def has_tool(department: str, name: str) -> bool:
    spec = TOOL_DEFS.get(name)
    return bool(spec and department in spec["departments"])


def host_tool_definitions(tool_names: list[str]) -> list[dict[str, Any]]:
    return [dict(HOST_TOOL_SCHEMAS[name]) for name in tool_names if name in HOST_TOOL_SCHEMAS]


class ToolRuntime:
    def __init__(self, workspace: Workspace, registered_commands: dict[str, Any] | None = None) -> None:
        self.workspace = workspace
        self._registered_commands = normalize_registered_commands(registered_commands)
        self._command_attempts: dict[str, int] = {}
        self._handlers: dict[str, Callable[..., Any]] = {
            "read_file": self._read_file,
            "list_files": self._list_files,
            "search": self._search,
            "read_range": self._read_range,
            "write_file": self._write_file,
            "edit_range": self._edit_range,
            "delete_file": self._delete_file,
            "move_file": self._move_file,
            "run_check": self._run_check,
            "run_command": self._run_command,
            "submit_product_spec": self._submit,
            "submit_product_decision": self._submit,
            "submit_request": self._submit,
            "submit_response": self._submit,
            "submit_guidance_response": self._submit,
            "submit_plan": self._submit,
            "submit_delivery": self._submit,
            "submit_review": self._submit,
        }

    def execute(self, department: str, name: str, args: dict[str, Any] | None = None) -> ToolResult:
        args = dict(args or {})
        if not has_tool(department, name):
            return ToolResult(name, False, None, f"{department} cannot use {name}")
        handler = self._handlers.get(name)
        if handler is None:
            return ToolResult(name, False, None, f"unknown tool {name}")
        try:
            if name in SUBMIT_KINDS:
                output = handler(department, name, args)
            else:
                output = handler(department, args)
            return ToolResult(name, True, output)
        except Exception as exc:
            return ToolResult(name, False, None, str(exc))

    def _read_file(self, department: str, args: dict[str, Any]) -> str:
        return self.workspace.read_file(str(args["path"]))

    def _list_files(self, department: str, args: dict[str, Any]) -> list[str]:
        prefix = args.get("prefix")
        return self.workspace.list_files(None if prefix in (None, "") else str(prefix))

    def _search(self, department: str, args: dict[str, Any]) -> dict[str, Any]:
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

    def _read_range(self, department: str, args: dict[str, Any]) -> dict[str, Any]:
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
        self.workspace.resolve(rel)
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

    def _write_file(self, department: str, args: dict[str, Any]) -> str:
        return self.workspace.write_file(str(args["path"]), str(args["content"]))

    def _edit_range(self, department: str, args: dict[str, Any]) -> dict[str, Any]:
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
        # 路径校验复用公开树规则，私有、逃逸、链接与歧义名称直接报错
        target = self.workspace.resolve(rel)
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

    def _delete_file(self, department: str, args: dict[str, Any]) -> str:
        _require_reason(args)
        return self.workspace.delete_file(args["path"])

    def _move_file(self, department: str, args: dict[str, Any]) -> dict[str, str]:
        _require_reason(args)
        return self.workspace.move_file(args["source"], args["destination"])

    def _run_check(self, department: str, args: dict[str, Any]) -> dict[str, Any]:
        return self._execute_check(department, args)

    def _run_command(self, department: str, args: dict[str, Any]) -> dict[str, Any]:
        name = args.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("run_command requires a registered command name")
        entry = self._registered_commands.get(name)
        if entry is None:
            raise ValueError(f"unknown registered command: {name}; only project-registered commands may run")
        extra = args.get("args", [])
        if extra is None:
            extra = []
        if not isinstance(extra, list) or any(not isinstance(item, str) for item in extra):
            raise ValueError(f"run_command {name} args must be a list of strings")
        for item in extra:
            if item not in entry["args"]:
                raise ValueError(f"argument not allowlisted for {name}: {item}")
        # 模型自报 exit_code 不是证据：这里只读登记表与主机执行结果，从不读取该字段
        argv = [*entry["argv"], *extra]
        resolved = _resolve_argv(self.workspace, argv)
        snapshot = self.workspace.snapshot()
        attempt = self._command_attempts.get(name, 0) + 1
        self._command_attempts[name] = attempt
        outcome = _run_process_tree(
            resolved, self.workspace.root,
            {**sanitized_env(), "PYTHONDONTWRITEBYTECODE": "1"},
            entry["timeout_sec"], entry["output_limit"],
        )
        return {
            "name": name,
            "argv": argv,
            "exit_code": outcome["exit_code"],
            "status": outcome["status"],
            "output": outcome["output"],
            "truncated": outcome["truncated"],
            "snapshot_hash": snapshot.digest,
            "executor": "host",
            "attempt": attempt,
        }

    def _submit(self, department: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
        payload = dict(args)
        payload["kind"] = SUBMIT_KINDS[name]
        payload.pop("exit_code", None)
        return payload

    def _execute_check(self, department: str, args: dict[str, Any]) -> dict[str, Any]:
        name = str(args.get("name") or "").strip()
        if not name:
            raise ValueError("check name is required")
        argv = _argv_from_args(args)
        snapshot = self.workspace.snapshot()
        original_digest = snapshot.digest
        with self.workspace.check_copy(snapshot.tree) as copy_root:
            resolved = _resolve_argv(self.workspace, argv, cwd=copy_root)
            try:
                completed = subprocess.run(
                    resolved,
                    cwd=str(copy_root),
                    env={**sanitized_env(), "PYTHONDONTWRITEBYTECODE": "1"},
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=CHECK_TIMEOUT_SEC,
                )
                exit_code = int(completed.returncode)
                output = _summarize_output(completed.stdout, completed.stderr)
            except subprocess.TimeoutExpired as exc:
                exit_code = 124
                output = f"check timed out after {CHECK_TIMEOUT_SEC}s"
                if exc.stdout:
                    output += "\n" + _decode(exc.stdout)
                if exc.stderr:
                    output += "\n" + _decode(exc.stderr)
            snapshot_hash = original_digest
            verification_errors = []
            # A process result remains evidence even when its tested bytes cannot be verified.
            for label, root in (("tested tree", copy_root), ("source workspace", self.workspace.root)):
                try:
                    observed_digest = capture_public_tree(root).digest
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
                department,
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
                "product_spec_hash": receipt.product_spec_hash,
                "delivery_spec_hash": receipt.delivery_spec_hash,
                "activation_id": receipt.activation_id,
                "effective_contract_hash": receipt.effective_contract_hash,
                "engineering_plan_hash": receipt.engineering_plan_hash,
            }


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
    python = Path(sys.executable).name
    for index, item in enumerate(argv):
        if index == 0 and Path(item).resolve() == Path(sys.executable).resolve():
            shown.append(python)
        else:
            shown.append(item)
    return json_dumps(shown)


def _summarize_output(stdout: str, stderr: str) -> str:
    text = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part)
    if len(text) > CHECK_OUTPUT_LIMIT:
        text = text[:CHECK_OUTPUT_LIMIT] + "\n...truncated..."
    return text


def _run_process_tree(argv: list[str], cwd: Path, env: dict[str, str],
                      timeout_sec: int, output_limit: int) -> dict[str, Any]:
    # 登记命令固定工作目录与最简环境执行；超时后整棵进程树必须停止，不留孤儿
    spawn_kwargs: dict[str, Any] = {}
    if os.name == "nt":
        spawn_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        spawn_kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        argv, cwd=str(cwd), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        **spawn_kwargs,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_sec)
        exit_code = int(proc.returncode)
        status = "ok" if exit_code == 0 else "failed"
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        stdout, stderr = proc.communicate()
        exit_code = 124
        status = "timeout"
    text = "\n".join(part for part in ((stdout or "").strip(), (stderr or "").strip()) if part)
    truncated = False
    if len(text) > output_limit:
        text = text[:output_limit] + "\n...truncated..."
        truncated = True
    if status == "timeout":
        text = ((text + "\n") if text else "") + f"command timed out after {timeout_sec}s; the process tree was stopped"
    return {"exit_code": exit_code, "status": status, "output": redact_text(text), "truncated": truncated}


def _kill_process_tree(proc: subprocess.Popen[str]) -> None:
    # Windows 用 taskkill 按树杀，POSIX 杀整个会话进程组；两边都处理显式分支
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)


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
    while len(page) > 1 and _result_size({**probe, "truncated": True}) > CHECK_OUTPUT_LIMIT:
        page = page[:-1]
        truncated = True
    if len(page) == 1 and _result_size({"matches": page, "truncated": True}) > CHECK_OUTPUT_LIMIT:
        only = dict(page[0])
        snippet = only["snippet"]
        while len(snippet) > 1 and _result_size({"matches": [{**only, "snippet": snippet}], "truncated": True}) > CHECK_OUTPUT_LIMIT:
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
        if _result_size({"lines": candidate, "truncated": True}) > CHECK_OUTPUT_LIMIT:
            break
        entries = candidate
    if not entries and wanted:
        number, text = wanted[0]
        clipped = text
        while len(clipped) > 1 and _result_size({"lines": [{"line": number, "text": clipped}], "truncated": True}) > CHECK_OUTPUT_LIMIT:
            clipped = clipped[:len(clipped) // 2]
        entries = [{"line": number, "text": clipped + "\n...truncated..."}]
        return entries, 1
    return entries, len(entries)


def _decode(raw: str | bytes | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw


def _object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _string_list_schema(description: str) -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}, "description": description}


HOST_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "read_file": {
        "name": "read_file",
        "label": "read_file",
        "description": "Return the entire content of one public workspace file as a single UTF-8 string, without line numbers or truncation. Files that are not valid UTF-8 are rejected. Paths under .checks are host-private. Use read_range for large files, or when you need line numbers and the content_hash that edit_range checks.",
        "parameters": _object_schema({"path": {"type": "string", "description": "Workspace-relative file path"}}, ["path"]),
        "loadMode": "essential",
    },
    "list_files": {
        "name": "list_files",
        "label": "list_files",
        "description": "List every file in the public workspace tree, recursively, as workspace-relative paths. prefix filters by plain string prefix on those paths: \"src/\" keeps only the src directory, while \"src\" also keeps paths such as \"src2/a.py\". Paths under .checks are never listed.",
        "parameters": _object_schema({"prefix": {"type": "string", "description": "Optional string prefix on workspace-relative paths; end it with / to limit the list to one directory"}}),
        "loadMode": "essential",
    },
    "search": {
        "name": "search",
        "label": "search",
        "description": "Search public workspace files with a Python re regex. Returns path, 1-based line and snippet per match with the snapshot digest. Large results are truncated with next_cursor.",
        "parameters": _object_schema(
            {
                "pattern": {"type": "string", "description": "Python re regex searched per line"},
                "path": {"type": ["string", "null"], "description": "Optional file or directory scope within the public tree"},
                "max_results": {"type": ["integer", "null"], "description": "Maximum matches per page"},
                "cursor": {"type": ["string", "null"], "description": "Continuation cursor from a truncated search"},
            },
            ["pattern"],
        ),
        "loadMode": "essential",
    },
    "read_range": {
        "name": "read_range",
        "label": "read_range",
        "description": "Read a line range of one public workspace file. Returns path, start_line, end_line, total_lines, the snapshot digest and the file content_hash. Truncated output carries next_cursor.",
        "parameters": _object_schema(
            {
                "path": {"type": "string", "description": "Workspace-relative file path"},
                "start_line": {"type": "integer", "description": "First line to read, 1-based"},
                "end_line": {"type": ["integer", "null"], "description": "Last line to read, inclusive; omit for end of file"},
                "cursor": {"type": ["string", "null"], "description": "Continuation cursor from a truncated read"},
            },
            ["path", "start_line"],
        ),
        "loadMode": "essential",
    },
    "write_file": {
        "name": "write_file",
        "label": "write_file",
        "description": "Create one public workspace file or replace its entire content with UTF-8 text; missing parent directories are created. Engineering only. Requires an accepted engineering plan for the current effective contract, and the path must be inside that plan's scope; otherwise the call is rejected and nothing is written. Paths under .checks are host-private. Use edit_range to change part of an existing file.",
        "parameters": _object_schema(
            {
                "path": {"type": "string", "description": "Workspace-relative file path"},
                "content": {"type": "string", "description": "Full file contents"},
            },
            ["path", "content"],
        ),
        "loadMode": "essential",
    },
    "edit_range": {
        "name": "edit_range",
        "label": "edit_range",
        "description": "Replace an exact original line span inside one public workspace file. Engineering only. The span must equal expected_text exactly, expected_text must occur exactly once in the file, and expected_digest (the read_range file content_hash) must still match when given; otherwise the edit is rejected and the file is left unchanged. Requires an accepted engineering plan for the current effective contract, and the path must be inside that plan's scope.",
        "parameters": _object_schema(
            {
                "path": {"type": "string", "description": "Workspace-relative file path"},
                "start_line": {"type": "integer", "description": "First line to replace, 1-based"},
                "end_line": {"type": "integer", "description": "Last line to replace, inclusive"},
                "expected_text": {"type": "string", "description": "Exact original lines previously read, joined by newline without a trailing newline"},
                "new_text": {"type": "string", "description": "Replacement text for the span, lines joined by newline"},
                "expected_digest": {"type": ["string", "null"], "description": "File content_hash observed when the span was read; omit to skip the digest check"},
            },
            ["path", "start_line", "end_line", "expected_text", "new_text"],
        ),
        "loadMode": "essential",
    },
    "delete_file": {        "name": "delete_file",
        "label": "delete_file",
        "description": "Delete one existing regular workspace file within the effective engineering plan. Engineering only; requires a reason. Directories and links are rejected.",
        "parameters": _object_schema(
            {"path": {"type": "string"}, "reason": {"type": "string", "minLength": 1}},
            ["path", "reason"],
        ),
        "loadMode": "essential",
    },
    "move_file": {
        "name": "move_file",
        "label": "move_file",
        "description": "Move one existing regular workspace file without overwriting. Both paths must be in the effective engineering plan. Engineering only; requires a reason. Directories and links are rejected.",
        "parameters": _object_schema(
            {"source": {"type": "string"}, "destination": {"type": "string"},
             "reason": {"type": "string", "minLength": 1}},
            ["source", "destination", "reason"],
        ),
        "loadMode": "essential",
    },
    "run_check": {
        "name": "run_check",
        "label": "run_check",
        "description": "Host-executes a check in the workspace and records exit_code, summary, and snapshot hash. Do not self-report exit_code. argv example: [\"python\", \"src/echo.py\", \"hello\"].",
        "parameters": _object_schema(
            {
                "name": {"type": "string", "description": "Check name, e.g. smoke"},
                "argv": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Argument vector executed by the host, e.g. [\"python\", \"src/echo.py\", \"hello\"]",
                },
            },
            ["name", "argv"],
        ),
        "loadMode": "essential",
    },
    "run_command": {
        "name": "run_command",
        "label": "run_command",
        "description": "Engineering-only: run one project-registered command in the run workspace with a stripped environment, time limit, output limit, and process-tree cleanup. Only the registered name and allowlisted extra args are accepted. The host-observed exit status is the evidence; a self-reported exit_code is never read.",
        "parameters": _object_schema(
            {
                "name": {"type": "string", "description": "Registered command name frozen for this run"},
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Extra arguments; every item must be in the registered allowlist",
                },
            },
            ["name"],
        ),
        "loadMode": "essential",
    },
    "submit_product_spec": {
        "name": "submit_product_spec",
        "label": "submit_product_spec",
        "description": "Submit a ProductSpec. Required: goal, requirements, acceptance_criteria.",
        "parameters": _object_schema(
            {
                "goal": {"type": "string"},
                "requirements": _string_list_schema("Must contain at least one item"),
                "acceptance_criteria": _string_list_schema("Must contain at least one item"),
                "boundaries": _string_list_schema("Optional"),
                "constraints": _string_list_schema("Optional"),
                "fatal_conditions": _string_list_schema("Optional"),
                "non_goals": _string_list_schema("Optional"),
                "change_record": {
                    **_object_schema(
                        {
                            "changed": _string_list_schema("Requirements added or changed in this revision"),
                            "retained": _string_list_schema("Requirements explicitly preserved"),
                            "retired": _string_list_schema("Requirements explicitly removed"),
                            "rationale": {"type": "string", "minLength": 1},
                        },
                        ["changed", "retained", "retired", "rationale"],
                    ),
                    "description": "Required when replacing a ProductSpec. Submit the complete new requirements and explain changed, retained, and retired behavior. A complete ProductSpec processes user input; a response or product decision does not. Omit on the first spec.",
                },
                "decision_changes": {
                    "type": "array",
                    "items": _object_schema({
                        "decision_hash": {"type": "string"},
                        "disposition": {"type": "string", "enum": ["retain", "integrate", "retire"]},
                        "rationale": {"type": "string"},
                    }, ["decision_hash", "disposition", "rationale"]),
                    "description": "When replacing a spec, explicitly retain, integrate, or retire every effective product decision. Empty for the first spec.",
                },
            },
            ["goal", "requirements", "acceptance_criteria"],
        ),
        "loadMode": "essential",
    },
    "submit_product_decision": {
        "name": "submit_product_decision",
        "label": "submit_product_decision",
        "description": "Publish an explicit product requirement decision with its rationale. This changes the effective contract. A consultation response alone does not change product requirements.",
        "parameters": _object_schema(
            {"statement": {"type": "string"}, "rationale": {"type": "string"}},
            ["statement", "rationale"],
        ),
        "loadMode": "essential",
    },
    "submit_request": {
        "name": "submit_request",
        "label": "submit_request",
        "description": "Ask another department for consultation or a concrete action. The recipient responds before the requester resumes. Only one request may be pending; consultation does not authorize delivery changes.",
        "parameters": _object_schema(
            {
                "recipient": {"type": "string", "enum": ["product", "engineering", "quality"]},
                "request_type": {"type": "string", "enum": ["consultation", "action"]},
                "question": {"type": "string"},
                "background": {"type": "string"},
                "expected_result": {"type": "string"},
                "action": {"type": ["string", "null"], "enum": [None, "inspect", "check", "revise_requirements", "revise_delivery"]},
            },
            ["recipient", "request_type", "question", "background", "expected_result", "action"],
        ),
        "loadMode": "essential",
    },
    "submit_response": {
        "name": "submit_response",
        "label": "submit_response",
        "description": "Respond to the pending request addressed to your department. For completed actions, first produce normal accepted artifacts or host checks and cite their actual event IDs. Do not invent evidence or use a response as a product decision.",
        "parameters": _object_schema(
            {
                "request_id": {"type": "string"},
                "status": {"type": "string", "enum": ["answered", "completed", "declined", "needs_work"]},
                "text": {"type": "string"},
                "result_event_ids": _string_list_schema("Actual accepted result or host tool event IDs for this request"),
            },
            ["request_id", "status", "text", "result_event_ids"],
        ),
        "loadMode": "essential",
    },
    "submit_guidance_response": {
        "name": "submit_guidance_response",
        "label": "submit_guidance_response",
        "description": "Respond to one persisted department guidance item. Use explained when the handling is an explanation, no change is required, or this department cannot apply it. Use completed only when host-verified actions after this guidance was adopted are listed in guidance_results; the host binds those results and result_event_ids cannot enlarge that set. Empty, rejected, failed, or earlier-unrelated results cannot complete an action. This response does not change the contract, plan, files, or QA result by itself.",
        "parameters": _object_schema(
            {
                "guidance_id": {"type": "string"},
                "status": {"type": "string", "enum": ["explained", "completed", "declined", "needs_work"]},
                "text": {"type": "string"},
                "result_event_ids": _string_list_schema("Optional. completed must be a subset of guidance_results; the host binds those results. explained, declined, and needs_work do not require results."),
            },
            ["guidance_id", "status", "text", "result_event_ids"],
        ),
        "loadMode": "essential",
    },
    "submit_plan": {
        "name": "submit_plan",
        "label": "submit_plan",
        "description": "Submit an engineering plan before changing delivery files. The host binds it to the current effective contract. Plan adjustments require a reason; product requirements must be decided by product.",
        "parameters": _object_schema(
            {
                "objective": {"type": "string"},
                "scope": _string_list_schema("Relative files or directories ending with /; . means the entire public workspace"),
                "tasks": {
                    "type": "array",
                    "items": _object_schema(
                        {
                            "title": {"type": "string"},
                            "outputs": _string_list_schema("Observable outputs of this task"),
                            "verification": {"type": "string", "description": "How to verify these outputs"},
                        },
                        ["title", "outputs", "verification"],
                    ),
                    "description": "Non-empty tasks in execution order",
                },
                "refactoring": _string_list_schema("Necessary structural changes, or an empty list"),
                "assumptions": {
                    "type": "array",
                    "items": _object_schema(
                        {"decision": {"type": "string"}, "basis": {"type": "string"}},
                        ["decision", "basis"],
                    ),
                    "description": "Professional defaults and their basis; do not present defaults as user statements",
                },
                "reason": {"type": "string", "description": "Reason for adjusting an existing plan; may be empty for the first plan"},
            },
            ["objective", "scope", "tasks", "refactoring", "assumptions", "reason"],
        ),
        "loadMode": "essential",
    },
    "submit_delivery": {
        "name": "submit_delivery",
        "label": "submit_delivery",
        "description": "Submit a DeliverySpec after writing files and running checks. Every name in check_names must be a name you passed to run_check in this activation on the current workspace; receipts from earlier activations are not reused, and if any file changes after a check, call run_check again before submitting. run_command results are action receipts and are not accepted as delivery check receipts. A name without a matching run_check receipt rejects the delivery.",
        "parameters": _object_schema(
            {
                "summary": {"type": "string"},
                "files": _string_list_schema("Workspace-relative files included in the delivery"),
                "check_names": _string_list_schema("Names passed to run_check in this activation on the current workspace; run_command results do not count"),
                "known_risks": _string_list_schema("Optional"),
            },
            ["summary", "files", "check_names"],
        ),
        "loadMode": "essential",
    },
    "submit_review": {
        "name": "submit_review",
        "label": "submit_review",
        "description": "Submit a QAReview. release requires quality-run host receipts with exit_code 0 on the current snapshot. Engineering receipts are not accepted as QA evidence. checks are check names.",
        "parameters": _object_schema(
            {
                "verdict": {"type": "string", "enum": ["rework_product", "rework_engineering", "release"]},
                "rationale": {"type": "string"},
                "checks": {"type": "array", "items": {"type": "string"}, "description": "Quality check names run via run_check"},
                "defects": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "severity": {"type": "string", "enum": ["blocker", "major", "minor"]},
                            "summary": {"type": "string"},
                        },
                        "required": ["severity", "summary"],
                    },
                },
            },
            ["verdict", "rationale", "checks"],
        ),
        "loadMode": "essential",
    },
}
