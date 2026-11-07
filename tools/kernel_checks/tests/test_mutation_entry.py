# 理由登记与合并检查入口（tools/kernel_checks/registry.py、__main__.py，
# docs/design/kernel-quality-gate.md「存活的出口与理由登记」「全量模式与「立住」」「合并检查」）：
# 等价变异写了有理由的登记项，通过并单列；没有理由的登记项不通过；对不上任何存活变异的登记项
# 算过期、不通过；改动模式不核对没改到的函数里的登记项，全量模式核对全部；变异开关由关变开的
# 那次合并对整个模块跑全量，开关本来就开着、只改了别处的提交走改动模式；没改到开关已打开的模块
# 时不运行变异检查。
#
# 用真实 git 仓库、真实 pytest、真实 coverage 与真实 poodle，不用假的替身。

from __future__ import annotations

from tools.kernel_checks import report

import support

BUILD = 'def build(record):\n    record.append("start")\n    return 7\n'
CHANGED = 'def build(record):\n    record.append("target")\n    return 7\n'
BUILD_TEST = (
    "from harness.example import build\n\n\n"
    "def test_build():\n"
    "    record = []\n"
    "    assert build(record) == 7\n"
    "    assert len(record) == 1\n"
)

ANSWER = "def answer(value):\n    return value * 2\n"
ANSWER_TEST = "from harness.example import answer\n\n\ndef test_answer():\n    assert answer(3) == 6\n"
TWO_FUNCTIONS = ANSWER + "\n\n" + BUILD
TWO_TESTS = (
    "from harness.example import answer, build\n\n\n"
    "def test_answer():\n"
    "    assert answer(3) == 6\n\n\n"
    "def test_build():\n"
    "    record = []\n"
    "    assert build(record) == 7\n"
    "    assert len(record) == 1\n"
)


def _reason(**overrides: object) -> dict:
    item: dict = {
        "file": support.MODULE,
        "function": "build",
        "before": 'record.append("target")',
        "after": "record.append('XXtargetXX')",
        "reason": "这处改动只换了一个没人读的标签，行为不变",
        "registered_by": "solo-deepseek-v4.1-flash",
        "registered_at": "2026-11-07T06:00:00+08:00",
    }
    item.update(overrides)
    for name, value in overrides.items():
        if value is None:
            item.pop(name, None)
    return item


def _module(data: dict) -> dict:
    modules = data["mutation"]["modules"]
    assert len(modules) == 1
    return modules[0]


def _changed_build(tmp_path):
    fixture = support.start_repo(tmp_path, BUILD, {"test_build.py": BUILD_TEST}, checks={"complexity": True, "mutation": True})
    fixture.commit({"harness/example.py": CHANGED})
    return fixture


def test_an_equivalent_mutation_with_a_reason_passes_and_is_listed(tmp_path):
    fixture = _changed_build(tmp_path)
    try:
        done, data = fixture.report("--mutation-slow-seconds", "30")
        assert done.returncode == 1
        assert _module(data)["survived"][0]["accepted"] is False

        support.write(fixture.root, {support.REASONS: support.reasons([_reason()])})
        done, data = fixture.report("--mutation-slow-seconds", "30")
        assert done.returncode == 0, done.stdout.decode("utf-8", "replace")
        module = _module(data)
        assert module["passed"] is True
        assert len(module["matched"]) == 1
        assert module["matched"][0]["function"] == "build"
        assert module["survived"][0]["accepted"] is True
        assert "命中的登记项" in done.stdout.decode("utf-8", "replace")
    finally:
        support.cleanup(fixture)


