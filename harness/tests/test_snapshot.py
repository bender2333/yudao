import hashlib
import json
import os
import shutil
from dataclasses import asdict
from pathlib import Path

import pytest

from harness.adapters.fake import FakeAdapter
from harness.models import ArtifactRef, EventType, ProjectEventType, canonical_hash, json_dumps
from harness.public_tree import TreeError, capture_public_tree
from harness.runtime import LoopSystem
from harness.snapshot import ingest_snapshot, restore_snapshot
from harness.tests.helpers import happy_script
from harness.tests.test_web import get_json, request, running_server, wait_until

GOAL = "把一份可信代码快照接入后完成增量变更。"
APP_BYTES = "print('hello')\n".encode("utf-8")
BIN_BYTES = bytes(range(256))
HIDDEN_BYTES = b"\x00\xff\xfe\r\n"


def _system(data_dir):
    return LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))


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
    project_id = system.projects.register("快照项目", GOAL)
    work_item_id, run_id = system.projects.start_work_item_from_snapshot(
        project_id, str(source), "从快照开始的事项")
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
    project_id = system.projects.register("快照项目", GOAL)
    with pytest.raises(TreeError, match="Links and reparse"):
        system.projects.start_work_item_from_snapshot(project_id, str(source), "带链接的源")
    assert outside.read_bytes() == b"outside"
    assert system.projects.projection(project_id).work_items == []
    # 拒绝后项目仍可用
    outside.unlink()
    (source / "linked.txt").unlink()
    _project_id, _work_item_id, run_id, snapshot = _start(system, source)
    assert system.project(run_id).workspace_digest == snapshot["tree_digest"]


def test_snapshot_rejects_host_private_paths(data_dir, tmp_path):
    source = _make_source(tmp_path / "source")
    (source / ".git").mkdir()
    (source / ".git" / "HEAD").write_bytes(b"ref: refs/heads/main\n")
    system = _system(data_dir)
    project_id = system.projects.register("快照项目", GOAL)
    with pytest.raises(TreeError, match="私有"):
        system.projects.start_work_item_from_snapshot(project_id, str(source), "带_git_的源")
    assert (source / ".git" / "HEAD").read_bytes() == b"ref: refs/heads/main\n"
    assert system.projects.projection(project_id).work_items == []


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
    reopened = LoopSystem(data_dir)
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
    assert system.run_until_stop(run_id).phase == "DONE"
    assert system.projects.settle(run_id).type == ProjectEventType.DELIVERABLE_ADOPTED
    assert system.projects.projection(project_id).work_item(work_item_id).status == "adopted"


def test_ingest_snapshot_function_writes_nothing_to_source(tmp_path, data_dir):
    source = _make_source(tmp_path / "source")
    before = _fingerprint(source)
    system = _system(data_dir)
    tree, record = ingest_snapshot(source, system.artifacts, "run_direct")
    assert record["tree_digest"] == tree.digest == capture_public_tree(source).digest
    assert _fingerprint(source) == before
    restored = restore_snapshot(system.artifacts, "run_direct", record, tmp_path / "direct")
    assert capture_public_tree(restored).digest == tree.digest


def test_work_items_http_entry_accepts_source_dir(data_dir, tmp_path):
    source = _make_source(tmp_path / "source")
    system = _system(data_dir)
    with running_server(system) as (_server, host, port):
        status, raw, _ = request(host, port, "POST", "/api/projects", {"name": "快照", "goal": GOAL})
        assert status == 201, raw
        project_id = json.loads(raw)["project_id"]
        status, raw, _ = request(
            host, port, "POST", f"/api/projects/{project_id}/work-items",
            {"text": "从快照开始", "source_dir": str(source)})
        assert status == 201, raw
        created = json.loads(raw)
        status, raw, _ = request(
            host, port, "POST", f"/api/projects/{project_id}/work-items",
            {"text": "未知字段", "source_dir": str(source), "extra": 1})
        assert status == 400, raw

        def settled():
            project = get_json(host, port, f"/api/projects/{project_id}")
            item = next(entry for entry in project["work_items"]
                        if entry["work_item_id"] == created["work_item_id"])
            if item["status"] not in {"adopted", "held", "stopped"}:
                return False
            if get_json(host, port, "/api/health")["busy"]:
                return False
            return project

        project = wait_until(settled, timeout=60.0)
        item = next(entry for entry in project["work_items"]
                    if entry["work_item_id"] == created["work_item_id"])
        assert item["status"] == "adopted"
        assert item["snapshot"]["source"] == str(source.absolute())
        assert (system.workspace(created["run_id"]).root / "src" / "app.py").exists()
