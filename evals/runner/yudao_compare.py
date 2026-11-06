"""版本比较与两侧对照（`docs/design/evaluation-scenarios.md` 「报告与版本比较」）。

- 版本比较（docs/design/evaluation-scenarios.md「噪声范围与三种结论」）：同一场景按运行的序号配对，第 1 次对第 1 次，不按运行编号；
  只有材料版本与评分器版本都相同时才配对，否则拒绝比较；噪声来自同一版本的重复运行，
  差值用配对的随机化检验；三种结论：改进 / 无差别 / 退化；必需证据缺失时标受阻并保留
  已算指标。
- 两侧对照（docs/design/evaluation-scenarios.md「Yudao 对单个 agent」）：Yudao 对单个 agent（OpenCode），判定按 D38 的 N-G1，结论是
  「高于」「没有达到」「受阻」之一；逐次并排的表只报告，不据此判定。
"""

import yudao_metrics

PRIMARY_METRIC = "qa_false_release"
SECONDARY_METRICS = ("asks", "reworks", "completion", "requests", "cost", "elapsed")

# N-G1（docs/design/evaluation-scenarios.md「Yudao 对单个 agent」中「高于」看质检这一段）：同一个场景 3 次运行中至少 2 次满足条件
REQUIRED_RUNS = 2

VERDICT_LABELS = {"above": "高于", "not_reached": "没有达到", "blocked": "受阻"}

# ponytail: 配对随机化检验在两侧样本都只有 1 次时退化为「差值与噪声范围直接比较」；
# 三次运行（#324）到位以后，两侧 3×3 的置换分布才有检验效力。


def compare(current, baseline):
    """比较两个结果（`build_result` 的返回）。

    返回的 verdict 是 "improved" / "no_difference" / "regressed" / "blocked" 之一；
    blocked 时保留已算的逐任务差值。配对按运行序号（`runs` 数组的位置，从 1 起）。
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
                "paired_tasks": [], "unpaired": {"current": [], "baseline": []},
                "noise": None,
                "primary": {"metric": PRIMARY_METRIC, "current": None, "baseline": None,
                            "difference": None},
                "secondary": []}
    current_runs = _run_scores(current)
    baseline_runs = _run_scores(baseline)
    shared = sorted(set(current_runs) & set(baseline_runs))
    if not shared:
        return {"compared": False,
                "block_reason": "两侧没有可配对的运行（逐次评分缺失）",
                "verdict": "blocked",
                "material_version": material, "scorer_version": scorer,
                "paired_tasks": [], "unpaired": _unpaired(current_runs, baseline_runs, ()),
                "noise": None,
                "primary": {"metric": PRIMARY_METRIC, "current": None, "baseline": None,
                            "difference": None},
                "secondary": []}

    paired = []
    for index in shared:
        current_run = current_runs[index]
        baseline_run = baseline_runs[index]
        paired.append({
            "run_index": index,
            "current_run": current_run["run_id"],
            "baseline_run": baseline_run["run_id"],
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
            "paired_tasks": paired, "unpaired": _unpaired(current_runs, baseline_runs, shared),
            "noise": noise,
            "primary": {"metric": PRIMARY_METRIC,
                        "rule": "non_inferior", "margin": 0,
                        "current": current_total, "baseline": baseline_total,
                        "difference": current_total - baseline_total},
            "secondary": _secondary(paired)}


def _run_scores(result):
    """逐次运行的评分：键是运行的序号（`runs` 数组的位置，从 1 起），不按 run_id。

    运行编号前缀随批次变化（docs/design/evaluation-scenarios.md「噪声范围与三种结论」），按 run_id 配对时两组结果一对也配不上。作废的
    运行没有评分，它的序号在另一侧没有配对。
    """
    scores = {}
    for index, run in enumerate(result.get("runs", []), start=1):
        if run.get("void"):
            continue
        metrics = run.get("metrics", {})
        checkpoints = metrics.get("checkpoints", {})
        false_release = (checkpoints.get("no_false_release") or {}).get("passed") is False
        score = run.get("score") or {}
        scores[index] = {
            "run_id": run.get("run_id"),
            "false_release": false_release,
            "completion": score.get("completion"),
            "checkpoints_failed": sorted(key for key, item in checkpoints.items()
                                         if item.get("passed") is False),
        }
    return scores


def _unpaired(current_runs, baseline_runs, shared):
    """序号对不上的部分：一侧有评分、另一侧在这个序号上没有评分。"""
    return {"current": sorted(set(current_runs) - set(shared)),
            "baseline": sorted(set(baseline_runs) - set(shared))}


def _noise_range(current, baseline, tasks):
    """噪声范围来自同一版本的重复运行：同版本重复运行的完成度极差。"""
    spreads = []
    for result in (current, baseline):
        values = [item["completion"] for item in _run_scores(result).values()
                  if item["completion"] is not None]
        if len(values) >= 2:
            spreads.append(max(values) - min(values))
    return {"source": "同一版本的重复运行",
            "method": "配对的随机化检验",
            "completion_spread": max(spreads) if spreads else None,
            "note": ("两侧都只有一次运行，噪声范围未知，差值按原值列示"
                     if not spreads else "同版本重复运行的完成度极差")}


def _secondary(paired):
    return [{"run_index": item["run_index"],
             "completion_difference": item["completion_difference"],
             "checkpoints_failed_difference": (len(item["current_checkpoints_failed"])
                                               - len(item["baseline_checkpoints_failed"]))}
            for item in paired]


def _verdict(paired, noise):
    """三种结论：
    - 退化：任一运行误放行增加，或出现基线没有的新检查点失败，或完成度下降超出噪声范围；
    - 改进：误放行总数下降超出噪声范围，并且没有任何运行退化；
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