def test_identical_statements_are_matched_by_occurrence(tmp_path):
    module = (
        "def build(record):\n"
        '    record.append("start")\n'
        '    record.append("start")\n'
        "    return 7\n"
    )
    changed = module.replace('"start"', '"target"')
    test = (
        "from harness.example import build\n\n\n"
        "def test_build():\n"
        "    record = []\n"
        "    assert build(record) == 7\n"
        "    assert len(record) == 2\n"
    )
    fixture = support.start_repo(tmp_path, module, {"test_build.py": test}, checks={"complexity": True, "mutation": True})
    try:
        fixture.commit({"harness/example.py": changed})
        support.write(fixture.root, {support.REASONS: support.reasons([_reason(occurrence=2)])})
        done, data = fixture.report("--mutation-slow-seconds", "30")
        assert done.returncode == 1
        module_data = _module(data)
        assert [item["occurrence"] for item in module_data["survived"]] == [1, 2]
        assert [item["accepted"] for item in module_data["survived"]] == [False, True]

        support.write(
            fixture.root,
            {support.REASONS: support.reasons([_reason(occurrence=1), _reason(occurrence=2)])},
        )
        done, data = fixture.report("--mutation-slow-seconds", "30")
        assert done.returncode == 0, done.stdout.decode("utf-8", "replace")
        module_data = _module(data)
        assert module_data["passed"] is True
        assert len(module_data["matched"]) == 2
    finally:
        support.cleanup(fixture)


def test_a_reason_without_an_explanation_fails(tmp_path):
    fixture = _changed_build(tmp_path)
    try:
        support.write(fixture.root, {support.REASONS: support.reasons([_reason(reason=None)])})
        done, data = fixture.report("--mutation-slow-seconds", "30")
        assert done.returncode == 1
        assert data["reasons"]["problems"]
        assert "第 1 项" in data["reasons"]["problems"][0] and "reason" in data["reasons"]["problems"][0]
        assert data["mutation"]["skipped"] == "理由登记有问题，没有运行变异检查"
    finally:
        support.cleanup(fixture)


def test_a_reason_that_matches_no_surviving_mutation_is_stale_and_fails(tmp_path):
    fixture = _changed_build(tmp_path)
    try:
        stale = _reason(before='record.append("old")', after="record.append('XXoldXX')")
        support.write(fixture.root, {support.REASONS: support.reasons([stale])})
        done, data = fixture.report("--mutation-slow-seconds", "30")
        assert done.returncode == 1
        module = _module(data)
        assert len(module["stale"]) == 1
        assert module["stale"][0]["before"] == 'record.append("old")'
        assert module["passed"] is False
        assert "过期的登记项" in done.stdout.decode("utf-8", "replace")
    finally:
        support.cleanup(fixture)


def test_change_mode_ignores_reasons_in_functions_it_did_not_touch(tmp_path):
    fixture = support.start_repo(
        tmp_path, TWO_FUNCTIONS, {"test_both.py": TWO_TESTS}, checks={"complexity": True, "mutation": True}
    )
    try:
        fixture.commit({"harness/example.py": TWO_FUNCTIONS.replace('"start"', '"target"')})
        untouched = _reason(
            function="answer", before="return value * 2", after="return None", reason="这处登记不该被改动模式核对"
        )
        support.write(
            fixture.root,
            {support.REASONS: support.reasons([_reason(), untouched])},
        )
        done, data = fixture.report("--mutation-slow-seconds", "30")
        assert done.returncode == 0, done.stdout.decode("utf-8", "replace")
        assert _module(data)["stale"] == []

        done, data = fixture.report(
            "--module", support.MODULE, "--mutation-mode", "full", "--mutation-slow-seconds", "30"
        )
        assert done.returncode == 1
        module = _module(data)
        assert any(item["function"] == "answer" for item in module["stale"])
    finally:
        support.cleanup(fixture)


def test_turning_the_switch_on_runs_full_mode_until_a_new_test_covers_the_module(tmp_path):
    module = "def answer(value):\n    return value * 2\n\n\ndef unused():\n    return 5\n"
    fixture = support.start_repo(
        tmp_path,
        module,
        {"test_answer.py": ANSWER_TEST},
        checks={"complexity": True, "mutation": False},
    )
    try:
        fixture.commit(
            {"harness/definitions/kernel-manifest.json": support.manifest({"complexity": True, "mutation": True})}
        )
        done, data = fixture.report("--mutation-slow-seconds", "30")
        assert done.returncode == 1
        module_data = _module(data)
        assert module_data["mode"] == "full"
        assert module_data["uncovered"] == [{"function": "unused", "lineno": 6, "text": "return 5"}]

        fixture.commit(
            {"harness/tests/kernel/test_unused.py": "from harness.example import unused\n\n\ndef test_unused():\n    assert unused() == 5\n"}
        )
        done, data = fixture.report("--mutation-slow-seconds", "30")
        assert done.returncode == 0, done.stdout.decode("utf-8", "replace")
        module_data = _module(data)
        assert module_data["mode"] == "full"
        assert module_data["uncovered"] == []
        assert module_data["survived"] == []
        assert module_data["passed"] is True
    finally:
        support.cleanup(fixture)


