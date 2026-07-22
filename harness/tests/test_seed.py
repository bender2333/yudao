"""Tests for strict, safe visible workspace seeding."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

import harness.seed as seed_module
from harness.seed import seed_workspace


def _make_symlink(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as error:
        pytest.fail(f"test environment cannot create required symlink: {error}")


def test_seed_workspace_copies_regular_files_and_returns_sorted_posix_paths(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    (source / "nested").mkdir()
    (source / "z.txt").write_text("z", encoding="utf-8")
    (source / "nested" / "雪.txt").write_text("snow", encoding="utf-8")
    (source / "empty.txt").write_bytes(b"")

    copied = seed_workspace(str(source), str(destination))

    assert copied == ["empty.txt", "nested/雪.txt", "z.txt"]
    assert (destination / "nested" / "雪.txt").read_text(encoding="utf-8") == "snow"
    assert (destination / "empty.txt").read_bytes() == b""


@pytest.mark.parametrize("which", ["source", "destination"])
def test_seed_workspace_requires_existing_directories(tmp_path: Path, which: str) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    if which != "source":
        source.mkdir()
    if which != "destination":
        destination.mkdir()

    with pytest.raises(FileNotFoundError):
        seed_workspace(str(source), str(destination))


@pytest.mark.parametrize("entry_kind", ["file", "directory"])
def test_seed_workspace_requires_empty_destination(tmp_path: Path, entry_kind: str) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    entry = destination / "existing"
    entry.mkdir() if entry_kind == "directory" else entry.write_text("existing", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        seed_workspace(str(source), str(destination))


@pytest.mark.parametrize("root_name", ["source", "destination"])
def test_seed_workspace_rejects_link_roots(tmp_path: Path, root_name: str) -> None:
    real_source = tmp_path / "real-source"
    real_destination = tmp_path / "real-destination"
    real_source.mkdir()
    real_destination.mkdir()
    source = real_source
    destination = real_destination
    if root_name == "source":
        source = tmp_path / "source-link"
        _make_symlink(source, real_source, directory=True)
    else:
        destination = tmp_path / "destination-link"
        _make_symlink(destination, real_destination, directory=True)

    with pytest.raises(ValueError, match="link"):
        seed_workspace(str(source), str(destination))


@pytest.mark.parametrize("alias", [False, True], ids=["same-path", "lexical-alias"])
def test_seed_workspace_rejects_same_root_without_changes(tmp_path: Path, alias: bool) -> None:
    root = tmp_path / "root"
    root.mkdir()
    source_file = root / "keep.txt"
    source_file.write_text("keep", encoding="utf-8")
    destination = root / "." if alias else root

    with pytest.raises(ValueError, match="root overlap"):
        seed_workspace(str(root), str(destination))

    assert source_file.read_text(encoding="utf-8") == "keep"
    assert sorted(path.name for path in root.iterdir()) == ["keep.txt"]


@pytest.mark.parametrize("destination_inside", [True, False], ids=["destination-in-source", "source-in-destination"])
def test_seed_workspace_rejects_nested_roots_before_empty_check(
    tmp_path: Path, destination_inside: bool
) -> None:
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    source, destination = (outer, inner) if destination_inside else (inner, outer)
    source_file = source / "keep.txt"
    source_file.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="root overlap"):
        seed_workspace(str(source), str(destination))

    assert source_file.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("root_name", ["source", "destination"])
@pytest.mark.parametrize("ancestor_kind", ["file", "directory"])
def test_seed_workspace_rejects_symlink_ancestor(
    tmp_path: Path, root_name: str, ancestor_kind: str
) -> None:
    target = tmp_path / "target"
    if ancestor_kind == "directory":
        target.mkdir()
    else:
        target.write_text("target", encoding="utf-8")
    linked_ancestor = tmp_path / "linked-ancestor"
    _make_symlink(linked_ancestor, target, directory=ancestor_kind == "directory")
    linked_root = linked_ancestor / "root"
    if ancestor_kind == "directory":
        linked_root.mkdir()
    ordinary_root = tmp_path / "ordinary"
    ordinary_root.mkdir()
    source = linked_root if root_name == "source" else ordinary_root
    destination = linked_root if root_name == "destination" else ordinary_root

    with pytest.raises(ValueError, match="link"):
        seed_workspace(str(source), str(destination))

    assert list(ordinary_root.iterdir()) == []


@pytest.mark.parametrize("root_name", ["source", "destination"])
def test_seed_workspace_rejects_junction_ancestor_via_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, root_name: str
) -> None:
    ancestor = tmp_path / "junction-ancestor"
    linked_root = ancestor / "root"
    linked_root.mkdir(parents=True)
    ordinary_root = tmp_path / "ordinary"
    ordinary_root.mkdir()
    real_check = seed_module._is_link_or_junction
    monkeypatch.setattr(
        seed_module,
        "_is_link_or_junction",
        lambda path: os.path.normcase(os.fspath(path)) == os.path.normcase(os.fspath(ancestor))
        or real_check(path),
    )
    source = linked_root if root_name == "source" else ordinary_root
    destination = linked_root if root_name == "destination" else ordinary_root

    with pytest.raises(ValueError, match="link"):
        seed_workspace(str(source), str(destination))


@pytest.mark.parametrize("directory", [False, True], ids=["file", "directory"])
def test_seed_workspace_rejects_source_symlinks(tmp_path: Path, directory: bool) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    target = tmp_path / ("target-directory" if directory else "target.txt")
    target.mkdir() if directory else target.write_text("target", encoding="utf-8")
    _make_symlink(source / "linked", target, directory=directory)

    with pytest.raises(ValueError, match="link"):
        seed_workspace(str(source), str(destination))


def test_seed_workspace_rejects_special_source_file_without_platform_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    special = source / "special"
    special.write_bytes(b"placeholder")
    real_lstat = seed_module.os.lstat

    def fake_lstat(path):
        result = real_lstat(path)
        if os.fspath(path) == os.fspath(special):
            values = list(result)
            values[stat.ST_MODE] = stat.S_IFIFO
            return os.stat_result(values)
        return result

    monkeypatch.setattr(seed_module.os, "lstat", fake_lstat)

    with pytest.raises(ValueError, match="special"):
        seed_workspace(str(source), str(destination))


def test_seed_workspace_checks_copied_target_is_still_regular(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    (source / "file.txt").write_text("content", encoding="utf-8")
    real_lstat = seed_module.os.lstat

    def fake_lstat(path):
        result = real_lstat(path)
        if os.fspath(path) == os.fspath(destination / "file.txt"):
            values = list(result)
            values[stat.ST_MODE] = stat.S_IFLNK
            return os.stat_result(values)
        return result

    monkeypatch.setattr(seed_module.os, "lstat", fake_lstat)

    with pytest.raises(ValueError, match="target"):
        seed_workspace(str(source), str(destination))
