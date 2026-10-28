"""用新视图重放同一次运行，并与现状逐步对比。

做三件事：

1. `verify`：规则全关时，`view()` 必须一字不差地还原记录下来的请求体（`messages` 与
   `tools` 两部分），这是回放忠实的证据。
2. `run_replay`：规则打开以后，逐步比较用量、召回与浪费；再逐条关掉一条规则，看每条
   规则各贡献多少（消融）。所有数字都来自同一批事件，不需要模型。
3. `write_report`：把结果写成设计说明第 6 节要的表。

召回与浪费沿用 measure.py 的定义与同一套真值集合：真值集合来自这一步的模型输出，
浪费是「此后从未被引用」的用量。
"""

from __future__ import annotations

import collections
import dataclasses
import json
import os
import statistics
from dataclasses import dataclass
from typing import Any

from . import references
from .items import Entry, estimate_tokens, normalize_request, tokens_of
from .measure import _quantiles, score_view
from .store import EventLog
from .view import Rules, canonical_bytes, load_rules, view

IDENTITY = Rules(
    input_single_copy=False,
    superseded_read_collapse=False,
    tool_result_keep_tokens=10 ** 9,
    tool_result_clear_min_tokens=10 ** 9,
    error_result_keep=True,
    pinned_reference_gate=False,
    round_fold_granularity=False,
    work_limit_tokens=10 ** 9,
)

ABLATIONS = (
    ("input_single_copy", {"input_single_copy": False}),
    ("superseded_read_collapse", {"superseded_read_collapse": False}),
    ("tool_result_age_budget", {"tool_result_keep_tokens": 10 ** 9}),
    ("error_result_keep", {"error_result_keep": False}),
    ("pinned_reference_gate", {"pinned_reference_gate": False}),
    ("round_fold_granularity", {"round_fold_granularity": False}),
)


@dataclass
class Pair:
    """一步的现状与新视图对照。"""

    run_id: str
    department: str
    step_id: int
    before_tokens: int
    after_tokens: int
    before_recall: float
    after_recall: float
    before_waste: float
    after_waste: float
    missing_after: tuple[str, ...] = ()


def _measured(log: EventLog):
    """每一步的原视图条目、真值集合与此后引用集合。与 measure.py 用同一套定义。"""
    from .measure import measure_run

    steps_out = []
    for run_id in log.runs():
        views = measure_run(log, run_id)
        steps = log.steps(run_id)
        by_event = {step.event_id: step for step in steps}
        for item in views:
            steps_out.append((item, by_event))
    return steps_out


def section_ablation(views: list, rules: Rules) -> dict[str, dict[str, float]]:
    """逐段核对 R5：单独把这一段换成摘要，能省多少用量、会丢多少需要的记号。

    「会丢」的判据很严：这个记号在这一步需要、在这一段里有、在视图的其它任何地方都没有。
    这样的记号一旦因为这一段被换成摘要而消失，就是真的少了信息。
    """
    result: dict[str, dict[str, float]] = collections.defaultdict(
        lambda: {"steps": 0, "saved_tokens": 0.0, "lost_tokens": 0.0, "lost_steps": 0.0})
    for item in views:
        pinned = next((entry for entry in item.entries if entry.kind == "pinned"), None)
        if pinned is None:
            continue
        others: set[str] = set()
        for entry in item.entries:
            if entry.index == pinned.index:
                continue
            if entry.kind == "pinned":
                for source, body in entry.sections:
                    if source not in rules.gated_sections:
                        others.update(references.extract(body))
                continue
            others.update(references.tokens_of_entry(entry))
        for source, body in pinned.sections:
            if source not in rules.gated_sections:
                continue
            stub = body[:rules.pinned_stub_chars]
            saved = estimate_tokens(body) - estimate_tokens(stub)
            in_body = set(references.extract(body))
            lost = [token for token in item.needed_set if token in in_body and token not in others]
            row = result[source]
            row["steps"] += 1
            row["saved_tokens"] += max(0, saved)
            row["lost_tokens"] += len(lost)
            row["lost_steps"] += 1 if lost else 0
    return {key: {k: round(v, 2) for k, v in value.items()} for key, value in sorted(
        result.items(), key=lambda item: -item[1]["saved_tokens"])}


