import os
import shutil
import subprocess
from pathlib import Path

import pytest

import harness.submissions as submissions
import harness.workspace as workspaces
from harness.adapters.fake import FakeAdapter
from harness.models import EventType
from harness.proposals import delivery_turn, plan_turn, product_spec, review_turn
from harness.public_tree import TreeError, capture_public_tree, materialize_tree
from harness.runtime import LoopSystem
from harness.tree_archive import load_tree
from harness.workspace import Workspace


def _system_with_delivery(tmp_path):
    system = LoopSystem.for_testing(tmp_path / "new" / "data", FakeAdapter([
        product_spec(), plan_turn(), delivery_turn(), review_turn("release", "Checks passed"),
    ]))
    run_id = system.create_run("Build echo")
    workspace = system.workspace(run_id)
    (workspace.root / ".hidden").write_bytes(b"\x00\xff\xfe")
    (workspace.root / "undeclared.bin").write_bytes(b"\x80\x81\r\n")
    (workspace.root / "empty" / "nested").mkdir(parents=True)
    return system, run_id, workspace


def test_first_run_archives_and_restores_every_public_byte_from_a_new_data_directory(tmp_path):
    system, run_id, workspace = _system_with_delivery(tmp_path)
    result = system.run_until_stop(run_id)
    assert result.phase == "DONE", result.error
    delivery = result.delivery_spec
    assert delivery.files == ["src/echo.py"]
    tree = load_tree(system.artifacts, run_id, delivery.tree_ref)
    assert tree.digest == delivery.code_tree_digest
    assert [item.path for item in tree.files] == [".hidden", "src/echo.py", "undeclared.bin"]
    assert tree.directories == ("empty", "empty/nested", "src")
    assert all(receipt["snapshot_hash"] == tree.digest for receipt in delivery.checks)
    assert result.last_review.code_snapshot_hash == tree.digest
    event = next(event for event in system.store.list_events(run_id) if event.type == EventType.DELIVERY_ACCEPTED)
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
    assert result.phase == "FAILED"
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
    assert result.phase == "FAILED" and result.stop_reason == "host_commit_error"
    assert result.delivery_spec is None
    assert not any(event.type == EventType.DELIVERY_ACCEPTED for event in system.store.list_events(run_id))
    assert len(stored) == 1
    captured, reference = stored[0]
    archived = load_tree(system.artifacts, run_id, reference)
    assert archived == captured
    assert next(item.data for item in archived.files if item.path == "undeclared.bin") == b"\x80\x81\r\n"


def test_workspace_snapshot_and_copy_derive_from_one_capture(tmp_path, monkeypatch):
    workspace = Workspace(tmp_path / "new" / "nested" / "workspace")
    workspace.write_file("file.txt", "captured")
    original_capture = workspaces.capture_public_tree
    calls = []

    def change_after_capture(root):
        captured = original_capture(root)
        calls.append(captured)
        (workspace.root / "file.txt").write_bytes(b"later bytes")
        (workspace.root / "later.txt").write_bytes(b"later file")
        return captured

    monkeypatch.setattr(workspaces, "capture_public_tree", change_after_capture)
    snapshot = workspace.snapshot()
    assert snapshot.tree is calls[0]
    assert snapshot.files == ("file.txt",)
    assert snapshot.digest == snapshot.tree.digest
    with workspace.check_copy(snapshot.tree) as copy_root:
        assert (copy_root / "file.txt").read_bytes() == b"captured"
        assert not (copy_root / "later.txt").exists()
        assert capture_public_tree(copy_root).digest == snapshot.digest
    assert len(calls) == 1


