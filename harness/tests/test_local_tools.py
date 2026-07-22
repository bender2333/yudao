from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from harness import local_tools, process_control
from harness.local_tools import (
    READ_TOOL_NAMES,
    SEARCH_OUTPUT_BYTES,
    WRITE_TOOL_NAMES,
    CheckReceipt,
    CheckSpec,
    LocalToolRuntime,
    _path_is_within,
    _safe_env,
    load_check_manifest,
)
from harness.process_control import run_process_tree

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
    assert runtime.dispatch("run_check", {"name": "x"}).startswith("Error: unknown check")
    assert runtime.dispatch("run_check", {"name": "x", "argv": []}).startswith("Error:")


def test_load_check_manifest_accepts_exact_schema(tmp_path: Path) -> None:
    manifest = tmp_path / "checks.json"
    manifest.write_text(
        json.dumps(
            {
                "protected_paths": ["TASK.md", "tests/public"],
                "checks": {"public_tests": {"argv": ["python", "-V"], "timeout_seconds": 2}},
            }
        ),
        encoding="utf-8",
    )

    checks, protected = load_check_manifest(manifest)

    assert checks == {"public_tests": CheckSpec(("python", "-V"), 2.0)}
    assert protected == ("task.md", "tests/public")


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ([], "top-level"),
        ({"protected_paths": [], "checks": {}, "extra": 1}, "top-level"),
        ({"protected_paths": [], "checks": []}, "checks"),
        ({"protected_paths": [], "checks": {"bad/name": {"argv": ["x"], "timeout_seconds": 1}}}, "name"),
        ({"protected_paths": [], "checks": {"x": {"argv": [], "timeout_seconds": 1}}}, "argv"),
        ({"protected_paths": [], "checks": {"x": {"argv": ["x", 1], "timeout_seconds": 1}}}, "argv"),
        ({"protected_paths": [], "checks": {"x": {"argv": ["x\0"], "timeout_seconds": 1}}}, "argv"),
        ({"protected_paths": [], "checks": {"x": {"argv": ["x"], "timeout_seconds": True}}}, "timeout"),
        ({"protected_paths": [], "checks": {"x": {"argv": ["x"], "timeout_seconds": float("inf")}}}, "timeout"),
        ({"protected_paths": [], "checks": {"x": {"argv": ["x"], "timeout_seconds": 1, "extra": 1}}}, "check x"),
        ({"protected_paths": ["../escape"], "checks": {}}, "protected"),
    ],
)
def test_load_check_manifest_rejects_invalid_fields(tmp_path: Path, payload: object, field: str) -> None:
    manifest = tmp_path / "checks.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=field):
        load_check_manifest(manifest)


@pytest.mark.parametrize("content", [b"\xff", b"{"])
def test_load_check_manifest_reports_utf8_and_json_errors(tmp_path: Path, content: bytes) -> None:
    manifest = tmp_path / "checks.json"
    manifest.write_bytes(content)
    with pytest.raises(ValueError, match="manifest"):
        load_check_manifest(manifest)


def test_runtime_revalidates_programmatic_check_specs(tmp_path: Path) -> None:
    workspace = Workspace(str(tmp_path / "workspace"))
    for checks in (
        {"bad/name": CheckSpec(("python",), 1)},
        {"ok": CheckSpec(("python\0",), 1)},
        {"ok": CheckSpec(("python",), float("nan"))},
        {"ok": CheckSpec(("python",), True)},
    ):
        with pytest.raises((TypeError, ValueError), match="check"):
            LocalToolRuntime(workspace, checks, (), tmp_path / "audit")


def test_run_process_tree_validates_inputs_and_streams_bytes(tmp_path: Path) -> None:
    stdout = tmp_path / "stdout.log"
    stderr = tmp_path / "stderr.log"
    result = run_process_tree(
        [sys.executable, "-c", "import os;os.write(1,b'out\\xff');os.write(2,b'err\\xfe')"],
        cwd=tmp_path,
        env={"PYTHONIOENCODING": "utf-8"},
        timeout_seconds=5,
        stdout_path=stdout,
        stderr_path=stderr,
    )
    assert (result.returncode, result.timed_out) == (0, False)
    assert result.duration_ms >= 0
    assert stdout.read_bytes() == b"out\xff"
    assert stderr.read_bytes() == b"err\xfe"
    with pytest.raises(ValueError, match="different"):
        run_process_tree([sys.executable], cwd=tmp_path, env={}, timeout_seconds=1, stdout_path=stdout, stderr_path=stdout)


