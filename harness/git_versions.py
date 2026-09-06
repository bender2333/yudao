"""Host-owned immutable Git snapshots; accepted events own the formal history."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .public_tree import CapturedFile, CapturedTree, TreeError, validate_public_path


_OID = re.compile(r"[0-9a-f]{40}")
_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
_FORMAT = "yudao-git-version-v1"
_ERROR = "Git version is unavailable or invalid"


class GitVersionError(ValueError):
    """A snapshot cannot be written or verified without ambiguity."""


class GitVersionStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).absolute()
        self._git_path = shutil.which("git")
        if self._git_path is None:
            raise GitVersionError("Git executable is unavailable")
        self._directory(self.root, create=True)
        self._hooks = self.root / "empty-hooks"
        self._directory(self._hooks, create=True)

    def prepare(
        self,
        run_id: str,
        *,
        parent_commit: str | None,
        updates: dict[str, bytes | None],
        message: str,
        code_tree: CapturedTree | None = None,
    ) -> dict[str, Any]:
        self._run_id(run_id)
        if parent_commit is not None:
            self._oid(parent_commit)
        if not isinstance(message, str) or not isinstance(updates, dict):
            raise GitVersionError(_ERROR)
        try:
            message.encode("utf-8")
        except UnicodeError:
            raise GitVersionError(_ERROR) from None
        for path, data in updates.items():
            self._path(path)
            if path.casefold() == "code" or path.casefold().startswith("code/"):
                raise GitVersionError("Code changes require a complete captured tree")
            if data is not None and not isinstance(data, bytes):
                raise GitVersionError(_ERROR)
        if code_tree is not None and not isinstance(code_tree, CapturedTree):
            raise GitVersionError(_ERROR)
        repo = self._repository(run_id, create=True)
        previous_files: dict[str, bytes] = {}
        previous_objects: dict[str, str] = {}
        if parent_commit is not None:
            parent = self._commit(repo, run_id, parent_commit)
            previous_files, previous_objects = self._read_tree(repo, parent["tree"])
        files = dict(previous_files)
        for path, data in updates.items():
            if data is None:
                files.pop(path, None)
            else:
                files[path] = data
        if code_tree is not None:
            files = {path: data for path, data in files.items() if not path.startswith("code/")}
            files.update({"code/" + item.path: item.data for item in code_tree.files})
        self._validate_files(files)
        tree = self._write_tree(repo, files, previous_files, previous_objects)
        metadata = json.dumps(
            {"format": _FORMAT, "run_id": run_id, "message": message},
            ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        arguments = ["commit-tree", tree]
        if parent_commit is not None:
            arguments.extend(["-p", parent_commit])
        commit = self._git(repo, *arguments, data=metadata).decode("ascii").strip()
        self._oid(commit)
        # This immutable ref preserves objects, but does not accept a business version.
        reference = "refs/snapshots/" + commit
        existing = self._git(repo, "for-each-ref", "--format=%(objectname)", reference)
        if existing == b"":
            self._git(repo, "update-ref", reference, commit, "0" * 40)
        elif existing != (commit + "\n").encode("ascii"):
            raise GitVersionError(_ERROR)
        revision = {"commit": commit, "parent_commit": parent_commit, "tree": tree}
        if self._load(repo, run_id, revision) != files:
            raise GitVersionError(_ERROR)
        return revision

    def verify(self, run_id: str, revision: dict[str, Any]) -> None:
        self.read_files(run_id, revision)

    def read_files(self, run_id: str, revision: dict[str, Any]) -> dict[str, bytes]:
        repo = self._repository(run_id)
        return self._load(repo, run_id, revision)

    def read_file(self, run_id: str, revision: dict[str, Any], path: str) -> bytes:
        self._path(path)
        files = self.read_files(run_id, revision)
        if path not in files:
            raise GitVersionError("File is not present in this Git version")
        return files[path]

    def diff(self, run_id: str, revision: dict[str, Any]) -> str:
        return self.show(run_id, revision)["diff"]

    def show(self, run_id: str, revision: dict[str, Any]) -> dict[str, Any]:
        repo = self._repository(run_id)
        self._load(repo, run_id, revision)
        parent_commit = revision["parent_commit"]
        if parent_commit is not None:
            parent = self._commit(repo, run_id, parent_commit)
            self._read_tree(repo, parent["tree"])
        base = ["diff-tree", "--root", "--no-commit-id", "--no-renames", "--no-ext-diff", "--no-textconv", "--no-relative", "-r"]
        changes = self._git(repo, *base, "--name-status", "-z", revision["commit"]).split(b"\0")
        files = []
        if changes[-1] != b"" or (len(changes) - 1) % 2:
            raise GitVersionError(_ERROR)
        binary = set()
        for item in self._git(repo, *base, "--numstat", "-z", revision["commit"]).split(b"\0"):
            if not item:
                continue
            added, deleted, path = item.split(b"\t", 2)
            if added == b"-" and deleted == b"-":
                binary.add(path)
        for index in range(0, len(changes) - 1, 2):
            status, path = changes[index:index + 2]
            if status not in {b"A", b"M", b"D"}:
                raise GitVersionError(_ERROR)
            files.append({"path": path.decode("utf-8"), "status": status.decode("ascii"), "binary": path in binary})
        patch = self._git(
            repo, *base, "--patch", "--no-ext-diff", "--no-textconv", "--no-color", "--full-index",
            "--src-prefix=a/", "--dst-prefix=b/", revision["commit"],
        ).decode("utf-8", errors="replace")
        return {**revision, "files": files, "diff": patch}

    def _load(self, repo: Path, run_id: str, revision: dict[str, Any]) -> dict[str, bytes]:
        self._revision(revision)
        actual = self._commit(repo, run_id, revision["commit"])
        if actual != revision:
            raise GitVersionError(_ERROR)
        return self._read_tree(repo, revision["tree"])[0]

    def _read_tree(self, repo: Path, tree: str) -> tuple[dict[str, bytes], dict[str, str]]:
        entries = self._git(repo, "ls-tree", "-r", "-t", "-z", tree).split(b"\0")
        if entries[-1] != b"":
            raise GitVersionError(_ERROR)
        file_objects = {}
        requested = {tree: "tree"}
        for entry in entries[:-1]:
            try:
                metadata, name = entry.split(b"\t", 1)
                mode, kind, oid = metadata.split(b" ")
                path = name.decode("utf-8")
                object_id = oid.decode("ascii")
            except (ValueError, UnicodeError):
                raise GitVersionError(_ERROR) from None
            self._path(path)
            if mode == b"040000" and kind == b"tree":
                requested[object_id] = "tree"
            elif mode == b"100644" and kind == b"blob":
                if path in file_objects:
                    raise GitVersionError(_ERROR)
                requested[object_id] = "blob"
                file_objects[path] = object_id
            else:
                raise GitVersionError(_ERROR)
        objects = self._objects(repo, requested)
        files = {path: objects[oid] for path, oid in file_objects.items()}
        self._validate_files(files)
        return files, file_objects

    def _commit(self, repo: Path, run_id: str, commit: str) -> dict[str, Any]:
        self._oid(commit)
        ref = self._git(repo, "show-ref", "--verify", "--hash", "refs/snapshots/" + commit)
        if ref != (commit + "\n").encode("ascii"):
            raise GitVersionError(_ERROR)
        raw = self._object(repo, commit, "commit")
        try:
            header, body = raw.split(b"\n\n", 1)
            trees = [line[5:].decode("ascii") for line in header.split(b"\n") if line.startswith(b"tree ")]
            parents = [line[7:].decode("ascii") for line in header.split(b"\n") if line.startswith(b"parent ")]
            metadata = json.loads(body)
            if len(trees) != 1 or len(parents) > 1 or not isinstance(metadata, dict):
                raise ValueError
            if set(metadata) != {"format", "run_id", "message"}:
                raise ValueError
            if metadata["format"] != _FORMAT or metadata["run_id"] != run_id or not isinstance(metadata["message"], str):
                raise ValueError
            self._oid(trees[0])
            if parents:
                self._oid(parents[0])
        except (ValueError, UnicodeError):
            raise GitVersionError(_ERROR) from None
        return {"commit": commit, "parent_commit": parents[0] if parents else None, "tree": trees[0]}

    def _object(self, repo: Path, oid: str, kind: str) -> bytes:
        return self._objects(repo, {oid: kind})[oid]

    def _objects(self, repo: Path, requested: dict[str, str]) -> dict[str, bytes]:
        for oid in requested:
            self._oid(oid)
        output = self._git(repo, "cat-file", "--batch", data="".join(oid + "\n" for oid in requested).encode("ascii"))
        objects = {}
        offset = 0
        # Batch payloads are length-delimited; binary data may contain any delimiter.
        for expected_oid, expected_kind in requested.items():
            try:
                end = output.index(b"\n", offset)
                oid, kind, size = output[offset:end].split(b" ")
                if oid.decode("ascii") != expected_oid or kind.decode("ascii") != expected_kind or not size.isdigit():
                    raise ValueError
                length = int(size)
                raw = output[end + 1:end + 1 + length]
                offset = end + 1 + length
                if len(raw) != length or output[offset:offset + 1] != b"\n":
                    raise ValueError
                offset += 1
                # Git may read a recompressed loose object even when its OID is wrong.
                digest = hashlib.sha1(kind + b" " + str(length).encode("ascii") + b"\0" + raw).hexdigest()
                if digest != expected_oid:
                    raise ValueError
            except (ValueError, UnicodeError):
                raise GitVersionError(_ERROR) from None
            objects[expected_oid] = raw
        if offset != len(output):
            raise GitVersionError(_ERROR)
        return objects

    def _write_tree(
        self, repo: Path, files: dict[str, bytes], previous_files: dict[str, bytes], previous_objects: dict[str, str],
    ) -> str:
        nodes: dict[str, Any] = {}
        for path, data in files.items():
            node = nodes
            parts = path.split("/")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            if path in previous_files and previous_files[path] == data:
                node[parts[-1]] = previous_objects[path].encode("ascii")
            else:
                node[parts[-1]] = self._git(repo, "hash-object", "-w", "--stdin", "--no-filters", data=data).strip()

        def write(node: dict[str, Any]) -> str:
            entries = []
            for name, value in node.items():
                if isinstance(value, dict):
                    prefix = b"040000 tree " + write(value).encode("ascii")
                else:
                    prefix = b"100644 blob " + value
                entries.append(prefix + b"\t" + name.encode("utf-8") + b"\0")
            result = self._git(repo, "mktree", "-z", data=b"".join(entries)).decode("ascii").strip()
            self._oid(result)
            return result

        return write(nodes)

    def _repository(self, run_id: str, *, create: bool = False) -> Path:
        self._run_id(run_id)
        self._directory(self.root)
        self._directory(self._hooks)
        repo = self.root / (run_id + ".git")
        if not os.path.lexists(repo):
            if not create:
                raise GitVersionError(_ERROR)
            self._git(repo, "init", "--bare", "--template=", "--object-format=sha1")
        self._directory(repo)
        for path in (repo / "objects", repo / "objects" / "info", repo / "refs"):
            self._directory(path)
        if os.path.lexists(repo / "objects" / "info" / "alternates"):
            raise GitVersionError(_ERROR)
        return repo

    def _git(self, repo: Path, *arguments: str, data: bytes | None = None) -> bytes:
        environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
        timestamp = datetime.now(timezone.utc).isoformat()
        environment.update({
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1", "GIT_NO_REPLACE_OBJECTS": "1", "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": "Yudao", "GIT_AUTHOR_EMAIL": "host@yudao.invalid", "GIT_AUTHOR_DATE": timestamp,
            "GIT_COMMITTER_NAME": "Yudao", "GIT_COMMITTER_EMAIL": "host@yudao.invalid", "GIT_COMMITTER_DATE": timestamp,
        })
        command = [
            self._git_path, "--no-pager", "--git-dir=" + str(repo),
            "-c", "core.hooksPath=" + str(self._hooks), "-c", "commit.gpgSign=false",
            "-c", "gc.auto=0", "-c", "maintenance.auto=false", "-c", "core.autocrlf=false",
            "-c", "core.attributesFile=" + os.devnull, "-c", "core.quotePath=false",
            "-c", "diff.renames=false", "-c", "diff.noprefix=false", *arguments,
        ]
        try:
            completed = subprocess.run(command, input=data, capture_output=True, shell=False, env=environment, timeout=30, check=True)
        except (OSError, subprocess.SubprocessError):
            raise GitVersionError(_ERROR) from None
        return completed.stdout

    @staticmethod
    def _directory(path: Path, *, create: bool = False) -> None:
        try:
            if ".." in path.parts:
                raise ValueError
            for item in [*reversed(path.parents), path]:
                if not os.path.lexists(item):
                    if not create:
                        raise ValueError
                    item.mkdir()
                observed = item.lstat()
                reparse = getattr(observed, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                if not stat.S_ISDIR(observed.st_mode) or stat.S_ISLNK(observed.st_mode) or reparse:
                    raise ValueError
        except (OSError, ValueError):
            raise GitVersionError(_ERROR) from None

    @staticmethod
    def _oid(value: str) -> None:
        if not isinstance(value, str) or _OID.fullmatch(value) is None:
            raise GitVersionError(_ERROR)

    @staticmethod
    def _run_id(run_id: str) -> None:
        if not isinstance(run_id, str) or _RUN.fullmatch(run_id) is None:
            raise GitVersionError(_ERROR)
        GitVersionStore._path(run_id)

    @staticmethod
    def _path(path: str) -> None:
        try:
            validate_public_path(path)
        except (TreeError, ValueError):
            raise GitVersionError(_ERROR) from None

    @staticmethod
    def _revision(revision: dict[str, Any]) -> None:
        if not isinstance(revision, dict) or set(revision) != {"commit", "parent_commit", "tree"}:
            raise GitVersionError(_ERROR)
        GitVersionStore._oid(revision["commit"])
        GitVersionStore._oid(revision["tree"])
        if revision["parent_commit"] is not None:
            GitVersionStore._oid(revision["parent_commit"])

    @staticmethod
    def _validate_files(files: dict[str, bytes]) -> None:
        directories = set()
        try:
            for path in files:
                GitVersionStore._path(path)
                directories.update(str(parent) for parent in PurePosixPath(path).parents if str(parent) != ".")
            CapturedTree(tuple(sorted(directories)), tuple(CapturedFile(path, data) for path, data in sorted(files.items())))
        except (TreeError, ValueError):
            raise GitVersionError(_ERROR) from None
