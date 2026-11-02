"""读一次评测运行导出的事件日志（run-export.json）与评分结果（metrics.json），回答三件事：
循环几轮、停在哪个部门哪一层、质检的结论与评分器是否一致。

用法：uv run python docs/research/architecture-diagnosis-2026-10-19/read_export.py <证据目录>
证据目录是 .yudao/evals/scenario-3/yudao/<运行编号>，里面有 run-export.json 与 metrics.json。
只读文件，不导入 harness。层的对应按总体架构说明与循环与收敛设计说明第 2 节，取其中四层：角色的步骤循环、部门激活、部门之间的循环、项目循环。
"""
import collections
import json
import pathlib
import sys

# 停止原因属于哪一层（定义里没有循环层，循环与收敛设计说明第 2 节还没有实施，这张表是手工对应）：步数、不调用工具与模型故障发生在角色的步骤循环里；循环次数是部门之间的循环；
# 时间、取消与放行是整个 run（项目循环里的一个事项）。未列出的原样报告
LAYER = {"no_tool_call": "角色的步骤循环", "model_steps_exhausted": "角色的步骤循环",
         "provider_error": "角色的步骤循环", "provider_timeout": "角色的步骤循环",
         "provider_protocol": "角色的步骤循环", "retry_after_too_long": "角色的步骤循环",
         "context_overflow": "角色的步骤循环", "compaction_failed": "角色的步骤循环",
         "workspace_unrepresentable": "部门激活", "host_commit_error": "部门激活",
         "max_cycles": "部门之间的循环", "time_limit": "事项（run）", "cancelled": "事项（run）",
         "released": "事项（run）"}


def main(evidence):
    evidence = pathlib.Path(evidence)
    export = json.loads((evidence / "run-export.json").read_text("utf-8"))
    metrics = json.loads((evidence / "metrics.json").read_text("utf-8"))
    events = export["events"]
    types = collections.Counter(e["type"] for e in events)
    activations = [(e.get("department"), (e.get("payload") or {}).get("cycle")) for e in events
                   if e["type"] == "department_activated"]
    print("## 循环")
    print("- 部门激活 %d 次：%s" % (len(activations), " → ".join("%s(%s)" % a for a in activations)))
    transitions = [(e["payload"].get("from"), e["payload"].get("to")) for e in events if e["type"] == "transition"]
    print("- 阶段转换：%s" % " → ".join([transitions[0][0]] + [t[1] for t in transitions]) if transitions else "- 没有阶段转换")
    rework = [e["payload"].get("verdict") for e in events if e["type"] == "qa_submitted"]
    print("- 质检结论：%s" % (rework or "没有"))
    print("- 交付被接纳 %d 次，提案被拒 %d 次，询问 %d 次" % (
        types["delivery_accepted"], types["proposal_rejected"], types["collaboration_requested"]))
    for e in events:
        if e["type"] == "proposal_rejected":
            p = e.get("payload") or {}
            print("  - 拒绝 #%s %s：%s" % (e.get("position"), e.get("department"),
                                       str(p.get("reason") or p.get("errors") or p)[:200]))
    tools = collections.Counter((e.get("department"), (e.get("payload") or {}).get("name"))
                                for e in events if e["type"] == "tool_started")
    print("- 工具调用：%s" % dict(tools))
    failed = collections.Counter((e.get("department"), (e.get("payload") or {}).get("reason"))
                                 for e in events if e["type"] == "model_attempt_failed")
    print("- 模型尝试：完成 %d，失败 %d %s" % (types["model_attempt_finished"], types["model_attempt_failed"], dict(failed)))
    print("- 工具调用缺失的提示（tool_call_required）%d 次，压缩 %d 次" % (types["tool_call_required"], types["compaction_recorded"]))
    print("\n## 停在哪里")
    ends = [e for e in events if e["type"] in ("run_done", "run_paused", "run_failed")]
    if ends:
        last = ends[-1]
        reason = last.get("stop_reason") or (last.get("payload") or {}).get("stop_reason")
        active = [e for e in events if e["type"] == "department_activated"]
        print("- 事件 #%s %s，停止原因 %s，层：%s，最后在工作的部门：%s" % (
            last.get("position"), last["type"], reason, LAYER.get(reason, "未归类"),
            active[-1].get("department") if active else None))
        if last.get("error"):
            print("- 错误：%s" % last["error"][:300])
    else:
        print("- 导出中没有结束事件")
    print("\n## 质检与评分器")
    score = metrics["score"]
    failing = [c for c in score["checks"] if c["status"] != "pass"]
    print("- 评分：完成度 %s，正确性 %s，通过 %d / %d" % (score.get("completion"), score.get("correctness"),
                                                 len(score["checks"]) - len(failing), len(score["checks"])))
    by_status = collections.Counter(c["status"] for c in failing)
    print("- 未通过的检查按状态：%s" % dict(by_status))
    checkpoints = metrics["metrics"].get("checkpoints", {})
    for key, item in checkpoints.items():
        print("- 检查点 %s：%s" % (key, item.get("passed")))
    print("- 质检放行：%s；隐藏检查失败 %d 条" % (any(v == "release" for v in rework), len(failing)))


if __name__ == "__main__":
    main(sys.argv[1])
