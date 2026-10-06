"""场景 2 评分器的单元层测试。

用真实 pytest 跑一个临时生成的小仓库：把 junit 输出、失败分类与聚合这三段逻辑放到
真实的运行结果上核对，不用手写的假 junit 代替真实输出。
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

EVALS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORER_DIR = os.path.join(EVALS_DIR, "scorer")
CHECKS_DIR = os.path.join(EVALS_DIR, "scenarios", "scenario-2", "checks")
for path in (SCORER_DIR, CHECKS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

import pytest_checks
import scenario2

PACKAGE = """\
def add(left, right):
    return left + right


def divide(left, right):
    return left / right
"""

# 一条通过、一条因为入口不存在而失败、一条结果不对，覆盖三种状态
BROKEN_TESTS = """\
from sample import add, divide


def test_add():
    assert add(1, 2) == 3


def test_missing_entry():
    assert missing_entry() == 1


def test_divide():
    assert divide(6, 3) == 3
"""

# 求商的结果改成 2：模型改对以后这条通过
FIXED_TESTS = """\
from sample import add, divide


def test_add():
    assert add(1, 2) == 3


def test_missing_entry():
    assert missing_entry() == 1


def test_divide():
    assert divide(6, 3) == 2
"""

EXISTING_TESTS = """\
from sample import add


def test_add_again():
    assert add(2, 2) == 4


def test_add_negative():
    assert add(-1, 1) == 0
