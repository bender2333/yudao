# 改动识别（tools/kernel_checks/changes.py，docs/design/kernel-quality-gate.md「改到的语句与函数」）：
# 在真实 git 仓库的夹具里改一条语句，报出这个函数与这条语句；只改注释、空行或排版时不报；
# 类里的方法按单独的函数报。夹具用真实的 git 与真实文件，工具按相对合并基点的改动读它们。

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tools.kernel_checks import changes

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE = "harness/module_under_test.py"
MANIFEST = "harness/definitions/kernel-manifest.json"
REASONS = "harness/tests/kernel/mutation_reasons.json"


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args], cwd=root, capture_output=True, text=True, encoding="utf-8"
    )
    assert done.returncode == 0, f"git {' '.join(args)} 失败：{done.stderr}"
    return done.stdout


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, [environment.get("PYTHONPATH", ""), str(REPO_ROOT)]))
    environment["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "tools.kernel_checks", "check", *args], cwd=root, capture_output=True, env=environment
    )


def _write(root: Path, files: dict[str, str | None]) -> None:
    for name, text in files.items():
        path = root / name
        if text is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")


def _manifest(entries: list[dict]) -> str:
    return (
        json.dumps({"owner": "user", "kinds": {"module": "内核模块", "material": "评价材料"}, "paths": entries}, ensure_ascii=False, indent=2)
        + "\n"
    )


def _start_repo(tmp_path: Path, module_source: str, checks: dict | None) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "kernel-checks@example.invalid")
    _git(root, "config", "user.name", "kernel checks")
    _git(root, "config", "core.autocrlf", "false")
    _git(root, "config", "commit.gpgsign", "false")
    entry: dict = {"path": MODULE, "kind": "module", "why": "测试用的内核模块"}
    if checks is not None:
        entry["checks"] = checks
    _write(
        root,
        {
            MANIFEST: _manifest([entry]),
            REASONS: "[]\n",
            MODULE: module_source,
        },
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "起点")
    _git(root, "update-ref", "refs/remotes/origin/main", _git(root, "rev-parse", "HEAD").strip())
    return root


def _commit(root: Path, files: dict[str, str | None]) -> None:
    _write(root, files)
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "改动")


def _report(root: Path) -> dict:
    done = _run(root, "--report", "report.json")
    assert done.returncode == 0, done.stdout.decode("utf-8")
    return json.loads((root / "report.json").read_text(encoding="utf-8"))


SIMPLE = "def answer(value):\n    # 老的注释\n\n    if value > 0:\n        return value\n    return 0\n"


def test_a_changed_statement_is_reported_with_its_function(tmp_path):
    root = _start_repo(tmp_path, SIMPLE, {"complexity": True})
    _commit(root, {MODULE: SIMPLE.replace("return 0", "return -1")})
    report = _report(root)
    assert [item["function"] for item in report["functions"]] == ["answer"]
    statements = report["files"][0]["functions"][0]["statements"]
    assert [item["text"] for item in statements] == ["return -1"]


def test_comment_blank_line_and_layout_changes_are_not_reported(tmp_path):
    base = "def answer(value):\n    return value + 1\n"
    root = _start_repo(tmp_path, base, {"complexity": True})
    _commit(root, {MODULE: "# 新的注释\ndef answer(value):\n\n    return (value +\n            1)\n"})
    report = _report(root)
    assert report["files"] == []
    assert report["functions"] == []


CLASS = "class Widget:\n    def first(self):\n        return 1\n\n    def second(self):\n        return 2\n"


def test_class_methods_are_reported_as_their_own_functions(tmp_path):
    root = _start_repo(tmp_path, CLASS, {"complexity": True})
    _commit(root, {MODULE: CLASS.replace("return 2", "return 3")})
    report = _report(root)
    assert [item["function"] for item in report["functions"]] == ["Widget.second"]
    assert "Widget.first" not in [item["function"] for item in report["functions"]]


def test_a_deleted_statement_marks_the_function_without_a_new_statement():
    old = "def answer():\n    value = 1\n    return value\n"
    new = "def answer():\n    return value\n"
    result = changes.detect(old, new)
    assert [function.name for function in result.functions] == ["answer"]
    assert result.functions[0].statements == ()
    assert result.functions[0].removed == 1
    assert result.removed_functions == ()


def test_a_changed_condition_is_reported_as_the_if_statement():
    old = "def answer(value):\n    if value > 0:\n        return value\n    return 0\n"
    new = "def answer(value):\n    if value >= 0:\n        return value\n    return 0\n"
    result = changes.detect(old, new)
    assert [function.name for function in result.functions] == ["answer"]
    assert [item.text.splitlines()[0] for item in result.functions[0].statements] == ["if value >= 0:"]


def test_a_removed_function_is_reported():
    old = "def kept():\n    return 1\n\n\ndef dropped():\n    return 2\n"
    new = "def kept():\n    return 1\n"
    result = changes.detect(old, new)
    assert result.functions == ()
    assert result.removed_functions == ("dropped",)