# ---------------------------------------------------------------------------
# 两侧对照：Yudao 对单个 agent（docs/design/evaluation-scenarios.md「Yudao 对单个 agent」）


def compare_sides(yudao_result, opencode_result):
    """Yudao 对 OpenCode 的对照（docs/design/evaluation-scenarios.md「Yudao 对单个 agent」、D38 的 N-G1）：三种结论之一。

    材料版本与评分器版本相同才比较，否则「受阻」。判定看质检这一段：同一个场景至少
    2 次运行里，质检在时间上限以内给出结论、最终交付比本次第一次交付多通过至少 1 条
    隐藏检查；第一次交付已经全部通过的运行不计入；每一次运行都没有质检误放行。
    逐次并排的表只报告，不单独据此判定。
    """
    material = yudao_result.get("material_version")
    scorer = yudao_result.get("scorer_version")
    version_block = None
    if material != opencode_result.get("material_version") \
            or scorer != opencode_result.get("scorer_version"):
        version_block = ("材料版本或评分器版本不同：" + str(material) + "/" + str(scorer)
                         + " 对比 " + str(opencode_result.get("material_version")) + "/"
                         + str(opencode_result.get("scorer_version")))
    if version_block is not None:
        return {"compared": False, "verdict": "blocked", "verdict_label": VERDICT_LABELS["blocked"],
                "block_reason": version_block,
                "scenario": yudao_result.get("scenario"),
                "material_version": material, "scorer_version": scorer,
                "yudao": _side_summary(yudao_result, "yudao_commit"),
                "opencode": _side_summary(opencode_result, "opencode_version"),
                "criterion": None, "pairs": [],
                "unpaired": {"yudao": [], "opencode": []}}

    criterion = qa_advantage(yudao_result.get("runs") or [])
    pairs, unpaired = _side_pairs(yudao_result, opencode_result)
    return {"compared": True, "verdict": criterion["verdict"],
            "verdict_label": VERDICT_LABELS[criterion["verdict"]],
            "block_reason": criterion["block_reason"],
            "scenario": yudao_result.get("scenario"),
            "material_version": material, "scorer_version": scorer,
            "yudao": _side_summary(yudao_result, "yudao_commit"),
            "opencode": _side_summary(opencode_result, "opencode_version"),
            "criterion": criterion, "pairs": pairs, "unpaired": unpaired}


