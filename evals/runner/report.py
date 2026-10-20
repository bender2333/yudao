"""报告：机器可读的结果与中文报告。

结果记录 OpenCode 版本号、模型、材料版本、评分器版本、宿主环境与每次运行的
全部指标与失败条目（第 6 节）。多次运行时每个指标报告平均值、最小值与最大值。
原始证据放在 .yudao/evals/ 下，结果与报告提交到 docs/evaluation/。
"""

import json
import os
import platform
import shutil
import subprocess

AGGREGATED_METRICS = ("request_count", "input_tokens", "output_tokens",
                      "cache_read_tokens", "cache_write_tokens", "cost",
                      "elapsed_seconds")


def host_environment():
    return {
        "system": platform.system() + " " + platform.release() + " (" + platform.machine() + ")",
        "python": platform.python_version(),
        "uv": _version("uv"),
        "node": _version("node"),
        "opencode": _version("opencode"),
        "git": _version("git"),
    }


def _version(name):
    """记录宿主环境里的工具版本（第 6 节）。"""
    executable = shutil.which(name)
    if executable is None:
        return "not installed"
    result = subprocess.run([executable, "--version"], capture_output=True,
                            encoding="utf-8", errors="replace")
    return (result.stdout or result.stderr or "").strip() or "not installed"


def aggregate(runs):
    """多次运行的平均值、最小值与最大值（第 5.2 节）。"""
    counts = []
    for run in runs:
        if run.get("void") or run.get("model_service_failure"):
            continue
        counts.append(run)
    summary = {}
    for name in AGGREGATED_METRICS:
        values = [float(run["metrics"][name]) for run in counts
                  if name in run.get("metrics", {}) and run["metrics"][name] is not None]
        if not values:
            continue
        summary[name] = {
            "count": len(values),
            "mean": sum(values) / len(values),
            "min": min(values),
            "max": max(values),
        }
    return summary


def build_result(scenario, material_version, scorer_version, model, runs):
    counted = [run for run in runs
               if not run.get("void") and not run.get("model_service_failure")]
    return {
        "scenario": scenario,
        "material_version": material_version,
        "scorer_version": scorer_version,
        "side": "opencode",
        "model": model,
        "opencode_version": host_environment()["opencode"],
        "network": {
            "allowed": False,
            "note": "两边都不联网：Yudao 的评测项目不登记取回来源与 MCP 服务器；"
                    "OpenCode 的运行配置关闭 webfetch 与 websearch，"
                    "运行器检查 JSON 输出中没有这两类工具的调用。",
        },
        "host_environment": host_environment(),
        "run_count": len(counted),
        "void_runs": [run["run_id"] for run in runs if run.get("void")],
        "model_service_failures": [run["run_id"] for run in runs
                                   if run.get("model_service_failure")],
        "summary": aggregate(runs),
        "runs": runs,
    }


def write_result(result, path):
    _write(path, json.dumps(result, ensure_ascii=False, indent=2) + "\n")


def _scenario_title(scenario):
    return {"scenario-1": "场景 1：网页应用",
            "scenario-2": "场景 2：在已有代码上加功能",
            "scenario-3": "场景 3：从较长的 PRD 新建项目"}[scenario]