@pytest.mark.parametrize("department", ["engineering", "quality"])
def test_changed_tree_receipts_are_not_reused_even_when_the_hash_later_matches(tmp_path, department):
    workspace = Workspace(tmp_path)
    workspace.write_file("file.txt", "adopted contents")
    digest = workspace.digest()
    workspace.record_check(department, "changed-check", 0, "The test changed its tree", snapshot_hash=digest, tree_changed=True)
    snapshot = workspace.snapshot()
    assert snapshot.checks[-1].snapshot_hash == snapshot.digest
    assert snapshot.checks[-1].exit_code == 0
    assert snapshot.latest_check(department, "changed-check") is None


def test_move_and_delete_preserve_binary_bytes_and_do_not_delete_old_archives(tmp_path):
    system, run_id, workspace = _system_with_delivery(tmp_path)
    result = system.run_until_stop(run_id)
    assert result.phase == "DONE", result.error
    reference = result.delivery_spec.tree_ref
    before = load_tree(system.artifacts, run_id, reference)
    result = workspace.move_file("undeclared.bin", "moved/new.bin")
    assert result == {"source": "undeclared.bin", "destination": "moved/new.bin"}
    assert not (workspace.root / "undeclared.bin").exists()
    assert (workspace.root / "moved" / "new.bin").read_bytes() == b"\x80\x81\r\n"
    assert (workspace.root / "moved" / "new.bin").stat().st_nlink == 1
    assert workspace.delete_file("moved/new.bin") == "moved/new.bin"
    assert not (workspace.root / "moved" / "new.bin").exists()
    assert load_tree(system.artifacts, run_id, reference) == before


def test_move_refuses_existing_destination_without_changing_either_file(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.write_file("source", "source bytes")
    workspace.write_file("destination", "existing bytes")
    with pytest.raises(FileExistsError, match="already exists"):
        workspace.move_file("source", "destination")
    assert workspace.read_file("source") == "source bytes"
    assert workspace.read_file("destination") == "existing bytes"


def test_move_never_overwrites_a_destination_created_after_validation(tmp_path, monkeypatch):
    workspace = Workspace(tmp_path)
    workspace.write_file("source", "source bytes")
    original_link = os.link

    def create_before_move(source, destination, **kwargs):
        Path(destination).write_bytes(b"concurrent destination")
        return original_link(source, destination, **kwargs)

    monkeypatch.setattr(workspaces.os, "link", create_before_move)
    with pytest.raises(FileExistsError):
        workspace.move_file("source", "destination")
    assert workspace.read_file("source") == "source bytes"
    assert workspace.read_file("destination") == "concurrent destination"


def test_move_rolls_back_its_destination_when_source_removal_fails(tmp_path, monkeypatch):
    workspace = Workspace(tmp_path)
    workspace.write_file("source", "source bytes")
    original_unlink = Path.unlink

    def failing_unlink(path, *args, **kwargs):
        if path == workspace.root / "source":
            raise PermissionError("source removal denied")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    with pytest.raises(PermissionError, match="source removal denied"):
        workspace.move_file("source", "destination")
    assert workspace.read_file("source") == "source bytes"
    assert not (workspace.root / "destination").exists()
    assert (workspace.root / "source").stat().st_nlink == 1


@pytest.mark.parametrize("operation", ["delete", "move"])
def test_file_mutations_do_not_recursively_operate_on_directories(tmp_path, operation):
    workspace = Workspace(tmp_path)
    workspace.write_file("directory/keep", "kept")
    with pytest.raises(ValueError, match="regular"):
        if operation == "delete":
            workspace.delete_file("directory")
        else:
            workspace.move_file("directory", "elsewhere")
    assert workspace.read_file("directory/keep") == "kept"
    assert not (workspace.root / "elsewhere").exists()


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


def test_file_operations_preserve_legal_leading_spaces_in_names(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.write_file(" file", "bytes")
    assert workspace.read_file(" file") == "bytes"
    workspace.move_file(" file", " moved")
    assert (workspace.root / " moved").read_bytes() == b"bytes"
    assert not (workspace.root / "moved").exists()
    workspace.delete_file(" moved")
    assert workspace.list_files() == []


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
