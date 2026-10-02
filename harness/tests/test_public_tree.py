import os
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from harness.models import hash_bytes
from harness.public_tree import (
    CapturedFile, CapturedTree, TreeError, capture_public_tree, excluded_by_ignore_rules,
    ignore_probe_directory, materialize_tree, validate_manifest, validate_public_path, verify_public_tree,
)


def _workspace(root):
    root.mkdir()
    (root / ".checks").mkdir()
    (root / ".checks" / "private.txt").write_bytes(b"not public")
    (root / "nested" / "empty").mkdir(parents=True)
    (root / ".hidden").write_bytes(b"hidden\r\n")
    (root / "nested" / "binary.bin").write_bytes(b"\x00\xff\xfe\r\n\x80")
    (root / "undeclared.txt").write_bytes(b"original\r\nbytes\r")
    return root


def _symlink(target, link, *, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError:
        pytest.skip("symbolic links are unavailable")


def test_complete_tree_round_trip_preserves_bytes_hidden_files_and_empty_directories(tmp_path):
    source = _workspace(tmp_path / "source")
    tree = capture_public_tree(source)
    assert tree.directories == ("nested", "nested/empty")
    assert [item.path for item in tree.files] == [".hidden", "nested/binary.bin", "undeclared.txt"]
    assert tree.manifest["files"][1] == {
        "path": "nested/binary.bin", "size": 6, "content_hash": hash_bytes(b"\x00\xff\xfe\r\n\x80"),
    }
    (source / "undeclared.txt").write_bytes(b"source has moved on")
    restored = materialize_tree(tree, tmp_path / "restored")
    assert (restored / "undeclared.txt").read_bytes() == b"original\r\nbytes\r"
    assert (restored / "nested" / "binary.bin").read_bytes() == b"\x00\xff\xfe\r\n\x80"
    assert (restored / "nested" / "empty").is_dir()
    assert not (restored / ".checks").exists()
    assert capture_public_tree(restored) == tree
    assert capture_public_tree(restored).digest == tree.digest


@pytest.mark.parametrize("change", ["extra_file", "empty_directory", "file_bytes"])
def test_verification_checks_the_whole_tree_not_only_declared_file_hashes(tmp_path, change):
    source = _workspace(tmp_path / "source")
    tree = capture_public_tree(source)
    if change == "extra_file":
        (source / "not-in-manifest.txt").write_bytes(b"extra")
    elif change == "empty_directory":
        (source / "nested" / "empty").rmdir()
    else:
        (source / "nested" / "binary.bin").write_bytes(b"\x00\xff\xfe\r\n\x81")
    with pytest.raises(TreeError, match="complete recorded manifest"):
        verify_public_tree(source, tree.manifest)


def test_private_receipts_and_timestamp_changes_do_not_change_public_identity(tmp_path):
    source = _workspace(tmp_path / "source")
    tree = capture_public_tree(source)
    (source / ".checks" / "private.txt").write_bytes(b"new host receipt")
    os.utime(source / ".hidden", ns=(1234567890000000000, 1234567890000000000))
    assert capture_public_tree(source).digest == tree.digest


def test_empty_public_tree_can_be_restored(tmp_path):
    source = tmp_path / "empty"
    source.mkdir()
    tree = capture_public_tree(source)
    restored = materialize_tree(tree, tmp_path / "restored")
    assert tree.directories == () and tree.files == ()
    assert list(restored.iterdir()) == []


@pytest.mark.parametrize("relative", [
    "", ".", "..", "../outside", "/absolute", "C:relative", "C:/absolute", "//server/share",
    "dir\\file", "dir//file", "dir/./file", "dir/../file", ".checks/receipts", ".CHECKS/receipts",
    "name.", "name ", "dir/name:stream", "NUL", "con.txt", "aux.py", "COM1", "Lpt9.log", "COM\u00b9", "CON .txt",
    "bad?name", "bad\x00name", "bad\x1fname", "bad\udcffname",
])
def test_unsafe_or_ambiguous_manifest_paths_are_rejected(relative):
    with pytest.raises(TreeError):
        validate_public_path(relative)


def test_unicode_file_names_and_contents_remain_exact(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    name = "\u4ea4\u4ed8\u5185\u5bb9.txt"
    data = "\u4e2d\u6587\r\n".encode("utf-8")
    (source / name).write_bytes(data)
    tree = capture_public_tree(source)
    restored = materialize_tree(tree, tmp_path / "restored")
    assert tree.files == (CapturedFile(name, data),)
    assert (restored / name).read_bytes() == data


@pytest.mark.parametrize("change", ["duplicate", "case_collision", "missing_parent", "file_parent", "unsorted", "bool_size", "extra_field"])
def test_manifest_rejects_ambiguous_or_incomplete_tree_structure(tmp_path, change):
    manifest = capture_public_tree(_workspace(tmp_path / "source")).manifest
    if change == "duplicate":
        manifest["files"].append(deepcopy(manifest["files"][-1]))
    elif change == "case_collision":
        manifest["directories"] = ["Nested", *manifest["directories"]]
    elif change == "missing_parent":
        manifest["directories"].remove("nested")
    elif change == "file_parent":
        manifest["files"][-1]["path"] = "undeclared.txt/child"
    elif change == "unsorted":
        manifest["files"].reverse()
    elif change == "bool_size":
        manifest["files"][0]["size"] = True
    else:
        manifest["files"][0]["extra"] = "unknown"
    with pytest.raises(TreeError):
        validate_manifest(manifest)


@pytest.mark.parametrize("kind", ["file", "directory", "dangling", "root", "ancestor"])
def test_capture_rejects_links_instead_of_silently_omitting_them(tmp_path, kind):
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"outside")
    if kind == "root":
        linked = tmp_path / "linked"
        _symlink(source, linked, directory=True)
        target = linked
    elif kind == "ancestor":
        linked = tmp_path / "linked"
        _symlink(tmp_path, linked, directory=True)
        target = linked / "source"
    else:
        target = source
        destination = outside if kind == "directory" else outside / ("missing" if kind == "dangling" else "secret.txt")
        _symlink(destination, source / "linked", directory=kind == "directory")
    with pytest.raises(TreeError, match="Links and reparse"):
        capture_public_tree(target)
    assert (outside / "secret.txt").read_bytes() == b"outside"


def test_capture_rejects_hardlinks(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    try:
        os.link(outside, source / "linked.bin")
    except OSError:
        pytest.skip("hard links are unavailable")
    with pytest.raises(TreeError, match="Hard-linked"):
        capture_public_tree(source)


@pytest.mark.skipif(os.name != "nt", reason="junctions are Windows-specific")
@pytest.mark.parametrize("placement", ["entry", "root", "ancestor"])
def test_capture_rejects_windows_junctions(tmp_path, placement):
    source = tmp_path / "source"
    outside = tmp_path / "outside"
    source.mkdir()
    outside.mkdir()
    link = source / "junction" if placement == "entry" else tmp_path / "junction"
    destination = outside if placement == "entry" else source if placement == "root" else tmp_path
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(destination)], capture_output=True)
    if result.returncode:
        pytest.skip("junctions are unavailable")
    target = source if placement == "entry" else link if placement == "root" else link / "source"
    with pytest.raises(TreeError, match="Links and reparse"):
        capture_public_tree(target)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are unavailable")