def write_report(result, path, run_reports):
    lines = []
    lines.append("# " + _scenario_title(result["scenario"]) + " · OpenCode 一侧评测报告")
    lines.append("")
    lines.append("## 一、基本信息")
    lines.append("")
    lines.append("| 项目 | 取值 |")
    lines.append("| --- | --- |")
    lines.append("| 场景 | " + result["scenario"] + " |")
    lines.append("| 材料版本 | " + result["material_version"] + " |")
    lines.append("| 评分器版本 | " + result["scorer_version"] + " |")
    lines.append("| 被测模型 | " + result["model"] + " |")
    lines.append("| OpenCode 版本 | " + result["opencode_version"] + " |")
    lines.append("| 计入结果的运行次数 | " + str(result["run_count"]) + " |")
    lines.append("")
    lines.append("## 二、宿主环境")
    lines.append("")
    lines.append("| 项目 | 版本 |")
    lines.append("| --- | --- |")
    for key, value in result["host_environment"].items():
        lines.append("| " + key + " | " + value + " |")
    lines.append("")
    lines.append("## 三、联网")
    lines.append("")
    lines.append("两边都不联网。任务来自公开仓库，联网取回可能直接取回上游的答案。")
    lines.append("OpenCode 的运行配置中取回与搜索工具（webfetch、websearch）关闭；"
                 "运行器检查 JSON 输出中没有这两类工具的调用。")
    lines.append("")
    lines.append("## 四、指标汇总")
    lines.append("")
    if result["summary"]:
        lines.append("| 指标 | 平均值 | 最小值 | 最大值 |")
        lines.append("| --- | --- | --- | --- |")
        for name, item in result["summary"].items():
            lines.append("| " + _metric_label(name) + " | " + _number(item["mean"])
                         + " | " + _number(item["min"]) + " | " + _number(item["max"]) + " |")
    else:
        lines.append("没有计入结果的运行。")
    lines.append("")
    lines.append("## 五、逐次运行")
    lines.append("")
    for item in run_reports:
        lines.extend(item)
    lines.append("")
    lines.append("## 六、不计入结果的运行")
    lines.append("")
    lines.extend(_excluded_section(result, runs=result["runs"]))
    lines.append("")
    lines.append("原始证据（交付副本、输出、评分日志）在 `.yudao/evals/` 下，不进入 Git。")
    _write(path, "\n".join(lines) + "\n")


