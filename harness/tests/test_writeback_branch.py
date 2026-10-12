import gc
import sys
from dataclasses import asdict
from pathlib import Path

import pygit2
import pytest

from harness.artifacts import ArtifactStore
from harness.event_store import EventStore, project_stream
from harness.models import ProjectEventType
from harness.project_projection import handler_for
from harness.projects import ProjectService
from harness.public_tree import CapturedFile, CapturedTree
from harness.tree_archive import store_tree
from harness.write_path import NewProjectEvent, WritePath
from harness.writeback import git_tree_to_captured

from .test_writeback import _commit_to_bare_repo, _create_bare_repo, _setup_yudao_env


def _adopt(
    writes, artifacts, pid, work_item_id, run_id, adoption_id,
    base_captured, adopted_captured, *, baseline_extra=None, check_names=("chk_ok",),
):
    baseline = {"tree_ref": asdict(store_tree(artifacts, run_id, base_captured)),
                "code_tree_digest": base_captured.digest}
    if baseline_extra:
        baseline.update(baseline_extra)
    writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
        ProjectEventType.WORK_ITEM_CREATED,
        {
            "work_item_id": work_item_id, "title": work_item_id, "text": "desc", "run_id": run_id,
            "baseline": baseline,
            "project_context_ref": {"path": "dummy"}, "prompt_config_versions": {},
            "max_cycles": 1, "run_time_limit_sec": 60, "context_window": 1000,
        },
        actor="user",
    )))
    adopted_ref = store_tree(artifacts, run_id, adopted_captured)
    writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
        ProjectEventType.DELIVERABLE_ADOPTED,
        {
            "adoption_id": adoption_id, "work_item_id": work_item_id, "run_id": run_id,
            "delivery_event_id": "d1", "qa_event_id": "q1",
            "tree_ref": asdict(adopted_ref), "code_tree_digest": adopted_captured.digest,
            "summary": adoption_id, "files": [f.path for f in adopted_captured.files],
            "check_names": list(check_names), "known_risks": [], "previous_adoption_id": None,
        },
        actor="user",
    )))


def test_writeback_uses_project_target_branch(tmp_path):
    # 项目设置给出目标分支时，起点树、目标树与写回分支都按它进行
    bare_path = tmp_path / "bare.git"
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    c1 = _create_bare_repo(bare_path, {"app.py": b"print('base')\n"})
    _commit_to_bare_repo(bare_path, "trunk", {"app.py": b"print('base')\n", "extra.txt": b"e"}, "trunk tip", c1)

    store, writes, artifacts, projects = _setup_yudao_env(tmp_path)
    try:
        pid = projects.register("BranchTest", "Goal")
        projects.configure_source_directory(
            pid, "default", str(src_dir), base_version=0,
            writeback_enabled=True, remote=str(bare_path), target_branch="trunk",
            check_commands=["chk_ok"],
        )
        projects.configure_command(pid, "chk_ok", [sys.executable, "-c", "import sys; sys.exit(0)"], base_version=0)

        base_captured = CapturedTree((), (CapturedFile("app.py", b"print('base')\n"),))
        adopted_captured = CapturedTree((), (CapturedFile("app.py", b"print('adopted')\n"),))
        _adopt(writes, artifacts, pid, "w1", "r1", "adopt_1", base_captured, adopted_captured)

        event = projects.execute_writeback(pid, "adopt_1")
        assert event.type == ProjectEventType.WRITEBACK_COMPLETED
        payload = event.payload
        assert payload["branch"] == "writeback/adopt_1"
        assert payload["pull_request"]["target_branch"] == "trunk"

        bare_repo = pygit2.Repository(str(bare_path))
        trunk_id = bare_repo.references["refs/heads/trunk"].target
        assert payload["target_commit"] == str(trunk_id)
        wb_commit = bare_repo.references["refs/heads/writeback/adopt_1"].peel(pygit2.Commit)
        assert wb_commit.parents[0].id == trunk_id

        # 起点树与采纳树的摘要各自保留，与最终树摘要都不同
        assert payload["source_tree_digest"] == base_captured.digest
        assert payload["adopted_tree_digest"] == adopted_captured.digest
        assert len({payload["source_tree_digest"], payload["adopted_tree_digest"],
                    payload["target_tree_digest"], payload["final_tree_digest"]}) == 4

        # 目标树摘要等于目标提交的公开树摘要
        trunk_tree = git_tree_to_captured(bare_repo, bare_repo[trunk_id].tree)
        assert payload["target_tree_digest"] == trunk_tree.digest
        final_tree = git_tree_to_captured(bare_repo, wb_commit.tree)
        assert payload["final_tree_digest"] == final_tree.digest

        # 保存的最终树工件可以读回，摘要与事件一致
        restored = projects.projection(pid).work_item("w1").writeback
        assert restored.final_tree_digest == payload["final_tree_digest"]
        assert restored.branch == "writeback/adopt_1"
        del bare_repo
    finally:
        store.close()
        gc.collect()


