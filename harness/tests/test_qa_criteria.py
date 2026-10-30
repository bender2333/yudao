# 质检逐条结论的词表与检验覆盖的三个数（验证的独立性设计说明第 7.1 节，工单 #151）。
#
# 检验方式的六个代码名是内核里的封闭取值（kernel_events.QA_METHODS），可执行与不可执行的分类、三个数的
# 算法在覆盖模块（coverage.py）里。两端共读的夹具是 harness/tests/fixtures/check_methods.json：
# 服务端核对封闭取值与夹具一致（这条用例），客户端声明表覆盖夹具（client/tests/unit/check-methods.test.ts）。
# 读静态定义与夹具、调纯函数，不使用临时目录与子进程，属于单元层。

import json
from pathlib import Path

from harness.coverage import (EXECUTABLE_METHODS, MODEL_READING_METHODS, coverage_report,
                              method_is_executable, open_criteria)
from harness.kernel_events import QA_METHODS, QA_RESULTS

FIXTURES = Path(__file__).resolve().parent / "fixtures"
# 客户端那一份夹具与这一份同内容（两者不一致时两端的词表就分叉了）
CLIENT_FIXTURE = Path(__file__).resolve().parents[2] / "client" / "tests" / "fixtures" / "check-methods.json"


def _fixture() -> dict:
    return json.loads((FIXTURES / "check_methods.json").read_text(encoding="utf-8"))


def test_the_two_fixtures_hold_the_same_methods():
    # 两端各读自己那一份夹具：两份内容必须相同（守 R2，词表是两端的合同）
    assert json.loads(CLIENT_FIXTURE.read_text(encoding="utf-8")) == _fixture()


def test_the_service_method_table_matches_the_shared_fixture():
    # 两端共读的夹具与服务端的封闭取值一致：代码名逐一相同、可执行与不可执行的分类相同。
    # 守 R2（独立性说明第 7.1 节的词表是两端的合同）与 R3（逐条结论用的检验方式）
    fixture = _fixture()
    assert [item["code"] for item in fixture["methods"]] == list(QA_METHODS)
    executable = {item["code"] for item in fixture["methods"] if item["executable"]}
    assert executable == set(EXECUTABLE_METHODS)
    assert {item["code"] for item in fixture["methods"] if not item["executable"]} == {
        "judgement", "human", "open"}
    # 模型阅读是判定点这一种，含于开环
    assert set(MODEL_READING_METHODS) == {"judgement"}
    assert list(QA_RESULTS) == ["passed", "failed", "unverified"]


def test_coverage_counts_covered_open_and_model_reading():
    # 第 7.1 节第 4 点：比例的分母是条件总数，分子是可执行检验里通过的那些；开环 = 条件总数 −
    # 可执行检验的条件数；模型阅读（judgement）含于开环。守 R2（三个数的口径）
    criteria = [
        {"criterion": "AC1", "method": "check", "result": "passed"},
        {"criterion": "AC2", "method": "measure", "result": "failed"},
        {"criterion": "AC3", "method": "judgement", "result": "unverified"},
        {"criterion": "AC4", "method": "open", "result": "unverified"},
    ]
    assert coverage_report(criteria) == {
        "criteria_total": 4, "executable": 2, "covered": 1, "coverage_ratio": 0.25,
        "model_reading": 1, "open": 2,
    }
    assert open_criteria(criteria) == ["AC3", "AC4"]
    assert method_is_executable("trial") and not method_is_executable("human")


def test_an_unverified_executable_criterion_is_not_counted_as_covered():
    # 没有证据的条件不算已核（#724 的验收用例 2）：可执行检验写成 unverified 时不计入分子
    criteria = [{"criterion": "AC1", "method": "check", "result": "unverified"}]
    report = coverage_report(criteria)
    assert report["covered"] == 0 and report["coverage_ratio"] == 0.0
    assert report["open"] == 0


def test_an_empty_criteria_list_reports_a_zero_ratio():
    assert coverage_report([]) == {"criteria_total": 0, "executable": 0, "covered": 0,
                                   "coverage_ratio": 0.0, "model_reading": 0, "open": 0}
    assert open_criteria([]) == []
