"""多次运行的汇总：完成度与正确性、每个指标的噪声范围、费用未知（评测场景设计第 5.2 节）。

守第 13 节的 R2：结果与报告里的汇总形状是公开合同，版本比较与报告页面按它读数。
用例只读真实代码（`report.aggregate`、`report.build_result`、`report.write_report`），
不访问模型服务。
"""

import os
import sys

EVALS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER_DIR = os.path.join(EVALS_DIR, "runner")
if RUNNER_DIR not in sys.path:
    sys.path.insert(0, RUNNER_DIR)

import metrics
import report
import yudao_report

MODEL = "yudao-eval/test-model"
LIMITS = {"context_window": 262_144, "context_window_source": "model_list",
          "max_output_tokens": 64_000, "max_output_tokens_source": "model_list"}


def _run(run_id, completion=0.5, correctness=0.4, cost=0.25, elapsed=10.0):
    return {
        "run_id": run_id,
        "void": False,
        "model_service_failure": False,
        "metrics": {"request_count": 4, "input_tokens": 100, "output_tokens": 20,
                    "cache_read_tokens": 0, "cache_write_tokens": 0,
                    "cost": cost, "elapsed_seconds": elapsed},
        "score": {"completion": completion, "correctness": correctness,
                  "material_version": "scenario-3@2", "scorer_version": "scorer-3@2"},
    }


def _report_text(tmp_path, runs, name="report.md"):
    result = report.build_result("scenario-3", "scenario-3@2", "scorer-3@2", MODEL, runs,
                                 model_capacity=LIMITS)
    path = str(tmp_path / name)
    report.write_report(result, path, [])
    with open(path, encoding="utf-8") as handle:
        return result, handle.read()


def test_summary_holds_the_scorer_completion_and_correctness():
    """汇总里有评分器给出的完成度与正确性（第 5.2 节）。"""
    runs = [_run("run-1", completion=0.5, correctness=0.4),
            _run("run-2", completion=0.75, correctness=0.5)]
    summary = report.aggregate(runs)
    assert summary["completion"] == {"count": 2, "unknown": 0, "mean": 0.625,
                                     "min": 0.5, "max": 0.75, "spread": 0.25}
    assert summary["correctness"]["mean"] == 0.45
    assert summary["correctness"]["min"] == 0.4
    assert summary["correctness"]["max"] == 0.5


def test_noise_range_is_the_extremes_of_the_runs():
    """噪声范围是同一版本各次运行的取值极差（最大值减最小值）。"""
    runs = [_run("run-1", cost=0.1, elapsed=10.0), _run("run-2", cost=0.9, elapsed=30.0)]
    summary = report.aggregate(runs)
    assert summary["elapsed_seconds"]["spread"] == 20.0
    assert abs(summary["cost"]["spread"] - 0.8) < 1e-9


def test_a_single_run_has_no_noise_range(tmp_path):
    """只有一次运行时噪声范围写「未知」，不写零（第 5.2 节）。"""
    summary = report.aggregate([_run("run-1")])
    assert summary["completion"]["spread"] is None

    _, text = _report_text(tmp_path, [_run("run-1")])
    assert "| 完成度 | 0.5 | 0.5 | 0.5 | 未知 | 1 | 0 |" in text
    assert "噪声范围" in text


def test_a_cost_that_is_always_zero_or_missing_stays_unknown(tmp_path):
    """各次请求的费用全为 0 或为空：运行与汇总的费用都是「未知」，不是 0.0。"""
    events = [{"type": "step_finish", "part": {"tokens": {}, "cost": 0}},
              {"type": "step_finish", "part": {"tokens": {}}}]
    collected = metrics.collect({"returncode": 0, "timed_out": False, "elapsed_seconds": 2.0},
                                events)
    assert collected["cost"] is None

    runs = []
    for run_id in ("run-1", "run-2"):
        run = _run(run_id)
        run["metrics"].update(collected)
        runs.append(run)
    summary = report.aggregate(runs)
    assert summary["cost"] == {"count": 2, "unknown": 2}
    _, text = _report_text(tmp_path, runs)
    assert "| 费用 | 未知 | 未知 | 未知 | 未知 | 0 | 2 |" in text


def test_void_runs_stay_out_of_every_summary_column():
    """作废的运行与模型服务故障的运行不进任何一列，也不进噪声范围。"""
    voided = _run("run-void", completion=1.0)
    voided["void"] = True
    failed = _run("run-failed", completion=1.0)
    failed["model_service_failure"] = True
    summary = report.aggregate([_run("run-1", completion=0.5), voided, failed])
    assert summary["completion"] == {"count": 1, "unknown": 0, "mean": 0.5,
                                     "min": 0.5, "max": 0.5, "spread": None}