def test_writeback_executable_flag_follows_tree_manifest(tmp_path):
    # 写回树的可执行标记取自树清单：采纳树声明可执行时生效，未声明时不继承目标提交的标记
    bare_path = tmp_path / "bare.git"
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    c1 = _create_bare_repo(bare_path, {"run.sh": b"#!/bin/sh\nold\n", "tool.sh": b"#!/bin/sh\ntool\n"},
                           executable_files={"run.sh", "tool.sh"})

    store, writes, artifacts, projects = _setup_yudao_env(tmp_path)
    try:
        pid = projects.register("ExecTest", "Goal")
        projects.configure_source_directory(
            pid, "default", str(src_dir), base_version=0,
            writeback_enabled=True, remote=str(bare_path), target_branch="main",
            check_commands=["chk_ok"],
        )
        projects.configure_command(pid, "chk_ok", [sys.executable, "-c", "import sys; sys.exit(0)"], base_version=0)

        base_captured = CapturedTree((), (
            CapturedFile("run.sh", b"#!/bin/sh\nold\n"),
            CapturedFile("tool.sh", b"#!/bin/sh\ntool\n"),
        ))
        adopted_captured = CapturedTree(
            directories=(),
            files=(
                CapturedFile("run.sh", b"#!/bin/sh\nnew\n"),
                CapturedFile("tool.sh", b"#!/bin/sh\ntool\n"),
            ),
        )
        _adopt(writes, artifacts, pid, "w1", "r1", "adopt_exec", base_captured, adopted_captured)

        event = projects.execute_writeback(pid, "adopt_exec")
        assert event.type == ProjectEventType.WRITEBACK_COMPLETED

        bare_repo = pygit2.Repository(str(bare_path))
        wb_commit = bare_repo.references["refs/heads/writeback/adopt_exec"].peel(pygit2.Commit)
        assert wb_commit.tree["run.sh"].filemode == pygit2.enums.FileMode.BLOB_EXECUTABLE
        assert wb_commit.tree["tool.sh"].filemode == pygit2.enums.FileMode.BLOB_EXECUTABLE
        del bare_repo
    finally:
        store.close()
        gc.collect()


def test_writeback_missing_source_reference_stops(tmp_path):
    # 事项既没有起点树也没有快照时，缺少起点依据，写回停止
    bare_path = tmp_path / "bare.git"
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    _create_bare_repo(bare_path, {"app.py": b"print('base')\n"})

    store, writes, artifacts, projects = _setup_yudao_env(tmp_path)
    try:
        pid = projects.register("NoSourceTest", "Goal")
        projects.configure_source_directory(
            pid, "default", str(src_dir), base_version=0,
            writeback_enabled=True, remote=str(bare_path), target_branch="main",
            check_commands=["chk_ok"],
        )
        projects.configure_command(pid, "chk_ok", [sys.executable, "-c", "import sys; sys.exit(0)"], base_version=0)

        writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
            ProjectEventType.WORK_ITEM_CREATED,
            {
                "work_item_id": "w1", "title": "Item", "text": "desc", "run_id": "r1",
                "baseline": None,
                "project_context_ref": {"path": "dummy"}, "prompt_config_versions": {},
                "max_cycles": 1, "run_time_limit_sec": 60, "context_window": 1000,
            },
            actor="user",
        )))
        adopted_captured = CapturedTree((), (CapturedFile("app.py", b"print('adopted')\n"),))
        adopted_ref = store_tree(artifacts, "r1", adopted_captured)
        writes.transact(project_stream(pid), lambda tx: tx.append(NewProjectEvent(
            ProjectEventType.DELIVERABLE_ADOPTED,
            {
                "adoption_id": "adopt_missing", "work_item_id": "w1", "run_id": "r1",
                "delivery_event_id": "d1", "qa_event_id": "q1",
                "tree_ref": asdict(adopted_ref), "code_tree_digest": adopted_captured.digest,
                "summary": "Missing source", "files": ["app.py"], "check_names": ["chk_ok"],
                "known_risks": [], "previous_adoption_id": None,
            },
            actor="user",
        )))

        event = projects.execute_writeback(pid, "adopt_missing")
        assert event.type == ProjectEventType.WRITEBACK_STOPPED
        assert event.payload["reason"] == "missing_source_reference"
        assert event.payload["final_tree_digest"] is None

        bare_repo = pygit2.Repository(str(bare_path))
        assert "refs/heads/writeback/adopt_missing" not in bare_repo.references
        del bare_repo
    finally:
        store.close()
        gc.collect()