def qa_advantage(runs):
    """N-G1 的判定（docs/design/evaluation-scenarios.md「Yudao 对单个 agent」中「高于」看质检这一段）：3 次运行中至少 2 次满足「高于」的条件。

    「至少 2 次」指不计入以外的运行里至少 2 次满足条件；不计入的运行不算满足，也不是
    失败。可以观察质检提高的运行不到 2 次、或者第一次交付的评分缺失时结论是「受阻」，
    写明缺哪项证据。
    """
    considered = [run for run in runs
                  if not run.get("void")
                  and not (run.get("metrics") or {}).get("model_service_failure")]
    missing = [str(run.get("run_id")) for run in considered if run.get("first_score") is None]
    if missing:
        return {"verdict": "blocked",
                "block_reason": ("缺第一次交付的评分：" + "、".join(missing)
                                 + "（结果里没有第一次交付的评分，质检带来的提高无法计算）"),
                "considered": len(considered), "observing": 0, "meeting": 0,
                "not_counted": 0, "no_conclusion": 0, "false_release": 0,
                "runs": []}

    items = []
    not_counted = 0
    no_conclusion = 0
    observing = 0
    meeting = 0
    false_release = 0
    for index, run in enumerate(considered, start=1):
        delivery = run.get("delivery") or {}
        improvement = delivery.get("qa_improvement") or {}
        status = improvement.get("status")
        within_limit = bool(delivery.get("qa_within_limit"))
        gain = improvement.get("passed_gain")
        released_wrongly = _false_release(run)
        if released_wrongly:
            false_release += 1
        item = {"run_index": index, "run_id": run.get("run_id"),
                "qa_within_limit": within_limit, "passed_gain": gain,
                "false_release": released_wrongly, "counted": False, "meets": False,
                "first_all_passed": bool((delivery.get("first") or {}).get("all_passed"))}
        if status == yudao_metrics.IMPROVEMENT_NOT_COUNTED:
            not_counted += 1
            item["status"] = "not_counted"
            item["reason"] = "第一次交付已全部通过，不计入"
        elif status == yudao_metrics.IMPROVEMENT_NO_CONCLUSION:
            no_conclusion += 1
            item["status"] = "no_conclusion"
            item["reason"] = "质检没有给出结论"
        else:
            observing += 1
            item["counted"] = True
            item["meets"] = within_limit and isinstance(gain, int) and gain >= 1 \
                and not released_wrongly
            item["status"] = "meets" if item["meets"] else "no_improvement"
            item["reason"] = (("最终交付多通过 " + str(gain) + " 条隐藏检查")
                              if item["meets"] else "最终交付没有多通过隐藏检查")
            if item["meets"]:
                meeting += 1
        items.append(item)

    if meeting >= REQUIRED_RUNS and false_release == 0:
        return {"verdict": "above", "block_reason": None,
                "considered": len(considered), "observing": observing, "meeting": meeting,
                "not_counted": not_counted, "no_conclusion": no_conclusion,
                "false_release": false_release, "runs": items}

    if observing < REQUIRED_RUNS:
        reasons = ["可以观察质检带来的提高的运行只有 " + str(observing) + " 次（要求至少 "
                   + str(REQUIRED_RUNS) + " 次）"]
        if not_counted:
            reasons.append("第一次交付已全部通过的运行有 " + str(not_counted) + " 次，不计入")
        if no_conclusion:
            reasons.append("质检没有给出结论的运行有 " + str(no_conclusion) + " 次")
        missing_evidence = "；".join(reasons)
        return {"verdict": "blocked", "block_reason": missing_evidence + "：缺足够的运行观察质检带来的提高",
                "considered": len(considered), "observing": observing, "meeting": meeting,
                "not_counted": not_counted, "no_conclusion": no_conclusion,
                "false_release": false_release, "runs": items}

    reasons = ["满足条件的运行只有 " + str(meeting) + " 次（要求至少 " + str(REQUIRED_RUNS) + " 次）"]
    if false_release:
        reasons.append("有 " + str(false_release) + " 次运行质检误放行")
    return {"verdict": "not_reached", "block_reason": "；".join(reasons),
            "considered": len(considered), "observing": observing, "meeting": meeting,
            "not_counted": not_counted, "no_conclusion": no_conclusion,
            "false_release": false_release, "runs": items}


def _false_release(run):
    """质检误放行：放行而隐藏检查中存在失败。"""
    checkpoints = (run.get("metrics") or {}).get("checkpoints") or {}
    return (checkpoints.get("no_false_release") or {}).get("passed") is False


def _side_summary(result, version_key):
    return {"model": result.get("model"), "version": result.get(version_key),
            "run_count": len(result.get("runs") or [])}


def _side_pairs(yudao_result, opencode_result):
    """逐次并排：按运行序号配对（第 1 次对第 1 次），序号对不上的列为没有配对。"""
    yudao_runs = yudao_result.get("runs") or []
    opencode_runs = opencode_result.get("runs") or []
    pairs = []
    for index in range(1, min(len(yudao_runs), len(opencode_runs)) + 1):
        pairs.append({"run_index": index,
                      "yudao": _yudao_row(yudao_runs[index - 1]),
                      "opencode": _opencode_row(opencode_runs[index - 1])})
    unpaired = {"yudao": list(range(len(opencode_runs) + 1, len(yudao_runs) + 1)),
                "opencode": list(range(len(yudao_runs) + 1, len(opencode_runs) + 1))}
    return pairs, unpaired


def _yudao_row(run):
    metrics = run.get("metrics") or {}
    return {"run_id": run.get("run_id"), "void": bool(run.get("void")),
            "completion_first": _completion(run.get("first_score")),
            "completion_final": _completion(run.get("score")),
            "correctness": _correctness(run.get("score")),
            "failed": _failed_checks(run.get("score")),
            "elapsed_seconds": metrics.get("elapsed_seconds"),
            "model_requests": metrics.get("model_requests"),
            "total_tokens": metrics.get("total_tokens")}


def _opencode_row(run):
    metrics = run.get("metrics") or {}
    return {"run_id": run.get("run_id"), "void": bool(run.get("void")),
            "completion_first": None, "completion_final": _completion(run.get("score")),
            "correctness": _correctness(run.get("score")),
            "failed": _failed_checks(run.get("score")),
            "elapsed_seconds": metrics.get("elapsed_seconds"),
            "model_requests": metrics.get("request_count"),
            "total_tokens": metrics.get("total_tokens")}


def _completion(scores):
    return (scores or {}).get("completion")


def _correctness(scores):
    return (scores or {}).get("correctness")


def _failed_checks(scores):
    """失败条目：评分器记录的逐条检查里没有通过的；没有逐条结果时退回两个清单。"""
    if not scores:
        return []
    checks = scores.get("checks")
    if checks:
        return [check["id"] for check in checks if check.get("status") != "pass"]
    return list(scores.get("wrong") or []) + list(scores.get("not_done") or [])
