"""Tests for the Yudao runner, metrics and report.

Offline tests never call a model; the real-run tests need the model service
credentials in the environment and skip without them.
"""

import json
import os
import sys

import pytest

EVALS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER_DIR = os.path.join(EVALS_DIR, "runner")
if RUNNER_DIR not in sys.path:
    sys.path.insert(0, RUNNER_DIR)

import run_yudao_eval
import yudao
import yudao_metrics
import yudao_report

MODEL = "deepseek-v4.1-flash"
REPO_ROOT = EVALS_DIR


def model_credentials_present():
    return bool(os.environ.get(yudao.MODEL_SERVICE_BASE_URL_ENV)
                and os.environ.get(yudao.MODEL_SERVICE_API_KEY_ENV))


needs_model = pytest.mark.skipif(not model_credentials_present(),
                                 reason="model service credentials are not in the environment")


@pytest.fixture
def runs_root(tmp_path):
    root = str(tmp_path / "runs")
    os.makedirs(root)
    return root


# ---------------------------------------------------------------------------
# 起点与隔离

def test_data_directory_is_created_outside_the_repository(runs_root):
    path = yudao.data_dir_for(runs_root, "run-1")
    assert os.path.isdir(path)
    assert not _inside(path, os.path.join(REPO_ROOT, ".."))


def test_data_directory_inside_the_repository_is_rejected():
    inside = os.path.join(REPO_ROOT, "evals", "inside-the-repo")
    with pytest.raises(ValueError, match="outside the Yudao repository"):
        yudao.data_dir_for(os.path.join(REPO_ROOT, "evals"), "inside-the-repo")
    assert not os.path.exists(inside)


def test_material_path_in_the_event_log_voids_the_run():
    log = json.dumps({"summary": "read " + os.path.join(yudao.materials_dir(), "prd.md")})
    hits = yudao.material_path_hits(log)
    assert [hit["part"] for hit in hits] == ["materials"]
    assert "materials" in yudao.describe_hits(hits)


def test_unrelated_paths_do_not_void_the_run():
    assert yudao.material_path_hits(json.dumps({"summary": "read notes/plan.md"})) == []


def test_requirement_text_carries_the_prd_and_the_agreement():
    text = yudao.requirement_text()
    assert "## 需求原文" in text and "## 接口约定" in text
    with open(os.path.join(yudao.materials_dir(), "prd.md"), encoding="utf-8") as handle:
        prd = handle.read()
    assert prd in text


def test_requirement_text_names_the_missing_start_file():
    """起点文件没有进入工作区：运行器如实告诉工程，由工程自己写出这份数据文件。"""
    text = yudao.requirement_text()
    assert "subway_data.json" in text
    assert "data_loader.DATA_FILE_PATH" in text


def test_requirement_text_holds_no_hidden_material():
    text = yudao.requirement_text()
    for part in yudao.hidden_dirs().values():
        assert part not in text
        assert part.replace("\\", "/") not in text


# ---------------------------------------------------------------------------
# 登记命令

def test_registered_commands_match_the_interface_agreement():
    registered = {item["name"]: item for item in yudao.commands()}
    assert set(registered) == {"run_cli", "check_data"}
    for item in registered.values():
        assert item["argv"][1:] == ["src/cli.py"] or item["argv"][1:] == ["src/cli.py", "--check_data"]
    assert registered["check_data"]["argv"][-1] == "--check_data"


def test_registered_commands_name_no_hidden_check():
    """登记命令是通用命令，不含任何隐藏检查（第 3 节「命令」）。"""
    for item in yudao.commands():
        joined = " ".join(item["argv"] + item.get("args", []))
        for part in yudao.hidden_dirs().values():
            assert part not in joined


# ---------------------------------------------------------------------------
# 结束状态与检查点

def _export(outcome="released", events=None, projection=None):
    return {
        "projection": projection or {"outcome": outcome, "stop_reason": None},
        "events": events or [],
        "usage": {},
    }


def test_released_run_is_reported_as_released():
    collected = yudao_metrics.collect(_export(), {"timed_out": False, "elapsed_seconds": 1.0,
                                                   "hidden_failures": []})
    assert collected["end_status"] == "released"


def test_timeout_run_is_reported_with_the_time_limit_reason():
    collected = yudao_metrics.collect(_export("paused"),
                                      {"timed_out": True, "elapsed_seconds": 90.0,
                                       "hidden_failures": []})
    assert collected["end_status"] == "ended"
    assert collected["end_reason"] == yudao_metrics.TIME_LIMIT
    assert collected["timed_out"] is True


def test_metrics_read_cycles_rework_requests_and_usage():
    export = _export(projection={"outcome": "released", "cycle_count": 4, "rework_count": 2,
                                 "request_count": 11})
    export["events"] = [{"type": "collaboration_requested"}, {"type": "collaboration_requested"},
                        {"type": "collaboration_requested"}]
    export["usage"] = {"totals": {"attempts": 11, "input_tokens": 1000, "output_tokens": 250,
                                  "total_tokens": 1250, "cost": 0.5, "latency_ms": 40_000}}
    collected = yudao_metrics.collect(export, {"timed_out": False, "elapsed_seconds": 12.3,
                                               "hidden_failures": []})
    assert collected["cycles"] == 4
    assert collected["rework"] == 2
    assert collected["collaboration"] == 3
    assert collected["model_requests"] == 11
    assert collected["input_tokens"] == 1000
    assert collected["output_tokens"] == 250
    assert collected["elapsed_seconds"] == 12.3