def test_writeback_unregistered_check_command_stops(tmp_path):
    # 项目设置里写了没有登记的检查命令时，写回停止并给出回执
    bare_path = tmp_path / "bare.git"
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    _create_bare_repo(bare_path, {"app.py": b"print('base')\n"})

    store, writes, artifacts, projects = _setup_yudao_env(tmp_path)
    try:
        pid = projects.register("UnregisteredTest", "Goal")
        projects.configure_source_directory(
            pid, "default", str(src_dir), base_version=0,
            writeback_enabled=True, remote=str(bare_path), target_branch="main",
            check_commands=["chk_missing"],
        )
        base_captured = CapturedTree((), (CapturedFile("app.py", b"print('base')\n"),))
        adopted_captured = CapturedTree((), (CapturedFile("app.py", b"print('adopted')\n"),))
        _adopt(writes, artifacts, pid, "w1", "r1", "adopt_unreg", base_captured, adopted_captured,
               check_names=("chk_missing",))

        event = projects.execute_writeback(pid, "adopt_unreg")
        assert event.type == ProjectEventType.WRITEBACK_STOPPED
        assert event.payload["reason"] == "verification_failed"
        receipts = event.payload["check_receipts"]
        assert len(receipts) == 1
        assert receipts[0]["name"] == "chk_missing"
        assert receipts[0]["argv"] == []

        bare_repo = pygit2.Repository(str(bare_path))
        assert "refs/heads/writeback/adopt_unreg" not in bare_repo.references
        del bare_repo
    finally:
        store.close()
        gc.collect()


def test_writeback_runs_adoption_registered_checks(tmp_path):
    # 采纳成果登记的检查也进入写回检查清单：项目设置为空时仍按采纳登记的检查核验最终树
    bare_path = tmp_path / "bare.git"
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    _create_bare_repo(bare_path, {"value.txt": b"1"})

    store, writes, artifacts, projects = _setup_yudao_env(tmp_path)
    try:
        pid = projects.register("AdoptionChecksTest", "Goal")
        projects.configure_source_directory(
            pid, "default", str(src_dir), base_version=0,
            writeback_enabled=True, remote=str(bare_path), target_branch="main",
            check_commands=[],
        )
        check_code = "\n".join([
            "import sys, pathlib",
            "content = pathlib.Path('value.txt').read_text().strip()",
            "sys.exit(0 if content == 'expected' else 1)",
        ])
        projects.configure_command(pid, "chk_adopted", [sys.executable, "-c", check_code], base_version=0)

        base_captured = CapturedTree((), (CapturedFile("value.txt", b"1"),))
        adopted_captured = CapturedTree((), (CapturedFile("value.txt", b"expected"),))
        _adopt(writes, artifacts, pid, "w1", "r1", "adopt_checks",
               base_captured, adopted_captured, check_names=("chk_adopted",))

        event = projects.execute_writeback(pid, "adopt_checks")
        assert event.type == ProjectEventType.WRITEBACK_COMPLETED
        receipts = event.payload["check_receipts"]
        assert [r["name"] for r in receipts] == ["chk_adopted"]
        assert receipts[0]["exit_code"] == 0

        bare_repo = pygit2.Repository(str(bare_path))
        assert "refs/heads/writeback/adopt_checks" in bare_repo.references
        del bare_repo
    finally:
        store.close()
        gc.collect()


def test_writeback_unknown_adoption_and_disabled_source(tmp_path):
    # 未开启写回的源目录与不存在的采纳身份都不产生写回
    bare_path = tmp_path / "bare.git"
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    _create_bare_repo(bare_path, {"app.py": b"print('base')\n"})

    store, writes, artifacts, projects = _setup_yudao_env(tmp_path)
    try:
        pid = projects.register("DisabledTest", "Goal")
        projects.configure_source_directory(pid, "default", str(src_dir), base_version=0)
        base_captured = CapturedTree((), (CapturedFile("app.py", b"print('base')\n"),))
        adopted_captured = CapturedTree((), (CapturedFile("app.py", b"print('adopted')\n"),))
        _adopt(writes, artifacts, pid, "w1", "r1", "adopt_off", base_captured, adopted_captured)

        assert projects.execute_writeback(pid, "adopt_off") is None
        assert projects.execute_writeback(pid, "adopt_unknown") is None

        bare_repo = pygit2.Repository(str(bare_path))
        assert "refs/heads/writeback/adopt_off" not in bare_repo.references
        del bare_repo
    finally:
        store.close()
        gc.collect()