def run_replay(db_path: str, artifacts_root: str | None, rules_path: str) -> dict[str, Any]:
    rules = load_rules(rules_path)
    with EventLog(db_path, artifacts_root) as log:
        pairs: list[Pair] = []
        ablations: dict[str, dict[str, float]] = collections.defaultdict(
            lambda: {"before_tokens": 0.0, "after_tokens": 0.0, "needed": 0.0, "covered": 0.0})
        totals = {"before_tokens": 0, "after_tokens": 0, "needed": 0, "covered_before": 0, "covered_after": 0,
                  "waste_before": 0, "waste_after": 0}
        all_views: list = []
        for run_id in log.runs():
            from .measure import measure_run

            views = measure_run(log, run_id)
            all_views.extend(views)
            steps = {step.step_id: step for step in log.steps(run_id)}
            for item in views:
                step = steps.get(item.step_id)
                if step is None:
                    continue
                before = score_view(item.entries, item.needed_set, item.later_set)
                request = view(item.entries, rules, tools=step.body.get("tools"))
                after_entries = normalize_request(request, item.step_id)
                after = score_view(after_entries, item.needed_set, item.later_set)
                present = references.presence(after_entries)
                missing = tuple(sorted(token for token in item.needed_set if token not in present))
                pairs.append(Pair(
                    run_id=run_id, department=item.department, step_id=item.step_id,
                    before_tokens=before.tokens, after_tokens=after.tokens,
                    before_recall=before.recall, after_recall=after.recall,
                    before_waste=before.waste_ratio, after_waste=after.waste_ratio,
                    missing_after=missing,
                ))
                totals["before_tokens"] += before.tokens
                totals["after_tokens"] += after.tokens
                totals["needed"] += before.needed
                totals["covered_before"] += before.covered
                totals["covered_after"] += after.covered
                totals["waste_before"] += before.waste_tokens
                totals["waste_after"] += after.waste_tokens
                for name, override in ABLATIONS:
                    candidate = dataclasses.replace(rules, **override)
                    request = view(item.entries, candidate, tools=step.body.get("tools"))
                    entries = normalize_request(request, item.step_id)
                    score = score_view(entries, item.needed_set, item.later_set)
                    ablations[name]["before_tokens"] += before.tokens
                    ablations[name]["after_tokens"] += score.tokens
                    ablations[name]["needed"] += score.needed
                    ablations[name]["covered"] += score.covered
        data = summarise(pairs, totals, ablations, rules)
        data["sections"] = section_ablation(all_views, rules)
    data["rules_path"] = os.path.abspath(rules_path)
    data["rules_version"] = rules.version()
    return data


def summarise(pairs: list[Pair], totals: dict[str, int], ablations: dict[str, dict[str, float]],
              rules: Rules) -> dict[str, Any]:
    saved = totals["before_tokens"] - totals["after_tokens"]
    data: dict[str, Any] = {
        "steps": len(pairs),
        "before_tokens": totals["before_tokens"],
        "after_tokens": totals["after_tokens"],
        "saved_tokens": saved,
        "saved_ratio": round(saved / max(1, totals["before_tokens"]), 4),
        "recall_before": round(totals["covered_before"] / max(1, totals["needed"]), 4),
        "recall_after": round(totals["covered_after"] / max(1, totals["needed"]), 4),
        "waste_before": round(totals["waste_before"] / max(1, totals["before_tokens"]), 4),
        "waste_after": round(totals["waste_after"] / max(1, totals["after_tokens"]), 4),
        "rules": rules.to_dict(),
        "by_department": {},
        "by_step": {},
        "losses": [],
        "ablations": {},
    }
    for name, key in (("by_department", lambda pair: pair.department or "?"),
                      ("by_step", lambda pair: "1" if pair.step_id == 1 else "2-3" if pair.step_id <= 3
                       else "4-7" if pair.step_id <= 7 else "8-15" if pair.step_id <= 15 else "16+")):
        groups: dict[str, list[Pair]] = collections.defaultdict(list)
        for pair in pairs:
            groups[key(pair)].append(pair)
        for group, items in sorted(groups.items()):
            before = sum(pair.before_tokens for pair in items)
            after = sum(pair.after_tokens for pair in items)
            data[name][group] = {
                "steps": len(items),
                "before_tokens": before,
                "after_tokens": after,
                "saved_ratio": round((before - after) / max(1, before), 4),
                "recall_before": round(statistics.mean(pair.before_recall for pair in items), 4),
                "recall_after": round(statistics.mean(pair.after_recall for pair in items), 4),
            }
    for pair in pairs:
        if pair.after_recall < pair.before_recall:
            data["losses"].append({
                "run_id": pair.run_id, "department": pair.department,
                "step_id": pair.step_id, "before": round(pair.before_recall, 4),
                "after": round(pair.after_recall, 4), "missing": list(pair.missing_after)[:10],
            })
    data["loss_count"] = len(data["losses"])
    for name, value in ablations.items():
        data["ablations"][name] = {
            "before_tokens": int(value["before_tokens"]),
            "after_tokens": int(value["after_tokens"]),
            "recall": round(value["covered"] / max(1, value["needed"]), 4),
            # 正数 = 打开这条规则省下的用量
            "marginal_saved_tokens": int(value["after_tokens"] - totals["after_tokens"]),
            "marginal_recall": round(value["covered"] / max(1, value["needed"])
                                     - totals["covered_after"] / max(1, totals["needed"]), 4),
        }
    return data


