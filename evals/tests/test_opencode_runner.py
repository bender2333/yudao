"""Tests for the OpenCode runner.

They run the real opencode binary with a real model, build real run
directories outside the repository and score the real delivery. No mock is
used: the model service settings come from the user's environment
variables. The tests that need the model carry the `real_model` marker: they
run only with `-m real_model`, and are skipped when a variable is missing.
"""

import json
import os
import re
import sys
import shutil

import pytest

EVALS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER_DIR = os.path.join(EVALS_DIR, "runner")
if RUNNER_DIR not in sys.path:
    sys.path.insert(0, RUNNER_DIR)

import metrics
import model_service
import opencode
import report
import run_eval
import scenario3
import yudao

# 不需要模型服务的用例使用的占位名；真实模型用例在运行时取 YUDAO_EVAL_MODEL（见 real_model_names）。
MODEL_ID = "test-model"
MODEL = "yudao-eval/" + MODEL_ID
SCENARIO = scenario3
REPO_ROOT = EVALS_DIR

# 模型列表报告的容量：用例把它写进运行配置的模型限额，不访问模型服务
LIMITS = {"context_window": 262_144, "context_window_source": "model_list",
          "max_output_tokens": 64_000, "max_output_tokens_source": "model_list"}

# 需要真实模型的用例：默认不选，`-m real_model` 才运行；三个变量缺哪个由根目录 conftest.py 跳过并写明。
real_model = pytest.mark.real_model


def real_model_names():
    """opencode 一侧的 `provider/model` 写法与模型名，由 YUDAO_EVAL_MODEL 拼出。"""
    model_id = os.environ["YUDAO_EVAL_MODEL"]
    return "yudao-eval/" + model_id, model_id


@pytest.fixture
def runs_root(tmp_path):
    root = str(tmp_path / "runs")
    os.makedirs(root)
    return root


def test_run_directory_holds_only_the_starting_point(runs_root):
    run_dir = opencode.create_run_dir(runs_root, "start-only", MODEL, MODEL_ID, LIMITS)
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
        opencode.create_run_dir(inside, "run-1", MODEL, MODEL_ID, LIMITS)
    assert not os.path.exists(inside)


def test_existing_run_directory_is_rejected(runs_root):
    opencode.create_run_dir(runs_root, "once", MODEL, MODEL_ID, LIMITS)
    with pytest.raises(ValueError, match="already exists"):
        opencode.create_run_dir(runs_root, "once", MODEL, MODEL_ID, LIMITS)


def test_run_configuration_denies_fetch_and_search(runs_root):
    run_dir = opencode.create_run_dir(runs_root, "config", MODEL, MODEL_ID, LIMITS)
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


def test_run_configuration_carries_the_same_capacity_as_the_yudao_definition(runs_root):
    """运行配置的模型限额与 Yudao 的模型访问定义是同一对数（第 3 节「模型的容量」）。"""
    run_dir = opencode.create_run_dir(runs_root, "capacity", MODEL, MODEL_ID, LIMITS)
    with open(os.path.join(run_dir, ".opencode-config", "opencode.json"),
              encoding="utf-8") as handle:
        config = json.load(handle)
    limit = config["provider"]["yudao-eval"]["models"][MODEL_ID]["limit"]
    definition = yudao.model_definition(MODEL_ID, LIMITS)
    assert limit == {"context": definition["context_window"],
                     "output": definition["max_output_tokens"]}
    assert limit == {"context": 262_144, "output": 64_000}


def test_message_points_at_the_same_materials_the_run_directory_has(runs_root):
    run_dir = opencode.create_run_dir(runs_root, "inputs", MODEL, MODEL_ID, LIMITS)
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


