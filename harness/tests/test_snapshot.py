import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.app.application import Application
from harness.models import ArtifactRef, EventType, ProjectEventType, canonical_hash, json_dumps
from harness.public_tree import TreeError, capture_public_tree
from harness.proposals import baseline_review_turn, product_spec, structure_turn
from harness.runtime import LoopSystem
from harness.snapshot import git_provenance, ingest_snapshot, restore_snapshot
from harness.tests.api_helpers import running_api
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

GOAL = "把一份可信代码快照接入后完成增量变更。"
REQUIREMENT = "run the CLI with a word"
APP_BYTES = "print('hello')\n".encode("utf-8")
BIN_BYTES = bytes(range(256))
HIDDEN_BYTES = b"\x00\xff\xfe\r\n"


def _system(data_dir):
    # 建档 run 的三个部门依次提交初始 PRD、现有结构说明与基线核验；
    # 工程与质检的 run_check 回执运行源目录里可执行的 src/app.py
    return LoopSystem.for_testing(data_dir, FakeAdapter([
        FakeTurn(proposal=product_spec(requirements=[REQUIREMENT], acceptance=["run the CLI with a word"])),
        structure_turn(checks={"smoke": 0},
                       modules=[{"path": "src/", "responsibility": "the app"}],
                       entry_points=[{"kind": "command_line", "path": "src/app.py", "how_to_run": "python src/app.py"}],
                       build_and_test=[{"name": "smoke", "argv": ["python", "src/app.py"], "purpose": "run it"}],
                       requirement_locations=[{"requirement": REQUIREMENT, "locations": ["src/app.py"]}]),
        baseline_review_turn(conclusions=[{"requirement": REQUIREMENT, "status": "verified", "evidence": "smoke"}]),
    ]))


def _make_source(root: Path) -> Path:
    # 二进制、隐藏文件与空目录都在场
    root.mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "app.py").write_bytes(APP_BYTES)
    (root / "src" / "data.bin").write_bytes(BIN_BYTES)
    (root / ".hidden").write_bytes(HIDDEN_BYTES)
    (root / "empty").mkdir()
    (root / "empty" / "nested").mkdir()
    return root


def _fingerprint(root: Path):
    files = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = Path(dirpath) / name
            files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    dirs = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_dir()}
    return files, dirs


