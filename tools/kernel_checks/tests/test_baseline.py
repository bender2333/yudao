# 基线运行（tools/kernel_checks/baseline.py，docs/design/kernel-quality-gate.md「变异检查」）：
# 在没有变异的副本里跑内核目录的全部测试，记下每个测试文件的耗时与它执行到的模块；副本取自
# 当前提交，工作区里的改动不算；基线本身失败算工具出错（退出码 2），poodle 起不来也一样。
#
# 用真实 git 仓库、真实 pytest、真实 coverage，不用假的替身。

from __future__ import annotations

import os
import subprocess
import sys

from tools.kernel_checks import baseline

import support

MODULE = "def answer(value):\n    return value * 2\n"
TEST = "from harness.example import answer\n\n\ndef test_answer():\n    assert answer(3) == 6\n"


def test_the_baseline_records_each_test_file_and_the_modules_it_executes(tmp_path):
    fixture = support.start_repo(
        tmp_path,
        MODULE,
        {
            "test_one.py": TEST,
            "test_two.py": "def test_other():\n    assert 1 + 1 == 2\n",
        },
        checks={"complexity": True, "mutation": True},
    )
    try:
        result = baseline.run(fixture.root)
        try:
            assert [item.test_file for item in result.test_files] == [
                "harness/tests/kernel/test_one.py",
                "harness/tests/kernel/test_two.py",
            ]
            one, two = result.test_files
            assert "harness/example.py" in one.covered_modules
            assert "harness/example.py" not in two.covered_modules
            assert 2 in result.executed_lines("harness/example.py")
            assert result.seconds > 0
            assert result.work_dir.is_dir()
        finally:
            baseline.cleanup(result.work_dir)
        assert not result.work_dir.exists()
    finally:
        support.cleanup(fixture)


def test_the_copy_comes_from_the_commit_not_the_working_tree(tmp_path):
    changed = MODULE.replace("* 2", "* 3")
    fixture = support.start_repo(tmp_path, changed, {"test_answer.py": TEST}, checks={"complexity": True, "mutation": True})
    try:
        fixture.commit({"harness/example.py": MODULE})
        # 工作区里把测试改坏，但不提交：基线取的是当前提交里的测试，应当仍然通过
        support.write(fixture.root, {"harness/tests/kernel/test_answer.py": "def test_bad():\n    assert False\n"})
        done, report = fixture.report("--mutation-slow-seconds", "30")
        assert done.returncode == 0, done.stdout.decode("utf-8", "replace")
        assert report["verdict"] == "pass"
    finally:
        support.cleanup(fixture)


def test_a_failing_baseline_is_a_tool_error(tmp_path):
    fixture = support.start_repo(
        tmp_path,
        MODULE,
        {"test_answer.py": "def test_bad():\n    assert False\n"},
        checks={"complexity": True, "mutation": True},
    )
    try:
        fixture.commit({"harness/example.py": MODULE.replace("* 2", "* 3")})
        done, report = fixture.report()
        assert done.returncode == 2
        text = done.stdout.decode("utf-8", "replace")
        assert "工具出错" in text and "基线运行失败" in text
        assert report["verdict"] == "error"
    finally:
        support.cleanup(fixture)


def test_poodle_missing_is_a_tool_error(tmp_path):
    fixture = support.start_repo(tmp_path, MODULE, {"test_answer.py": TEST}, checks={"complexity": True, "mutation": True})
    try:
        fixture.commit(
            {"harness/example.py": "def answer(value):\n    label = \"x\"\n    return value * 2\n"}
        )
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(support.REPO_ROOT)
        environment["PYTHONUTF8"] = "1"
        code = (
            "import sys\n"
            "sys.modules['poodle'] = None\n"
            "from tools.kernel_checks.__main__ import main\n"
            "raise SystemExit(main(['check']))\n"
        )
        done = subprocess.run(
            [sys.executable, "-c", code], cwd=fixture.root, capture_output=True, env=environment
        )
        assert done.returncode == 2
        text = done.stdout.decode("utf-8", "replace")
        assert "工具出错" in text and "poodle 起不来" in text
    finally:
        support.cleanup(fixture)
