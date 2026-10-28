"""参数扫描：同一个规则集上只改一个参数的取值，看省下多少用量、丢掉多少召回。

用途是给参数定默认值（设计说明第 4 节 R3）：`tool_result_keep_tokens` 的取值应当来自
「保留量 → 省量 / 召回」的曲线，而不是抄一个来源不明的数。

    python -m evals.context sweep --db <events.sqlite> --param tool_result_keep_tokens \
        --values 40000,20000,12000,8000,4000,2000

只算用量、召回与被丢掉的记号，不做逐条规则的消融，所以比 `replay` 快。
"""

from __future__ import annotations

import dataclasses
import os
from typing import Any

from .items import normalize_request
from .measure import measure_run, score_view
from .store import EventLog
from .view import Rules, load_rules, view


def sweep(db_path: str, artifacts_root: str | None, rules_path: str, param: str,
          values: list[Any]) -> dict[str, Any]:
    rules = load_rules(rules_path)
    fields = {item.name for item in dataclasses.fields(Rules)}
    if param not in fields:
        raise SystemExit(f"没有这个规则字段：{param}；可用：{sorted(fields)}")
    rows: list[dict[str, Any]] = []
    with EventLog(db_path, artifacts_root) as log:
        prepared = []
        for run_id in log.runs():
            steps = {step.step_id: step for step in log.steps(run_id)}
            for item in measure_run(log, run_id):
                step = steps.get(item.step_id)
                if step is not None:
                    prepared.append((item, step.body.get("tools")))
        for value in values:
            candidate = dataclasses.replace(rules, **{param: value})
            before = after = needed = covered_before = covered_after = 0
            losses = 0
            for item, tools in prepared:
                score_before = score_view(item.entries, item.needed_set, item.later_set)
                entries = normalize_request(view(item.entries, candidate, tools=tools), item.step_id)
                score_after = score_view(entries, item.needed_set, item.later_set)
                before += score_before.tokens
                after += score_after.tokens
                needed += score_before.needed
                covered_before += score_before.covered
                covered_after += score_after.covered
                losses += 1 if score_after.recall < score_before.recall else 0
            rows.append({
                "value": value,
                "tokens": after,
                "saved_tokens": before - after,
                "saved_ratio": round((before - after) / max(1, before), 4),
                "recall_before": round(covered_before / max(1, needed), 4),
                "recall_after": round(covered_after / max(1, needed), 4),
                "steps_with_lower_recall": losses,
            })
            print(f"{param}={value}: 省 {rows[-1]['saved_ratio'] * 100:.1f}%，"
                  f"召回 {rows[-1]['recall_before']} → {rows[-1]['recall_after']}，"
                  f"召回下降 {losses} 步")
    return {"param": param, "rows": rows, "rules_version": rules.version()}


def to_markdown(data: dict[str, Any]) -> str:
    lines = [f"`{data['param']}` 扫描（规则版本 `{data['rules_version']}`）", "",
             "| 取值 | 省 | 召回 现状 | 召回 新视图 | 召回下降的步 |",
             "| --- | --- | --- | --- | --- |"]
    for row in data["rows"]:
        lines.append(f"| {row['value']} | {100 * row['saved_ratio']:.1f}% | {row['recall_before']} | "
                     f"{row['recall_after']} | {row['steps_with_lower_recall']} |")
    return "\n".join(lines) + "\n"