def _symlink(target, link, *, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError:
        pytest.skip("symbolic links are unavailable")

def _wait_for(predicate, timeout=WAIT_FOR_HOST_WORK_SEC):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _start(system, source: Path):
    # 已有代码的唯一入口是 project.onboard：同一个事务登记项目、源目录与建档事项，随后创建建档 run
    project_id, work_item_id, run_id = system.projects.onboard(
        "快照项目", GOAL, "src", str(source))
    item = system.projects.projection(project_id).work_item(work_item_id)
    return project_id, work_item_id, run_id, item.snapshot


def test_ingest_leaves_source_byte_identical(data_dir, tmp_path):
    source = _make_source(tmp_path / "source")
    before = _fingerprint(source)
    system = _system(data_dir)
    _project_id, _work_item_id, _run_id, _snapshot = _start(system, source)
    assert _fingerprint(source) == before


def test_snapshot_identity_and_independent_restore(data_dir, tmp_path):
    source = _make_source(tmp_path / "source")
    system = _system(data_dir)
    _project_id, _work_item_id, run_id, snapshot = _start(system, source)
    assert snapshot["source"] == str(source.absolute())
    assert snapshot["files"] == [".hidden", "src/app.py", "src/data.bin"]
    assert snapshot["directories"] == ["empty", "empty/nested", "src"]
    assert snapshot["tree_digest"] == capture_public_tree(source).digest
    restored = restore_snapshot(system.artifacts, run_id, snapshot, tmp_path / "independent")
    assert capture_public_tree(restored).digest == snapshot["tree_digest"]
    assert (restored / "src" / "app.py").read_bytes() == APP_BYTES
    assert (restored / "src" / "data.bin").read_bytes() == BIN_BYTES
    assert (restored / ".hidden").read_bytes() == HIDDEN_BYTES
    assert (restored / "empty" / "nested").is_dir()
    assert not (restored / ".checks").exists()


def test_run_workspace_is_independent_from_source(data_dir, tmp_path):
    source = _make_source(tmp_path / "source")
    before = _fingerprint(source)
    system = _system(data_dir)
    _project_id, _work_item_id, run_id, _snapshot = _start(system, source)
    workspace = system.workspace(run_id)
    workspace.write_file("src/app.py", "print('changed in workspace')\n")
    (workspace.root / "src" / "data.bin").write_bytes(b"workspace bytes")
    (workspace.root / "src" / "new.py").write_bytes(b"new = True\n")
    assert (source / "src" / "app.py").read_bytes() == APP_BYTES
    assert (source / "src" / "data.bin").read_bytes() == BIN_BYTES
    assert not (source / "src" / "new.py").exists()
    assert _fingerprint(source) == before


def test_snapshot_rejects_symlink_inside_source(data_dir, tmp_path):
    source = _make_source(tmp_path / "source")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside")
    _symlink(outside, source / "linked.txt")
    system = _system(data_dir)
    with pytest.raises(TreeError, match="Links and reparse"):
        system.projects.onboard("快照项目", GOAL, "src", str(source))
    assert outside.read_bytes() == b"outside"
    # 拒绝时没有建立项目，也没有写入任何事件
    assert system.store.list_project_ids() == []
    # 拒绝后源目录仍可接入
    outside.unlink()
    (source / "linked.txt").unlink()
    _project_id, _work_item_id, run_id, snapshot = _start(system, source)
    assert system.project(run_id).workspace_digest == snapshot["tree_digest"]


def test_snapshot_rejects_host_private_paths(data_dir, tmp_path):
    # .checks 是 Yudao 工作区自身标记的宿主私有路径，仍然拒绝；仓库自身的 .git 目录按设计从公开树排除
    source = _make_source(tmp_path / "source")
    (source / ".checks").mkdir()
    (source / ".checks" / "state").write_bytes(b"x")
    system = _system(data_dir)
    with pytest.raises(TreeError, match="私有"):
        system.projects.onboard("快照项目", GOAL, "src", str(source))
    assert (source / ".checks" / "state").read_bytes() == b"x"
    assert system.store.list_project_ids() == []


def test_snapshot_restore_rejects_reserved_path_in_archive(data_dir, tmp_path):
    source = _make_source(tmp_path / "source")
    system = _system(data_dir)
    _project_id, _work_item_id, run_id, snapshot = _start(system, source)
    payload = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**snapshot["tree_ref"])))
    payload["tree"]["files"][0]["path"] = "NUL"
    payload["tree_digest"] = canonical_hash(payload["tree"])
    forged = system.artifacts.put(
        run_id, "tree_manifest", json_dumps(payload).encode("utf-8"), media_type="application/json")
    bad = {**snapshot, "tree_ref": asdict(forged), "tree_digest": payload["tree_digest"]}
    with pytest.raises(TreeError, match="reserved"):
        restore_snapshot(system.artifacts, run_id, bad, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_restore_after_source_deleted_uses_only_persisted_artifacts(data_dir, tmp_path):
    source = _make_source(tmp_path / "source")
    system = _system(data_dir)
    project_id, _work_item_id, run_id, _snapshot = _start(system, source)
    expected = capture_public_tree(source).digest
    shutil.rmtree(source)
    assert not source.exists()
    reopened = LoopSystem(data_dir, resume_on_startup=False)
    item = reopened.projects.projection(project_id).work_items[0]
    assert item.snapshot["tree_digest"] == expected
    restored = restore_snapshot(reopened.artifacts, run_id, item.snapshot, tmp_path / "recovered")
    assert capture_public_tree(restored).digest == expected
    assert (restored / "src" / "app.py").read_bytes() == APP_BYTES
    assert (restored / "src" / "data.bin").read_bytes() == BIN_BYTES
    assert (restored / ".hidden").read_bytes() == HIDDEN_BYTES
    assert (restored / "empty" / "nested").is_dir()
    reopened.close()


def test_run_created_from_snapshot_has_files_before_activation(data_dir, tmp_path):
    source = _make_source(tmp_path / "source")
    system = _system(data_dir)
    project_id, work_item_id, run_id, snapshot = _start(system, source)
    workspace = system.workspace(run_id)
    assert (workspace.root / "src" / "app.py").read_bytes() == APP_BYTES
    assert (workspace.root / "src" / "data.bin").read_bytes() == BIN_BYTES
    assert (workspace.root / ".hidden").read_bytes() == HIDDEN_BYTES
    assert (workspace.root / "empty" / "nested").is_dir()
    run = system.project(run_id)
    assert run.workspace_digest == snapshot["tree_digest"]
    assert run.snapshot == snapshot
    assert run.baseline is None
    events = system.store.list_events(run_id)
    assert [event.type for event in events] == [EventType.RUN_CREATED, EventType.TRANSITION]
    created = next(event for event in events if event.type == EventType.RUN_CREATED)
    assert created.payload["snapshot"]["source"] == str(source.absolute())
    assert created.payload["snapshot"]["files"] == [".hidden", "src/app.py", "src/data.bin"]
    assert created.payload["snapshot"]["directories"] == ["empty", "empty/nested", "src"]
    # 建档 run 以 baseline_verified 结束；结算按工单 #136 提出初始 PRD 候选并请求用户确认
    result = system.run_until_stop(run_id)
    assert result.phase == "DONE"
    assert result.stop_reason == "baseline_verified"
    [proposed, requested] = [system.projects.settle(run_id), system.projects.settle(run_id)]
    assert proposed is not None and requested is None
    assert proposed.type == ProjectEventType.INITIAL_PRD_PROPOSED
    assert proposed.payload["round"] == 1
    assert proposed.payload["run_id"] == run_id
    assert system.projects.projection(project_id).work_item(work_item_id).status == "awaiting_initial_prd"
    assert system.projects.projection(project_id).work_item(work_item_id).kind == "onboarding"


def test_ingest_snapshot_function_writes_nothing_to_source(tmp_path, data_dir):
    source = _make_source(tmp_path / "source")
    before = _fingerprint(source)
    system = _system(data_dir)
    tree, record = ingest_snapshot(source, system.artifacts, "run_direct")
    assert record["tree_digest"] == tree.digest == capture_public_tree(source).digest
    assert _fingerprint(source) == before
    restored = restore_snapshot(system.artifacts, "run_direct", record, tmp_path / "direct")
    assert capture_public_tree(restored).digest == tree.digest


def test_project_onboard_http_entry(data_dir, tmp_path):
    # 经 HTTP 命令 project.onboard 接入：建档 run 由流程编排作为任务运行到 baseline_verified
    source = _make_source(tmp_path / "source")
    before = _fingerprint(source)
    system = _system(data_dir)
    application = Application(system)
    with running_api(lambda: application) as client:
        status = client.post("/api/commands/project.onboard", json={
            "command_id": str(uuid.uuid4()), "name": "快照", "goal": GOAL,
            "source_name": "src", "source_path": str(source)})
        assert status.status_code == 200, status.text
        accepted = status.json()
        project_id = accepted["refs"]["project_id"]
        run_id = accepted["refs"]["run_id"]

        def settled():
            project = client.get(f"/api/queries/project.overview?project_id={project_id}").json()["data"]
            item = next(entry for entry in project["work_items"]
                        if entry["work_item_id"] == accepted["refs"]["work_item_id"])
            # 建档 run 结束时事项停在 released_unsettled（基线采纳由 #136 实现）
            if item["status"] not in {"released_unsettled", "stopped", "adopted", "held"}:
                return False
            return client.get("/api/queries/system.status").json()["data"]["drain"]["running_runs"] == 0

        assert _wait_for(settled), "the onboarding run did not stop"
        run = system.project(run_id)
        assert run.phase == "DONE"
        assert run.stop_reason == "baseline_verified"
        assert run.workspace_digest == run.snapshot["tree_digest"]
        assert _fingerprint(source) == before
        assert (system.workspace(run_id).root / "src" / "app.py").exists()
        # 带未知字段（旧的代码快照来源参数）的请求按未知字段拒绝
        rejected = client.post("/api/commands/project.onboard", json={
            "command_id": str(uuid.uuid4()), "name": "快照2", "goal": GOAL,
            "source_name": "src", "source_path": str(source), "source_dir": str(source)})
        assert rejected.status_code == 422, rejected.text


def _git_environment() -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    environment.update({
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    })
    return environment

def _git(base: Path, *arguments: str) -> str:
    completed = subprocess.run(["git", "--no-pager", "-C", str(base), *arguments],
                               capture_output=True, check=True, env=_git_environment())
    return completed.stdout.decode("utf-8").strip()

def test_provenance_reads_a_repository_created_by_git_without_any_process(tmp_path, monkeypatch):
    # 验收：来源核对改用进程内的 libgit2——提交、分支与未提交修改与 Git 命令行一致，且核对本身不启动进程
    source = _make_source(tmp_path / "repo")
    _git(source, "init", "-q")
    _git(source, "add", "-A")
    _git(source, "commit", "-q", "-m", "baseline")
    expected = {"commit": _git(source, "rev-parse", "HEAD"),
                "branch": _git(source, "rev-parse", "--abbrev-ref", "HEAD"), "dirty": False}
    assert git_provenance(source) == expected
    (source / "src" / "app.py").write_bytes(b"print('edited')\n")
    (source / "extra.txt").write_bytes(b"untracked\n")
    def forbidden(*args, **kwargs):
        raise AssertionError(f"provenance must not start a process: {args}")
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    provenance = git_provenance(source)
    assert provenance["commit"] == expected["commit"]
    assert provenance["branch"] == expected["branch"]
    monkeypatch.undo()
    assert provenance["dirty"] is (_git(source, "status", "--porcelain") != "")

def test_provenance_is_empty_for_directories_that_are_not_work_trees(tmp_path):
    # 普通目录没有来源；裸库没有工作树，与改造前 Git 命令行的 rev-parse --is-inside-work-tree 判定相同
    plain = _make_source(tmp_path / "plain")
    assert git_provenance(plain) == {}
    bare = tmp_path / "bare"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, env=_git_environment())
    assert git_provenance(bare) == {}
    # 尚无任何提交的工作树（HEAD 未出生）：与改造前一致，报错而不是静默留空
    unborn = tmp_path / "unborn"
    unborn.mkdir()
    subprocess.run(["git", "init", "-q", str(unborn)], check=True, env=_git_environment())
    with pytest.raises(TreeError):
        git_provenance(unborn)
