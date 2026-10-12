import gc
import os
import sys
from dataclasses import asdict
from pathlib import Path

import pygit2
import pytest

from harness.artifacts import ArtifactStore
from harness.event_store import EventStore, project_stream
from harness.models import ArtifactRef, ProjectEventType
from harness.project_projection import handler_for
from harness.projects import ProjectService
from harness.public_tree import CapturedFile, CapturedTree
from harness.tree_archive import load_tree, store_tree
from harness.write_path import NewProjectEvent, WritePath
from harness.writeback import git_tree_to_captured


def _create_bare_repo(bare_path: Path, files: dict[str, bytes], executable_files: set[str] | None = None) -> pygit2.Oid:
    repo = pygit2.init_repository(str(bare_path), bare=True)
    sig = pygit2.Signature("Yudao Test", "test@yudao.invalid")
    nodes: dict = {}
    executable_files = executable_files or set()

    for path, content in files.items():
        blob_id = repo.create_blob(content)
        mode = pygit2.enums.FileMode.BLOB_EXECUTABLE if path in executable_files else pygit2.enums.FileMode.BLOB
        parts = path.split("/")
        curr = nodes
        for part in parts[:-1]:
            curr = curr.setdefault(part, {})
        curr[parts[-1]] = (blob_id, mode)

    def _build_tree(node: dict, target_repo: pygit2.Repository) -> pygit2.Oid:
        tb = target_repo.TreeBuilder()
        for name, value in node.items():
            if isinstance(value, dict):
                sub_oid = _build_tree(value, target_repo)
                tb.insert(name, sub_oid, pygit2.enums.FileMode.TREE)
            else:
                oid, mode = value
                tb.insert(name, oid, mode)
        return tb.write()

    tree_oid = _build_tree(nodes, repo)
    repo.set_head("refs/heads/main")
    commit_oid = repo.create_commit("refs/heads/main", sig, sig, "Initial commit", tree_oid, [])
    del repo
    gc.collect()
    return commit_oid


def _commit_to_bare_repo(bare_path: Path, branch: str, files: dict[str, bytes], msg: str, parent_oid: pygit2.Oid, executable_files: set[str] | None = None) -> pygit2.Oid:
    repo = pygit2.Repository(str(bare_path))
    sig = pygit2.Signature("Yudao Test", "test@yudao.invalid")
    nodes: dict = {}
    executable_files = executable_files or set()
    for path, content in files.items():
        blob_id = repo.create_blob(content)
        mode = pygit2.enums.FileMode.BLOB_EXECUTABLE if path in executable_files else pygit2.enums.FileMode.BLOB
        parts = path.split("/")
        curr = nodes
        for part in parts[:-1]:
            curr = curr.setdefault(part, {})
        curr[parts[-1]] = (blob_id, mode)

    def _build_tree(node: dict, target_repo: pygit2.Repository) -> pygit2.Oid:
        tb = target_repo.TreeBuilder()
        for name, value in node.items():
            if isinstance(value, dict):
                sub_oid = _build_tree(value, target_repo)
                tb.insert(name, sub_oid, pygit2.enums.FileMode.TREE)
            else:
                oid, mode = value
                tb.insert(name, oid, mode)
        return tb.write()

    tree_oid = _build_tree(nodes, repo)
    commit_oid = repo.create_commit(f"refs/heads/{branch}", sig, sig, msg, tree_oid, [parent_oid])
    del repo
    gc.collect()
    return commit_oid


def _setup_yudao_env(root: Path):
    store = EventStore(root / "events.db")
    writes = WritePath(store, handler_for)
    artifacts = ArtifactStore(root / "artifacts")
    projects = ProjectService(store, writes, artifacts, None)
    return store, writes, artifacts, projects


