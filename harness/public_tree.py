"""Capture and reproduce a complete public workspace without following links."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .models import canonical_hash, hash_bytes


TREE_FORMAT = "yudao-public-tree-v1"
_HASH = re.compile(r"sha256:[0-9a-f]{64}")
_DEVICE = re.compile(r"(?:con|prn|aux|nul|com[1-9\u00b9\u00b2\u00b3]|lpt[1-9\u00b9\u00b2\u00b3]|conin\$|conout\$)", re.IGNORECASE)


class TreeError(ValueError):
    """A tree is incomplete, changed, or cannot be represented without ambiguity."""


@dataclass(frozen=True)
class CapturedFile:
    path: str
    data: bytes

    def __post_init__(self) -> None:
        validate_public_path(self.path)
        if not isinstance(self.data, bytes):
            raise TreeError("Captured file data must be bytes")


@dataclass(frozen=True)
class CapturedTree:
    directories: tuple[str, ...]
    files: tuple[CapturedFile, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.directories, tuple) or not isinstance(self.files, tuple):
            raise TreeError("Captured tree entries must be immutable tuples")
        if any(not isinstance(item, CapturedFile) for item in self.files):
            raise TreeError("Captured tree files must contain captured bytes")
        validate_manifest(self.manifest)

    @property
    def manifest(self) -> dict[str, Any]:
        return {
            "format": TREE_FORMAT,
            "directories": list(self.directories),
            "files": [{"path": item.path, "size": len(item.data), "content_hash": hash_bytes(item.data)} for item in self.files],
        }

    @property
    def digest(self) -> str:
        return canonical_hash(self.manifest)


def is_private_path(relative: str) -> bool:
    parts = relative.replace("\\", "/").casefold().split("/")
    return parts[0] == ".checks" or ".git" in parts


def validate_public_path(relative: str) -> None:
    """Accept an unambiguous portable relative path, never silently normalize it."""
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise TreeError(f"Invalid public path: {relative!r}")
    if PurePosixPath(relative).is_absolute() or PureWindowsPath(relative).drive:
        raise TreeError(f"Public path must be relative: {relative!r}")
    for part in relative.split("/"):
        if not part or part in {".", ".."} or part.endswith((".", " ")):
            raise TreeError(f"Ambiguous public path: {relative!r}")
        if any(ord(character) < 32 or character in '<>:"|?*' for character in part) or _DEVICE.fullmatch(part.split(".", 1)[0].rstrip(" ")):
            raise TreeError(f"Public path has a reserved component: {relative!r}")
        try:
            part.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise TreeError(f"Public path is not valid UTF-8: {relative!r}") from exc
    if is_private_path(relative):
        raise TreeError(f"Host-private path is not part of a public tree: {relative!r}")


def validate_manifest(manifest: dict[str, Any]) -> None:
    """Check the complete directory and file set before any destination is written."""
    if not isinstance(manifest, dict) or set(manifest) != {"format", "directories", "files"}:
        raise TreeError("Invalid public tree manifest fields")
    if manifest["format"] != TREE_FORMAT:
        raise TreeError("Unsupported public tree format")
    directories, files = manifest["directories"], manifest["files"]
    if not isinstance(directories, list) or not isinstance(files, list):
        raise TreeError("Public tree directories and files must be lists")
    paths = []
    for directory in directories:
        validate_public_path(directory)
        paths.append(directory)
    file_paths = []
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "size", "content_hash"}:
            raise TreeError("Invalid public tree file entry")
        validate_public_path(item["path"])
        if type(item["size"]) is not int or item["size"] < 0:
            raise TreeError("Public tree file size must be a nonnegative integer")
        if not isinstance(item["content_hash"], str) or not _HASH.fullmatch(item["content_hash"]):
            raise TreeError("Invalid public tree file content hash")
        file_paths.append(item["path"])
    if directories != sorted(directories) or file_paths != sorted(file_paths):
        raise TreeError("Public tree entries must be sorted by path")
    paths.extend(file_paths)
    if len({path.casefold() for path in paths}) != len(paths):
        raise TreeError("Public tree has duplicate paths or a case collision")
    directory_set = set(directories)
    for relative in paths:
        parent = PurePosixPath(relative).parent
        if parent != PurePosixPath(".") and str(parent) not in directory_set:
            raise TreeError(f"Public tree entry has no declared parent directory: {relative}")


def capture_public_tree(root: str | Path) -> CapturedTree:
    """Capture stable local bytes; filesystem changes during collection are errors."""
    base = _checked_directory(root)
    before = _scan(base)
    files = []
    for relative, observed in before.items():
        if relative and stat.S_ISREG(observed.st_mode):
            files.append(CapturedFile(relative, _read_stable_file(base / relative, observed)))
    after = _scan(base)
    if {path: _identity(value) for path, value in before.items()} != {
        path: _identity(value) for path, value in after.items()
    }:
        raise TreeError("Public tree changed during capture")
    return CapturedTree(
        directories=tuple(sorted(path for path, value in before.items() if path and stat.S_ISDIR(value.st_mode))),
        files=tuple(sorted(files, key=lambda item: item.path)),
    )


def verify_public_tree(root: str | Path, manifest: dict[str, Any]) -> None:
    validate_manifest(manifest)
    if capture_public_tree(root).manifest != manifest:
        raise TreeError("Public tree does not match the complete recorded manifest")


def resolve_public_path(root: str | Path, relative: str) -> Path:
    """Resolve a public name while checking existing ancestors without following links."""
    validate_public_path(relative)
    target = _absolute_path(root) / relative
    for path in [*reversed(target.parents), target]:
        try:
            observed = path.lstat()
        except FileNotFoundError:
            break
        _check_kind(path, observed)
        if path != target and not stat.S_ISDIR(observed.st_mode):
            raise TreeError(f"Public path ancestor is not a directory: {path}")
    return target


def materialize_tree(tree: CapturedTree, new_directory: str | Path) -> Path:
    """Write already-validated bytes only into a new directory, then verify its tree."""
    if not isinstance(tree, CapturedTree):
        raise TreeError("Restoration requires a fully captured tree")
    validate_manifest(tree.manifest)
    target = _absolute_path(new_directory)
    _checked_directory(target.parent)
    if os.path.lexists(target):
        raise TreeError(f"Restoration destination already exists: {target}")
    target.mkdir()
    for relative in tree.directories:
        _checked_directory((target / relative).parent)
        (target / relative).mkdir()
    for item in tree.files:
        _checked_directory((target / item.path).parent)
        with (target / item.path).open("xb") as handle:
            handle.write(item.data)
    verify_public_tree(target, tree.manifest)
    return target


def _absolute_path(path: str | Path) -> Path:
    supplied = Path(path)
    if ".." in supplied.parts:
        raise TreeError(f"Tree root cannot contain parent traversal: {path}")
    for part in supplied.parts:
        if part != supplied.anchor:
            validate_public_path("root/" + part)
    return supplied.absolute()


def _checked_directory(root: str | Path) -> Path:
    base = _absolute_path(root)
    for path in [*reversed(base.parents), base]:
        observed = path.lstat()
        _check_kind(path, observed)
        if not stat.S_ISDIR(observed.st_mode):
            raise TreeError(f"Tree root or ancestor is not a directory: {path}")
    return base


def _check_kind(path: Path, observed: os.stat_result) -> None:
    reparse = getattr(observed, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if stat.S_ISLNK(observed.st_mode) or reparse:
        raise TreeError(f"Links and reparse points are not supported: {path}")
    if not (stat.S_ISDIR(observed.st_mode) or stat.S_ISREG(observed.st_mode)):
        raise TreeError(f"Only regular files and directories are supported: {path}")
    if stat.S_ISREG(observed.st_mode) and observed.st_nlink != 1:
        raise TreeError(f"Hard-linked files are not supported: {path}")


def _scan(base: Path) -> dict[str, os.stat_result]:
    _checked_directory(base)
    found = {}
    pending = [(base, "")]
    while pending:
        directory, relative_directory = pending.pop()
        observed = directory.lstat()
        _check_kind(directory, observed)
        if not stat.S_ISDIR(observed.st_mode):
            raise TreeError(f"Directory changed during capture: {directory}")
        found[relative_directory] = observed
        with os.scandir(directory) as entries:
            for entry in entries:
                relative = f"{relative_directory}/{entry.name}" if relative_directory else entry.name
                if is_private_path(relative):
                    continue
                validate_public_path(relative)
                path = directory / entry.name
                # Windows DirEntry.stat omits file identity and link count.
                observed = path.lstat()
                _check_kind(path, observed)
                if stat.S_ISDIR(observed.st_mode):
                    pending.append((path, relative))
                else:
                    found[relative] = observed
    return found


def _read_stable_file(path: Path, expected: os.stat_result) -> bytes:
    with path.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        _check_kind(path, opened)
        # Windows path stat and fstat disagree on the meaning of st_ctime.
        if _identity(opened, change_time=False) != _identity(expected, change_time=False):
            raise TreeError(f"File changed before it could be captured: {path}")
        raw = handle.read()
        closed = os.fstat(handle.fileno())
    current = path.lstat()
    _check_kind(path, current)
    if _identity(closed) != _identity(opened) or _identity(current) != _identity(expected) or len(raw) != expected.st_size:
        raise TreeError(f"File changed while it was being captured: {path}")
    return raw


def _identity(observed: os.stat_result, *, change_time: bool = True) -> tuple[int, ...]:
    fields = (
        observed.st_dev, observed.st_ino, observed.st_mode, observed.st_nlink,
        observed.st_size, observed.st_mtime_ns,
    )
    return (*fields, observed.st_ctime_ns) if change_time else fields
