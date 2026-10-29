"""缓存感知的费用折算：同一批运行，换一套视图规则，按前缀缓存计价会花多少。

上游按前缀缓存计价：一步的请求与上一步的请求从头起相同的那一段命中缓存，按缓存读的单价算；
从第一处不同起的全部内容按未缓存的单价算。不折叠的历史只在末尾追加，上一步的请求整段命中；
折叠把旧的一轮换成占位，从那一处起之后的内容都按未缓存重发。所以 token 数下降不等于费用下降。

折算：费用 = 命中缓存的 token × CACHED_PRICE + 其余 token × 1。CACHED_PRICE 取 0.1（缓存读单价
约为未缓存输入的十分之一）。基线的命中率用 `implied_hit` 反推，可以与上游回报的缓存读占比核对。

不读模型、不导入 harness。
"""

from __future__ import annotations

import collections
import dataclasses
import json
import os
from typing import Any, Sequence

from .items import normalize_request
from .measure import measure_run
from .store import EventLog
from .view import Rules, load_rules, view

CACHED_PRICE = 0.1

# 每个变体是对规则集的覆盖；None 表示记录下来的请求（现状）。
# OFF 把所有减法规则关掉，每个变体在它上面只开一条，才能分清是哪一条改变了前缀。
OFF = dict(input_single_copy=False, superseded_read_collapse=False, pinned_reference_gate=False,
           tool_result_keep_tokens=10 ** 9, work_limit_tokens=10 ** 9)
VARIANTS: dict[str, dict[str, Any] | None] = {
    "现状（记录）": None,
    "R1 部门输入只留最新": dict(OFF, input_single_copy=True),
    "R2 同路径读取只留最新": dict(OFF, superseded_read_collapse=True),
    "R5 引证段按引用门控": dict(OFF, pinned_reference_gate=True),
    "R3 保留 16000 / 最少省 4000": dict(OFF, tool_result_keep_tokens=16000, tool_result_clear_min_tokens=4000),
    "R3 保留 40000 / 最少省 20000": dict(OFF, tool_result_keep_tokens=40000, tool_result_clear_min_tokens=20000),
    "全开（16000 / 4000）": dict(tool_result_keep_tokens=16000, tool_result_clear_min_tokens=4000),
}


def cached_prefix_tokens(previous: Sequence[tuple], current: Sequence[tuple], tokens: Sequence[int]) -> int:
    """当前请求与上一步请求从头起逐条相同的那一段的 token 数；上一步为空（会话第一步）时为 0。"""
    cached = 0
    for index, key in enumerate(current):
        if index < len(previous) and previous[index] == key:
            cached += tokens[index]
        else:
            break
    return cached


def step_cost(total: int, cached: int) -> float:
    return cached * CACHED_PRICE + (total - cached)


def run_cost(db_path: str, artifacts_root: str | None, rules_path: str,
             variants: dict[str, dict[str, Any] | None] | None = None) -> dict[str, Any]:
    variants = variants or VARIANTS
    rules = load_rules(rules_path)
    totals: dict[str, dict[str, float]] = {name: {"tokens": 0, "cost": 0.0} for name in variants}
    by_department: dict[tuple[str, str], dict[str, float]] = collections.defaultdict(
        lambda: {"tokens": 0, "cost": 0.0})
    with EventLog(db_path, artifacts_root) as log:
        for run_id in log.runs():
            steps = {step.step_id: step for step in log.steps(run_id)}
            sessions: dict[str | None, list] = collections.defaultdict(list)
            for item in measure_run(log, run_id):
                sessions[item.session_id].append(item)
            for items in sessions.values():
                items.sort(key=lambda item: item.index)
                for name, override in variants.items():
                    candidate = None if override is None else dataclasses.replace(rules, **override)
                    previous: Sequence[tuple] = ()
                    for item in items:
                        if candidate is None:
                            entries = item.entries
                        else:
                            request = view(item.entries, candidate, tools=steps[item.step_id].body.get("tools"))
                            entries = normalize_request(request, item.step_id)
                        keys = [(entry.kind, entry.text) for entry in entries]
                        tokens = [entry.tokens for entry in entries]
                        total = sum(tokens)
                        cost = step_cost(total, cached_prefix_tokens(previous, keys, tokens))
                        for bucket in (totals[name], by_department[(item.department, name)]):
                            bucket["tokens"] += total
                            bucket["cost"] += cost
                        previous = keys
    baseline = totals[next(iter(variants))]
    rows = []
    for name, bucket in totals.items():
        rows.append({"variant": name, "tokens": int(bucket["tokens"]), "cost": round(bucket["cost"]),
                     "tokens_ratio": round(bucket["tokens"] / baseline["tokens"], 4),
                     "cost_ratio": round(bucket["cost"] / baseline["cost"], 4)})
    departments: dict[str, list[dict[str, Any]]] = {}
    for department in sorted({key[0] for key in by_department}):
        base = by_department[(department, next(iter(variants)))]
        departments[department] = [
            {"variant": name, "tokens_ratio": round(by_department[(department, name)]["tokens"] / base["tokens"], 4),
             "cost_ratio": round(by_department[(department, name)]["cost"] / base["cost"], 4)}
            for name in variants]
        departments[department][0]["implied_hit"] = round(implied_hit(base["tokens"], base["cost"]), 4)
    return {"rows": rows, "departments": departments, "cached_price": CACHED_PRICE,
            "implied_hit": round(implied_hit(baseline["tokens"], baseline["cost"]), 4),
            "rules_version": rules.version()}


def implied_hit(tokens: float, cost: float) -> float:
    """由基线的折算费用反推缓存命中的 token 占比：cost / tokens = 1 - hit * (1 - CACHED_PRICE)。"""
    return 0.0 if tokens == 0 else (1 - cost / tokens) / (1 - CACHED_PRICE)


def to_markdown(data: dict[str, Any], title: str = "") -> str:
    lines = [f"缓存感知的费用折算{('：' + title) if title else ''}（缓存读按 {data['cached_price']}，其余按 1；"
             f"基线反推的缓存命中占比 {data['implied_hit'] * 100:.1f}%）", "",
             "| 变体 | token 数（现状 = 100%） | 折算费用（现状 = 100%） |", "| --- | --- | --- |"]
    for row in data["rows"]:
        lines.append(f"| {row['variant']} | {row['tokens_ratio'] * 100:.1f}% | {row['cost_ratio'] * 100:.1f}% |")
    lines += ["", "按部门（隐含缓存命中 = 现状基线反推）：", "",
              "| 部门 | 隐含缓存命中 | " + " | ".join(row["variant"] for row in data["rows"][1:]) + " |",
              "| --- | --- | " + " | ".join("---" for _ in data["rows"][1:]) + " |"]
    for department, rows in data["departments"].items():
        cells = " | ".join(f"{row['cost_ratio'] * 100:.0f}%" for row in rows[1:])
        lines.append(f"| {department} | {rows[0]['implied_hit'] * 100:.0f}% | {cells} |")
    return "\n".join(lines) + "\n"


def write_report(data: dict[str, Any], out_json: str, out_md: str, title: str = "") -> None:
    os.makedirs(os.path.dirname(os.path.abspath(out_json)), exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1, sort_keys=True)
    with open(out_md, "w", encoding="utf-8") as handle:
        handle.write(to_markdown(data, title))