def test_writeback_three_way_merge_preserves_independent_changes(tmp_path):
    bare_path = tmp_path / "bare.git"
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "uncommitted.txt").write_text("uncommitted dirty file", encoding="utf-8")

    initial_files = {
        "common.txt": b"base common content",
        "to_delete.txt": b"delete me in adopted",
        "stable.txt": b"unchanged content",
        "run.sh": b"#!/bin/sh\necho hi\n",
        ".checks/config.json": b'{"private": true}',
    }
    c1 = _create_bare_repo(bare_path, initial_files, executable_files={"run.sh"})

    # 目标分支 main 期间发生了独立修改与新增
    c2_files = dict(initial_files)
    c2_files["target_new.txt"] = b"target branch independent addition"
    c2_files["target_modified.txt"] = b"target branch another change"
    c2 = _commit_to_bare_repo(bare_path, "main", c2_files, "Target branch advances", c1, executable_files={"run.sh"})

    store, writes, artifacts, projects = _setup_yudao_env(tmp_path)
    try:
        pid = projects.register("WritebackTest", "Long term goal")
        projects.configure_source_directory(
            pid, "default", str(src_dir), base_version=0,
            writeback_enabled=True, remote=str(bare_path), target_branch="main",
            check_commands=["chk_ok"],
        )
        projects.configure_command(
            pid, "chk_ok", [sys.executable, "-c", "import sys; sys.exit(0)"], base_version=0,
        )

        # Base tree
        base_captured = CapturedTree(
            (),
            (
                CapturedFile("common.txt", b"base common content"),
                CapturedFile("run.sh", b"#!/bin/sh\necho hi\n"),
                CapturedFile("stable.txt", b"unchanged content"),
                CapturedFile("to_delete.txt", b"delete me in adopted"),
            ),
        )
        base_ref = store_tree(artifacts, "r1", base_captured)

        # Adopted tree: 修改 common.txt、删除 to_delete.txt、新增 adopted_new.txt、修改 run.sh
        adopted_captured = CapturedTree(
            (),
            (
                CapturedFile("adopted_new.txt", b"adopted new file"),
                CapturedFile("common.txt", b"adopted modified common content"),
                CapturedFile("run.sh", b"#!/bin/sh\necho updated\n"),
                CapturedFile("stable.txt", b"unchanged content"),
            ),
        )
        adopted_ref = store_tree(artifacts, "r1", adopted_captured)

        writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
            ProjectEventType.WORK_ITEM_CREATED,
            {
                "work_item_id": "w1", "title": "Work Item 1", "text": "Task description",
                "run_id": "r1",
                "baseline": {"tree_ref": asdict(base_ref), "code_tree_digest": base_captured.digest},
                "project_context_ref": {"path": "dummy"}, "prompt_config_versions": {},
                "max_cycles": 1, "run_time_limit_sec": 60, "context_window": 1000,
            },
            actor="user",
        )))

        writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
            ProjectEventType.DELIVERABLE_ADOPTED,
            {
                "adoption_id": "adopt_1", "work_item_id": "w1", "run_id": "r1",
                "delivery_event_id": "d1", "qa_event_id": "q1",
                "tree_ref": asdict(adopted_ref), "code_tree_digest": adopted_captured.digest,
                "summary": "Delivery summary 1", "files": ["common.txt", "adopted_new.txt", "run.sh"],
                "check_names": ["chk_ok"], "known_risks": [], "previous_adoption_id": None,
            },
            actor="user",
        )))

        event = projects.execute_writeback(pid, "adopt_1")
        assert event is not None
        assert event.type == ProjectEventType.WRITEBACK_COMPLETED
        payload = event.payload
        assert payload["target_commit"] == str(c2)
        assert payload["branch"] == "writeback/adopt_1"
        assert payload["pull_request"]["identity"] == "pr-adopt_1"
        assert payload["pull_request"]["status"] == "local_test_boundary"

        # 核对远端裸仓库上的写回分支
        bare_repo = pygit2.Repository(str(bare_path))
        assert "refs/heads/writeback/adopt_1" in bare_repo.references
        wb_commit = bare_repo.references["refs/heads/writeback/adopt_1"].peel(pygit2.Commit)
        assert wb_commit.parents[0].id == c2

        wb_captured = git_tree_to_captured(bare_repo, wb_commit.tree)
        file_map = {f.path: f.data for f in wb_captured.files}

        # 采纳成果变更保留
        assert file_map["common.txt"] == b"adopted modified common content"
        assert "to_delete.txt" not in file_map
        assert file_map["adopted_new.txt"] == b"adopted new file"
        assert file_map["stable.txt"] == b"unchanged content"

        # 目标分支独立变更保留
        assert file_map["target_new.txt"] == b"target branch independent addition"
        assert file_map["target_modified.txt"] == b"target branch another change"

        # 可执行权限保留
        assert wb_commit.tree["run.sh"].filemode == pygit2.enums.FileMode.BLOB_EXECUTABLE

        # 公开树以外的文件保持目标提交内容
        assert ".checks" in wb_commit.tree
        checks_tree = bare_repo[wb_commit.tree[".checks"].id]
        assert "config.json" in checks_tree
        assert bare_repo[checks_tree["config.json"].id].data == b'{"private": true}'

        # 源目录中的未提交修改与目标分支保持原状
        assert (src_dir / "uncommitted.txt").read_text(encoding="utf-8") == "uncommitted dirty file"
        assert bare_repo.references["refs/heads/main"].target == c2
        del bare_repo
    finally:
        store.close()
        gc.collect()


