from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .artifacts import ArtifactStore
from .models import ArtifactRef
from .public_tree import (
    CapturedTree,
    TreeError,
    capture_public_tree,
    is_private_path,
    materialize_tree,
)
from .tree_archive import load_tree, store_tree

SNAPSHOT_FIELDS = frozenset({"source", "tree_digest", "files", "directories", "tree_ref"})


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
    }
    return tree, record


def restore_snapshot(
    artifacts: ArtifactStore, run_id: str, snapshot: dict[str, Any], destination: str | Path
) -> Path:
    # 仅凭持久化工件恢复：不读源目录，不执行任何命令
    if not isinstance(snapshot, dict) or set(snapshot) != SNAPSHOT_FIELDS:
        raise TreeError("快照记录字段不完整，无法恢复")
    tree = load_tree(artifacts, run_id, ArtifactRef(**snapshot["tree_ref"]))
    if tree.digest != snapshot["tree_digest"]:
        raise TreeError("封存摘要与快照记录不一致，拒绝恢复")
    return materialize_tree(tree, destination)


def _reject_private_paths(source_dir: str | Path) -> None:
    # 采集会静默跳过宿主私有路径；快照接入必须明确拒绝并给出原因
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
            if is_private_path(relative):
                raise TreeError(f"宿主私有路径不能进入公开快照：{relative}")
            if entry.is_dir(follow_symlinks=False):
                pending.append((Path(entry.path), relative))
