import json
import shutil
import subprocess
from dataclasses import replace

import pytest

from harness.artifacts import ArtifactStore
from harness.models import canonical_hash, json_dumps
from harness.public_tree import TreeError, capture_public_tree, materialize_tree, verify_public_tree
from harness.tree_archive import load_tree, store_tree


RUN_ID = "run_archive"


def _captured(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "nested" / "empty").mkdir(parents=True)
    (source / ".hidden").write_bytes(b"\x00\xff\xfe")
    (source / "nested" / "main.py").write_bytes(b"raise RuntimeError('must never execute during restore')\r\n")
    (source / "unlisted.txt").write_bytes(b"first\r\nsecond\r\n")
    return source, capture_public_tree(source)


def _rewrite_manifest(store, ref, mutate):
    data = json.loads(store.get_for_run(RUN_ID, ref))
    mutate(data)
    return store.put(RUN_ID, "tree_manifest", json_dumps(data), media_type="application/json")


def test_archived_tree_restores_after_original_is_deleted_and_store_is_relocated(tmp_path, monkeypatch):
    source, tree = _captured(tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store_tree(store, RUN_ID, tree)
    shutil.rmtree(source)
    moved = tmp_path / "moved"
    store.root.rename(moved)
    reopened = ArtifactStore(moved)

    def forbidden(*args, **kwargs):
        raise AssertionError("loading/restoration must not execute a command")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    loaded = load_tree(reopened, RUN_ID, ref)
    assert loaded == tree
    restored = materialize_tree(loaded, tmp_path / "restored")
    verify_public_tree(restored, tree.manifest)
    assert (restored / ".hidden").read_bytes() == b"\x00\xff\xfe"
    assert (restored / "nested" / "empty").is_dir()
    assert (restored / "unlisted.txt").read_bytes() == b"first\r\nsecond\r\n"


@pytest.mark.parametrize("change", ["corrupt", "missing"])
def test_broken_blob_prevents_loading_and_no_destination_is_created(tmp_path, change):
    _, tree = _captured(tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store_tree(store, RUN_ID, tree)
    payload = json.loads(store.get_for_run(RUN_ID, ref))
    blob = store.root / payload["blobs"][-1]["artifact"]["path"]
    if change == "corrupt":
        blob.write_bytes(b"corrupted")
    else:
        blob.unlink()
    target = tmp_path / "restored"
    with pytest.raises((ValueError, FileNotFoundError)):
        materialize_tree(load_tree(store, RUN_ID, ref), target)
    assert not target.exists()


@pytest.mark.parametrize("change", ["missing_blob", "extra_blob", "wrong_path", "wrong_hash", "wrong_size", "wrong_digest", "private", "outside", "directory_missing"])
def test_archive_load_rejects_inconsistent_content_and_references(tmp_path, change):
    _, tree = _captured(tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store_tree(store, RUN_ID, tree)

    def mutate(payload):
        if change == "missing_blob":
            payload["blobs"].pop()
        elif change == "extra_blob":
            payload["blobs"].append(payload["blobs"][-1])
        elif change == "wrong_path":
            payload["blobs"][0]["path"] = "wrong"
        elif change == "wrong_hash":
            payload["blobs"][0]["artifact"]["content_hash"] = "sha256:" + "0" * 64
        elif change == "wrong_size":
            payload["tree"]["files"][0]["size"] += 1
        elif change == "wrong_digest":
            payload["tree_digest"] = "sha256:" + "0" * 64
            return
        elif change == "private":
            payload["tree"]["files"][0]["path"] = ".checks/private"
        elif change == "outside":
            payload["blobs"][0]["artifact"]["path"] = "../outside"
        else:
            payload["tree"]["directories"].remove("nested")
        payload["tree_digest"] = canonical_hash(payload["tree"])

    changed = _rewrite_manifest(store, ref, mutate)
    with pytest.raises((TreeError, ValueError)):
        load_tree(store, RUN_ID, changed)


@pytest.mark.parametrize("raw", [
    b'{"format":"one","format":"two"}', b'{"format":NaN}', b'{"format":Infinity}', b"\xff",
    b"[]", b"{",
])
def test_archive_requires_strict_utf8_json(tmp_path, raw):
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store.put(RUN_ID, "tree_manifest", raw, media_type="application/json")
    with pytest.raises(TreeError):
        load_tree(store, RUN_ID, ref)


def test_manifest_reference_is_bound_to_its_run(tmp_path):
    _, tree = _captured(tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store_tree(store, RUN_ID, tree)
    with pytest.raises(ValueError, match="this run"):
        load_tree(store, "another_run", ref)
    with pytest.raises(TreeError, match="manifest artifact"):
        load_tree(store, RUN_ID, replace(ref, kind="source_file"))


def test_store_detects_preexisting_corrupt_blob_before_publishing_manifest(tmp_path):
    _, tree = _captured(tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    corrupt = store.put(RUN_ID, "tree_file", tree.files[0].data, media_type="application/octet-stream")
    (store.root / corrupt.path).write_bytes(b"old corrupted blob")
    with pytest.raises(ValueError, match="hash mismatch"):
        store_tree(store, RUN_ID, tree)
    assert len(list(store.root.rglob("*"))) == 3


def test_readback_failure_does_not_return_an_archive_reference(tmp_path, monkeypatch):
    _, tree = _captured(tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    put = store.put

    def broken_put(run_id, kind, data, **kwargs):
        ref = put(run_id, kind, data, **kwargs)
        if kind == "tree_manifest":
            (store.root / ref.path).write_bytes(b"incomplete write")
        return ref

    monkeypatch.setattr(store, "put", broken_put)
    with pytest.raises(ValueError, match="hash mismatch"):
        store_tree(store, RUN_ID, tree)


@pytest.mark.parametrize("run_id", ["../outside", "C:relative", "nested/run", "run.", "NUL", ".checks"])
def test_invalid_run_id_is_rejected_before_artifact_write(tmp_path, run_id):
    _, tree = _captured(tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    with pytest.raises(TreeError):
        store_tree(store, run_id, tree)
    assert list(store.root.iterdir()) == []
