import os

import pytest

from harness.tools import TOOL_DEFS, ToolRuntime, tools_for
from harness.workspace import Workspace


def _runtime(root):
    workspace = Workspace(root)
    return workspace, ToolRuntime(workspace)


def test_search_tools_are_read_only_for_all_departments():
    for name in ("search", "read_range"):
        assert TOOL_DEFS[name]["access"] == "read"
        assert set(TOOL_DEFS[name]["departments"]) == set(TOOL_DEFS["read_file"]["departments"])
        for department in ("product", "engineering", "quality"):
            assert name in tools_for(department)


def test_search_returns_path_line_and_locatable_snippet(tmp_path):
    workspace, runtime = _runtime(tmp_path)
    workspace.write_file("src/main.py", "第一行\nneedle 在这里\n最后一行\n")
    result = runtime.execute("engineering", "search", {"pattern": "needle"})
    assert result.ok, result.error
    assert result.output["total_matches"] == 1
    match = result.output["matches"][0]
    assert match["path"] == "src/main.py"
    assert match["line"] == 2
    # 片段必须能定位到原文件对应行
    assert workspace.read_file("src/main.py").splitlines()[match["line"] - 1] == match["snippet"]
    assert result.output["digest"] == workspace.digest()
    assert result.output["truncated"] is False
    assert result.output["next_cursor"] is None


def test_search_scope_covers_every_file_inside_without_silent_skips(tmp_path):
    workspace, runtime = _runtime(tmp_path)
    workspace.write_file("src/a.py", "target 出现在甲文件\n")
    workspace.write_file("src/nested/b.py", "target 出现在乙文件 twice target\n")
    workspace.write_file("src/.hidden", "target 藏在隐藏文件\n")
    workspace.write_file("other/c.py", "target 在范围之外\n")
    # 二进制文件同样参与匹配，作用域内不静默跳过
    (workspace.root / "src" / "binary.bin").write_bytes(b"\x00\xfftarget\xfe\x80\n")
    result = runtime.execute("engineering", "search", {"pattern": "target", "path": "src"})
    assert result.ok, result.error
    paths = [match["path"] for match in result.output["matches"]]
    assert "src/a.py" in paths
    assert "src/nested/b.py" in paths
    assert "src/.hidden" in paths
    assert "src/binary.bin" in paths
    assert "other/c.py" not in paths
    # 作用域内每个命中行都上报，不静默跳过
    assert result.output["total_matches"] == 4
    scoped_file = runtime.execute("engineering", "search", {"pattern": "target", "path": "src/nested/b.py"})
    assert scoped_file.ok, scoped_file.error
    assert [match["path"] for match in scoped_file.output["matches"]] == ["src/nested/b.py"]


def test_search_truncation_cursor_returns_every_match_exactly_once(tmp_path):
    workspace, runtime = _runtime(tmp_path)
    workspace.write_file("log.txt", "".join(f"第{i}行 needle\n" for i in range(1, 121)))
    first = runtime.execute("engineering", "search", {"pattern": "needle", "max_results": 10})
    assert first.ok, first.error
    assert first.output["truncated"] is True
    assert first.output["next_cursor"]
    seen = list(first.output["matches"])
    cursor = first.output["next_cursor"]
    while True:
        result = runtime.execute("engineering", "search", {
            "pattern": "needle", "max_results": 10, "cursor": cursor,
        })
        assert result.ok, result.error
        assert result.output["digest"] == first.output["digest"]
        seen.extend(result.output["matches"])
        if not result.output["truncated"]:
            assert result.output["next_cursor"] is None
            break
        cursor = result.output["next_cursor"]
    assert [(match["path"], match["line"]) for match in seen] == [("log.txt", i) for i in range(1, 121)]
    assert first.output["total_matches"] == 120


def test_read_range_full_middle_and_beyond_eof(tmp_path):
    workspace, runtime = _runtime(tmp_path)
    workspace.write_file("doc.txt", "".join(f"行{i}\n" for i in range(1, 11)))
    full = runtime.execute("engineering", "read_range", {"path": "doc.txt", "start_line": 1})
    assert full.ok, full.error
    assert full.output["total_lines"] == 10
    assert [(entry["line"], entry["text"]) for entry in full.output["lines"]] == [(i, f"行{i}") for i in range(1, 11)]
    assert full.output["start_line"] == 1 and full.output["end_line"] == 10
    assert full.output["truncated"] is False
    middle = runtime.execute("engineering", "read_range", {"path": "doc.txt", "start_line": 4, "end_line": 6})
    assert middle.ok, middle.error
    assert [(entry["line"], entry["text"]) for entry in middle.output["lines"]] == [(4, "行4"), (5, "行5"), (6, "行6")]
    assert middle.output["start_line"] == 4 and middle.output["end_line"] == 6
    beyond = runtime.execute("engineering", "read_range", {"path": "doc.txt", "start_line": 50})
    assert beyond.ok, beyond.error
    assert beyond.output["lines"] == []
    assert beyond.output["total_lines"] == 10
    assert beyond.output["truncated"] is False


