"""Tests for deterministic and safe workspace snapshots."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import pytest

import harness.workspace as workspace_module
from harness.workspace import Workspace, _is_link_or_junction, _sha256_file, diff_manifests


def _write_tree(root: Path, entries: list[tuple[str, bytes]]) -> None:
    for relative, content in entries:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def _make_symlink(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as error:
        pytest.fail(f"test environment cannot create required symlink: {error}")


def test_tree_hash_is_order_independent_and_manifest_is_sorted(tmp_path: Path) -> None:
    first = Workspace(str(tmp_path / "first"))
    second = Workspace(str(tmp_path / "second"))
    _write_tree(Path(first.dir), [("z.txt", b"z"), ("nested/b.txt", b"b"), ("a.txt", b"a")])
    _write_tree(Path(second.dir), [("a.txt", b"a"), ("nested/b.txt", b"b"), ("z.txt", b"z")])

    assert first.tree_manifest() == second.tree_manifest()
    assert [item["path"] for item in first.tree_manifest()] == ["a.txt", "nested/b.txt", "z.txt"]
    assert first.tree_hash() == second.tree_hash()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda root: (root / "data.txt").write_bytes(b"changed"),
        lambda root: (root / "data.txt").rename(root / "renamed.txt"),
        lambda root: (root / "empty.txt").write_bytes(b"non-empty"),
    ],
    ids=["content", "path", "empty-file"],
)
def test_tree_hash_changes_for_deliverable_changes(tmp_path: Path, mutation) -> None:
    workspace = Workspace(str(tmp_path / "workspace"))
    root = Path(workspace.dir)
    _write_tree(root, [("data.txt", b"data"), ("empty.txt", b"")])
    before = workspace.tree_hash()

    mutation(root)

    assert workspace.tree_hash() != before


def test_utf8_paths_have_stable_posix_manifest_paths(tmp_path: Path) -> None:
    workspace = Workspace(str(tmp_path / "workspace"))
    _write_tree(Path(workspace.dir), [("资料/雪人-☃.txt", "内容".encode("utf-8"))])

    manifest = workspace.tree_manifest()

    assert manifest[0]["path"] == "资料/雪人-☃.txt"
    assert manifest[0]["sha256"] == "sha256:" + hashlib.sha256("内容".encode("utf-8")).hexdigest()
    assert workspace.tree_hash() == workspace.tree_hash()


def test_workspace_init_only_creates_root_and_harness_contents_are_ignored(tmp_path: Path) -> None:
    workspace = Workspace(str(tmp_path / "workspace"))
    root = Path(workspace.dir)
    assert list(root.iterdir()) == []
    (root / "kept.txt").write_text("kept", encoding="utf-8")
    (root / ".harness").mkdir()
    (root / ".harness" / "ignored.txt").write_text("ignored", encoding="utf-8")

    assert [item["path"] for item in workspace.tree_manifest()] == ["kept.txt"]


def test_harness_directory_link_is_rejected_before_name_filter(tmp_path: Path) -> None:
    workspace = Workspace(str(tmp_path / "workspace"))
    outside = tmp_path / "outside"
    outside.mkdir()
    _make_symlink(Path(workspace.dir) / ".harness", outside, directory=True)

    with pytest.raises(ValueError, match="link"):
        workspace.tree_manifest()


@pytest.mark.parametrize("directory", [False, True], ids=["file", "directory"])
def test_tree_manifest_rejects_symlinks(tmp_path: Path, directory: bool) -> None:
    workspace = Workspace(str(tmp_path / "workspace"))
    root = Path(workspace.dir)
    target = tmp_path / ("target-dir" if directory else "target.txt")
    target.mkdir() if directory else target.write_text("target", encoding="utf-8")
    _make_symlink(root / "linked", target, directory=directory)

    with pytest.raises(ValueError, match="link"):
        workspace.tree_manifest()


def test_tree_manifest_rejects_link_root(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "linked-root"
    _make_symlink(link, target, directory=True)

    with pytest.raises(ValueError, match="link"):
        Workspace(str(link)).tree_manifest()


@pytest.mark.parametrize("ancestor_kind", ["file", "directory"])
def test_workspace_init_rejects_symlink_ancestor(tmp_path: Path, ancestor_kind: str) -> None:
    target = tmp_path / "target"
    if ancestor_kind == "directory":
        target.mkdir()
    else:
        target.write_text("target", encoding="utf-8")
    linked_ancestor = tmp_path / "linked-ancestor"
    _make_symlink(linked_ancestor, target, directory=ancestor_kind == "directory")
    root = linked_ancestor / "workspace"

    with pytest.raises(ValueError, match="link"):
        Workspace(str(root))

    if ancestor_kind == "directory":
        assert not (target / "workspace").exists()


def test_workspace_init_rejects_junction_ancestor_via_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ancestor = tmp_path / "junction-ancestor"
    ancestor.mkdir()
    root = ancestor / "workspace"
    real_check = workspace_module._is_link_or_junction
    monkeypatch.setattr(
        workspace_module,
        "_is_link_or_junction",
        lambda path: os.path.normcase(os.fspath(path)) == os.path.normcase(os.fspath(ancestor))
        or real_check(path),
    )

    with pytest.raises(ValueError, match="link"):
        Workspace(str(root))

    assert not root.exists()


def test_is_link_or_junction_uses_platform_junction_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os.path, "islink", lambda _path: False)
    monkeypatch.setattr(os.path, "isjunction", lambda path: path == "junction", raising=False)

    assert _is_link_or_junction("junction") is True
    assert _is_link_or_junction("regular") is False


def test_tree_manifest_rejects_native_junction_or_helper_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = Workspace(str(tmp_path / "workspace"))
    junction = Path(workspace.dir) / "junction"
    target = tmp_path / "junction-target"
    target.mkdir()
    created = False
    if hasattr(os.path, "isjunction") and os.name == "nt":
        import subprocess

        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
            capture_output=True,
            check=False,
        ).returncode == 0
    if not created:
        junction.mkdir()
        real_check = workspace_module._is_link_or_junction
        monkeypatch.setattr(
            workspace_module,
            "_is_link_or_junction",
            lambda path: os.fspath(path) == os.fspath(junction) or real_check(path),
        )

    with pytest.raises(ValueError, match="link"):
        workspace.tree_manifest()


def test_tree_manifest_rejects_native_fifo_or_lstat_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = Workspace(str(tmp_path / "workspace"))
    special = Path(workspace.dir) / "special"
    if hasattr(os, "mkfifo"):
        try:
            os.mkfifo(special)
        except OSError:
            special.write_bytes(b"placeholder")
    else:
        special.write_bytes(b"placeholder")

    if stat.S_ISREG(os.lstat(special).st_mode):
        real_lstat = workspace_module.os.lstat

        def fake_lstat(path):
            result = real_lstat(path)
            if os.fspath(path) == os.fspath(special):
                values = list(result)
                values[stat.ST_MODE] = stat.S_IFIFO
                return os.stat_result(values)
            return result

        monkeypatch.setattr(workspace_module.os, "lstat", fake_lstat)

    with pytest.raises(ValueError, match="special"):
        workspace.tree_manifest()


def test_tree_manifest_rejects_special_file_without_platform_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = Workspace(str(tmp_path / "workspace"))
    special = Path(workspace.dir) / "special"
    special.write_bytes(b"placeholder")
    real_lstat = workspace_module.os.lstat

    def fake_lstat(path):
        result = real_lstat(path)
        if os.fspath(path) == os.fspath(special):
            values = list(result)
            values[stat.ST_MODE] = stat.S_IFIFO
            return os.stat_result(values)
        return result

    monkeypatch.setattr(workspace_module.os, "lstat", fake_lstat)

    with pytest.raises(ValueError, match="special"):
        workspace.tree_manifest()


def test_sha256_file_is_prefixed_and_handles_multiple_chunks(tmp_path: Path) -> None:
    path = tmp_path / "large.bin"
    content = b"a" * (1024 * 1024 + 17)
    path.write_bytes(content)

    assert _sha256_file(str(path)) == "sha256:" + hashlib.sha256(content).hexdigest()


def test_snapshot_compatibility_is_derived_from_manifest(tmp_path: Path) -> None:
    workspace = Workspace(str(tmp_path / "workspace"))
    (Path(workspace.dir) / "a.txt").write_bytes(b"abc")

    assert workspace.snapshot_files() == {"a.txt": 3}
    assert workspace.snapshot_fingerprints() == {"a.txt": hashlib.sha256(b"abc").hexdigest()}


def test_diff_manifests_reports_sorted_add_change_delete() -> None:
    before = [
        {"path": "delete.txt", "size": 1, "sha256": "sha256:old"},
        {"path": "change.txt", "size": 1, "sha256": "sha256:one"},
        {"path": "same.txt", "size": 4, "sha256": "sha256:same"},
    ]
    after = [
        {"path": "same.txt", "size": 4, "sha256": "sha256:same"},
        {"path": "change.txt", "size": 2, "sha256": "sha256:two"},
        {"path": "add.txt", "size": 1, "sha256": "sha256:new"},
    ]

    assert diff_manifests(before, after) == ["add.txt", "change.txt", "delete.txt"]


@pytest.mark.parametrize(
    "manifest",
    [
        [{}],
        [{"path": "a", "size": 1}],
        [{"path": "a", "size": "1", "sha256": "sha256:x"}],
        [{"path": "a", "size": 1, "sha256": 1}],
        [{"path": "a", "size": 1, "sha256": "sha256:x"}, {"path": "a", "size": 1, "sha256": "sha256:x"}],
    ],
    ids=["missing-path", "missing-sha", "bad-size", "bad-sha", "duplicate-path"],
)
def test_diff_manifests_rejects_malformed_or_duplicate_items(manifest) -> None:
    with pytest.raises(ValueError):
        diff_manifests(manifest, [])
    with pytest.raises(ValueError):
        diff_manifests([], manifest)
