"""部门工具白名单。Product/Quality 无写工具，Engineering 才有写工具。检查由主机执行。"""

from __future__ import annotations

import base64
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .models import json_dumps
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
    "delete_file": {"access": "write", "departments": ("engineering",)},
    "move_file": {"access": "write", "departments": ("engineering",)},
    "run_check": {"access": "check", "departments": ("product", "engineering", "quality")},
    "collect_evidence": {"access": "check", "departments": ("quality",)},
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
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self._handlers: dict[str, Callable[..., Any]] = {
            "read_file": self._read_file,
            "list_files": self._list_files,
            "search": self._search,
            "read_range": self._read_range,
            "write_file": self._write_file,
            "delete_file": self._delete_file,
            "move_file": self._move_file,
            "run_check": self._run_check,
            "collect_evidence": self._collect_evidence,
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

    def _delete_file(self, department: str, args: dict[str, Any]) -> str:
        _require_reason(args)
        return self.workspace.delete_file(args["path"])

    def _move_file(self, department: str, args: dict[str, Any]) -> dict[str, str]:
        _require_reason(args)
        return self.workspace.move_file(args["source"], args["destination"])

    def _run_check(self, department: str, args: dict[str, Any]) -> dict[str, Any]:
        return self._execute_check(department, args)

    def _collect_evidence(self, department: str, args: dict[str, Any]) -> dict[str, Any]:
        return self._execute_check(department, args)

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
    raise ValueError("run_check/collect_evidence require host-executed argv or command; exit_code is not evidence")


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
        "description": "Read a workspace file. Paths under .checks are host-private.",
        "parameters": _object_schema({"path": {"type": "string", "description": "Workspace-relative file path"}}, ["path"]),
        "loadMode": "essential",
    },
    "list_files": {
        "name": "list_files",
        "label": "list_files",
        "description": "List workspace files. Does not include .checks.",
        "parameters": _object_schema({"prefix": {"type": "string", "description": "Optional path prefix"}}),
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
        "description": "Read a line range of one public workspace file. Returns path, start_line, end_line, total_lines and the snapshot digest. Truncated output carries next_cursor.",
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
        "description": "Write a workspace file. Engineering only. Cannot write .checks.",
        "parameters": _object_schema(
            {
                "path": {"type": "string", "description": "Workspace-relative file path"},
                "content": {"type": "string", "description": "Full file contents"},
            },
            ["path", "content"],
        ),
        "loadMode": "essential",
    },
    "delete_file": {
        "name": "delete_file",
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
    "collect_evidence": {
        "name": "collect_evidence",
        "label": "collect_evidence",
        "description": "Quality-only host-executed check. Engineering receipts are not accepted as QA evidence.",
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
        "description": "Submit a DeliverySpec after writing files and host-running checks. check_names must match host receipts on the current snapshot.",
        "parameters": _object_schema(
            {
                "summary": {"type": "string"},
                "files": _string_list_schema("Workspace-relative files included in the delivery"),
                "check_names": _string_list_schema("Names of host-executed engineering checks"),
                "known_risks": _string_list_schema("Optional"),
            },
            ["summary", "files", "check_names"],
        ),
        "loadMode": "essential",
    },
    "submit_review": {
        "name": "submit_review",
        "label": "submit_review",
        "description": "Submit a QAReview. release requires quality-run host receipts with exit_code 0 on the current snapshot. checks are check names.",
        "parameters": _object_schema(
            {
                "verdict": {"type": "string", "enum": ["rework_product", "rework_engineering", "release"]},
                "rationale": {"type": "string"},
                "checks": {"type": "array", "items": {"type": "string"}, "description": "Quality check names run via collect_evidence or run_check"},
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
