"""Tests for the OpenCode runner.

They run the real opencode binary with a real model, build real run
directories outside the repository and score the real delivery. No mock is
used: the model service credentials come from the user's environment
variables, so the tests are skipped when they are absent.
"""

import json
import os
import re
import sys

import pytest

EVALS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER_DIR = os.path.join(EVALS_DIR, "runner")
if RUNNER_DIR not in sys.path:
    sys.path.insert(0, RUNNER_DIR)

import metrics
import opencode
import report
import run_eval
import scenario3

MODEL = "yudao-eval/cbcn/deepseek-v4.1-flash"
MODEL_ID = "cbcn/deepseek-v4.1-flash"
SCENARIO = scenario3
REPO_ROOT = EVALS_DIR


def model_credentials_present():
    return bool(os.environ.get(opencode.MODEL_SERVICE_BASE_URL_ENV)
                and os.environ.get(opencode.MODEL_SERVICE_API_KEY_ENV))


needs_model = pytest.mark.skipif(not model_credentials_present(),
                                 reason="model service credentials are not in the environment")


@pytest.fixture
def runs_root(tmp_path):
    root = str(tmp_path / "runs")
    os.makedirs(root)
    return root


def test_run_directory_holds_only_the_starting_point(runs_root):
    run_dir = opencode.create_run_dir(runs_root, "start-only", MODEL, MODEL_ID)
    names = set(os.listdir(run_dir))
    assert names == {"PRD.md", "interface_agreement.md", "subway_data.json",
                     "manifest.json", ".git", ".opencode-config"}

    # 隐藏检查、条目表与参考实现不在运行目录中
    for label, path in scenario3.hidden_dirs().items():
        assert not _inside(run_dir, path), label
    assert {"checks", "reference", "requirement-table.json"}.isdisjoint(names)




def test_run_directory_inside_the_repository_is_rejected():
    inside = os.path.join(REPO_ROOT, "evals", "inside-the-repo")
    with pytest.raises(ValueError, match="outside the Yudao repository"):
        opencode.create_run_dir(inside, "run-1", MODEL, MODEL_ID)
    assert not os.path.exists(inside)


def test_existing_run_directory_is_rejected(runs_root):
    opencode.create_run_dir(runs_root, "once", MODEL, MODEL_ID)
    with pytest.raises(ValueError, match="already exists"):
        opencode.create_run_dir(runs_root, "once", MODEL, MODEL_ID)


def test_run_configuration_denies_fetch_and_search(runs_root):
    run_dir = opencode.create_run_dir(runs_root, "config", MODEL, MODEL_ID)
    with open(os.path.join(run_dir, ".opencode-config", "opencode.json"),
              encoding="utf-8") as handle:
        config = json.load(handle)
    assert config["permission"]["webfetch"] == "deny"
    assert config["permission"]["websearch"] == "deny"
    # 凭据不写进配置，用环境变量引用
    assert config["provider"]["yudao-eval"]["options"]["apiKey"] == \
        "{env:" + opencode.MODEL_SERVICE_API_KEY_ENV + "}"
    assert opencode.MODEL_SERVICE_API_KEY_ENV not in json.dumps(config).replace(
        "{env:" + opencode.MODEL_SERVICE_API_KEY_ENV + "}", "")
    if os.environ.get(opencode.MODEL_SERVICE_API_KEY_ENV):
        assert os.environ[opencode.MODEL_SERVICE_API_KEY_ENV] not in json.dumps(config)


def test_message_points_at_the_same_materials_the_run_directory_has(runs_root):
    run_dir = opencode.create_run_dir(runs_root, "inputs", MODEL, MODEL_ID)
    attached = scenario3.message_files(run_dir)
    assert [os.path.basename(path) for path in attached] == \
        ["PRD.md", "interface_agreement.md", "subway_data.json"]
    for path in attached:
        assert os.path.exists(path)
    # 附加的文件就是交给 Yudao 一侧的同一份公开材料
    with open(os.path.join(run_dir, "PRD.md"), encoding="utf-8") as handle:
        delivered_prd = handle.read()
    with open(os.path.join(scenario3.materials_dir(), "prd.md"), encoding="utf-8") as handle:
        assert handle.read() == delivered_prd


def test_command_line_fits_the_windows_limit(runs_root):
    """Windows 的命令行有长度上限，材料全文放进命令行会被系统拒绝。"""
    run_dir = opencode.create_run_dir(runs_root, "limits", MODEL, MODEL_ID)
    command = opencode.build_command(run_dir, MODEL)
    length = sum(len(item) for item in command)
    assert length < 8000, length


