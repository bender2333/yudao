import os
import shutil
import stat
import subprocess
import zlib
from pathlib import Path
from datetime import datetime, timezone

import pytest

from harness.git_versions import GitVersionError, GitVersionStore
from harness.public_tree import CapturedFile, CapturedTree


RUN = "run_versions"


@pytest.fixture
def store(tmp_path):
    return GitVersionStore(tmp_path / "git")


@pytest.fixture
def frozen_git_time(monkeypatch):
    class FrozenTime:
        @staticmethod
        def now(zone):
            return datetime(2026, 9, 6, 8, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr("harness.git_versions.datetime", FrozenTime)


def _tree(files):
    directories = {parent.as_posix() for path in files for parent in Path(path).parents if str(parent) != "."}
    return CapturedTree(tuple(sorted(directories)), tuple(CapturedFile(path, data) for path, data in sorted(files.items())))


def _prepare(store, files=None, parent=None, code=None, message="accepted"):
    return store.prepare(RUN, parent_commit=parent, updates=files or {}, message=message, code_tree=code)


def _git(store, *arguments):
    # 用 Git 命令行直接查看版本库；去掉环境中的 GIT_ 变量，与版本库自己的调用一样不受外部配置影响
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    return subprocess.run(["git", "--no-pager", "--git-dir=" + str(store.root / (RUN + ".git")), *arguments],
                          capture_output=True, check=True, env=environment).stdout


def _failing_git(monkeypatch, fails):
    # Git 命令在 fails(命令) 为真时失败（与 Git 返回非零退出码相同），其余命令照常执行；返回执行过的命令
    run = subprocess.run
    commands = []

    def git(command, **kwargs):
        commands.append(command)
        if fails(command):
            raise subprocess.CalledProcessError(1, command, stderr=b"injected failure")
        return run(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", git)
    return commands


def test_round_trip_preserves_raw_bytes_and_unicode_paths_and_survives_reopen(store):
    code = {" nested/\u539f\u6587.txt": b"a\r\nb\r\n", ".hidden": b"\x00\xff\xfe", "empty.txt": b""}
    version = _prepare(store, {"intend.md": "  \u539f\u6587\r\n".encode()}, code=_tree(code))
    reopened = GitVersionStore(store.root)
    assert reopened.read_files(RUN, version) == {"intend.md": "  \u539f\u6587\r\n".encode(), **{"code/" + name: data for name, data in code.items()}}
    assert reopened.read_file(RUN, version, "code/ nested/\u539f\u6587.txt") == b"a\r\nb\r\n"
    assert reopened.verify(RUN, version) is None
    assert _git(store, "for-each-ref", "--format=%(refname)").decode().splitlines() == ["refs/snapshots/" + version["commit"]]
    _git(store, "fsck", "--strict", "--no-reflogs")


def test_material_patch_retains_delivered_code_and_explicit_delivery_replaces_it(store):
    first = _prepare(store, {"intend.md": b"one", "obsolete.md": b"obsolete"}, code=_tree({"old.txt": b"old", "keep.txt": b"keep"}))
    second = _prepare(store, {"intend.md": b"one two", "obsolete.md": None}, first["commit"])
    assert store.read_files(RUN, second) == {"intend.md": b"one two", "code/old.txt": b"old", "code/keep.txt": b"keep"}
    third = _prepare(store, {"specs/delivery-tree.json": b"{}"}, second["commit"], _tree({"new.txt": b"new", "keep.txt": b"keep"}))
    assert store.read_files(RUN, third) == {"intend.md": b"one two", "specs/delivery-tree.json": b"{}", "code/new.txt": b"new", "code/keep.txt": b"keep"}
    assert [second["parent_commit"], third["parent_commit"]] == [first["commit"], second["commit"]]
    fourth = _prepare(store, parent=third["commit"], code=_tree({}))
    assert not any(path.startswith("code/") for path in store.read_files(RUN, fourth))


def test_formal_parent_is_supplied_and_orphan_snapshot_does_not_change_it(store):
    first = _prepare(store, {"intend.md": b"first"})
    orphan = _prepare(store, {"PRD.md": b"unaccepted"}, first["commit"])
    accepted = _prepare(store, {"intend.md": b"next"}, first["commit"])
    assert accepted["parent_commit"] == first["commit"]
    assert "PRD.md" not in store.read_files(RUN, accepted)
    assert store.read_file(RUN, orphan, "PRD.md") == b"unaccepted"


def test_show_reports_real_add_modify_delete_and_binary_diff_without_private_paths(store):
    first = _prepare(store, {"PRD.md": b"old\n", "gone.txt": b"gone\n", "binary.dat": b"\0old"})
    second = _prepare(store, {"PRD.md": b"new\n", "gone.txt": None, " added.txt": b"hello\n", "binary.dat": b"\0new"}, first["commit"])
    result = store.show(RUN, second)
    assert result["files"] == [
        {"path": " added.txt", "status": "A", "binary": False},
        {"path": "PRD.md", "status": "M", "binary": False},
        {"path": "binary.dat", "status": "M", "binary": True},
        {"path": "gone.txt", "status": "D", "binary": False},
    ]
    assert "-old\n+new\n" in result["diff"]
    assert "Binary files a/binary.dat and b/binary.dat differ" in result["diff"]
    assert str(store.root) not in result["diff"]
    assert store.diff(RUN, second) == result["diff"]
    assert all(item["status"] == "A" for item in store.show(RUN, first)["files"])


@pytest.mark.parametrize("path", ["../outside", "/absolute", "C:relative", "a\\b", "a/../b", "a//b", ".git/config", "code/.git/config", ".checks/private", "NUL", "end ", "a\0b", "\ud800"])
def test_invalid_update_paths_are_rejected_before_repository_creation(store, path):
    with pytest.raises(GitVersionError):
        _prepare(store, {path: b"bad"})
    assert not (store.root / (RUN + ".git")).exists()


@pytest.mark.parametrize("files", [{"a": b"x", "a/b": b"y"}, {"A": b"x", "a": b"y"}, {"Dir/a": b"x", "dir/b": b"y"}])
def test_file_directory_and_case_collisions_are_rejected(store, files):
    with pytest.raises(GitVersionError):
        _prepare(store, files)


@pytest.mark.parametrize("path", ["code", "code/main.py", "CODE/main.py"])
def test_updates_cannot_mutate_the_code_namespace(store, path):
    with pytest.raises(GitVersionError, match="complete captured tree"):
        _prepare(store, {path: b"x"})


@pytest.mark.parametrize("run_id", ["../outside", "nested/run", "C:relative", "run.", "NUL", ".checks", "", "run space"])
def test_invalid_run_ids_are_rejected(store, run_id):
    with pytest.raises(GitVersionError):
        store.prepare(run_id, parent_commit=None, updates={}, message="input")


@pytest.mark.parametrize("value", ["HEAD", "HEAD~1", "--help", "a" * 39, "A" * 40, "0" * 40, None])
def test_arbitrary_missing_or_invalid_revisions_are_rejected(store, value):
    version = _prepare(store)
    with pytest.raises(GitVersionError):
        store.show(RUN, {**version, "commit": value})


def test_wrong_tree_parent_extra_fields_and_unbound_snapshot_are_rejected(store):
    first = _prepare(store, {"a": b"a"})
    second = _prepare(store, {"a": b"b"}, first["commit"])
    for invalid in ({**second, "tree": first["tree"]}, {**second, "parent_commit": None}, {**second, "extra": 1}):
        with pytest.raises(GitVersionError):
            store.verify(RUN, invalid)
    _git(store, "update-ref", "-d", "refs/snapshots/" + second["commit"])
    with pytest.raises(GitVersionError):
        store.verify(RUN, second)


def test_copied_objects_and_refs_cannot_be_used_by_another_run(store):
    version = _prepare(store, {"PRD.md": b"belongs to run_versions"})
    shutil.copytree(store.root / (RUN + ".git"), store.root / "run_other.git")
    with pytest.raises(GitVersionError):
        store.read_files("run_other", version)
    with pytest.raises(GitVersionError):
        store.prepare("run_other", parent_commit=version["commit"], updates={}, message="wrong run")


@pytest.mark.parametrize("kind", ["blob", "tree", "commit"])
def test_recompressed_object_under_original_oid_is_rejected(store, kind):
    version = _prepare(store, {"PRD.md": b"original\n"})
    if kind == "blob":
        oid = _git(store, "rev-parse", version["commit"] + ":PRD.md").decode().strip()
    else:
        oid = version[kind]
    path = store.root / (RUN + ".git") / "objects" / oid[:2] / oid[2:]
    raw = zlib.decompress(path.read_bytes())
    if kind == "blob":
        changed = raw.replace(b"original", b"tampered")
    elif kind == "tree":
        changed = raw.replace(b"PRD.md", b"BAD.md")
    else:
        changed = raw.replace(b"accepted", b"tampered")
    assert changed != raw and len(changed) == len(raw)
    path.chmod(stat.S_IREAD | stat.S_IWRITE)
    path.write_bytes(zlib.compress(changed))
    with pytest.raises(GitVersionError):
        store.show(RUN, version)


def test_failed_git_write_does_not_return_a_reference(store, monkeypatch):
    _failing_git(monkeypatch, lambda command: "update-ref" in command)
    with pytest.raises(GitVersionError):
        _prepare(store, {"a": b"a"})
    assert _git(store, "for-each-ref") == b""


def test_failed_readback_does_not_return_a_reference(store, monkeypatch):
    # 写入引用以后的回读（ls-tree）失败：不交回版本
    commands = _failing_git(monkeypatch, lambda command: "ls-tree" in command)
    with pytest.raises(GitVersionError):
        _prepare(store)
    assert any("update-ref" in command for command in commands)


def test_git_ignores_global_environment_filters_textconv_hooks_and_autocrlf(store, tmp_path, monkeypatch):
    global_config = tmp_path / "global-config"
    global_config.write_text("[core]\n autocrlf = true\n[filter \"bad\"]\n clean = command-that-must-never-run\n required = true\n[diff \"bad\"]\n textconv = command-that-must-never-run\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.bare")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "false")
    monkeypatch.setenv("GIT_EXTERNAL_DIFF", "command-that-must-never-run")
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(tmp_path / "wrong-objects"))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "untrusted author")
    first = _prepare(store, {".gitattributes": b"* filter=bad diff=bad text\n", "PRD.md": b"old\r\n"})
    repo = store.root / (RUN + ".git")
    hooks = repo / "hostile-hooks"
    hooks.mkdir()
    (hooks / "reference-transaction").write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    _git(store, "config", "core.hooksPath", str(hooks))
    _git(store, "config", "diff.bad.textconv", "command-that-must-never-run")
    _git(store, "config", "filter.bad.clean", "command-that-must-never-run")
    _git(store, "config", "filter.bad.required", "true")
    (repo / "info").mkdir()
    (repo / "info" / "attributes").write_text("* filter=bad diff=bad text\n", encoding="utf-8")
    second = _prepare(store, {"PRD.md": b"new\r\n"}, first["commit"])
    assert store.read_file(RUN, second, "PRD.md") == b"new\r\n"
    assert "+new\r\n" in store.diff(RUN, second)
    commit = _git(store, "cat-file", "commit", second["commit"])
    assert b"author Yudao <host@yudao.invalid>" in commit
    assert not (tmp_path / "wrong-objects").exists()