def test_command_line_fits_the_windows_limit(runs_root, monkeypatch):
    """Windows 的命令行有长度上限，材料全文放进命令行会被系统拒绝。

    只核对命令行的长度，不起 opencode：可执行文件的查找换成一个典型的安装路径，
    运行机上有没有 opencode 都能运行。
    """
    monkeypatch.setattr(opencode.shutil, "which",
                        lambda name: "C:/Users/runner/AppData/Roaming/npm/" + name + ".cmd")
    run_dir = opencode.create_run_dir(runs_root, "limits", MODEL, MODEL_ID, LIMITS)
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


def test_upstream_repository_in_the_output_voids_the_run():
    url = "https://github.com/" + scenario3.UPSTREAM_REPOSITORY
    assert opencode.upstream_hits("clone " + url)
    assert opencode.upstream_hits("clone " + url.replace("github.com/", "github.com:"))
    # 事件里的字符串是被转义过的，转义后的形式也要找到
    assert opencode.upstream_hits(json.dumps({"text": "clone " + url}, ensure_ascii=False))
    assert opencode.upstream_hits("clone " + scenario3.UPSTREAM_REPOSITORY.upper()) == []


def test_unrelated_repositories_are_not_upstream_access():
    assert opencode.upstream_hits("clone https://github.com/openai/openai-agents-python") == []


def test_a_tampered_check_voids_the_scoring_run(tmp_path):
    copy = tmp_path / "scenario-3"
    shutil.copytree(scenario3.scenario_base(), copy)
    (copy / "checks" / "check_harness.py").write_text(
        (copy / "checks" / "check_harness.py").read_text(encoding="utf-8") + "\n# tampered\n",
        encoding="utf-8")
    reasons = opencode.digest_reasons(copy)
    assert [reason.split("：")[1] for reason in reasons] == ["checks"], reasons
    assert opencode.digest_reasons(scenario3.scenario_base()) == []


def test_stray_bytecode_in_the_checks_does_not_change_the_digest(tmp_path):
    copy = tmp_path / "scenario-3"
    shutil.copytree(scenario3.scenario_base(), copy,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (copy / "checks" / "__pycache__").mkdir()
    (copy / "checks" / "__pycache__" / "check_harness.cpython-313.pyc").write_bytes(b"x")
    assert opencode.digest_reasons(copy) == []


# ---------------------------------------------------------------------------
# 运行器入口：评分之前的核对走完整条 run_once

def _stub_opencode(monkeypatch, tmp_path, base):
    """把 `run_once` 触碰的运行、评分与指标换成固定值，核对调用点保持真实。

    不起 opencode 进程、不跑评分器；`opencode.digest_reasons` 与材料路径、上游仓库
    的查找都是真代码，改动的只是场景目录指向副本。
    """
    run_dir = str(tmp_path / "run")
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "delivery.txt"), "w", encoding="utf-8") as handle:
        handle.write("delivery")
    monkeypatch.setattr(opencode, "create_run_dir",
                        lambda runs_root, run_id, model, model_id, limits,
                        scenario_name=None: run_dir)
    monkeypatch.setattr(opencode, "run_opencode",
                        lambda run_dir, model, limit_seconds, **kwargs:
                        {"returncode": 0, "timed_out": False, "stdout": "", "stderr": "",
                         "elapsed_seconds": 1.0, "command": []})
    monkeypatch.setattr(run_eval, "score_delivery",
                        lambda run_dir, evidence_dir, scenario_name=None, python=None,
                        skipped=None:
                        {"checks": [], "material_version": "scenario-3@2",
                         "scorer_version": "scorer-3@2"})
    monkeypatch.setattr(scenario3, "scenario_base", lambda: base)


def test_a_tampered_check_voids_the_opencode_run(runs_root, tmp_path, monkeypatch):
    """改一份隐藏检查：`run_once` 在评分之前判这次运行无效，报告写明摘要不同。"""
    copy = tmp_path / "scenario-3"
    shutil.copytree(scenario3.scenario_base(), copy)
    target = copy / "checks" / "check_harness.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")
    _stub_opencode(monkeypatch, tmp_path, str(copy))

    run = run_eval.run_once("run-1", runs_root, str(tmp_path / "evidence"), MODEL, MODEL_ID,
                           60, LIMITS)

    assert run["void"] is True
    assert run["void_reasons"] == ["材料摘要与材料版本记录不同：checks"]


