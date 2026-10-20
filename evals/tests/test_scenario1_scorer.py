"""场景 1 评分器与材料的分层测试。

不需要模型与浏览器的用例（材料摘要、用例表的结构、空目录交付全部记为没有做、
交付启动失败的处理、运行器配置）在 CI check 中运行；
需要界面智能体或浏览器的用例带 real_model 标记，只在明确选择时（-m real_model）运行。
"""

import json
import os
import sys

import pytest

import importlib.util

EVALS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORER_DIR = os.path.join(EVALS_DIR, "scorer")
RUNNER_DIR = os.path.join(EVALS_DIR, "runner")
SCENARIO1_DIR = os.path.join(EVALS_DIR, "scenarios", "scenario-1")
if RUNNER_DIR not in sys.path:
    sys.path.append(RUNNER_DIR)

import material_integrity

def _load_module(name, file_path):
    spec = importlib.util.spec_from_file_location(name, file_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

scorer_scenario1 = _load_module("evals_scorer_scenario1", os.path.join(SCORER_DIR, "scenario1.py"))
runner_scenario1 = _load_module("evals_runner_scenario1", os.path.join(RUNNER_DIR, "scenario1.py"))

real_model = pytest.mark.real_model


def test_material_manifest_and_digests():
    """核对场景 1 材料版本与 manifest 登记的摘要一致。"""
    manifest_path = os.path.join(SCENARIO1_DIR, "materials", "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["scenario"] == "scenario-1"
    assert manifest["material_version"] == "scenario-1@2"

    entries = {"checks", "reference", "materials/requirement-table.json"}
    reasons = material_integrity.digest_reasons(SCENARIO1_DIR, entries)
    assert reasons == []


def test_requirement_table_and_cases_consistency():
    """核对 8 个需求条目与 8 条用例的一致对应关系。"""
    table_path = os.path.join(SCENARIO1_DIR, "materials", "requirement-table.json")
    cases_path = os.path.join(SCENARIO1_DIR, "checks", "cases.json")

    with open(table_path, "r", encoding="utf-8") as f:
        table = json.load(f)
    with open(cases_path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    assert len(table["requirements"]) == 8
    assert len(cases) == 8

    req_ids = [r["id"] for r in table["requirements"]]
    expected_req_ids = [f"R{i}" for i in range(1, 9)]
    assert req_ids == expected_req_ids

    case_ids = [c["id"] for c in cases]
    expected_case_ids = [f"case_{i}" for i in range(1, 9)]
    assert case_ids == expected_case_ids

    # 检查每个需求条目下的 checks 与用例 ID 一致
    for req in table["requirements"]:
        assert len(req["checks"]) == 1
        cid = req["checks"][0]
        matching_case = next((c for c in cases if c["id"] == cid), None)
        assert matching_case is not None
        assert matching_case["requirement_id"] == req["id"]


def test_empty_delivery_scores_all_not_done(tmp_path):
    """空目录的交付 8 条用例都记为「没有做」，不需要模型与浏览器。"""
    empty_dir = str(tmp_path / "empty_delivery")
    os.makedirs(empty_dir)

    result = scorer_scenario1.score(empty_dir)

    assert result["scenario"] == "scenario-1"
    assert result["material_version"] == "scenario-1@2"
    assert result["scorer_version"] == "scorer-1@2"
    assert result["ui_agent_model"] == "ag/gemini-3.8-flash-high"
    assert result["judge_model"] == "ag/gemini-3.8-flash-high"
    assert result["richness"]["score"] == 0.0
    assert len(result["richness"]["items"]) == 10
    assert result["completion"] == 0.0
    assert result["correctness"] == 0.0
    assert result["not_done_count"] == 8
    assert result["wrong_count"] == 0
    assert len(result["not_done"]) == 8
    assert result["wrong"] == []

    for check in result["checks"]:
        assert check["status"] == "not_done"
        assert check["score"] == 0.0
        assert check["verdict"] == "NOT_DONE"
        assert check["requirement"].startswith("R")
        assert check["detail"] is not None

    for req_id, req_score in result["requirements"].items():
        assert req_score["passed"] == 0
        assert req_score["total"] == 1
        assert req_score["score"] == 0.0
def test_failed_start_delivery_scores_all_not_done(tmp_path):
    """交付启动失败时 8 条用例都记为「没有做」，不需要模型与浏览器。"""
    fail_dir = str(tmp_path / "fail_delivery")
    os.makedirs(fail_dir)
    package_json = os.path.join(fail_dir, "package.json")
    with open(package_json, "w", encoding="utf-8") as f:
        json.dump({"scripts": {"start": "node -e \"process.exit(1)\""}}, f)

    result = scorer_scenario1.score(fail_dir)

    assert result["completion"] == 0.0
    assert result["correctness"] == 0.0
    assert result["not_done_count"] == 8
    assert result["wrong_count"] == 0
    assert result["startup_error"] is not None
    assert "Failed to start delivery server" in result["startup_error"]

    for check in result["checks"]:
        assert check["status"] == "not_done"
        assert check["score"] == 0.0


def test_runner_scenario1_interface_and_run_dir(tmp_path):
    """核对 scenario1 运行器模块接口与运行目录起点装配。"""
    assert runner_scenario1.SCENARIO == "scenario-1"
    assert runner_scenario1.SCORER_SCRIPT == "scenario1.py"
    assert "requirement.md" in runner_scenario1.START_FILES
    assert "interface-agreement.md" in runner_scenario1.START_FILES

    urls = runner_scenario1.upstream_urls()
    assert any("mnluzimu/WebGen-Bench" in u for u in urls)

    run_dir = str(tmp_path / "run_test")
    os.makedirs(run_dir)
    runner_scenario1.fill_run_dir(run_dir)

    files = runner_scenario1.message_files(run_dir)
    basenames = [os.path.basename(f) for f in files]
    assert "requirement.md" in basenames
    assert "interface-agreement.md" in basenames

    msg = runner_scenario1.message()
    assert "requirement.md" in msg
    assert "interface-agreement.md" in msg

    cmd = runner_scenario1.scorer_command(sys.executable, str(tmp_path / "scoring"), str(tmp_path / "delivery"))
    assert sys.executable in cmd
    assert any("scenario1.py" in arg for arg in cmd)


def test_empty_delivery_report_run_section(tmp_path):
    """空目录交付写出的报告有场景 1 标题，8 条用例都列为没有做，丰富程度 10 项都是 0 分并写明原因。"""
    empty_dir = str(tmp_path / "empty_delivery_report")
    os.makedirs(empty_dir)

    result = scorer_scenario1.score(empty_dir)

    run = {
        "run_id": "test-run-1",
        "run_dir": empty_dir,
        "evidence_dir": str(tmp_path / "evidence"),
        "metrics": {
            "status": "completed",
            "reason": "normal",
            "timed_out": False,
            "request_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "cost": 0.0,
            "elapsed_seconds": 1.0,
            "model_service_failure": False,
        },
        "tool_calls": [],
        "void": False,
        "void_reasons": [],
        "model_service_failure": False,
        "score": result,
    }

    import report
    lines = report.run_section(run, result)
    report_result = report.build_result(
        scenario="scenario-1",
        material_version=result["material_version"],
        scorer_version=result["scorer_version"],
        model="test-model",
        runs=[run],
    )
    report_path = str(tmp_path / "report.md")
    report.write_report(report_result, report_path, [lines])

    with open(report_path, "r", encoding="utf-8") as f:
        text = f.read()

    # 报告包含场景 1 的标题
    assert "# 场景 1：网页应用 · OpenCode 一侧评测报告" in text

    # 8 条用例都列为「没有做」
    cases = scorer_scenario1.load_cases(scorer_scenario1.CHECKS_DIR)
    assert len(cases) == 8
    for c in cases:
        cid = c["id"]
        req = c["requirement_id"]
        expected = f"| {cid} | {req} | 没有做 |"
        assert expected in text

    # 丰富程度 10 项都是 0 分并写明原因
    richness = result["richness"]
    assert richness is not None
    assert richness["score"] == 0.0
    assert len(richness["items"]) == 10
    assert "丰富程度：" in text
    for item in richness["items"]:
        assert item["score"] == 0.0
        assert len(item["reason"]) > 0
        assert f"| {item['title']} | 0 |" in text

def test_server_startup_with_heavy_logging(tmp_path, monkeypatch):
    """启动时打印几百行的交付能被启动并判定就绪，不需要模型与浏览器。"""
    delivery_dir = str(tmp_path / "heavy_log_delivery")
    os.makedirs(delivery_dir)
    package_json = os.path.join(delivery_dir, "package.json")
    with open(package_json, "w", encoding="utf-8") as f:
        json.dump({"scripts": {"start": "node server.js"}}, f)

    server_js = os.path.join(delivery_dir, "server.js")
    with open(server_js, "w", encoding="utf-8") as f:
        f.write("""
const http = require('http');
for (let i = 0; i < 500; i++) {
    console.log('Startup log line ' + i);
    console.error('Startup stderr line ' + i);
}
const port = process.env.PORT || 3000;
const server = http.createServer((req, res) => {
    res.writeHead(200, {'Content-Type': 'text/plain'});
    res.end('OK');
});
server.listen(port, '127.0.0.1');
""")

    work_dir = str(tmp_path / "work_heavy")
    cases = scorer_scenario1.load_cases(scorer_scenario1.CHECKS_DIR)
    mock_records = [{
        "id": c["id"],
        "requirement": c.get("requirement_id"),
        "status": "pass",
        "detail": "mocked pass",
        "score": 1.0,
        "screenshots": [],
        "verdict": "YES",
    } for c in cases]

    import ui_agent
    monkeypatch.setattr(ui_agent, "run_ui_eval", lambda url, cases, s_dir: mock_records)

    result = scorer_scenario1.score(delivery_dir, work_dir=work_dir)
    assert result["startup_error"] is None
    assert result["completion"] == 1.0
    assert result["correctness"] == 1.0

    log_file = os.path.join(work_dir, "server.log")
    assert os.path.isfile(log_file)
    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    assert "Startup log line 499" in content
    assert "Startup stderr line 499" in content


@real_model
def test_reference_solution_all_pass(tmp_path):
    """参考解法通过全部 8 条用例（需要真实模型与浏览器）。"""
    reference_dir = os.path.join(SCENARIO1_DIR, "reference")
    work_dir = str(tmp_path / "reference_work")

    result = scorer_scenario1.score(reference_dir, work_dir=work_dir)

    assert result["scenario"] == "scenario-1"
    assert result["material_version"] == "scenario-1@2"
    assert result["scorer_version"] == "scorer-1@2"
    assert result["judge_model"] == "ag/gemini-3.8-flash-high"
    assert 0 <= result["richness"]["score"] <= 100
    assert len(result["richness"]["items"]) == 10
    assert result["completion"] == 1.0
    assert result["correctness"] == 1.0
    assert result["not_done_count"] == 0
    assert result["wrong_count"] == 0
    assert len(result["checks"]) == 8
    for check in result["checks"]:
        assert check["status"] == "pass"
        assert check["score"] == 1.0