def test_writeback_stops_on_conflicts(tmp_path):
    # 验证三种冲突：content、delete_modify、path_type
    conflict_scenarios = [
        ("content", "c.txt", {"c.txt": b"target conflict"}, {"c.txt": b"adopted conflict"}),
        ("delete_modify", "c.txt", {}, {"c.txt": b"adopted modified"}),
        ("path_type", "c", {"c/sub.txt": b"dir"}, {"c": b"file"}),
    ]

    for scenario_name, base_key, target_files, adopted_files in conflict_scenarios:
        case_dir = tmp_path / scenario_name
        case_dir.mkdir()
        bare_path = case_dir / "bare.git"
        src_dir = case_dir / "src"
        src_dir.mkdir()

        init_files = {base_key: b"base content", "stable.txt": b"stable"}
        c1 = _create_bare_repo(bare_path, init_files)
        # 构造 target 分支
        tgt_full = {"stable.txt": b"stable"}
        tgt_full.update(target_files)
        c2 = _commit_to_bare_repo(bare_path, "main", tgt_full, "target advance", c1)

        store, writes, artifacts, projects = _setup_yudao_env(case_dir)
        try:
            pid = projects.register(f"Conflict_{scenario_name}", "Goal")
            projects.configure_source_directory(
                pid, "default", str(src_dir), base_version=0,
                writeback_enabled=True, remote=str(bare_path), target_branch="main",
                check_commands=["chk_ok"],
            )
            projects.configure_command(
                pid, "chk_ok", [sys.executable, "-c", "import sys; sys.exit(0)"], base_version=0,
            )

            base_files = [CapturedFile(base_key, b"base content"), CapturedFile("stable.txt", b"stable")]
            base_files.sort(key=lambda x: x.path)
            base_captured = CapturedTree((), tuple(base_files))
            base_ref = store_tree(artifacts, "r1", base_captured)

            adp_files_list = [CapturedFile("stable.txt", b"stable")]
            dirs = ("c",) if any("/" in k for k in adopted_files) else ()
            for k, v in adopted_files.items():
                adp_files_list.append(CapturedFile(k, v))
            adp_files_list.sort(key=lambda x: x.path)
            adopted_captured = CapturedTree(dirs, tuple(adp_files_list))
            adopted_ref = store_tree(artifacts, "r1", adopted_captured)

            writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
                ProjectEventType.WORK_ITEM_CREATED,
                {
                    "work_item_id": "w1", "title": "Item 1", "text": "desc", "run_id": "r1",
                    "baseline": {"tree_ref": asdict(base_ref), "code_tree_digest": base_captured.digest},
                    "project_context_ref": {"path": "dummy"}, "prompt_config_versions": {},
                    "max_cycles": 1, "run_time_limit_sec": 60, "context_window": 1000,
                },
                actor="user",
            )))

            writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
                ProjectEventType.DELIVERABLE_ADOPTED,
                {
                    "adoption_id": "adopt_c", "work_item_id": "w1", "run_id": "r1",
                    "delivery_event_id": "d1", "qa_event_id": "q1",
                    "tree_ref": asdict(adopted_ref), "code_tree_digest": adopted_captured.digest,
                    "summary": "Conflict summary", "files": list(adopted_files.keys()),
                    "check_names": ["chk_ok"], "known_risks": [], "previous_adoption_id": None,
                },
                actor="user",
            )))

            event = projects.execute_writeback(pid, "adopt_c")
            assert event is not None
            assert event.type == ProjectEventType.WRITEBACK_STOPPED
            assert event.payload["reason"] == "conflict"
            assert event.payload["source_tree_digest"] == base_captured.digest
            assert event.payload["adopted_tree_digest"] == adopted_captured.digest
            assert event.payload["target_commit"] == str(c2)
            assert event.payload["conflict_ref"] is not None

            # 核对保存的冲突工件与分类
            conflicts = event.payload["conflicts"]
            assert len(conflicts) > 0
            assert any(c["kind"] == scenario_name for c in conflicts)

            conflict_raw = artifacts.get_for_run("r1", ArtifactRef(**event.payload["conflict_ref"]))
            assert b"path" in conflict_raw

            # 远端没有新分支
            bare_repo = pygit2.Repository(str(bare_path))
            assert "refs/heads/writeback/adopt_c" not in bare_repo.references
            del bare_repo
        finally:
            store.close()
            gc.collect()


