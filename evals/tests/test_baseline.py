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
    assert summary["issues"] >= 195
    assert summary["merged"] == 128
    assert summary["with_usage"] == 76
    assert summary["stalled"] >= 16

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
    assert summary["review_rounds"]["count"] == 128
    assert summary["review_rounds"]["distribution"] == {1: 118, 2: 10}
    assert summary["review_rounds"]["median"] == 1
    assert summary["integration_failures"]["distribution"] == {0: 113, 1: 15}
    assert summary["integration_failures"]["median"] == 0
    assert summary["elapsed_minutes"]["median"] == 221
    assert summary["elapsed_minutes"]["min"] == 16
    assert summary["elapsed_minutes"]["count"] == 121
    # 费用：omp 的运行输出里 cost 全为 0，费用要按用量乘单价另算
    assert summary["cost"]["median"] == 0
    # 失败计数按集成层记录：归因到的写明工单，没写明的列为未归因
    assert result["failures"] == {"failures": 18, "attributed_failures": 12,
                                  "unattributed_failures": 6, "failure_pairs": 15}
    # 归因结果不含范围外工单：#268 出现在评论里但没有 Stage 3 里程碑
    assert all(268 not in entry["issues"] for entry in result["attribution"])


def test_integration_records_and_stalled_reasons():
    data = recorded_data()
    integration = compute.integration_runs(data["stage_comments"])
    assert len(integration) == 36
    failures = [record for record in integration if record["verdict"] == "FAIL"]
    assert len(failures) == 18
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
    for heading in ("## 一、口径", "## 四、汇总", "## 五、逐个工单",
                    "## 六、搁置的原因", "## 七、集成层失败与归因"):
        assert heading in report, heading
    assert "中位数" in report


def test_compute_touches_no_external_process(monkeypatch):
    # 计算一步只读数据文件：把子进程换成会立刻失败的桩以后仍能算完
    def explode(*args, **kwargs):
        raise AssertionError("计算一步不应调用外部命令")

    monkeypatch.setattr(collect.subprocess, "run", explode)
    assert computed()["summary"]["merged"] == 128


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


def _write_run(path, lines, done="exit 0 12:00"):
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    done_path = path.with_suffix(".done")
    done_path.write_text(done, encoding="utf-8")


def _run(models, rounds=(("a", "omp"),)):
    """构造 runs 列表：[(model_key, usage_dict, role, round)]，role/round 用来组元组。"""
    out = []
    for round_suffix, role in rounds:
        for model_key, usage in models:
            entry = {"requests": 1}
            entry.update(usage)
            entry["requests_with_usage"] = 1 if all(
                key in usage for key in ("input", "output", "cacheRead",
                                          "cacheWrite", "totalTokens")) else 0
            entry["requests_without_usage"] = 1 - entry["requests_with_usage"]
            entry["input_tokens"] = int(usage.get("input") or 0)
            entry["output_tokens"] = int(usage.get("output") or 0)
            entry["cache_read_tokens"] = int(usage.get("cacheRead") or 0)
            entry["cache_write_tokens"] = int(usage.get("cacheWrite") or 0)
            entry["total_tokens"] = int(usage.get("totalTokens") or 0)
            entry["reported_cost"] = float((usage.get("cost") or {}).get("total") or 0)
            entry["models"] = {model_key: {"requests": 1,
                                            "requests_with_usage": entry["requests_with_usage"],
                                            "input_tokens": entry["input_tokens"],
                                            "output_tokens": entry["output_tokens"],
                                            "cache_read_tokens": entry["cache_read_tokens"],
                                            "cache_write_tokens": entry["cache_write_tokens"],
                                            "total_tokens": entry["total_tokens"],
                                            "reported_cost": entry["reported_cost"]}}
            out.append({"file": "%s-345%s.jsonl" % (role, round_suffix),
                        "role": role, "issue": 345, "round": round_suffix,
                        "started_ms": 1700000000000, "finished_ms": 1700000001000,
                        "exit_code": 0, "finished_local": "12:00",
                        **entry})
    return out


