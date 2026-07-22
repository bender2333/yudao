"""Shell-free, fail-closed local file tools for agent workspaces."""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import math
import ntpath
import os
import re
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .process_control import run_process_tree
from .seed import seed_workspace
from .workspace import Workspace, _require_link_free_components

READ_TOOL_NAMES = frozenset({"read_file", "list_files", "search_text", "run_check"})
WRITE_TOOL_NAMES = frozenset({"write_file", "edit_file"})
_MAX_FILE_BYTES = 1024 * 1024
_MAX_LIST_PATHS = 1000
_MAX_SEARCH_MATCHES = 200
SEARCH_OUTPUT_BYTES = 64 * 1024
_SEARCH_TRUNCATION_MARKER = "[truncated at 200 matches or 65536 bytes]"
_CHECK_NAME = re.compile(r"[A-Za-z0-9_.-]+\Z")


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

def _canonical_parts(parts: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(part.casefold() for part in parts)


def _path_is_within(root: str, candidate: str) -> bool:
    root_drive = (ntpath.splitdrive(root)[0] or os.path.splitdrive(root)[0]).casefold()
    candidate_drive = (ntpath.splitdrive(candidate)[0] or os.path.splitdrive(candidate)[0]).casefold()
    if root_drive != candidate_drive:
        return False
    return os.path.commonpath((root, candidate)) == root



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
    if any(part.endswith((".", " ")) for part in parts):
        raise ValueError(f"{label} contains a Windows-aliased component")
    return parts


def _check_name(value: object) -> str:
    if type(value) is not str or not value or _CHECK_NAME.fullmatch(value) is None:
        raise ValueError("check name must be a non-empty safe identifier")
    return value


def _check_spec(name: str, value: object) -> CheckSpec:
    if type(value) is not dict or set(value) != {"argv", "timeout_seconds"}:
        raise ValueError(f"check {name} must have exact fields argv and timeout_seconds")
    argv = value["argv"]
    if type(argv) is not list or not argv or any(type(arg) is not str or not arg or "\0" in arg for arg in argv):
        raise ValueError(f"check {name} argv must be a non-empty list of exact non-empty strings without NUL")
    timeout = value["timeout_seconds"]
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError(f"check {name} timeout_seconds must be a finite positive number")
    return CheckSpec(tuple(argv), float(timeout))


def load_check_manifest(path: str | os.PathLike[str]) -> tuple[dict[str, CheckSpec], tuple[str, ...]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"manifest: {error}") from error
    if type(payload) is not dict or set(payload) != {"protected_paths", "checks"}:
        raise ValueError("top-level manifest must be an object with exact fields protected_paths and checks")
    protected = payload["protected_paths"]
    if type(protected) is not list:
        raise ValueError("protected_paths must be a list")
    try:
        normalized_parts = tuple(_relative_parts(item, "protected path") for item in protected)
    except (TypeError, ValueError) as error:
        raise ValueError(str(error)) from error
    canonical = tuple(_canonical_parts(parts) for parts in normalized_parts)
    if len(set(canonical)) != len(canonical):
        raise ValueError("duplicate protected path")
    raw_checks = payload["checks"]
    if type(raw_checks) is not dict:
        raise ValueError("checks must be an object")
    checks: dict[str, CheckSpec] = {}
    for raw_name, raw_spec in raw_checks.items():
        name = _check_name(raw_name)
        checks[name] = _check_spec(name, raw_spec)
    return checks, tuple("/".join(parts) for parts in canonical)


def _safe_env() -> dict[str, str]:
    allowed = {
        "PATH", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR",
        "HOME", "USERPROFILE", "LANG", "LC_ALL",
    }
    blocked = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
    env = {
        key: value
        for key, value in os.environ.items()
        if key in allowed and type(value) is str and not any(marker in key.upper() for marker in blocked)
    }
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


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
            _check_name(name)
            if type(spec) is not CheckSpec:
                raise TypeError("check values must be CheckSpec")
            if type(spec.argv) is not tuple or not spec.argv or any(
                type(arg) is not str or not arg or "\0" in arg for arg in spec.argv
            ):
                raise ValueError(f"check {name!r} argv must be a non-empty tuple of exact strings without NUL")
            if type(spec.timeout_seconds) not in (int, float) or not math.isfinite(spec.timeout_seconds) or spec.timeout_seconds <= 0:
                raise ValueError(f"check {name!r} timeout must be finite and positive")
        if not isinstance(self.protected_paths, tuple):
            raise TypeError("protected_paths must be a tuple")
        normalized_parts = tuple(_relative_parts(path, "protected path") for path in self.protected_paths)
        canonical = tuple(_canonical_parts(parts) for parts in normalized_parts)
        if len(set(canonical)) != len(canonical):
            raise ValueError("duplicate protected path")
        self.protected_paths = tuple("/".join(parts) for parts in canonical)
        if not isinstance(self.audit_dir, Path):
            raise TypeError("audit_dir must be a Path")
        root = os.path.realpath(self.workspace.dir)
        audit = os.path.realpath(self.audit_dir)
        if _path_is_within(root, audit):
            raise ValueError("audit_dir must be outside workspace")
        _require_link_free_components(self.audit_dir, "audit_dir")
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        _require_link_free_components(self.audit_dir, "audit_dir")
        if not self.audit_dir.is_dir():
            raise ValueError("audit_dir must be a real directory")

    def tool_defs(self, writable: bool) -> list[dict]:
        names = READ_TOOL_NAMES | (WRITE_TOOL_NAMES if writable else frozenset())
        return copy.deepcopy([_TOOL_DEFS[name] for name in sorted(names)])

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
        if parts[0].casefold() == ".harness":
            raise ValueError("reserved path")
        root = Path(self.workspace.dir)
        target = root.joinpath(*parts)
        root_real = os.path.realpath(root)
        target_real = os.path.realpath(target)
        if not _path_is_within(root_real, target_real):
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
        canonical = "/".join(_canonical_parts(tuple(relative.split("/"))))
        if any(canonical == protected or canonical.startswith(protected + "/") for protected in self.protected_paths):
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
                relative = child.relative_to(root).as_posix()
                if relative.split("/", 1)[0].casefold() == ".harness":
                    raise ValueError("reserved path")
                if _is_link_or_junction(child) or not stat.S_ISDIR(child.lstat().st_mode):
                    raise ValueError(f"unsafe workspace entry: {relative}")
            for filename in filenames:
                child = directory / filename
                relative = child.relative_to(root).as_posix()
                if relative.split("/", 1)[0].casefold() == ".harness":
                    raise ValueError("reserved path")
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
        used_bytes = 0
        marker_bytes = len(_SEARCH_TRUNCATION_MARKER.encode("utf-8")) + 1
        truncated = False
        for relative, path in self._files():
            if path.stat().st_size > _MAX_FILE_BYTES:
                raise ValueError(f"file exceeds {_MAX_FILE_BYTES} bytes: {relative}")
            data = path.read_bytes()
            if len(data) > _MAX_FILE_BYTES:
                raise ValueError(f"file exceeds {_MAX_FILE_BYTES} bytes: {relative}")
            text = data.decode("utf-8", errors="strict")
            for line_number, line in enumerate(text.splitlines(), 1):
                if query not in line:
                    continue
                candidate = f"{relative}:{line_number}:{line}"
                candidate_bytes = len(candidate.encode("utf-8")) + (1 if matches else 0)
                if len(matches) >= _MAX_SEARCH_MATCHES or used_bytes + candidate_bytes + marker_bytes > SEARCH_OUTPUT_BYTES:
                    truncated = True
                    break
                matches.append(candidate)
                used_bytes += candidate_bytes
            if truncated:
                break
        if truncated:
            matches.append(_SEARCH_TRUNCATION_MARKER)
        return "\n".join(matches) or "(no matches)"

    def receipt(self, name: str, tree_hash: str) -> CheckReceipt | None:
        if type(name) is not str or type(tree_hash) is not str:
            return None
        return self.receipts.get((name, tree_hash))

    def run_check(self, name: str) -> str:
        _check_name(name)
        self._files()
        spec = self.checks.get(name)
        if spec is None:
            raise ValueError(f"unknown check: {name}")
        self.workspace.tree_manifest()
        before_hash = self.workspace.tree_hash()
        with tempfile.TemporaryDirectory(prefix="check-mirror-") as mirror:
            seed_workspace(self.workspace.dir, mirror)
            self.check_sequence += 1
            sequence = self.check_sequence
            stdout_path = self.audit_dir / f"{sequence:04d}-{name}.stdout.log"
            stderr_path = self.audit_dir / f"{sequence:04d}-{name}.stderr.log"
            result = run_process_tree(
                list(spec.argv),
                cwd=mirror,
                env=_safe_env(),
                timeout_seconds=spec.timeout_seconds,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
        receipt = CheckReceipt(
            name=name,
            tree_hash=before_hash,
            exit_code=result.returncode,
            timed_out=result.timed_out,
            stdout_digest=_digest(stdout_path),
            stderr_digest=_digest(stderr_path),
            duration_ms=result.duration_ms,
        )
        self.receipts[(name, before_hash)] = receipt
        exit_value = "none" if receipt.exit_code is None else str(receipt.exit_code)
        return (
            f"name={name} exit={exit_value} timed_out={str(receipt.timed_out).lower()} "
            f"duration_ms={receipt.duration_ms} tree_hash={before_hash} "
            f"stdout_digest={receipt.stdout_digest} stderr_digest={receipt.stderr_digest}"
        )
