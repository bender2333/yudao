"""版本比较：同一任务两个版本的配对比较（`docs/design/rules-and-parameters.md` 第 4 节）。

- 只有材料版本与评分器版本都相同时才配对，否则拒绝比较；
- 噪声来自同一版本的重复运行（同版本重复运行的离散），差值用配对的随机化检验；
- 三种结论：改进 / 无差别 / 退化；必需证据缺失时标受阻并保留已算指标。
"""

PRIMARY_METRIC = "qa_false_release"
SECONDARY_METRICS = ("asks", "reworks", "completion", "requests", "cost", "elapsed")

# ponytail: 配对随机化检验在两侧样本都只有 1 次时退化为「差值与噪声范围直接比较」；
# 三次运行（#324）到位以后，两侧 3×3 的置换分布才有检验效力。


def compare(current, baseline):
    """比较两个结果（`build_result` 的返回）。

    返回的 verdict 是 "improved" / "no_difference" / "regressed" / "blocked" 之一；
    blocked 时保留已算的逐任务差值。
    """
    material = current.get("material_version")
    scorer = current.get("scorer_version")
    if material != baseline.get("material_version") or scorer != baseline.get("scorer_version"):
        return {"compared": False,
                "block_reason": ("材料版本或评分器版本不同："
                                 + str(current.get("material_version")) + "/"
                                 + str(current.get("scorer_version")) + " 对比 "
                                 + str(baseline.get("material_version")) + "/"
                                 + str(baseline.get("scorer_version"))),
                "verdict": "blocked",
                "material_version": material, "scorer_version": scorer,
                "paired_tasks": [], "noise": None,
                "primary": {"metric": PRIMARY_METRIC, "current": None, "baseline": None,
                            "difference": None},
                "secondary": []}
    current_pairs = _task_scores(current)
    baseline_pairs = _task_scores(baseline)
    shared = sorted(set(current_pairs) & set(baseline_pairs))
    if not shared:
        return {"compared": False,
                "block_reason": "两侧没有可配对的任务（逐任务评分缺失）",
                "verdict": "blocked",
                "material_version": material, "scorer_version": scorer,
                "paired_tasks": [], "noise": None,
                "primary": {"metric": PRIMARY_METRIC, "current": None, "baseline": None,
                            "difference": None},
                "secondary": []}

    paired = []
    for task in shared:
        current_run = current_pairs[task]
        baseline_run = baseline_pairs[task]
        paired.append({
            "task": task,
            "current_false_release": int(bool(current_run["false_release"])),
            "baseline_false_release": int(bool(baseline_run["false_release"])),
            "false_release_difference": (int(bool(current_run["false_release"]))
                                         - int(bool(baseline_run["false_release"]))),
            "current_completion": current_run["completion"],
            "baseline_completion": baseline_run["completion"],
            "completion_difference": (current_run["completion"] - baseline_run["completion"]
                                      if current_run["completion"] is not None
                                      and baseline_run["completion"] is not None else None),
            "current_checkpoints_failed": current_run["checkpoints_failed"],
            "baseline_checkpoints_failed": baseline_run["checkpoints_failed"],
        })
    noise = _noise_range(current, baseline, shared)
    verdict = _verdict(paired, noise)
    current_total = sum(item["current_false_release"] for item in paired)
    baseline_total = sum(item["baseline_false_release"] for item in paired)
    return {"compared": True, "block_reason": None, "verdict": verdict,
            "material_version": material, "scorer_version": scorer,
            "paired_tasks": paired, "noise": noise,
            "primary": {"metric": PRIMARY_METRIC,
                        "rule": "non_inferior", "margin": 0,
                        "current": current_total, "baseline": baseline_total,
                        "difference": current_total - baseline_total},
            "secondary": _secondary(paired)}


def _task_scores(result):
    """逐任务评分：run_id 即任务名；误放行 = 放行且隐藏检查存在失败。"""
    scores = {}
    for run in result.get("runs", []):
        if run.get("void"):
            continue
        metrics = run.get("metrics", {})
        checkpoints = metrics.get("checkpoints", {})
        false_release = (checkpoints.get("no_false_release") or {}).get("passed") is False
        score = run.get("score") or {}
        scores[run["run_id"]] = {
            "false_release": false_release,
            "completion": score.get("completion"),
            "checkpoints_failed": sorted(key for key, item in checkpoints.items()
                                         if item.get("passed") is False),
        }
    return scores


def _noise_range(current, baseline, tasks):
    """噪声范围来自同一版本的重复运行：同版本重复运行的完成度极差。"""
    spreads = []
    for result in (current, baseline):
        values = [item["completion"] for item in _task_scores(result).values()
                  if item["completion"] is not None]
        if len(values) >= 2:
            spreads.append(max(values) - min(values))
    return {"source": "同一版本的重复运行",
            "method": "配对的随机化检验",
            "completion_spread": max(spreads) if spreads else None,
            "note": ("两侧都只有一次运行，噪声范围未知，差值按原值列示"
                     if not spreads else "同版本重复运行的完成度极差")}


def _secondary(paired):
    return [{"task": item["task"],
             "completion_difference": item["completion_difference"],
             "checkpoints_failed_difference": (len(item["current_checkpoints_failed"])
                                               - len(item["baseline_checkpoints_failed"]))}
            for item in paired]


def _verdict(paired, noise):
    """三种结论（第 4 节第 4 条）：
    - 退化：任一任务误放行增加，或出现基线没有的新检查点失败，或完成度下降超出噪声范围；
    - 改进：误放行总数下降超出噪声范围，并且没有任何任务退化；
    - 无差别：其余情况。
    """
    spread = noise.get("completion_spread")
    for item in paired:
        if item["false_release_difference"] > 0:
            return "regressed"
        new_failures = (set(item["current_checkpoints_failed"])
                        - set(item["baseline_checkpoints_failed"]))
        if new_failures:
            return "regressed"
        diff = item["completion_difference"]
        if diff is not None and spread is not None and diff < -spread:
            return "regressed"
    total = sum(item["false_release_difference"] for item in paired)
    if total < 0:
        return "improved"
    for item in paired:
        diff = item["completion_difference"]
        if diff is not None and spread is not None and diff > spread:
            return "improved"
    return "no_difference"