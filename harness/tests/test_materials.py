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


def test_new_snapshot_does_not_modify_previous_input_or_snapshot(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    first = append_intend(store, "run", "old")
    second = append_intend(store, "run", "new", previous_ref=first.intend_ref)
    assert store.get_for_run("run", first.input_ref) == b"old"
    assert store.get_for_run("run", first.intend_ref) == b"old"
    assert store.get_for_run("run", second.intend_ref) == b"oldnew"


