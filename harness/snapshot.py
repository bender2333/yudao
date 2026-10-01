from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

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
    # 用 Git 命令行读取基线对应的提交、分支与是否有未提交的修改；源目录不是 git 仓库时为空
    base = Path(source_dir).absolute()
    executable = shutil.which("git")
    if executable is None:
        return {}
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    environment.update({
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_ATTR_NOSYSTEM": "1", "GIT_NO_REPLACE_OBJECTS": "1", "GIT_TERMINAL_PROMPT": "0",
    })
    inside = _git(executable, base, "rev-parse", "--is-inside-work-tree", environment=environment, check=False)
    if inside is None or inside.strip() != b"true":
        return {}
    commit = _git(executable, base, "rev-parse", "HEAD", environment=environment)
    branch = _git(executable, base, "rev-parse", "--abbrev-ref", "HEAD", environment=environment)
    status = _git(executable, base, "status", "--porcelain", environment=environment)
    return {
        "commit": commit.decode("utf-8", errors="strict").strip(),
        "branch": branch.decode("utf-8", errors="strict").strip(),
        "dirty": bool(status.strip()),
    }

def _git(executable: str, base: Path, *arguments: str, environment: dict[str, str],
         check: bool = True) -> bytes | None:
    command = [executable, "--no-pager", "-C", str(base), "-c", "core.quotePath=false", *arguments]
    completed = subprocess.run(command, capture_output=True, shell=False, env=environment, check=False, timeout=30)
    if completed.returncode != 0:
        if check:
            raise TreeError(
                f"git {' '.join(arguments)} 失败：退出状态 {completed.returncode}："
                f"{completed.stderr.decode('utf-8', errors='replace').strip()}"
            )
        return None
    return completed.stdout

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
    # git 来源由 Git 命令行读取；其余宿主私有路径（.checks）与无法表示的条目仍然拒绝
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
