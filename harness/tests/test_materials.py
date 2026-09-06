from dataclasses import replace

import pytest

from harness.artifacts import ArtifactStore
from harness.materials import append_intend
from harness.models import hash_bytes


def test_inputs_remain_verbatim_and_byte_spans_recover_every_source(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    texts = ["  \ufeffinitial\r\n", "\u4e2d\u6587 continuation\n\t", "next\x00input", "\nfinal  "]
    materials = []
    previous_ref = None
    combined = b""
    for text in texts:
        material = append_intend(store, "run", text, previous_ref=previous_ref)
        assert material.byte_start == len(combined)
        combined += text.encode("utf-8")
        assert material.byte_end == len(combined)
        assert store.get_for_run("run", material.input_ref) == text.encode("utf-8")
        assert store.get_for_run("run", material.intend_ref) == combined
        assert material.input_ref.kind == "user_input"
        assert material.intend_ref.kind == "intend"
        assert material.intend_ref.content_hash == hash_bytes(combined)
        materials.append(material)
        previous_ref = material.intend_ref
    for material, text in zip(materials, texts):
        assert combined[material.byte_start:material.byte_end] == text.encode("utf-8")
    assert materials[1].byte_end - materials[1].byte_start > len(texts[1])
    assert b"input_ref" not in combined and b"byte_start" not in combined


def test_initial_input_and_snapshot_share_bytes_without_extra_storage(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    result = append_intend(store, "run", "source text")
    assert result.byte_start == 0 and result.byte_end == len(b"source text")
    assert result.input_ref.path == result.intend_ref.path
    assert result.input_ref.content_hash == result.intend_ref.content_hash
    assert len([path for path in store.root.rglob("*") if path.is_file()]) == 1


def test_new_snapshot_does_not_modify_previous_input_or_snapshot(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    first = append_intend(store, "run", "old")
    second = append_intend(store, "run", "new", previous_ref=first.intend_ref)
    assert store.get_for_run("run", first.input_ref) == b"old"
    assert store.get_for_run("run", first.intend_ref) == b"old"
    assert store.get_for_run("run", second.intend_ref) == b"oldnew"


@pytest.mark.parametrize("text", [None, 1, b"bytes", "", " \r\n\t"])
def test_invalid_input_is_rejected_before_any_artifact_is_written(tmp_path, text):
    store = ArtifactStore(tmp_path / "artifacts")
    with pytest.raises(ValueError, match="non-empty string"):
        append_intend(store, "run", text)
    assert list(store.root.iterdir()) == []


@pytest.mark.parametrize("run_id", [None, "", ".", "..", "../outside", "run/child", "run\\child", "C:\\outside"])
def test_invalid_run_id_cannot_write_before_rejection(tmp_path, run_id):
    store = ArtifactStore(tmp_path / "artifacts")
    with pytest.raises(ValueError, match="run id"):
        append_intend(store, run_id, "original")
    assert list(store.root.iterdir()) == []


def test_previous_snapshot_cannot_be_borrowed_from_another_run(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    first = append_intend(store, "first-run", "first")
    with pytest.raises(ValueError, match="does not belong to this run"):
        append_intend(store, "second-run", "second", previous_ref=first.intend_ref)
    assert not (store.root / "second-run").exists()


@pytest.mark.parametrize("kind", ["user_input", "department_prompt", "tool_output"])
def test_previous_snapshot_must_be_an_intend_artifact(tmp_path, kind):
    store = ArtifactStore(tmp_path / "artifacts")
    ref = store.put("run", kind, "not an intend snapshot")
    before = set(store.root.rglob("*"))
    with pytest.raises(ValueError, match="intend artifact"):
        append_intend(store, "run", "new", previous_ref=ref)
    assert set(store.root.rglob("*")) == before


@pytest.mark.parametrize("change", [
    {"path": "../other-run/file"}, {"content_hash": "invalid"},
    {"content_hash": "sha256:" + "0" * 64},
])
def test_wrong_previous_reference_is_rejected_without_persisting_new_input(tmp_path, change):
    store = ArtifactStore(tmp_path / "artifacts")
    first = append_intend(store, "run", "first")
    before = set(store.root.rglob("*"))
    with pytest.raises(ValueError):
        append_intend(store, "run", "new", previous_ref=replace(first.intend_ref, **change))
    assert set(store.root.rglob("*")) == before


def test_modified_previous_bytes_are_rejected_before_append(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    first = append_intend(store, "run", "first")
    (store.root / first.intend_ref.path).write_bytes(b"modified")
    with pytest.raises(ValueError, match="hash mismatch"):
        append_intend(store, "run", "new", previous_ref=first.intend_ref)


def test_non_utf8_previous_snapshot_is_rejected(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    invalid = store.put("run", "intend", b"\xff")
    before = set(store.root.rglob("*"))
    with pytest.raises(UnicodeDecodeError):
        append_intend(store, "run", "new", previous_ref=invalid)
    assert set(store.root.rglob("*")) == before


@pytest.mark.parametrize("failed_kind", ["user_input", "intend"])
def test_storage_failure_returns_no_material_and_preserves_previous_snapshot(tmp_path, monkeypatch, failed_kind):
    store = ArtifactStore(tmp_path / "artifacts")
    first = append_intend(store, "run", "first")
    original_put = store.put

    def failed_put(run_id, kind, data, **kwargs):
        if kind == failed_kind:
            raise OSError("storage unavailable")
        return original_put(run_id, kind, data, **kwargs)

    monkeypatch.setattr(store, "put", failed_put)
    with pytest.raises(OSError, match="storage unavailable"):
        append_intend(store, "run", "new", previous_ref=first.intend_ref)
    assert store.get_for_run("run", first.intend_ref) == b"first"


def test_existing_corrupt_destination_is_not_acknowledged_as_stored(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    first = append_intend(store, "run", "first")
    corrupt_destination = store.put("run", "intend", b"firstnew")
    (store.root / corrupt_destination.path).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash mismatch"):
        append_intend(store, "run", "new", previous_ref=first.intend_ref)
    assert store.get_for_run("run", first.intend_ref) == b"first"


def test_readback_failure_is_not_acknowledged_as_a_successful_append(tmp_path, monkeypatch):
    store = ArtifactStore(tmp_path / "artifacts")
    original_get = store.get_for_run

    def failed_get(run_id, ref):
        if ref.kind == "intend":
            raise OSError("readback failed")
        return original_get(run_id, ref)

    monkeypatch.setattr(store, "get_for_run", failed_get)
    with pytest.raises(OSError, match="readback failed"):
        append_intend(store, "run", "original")
