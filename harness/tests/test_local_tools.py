from __future__ import annotations

import os
from pathlib import Path

import pytest

from harness.local_tools import (
    READ_TOOL_NAMES,
    SEARCH_OUTPUT_BYTES,
    WRITE_TOOL_NAMES,
    CheckReceipt,
    CheckSpec,
    LocalToolRuntime,
    _path_is_within,
)
from harness.workspace import Workspace


def make_runtime(tmp_path: Path, *, protected: tuple[str, ...] = ()) -> LocalToolRuntime:
    return LocalToolRuntime(
        Workspace(str(tmp_path / "workspace")),
        {},
        protected,
        tmp_path / "audit",
    )


@pytest.mark.parametrize(
    "path",
    [
        "",
        ".",
        "/absolute",
        "C:/absolute",
        "C:relative",
        "//server/share",
        "\\\\server\\share",
        "a/../b",
        "../b",
        "a//b",
        "a/./b",
        "a\\b",
        "a:b",
        "a\x00b",
        "a\x1fb",
        "a\x7fb",
    ],
)
def test_file_tools_reject_lexically_unsafe_paths(tmp_path: Path, path: str) -> None:
    runtime = make_runtime(tmp_path)
    for name, extra in (
        ("read_file", {}),
        ("write_file", {"content": "x"}),
        ("edit_file", {"old": "x", "new": "y"}),
    ):
        assert runtime.dispatch(name, {"path": path, **extra}).startswith("Error:")

@pytest.mark.parametrize(
    "path",
    ["TASK.md.", "TASK.md ", "tests/public./x", "tests/public /x"],
)
def test_file_tools_reject_windows_trailing_alias_components(tmp_path: Path, path: str) -> None:
    runtime = make_runtime(tmp_path)
    for name, extra in (
        ("read_file", {}),
        ("write_file", {"content": "x"}),
        ("edit_file", {"old": "x", "new": "y"}),
    ):
        assert runtime.dispatch(name, {"path": path, **extra}).startswith("Error:")



