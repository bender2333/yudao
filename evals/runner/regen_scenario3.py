"""从可取回的旧版 JSON 重生 `docs/evaluation/scenario-3-yudao.json` 与 `.md`。

本次重算以已提交的旧版 JSON 为输入，重算检查点与用量 unknown 字段：
- 输入：旧版 JSON（默认从 `origin/main` 的 `docs/evaluation/scenario-3-yudao.json`
  读取；测试可指定 `--source <path>` 从本地副本读）。
- 重算只重新解释旧 JSON 已有的字段——不再现原始导出，不补造未知字段。
- 旧 JSON 里没有的字段（replay 结果、质检 payload、覆盖比例、参数版本）一律标
  为「未核实」，不取回也不补造。
- 旧 JSON 里上报为零的 `total_tokens`/`model_latency_ms` 仍按上游上报值原样保留
  （旧口径：缺失字段记 0，按上限报 `total` 时分项未上报）；仓库内没有原始事件日志
  可核对其来源，因此报告写「来源未核实」。

脚本与评测工具共用 `yudao_report` 中的形状，保证生成结果与
`docs/evaluation/scenario-3-yudao.json` 的现有口径一致。
"""
import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
sys.path.insert(0, os.path.join(ROOT, "evals", "runner"))

import yudao_report  # noqa: E402

DEFAULT_SOURCE = "origin/main:docs/evaluation/scenario-3-yudao.json"
DEFAULT_JSON = os.path.join(ROOT, "docs", "evaluation", "scenario-3-yudao.json")
DEFAULT_MD = os.path.join(ROOT, "docs", "evaluation", "scenario-3-yudao.md")


def _read_source(path):
    """读旧版 JSON：本地路径直接读，git 引用走 `git show`。"""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    if ":" in path:
        result = subprocess.run(
            ["git", "-C", ROOT, "show", path],
            check=True, capture_output=True, encoding="utf-8")
        return json.loads(result.stdout)
    raise FileNotFoundError(path)


def _reshape_checkpoints(run_metrics, hidden_failures):
    """按新六项口径重算检查点；未核实项如实标注。"""
    released = run_metrics.get("end_status") == "released"
    phase = run_metrics.get("phase")
    stop_reason = run_metrics.get("stop_reason")
    if released:
        detail = ("运行在冻结限额内以放行结束：阶段 " + str(phase)
                  + "、停止原因 " + str(stop_reason)
                  + "、质检已放行、用量未超限额")
    else:
        detail = "运行未通过放行判定：阶段 " + str(phase) + "（实际为 " + str(phase) + "）；停止原因 " + str(stop_reason) + "（实际为 " + str(stop_reason) + "）；没有当前交付快照的质检放行；用量未超限额"
    return {
        "ended_within_limit": {"passed": released, "applicable": True, "detail": detail},
        "quality_release_bound_to_delivery": {
            "passed": (not released), "applicable": released,
            "detail": "本次没有放行，本项不适用" if not released else
                      "质检已放行；待按 parameters_version 与本次激活核对回收记录。",
            "recheck_ratio": None, "self_run": None, "checks_total": None,
            "recheck_ratio_status": "unverified",
            "recheck_ratio_note": "原始事件日志不在仓库内，取不回 parameters_version"},
        "no_write_before_plan_accepted": {
            "passed": None, "applicable": True,
            "detail": "原始事件日志不在仓库内，工程是否在计划被接纳前写入待核实。"},
        "replay_consistent": {
            "passed": None, "applicable": True,
            "detail": "原始事件日志不在仓库内，重放结果无法取回，按未核实。"},
        "no_false_release": {
            "passed": True,
            "detail": ("本次没有放行，不存在误放行；隐藏检查的失败条目："
                       + "、".join(hidden_failures))
            if (not released and hidden_failures)
            else ("本次没有放行，不存在误放行"
                  if not released else "质检放行，隐藏检查中无失败条目（按现报）")},
        "release_coverage": {
            "passed": (not released), "applicable": released,
            "covered_ratio": None, "model_read_count": None, "open_loop_count": None,
            "detail": "本次没有放行，本项不适用" if not released else
                      "原始事件日志不在仓库内，逐条覆盖、模型阅读与开环数据无法取回，按未核实。"},
    }


def _shape_run_metrics(run_metrics):
    """用量按新口径：input/output/cache_read/cache_write/cost 为未知。"""
    out = dict(run_metrics)
    for key in ("input_tokens", "output_tokens", "cache_read_tokens",
                "cache_write_tokens", "cost"):
        out[key] = None
    return out