def test_writeback_checks_execution_and_verification_failure(tmp_path):
    bare_path = tmp_path / "bare.git"
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    init_files = {"test_val.txt": b"1"}
    c1 = _create_bare_repo(bare_path, init_files)

    store, writes, artifacts, projects = _setup_yudao_env(tmp_path)
    try:
        pid = projects.register("ChecksTest", "Goal")
        projects.configure_source_directory(
            pid, "default", str(src_dir), base_version=0,
            writeback_enabled=True, remote=str(bare_path), target_branch="main",
            check_commands=["chk_assert", "chk_timeout"],
        )
        # chk_assert 要求 test_val.txt 内容为 "expected_final"
        chk_code = (
            "import sys, pathlib; "
            "content = pathlib.Path('test_val.txt').read_text().strip(); "
            "sys.exit(0 if content == 'expected_final' else 1)"
        )
        projects.configure_command(pid, "chk_assert", [sys.executable, "-c", chk_code], base_version=0)
        projects.configure_command(
            pid, "chk_timeout",
            [sys.executable, "-c", "import time; time.sleep(1)"],
            timeout_sec=1, base_version=0,
        )

        base_captured = CapturedTree((), (CapturedFile("test_val.txt", b"1"),))
        base_ref = store_tree(artifacts, "r1", base_captured)

        # 1. 最终树内容错误导致核验失败（即使原采纳快照放行）
        bad_adopted = CapturedTree((), (CapturedFile("test_val.txt", b"wrong_val"),))
        bad_adopted_ref = store_tree(artifacts, "r1", bad_adopted)

        writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
            ProjectEventType.WORK_ITEM_CREATED,
            {
                "work_item_id": "w1", "title": "Item 1", "text": "desc", "run_id": "r1",
                "baseline": {"tree_ref": asdict(base_ref), "code_tree_digest": base_captured.digest},
                "project_context_ref": {"path": "dummy"}, "prompt_config_versions": {},
                "max_cycles": 1, "run_time_limit_sec": 60, "context_window": 1000,
            },
            actor="user",
        )))

        writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
            ProjectEventType.DELIVERABLE_ADOPTED,
            {
                "adoption_id": "adopt_bad", "work_item_id": "w1", "run_id": "r1",
                "delivery_event_id": "d1", "qa_event_id": "q1",
                "tree_ref": asdict(bad_adopted_ref), "code_tree_digest": bad_adopted.digest,
                "summary": "Bad adoption", "files": ["test_val.txt"],
                "check_names": ["chk_assert"], "known_risks": [], "previous_adoption_id": None,
            },
            actor="user",
        )))

        event = projects.execute_writeback(pid, "adopt_bad")
        assert event is not None
        assert event.type == ProjectEventType.WRITEBACK_STOPPED
        assert event.payload["reason"] == "verification_failed"
        receipts = event.payload["check_receipts"]
        assert len(receipts) == 1
        assert receipts[0]["name"] == "chk_assert"
        assert receipts[0]["exit_code"] != 0
        assert receipts[0]["tree_digest"] == event.payload["final_tree_digest"]

        # 远端不推送
        bare_repo = pygit2.Repository(str(bare_path))
        assert "refs/heads/writeback/adopt_bad" not in bare_repo.references

        # 2. 缺少检查命令停止
        projects.configure_source_directory(
            pid, "default", str(src_dir), base_version=1,
            writeback_enabled=True, remote=str(bare_path), target_branch="main",
            check_commands=[],
        )
        good_adopted = CapturedTree((), (CapturedFile("test_val.txt", b"expected_final"),))
        good_adopted_ref = store_tree(artifacts, "r1", good_adopted)

        writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
            ProjectEventType.DELIVERABLE_ADOPTED,
            {
                "adoption_id": "adopt_no_checks", "work_item_id": "w1", "run_id": "r1",
                "delivery_event_id": "d2", "qa_event_id": "q2",
                "tree_ref": asdict(good_adopted_ref), "code_tree_digest": good_adopted.digest,
                "summary": "No checks", "files": ["test_val.txt"],
                "check_names": [], "known_risks": [], "previous_adoption_id": None,
            },
            actor="user",
        )))

        event_no_chk = projects.execute_writeback(pid, "adopt_no_checks")
        assert event_no_chk.type == ProjectEventType.WRITEBACK_STOPPED
        assert event_no_chk.payload["reason"] == "verification_failed"
        assert event_no_chk.payload["check_receipts"] == []

        # 3. 检查命令超时停止
        projects.configure_source_directory(
            pid, "default", str(src_dir), base_version=2,
            writeback_enabled=True, remote=str(bare_path), target_branch="main",
            check_commands=["chk_timeout"],
        )
        writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
            ProjectEventType.DELIVERABLE_ADOPTED,
            {
                "adoption_id": "adopt_timeout", "work_item_id": "w1", "run_id": "r1",
                "delivery_event_id": "d3", "qa_event_id": "q3",
                "tree_ref": asdict(good_adopted_ref), "code_tree_digest": good_adopted.digest,
                "summary": "Timeout", "files": ["test_val.txt"],
                "check_names": ["chk_timeout"], "known_risks": [], "previous_adoption_id": None,
            },
            actor="user",
        )))
        event_timeout = projects.execute_writeback(pid, "adopt_timeout")
        assert event_timeout.type == ProjectEventType.WRITEBACK_STOPPED
        assert event_timeout.payload["reason"] == "verification_failed"
        assert event_timeout.payload["check_receipts"][0]["timed_out"] is True

        # 4. 正确的最终树且检查通过
        projects.configure_source_directory(
            pid, "default", str(src_dir), base_version=3,
            writeback_enabled=True, remote=str(bare_path), target_branch="main",
            check_commands=["chk_assert"],
        )
        writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
            ProjectEventType.DELIVERABLE_ADOPTED,
            {
                "adoption_id": "adopt_good", "work_item_id": "w1", "run_id": "r1",
                "delivery_event_id": "d4", "qa_event_id": "q4",
                "tree_ref": asdict(good_adopted_ref), "code_tree_digest": good_adopted.digest,
                "summary": "Good adoption", "files": ["test_val.txt"],
                "check_names": ["chk_assert"], "known_risks": [], "previous_adoption_id": None,
            },
            actor="user",
        )))
        event_good = projects.execute_writeback(pid, "adopt_good")
        assert event_good.type == ProjectEventType.WRITEBACK_COMPLETED
        assert event_good.payload["check_receipts"][0]["exit_code"] == 0
        assert "refs/heads/writeback/adopt_good" in bare_repo.references
        del bare_repo
    finally:
        store.close()
        gc.collect()


