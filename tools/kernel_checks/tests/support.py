# 测试夹具的共用部分（tools/kernel_checks/tests）：在临时目录里建一个真实的 git 仓库，
# 里面有一个很小的内核模块、它的真实测试与内核清单。工具的测试真的运行 poodle、coverage、
# pytest 与 git，不用假的替身。

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE = "harness/example.py"
MANIFEST = "harness/definitions/kernel-manifest.json"
REASONS = "harness/tests/kernel/mutation_reasons.json"


def git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args], cwd=root, capture_output=True, text=True, encoding="utf-8"
    )
    assert done.returncode == 0, f"git {' '.join(args)} 失败：{done.stderr}"
    return done.stdout


def write(root: Path, files: dict[str, str | None]) -> None:
    for name, text in files.items():
        path = root / name
        if text is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")


def manifest(checks: dict | None, path: str = MODULE) -> str:
    entry: dict = {"path": path, "kind": "module", "why": "测试用的内核模块"}
    if checks is not None:
        entry["checks"] = checks
    return (
        json.dumps(
            {"owner": "user", "kinds": {"module": "内核模块", "material": "评价材料"}, "paths": [entry]},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def reasons(items: list[dict]) -> str:
    return json.dumps(items, ensure_ascii=False, indent=2) + "\n"


@dataclass
class Fixture:
    root: Path

    def commit(self, files: dict[str, str | None], message: str = "改动") -> None:
        write(self.root, files)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-m", message)

    def set_origin_main(self, commit: str | None = None) -> None:
        target = commit or git(self.root, "rev-parse", "HEAD").strip()
        git(self.root, "update-ref", "refs/remotes/origin/main", target)

    def run(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
        return self.run_raw("check", *args, env=env)

    def run_raw(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.pathsep.join(filter(None, [environment.get("PYTHONPATH", ""), str(REPO_ROOT)]))
        environment["PYTHONUTF8"] = "1"
        if env is not None:
            environment.update(env)
        return subprocess.run(
            [sys.executable, "-m", "tools.kernel_checks", *args],
            cwd=self.root,
            capture_output=True,
            env=environment,
        )

    def report(self, *args: str, env: dict[str, str] | None = None) -> tuple[subprocess.CompletedProcess[bytes], dict]:
        done = self.run("--report", "report.json", *args, env=env)
        path = self.root / "report.json"
        assert path.is_file(), done.stdout.decode("utf-8", "replace") + done.stderr.decode("utf-8", "replace")
        return done, json.loads(path.read_text(encoding="utf-8"))


def start_repo(
    tmp_path: Path,
    module_source: str,
    test_files: dict[str, str],
    checks: dict | None = None,
    reasons_text: str | None = None,
    extra_files: dict[str, str] | None = None,
) -> Fixture:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "kernel-checks@example.invalid")
    git(root, "config", "user.name", "kernel checks")
    git(root, "config", "core.autocrlf", "false")
    git(root, "config", "commit.gpgsign", "false")
    files: dict[str, str | None] = {
        "harness/__init__.py": "",
        "harness/tests/__init__.py": "",
        MANIFEST: manifest(checks),
        REASONS: reasons_text if reasons_text is not None else "[]\n",
        MODULE: module_source,
    }
    for name, text in test_files.items():
        files[f"harness/tests/kernel/{name}"] = text
    if extra_files:
        files.update(extra_files)
    write(root, files)
    git(root, "add", "-A")
    git(root, "commit", "-m", "起点")
    fixture = Fixture(root=root)
    fixture.set_origin_main()
    return fixture


def cleanup(fixture: Fixture) -> None:
    shutil.rmtree(fixture.root, ignore_errors=True)