def _extract_hidden_failures(run):
    """从旧版检查点的 `no_false_release` 提取隐藏检查失败条目。"""
    detail = (run.get("metrics", {}).get("checkpoints", {})
              .get("no_false_release", {}).get("detail", ""))
    if "隐藏检查的失败条目：" not in detail:
        return []
    tail = detail.split("隐藏检查的失败条目：", 1)[1]
    return [part.strip() for part in tail.split("、") if part.strip()]


def regenerate(source, comparison=None):
    """重算：从 source 读到旧版 JSON，重算检查点与用量 unknown。"""
    data = _read_source(source)

    notes = list(data.get("notes") or [])
    notes.append("证据不可取回：原始 `evidence_dir` 指向 issue-192 worktree 下的 "
                 "`.yudao/evals/`，本工单仓库内没有这些文件，无法重算检查点依据与 "
                 "hidden_failures 取回；按设计要求标为「未核实」。")
    notes.append("用量按新口径：input_tokens / output_tokens / cache_read_tokens / "
                 "cache_write_tokens / cost 字段都记未知（None），不进均值、不进最小/"
                 "最大、不进噪声。")
    notes.append("总用量（`total_tokens`）沿用旧 JSON 上报值：旧口径按 `usage.totals` "
                 "原值记入；上游分项统计（input_tokens / output_tokens）未上报时归零，"
                 "本工单仓库内无原始事件日志，来源未核实。")
    notes.append("三次运行的版本比较（#324）尚未开展，本次报告未提供版本比较段；"
                 "同版本重复运行的离散由后续阶段补上。")
    notes.append("交付到 `docs/evaluation/scenario-3-yudao.json` 的 `replay` / "
                 "`qa_submitted` payload / `coverage` 等逐项未核实字段未补造。")

    runs = []
    for run in data["runs"]:
        metrics = copy.deepcopy(run["metrics"])
        hidden_failures = _extract_hidden_failures(run)
        metrics.update(_shape_run_metrics(metrics))
        metrics["checkpoints"] = _reshape_checkpoints(metrics, hidden_failures)
        new_run = dict(run)
        new_run["metrics"] = metrics
        runs.append(new_run)

    payload = {
        "scenario": data["scenario"],
        "material_version": data["material_version"],
        "scorer_version": data["scorer_version"],
        "side": data["side"],
        "model": data["model"],
        "yudao_commit": data["yudao_commit"],
        "network": data["network"],
        "host_environment": data["host_environment"],
        "run_count": data["run_count"],
        "void_runs": data.get("void_runs", []),
        "model_service_failures": data.get("model_service_failures", []),
        "notes": notes,
        "summary": yudao_report.aggregate_metrics(runs),
        "runs": runs,
    }
    if comparison is not None:
        payload["comparison"] = comparison
    return payload


def render_md(payload):
    """把 payload 渲成中文报告文本：用 `yudao_report.write_report` 落到临时文件再读回。"""
    run_reports = [yudao_report.run_section(run, run.get("score") or {})
                   for run in payload["runs"]]
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                     encoding="utf-8") as handle:
        path = handle.name
    try:
        yudao_report.write_report(payload, path, run_reports)
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    finally:
        os.unlink(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=DEFAULT_SOURCE,
                        help="旧版 JSON 路径（默认 origin/main 上的文档）")
    parser.add_argument("--json-out", default=DEFAULT_JSON)
    parser.add_argument("--md-out", default=DEFAULT_MD)
    parser.add_argument("--check", action="store_true",
                        help="仅在生成结果与磁盘文件不一致时打印差异并以 1 退出")
    args = parser.parse_args(argv)

    payload = regenerate(args.source)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    md_text = render_md(payload)

    if args.check:
        existing_json = (open(args.json_out, encoding="utf-8").read()
                         if os.path.exists(args.json_out) else "")
        existing_md = (open(args.md_out, encoding="utf-8").read()
                       if os.path.exists(args.md_out) else "")
        if json_text != existing_json or md_text != existing_md:
            print("regenerate: output differs from committed files")
            return 1
        print("regenerate: output matches committed files")
        return 0
    with open(args.json_out, "w", encoding="utf-8") as handle:
        handle.write(json_text)
    with open(args.md_out, "w", encoding="utf-8") as handle:
        handle.write(md_text)
    print("wrote", args.json_out, "and", args.md_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