def test_run_summary_separates_usage_complete_and_missing(tmp_path):
    # 用量字段齐全时进入 valid 用量；缺一字段时记入 requests_without_usage，不累加 token
    path = tmp_path / "omp-345a.jsonl"
    good = '{"type": "message_end", "message": {"role": "assistant", ' \
        '"provider": "9router", "model": "oro", "usage": {"input": 10, ' \
        '"output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 10, ' \
        '"cost": {"total": 0.01}}, "timestamp": 1700000000000, ' \
        '"completedAt": 1700000001000}}'
    bad = '{"type": "message_end", "message": {"role": "assistant", ' \
        '"provider": "9router", "model": "oro", "usage": {"input": 999}, ' \
        '"timestamp": 1700000002000, "completedAt": 1700000003000}}'
    _write_run(path, [good, bad])
    summary = collect._run_summary(str(path), "omp-345a.jsonl", "omp", 345, "a",
                                   str(tmp_path))
    assert summary["requests"] == 2
    assert summary["requests_with_usage"] == 1
    assert summary["requests_without_usage"] == 1
    # 999 不进入统计，只统计第一条明确上报的 10
    assert summary["input_tokens"] == 10
    assert summary["total_tokens"] == 10
    # cost 取自原始 cost.total
    assert summary["reported_cost"] == 0.01


def test_run_summary_zero_usage_counts_as_known_value(tmp_path):
    # 全部字段都出现（含 0）即视为明确零，不是未知
    path = tmp_path / "omp-345a.jsonl"
    zero = '{"type": "message_end", "message": {"role": "assistant", ' \
        '"provider": "9router", "model": "oro", "usage": {"input": 0, ' \
        '"output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 0, ' \
        '"cost": {"total": 0}}, "timestamp": 1700000000000, ' \
        '"completedAt": 1700000001000}}'
    _write_run(path, [zero])
    summary = collect._run_summary(str(path), "omp-345a.jsonl", "omp", 345, "a",
                                   str(tmp_path))
    assert summary["requests_with_usage"] == 1
    assert summary["requests_without_usage"] == 0
    assert summary["input_tokens"] == 0
    assert summary["total_tokens"] == 0


def test_load_model_prices_returns_empty_when_file_missing():
    # 文件缺失：所有模型视为缺单价，不参与费用
    empty = collect.load_model_prices(None)
    assert empty == {"_source": "", "loaded": False, "prices": {}}
    assert collect.load_model_prices("/definitely/not/exists.json")["loaded"] is False


def test_load_model_prices_parses_valid_entries_and_lists_missing():
    import tempfile
    import pathlib
    raw = {
        "9router/oro": {"input": 1.5, "output": 6.0,
                        "cache_read": 0.3, "cache_write": 3.75},
        "9router/unknown-model": {"input": 2.0,
                                   "output": None,
                                   "cache_read": 0.1,
                                   "cache_write": 0.5},
        "9router/all-missing": {"input": None, "output": None,
                                 "cache_read": None, "cache_write": None},
        "not-a-dict": "broken"}
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json",
                                     encoding="utf-8") as handle:
        import json as _json
        _json.dump(raw, handle)
        path = handle.name
    try:
        loaded = collect.load_model_prices(path)
        assert loaded["loaded"] is True
        assert loaded["prices"]["9router/oro"]["input"] == 1.5
        # 部分字段缺失仍记入价格表，仅写入有的字段
        assert "9router/unknown-model" in loaded["prices"]
        assert "output" not in loaded["prices"]["9router/unknown-model"]
        assert "9router/all-missing" not in loaded["prices"]
        assert ("9router/all-missing", "全部字段缺失") in loaded["missing_fields"]
        # 整条不是字典的条目也只出现在 missing_fields
        assert ("not-a-dict", "不是字典") in loaded["missing_fields"]
    finally:
        pathlib.Path(path).unlink()


def test_issue_usage_with_prices_computes_full_cost_and_marks_missing():
    runs = _run([
        ("9router/oro", {"input": 1_000_000, "output": 500_000,
                          "cacheRead": 0, "cacheWrite": 0,
                          "totalTokens": 1_500_000,
                          "cost": {"total": 0}}),
        ("9router/oro-no-price", {"input": 200_000, "output": 0,
                                    "cacheRead": 0, "cacheWrite": 0,
                                    "totalTokens": 200_000,
                                    "cost": {"total": 0}})])
    prices = {"_source": "x", "loaded": True,
              "prices": {"9router/oro": {"input": 2.0,
                                          "output": 8.0,
                                          "cache_read": 0.4,
                                          "cache_write": 4.0}}}
    usage = compute.issue_usage(345, runs, prices)
    # 完整费用 = (1_000_000×2 + 500_000×8) / 1e6 = 6.0
    assert usage["valid_cost_usd"] == 6.0
    # 缺单价的模型条目标记 missing_price
    assert usage["models"]["9router/oro-no-price"]["missing_price"] is True
    assert usage["models"]["9router/oro"]["missing_price"] is False
    # 各模型的请求数、用量字段从有 usage 的请求累加
    assert usage["models"]["9router/oro"]["total_tokens"] == 1_500_000