def to_markdown(data: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add(f"规则版本 `{data['rules_version']}`；回放 {data['steps']} 步。")
    add("")
    add(f"- 用量：{data['before_tokens']} → {data['after_tokens']} token，"
        f"省 {data['saved_tokens']}（{100 * data['saved_ratio']:.1f}%）。")
    add(f"- 召回：{data['recall_before']} → {data['recall_after']}（按需要的记号计）。")
    add(f"- 浪费：{100 * data['waste_before']:.1f}% → {100 * data['waste_after']:.1f}%。")
    add(f"- 召回下降的步：{data['loss_count']} 步。")
    add("")
    for name, title in (("by_department", "按部门"), ("by_step", "按步序")):
        add(f"**{title}**")
        add("")
        add("| 分组 | 步数 | 现状 token | 新视图 token | 省 | 召回 现状 | 召回 新视图 |")
        add("| --- | --- | --- | --- | --- | --- | --- |")
        for key, value in data[name].items():
            add(f"| {key} | {value['steps']} | {value['before_tokens']} | {value['after_tokens']} | "
                f"{100 * value['saved_ratio']:.1f}% | {value['recall_before']} | {value['recall_after']} |")
        add("")
    add("**逐条规则的贡献**（打开这一条相对关掉它省下的用量；召回一列为正表示这一条会丢召回）")
    add("")
    add("| 规则 | 打开后省下的用量 | 这一条省下的 token | 这一条丢掉的召回 |")
    add("| --- | --- | --- | --- |")
    for name, value in data["ablations"].items():
        saved = 100 * (1 - value["after_tokens"] / max(1, value["before_tokens"]))
        add(f"| {name} | {saved:.1f}% | {value['marginal_saved_tokens']} | {-value['marginal_recall']:+.4f} |")
    add("")
    if data.get("sections"):
        add("**R5 逐段核对**（这一段换成摘要能省多少、会不会丢掉只在这一段里的记号）")
        add("")
        add("| 段 | 步数 | 省下的 token | 丢掉的记号 | 丢记号的步 |")
        add("| --- | --- | --- | --- | --- |")
        for key, value in data["sections"].items():
            add(f"| {key} | {int(value['steps'])} | {int(value['saved_tokens'])} | "
                f"{int(value['lost_tokens'])} | {int(value['lost_steps'])} |")
        add("")
    if data["losses"]:
        add("**召回下降的步（逐个）**")
        add("")
        add("| run | 部门 | 步 | 现状召回 | 新视图召回 | 缺的记号 |")
        add("| --- | --- | --- | --- | --- | --- |")
        for loss in data["losses"][:40]:
            add(f"| {loss['run_id']} | {loss['department']} | {loss['step_id']} | {loss['before']} | "
                f"{loss['after']} | {', '.join(loss['missing'])} |")
        add("")
    return "\n".join(lines)


def write_report(data: dict[str, Any], out_json: str, out_md: str) -> None:
    for path in (out_json, out_md):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1, sort_keys=True)
    with open(out_md, "w", encoding="utf-8") as handle:
        handle.write(to_markdown(data))
