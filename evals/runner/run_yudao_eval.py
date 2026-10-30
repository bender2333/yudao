"""一次评测：运行 Yudao、按评分器评分、写出结果与报告。

与 OpenCode 一侧（`run_eval.py`）同一套形状：原始证据（事件日志导出、交付副本、
评分日志）放在 `.yudao/evals/` 下，不进入 Git；结果与报告提交到 `docs/evaluation/`
（评测场景设计第 6 节）。
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import model_service
import yudao
import yudao_metrics
import yudao_report

# 每次运行的墙钟上限：两边相同，由运行器到点结束（评测场景设计第 3 节「时间上限」）
TIME_LIMIT_SECONDS = 120 * 60
SCENARIO_PYTHON = "3.13"


def empty_output_note(runs):
    """模型成功但没有任何输出项时，报告写明这一条：停止原因与真实原因不符。"""
    total = sum(run["metrics"].get("empty_model_responses", 0) for run in runs)
    if not total:
        return None
    return ("被测模型有 " + str(total) + " 次调用返回成功但没有任何输出项"
            "（`status=success`、`output_item_count=0`、无错误）。主机把这类调用当成一次"
            "正常的模型回复，连续多次以后按 `no_tool_call` 暂停，停止原因与真实原因不符；"
            "详见 docs/architecture-issues.md 中本工单的登记。")


def scenario_python():
    """场景 3 的运行环境是 uv 管理的 Python 3.13（评测场景设计第 3 节）。"""
    found = subprocess.run(["uv", "python", "find", SCENARIO_PYTHON],
                           capture_output=True, encoding="utf-8", errors="replace")
    path = (found.stdout or "").strip()
    if found.returncode != 0 or not path:
        raise RuntimeError("uv cannot provide Python " + SCENARIO_PYTHON)
    return path


def score_delivery(delivery_dir, evidence_dir):
    """运行结束以后把隐藏检查与条目表复制到评分目录，再评分。"""
    scoring_dir = os.path.join(evidence_dir, "scoring")
    if os.path.exists(scoring_dir):
        shutil.rmtree(scoring_dir)
    os.makedirs(scoring_dir)
    for name in ("checks", "reference"):
        shutil.copytree(os.path.join(yudao.scenario_base(), name),
                        os.path.join(scoring_dir, name))
    shutil.copy2(os.path.join(yudao.materials_dir(), "requirement-table.json"),
                 os.path.join(scoring_dir, "requirement-table.json"))
    delivery_copy = os.path.join(scoring_dir, "delivery")
    shutil.copytree(delivery_dir, delivery_copy,
                    ignore=shutil.ignore_patterns(".git"))
    result_path = os.path.join(scoring_dir, "score.json")
    scorer = os.path.abspath(os.path.join(yudao.scenario_base(), "..", "..", "scorer", "scorer.py"))
    command = [scenario_python(), scorer,
               "--delivery", delivery_copy,
               "--checks", os.path.join(scoring_dir, "checks"),
               "--result", result_path]
    completed = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise RuntimeError("scorer failed: " + completed.stderr)
    with open(result_path, encoding="utf-8") as handle:
        return json.load(handle)


def run_once(run_id, runs_root, evidence_root, model_name, limit_seconds, limits):
    """运行一次 Yudao，评分并收好原始证据。

    提交号在启动服务之前记下：每次运行各带自己的提交号（第 3 节「运行环境」）。
    """
    commit = yudao.yudao_commit()
    data_dir = yudao.data_dir_for(runs_root, run_id)
    start_dir = yudao.fresh_start_dir(runs_root, run_id)
    evidence_dir = os.path.join(evidence_root, run_id)
    os.makedirs(evidence_dir, exist_ok=True)
    delivery_dir = os.path.join(evidence_dir, "delivery")

    port = yudao.free_port()
    process, client = yudao.start_service(data_dir, port)
    stdout = stderr = ""
    export = None
    replay = None
    delivery_files = []
    released = False
    elapsed = 0.0
    timed_out = False
    served_model = model_name
    try:
        client.wait_ready()
        admission = yudao.register_model(client, model_name, limits)
        served_model = admission.get("admitted_model") or model_name
        project_id = yudao.create_project(client, "评测 · 场景 3",
                                          "按需求原文与接口约定实现地铁换乘查询程序",
                                          initial_directory=start_dir)
        yudao.save_department_settings(client, project_id)
        work_item_id, run_id_yudao = yudao.submit_requirement(client, project_id,
                                                               yudao.requirement_text())
        started = time.monotonic()
        card, timed_out = yudao.wait_for_end(client, project_id, work_item_id, limit_seconds)
        with open(os.path.join(evidence_dir, "work-item.json"), "w", encoding="utf-8") as handle:
            json.dump(card, handle, ensure_ascii=False, indent=2)
        elapsed = time.monotonic() - started
        export = yudao.export_run(client, run_id_yudao)
        replay = client.query("replay.check", {"run_id": run_id_yudao})["data"]
        released = yudao.quality_released(export)
        delivery_event = yudao.last_archived_delivery(export)
        if delivery_event is not None:
            delivery_files = yudao.fetch_delivery(client, delivery_event, delivery_dir)
        else:
            os.makedirs(delivery_dir, exist_ok=True)
    finally:
        client.stop()
        stdout, stderr = yudao.stop_service(process)
        with open(os.path.join(evidence_dir, "service-stdout.txt"), "w", encoding="utf-8") as handle:
            handle.write(stdout)
        with open(os.path.join(evidence_dir, "service-stderr.txt"), "w", encoding="utf-8") as handle:
            handle.write(stderr)

    if export is None:
        raise RuntimeError("the run did not finish and produced no event log")

    # 原始证据：事件日志导出与交付副本
    with open(os.path.join(evidence_dir, "run-export.json"), "w", encoding="utf-8") as handle:
        json.dump(export, handle, ensure_ascii=False, indent=2)

    # 评分之前核对：材料目录的路径、材料摘要、对上游仓库的访问，任一命中这次运行无效
    outcome = {"timed_out": timed_out, "elapsed_seconds": elapsed, "hidden_failures": []}
    void_reasons = yudao.void_reasons(json.dumps(export, ensure_ascii=False))
    scores = score_delivery(delivery_dir, evidence_dir)
    # 质检误放行这一项要等评分结果，先算其余指标，评分以后用同一个判断重算
    parameters_version = _parameters_version(export)
    outcome["hidden_failures"] = [check["id"] for check in scores["checks"] if check["status"] != "pass"]
    metrics = yudao_metrics.collect(export, outcome, replay, parameters_version)

    with open(os.path.join(evidence_dir, "metrics.json"), "w", encoding="utf-8") as handle:
        json.dump({"run_id": run_id, "data_dir": data_dir, "metrics": metrics,
                   "void_reasons": void_reasons, "score": scores},
                  handle, ensure_ascii=False, indent=2)

    return {
        "run_id": run_id,
        "yudao_run_id": export["run_id"],
        "yudao_commit": commit,
        "served_model": served_model,
        "data_dir": data_dir,
        "start_dir": start_dir,
        "evidence_dir": evidence_dir,
        "metrics": metrics,
        "delivery_files": len(delivery_files),
        "void": bool(void_reasons),
        "void_reason": "、".join(void_reasons),
        "model_service_failure": metrics["model_service_failure"],
        "score": scores,
    }


def _parameters_version(export):
    """取冻结的参数版本：`run_created` 事件的 `parameters_version`。
    缺失或占位返回空，第 2 项检查点写「未取到冻结的 parameters_version」。"""
    for event in export["events"]:
        if event["type"] != "run_created":
            continue
        version = (event.get("payload") or {}).get("parameters_version")
        return version if isinstance(version, str) else None
    return None


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Scenario 3 Yudao evaluation")
    parser.add_argument("--model", required=True, help="被测模型名（模型服务里的 model）")
    parser.add_argument("--runs", type=int, default=1, help="运行次数（每个场景每边 3 次）")
    parser.add_argument("--limit-seconds", type=float, default=TIME_LIMIT_SECONDS,
                        help="单次运行的墙钟上限")
    parser.add_argument("--context-window", type=int, default=None,
                        help="上下文窗口；模型列表没有报告这个模型时用它（第 3 节「模型的容量」）")
    parser.add_argument("--max-output-tokens", type=int, default=None,
                        help="单次输出上限；模型列表没有报告这个模型时用它")
    parser.add_argument("--run-id-prefix", default="yudao-run")
    parser.add_argument("--runs-root", required=True, help="运行目录根，必须在 Yudao 仓库之外")
    parser.add_argument("--result", help="机器可读结果的路径")
    parser.add_argument("--report", help="中文报告的路径")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    limits = model_service.model_limits(args.model, args.context_window, args.max_output_tokens)
    print("model capacity: " + model_service.describe(limits), flush=True)

    evidence_root = os.path.join(yudao_report.default_evidence_dir(), yudao.SCENARIO, "yudao")

    runs = []
    run_reports = []
    for index in range(1, args.runs + 1):
        run_id = "%s-%d" % (args.run_id_prefix, index)
        print("running " + run_id + "...", flush=True)
        run = run_once(run_id, args.runs_root, evidence_root, args.model, args.limit_seconds,
                       limits)
        runs.append(run)
        run_reports.append(yudao_report.run_section(run, run["score"]))
        print("  end_status=%s reason=%s commit=%s completion=%.4f" % (
            run["metrics"]["end_status"], run["metrics"]["end_reason"],
            run["yudao_commit"], run["score"]["completion"]), flush=True)

    result = yudao_report.build_result(
        scenario=yudao.SCENARIO,
        material_version=runs[0]["score"]["material_version"],
        scorer_version=runs[0]["score"]["scorer_version"],
        model=runs[0]["served_model"],
        runs=runs,
        model_capacity=limits,
        notes=[note for note in [empty_output_note(runs)] if note],
    )
    if args.result:
        yudao_report.write_result(result, args.result)
    if args.report:
        yudao_report.write_report(result, args.report, run_reports)
    return 0


if __name__ == "__main__":
    sys.exit(main())