def run_section(run, scores):
    """一次运行的中文小节。"""
    lines = ["### " + run["run_id"], ""]
    lines.append("| 项目 | 取值 |")
    lines.append("| --- | --- |")
    lines.append("| 结束状态 | " + run["metrics"]["status"] + " |")
    lines.append("| 结束原因 | " + run["metrics"]["reason"] + " |")
    lines.append("| 超时 | " + ("是" if run["metrics"]["timed_out"] else "否") + " |")
    lines.append("| 模型请求数 | " + str(run["metrics"]["request_count"]) + " |")
    lines.append("| 输入用量 | " + str(run["metrics"]["input_tokens"]) + " |")
    lines.append("| 输出用量 | " + str(run["metrics"]["output_tokens"]) + " |")
    lines.append("| 耗时（秒） | " + _number(run["metrics"]["elapsed_seconds"]) + " |")
    lines.append("| 完成度 | " + _number(scores["completion"]) + " |")
    lines.append("| 正确性 | " + _number(scores["correctness"]) + " |")
    if "richness" in scores and scores["richness"] is not None:
        richness_data = scores["richness"]
        r_score = richness_data.get("score") if isinstance(richness_data, dict) else richness_data
        lines.append("| 丰富程度 | " + _number(r_score) + " |")
    lines.append("| 这次运行是否作废 | " + ("是" if run.get("void") else "否") + " |")
    lines.append("")
    if run.get("void_reasons"):
        lines.append("作废原因：")
        for reason in run["void_reasons"]:
            lines.append("- " + reason)
        lines.append("")
    lines.append("需求条目得分：")
    lines.append("")
    lines.append("| 条目 | 通过 | 总数 | 得分 |")
    lines.append("| --- | --- | --- | --- |")
    for name, item in scores["requirements"].items():
        lines.append("| " + name + " | " + str(item["passed"]) + " | "
                     + str(item["total"]) + " | " + _number(item["score"]) + " |")
    lines.append("")
    has_screenshots = any("screenshots" in item for item in scores.get("checks", []))
    if has_screenshots:
        lines.append("逐条用例：")
        lines.append("")
        lines.append("| 用例 | 条目 | 结论 | 得分 | 截图位置 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for item in scores["checks"]:
            conclusion = _conclusion(item)
            score_val = _number(item.get("score", 0))
            shots = item.get("screenshots") or []
            if shots:
                shot_dir = _relative_to_repo(os.path.dirname(shots[-1]))
                last_shot = _relative_to_repo(shots[-1])
                loc = f"目录：{shot_dir}，最后截图：{last_shot}"
            else:
                loc = "无"
            lines.append(f"| {item['id']} | {item.get('requirement', '')} | {conclusion} | {score_val} | {loc} |")
        lines.append("")

    failed = [item for item in scores["checks"] if item["status"] != "pass"]
    if failed:
        lines.append("失败条目：")
        lines.append("")
        lines.append("| 检查 | 条目 | 分类 | 详情 |")
        lines.append("| --- | --- | --- | --- |")
        for item in failed:
            label = "没有做" if item["status"] == "not_done" else "做了但结果不对"
            lines.append("| " + item["id"] + " | " + item["requirement"] + " | "
                         + label + " | " + item["detail"].replace("|", "/") + " |")
        lines.append("")

    regression = scores.get("regression")
    if regression is not None:
        lines.append("原有功能（" + str(regression["total"]) + " 条 P2P，失败条数不计入完成度）：")
        lines.append("")
        lines.append("| 项目 | 取值 |")
        lines.append("| --- | --- |")
        lines.append("| 通过 | " + str(regression["passed"]) + " |")
        lines.append("| 失败 | " + str(regression["failed"]) + " |")
        lines.append("")
        if regression["failures"]:
            lines.append("失败的原有功能测试：")
            lines.append("")
            lines.append("| 测试 | 详情 |")
            lines.append("| --- | --- |")
            for item in regression["failures"]:
                lines.append("| " + item["id"] + " | " + item["detail"].replace("|", "/") + " |")
            lines.append("")
    richness = scores.get("richness")
    if richness is not None:
        items = richness.get("items") if isinstance(richness, dict) else richness
        lines.append("丰富程度：")
        lines.append("")
        lines.append("| 检查项 | 得分 | 理由 |")
        lines.append("| --- | --- | --- |")
        for item in items:
            title = item.get("title", "")
            score_val = _number(item.get("score", 0))
            reason = str(item.get("reason") or item.get("comment") or "").replace("|", "/")
            lines.append(f"| {title} | {score_val} | {reason} |")
        lines.append("")
    return lines


def _excluded_section(result, runs):
    lines = []
    if not result["void_runs"] and not result["model_service_failures"]:
        lines.append("没有作废的运行，也没有因为模型服务故障结束的运行。")
        return lines
    for run in runs:
        if run["run_id"] not in result["void_runs"] + result["model_service_failures"]:
            continue
        if run["run_id"] in result["model_service_failures"]:
            lines.append("- " + run["run_id"] + "：因为模型服务故障结束，不计入结果，按规定补跑。")
        else:
            lines.append("- " + run["run_id"] + "：这次运行作废。")
            for reason in run.get("void_reasons", []):
                lines.append("  - " + reason)
    return lines


_METRIC_LABELS = {
    "request_count": "模型请求数",
    "input_tokens": "输入用量",
    "output_tokens": "输出用量",
    "cache_read_tokens": "缓存读取用量",
    "cache_write_tokens": "缓存写入用量",
    "cost": "费用",
    "elapsed_seconds": "耗时（秒）",
}


def _metric_label(name):
    return _METRIC_LABELS.get(name, name)


def _number(value):
    value = float(value)
    return str(int(value)) if value == int(value) else ("%.4f" % value).rstrip("0").rstrip(".")


def _write(path, text):
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def default_evidence_dir():
    """原始证据目录：仓库根的 .yudao/evals/（已被 git 忽略）。"""
    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    return os.path.join(root, ".yudao", "evals")

def _conclusion(item):
    if item.get("status") == "pass" or item.get("verdict") == "YES":
        return "通过"
    if item.get("score") == 0.5 or item.get("verdict") == "PARTIAL":
        return "部分通过"
    if item.get("status") == "not_done" or item.get("verdict") == "NOT_DONE":
        return "没有做"
    return "不通过"


def _relative_to_repo(path):
    if not path:
        return ""
    p = os.path.abspath(path).replace("\\", "/")
    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")).replace("\\", "/")
    if p.startswith(root):
        return os.path.relpath(p, root).replace("\\", "/")
    idx = p.find(".yudao/evals/")
    if idx != -1:
        return p[idx:]
    return p
