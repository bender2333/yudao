import os

import pytest

from harness.environment import LocalEnvironment
from harness.tests.helpers import perform
from harness.workspace import Workspace

def _environment(root):
    workspace = Workspace(root)
    return workspace, LocalEnvironment(workspace)

def _read_content_hash(environment, path, start=1, end=None):
    args = {"path": path, "start_line": start}
    if end is not None:
        args["end_line"] = end
    seen = perform(environment, "read_range", args)
    assert seen.ok, seen.error
    return seen.output["content_hash"]


def test_successful_edit_replaces_exactly_the_requested_span(tmp_path):
    workspace, environment = _environment(tmp_path)
    workspace.write_file("src/a.py", "HEADER = True\nVALUE = 1\nFOOTER = True\n")
    content_hash = _read_content_hash(environment, "src/a.py", 1, 3)
    result = perform(environment, "edit_range", {
        "path": "src/a.py", "start_line": 2, "end_line": 2,
        "expected_text": "VALUE = 1", "new_text": "VALUE = 2\nDOUBLED = True",
        "expected_digest": content_hash,
    })
    assert result.ok, result.error
    assert result.output["path"] == "src/a.py"
    assert (result.output["start_line"], result.output["end_line"]) == (2, 3)
    assert result.output["digest"] == workspace.digest()
    # 回执的新摘要与区间可直接复核
    reread = perform(environment, "read_range", {"path": "src/a.py", "start_line": 1})
    assert reread.ok, reread.error
    assert reread.output["digest"] == result.output["digest"]
    assert [entry["text"] for entry in reread.output["lines"]] == [
        "HEADER = True", "VALUE = 2", "DOUBLED = True", "FOOTER = True",
    ]
    assert workspace.read_file("src/a.py") == "HEADER = True\nVALUE = 2\nDOUBLED = True\nFOOTER = True\n"

def test_changed_file_since_read_is_rejected_without_modification(tmp_path):
    workspace, environment = _environment(tmp_path)
    workspace.write_file("src/a.py", "VALUE = 1\nTAIL = 1\n")
    stale_hash = _read_content_hash(environment, "src/a.py", 1, 2)
    before_bytes = (workspace.root / "src" / "a.py").read_bytes()
    before_digest = workspace.digest()
    # 文件已被他人改动：摘要与原文都不再对得上
    workspace.write_file("src/a.py", "VALUE = 9\nTAIL = 1\n")
    changed_digest = workspace.digest()
    changed_hash = _read_content_hash(environment, "src/a.py", 1, 2)
    assert changed_digest != before_digest
    rejected = perform(environment, "edit_range", {
        "path": "src/a.py", "start_line": 1, "end_line": 1,
        "expected_text": "VALUE = 1", "new_text": "VALUE = 2",
        "expected_digest": stale_hash,
    })
    assert rejected.ok is False
    assert "re-read" in (rejected.error or "")
    # 摘要对得上但原文写错同样拒绝
    wrong_text = perform(environment, "edit_range", {
        "path": "src/a.py", "start_line": 1, "end_line": 1,
        "expected_text": "VALUE = 1", "new_text": "VALUE = 2",
        "expected_digest": changed_hash,
    })
    assert wrong_text.ok is False
    assert "re-read" in (wrong_text.error or "")
    assert (workspace.root / "src" / "a.py").read_bytes() == before_bytes.replace(b"VALUE = 1", b"VALUE = 9")
    assert workspace.digest() == changed_digest

def test_ambiguous_expected_text_is_rejected_without_a_matching_start_line(tmp_path):
    # 工单 #719：原文出现多次时用 start_line 消歧；没有这样的一处就拒绝，并写明匹配了几次
    workspace, environment = _environment(tmp_path)
    workspace.write_file("src/a.py", "VALUE = 1\nOTHER = 2\nVALUE = 1\n")
    content_hash = _read_content_hash(environment, "src/a.py", 1, 1)
    before_bytes = (workspace.root / "src" / "a.py").read_bytes()
    before_digest = workspace.digest()
    # 不给 start_line：无法消歧
    result = perform(environment, "edit_range", {
        "path": "src/a.py",
        "expected_text": "VALUE = 1", "new_text": "VALUE = 2",
        "expected_digest": content_hash,
    })
    assert result.ok is False
    assert "ambiguous" in (result.error or "")
    assert "2 times" in (result.error or "")
    assert (workspace.root / "src" / "a.py").read_bytes() == before_bytes
    assert workspace.digest() == before_digest
    # start_line 指到没有匹配的那一行：同样拒绝
    wrong_line = perform(environment, "edit_range", {
        "path": "src/a.py", "start_line": 2, "end_line": 2,
        "expected_text": "VALUE = 1", "new_text": "VALUE = 2",
        "expected_digest": content_hash,
    })
    assert wrong_line.ok is False
    assert "ambiguous" in (wrong_line.error or "")
    assert (workspace.root / "src" / "a.py").read_bytes() == before_bytes
    assert workspace.digest() == before_digest


def test_symlink_is_rejected_without_modification(tmp_path):
    workspace, environment = _environment(tmp_path / "workspace")
    workspace.write_file("real.txt", "VALUE = 1\n")
    outside = tmp_path / "outside.txt"
    outside.write_text("VALUE = 9\n", encoding="utf-8")
    before_digest = workspace.digest()
    link = workspace.root / "linked.txt"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("symbolic links are unavailable")
    result = perform(environment, "edit_range", {
        "path": "linked.txt", "start_line": 1, "end_line": 1,
        "expected_text": "VALUE = 9", "new_text": "VALUE = 2",
    })
    assert result.ok is False
    assert "Links and reparse points are not supported" in (result.error or "")
    assert outside.read_text(encoding="utf-8") == "VALUE = 9\n"
    assert link.is_symlink() and link.resolve() == outside.resolve()
    assert workspace.read_file("real.txt") == "VALUE = 1\n"
    # 公开树不表示链接，工作区含链接时没有摘要；移除链接后其余公开字节与编辑前一致
    link.unlink()
    assert workspace.digest() == before_digest


def test_stale_pass_verdict_cannot_be_reused_after_tree_changes(tmp_path):
    workspace, environment = _environment(tmp_path)
    workspace.write_file("app.py", "print('ok')\n")
    workspace.write_file("check.py", "raise SystemExit(0)\n")
    passed = perform(environment, "run_check", {"name": "smoke", "command": "python check.py"})
    assert passed.ok and passed.output["exit_code"] == 0, passed.error
    assert workspace.snapshot().facts.latest_check("engineering", "smoke") is not None
    content_hash = _read_content_hash(environment, "app.py", 1, 1)
    edited = perform(environment, "edit_range", {
        "path": "app.py", "start_line": 1, "end_line": 1,
        "expected_text": "print('ok')", "new_text": "print('changed')",
        "expected_digest": content_hash,
    })
    assert edited.ok, edited.error
    # 树已变，绑定旧树的通过结论不能沿用
    assert workspace.snapshot().facts.latest_check("engineering", "smoke") is None


