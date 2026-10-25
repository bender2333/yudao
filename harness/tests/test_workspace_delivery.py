import os
import shutil
import subprocess

import pytest

import harness.submissions as submissions
from harness.adapters.fake import FakeAdapter
from harness.models import EventType
from harness.proposals import delivery_turn, product_spec, review_turn
from harness.public_tree import TreeError, capture_public_tree, materialize_tree
from harness.runtime import LoopSystem
from harness.tree_archive import load_tree
from harness.workspace import Workspace

def _system_with_delivery(tmp_path):
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）。
    # 质检给两项：交付到达以前提交的那一项没有交付可以核验，被拒绝；到达以后的那一项核验并放行
    system = LoopSystem.for_testing(tmp_path / "new" / "data", FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [review_turn("release", "Checks passed"), review_turn("release", "Checks passed")],
    }))
    run_id = system.create_run("Build echo")
    workspace = system.workspace(run_id)
    (workspace.root / ".hidden").write_bytes(b"\x00\xff\xfe")
    (workspace.root / "undeclared.bin").write_bytes(b"\x80\x81\r\n")
    (workspace.root / "empty" / "nested").mkdir(parents=True)
    return system, run_id, workspace

def test_first_run_archives_and_restores_every_public_byte_from_a_new_data_directory(tmp_path):
    system, run_id, workspace = _system_with_delivery(tmp_path)
    result = system.run_until_stop(run_id)
    assert result.status == "done", result.error
    delivery = result.delivery_spec
    # 清单由主机从封存的交付快照得出：公开树的全部文件，按路径排序（工单 #677）
    assert delivery.files == [".hidden", "src/echo.py", "undeclared.bin"]
    tree = load_tree(system.artifacts, run_id, delivery.tree_ref)
    assert tree.digest == delivery.code_tree_digest
    assert [item.path for item in tree.files] == [".hidden", "src/echo.py", "undeclared.bin"]
    assert tree.directories == ("empty", "empty/nested", "src")
    assert all(receipt["snapshot_hash"] == tree.digest for receipt in delivery.checks)
    assert result.last_review.code_snapshot_hash == tree.digest
    event = next(event for event in system.store.list_events(run_id) if event.type == EventType.DELIVERY_ACCEPTED)
    # 落进事件日志的那一份交付，清单同样是封存树的全部文件（工单验收第 1 条）
    assert event.payload["files"] == [".hidden", "src/echo.py", "undeclared.bin"]
    assert event.payload["tree_ref"]["content_hash"] in event.artifact_hashes
    assert "file_refs" not in event.payload and "snapshot_ref" not in event.payload
    shutil.rmtree(workspace.root)
    restored = materialize_tree(load_tree(system.artifacts, run_id, delivery.tree_ref), tmp_path / "restored")
    assert (restored / ".hidden").read_bytes() == b"\x00\xff\xfe"
    assert (restored / "undeclared.bin").read_bytes() == b"\x80\x81\r\n"
    assert not (restored / ".checks").exists()
    assert capture_public_tree(restored).digest == delivery.code_tree_digest
    assert system.replay(run_id).delivery_spec.tree_ref == delivery.tree_ref

def test_delivery_blob_failure_does_not_accept_or_release_the_delivery(tmp_path, monkeypatch):
    system, run_id, _ = _system_with_delivery(tmp_path)
    put = system.artifacts.put

    def failing_put(run_id, kind, data, **kwargs):
        if kind == "tree_file":
            raise OSError("simulated artifact write failure")
        return put(run_id, kind, data, **kwargs)

    monkeypatch.setattr(system.artifacts, "put", failing_put)
    result = system.run_until_stop(run_id)
    assert result.status == "failed"
    assert result.stop_reason == "host_commit_error"
    assert "simulated artifact write failure" in result.error
    assert result.delivery_spec is None
    assert not any(event.type in {EventType.DELIVERY_ACCEPTED, EventType.RUN_DONE} for event in system.store.list_events(run_id))

