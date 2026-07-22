"""Deterministic, link-safe snapshots of an agent workspace."""

from __future__ import annotations

import hashlib
import json
import os
import stat


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _is_link_or_junction(path: str) -> bool:
    return os.path.islink(path) or getattr(os.path, "isjunction", lambda _path: False)(path)


def _require_link_free_components(path: str, label: str, link_check=None) -> str:
    absolute = os.path.abspath(path)
    current = absolute
    components = []
    while True:
        components.append(current)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    check = link_check or _is_link_or_junction
    for component in reversed(components):
        if os.path.lexists(component) and check(component):
            raise ValueError(f"{label} link is not allowed: {component}")
    return absolute


def _require_real_directory(path: str, label: str, link_check=None) -> str:
    absolute = _require_link_free_components(path, label, link_check)
    if not os.path.isdir(absolute):
        raise FileNotFoundError(f"{label} not found: {path}")
    return os.path.realpath(absolute)


def _manifest_by_path(manifest: list[dict]) -> dict[str, tuple[int, str]]:
    result: dict[str, tuple[int, str]] = {}
    for item in manifest:
        if not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}:
            raise ValueError("malformed manifest item")
        path = item["path"]
        size = item["size"]
        sha256 = item["sha256"]
        if not isinstance(path, str) or not isinstance(size, int) or not isinstance(sha256, str):
            raise ValueError("malformed manifest item")
        if path in result:
            raise ValueError(f"duplicate manifest path: {path}")
        result[path] = (size, sha256)
    return result


def diff_manifests(before: list[dict], after: list[dict]) -> list[str]:
    before_by_path = _manifest_by_path(before)
    after_by_path = _manifest_by_path(after)
    return sorted(
        path
        for path in before_by_path.keys() | after_by_path.keys()
        if before_by_path.get(path) != after_by_path.get(path)
    )


class Workspace:
    def __init__(self, root: str):
        root_path = _require_link_free_components(root, "workspace root")
        os.makedirs(root_path, exist_ok=True)
        self.dir = _require_real_directory(root_path, "workspace root")

    def tree_manifest(self) -> list[dict]:
        if not os.path.isdir(self.dir):
            raise FileNotFoundError(f"workspace root is not a directory: {self.dir}")
        if _is_link_or_junction(self.dir):
            raise ValueError(f"workspace root link is not allowed: {self.dir}")

        result: list[dict] = []
        for dirpath, dirnames, filenames in os.walk(self.dir, followlinks=False):
            for dirname in dirnames:
                full_dir = os.path.join(dirpath, dirname)
                if _is_link_or_junction(full_dir):
                    raise ValueError(f"workspace directory link is not allowed: {full_dir}")
                if not stat.S_ISDIR(os.lstat(full_dir).st_mode):
                    raise ValueError(f"workspace special directory is not allowed: {full_dir}")
            dirnames[:] = sorted(name for name in dirnames if name != ".harness")
            for filename in sorted(filenames):
                full = os.path.join(dirpath, filename)
                if _is_link_or_junction(full):
                    raise ValueError(f"workspace file link is not allowed: {full}")
                file_stat = os.lstat(full)
                if not stat.S_ISREG(file_stat.st_mode):
                    raise ValueError(f"workspace special file is not allowed: {full}")
                result.append(
                    {
                        "path": os.path.relpath(full, self.dir).replace(os.sep, "/"),
                        "size": file_stat.st_size,
                        "sha256": _sha256_file(full),
                    }
                )
        return sorted(result, key=lambda item: item["path"])

    def tree_hash(self) -> str:
        encoded = json.dumps(
            self.tree_manifest(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def snapshot_files(self) -> dict[str, int]:
        """Return the legacy path-to-size snapshot format."""
        return {item["path"]: item["size"] for item in self.tree_manifest()}

    def snapshot_fingerprints(self) -> dict[str, str]:
        """Return legacy unprefixed content fingerprints."""
        return {item["path"]: item["sha256"].removeprefix("sha256:") for item in self.tree_manifest()}
