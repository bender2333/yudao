"""Adopted change writeback with three-tree merge (ADR-0034)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

import pygit2
from pygit2.enums import FileMode, RepositoryInitFlag, RepositoryOpenFlag

from .artifacts import ArtifactStore
from .event_store import Command, project_stream
from .environment import _resolve_bash
from .models import (
    ArtifactRef,
    ProjectEvent,
    ProjectEventType,
    json_dumps,
    new_id,
)
from .path_rules import TreeError, is_private_path
from .parameters import value_for_project
from .public_tree import CapturedFile, CapturedTree, materialize_tree
from .tree_archive import artifact_run, load_tree, store_tree
from .write_path import NewProjectEvent, Transaction

def _ref_dict(ref: Any) -> dict[str, Any] | None:
    if ref is None:
        return None
    if isinstance(ref, dict):
        return ref
    return asdict(ref)


class WritebackTargetUnavailable(Exception):
    # 写回的目标不可用：远端仓库路径不存在、那个路径不是 git 仓库，或目标分支不存在。
    # 三种都是源目录登记里的配置问题，由命令层给出中文的拒绝说明（工单 #709）。
    def __init__(self, reason: str, target: str) -> None:
        super().__init__(f"{reason}: {target}")
        self.reason = reason
        self.target = target


def build_git_tree(
    repo: pygit2.Repository,
    tree: CapturedTree,
    reference_tree: pygit2.Tree | None = None,
) -> pygit2.Tree:
    """Build a pygit2 Tree from a CapturedTree, preserving executable flags from reference_tree."""
    executable_paths: set[str] = set()
    if reference_tree is not None:
        _collect_executable_paths(repo, reference_tree, "", executable_paths)

    nodes: dict[str, Any] = {}
    for item in tree.files:
        blob_id = repo.create_blob(item.data)
        mode = FileMode.BLOB_EXECUTABLE if item.path in executable_paths else FileMode.BLOB
        parts = item.path.split("/")
        curr = nodes
        for part in parts[:-1]:
            curr = curr.setdefault(part, {})
        curr[parts[-1]] = (blob_id, mode)

    def _build(node: dict[str, Any]) -> pygit2.Oid:
        builder = repo.TreeBuilder()
        for name, value in node.items():
            if isinstance(value, dict):
                sub_tree_oid = _build(value)
                builder.insert(name, sub_tree_oid, FileMode.TREE)
            else:
                oid, mode = value
                builder.insert(name, oid, mode)
        return builder.write()

    return repo[_build(nodes)]


def _collect_executable_paths(
    repo: pygit2.Repository, tree: pygit2.Tree, prefix: str, out: set[str]
) -> None:
    for entry in tree:
        path = f"{prefix}{entry.name}"
        if entry.type_str == "tree":
            _collect_executable_paths(repo, repo[entry.id], f"{path}/", out)
        elif entry.type_str == "blob" and entry.filemode == FileMode.BLOB_EXECUTABLE:
            out.add(path)


def git_tree_to_captured(repo: pygit2.Repository, tree: pygit2.Tree) -> CapturedTree:
    """Extract CapturedTree from pygit2 Tree."""
    files: list[CapturedFile] = []
    directories: set[str] = set()

    def _walk(curr_tree: pygit2.Tree, prefix: str) -> None:
        for entry in curr_tree:
            path = f"{prefix}{entry.name}"
            if is_private_path(path):
                continue
            if entry.type_str == "tree":
                directories.add(path)
                _walk(repo[entry.id], f"{path}/")
            elif entry.type_str == "blob":
                data = repo[entry.id].data
                files.append(CapturedFile(path, data))

    _walk(tree, "")
    return CapturedTree(tuple(sorted(directories)), tuple(files))


def classify_conflict(
    anc: pygit2.IndexEntry | None,
    ours: pygit2.IndexEntry | None,
    theirs: pygit2.IndexEntry | None,
    base_captured: CapturedTree,
    target_captured: CapturedTree,
    adopted_captured: CapturedTree,
) -> str:
    path = (ours or theirs or anc).path
    all_dirs = set(base_captured.directories) | set(target_captured.directories) | set(adopted_captured.directories)
    if path in all_dirs:
        return "path_type"
    for tree in (base_captured, target_captured, adopted_captured):
        if any(f.path.startswith(f"{path}/") for f in tree.files):
            return "path_type"
    if ours is not None and theirs is not None and ours.mode != theirs.mode:
        return "path_type"
    if ours is None or theirs is None:
        return "delete_modify"
    return "content"


def is_adoption_merged_in_target(
    repo: pygit2.Repository,
    target_commit: pygit2.Commit,
    previous_adoption_id: str,
    prev_writeback_branch: str | None = None,
    prev_pr_identity: str | None = None,
) -> bool:
    """Check if previous adoption is merged into target branch (including squash merges)."""
    search_keys = [previous_adoption_id]
    if prev_writeback_branch:
        search_keys.append(prev_writeback_branch)
        if prev_writeback_branch.startswith("refs/heads/"):
            search_keys.append(prev_writeback_branch[len("refs/heads/"):])
        else:
            search_keys.append(f"refs/heads/{prev_writeback_branch}")
    if prev_pr_identity:
        search_keys.append(prev_pr_identity)

    ref_names_to_try = []
    if prev_writeback_branch:
        ref_names_to_try.extend([
            prev_writeback_branch,
            f"refs/heads/{prev_writeback_branch}",
            f"refs/remotes/origin/{prev_writeback_branch}",
        ])
    for r_name in ref_names_to_try:
        if r_name in repo.references:
            prev_c = repo.references[r_name].peel(pygit2.Commit)
            if repo.descendant_of(target_commit.id, prev_c.id):
                return True

    for commit in repo.walk(target_commit.id, pygit2.enums.SortMode.TIME):
        msg = commit.message or ""
        if any(key in msg for key in search_keys):
            return True
    return False


def run_writeback_checks(
    workspace_path: Path,
    check_commands: Sequence[str],
    timeout_sec: float,
    artifacts: ArtifactStore,
    run_id: str,
    final_tree_digest: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Run writeback check command strings on the check copy."""
    if not check_commands:
        return [], False

    receipts: list[dict[str, Any]] = []
    all_passed = True

    for check_command in check_commands:
        start = time.monotonic()
        timed_out = False
        try:
            completed = subprocess.run(
                [_resolve_bash(), "-c", check_command],
                cwd=str(workspace_path),
                capture_output=True,
                timeout=timeout_sec,
                check=False,
            )
            code = completed.returncode
            output = completed.stdout + (b"\n" if completed.stdout and completed.stderr else b"") + completed.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            code = -1
            output = (exc.stdout or b"") + (exc.stderr or b"")
        except Exception as exc:
            code = -1
            output = str(exc).encode("utf-8")

        duration_ms = int((time.monotonic() - start) * 1000)
        output_ref = artifacts.put(run_id, "check_output", output, media_type="text/plain")

        receipt = {
            "name": check_command,
            "command": check_command,
            "exit_code": code,
            "output_ref": _ref_dict(output_ref),
            "tree_digest": final_tree_digest,
            "timed_out": timed_out,
            "duration_ms": duration_ms,
        }
        receipts.append(receipt)

        if code != 0 or timed_out:
            all_passed = False
            break

    return receipts, all_passed