def test_writeback_target_changed_and_retry(tmp_path):
    bare_path = tmp_path / "bare.git"
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    init_files = {"file.txt": b"base"}
    c1 = _create_bare_repo(bare_path, init_files)

    store, writes, artifacts, projects = _setup_yudao_env(tmp_path)
    try:
        pid = projects.register("TargetChangedTest", "Goal")

        # 检查命令在运行时把远端 bare 仓库的目标分支推进一次（只在目标还没有推进过时推进）
        hook_script = "\n".join([
            "import sys, pygit2",
            f"repo = pygit2.Repository(r'{bare_path}')",
            "parent_id = repo.references['refs/heads/main'].target",
            "if 'concurrent.txt' not in repo[parent_id].tree:",
            "    sig = pygit2.Signature('Concurrent', 'c@yudao.invalid')",
            "    tb = repo.TreeBuilder(repo[parent_id].tree)",
            "    tb.insert('concurrent.txt', repo.create_blob(b'advanced'), pygit2.enums.FileMode.BLOB)",
            "    repo.create_commit('refs/heads/main', sig, sig, 'Concurrent advance', tb.write(), [parent_id])",
            "sys.exit(0)",
        ])

        projects.configure_source_directory(
            pid, "default", str(src_dir), base_version=0,
            writeback_enabled=True, remote=str(bare_path), target_branch="main",
            check_commands=["advance_target_concurrently"],
        )
        projects.configure_command(
            pid, "advance_target_concurrently", [sys.executable, "-c", hook_script], base_version=0,
        )

        base_captured = CapturedTree((), (CapturedFile("file.txt", b"base"),))
        base_ref = store_tree(artifacts, "r1", base_captured)

        adopted_captured = CapturedTree((), (CapturedFile("file.txt", b"adopted"),))
        adopted_ref = store_tree(artifacts, "r1", adopted_captured)

        writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
            ProjectEventType.WORK_ITEM_CREATED,
            {
                "work_item_id": "w1", "title": "Item 1", "text": "desc", "run_id": "r1",
                "baseline": {"tree_ref": asdict(base_ref), "code_tree_digest": base_captured.digest},
                "project_context_ref": {"path": "dummy"}, "prompt_config_versions": {},
                "max_cycles": 1, "run_time_limit_sec": 60, "context_window": 1000,
            },
            actor="user",
        )))

        writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
            ProjectEventType.DELIVERABLE_ADOPTED,
            {
                "adoption_id": "adopt_tc", "work_item_id": "w1", "run_id": "r1",
                "delivery_event_id": "d1", "qa_event_id": "q1",
                "tree_ref": asdict(adopted_ref), "code_tree_digest": adopted_captured.digest,
                "summary": "Target changed test", "files": ["file.txt"],
                "check_names": ["advance_target_concurrently"], "known_risks": [], "previous_adoption_id": None,
            },
            actor="user",
        )))

        # 首次执行：核验完成后发现 target_changed，停止写回
        event1 = projects.execute_writeback(pid, "adopt_tc")
        assert event1 is not None
        assert event1.type == ProjectEventType.WRITEBACK_STOPPED
        assert event1.payload["reason"] == "target_changed"
        assert event1.payload["target_commit"] == str(c1)
        assert event1.payload["new_target_commit"] is not None
        assert event1.payload["new_target_commit"] != str(c1)

        bare_repo = pygit2.Repository(str(bare_path))
        advanced_c2 = bare_repo.references["refs/heads/main"].target
        assert str(advanced_c2) == event1.payload["new_target_commit"]
        assert "refs/heads/writeback/adopt_tc" not in bare_repo.references

        # 改换检查命令为正常无副作用的命令
        projects.configure_source_directory(
            pid, "default", str(src_dir), base_version=1,
            writeback_enabled=True, remote=str(bare_path), target_branch="main",
            check_commands=["normal_pass"],
        )
        projects.configure_command(pid, "normal_pass", [sys.executable, "-c", "import sys; sys.exit(0)"], base_version=0)

        # 重新发起：以新目标提交核验并成功写回
        event2 = projects.execute_writeback(pid, "adopt_tc")
        assert event2 is not None
        assert event2.type == ProjectEventType.WRITEBACK_COMPLETED
        assert event2.payload["target_commit"] == str(advanced_c2)
        assert "refs/heads/writeback/adopt_tc" in bare_repo.references

        wb_commit = bare_repo.references["refs/heads/writeback/adopt_tc"].peel(pygit2.Commit)
        assert wb_commit.parents[0].id == advanced_c2
        wb_tree = git_tree_to_captured(bare_repo, wb_commit.tree)
        file_map = {f.path: f.data for f in wb_tree.files}
        assert file_map["file.txt"] == b"adopted"
        assert file_map["concurrent.txt"] == b"advanced"
        del bare_repo
    finally:
        store.close()
        gc.collect()


