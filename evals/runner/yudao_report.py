"""Yudao 一侧的结果与中文报告：机器可读的结果、指标汇总、过程检查点与逐次运行。

与 OpenCode 一侧共用同一套形状（第 6 节）：记录 Yudao 提交号、模型、场景材料版本、
评分器版本、宿主环境、每次运行的全部指标与失败条目。原始证据（事件日志导出、交付
副本、评分日志）放在 `.yudao/evals/` 下，不进入 Git。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yudao as driver
from report import _number, _write, host_environment

AGGREGATED_METRICS = ("cycles", "rework", "collaboration", "model_requests",
                      "input_tokens", "output_tokens", "total_tokens",
                      "cost", "elapsed_seconds")

METRIC_LABELS = {
    "cycles": "循环次数",
    "rework": "返工次数",
    "collaboration": "部门之间询问次数",
    "model_requests": "模型请求数",
    "input_tokens": "输入用量",
    "output_tokens": "输出用量",
    "total_tokens": "总用量",
    "cost": "费用",
    "elapsed_seconds": "耗时（秒）",
}

CHECKPOINT_LABELS = {
    "ended_within_limit": "run 在限额内结束，状态为放行",
    "quality_release_bound_to_delivery": "质检的放行绑定最后提交的交付树",
    "no_write_before_plan_accepted": "工程的计划被接纳以前没有写入文件",
    "replay_consistent": "重放结果与记录一致",
    "no_false_release": "质检没有误放行",
}


def aggregate_metrics(runs):
    """按 Yudao 的指标名聚合（第 5.2 节：平均值、最小值与最大值）。"""
    counted = [run for run in runs
               if not run.get("void") and not run.get("metrics", {}).get("model_service_failure")]
    summary = {}
    for name in AGGREGATED_METRICS:
        values = [float(run["metrics"][name]) for run in counted if name in run["metrics"]]
        if not values:
            continue
        summary[name] = {"count": len(values), "mean": sum(values) / len(values),
                         "min": min(values), "max": max(values)}
    return summary


def build_result(scenario, material_version, scorer_version, model, runs, yudao_commit,
                 notes=()):
    counted = [run for run in runs
               if not run.get("void") and not run["metrics"].get("model_service_failure")]
    return {
        "scenario": scenario,
        "material_version": material_version,
        "scorer_version": scorer_version,
        "side": "yudao",
        "model": model,
        "yudao_commit": yudao_commit,
        "network": {
            "allowed": False,
            "note": "Yudao 的评测项目不登记取回来源与 MCP 服务器，运行中也没有这两类工具的调用。",
        },
        "host_environment": host_environment(),
        "run_count": len(counted),
        "void_runs": [run["run_id"] for run in runs if run.get("void")],
        "model_service_failures": [run["run_id"] for run in runs
                                   if run["metrics"].get("model_service_failure")],
        "notes": list(notes),
        "summary": aggregate_metrics(runs),
        "runs": runs,
    }


def write_result(result, path):
    _write(path, json.dumps(result, ensure_ascii=False, indent=2) + "\n")


def write_report(result, path, run_reports):
    lines = ["# 场景 3 · Yudao 一侧评测报告", ""]
    lines.extend(_basic_section(result))
    lines.extend(_host_section(result))
    lines.extend(_network_section())
    lines.extend(_checkpoints_section(result))
    lines.extend(_summary_section(result))
    lines.append("## 六、逐次运行")
    lines.append("")
    for item in run_reports:
        lines.extend(item)
    lines.append("")
    lines.append("## 七、不计入结果的运行")
    lines.append("")
    lines.extend(_excluded_section(result))
    if result["notes"]:
        lines.append("")
        lines.append("## 八、起点缺口与运行条件")
        lines.append("")
        for note in result["notes"]:
            lines.append("- " + note)
    lines.append("")
    lines.append("原始证据（事件日志导出、交付副本、评分日志）在 `.yudao/evals/` 下，不进入 Git。")
    _write(path, "\n".join(lines) + "\n")


def _basic_section(result):
    lines = ["## 一、基本信息", ""]
    lines.append("| 项目 | 取值 |")
    lines.append("| --- | --- |")
    lines.append("| 场景 | " + result["scenario"] + " |")
    lines.append("| 材料版本 | " + result["material_version"] + " |")
    lines.append("| 评分器版本 | " + result["scorer_version"] + " |")
    lines.append("| 被测模型 | " + result["model"] + " |")
    lines.append("| Yudao 提交号 | " + result["yudao_commit"] + " |")
    lines.append("| 计入结果的运行次数 | " + str(result["run_count"]) + " |")
    return lines + [""]


def _host_section(result):
    lines = ["## 二、宿主环境", ""]
    lines.append("| 项目 | 版本 |")
    lines.append("| --- | --- |")
    for key, value in result["host_environment"].items():
        lines.append("| " + key + " | " + value + " |")
    return lines + [""]


def _network_section():
    return ["## 三、联网", "",
            "不联网。Yudao 的评测项目不登记取回来源与 MCP 服务器，运行中也没有这两类工具的调用。", ""]


def _checkpoints_section(result):
    """过程检查点（第 5.1 节）：结论与依据，逐次运行列出。"""
    lines = ["## 四、过程检查点", ""]
    lines.append("| 检查点 | " + " | ".join(run["run_id"] for run in result["runs"]) + " |")
    lines.append("| --- | " + " | ".join("---" for _ in result["runs"]) + " |")
    for key, label in CHECKPOINT_LABELS.items():
        cells = []
        for run in result["runs"]:
            checkpoint = run["metrics"]["checkpoints"].get(key, {})
            cells.append("通过" if checkpoint.get("passed") else "未通过")
        lines.append("| " + label + " | " + " | ".join(cells) + " |")
    lines.append("")
    for run in result["runs"]:
        lines.append("### " + run["run_id"] + " 的检查点依据")
        lines.append("")
        for key, label in CHECKPOINT_LABELS.items():
            checkpoint = run["metrics"]["checkpoints"].get(key, {})
            lines.append("- " + label + "：" + str(checkpoint.get("detail", "")))
        lines.append("")
    return lines


def _summary_section(result):
    lines = ["## 五、指标汇总", ""]
    if result["summary"]:
        lines.append("| 指标 | 平均值 | 最小值 | 最大值 |")
        lines.append("| --- | --- | --- | --- |")
        for name, item in result["summary"].items():
            lines.append("| " + METRIC_LABELS.get(name, name) + " | " + _number(item["mean"])
                         + " | " + _number(item["min"]) + " | " + _number(item["max"]) + " |")
    else:
        lines.append("没有计入结果的运行。")
    return lines + [""]


def run_section(run, scores):
    """一次运行的中文小节：指标、评分与失败条目。"""
    metrics = run["metrics"]
    lines = ["### " + run["run_id"], ""]
    lines.append("| 项目 | 取值 |")
    lines.append("| --- | --- |")
    lines.append("| 结束状态 | " + str(metrics["end_status"]) + " |")
    lines.append("| 结束原因 | " + str(metrics["end_reason"]) + " |")
    lines.append("| 停止原因 | " + str(metrics["stop_reason"]) + " |")
    lines.append("| 循环次数 | " + _number(metrics["cycles"]) + " |")
    lines.append("| 返工次数 | " + _number(metrics["rework"]) + " |")
    lines.append("| 部门之间询问次数 | " + _number(metrics["collaboration"]) + " |")
    lines.append("| 模型请求数 | " + _number(metrics["model_requests"]) + " |")
    lines.append("| 输入用量 | " + _number(metrics["input_tokens"]) + " |")
    lines.append("| 输出用量 | " + _number(metrics["output_tokens"]) + " |")
    lines.append("| 耗时（秒） | " + _number(metrics["elapsed_seconds"]) + " |")
    lines.append("| 封存的交付文件数 | " + _number(run.get("delivery_files", 0)) + " |")
    lines.append("| 成功但没有输出项的模型调用 | "
                 + _number(metrics.get("empty_model_responses", 0)) + " |")
    lines.append("| 完成度 | " + _number(scores["completion"]) + " |")
    lines.append("| 正确性 | " + _number(scores["correctness"]) + " |")
    lines.append("| 未做的隐藏检查数 | " + _number(scores["not_done_count"]) + " |")
    lines.append("| 出错的隐藏检查数 | " + _number(scores["wrong_count"]) + " |")
    lines.append("")
    lines.extend(_failures_section(run, scores))
    return lines


def _failures_section(run, scores):
    """失败条目：未通过的要求与没有通过的隐藏检查（第 6 节要求写进报告）。"""
    lines = ["失败条目：", ""]
    for name, item in scores["requirements"].items():
        if item["passed"] == item["total"]:
            continue
        lines.append("- 要求 " + name + "：" + str(item["passed"]) + "/" + str(item["total"]) + " 通过")
    for check in scores["checks"]:
        if check["status"] == "pass":
            continue
        lines.append("- 隐藏检查 " + check["id"] + "（" + check["status"] + "）：" + check["detail"])
    if len(lines) == 2:
        lines.append("无：全部要求与隐藏检查通过。")
    lines.append("")
    if run.get("void"):
        lines.append("这次运行作废：" + str(run.get("void_reason", "")))
        lines.append("")
    return lines


def _excluded_section(result):
    lines = []
    for run in result["runs"]:
        if run.get("void"):
            lines.append("- " + run["run_id"] + "：作废（" + str(run.get("void_reason", "")) + "）")
        elif run["metrics"].get("model_service_failure"):
            lines.append("- " + run["run_id"] + "：模型服务故障（" + run["metrics"]["end_reason"] + "）")
    if not lines:
        lines.append("无：每次运行都计入结果。")
    return lines


def default_evidence_dir():
    """原始证据目录：仓库根的 .yudao/evals/（已被 git 忽略）。"""
    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    return os.path.join(root, ".yudao", "evals")


def yudao_commit():
    return driver.yudao_commit()