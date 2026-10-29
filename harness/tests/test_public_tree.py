import os
import subprocess
import threading
from pathlib import Path

import pytest

from harness import public_tree as public_tree_module
from harness.models import hash_bytes
from harness.public_tree import (
    TreeError,
    capture_public_tree,
    excluded_by_ignore_rules,
    ignore_probe_directory,
    materialize_tree,
    validate_public_path,
    verify_public_tree,
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


@pytest.mark.parametrize("relative", [
    "", ".", "..", "../outside", "/absolute", "C:relative", "C:/absolute", "//server/share",
    "dir\\file", "dir//file", "dir/./file", "dir/../file", ".checks/receipts", ".CHECKS/receipts",
    "name.", "name ", "dir/name:stream", "NUL", "con.txt", "aux.py", "COM1", "Lpt9.log", "COM\u00b9", "CON .txt",
    "bad?name", "bad\x00name", "bad\x1fname", "bad\udcffname",
])
def test_unsafe_or_ambiguous_manifest_paths_are_rejected(relative):
    with pytest.raises(TreeError):
        validate_public_path(relative)


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


@pytest.mark.parametrize("change", ["rewrite", "replace", "toggle_file", "toggle_directory"])
def test_capture_rejects_a_tree_that_keeps_changing_during_collection(tmp_path, monkeypatch, change):
    # 一直变的工作区：有界重读用完后仍然报错，不吞成空树，也不返回这一轮读到的残缺的树
    source = _workspace(tmp_path / "source")
    trigger = source / "undeclared.txt"
    original_open = Path.open
    attempts = []

    def changing_open(path, mode="r", *args, **kwargs):
        if path == trigger and mode == "rb":
            attempts.append(path)
            if change == "rewrite":
                with original_open(trigger, "wb") as handle:
                    handle.write(b"changed %d bytes" % len(attempts))
            elif change == "replace":
                trigger.unlink()
                with original_open(trigger, "wb") as handle:
                    handle.write(b"replacement %d bytes" % len(attempts))
            elif change == "toggle_file":
                toggled = source / "toggled.txt"
                if toggled.exists():
                    toggled.unlink()
                else:
                    with original_open(toggled, "wb") as handle:
                        handle.write(b"toggle")
            else:
                toggled = source / "nested" / "toggled"
                if toggled.exists():
                    toggled.rmdir()
                else:
                    toggled.mkdir()
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", changing_open)
    with pytest.raises(TreeError) as raised:
        capture_public_tree(source)
    assert len(attempts) == public_tree_module.CAPTURE_ATTEMPTS
    assert "changed" in str(raised.value)


def test_capture_rereads_once_another_department_is_done_writing(tmp_path, monkeypatch):
    # 另一个线程在工作区里写文件（模拟工程的 write_file）：捕获撞上这一次写入时重读，成功返回
    source = _workspace(tmp_path / "source")
    trigger = source / "undeclared.txt"
    original_open = Path.open
    write_started = threading.Event()
    writes_done = threading.Event()
    reads = []

    def writer():
        # 一次完整的写入：写完之后这个文件就稳定了，重读应当读到它
        if write_started.wait(10):
            with original_open(trigger, "wb") as handle:
                handle.write(b"engineering wrote this\r\n")
            writes_done.set()

    def writing_open(path, mode="r", *args, **kwargs):
        if path == trigger and mode == "rb" and not reads:
            write_started.set()
            assert writes_done.wait(10), "the writing thread never finished its write"
        if path == trigger and mode == "rb":
            reads.append(path)
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", writing_open)
    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    try:
        tree = capture_public_tree(source)
    finally:
        thread.join(10)

    assert len(reads) >= 2, "the first capture should have collided with the write and been retried"
    captured = {item.path: item.data for item in tree.files}
    assert captured["undeclared.txt"] == b"engineering wrote this\r\n"
    assert sorted(captured) == [".hidden", "nested/binary.bin", "undeclared.txt"]
    assert tree.directories == ("nested", "nested/empty")


def test_capture_reports_a_file_it_can_never_read_stably(tmp_path, monkeypatch):
    # 整个窗口里一直变：重读写不完，仍然报错，消息里有文件名与原因
    source = _workspace(tmp_path / "source")
    trigger = source / "undeclared.txt"
    original_open = Path.open
    reads = []

    def always_changing_open(path, mode="r", *args, **kwargs):
        if path == trigger and mode == "rb":
            reads.append(path)
            # 每次读之前都写一次，长度逐次变化，而且第一次就与原内容（`original\r\nbytes\r`，16 字节）不同：
            # Windows 上文件时间按系统时钟更新（约 15.6 毫秒一格），同一格里的两次**等长**写入在
            # `st_size` 与 `st_mtime_ns` 上都看不出变化，捕获会被当成稳定（2026-10-29 的 CI 上就是这样
            # 失败的：DID NOT RAISE TreeError；本机慢一些、每次写入跨格，所以本机一直通过）
            with original_open(trigger, "wb") as handle:
                handle.write(b"still changing " + b"y" * (10 + len(reads)))
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", always_changing_open)
    with pytest.raises(TreeError) as raised:
        capture_public_tree(source)
    assert len(reads) == public_tree_module.CAPTURE_ATTEMPTS
    assert 1 < public_tree_module.CAPTURE_ATTEMPTS <= 5
    assert "undeclared.txt" in str(raised.value)
    assert "File changed" in str(raised.value)


@pytest.mark.parametrize("name", ["jizhang.cmd", "start.bat", "tool.exe"])
def test_capture_reads_a_stable_script_file_whose_path_and_handle_modes_differ(tmp_path, name):
    # 工作区里一个稳定的 .cmd/.bat/.exe：Windows 上按路径 stat 按后缀补上可执行位、按句柄 fstat
    # 不补，同一个文件的 st_mode 因此不同，不能被当成「文件在变」（工单 #1214，试用 Tc1f7185a-02）
    source = tmp_path / "source"
    source.mkdir()
    (source / "notes.txt").write_bytes(b"stable\r\n")
    (source / name).write_bytes(b"@echo off\r\n")
    tree = capture_public_tree(source)
    assert sorted(item.path for item in tree.files) == sorted(["notes.txt", name])
    assert {item.path: item.data for item in tree.files}[name] == b"@echo off\r\n"


@pytest.mark.parametrize("kind", ["link", "hardlink", "junction"])
def test_a_reread_does_not_loosen_what_the_tree_cannot_represent(tmp_path, monkeypatch, kind):
    # 链接、硬链接与重解析点不可表示：第一次就拒绝，不靠重读把它们绕过去
    source = tmp_path / "source"
    source.mkdir()
    (source / "keep.txt").write_bytes(b"keep")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"outside")
    if kind == "link":
        _symlink(outside, source / "linked", directory=True)
    elif kind == "junction":
        if os.name != "nt":
            pytest.skip("junctions are Windows-specific")
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(source / "linked"), str(outside)], capture_output=True)
        if result.returncode:
            pytest.skip("junctions are unavailable")
    else:
        try:
            os.link(outside / "secret.txt", source / "linked.bin")
        except OSError:
            pytest.skip("hard links are unavailable")
    attempts = []
    original_capture_once = public_tree_module._capture_once

    def counting_capture_once(base, **kwargs):
        attempts.append(base)
        return original_capture_once(base, **kwargs)

    monkeypatch.setattr(public_tree_module, "_capture_once", counting_capture_once)
    with pytest.raises(TreeError, match="not supported") as raised:
        capture_public_tree(source)
    assert len(attempts) == 1, "an entry the tree cannot represent must not be reread"
    assert "linked" in str(raised.value)


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


def test_a_capture_still_excludes_ignored_directories(tmp_path, monkeypatch):
    # 有忽略文件时采集的公开树排除它：被忽略的目录不进入公开树，其中的条目也不再进入
    _forbid_subprocess(monkeypatch)
    workspace = _ignore_workspace(tmp_path / "work", rules="build/\n")
    tree = capture_public_tree(workspace, True)
    assert [item.path for item in tree.files] == [".gitignore", "src/app.py"]
    assert tree.directories == ("nested", "nested/empty", "src")


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