def test_writeback_sequential_adoptions_and_no_writeback(tmp_path):
    bare_path = tmp_path / "bare.git"
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    init_files = {"app.py": b"print('base')\n"}
    c1 = _create_bare_repo(bare_path, init_files)

    store, writes, artifacts, projects = _setup_yudao_env(tmp_path)
    try:
        pid = projects.register("SeqTest", "Goal")
        projects.configure_source_directory(
            pid, "default", str(src_dir), base_version=0,
            writeback_enabled=True, remote=str(bare_path), target_branch="main",
            check_commands=["chk_ok"],
        )
        projects.configure_command(pid, "chk_ok", [sys.executable, "-c", "import sys; sys.exit(0)"], base_version=0)

        # 1. 建档采纳（onboarding）：不写回
        base_captured = CapturedTree((), (CapturedFile("app.py", b"print('base')\n"),))
        base_ref = store_tree(artifacts, "r_onboard", base_captured)

        writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
            ProjectEventType.WORK_ITEM_CREATED,
            {
                "work_item_id": "w_onboard", "title": "Onboarding", "text": "desc", "run_id": "r_onboard",
                "kind": "onboarding",
                "baseline": None,
                "snapshot": {"tree_ref": asdict(base_ref), "tree_digest": base_captured.digest},
                "project_context_ref": {"path": "dummy"}, "prompt_config_versions": {},
                "max_cycles": 1, "run_time_limit_sec": 60, "context_window": 1000,
            },
            actor="user",
        )))
        writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
            ProjectEventType.BASELINE_ADOPTED,
            {
                "adoption_id": "adopt_base", "work_item_id": "w_onboard", "run_id": "r_onboard",
                "candidate_event_id": "c_init",
                "tree_ref": asdict(base_ref), "code_tree_digest": base_captured.digest,
                "summary": "Baseline adopted", "files": ["app.py"], "check_names": ["chk_ok"],
                "known_risks": [], "previous_adoption_id": None,
                "prd_ref": {"path": "prd"}, "product_spec_hash": "hash1",
                "structure_ref": {"path": "struct"},
            },
            actor="user",
        )))

        # 执行建档采纳的写回：返回 None，不写回
        res_onboard = projects.execute_writeback(pid, "adopt_base")
        assert res_onboard is None

        # 2. 变更已全部存在于目标树：writeback_not_needed，不创建空分支
        writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
            ProjectEventType.WORK_ITEM_CREATED,
            {
                "work_item_id": "w_no_op", "title": "No op", "text": "desc", "run_id": "r_no_op",
                "baseline": {"tree_ref": asdict(base_ref), "code_tree_digest": base_captured.digest, "adoption_id": "adopt_base"},
                "project_context_ref": {"path": "dummy"}, "prompt_config_versions": {},
                "max_cycles": 1, "run_time_limit_sec": 60, "context_window": 1000,
            },
            actor="user",
        )))
        writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
            ProjectEventType.DELIVERABLE_ADOPTED,
            {
                "adoption_id": "adopt_no_op", "work_item_id": "w_no_op", "run_id": "r_no_op",
                "delivery_event_id": "d_noop", "qa_event_id": "q_noop",
                "tree_ref": asdict(base_ref), "code_tree_digest": base_captured.digest,
                "summary": "No change", "files": ["app.py"], "check_names": ["chk_ok"],
                "known_risks": [], "previous_adoption_id": "adopt_base",
            },
            actor="user",
        )))
        res_noop = projects.execute_writeback(pid, "adopt_no_op")
        assert res_noop.type == ProjectEventType.WRITEBACK_NOT_NEEDED
        assert res_noop.payload["reason"] == "changes_already_present"

        bare_repo = pygit2.Repository(str(bare_path))
        assert "refs/heads/writeback/adopt_no_op" not in bare_repo.references

        # 3. 连续两项采纳：第二项依赖第一项
        tree1 = CapturedTree((), (CapturedFile("app.py", b"print('step1')\n"),))
        ref1 = store_tree(artifacts, "r1", tree1)
        writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
            ProjectEventType.WORK_ITEM_CREATED,
            {
                "work_item_id": "w1", "title": "Step 1", "text": "desc", "run_id": "r1",
                "baseline": {"tree_ref": asdict(base_ref), "code_tree_digest": base_captured.digest, "adoption_id": "adopt_base"},
                "project_context_ref": {"path": "dummy"}, "prompt_config_versions": {},
                "max_cycles": 1, "run_time_limit_sec": 60, "context_window": 1000,
            },
            actor="user",
        )))
        writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
            ProjectEventType.DELIVERABLE_ADOPTED,
            {
                "adoption_id": "adopt_step1", "work_item_id": "w1", "run_id": "r1",
                "delivery_event_id": "d1", "qa_event_id": "q1",
                "tree_ref": asdict(ref1), "code_tree_digest": tree1.digest,
                "summary": "Step 1", "files": ["app.py"], "check_names": ["chk_ok"],
                "known_risks": [], "previous_adoption_id": "adopt_base",
            },
            actor="user",
        )))
        event_s1 = projects.execute_writeback(pid, "adopt_step1")
        assert event_s1.type == ProjectEventType.WRITEBACK_COMPLETED
        assert "refs/heads/writeback/adopt_step1" in bare_repo.references

        # 第二项采纳：依赖第一项采纳
        tree2 = CapturedTree((), (CapturedFile("app.py", b"print('step2')\n"), CapturedFile("step2.txt", b"s2")))
        ref2 = store_tree(artifacts, "r2", tree2)
        writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
            ProjectEventType.WORK_ITEM_CREATED,
            {
                "work_item_id": "w2", "title": "Step 2", "text": "desc", "run_id": "r2",
                "baseline": {"tree_ref": asdict(ref1), "code_tree_digest": tree1.digest, "adoption_id": "adopt_step1"},
                "project_context_ref": {"path": "dummy"}, "prompt_config_versions": {},
                "max_cycles": 1, "run_time_limit_sec": 60, "context_window": 1000,
            },
            actor="user",
        )))
        writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
            ProjectEventType.DELIVERABLE_ADOPTED,
            {
                "adoption_id": "adopt_step2", "work_item_id": "w2", "run_id": "r2",
                "delivery_event_id": "d2", "qa_event_id": "q2",
                "tree_ref": asdict(ref2), "code_tree_digest": tree2.digest,
                "summary": "Step 2", "files": ["app.py", "step2.txt"], "check_names": ["chk_ok"],
                "known_risks": [], "previous_adoption_id": "adopt_step1",
            },
            actor="user",
        )))

        # 此时目标分支 main 尚未合入 adopt_step1：第二项写回应被挂起（writeback_held）
        event_s2_held = projects.execute_writeback(pid, "adopt_step2")
        assert event_s2_held.type == ProjectEventType.WRITEBACK_HELD
        assert event_s2_held.payload["reason"] == "waiting_previous_adoption"
        assert event_s2_held.payload["previous_adoption_id"] == "adopt_step1"
        assert "refs/heads/writeback/adopt_step2" not in bare_repo.references

        # 模拟目标分支上执行了对 adopt_step1 的 squash 合并
        squash_commit = _commit_to_bare_repo(
            bare_path, "main", {"app.py": b"print('step1')\n"},
            "Squash merge PR pr-adopt_step1 (adoption_id: adopt_step1)", c1,
        )

        # 合入后重新执行第二项写回：成功合并并只写本项变更
        event_s2_ok = projects.execute_writeback(pid, "adopt_step2")
        assert event_s2_ok.type == ProjectEventType.WRITEBACK_COMPLETED
        assert event_s2_ok.payload["target_commit"] == str(squash_commit)
        assert "refs/heads/writeback/adopt_step2" in bare_repo.references

        wb2_commit = bare_repo.references["refs/heads/writeback/adopt_step2"].peel(pygit2.Commit)
        wb2_tree = git_tree_to_captured(bare_repo, wb2_commit.tree)
        wb2_files = {f.path: f.data for f in wb2_tree.files}
        assert wb2_files["app.py"] == b"print('step2')\n"
        assert wb2_files["step2.txt"] == b"s2"
        del bare_repo
    finally:
        store.close()
        gc.collect()


