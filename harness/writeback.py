"""Adopted change writeback with three-tree merge (ADR-0034)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

import httpx
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
    # 写回的目标不可用：远端仓库路径不存在、那个路径不是 git 仓库、目标分支不存在，或者远端是
    # 宿主仓库地址时凭据引用解析不到、远端读不到、合并请求接口明确拒绝创建（工单 #980）。
    # 都是源目录登记里的配置问题，由命令层给出中文的拒绝说明（工单 #709）。
    def __init__(self, reason: str, target: str) -> None:
        super().__init__(f"{reason}: {target}")
        self.reason = reason
        self.target = target


class WritebackOutcomeUnknown(Exception):
    # 外部动作的结果未知（ADR-0034、恢复契约「采纳写回」）：核实以后仍不能确认推送、分支或合并请求
    # 的结果时交出这一种异常，写回不写完成事件，动作保持待核实；下一次尝试先核实再动作。
    def __init__(self, action: str, detail: str) -> None:
        super().__init__(f"{action}: {detail}")
        self.action = action
        self.detail = detail


@dataclass(frozen=True)
class WritebackRemote:
    # 写回的目标（ADR-0034）：本地仓库，或宿主仓库地址（工单 #980）。
    # hosted 的接口根按主机取：github.com 用 api.github.com，其他主机按 GitHub Enterprise 的形状
    # 用同一个主机下的 /api/v3，本机 HTTP 服务照这一条；凭据不在地址里
    kind: str
    git_url: str = ""
    api_base: str = ""
    owner: str = ""
    repo: str = ""


# 合并请求创建的尝试次数：结果未知时先核实，核实确认没有创建才再试一次
PULL_REQUEST_ATTEMPTS = 2
PULL_REQUEST_TIMEOUT_SEC = 30.0

GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})
GITHUB_API_BASE = "https://api.github.com"
# 推送与读取分支用同一个凭据：GitHub 的令牌按用户名 x-access-token 走 Basic 认证
GIT_CREDENTIAL_USERNAME = "x-access-token"
REDACTED = "***"


def resolve_writeback_remote(remote_setting: str) -> WritebackRemote:
    """源目录登记的远端是 http(s) 地址时按宿主仓库解析，否则仍是本地仓库（工单 #902 的规则不变）。"""
    setting = (remote_setting or "").strip()
    scheme = urllib.parse.urlsplit(setting).scheme.lower()
    if scheme not in {"http", "https"}:
        return WritebackRemote(kind="local")
    split = urllib.parse.urlsplit(setting)
    path = split.path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    parts = [part for part in path.split("/") if part]
    host = (split.hostname or "").lower()
    if len(parts) < 2 or not host:
        raise WritebackTargetUnavailable("remote_missing", setting)
    netloc = split.netloc.rsplit("@", 1)[-1]
    api_base = GITHUB_API_BASE if host in GITHUB_HOSTS else f"{split.scheme}://{netloc}/api/v3"
    # 地址里即使写了用户名与口令也不带进推送地址与事件：凭据只从凭据引用取（工单 #980）
    git_url = urllib.parse.urlunsplit((split.scheme, netloc, split.path or "", "", ""))
    return WritebackRemote(kind="hosted", git_url=git_url, api_base=api_base,
                           owner=parts[-2], repo=parts[-1])


def _redact(text: str, secret: str | None) -> str:
    # 凭据值不出现在事件、工件、日志与 HTTP 错误诊断里：写进说明之前先按值替换
    if secret and secret in text:
        return text.replace(secret, REDACTED)
    return text


def _writeback_credential(system: Any, source_dir: Any, remote: WritebackRemote) -> str | None:
    # 凭据引用的解析边界（`harness/providers/facade.py` 的 resolve_credential）：材料只在控制主机上
    # 使用，不写进事件、工件、日志与错误说明；缺凭据时按既有的拒绝边界交回（工单 #980）
    if remote.kind != "hosted":
        return None
    ref = str(getattr(source_dir, "credential_ref", "") or "").strip()
    if not ref:
        raise WritebackTargetUnavailable("credential_missing", "源目录没有登记凭据引用")
    resolver = getattr(system, "credential_resolver", None)
    material = resolver(ref) if resolver is not None else None
    if material is None:
        raise WritebackTargetUnavailable("credential_missing", ref)
    return material.secret


def _git_callbacks(secret: str) -> pygit2.RemoteCallbacks:
    return pygit2.RemoteCallbacks(credentials=pygit2.UserPass(GIT_CREDENTIAL_USERNAME, secret))