def test_material_path_in_output_voids_the_run():
    materials = scenario3.materials_dir()
    assert opencode.material_path_hits("read " + materials)
    assert opencode.material_path_hits("read " + materials.replace("\\", "/"))
    assert opencode.material_path_hits("read " + scenario3.hidden_dirs()["checks"])
    # 运行目录本身的路径不是泄漏
    assert opencode.material_path_hits("read C:/runs/run-1/PRD.md") == []
    assert opencode.material_path_hits("read C:/project/notes.md") == []


def test_network_tool_calls_are_found():
    events = [{"type": "tool_use", "part": {"type": "tool", "tool": "webfetch",
                                            "state": {"status": "completed", "output": ""}}}]
    calls = opencode.tool_calls(events)
    assert [call["tool"] for call in opencode.network_tool_calls(calls)] == ["webfetch"]

    events = [{"type": "tool_use", "part": {"type": "tool", "tool": "write",
                                            "state": {"status": "completed", "output": "ok"}}}]
    assert opencode.network_tool_calls(opencode.tool_calls(events)) == []


def test_metrics_count_requests_tokens_and_elapsed():
    events = [
        {"type": "step_finish", "part": {"tokens": {"input": 100, "output": 20,
                                                    "cache": {"read": 5, "write": 1}},
                                          "cost": 0.1}},
        {"type": "tool_use", "part": {"type": "tool", "tool": "write",
                                     "state": {"status": "completed", "output": "ok"}}},
        {"type": "step_finish", "part": {"tokens": {"input": 30, "output": 7,
                                                    "cache": {"read": 0, "write": 0}},
                                          "cost": 0.2}},
    ]
    outcome = {"returncode": 0, "timed_out": False, "elapsed_seconds": 12.5}
    collected = metrics.collect(outcome, events)
    assert collected["request_count"] == 2
    assert collected["input_tokens"] == 130
    assert collected["output_tokens"] == 27
    assert collected["cache_read_tokens"] == 5
    assert collected["cache_write_tokens"] == 1
    assert collected["elapsed_seconds"] == 12.5
    assert collected["reason"] == "stop"
    assert collected["timed_out"] is False


def test_metrics_mark_a_timeout_run():
    outcome = {"returncode": 1, "timed_out": True, "elapsed_seconds": 60.0}
    collected = metrics.collect(outcome, [])
    assert collected["timed_out"] is True
    assert collected["reason"] == "time_limit"


def test_metrics_recognise_a_model_service_failure():
    events = [{"type": "error", "error": {"name": "APIError",
                                          "data": {"message": "503 Service Unavailable"}}}]
    outcome = {"returncode": 1, "timed_out": False, "elapsed_seconds": 3.0}
    collected = metrics.collect(outcome, events)
    assert collected["model_service_failure"] is True
    assert collected["reason"] == metrics.MODEL_SERVICE_FAILURE


def test_metrics_do_not_mark_a_normal_stop_as_service_failure():
    outcome = {"returncode": 0, "timed_out": False, "elapsed_seconds": 3.0}
    assert metrics.collect(outcome, [])["model_service_failure"] is False


def test_unparseable_lines_are_ignored():
    events = opencode.parse_events('{"type": "text"}\nnot json\n\n{"type": "text"}\n')
    assert [event["type"] for event in events] == ["text", "text"]


def test_aggregate_reports_mean_min_and_max():
    runs = [
        {"void": False, "model_service_failure": False,
         "metrics": {name: value for name, value in
                     [("request_count", 4), ("input_tokens", 40), ("output_tokens", 8),
                      ("cache_read_tokens", 0), ("cache_write_tokens", 0),
                      ("cost", 0.0), ("elapsed_seconds", 10.0)]}},
        {"void": False, "model_service_failure": False,
         "metrics": {name: value for name, value in
                     [("request_count", 6), ("input_tokens", 80), ("output_tokens", 16),
                      ("cache_read_tokens", 0), ("cache_write_tokens", 0),
                      ("cost", 0.0), ("elapsed_seconds", 30.0)]}},
        # 作废的运行与模型服务故障的运行不计入结果
        {"void": True, "void_reasons": ["材料路径"],
         "metrics": {name: 999 for name in ["request_count", "input_tokens", "output_tokens",
                                            "cache_read_tokens", "cache_write_tokens",
                                            "cost", "elapsed_seconds"]}},
        {"void": False, "model_service_failure": True,
         "metrics": {name: 888 for name in ["request_count", "input_tokens", "output_tokens",
                                            "cache_read_tokens", "cache_write_tokens",
                                            "cost", "elapsed_seconds"]}},
    ]
    summary = report.aggregate(runs)
    assert summary["request_count"] == {"count": 2, "mean": 5.0, "min": 4, "max": 6}
    assert summary["elapsed_seconds"] == {"count": 2, "mean": 20.0, "min": 10.0, "max": 30.0}


