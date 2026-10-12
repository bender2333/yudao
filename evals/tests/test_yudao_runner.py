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
    """构造一次 `run.export`：终端事件决定阶段与停止原因，未给时按 outcome 生成。"""
    if events is None:
        if outcome == "released":
            events = [{"type": "run_done", "state_after": "DONE",
                       "stop_reason": "released", "payload": {"stop_reason": "released"}}]
        elif outcome == "paused":
            events = [{"type": "run_paused", "state_after": "PAUSED",
                       "stop_reason": "no_tool_call", "payload": {"stop_reason": "no_tool_call"}}]
        elif outcome == "failed":
            events = [{"type": "run_failed", "state_after": "FAILED",
                       "stop_reason": "provider_error", "payload": {"stop_reason": "provider_error"}}]
        else:
            events = []
    base = {"outcome": "done" if outcome == "released" else outcome,
            "stop_reason": "released" if outcome == "released" else None,
            "phase": "DONE" if outcome == "released" else None}
    if projection:
        base.update(projection)
    return {"projection": base, "events": events, "usage": {}}


def _release_events(binding="match", coverage=None):
    """一次放行的事件：质检放行绑定最后一次封存的交付。"""
    delivery_tree = "tree-a" if binding == "match" else "tree-b"
    events = [
        {"type": "run_created", "payload": {"run_time_limit_sec": 7200,
                                            "parameters_version": "sha256:test"}},
        {"type": "department_activated", "department": "quality",
         "payload": {"activation_id": "act-qa-1"}},
        {"type": "plan_accepted", "payload": {}},
        {"type": "delivery_accepted",
         "payload": {"code_tree_digest": "tree-a", "content_hash": "spec-a",
                     "checks": [{"name": "smoke"}]}},
        {"type": "qa_submitted",
         "payload": {"verdict": "release", "code_snapshot_hash": delivery_tree,
                     "delivery_spec_hash": "spec-a",
                     "checks": [{"name": "smoke", "activation_id": "act-qa-1",
                                 "snapshot_hash": delivery_tree}]}},
        {"type": "run_done", "state_after": "DONE",
         "stop_reason": "released", "payload": {"stop_reason": "released"}},
    ]
    if coverage is not None:
        events[4]["payload"]["coverage"] = coverage
    return events


def test_released_run_is_reported_as_released():
    collected = yudao_metrics.collect(_export(), {"timed_out": False, "elapsed_seconds": 1.0,
                                                   "hidden_failures": []})
    assert collected["end_status"] == "released"
    assert collected["outcome"] == "done"
    assert collected["stop_reason"] == "released"
    assert collected["phase"] == "DONE"


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


def test_usage_that_the_model_did_not_report_is_unknown_not_zero():
    """模型服务没有上报的用量记未知：不记 0、不进均值（第 5.2 节）。"""
    export = _export(projection={"outcome": "paused"})
    export["usage"] = {"totals": {"attempts": 11, "input_tokens": None, "output_tokens": None,
                                  "total_tokens": 216_649, "cost": None}}
    collected = yudao_metrics.collect(export, {"timed_out": False, "elapsed_seconds": 5.0,
                                               "hidden_failures": []})
    assert collected["input_tokens"] is None
    assert collected["output_tokens"] is None
    assert collected["cost"] is None
    assert collected["total_tokens"] == 216_649


def test_missing_usage_fields_are_unknown():
    """字段整个缺失与上报为 None 同样是未知。"""
    export = _export(projection={"outcome": "paused"})
    export["usage"] = {"totals": {"attempts": 11, "total_tokens": 216_649}}
    collected = yudao_metrics.collect(export, {"timed_out": False, "elapsed_seconds": 5.0,
                                               "hidden_failures": []})
    assert collected["input_tokens"] is None
    assert collected["output_tokens"] is None
    assert collected["cost"] is None


def test_unknown_usage_stays_out_of_the_aggregate():
    """未知样本不进均值、最小值与最大值；统计列写出未知样本数与原因。"""
    run = _run()
    run["metrics"].update({"input_tokens": None, "output_tokens": None, "cost": None,
                           "total_tokens": None, "elapsed_seconds": 20.0})
    summary = yudao_report.aggregate_metrics([run])
    assert summary["input_tokens"]["unknown"] == 1
    assert "mean" not in summary["input_tokens"]
    assert "模型服务未上报输入用量" in summary["input_tokens"]["unknown_reason"]
    known = _run(run_id="known")
    known["metrics"].update({"input_tokens": 5000, "output_tokens": 200, "cost": 0.25,
                             "total_tokens": 5200, "elapsed_seconds": 30.0})
    summary = yudao_report.aggregate_metrics([run, known])
    assert summary["input_tokens"]["unknown"] == 1
    assert summary["input_tokens"]["mean"] == 5000.0
    assert summary["input_tokens"]["count"] == 2


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
# 六项过程检查点（设计第 5.1 节）

