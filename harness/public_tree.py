"""Capture and reproduce a complete public workspace without following links.

The public tree holds every workspace entry except the host-private paths and the
paths the project's ignore rules (its .gitignore files and Git exclude files)
exclude. The ignore rules are decided by the Git command line; see
`_ignored_paths`. Entries the public tree cannot represent (links, reparse
points, hard links, special files) raise `UnrepresentableWorkspace` naming only
the workspace-relative path.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Sequence

from .models import canonical_hash, hash_bytes

TREE_FORMAT = "yudao-public-tree-v1"
_HASH = re.compile(r"sha256:[0-9a-f]{64}")
_DEVICE = re.compile(r"(?:con|prn|aux|nul|com[1-9\u00b9\u00b2\u00b3]|lpt[1-9\u00b9\u00b2\u00b3]|conin\$|conout\$)", re.IGNORECASE)
# 工作区忽略规则探测用的 Git 目录：放在工作区自身之外，避免它成为公开树的条目
IGNORE_PROBE_DIR = ".yudao-ignore-probe.git"
_GIT_DIR_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

class TreeError(ValueError):
    """A tree is incomplete, changed, or cannot be represented without ambiguity."""

class UnrepresentableWorkspace(TreeError):
    """The workspace holds entries the public tree cannot represent.

    `findings` 是（工作区内相对路径，原因）的序列；说明文字只出现相对路径。
    """

    def __init__(self, findings: Sequence[tuple[str, str]]) -> None:
        self.paths = tuple(relative for relative, _reason in findings)
        self.reasons = tuple(reason for _relative, reason in findings)
        super().__init__(
            "; ".join([*self.reasons, "Add these paths to the project's ignore rules or delete them."])
        )

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

def is_git_metadata(relative: str) -> bool:
    # 仓库自身的 Git 元数据：公开树排除它（设计第 4.2 节），快照接入不因为它拒绝源目录
    return ".git" in relative.replace("\\", "/").casefold().split("/")

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

def ignore_probe_directory(root: str | Path) -> Path:
    """The probe Git directory for one workspace root: outside the workspace itself."""
    base = _absolute_path(root)
    probe = base.parent / (base.name + IGNORE_PROBE_DIR)
    if not _GIT_DIR_NAME.fullmatch(probe.name):
        raise TreeError(f"Ignore probe directory is not a plain name: {probe.name!r}")
    return probe

def has_ignore_rules(root: str | Path, relative: str) -> bool:
    """Whether any ignore file Git reads for this relative path can exclude it.

    Git reads the ignore files inside the work tree plus the probe repository's own
    info/exclude. The probe repository is created with an empty template, so it has no
    info/exclude, and its environment points core.excludesFile and core.attributesFile at
    the null device. The only rules that can apply to a relative path therefore live in
    the directories from the work tree root down to that path's own parent, and a .git
    directory ends the search because Git stops there. A workspace holding no ignore file
    at all excludes nothing, and no Git command line is started to learn that.
    """
    base = _absolute_path(root)
    if os.path.exists(ignore_probe_directory(base) / "info" / "exclude"):
        return True
    directory = base
    for part in PurePosixPath(relative).parent.parts:
        directory = directory / part
        if (directory / ".gitignore").exists() or (directory / ".git").exists():
            return True
    return (base / ".gitignore").exists() or (base / ".git").exists()

def excluded_by_ignore_rules(root: str | Path, relatives: Sequence[str]) -> frozenset[str]:
    """The relatives the project's ignore rules exclude, decided by the Git command line.

    The probe repository belongs to the workspace root and lives beside it, so the
    enclosing repository's rules (for example an outer .gitignore) do not leak in.
    Returns the paths Git echoes back; exit code 1 with no output means nothing is
    ignored. Relatives no ignore file can reach are not decided on the command line: with
    no ignore file at all the answer is empty and the Git process is never started.
    """
    candidates = [relative for relative in relatives if has_ignore_rules(root, relative)]
    if not candidates:
        return frozenset()
    base = _absolute_path(root)
    probe = ignore_probe_directory(base)
    if not os.path.exists(probe / "HEAD"):
        probe.mkdir(parents=True, exist_ok=True)
        _git_probe(probe, base, "init", "--quiet", "--template=")
    environment = _git_environment()
    output = _git_probe(
        probe, base, "check-ignore", "--no-index", "--stdin", "-z",
        data="\0".join(candidates).encode("utf-8") + b"\0", environment=environment,
    )
    return frozenset(item for item in output.decode("utf-8", errors="strict").split("\0") if item)

def unrepresentable_reason(observed: os.stat_result, relative: str) -> str | None:
    """Why a workspace entry cannot enter the public tree, naming the relative path only."""
    reparse = getattr(observed, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if stat.S_ISLNK(observed.st_mode) or reparse:
        return f"Links and reparse points are not supported: {relative}"
    if not (stat.S_ISDIR(observed.st_mode) or stat.S_ISREG(observed.st_mode)):
        return f"Only regular files and directories are supported: {relative}"
    if stat.S_ISREG(observed.st_mode) and observed.st_nlink != 1:
        return f"Hard-linked files are not supported: {relative}"
    return None

def capture_public_tree(root: str | Path, respect_ignore_rules: bool = False) -> CapturedTree:
    """Capture stable local bytes; filesystem changes during collection are errors.

    respect_ignore_rules 打开时（run 工作区的读取），被项目忽略规则排除的路径不进入公开树，
    规则由 Git 命令行判断；其余读取（封存、恢复、核对）不执行命令，也不应用忽略规则。
    """
    base = _checked_directory(root)
    before = _scan(base, respect_ignore_rules=respect_ignore_rules)
    files = []
    for relative, observed in before.items():
        if relative and stat.S_ISREG(observed.st_mode):
            files.append(CapturedFile(relative, _read_stable_file(base / relative, observed, relative)))
    after = _scan(base, respect_ignore_rules=respect_ignore_rules)
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
    # 检查到无法表示的条目时说明文字写工作区内的相对路径；root 自身不经过这个循环
    for path in [*reversed(target.parents), target]:
        try:
            observed = path.lstat()
        except FileNotFoundError:
            break
        depth = len(path.parents) - len(target.parents)
        named = relative if path == target else (relative.split("/")[0] if depth == 1 else "/".join(relative.split("/")[:depth]))
        _check_kind(path, observed, named)
        if path != target and not stat.S_ISDIR(observed.st_mode):
            raise TreeError(f"Public path ancestor is not a directory: {named}")
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

def _check_kind(path: Path, observed: os.stat_result, relative: str | None = None) -> None:
    # relative 给出时（扫描与解析中）说明文字只写工作区内的相对路径；树根本身的检查保留主机路径
    reparse = getattr(observed, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if stat.S_ISLNK(observed.st_mode) or reparse:
        raise TreeError(f"Links and reparse points are not supported: {relative if relative is not None else path}")
    if not (stat.S_ISDIR(observed.st_mode) or stat.S_ISREG(observed.st_mode)):
        raise TreeError(f"Only regular files and directories are supported: {relative if relative is not None else path}")
    if stat.S_ISREG(observed.st_mode) and observed.st_nlink != 1:
        raise TreeError(f"Hard-linked files are not supported: {relative if relative is not None else path}")

def _scan(base: Path, *, respect_ignore_rules: bool = False) -> dict[str, os.stat_result]:
    _checked_directory(base)
    found: dict[str, os.stat_result] = {}
    # 无法表示的条目按遇到顺序收集（相对路径与原因），扫描完成后再报错
    findings: list[tuple[str, str]] = []
    pending: list[tuple[Path, str]] = [(base, "")]
    while pending:
        directory, relative_directory = pending.pop()
        observed = directory.lstat()
        _check_kind(directory, observed)
        if not stat.S_ISDIR(observed.st_mode):
            raise TreeError(f"Directory changed during capture: {directory}")
        if relative_directory:
            found[relative_directory] = observed
        entries: list[tuple[str, Path, os.stat_result]] = []
        with os.scandir(directory) as scanning:
            for entry in scanning:
                relative = f"{relative_directory}/{entry.name}" if relative_directory else entry.name
                if is_private_path(relative):
                    continue
                validate_public_path(relative)
                path = directory / entry.name
                # Windows DirEntry.stat omits file identity and link count.
                entries.append((relative, path, path.lstat()))
        ignored = (excluded_by_ignore_rules(base, [relative for relative, _path, _observed in entries])
                   if respect_ignore_rules else frozenset())
        for relative, path, entry_observed in entries:
            if relative in ignored:
                continue
            reason = unrepresentable_reason(entry_observed, relative)
            if reason is not None:
                findings.append((relative, reason))
                continue
            if stat.S_ISDIR(entry_observed.st_mode):
                pending.append((path, relative))
            else:
                found[relative] = entry_observed
    if findings:
        raise UnrepresentableWorkspace(findings)
    return found

def _read_stable_file(path: Path, expected: os.stat_result, relative: str) -> bytes:
    with path.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        _check_kind(path, opened, relative)
        # Windows path stat and fstat disagree on the meaning of st_ctime.
        if _identity(opened, change_time=False) != _identity(expected, change_time=False):
            raise TreeError(f"File changed before it could be captured: {relative}")
        raw = handle.read()
        closed = os.fstat(handle.fileno())
    current = path.lstat()
    _check_kind(path, current, relative)
    if _identity(closed) != _identity(opened) or _identity(current) != _identity(expected) or len(raw) != expected.st_size:
        raise TreeError(f"File changed while it was being captured: {relative}")
    return raw

def _identity(observed: os.stat_result, *, change_time: bool = True) -> tuple[int, ...]:
    fields = (
        observed.st_dev, observed.st_ino, observed.st_mode, observed.st_nlink,
        observed.st_size, observed.st_mtime_ns,
    )
    return (*fields, observed.st_ctime_ns) if change_time else fields

def _git_environment() -> dict[str, str]:
    # 探测用的 Git 环境与 git_versions 相同的隔离：系统与全局配置不进入判定
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    environment.update({
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_ATTR_NOSYSTEM": "1", "GIT_NO_REPLACE_OBJECTS": "1", "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.excludesFile", "GIT_CONFIG_VALUE_0": os.devnull,
    })
    return environment

def _git_probe(probe: Path, work_tree: Path, *arguments: str, data: bytes | None = None,
               environment: dict[str, str] | None = None) -> bytes:
    executable = shutil.which("git")
    if executable is None:
        raise TreeError("Git executable is unavailable; the project's ignore rules cannot be decided")
    command = [
        executable, "--no-pager", f"--git-dir={probe}", f"--work-tree={work_tree}",
        "-c", "core.quotePath=false", *arguments,
    ]
    completed = subprocess.run(command, input=data, capture_output=True, shell=False,
                               env=environment if environment is not None else _git_environment(), check=False)
    if completed.returncode not in (0, 1):
        raise TreeError(
            "git check-ignore failed with exit code "
            f"{completed.returncode}: {completed.stderr.decode('utf-8', errors='replace').strip()}"
        )
    return completed.stdout

__all__ = [
    "CapturedFile", "CapturedTree", "TreeError", "UnrepresentableWorkspace",
    "capture_public_tree", "excluded_by_ignore_rules", "has_ignore_rules", "ignore_probe_directory",
    "is_git_metadata", "is_private_path", "materialize_tree", "resolve_public_path", "unrepresentable_reason",
    "validate_manifest", "validate_public_path", "verify_public_tree",
]