def test_result_records_the_environment_and_the_no_network_rule():
    runs = [{"run_id": "run-1", "void": False, "model_service_failure": False,
             "metrics": {name: 1 for name in ["request_count", "input_tokens", "output_tokens",
                                              "cache_read_tokens", "cache_write_tokens",
                                              "cost", "elapsed_seconds"]}}]
    result = report.build_result("scenario-3", "scenario-3@2", "scorer-3@2", MODEL, runs)
    assert result["network"]["allowed"] is False
    assert "webfetch" in result["network"]["note"]
    for key in ("system", "python", "uv", "node", "opencode"):
        assert result["host_environment"][key]


@needs_model
def test_real_run_delivers_into_the_run_directory(runs_root, tmp_path):
    """真实运行一次：交付落在运行目录，取回与搜索工具没有调用。"""
    outcome = _run_with_cap(runs_root, "real")
    events = opencode.parse_events(outcome["stdout"])
    calls = opencode.tool_calls(events)

    assert events, "opencode produced no JSON events"
    assert opencode.network_tool_calls(calls) == []
    assert opencode.material_path_hits(outcome["stdout"]) == []
    # 交付写进运行目录本身，不是系统临时目录
    assert os.path.isdir(os.path.join(outcome["run_dir"], "src"))
    for call in calls:
        for path in _paths_in(call):
            assert _inside(path, outcome["run_dir"]), path


def _paths_in(call):
    """工具调用记录里出现过的绝对路径。"""
    text = json.dumps({"input": call["input"], "output": call["output"]},
                      ensure_ascii=False)
    found = []
    # 盘符后必须有分隔符，否则会把单独出现的 C: 当成路径
    for match in re.finditer(r"[A-Za-z]:[\\/][^\\\"'\r\n]*", text):
        candidate = match.group(0).rstrip("\\/,) ")
        if len(candidate) > 3 and os.path.exists(candidate):
            found.append(candidate)
    return found


def _inside(path, parent):
    path = os.path.normcase(os.path.abspath(path))
    parent = os.path.normcase(os.path.abspath(parent))
    return path == parent or path.startswith(parent + os.sep)


@needs_model
def test_real_run_is_scored_by_the_scorer(runs_root, tmp_path):
    outcome = _run_with_cap(runs_root, "scored")
    evidence = str(tmp_path / "evidence")
    scores = run_eval.score_delivery(outcome["run_dir"], evidence)

    assert scores["material_version"] == "scenario-3@2"
    assert scores["scorer_version"] == "scorer-3@2"
    assert len(scores["checks"]) == 24
    # 完成度与正确性各自独立：完成度是需求条目得分的平均，
    # 正确性是已尝试检查的通过比例，二者没有大小关系
    assert 0.0 <= scores["completion"] <= 1.0
    assert 0.0 <= scores["correctness"] <= 1.0
    # 隐藏检查与参考实现在评分目录里，不在交付副本里
    assert os.path.isdir(os.path.join(evidence, "scoring", "checks"))
    assert not os.path.exists(os.path.join(evidence, "scoring", "delivery", "checks"))


def _run_with_cap(runs_root, run_id):
    """真实运行一次，时间上限只用来把测试的时长控制住。

    场景 3 的完整实现超过这个上限，所以这里断言的是运行器保证的部分：
    事件流、取回与搜索工具没有调用、交付落在运行目录。
    """
    run_dir = opencode.create_run_dir(runs_root, run_id, MODEL, MODEL_ID)
    outcome = opencode.run_opencode(run_dir, MODEL, 180)
    outcome["run_dir"] = run_dir
    return outcome


@needs_model
def test_time_limit_ends_the_run(runs_root, tmp_path):
    """时间上限到达时运行被结束，按结束时的目录评分并标记超时。"""
    run_dir = opencode.create_run_dir(runs_root, "timeout", MODEL, MODEL_ID)
    started = opencode.create_run_dir(runs_root, "timeout-control", MODEL, MODEL_ID)
    assert os.path.isdir(run_dir) and os.path.isdir(started)

    outcome = opencode.run_opencode(run_dir, MODEL, 20)
    assert outcome["timed_out"] is True
    # 到上限以后进程已经结束，没有残留
    collected = metrics.collect(outcome, opencode.parse_events(outcome["stdout"]))
    assert collected["reason"] == "time_limit"
    assert collected["timed_out"] is True

    # 超时的交付按结束时的目录评分，不因为没有跑完而作废
    scores = run_eval.score_delivery(run_dir, str(tmp_path / "evidence-timeout"))
    assert len(scores["checks"]) == 24
    assert 0.0 <= scores["completion"] <= 1.0