def test_runtime_validates_configuration_and_normalizes_protected_paths(tmp_path: Path) -> None:
    workspace = Workspace(str(tmp_path / "workspace"))
    with pytest.raises(TypeError, match="workspace"):
        LocalToolRuntime(object(), {}, (), tmp_path / "audit")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="checks"):
        LocalToolRuntime(workspace, [], (), tmp_path / "audit")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="audit_dir"):
        LocalToolRuntime(workspace, {}, (), str(tmp_path / "audit"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="outside"):
        LocalToolRuntime(workspace, {}, (), Path(workspace.dir) / "audit")
    with pytest.raises(ValueError, match="protected"):
        LocalToolRuntime(workspace, {}, ("../secret",), tmp_path / "audit")
    with pytest.raises(ValueError, match="duplicate"):
        LocalToolRuntime(workspace, {}, ("safe", "safe"), tmp_path / "audit")
    with pytest.raises(ValueError, match="duplicate"):
        LocalToolRuntime(workspace, {}, ("TASK.md", "task.MD"), tmp_path / "audit")
    with pytest.raises((TypeError, ValueError), match="check"):
        LocalToolRuntime(workspace, {1: CheckSpec(("python",), 1)}, (), tmp_path / "audit")  # type: ignore[dict-item]
    assert not (tmp_path / "audit").exists()
    runtime = LocalToolRuntime(workspace, {}, ("TASK.md",), tmp_path / "audit")
    assert runtime.audit_dir.is_dir()


def test_frozen_receipt_types_and_runtime_state(tmp_path: Path) -> None:
    spec = CheckSpec(("python", "-V"), 2.0)
    receipt = CheckReceipt("public", "sha256:x", 0, False, "out", "err", 7)
    assert spec.argv == ("python", "-V")
    assert receipt.duration_ms == 7
    with pytest.raises(Exception):
        spec.timeout_seconds = 3  # type: ignore[misc]
    runtime = make_runtime(tmp_path)
    assert runtime.receipts == {}
    assert runtime.check_sequence == 0


def test_read_write_edit_roundtrip_and_protected_boundaries(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path, protected=("TASK.md", "tests/public"))
    root = Path(runtime.workspace.dir)
    (root / "TASK.md").write_text("task", encoding="utf-8")
    assert runtime.dispatch("write_file", {"path": "src/雪.py", "content": "old old\n"}) == "Wrote src/雪.py"
    assert runtime.dispatch("read_file", {"path": "src/雪.py"}) == "old old\n"
    assert runtime.dispatch("edit_file", {"path": "src/雪.py", "old": "old", "new": "new"}) == "Edited src/雪.py: 2 replacements"
    assert (root / "src" / "雪.py").read_text(encoding="utf-8") == "new new\n"
    for path in ("TASK.md", "tests/public", "tests/public/x.py"):
        assert runtime.dispatch("write_file", {"path": path, "content": "x"}).startswith("Error:")
    assert runtime.dispatch("write_file", {"path": "tests/publicity/x.py", "content": "ok"}).startswith("Wrote")
    for path in ("task.md", "tests/PUBLIC/x.py"):
        assert runtime.dispatch("write_file", {"path": path, "content": "x"}).startswith("Error:")


def test_content_and_file_size_and_utf8_fail_closed(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    root = Path(runtime.workspace.dir)
    assert runtime.dispatch("write_file", {"path": "x", "content": None}).startswith("Error:")
    assert runtime.dispatch("write_file", {"path": "x", "content": "é" * (512 * 1024 + 1)}).startswith("Error:")
    (root / "large").write_bytes(b"x" * (1024 * 1024 + 1))
    (root / "binary").write_bytes(b"\xff")
    assert runtime.dispatch("read_file", {"path": "large"}).startswith("Error:")
    assert runtime.dispatch("read_file", {"path": "binary"}).startswith("Error:")
    assert runtime.dispatch("edit_file", {"path": "binary", "old": "x", "new": "y"}).startswith("Error:")
    assert runtime.dispatch("edit_file", {"path": "missing", "old": "x", "new": "y"}).startswith("Error:")
    assert runtime.dispatch("edit_file", {"path": "large", "old": "x", "new": "y"}).startswith("Error:")
    assert runtime.dispatch("edit_file", {"path": "x", "old": "", "new": "y"}).startswith("Error:")


def test_existing_directories_and_links_are_never_treated_as_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = make_runtime(tmp_path)
    root = Path(runtime.workspace.dir)
    (root / "dir").mkdir()
    for name, args in (
        ("read_file", {"path": "dir"}),
        ("write_file", {"path": "dir", "content": "x"}),
        ("edit_file", {"path": "dir", "old": "x", "new": "y"}),
    ):
        assert runtime.dispatch(name, args).startswith("Error:")
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        monkeypatch.setattr("harness.local_tools._is_link_or_junction", lambda path: Path(path) == link)
        link.mkdir()
    assert runtime.dispatch("write_file", {"path": "linked/escape", "content": "x"}).startswith("Error:")
    assert not (outside / "escape").exists()
    assert runtime.dispatch("list_files", {}).startswith("Error:")


def test_list_files_is_recursive_sorted_and_loud_on_limits(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    assert runtime.dispatch("list_files", {}) == "(empty)"
    root = Path(runtime.workspace.dir)
    (root / "a").mkdir()
    (root / "a" / "é.txt").write_text("e", encoding="utf-8")
    (root / "b.txt").write_text("b", encoding="utf-8")
    assert runtime.dispatch("list_files", {}) == "a/é.txt\nb.txt"
    for index in range(999):
        (root / f"f{index:03d}").write_text("", encoding="utf-8")
    assert runtime.dispatch("list_files", {}).startswith("Error:")

def test_reserved_harness_namespace_is_never_accessible_or_exposed(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    root = Path(runtime.workspace.dir)
    for alias in (".harness", ".HARNESS"):
        for name, args in (
            ("read_file", {"path": f"{alias}/x"}),
            ("write_file", {"path": f"{alias}/x", "content": "secret"}),
            ("edit_file", {"path": f"{alias}/x", "old": "x", "new": "y"}),
        ):
            assert runtime.dispatch(name, args) == "Error: reserved path"
    (root / ".HARNESS").mkdir()
    (root / ".HARNESS" / "secret").write_text("needle", encoding="utf-8")
    assert runtime.dispatch("list_files", {}) == "Error: reserved path"
    assert runtime.dispatch("search_text", {"query": "needle"}) == "Error: reserved path"



def test_search_text_is_literal_sorted_strict_and_truncated(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    root = Path(runtime.workspace.dir)
    (root / "b.txt").write_text("no\na.b second\n", encoding="utf-8")
    (root / "a.txt").write_text("a.b first\n", encoding="utf-8")
    assert runtime.dispatch("search_text", {"query": "a.b"}) == "a.txt:1:a.b first\nb.txt:2:a.b second"
    assert runtime.dispatch("search_text", {"query": ""}).startswith("Error:")
    assert runtime.dispatch("search_text", {"query": None}).startswith("Error:")
    (root / "many.txt").write_text("\n".join(["hit"] * 201), encoding="utf-8")
    result = runtime.dispatch("search_text", {"query": "hit"})
    assert len(result.splitlines()) == 201
    assert result.endswith("[truncated at 200 matches or 65536 bytes]")
    (root / "bad.bin").write_bytes(b"\xff")
    assert runtime.dispatch("search_text", {"query": "hit"}).startswith("Error:")


def test_search_text_caps_utf8_bytes_without_partial_lines(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    root = Path(runtime.workspace.dir)
    complete_line = "needle" + "雪" * 1000
    (root / "many.txt").write_text("\n".join([complete_line] * 30), encoding="utf-8")
    result = runtime.dispatch("search_text", {"query": "needle"})
    assert len(result.encode("utf-8")) <= SEARCH_OUTPUT_BYTES
    assert result.endswith("[truncated at 200 matches or 65536 bytes]")
    assert all(line == f"many.txt:{index}:{complete_line}" for index, line in enumerate(result.splitlines()[:-1], 1))
    assert runtime.dispatch("search_text", {"query": "absent"}) == "(no matches)"


def test_tool_defs_are_isolated_deep_copies(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    definitions = runtime.tool_defs(True)
    definitions[0]["function"]["parameters"]["properties"]["injected"] = {"type": "string"}
    assert "injected" not in repr(runtime.tool_defs(True))
    assert "injected" not in repr(make_runtime(tmp_path / "other").tool_defs(True))


def test_windows_cross_drive_paths_are_outside_without_commonpath(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os.path, "commonpath", lambda _paths: pytest.fail("commonpath must not compare drives"))
    assert not _path_is_within(r"C:\workspace", r"D:\audit")


def test_audit_dir_rejects_linked_ancestors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = Workspace(str(tmp_path / "workspace"))
    audit = tmp_path / "audit-parent" / "audit"

    def reject_audit(path: object, label: str, link_check: object = None) -> str:
        if Path(path) == audit:
            raise ValueError(f"{label} link is not allowed")
        return os.path.abspath(path)

    monkeypatch.setattr("harness.local_tools._require_link_free_components", reject_audit)
    with pytest.raises(ValueError, match="audit_dir link"):
        LocalToolRuntime(workspace, {}, (), audit)


def test_tool_capabilities_schemas_handlers_and_dispatch_are_closed(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    read_defs = runtime.tool_defs(False)
    write_defs = runtime.tool_defs(True)
    assert {item["function"]["name"] for item in read_defs} == READ_TOOL_NAMES
    assert {item["function"]["name"] for item in write_defs} == READ_TOOL_NAMES | WRITE_TOOL_NAMES
    assert "bash" not in repr(write_defs)
    for item in write_defs:
        parameters = item["function"]["parameters"]
        assert parameters["additionalProperties"] is False
        assert set(parameters["required"]) <= set(parameters["properties"])
    assert set(runtime.handlers()) == READ_TOOL_NAMES | WRITE_TOOL_NAMES
    assert runtime.dispatch("unknown", {}).startswith("Error: unknown tool")
    assert runtime.dispatch("read_file", []).startswith("Error:")  # type: ignore[arg-type]
    class DictSubclass(dict):
        pass

    assert runtime.dispatch("list_files", DictSubclass()).startswith("Error:")
    assert runtime.dispatch("read_file", {}).startswith("Error:")
    assert runtime.dispatch("list_files", {"path": "."}).startswith("Error:")
    assert runtime.dispatch("run_check", {"name": "x"}).startswith("Error: not implemented")
