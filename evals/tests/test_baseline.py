"""Tests for the Stage 3 omp baseline.

They run the real computation against the recorded data file
(`docs/evaluation/baseline-omp-stage3.json`, captured from GitHub and the
autopilot run directory) and check the numbers of representative issues plus
the aggregates. No mock is used: `compute` reads that file and nothing else.
"""

import json
import os
import sys

EVALS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE_DIR = os.path.join(EVALS_DIR, "baseline")
if BASELINE_DIR not in sys.path:
    sys.path.insert(0, BASELINE_DIR)

import collect
import compute

REPO_ROOT = os.path.dirname(EVALS_DIR)
DATA_FILE = os.path.join(REPO_ROOT, "docs", "evaluation", "baseline-omp-stage3.json")


def recorded_data():
    assert os.path.exists(DATA_FILE), (
        "%s 不存在，先运行 evals/baseline/collect.py 抓取一次真实数据" % DATA_FILE)
    with open(DATA_FILE, encoding="utf-8") as handle:
        return json.load(handle)


def computed():
    return compute.compute(recorded_data())


def record_for(result, number):
    for record in result["issues"]:
        if record["number"] == number:
            return record
    raise AssertionError("数据文件里没有 #%d" % number)


def test_issue_numbers_from_recorded_data():
    # 每个工单的数字：审查轮数、交付轮数、集成层失败、耗时与用量
    result = computed()
    summary = result["summary"]
    assert summary["issues"] == 171
    assert summary["merged"] == 94
    assert summary["with_usage"] == 70
    assert summary["stalled"] == 15

    # 一轮通过、有运行记录、无集成层失败
    assert record_for(result, 346)["review_rounds"] == 1
    assert record_for(result, 346)["delivery_rounds"] == [1]
    assert record_for(result, 346)["integration_failures"] == []
    assert record_for(result, 346)["elapsed_minutes"] == 55
    assert record_for(result, 346)["usage"]["requests"] == 152

    # 四轮交付但审查轮数仍是 1（没有 review-failed）
    assert record_for(result, 316)["review_rounds"] == 1
    assert record_for(result, 316)["delivery_rounds"] == [4]
    assert record_for(result, 316)["elapsed_minutes"] == 497

    # review-failed 一次的工单：审查轮数为 2
    assert record_for(result, 90)["review_rounds"] == 2
    assert record_for(result, 90)["delivery_rounds"] == [1, 2]
    assert record_for(result, 89)["review_rounds"] == 2
    assert record_for(result, 89)["delivery_rounds"] == [2, 5, 5, 6, 7, 8]
    assert record_for(result, 319)["review_rounds"] == 2
    assert record_for(result, 319)["delivery_rounds"] == [2, 3]

    # 集成层失败归因到被评论点名（以引入方写法）的工单
    assert [failure["commit"] for failure in
            record_for(result, 248)["integration_failures"]] == ["d7718fc5"]
    assert [failure["commit"] for failure in
            record_for(result, 90)["integration_failures"]] == ["ac2dd004"]
    assert [failure["commit"] for failure in
            record_for(result, 301)["integration_failures"]] == ["b80938ca"]
    # d29683c4 的引入方是 #242（给登记命令增加 repeatable 没有重写基准）；
    # #136 在评论里全部写在修复一侧（"第 3 轮的分支已经重写了这三个基准"）
    assert [failure["commit"] for failure in
            record_for(result, 242)["integration_failures"]] == ["d29683c4"]
    assert record_for(result, 136)["integration_failures"] == []
    # 一次失败点名两个工单时两边都记（dcd742f1 → #16 与 #75）
    assert [failure["commit"] for failure in
            record_for(result, 16)["integration_failures"]] == ["dcd742f1"]
    assert [failure["commit"] for failure in
            record_for(result, 75)["integration_failures"]] == ["dcd742f1"]
    # 修复方写法点名的工单不记：#285 是修 #248 引入的失败，不算引入方
    assert record_for(result, 285)["integration_failures"] == []

    # 未合并的工单没有耗时
    assert record_for(result, 19)["merged_at"] is None
    assert record_for(result, 19)["elapsed_minutes"] is None


def test_summary_numbers_from_recorded_data():
    result = computed()
    summary = result["summary"]
    assert summary["review_rounds"]["count"] == 94
    assert summary["review_rounds"]["distribution"] == {1: 85, 2: 9}
    assert summary["review_rounds"]["median"] == 1
    assert summary["integration_failures"]["distribution"] == {0: 84, 1: 10}
    assert summary["integration_failures"]["median"] == 0
    assert summary["elapsed_minutes"]["median"] == 221.5
    assert summary["elapsed_minutes"]["min"] == 17
    assert summary["elapsed_minutes"]["count"] == 92
    # 费用：omp 的运行输出里 cost 全为 0，费用要按用量乘单价另算
    assert summary["cost"]["median"] == 0
    # 失败计数按集成层记录：归因到的写明工单，没写明的列为未归因
    assert result["failures"] == {"failures": 11, "attributed_failures": 8,
                                  "unattributed_failures": 3, "failure_pairs": 10}
    # 归因结果不含范围外工单：#268 出现在评论里但没有 Stage 3 里程碑
    assert all(268 not in entry["issues"] for entry in result["attribution"])


