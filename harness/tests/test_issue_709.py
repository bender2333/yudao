# 工单 #709：写回的界面入口。
# 两件事：写回的结果要有一条查询可以读（页面上看得见成果有没有回到仓库）；
# 写回的目标不可用时命令给出中文的拒绝说明（以前是 500 内部错误，页面上什么也没发生）。

import asyncio
import gc
import sys
from dataclasses import asdict
from pathlib import Path

import pygit2
import pytest

from harness.app.commands import Rejection
from harness.app.project_and_work_item_commands import WritebackExecute, _execute_writeback
from harness.app.project_queries import ProjectWriteback, _project_writeback
from harness.artifacts import ArtifactStore
from harness.event_store import Command, EventStore, project_stream
from harness.models import ProjectEventType
from harness.project_projection import handler_for
from harness.projects import ProjectService
from harness.public_tree import CapturedFile, CapturedTree
from harness.tree_archive import store_tree
from harness.write_path import NewProjectEvent, WritePath

PASSING_CHECK = f'"{sys.executable}" -c "import sys; sys.exit(0)"'


def _service(root: Path):
    store = EventStore(root / "events.db")
    writes = WritePath(store, handler_for)
    artifacts = ArtifactStore(root / "artifacts")
    projects = ProjectService(store, writes, artifacts, None)
    return store, writes, artifacts, projects


class _App:
    # 应用层要的最小形状：命令处理与查询都只经过 system.projects、system.store 与 system.artifacts
    def __init__(self, store, artifacts, projects):
        self.system = type("System", (), {"store": store, "artifacts": artifacts, "projects": projects})()


def _bare_repo(path: Path, branch: str = "main") -> None:
    # 一个只有一次提交的裸仓库：写回把分支推进到这个仓库上
    repo = pygit2.init_repository(str(path), bare=True)
    signature = pygit2.Signature("Yudao Test", "test@yudao.invalid")
    blob = repo.create_blob(b"base\n")
    builder = repo.TreeBuilder()
    builder.insert("base.txt", blob, pygit2.enums.FileMode.BLOB)
    tree = builder.write()
    repo.set_head(f"refs/heads/{branch}")
    repo.create_commit(f"refs/heads/{branch}", signature, signature, "初始提交", tree, [])
    del repo


def _project_with_adoption(root: Path, *, remote: str, target_branch: str):
    # 一个已经采纳了成果的项目：源目录打开了写回，事项与采纳都登记了
    store, writes, artifacts, projects = _service(root)
    project_id = projects.register("写回项目", "把成果写回仓库")
    projects.configure_source_directory(
        project_id, "default", str(root / "src"), base_version=0,
        writeback_enabled=True, remote=remote, target_branch=target_branch,
        check_commands=[PASSING_CHECK])
    base = CapturedTree((), (CapturedFile("base.txt", b"base\n"),))
    base_ref = store_tree(artifacts, "r1", base)
    adopted = CapturedTree((), (CapturedFile("added.txt", b"new\n"), CapturedFile("base.txt", b"changed\n")))
    adopted_ref = store_tree(artifacts, "r1", adopted)
    writes.transact(project_stream(project_id), lambda tx: tx.append(NewProjectEvent(
        ProjectEventType.WORK_ITEM_CREATED,
        {
            "work_item_id": "w1", "title": "改一处", "text": "任务说明", "run_id": "r1",
            "baseline": {"tree_ref": asdict(base_ref), "code_tree_digest": base.digest},
            "project_context_ref": {"path": "dummy"}, "prompt_config_versions": {},
            "max_cycles": 1, "run_time_limit_sec": 60, "context_window": 1000,
        },
        actor="user")))
    writes.transact(project_stream(project_id), lambda tx: tx.append(NewProjectEvent(
        ProjectEventType.DELIVERABLE_ADOPTED,
        {
            "adoption_id": "adopt_1", "work_item_id": "w1", "run_id": "r1",
            "delivery_event_id": "d1", "qa_event_id": "q1",
            "tree_ref": asdict(adopted_ref), "code_tree_digest": adopted.digest,
            "summary": "交付说明", "files": ["base.txt", "added.txt"],
            "check_names": [], "known_risks": [], "previous_adoption_id": None,
        },
        actor="user")))
    return store, artifacts, projects, project_id


def test_the_writeback_query_gives_the_page_the_result_of_a_writeback(tmp_path):
    # 写回完成以后，查询给出页面上要显示的事实：状态、推送的分支、目标分支与合并请求
    bare_path = tmp_path / "bare.git"
    _bare_repo(bare_path)
    store, artifacts, projects, project_id = _project_with_adoption(
        tmp_path, remote=str(bare_path), target_branch="main")
    try:
        event = projects.execute_writeback(project_id, "adopt_1")
        assert event is not None and event.type == ProjectEventType.WRITEBACK_COMPLETED

        app = _App(store, artifacts, projects)
        snapshot = _project_writeback(app, ProjectWriteback(project_id=project_id))
        assert len(snapshot.data.records) == 1
        record = snapshot.data.records[0]
        assert record.status == "completed"
        assert record.adoption_id == "adopt_1"
        assert record.work_item_id == "w1"
        assert record.branch == "writeback/adopt_1"
        assert record.target_branch == "main"
        assert record.pull_request_title is not None
        # 合并请求还只是本地记录：页面上照实写明，不说已经创建
        assert record.pull_request_local_only is True
        assert record.conflicts == []
        assert record.created_at != ""
    finally:
        store.close()
        gc.collect()


