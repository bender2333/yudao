"""Tests for harness.tools (spec §5)."""

import os

from harness.tools import dispatch, safe_path


def test_safe_path_blocks_traversal(tmp_path):
    ws = str(tmp_path)
    # write via a traversal path should be refused
    out = dispatch("write_file", {"path": "../escape.txt", "content": "x"}, ws)
    assert out.startswith("Error")
    assert not os.path.exists(os.path.join(os.path.dirname(ws), "escape.txt"))


def test_safe_path_allows_inside(tmp_path):
    ws = str(tmp_path)
    p = safe_path(ws, "sub/file.txt")
    assert p.startswith(os.path.realpath(ws))


def test_write_then_read_roundtrip(tmp_path):
    ws = str(tmp_path)
    w = dispatch("write_file", {"path": "a.txt", "content": "hello world"}, ws)
    assert "Wrote" in w
    r = dispatch("read_file", {"path": "a.txt"}, ws)
    assert r == "hello world"


def test_write_creates_nested_dirs(tmp_path):
    ws = str(tmp_path)
    dispatch("write_file", {"path": "d1/d2/x.txt", "content": "nested"}, ws)
    assert dispatch("read_file", {"path": "d1/d2/x.txt"}, ws) == "nested"


def test_edit_hit(tmp_path):
    ws = str(tmp_path)
    dispatch("write_file", {"path": "b.txt", "content": "foo bar foo"}, ws)
    out = dispatch("edit_file", {"path": "b.txt", "old": "foo", "new": "baz"}, ws)
    assert "2 replacement" in out
    assert dispatch("read_file", {"path": "b.txt"}, ws) == "baz bar baz"


def test_edit_miss(tmp_path):
    ws = str(tmp_path)
    dispatch("write_file", {"path": "c.txt", "content": "abc"}, ws)
    out = dispatch("edit_file", {"path": "c.txt", "old": "zzz", "new": "y"}, ws)
    assert out.startswith("Error")


def test_read_missing_file(tmp_path):
    ws = str(tmp_path)
    out = dispatch("read_file", {"path": "nope.txt"}, ws)
    assert out.startswith("Error")


def test_bash_blacklist(tmp_path):
    ws = str(tmp_path)
    out = dispatch("bash", {"command": "sudo rm -rf /"}, ws)
    assert "Dangerous command blocked" in out


def test_bash_runs_in_workspace(tmp_path):
    ws = str(tmp_path)
    dispatch("write_file", {"path": "marker.txt", "content": "hi"}, ws)
    out = dispatch("bash", {"command": "python -c \"import os;print(os.path.exists('marker.txt'))\""}, ws)
    assert "True" in out


def test_list_dir(tmp_path):
    ws = str(tmp_path)
    dispatch("write_file", {"path": "one.txt", "content": "1"}, ws)
    out = dispatch("list_dir", {}, ws)
    assert "one.txt" in out


def test_unknown_tool(tmp_path):
    out = dispatch("nonexistent", {}, str(tmp_path))
    assert out.startswith("Error")
    assert "unknown tool" in out


def test_bad_args(tmp_path):
    # missing required 'content'
    out = dispatch("write_file", {"path": "x.txt"}, str(tmp_path))
    assert out.startswith("Error")