def test_write_before_the_plan_is_accepted_fails_the_checkpoint():
    events = [{"type": "tool_called", "payload": {"name": "write_file"}}]
    checkpoints = yudao_metrics.checkpoints_of(events, "ended", None,
                                               {"timed_out": False, "hidden_failures": []})
    assert checkpoints["no_write_before_plan_accepted"]["passed"] is False


def test_write_after_the_plan_is_accepted_passes_the_checkpoint():
    events = [{"type": "plan_accepted", "payload": {}},
              {"type": "tool_called", "payload": {"name": "write_file"}}]
    checkpoints = yudao_metrics.checkpoints_of(events, "ended", None,
                                               {"timed_out": False, "hidden_failures": []})
    assert checkpoints["no_write_before_plan_accepted"]["passed"] is True


def test_reading_files_before_the_plan_does_not_fail_the_checkpoint():
    events = [{"type": "tool_called", "payload": {"name": "read_file"}},
              {"type": "plan_accepted", "payload": {}},
              {"type": "tool_called", "payload": {"name": "write_file"}}]
    checkpoints = yudao_metrics.checkpoints_of(events, "ended", None,
                                               {"timed_out": False, "hidden_failures": []})
    assert checkpoints["no_write_before_plan_accepted"]["passed"] is True


def test_replay_difference_fails_the_checkpoint():
    replay = {"consistent": False, "differences": ["phase: DONE != PAUSED"]}
    checkpoints = yudao_metrics.checkpoints_of([], "released", replay,
                                               {"timed_out": False, "hidden_failures": []})
    assert checkpoints["replay_consistent"]["passed"] is False
    assert "phase" in checkpoints["replay_consistent"]["detail"]


def test_false_release_is_reported_when_hidden_checks_fail():
    checkpoints = yudao_metrics.checkpoints_of([], "released", None,
                                               {"timed_out": False,
                                                "hidden_failures": ["cmd_3_1b", "unit_5_2"]})
    checkpoint = checkpoints["no_false_release"]
    assert checkpoint["passed"] is False
    assert "cmd_3_1b" in checkpoint["detail"] and "unit_5_2" in checkpoint["detail"]


def test_a_run_without_release_is_not_a_false_release():
    """没有放行就不存在误放行：隐藏检查的失败由评分报告写出，不计为质检的问题。"""
    checkpoints = yudao_metrics.checkpoints_of([], "ended", None,
                                               {"timed_out": False,
                                                "hidden_failures": ["cmd_3_1b"]})
    checkpoint = checkpoints["no_false_release"]
    assert checkpoint["passed"] is True
    assert "没有放行" in checkpoint["detail"]
    assert "cmd_3_1b" in checkpoint["detail"]


def test_request_count_falls_back_to_the_attempts_in_the_usage_report():
    """投影的 request_count 在没有分项统计时是 0，请求数取用量里的 attempts。"""
    export = _export(projection={"outcome": "paused", "request_count": 0})
    export["usage"] = {"totals": {"attempts": 11, "total_tokens": 216_649, "latency_ms": 386_341}}
    collected = yudao_metrics.collect(export, {"timed_out": False, "elapsed_seconds": 5.0,
                                               "hidden_failures": []})
    assert collected["model_requests"] == 11
    assert collected["total_tokens"] == 216_649


def test_reported_input_tokens_are_absent_and_count_as_zero():
    export = _export(projection={"outcome": "paused"})
    export["usage"] = {"totals": {"attempts": 11, "input_tokens": None, "output_tokens": None,
                                  "total_tokens": 216_649}}
    collected = yudao_metrics.collect(export, {"timed_out": False, "elapsed_seconds": 5.0,
                                               "hidden_failures": []})
    assert collected["input_tokens"] == 0
    assert collected["output_tokens"] == 0


def test_model_service_failure_is_recognised():
    events = [{"type": "model_attempt_failed", "payload": {"error": {"name": "APIError"}}}]
    collected = yudao_metrics.collect(_export("failed", events),
                                      {"timed_out": False, "elapsed_seconds": 1.0,
                                       "hidden_failures": []})
    assert collected["model_service_failure"] is True
    assert collected["end_reason"] == yudao_metrics.MODEL_SERVICE_FAILURE


def test_a_normal_release_is_not_a_model_service_failure():
    collected = yudao_metrics.collect(_export(), {"timed_out": False, "elapsed_seconds": 1.0,
                                                   "hidden_failures": []})
    assert collected["model_service_failure"] is False


# ---------------------------------------------------------------------------
# 结果与报告