def test_capture_rejects_special_files_without_trying_to_read_them(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    os.mkfifo(source / "pipe")
    with pytest.raises(TreeError, match="Only regular"):
        capture_public_tree(source)


@pytest.mark.parametrize("change", ["rewrite", "replace", "add_file", "remove_directory"])
def test_capture_rejects_a_tree_that_changes_during_collection(tmp_path, monkeypatch, change):
    source = _workspace(tmp_path / "source")
    trigger = source / "undeclared.txt"
    original_open = Path.open
    changed = False

    def changing_open(path, mode="r", *args, **kwargs):
        nonlocal changed
        if path == trigger and mode == "rb" and not changed:
            changed = True
            if change == "rewrite":
                with original_open(trigger, "wb") as handle:
                    handle.write(b"changed bytes")
            elif change == "replace":
                trigger.unlink()
                with original_open(trigger, "wb") as handle:
                    handle.write(b"replacement bytes")
            elif change == "add_file":
                with original_open(source / "new.txt", "wb") as handle:
                    handle.write(b"new")
            else:
                (source / "nested" / "empty").rmdir()
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", changing_open)
    with pytest.raises((TreeError, FileNotFoundError)):
        capture_public_tree(source)
    assert changed


def test_capture_rejects_a_file_rewritten_during_its_read(tmp_path, monkeypatch):
    source = _workspace(tmp_path / "source")
    trigger = source / "undeclared.txt"
    original_open = Path.open

    class ChangingReader:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            self.handle.__enter__()
            return self

        def __exit__(self, *args):
            return self.handle.__exit__(*args)

        def fileno(self):
            return self.handle.fileno()

        def read(self):
            raw = self.handle.read()
            with original_open(trigger, "wb") as handle:
                handle.write(b"changed while reading")
            return raw

    def changing_open(path, mode="r", *args, **kwargs):
        handle = original_open(path, mode, *args, **kwargs)
        return ChangingReader(handle) if path == trigger and mode == "rb" else handle

    monkeypatch.setattr(Path, "open", changing_open)
    with pytest.raises(TreeError, match="while it was being captured"):
        capture_public_tree(source)


def test_restore_rejects_existing_destination_without_changing_it(tmp_path):
    tree = capture_public_tree(_workspace(tmp_path / "source"))
    destination = tmp_path / "exists"
    destination.mkdir()
    marker = destination / "keep"
    marker.write_bytes(b"existing data")
    with pytest.raises(TreeError, match="already exists"):
        materialize_tree(tree, destination)
    assert list(destination.iterdir()) == [marker]
    assert marker.read_bytes() == b"existing data"


def test_restore_rejects_a_linked_destination_parent(tmp_path):
    tree = capture_public_tree(_workspace(tmp_path / "source"))
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked"
    _symlink(outside, linked, directory=True)
    with pytest.raises(TreeError, match="Links and reparse"):
        materialize_tree(tree, linked / "restored")
    assert list(outside.iterdir()) == []


def test_restore_verifies_written_bytes_before_reporting_success(tmp_path, monkeypatch):
    tree = capture_public_tree(_workspace(tmp_path / "source"))
    original_open = Path.open

    class CorruptingWriter:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            self.handle.__enter__()
            return self

        def __exit__(self, *args):
            return self.handle.__exit__(*args)

        def write(self, data):
            return self.handle.write(b"wrong bytes")

    def corrupting_open(path, mode="r", *args, **kwargs):
        handle = original_open(path, mode, *args, **kwargs)
        return CorruptingWriter(handle) if mode == "xb" else handle

    monkeypatch.setattr(Path, "open", corrupting_open)
    with pytest.raises(TreeError, match="complete recorded manifest"):
        materialize_tree(tree, tmp_path / "restored")


def test_captured_tree_cannot_hide_mutable_or_unvalidated_file_contents():
    with pytest.raises(TreeError, match="bytes"):
        CapturedFile("file", bytearray(b"mutable"))
    with pytest.raises(TreeError, match="tuples"):
        CapturedTree([], ())
    with pytest.raises(TreeError, match="declared parent"):
        CapturedTree((), (CapturedFile("missing/file", b"data"),))

def _forbid_subprocess(monkeypatch):
    # 采集与忽略规则判定不再启动任何子进程：一旦启动 subprocess 就报错
    def forbidden(command, *args, **kwargs):
        raise AssertionError(f"capture must not start a process: {command}")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)

