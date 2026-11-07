# 变异检查（tools/kernel_checks/mutation.py，docs/design/kernel-quality-gate.md「变异检查」）：
# 改坏一处并有测试检查它，变异在快层被杀死；没有测试检查的变异存活、报告写出改动前后的文字；
# 只给人看的文字不产生变异；未覆盖的语句不运行变异、直接不通过；只被慢层测试杀死的变异算被杀死，
# 阈值变了结论不变；卡住的变异超时单列、重跑仍超时算被杀死。
#
# 用真实 git 仓库、真实 pytest、真实 coverage 与真实 poodle，不用假的替身。

from __future__ import annotations

from collections import Counter

from tools.kernel_checks import mutation, report

import support

ANSWER = "def answer(value):\n    return value * 2\n"
ANSWER_TEST = "from harness.example import answer\n\n\ndef test_answer():\n    assert answer(3) == 6\n"

BUILD = 'def build(record):\n    record.append("start")\n    return 7\n'
BUILD_TEST = (
    "from harness.example import build\n\n\n"
    "def test_build():\n"
    "    record = []\n"
    "    assert build(record) == 7\n"
    "    assert len(record) == 1\n"
)


def _module(report_data: dict) -> dict:
    modules = report_data["mutation"]["modules"]
    assert len(modules) == 1
    return modules[0]


def test_a_mutation_checked_by_a_test_is_killed_in_the_fast_layer(tmp_path):
    fixture = support.start_repo(
        tmp_path, ANSWER.replace("* 2", "* 3"), {"test_answer.py": ANSWER_TEST}, checks={"complexity": True, "mutation": True}
    )
    try:
        fixture.commit({"harness/example.py": ANSWER})
        done, data = fixture.report("--mutation-slow-seconds", "30")
        assert done.returncode == 0, done.stdout.decode("utf-8", "replace")
        module = _module(data)
        assert module["fast_files"] and module["slow_files"] == []
        assert module["generated"] >= 4
        assert module["killed_by_layer"]["fast"] >= 1
        assert module["survived"] == []
        assert module["passed"] is True
    finally:
        support.cleanup(fixture)


def test_a_mutation_without_a_test_is_reported_with_before_and_after_and_fails(tmp_path):
    fixture = support.start_repo(
        tmp_path, BUILD, {"test_build.py": BUILD_TEST}, checks={"complexity": True, "mutation": True}
    )
    try:
        fixture.commit({"harness/example.py": BUILD.replace('"start"', '"target"')})
        done, data = fixture.report("--mutation-slow-seconds", "30")
        assert done.returncode == 1
        module = _module(data)
        survived = [item for item in module["survived"] if item["mutator"] == "String"]
        assert len(survived) == 1
        assert survived[0]["before"] == 'record.append("target")'
        assert survived[0]["after"] == "record.append('XXtargetXX')"
        assert survived[0]["accepted"] is False
        assert module["passed"] is False
        text = done.stdout.decode("utf-8", "replace")
        assert survived[0]["before"] in text and survived[0]["after"] in text
        assert report.MUTATION_OUTLETS in text
        assert "补一条检查它的测试" in text and "删掉死代码" in text and "在理由登记里写明理由" in text
    finally:
        support.cleanup(fixture)


def test_human_facing_text_does_not_produce_mutations():
    source = (
        "import logging\n"
        "\n"
        "logger = logging.getLogger(__name__)\n"
        "\n"
        "\n"
        "def run(value):\n"
        '    """说明文字。"""\n'
        '    label = "action"\n'
        "    if value < 0:\n"
        '        logger.warning("值为负数")\n'
        '        raise ValueError("值是负数")\n'
        "    return label\n"
    )
    mutants = mutation.generate(source)
    assert not any("XX说明文字XX" in item.after for item in mutants)
    assert not any("XX值为负数XX" in item.after for item in mutants)
    assert not any("XX值是负数XX" in item.after for item in mutants)
    strings = [item for item in mutants if item.mutator == "String"]
    assert any("XXactionXX" in item.after for item in strings)
    assert Counter(item.mutator for item in mutants)["Delete"] >= 1