def _stop(
    *,
    system: Any,
    project_id: str,
    item: Any,
    adoption: Any,
    reason: str,
    target_commit: pygit2.Commit,
    source_tree_digest: str,
    adopted_tree_digest: str,
    target_tree_digest: str,
    final_tree_digest: str | None,
    conflict_ref: Any,
    conflicts: list[dict[str, Any]],
    check_receipts: list[dict[str, Any]],
    new_target_commit: str | None,
    command: Command | None,
) -> ProjectEvent | None:
    """追加一条 writeback_stopped：写回停止时的事实统一经过这里写入项目流。"""
    written = system.writes.transact(
        project_stream(project_id),
        lambda tx: tx.append(
            NewProjectEvent(
                ProjectEventType.WRITEBACK_STOPPED,
                {
                    "work_item_id": item.work_item_id,
                    "run_id": adoption.run_id,
                    "adoption_id": adoption.adoption_id,
                    "reason": reason,
                    "target_commit": str(target_commit.id),
                    "source_tree_digest": source_tree_digest,
                    "adopted_tree_digest": adopted_tree_digest,
                    "target_tree_digest": target_tree_digest,
                    "final_tree_digest": final_tree_digest,
                    "conflict_ref": _ref_dict(conflict_ref),
                    "conflicts": conflicts,
                    "check_receipts": check_receipts,
                    "new_target_commit": new_target_commit,
                },
                actor="system",
            )
        ),
        command=command,
    )
    return written[0] if written else None