# 系统事件序列（fake 适配器）：harness 自带的测试序列，文件头 `adapter: fake`。
# 它们用于驱动同一套 `run.export` 形状的判定逻辑；真实系统导出的证据不可取回
# （issue-192 的 `.yudao/evals/` 不在本仓库），凡是需要真实导出才能核实的项一律记
# 「未核实」，不把这些序列当作真实系统导出。
FIXTURES = os.path.abspath(os.path.join(EVALS_DIR, "..", "harness", "tests",
                                        "event_sequences"))


def _load_fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)

def test_release_checkpoint_passes_on_handoff_release_fixture():
    """第一项四项同检：系统事件序列（fake 适配器）里的放行记录必须通过。"""
    export = _load_fixture("handoff_release.json")
    params = next(e["payload"] for e in export["events"] if e["type"] == "run_created").get(
        "parameters_version")
    collected = yudao_metrics.collect(export, {"timed_out": False, "elapsed_seconds": 1.0,
                                               "hidden_failures": []}, None, params)
    assert collected["checkpoints"]["ended_within_limit"]["passed"] is True
    assert collected["end_status"] == "released"
    assert collected["outcome"] == "done"
    assert collected["stop_reason"] == "released"
    assert collected["phase"] == "DONE"

def test_release_checkpoint_fails_on_no_tool_call_pause():
    """第一项四项同检：no_tool_call 暂停不算放行。"""
    export = _load_fixture("no_tool_call_pause.json")
    collected = yudao_metrics.collect(export, {"timed_out": False, "elapsed_seconds": 1.0,
                                               "hidden_failures": []}, None, None)
    assert collected["end_status"] == "ended"
    assert collected["checkpoints"]["ended_within_limit"]["passed"] is False
    assert "不是 released" in collected["checkpoints"]["ended_within_limit"]["detail"]


def test_release_checkpoint_fails_on_a_cancellation():
    """第一项四项同检：取消的运行不算放行。"""
    export = _load_fixture("request_time_unavailable_cancel.json")
    collected = yudao_metrics.collect(export, {"timed_out": False, "elapsed_seconds": 1.0,
                                               "hidden_failures": []}, None, None)
    assert collected["end_status"] == "ended"
    assert collected["checkpoints"]["ended_within_limit"]["passed"] is False
    assert "不是 released" in collected["checkpoints"]["ended_within_limit"]["detail"]


def test_release_checkpoint_fails_on_a_time_limit():
    """第一项四项同检：运行到时间上限不算放行（运行器结束）。"""
    export = _load_fixture("time_limit.json")
    collected = yudao_metrics.collect(export, {"timed_out": True, "elapsed_seconds": 150.0,
                                               "hidden_failures": []}, None, None)
    assert collected["checkpoints"]["ended_within_limit"]["passed"] is False
    assert "时间上限" in collected["checkpoints"]["ended_within_limit"]["detail"]


def test_release_checkpoint_fails_on_a_provider_error():
    """第一项四项同检：模型服务故障不算放行。"""
    # 构造：retry_exhausted.json 的事件没有 ProviderError 字样，改写私有副本的
    # `model_attempt_failed` 错误字段（`_load_fixture` 每次 `json.load` 返回的是本次
    # 独有副本，不影响其他测试），再跑同一套判定。
    export = _load_fixture("retry_exhausted.json")
    for event in export["events"]:
        if event["type"] == "model_attempt_failed":
            event["error"] = "ProviderError"
            event["payload"]["error"] = "ProviderError"
    collected = yudao_metrics.collect(export, {"timed_out": False, "elapsed_seconds": 60.0,
                                               "hidden_failures": []}, None, None)
    assert collected["end_status"] == "ended"
    assert collected["end_reason"] == yudao_metrics.MODEL_SERVICE_FAILURE
    assert collected["checkpoints"]["ended_within_limit"]["passed"] is False
    assert "模型服务故障" in collected["checkpoints"]["ended_within_limit"]["detail"]

