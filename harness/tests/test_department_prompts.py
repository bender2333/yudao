import pytest

from harness.artifacts import ArtifactStore
from harness.definitions import DEFINITIONS
from harness.department_prompts import save_department_prompt
from harness.models import DEPARTMENTS, hash_bytes


@pytest.mark.parametrize("department", DEPARTMENTS)
def test_default_prompt_is_saved_verbatim_and_can_be_edited_without_changing_defaults(tmp_path, department):
    store = ArtifactStore(tmp_path / "artifacts")
    initial_text = DEFINITIONS.role(department).prompt
    initial = save_department_prompt(store, "run", department, initial_text)
    edited_text = "  updated\r\n\u4e2d\u6587 instructions\n\t"
    edited = save_department_prompt(store, "run", department, edited_text)
    assert store.get_for_run("run", initial) == initial_text.encode("utf-8")
    assert store.get_for_run("run", edited) == edited_text.encode("utf-8")
    assert initial.kind == edited.kind == "department_prompt"
    assert edited.content_hash == hash_bytes(edited_text.encode("utf-8"))
    assert initial.content_hash != edited.content_hash
    assert DEFINITIONS.role(department).prompt == initial_text


@pytest.mark.parametrize("department", [None, "", "other", "PRODUCT"])
def test_unknown_department_cannot_create_prompt_material(tmp_path, department):
    store = ArtifactStore(tmp_path / "artifacts")
    with pytest.raises(ValueError, match="unknown prompt department"):
        save_department_prompt(store, "run", department, "text")
    assert list(store.root.iterdir()) == []