def test_clean_materials_let_the_opencode_run_score(runs_root, tmp_path, monkeypatch):
    """材料没有改动、没有上游访问：`run_once` 不作废，评分与报告照常。"""
    _stub_opencode(monkeypatch, tmp_path, scenario3.scenario_base())

    run = run_eval.run_once("run-1", runs_root, str(tmp_path / "evidence"), MODEL, MODEL_ID,
                           60, LIMITS)

    assert run["void"] is False
    assert run["void_reasons"] == []
    assert run["score"]["scorer_version"] == "scorer-3@2"



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


def test_metrics_record_cost_as_unknown_when_no_request_reports_one():
    """各次请求的费用全为 0 或为空：这次运行的费用记未知，不记 0.0（第 5.2 节）。"""
    events = [{"type": "step_finish", "part": {"tokens": {}, "cost": 0}},
              {"type": "step_finish", "part": {"tokens": {}}}]
    collected = metrics.collect({"returncode": 0, "timed_out": False, "elapsed_seconds": 2.0},
                                events)
    assert collected["cost"] is None


def test_metrics_sum_the_costs_the_service_reports():
    events = [{"type": "step_finish", "part": {"cost": 0.1}},
              {"type": "step_finish", "part": {"cost": 0.2}}]
    collected = metrics.collect({"returncode": 0, "timed_out": False, "elapsed_seconds": 2.0},
                                events)
    assert abs(collected["cost"] - 0.3) < 1e-9


def test_reserved_device_names_are_skipped_with_or_without_extension():
    """Windows 的保留设备名不分大小写，带不带扩展名都算（第 3 节「隔离」）。"""
    names = ["nul", "NUL.TXT", "con.md", "aux", "com1", "lpt9.tar.gz", "src", "readme.md",
             "COM10", "nullify.py"]
    assert opencode.reserved_device_names(names) == ["NUL.TXT", "aux", "com1", "con.md",
                                                     "lpt9.tar.gz", "nul"]


def _reserved_path(directory, name="nul"):
    """保留设备名的长路径：`os.path.abspath` 会把 `nul` 折成 `\\.\nul`，所以只规范化目录。"""
    return "\\\\?\\" + os.path.abspath(directory).rstrip("\\") + "\\" + name


