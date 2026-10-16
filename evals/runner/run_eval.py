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

import material_integrity
import metrics
import opencode
import report

TIME_LIMIT_SECONDS = 90 * 60
SCENARIO_PYTHON = "3.13"


def scenario_python():
    """运行环境是 uv 管理的 Python 3.13（评测场景设计第 3 节）。"""
    found = subprocess.run(["uv", "python", "find", SCENARIO_PYTHON],
                           capture_output=True, encoding="utf-8", errors="replace")
    path = (found.stdout or "").strip()
    if found.returncode != 0 or not path:
        raise RuntimeError("uv cannot provide Python " + SCENARIO_PYTHON)
    return path


def prepare_scoring_dir(scenario_module, run_dir, evidence_dir):
    """运行结束以后把隐藏检查与条目表复制到评分目录，再复制一份交付。

    隐藏部分与交付副本各自独立：被测方在运行期间见不到检查与条目表。
    """
    scoring_dir = os.path.join(evidence_dir, "scoring")
    if os.path.exists(scoring_dir):
        shutil.rmtree(scoring_dir)
    os.makedirs(scoring_dir)
    base = scenario_module.scenario_base()
    for relative in scenario_module.SCORING_INPUTS:
        source = os.path.join(base, relative)
        target = os.path.join(scoring_dir, os.path.basename(relative))
        if os.path.isdir(source):
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    delivery_copy = os.path.join(scoring_dir, "delivery")
    shutil.copytree(run_dir, delivery_copy,
                    ignore=shutil.ignore_patterns(*scenario_module.SCORING_IGNORES))
    return scoring_dir, delivery_copy


def score_delivery(run_dir, evidence_dir, scenario_name=None, python=None):
    """在评分目录中对交付评分，返回机器可读结果。"""
    scenario_module = opencode.scenario(scenario_name)
    scoring_dir, delivery_copy = prepare_scoring_dir(scenario_module, run_dir, evidence_dir)
    result_path = os.path.join(scoring_dir, "score.json")
    command = scenario_module.scorer_command(python or scenario_python(),
                                             scoring_dir, delivery_copy) + ["--result", result_path]
    completed = subprocess.run(command, capture_output=True, encoding="utf-8",
                               errors="replace")
    if completed.returncode != 0:
        raise RuntimeError("scorer failed: " + (completed.stderr or completed.stdout))
    with open(result_path, encoding="utf-8") as handle:
        return json.load(handle)


def run_once(run_id, runs_root, evidence_root, model, model_id, limit_seconds,
             scenario_name=None):
    """运行一次 OpenCode，评分并收好原始证据。"""
    scenario_module = opencode.scenario(scenario_name)
    run_dir = opencode.create_run_dir(runs_root, run_id, model, model_id, scenario_name)
    evidence_dir = os.path.join(evidence_root, run_id)
    os.makedirs(evidence_dir, exist_ok=True)

    outcome = opencode.run_opencode(run_dir, model, limit_seconds, scenario_name=scenario_name)
    events = opencode.parse_events(outcome["stdout"])
    calls = opencode.tool_calls(events)

    # 原始证据：JSON 输出、标准错误与交付副本
    with open(os.path.join(evidence_dir, "opencode-output.jsonl"), "w", encoding="utf-8") as handle:
        handle.write(outcome["stdout"])
    with open(os.path.join(evidence_dir, "opencode-stderr.txt"), "w", encoding="utf-8") as handle:
        handle.write(outcome["stderr"])
    shutil.copytree(run_dir, os.path.join(evidence_dir, "delivery"),
                    ignore=shutil.ignore_patterns(*scenario_module.SCORING_IGNORES),
                    dirs_exist_ok=True)

    run_metrics = metrics.collect(outcome, events, run_dir=run_dir)

    void_reasons = []
    hits = opencode.material_path_hits(outcome["stdout"], scenario_name)
    if hits:
        void_reasons.append("JSON 输出中出现材料目录的路径：" + _describe_hits(hits))
    urls = opencode.upstream_hits(outcome["stdout"], scenario_name)
    if urls:
        void_reasons.append("JSON 输出中出现对上游仓库的访问："
                            + material_integrity.describe_urls(urls))
    web_calls = opencode.network_tool_calls(calls)
    if web_calls:
        void_reasons.append("JSON 输出中出现取回或搜索工具的调用："
                            + ", ".join(sorted({call["tool"] for call in web_calls})))
    # 评分之前核对材料摘要：算在场景目录的材料原件上，被测方在运行途中改掉它才算数
    void_reasons.extend(opencode.digest_reasons(scenario_module.scenario_base(), scenario_name))

    scores = score_delivery(run_dir, evidence_dir, scenario_name)
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
    parser = argparse.ArgumentParser(description="OpenCode evaluation for one scenario")
    parser.add_argument("--scenario", default="scenario3",
                        help="场景：scenario3 或 scenario2")
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
    scenario_module = opencode.scenario(args.scenario)
    evidence_root = os.path.join(report.default_evidence_dir(), scenario_module.SCENARIO)

    runs = []
    run_reports = []
    for index in range(1, args.runs + 1):
        run_id = "%s-%d" % (args.run_id_prefix, index)
        print("running " + run_id + "...", flush=True)
        run = run_once(run_id, args.runs_root, evidence_root, args.model, model_id,
                       args.limit_seconds, args.scenario)
        runs.append(run)
        run_reports.append(report.run_section(run, run["score"]))
        print("  status=%s reason=%s completion=%.4f" % (
            run["metrics"]["status"], run["metrics"]["reason"],
            run["score"]["completion"]), flush=True)

    result = report.build_result(
        scenario=scenario_module.SCENARIO,
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