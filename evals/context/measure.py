"""按步测量现状：每一步的召回与浪费，按步、按部门、按窗口大小看分布。

定义（设计说明第 3 节）：

- **视图**：这一步请求里的全部条目（部门材料各段、部门输入、历史消息、工具调用与结果）
  与工具定义。用量按 `items.estimate_tokens` 算。
- **真值集合**：这一步模型的输出里抽出的引用（references.py）。
- **召回**：真值集合里那些「此前已经出现过」的记号，有多少还在这一步的视图里。此前出现
  过 = 在更早的视图里或更早的输出里出现过；模型自己新造的记号不进分母。
- **浪费**：视图里此后（这一步及之后）从未被引用的记号所在的条目，它们的用量合计。归属按
  references.py 的规则：记号记给最早持有它的条目。

两个数都是每步一个，再按步序、部门、窗口大小分组看分布，不只给平均数。
"""

from __future__ import annotations

import collections
import hashlib
import json
import os
import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable

from . import references
from .items import Entry, estimate_tokens, normalize_request, tokens_of
from .store import EventLog

STEP_BUCKETS = ((1, 1), (2, 3), (4, 7), (8, 15), (16, 10 ** 9))


def _bucket(step_id: int) -> str:
    for low, high in STEP_BUCKETS:
        if low <= step_id <= high:
            return f"{low}-{high}" if high < 10 ** 9 else f"{low}+"
    return "?"


@dataclass
class StepView:
    run_id: str
    session_id: str | None
    department: str
    step_id: int
    index: int
    window: int
    entries: list[Entry]
    usage: list[references.EntryUsage]
    needed: int
    covered: int
    origins: dict[str, int] = field(default_factory=dict)
    model: str | None = None
    provider: str | None = None
    missing: tuple[tuple[str, str], ...] = ()
    needed_set: frozenset[str] = frozenset()
    later_set: frozenset[str] = frozenset()

    @property
    def view_tokens(self) -> int:
        return tokens_of(self.entries)

    @property
    def waste_tokens(self) -> int:
        waste = {usage.index for usage in self.usage if not usage.referenced}
        return sum(entry.tokens for entry in self.entries if entry.index in waste)

    @property
    def recall(self) -> float:
        return 1.0 if self.needed == 0 else self.covered / self.needed

    @property
    def waste_ratio(self) -> float:
        total = self.view_tokens
        return 0.0 if total == 0 else self.waste_tokens / total

    @property
    def fill(self) -> float:
        return 0.0 if self.window <= 0 else self.view_tokens / self.window


@dataclass
class StepScore:
    """对候选视图的同一套评分：这一步的召回与浪费。"""

    tokens: int
    needed: int
    covered: int
    waste_tokens: int

    @property
    def recall(self) -> float:
        return 1.0 if self.needed == 0 else self.covered / self.needed

    @property
    def waste_ratio(self) -> float:
        return 0.0 if self.tokens == 0 else self.waste_tokens / self.tokens


def score_view(entries: list[Entry], needed: frozenset[str], later: frozenset[str]) -> StepScore:
    """对任意一个候选视图（条目序列）算召回与浪费，用于比较现状与新视图。"""
    usage = references.attribute(entries, set(later))
    present = references.presence(entries)
    waste = {item.index for item in usage if not item.referenced}
    return StepScore(tokens=tokens_of(entries), needed=len(needed), covered=len(needed & present),
                     waste_tokens=sum(entry.tokens for entry in entries if entry.index in waste))