def _fetch_hosted_heads(repo: pygit2.Repository, callbacks: pygit2.RemoteCallbacks,
                        secret: str) -> None:
    # 读远端分支：核实与读取目标分支都按这一份远端事实
    try:
        repo.remotes["origin"].fetch(["+refs/heads/*:refs/remotes/origin/*"], callbacks=callbacks)
    except pygit2.GitError as error:
        raise WritebackTargetUnavailable("remote_unreachable", _redact(str(error), secret)) from error


def _hosted_target_commit(repo: pygit2.Repository, target_branch: str) -> pygit2.Commit | None:
    name = f"refs/remotes/origin/{target_branch}"
    if name not in repo.references:
        return None
    return repo.references[name].peel(pygit2.Commit)


def _hosted_branch_commit(repo: pygit2.Repository, branch_name: str) -> pygit2.Commit | None:
    name = f"refs/remotes/origin/{branch_name}"
    if name not in repo.references:
        return None
    return repo.references[name].peel(pygit2.Commit)


def _push_hosted_branch(repo: pygit2.Repository, branch_name: str, callbacks: pygit2.RemoteCallbacks,
                        secret: str) -> str | None:
    # 推送分支：成功时返回 None；失败时返回已经隐去凭据的说明，由调用方按远端事实核实（结果未知）
    refspec = f"refs/heads/{branch_name}:refs/heads/{branch_name}"
    try:
        repo.remotes["origin"].push([refspec], callbacks=callbacks)
    except pygit2.GitError as error:
        return _redact(str(error), secret)
    return None