def test_a_change_elsewhere_uses_change_mode_when_the_switch_was_already_on(tmp_path):
    fixture = support.start_repo(
        tmp_path, ANSWER, {"test_answer.py": ANSWER_TEST}, checks={"complexity": True, "mutation": True}
    )
    try:
        fixture.commit(
            {
                "harness/example.py": ANSWER.replace("* 2", "* 4"),
                "harness/tests/kernel/test_answer.py": ANSWER_TEST.replace("== 6", "== 12"),
            }
        )
        done, data = fixture.report("--mutation-slow-seconds", "30")
        assert done.returncode == 0, done.stdout.decode("utf-8", "replace")
        assert _module(data)["mode"] == "change"
    finally:
        support.cleanup(fixture)


def test_a_module_that_was_not_touched_does_not_run_mutation(tmp_path):
    fixture = support.start_repo(
        tmp_path, ANSWER, {"test_answer.py": ANSWER_TEST}, checks={"complexity": True, "mutation": True}
    )
    try:
        fixture.commit({"README.md": "说明\n"})
        done, data = fixture.report()
        assert done.returncode == 0, done.stdout.decode("utf-8", "replace")
        assert data["mutation"] is None
        assert "变异检查" not in done.stdout.decode("utf-8", "replace")
    finally:
        support.cleanup(fixture)


def test_the_module_option_runs_full_mode_on_an_unchanged_module(tmp_path):
    fixture = support.start_repo(tmp_path, ANSWER, {"test_answer.py": ANSWER_TEST}, checks=None)
    try:
        done, data = fixture.report("--module", support.MODULE, "--mutation-mode", "full", "--mutation-slow-seconds", "30")
        assert done.returncode == 0, done.stdout.decode("utf-8", "replace")
        module_data = _module(data)
        assert module_data["mode"] == "full"
        assert data["mutation"]["baseline"]["test_files"] == 1
        assert module_data["passed"] is True
    finally:
        support.cleanup(fixture)


def test_the_new_options_are_in_help_and_their_ranges_are_checked(tmp_path):
    fixture = support.start_repo(tmp_path, ANSWER, {"test_answer.py": ANSWER_TEST}, checks=None)
    try:
        done = fixture.run_raw("check", "--help")
        assert done.returncode == 0
        text = done.stdout.decode("utf-8", "replace")
        for option in ("--module", "--mutation-mode", "--mutation-slow-seconds", "--mutation-jobs"):
            assert option in text
        assert fixture.run("--mutation-slow-seconds", "0").returncode == 2
        assert fixture.run("--mutation-slow-seconds", "31").returncode == 2
        assert fixture.run("--mutation-jobs", "0").returncode == 2
        done = fixture.run("--module", "harness/not-a-module.py")
        assert done.returncode == 2
        assert "清单里没有这些内核模块" in done.stdout.decode("utf-8", "replace")
    finally:
        support.cleanup(fixture)


def test_the_outlets_text_is_not_in_a_passing_report(tmp_path):
    fixture = support.start_repo(
        tmp_path, ANSWER.replace("* 2", "* 3"), {"test_answer.py": ANSWER_TEST}, checks={"complexity": True, "mutation": True}
    )
    try:
        fixture.commit({"harness/example.py": ANSWER})
        done, data = fixture.report("--mutation-slow-seconds", "30")
        assert done.returncode == 0, done.stdout.decode("utf-8", "replace")
        assert report.MUTATION_OUTLETS not in done.stdout.decode("utf-8", "replace")
        assert data["verdict"] == "pass"
    finally:
        support.cleanup(fixture)