def measure_run(log: EventLog, run_id: str) -> list[StepView]:
    """把一个 run 的每一步量出来。会话各自独立：部门之间不共享视图。"""
    steps = log.steps(run_id)
    outputs = {}
    for index, step in enumerate(steps):
        next_position = steps[index + 1].position if index + 1 < len(steps) else None
        outputs[step.event_id] = log.outputs_for(step, next_position)

    order: dict[str | None, list[int]] = collections.defaultdict(list)
    for index, step in enumerate(steps):
        order[step.session_id].append(index)

    # 每个记号「此前出现过」的位置与该记号所在的输出
    produced: dict[str | None, dict[str, int]] = collections.defaultdict(dict)
    origins: dict[str | None, dict[str, int]] = collections.defaultdict(dict)
    for session, indexes in order.items():
        for position, index in enumerate(indexes):
            step = steps[index]
            for token in references.tokens_of_output(outputs[step.event_id].items,
                                                     outputs[step.event_id].tool_results):
                produced[session].setdefault(token, position)
            for result in outputs[step.event_id].tool_results:
                call = (result.get("item") or {}).get("call_id")
                if call:
                    origins[session].setdefault(call, step.step_id)
            entries = normalize_request(step.body, step.step_id)
            for entry in entries:
                for token in references.tokens_of_entry(entry):
                    produced[session].setdefault(token, position)

    views: list[StepView] = []
    for session, indexes in order.items():
        for position, index in enumerate(indexes):
            step = steps[index]
            entries = normalize_request(step.body, step.step_id)
            later: set[str] = set()
            for later_index in indexes[position:]:
                later_step = steps[later_index]
                later.update(references.tokens_of_output(outputs[later_step.event_id].items,
                                                         outputs[later_step.event_id].tool_results))
            usage = references.attribute(entries, later)
            truth = references.tokens_of_output(outputs[step.event_id].items,
                                                outputs[step.event_id].tool_results)
            # 此前出现过的记号才可能来自视图；模型在这一次输出里新造的记号不进分母
            before = produced[session]
            needed_tokens = {token for token in truth if before.get(token, position) < position}
            present = references.presence(entries)
            covered = len(needed_tokens & present)
            missing = tuple(sorted((token, truth[token]) for token in needed_tokens - present))
            views.append(StepView(
                run_id=run_id, session_id=session, department=step.department, step_id=step.step_id,
                index=index, window=step.context_window, entries=entries, usage=usage,
                needed=len(needed_tokens), covered=covered, origins=dict(origins[session]),
                model=step.model, provider=step.provider, missing=missing,
                needed_set=frozenset(needed_tokens), later_set=frozenset(later),
            ))
    views.sort(key=lambda view: view.index)
    return views


def measure_all(log: EventLog, *, min_steps: int = 1) -> list[StepView]:
    views: list[StepView] = []
    for run_id in log.runs():
        run_views = measure_run(log, run_id)
        if len(run_views) < min_steps:
            continue
        views.extend(run_views)
    return views


def _quantiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    def at(ratio: float) -> float:
        index = min(len(ordered) - 1, max(0, int(round(ratio * (len(ordered) - 1)))))
        return ordered[index]
    return {"n": len(ordered), "mean": round(statistics.mean(ordered), 4),
            "p10": round(at(0.10), 4), "median": round(statistics.median(ordered), 4),
            "p90": round(at(0.90), 4), "max": round(ordered[-1], 4)}


def _group(views: Iterable[StepView], key) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[StepView]] = collections.defaultdict(list)
    for view in views:
        groups[key(view)].append(view)
    result = {}
    for name, items in sorted(groups.items()):
        result[name] = {
            "steps": len(items),
            "tokens": sum(view.view_tokens for view in items),
            "waste_tokens": sum(view.waste_tokens for view in items),
            "waste_ratio": round(sum(view.waste_tokens for view in items) / max(1, sum(view.view_tokens for view in items)), 4),
            "recall": _quantiles([view.recall for view in items]),
            "fill": _quantiles([view.fill for view in items]),
        }
    return result