def test_an_uncovered_changed_statement_is_reported_without_running_mutations(tmp_path):
    module = "def used():\n    return 1\n\n\ndef unused():\n    return 2\n"
    fixture = support.start_repo(
        tmp_path, module, {"test_used.py": "from harness.example import used\n\n\ndef test_used():\n    assert used() == 1\n"}, checks={"complexity": True, "mutation": True}
    )
    try:
        fixture.commit({"harness/example.py": module.replace("return 2", "return 3")})
        done, data = fixture.report("--mutation-slow-seconds", "30")
        assert done.returncode == 1
        module_data = _module(data)
        assert module_data["generated"] == 0
        assert module_data["uncovered"] == [{"function": "unused", "lineno": 6, "text": "return 3"}]
        assert module_data["passed"] is False
        assert "未覆盖的语句" in done.stdout.decode("utf-8", "replace")
    finally:
        support.cleanup(fixture)


def test_a_mutation_killed_only_in_the_slow_layer_and_the_threshold_keeps_the_verdict(tmp_path):
    fixture = support.start_repo(
        tmp_path,
        ANSWER.replace("* 2", "* 3"),
        {
            "test_fast.py": "from harness.example import answer\n\n\ndef test_zero():\n    assert answer(0) == 0\n",
            "test_slow.py": (
                "import time\n\nfrom harness.example import answer\n\n\n"
                "def test_positive():\n    time.sleep(10)\n    assert answer(3) == 6\n"
            ),
        },
        checks={"complexity": True, "mutation": True},
    )
    try:
        fixture.commit({"harness/example.py": ANSWER})
        slow_done, slow_data = fixture.report("--mutation-slow-seconds", "8")
        assert slow_done.returncode == 0, slow_done.stdout.decode("utf-8", "replace")
        slow_module = _module(slow_data)
        assert len(slow_module["slow_files"]) == 1
        assert slow_module["killed_by_layer"]["slow"] >= 1

        fast_done, fast_data = fixture.report("--mutation-slow-seconds", "30")
        assert fast_done.returncode == 0, fast_done.stdout.decode("utf-8", "replace")
        fast_module = _module(fast_data)
        assert fast_module["slow_files"] == []
        assert fast_module["killed_by_layer"]["slow"] == 0
        assert fast_module["killed_by_layer"]["fast"] >= 1
        assert fast_module["passed"] is True and slow_module["passed"] is True
    finally:
        support.cleanup(fixture)


def test_a_hanging_mutation_times_out_is_listed_and_a_repeated_timeout_is_killed(tmp_path):
    module = (
        "def first_negative(values):\n"
        "    index = 0\n"
        "    while True:\n"
        "        if values[index] < 0:\n"
        "            return index\n"
        "        index += 1\n"
    )
    changed = (
        "def first_negative(values):\n"
        "    index = 0\n"
        "    while True:\n"
        "        if values[index] < 0:\n"
        "            break\n"
        "        index += 1\n"
        "    return index\n"
    )
    fixture = support.start_repo(
        tmp_path,
        module,
        {
            "test_negative.py": (
                "from harness.example import first_negative\n\n\n"
                "def test_negative():\n    assert first_negative([0, 1, 2, -1]) == 3\n"
            )
        },
        checks={"complexity": True, "mutation": True},
    )
    try:
        fixture.commit({"harness/example.py": changed})
        done, data = fixture.report("--mutation-slow-seconds", "30")
        assert done.returncode == 0, done.stdout.decode("utf-8", "replace")
        module_data = _module(data)
        assert len(module_data["timeouts"]) >= 1
        assert any(
            item["function"] == "first_negative"
            and item["first_layer"] == "fast"
            and item["second_outcome"] == "timeout"
            for item in module_data["timeouts"]
        )
        assert module_data["survived"] == []
        assert module_data["passed"] is True
        assert "超时的变异" in done.stdout.decode("utf-8", "replace")
    finally:
        support.cleanup(fixture)