def perform_writeback(
    system: Any,
    project_id: str,
    adoption_id: str,
    *,
    command: Command | None = None,
    simulate_unknown_push: bool = False,
) -> ProjectEvent | None:
    """Execute three-tree writeback merge, verification, and branch push."""
    store = system.store
    artifacts = system.artifacts
    project = system.projection(project_id)

    # 1. 查找源目录与写回配置
    source_dir = next((d for d in project.source_directories.values() if d.writeback_enabled), None)
    if source_dir is None:
        return None

    remote_name_or_url = source_dir.remote
    target_branch = source_dir.target_branch
    check_commands = list(source_dir.check_commands)

    # 2. 查找本次采纳与对应事项
    adoption = next((a for a in project.adoptions if a.adoption_id == adoption_id), None)
    if adoption is None:
        return None

    item = project.work_item(adoption.work_item_id)
    if item is None or item.kind == "onboarding":
        # 建档采纳不写回
        return None

    # 3. 准备隔离的 Git 工作仓库（独立目录，不触碰源目录未提交修改）
    remote_repo_path = _resolve_repo_path(source_dir.path, remote_name_or_url)
    if not os.path.exists(remote_repo_path):
        raise WritebackTargetUnavailable("remote_missing", str(remote_repo_path))

    # 先确认目标是 git 仓库再克隆：克隆一个不是仓库的目录抛出的 GitError 与「目标不可用」是
    # 同一类配置问题，命令层照「不是 git 仓库」拒绝，接口层不再回 500（工单 #902）
    target_ref_name = f"refs/heads/{target_branch}"
    try:
        remote_repo = pygit2.Repository(str(remote_repo_path))
    except pygit2.GitError as error:
        raise WritebackTargetUnavailable("not_a_repository", str(remote_repo_path)) from error
    if target_ref_name not in remote_repo.references:
        raise WritebackTargetUnavailable("target_branch_missing", target_branch)
    remote_target_commit = remote_repo.references[target_ref_name].peel(pygit2.Commit)
    target_is_bare = remote_repo.is_bare
    del remote_repo

    scratch_temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        scratch_dir = Path(scratch_temp.name) / "scratch.git"
        # 复制或打开仓库进行操作
        repo = pygit2.clone_repository(str(remote_repo_path), str(scratch_dir), bare=False)

        # 4. 读取目标提交与目标树
        target_commit = repo[remote_target_commit.id]
        if target_ref_name not in repo.references:
            repo.create_reference(target_ref_name, target_commit.id, force=True)

        target_tree = target_commit.tree
        target_captured = git_tree_to_captured(repo, target_tree)
        target_tree_digest = target_captured.digest

        # 5. 加载起点树（base tree）与采纳树（adopted tree）
        base_captured: CapturedTree
        base_tree_digest: str
        if item.baseline is not None:
            base_ref = item.baseline["tree_ref"]
            base_tree_digest = item.baseline["code_tree_digest"]
            base_captured = load_tree(artifacts, artifact_run(base_ref["path"]), ArtifactRef(**base_ref))
        elif item.snapshot is not None:
            base_ref = item.snapshot["tree_ref"]
            base_tree_digest = item.snapshot["tree_digest"]
            base_captured = load_tree(artifacts, artifact_run(base_ref["path"]), ArtifactRef(**base_ref))
        else:
            # 缺少起点依据：无法得出本事项的变更集，停止写回（ADR-0034）
            return _stop(
                system=system, project_id=project_id, item=item, adoption=adoption,
                reason="missing_source_reference", target_commit=target_commit,
                source_tree_digest="", adopted_tree_digest=adoption.code_tree_digest,
                target_tree_digest=target_tree_digest, final_tree_digest=None,
                conflict_ref=None, conflicts=[], check_receipts=[], new_target_commit=None,
                command=command,
            )

        adopted_ref = adoption.tree_ref
        adopted_tree_digest = adoption.code_tree_digest
        adopted_captured = load_tree(artifacts, artifact_run(adopted_ref["path"]), ArtifactRef(**adopted_ref))

        # 6. 检查前项依赖与顺序（连续采纳第二项依赖前项时等待前项合入）
        if item.baseline is not None:
            prev_adoption_id = item.baseline.get("adoption_id")
            if prev_adoption_id and prev_adoption_id != adoption.adoption_id:
                prev_adoption = next((a for a in project.adoptions if a.adoption_id == prev_adoption_id), None)
                prev_item = project.work_item(prev_adoption.work_item_id) if prev_adoption else None
                # 建档采纳不写回，因此无需等待建档采纳合入
                if prev_item is not None and prev_item.kind != "onboarding":
                    prev_record = next((wb for wb in reversed(project.writebacks) if wb.adoption_id == prev_adoption_id), None)
                    prev_branch = prev_record.branch if prev_record else f"writeback/{prev_adoption_id}"
                    prev_pr_id = prev_record.pull_request.get("identity") if prev_record and prev_record.pull_request else f"pr-{prev_adoption_id}"

                    if not is_adoption_merged_in_target(repo, target_commit, prev_adoption_id, prev_branch, prev_pr_id):
                        held_event = system.writes.transact(
                            project_stream(project_id),
                            lambda tx: tx.append(
                                NewProjectEvent(
                                    ProjectEventType.WRITEBACK_HELD,
                                    {
                                        "work_item_id": item.work_item_id,
                                        "run_id": adoption.run_id,
                                        "adoption_id": adoption.adoption_id,
                                        "reason": "waiting_previous_adoption",
                                        "previous_adoption_id": prev_adoption_id,
                                        "target_commit": str(target_commit.id),
                                    },
                                    actor="system",
                                )
                            ),
                            command=command,
                        )
                        return held_event[0] if held_event else None

        # 7. 在 git repo 中构建 base_tree 与 adopted_tree
        base_git_tree = build_git_tree(repo, base_captured, target_tree)
        adopted_git_tree = build_git_tree(repo, adopted_captured, target_tree)

        # 8. 执行 pygit2 三方合并
        merge_index = repo.merge_trees(base_git_tree, target_tree, adopted_git_tree)

        # 9. 冲突检查
        if merge_index.conflicts is not None:
            conflicts_list = []
            for anc, ours, theirs in merge_index.conflicts:
                path = (ours or theirs or anc).path
                kind = classify_conflict(anc, ours, theirs, base_captured, target_captured, adopted_captured)
                conflicts_list.append({
                    "path": path,
                    "kind": kind,
                    "ancestor": str(anc.id) if anc else None,
                    "ours": str(ours.id) if ours else None,
                    "theirs": str(theirs.id) if theirs else None,
                })

            conflict_payload_raw = json_dumps(conflicts_list).encode("utf-8")
            conflict_ref = artifacts.put(
                adoption.run_id, "writeback_conflict", conflict_payload_raw, media_type="application/json"
            )

            return _stop(
                system=system, project_id=project_id, item=item, adoption=adoption,
                reason="conflict", target_commit=target_commit,
                source_tree_digest=base_tree_digest, adopted_tree_digest=adopted_tree_digest,
                target_tree_digest=target_tree_digest, final_tree_digest=None,
                conflict_ref=conflict_ref, conflicts=conflicts_list, check_receipts=[],
                new_target_commit=None, command=command,
            )

        # 10. 合并无冲突，写入最终树
        try:
            final_tree_oid = merge_index.write_tree(repo)
            final_git_tree = repo[final_tree_oid]
            final_captured_tree = git_tree_to_captured(repo, final_git_tree)
            final_tree_digest = final_captured_tree.digest
            final_tree_ref = store_tree(artifacts, adoption.run_id, final_captured_tree)
        except Exception as exc:
            return _stop(
                system=system, project_id=project_id, item=item, adoption=adoption,
                reason="unrepresentable_path", target_commit=target_commit,
                source_tree_digest=base_tree_digest, adopted_tree_digest=adopted_tree_digest,
                target_tree_digest=target_tree_digest, final_tree_digest=None,
                conflict_ref=None,
                conflicts=[{"path": str(exc), "kind": "unrepresentable_path"}],
                check_receipts=[], new_target_commit=None, command=command,
            )

        # 11. 检查是否无需写回（变更已全部存在于目标树）
        if final_tree_oid == target_tree.id:
            not_needed_event = system.writes.transact(
                project_stream(project_id),
                lambda tx: tx.append(
                    NewProjectEvent(
                        ProjectEventType.WRITEBACK_NOT_NEEDED,
                        {
                            "work_item_id": item.work_item_id,
                            "run_id": adoption.run_id,
                            "adoption_id": adoption.adoption_id,
                            "target_commit": str(target_commit.id),
                            "reason": "changes_already_present",
                            "source_tree_digest": base_tree_digest,
                            "adopted_tree_digest": adopted_tree_digest,
                            "target_tree_digest": target_tree_digest,
                        },
                        actor="system",
                    )
                ),
                command=command,
            )
            return not_needed_event[0] if not_needed_event else None

        # 12. 在独立检查副本中执行写回检查：源目录设置里写明的写回检查命令与本次采纳成果登记的检查命令
        # 都包含在这份清单里，覆盖本次交付与项目基线已有的检查（ADR-0034）
        check_commands = list(check_commands)
        for check_command in adoption.check_names:
            if check_command not in check_commands:
                check_commands.append(check_command)
        check_timeout = float(value_for_project(store, project_id, "check_timeout_sec") or 600)
        with tempfile.TemporaryDirectory() as check_temp:
            check_workspace = Path(check_temp) / "check_copy"
            materialize_tree(final_captured_tree, check_workspace)

            receipts, checks_passed = run_writeback_checks(
                workspace_path=check_workspace,
                check_commands=check_commands,
                timeout_sec=check_timeout,
                artifacts=artifacts,
                run_id=adoption.run_id,
                final_tree_digest=final_tree_digest,
            )

        if not checks_passed:
            return _stop(
                system=system, project_id=project_id, item=item, adoption=adoption,
                reason="verification_failed", target_commit=target_commit,
                source_tree_digest=base_tree_digest, adopted_tree_digest=adopted_tree_digest,
                target_tree_digest=target_tree_digest, final_tree_digest=final_tree_digest,
                conflict_ref=None, conflicts=[], check_receipts=receipts,
                new_target_commit=None, command=command,
            )

        # 13. 推送前核对目标分支是否改变（target_changed 检测）
        # 重新读取远端仓库目标分支 tip
        remote_repo = pygit2.Repository(str(remote_repo_path))
        latest_target_commit = remote_repo.references[target_ref_name].peel(pygit2.Commit)
        if latest_target_commit.id != target_commit.id:
            return _stop(
                system=system, project_id=project_id, item=item, adoption=adoption,
                reason="target_changed", target_commit=target_commit,
                source_tree_digest=base_tree_digest, adopted_tree_digest=adopted_tree_digest,
                target_tree_digest=target_tree_digest, final_tree_digest=final_tree_digest,
                conflict_ref=None, conflicts=[], check_receipts=receipts,
                new_target_commit=str(latest_target_commit.id), command=command,
            )

        # 14. 准备独立分支与提交
        branch_name = f"writeback/{adoption.adoption_id}"
        branch_ref_name = f"refs/heads/{branch_name}"
        verified_external = False

        # 核实远端分支是否已存在（外部结果未知先核实）
        if branch_ref_name in remote_repo.references:
            existing_remote_commit = remote_repo.references[branch_ref_name].peel(pygit2.Commit)
            if existing_remote_commit.tree.id == final_tree_oid and (
                existing_remote_commit.parents and existing_remote_commit.parents[0].id == target_commit.id
            ):
                verified_external = True
                # 追加核实事件
                system.writes.transact(
                    project_stream(project_id),
                    lambda tx: tx.append(
                        NewProjectEvent(
                            ProjectEventType.WRITEBACK_VERIFIED,
                            {
                                "work_item_id": item.work_item_id,
                                "run_id": adoption.run_id,
                                "adoption_id": adoption.adoption_id,
                                "action": "push",
                                "branch": branch_name,
                                "target_commit": str(target_commit.id),
                                "verified_fact": {
                                    "remote_branch": branch_name,
                                    "commit": str(existing_remote_commit.id),
                                    "verified": True,
                                },
                            },
                            actor="system",
                        )
                    ),
                    command=command,
                )

        if not verified_external:
            sig = pygit2.Signature("Yudao", "host@yudao.invalid")
            commit_msg = (
                f"Writeback adoption {adoption.adoption_id} for {item.title}\n\n"
                f"adoption_id: {adoption.adoption_id}\n"
                f"run_id: {adoption.run_id}\n"
                f"summary: {adoption.summary}\n"
            )
            writeback_commit_oid = repo.create_commit(
                branch_ref_name, sig, sig, commit_msg, final_tree_oid, [target_commit.id]
            )

            if target_is_bare:
                # 推送到远端裸仓库
                remote_obj = repo.remotes["origin"]
                remote_obj.push([f"{branch_ref_name}:{branch_ref_name}"])
            else:
                # 远端留空时目标是源目录这个普通仓库：libgit2 不支持向非裸仓库推送，
                # 把写回分支直接写进目标仓库（工单 #902）
                _write_local_branch(remote_repo_path, repo, branch_ref_name, writeback_commit_oid)

            if simulate_unknown_push:
                # 模拟推送已在远端完成但调用方收到未知结果中断
                raise RuntimeError("simulated unknown push outcome")

        # 15. 合并请求（本地测试保留明确未验收边界）
        pull_request = {
            "identity": f"pr-{adoption.adoption_id}",
            "branch": branch_name,
            "target_branch": target_branch,
            "title": f"[{item.title}] {adoption.summary}",
            "status": "local_test_boundary",
            "boundary_note": "合并请求在自举试点以真实 GitHub 验收，本地测试保留明确的未验收边界",
        }

        # 16. 记录 writeback_completed 事件
        completed_event = system.writes.transact(
            project_stream(project_id),
            lambda tx: tx.append(
                NewProjectEvent(
                    ProjectEventType.WRITEBACK_COMPLETED,
                    {
                        "work_item_id": item.work_item_id,
                        "run_id": adoption.run_id,
                        "adoption_id": adoption.adoption_id,
                        "source_tree_digest": base_tree_digest,
                        "source_tree_ref": _ref_dict(base_ref),
                        "adopted_tree_digest": adopted_tree_digest,
                        "adopted_tree_ref": _ref_dict(adopted_ref),
                        "target_commit": str(target_commit.id),
                        "target_tree_digest": target_tree_digest,
                        "final_tree_digest": final_tree_digest,
                        "final_tree_ref": _ref_dict(final_tree_ref),
                        "check_receipts": receipts,
                        "branch": branch_name,
                        "pull_request": pull_request,
                        "verified_external": verified_external,
                    },
                    actor="system",
                )
            ),
            command=command,
        )
        return completed_event[0] if completed_event else None

    finally:
        try:
            del repo
        except Exception:
            pass
        import gc
        gc.collect()
        try:
            scratch_temp.cleanup()
        except Exception:
            pass