def test_read_range_truncation_cursor_returns_every_line_exactly_once(tmp_path):
    workspace, runtime = _runtime(tmp_path)
    workspace.write_file("big.txt", "".join(f"内容行{i:03d}-" + "x" * 120 + "\n" for i in range(1, 201)))
    first = runtime.execute("engineering", "read_range", {"path": "big.txt", "start_line": 1})
    assert first.ok, first.error
    assert first.output["truncated"] is True
    assert first.output["next_cursor"]
    assert first.output["total_lines"] == 200
    seen = list(first.output["lines"])
    cursor = first.output["next_cursor"]
    while True:
        result = runtime.execute("engineering", "read_range", {
            "path": "big.txt", "start_line": 1, "cursor": cursor,
        })
        assert result.ok, result.error
        assert result.output["digest"] == first.output["digest"]
        assert result.output["total_lines"] == 200
        seen.extend(result.output["lines"])
        if not result.output["truncated"]:
            assert result.output["next_cursor"] is None
            break
        cursor = result.output["next_cursor"]
    assert [entry["line"] for entry in seen] == list(range(1, 201))
    assert len({entry["line"] for entry in seen}) == 200


@pytest.mark.parametrize("rel", [
    ".checks/receipts.jsonl",
    ".git/HEAD",
    "../outside.txt",
    "name.",
    "bad?name",
])
def test_unsafe_paths_raise_verifiable_errors(tmp_path, rel):
    workspace, runtime = _runtime(tmp_path)
    workspace.write_file("ok.txt", "needle\n")
    (workspace.root / ".checks" / "notes.txt").write_text("needle 私有回执\n", encoding="utf-8")
    git_dir = workspace.root / ".git"
    git_dir.mkdir(exist_ok=True)
    (git_dir / "HEAD").write_text("needle 版本元数据\n", encoding="utf-8")
    for tool, args in (
        ("read_range", {"path": rel, "start_line": 1}),
        ("search", {"pattern": "needle", "path": rel}),
    ):
        result = runtime.execute("engineering", tool, args)
        assert result.ok is False
        assert result.error


def test_search_never_exposes_private_tree_content(tmp_path):
    workspace, runtime = _runtime(tmp_path)
    (workspace.root / ".checks" / "notes.txt").write_text("s3cr3t 私有回执\n", encoding="utf-8")
    result = runtime.execute("engineering", "search", {"pattern": "s3cr3t"})
    assert result.ok, result.error
    assert result.output["matches"] == []
    assert result.output["total_matches"] == 0


def test_symlink_paths_raise_verifiable_errors(tmp_path):
    workspace, runtime = _runtime(tmp_path)
    workspace.write_file("real.txt", "needle 真实文件\n")
    outside = tmp_path / "outside.txt"
    outside.write_text("needle 外部文件\n", encoding="utf-8")
    try:
        os.symlink(outside, workspace.root / "linked.txt")
    except OSError:
        pytest.skip("symbolic links are unavailable")
    result = runtime.execute("engineering", "read_range", {"path": "linked.txt", "start_line": 1})
    assert result.ok is False
    assert result.error


def test_repeated_search_is_stable_and_change_reports_new_digest(tmp_path):
    workspace, runtime = _runtime(tmp_path)
    workspace.write_file("app.py", "version one needle\n")
    runtime = ToolRuntime(workspace)
    first = runtime.execute("engineering", "search", {"pattern": "needle"})
    second = runtime.execute("engineering", "search", {"pattern": "needle"})
    assert first.ok and second.ok
    assert first.output == second.output
    old_digest = first.output["digest"]
    assert old_digest == workspace.digest()
    workspace.write_file("app.py", "version two needle needle\n")
    third = runtime.execute("engineering", "search", {"pattern": "needle"})
    assert third.ok, third.error
    assert third.output["digest"] == workspace.digest()
    assert third.output["digest"] != old_digest
    assert third.output["matches"] != first.output["matches"]
    assert all(match["snippet"] == "version two needle needle" for match in third.output["matches"])