def _pull_request_headers(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


class _PullRequestUnknown(Exception):
    # 创建合并请求的结果未知：传输错误、5xx，或 GitHub 用 422 回答「同一个 head 已有请求」
    pass


class _PullRequestRejected(Exception):
    # 合并请求接口明确拒绝创建：地址、凭据或参数不对，重试同一请求也不会成功
    pass


def _pull_request_error_text(response: httpx.Response, secret: str) -> str:
    message = ""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        message = str(body.get("message") or "")
    text = message or response.text[:400]
    return _redact(f"HTTP {response.status_code} {text}".strip(), secret)


def _pull_request_title(item: Any, adoption: Any) -> str:
    return f"[{item.title}] {adoption.summary}"


def _pull_request_body(item: Any, adoption: Any, *, branch_name: str, target_branch: str,
                       target_commit: str, final_tree_digest: str) -> str:
    # 请求的说明携带采纳身份、事项与验收摘要（工单 #980）
    files = "、".join(adoption.files) or "（没有改动文件）"
    checks = "、".join(adoption.check_names) or "（没有检查命令）"
    risks = "、".join(adoption.known_risks) or "（没有已知风险）"
    return "\n".join([
        f"采纳身份：{adoption.adoption_id}",
        f"事项：{item.title}（{item.work_item_id}）",
        f"运行：{adoption.run_id}",
        f"写回分支：{branch_name} → {target_branch}",
        f"目标提交：{target_commit}",
        f"最终树摘要：{final_tree_digest}",
        "",
        "## 验收摘要",
        f"- 采纳摘要：{adoption.summary}",
        f"- 变更文件：{files}",
        f"- 检查：{checks}",
        f"- 已知风险：{risks}",
    ])


def _pull_request_record(data: dict[str, Any], remote: WritebackRemote, *, branch_name: str,
                         target_branch: str, status: str,
                         branch_commit: str | None = None) -> dict[str, Any]:
    # 事件只记录请求身份、地址、分支与结果（工单 #980），不记录凭据值；
    # branch_commit 是创建请求之前核实过的远端分支提交
    repository = f"{remote.owner}/{remote.repo}"
    return {
        "identity": f"{repository}#{data.get('number')}",
        "number": data.get("number"),
        "url": data.get("html_url"),
        "title": data.get("title"),
        "repository": repository,
        "branch": branch_name,
        "target_branch": target_branch,
        "branch_commit": branch_commit,
        "status": status,
    }


def _create_pull_request(remote: WritebackRemote, secret: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{remote.api_base}/repos/{remote.owner}/{remote.repo}/pulls"
    try:
        with httpx.Client(timeout=PULL_REQUEST_TIMEOUT_SEC) as client:
            response = client.post(url, json=payload, headers=_pull_request_headers(secret))
    except httpx.HTTPError as error:
        raise _PullRequestUnknown(_redact(str(error), secret)) from error
    if response.status_code in (200, 201):
        try:
            data = response.json()
        except ValueError as error:
            raise _PullRequestUnknown("创建合并请求的回应不是 JSON") from error
        if isinstance(data, dict) and data.get("number") is not None:
            return data
        raise _PullRequestUnknown("创建合并请求的回应里没有请求身份")
    if response.status_code == 422 or response.status_code >= 500:
        # 422 是 GitHub 对「同一个 head 已有合并请求」的回答；与 5xx 一样先核实
        raise _PullRequestUnknown(_pull_request_error_text(response, secret))
    raise _PullRequestRejected(_pull_request_error_text(response, secret))


def _find_pull_request(remote: WritebackRemote, secret: str, branch_name: str) -> dict[str, Any] | None:
    # 核实请求身份：读接口返回的请求列表，同一个 head 分支持有的请求就是这次动作的结果
    url = f"{remote.api_base}/repos/{remote.owner}/{remote.repo}/pulls"
    params = {"state": "all", "head": f"{remote.owner}:{branch_name}"}
    try:
        with httpx.Client(timeout=PULL_REQUEST_TIMEOUT_SEC) as client:
            response = client.get(url, params=params, headers=_pull_request_headers(secret))
    except httpx.HTTPError as error:
        raise WritebackOutcomeUnknown(
            "pull_request", _redact(f"核实合并请求身份失败：{error}", secret)) from error
    if response.status_code != 200:
        raise WritebackOutcomeUnknown(
            "pull_request", _redact(f"核实合并请求身份失败：{_pull_request_error_text(response, secret)}", secret))
    try:
        items = response.json()
    except ValueError as error:
        raise WritebackOutcomeUnknown("pull_request", "核实合并请求身份的回应不是 JSON") from error
    if not isinstance(items, list):
        raise WritebackOutcomeUnknown("pull_request", "核实合并请求身份的回应不是请求列表")
    for entry in items:
        if not isinstance(entry, dict):
            continue
        head = entry.get("head") or {}
        if isinstance(head, dict) and head.get("ref") == branch_name:
            return entry
    return None


def _append_verified(system: Any, project_id: str, item: Any, adoption: Any, *, action: str,
                     branch_name: str, target_commit: str, verified_fact: dict[str, Any],
                     command: Command | None) -> None:
    # 核实了已经发生的远端动作：只记核实事实，不改写原来的观察（恢复契约「采纳写回」）
    system.writes.transact(
        project_stream(project_id),
        lambda tx: tx.append(NewProjectEvent(
            ProjectEventType.WRITEBACK_VERIFIED,
            {
                "work_item_id": item.work_item_id,
                "run_id": adoption.run_id,
                "adoption_id": adoption.adoption_id,
                "action": action,
                "branch": branch_name,
                "target_commit": target_commit,
                "verified_fact": verified_fact,
            },
            actor="system",
        )),
        command=command,
    )


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

    # 3. 写回的目标：源目录登记的远端可以是宿主仓库地址（工单 #980），否则按已有的规则解析成本地仓库。
    # 宿主仓库地址的凭据从源目录的凭据引用解析，只在控制主机上使用；缺凭据在这里拒绝，不发起外部动作
    remote_target = resolve_writeback_remote(remote_name_or_url)
    remote_secret = _writeback_credential(system, source_dir, remote_target)
    callbacks = _git_callbacks(remote_secret) if remote_secret is not None else None

    remote_repo_path: Path | None = None
    remote_target_commit: pygit2.Commit | None = None
    target_is_bare = True
    target_ref_name = f"refs/heads/{target_branch}"
    if remote_target.kind == "local":
        # 准备隔离的 Git 工作仓库（独立目录，不触碰源目录未提交修改）
        remote_repo_path = _resolve_repo_path(source_dir.path, remote_name_or_url)
        if not os.path.exists(remote_repo_path):
            raise WritebackTargetUnavailable("remote_missing", str(remote_repo_path))

        # 先确认目标是 git 仓库再克隆：克隆一个不是仓库的目录抛出的 GitError 与「目标不可用」是
        # 同一类配置问题，命令层照「不是 git 仓库」拒绝，接口层不再回 500（工单 #902）
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
        if remote_target.kind == "local":
            # 复制或打开仓库进行操作
            repo = pygit2.clone_repository(str(remote_repo_path), str(scratch_dir), bare=False)
            # 4. 读取目标提交与目标树
            target_commit = repo[remote_target_commit.id]
            if target_ref_name not in repo.references:
                repo.create_reference(target_ref_name, target_commit.id, force=True)
        else:
            # 宿主仓库：按远端事实读目标分支（同一个远端用在推送与读取分支上）
            repo = pygit2.init_repository(str(scratch_dir), bare=False)
            repo.remotes.create("origin", remote_target.git_url)
            _fetch_hosted_heads(repo, callbacks, remote_secret)
            hosted_target = _hosted_target_commit(repo, target_branch)
            if hosted_target is None:
                raise WritebackTargetUnavailable("target_branch_missing", target_branch)
            target_commit = hosted_target
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

        # 13. 推送前核对目标分支是否改变（target_changed 检测）：重新读取远端的目标分支 tip
        local_target_repo: pygit2.Repository | None = None
        if remote_target.kind == "local":
            local_target_repo = pygit2.Repository(str(remote_repo_path))
            latest_target_commit_id = local_target_repo.references[target_ref_name].target
        else:
            _fetch_hosted_heads(repo, callbacks, remote_secret)
            hosted_latest = _hosted_target_commit(repo, target_branch)
            latest_target_commit_id = None if hosted_latest is None else hosted_latest.id
        if latest_target_commit_id is None or latest_target_commit_id != target_commit.id:
            return _stop(
                system=system, project_id=project_id, item=item, adoption=adoption,
                reason="target_changed", target_commit=target_commit,
                source_tree_digest=base_tree_digest, adopted_tree_digest=adopted_tree_digest,
                target_tree_digest=target_tree_digest, final_tree_digest=final_tree_digest,
                conflict_ref=None, conflicts=[], check_receipts=receipts,
                new_target_commit=None if latest_target_commit_id is None else str(latest_target_commit_id),
                command=command,
            )

        # 14. 准备独立分支与提交
        branch_name = f"writeback/{adoption.adoption_id}"
        branch_ref_name = f"refs/heads/{branch_name}"
        verified_external = False

        # 核实远端分支是否已经存在（外部结果未知先核实，ADR-0034）
        if remote_target.kind == "local":
            existing_remote_commit = (
                local_target_repo.references[branch_ref_name].peel(pygit2.Commit)
                if branch_ref_name in local_target_repo.references else None
            )
        else:
            existing_remote_commit = _hosted_branch_commit(repo, branch_name)
        if existing_remote_commit is not None and (
            existing_remote_commit.tree.id == final_tree_oid
            and existing_remote_commit.parents
            and existing_remote_commit.parents[0].id == target_commit.id
        ):
            verified_external = True
            confirmed_branch_commit = str(existing_remote_commit.id)
            _append_verified(
                system, project_id, item, adoption, action="push", branch_name=branch_name,
                target_commit=str(target_commit.id),
                verified_fact={
                    "remote_branch": branch_name,
                    "commit": str(existing_remote_commit.id),
                    "verified": True,
                },
                command=command,
            )
        elif remote_target.kind == "hosted" and existing_remote_commit is not None:
            # 远端已有同名分支但内容不是这一次的结果：不覆盖、不强制推送，交给人重新发起（ADR-0034）
            raise WritebackTargetUnavailable("branch_exists", branch_name)

        writeback_commit_oid: pygit2.Oid | None = None
        confirmed_branch_commit: str | None = None
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

            if remote_target.kind == "hosted":
                # 推送到宿主仓库：结果未知时先读远端分支（核实不了时保持待核实）；核实确认推送成功了
                # 就记下核实事实，确认没有推送上去或者分支已是别的内容时按目标的配置问题交回
                push_error = _push_hosted_branch(repo, branch_name, callbacks, remote_secret)
                if push_error is not None:
                    try:
                        _fetch_hosted_heads(repo, callbacks, remote_secret)
                    except WritebackTargetUnavailable as unreachable:
                        raise WritebackOutcomeUnknown("push", unreachable.target) from unreachable
                    pushed_commit = _hosted_branch_commit(repo, branch_name)
                    if pushed_commit is None:
                        raise WritebackTargetUnavailable("push_failed", push_error)
                    if pushed_commit.id != writeback_commit_oid:
                        raise WritebackTargetUnavailable("branch_exists", branch_name)
                    verified_external = True
                    confirmed_branch_commit = str(pushed_commit.id)
                    _append_verified(
                        system, project_id, item, adoption, action="push", branch_name=branch_name,
                        target_commit=str(target_commit.id),
                        verified_fact={
                            "remote_branch": branch_name,
                            "commit": str(pushed_commit.id),
                            "verified": True,
                            "unconfirmed_call": push_error,
                        },
                        command=command,
                    )
                else:
                    # 推送的回应说成功了：创建请求之前按远端事实再核实一次分支提交（工单 #980 的验收：
                    # 推送成功而创建请求结果未知时，核实远端分支提交和请求身份）
                    _fetch_hosted_heads(repo, callbacks, remote_secret)
                    confirmed_commit = _hosted_branch_commit(repo, branch_name)
                    if confirmed_commit is None or confirmed_commit.id != writeback_commit_oid:
                        raise WritebackTargetUnavailable("push_failed", branch_name)
                    confirmed_branch_commit = str(confirmed_commit.id)
            elif target_is_bare:
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

        # 15. 合并请求：远端是宿主仓库地址时经合并请求接口创建（工单 #980），
        # 本地目标保留明确未验收的边界（ADR-0034）
        if remote_target.kind == "hosted":
            pull_request = _ensure_pull_request(
                system, project_id, item, adoption, remote=remote_target, secret=remote_secret,
                branch_name=branch_name, target_branch=target_branch, target_commit=target_commit,
                final_tree_digest=final_tree_digest, branch_commit=confirmed_branch_commit,
                command=command,
            )
        else:
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
            del local_target_repo
        except Exception:
            pass
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


def _ensure_pull_request(
    system: Any,
    project_id: str,
    item: Any,
    adoption: Any,
    *,
    remote: WritebackRemote,
    secret: str,
    branch_name: str,
    target_branch: str,
    target_commit: pygit2.Commit,
    final_tree_digest: str,
    branch_commit: str | None,
    command: Command | None,
) -> dict[str, Any]:
    """经宿主仓库的合并请求接口创建请求；已存在时记下它的身份，不重复创建（工单 #980）。

    结果未知时先核实接口返回的请求列表：找到了就记成核实事实；核实确认没有创建时按新尝试再创建一次；
    核实本身做不了时保持待核实，不写完成事件。
    """
    existing = _find_pull_request(remote, secret, branch_name)
    if existing is not None:
        _append_verified(
            system, project_id, item, adoption, action="pull_request", branch_name=branch_name,
            target_commit=str(target_commit.id),
            verified_fact={
                "pull_request": _pull_request_record(existing, remote, branch_name=branch_name,
                                                     target_branch=target_branch, status="existing",
                                                     branch_commit=branch_commit),
                "verified": True,
            },
            command=command,
        )
        return _pull_request_record(existing, remote, branch_name=branch_name,
                                    target_branch=target_branch, status="existing",
                                    branch_commit=branch_commit)

    payload = {
        "title": _pull_request_title(item, adoption),
        "head": branch_name,
        "base": target_branch,
        "body": _pull_request_body(
            item, adoption, branch_name=branch_name, target_branch=target_branch,
            target_commit=str(target_commit.id), final_tree_digest=final_tree_digest),
    }
    last_unknown = "创建合并请求的结果未知"
    for _attempt in range(PULL_REQUEST_ATTEMPTS):
        try:
            created = _create_pull_request(remote, secret, payload)
        except _PullRequestUnknown as unknown:
            last_unknown = str(unknown)
            # 结果未知：先核实请求列表（做不了核实时 _find_pull_request 交回「保持待核实」）
            found = _find_pull_request(remote, secret, branch_name)
            if found is not None:
                _append_verified(
                    system, project_id, item, adoption, action="pull_request", branch_name=branch_name,
                    target_commit=str(target_commit.id),
                    verified_fact={
                        "pull_request": _pull_request_record(found, remote, branch_name=branch_name,
                                                             target_branch=target_branch, status="existing",
                                                             branch_commit=branch_commit),
                        "verified": True,
                        "unconfirmed_call": last_unknown,
                    },
                    command=command,
                )
                return _pull_request_record(found, remote, branch_name=branch_name,
                                            target_branch=target_branch, status="existing",
                                            branch_commit=branch_commit)
            # 核实确认没有创建：按新尝试再创建一次
            continue
        except _PullRequestRejected as rejected:
            raise WritebackTargetUnavailable("pull_request_rejected", str(rejected)) from rejected
        return _pull_request_record(created, remote, branch_name=branch_name,
                                    target_branch=target_branch, status="created",
                                    branch_commit=branch_commit)
    raise WritebackOutcomeUnknown("pull_request", last_unknown)


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
