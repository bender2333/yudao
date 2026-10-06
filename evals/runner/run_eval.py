"""一次评测：运行 OpenCode、按评分器评分、写出结果与报告。

原始证据（交付副本、输出、评分日志）放在 .yudao/evals/ 下，不进入 Git；
结果与报告提交到 docs/evaluation/（评测场景设计第 6 节）。
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import metrics
import opencode
import report

TIME_LIMIT_SECONDS = 90 * 60
SCENARIO_PYTHON = "3.13"


def scenario_base():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scenarios", opencode.SCENARIO)


def scenario_python():
    """场景 3 的运行环境是 uv 管理的 Python 3.13（评测场景设计第 3 节）。"""
    found = subprocess.run(["uv", "python", "find", SCENARIO_PYTHON],
                           capture_output=True, encoding="utf-8", errors="replace")
    path = (found.stdout or "").strip()
    if found.returncode != 0 or not path:
        raise RuntimeError("uv cannot provide Python " + SCENARIO_PYTHON)
    return path


def score_delivery(run_dir, evidence_dir, python=None):
    """运行结束以后把隐藏检查与条目表复制到评分目录，再评分。"""
    scoring_dir = os.path.join(evidence_dir, "scoring")
    if os.path.exists(scoring_dir):
        shutil.rmtree(scoring_dir)
    os.makedirs(scoring_dir)
    for name in ("checks", "reference"):
        shutil.copytree(os.path.join(scenario_base(), name), os.path.join(scoring_dir, name))
    shutil.copy2(os.path.join(scenario_base(), "materials", "requirement-table.json"),
                 os.path.join(scoring_dir, "requirement-table.json"))
    delivery_copy = os.path.join(scoring_dir, "delivery")
    shutil.copytree(run_dir, delivery_copy,
                    ignore=shutil.ignore_patterns(".git", ".opencode-config"))
    result_path = os.path.join(scoring_dir, "score.json")
    scorer = os.path.abspath(os.path.join(scenario_base(), "..", "..", "scorer", "scorer.py"))
    command = [python or scenario_python(), scorer,
               "--delivery", delivery_copy,
               "--checks", os.path.join(scoring_dir, "checks"),
               "--result", result_path]
    completed = subprocess.run(command, capture_output=True, encoding="utf-8",
                               errors="replace")
    if completed.returncode != 0:
        raise RuntimeError("scorer failed: " + completed.stderr)
    with open(result_path, encoding="utf-8") as handle:
        return json.load(handle)


def run_once(run_id, runs_root, evidence_root, model, model_id, limit_seconds):
    """运行一次 OpenCode，评分并收好原始证据。"""
    run_dir = opencode.create_run_dir(runs_root, run_id, model, model_id)
    evidence_dir = os.path.join(evidence_root, run_id)
    os.makedirs(evidence_dir, exist_ok=True)

    outcome = opencode.run_opencode(run_dir, model, limit_seconds)
    events = opencode.parse_events(outcome["stdout"])
    calls = opencode.tool_calls(events)

    # 原始证据：JSON 输出、标准错误与交付副本
    with open(os.path.join(evidence_dir, "opencode-output.jsonl"), "w", encoding="utf-8") as handle:
        handle.write(outcome["stdout"])
    with open(os.path.join(evidence_dir, "opencode-stderr.txt"), "w", encoding="utf-8") as handle:
        handle.write(outcome["stderr"])
    shutil.copytree(run_dir, os.path.join(evidence_dir, "delivery"),
                    ignore=shutil.ignore_patterns(".git", ".opencode-config"), dirs_exist_ok=True)

    run_metrics = metrics.collect(outcome, events, run_dir=run_dir)

    void_reasons = []
    hits = opencode.material_path_hits(outcome["stdout"])
    if hits:
        void_reasons.append("JSON 输出中出现材料目录的路径：" + _describe_hits(hits))
    web_calls = opencode.network_tool_calls(calls)
    if web_calls:
        void_reasons.append("JSON 输出中出现取回或搜索工具的调用："
                            + ", ".join(sorted({call["tool"] for call in web_calls})))

    scores = score_delivery(run_dir, evidence_dir)
    with open(os.path.join(evidence_dir, "metrics.json"), "w", encoding="utf-8") as handle:
        json.dump({"run_id": run_id, "run_dir": run_dir, "metrics": run_metrics,
                   "tool_calls": calls, "void_reasons": void_reasons,
                   "score": scores}, handle, ensure_ascii=False, indent=2)

    return {
        "run_id": run_id,
        "run_dir": run_dir,
        "evidence_dir": evidence_dir,
        "metrics": run_metrics,
        "tool_calls": calls,
        "void": bool(void_reasons),
        "void_reasons": void_reasons,
        "model_service_failure": run_metrics["model_service_failure"],
        "score": scores,
    }


def _describe_hits(hits):
    parts = sorted({hit["part"] for hit in hits})
    return "、".join(parts)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scenario 3 OpenCode evaluation")
    parser.add_argument("--model", required=True, help="被测模型，provider/model")
    parser.add_argument("--model-id", help="模型服务里的模型名，默认取 --model 的 model 部分")
    parser.add_argument("--runs", type=int, default=1, help="运行次数（每个场景每边 3 次）")
    parser.add_argument("--limit-seconds", type=float, default=TIME_LIMIT_SECONDS,
                        help="单次运行的墙钟上限")
    parser.add_argument("--run-id-prefix", default="run")
    parser.add_argument("--runs-root", required=True, help="运行目录根，必须在 Yudao 仓库之外")
    parser.add_argument("--result", help="机器可读结果的路径")
    parser.add_argument("--report", help="中文报告的路径")
    args = parser.parse_args(argv)

    model_id = args.model_id or args.model.split("/", 1)[1]
    evidence_root = os.path.join(report.default_evidence_dir(), opencode.SCENARIO)

    runs = []
    run_reports = []
    for index in range(1, args.runs + 1):
        run_id = "%s-%d" % (args.run_id_prefix, index)
        print("running " + run_id + "...", flush=True)
        run = run_once(run_id, args.runs_root, evidence_root, args.model, model_id,
                       args.limit_seconds)
        runs.append(run)
        run_reports.append(report.run_section(run, run["score"]))
        print("  status=%s reason=%s completion=%.4f" % (
            run["metrics"]["status"], run["metrics"]["reason"],
            run["score"]["completion"]), flush=True)

    result = report.build_result(
        scenario=opencode.SCENARIO,
        material_version=runs[0]["score"]["material_version"],
        scorer_version=runs[0]["score"]["scorer_version"],
        model=args.model,
        runs=runs,
    )
    if args.result:
        report.write_result(result, args.result)
    if args.report:
        report.write_report(result, args.report, run_reports)
    return 0


if __name__ == "__main__":
    sys.exit(main())