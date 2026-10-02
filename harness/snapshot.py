from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pygit2
from pygit2.enums import RepositoryOpenFlag

from .artifacts import ArtifactStore
from .models import ArtifactRef
from .public_tree import (
    CapturedTree,
    TreeError,
    capture_public_tree,
    is_git_metadata,
    is_private_path,
    materialize_tree,
)
from .tree_archive import load_tree, store_tree

SNAPSHOT_FIELDS = frozenset({"source", "tree_digest", "files", "directories", "tree_ref", "provenance"})


def ingest_snapshot(source_dir: str | Path, artifacts: ArtifactStore, run_id: str) -> tuple[CapturedTree, dict[str, Any]]:
    # 只读采集：先拒绝宿主私有路径，再采集封存；源目录不被写入
    _reject_private_paths(source_dir)
    tree = capture_public_tree(source_dir)
    ref = store_tree(artifacts, run_id, tree)
    record = {
        "source": str(Path(source_dir).absolute()),
        "tree_digest": tree.digest,
        "files": [item.path for item in tree.files],
        "directories": list(tree.directories),
        "tree_ref": asdict(ref),
        "provenance": git_provenance(source_dir),
    }
    return tree, record

def git_provenance(source_dir: str | Path) -> dict[str, Any]:
    # 在进程内用 libgit2 读取基线对应的提交、分支与是否有未提交的修改；源目录不是工作树时为空
    base = Path(source_dir).absolute()
    found = pygit2.discover_repository(str(base))
    if found is None or not os.path.exists(found):
        return {}
    repository = pygit2.Repository(found, flags=RepositoryOpenFlag.NO_SEARCH)
    if repository.is_bare:
        # 裸库没有工作树：与 Git 命令行的 rev-parse --is-inside-work-tree 相同，来源为空
        return {}
    try:
        commit = str(repository.head.target)
    except pygit2.GitError as error:
        raise TreeError(f"git rev-parse HEAD 失败：{error}") from error
    return {"commit": commit, "branch": repository.head.shorthand, "dirty": bool(repository.status())}

def restore_snapshot(
    artifacts: ArtifactStore, run_id: str, snapshot: dict[str, Any], destination: str | Path
) -> Path:
    # 仅凭持久化工件恢复：不读源目录，不执行任何命令。
    # 旧事件没有 provenance 字段（缺省为空，ADR-0019），恢复只依据 tree_ref 与 tree_digest
    if not isinstance(snapshot, dict) or set(snapshot) not in (SNAPSHOT_FIELDS, SNAPSHOT_FIELDS - {"provenance"}):
        raise TreeError("快照记录字段不完整，无法恢复")
    tree = load_tree(artifacts, run_id, ArtifactRef(**snapshot["tree_ref"]))
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