"""

TABLE = {
    "requirements": [
        {"id": "R1", "title": "求和",
         "checks": ["tests/test_new.py::test_add", "tests/test_new.py::test_missing_entry"]},
        {"id": "R2", "title": "求商", "checks": ["tests/test_new.py::test_divide"]},
    ]
}

F2P = ["tests/test_new.py::test_add", "tests/test_new.py::test_missing_entry",
       "tests/test_new.py::test_divide"]
P2P = ["tests/test_existing.py::test_add_again",
       "tests/test_existing.py::test_add_negative"]


def write_tests(root, name, text):
    with open(os.path.join(root, "tests", name), "w", encoding="utf-8") as handle:
        handle.write(text)


PYPROJECT = """\
[project]
name = "sample"
version = "0.1.0"
requires-python = ">=3.13"

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["sample.py"]
"""


def write_delivery(root, new_tests=BROKEN_TESTS):
    """生成一份可交付的小仓库：源文件、原有功能测试，以及可选的新功能测试。

    new_tests 为 None 时不写新功能测试文件，它由测试补丁加进来——与场景 2 的材料一样，
    F2P 的测试文件只有测试补丁里有。
    """
    tests_dir = os.path.join(root, "tests")
    os.makedirs(tests_dir)
    with open(os.path.join(root, "sample.py"), "w", encoding="utf-8") as handle:
        handle.write(PACKAGE)
    # 空包文件：pytest 才能从目录导入测试模块，用 tests.文件名::类.方法 的写法选中
    with open(os.path.join(tests_dir, "__init__.py"), "w", encoding="utf-8") as handle:
        handle.write("")
    write_tests(root, "test_existing.py", EXISTING_TESTS)
    if new_tests is not None:
        write_tests(root, "test_new.py", new_tests)
    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True,
                   capture_output=True)
    return root


@pytest.fixture(scope="module")
def environment_template(tmp_path_factory):
    """建好环境的 uv 项目：每个用例复制一份，省掉重复建立依赖的时间。"""
    root = str(tmp_path_factory.mktemp("env"))
    with open(os.path.join(root, "pyproject.toml"), "w", encoding="utf-8") as handle:
        handle.write(PYPROJECT)
    synced = subprocess.run(["uv", "sync", "--python", "3.13"], cwd=root,
                            capture_output=True, encoding="utf-8", errors="replace")
    if synced.returncode != 0:
        raise AssertionError("uv sync failed: " + synced.stderr)
    return root


def uv_delivery(root, template, new_tests=BROKEN_TESTS):
    """复制一份建好环境的项目，放进交付内容。"""
    os.makedirs(root)
    for name in os.listdir(template):
        source = os.path.join(template, name)
        target = os.path.join(root, name)
        if os.path.isdir(source):
            shutil.copytree(source, target, symlinks=True)
        else:
            shutil.copy2(source, target)
    return write_delivery(root, new_tests)


def write_scoring(root, f2p, p2p, new_tests=BROKEN_TESTS):
    """建立评分目录：清单、条目表、检查模块与隐藏测试文件，形状与运行器复制出来的相同。"""
    checks = os.path.join(root, "checks")
    os.makedirs(checks)
    for name, tests in (("f2p.json", f2p), ("p2p.json", p2p)):
        with open(os.path.join(checks, name), "w", encoding="utf-8") as handle:
            json.dump({"count": len(tests), "tests": tests}, handle)
    hidden = os.path.join(checks, "tests")
    os.makedirs(hidden)
    with open(os.path.join(hidden, "test_new.py"), "w", encoding="utf-8") as handle:
        handle.write(new_tests)
    shutil.copy(os.path.join(CHECKS_DIR, "pytest_checks.py"),
                os.path.join(checks, "pytest_checks.py"))
    with open(os.path.join(checks, "__init__.py"), "w", encoding="utf-8") as handle:
        handle.write("")
    table_path = os.path.join(root, "requirement-table.json")
    with open(table_path, "w", encoding="utf-8") as handle:
        json.dump(TABLE, handle)
    return checks, table_path


def run_pytest(root, tests, junit_path):
    return subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
                           "-q", "--junit-xml", junit_path] + tests,
                          cwd=root, capture_output=True, encoding="utf-8",
                          errors="replace")


def test_junit_gives_back_registered_identifiers(tmp_path):
    """junit 的 classname 是点分隔的模块名，清单里写的是文件路径。"""
    delivery = write_delivery(str(tmp_path / "delivery"))
    junit = str(tmp_path / "junit.xml")
    tests = ["tests/test_new.py::test_add",
             "tests/test_existing.py::test_add_again"]
    completed = run_pytest(delivery, tests, junit)

    assert completed.returncode == 0, completed.stdout
    cases = scenario2.parse_junit(junit, scenario2.registered_files(tests))
    assert cases == {"tests/test_new.py::test_add": ("pass", ""),
                     "tests/test_existing.py::test_add_again": ("pass", "")}


def test_junit_keeps_the_class_level_of_registered_identifiers(tmp_path):
    """清单里的用例标识可以带测试类，junit 的 classname 也带着这一段。"""
    delivery = write_delivery(str(tmp_path / "delivery"))
    write_tests(delivery, "test_existing.py",
                "from sample import add\n\n\n"
                "class TestCalculator:\n"
                "    def test_add_inside_a_class(self):\n"
                "        assert add(2, 2) == 4\n")
    junit = str(tmp_path / "junit.xml")
    tests = ["tests/test_existing.py::TestCalculator::test_add_inside_a_class"]
    completed = run_pytest(delivery, tests, junit)

    assert completed.returncode == 0, completed.stdout
    cases = scenario2.parse_junit(junit, scenario2.registered_files(tests))
    assert cases == {tests[0]: ("pass", "")}


def test_unregistered_module_in_junit_is_rejected(tmp_path):
    """junit 里出现清单以外的模块，说明清单与交付对不上，直接报错。"""
    delivery = write_delivery(str(tmp_path / "delivery"))
    junit = str(tmp_path / "junit.xml")
    completed = run_pytest(delivery, ["tests/test_new.py::test_add"], junit)

    assert completed.returncode == 0, completed.stdout
    with pytest.raises(ValueError, match="unregistered module"):
        scenario2.parse_junit(junit, ["tests/test_other.py"])


def test_failure_classification_reads_the_real_failure(tmp_path):
    """真实运行的三种状态分别落到通过、没有做、做了但结果不对。"""
    delivery = write_delivery(str(tmp_path / "delivery"))
    junit = str(tmp_path / "junit.xml")
    completed = run_pytest(delivery, F2P, junit)

    assert completed.returncode != 0
    cases = scenario2.parse_junit(junit, scenario2.registered_files(F2P))
    outcomes = {name: scenario2.classify(*cases[name])[0] for name in F2P}
    assert outcomes == {"tests/test_new.py::test_add": "pass",
                        "tests/test_new.py::test_missing_entry": "not_done",
                        "tests/test_new.py::test_divide": "wrong"}


def test_parameterized_cases_fail_if_any_case_fails(tmp_path):
    """参数化的用例：三个参数里有一个不成立，这个函数就算失败。"""
    delivery = write_delivery(str(tmp_path / "delivery"))
    write_tests(delivery, "test_new.py",
                "import pytest\n\n\n"
                "@pytest.mark.parametrize('left', [1, 2, 99])\n"
                "def test_small_left(left):\n    assert left < 10\n")
    junit = str(tmp_path / "junit.xml")
    tests = ["tests/test_new.py::test_small_left"]
    completed = run_pytest(delivery, tests, junit)

    assert completed.returncode != 0
    cases = scenario2.parse_junit(junit, scenario2.registered_files(tests))
    assert cases[tests[0]][0] == "fail"


def test_regression_failures_do_not_move_completion(tmp_path):
    """原有功能测试失败单独报告，完成度只看 F2P（评测场景设计第 4.2 节）。"""
    delivery = write_delivery(str(tmp_path / "delivery"))
    junit = str(tmp_path / "p2p.xml")
    completed = run_pytest(delivery, P2P, junit)

    assert completed.returncode == 0, completed.stdout
    cases = scenario2.parse_junit(junit, scenario2.registered_files(P2P))
    regression = {"passed": 0, "failed": 0, "total": len(P2P), "failures": []}
    for name in P2P:
        status, detail = cases[name]
        if status == "pass":
            regression["passed"] += 1
        else:
            regression["failed"] += 1
            regression["failures"].append({"id": name, "detail": detail})
    assert regression == {"passed": 2, "failed": 0, "total": 2, "failures": []}

    records = [{"id": "tests/test_new.py::test_add", "requirement": "R1",
                "status": "pass", "detail": ""}]
    scores = scenario2.aggregate(records, ["R1", "R2"], regression, {"f2p": 1, "p2p": 0})
    # R2 没有通过任何检查，完成度是 1/2
    assert scores["completion"] == 0.5
    assert scores["correctness"] == 1.0
    assert scores["regression"] == regression


def test_not_done_entries_do_not_count_into_correctness():
    """一条检查都没有做时正确性没有分母，按 0 计。"""
    records = [{"id": "tests/test_new.py::test_add", "requirement": "R1",
                "status": "not_done", "detail": "NameError missing_entry"}]
    regression = {"passed": 0, "failed": 0, "total": 0, "failures": []}
    scores = scenario2.aggregate(records, ["R1"], regression, {"f2p": 1, "p2p": 5})

    assert scores["completion"] == 0.0
    assert scores["correctness"] == 0.0
    assert scores["not_done_count"] == 1
    assert scores["wrong_count"] == 0
    assert scores["requirements"]["R1"] == {"passed": 0, "total": 1, "score": 0.0}


def test_scorer_scores_a_delivery_that_did_not_implement_the_feature(tmp_path,
                                                                    environment_template):
    """交付没有实现新功能：只有不依赖新功能的那条 F2P 通过，完成度是一半。"""
    delivery = uv_delivery(str(tmp_path / "delivery"), environment_template,
                           new_tests=None)
    checks, table_path = write_scoring(str(tmp_path / "scoring"), F2P, P2P)

    scores = scenario2.score(delivery, checks, table_path, str(tmp_path / "work"))

    assert scores["scenario"] == "scenario-2"
    assert scores["material_version"] == "scenario-2@1"
    assert scores["scorer_version"] == "scorer-2@1"
    assert scores["completion"] == 0.25
    assert scores["not_done_count"] == 1
    assert scores["wrong_count"] == 1
    assert scores["requirements"] == {"R1": {"passed": 1, "total": 2, "score": 0.5},
                                       "R2": {"passed": 0, "total": 1, "score": 0.0}}
    # 原有功能没有被动过
    assert scores["regression"] == {"passed": 2, "failed": 0, "total": 2,
                                    "failures": []}
    assert scores["test_exit_codes"] == {"f2p": 1, "p2p": 0}


def test_scorer_scores_a_delivery_that_broke_the_existing_feature(tmp_path,
                                                                  environment_template):
    """交付改坏了原有功能：完成度看 F2P，回归失败条数单独可见。"""
    delivery = uv_delivery(str(tmp_path / "delivery"), environment_template,
                           new_tests=None)
    write_tests(delivery, "test_existing.py",
                "from sample import add\n\n\ndef test_add_again():\n"
                "    assert add(2, 2) == 5\n\n\ndef test_add_negative():\n"
                "    assert add(-1, 1) == 0\n")
    checks, table_path = write_scoring(str(tmp_path / "scoring"), F2P, P2P)

    scores = scenario2.score(delivery, checks, table_path, str(tmp_path / "work"))

    assert scores["completion"] == 0.25
    assert scores["regression"]["failed"] == 1
    assert scores["regression"]["passed"] == 1
    assert [item["id"] for item in scores["regression"]["failures"]] == \
        ["tests/test_existing.py::test_add_again"]
    assert scores["test_exit_codes"] == {"f2p": 1, "p2p": 1}


def test_scorer_scores_a_delivery_that_implemented_the_feature(tmp_path,
                                                               environment_template):
    """交付把新功能实现对了：R1 缺的那个入口仍然没有做，条目得分是一半。"""
    delivery = uv_delivery(str(tmp_path / "delivery"), environment_template,
                           new_tests=None)
    checks, table_path = write_scoring(str(tmp_path / "scoring"), F2P, P2P,
                                       new_tests=FIXED_TESTS)

    scores = scenario2.score(delivery, checks, table_path, str(tmp_path / "work"))

    assert scores["requirements"] == {"R1": {"passed": 1, "total": 2, "score": 0.5},
                                       "R2": {"passed": 1, "total": 1, "score": 1.0}}
    assert scores["completion"] == 0.75
    # 三条都被收集：test_add 与 test_divide 通过，test_missing_entry 抛 NameError 算没有做
    assert scores["correctness"] == 1.0
    assert scores["regression"]["failed"] == 0


def test_scorer_replaces_a_test_the_delivery_edited(tmp_path, environment_template):
    """交付改写了隐藏检查的测试：评分按材料里的版本，不看交付自己写的。"""
    delivery = uv_delivery(str(tmp_path / "delivery"), environment_template,
                           new_tests=None)
    # 被测方把 F2P 的断言改成一个恒成立的写法，并且删掉了要求新功能的用例
    write_tests(delivery, "test_new.py",
                "def test_add():\n    assert True\n")
    checks, table_path = write_scoring(str(tmp_path / "scoring"), F2P, P2P,
                                       new_tests=FIXED_TESTS)

    scores = scenario2.score(delivery, checks, table_path, str(tmp_path / "work"))

    # 材料里的版本仍然要求 missing_entry 存在，这条仍然是没有做
    assert scores["not_done_count"] == 1
    assert scores["requirements"]["R1"] == {"passed": 1, "total": 2, "score": 0.5}
    assert scores["completion"] == 0.75
    with open(os.path.join(delivery, "tests", "test_new.py"), encoding="utf-8") as handle:
        assert handle.read() == FIXED_TESTS


def test_count_in_the_lists_must_match_the_lists(tmp_path):
    """清单里写下的条数与条数对不上就报错，避免材料与用例数脱节。"""
    checks = str(tmp_path / "checks")
    os.makedirs(checks)
    with open(os.path.join(checks, "f2p.json"), "w", encoding="utf-8") as handle:
        json.dump({"count": 2, "tests": ["tests/test_new.py::test_add"]}, handle)

    with pytest.raises(ValueError, match="count does not match"):
        pytest_checks.f2p_tests(checks)