def summarise(views: list[StepView]) -> dict[str, Any]:
    """把逐步骤的量汇总成设计说明里的几张表。"""
    total_tokens = sum(view.view_tokens for view in views)
    total_waste = sum(view.waste_tokens for view in views)
    by_kind: dict[str, dict[str, int]] = collections.defaultdict(lambda: {"tokens": 0, "entries": 0})
    for view in views:
        for entry in view.entries:
            by_kind[entry.kind]["tokens"] += entry.tokens
            by_kind[entry.kind]["entries"] += 1

    section_tokens: dict[str, dict[str, int]] = collections.defaultdict(lambda: {"tokens": 0, "steps": 0})
    for view in views:
        for entry in view.entries:
            if entry.kind == "pinned":
                for source, body in entry.sections:
                    section_tokens[source]["tokens"] += estimate_tokens(body)
                section_tokens["_pinned_steps"]["steps"] += 1

    waste_by_kind: dict[str, dict[str, int]] = collections.defaultdict(lambda: {"tokens": 0, "entries": 0})
    for view in views:
        waste = {usage.index: usage for usage in view.usage}
        for entry in view.entries:
            if not waste.get(entry.index, None) or not waste[entry.index].referenced:
                waste_by_kind[entry.kind]["tokens"] += entry.tokens
                waste_by_kind[entry.kind]["entries"] += 1

    waste_by_source: dict[str, int] = collections.defaultdict(int)
    for view in views:
        unused = {usage.index for usage in view.usage if not usage.referenced}
        for entry in view.entries:
            if entry.index not in unused:
                continue
            if entry.kind == "pinned":
                for source, body in entry.sections:
                    waste_by_source[source] += estimate_tokens(body)
            elif entry.kind == "tool":
                waste_by_source[f"tool:{entry.tool or '?'}"] += entry.tokens
            elif entry.kind == "input":
                label = (entry.meta or {}).get("label") or "input"
                waste_by_source[f"input:{label}"] += entry.tokens
            else:
                waste_by_source[entry.kind] += entry.tokens

    # 工具结果按「步龄」看用处：产生以后过了几步才被引用
    ages: dict[str, dict[str, int]] = collections.defaultdict(lambda: {"entries": 0, "referenced": 0, "tokens": 0, "referenced_tokens": 0})
    tool_sizes: dict[str, dict[str, int]] = collections.defaultdict(lambda: {"entries": 0, "referenced": 0, "tokens": 0, "referenced_tokens": 0})
    read_paths: dict[str, int] = collections.Counter()
    in_view: dict[str, dict[str, int]] = collections.defaultdict(lambda: {"extra": 0, "groups": 0, "tokens": 0})
    resend: dict[str, dict[str, int]] = collections.defaultdict(lambda: {"views": 0, "tokens": 0})
    for view in views:
        usage = {item.index: item for item in view.usage}
        counts: dict[str, list[int]] = collections.defaultdict(list)
        for entry in view.entries:
            if entry.kind != "tool":
                continue
            origin = view.origins.get(entry.call_id or "")
            age = 0 if origin is None else max(0, view.step_id - origin)
            bucket = "0-1" if age <= 1 else "2-3" if age <= 3 else "4-7" if age <= 7 else "8-15" if age <= 15 else "16-31" if age <= 31 else "32+"
            used = bool(usage.get(entry.index) and usage[entry.index].referenced)
            ages[bucket]["entries"] += 1
            ages[bucket]["tokens"] += entry.tokens
            ages[bucket]["referenced"] += 1 if used else 0
            ages[bucket]["referenced_tokens"] += entry.tokens if used else 0
            size = "<=200" if entry.tokens <= 200 else "201-1000" if entry.tokens <= 1000 else "1001-4000" if entry.tokens <= 4000 else ">4000"
            tool_sizes[size]["entries"] += 1
            tool_sizes[size]["tokens"] += entry.tokens
            tool_sizes[size]["referenced"] += 1 if used else 0
            tool_sizes[size]["referenced_tokens"] += entry.tokens if used else 0
            path = (entry.meta or {}).get("path")
            if path and entry.tool in ("read_file", "read_range"):
                read_paths[f"{entry.tool}:{path}"] += 1
            name = entry.tool or "?"
            counts[_call_key(entry)].append(entry.tokens)
            resend[name]["views"] += 1
            resend[name]["tokens"] += entry.tokens
        # 同一步里同一次调用出现两遍：只有一份是必要的
        for key, sizes in counts.items():
            if len(sizes) < 2:
                continue
            tool = key.split("|", 1)[0]
            in_view[tool]["groups"] += 1
            in_view[tool]["extra"] += len(sizes) - 1
            in_view[tool]["tokens"] += sum(sizes) - max(sizes)

    # 部门输入的重复情况：同一条输入在后续每一步里都跟着装
    inputs: dict[str, dict[str, int]] = collections.defaultdict(lambda: {"entries": 0, "tokens": 0, "distinct": 0})
    input_digests: dict[str, set[str]] = collections.defaultdict(set)
    for view in views:
        for entry in view.entries:
            if entry.kind != "input":
                continue
            label = (entry.meta or {}).get("label") or "input"
            inputs[label]["entries"] += 1
            inputs[label]["tokens"] += entry.tokens
            input_digests[label].add(hashlib.sha256(entry.text.encode("utf-8")).hexdigest())
    for label, digests in input_digests.items():
        inputs[label]["distinct"] = len(digests)

    # 部门材料各段：用量与被引用记号覆盖的字符占比
    section_use: dict[str, dict[str, float]] = collections.defaultdict(
        lambda: {"tokens": 0, "chars": 0, "covered_chars": 0, "steps": 0})
    for view in views:
        usage = {item.index: item for item in view.usage}
        for entry in view.entries:
            if entry.kind != "pinned":
                continue
            credited = set(usage[entry.index].credited) if entry.index in usage else set()
            for source, body in entry.sections:
                section_use[source]["tokens"] += estimate_tokens(body)
                section_use[source]["steps"] += 1
                section_use[source]["chars"] += len(body)
                section_use[source]["covered_chars"] += min(
                    len(body), sum(len(token) for token in credited if token in body))

    missing: dict[str, int] = collections.Counter()
    for view in views:
        for token, kind in view.missing:
            missing[f"{kind}:{token if len(token) <= 40 else token[:37] + '...'}"] += 1

    # 失败结果：折叠预算之外，按定义不折叠
    errors: dict[str, dict[str, int]] = collections.defaultdict(
        lambda: {"entries": 0, "referenced": 0, "tokens": 0, "referenced_tokens": 0})
    for view in views:
        usage = {item.index: item for item in view.usage}
        for entry in view.entries:
            if entry.kind != "tool":
                continue
            state = "error" if entry.ok is False else "unknown" if entry.ok is None else "ok"
            used = bool(usage.get(entry.index) and usage[entry.index].referenced)
            errors[state]["entries"] += 1
            errors[state]["tokens"] += entry.tokens
            errors[state]["referenced"] += 1 if used else 0
            errors[state]["referenced_tokens"] += entry.tokens if used else 0

    return {
        "steps": len(views),
        "runs": len({view.run_id for view in views}),
        "sessions": len({(view.run_id, view.session_id) for view in views}),
        "tokens": total_tokens,
        "waste_tokens": total_waste,
        "waste_ratio": round(total_waste / max(1, total_tokens), 4),
        "recall": _quantiles([view.recall for view in views]),
        "recall_needed_total": sum(view.needed for view in views),
        "recall_covered_total": sum(view.covered for view in views),
        "waste_by_kind": {key: dict(value) for key, value in waste_by_kind.items()},
        "by_kind": {key: dict(value) for key, value in by_kind.items()},
        "sections": {key: dict(value) for key, value in section_tokens.items()},
        "waste_by_source": dict(sorted(waste_by_source.items(), key=lambda item: -item[1])),
        "ages": dict(sorted(ages.items())),
        "tool_sizes": dict(sorted(tool_sizes.items())),
        "duplicate_in_view": {key: dict(value) for key, value in in_view.items()},
        "duplicate_in_view_tokens": sum(value["tokens"] for value in in_view.values()),
        "resend": {key: dict(value) for key, value in resend.items()},
        "repeat_reads": {key: count for key, count in read_paths.most_common(15)},
        "inputs": {key: dict(value) for key, value in sorted(inputs.items(), key=lambda item: -item[1]["tokens"])},
        "section_use": {key: {k: round(v, 2) for k, v in value.items()}
                        for key, value in sorted(section_use.items(), key=lambda item: -item[1]["tokens"])},
        "missing_top": dict(missing.most_common(20)),
        "errors": {key: dict(value) for key, value in sorted(errors.items())},
        "by_step": _group(views, lambda view: _bucket(view.step_id)),
        "by_department": _group(views, lambda view: view.department or "?"),
        "by_window": _group(views, lambda view: f"{view.window}"),
        "by_fill": _group(views, lambda view: _fill_bucket(view.fill)),
        "by_model": _group(views, lambda view: f"{view.provider}/{view.model}"),
    }