def _reserved_file(directory, name="nul"):
    """在目录里建一个名为 `nul` 的文件：普通路径写进的是设备，加长路径前缀才落到磁盘上。"""
    path = _reserved_path(directory, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("reserved device name")
    return path


def _remove_reserved_file(directory, name="nul"):
    os.remove(_reserved_path(directory, name))


@pytest.mark.skipif(os.name != "nt", reason="Windows 的保留设备名只在 Windows 上存在")
def test_a_run_directory_holding_a_reserved_name_still_copies_and_scores(runs_root, tmp_path,
                                                                       monkeypatch):
    """交付里有名为 `nul` 的文件：复制与评分照常完成，报告列出被跳过的文件。

    以前把这棵目录树复制到证据目录或评分目录时会中止整组运行：普通路径的 `nul` 写进
    复制目标的是设备，不是文件。同一棵目录树复制两次，跳过的文件只记一次。
    """
    run_dir = opencode.create_run_dir(runs_root, "reserved", MODEL, MODEL_ID, LIMITS)
    _reserved_file(run_dir)
    monkeypatch.setattr(opencode, "create_run_dir",
                        lambda runs_root, run_id, model, model_id, limits,
                        scenario_name=None: run_dir)
    monkeypatch.setattr(opencode, "run_opencode",
                        lambda run_dir, model, limit_seconds, **kwargs:
                        {"returncode": 0, "timed_out": False, "stdout": "", "stderr": "",
                         "elapsed_seconds": 1.0, "command": []})
    try:
        run = run_eval.run_once("run-1", runs_root, str(tmp_path / "evidence"), MODEL, MODEL_ID,
                                60, LIMITS)
    finally:
        _remove_reserved_file(run_dir)

    assert run["skipped_files"] == ["nul"]
    assert len(run["score"]["checks"]) == 24
    text = "\n".join(report.run_section(run, run["score"]))
    assert "保留设备名" in text
    assert "nul" in text


def test_default_time_limit_is_two_hours():
    """两个运行器的默认时间上限都是 120 分钟（第 3 节「时间上限」）。"""
    assert run_eval.TIME_LIMIT_SECONDS == 120 * 60
    args = run_eval.parse_args(["--model", MODEL, "--runs-root", "C:/runs"])
    assert args.limit_seconds == 120 * 60


def test_explicit_time_limit_reaches_opencode(runs_root, tmp_path, monkeypatch):
    """显式给出的 `--limit-seconds` 覆盖默认值，并且回到 OpenCode 时用的就是它。"""
    args = run_eval.parse_args(["--model", MODEL, "--runs-root", "C:/runs",
                                "--limit-seconds", "600"])
    assert args.limit_seconds == 600.0
    _stub_opencode(monkeypatch, tmp_path, scenario3.scenario_base())
    seen = []

    def run_opencode(run_dir, model, limit_seconds, **kwargs):
        seen.append(limit_seconds)
        return {"returncode": 0, "timed_out": False, "stdout": "", "stderr": "",
                "elapsed_seconds": 1.0, "command": []}

    monkeypatch.setattr(opencode, "run_opencode", run_opencode)
    run_eval.run_once("run-1", runs_root, str(tmp_path / "evidence"), MODEL, MODEL_ID,
                      args.limit_seconds, LIMITS)
    assert seen == [600.0]


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
    assert summary["request_count"] == {"count": 2, "unknown": 0, "mean": 5.0, "min": 4.0,
                                        "max": 6.0, "spread": 2.0}
    assert summary["elapsed_seconds"] == {"count": 2, "unknown": 0, "mean": 20.0, "min": 10.0,
                                          "max": 30.0, "spread": 20.0}
    # 运行费用记 0.0 的样本照常计入
    assert summary["cost"]["mean"] == 0.0


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


@real_model
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


@real_model
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
    model, model_id = real_model_names()
    limits = model_service.model_limits(model_id)
    run_dir = opencode.create_run_dir(runs_root, run_id, model, model_id, limits)
    outcome = opencode.run_opencode(run_dir, model, 180)
    outcome["run_dir"] = run_dir
    return outcome


@real_model
def test_time_limit_ends_the_run(runs_root, tmp_path):
    """时间上限到达时运行被结束，按结束时的目录评分并标记超时。"""
    model, model_id = real_model_names()
    limits = model_service.model_limits(model_id)
    run_dir = opencode.create_run_dir(runs_root, "timeout", model, model_id, limits)
    started = opencode.create_run_dir(runs_root, "timeout-control", model, model_id, limits)
    assert os.path.isdir(run_dir) and os.path.isdir(started)

    outcome = opencode.run_opencode(run_dir, model, 20)
    assert outcome["timed_out"] is True
    # 到上限以后进程已经结束，没有残留
    collected = metrics.collect(outcome, opencode.parse_events(outcome["stdout"]))
    assert collected["reason"] == "time_limit"
    assert collected["timed_out"] is True

    # 超时的交付按结束时的目录评分，不因为没有跑完而作废
    scores = run_eval.score_delivery(run_dir, str(tmp_path / "evidence-timeout"))
    assert len(scores["checks"]) == 24
    assert 0.0 <= scores["completion"] <= 1.0
