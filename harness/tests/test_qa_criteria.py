# 质检逐条结论的词表与检验覆盖的三个数（验证的独立性设计说明第 7.1 节，工单 #151）。
#
# 检验方式的六个代码名是内核里的封闭取值（kernel_events.QA_METHODS），可执行与不可执行的分类、三个数的
# 算法在覆盖模块（coverage.py）里。两端共读的夹具是 harness/tests/fixtures/check_methods.json：
# 服务端核对封闭取值与夹具一致（这条用例），客户端声明表覆盖夹具（client/tests/unit/check-methods.test.ts）。
# 读静态定义与夹具、调纯函数，不使用临时目录与子进程，属于单元层。

import json
from pathlib import Path
from types import SimpleNamespace

from harness.coverage import (EXECUTABLE_METHODS, MODEL_READING_METHODS, coverage_report,
                              method_is_executable, open_criteria)
from harness.kernel_events import QA_METHODS, QA_RESULTS
from harness.tightening import (_criteria_coverage_errors, _criteria_evidence_errors, _qa_criteria,
                                _qa_criteria_errors, _release_criteria_errors)

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

# ---------------------------------------------------------------------------
# 逐条结论的规则（工单 #151）：结构、覆盖全部验收条件、可执行检验的证据、放行的三条规则。
# 这些函数读提案、当前 ProductSpec 的验收条件与本次激活的回执，都是纯判断，不写事件。


def _criterion(criterion="AC1", method="check", result="passed", checks=("qa_smoke",)):
    return {"criterion": criterion, "method": method, "result": result,
            "checks": list(checks), "trial_cases": [], "note": ""}


def _spec(count: int):
    # 当前 ProductSpec 的验收条件：只用到条数的这一项
    return SimpleNamespace(product_spec=SimpleNamespace(acceptance_criteria=["本" + str(index) for index in range(count)]))


def test_a_review_must_cover_every_acceptance_criterion_once():
    # 覆盖全部验收条件：缺一条报在 criteria 上并写明缺哪个，多一条也拒绝（守 R3）
    criteria = [_criterion("AC1")]
    missing = _criteria_coverage_errors(criteria, _spec(2), receipts={"qa_smoke": {}})
    assert [error.field for error in missing] == ["criteria"]
    assert "AC2" in missing[0].message

    extra = [_criterion("AC1"), _criterion("AC2"), _criterion("AC3")]
    errors = _criteria_coverage_errors(extra, _spec(2), receipts={"qa_smoke": {}})
    assert any("AC3" in error.message for error in errors)

    twice = [_criterion("AC1"), _criterion("AC1")]
    assert any("twice" in error.message
               for error in _criteria_coverage_errors(twice, _spec(1), receipts={"qa_smoke": {}}))


def test_criteria_checks_must_be_quality_receipts_of_this_activation():
    # 引用的检查名要在本次激活的质检回执里：工程的回执与别的激活的回执都不在 receipts 里（守 R1、R3）
    criteria = [_criterion("AC1", checks=["qa_smoke", "engineering_only"])]
    errors = _criteria_coverage_errors(criteria, _spec(1), receipts={"qa_smoke": {}})
    assert [error.field for error in errors] == ["criteria[0].checks"]
    assert "engineering_only" in errors[0].message


def test_a_passed_executable_criterion_needs_a_check_receipt():
    # 可执行检验写成 passed 时要有证据；不可执行检验的条件不要求（守 R3，对应 #724 的验收用例 2）
    assert _criteria_evidence_errors([_criterion("AC1", checks=[])])
    assert not _criteria_evidence_errors([_criterion("AC1", checks=["qa_smoke"])])
    assert not _criteria_evidence_errors([_criterion("AC1", method="judgement", result="unverified", checks=[])])


def test_release_rejects_failed_criteria_and_unpassed_executable_criteria():
    # 放行的三条规则（第 7.1 节第 3 点）：没有 failed；可执行检验的条件都是 passed；不可执行的可以是 unverified
    failed = _release_criteria_errors([_criterion("AC1", result="failed")])
    assert [error.field for error in failed] == ["criteria[0].result"]

    unverified = _release_criteria_errors([_criterion("AC1", method="measure", result="unverified")])
    assert [error.field for error in unverified] == ["criteria[0].result"]

    open_loop = _release_criteria_errors([_criterion("AC1", method="open", result="unverified", checks=[])])
    assert open_loop == []


def test_the_criterion_shape_is_closed():
    # 字段封闭、检验方式与结果在封闭取值里、criterion 是 AC<序号>、trial_cases 现在必须为空（守 R2）
    proposal = {"criteria": [{"criterion": "AC1", "method": "check", "result": "passed",
                              "checks": ["qa"], "trial_cases": [], "note": "", "extra": 1}]}
    assert [error.field for error in _qa_criteria_errors(proposal)] == ["criteria[0].extra"]

    for item, field in (({"criterion": "a1", "method": "check", "result": "passed"}, "criteria[0].criterion"),
                        ({"criterion": "AC1", "method": "probe", "result": "passed"}, "criteria[0].method"),
                        ({"criterion": "AC1", "method": "check", "result": "ok"}, "criteria[0].result"),
                        ({"criterion": "AC1", "method": "check", "result": "passed",
                          "trial_cases": ["case-1"]}, "criteria[0].trial_cases")):
        errors = _qa_criteria_errors({"criteria": [item]})
        assert field in [error.field for error in errors], (item, errors)

    assert _qa_criteria_errors({})[0].field == "criteria"
    rows, errors = _qa_criteria({"criteria": [_criterion("AC1")]})
    assert errors == [] and rows[0]["criterion"] == "AC1" and rows[0]["trial_cases"] == []

