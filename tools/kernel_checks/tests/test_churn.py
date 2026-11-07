# 近两周改动（tools/kernel_checks/churn.py、报告与文字输出，docs/design/kernel-quality-gate.md
# 「接口」「方案」4.1）：在真实 git 仓库的夹具里，用 GIT_COMMITTER_DATE 造出窗口内与窗口外的提交；
# 窗口内的新增与删除计入，窗口外的不计；比值是合计除以模块在当前提交上的物理行数，百分数保留一位
# 小数；没有改动的内核模块写 0.0%，仍有一行；取不到 git 记录（没有提交过、浅克隆里历史不够）的模块
# 比值留空并写明原因，退出码不变、不算工具出错。这一项只是读数：默认模式与 --ignore-switches 都写，
# 不进结论、不改退出码。

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = "harness/definitions/kernel-manifest.json"
REASONS = "harness/tests/kernel/mutation_reasons.json"


def _git(root: Path, *args: str, env: dict[str, str] | None = None) -> str:
    environment = dict(os.environ)
    if env is not None:
        environment.update(env)
    done = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
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
            path.write_text(text, encoding="utf-8", newline="\n")


def _manifest(paths: list[str]) -> str:
    entries = [{"path": path, "kind": "module", "why": "测试用的内核模块"} for path in paths]
    return (
        json.dumps(
            {"owner": "user", "kinds": {"module": "内核模块", "material": "评价材料"}, "paths": entries},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def _dated(days_ago: int) -> dict[str, str]:
    # 造出窗口内与窗口外的提交：作者时间与提交时间都用这个日期
    stamp = (datetime.now().astimezone() - timedelta(days=days_ago)).isoformat(timespec="seconds")
    return {"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}


def _commit(root: Path, files: dict[str, str | None], days_ago: int) -> None:
    _write(root, files)
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "改动", env=_dated(days_ago))


def _start_repo(tmp_path: Path, modules: dict[str, str], listed: list[str]) -> Path:
    # 起点提交在 30 天以前（窗口外），origin/main 指向它
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "kernel-checks@example.invalid")
    _git(root, "config", "user.name", "kernel checks")
    _git(root, "config", "core.autocrlf", "false")
    _git(root, "config", "commit.gpgsign", "false")
    files: dict[str, str | None] = {MANIFEST: _manifest(listed), REASONS: "[]\n"}
    files.update(modules)
    _commit(root, files, 30)
    _git(root, "update-ref", "refs/remotes/origin/main", _git(root, "rev-parse", "HEAD").strip())
    return root


def _modules(report: dict) -> dict[str, dict]:
    return {item["module"]: item for item in report["churn"]["modules"]}


GROWN_BASE = "def grown(value):\n    return value\n"
GROWN_HEAD = "def grown(value):\n    return value\n\n\ndef other():\n    return 1\n"
SHRUNK_BASE = "def shrunk(value):\n    if value:\n        return value\n    return None\n"
SHRUNK_HEAD = "def shrunk(value):\n    return None\n"
QUIET_HEAD = "def quiet():\n    return 1\n"
GROWN = "harness/grown.py"
SHRUNK = "harness/shrunk.py"
QUIET = "harness/quiet.py"
MISSING = "harness/missing.py"


def _three_modules(tmp_path: Path) -> Path:
    # grown 在窗口内加了 4 行；shrunk 在窗口内删了 2 行；quiet 的改动在 20 天前（窗口外）
    root = _start_repo(tmp_path, {GROWN: GROWN_BASE, SHRUNK: SHRUNK_BASE, QUIET: QUIET_HEAD}, [GROWN, SHRUNK, QUIET])
    _commit(root, {QUIET: QUIET_HEAD.replace("return 1", "return 2")}, 20)
    _commit(root, {GROWN: GROWN_HEAD, SHRUNK: SHRUNK_HEAD}, 2)
    return root


def test_commits_inside_the_window_count_and_ones_outside_do_not(tmp_path):
    root = _three_modules(tmp_path)
    done = _run(root, "--report", "report.json")
    assert done.returncode == 0, done.stdout.decode("utf-8")
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    assert report["churn"]["window_days"] == 14
    modules = _modules(report)
    assert modules[GROWN] == {
        "module": GROWN,
        "added": 4,
        "deleted": 0,
        "total": 4,
        "lines": 6,
        "ratio": 66.7,
        "why": None,
    }
    assert modules[SHRUNK]["added"] == 0 and modules[SHRUNK]["deleted"] == 2
    assert modules[SHRUNK]["total"] == 2 and modules[SHRUNK]["lines"] == 2
    assert modules[SHRUNK]["ratio"] == 100.0
    # 20 天前的改动在窗口外，这个模块没有改动：比值 0.0%，仍有一行
    assert modules[QUIET]["total"] == 0 and modules[QUIET]["ratio"] == 0.0
    text = done.stdout.decode("utf-8")
    assert "近两周改动：harness/grown.py 4 行（新增 4、删除 0）÷ 6 行 = 66.7%" in text
    assert "近两周改动：harness/shrunk.py 2 行（新增 0、删除 2）÷ 2 行 = 100.0%" in text
    assert "近两周改动：harness/quiet.py 0 行（新增 0、删除 0）÷ 2 行 = 0.0%" in text
    assert "结论：通过" in text


def test_a_module_without_any_commit_shows_an_empty_ratio_and_the_reason(tmp_path):
    root = _start_repo(tmp_path, {GROWN: GROWN_BASE}, [GROWN, MISSING])
    _commit(root, {GROWN: GROWN_HEAD}, 2)
    done = _run(root, "--report", "report.json")
    assert done.returncode == 0, done.stdout.decode("utf-8")
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    modules = _modules(report)
    assert modules[MISSING]["ratio"] is None
    assert modules[MISSING]["why"] and "取不到 git 记录" in modules[MISSING]["why"]
    assert modules[GROWN]["ratio"] == 66.7  # 取不到的模块不影响别的模块的读数
    text = done.stdout.decode("utf-8")
    assert f"近两周改动：{MISSING} 比值留空（{modules[MISSING]['why']}）" in text
    assert "结论：通过" in text


def test_a_shallow_clone_without_the_history_shows_the_reason(tmp_path):
    source = _three_modules(tmp_path)
    root = tmp_path / "shallow"
    _git(tmp_path, "clone", "--depth", "1", source.as_uri(), str(root))
    done = _run(root, "--report", "report.json")
    assert done.returncode == 0, done.stdout.decode("utf-8")
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    quiet = _modules(report)[QUIET]
    assert quiet["ratio"] is None
    assert quiet["why"] and "浅克隆" in quiet["why"]
    assert f"近两周改动：{QUIET} 比值留空（{quiet['why']}）" in done.stdout.decode("utf-8")


def test_both_modes_write_the_readings(tmp_path):
    root = _three_modules(tmp_path)
    default = _run(root, "--report", "default.json")
    assert default.returncode == 0, default.stdout.decode("utf-8")
    ignoring = _run(root, "--ignore-switches", "--report", "ignoring.json")
    assert ignoring.returncode == 0, ignoring.stdout.decode("utf-8")
    for done, name in ((default, "default.json"), (ignoring, "ignoring.json")):
        report = json.loads((root / name).read_text(encoding="utf-8"))
        assert [item["module"] for item in report["churn"]["modules"]] == [GROWN, SHRUNK, QUIET]
        assert "近两周改动：harness/quiet.py 0 行（新增 0、删除 0）÷ 2 行 = 0.0%" in done.stdout.decode("utf-8")


def test_a_failing_check_still_fails_with_the_readings(tmp_path):
    # 这一项不进结论：复杂度不通过时退出码仍是 1，读数照常写出来
    wide_base = _branches(9)
    root = _start_repo(tmp_path, {GROWN: wide_base}, [GROWN])
    _commit(root, {GROWN: _branches(10)}, 2)
    done = _run(root, "--ignore-switches", "--report", "report.json")
    assert done.returncode == 1, done.stdout.decode("utf-8")
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    assert report["verdict"] == "fail"
    assert _modules(report)[GROWN]["ratio"] is not None
    text = done.stdout.decode("utf-8")
    assert "近两周改动：harness/grown.py" in text
    assert "结论：不通过" in text


def _branches(count: int, name: str = "branches") -> str:
    lines = [f"def {name}(value):"]
    for index in range(count):
        lines.append(f"    if value == {index}:")
        lines.append(f"        return {index}")
    lines.append("    return -1")
    return "\n".join(lines) + "\n"