def test_release_binding_passes_when_qa_review_and_delivery_match():
    """第二项：放行引用的快照与最后一次封存一致；recheck_ratio 只在冻结参数可识别时核对。"""
    export = _load_fixture("handoff_release.json")
    params = next(e["payload"] for e in export["events"] if e["type"] == "run_created").get(
        "parameters_version")
    collected = yudao_metrics.collect(export, {"timed_out": False, "elapsed_seconds": 1.0,
                                               "hidden_failures": []}, None, params)
    checkpoint = collected["checkpoints"]["quality_release_bound_to_delivery"]
    assert checkpoint["passed"] is None  # 冻结参数的 ratio 未在导出中给出，记未核实
    assert checkpoint["recheck_ratio"] is None
    assert checkpoint["recheck_ratio_status"] == "unverified"
    assert checkpoint["checks_total"] == 1
    assert checkpoint["self_run"] == 1


def test_release_binding_fails_when_qa_review_and_delivery_differ():
    """第二项：放行引用与最后一次封存不同，绑定核对不通过。"""
    export = _load_fixture("handoff_release.json")
    review = next(e for e in export["events"] if e["type"] == "qa_submitted")
    review["payload"]["code_snapshot_hash"] = "tree-other"
    params = next(e["payload"] for e in export["events"] if e["type"] == "run_created").get(
        "parameters_version")
    collected = yudao_metrics.collect(export, {"timed_out": False, "elapsed_seconds": 1.0,
                                               "hidden_failures": []}, None, params)
    checkpoint = collected["checkpoints"]["quality_release_bound_to_delivery"]
    assert checkpoint["passed"] is False
    assert "交付快照" in checkpoint["detail"]


def test_release_binding_is_unverified_when_ratio_is_unreadable():
    """第二项：`parameters_version` 只是参数内容摘要，不含参数现值。

    导出中取不到冻结的 `verification.recheck_ratio` 时（`run_created` 的
    `parameters_version` 缺失、不可识别或只是摘要），比例核对记「未核实」，
    不用仓库内文件顶替；绑定本身仍按摘要与回执引用核对。
    """
    export = _load_fixture("handoff_release.json")
    review = next(e for e in export["events"] if e["type"] == "qa_submitted")
    review["payload"]["checks"] = [{"name": "smoke", "activation_id": "act-other",
                                    "snapshot_hash": review["payload"]["code_snapshot_hash"]}]
    params = next(e["payload"] for e in export["events"] if e["type"] == "run_created").get(
        "parameters_version")
    collected = yudao_metrics.collect(export, {"timed_out": False, "elapsed_seconds": 1.0,
                                               "hidden_failures": []}, None, params)
    checkpoint = collected["checkpoints"]["quality_release_bound_to_delivery"]
    assert checkpoint["self_run"] == 0
    assert checkpoint["recheck_ratio"] is None
    assert checkpoint["recheck_ratio_status"] == "unverified"
    assert checkpoint["passed"] is None
    # 摘要可识别时仍只确认已冻结，比例仍取不到，仍按未核实
    fixed = yudao_metrics.collect(export, {"timed_out": False, "elapsed_seconds": 1.0,
                                            "hidden_failures": []}, None,
                                   "sha256:frozen")
    fixed_checkpoint = fixed["checkpoints"]["quality_release_bound_to_delivery"]
    assert fixed_checkpoint["recheck_ratio_status"] == "frozen"
    assert fixed_checkpoint["passed"] is None


def test_release_coverage_is_unknown_when_per_data_is_absent():
    """第六项：放行记录没有逐条覆盖数据时写未知。"""
    export = _load_fixture("handoff_release.json")
    params = next(e["payload"] for e in export["events"] if e["type"] == "run_created").get(
        "parameters_version")
    collected = yudao_metrics.collect(export, {"timed_out": False, "elapsed_seconds": 1.0,
                                               "hidden_failures": []}, None, params)
    checkpoint = collected["checkpoints"]["release_coverage"]
    assert checkpoint["passed"] is None
    assert checkpoint["covered_ratio"] is None
    assert "未核实" in checkpoint["detail"]


def test_release_coverage_passes_with_full_coverage():
    """第六项：放行记录给出完整覆盖时通过。"""
    export = _load_fixture("handoff_release.json")
    review = next(e for e in export["events"] if e["type"] == "qa_submitted")
    review["payload"]["coverage"] = {"covered_ratio": 1.0, "model_read_count": 0,
                                     "open_loop_count": 0}
    params = next(e["payload"] for e in export["events"] if e["type"] == "run_created").get(
        "parameters_version")
    collected = yudao_metrics.collect(export, {"timed_out": False, "elapsed_seconds": 1.0,
                                               "hidden_failures": []}, None, params)
    checkpoint = collected["checkpoints"]["release_coverage"]
    assert checkpoint["passed"] is True
    assert checkpoint["covered_ratio"] == 1.0
    assert checkpoint["model_read_count"] == 0
    assert checkpoint["open_loop_count"] == 0


