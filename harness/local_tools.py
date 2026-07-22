"""Shell-free, fail-closed local file tools for agent workspaces."""

from __future__ import annotations

import inspect
import ntpath
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .workspace import Workspace

READ_TOOL_NAMES = frozenset({"read_file", "list_files", "search_text", "run_check"})
WRITE_TOOL_NAMES = frozenset({"write_file", "edit_file"})
_MAX_FILE_BYTES = 1024 * 1024
_MAX_LIST_PATHS = 1000
_MAX_SEARCH_MATCHES = 200


@dataclass(frozen=True)
class CheckSpec:
    argv: tuple[str, ...]
    timeout_seconds: float


@dataclass(frozen=True)
class CheckReceipt:
    name: str
    tree_hash: str
    exit_code: int | None
    timed_out: bool
    stdout_digest: str
    stderr_digest: str
    duration_ms: int


def _is_link_or_junction(path: os.PathLike[str] | str) -> bool:
    return os.path.islink(path) or getattr(os.path, "isjunction", lambda _path: False)(path)


def _relative_parts(value: object, label: str = "path") -> tuple[str, ...]:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if not value:
        raise ValueError(f"{label} must not be empty")
    if os.path.isabs(value) or ntpath.isabs(value) or ntpath.splitdrive(value)[0]:
        raise ValueError(f"{label} must be relative")
    if value.startswith(("//", "\\\\")):
        raise ValueError(f"{label} must not be UNC")
    if "\\" in value or ":" in value:
        raise ValueError(f"{label} contains a forbidden character")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{label} contains a control character")
    parts = tuple(value.split("/"))
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{label} contains an invalid component")
    return parts


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


_TOOL_DEFS = {
    "read_file": _fn(
        "read_file",
        "Read one UTF-8 text file relative to the workspace.",
        {"path": {"type": "string"}},
        ["path"],
    ),
    "list_files": _fn(
        "list_files",
        "List all regular files in the workspace recursively.",
        {},
        [],
    ),
    "search_text": _fn(
        "search_text",
        "Search workspace UTF-8 files for a literal substring.",
        {"query": {"type": "string"}},
        ["query"],
    ),
    "run_check": _fn(
        "run_check",
        "Run a pre-registered check for the current workspace tree.",
        {"name": {"type": "string"}},
        ["name"],
    ),
    "write_file": _fn(
        "write_file",
        "Create or replace one UTF-8 file relative to the workspace.",
        {"path": {"type": "string"}, "content": {"type": "string"}},
        ["path", "content"],
    ),
    "edit_file": _fn(
        "edit_file",
        "Replace every occurrence of exact text in one UTF-8 workspace file.",
        {
            "path": {"type": "string"},
            "old": {"type": "string"},
            "new": {"type": "string"},
        },
        ["path", "old", "new"],
    ),
}


