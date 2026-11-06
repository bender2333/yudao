# 理由登记的读取与校验、报告与退出码（tools/kernel_checks/registry.py、report.py 与命令行入口，
# docs/design/kernel-quality-gate.md「4.5 存活的出口与理由登记」「4.7 合并检查」）：
# 空列表读取通过；缺理由或字段不全的项读取时报错并指出是哪一项；报告写成 JSON 文件；
# 退出码：通过 0、不通过 1、工具出错 2（合并基点不存在、清单读不了）。

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

SIMPLE = "def answer(value):\n    if value > 0:\n        return value\n    return 1\n"


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args], cwd=root, capture_output=True, text=True, encoding="utf-8"
    )
    assert done.returncode == 0, f"git {' '.join(args)} 失败：{done.stderr}"
    return done.stdout


def _module(root: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, [environment.get("PYTHONPATH", ""), str(REPO_ROOT)]))
    environment["PYTHONUTF8"] = "1"
    if env is not None:
        environment.update(env)
    return subprocess.run(
        [sys.executable, "-m", "tools.kernel_checks", *args], cwd=root, capture_output=True, env=environment
    )


def _run(root: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    return _module(root, "check", *args, env=env)


def _write(root: Path, files: dict[str, str | None]) -> None:
    for name, text in files.items():
        path = root / name
        if text is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")


def _start_repo(tmp_path: Path, module_source: str = SIMPLE) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "kernel-checks@example.invalid")
    _git(root, "config", "user.name", "kernel checks")
    _git(root, "config", "core.autocrlf", "false")
    _git(root, "config", "commit.gpgsign", "false")
    manifest = {
        "owner": "user",
        "kinds": {"module": "内核模块", "material": "评价材料"},
        "paths": [{"path": MODULE, "kind": "module", "why": "测试用的内核模块", "checks": {"complexity": True}}],
    }
    _write(
        root,
        {
            MANIFEST: json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
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


def _branches(count: int) -> str:
    lines = ["def branches(value):"]
    for index in range(count):
        lines.append(f"    if value == {index}:")
        lines.append(f"        return {index}")
    lines.append("    return -1")
    return "\n".join(lines) + "\n"


def _reason(**overrides: object) -> dict:
    item: dict = {
        "file": MODULE,
        "function": "answer",
        "before": "return 1",
        "after": "return 2",
        "reason": "这两个值在调用处经过同一化，行为不变",
        "registered_by": "solo-deepseek-v4.1-flash",
        "registered_at": "2026-11-07T02:00:00+08:00",
    }
    item.update(overrides)
    for name, value in overrides.items():
        if value is None:
            item.pop(name, None)
    return item


def _registry(items: list[dict]) -> str:
    return json.dumps(items, ensure_ascii=False, indent=2) + "\n"


def test_an_empty_reason_registry_passes(tmp_path):
    root = _start_repo(tmp_path)
    _commit(root, {MODULE: SIMPLE.replace("return 1", "return 2")})
    done = _run(root, "--report", "report.json")
    assert done.returncode == 0, done.stdout.decode("utf-8")
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    assert report["reasons"] == {"path": REASONS, "count": 0, "problems": []}


def test_a_reason_without_the_reason_field_names_the_item(tmp_path):
    root = _start_repo(tmp_path)
    _commit(root, {REASONS: _registry([_reason(reason=None)])})
    done = _run(root, "--report", "report.json")
    assert done.returncode == 1
    text = done.stdout.decode("utf-8")
    assert "第 1 项" in text and "reason" in text
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    assert report["verdict"] == "fail"
    assert any("第 1 项" in problem and "reason" in problem for problem in report["reasons"]["problems"])


def test_a_reason_missing_another_field_names_the_item(tmp_path):
    root = _start_repo(tmp_path)
    _commit(root, {REASONS: _registry([_reason(registered_by=None)])})
    done = _run(root)
    assert done.returncode == 1
    text = done.stdout.decode("utf-8")
    assert "第 1 项" in text and "registered_by" in text


def test_a_blank_reason_is_rejected(tmp_path):
    root = _start_repo(tmp_path)
    _commit(root, {REASONS: _registry([_reason(reason="   ")])})
    done = _run(root)
    assert done.returncode == 1
    assert "第 1 项" in done.stdout.decode("utf-8")


def test_a_complete_reason_is_accepted(tmp_path):
    root = _start_repo(tmp_path)
    _commit(root, {REASONS: _registry([_reason()])})
    done = _run(root, "--report", "report.json")
    assert done.returncode == 0, done.stdout.decode("utf-8")
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    assert report["reasons"]["count"] == 1
    assert report["reasons"]["problems"] == []


def test_exit_code_one_for_a_failing_change(tmp_path):
    root = _start_repo(tmp_path, _branches(9))
    _commit(root, {MODULE: _branches(10)})
    assert _run(root).returncode == 1


def test_exit_code_two_when_the_merge_base_does_not_exist(tmp_path):
    root = _start_repo(tmp_path)
    done = _run(root, "--base", "origin/does-not-exist")
    assert done.returncode == 2
    text = done.stdout.decode("utf-8")
    assert "工具出错" in text and "合并基点不存在" in text


def test_exit_code_two_when_the_manifest_is_unreadable(tmp_path):
    root = _start_repo(tmp_path)
    _write(root, {MANIFEST: "{ 这不是 JSON\n"})
    done = _run(root)
    assert done.returncode == 2
    text = done.stdout.decode("utf-8")
    assert "工具出错" in text and "内核清单" in text


def test_the_report_file_is_written_and_its_directory_created(tmp_path):
    root = _start_repo(tmp_path)
    _commit(root, {MODULE: SIMPLE.replace("return 1", "return 2")})
    done = _run(root, "--report", ".tmp/kernel-checks/report.json")
    assert done.returncode == 0, done.stdout.decode("utf-8")
    written = root / ".tmp" / "kernel-checks" / "report.json"
    assert written.is_file()
    report = json.loads(written.read_text(encoding="utf-8"))
    assert report["verdict"] == "pass"
    assert report["tool"] == "tools.kernel_checks"


def test_the_default_base_is_origin_main(tmp_path):
    root = _start_repo(tmp_path)
    base = _git(root, "rev-parse", "refs/remotes/origin/main").strip()
    _commit(root, {MODULE: SIMPLE.replace("return 1", "return 2")})
    done = _run(root, "--report", "report.json")
    assert done.returncode == 0, done.stdout.decode("utf-8")
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    assert report["base"] == "origin/main"
    assert report["merge_base"] == base
    assert [item["function"] for item in report["functions"]] == ["answer"]


def test_base_option_chooses_another_merge_base(tmp_path):
    root = _start_repo(tmp_path)
    _commit(root, {MODULE: SIMPLE.replace("return 1", "return 2")})
    start = _git(root, "rev-parse", "HEAD").strip()
    _git(root, "update-ref", "refs/heads/start", start)
    done = _run(root, "--base", "start", "--report", "report.json")
    assert done.returncode == 0, done.stdout.decode("utf-8")
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    assert report["merge_base"] == start
    assert report["files"] == []


def test_help_lists_the_written_options(tmp_path):
    root = _start_repo(tmp_path)
    done = _module(root, "--help")
    assert done.returncode == 0
    text = done.stdout.decode("utf-8")
    assert "uv run python -m tools.kernel_checks check" in text
    for option in ("--base", "--report", "--ignore-switches"):
        assert option in text


def test_stdout_is_utf8_when_the_console_encoding_cannot_write_chinese(tmp_path):
    root = _start_repo(tmp_path)
    _commit(root, {MODULE: SIMPLE.replace("return 1", "return 2")})
    done = _run(root, env={"PYTHONIOENCODING": "cp437:strict"})
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    text = done.stdout.decode("utf-8")
    assert "结论：通过" in text