def _git_check_ignore(workspace, relatives):
    # 外部对照：与改造前生产代码完全相同的 Git 命令行（同一个探测目录、同一份环境隔离）
    probe = ignore_probe_directory(workspace)
    assert os.path.exists(probe / "HEAD"), "进程内判定应当已经建好探测库"
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    environment.update({
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.excludesFile", "GIT_CONFIG_VALUE_0": os.devnull,
    })
    completed = subprocess.run(
        ["git", "--no-pager", f"--git-dir={probe}", f"--work-tree={workspace}", "-c", "core.quotePath=false",
         "check-ignore", "--no-index", "--stdin", "-z"],
        input="\0".join(relatives).encode("utf-8") + b"\0", capture_output=True, check=False, env=environment)
    assert completed.returncode in (0, 1), completed.stderr.decode("utf-8", errors="replace")
    return frozenset(item for item in completed.stdout.decode("utf-8").split("\0") if item)

def _ignore_workspace(root, *, rules=None):
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "app.py").write_bytes(b"print('hello')\n")
    (root / "build").mkdir()
    (root / "build" / "out.bin").write_bytes(b"\x00\x01\x02")
    (root / "nested" / "empty").mkdir(parents=True)
    if rules is not None:
        (root / ".gitignore").write_bytes(rules.encode("utf-8"))
    return root

def test_ignore_rules_exclude_nothing_when_the_workspace_has_no_ignore_file(tmp_path, monkeypatch):
    # 工作区内没有 .gitignore 时没有任何规则可以排除路径：判定连探测库都不打开，也不启动进程
    _forbid_subprocess(monkeypatch)
    workspace = _ignore_workspace(tmp_path / "work")
    relatives = ["src/app.py", "build/out.bin", "build"]
    assert excluded_by_ignore_rules(workspace, relatives) == frozenset()
    assert not os.path.exists(ignore_probe_directory(workspace))

def test_ignore_rules_exclude_the_paths_the_project_lists(tmp_path, monkeypatch):
    # 有忽略文件时由进程内的 libgit2 判定：被排除的路径与被保留的路径分开，且与 Git 命令行一致
    _forbid_subprocess(monkeypatch)
    workspace = _ignore_workspace(tmp_path / "work", rules="build/\n")
    relatives = ["src/app.py", "build/out.bin", "build"]
    excluded = excluded_by_ignore_rules(workspace, relatives)
    monkeypatch.undo()
    assert excluded == {"build", "build/out.bin"}
    assert excluded == _git_check_ignore(workspace, relatives)