@dataclass
class LocalToolRuntime:
    workspace: Workspace
    checks: dict[str, CheckSpec]
    protected_paths: tuple[str, ...]
    audit_dir: Path
    receipts: dict[tuple[str, str], CheckReceipt] = field(default_factory=dict)
    check_sequence: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.workspace, Workspace):
            raise TypeError("workspace must be a Workspace")
        if not isinstance(self.checks, dict):
            raise TypeError("checks must be a dict")
        for name, spec in self.checks.items():
            if not isinstance(name, str) or not name or not isinstance(spec, CheckSpec):
                raise TypeError("check names must be non-empty strings and values must be CheckSpec")
            if not spec.argv or not all(isinstance(arg, str) and arg for arg in spec.argv):
                raise ValueError(f"check {name!r} argv must contain non-empty strings")
            if not isinstance(spec.timeout_seconds, (int, float)) or spec.timeout_seconds <= 0:
                raise ValueError(f"check {name!r} timeout must be positive")
        if not isinstance(self.protected_paths, tuple):
            raise TypeError("protected_paths must be a tuple")
        normalized = tuple("/".join(_relative_parts(path, "protected path")) for path in self.protected_paths)
        if len(set(normalized)) != len(normalized):
            raise ValueError("duplicate protected path")
        self.protected_paths = normalized
        if not isinstance(self.audit_dir, Path):
            raise TypeError("audit_dir must be a Path")
        root = os.path.realpath(self.workspace.dir)
        audit = os.path.realpath(self.audit_dir)
        if os.path.commonpath((root, audit)) == root:
            raise ValueError("audit_dir must be outside workspace")
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        if _is_link_or_junction(self.audit_dir) or not self.audit_dir.is_dir():
            raise ValueError("audit_dir must be a real directory")

    def tool_defs(self, writable: bool) -> list[dict]:
        names = READ_TOOL_NAMES | (WRITE_TOOL_NAMES if writable else frozenset())
        return [_TOOL_DEFS[name] for name in sorted(names)]

    def handlers(self) -> dict[str, Callable]:
        return {
            "read_file": self.read_file,
            "write_file": self.write_file,
            "edit_file": self.edit_file,
            "list_files": self.list_files,
            "search_text": self.search_text,
            "run_check": self.run_check,
        }

    def dispatch(self, name: str, args: dict) -> str:
        handler = self.handlers().get(name) if isinstance(name, str) else None
        if handler is None:
            return f"Error: unknown tool: {name}"
        if type(args) is not dict:
            return f"Error: bad arguments for {name}: arguments must be an exact dict"
        try:
            inspect.signature(handler).bind(**args)
            return handler(**args)
        except (TypeError, ValueError, OSError, UnicodeError) as error:
            return f"Error: {error}"
        except Exception as error:  # Model-facing dispatch is a hard exception boundary.
            return f"Error: {error}"

    def _path(self, value: object) -> tuple[Path, str]:
        parts = _relative_parts(value)
        relative = "/".join(parts)
        root = Path(self.workspace.dir)
        target = root.joinpath(*parts)
        root_real = os.path.realpath(root)
        target_real = os.path.realpath(target)
        if os.path.commonpath((root_real, target_real)) != root_real:
            raise ValueError("path escapes workspace")
        current = root
        for part in parts:
            if os.path.lexists(current) and _is_link_or_junction(current):
                raise ValueError(f"link or junction is not allowed: {relative}")
            current /= part
        if os.path.lexists(current) and _is_link_or_junction(current):
            raise ValueError(f"link or junction is not allowed: {relative}")
        return target, relative

    def _regular_file(self, value: object) -> tuple[Path, str]:
        path, relative = self._path(value)
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            raise FileNotFoundError(f"file not found: {relative}") from None
        if not stat.S_ISREG(mode):
            raise ValueError(f"not a regular file: {relative}")
        return path, relative

    def _read_bytes(self, value: object) -> tuple[bytes, str]:
        path, relative = self._regular_file(value)
        if path.stat().st_size > _MAX_FILE_BYTES:
            raise ValueError(f"file exceeds {_MAX_FILE_BYTES} bytes: {relative}")
        data = path.read_bytes()
        if len(data) > _MAX_FILE_BYTES:
            raise ValueError(f"file exceeds {_MAX_FILE_BYTES} bytes: {relative}")
        return data, relative

    def _require_writable(self, relative: str) -> None:
        if any(relative == protected or relative.startswith(protected + "/") for protected in self.protected_paths):
            raise ValueError(f"protected path: {relative}")

    def _create_parents(self, path: Path, relative: str) -> None:
        root = Path(self.workspace.dir)
        current = root
        for part in path.relative_to(root).parts[:-1]:
            current /= part
            if os.path.lexists(current):
                if _is_link_or_junction(current):
                    raise ValueError(f"link or junction is not allowed: {relative}")
                if not stat.S_ISDIR(current.lstat().st_mode):
                    raise ValueError(f"parent is not a directory: {relative}")
            else:
                current.mkdir()
                if _is_link_or_junction(current) or not stat.S_ISDIR(current.lstat().st_mode):
                    raise ValueError(f"created parent is unsafe: {relative}")
        self._path(relative)

    @staticmethod
    def _encoded(content: object, label: str = "content") -> bytes:
        if not isinstance(content, str):
            raise TypeError(f"{label} must be a string")
        if len(content) > _MAX_FILE_BYTES:
            raise ValueError(f"{label} exceeds {_MAX_FILE_BYTES} UTF-8 bytes")
        encoded = content.encode("utf-8")
        if len(encoded) > _MAX_FILE_BYTES:
            raise ValueError(f"{label} exceeds {_MAX_FILE_BYTES} UTF-8 bytes")
        return encoded

    def read_file(self, path: str) -> str:
        data, _relative = self._read_bytes(path)
        return data.decode("utf-8", errors="strict")

    def write_file(self, path: str, content: str) -> str:
        target, relative = self._path(path)
        self._require_writable(relative)
        encoded = self._encoded(content)
        self._create_parents(target, relative)
        if os.path.lexists(target) and not stat.S_ISREG(target.lstat().st_mode):
            raise ValueError(f"not a regular file: {relative}")
        target.write_bytes(encoded)
        verified, _ = self._regular_file(relative)
        if verified.stat().st_size != len(encoded):
            raise OSError(f"write verification failed: {relative}")
        return f"Wrote {relative}"

    def edit_file(self, path: str, old: str, new: str) -> str:
        if not isinstance(old, str) or not isinstance(new, str):
            raise TypeError("old and new must be strings")
        if not old:
            raise ValueError("old must not be empty")
        data, relative = self._read_bytes(path)
        self._require_writable(relative)
        source = data.decode("utf-8", errors="strict")
        count = source.count(old)
        if not count:
            raise ValueError(f"old text not found: {relative}")
        encoded = self._encoded(source.replace(old, new), "edited content")
        target, _ = self._regular_file(relative)
        target.write_bytes(encoded)
        self._regular_file(relative)
        return f"Edited {relative}: {count} replacements"

    def _files(self) -> list[tuple[str, Path]]:
        root = Path(self.workspace.dir)
        if _is_link_or_junction(root) or not stat.S_ISDIR(root.lstat().st_mode):
            raise ValueError("workspace root is not a real directory")
        files: list[tuple[str, Path]] = []
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            directory = Path(dirpath)
            for dirname in dirnames:
                child = directory / dirname
                if _is_link_or_junction(child) or not stat.S_ISDIR(child.lstat().st_mode):
                    raise ValueError(f"unsafe workspace entry: {child.relative_to(root).as_posix()}")
            for filename in filenames:
                child = directory / filename
                relative = child.relative_to(root).as_posix()
                if _is_link_or_junction(child) or not stat.S_ISREG(child.lstat().st_mode):
                    raise ValueError(f"unsafe workspace entry: {relative}")
                files.append((relative, child))
        return sorted(files)

    def list_files(self) -> str:
        files = self._files()
        if len(files) > _MAX_LIST_PATHS:
            raise ValueError(f"workspace exceeds {_MAX_LIST_PATHS} files")
        return "\n".join(relative for relative, _path in files) or "(empty)"

    def search_text(self, query: str) -> str:
        if not isinstance(query, str) or not query:
            raise ValueError("query must be a non-empty string")
        matches: list[str] = []
        truncated = False
        for relative, path in self._files():
            if path.stat().st_size > _MAX_FILE_BYTES:
                raise ValueError(f"file exceeds {_MAX_FILE_BYTES} bytes: {relative}")
            data = path.read_bytes()
            if len(data) > _MAX_FILE_BYTES:
                raise ValueError(f"file exceeds {_MAX_FILE_BYTES} bytes: {relative}")
            text = data.decode("utf-8", errors="strict")
            for line_number, line in enumerate(text.splitlines(), 1):
                if query in line:
                    if len(matches) < _MAX_SEARCH_MATCHES:
                        matches.append(f"{relative}:{line_number}:{line}")
                    else:
                        truncated = True
        if truncated:
            matches.append(f"[truncated at {_MAX_SEARCH_MATCHES} matches]")
        return "\n".join(matches) or "(empty)"

    def run_check(self, name: str) -> str:
        raise ValueError("not implemented until Task 7")