def test_the_report_records_the_model_capacity_and_its_source(tmp_path):
    """结果与报告写明模型容量的取值与来源（第 3 节「模型的容量」）。"""
    result, text = _report_text(tmp_path, [_run("run-1")])
    assert result["model_capacity"] == LIMITS
    assert "上下文窗口 262144（模型服务的模型列表），单次输出上限 64000（模型服务的模型列表）" in text


def _void_run(run_id="run-void"):
    """作废的运行：初始 PRD 没有被确认，没有事项、没有可以评分的交付（runner 的返回形状）。"""
    return {
        "run_id": run_id,
        "yudao_run_id": None,
        "yudao_commit": "107e1a31",
        "served_model": MODEL,
        "data_dir": "data",
        "source_dir": "source",
        "evidence_dir": "evidence",
        "onboarding": {"run_id": run_id + "-onboarding", "model_requests": 7, "input_tokens": 1200,
                       "output_tokens": 300, "total_tokens": 1500, "elapsed_seconds": 42.5},
        "metrics": {"end_status": "void", "end_reason": "initial_prd_not_confirmed", "outcome": None,
                    "stop_reason": None, "status": None, "cycles": 0, "rework": 0, "collaboration": 0,
                    "model_requests": 0, "input_tokens": None, "output_tokens": None,
                    "cache_read_tokens": None, "cache_write_tokens": None, "total_tokens": None,
                    "cost": None, "model_latency_ms": None, "elapsed_seconds": 0.0,
                    "timed_out": False, "model_service_failure": False, "empty_model_responses": 0,
                    "checkpoints": {}},
        "delivery_files": 0,
        "void": True,
        "void_reason": "initial_prd_not_confirmed",
        "model_service_failure": False,
        "score": None,
    }


def _failed_run(run_id="run-failed"):
    """模型服务故障结束的运行：有事项但没有可以评分的交付。"""
    run = _void_run(run_id)
    run["yudao_run_id"] = "yudao-run-1"
    run["void"] = False
    run["void_reason"] = ""
    run["metrics"].update({"end_status": "failed", "end_reason": "model_service_failure",
                           "model_service_failure": True, "elapsed_seconds": 12.0})
    return run


def test_a_void_run_still_writes_a_chinese_report(tmp_path):
    """守 R1/R2：作废的运行（没有评分器版本）也能出完整中文报告（工单 #1350）。

    报告写明作废原因、跑到哪一步、建档用量与耗时，评分字段写「未评分」；写报告不抛异常。
    """
    run = _void_run()
    result = yudao_report.build_result("scenario-2", "scenario-2@1", None, MODEL, [run],
                                       model_capacity=LIMITS)
    path = str(tmp_path / "void.md")
    yudao_report.write_report(result, path, [yudao_report.run_section(run, None)])
    with open(path, encoding="utf-8") as handle:
        text = handle.read()

    assert "| 评分器版本 | 未评分 |" in text
    assert "| 作废原因 | run-void：initial_prd_not_confirmed |" in text
    assert "| 跑到哪一步 | run-void：建档（initial_prd_not_confirmed，没有新建事项） |" in text
    assert "| 逐条结论与覆盖读数 | 未产生（没有可以评分的交付） |" in text
    assert "没有计入结果的运行。评分（完成度、正确性）与噪声范围：未评分。" in text
    assert "| run-void-onboarding | 7 | 1200 | 300 | 1500 | 42.5 |" in text
    assert "| 评分 | 作废，未评分 |" in text
    assert "这次运行作废：initial_prd_not_confirmed" in text


def test_a_failed_run_still_writes_a_report(tmp_path):
    """守 R1：模型服务故障结束的运行同样能写出报告，评分字段写「未评分」。"""
    run = _failed_run()
    result = yudao_report.build_result("scenario-3", "scenario-3@2", None, MODEL, [run],
                                       model_capacity=LIMITS)
    path = str(tmp_path / "failed.md")
    yudao_report.write_report(result, path, [yudao_report.run_section(run, None)])
    with open(path, encoding="utf-8") as handle:
        text = handle.read()

    assert "| 结束状态 | failed |" in text
    assert "| 结束原因 | model_service_failure |" in text
    assert "| 评分器版本 | 未评分 |" in text
    assert "评分（完成度、正确性）与噪声范围：未评分。" in text