def test_integration_records_and_stalled_reasons():
    data = recorded_data()
    integration = compute.integration_runs(data["stage_comments"])
    assert len(integration) == 27
    failures = [record for record in integration if record["verdict"] == "FAIL"]
    assert len(failures) == 11
    # 两种首行写法都解析得动：带竖线计数与不带计数
    counts = {record["commit"]: record["counts"] for record in failures}
    assert counts["d7718fc5"].startswith("17 failed")
    assert counts["f67e79f6"].startswith("1642 passed")
    assert counts["dcd742f1"] == ""

    # 搁置：#75 标过 ready-for-human，原因是模型当天额度用完
    result = computed()
    stalled = record_for(result, 75)["stalled"]
    assert stalled["since"] == "2026-09-29T20:49:10Z"
    assert "Billing daily count exceeded" in stalled["comments"][0]["text"]
    assert record_for(result, 346)["stalled"] is None


def test_report_covers_merged_issues_and_is_written_in_chinese():
    result = computed()
    report = compute.build_report(result)
    # 覆盖 Stage 3 已合并的工单
    for record in result["issues"]:
        if record["merged_at"]:
            assert "| #%d |" % record["number"] in report, record["number"]
    # 报告用中文，含五项口径、汇总与失败归因
    for word in ("审查轮数", "集成层失败归因", "搁置的原因", "耗时", "用量"):
        assert word in report, word
    for heading in ("## 一、口径", "## 三、汇总", "## 四、逐个工单",
                    "## 五、搁置的原因", "## 六、集成层失败与归因"):
        assert heading in report, heading
    assert "中位数" in report


def test_compute_touches_no_external_process(monkeypatch):
    # 计算一步只读数据文件：把子进程换成会立刻失败的桩以后仍能算完
    def explode(*args, **kwargs):
        raise AssertionError("计算一步不应调用外部命令")

    monkeypatch.setattr(collect.subprocess, "run", explode)
    assert computed()["summary"]["merged"] == 94


def test_collect_parses_usage_from_real_run_output(tmp_path):
    # 抓取运行目录里的一行事件流：用量、费用、模型与请求数按真实 JSONL 累计
    path = tmp_path / "omp-345a.jsonl"
    lines = [
        '{"type": "session", "id": "s1"}',
        '{"type": "message_end", "message": {"role": "assistant", '
        '"provider": "9router", "model": "oro", "usage": {"input": 10, '
        '"output": 5, "cacheRead": 2, "cacheWrite": 0, "totalTokens": 17, '
        '"cost": {"total": 0}}, "timestamp": 1700000000000, '
        '"completedAt": 1700000001000}}',
        '{"type": "message_end", "message": {"role": "assistant", '
        '"provider": "9router", "model": "my-small", "usage": {"input": 3, '
        '"output": 1, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 4, '
        '"cost": {"total": 0}}, "timestamp": 1700000002000, '
        '"completedAt": 1700000003000}}',
        "这一行不是 JSON",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (tmp_path / "omp-345a.done").write_text("exit 0 16:55", encoding="utf-8")
    summary = collect._run_summary(str(path), "omp-345a.jsonl", "omp", 345, "a",
                                   str(tmp_path))
    assert summary["issue"] == 345
    assert summary["round"] == "a"
    assert summary["requests"] == 2
    assert summary["input_tokens"] == 13
    assert summary["output_tokens"] == 6
    assert summary["cache_read_tokens"] == 2
    assert summary["total_tokens"] == 21
    assert summary["started_ms"] == 1700000000000
    assert summary["finished_ms"] == 1700000003000
    assert summary["exit_code"] == 0
    assert summary["finished_local"] == "16:55"
    assert sorted(summary["models"]) == ["9router/my-small", "9router/oro"]


def test_run_directory_only_counts_omp_and_reviewer_output(tmp_path):
    # 运行目录里只有 omp- 与 rv- 开头的运行输出进入数据文件
    for name in ("omp-346a.jsonl", "rv-346a.jsonl", "int-4123cb97.log",
                 "oc-346a.done", ".seen"):
        (tmp_path / name).write_text("", encoding="utf-8")
    runs = collect.run_usage(str(tmp_path))
    assert [run["file"] for run in runs] == ["omp-346a.jsonl", "rv-346a.jsonl"]
    assert [run["role"] for run in runs] == ["omp", "rv"]