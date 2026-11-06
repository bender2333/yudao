# 复杂度检查与开关（tools/kernel_checks/complexity.py 与清单里的 checks，
# docs/design/kernel-quality-gate.md「4.1 接入：按模块，两个开关」「4.3 复杂度检查」）：
# 改到的函数圈复杂度超过 10 时不通过并写出函数与数值，恰为 10 时通过；没有改到的超限函数不报；
# 清单里没写开关的模块不检查，用 --ignore-switches 时才检查。

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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
            MANIFEST: json.dumps(
                {"owner": "user", "kinds": {"module": "内核模块", "material": "评价材料"}, "paths": [entry]},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
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


def _branches(count: int, name: str = "branches") -> str:
    # 圈复杂度 = 1 + 分支数：count 个 if 时是 count + 1
    lines = [f"def {name}(value):"]
    for index in range(count):
        lines.append(f"    if value == {index}:")
        lines.append(f"        return {index}")
    lines.append("    return -1")
    return "\n".join(lines) + "\n"


def test_a_changed_function_over_the_limit_fails_with_its_number(tmp_path):
    root = _start_repo(tmp_path, _branches(9), {"complexity": True})
    _commit(root, {MODULE: _branches(10)})
    done = _run(root, "--report", "report.json")
    assert done.returncode == 1
    text = done.stdout.decode("utf-8")
    assert "不通过" in text and "branches" in text and "11" in text
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    assert report["verdict"] == "fail"
    assert report["violations"] == [{"module": MODULE, "function": "branches", "complexity": 11, "limit": 10}]


def test_a_changed_function_at_exactly_the_limit_passes(tmp_path):
    source = _branches(9)
    root = _start_repo(tmp_path, source, {"complexity": True})
    _commit(root, {MODULE: source.replace("return -1", "return -2")})
    done = _run(root, "--report", "report.json")
    assert done.returncode == 0, done.stdout.decode("utf-8")
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    assert report["verdict"] == "pass"
    assert report["violations"] == []
    assert [item["complexity"] for item in report["functions"]] == [10]


def test_an_unchanged_function_over_the_limit_is_not_reported(tmp_path):
    over = _branches(12, name="big")
    module = over + "\n\ndef small(value):\n    return value\n"
    root = _start_repo(tmp_path, module, {"complexity": True})
    _commit(root, {MODULE: module.replace("return value\n", "return value + 1\n")})
    done = _run(root, "--report", "report.json")
    assert done.returncode == 0, done.stdout.decode("utf-8")
    text = done.stdout.decode("utf-8")
    assert "big" not in text
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    assert report["violations"] == []
    assert [item["function"] for item in report["functions"]] == ["small"]


def test_a_module_without_the_switch_is_skipped_until_ignore_switches(tmp_path):
    root = _start_repo(tmp_path, _branches(9), None)
    _commit(root, {MODULE: _branches(10)})
    done = _run(root, "--report", "report.json")
    assert done.returncode == 0, done.stdout.decode("utf-8")
    text = done.stdout.decode("utf-8")
    assert "没检查的内核模块" in text and MODULE in text
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    assert report["checked_modules"] == []
    assert report["violations"] == []
    done = _run(root, "--ignore-switches", "--report", "report-all.json")
    assert done.returncode == 1, done.stdout.decode("utf-8")
    report = json.loads((root / "report-all.json").read_text(encoding="utf-8"))
    assert report["mode"] == "ignore-switches"
    assert report["violations"] == [{"module": MODULE, "function": "branches", "complexity": 11, "limit": 10}]


def test_a_module_with_complexity_switch_off_is_skipped_like_no_switch(tmp_path):
    root = _start_repo(tmp_path, _branches(9), {"complexity": False, "mutation": False})
    _commit(root, {MODULE: _branches(10)})
    done = _run(root, "--report", "report.json")
    assert done.returncode == 0, done.stdout.decode("utf-8")
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    assert report["checked_modules"] == []
    assert "没检查的内核模块" in done.stdout.decode("utf-8")