def _scores(**overrides):
    scores = {"completion": 0.75, "correctness": 0.9, "not_done_count": 1, "wrong_count": 1,
              "requirements": {"R1": {"passed": 3, "total": 3, "score": 1.0},
                               "R2": {"passed": 1, "total": 2, "score": 0.5}},
              "checks": [{"id": "unit_2_3", "status": "pass", "detail": ""},
                         {"id": "cmd_3_1b", "status": "wrong", "detail": "no distance"}]}
    scores.update(overrides)
    return scores


def _run(**overrides):
    run = {"run_id": "yudao-run-1", "void": False, "void_reason": "", "delivery_files": 5,
           "metrics": yudao_metrics.collect(_export(), {"timed_out": False, "elapsed_seconds": 20.0,
                                                        "hidden_failures": ["cmd_3_1b"]})}
    run.update(overrides)
    return run


def test_result_records_the_yudao_commit_and_the_host_environment():
    result = yudao_report.build_result("scenario-3", "scenario-3@2", "scorer-3@2", MODEL,
                                        [_run()], yudao_commit="abc1234")
    assert result["side"] == "yudao"
    assert result["yudao_commit"] == "abc1234"
    assert result["host_environment"]["python"]
    assert result["network"]["allowed"] is False


def test_result_aggregates_mean_min_and_max():
    runs = [_run(), _run(run_id="yudao-run-2")]
    runs[1]["metrics"] = yudao_metrics.collect(
        _export(projection={"outcome": "released", "cycle_count": 8, "request_count": 20}),
        {"timed_out": False, "elapsed_seconds": 40.0, "hidden_failures": []})
    summary = yudao_report.aggregate_metrics(runs)
    assert summary["elapsed_seconds"] == {"count": 2, "mean": 30.0, "min": 20.0, "max": 40.0}


def test_void_and_model_service_failures_stay_out_of_the_summary():
    runs = [_run(), _run(run_id="v", void=True, void_reason="材料路径"),
            _run(run_id="f")]
    runs[2]["metrics"] = yudao_metrics.collect(
        _export("failed", [{"type": "model_attempt_failed", "payload": {"error": "APIError"}}]),
        {"timed_out": False, "elapsed_seconds": 60.0, "hidden_failures": []})
    result = yudao_report.build_result("scenario-3", "scenario-3@2", "scorer-3@2", MODEL,
                                        runs, yudao_commit="abc1234")
    assert result["run_count"] == 1
    assert result["summary"]["elapsed_seconds"]["count"] == 1
    assert result["void_runs"] == ["v"]


def test_report_writes_every_metric_and_checkpoint(tmp_path):
    run = _run()
    result = yudao_report.build_result("scenario-3", "scenario-3@2", "scorer-3@2", MODEL,
                                        [run], yudao_commit="abc1234",
                                        notes=[run_yudao_eval.START_GAP_NOTE])
    path = str(tmp_path / "report.md")
    yudao_report.write_report(result, path, [yudao_report.run_section(run, _scores())])
    text = open(path, encoding="utf-8").read()
    assert "Yudao 提交号 | abc1234" in text
    assert "循环次数" in text and "返工次数" in text and "部门之间询问次数" in text
    assert "模型请求数" in text and "耗时（秒）" in text
    assert "质检没有误放行" in text
    assert "起点缺口" in text
    assert "cmd_3_1b" in text


def _inside(path, parent):
    path = os.path.normcase(os.path.abspath(path))
    parent = os.path.normcase(os.path.abspath(parent))
    return path == parent or path.startswith(parent + os.sep)


# ---------------------------------------------------------------------------
# 真实运行（需要模型服务凭据）

@needs_model
def test_real_run_produces_metrics_a_score_and_a_report(runs_root, tmp_path):
    """真实运行一次 Yudao：指标、五项过程检查点、评分与报告都在。"""
    evidence_root = os.path.join(yudao_report.default_evidence_dir(), yudao.SCENARIO,
                                 "yudao-tests")
    run = run_yudao_eval.run_once("yudao-real-1", runs_root, evidence_root,
                                  MODEL, 90 * 60)
    assert run["metrics"]["model_requests"] > 0
    assert run["metrics"]["elapsed_seconds"] > 0
    assert set(run["metrics"]["checkpoints"]) == {
        "ended_within_limit", "quality_release_bound_to_delivery",
        "no_write_before_plan_accepted", "replay_consistent", "no_false_release"}
    assert os.path.exists(os.path.join(run["evidence_dir"], "run-export.json"))
    assert os.path.exists(os.path.join(run["evidence_dir"], "scoring", "score.json"))
    assert 0.0 <= run["score"]["completion"] <= 1.0


@needs_model
def test_time_limit_ends_the_run_and_marks_it(runs_root):
    """时间上限到达时事项被结束，按结束时的交付评分并标记超时。"""
    evidence_root = os.path.join(yudao_report.default_evidence_dir(), yudao.SCENARIO,
                                 "yudao-tests")
    run = run_yudao_eval.run_once("yudao-limit-1", runs_root, evidence_root,
                                  MODEL, 120.0)
    assert run["metrics"]["timed_out"] is True
    assert run["metrics"]["end_reason"] == yudao_metrics.TIME_LIMIT
    assert 0.0 <= run["score"]["completion"] <= 1.0