def test_issue_usage_without_prices_leaves_valid_cost_at_zero():
    runs = _run([
        ("9router/oro", {"input": 1000, "output": 100,
                          "cacheRead": 0, "cacheWrite": 0,
                          "totalTokens": 1100,
                          "cost": {"total": 0.05}})])
    usage = compute.issue_usage(345, runs, None)
    # 没单价 -> 缺单价，valid_cost_usd 保持为 0
    assert usage["valid_cost_usd"] == 0.0
    assert usage["models"]["9router/oro"]["missing_price"] is True
    # reported_cost 仍然保留原始 cost.total，便于核对
    assert usage["reported_cost"] == 0.05
    assert usage["cost"] == 0.05


def test_summarize_counts_valid_and_unknown_samples_separately():
    # 没有运行记录的工单不进入有效样本
    empty_model = {"requests": 0, "requests_with_usage": 0,
                   "input_tokens": 0, "output_tokens": 0,
                   "cache_read_tokens": 0, "cache_write_tokens": 0,
                   "total_tokens": 0,
                   "reported_cost": 0.0, "valid_cost_usd": 0.0,
                   "missing_price": False}
    records = [
        {"number": 1, "title": "A", "milestone": "Stage 3 · M1",
         "state": "open", "merged_at": None,
         "usage": {"requests": 0, "requests_with_usage": 0,
                   "requests_without_usage": 0, "total_tokens": 0,
                   "valid_cost_usd": 0.0, "reported_cost": 0.0,
                   "models": {}, "runs": []},
         "integration_failures": [], "stalled": None,
         "review_rounds": 1, "delivery_rounds": [], "elapsed_minutes": None},
        {"number": 2, "title": "B", "milestone": "Stage 3 · M1",
         "state": "closed",
         "merged_at": "2026-10-07T00:00:00Z",
         "usage": {"requests": 10, "requests_with_usage": 10,
                   "requests_without_usage": 0, "total_tokens": 1000,
                   "valid_cost_usd": 0.0, "reported_cost": 0.0,
                   "models": {"9router/oro": {**empty_model, "requests": 10,
                                              "requests_with_usage": 10,
                                              "input_tokens": 700,
                                              "output_tokens": 200,
                                              "cache_read_tokens": 100,
                                              "cache_write_tokens": 0,
                                              "total_tokens": 1000,
                                              "missing_price": True}},
                   "runs": []},
         "integration_failures": [], "stalled": None,
         "review_rounds": 1, "delivery_rounds": [1], "elapsed_minutes": 60},
        {"number": 3, "title": "C", "milestone": "Stage 3 · M1",
         "state": "closed",
         "merged_at": "2026-10-07T00:00:00Z",
         "usage": {"requests": 5, "requests_with_usage": 0,
                   "requests_without_usage": 5, "total_tokens": 0,
                   "valid_cost_usd": 0.0, "reported_cost": 0.0,
                   "models": {}, "runs": []},
         "integration_failures": [], "stalled": None,
         "review_rounds": 1, "delivery_rounds": [1], "elapsed_minutes": 30}]
    summary = compute.summarize(records, {"loaded": False, "prices": {}})
    # merged 集为 [2, 3]
    assert summary["merged"] == 2
    # 有效用量 = 2；缺用量 = 3
    assert summary["samples"]["valid_usage"] == 1
    assert summary["samples"]["unknown_usage"] == 1
    assert summary["samples"]["cost_unknown_with_usage"] == 1
    assert summary["samples"]["with_run"] == 2
    # by_model 仅含用量完整的工单
    assert summary["by_model"]["9router/oro"]["requests"] == 10
    assert summary["by_model"]["9router/oro"]["missing_price"] is True


def test_failure_attribution_keeps_original_comment_for_unattributed():
    # 未归因的失败也能反查到原评论 body
    integration = [{
        "created_at": "2026-10-07T04:40:49Z",
        "verdict": "FAIL",
        "commit": "abcd1234",
        "counts": "",
        "body": "INTEGRATION: FAIL abcd1234\n\n与本工单无关的环境抖动。"}]
    attribution = compute.failure_attribution(
        integration, [], {999})
    assert attribution["abcd1234"]["attribution"] == "未归因"
    assert "环境抖动" in attribution["abcd1234"]["body"]