def test_source_change_after_blob_storage_rejects_acceptance_without_replacing_captured_bytes(tmp_path, monkeypatch):
    system, run_id, workspace = _system_with_delivery(tmp_path)
    store_tree = submissions.store_tree
    stored = []

    def change_after_storage(store, identity, tree):
        reference = store_tree(store, identity, tree)
        stored.append((tree, reference))
        (workspace.root / "undeclared.bin").write_bytes(b"changed after storage")
        return reference

    monkeypatch.setattr(submissions, "store_tree", change_after_storage)
    result = system.run_until_stop(run_id)
    assert result.status == "failed" and result.stop_reason == "host_commit_error"
    assert result.delivery_spec is None
    assert not any(event.type == EventType.DELIVERY_ACCEPTED for event in system.store.list_events(run_id))
    assert len(stored) == 1
    captured, reference = stored[0]
    archived = load_tree(system.artifacts, run_id, reference)
    assert archived == captured
    assert next(item.data for item in archived.files if item.path == "undeclared.bin") == b"\x80\x81\r\n"


@pytest.mark.parametrize("department", ["engineering", "quality"])
def test_changed_tree_receipts_are_not_reused_even_when_the_hash_later_matches(tmp_path, department):
    workspace = Workspace(tmp_path)
    workspace.write_file("file.txt", "adopted contents")
    digest = workspace.digest()
    workspace.record_check(department, "changed-check", 0, "The test changed its tree", snapshot_hash=digest, tree_changed=True)
    snapshot = workspace.snapshot()
    assert snapshot.checks[-1].snapshot_hash == snapshot.digest
    assert snapshot.checks[-1].exit_code == 0
    assert snapshot.facts.latest_check(department, "changed-check") is None


@pytest.mark.parametrize("path", [".checks/receipts.jsonl", ".CHECKS/receipts.jsonl", "../outside", "C:relative", "/absolute", "file:stream", "file.", "dir\\file"])
@pytest.mark.parametrize("operation", ["read", "write", "delete", "move_source", "move_destination"])
def test_all_workspace_file_operations_share_public_path_rules(tmp_path, path, operation):
    workspace = Workspace(tmp_path)
    workspace.write_file("source", "kept")
    (workspace.root / ".checks" / "receipts.jsonl").write_bytes(b"host record")
    with pytest.raises(TreeError):
        _operate(workspace, operation, path)
    assert workspace.read_file("source") == "kept"
    assert (workspace.root / ".checks" / "receipts.jsonl").read_bytes() == b"host record"

@pytest.mark.parametrize("operation", ["read", "write", "delete", "move_source", "move_destination"])
def test_all_workspace_file_operations_reject_hardlinks(tmp_path, operation):
    workspace = Workspace(tmp_path / "workspace")
    workspace.write_file("source", "kept")
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside")
    os.link(outside, workspace.root / "linked")
    with pytest.raises(TreeError, match="Hard-linked"):
        _operate(workspace, operation, "linked")
    assert outside.read_bytes() == b"outside"
    assert workspace.read_file("source") == "kept"

@pytest.mark.skipif(os.name != "nt", reason="junctions are Windows-specific")
@pytest.mark.parametrize("operation", ["read", "write", "delete", "move_source", "move_destination"])
def test_all_workspace_file_operations_reject_junction_ancestors(tmp_path, operation):
    workspace = Workspace(tmp_path / "workspace")
    workspace.write_file("source", "kept")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "file").write_bytes(b"outside")
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(workspace.root / "linked"), str(outside)], capture_output=True)
    assert result.returncode == 0
    with pytest.raises(TreeError, match="Links and reparse"):
        _operate(workspace, operation, "linked/file")
    assert (outside / "file").read_bytes() == b"outside"
    assert workspace.read_file("source") == "kept"


def _operate(workspace, operation, path):
    if operation == "read":
        return workspace.read_file(path)
    if operation == "write":
        return workspace.write_file(path, "changed")
    if operation == "delete":
        return workspace.delete_file(path)
    if operation == "move_source":
        return workspace.move_file(path, "moved")
    return workspace.move_file("source", path)