def test_read_operations_do_not_write_repository_objects_or_refs(store):
    version = _prepare(store, {"PRD.md": b"original\n"})
    before = {str(path.relative_to(store.root)): path.read_bytes() for path in store.root.rglob("*") if path.is_file()}
    store.show(RUN, version)
    store.read_file(RUN, version, "PRD.md")
    store.verify(RUN, version)
    after = {str(path.relative_to(store.root)): path.read_bytes() for path in store.root.rglob("*") if path.is_file()}
    assert after == before


def test_subprocess_failures_hide_private_paths_and_do_not_use_shell(store, monkeypatch):
    def fail(command, **kwargs):
        assert kwargs["shell"] is False
        assert isinstance(command, list)
        raise subprocess.CalledProcessError(1, command, stderr=b"private repo path and credential")

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(GitVersionError) as error:
        _prepare(store)
    assert str(error.value) == "Git version is unavailable or invalid"


def test_alternate_object_store_is_rejected(store, tmp_path):
    version = _prepare(store)
    (store.root / (RUN + ".git") / "objects" / "info" / "alternates").write_text(str(tmp_path), encoding="utf-8")
    with pytest.raises(GitVersionError):
        store.verify(RUN, version)


def test_root_parent_traversal_is_rejected(tmp_path):
    with pytest.raises(GitVersionError):
        GitVersionStore(tmp_path / "parent" / ".." / "git")


