import os
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


def test_identical_snapshot_can_be_prepared_again(store, frozen_git_time):
    first = _prepare(store, {"PRD.md": b"same"})
    second = _prepare(store, {"PRD.md": b"same"})
    assert second == first
    assert store.read_files(RUN, first) == store.read_files(RUN, second)


_ORIGINAL_READ_TREE = GitVersionStore._read_tree


def test_a_repository_and_commit_created_by_git_can_be_read_only(tmp_path):
    # 验收对照：版本库与提交由 Git 命令建立，进程内实现只读读取同样的对象与引用
    root = tmp_path / "git"
    repo = root / (RUN + ".git")
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    environment.update({"GIT_AUTHOR_NAME": "Yudao", "GIT_AUTHOR_EMAIL": "host@yudao.invalid",
                        "GIT_AUTHOR_DATE": "1757145600 +0000", "GIT_COMMITTER_NAME": "Yudao",
                        "GIT_COMMITTER_EMAIL": "host@yudao.invalid", "GIT_COMMITTER_DATE": "1757145600 +0000"})

    def git(*arguments, data=None):
        completed = subprocess.run(["git", "--no-pager", "--git-dir=" + str(repo), *arguments],
                                   input=data, capture_output=True, check=True, env=environment)
        return completed.stdout.decode().strip()

    git("init", "--bare", "--quiet", "--template=", str(repo))
    blob = git("hash-object", "-w", "-t", "blob", "--stdin", data=b"from git\n")
    inner = git("mktree", data=f"100644 blob {blob}\ta.py\n".encode())
    tree = git("mktree", data=f"040000 tree {inner}\tcode\n".encode())
    metadata = '{"format":"yudao-git-version-v1","message":"created by git","run_id":"run_versions"}\n'
    commit = git("commit-tree", tree, "-m", metadata)
    git("update-ref", "refs/snapshots/" + commit, commit)
    revision = {"commit": commit, "parent_commit": None, "tree": tree}
    reading = GitVersionStore(root, read_only=True)
    assert reading.read_files(RUN, revision) == {"code/a.py": b"from git\n"}
    assert reading.verify(RUN, revision) is None
    assert reading.show(RUN, revision)["files"] == [{"path": "code/a.py", "status": "A", "binary": False}]
    assert reading.diff(RUN, revision) == git("diff-tree", "-p", "--root", "--no-commit-id", "-r", "--no-renames", commit) + "\n"
    assert git("fsck", "--strict", "--no-reflogs") == ""


