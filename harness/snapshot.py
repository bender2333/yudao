from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pygit2
from pygit2.enums import RepositoryOpenFlag

from .artifacts import ArtifactStore
from .models import ArtifactRef
from .path_rules import TreeError, is_git_metadata, is_private_path
from .public_tree import (
    CapturedTree,
    capture_public_tree,
    materialize_tree,
)
from .tree_archive import load_tree, store_tree

SNAPSHOT_FIELDS = frozenset({"source", "tree_digest", "files", "directories", "tree_ref", "provenance", "bytes"})


def ingest_snapshot(source_dir: str | Path, artifacts: ArtifactStore, scope: str) -> tuple[CapturedTree, dict[str, Any]]:
    # scope 是工件所属范围：建档与修改轮的快照属于那个 run，项目起始文件夹的快照属于项目（工单 #321）
    # 只读采集：先拒绝宿主私有路径，再采集封存；源目录不被写入
    _reject_private_paths(source_dir)
    tree = capture_public_tree(source_dir, respect_ignore_rules=True)
    ref = store_tree(artifacts, scope, tree)
    record = {
        "source": str(Path(source_dir).absolute()),
        "tree_digest": tree.digest,
        "files": [item.path for item in tree.files],
        "directories": list(tree.directories),
        "tree_ref": asdict(ref),
        "provenance": git_provenance(source_dir),
        # 快照所有公开文件的总字节数：确认卡片显示快照规模用（原型 v8 快照的 bytes）
        "bytes": sum(len(item.data) for item in tree.files),
    }
    return tree, record

def git_provenance(source_dir: str | Path) -> dict[str, Any]:
    # 在进程内用 libgit2 读取基线对应的提交、分支与是否有未提交的修改；源目录不是工作树时为空
    # 只看源目录自己（工单 #841，设计第 4.6 节）：源目录本身是 Git 工作树的根目录（有自己的 .git）时才读取，
    # 不向上层目录查找——上层目录里的仓库（例如用户主目录下的 .git）既不影响结果也不被打开。
    # 源目录本身是仓库但打不开时抛 TreeError：建项目命令把它变成 source_invalid 拒绝并写明目录与原因，
    # 不是 500。快照是这个文件夹，上层仓库的提交与「有没有未提交的修改」说的是整个仓库，会误导。
    base = Path(source_dir).absolute()
    if not os.path.lexists(str(base / ".git")):
        return {}
    try:
        repository = pygit2.Repository(str(base), flags=RepositoryOpenFlag.NO_SEARCH)
    except (pygit2.GitError, OSError) as error:
        raise TreeError(f"源目录的 Git 仓库打不开：{base}：{error}") from error
    if repository.is_bare:
        # 裸库没有工作树：与 Git 命令行的 rev-parse --is-inside-work-tree 相同，来源为空
        return {}
    try:
        head = repository.head
        commit = str(head.target)
        branch = head.shorthand
    except (pygit2.GitError, KeyError) as error:
        raise TreeError(f"源目录的 Git 提交读不出：{base}：{error}") from error
    try:
        dirty = bool(repository.status())
    except (pygit2.GitError, OSError) as error:
        raise TreeError(f"源目录的 Git 状态读不出：{base}：{error}") from error
    return {"commit": commit, "branch": branch, "dirty": dirty}

def restore_snapshot(
    artifacts: ArtifactStore, scope: str, snapshot: dict[str, Any], destination: str | Path
) -> Path:
    # 仅凭持久化工件恢复：不读源目录，不执行任何命令。
    # 旧事件可能没有 provenance 或 bytes（缺省为空，ADR-0019），恢复只依据 tree_ref 与 tree_digest
    if not isinstance(snapshot, dict) or not {"source", "tree_digest", "files", "directories",
                                              "tree_ref"} <= set(snapshot):
        raise TreeError("快照记录字段不完整，无法恢复")
    tree = load_tree(artifacts, scope, ArtifactRef(**snapshot["tree_ref"]))
    if tree.digest != snapshot["tree_digest"]:
        raise TreeError("封存摘要与快照记录不一致，拒绝恢复")
    return materialize_tree(tree, destination)


def _reject_private_paths(source_dir: str | Path) -> None:
    # 采集会静默跳过宿主私有路径；快照接入必须明确拒绝并给出原因。
    # 仓库自身的 Git 元数据（.git）按设计第 4.2 节从公开树排除、不触发拒绝：任何 git 仓库的源目录都含它，
    # git 来源由进程内的 libgit2 读取；其余宿主私有路径（.checks）与无法表示的条目仍然拒绝
    base = Path(source_dir).absolute()
    pending = [(base, "")]
    while pending:
        directory, relative_directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise TreeError(f"快照源目录不可读：{source_dir}：{exc}") from exc
        for entry in entries:
            relative = f"{relative_directory}/{entry.name}" if relative_directory else entry.name
            if is_git_metadata(relative):
                continue
            if is_private_path(relative):
                raise TreeError(f"宿主私有路径不能进入公开快照：{relative}")
            if entry.is_dir(follow_symlinks=False):
                pending.append((Path(entry.path), relative))
