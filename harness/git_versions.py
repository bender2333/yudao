"""Host-owned immutable Git snapshots; accepted events own the formal history."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import pygit2
from pygit2.enums import FileMode, ObjectType, RepositoryInitFlag, RepositoryOpenFlag

from .public_tree import CapturedFile, CapturedTree, TreeError, validate_public_path

_OID = re.compile(r"[0-9a-f]{40}")
_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
_FORMAT = "yudao-git-version-v1"
_ERROR = "Git version is unavailable or invalid"
_TREE_MODES = {"tree": FileMode.TREE, "blob": FileMode.BLOB}
# 空树的固定摘要：空内容的树对象摘要，差异用它当首个版本的基准
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

class GitVersionError(ValueError):
    """A snapshot cannot be written or verified without ambiguity."""

class GitVersionStore:
    def __init__(self, root: str | Path, *, read_only: bool = False) -> None:
        self.root = Path(root).absolute()
        self.read_only = read_only
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
        repository = self._repository(run_id, create=True)
        previous_files: dict[str, bytes] = {}
        previous_objects: dict[str, str] = {}
        if parent_commit is not None:
            parent = self._commit(repository, run_id, parent_commit)
            previous_files, previous_objects = self._read_tree(repository, parent["tree"])
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
        tree = self._write_tree(repository, files, previous_files, previous_objects)
        metadata = json.dumps(
            {"format": _FORMAT, "run_id": run_id, "message": message},
            ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        parents = [] if parent_commit is None else [pygit2.Oid(hex=parent_commit)]
        commit = self._write_commit(repository, parents, tree, metadata)
        self._oid(commit)
        # This immutable ref preserves objects, but does not accept a business version.
        reference = "refs/snapshots/" + commit
        # 引用绑定与提交内容在同一次读里探测：缺失即首次绑定，已存在则必须正好是本次版本
        revision, bound = self._snapshot(repository, run_id, commit)
        if bound and revision != {"commit": commit, "parent_commit": parent_commit, "tree": tree}:
            raise GitVersionError(_ERROR)
        if not bound:
            self._bind_reference(repository, reference, commit)
        revision = {"commit": commit, "parent_commit": parent_commit, "tree": tree}
        # 绑定以后按引用回读：读取会一并校验提交与树的层级结构
        if self._read_tree(repository, reference, expected_root=tree)[0] != files:
            raise GitVersionError(_ERROR)
        return revision

    def verify(self, run_id: str, revision: dict[str, Any]) -> None:
        self.read_files(run_id, revision)

    def read_files(self, run_id: str, revision: dict[str, Any]) -> dict[str, bytes]:
        repository = self._repository(run_id)
        return self._load(repository, run_id, revision)

    def read_file(self, run_id: str, revision: dict[str, Any], path: str) -> bytes:
        self._path(path)
        files = self.read_files(run_id, revision)
        if path not in files:
            raise GitVersionError("File is not present in this Git version")
        return files[path]

    def diff(self, run_id: str, revision: dict[str, Any]) -> str:
        return self.show(run_id, revision)["diff"]

    def show(self, run_id: str, revision: dict[str, Any]) -> dict[str, Any]:
        repository = self._repository(run_id)
        self._load(repository, run_id, revision)
        parent_commit = revision["parent_commit"]
        base = None
        if parent_commit is not None:
            parent = self._commit(repository, run_id, parent_commit)
            self._read_tree(repository, parent["tree"])
            base = self._tree(repository, parent["tree"])
        else:
            # 首个版本没有父提交，与一棵空树比较得到全部文件的新增
            base = self._empty_tree(repository)
        comparison = self._diff(repository, base, self._tree(repository, revision["tree"]))
        files = []
        for patch in comparison:
            path, status, binary = self._delta(patch)
            files.append({"path": path, "status": status, "binary": binary})
        return {**revision, "files": files, "diff": comparison.patch}

    def _load(self, repository: pygit2.Repository, run_id: str, revision: dict[str, Any]) -> dict[str, bytes]:
        self._revision(revision)
        actual = self._commit(repository, run_id, revision["commit"])
        if actual != revision:
            raise GitVersionError(_ERROR)
        return self._read_tree(repository, revision["tree"])[0]

    def _read_tree(
        self, repository: pygit2.Repository, revision_ref: str, *, expected_root: str | None = None
    ) -> tuple[dict[str, bytes], dict[str, str]]:
        tree = self._tree(repository, revision_ref, expected_root=expected_root)
        file_objects: dict[str, str] = {}
        for path, object_id, kind in self._entries(repository, tree, ""):
            if kind != "blob":
                # 树的条目只接受普通文件与目录，符号链接与可执行位等不进入版本
                raise GitVersionError(_ERROR)
            if path in file_objects:
                raise GitVersionError(_ERROR)
            file_objects[path] = object_id
        blobs = self._payloads(repository, file_objects)
        files = {path: blobs[oid] for path, oid in file_objects.items()}
        self._validate_files(files)
        return files, file_objects

    def _entries(
        self, repository: pygit2.Repository, tree: pygit2.Tree, prefix: str,
    ) -> list[tuple[str, str, str]]:
        collected: list[tuple[str, str, str]] = []
        try:
            children = list(tree)
        except (pygit2.GitError, ValueError):
            raise GitVersionError(_ERROR) from None
        for child in children:
            path = prefix + child.name
            self._path(path)
            if child.type_str == "tree":
                collected.extend(self._entries(repository, child, path + "/"))
            elif child.type_str == "blob":
                collected.append((path, str(child.id), "blob"))
            else:
                raise GitVersionError(_ERROR)
        return collected

    def _commit(self, repository: pygit2.Repository, run_id: str, commit: str) -> dict[str, Any]:
        revision, bound = self._snapshot(repository, run_id, commit)
        if not bound or revision is None:
            raise GitVersionError(_ERROR)
        return revision

    def _snapshot(
        self, repository: pygit2.Repository, run_id: str, commit: str
    ) -> tuple[dict[str, Any] | None, bool]:
        """Read one snapshot commit and report whether the immutable ref already binds it."""
        self._oid(commit)
        reference = "refs/snapshots/" + commit
        target = self._reference_target(repository, reference)
        if target is None:
            return None, False
        if target != commit:
            raise GitVersionError(_ERROR)
        stored = self._raw(repository, commit, ObjectType.COMMIT)
        if stored is None:
            raise GitVersionError(_ERROR)
        try:
            header, body = stored.split(b"\n\n", 1)
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
        if self._tree_id(repository, commit) != trees[0]:
            raise GitVersionError(_ERROR)
        return {"commit": commit, "parent_commit": parents[0] if parents else None, "tree": trees[0]}, True

    def _write_tree(
        self, repository: pygit2.Repository, files: dict[str, bytes],
        previous_files: dict[str, bytes], previous_objects: dict[str, str],
    ) -> str:
        # 内容未变的文件沿用上一版已经校验过的对象，只写入真正改变的内容
        objects = {
            path: previous_objects[path]
            for path, data in files.items()
            if path in previous_files and previous_files[path] == data
        }
        for path, data in files.items():
            if path not in objects:
                objects[path] = self._write_blob(repository, data)
        nodes: dict[str, Any] = {}
        for path, object_id in objects.items():
            node = nodes
            for part in path.split("/")[:-1]:
                node = node.setdefault(part, {})
            node[path.split("/")[-1]] = object_id
        return str(self._write_trees(repository, nodes))

    def _write_trees(self, repository: pygit2.Repository, nodes: dict[str, Any]) -> pygit2.Oid:
        builder = repository.TreeBuilder()
        for name, value in nodes.items():
            builder.insert(
                name,
                self._write_trees(repository, value) if isinstance(value, dict) else pygit2.Oid(hex=value),
                _TREE_MODES["tree" if isinstance(value, dict) else "blob"],
            )
        return builder.write()

    @staticmethod
    def _empty_tree(repository: pygit2.Repository) -> pygit2.Tree:
        # 空树在建库时已经写入，这里只按它的固定摘要读取
        try:
            return repository[pygit2.Oid(hex=_EMPTY_TREE)]
        except (pygit2.GitError, KeyError, ValueError):
            raise GitVersionError(_ERROR) from None

    def _diff(
        self, repository: pygit2.Repository, base: pygit2.Tree | None, head: pygit2.Tree,
    ) -> pygit2.Diff:
        try:
            return repository.diff(base, head, context_lines=3)
        except (pygit2.GitError, ValueError, KeyError):
            raise GitVersionError(_ERROR) from None

    @staticmethod
    def _delta(patch: pygit2.Patch) -> tuple[str, str, bool]:
        file = patch.delta.new_file
        path = file.path or patch.delta.old_file.path
        if not isinstance(path, str):
            raise GitVersionError(_ERROR)
        try:
            path.encode("utf-8")
        except UnicodeError:
            raise GitVersionError(_ERROR) from None
        try:
            status = {pygit2.enums.DeltaStatus.ADDED: "A",
                      pygit2.enums.DeltaStatus.DELETED: "D",
                      pygit2.enums.DeltaStatus.MODIFIED: "M"}[patch.delta.status]
        except (KeyError, ValueError):
            raise GitVersionError(_ERROR) from None
        # 二进制内容没有文本行块，差异在补丁里只有一行说明
        return path, status, not patch.hunks

    def _repository(self, run_id: str, *, create: bool = False) -> pygit2.Repository:
        self._run_id(run_id)
        self._directory(self.root)
        self._directory(self._hooks)
        path = self.root / (run_id + ".git")
        if not os.path.lexists(path):
            if not create:
                raise GitVersionError(_ERROR)
            self._initialize(path)
        self._directory(path)
        for child in (path / "objects", path / "objects" / "info", path / "refs"):
            self._directory(child)
        if os.path.lexists(path / "objects" / "info" / "alternates"):
            raise GitVersionError(_ERROR)
        return self._open(path)

    @staticmethod
    def _initialize(path: Path) -> None:
        try:
            # 空模板与关闭钩子：宿主的版本库不读模板内容，也没有任何钩子可以运行
            repository = pygit2.init_repository(str(path), bare=True, flags=(
                RepositoryInitFlag.BARE | RepositoryInitFlag.MKPATH
                | RepositoryInitFlag.EXTERNAL_TEMPLATE
            ))
            # 空树在建库时写好：首个版本没有父提交，差异要拿它当基准，读取时才不用写入版本库
            repository.TreeBuilder().write()
        except (pygit2.GitError, OSError, ValueError):
            raise GitVersionError(_ERROR) from None

    @staticmethod
    def _open(path: Path) -> pygit2.Repository:
        try:
            # NO_SEARCH 只按给出的路径打开，版本库位置不随上层的版本库或环境改变
            return pygit2.Repository(str(path), flags=RepositoryOpenFlag.NO_SEARCH)
        except (pygit2.GitError, KeyError, OSError):
            raise GitVersionError(_ERROR) from None

    @staticmethod
    def _tree(
        repository: pygit2.Repository, revision: str, *, expected_root: str | None = None,
    ) -> pygit2.Tree:
        if expected_root is not None:
            GitVersionStore._oid(expected_root)
        try:
            resolved = repository.revparse_single(revision)
            if expected_root is not None and str(resolved.peel(pygit2.Commit).tree.id) != expected_root:
                raise GitVersionError(_ERROR)
            return resolved.peel(pygit2.Tree)
        except (pygit2.GitError, KeyError, ValueError, TypeError):
            raise GitVersionError(_ERROR) from None

    @staticmethod
    def _tree_id(repository: pygit2.Repository, commit: str) -> str:
        try:
            return str(repository.revparse_single(commit + "^{tree}").id)
        except (pygit2.GitError, KeyError, ValueError):
            raise GitVersionError(_ERROR) from None

    @staticmethod
    def _reference_target(repository: pygit2.Repository, reference: str) -> str | None:
        try:
            return str(repository.references[reference].target)
        except KeyError:
            return None
        except (pygit2.GitError, ValueError):
            raise GitVersionError(_ERROR) from None

    @staticmethod
    def _bind_reference(repository: pygit2.Repository, reference: str, commit: str) -> None:
        try:
            repository.references.create(reference, pygit2.Oid(hex=commit), force=False)
        except (pygit2.GitError, KeyError, ValueError, OSError):
            raise GitVersionError(_ERROR) from None

    @staticmethod
    def _write_blob(repository: pygit2.Repository, data: bytes) -> str:
        try:
            return str(repository.create_blob(data))
        except (pygit2.GitError, ValueError, OSError):
            raise GitVersionError(_ERROR) from None

    @staticmethod
    def _write_commit(
        repository: pygit2.Repository, parents: list[pygit2.Oid], tree: pygit2.Oid, metadata: bytes,
    ) -> str:
        # 提交的身份固定：作者与提交者是宿主，消息承载本次接纳的元数据
        timestamp = datetime.now(timezone.utc).timestamp()
        try:
            signature = pygit2.Signature("Yudao", "host@yudao.invalid", int(timestamp), 0)
            return str(repository.create_commit(
                None, signature, signature, metadata.decode("utf-8"), tree, parents,
            ))
        except (pygit2.GitError, ValueError, UnicodeError, OSError):
            raise GitVersionError(_ERROR) from None

    @staticmethod
    def _raw(repository: pygit2.Repository, oid: str, kind: ObjectType) -> bytes | None:
        try:
            observed, payload = repository.read(pygit2.Oid(hex=oid))
        except KeyError:
            return None
        except (pygit2.GitError, ValueError):
            raise GitVersionError(_ERROR) from None
        if observed != kind:
            raise GitVersionError(_ERROR)
        # 读取到的字节按自算摘要逐项核对：松散对象被改写以后内容与它的名称不再一致
        if GitVersionStore._digest(kind.name.lower(), payload) != oid:
            raise GitVersionError(_ERROR)
        return payload

    @staticmethod
    def _payloads(repository: pygit2.Repository, file_objects: dict[str, str]) -> dict[str, bytes]:
        blobs: dict[str, bytes] = {}
        for oid in file_objects.values():
            if oid in blobs:
                continue
            payload = GitVersionStore._raw(repository, oid, ObjectType.BLOB)
            if payload is None:
                raise GitVersionError(_ERROR)
            blobs[oid] = payload
        return blobs

    @staticmethod
    def _digest(kind: str, payload: bytes) -> str:
        return hashlib.sha1(kind.encode("ascii") + b" " + str(len(payload)).encode("ascii") + b"\0" + payload).hexdigest()

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