def test_a_capture_over_a_workspace_without_ignore_files_never_opens_a_probe(tmp_path, monkeypatch):
    # 一次采集的每一层目录都判定一遍忽略规则；工作区没有忽略文件时整次采集不打开探测库也不启动进程
    _forbid_subprocess(monkeypatch)
    workspace = _ignore_workspace(tmp_path / "work")
    tree = capture_public_tree(workspace, True)
    assert [item.path for item in tree.files] == ["build/out.bin", "src/app.py"]
    assert tree.directories == ("build", "nested", "nested/empty", "src")
    assert not os.path.exists(ignore_probe_directory(workspace))

def test_a_capture_still_excludes_ignored_directories(tmp_path, monkeypatch):
    # 有忽略文件时采集的公开树排除它：被忽略的目录不进入公开树，其中的条目也不再进入
    _forbid_subprocess(monkeypatch)
    workspace = _ignore_workspace(tmp_path / "work", rules="build/\n")
    tree = capture_public_tree(workspace, True)
    assert [item.path for item in tree.files] == [".gitignore", "src/app.py"]
    assert tree.directories == ("nested", "nested/empty", "src")

def test_an_ignore_file_in_a_nested_directory_only_excludes_paths_under_it(tmp_path, monkeypatch):
    # 忽略文件放在子目录时只影响它以下的路径：工作区根下的路径仍然进入公开树
    _forbid_subprocess(monkeypatch)
    workspace = _ignore_workspace(tmp_path / "work")
    (workspace / "src" / ".gitignore").write_bytes(b"app.py\n")
    tree = capture_public_tree(workspace, True)
    assert [item.path for item in tree.files] == ["build/out.bin", "src/.gitignore"]
    assert tree.directories == ("build", "nested", "nested/empty", "src")

def test_a_nested_git_directory_keeps_its_own_ignore_rules(tmp_path, monkeypatch):
    # 子目录里的 .git 目录使其中的忽略文件仍然生效：libgit2 到该目录为止继续读它自己的规则
    _forbid_subprocess(monkeypatch)
    workspace = _ignore_workspace(tmp_path / "work")
    (workspace / "src" / ".git").mkdir()
    (workspace / "src" / ".gitignore").write_bytes(b"app.py\n")
    tree = capture_public_tree(workspace, True)
    assert [item.path for item in tree.files] == ["build/out.bin", "src/.gitignore"]

@pytest.mark.parametrize("rules, nested, paths", [
    (b"build/\n", None, ["build", "build/out.bin", "src/app.py"]),
    (b"*.log\n!important.log\n", None, ["a.log", "important.log", "src/app.py"]),
    (b"", b"*.tmp\n", ["sub/x.tmp", "x.tmp", "src/app.py"]),
    (b"sub/keep.txt\n", b"keep.txt\n*.tmp\n", ["sub/keep.txt", "sub/x.tmp", "sub/gone.txt"]),
    (b"**/secret\n", None, ["secret", "sub/secret", "sub/keep.txt"]),
    (b"\\#a.txt\n", None, ["#a.txt", "a.txt"]),
    (b"file[0-9].txt\n", None, ["file3.txt", "fileX.txt"]),
    (b"b.txt \n", None, ["b.txt", "a.txt"]),
    (b"x/*\n!x/keep.txt\n", None, ["x/keep.txt", "x/deep/a.py"]),
])
def test_the_in_process_decision_matches_the_git_command_line(tmp_path, monkeypatch, rules, nested, paths):
    # 常见规则形状上逐条核对：进程内判定的结果与同一探测库上的 Git 命令行完全相同
    workspace = tmp_path / "work"
    workspace.mkdir()
    for relative in paths:
        target = workspace / relative
        if any(other != relative and other.startswith(relative + "/") for other in paths):
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x")
    (workspace / ".gitignore").write_bytes(rules)
    if nested is not None:
        (workspace / "sub" / ".gitignore").write_bytes(nested)
    _forbid_subprocess(monkeypatch)
    excluded = set(excluded_by_ignore_rules(workspace, paths))
    monkeypatch.undo()
    assert excluded == set(_git_check_ignore(workspace, paths))

def test_the_probe_repository_lives_outside_the_workspace_and_stays_clean(tmp_path, monkeypatch):
    # 探测库在工作区之外，因此它不会成为公开树的条目；只读判定也不向它写入对象
    workspace = _ignore_workspace(tmp_path / "work", rules="*.bin\n")
    _forbid_subprocess(monkeypatch)
    tree = capture_public_tree(workspace, True)
    probe = ignore_probe_directory(workspace)
    assert not os.path.exists(workspace / probe.name)
    assert [item.path for item in tree.files] == [".gitignore", "src/app.py"]
    assert tree.directories == ("build", "nested", "nested/empty", "src")
    objects = [entry for entry in (probe / "objects").rglob("*") if entry.is_file()]
    assert objects == []