def test_release_coverage_fails_with_open_loop_conditions():
    """第六项：放行记录给出开环条件时，第六项不通过。"""
    export = _load_fixture("handoff_release.json")
    review = next(e for e in export["events"] if e["type"] == "qa_submitted")
    review["payload"]["coverage"] = {"covered_ratio": 1.0, "model_read_count": 0,
                                     "open_loop_count": 1}
    review["payload"]["open_loop_conditions"] = ["R-3"]
    params = next(e["payload"] for e in export["events"] if e["type"] == "run_created").get(
        "parameters_version")
    collected = yudao_metrics.collect(export, {"timed_out": False, "elapsed_seconds": 1.0,
                                               "hidden_failures": []}, None, params)
    checkpoint = collected["checkpoints"]["release_coverage"]
    assert checkpoint["passed"] is False
    assert "R-3" in checkpoint["detail"]


def test_release_coverage_is_not_applicable_without_a_release():
    """第六项：没有放行时本项不适用。"""
    collected = yudao_metrics.collect(_export("paused"), {"timed_out": False, "elapsed_seconds": 1.0,
                                                          "hidden_failures": []}, None, None)
    checkpoint = collected["checkpoints"]["release_coverage"]
    assert checkpoint["passed"] is True
    assert checkpoint["applicable"] is False
    assert "不适用" in checkpoint["detail"]


def test_checkpoints_cover_all_six_items():
    """六项检查点：键集合固定。"""
    collected = yudao_metrics.collect(_export("paused"), {"timed_out": False, "elapsed_seconds": 1.0,
                                                          "hidden_failures": []}, None, None)
    assert set(collected["checkpoints"]) == {
        "ended_within_limit", "quality_release_bound_to_delivery",
        "no_write_before_plan_accepted", "replay_consistent",
        "no_false_release", "release_coverage"}


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
    assert summary["elapsed_seconds"] == {"count": 2, "unknown": 0, "mean": 30.0,
                                          "min": 20.0, "max": 40.0}


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
    run["metrics"].update({"input_tokens": None, "output_tokens": None, "cost": None,
                           "total_tokens": None})
    result = yudao_report.build_result("scenario-3", "scenario-3@2", "scorer-3@2", MODEL,
                                        [run], yudao_commit="abc1234",
                                        notes=[run_yudao_eval.START_GAP_NOTE],
                                        comparison={"compared": False,
                                                    "verdict": "blocked",
                                                    "block_reason": "示例受阻",
                                                    "material_version": "scenario-3@2",
                                                    "scorer_version": "scorer-3@2",
                                                    "paired_tasks": [],
                                                    "noise": None,
                                                    "primary": {"metric": "qa_false_release",
                                                                "current": None,
                                                                "baseline": None,
                                                                "difference": None},
                                                    "secondary": []})
    path = str(tmp_path / "report.md")
    yudao_report.write_report(result, path, [yudao_report.run_section(run, _scores())])
    text = open(path, encoding="utf-8").read()
    assert "Yudao 提交号 | abc1234" in text
    assert "循环次数" in text and "返工次数" in text and "部门之间询问次数" in text
    assert "模型请求数" in text and "耗时（秒）" in text
    assert "质检没有误放行" in text
    assert "起点缺口" in text
    assert "cmd_3_1b" in text
    assert "未知" in text  # 未知用量写为「未知」
    assert "八、版本比较" in text
    assert "九、起点缺口与运行条件" in text
    assert "示例受阻" in text


def _comparison_run(run_id, false_release=False, completion=0.5, failed=frozenset()):
    metrics = yudao_metrics.collect(_export("released"), {"timed_out": False,
                                                           "elapsed_seconds": 20.0,
                                                           "hidden_failures": []})
    for key in failed:
        metrics["checkpoints"][key] = {"passed": False, "detail": "人工置为失败"}
    if false_release:
        metrics["checkpoints"]["no_false_release"] = {"passed": False, "detail": "人工置为失败"}
    return {"run_id": run_id, "void": False, "void_reason": "", "delivery_files": 0,
            "metrics": metrics, "score": {"completion": completion}}


