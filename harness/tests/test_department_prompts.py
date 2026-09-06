import pytest

from harness.artifacts import ArtifactStore
from harness.department_prompts import DEFAULT_PROMPTS, save_department_prompt
from harness.models import DEPARTMENTS, hash_bytes


@pytest.mark.parametrize("department", DEPARTMENTS)
def test_default_prompt_is_saved_verbatim_and_can_be_edited_without_changing_defaults(tmp_path, department):
    store = ArtifactStore(tmp_path / "artifacts")
    initial_text = DEFAULT_PROMPTS[department]
    initial = save_department_prompt(store, "run", department, initial_text)
    edited_text = "  updated\r\n\u4e2d\u6587 instructions\n\t"
    edited = save_department_prompt(store, "run", department, edited_text)
    assert store.get_for_run("run", initial) == initial_text.encode("utf-8")
    assert store.get_for_run("run", edited) == edited_text.encode("utf-8")
    assert initial.kind == edited.kind == "department_prompt"
    assert edited.content_hash == hash_bytes(edited_text.encode("utf-8"))
    assert initial.content_hash != edited.content_hash
    assert DEFAULT_PROMPTS[department] == initial_text


def test_prompt_reference_is_scoped_to_its_run(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    first = save_department_prompt(store, "first-run", "product", "same prompt")
    second = save_department_prompt(store, "second-run", "product", "same prompt")
    assert first.content_hash == second.content_hash
    assert first.path != second.path
    with pytest.raises(ValueError, match="does not belong to this run"):
        store.get_for_run("second-run", first)


@pytest.mark.parametrize("department", [None, "", "other", "PRODUCT"])
def test_unknown_department_cannot_create_prompt_material(tmp_path, department):
    store = ArtifactStore(tmp_path / "artifacts")
    with pytest.raises(ValueError, match="unknown prompt department"):
        save_department_prompt(store, "run", department, "text")
    assert list(store.root.iterdir()) == []


@pytest.mark.parametrize("text", [None, "", " \r\n\t"])
def test_invalid_prompt_is_rejected_without_writing(tmp_path, text):
    store = ArtifactStore(tmp_path / "artifacts")
    with pytest.raises(ValueError, match="non-empty string"):
        save_department_prompt(store, "run", "product", text)
    assert list(store.root.iterdir()) == []


def test_failed_prompt_storage_is_not_returned_as_a_saved_prompt(tmp_path, monkeypatch):
    store = ArtifactStore(tmp_path / "artifacts")

    def failed_put(*args, **kwargs):
        raise OSError("storage unavailable")

    monkeypatch.setattr(store, "put", failed_put)
    with pytest.raises(OSError, match="storage unavailable"):
        save_department_prompt(store, "run", "product", "updated prompt")


def test_prompt_save_verifies_existing_artifact_bytes(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    ref = save_department_prompt(store, "run", "product", "prompt")
    (store.root / ref.path).write_bytes(b"modified")
    with pytest.raises(ValueError, match="hash mismatch"):
        save_department_prompt(store, "run", "product", "prompt")
