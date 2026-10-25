import hashlib
import json
import os
import shutil
import subprocess
import uuid
from dataclasses import asdict
from pathlib import Path

import pygit2
import pytest
from pygit2.enums import RepositoryOpenFlag

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.app.application import Application
from harness.models import ArtifactRef, EventType, ProjectEventType, canonical_hash, json_dumps
from harness.public_tree import TreeError, capture_public_tree
from harness.proposals import baseline_review_turn, product_spec, structure_turn
from harness.runtime import LoopSystem
from harness.snapshot import git_provenance, restore_snapshot
from harness.tests.api_helpers import running_api

GOAL = "把一份可信代码快照接入后完成增量变更。"
REQUIREMENT = "run the CLI with a word"
APP_BYTES = "print('hello')\n".encode("utf-8")
BIN_BYTES = bytes(range(256))
HIDDEN_BYTES = b"\x00\xff\xfe\r\n"


def _system(data_dir):
    # 建档 run 的三个部门依次提交初始 PRD、现有结构说明与基线核验；
    # 工程与质检的 run_check 回执运行源目录里可执行的 src/app.py。
    # 脚本按部门给出（工单 #557、#879）：PRD 被接纳以后工程与质检同时开始一轮工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化
    return LoopSystem.for_testing(data_dir, FakeAdapter({
        "product": [FakeTurn(proposal=product_spec(requirements=[REQUIREMENT],
                                                   acceptance=["run the CLI with a word"]))],
        "engineering": [structure_turn(checks={"smoke": 0},
                                       modules=[{"path": "src/", "responsibility": "the app"}],
                                       entry_points=[{"kind": "command_line", "path": "src/app.py",
                                                      "how_to_run": "python src/app.py"}],
                                       build_and_test=[{"name": "smoke", "command": "python src/app.py",
                                                        "purpose": "run it"}],
                                       requirement_locations=[{"requirement": REQUIREMENT, "locations": ["src/app.py"]}])],
        "quality": [baseline_review_turn(conclusions=[{"requirement": REQUIREMENT, "status": "verified",
                                                       "evidence": "smoke"}])],
    }))


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
    assert [event.type for event in events] == [EventType.RUN_CREATED]
    created = next(event for event in events if event.type == EventType.RUN_CREATED)
    assert created.payload["snapshot"]["source"] == str(source.absolute())
    assert created.payload["snapshot"]["files"] == [".hidden", "src/app.py", "src/data.bin"]
    assert created.payload["snapshot"]["directories"] == ["empty", "empty/nested", "src"]
    # 建档 run 以 baseline_verified 结束；结算按工单 #136 提出初始 PRD 候选并请求用户确认
    result = system.run_until_stop(run_id)
    assert result.status == "done"
    assert result.stop_reason == "baseline_verified"
    [proposed, requested] = [system.projects.settle(run_id), system.projects.settle(run_id)]
    assert proposed is not None and requested is None
    assert proposed.type == ProjectEventType.INITIAL_PRD_PROPOSED
    assert proposed.payload["round"] == 1
    assert proposed.payload["run_id"] == run_id
    assert system.projects.projection(project_id).work_item(work_item_id).status == "awaiting_initial_prd"
    assert system.projects.projection(project_id).work_item(work_item_id).kind == "onboarding"


@pytest.mark.parametrize("entry", ["initial_directory", "onboard", "restart_onboarding"])
def test_snapshot_entries_exclude_ignored_files_from_archives_and_workspaces(data_dir, tmp_path, entry):
    source = _make_source(tmp_path / "source")
    system = _system(data_dir)
    try:
        if entry == "restart_onboarding":
            project_id, _item_id, old_run_id, _snapshot = _start(system, source)
            system.cancel(old_run_id)
            system.projects.settle(old_run_id)
        (source / ".gitignore").write_bytes(b"secret.txt\ncache/\n")
        (source / "secret.txt").write_bytes(b"excluded source contents")
        (source / "cache").mkdir()
        (source / "cache" / "dependency.bin").write_bytes(b"excluded dependency")
        before = _fingerprint(source)

        if entry == "initial_directory":
            project_id = system.projects.register("快照项目", GOAL, initial_directory=str(source))
            snapshot = system.projects.projection(project_id).initial_snapshot
            _item_id, run_id = system.projects.start_work_item(project_id, REQUIREMENT)
            scope = project_id
        elif entry == "onboard":
            project_id, _item_id, run_id, snapshot = _start(system, source)
            scope = run_id
        else:
            item_id, run_id = system.projects.restart_onboarding(project_id, "src")
            snapshot = system.projects.projection(project_id).work_item(item_id).snapshot
            scope = run_id

        assert snapshot["files"] == [".gitignore", ".hidden", "src/app.py", "src/data.bin"]
        assert snapshot["directories"] == ["empty", "empty/nested", "src"]
        assert snapshot["bytes"] == len(b"secret.txt\ncache/\n") + len(HIDDEN_BYTES) + len(APP_BYTES) + len(BIN_BYTES)
        restored = restore_snapshot(system.artifacts, scope, snapshot, tmp_path / "restored")
        for root in (restored, system.workspace(run_id).root):
            assert not (root / "secret.txt").exists()
            assert not (root / "cache").exists()
            assert (root / "src" / "app.py").read_bytes() == APP_BYTES
        assert _fingerprint(source) == before
    finally:
        system.close()


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


