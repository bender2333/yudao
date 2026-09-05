"""部门工具白名单。Product/Quality 无写工具，Engineering 才有写工具。检查由主机执行。"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .models import json_dumps
from .redact import redact_text, sanitized_env
from .workspace import Workspace, is_private_path, tree_digest

CHECK_TIMEOUT_SEC = 30
CHECK_OUTPUT_LIMIT = 4000

TOOL_DEFS = {
    "read_file": {"access": "read", "departments": ("product", "engineering", "quality")},
    "list_files": {"access": "read", "departments": ("product", "engineering", "quality")},
    "write_file": {"access": "write", "departments": ("engineering",)},
    "run_check": {"access": "check", "departments": ("product", "engineering", "quality")},
    "collect_evidence": {"access": "check", "departments": ("quality",)},
    "submit_product_spec": {"access": "submit", "departments": ("product",)},
    "submit_reaction": {"access": "submit", "departments": ("product",)},
    "submit_ask": {"access": "submit", "departments": ("engineering",)},
    "submit_delivery": {"access": "submit", "departments": ("engineering",)},
    "submit_review": {"access": "submit", "departments": ("quality",)},
}

SUBMIT_KINDS = {
    "submit_product_spec": "product_spec",
    "submit_reaction": "product_reaction",
    "submit_ask": "ask_request",
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
            "write_file": self._write_file,
            "run_check": self._run_check,
            "collect_evidence": self._collect_evidence,
            "submit_product_spec": self._submit,
            "submit_reaction": self._submit,
            "submit_ask": self._submit,
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

    def _write_file(self, department: str, args: dict[str, Any]) -> str:
        return self.workspace.write_file(str(args["path"]), str(args["content"]))

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
        original_digest = self.workspace.digest()
        copy_root = self.workspace.make_check_copy()
        resolved = _resolve_argv(self.workspace, argv, cwd=copy_root)
        try:
            try:
                completed = subprocess.run(
                    resolved,
                    cwd=str(copy_root),
                    env=sanitized_env(),
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
            observed_digest = tree_digest(copy_root)
            tree_changed = observed_digest != original_digest
            snapshot_hash = original_digest if not tree_changed else observed_digest
            if tree_changed:
                output = (output + "\n" if output else "") + "tested tree changed; pass is not bound to the original snapshot"
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
            }
        finally:
            shutil.rmtree(copy_root, ignore_errors=True)


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
            },
            ["goal", "requirements", "acceptance_criteria"],
        ),
        "loadMode": "essential",
    },
    "submit_reaction": {
        "name": "submit_reaction",
        "label": "submit_reaction",
        "description": "Submit a ProductReaction. decision must be accept, reply, or reject. Include spec_update when rewriting the contract.",
        "parameters": _object_schema(
            {
                "decision": {"type": "string", "enum": ["accept", "reply", "reject"]},
                "rationale": {"type": "string"},
                "spec_update": {"type": "object", "description": "Optional ProductSpec fields when rewriting the contract"},
            },
            ["decision", "rationale"],
        ),
        "loadMode": "essential",
    },
    "submit_ask": {
        "name": "submit_ask",
        "label": "submit_ask",
        "description": "Submit an AskRequest when the current ProductSpec does not decide a required tradeoff.",
        "parameters": _object_schema(
            {
                "question": {"type": "string"},
                "background": {"type": "string"},
                "options": _string_list_schema("At least one option"),
                "impact": {"type": "string"},
                "recommendation": {"type": "string"},
                "decide_fields": _string_list_schema("Fields product must decide"),
            },
            ["question", "background", "options", "impact", "recommendation", "decide_fields"],
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
