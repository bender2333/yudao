"""Yudao 一侧的结果与中文报告：机器可读的结果、指标汇总、过程检查点与逐次运行。

与 OpenCode 一侧共用同一套形状（第 6 节）：记录 Yudao 提交号、模型、场景材料版本、
评分器版本、宿主环境、每次运行的全部指标与失败条目。原始证据（事件日志导出、交付
副本、评分日志）放在 `.yudao/evals/` 下，不进入 Git。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import model_service
from report import _number, _write, host_environment

AGGREGATED_METRICS = ("cycles", "rework", "collaboration", "model_requests",
                      "input_tokens", "output_tokens", "total_tokens",
                      "cost", "elapsed_seconds")
# 评分器给出的两项（第 5.2 节）：来自 run["score"]，与上面的指标一起进汇总
SCORED_METRICS = ("completion", "correctness")

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
    "completion": "完成度",
    "correctness": "正确性",
}

CHECKPOINT_LABELS = {
    "ended_within_limit": "run 在限额内结束，状态为放行",
    "quality_release_bound_to_delivery": "质检的放行绑定最后提交的交付树",
    "replay_consistent": "重放结果与记录一致",
    "no_false_release": "质检没有误放行",
    "release_coverage": "放行记录附检验覆盖比例、模型阅读条件数与开环条件数",
}

# 用量字段缺失时的原因：模型服务没有返回，取不到单价（设计第 5.2 节）
UNKNOWN_REASONS = {
    "input_tokens": "模型服务未上报输入用量",
    "output_tokens": "模型服务未上报输出用量",
    "cache_read_tokens": "模型服务未上报缓存读取代币数",
    "cache_write_tokens": "模型服务未上报缓存写取代币数",
    "total_tokens": "模型服务未上报总用量",
    "cost": "模型服务未上报费用，或材料版本未登记单价",
    "elapsed_seconds": "运行没有结束",
    "completion": "评分器没有给出完成度（运行作废或没有可以评分的交付）",
    "correctness": "评分器没有给出正确性（运行作废或没有可以评分的交付）",
}


def aggregate_metrics(runs):
    """按 Yudao 的指标名聚合（第 5.2 节）：平均值、最小值、最大值与噪声范围。

    每个指标报告有效样本数与未知样本数；缺字段的样本按未知处理，不进均值、最小、最大
    与噪声范围。噪声范围是同一版本各次运行的取值极差；只有一次运行时是「未知」，不写零。
    完成度与正确性来自评分器（`run["score"]`），与其余指标一起汇总。
    """
    counted = [run for run in runs
               if not run.get("void") and not run.get("metrics", {}).get("model_service_failure")]
    summary = {}
    for name in AGGREGATED_METRICS:
        values = [float(run["metrics"][name]) for run in counted
                  if run["metrics"].get(name) is not None]
        summary[name] = _aggregate_one(values, len(counted),
                                       UNKNOWN_REASONS.get(name, "模型服务未上报该项"))
    for name in SCORED_METRICS:
        values = [float(run["score"][name]) for run in counted
                  if (run.get("score") or {}).get(name) is not None]
        summary[name] = _aggregate_one(values, len(counted), UNKNOWN_REASONS[name])
    return summary


def _aggregate_one(values, total, unknown_reason):
    """一项指标的统计：有效样本、未知样本、平均值、最小值、最大值与噪声范围（极差）。"""
    item = {"count": total, "unknown": total - len(values)}
    if item["unknown"]:
        item["unknown_reason"] = unknown_reason
    if values:
        item.update({"mean": sum(values) / len(values),
                     "min": min(values), "max": max(values),
                     "spread": (max(values) - min(values)) if len(values) > 1 else None})
    return item


def build_result(scenario, material_version, scorer_version, model, runs, model_capacity=None,
                 notes=(), comparison=None):
    """一份结果：每次运行的指标与失败条目、逐次的提交号、模型的容量与来源（第 6 节）。"""
    counted = [run for run in runs
               if not run.get("void") and not run["metrics"].get("model_service_failure")]
    commits = _run_commits(runs)
    distinct = []
    for item in commits:
        if item["yudao_commit"] not in distinct:
            distinct.append(item["yudao_commit"])
    payload = {
        "scenario": scenario,
        "material_version": material_version,
        "scorer_version": scorer_version,
        "side": "yudao",
        "model": model,
        "yudao_commit": distinct[0] if len(distinct) == 1 else None,
        "yudao_commits": commits,
        "yudao_commit_mismatch": distinct if len(distinct) > 1 else [],
        "model_capacity": model_capacity,
        "network": {
            "allowed": False,
            "note": "被测的 Yudao 以关闭取回的启动参数（--no-fetch）启动，三个部门的请求里没有取回工具"
                    "（fetch_url、read_external_source）；评测项目也不设置 MCP 服务器，运行中没有这两类工具的调用。",
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
    # 场景 2 的建档单独成段（第 5.2 节）：建档的请求数、用量与耗时不计入事项的指标
    onboarding = [{"run_id": run["run_id"], **run["onboarding"]}
                  for run in runs if run.get("onboarding")]
    if onboarding:
        payload["onboarding"] = onboarding
    if comparison is not None:
        payload["comparison"] = comparison
    return payload


def _run_commits(runs):
    """每次运行的提交号：运行器在启动服务之前各自记下（第 3 节「运行环境」）。"""
    return [{"run_id": run["run_id"], "yudao_commit": run.get("yudao_commit")} for run in runs]


def write_result(result, path):
    _write(path, json.dumps(result, ensure_ascii=False, indent=2) + "\n")


def write_report(result, path, run_reports):
    lines = ["# " + _scenario_title(result["scenario"]) + " · Yudao 一侧评测报告", ""]
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
    if result.get("comparison"):
        lines.append("")
        lines.append("## 八、版本比较")
        lines.append("")
        lines.extend(_comparison_section(result["comparison"]))
    if result["notes"]:
        lines.append("")
        lines.append("## 九、运行条件与记录")
        lines.append("")
        for note in result["notes"]:
            lines.append("- " + note)
    lines.append("")
    lines.append("原始证据（事件日志导出、交付副本、评分日志）在 `.yudao/evals/` 下，不进入 Git。")
    _write(path, "\n".join(lines) + "\n")

def _comparison_section(comparison):
    """版本比较（`docs/design/rules-and-parameters.md` 第 4 节）：结论与逐任务差值。"""
    labels = {"improved": "改进", "no_difference": "无差别", "regressed": "退化", "blocked": "受阻"}
    verdict = labels.get(comparison.get("verdict"), "未判定")
    lines = ["| 项目 | 取值 |", "| --- | --- |",
             "| 结论 | " + verdict + " |",
             "| 材料版本 | " + str(comparison.get("material_version")) + " |",
             "| 评分器版本 | " + str(comparison.get("scorer_version")) + " |",
             "| 主要指标 | " + str(comparison.get("primary", {}).get("metric")) + "（当前 "
             + str(comparison.get("primary", {}).get("current")) + "，基线 "
             + str(comparison.get("primary", {}).get("baseline")) + "，差值 "
             + str(comparison.get("primary", {}).get("difference")) + "） |",
             "| 噪声 | " + _noise_text(comparison.get("noise")) + " |"]
    if comparison.get("block_reason"):
        lines.append("| 受阻原因 | " + comparison["block_reason"] + " |")
    lines.append("")
    if comparison.get("paired_tasks"):
        lines.append("按运行序号配对（第 1 次对第 1 次，不按运行编号）：")
        lines.append("")
        lines.append("| 运行序号 | 本次运行 | 基线运行 | 本次误放行 | 基线误放行 | 差值 "
                     "| 本次完成度 | 基线完成度 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for item in comparison["paired_tasks"]:
            lines.append("| " + str(item["run_index"])
                         + " | " + str(item.get("current_run"))
                         + " | " + str(item.get("baseline_run"))
                         + " | " + str(item["current_false_release"])
                         + " | " + str(item["baseline_false_release"])
                         + " | " + str(item["false_release_difference"])
                         + " | " + _maybe(item["current_completion"])
                         + " | " + _maybe(item["baseline_completion"]) + " |")
        lines.append("")
    unpaired = comparison.get("unpaired") or {}
    if unpaired.get("current") or unpaired.get("baseline"):
        lines.append("没有配对的部分（序号对不上）：")
        lines.append("")
        for side, label in (("current", "本次"), ("baseline", "基线")):
            if unpaired.get(side):
                lines.append("- " + label + "：第 " + "、".join(str(index) for index in unpaired[side])
                             + " 次")
        lines.append("")
    return lines


def _noise_text(noise):
    if not noise:
        return "未知"
    spread = noise.get("completion_spread")
    return "完成度极差 " + (str(spread) if spread is not None else "未知") + "（" + noise.get("note", "") + "）"


def write_side_report(comparison, path):
    """Yudao 对单个 agent 的中文报告（第 6.3 节）：结论、判定依据与逐次并排的表。

    由 `compare_sides.py` 在对照之后写出；结果文件（JSON）由同一个入口写出，报告本身
    发 Discussions，不提交到仓库（[README](../README.md)「结果放哪里」）。
    """
    lines = ["# " + _scenario_title(comparison.get("scenario")) + " · Yudao 对 OpenCode 的对照", ""]
    lines.extend(_side_verdict_section(comparison))
    lines.extend(_side_criterion_section(comparison))
    lines.extend(_side_pairs_section(comparison))
    lines.append("判定按 D38 的 N-G1（评测场景设计第 6.3 节）：同一个场景 3 次运行中至少 2 次，"
                 "质检在时间上限以内给出结论，并且最终交付比本次第一次交付多通过至少 1 条隐藏检查；"
                 "第一次交付已经全部通过的运行不计入，也不算失败；3 次都没有质检误放行。"
                 "逐次并排只报告，不单独据此判定「高于」。")
    lines.append("")
    _write(path, "\n".join(lines) + "\n")


def _side_verdict_section(comparison):
    lines = ["## 一、结论", "", "| 项目 | 取值 |", "| --- | --- |",
             "| 结论 | " + str(comparison.get("verdict_label")) + " |",
             "| 场景 | " + str(comparison.get("scenario")) + " |",
             "| 材料版本 | " + str(comparison.get("material_version")) + " |",
             "| 评分器版本 | " + str(comparison.get("scorer_version")) + " |",
             "| Yudao 一侧 | " + _side_text(comparison.get("yudao"), "提交号") + " |",
             "| OpenCode 一侧 | " + _side_text(comparison.get("opencode"), "版本号") + " |"]
    if comparison.get("block_reason"):
        lines.append("| 受阻原因 | " + str(comparison["block_reason"]) + " |")
    criterion = comparison.get("criterion") or {}
    if criterion.get("runs") or criterion.get("observing"):
        lines.append("| 判定依据 | " + _criterion_text(criterion) + " |")
    return lines + [""]


def _side_text(side, version_label):
    if not side:
        return "未知"
    return (str(side.get("model")) + "，" + version_label + " " + str(side.get("version"))
            + "，" + str(side.get("run_count")) + " 次运行")


def _criterion_text(criterion):
    return ("可以观察质检提高的运行 " + str(criterion.get("observing")) + " 次，满足条件 "
            + str(criterion.get("meeting")) + " 次；第一次交付已全部通过 "
            + str(criterion.get("not_counted")) + " 次（不计入），质检没有给出结论 "
            + str(criterion.get("no_conclusion")) + " 次，质检误放行 "
            + str(criterion.get("false_release")) + " 次")


def _side_criterion_section(comparison):
    criterion = comparison.get("criterion") or {}
    lines = ["## 二、判定依据（N-G1）", ""]
    if not criterion.get("runs"):
        lines.append("没有可以逐次列出的运行。")
        if comparison.get("block_reason"):
            lines.append("")
            lines.append("受阻原因：" + str(comparison["block_reason"]))
        return lines + [""]
    lines.append("| 运行序号 | 运行 | 质检在时间上限以内给出结论 | 第一次交付已全部通过 "
                 "| 提高的隐藏检查条数 | 质检误放行 | 满足条件 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for item in criterion["runs"]:
        lines.append("| " + str(item["run_index"]) + " | " + str(item.get("run_id"))
                     + " | " + _yes_no(item.get("qa_within_limit"))
                     + " | " + ("是（不计入）" if item.get("first_all_passed") else "否")
                     + " | " + _maybe(item.get("passed_gain"))
                     + " | " + _yes_no(item.get("false_release"))
                     + " | " + ("是" if item.get("meets") else "否") + " |")
    lines.append("")
    if comparison.get("block_reason"):
        lines.append("受阻原因：" + str(comparison["block_reason"]))
        lines.append("")
    return lines


_PAIR_HEADER = ("| 运行序号 | Yudao 第一次完成度 | Yudao 最终完成度 | Yudao 正确性 "
                "| Yudao 失败条目 | Yudao 用时（秒） | Yudao 请求数 | Yudao 用量 "
                "| OpenCode 完成度 | OpenCode 正确性 | OpenCode 失败条目 "
                "| OpenCode 用时（秒） | OpenCode 请求数 | OpenCode 用量 |")
_PAIR_RULE = "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"


def _side_pairs_section(comparison):
    lines = ["## 三、逐次并排", ""]
    pairs = comparison.get("pairs") or []
    if not pairs:
        lines.append("没有可以配对的运行。")
        return lines + [""]
    lines.append("两边按运行序号配对（第 1 次对第 1 次）；OpenCode 只有一份交付，"
                 "没有「第一次交付」一列。")
    lines.append("")
    lines.append(_PAIR_HEADER)
    lines.append(_PAIR_RULE)
    for pair in pairs:
        left = pair["yudao"]
        right = pair["opencode"]
        lines.append("| " + str(pair["run_index"])
                     + " | " + _maybe(left.get("completion_first"))
                     + " | " + _maybe(left.get("completion_final"))
                     + " | " + _maybe(left.get("correctness"))
                     + " | " + _failed_text(left.get("failed"))
                     + " | " + _maybe(left.get("elapsed_seconds"))
                     + " | " + _maybe(left.get("model_requests"))
                     + " | " + _maybe(left.get("total_tokens"))
                     + " | " + _maybe(right.get("completion_final"))
                     + " | " + _maybe(right.get("correctness"))
                     + " | " + _failed_text(right.get("failed"))
                     + " | " + _maybe(right.get("elapsed_seconds"))
                     + " | " + _maybe(right.get("model_requests"))
                     + " | " + _maybe(right.get("total_tokens")) + " |")
    lines.append("")
    unpaired = comparison.get("unpaired") or {}
    if unpaired.get("yudao") or unpaired.get("opencode"):
        lines.append("没有配对的部分（序号对不上）：")
        lines.append("")
        for side, label in (("yudao", "Yudao"), ("opencode", "OpenCode")):
            if unpaired.get(side):
                lines.append("- " + label + "：第 "
                             + "、".join(str(index) for index in unpaired[side]) + " 次")
        lines.append("")
    return lines


def _failed_text(failed):
    """失败条目：没有失败时写「无」。"""
    return "、".join(str(item) for item in failed) if failed else "无"


def _basic_section(result):
    # 作废的运行没有评分器版本：只有评分时才有的字段写「未评分」，不拼 None（工单 #1350）
    lines = ["## 一、基本信息", ""]
    lines.append("| 项目 | 取值 |")
    lines.append("| --- | --- |")
    lines.append("| 场景 | " + str(result["scenario"]) + " |")
    lines.append("| 材料版本 | " + str(result["material_version"]) + " |")
    lines.append("| 评分器版本 | " + _scored_text(result.get("scorer_version")) + " |")
    lines.append("| 被测模型 | " + str(result["model"]) + " |")
    lines.append("| Yudao 提交号 | " + _commit_text(result) + " |")
    if result.get("model_capacity"):
        lines.append("| 模型的容量 | " + model_service.describe(result["model_capacity"]) + " |")
    lines.append("| 计入结果的运行次数 | " + str(result["run_count"]) + " |")
    void_runs = [run for run in result.get("runs", []) if run.get("void")]
    if void_runs:
        # 作废的运行正是最需要报告的一类：顶部写清原因与跑到哪一步，没有结论时写明未产生
        lines.append("| 作废原因 | " + "；".join(
            str(run["run_id"]) + "：" + _void_reason_text(run) for run in void_runs) + " |")
        lines.append("| 跑到哪一步 | " + "；".join(
            str(run["run_id"]) + "：" + _void_position(run) for run in void_runs) + " |")
        if result["run_count"] == 0:
            lines.append("| 逐条结论与覆盖读数 | 未产生（没有可以评分的交付） |")
    return lines + [""]


def _scored_text(value):
    """只在评分时才有的字段（评分器版本这类）：作废的运行写「未评分」，不写 None。"""
    return str(value) if value not in (None, "") else "未评分"


def _void_reason_text(run):
    return str(run.get("void_reason") or "未写明原因")


def _void_position(run):
    """作废的运行跑到哪一步：建档没有完成时没有新建事项，事项已经开始的写出运行编号与结束状态。"""
    metrics = run.get("metrics") or {}
    if not run.get("yudao_run_id"):
        reason = metrics.get("end_reason") or "初始 PRD 没有被确认"
        return "建档（" + str(reason) + "，没有新建事项）"
    return "事项运行（" + str(run["yudao_run_id"]) + "，结束状态 " + str(metrics.get("end_status")) + "）"


def _commit_text(result):
    """提交号一栏：各次运行相同时写那个提交号，不同时写明不一致并逐次列出。"""
    commits = result.get("yudao_commits") or []
    if commits and result.get("yudao_commit") is None:
        return "各次运行不一致：" + "、".join(
            str(item["run_id"]) + " " + str(item["yudao_commit"]) for item in commits)
    return str(result.get("yudao_commit") or "未知")


def _host_section(result):
    lines = ["## 二、宿主环境", ""]
    lines.append("| 项目 | 版本 |")
    lines.append("| --- | --- |")
    for key, value in result["host_environment"].items():
        lines.append("| " + key + " | " + value + " |")
    return lines + [""]


def _network_section():
    return ["## 三、联网", "",
            "不联网。被测的 Yudao 以关闭取回的启动参数（`--no-fetch`）启动，三个部门的请求里没有取回工具"
            "（`fetch_url`、`read_external_source`）；评测项目也不设置 MCP 服务器，运行中没有这两类工具的调用。", ""]


def _checkpoints_section(result):
    """过程检查点（第 5.1 节）：结论与依据，逐次运行列出。三态：通过 / 未通过 / 未核实。"""
    lines = ["## 四、过程检查点", ""]
    lines.append("| 检查点 | " + " | ".join(run["run_id"] for run in result["runs"]) + " |")
    lines.append("| --- | " + " | ".join("---" for _ in result["runs"]) + " |")
    for key, label in CHECKPOINT_LABELS.items():
        cells = []
        for run in result["runs"]:
            checkpoint = run["metrics"]["checkpoints"].get(key, {})
            cells.append(_checkpoint_cell(checkpoint))
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
    summary = result["summary"]
    if result["run_count"] == 0:
        # 作废或模型服务故障的运行不进汇总：评分与噪声范围写「未评分」（工单 #1350）
        lines.append("没有计入结果的运行。评分（完成度、正确性）与噪声范围：未评分。")
        lines.append("")
        lines.extend(_onboarding_section(result))
        return lines
    if summary:
        lines.append("噪声范围是同一版本各次运行的取值极差（最大值减最小值）；只有一次运行、"
                     "或该项全部未知时写「未知」。")
        lines.append("")
        lines.append("| 指标 | 平均值 | 最小值 | 最大值 | 噪声范围（极差） | 有效样本数 | 未知样本数 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for name, item in summary.items():
            if "mean" in item:
                cells = [_number(item["mean"]), _number(item["min"]), _number(item["max"]),
                         "未知" if item.get("spread") is None else _number(item["spread"])]
            else:
                cells = ["未知", "未知", "未知", "未知"]
            lines.append("| " + METRIC_LABELS.get(name, name) + " | " + " | ".join(cells)
                         + " | " + str(item["count"] - item.get("unknown", 0))
                         + " | " + str(item.get("unknown", 0)) + " |")
    else:
        lines.append("没有计入结果的运行。")
    lines.append("")
    unknowns = [(name, item.get("unknown_reason", "")) for name, item in summary.items()
                if item.get("unknown")]
    if unknowns:
        lines.append("未知样本不进均值、最小值与最大值。缺失的原因：")
        lines.append("")
        for name, reason in unknowns:
            lines.append("- " + METRIC_LABELS.get(name, name) + "：" + reason)
        lines.append("")
    lines.extend(_onboarding_section(result))
    return lines


def _scenario_title(name):
    """场景名写成中文（报告标题用）：`scenario-2` 写成「场景 2」。"""
    tail = str(name).rsplit("-", 1)[-1]
    return "场景 " + tail if tail.isdigit() else str(name)


def _onboarding_section(result):
    """场景 2 的建档（第 5.2 节）：模型请求数、用量与耗时单独列出，不计入事项的指标。"""
    onboarding = result.get("onboarding") or []
    if not onboarding:
        return []
    lines = ["### 建档（场景 2）：模型请求数、用量与耗时", ""]
    lines.append("建档与事项是两个 run：下面这些数值不计入上面的指标汇总，也不进均值与噪声（第 5.2 节）。")
    lines.append("")
    lines.append("| 运行 | 模型请求数 | 输入用量 | 输出用量 | 总用量 | 耗时（秒） |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for item in onboarding:
        lines.append("| " + item["run_id"] + " | " + _number(item.get("model_requests", 0))
                     + " | " + _maybe(item.get("input_tokens"))
                     + " | " + _maybe(item.get("output_tokens"))
                     + " | " + _maybe(item.get("total_tokens"))
                     + " | " + _maybe(item.get("elapsed_seconds")) + " |")
    lines.append("")
    return lines


def _checkpoint_cell(checkpoint):
    if checkpoint.get("passed") is None:
        return "未核实"
    return "通过" if checkpoint.get("passed") else "未通过"


def _maybe(value):
    """用量字段缺失时写「未知」，不记 0（设计第 5.2 节）。"""
    return "未知" if value is None else _number(value)


def _version_text(value):
    """定义版本与参数版本（`run_created` 事件）：取不到时写「未知」。"""
    return str(value) if value not in (None, "") else "未知"


def _yes_no(value):
    return "是" if value else "否"


def _delivery_part(run, name, key=None):
    """一次运行里第一次或最终交付的指标（`run["delivery"][name]`）。"""
    item = (run.get("delivery") or {}).get(name)
    return item.get(key) if (key and item) else item


def _passed_checks_text(item):
    """一份交付通过了几条隐藏检查；没有交付时写「没有做」（第 4.1 节的分类）。"""
    if not item:
        return "未知"
    if not item.get("delivered"):
        return "没有做（没有交付）"
    return str(item.get("passed_checks")) + "/" + str(item.get("total_checks"))


def _improvement_text(improvement):
    """质检带来的提高：条数、不计入与没有结论各写清楚（第 6.3 节第 1 条）。"""
    improvement = improvement or {}
    status = improvement.get("status")
    if status == "improved":
        return "提高 " + str(improvement.get("passed_gain")) + " 条：" + str(improvement.get("detail"))
    if status == "none":
        return "没有提高（" + str(improvement.get("detail")) + "）"
    if status == "not_counted":
        return "不计入：" + str(improvement.get("detail"))
    if status == "no_conclusion":
        return "未知：" + str(improvement.get("detail"))
    return "未知"


def run_section(run, scores):
    """一次运行的中文小节：指标、评分与失败条目。

    场景 2 另列建档的模型请求数、用量与耗时（第 5.2 节）：建档与事项是两个 run，
    建档的数值不并入上面那一张表，也不计入汇总。初始 PRD 没有被确认的运行没有
    可以评分的交付（`scores` 为 None），这一节写「作废，未评分」。
    """
    metrics = run["metrics"]
    lines = ["### " + run["run_id"], ""]
    lines.append("| 项目 | 取值 |")
    lines.append("| --- | --- |")
    lines.append("| 结束状态 | " + str(metrics["end_status"]) + " |")
    lines.append("| 结束原因 | " + str(metrics["end_reason"]) + " |")
    lines.append("| 停止原因 | " + str(metrics["stop_reason"]) + " |")
    if run.get("yudao_commit"):
        lines.append("| Yudao 提交号 | " + str(run["yudao_commit"]) + " |")
    lines.append("| 定义版本 | " + _version_text(run.get("definitions_version")) + " |")
    lines.append("| 参数版本 | " + _version_text(run.get("parameters_version")) + " |")
    lines.append("| 循环次数 | " + _number(metrics["cycles"]) + " |")
    lines.append("| 返工次数 | " + _number(metrics["rework"]) + " |")
    lines.append("| 部门之间询问次数 | " + _number(metrics["collaboration"]) + " |")
    lines.append("| 模型请求数 | " + _number(metrics["model_requests"]) + " |")
    lines.append("| 输入用量 | " + _maybe(metrics["input_tokens"]) + " |")
    lines.append("| 输出用量 | " + _maybe(metrics["output_tokens"]) + " |")
    lines.append("| 总用量 | " + _maybe(metrics["total_tokens"]) + " |")
    lines.append("| 费用 | " + _maybe(metrics["cost"]) + " |")
    lines.append("| 耗时（秒） | " + _maybe(metrics["elapsed_seconds"]) + " |")
    lines.append("| 封存的交付文件数 | " + _number(run.get("delivery_files", 0)) + " |")
    lines.append("| 第一次封存的交付文件数 | "
                 + _number(run.get("first_delivery_files", run.get("delivery_files", 0))) + " |")
    lines.append("| 成功但没有输出项的模型调用 | "
                 + _number(metrics.get("empty_model_responses", 0)) + " |")
    if scores is None:
        lines.append("| 评分 | 作废，未评分 |")
        lines.append("")
        lines.extend(_failures_section(run, None))
        return lines
    lines.append("| 第一次交付的完成度 | " + _maybe(_delivery_part(run, "first", "completion"))
                 + " |")
    lines.append("| 完成度 | " + _number(scores["completion"]) + " |")
    lines.append("| 正确性 | " + _number(scores["correctness"]) + " |")
    lines.append("| 第一次交付通过的隐藏检查 | " + _passed_checks_text(_delivery_part(run, "first"))
                 + " |")
    lines.append("| 最终交付通过的隐藏检查 | " + _passed_checks_text(_delivery_part(run, "final"))
                 + " |")
    lines.append("| 质检在时间上限以内给出结论 | "
                 + _yes_no((run.get("delivery") or {}).get("qa_within_limit")) + " |")
    lines.append("| 质检带来的提高 | "
                 + _improvement_text((run.get("delivery") or {}).get("qa_improvement")) + " |")
    lines.append("| 未做的隐藏检查数 | " + _number(scores["not_done_count"]) + " |")
    lines.append("| 出错的隐藏检查数 | " + _number(scores["wrong_count"]) + " |")
    lines.append("")
    lines.extend(_failures_section(run, scores))
    return lines


def _failures_section(run, scores):
    """失败条目：未通过的要求与没有通过的隐藏检查（第 6 节要求写进报告）。"""
    lines = ["失败条目：", ""]
    if scores is None:
        lines.append("作废：没有可以评分的交付。")
        lines.append("")
        if run.get("void"):
            lines.append("这次运行作废：" + str(run.get("void_reason", "")))
            lines.append("")
        return lines
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
