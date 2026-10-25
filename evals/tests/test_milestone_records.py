"""里程碑工单记录的测试。

字段与汇总用录制的真实数据检查：`fixtures/milestone_early.json` 与
`fixtures/milestone_late.json` 是 `docs/archive/evaluation/milestones/stage3-m0.json`
（从 GitHub 抓取）里挑出的工单，原样保留。计算只读数据文件，不用 mock，不调用模型。

真实数据里没有的三种情况（一张工单几个 PR、加过两次 needs-architect、合并以后被重新打开）
用 `synthetic_issue` 在录制记录的基础上改写时间线与 PR 清单来检查，测试名里带 synthetic。
"""

import copy
import json
import os
import sys

EVALS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE_DIR = os.path.join(EVALS_DIR, "baseline")
if BASELINE_DIR not in sys.path:
    sys.path.insert(0, BASELINE_DIR)

import milestone

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def recorded(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


def record_for(result, number):
    return next(record for record in result["issues"] if record["number"] == number)


def early():
    return milestone.compute(recorded("milestone_early.json"))


def late():
    return milestone.compute(recorded("milestone_late.json"))


def test_one_round_approved_issue():
    # #533：一个 PR，一条 DELIVERY，批准，没有要求修改
    record = record_for(early(), 533)
    assert record["kind"] == "实现类"
    assert record["pull_requests"] == [536]
    assert record["rounds"] == 1
    assert (record["changes_requested"], record["final_review"]) == (0, "批准")
    assert record["elapsed_minutes"] == 104
    assert (record["files_total"], record["files_handwritten"]) == (5, 4)


def test_two_delivery_rounds_with_requested_changes():
    # #532：两轮 DELIVERY，一次要求修改，最后批准；51 个文件里 44 个是生成的基准与日记
    record = record_for(late(), 532)
    assert record["rounds"] == 2
    assert record["changes_requested"] == 1
    assert record["final_review"] == "批准"
    assert (record["files_total"], record["files_handwritten"]) == (51, 7)
    assert record["baseline_changes"] == 43


def test_comment_between_deliveries_is_not_a_round():
    # #463：两条 DELIVERY 中间夹着派发者的评论，只数首行为 DELIVERY: 的
    pull = next(p for p in recorded("milestone_late.json")["pull_requests"] if p["number"] == 592)
    assert len(pull["comments"]) == 3
    assert record_for(late(), 463)["rounds"] == 2


def test_dismissed_review_is_ignored():
    # #582：审查里有一次 DISMISSED，不算要求修改，最后结论取批准
    record = record_for(late(), 582)
    assert (record["changes_requested"], record["final_review"]) == (0, "批准")


def test_pull_request_without_delivery_comment():
    # #469 的 PR 在 DELIVERY 格式出现以前合并：轮数 0，耗时仍然有
    record = record_for(early(), 469)
    assert record["rounds"] == 0
    assert record["final_review"] == "无审查"
    assert record["elapsed_minutes"] == 72


def test_bug_label_is_fix_kind():
    assert record_for(early(), 584)["kind"] == "修复类"
    assert record_for(early(), 533)["kind"] == "实现类"


def test_closed_without_pr():
    record = record_for(late(), 544)
    assert record["closed_without_pr"] is True
    assert record["pull_requests"] == [] and record["elapsed_minutes"] is None


def test_open_issue_is_not_closed_without_pr():
    record = record_for(late(), 466)
    assert record["state"] == "OPEN" and record["closed_without_pr"] is False


def test_summary_of_recorded_data():
    summary = early()["summary"]
    assert summary["issues"] == 5 and summary["open"] == 0
    assert summary["with_delivery"] == 4
    assert summary["average_rounds"] == 1.0
    assert summary["fix_issues"] == 1 and summary["fix_ratio"] == 0.2
    assert summary["baseline_changes"] == 1
    assert summary["elapsed_minutes"]["max"] == 104
    summary = late()["summary"]
    assert summary["issues"] == 5 and summary["open"] == 1
    assert summary["average_rounds"] == 1.67
    assert summary["rounds_histogram"] == {"1": 1, "2": 2}
    assert summary["changes_requested"] == 2
    assert summary["closed_without_pr"] == 1
    assert summary["elapsed_minutes"]["median"] == 236


def synthetic_issue():
    """在录制的 #532 与它的 PR 上改写出真实数据里没有的情况，返回 (工单, [PR])。"""
    data = recorded("milestone_late.json")
    issue = copy.deepcopy(next(i for i in data["issues"] if i["number"] == 532))
    pull = copy.deepcopy(next(p for p in data["pull_requests"] if p["number"] == 537))
    return issue, pull


def test_synthetic_two_pull_requests_all_counted():
    issue, first = synthetic_issue()
    second = copy.deepcopy(first)
    second["number"] = 9999
    second["merged_at"] = "2026-10-17T12:00:00Z"
    second["comments"] = [{"created_at": "2026-10-17T11:00:00Z", "author": "x",
                           "first_line": "DELIVERY: 第 1 轮"}]
    second["reviews"] = [{"author": "x", "state": "CHANGES_REQUESTED",
                          "submitted_at": "2026-10-17T11:30:00Z"}]
    record = milestone.compute_issue(issue, [second, first])
    assert record["pull_requests"] == [537, 9999]
    assert record["rounds"] == 3
    assert record["rounds_per_pr"] == {537: 2, 9999: 1}
    assert record["changes_requested"] == 2
    assert record["final_review"] == "要求修改"  # 最晚的一次审查是新 PR 上的要求修改


def test_synthetic_architect_twice_and_reopened_after_merge():
    issue, pull = synthetic_issue()
    merged = pull["merged_at"]
    issue["timeline"] += [
        {"event": "labeled", "created_at": "2026-10-10T00:00:00Z", "actor": "a",
         "label": "needs-architect"},
        {"event": "labeled", "created_at": "2026-10-11T00:00:00Z", "actor": "a",
         "label": "needs-architect"},
        {"event": "reopened", "created_at": "2026-10-01T00:00:00Z", "actor": "a", "label": None},
        {"event": "reopened", "created_at": "2099-01-01T00:00:00Z", "actor": "a", "label": None}]
    record = milestone.compute_issue(issue, [pull])
    assert record["architect_interventions"] == 2
    # 只数第一个 PR 合并之后的 reopened：合并是 merged，2026-10-01 的那次更早
    assert merged > "2026-10-01T00:00:00Z"
    assert record["reopened_after_merge"] == 1


def test_compare_with_previous_milestone():
    current, previous = late(), early()
    rows = {name: (before, after) for name, before, after in milestone.compare(current, previous)}
    assert rows["工单数"] == (5, 5)
    assert rows["其中未关闭"] == (0, 1)
    assert rows["平均轮数"] == (1.0, 1.67)
    assert rows["要求修改的合计次数"] == (0, 2)
    assert rows["基准变化数合计"] == (1, 43)
    assert rows["关闭时没有 PR 的工单数"] == (0, 1)
    assert rows["修复类比例"] == (0.2, 0.0)


def test_report_lists_both_sides():
    text = milestone.build_report(late(), early())
    assert "与上一个里程碑比较" in text
    assert "| 平均轮数 | 1.0 | 1.67 |" in text
    assert "| 基准变化数合计 | 1 | 43 |" in text
    assert "还没有关闭" in text and "1 张还没有关闭" in text
    without = milestone.build_report(late())
    assert "与上一个里程碑比较" not in without


def test_report_command_reads_only_the_data_file(tmp_path):
    out = tmp_path / "report.md"
    result = milestone.report(os.path.join(FIXTURES, "milestone_late.json"), str(out),
                              os.path.join(FIXTURES, "milestone_early.json"))
    assert result["summary"]["issues"] == 5
    assert "#463" in out.read_text(encoding="utf-8")