def test_recorded_data_exposes_model_prices_field():
    # 录制数据文件至少能容纳 model_prices 字段（不存在或为空都行）
    data = recorded_data()
    prices = data.get("model_prices")
    assert prices is None or isinstance(prices, dict)


def test_computed_includes_by_model_and_missing_price_list():
    # compute() 必须把按模型组合与缺单价清单写进 summary
    result = computed()
    summary = result["summary"]
    assert "by_model" in summary
    # 当前录制数据中用到的模型至少包含 9router/my-small 与 9router/oro
    model_keys = set(summary["by_model"])
    assert "9router/my-small" in model_keys
    assert "9router/oro" in model_keys
    # 缺单价清单至少包含这些模型
    assert set(summary.get("missing_model_prices") or []) <= model_keys


def test_report_lists_models_and_unknown_reasons():
    result = computed()
    report = compute.build_report(result)
    for heading in ("## 一、口径", "## 二、覆盖与未知",
                    "## 三、按模型组合汇总", "## 五、逐个工单",
                    "## 七、集成层失败与归因", "## 八、未知原因统计"):
        assert heading in report, heading
    # 按模型组合表格必须列出 #387 用到的 9router/my-small
    assert "9router/my-small" in report
    # 集成层原评论代码块存在
    assert "```text" in report


def test_merge_updates_keeps_latest_state_without_regression():
    # 重新抓取时 timeline 与 comments 按 (created_at, event/author, body) 去重合并
    previous = [{
        "created_at": "2026-10-01T00:00:00Z", "event": "labeled",
        "label": "in-progress", "milestone": "Stage 3", "actor": "u1"}]
    latest = [
        {"created_at": "2026-10-01T00:00:00Z", "event": "labeled",
         "label": "in-progress", "milestone": "Stage 3", "actor": "u1"},
        {"created_at": "2026-10-02T00:00:00Z", "event": "closed",
         "label": None, "milestone": None, "actor": "u1"}]
    merged = collect._merge_timeline(previous, latest)
    assert len(merged) == 2
    assert merged[0]["created_at"] == "2026-10-01T00:00:00Z"
    assert merged[1]["created_at"] == "2026-10-02T00:00:00Z"

    previous_comments = [{"created_at": "2026-10-01T00:00:00Z",
                          "author": "u1", "body": "DELIVERY 第 1 轮"}]
    latest_comments = [{"created_at": "2026-10-02T00:00:00Z",
                          "author": "u1", "body": "REVIEW: PASS"}]
    merged_comments = collect._merge_comments(previous_comments, latest_comments)
    assert len(merged_comments) == 2


def test_collect_writes_prices_and_refresh_marker(tmp_path, monkeypatch):
    # 收集时把 model-prices 文件读进结果并写出 latest_refresh_at
    # 不调外部命令；用 monkeypatch 替换 gh 调用返回空数据集
    def fake_gh(args):
        if args and args[0] == "issue" and args[1] == "list":
            return []
        if args and args[0] == "pr" and args[1] == "list":
            return []
        if args and args[0] == "issue" and args[1] == "view":
            return []
        raise AssertionError("unexpected: %s" % args)

    def fake_gh_items(args):
        return []

    monkeypatch.setattr(collect, "_gh", fake_gh)
    monkeypatch.setattr(collect, "_gh_items", fake_gh_items)
    prices_path = tmp_path / "prices.json"
    prices_path.write_text(json.dumps(
        {"9router/oro": {"input": 1.5, "output": 6.0,
                          "cache_read": 0.3, "cache_write": 3.75}}),
        encoding="utf-8")
    data_path = tmp_path / "data.json"
    data = collect.collect(stage_parent=9, runs_root=str(tmp_path),
                            data_path=str(data_path),
                            model_prices_path=str(prices_path))
    assert data["model_prices"]["loaded"] is True
    assert data["model_prices"]["prices"]["9router/oro"]["output"] == 6.0
    assert "latest_refresh_at" in data
    # 重新抓一次：仍能续抓（已知工单列表为空），latest_refresh_at 重写
    data2 = collect.collect(stage_parent=9, runs_root=str(tmp_path),
                             data_path=str(data_path),
                             model_prices_path=str(prices_path))
    # 第二次调用覆写了 latest_refresh_at
    with open(data_path, encoding="utf-8") as handle:
        persisted = json.load(handle)
    assert persisted["latest_refresh_at"] == data2["latest_refresh_at"]