def _write_local_branch(
    target_path: Path,
    scratch_repo: pygit2.Repository,
    ref_name: str,
    commit_id: pygit2.Oid,
) -> None:
    """把写回分支写进本地的目标仓库。

    libgit2 不支持向非裸仓库推送（local push doesn't (yet) support pushing to non-bare
    repos），而远端留空时目标正是源目录这个普通仓库（工单 #902）。这里把新提交缺的对象
    补进目标仓库，再建立分支引用；目标仓库的工作区与 main 都不动。
    """
    target_repo = pygit2.Repository(str(target_path))
    copied: set[str] = set()

    def _copy(oid: pygit2.Oid) -> None:
        key = str(oid)
        if key in copied:
            return
        copied.add(key)
        try:
            target_repo[oid]
            return
        except KeyError:
            pass
        obj = scratch_repo[oid]
        if obj.type_str == "commit":
            _copy(obj.tree.id)
            for parent in obj.parents:
                _copy(parent.id)
        elif obj.type_str == "tree":
            for entry in obj:
                _copy(entry.id)
        target_repo.odb.write(obj.type, obj.read_raw())

    _copy(commit_id)
    target_repo.references.create(ref_name, commit_id)


def _resolve_repo_path(source_dir_path: str, remote_setting: str) -> Path:
    """Resolve the git repository path for remote bare repo or source directory.

    远端留空表示源目录本身；相对路径只按源目录解析，任何情况下都不按 Yudao 服务进程的
    当前目录解析；远端是源目录仓库里登记的远端名时取它登记的地址（工单 #902）。
    """
    source_path = Path(source_dir_path)
    setting = (remote_setting or "").strip()
    if not setting:
        return source_path.resolve()

    candidate = Path(setting)
    if candidate.is_absolute():
        return candidate.resolve()

    under_source = source_path / setting
    if under_source.exists():
        return under_source.resolve()

    try:
        repo = pygit2.Repository(str(source_path))
    except pygit2.GitError:
        return under_source.resolve()
    if setting in repo.remotes:
        remote_url = repo.remotes[setting].url
        remote_path = Path(remote_url)
        if not remote_path.is_absolute():
            remote_path = source_path / remote_path
        if remote_path.exists():
            return remote_path.resolve()
        return source_path.resolve()

    return under_source.resolve()