def test_missing_file_is_an_explicit_version_error(store):
    version = _prepare(store)
    with pytest.raises(GitVersionError, match="not present"):
        store.read_file(RUN, version, "missing")


def test_identical_snapshot_can_be_prepared_again(store, frozen_git_time):
    first = _prepare(store, {"PRD.md": b"same"})
    second = _prepare(store, {"PRD.md": b"same"})
    assert second == first
    assert store.read_files(RUN, first) == store.read_files(RUN, second)


def test_gitignore_and_gitattributes_do_not_change_complete_code_capture(store):
    code = {
        ".gitignore": b"*.dat\r\nbuild/\r\n",
        ".gitattributes": b"* text eol=lf filter=bad\r\n",
        "build/ignored.dat": b"\x00\xff\r\n\x00\n",
        "src/.checks/readme.txt": b"public nested directory\r\n",
        "text.txt": b"one\r\ntwo\r\n",
    }
    version = _prepare(store, code=_tree(code))
    assert store.read_files(RUN, version) == {"code/" + path: data for path, data in code.items()}


@pytest.mark.parametrize("broken", [b"", b"missing\n", b"bad blob 3\nabc\n", b"0" * 40 + b" blob 3\nab\n"])
def test_malformed_or_truncated_git_batch_output_is_rejected(store, monkeypatch, broken):
    version = _prepare(store, {"a": b"a"})
    run = subprocess.run

    def broken_batch(command, **kwargs):
        # Git 批量读取对象的输出残缺或格式不对
        if "cat-file" in command and "--batch" in command:
            return subprocess.CompletedProcess(command, 0, stdout=broken, stderr=b"")
        return run(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", broken_batch)
    with pytest.raises(GitVersionError):
        store.read_files(RUN, version)


def test_material_updates_reuse_validated_code_objects_and_batch_the_reads(store, monkeypatch):
    first = _prepare(store, {"intend.md": b"first"}, code=_tree({f"file-{index}.txt": str(index).encode() for index in range(20)}))
    commands = _failing_git(monkeypatch, lambda command: False)
    second = _prepare(store, {"intend.md": b"second"}, first["commit"])
    assert len([command for command in commands if "hash-object" in command]) == 1
    reads = [command for command in commands if "cat-file" in command]
    assert len(reads) == 4
    assert all(command[command.index("cat-file") + 1] == "--batch" for command in reads)
    assert _git(store, "rev-parse", first["commit"] + ":code") == _git(store, "rev-parse", second["commit"] + ":code")


def test_readback_failure_followed_by_identical_retry_accepts_existing_snapshot(store, monkeypatch, frozen_git_time):
    with monkeypatch.context() as failure:
        _failing_git(failure, lambda command: "ls-tree" in command)
        with pytest.raises(GitVersionError):
            _prepare(store, {"a": b"same"})
    [written] = [line.split()[0].decode("ascii") for line in _git(store, "for-each-ref", "--format=%(objectname) %(refname)").splitlines()]
    actual = _prepare(store, {"a": b"same"})
    assert actual["commit"] == written
    assert store.read_files(RUN, actual) == {"a": b"same"}


def test_existing_snapshot_ref_pointing_to_another_commit_is_rejected(store, frozen_git_time):
    first = _prepare(store, {"a": b"first"})
    other = _prepare(store, {"a": b"other"})
    _git(store, "update-ref", "refs/snapshots/" + first["commit"], other["commit"])
    with pytest.raises(GitVersionError):
        _prepare(store, {"a": b"first"})


def _directory_link(link, target):
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=True)
    else:
        link.symlink_to(target, target_is_directory=True)


def test_linked_root_is_rejected_before_git_runs(tmp_path, monkeypatch):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    _directory_link(link, target)

    def forbidden(*args, **kwargs):
        raise AssertionError("Git must not run through a linked root")

    monkeypatch.setattr(subprocess, "run", forbidden)
    with pytest.raises(GitVersionError):
        GitVersionStore(link / "git")
    assert list(target.iterdir()) == []


def test_linked_repository_is_rejected(store, tmp_path):
    version = _prepare(store, {"a": b"first"})
    repo = store.root / (RUN + ".git")
    moved = tmp_path / "moved.git"
    repo.rename(moved)
    _directory_link(repo, moved)
    with pytest.raises(GitVersionError):
        store.verify(RUN, version)