def _stub_gh(monkeypatch):
    # 不调外部命令：用 monkeypatch 替换 gh 调用返回空数据集
    def fake_gh(args):
        if args and args[0] == "issue" and args[1] == "list":
            return []
        if args and args[0] == "pr" and args[1] == "list":
            return []
        if args and args[0] == "issue" and args[1] == "view":
            # --jq 已经把评论取成列表
            return []
        raise AssertionError("unexpected: %s" % args)

    def fake_gh_items(args):
        return []

    monkeypatch.setattr(collect, "_gh", fake_gh)
    monkeypatch.setattr(collect, "_gh_items", fake_gh_items)


def _write_previous_data(path, runs, collected_at, runs_collected_at=None):
    payload = {"collected_at": collected_at,
               "stage_parent_issue": 9,
               "scope": {"milestone_prefix": "Stage 3"},
               "issues": [], "pull_requests": [], "stage_comments": [],
               "runs": runs}
    if runs_collected_at:
        payload["runs_collected_at"] = runs_collected_at
    path.write_text(json.dumps(payload), encoding="utf-8")


def _run_file(directory, name, tokens):
    line = ('{"type": "message_end", "message": {"role": "assistant", '
            '"provider": "9router", "model": "oro", "usage": {"input": %d, '
            '"output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": %d, '
            '"cost": {"total": 0}}, "timestamp": 1700000000000, '
            '"completedAt": 1700000001000}}' % (tokens, tokens))
    (directory / name).write_text(line + "\n", encoding="utf-8")


def test_collect_keeps_recorded_runs_when_directory_missing(tmp_path, monkeypatch):
    # 运行目录不存在（本机不是生成运行记录的那台机器）时保留已有 runs，不清空
    _stub_gh(monkeypatch)
    data_path = tmp_path / "data.json"
    recorded = [{"file": "omp-345a.jsonl", "role": "omp", "issue": 345,
                 "round": "a", "requests": 1, "requests_with_usage": 1,
                 "requests_without_usage": 0, "input_tokens": 10,
                 "output_tokens": 0, "cache_read_tokens": 0,
                 "cache_write_tokens": 0, "total_tokens": 10,
                 "reported_cost": 0.0, "models": {}, "started_ms": None,
                 "finished_ms": None, "exit_code": None,
                 "finished_local": None}]
    _write_previous_data(data_path, recorded, "2026-10-07T09:55:24Z")
    data = collect.collect(stage_parent=9,
                           runs_root=str(tmp_path / "不存在目录"),
                           data_path=str(data_path))
    assert data["runs"] == recorded
    assert data["runs_refreshed"] is False
    assert data["runs_collected_at"] == "2026-10-07T09:55:24Z"
    # 工单与评论的刷新时间照常写入，与运行记录的截止时间分开
    assert data["latest_refresh_at"] != "2026-10-07T09:55:24Z"
    result = compute.compute(data)
    report = compute.build_report(result)
    assert "2026-10-07T09:55:24Z，本次未刷新（本机无运行目录）" in report


def test_collect_refreshes_runs_when_directory_exists(tmp_path, monkeypatch):
    # 运行目录存在时重新读取，runs_collected_at 更新为本次时刻
    _stub_gh(monkeypatch)
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _run_file(runs_root, "omp-345a.jsonl", 10)
    data_path = tmp_path / "data.json"
    stale = [{"file": "omp-1a.jsonl", "role": "omp", "issue": 1, "round": "a",
              "requests": 0, "requests_with_usage": 0,
              "requests_without_usage": 0, "input_tokens": 0,
              "output_tokens": 0, "cache_read_tokens": 0,
              "cache_write_tokens": 0, "total_tokens": 0,
              "reported_cost": 0.0, "models": {}, "started_ms": None,
              "finished_ms": None, "exit_code": None, "finished_local": None}]
    _write_previous_data(data_path, stale, "2026-10-07T09:55:24Z",
                         runs_collected_at="2026-10-07T09:55:24Z")
    data = collect.collect(stage_parent=9, runs_root=str(runs_root),
                           data_path=str(data_path))
    assert [run["file"] for run in data["runs"]] == ["omp-345a.jsonl"]
    assert data["runs_refreshed"] is True
    assert data["runs_collected_at"] != "2026-10-07T09:55:24Z"
    report = compute.build_report(compute.compute(data))
    assert "本次未刷新" not in report