def _unreadable_repository(root: Path) -> Path:
    # 一个 libgit2 打不开的仓库：仓库的 config 损坏，模拟「仓库不属于当前用户」的归属检查失败（工单 #841）
    _git(root, "init", "-q")
    (root / ".git" / "config").write_text("this is not a git config\n", encoding="utf-8")
    return root


def _assert_cannot_be_opened(root: Path) -> None:
    # 这个前提要成立：仓库确实存在，但 libgit2 打开它时报错
    with pytest.raises(pygit2.GitError):
        pygit2.Repository(str(root), flags=RepositoryOpenFlag.NO_SEARCH)


def _create_project_over_http(client, name: str, initial_directory: Path):
    return client.post("/api/commands/project.create", json={
        "command_id": str(uuid.uuid4()), "name": name, "goal": GOAL,
        "initial_directory": str(initial_directory)})


def test_provenance_ignores_the_repository_above_the_source_directory(data_dir, tmp_path):
    # 验收（#841）：上层目录里的 .git 打不开（模拟归属检查失败）时，起始文件夹照常建成，来源为空。
    # 上层目录的仓库不是这个文件夹的来源，也不被打开。
    parent = tmp_path / "home"
    parent.mkdir()
    _unreadable_repository(parent)
    _assert_cannot_be_opened(parent)
    source = _make_source(parent / "project")
    assert git_provenance(source) == {}
    system = _system(data_dir)
    application = Application(system)
    with running_api(lambda: application) as client:
        response = _create_project_over_http(client, "上层有仓库的项目", source)
        assert response.status_code == 200, response.text
        project_id = response.json()["refs"]["project_id"]
        events = system.store.list_project_events(project_id)
        assert events[0].payload["initial_snapshot"]["provenance"] == {}


def test_provenance_is_empty_when_the_repository_above_has_no_commits(data_dir, tmp_path):
    # 验收（#841）：上层目录是当前用户的仓库但还没有提交时，起始文件夹照常建成，来源为空。
    # 上层仓库读不出 HEAD，但那个仓库不是这个文件夹的来源。
    parent = tmp_path / "parent"
    parent.mkdir()
    pygit2.init_repository(str(parent))
    with pytest.raises(pygit2.GitError):
        pygit2.Repository(str(parent), flags=RepositoryOpenFlag.NO_SEARCH).head
    source = _make_source(parent / "src")
    assert git_provenance(source) == {}
    system = _system(data_dir)
    application = Application(system)
    with running_api(lambda: application) as client:
        response = _create_project_over_http(client, "上层有未提交仓库的项目", source)
        assert response.status_code == 200, response.text
        project_id = response.json()["refs"]["project_id"]
        events = system.store.list_project_events(project_id)
        assert events[0].payload["initial_snapshot"]["provenance"] == {}


def test_create_rejects_a_source_directory_whose_repository_cannot_be_opened(data_dir, tmp_path):
    # 验收（#841）：源目录本身是仓库但打不开时，project.create 以 source_invalid 拒绝，
    # 说明里有这个目录与原因，不是 500
    source = _make_source(tmp_path / "source")
    _unreadable_repository(source)
    _assert_cannot_be_opened(source)
    system = _system(data_dir)
    application = Application(system)
    with running_api(lambda: application) as client:
        response = _create_project_over_http(client, "打不开的仓库", source)
        assert response.status_code == 409, response.text
        body = response.json()
        assert body["reason"] == "source_invalid"
        # 说明写明目录与原因
        assert str(source.absolute()) in body["message"]
        assert "Git" in body["message"]
        # 没有建立项目
        assert client.get("/api/queries/projects.list").json()["data"]["projects"] == []