def test_writeback_push_unknown_outcome_and_recovery(tmp_path):
    bare_path = tmp_path / "bare.git"
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    init_files = {"app.py": b"print('init')\n"}
    c1 = _create_bare_repo(bare_path, init_files)

    store, writes, artifacts, projects = _setup_yudao_env(tmp_path)
    try:
        pid = projects.register("RecoveryTest", "Goal")
        projects.configure_source_directory(
            pid, "default", str(src_dir), base_version=0,
            writeback_enabled=True, remote=str(bare_path), target_branch="main",
            check_commands=["chk_ok"],
        )
        projects.configure_command(pid, "chk_ok", [sys.executable, "-c", "import sys; sys.exit(0)"], base_version=0)

        base_captured = CapturedTree((), (CapturedFile("app.py", b"print('init')\n"),))
        base_ref = store_tree(artifacts, "r1", base_captured)

        adopted_captured = CapturedTree((), (CapturedFile("app.py", b"print('recovered')\n"),))
        adopted_ref = store_tree(artifacts, "r1", adopted_captured)

        writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
            ProjectEventType.WORK_ITEM_CREATED,
            {
                "work_item_id": "w1", "title": "Recovery Item", "text": "desc", "run_id": "r1",
                "baseline": {"tree_ref": asdict(base_ref), "code_tree_digest": base_captured.digest},
                "project_context_ref": {"path": "dummy"}, "prompt_config_versions": {},
                "max_cycles": 1, "run_time_limit_sec": 60, "context_window": 1000,
            },
            actor="user",
        )))
        writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
            ProjectEventType.DELIVERABLE_ADOPTED,
            {
                "adoption_id": "adopt_rec", "work_item_id": "w1", "run_id": "r1",
                "delivery_event_id": "d1", "qa_event_id": "q1",
                "tree_ref": asdict(adopted_ref), "code_tree_digest": adopted_captured.digest,
                "summary": "Recovery summary", "files": ["app.py"], "check_names": ["chk_ok"],
                "known_risks": [], "previous_adoption_id": None,
            },
            actor="user",
        )))

        # 1. 模拟推送已在远端裸仓库发生，但返回结果未知（网络中断/崩溃）
        with pytest.raises(RuntimeError, match="simulated unknown push outcome"):
            projects.execute_writeback(pid, "adopt_rec", simulate_unknown_push=True)

        bare_repo = pygit2.Repository(str(bare_path))
        # 远端分支已被推入
        assert "refs/heads/writeback/adopt_rec" in bare_repo.references
        first_commit_oid = bare_repo.references["refs/heads/writeback/adopt_rec"].target

        # 2. 恢复重试：核实远端已发生结果，不重复创建分支，追加核实事件与完成事件
        event_rec = projects.execute_writeback(pid, "adopt_rec")
        assert event_rec.type == ProjectEventType.WRITEBACK_COMPLETED
        assert event_rec.payload["verified_external"] is True
        assert event_rec.payload["pull_request"]["identity"] == "pr-adopt_rec"
        assert event_rec.payload["pull_request"]["status"] == "local_test_boundary"

        # 验证产生了 writeback_verified 事件
        all_events = store.list_project_events(pid)
        verified_events = [e for e in all_events if e.type == ProjectEventType.WRITEBACK_VERIFIED]
        assert len(verified_events) == 1
        assert verified_events[0].payload["action"] == "push"
        assert verified_events[0].payload["verified_fact"]["verified"] is True

        # 同一命令没有重复分支，分支提交未变
        assert bare_repo.references["refs/heads/writeback/adopt_rec"].target == first_commit_oid
        del bare_repo
    finally:
        store.close()
        gc.collect()


def test_writeback_command_dispatch_and_rejections(tmp_path):
    import asyncio
    from harness.app.project_and_work_item_commands import WritebackExecute, _execute_writeback
    from harness.app.commands import Rejection
    from harness.event_store import Command

    store, writes, artifacts, projects = _setup_yudao_env(tmp_path)
    try:
        class DummyApp:
            def __init__(self, p):
                self.system = type("System", (), {"projects": p})()

        app = DummyApp(projects)
        cmd = Command(command_id="00000000-0000-0000-0000-000000000001", name="writeback.execute", digest="d", actor="user")

        with pytest.raises(Rejection) as exc_missing:
            asyncio.run(_execute_writeback(app, cmd, WritebackExecute(command_id="00000000-0000-0000-0000-000000000001", project_id="nonexistent")))
        assert exc_missing.value.reason == "not_found"

        pid = projects.register("ArchivedProj", "Goal")
        projects.archive(pid)
        with pytest.raises(Rejection) as exc_archived:
            asyncio.run(_execute_writeback(app, cmd, WritebackExecute(command_id="00000000-0000-0000-0000-000000000002", project_id=pid)))
        assert exc_archived.value.reason == "project_archived"
    finally:
        store.close()
        gc.collect()
