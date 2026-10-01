"""Host-owned immutable Git snapshots; accepted events own the formal history."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .public_tree import CapturedFile, CapturedTree, TreeError, validate_public_path


_OID = re.compile(r"[0-9a-f]{40}")
_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
_FORMAT = "yudao-git-version-v1"
_ERROR = "Git version is unavailable or invalid"
_TREE_MODES = {"tree": b"40000", "blob": b"100644"}


class GitVersionError(ValueError):
    """A snapshot cannot be written or verified without ambiguity."""


class GitVersionStore:
    def __init__(self, root: str | Path, *, read_only: bool = False) -> None:
        self.root = Path(root).absolute()
        self.read_only = read_only
        self._git_path = shutil.which("git")
        if self._git_path is None:
            raise GitVersionError("Git executable is unavailable")
        self._hooks = self.root / "empty-hooks"
        if read_only:
            # 只读使用不建立目录：需要 Git 历史的操作在目录缺失时给出同样的错误
            return
        self._directory(self.root, create=True)
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
        # 引用绑定与提交内容在同一次批量读里探测：缺失即首次绑定，已存在则必须正好是本次版本
        revision, bound = self._snapshot(repo, run_id, commit)
        if bound and revision != {"commit": commit, "parent_commit": parent_commit, "tree": tree}:
            raise GitVersionError(_ERROR)
        if not bound:
            self._git(repo, "update-ref", reference, commit, "0" * 40)
        revision = {"commit": commit, "parent_commit": parent_commit, "tree": tree}
        # 绑定以后按引用回读：Git 会一并校验提交与树的层级结构
        if self._read_tree(repo, reference, expected_root=tree)[0] != files:
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

    def _read_tree(self, repo: Path, revision_ref: str, *, expected_root: str | None = None) -> tuple[dict[str, bytes], dict[str, str]]:
        entries = self._git(repo, "ls-tree", "-r", "-t", "-z", revision_ref).split(b"\0")
        if entries[-1] != b"":
            raise GitVersionError(_ERROR)
        file_objects = {}
        requested = {(revision_ref if expected_root is None else expected_root): "tree"}
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
        revision, bound = self._snapshot(repo, run_id, commit)
        if not bound or revision is None:
            raise GitVersionError(_ERROR)
        return revision

    def _snapshot(self, repo: Path, run_id: str, commit: str) -> tuple[dict[str, Any] | None, bool]:
        """Read one snapshot commit and report whether the immutable ref already binds it."""
        self._oid(commit)
        # 绑定探测、提交内容与树的指向在同一次批量读里完成，不再单开引用查询进程
        binding, stored, root = self._batch(repo, (
            ("refs/snapshots/" + commit, "commit", commit),
            (commit, "commit", commit),
            (commit + "^{tree}", "tree", None),
        ))
        if binding is None:
            return None, False
        if stored is None or root is None:
            raise GitVersionError(_ERROR)
        try:
            header, body = stored[1].split(b"\n\n", 1)
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
        # 引用解析出的树必须就是提交头里的那一棵，缺失即说明引用未指向本提交
        if root[0] != trees[0]:
            raise GitVersionError(_ERROR)
        return {"commit": commit, "parent_commit": parents[0] if parents else None, "tree": trees[0]}, True

    def _objects(self, repo: Path, requested: dict[str, str]) -> dict[str, bytes]:
        for oid in requested:
            self._oid(oid)
        records = self._batch(repo, tuple((oid, kind, oid) for oid, kind in requested.items()))
        objects = {}
        for oid, record in zip(requested, records):
            if record is None:
                raise GitVersionError(_ERROR)
            objects[oid] = record[1]
        return objects

    def _batch(self, repo: Path, requests: tuple[tuple[str, str, str | None], ...]) -> list[tuple[str, bytes] | None]:
        """Read many objects in one Git process; an unresolvable request comes back as None."""
        output = self._git(
            repo, "cat-file", "--batch",
            data="".join(request + "\n" for request, _, _ in requests).encode("ascii"),
        )
        records: list[tuple[str, bytes] | None] = []
        offset = 0
        # Batch payloads are length-delimited; binary data may contain any delimiter.
        for line, expected_kind, expected_oid in requests:
            try:
                end = output.index(b"\n", offset)
                fields = output[offset:end].split(b" ")
                if len(fields) == 2 and fields[1] == b"missing":
                    records.append(None)
                    offset = end + 1
                    continue
                oid, kind, size = fields
                observed_kind = kind.decode("ascii")
                object_id = oid.decode("ascii")
                if observed_kind != expected_kind or not size.isdigit():
                    raise ValueError
                length = int(size)
                raw = output[end + 1:end + 1 + length]
                offset = end + 1 + length
                if len(raw) != length or output[offset:offset + 1] != b"\n":
                    raise ValueError
                offset += 1
                # Git may read a recompressed loose object even when its OID is wrong.
                if self._digest(observed_kind, raw) != object_id:
                    raise ValueError
                if expected_oid is not None and object_id != expected_oid:
                    raise ValueError
            except (ValueError, UnicodeError):
                raise GitVersionError(_ERROR) from None
            records.append((object_id, raw))
        if offset != len(output):
            raise GitVersionError(_ERROR)
        return records

    def _write_tree(
        self, repo: Path, files: dict[str, bytes], previous_files: dict[str, bytes], previous_objects: dict[str, str],
    ) -> str:
        objects = {
            path: previous_objects[path]
            for path, data in files.items()
            if path in previous_files and previous_files[path] == data
        }
        # 临时文件落在版本库根之外：读操作要求版本库目录在写入前后逐字节一致
        staging = Path(tempfile.mkdtemp(prefix="yudao-git-"))
        try:
            objects.update(self._write_blobs(repo, staging, {
                path: data for path, data in files.items() if path not in objects}))
            nodes: dict[str, Any] = {}
            for path, object_id in objects.items():
                node = nodes
                for part in path.split("/")[:-1]:
                    node = node.setdefault(part, {})
                node[path.split("/")[-1]] = object_id
            return self._write_trees(repo, staging, nodes)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _write_blobs(self, repo: Path, staging: Path, pending: dict[str, bytes]) -> dict[str, str]:
        # 一次进程写入全部变更内容；Git 返回的摘要必须与自算摘要逐项相等
        if not pending:
            return {}
        items = list(pending.items())
        paths = self._stage(staging, "blob", [data for _, data in items])
        written = self._hash_objects(repo, "blob", paths, [self._digest("blob", data) for _, data in items])
        return {path: object_id for (path, _), object_id in zip(items, written)}

    def _write_trees(self, repo: Path, staging: Path, nodes: dict[str, Any]) -> str:
        records: list[bytes] = []

        def build(node: dict[str, Any]) -> str:
            entries = []
            for name, value in node.items():
                subtree = isinstance(value, dict)
                object_id = build(value) if subtree else value
                # Git 比较 tree 条目时把目录名连同结尾的斜杠一起排序
                # 条目内容是「模式 名字 结束符 对象摘要的二十字节原始形式」，不含对象种类
                entries.append((
                    name.encode("utf-8") + (b"/" if subtree else b""),
                    _TREE_MODES["tree" if subtree else "blob"] + b" " + name.encode("utf-8") + b"\x00" + bytes.fromhex(object_id),
                ))
            content = b"".join(record for _, record in sorted(entries))
            records.append(content)
            return self._digest("tree", content)

        root = build(nodes)
        paths = self._stage(staging, "tree", records)
        self._hash_objects(repo, "tree", paths, [self._digest("tree", content) for content in records])
        return root

    @staticmethod
    def _stage(staging: Path, kind: str, payloads: list[bytes]) -> list[str]:
        paths = []
        for index, data in enumerate(payloads):
            file = staging / (kind + "-" + str(index))
            file.write_bytes(data)
            paths.append(str(file))
        return paths

    def _hash_objects(self, repo: Path, kind: str, paths: list[str], expected: list[str]) -> list[str]:
        written = self._git(
            repo, "hash-object", "-w", *(["-t", kind] if kind != "blob" else []), "--no-filters", "--stdin-paths",
            data=os.fsencode("\n".join(paths)) + b"\n",
        ).decode("ascii").split()
        if len(written) != len(expected) or any(
            _OID.fullmatch(observed) is None or observed != want for observed, want in zip(written, expected)
        ):
            raise GitVersionError(_ERROR)
        return written

    @staticmethod
    def _digest(kind: str, payload: bytes) -> str:
        return hashlib.sha1(kind.encode("ascii") + b" " + str(len(payload)).encode("ascii") + b"\0" + payload).hexdigest()

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