def test_run_process_tree_timeout_kills_descendants(tmp_path: Path) -> None:
    sentinel = tmp_path / "sentinel"
    child = "import pathlib,sys,time;time.sleep(.8);pathlib.Path(sys.argv[1]).write_text('escaped');time.sleep(5)"
    parent = "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);time.sleep(5)"
    result = run_process_tree(
        [sys.executable, "-c", parent, child, str(sentinel)],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout_seconds=0.2,
        stdout_path=tmp_path / "out.log",
        stderr_path=tmp_path / "err.log",
    )
    time.sleep(1.0)
    assert result.timed_out
    assert not sentinel.exists()


def test_run_process_tree_timeout_kills_orphaned_grandchild(tmp_path: Path) -> None:
    sentinel = tmp_path / "orphan-sentinel"
    grandchild = "import pathlib,sys,time;time.sleep(.8);pathlib.Path(sys.argv[1]).write_text('escaped')"
    child = "import subprocess,sys;subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)"
    parent = "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2],sys.argv[3]],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);time.sleep(5)"
    result = run_process_tree(
        [sys.executable, "-c", parent, child, grandchild, str(sentinel)],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout_seconds=0.2,
        stdout_path=tmp_path / "orphan-out.log",
        stderr_path=tmp_path / "orphan-err.log",
    )
    time.sleep(1.0)
    assert result.timed_out
    assert not sentinel.exists()


def test_run_process_tree_reaps_after_wait_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = tmp_path / "wait-error-sentinel"
    child = "import pathlib,sys,time;time.sleep(.8);pathlib.Path(sys.argv[1]).write_text('escaped')"
    parent = "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);time.sleep(5)"
    real_popen = subprocess.Popen
    spawned: list[subprocess.Popen[bytes]] = []

    class FailingWaitPopen:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.process = real_popen(*args, **kwargs)
            self.first_wait = True
            spawned.append(self.process)

        def wait(self, *args: object, **kwargs: object) -> int:
            if self.first_wait:
                self.first_wait = False
                raise OSError("wait probe")
            return self.process.wait(*args, **kwargs)

        def __getattr__(self, name: str) -> object:
            return getattr(self.process, name)

    monkeypatch.setattr(process_control.subprocess, "Popen", FailingWaitPopen)
    with pytest.raises(OSError, match="wait probe"):
        run_process_tree(
            [sys.executable, "-c", parent, child, str(sentinel)],
            cwd=tmp_path,
            env=dict(os.environ),
            timeout_seconds=5,
            stdout_path=tmp_path / "wait-out.log",
            stderr_path=tmp_path / "wait-err.log",
        )
    time.sleep(1.0)
    assert spawned[0].poll() is not None
    assert not sentinel.exists()