def test_version_compare_refuses_when_versions_differ():
    """版本比较：材料或评分器版本不同直接拒绝，保留已算字段为空。"""
    import yudao_compare
    runs = [_comparison_run("task-1")]
    current = yudao_report.build_result("scenario-3", "scenario-3@2", "scorer-3@2", MODEL,
                                          runs, yudao_commit="abc1234")
    baseline = yudao_report.build_result("scenario-3", "scenario-3@1", "scorer-3@2", MODEL,
                                          runs, yudao_commit="abc1234")
    comparison = yudao_compare.compare(current, baseline)
    assert comparison["verdict"] == "blocked"
    assert "材料版本或评分器版本不同" in comparison["block_reason"]
    assert comparison["paired_tasks"] == []
    assert comparison["primary"]["difference"] is None


def test_version_compare_improvement_no_difference_regression_and_blocked():
    """三种结论加受阻：改进、无差别、退化，以及缺少逐任务评分。"""
    import yudao_compare

    def build(runs):
        return yudao_report.build_result("scenario-3", "scenario-3@2", "scorer-3@2", MODEL,
                                         runs, yudao_commit="abc1234")

    improved = yudao_compare.compare(
        build([_comparison_run("task-1", false_release=False, completion=0.6)]),
        build([_comparison_run("task-1", false_release=True, completion=0.4)]))
    assert improved["verdict"] == "improved"
    assert improved["primary"]["difference"] == -1
    same = yudao_compare.compare(
        build([_comparison_run("task-1", completion=0.5)]),
        build([_comparison_run("task-1", completion=0.5)]))
    assert same["verdict"] == "no_difference"
    regressed = yudao_compare.compare(
        build([_comparison_run("task-1", completion=0.5,
                                failed=frozenset(["no_write_before_plan_accepted"]))]),
        build([_comparison_run("task-1", completion=0.5)]))
    assert regressed["verdict"] == "regressed"
    false_release_regressed = yudao_compare.compare(
        build([_comparison_run("task-1", false_release=True, completion=0.6)]),
        build([_comparison_run("task-1", false_release=False, completion=0.6)]))
    assert false_release_regressed["verdict"] == "regressed"
    assert false_release_regressed["primary"]["difference"] == 1
    # 受阻：一侧唯一的运行不计入结果，另一侧没有可配对任务
    voided = _comparison_run("task-1")
    voided["void"] = True
    blocked = yudao_compare.compare(build([voided]), build([_comparison_run("task-1")]))
    assert blocked["verdict"] == "blocked"
    assert "可配对" in blocked["block_reason"]


def _inside(path, parent):
    path = os.path.normcase(os.path.abspath(path))
    parent = os.path.normcase(os.path.abspath(parent))
    return path == parent or path.startswith(parent + os.sep)



def test_process_exit_failure_is_not_a_release():
    """构造：harness 没有现成的进程退出事件序列。事件序列仍用 retry_exhausted.json
    （fake 适配器，事件里没有 `process_exit_failed` 标志），通过 outcome 标志触发
    运行器进程退出码非零分支：放行记未通过，停止原因取原始值。"""
    export = _load_fixture("retry_exhausted.json")
    outcome = {"timed_out": False, "elapsed_seconds": 60.0,
               "hidden_failures": [], "process_exit_failed": True}
    collected = yudao_metrics.collect(export, outcome, None, None)
    assert collected["checkpoints"]["ended_within_limit"]["passed"] is False
    assert "进程退出码非零" in collected["checkpoints"]["ended_within_limit"]["detail"]
    assert collected["end_reason"] != yudao_metrics.MODEL_SERVICE_FAILURE

# ---------------------------------------------------------------------------
# 真实运行（需要模型服务凭据）

@needs_model
def test_real_run_produces_metrics_a_score_and_a_report(runs_root, tmp_path):
    """真实运行一次 Yudao：指标、六项过程检查点、评分与报告都在。"""
    evidence_root = os.path.join(yudao_report.default_evidence_dir(), yudao.SCENARIO,
                                 "yudao-tests")
    run = run_yudao_eval.run_once("yudao-real-1", runs_root, evidence_root,
                                  MODEL, 90 * 60)
    assert run["metrics"]["model_requests"] > 0
    assert run["metrics"]["elapsed_seconds"] > 0
    assert set(run["metrics"]["checkpoints"]) == {
        "ended_within_limit", "quality_release_bound_to_delivery",
        "no_write_before_plan_accepted", "replay_consistent",
        "no_false_release", "release_coverage"}
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