def test_the_writeback_query_gives_the_conflicting_files_when_the_writeback_stops(tmp_path):
    # 写回停止（冲突）：查询给出停止原因与冲突的文件路径，页面上列出冲突在哪几个文件
    bare_path = tmp_path / "bare.git"
    _bare_repo(bare_path)
    repo = pygit2.Repository(str(bare_path))
    signature = pygit2.Signature("Yudao Test", "test@yudao.invalid")
    blob = repo.create_blob("目标分支的内容\n".encode("utf-8"))
    builder = repo.TreeBuilder()
    builder.insert("base.txt", blob, pygit2.enums.FileMode.BLOB)
    tree = builder.write()
    parent = repo.references["refs/heads/main"].peel(pygit2.Commit)
    repo.create_commit("refs/heads/main", signature, signature, "目标分支推进", tree, [parent.id])
    del repo

    store, artifacts, projects, project_id = _project_with_adoption(
        tmp_path, remote=str(bare_path), target_branch="main")
    try:
        event = projects.execute_writeback(project_id, "adopt_1")
        assert event is not None and event.type == ProjectEventType.WRITEBACK_STOPPED
        assert event.payload["reason"] == "conflict"

        app = _App(store, artifacts, projects)
        snapshot = _project_writeback(app, ProjectWriteback(project_id=project_id))
        assert len(snapshot.data.records) == 1
        record = snapshot.data.records[0]
        assert record.status == "stopped"
        assert record.reason == "conflict"
        assert record.conflicts == ["base.txt"]
        # 停止时没有推送分支，也没有合并请求
        assert record.branch is None
        assert record.pull_request_title is None
    finally:
        store.close()
        gc.collect()


def test_the_writeback_command_explains_an_unusable_target_in_chinese(tmp_path):
    # 目标分支不存在、远端仓库路径不存在：命令给出中文的拒绝说明，接口层回 409，
    # 以前这两种情况直接变成 500 内部错误，页面上什么也没发生（工单 #709）
    bare_path = tmp_path / "bare.git"
    _bare_repo(bare_path)
    store, artifacts, projects, project_id = _project_with_adoption(
        tmp_path, remote=str(bare_path), target_branch="main")
    command = Command(command_id="00000000-0000-0000-0000-000000000001", name="writeback.execute", digest="d", actor="user")
    app = _App(store, artifacts, projects)
    try:
        # 目标分支不存在
        projects.configure_source_directory(
            project_id, "default", str(tmp_path / "src"), base_version=1,
            writeback_enabled=True, remote=str(bare_path), target_branch="not-there",
            check_commands=[PASSING_CHECK])
        with pytest.raises(Rejection) as missing_branch:
            asyncio.run(_execute_writeback(
                app, command, WritebackExecute(
                    command_id="00000000-0000-0000-0000-000000000001", project_id=project_id)))
        assert missing_branch.value.reason == "not_allowed"
        assert "目标分支不存在" in missing_branch.value.message
        assert "not-there" in missing_branch.value.message

        # 远端仓库路径不存在
        projects.configure_source_directory(
            project_id, "default", str(tmp_path / "src"), base_version=2,
            writeback_enabled=True, remote=str(tmp_path / "no-such-repo.git"), target_branch="main",
            check_commands=[PASSING_CHECK])
        with pytest.raises(Rejection) as missing_remote:
            asyncio.run(_execute_writeback(
                app, command, WritebackExecute(
                    command_id="00000000-0000-0000-0000-000000000002", project_id=project_id)))
        assert missing_remote.value.reason == "not_allowed"
        assert "目标仓库不存在" in missing_remote.value.message
    finally:
        store.close()
        gc.collect()


def test_the_automatic_writeback_does_not_fail_the_adoption_when_the_target_is_unusable(tmp_path):
    # 采纳以后自动发起的写回：目标不可用时做不了，也不因此让这一次采纳失败。
    # 页面上这一次采纳仍是「还没有写回」，用户在设置页改好以后按「写回成果」重新发起，
    # 那时命令给出中文的理由（工单 #709）
    bare_path = tmp_path / "bare.git"
    _bare_repo(bare_path)
    store, artifacts, projects, project_id = _project_with_adoption(
        tmp_path, remote=str(bare_path), target_branch="main")
    try:
        projects.configure_source_directory(
            project_id, "default", str(tmp_path / "src"), base_version=1,
            writeback_enabled=True, remote=str(tmp_path / "no-such-repo.git"), target_branch="main",
            check_commands=[PASSING_CHECK])
        projects._trigger_writeback_if_enabled(project_id, "adopt_1")
        # 采纳仍然在项目里，写回没有发生
        projection = projects.projection(project_id)
        assert projection.current_adoption is not None
        assert projection.current_adoption.adoption_id == "adopt_1"
        assert projection.writebacks == []
    finally:
        store.close()
        gc.collect()