def test_run_check_uses_disposable_mirror_sanitized_env_and_receipts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDER_KEY", "must-not-leak")
    workspace = Workspace(str(tmp_path / "workspace"))
    root = Path(workspace.dir)
    (root / "value.txt").write_text("before", encoding="utf-8")
    script = (
        "import os,pathlib;assert 'PROVIDER_KEY' not in os.environ;"
        "assert pathlib.Path.cwd()!=pathlib.Path(sys.argv[1]);"
        "pathlib.Path('value.txt').write_text('mirror');pathlib.Path('created').write_text('x');"
        "os.write(1,b'out\\xff');os.write(2,b'err\\xfe')"
    )
    runtime = LocalToolRuntime(
        workspace,
        {"public_tests": CheckSpec((sys.executable, "-c", "import sys;" + script, workspace.dir), 5)},
        (),
        tmp_path / "audit",
    )
    before_hash = workspace.tree_hash()

    output = runtime.dispatch("run_check", {"name": "public_tests"})
    receipt = runtime.receipt("public_tests", before_hash)

    assert receipt is not None and receipt.exit_code == 0 and not receipt.timed_out
    assert output == (
        f"name=public_tests exit=0 timed_out=false duration_ms={receipt.duration_ms} tree_hash={before_hash} "
        f"stdout_digest={receipt.stdout_digest} stderr_digest={receipt.stderr_digest}"
    )
    assert (root / "value.txt").read_text(encoding="utf-8") == "before"
    assert not (root / "created").exists()
    assert receipt.stdout_digest == "sha256:" + hashlib.sha256(b"out\xff").hexdigest()
    assert receipt.stderr_digest == "sha256:" + hashlib.sha256(b"err\xfe").hexdigest()
    assert (tmp_path / "audit" / "0001-public_tests.stdout.log").read_bytes() == b"out\xff"
    assert runtime.receipt("public_tests", "sha256:wrong") is None
    (root / "value.txt").write_text("changed", encoding="utf-8")
    assert runtime.receipt("public_tests", workspace.tree_hash()) is None
    assert runtime.receipt("public_tests", before_hash) is receipt


def test_safe_env_canonicalizes_case_variants_without_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        local_tools.os,
        "environ",
        {"Path": "mixed-path", "provider_token": "secret", "HOME": "home"},
    )
    env = _safe_env()
    assert env["PATH"] == "mixed-path"
    assert "Path" not in env
    assert all("TOKEN" not in key.upper() and value != "secret" for key, value in env.items())


def test_run_check_never_overwrites_or_follows_existing_audit_paths(tmp_path: Path) -> None:
    workspace = Workspace(str(tmp_path / "workspace"))
    audit = tmp_path / "audit"
    audit.mkdir()
    old_stdout = audit / "0001-public.stdout.log"
    old_stderr = audit / "0001-public.stderr.log"
    old_stdout.write_bytes(b"old evidence")
    target = tmp_path / "symlink-target"
    target.write_bytes(b"target evidence")
    os.symlink(target, old_stderr)
    runtime = LocalToolRuntime(
        workspace,
        {"public": CheckSpec((sys.executable, "-c", "import os;os.write(1,b'new')"), 5)},
        (),
        audit,
    )
    runtime.run_check("public")
    assert old_stdout.read_bytes() == b"old evidence"
    assert target.read_bytes() == b"target evidence"
    assert (audit / "0002-public.stdout.log").read_bytes() == b"new"
    assert (audit / "0002-public.stderr.log").read_bytes() == b""


@pytest.mark.parametrize(
    ("name", "script", "timeout", "exit_code", "timed_out"),
    [
        ("nonzero", "import sys;sys.exit(7)", 5, 7, False),
        ("timeout", "import time;time.sleep(5)", 0.1, None, True),
    ],
)
def test_run_check_receipts_cover_nonzero_and_timeout(
    tmp_path: Path, name: str, script: str, timeout: float, exit_code: int | None, timed_out: bool
) -> None:
    workspace = Workspace(str(tmp_path / "workspace"))
    runtime = LocalToolRuntime(workspace, {name: CheckSpec((sys.executable, "-c", script), timeout)}, (), tmp_path / "audit")
    tree_hash = workspace.tree_hash()
    runtime.run_check(name)
    receipt = runtime.receipt(name, tree_hash)
    assert receipt is not None and receipt.timed_out is timed_out
    if exit_code is not None:
        assert receipt.exit_code == exit_code
    assert (tmp_path / "audit" / f"0001-{name}.stdout.log").is_file()
    assert (tmp_path / "audit" / f"0001-{name}.stderr.log").is_file()


def test_run_check_rejects_reserved_workspace_before_copy(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    reserved = Path(runtime.workspace.dir) / ".harness"
    reserved.mkdir()
    (reserved / "secret").write_text("x", encoding="utf-8")
    assert runtime.dispatch("run_check", {"name": "missing"}) == "Error: reserved path"