def _call_key(entry: Entry) -> str:
    """重复调用与重复结果的判据：同一工具、同一参数。"""
    arguments = (entry.meta or {}).get("arguments")
    if arguments is None:
        return f"{entry.tool or '?'}|{hash(entry.text) & 0xFFFFFFFF:x}"
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{entry.tool or '?'}|{hashlib.sha256(arguments.encode('utf-8')).hexdigest()[:12]}"


def _fill_bucket(fill: float) -> str:
    for limit in (0.02, 0.05, 0.10, 0.20, 0.50, 1.01):
        if fill <= limit:
            return f"<={int(limit * 100)}%"
    return ">100%"


def to_markdown(data: dict[str, Any]) -> str:
    """把汇总写成设计说明里可以直接引用的表。"""
    lines: list[str] = []
    add = lines.append
    add(f"回放：{data['runs']} 个 run、{data['sessions']} 个部门会话、{data['steps']} 步工作请求，"
        f"输入合计 {data['tokens']} token（估算）。")
    add("")
    add("| 条目种类 | 条目数 | token | 占比 |")
    add("| --- | --- | --- | --- |")
    total = max(1, data["tokens"])
    for kind, value in sorted(data["by_kind"].items(), key=lambda item: -item[1]["tokens"]):
        add(f"| {kind} | {value['entries']} | {value['tokens']} | {100 * value['tokens'] / total:.1f}% |")
    add("")
    add("| 条目种类 | 从未被引用的 token | 占该类 token |")
    add("| --- | --- | --- |")
    for kind, value in sorted(data["waste_by_kind"].items(), key=lambda item: -item[1]["tokens"]):
        kind_total = max(1, data["by_kind"].get(kind, {}).get("tokens", 0))
        add(f"| {kind} | {value['tokens']} | {100 * value['tokens'] / kind_total:.1f}% |")
    add("")
    recall = data["recall"]
    add(f"召回（按步）：均值 {recall.get('mean')}，中位 {recall.get('median')}，"
        f"p10 {recall.get('p10')}，p90 {recall.get('p90')}；"
        f"合计需要 {data['recall_needed_total']} 个记号，其中 {data['recall_covered_total']} 个在视图里。")
    add("")
    add(f"浪费（按步）：合计 {data['waste_tokens']} token，占全部输入的 {100 * data['waste_ratio']:.1f}%。")
    add("")
    for name, title in (("by_step", "按步序"), ("by_department", "按部门"), ("by_window", "按窗口大小"), ("by_fill", "按窗口占用")):
        add(f"**{title}**")
        add("")
        add("| 分组 | 步数 | token | 从未被引用的 token | 浪费占比 | 召回均值 | 召回中位 | 占用中位 |")
        add("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for key, value in data[name].items():
            add(f"| {key} | {value['steps']} | {value['tokens']} | {value['waste_tokens']} | "
                f"{100 * value['waste_ratio']:.1f}% | {value['recall'].get('mean')} | "
                f"{value['recall'].get('median')} | {value['fill'].get('median')} |")
        add("")
    add("**工具结果按步龄的用处**（步龄 = 这一步距它产生时的步数）")
    add("")
    add("| 步龄 | 条目数 | 被引用 | 引用率 | token | 被引用的 token | token 引用率 |")
    add("| --- | --- | --- | --- | --- | --- | --- |")
    for key, value in data["ages"].items():
        add(f"| {key} | {value['entries']} | {value['referenced']} | "
            f"{100 * value['referenced'] / max(1, value['entries']):.1f}% | {value['tokens']} | "
            f"{value['referenced_tokens']} | {100 * value['referenced_tokens'] / max(1, value['tokens']):.1f}% |")
    add("")
    add("**工具结果按自身大小**")
    add("")
    add("| token 区间 | 条目数 | 被引用 | 引用率 | token | 被引用的 token | token 引用率 |")
    add("| --- | --- | --- | --- | --- | --- | --- |")
    for key, value in data["tool_sizes"].items():
        add(f"| {key} | {value['entries']} | {value['referenced']} | "
            f"{100 * value['referenced'] / max(1, value['entries']):.1f}% | {value['tokens']} | "
            f"{value['referenced_tokens']} | {100 * value['referenced_tokens'] / max(1, value['tokens']):.1f}% |")
    add("")
    add("**从未被引用的用量，按来源排前 15**")
    add("")
    add("| 来源 | token |")
    add("| --- | --- |")
    for key, value in list(data["waste_by_source"].items())[:15]:
        add(f"| {key} | {value} |")
    add("")
    return "\n".join(lines)


def run_measure(db_path: str, artifacts_root: str | None = None, *, min_steps: int = 1) -> dict[str, Any]:
    with EventLog(db_path, artifacts_root) as log:
        views = measure_all(log, min_steps=min_steps)
    if not views:
        raise SystemExit("事件库里没有可回放的步骤（先确认 model_request_serialized 与工件库都在）")
    data = summarise(views)
    data["source"] = {"db": os.path.abspath(db_path), "artifacts": os.path.abspath(artifacts_root or "")}
    return data


def write_report(data: dict[str, Any], out_json: str, out_md: str) -> None:
    for path in (out_json, out_md):
        folder = os.path.dirname(os.path.abspath(path))
        os.makedirs(folder, exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1, sort_keys=True)
    with open(out_md, "w", encoding="utf-8") as handle:
        handle.write(to_markdown(data))
