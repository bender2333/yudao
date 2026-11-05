"""视图：`view(events, rules) → request`，事件日志上的纯函数。

输入
----
`events`：一个部门会话的日志条目序列（`items.Entry`），按进入历史的顺序排列，包含：

- `pinned`：这一步的部门材料（同一步里只有一条，材料本身带 `[source]` 分节）；
- `input`：部门输入与通知；
- `call` / `tool`：模型调用与工具结果，靠 `call_id` 成对；
- `message`：模型的文字回答。

`rules`：规则集（`Rules`），每条规则的默认值来自同目录的规则集文件，它同时是设计说明
第 4 节规则清单的机器可读版本。

输出
----
`{"messages": [...], "tools": [...]}`：这一步真正发给模型的请求体（chat 协议的形状）。
同一个 `events` 与同一个规则版本，输出逐字节相同（`canonical_bytes`）。

为什么是纯函数：装配要能用同一份输入重放出同一份请求（审计、重放核对、反事实回放），
也要能只改一条规则就看结果差多少（对照）。函数里没有时间、随机、网络与文件读取，
顺序只来自 `events` 的顺序与规则里写明的优先级。

七条规则（设计说明第 4 节，含数据来源）：

- `input_single_copy`（定义，admission）：同一条部门输入只装一份。
- `superseded_read_collapse`（定义，admission）：同一路径的读取只留最新原文。
- `tool_result_age_budget`（参数）：历史工具结果按新到旧累计，超出保留量从最旧的开始折叠。
- `error_result_keep`（定义，permission）：失败的结果不折叠、不占折叠预算。
- `pinned_reference_gate`（定义，admission + 参数）：引证类材料只在工作引用指向它时整段装入。
- `round_fold_granularity`（定义，格式）：折叠以「一轮」为单位，调用与结果成对。
- `admission_order`（顺序规则）：装入顺序与截断，窗口是硬上限。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, fields
from typing import Any, Iterable

from .items import Entry, estimate_tokens, item_text

# 部门材料里属于「契约」的一类：每一步都要，缺了部门会做错事
CONTRACT_SECTIONS = frozenset({
    "intend", "current_work", "current_product_spec", "current_contract", "department_rules",
    "allowed_tools", "proposal_contract", "input_handling", "input_progress",
    "professional_completion", "collaboration_rules", "pending_inputs", "validation_feedback",
    "qa_defects", "pending_ask", "pending_request", "latest_response", "request_results",
    "department_guidance", "guidance_results", "revision_note", "engineering_explanation",
})

# 引证类材料：整段装进来是为了「能查到」，工作引用没指向它时只装存在与查询方式
EVIDENCE_SECTIONS = frozenset({
    "current_delivery_spec", "project", "existing_overview", "prior_delivery",
    "prior_initial_prd", "prior_structure", "causal_chain", "binding_refs",
    "current_product_decisions",
})

DEFAULT_PLACEHOLDER = "（这一条已折叠：{tool} {path}；原文在事件日志里，需要时重新读取）"
DEFAULT_FOLDED_ROUND = "（这一轮已折叠：{calls}；结果共 {tokens} token，需要时重新读取）"


@dataclass(frozen=True)
class Rules:
    """规则版本。数值型的是参数，布尔型的是定义的开与关（关掉等于回到现状）。"""

    # R1 同一条部门输入只装一份
    input_single_copy: bool = True
    # R2 同一路径的读取只留最新原文
    superseded_read_collapse: bool = True
    # R3 历史工具结果的保留量（新到旧累计 token）；超出以后从最旧的开始折叠
    tool_result_keep_tokens: int = 16000
    # R3 折叠必须至少省下这么多 token 才做（避免为了几百 token 把一轮拆碎）
    tool_result_clear_min_tokens: int = 4000
    # R4 失败结果不折叠
    error_result_keep: bool = True
    # R5 引证类材料只在工作引用指向它时整段装入
    pinned_reference_gate: bool = True
    # R5 受这一条管的是哪几段（按回放数据逐段定，见设计说明第 4 节 R5）
    gated_sections: tuple[str, ...] = (
        "current_delivery_spec", "prior_delivery", "existing_overview", "causal_chain",
        "binding_refs", "prior_structure", "prior_initial_prd", "current_product_decisions",
    )
    # R5 每个引证段在「没有指向」时留下的摘要长度（字符）
    pinned_stub_chars: int = 400
    # R6 折叠以一轮为单位
    round_fold_granularity: bool = True
    # R1 旧部门输入的折叠写法
    superseded_input_stub: str = "（第 {step} 步的旧输入已折叠：同一部门输入只保留最新一份原文）"
    # R7 工作上限：请求的输入不超过这个用量（窗口是更硬的上限）
    work_limit_tokens: int = 100000

    def version(self) -> str:
        return canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "Rules":
        known = {item.name: item for item in fields(cls)}
        unknown = set(values) - set(known)
        if unknown:
            raise ValueError(f"规则文件里有未知的字段：{sorted(unknown)}")
        # 列表型字段在 JSON 里是数组，代码里是元组：两侧保持同一种形状，规则版本才不会漂移
        normalized = {key: tuple(value) if isinstance(value, list) else value
                      for key, value in values.items()}
        return cls(**normalized)


def canonical_hash(value: Any) -> str:
    """规则版本与视图摘要用的规范串：键排序、无空格，跨机器一致。"""
    import hashlib

    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_bytes(request: dict[str, Any]) -> bytes:
    """请求的逐字节形式：同样的条目与规则给出同样的字节。"""
    return json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_rules(path: str) -> Rules:
    with open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    values = document.get("values", document)
    return Rules.from_dict(values)


# --- 视图 ---

def view(events: list[Entry], rules: Rules, tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """把日志条目装配成请求。纯函数：同一输入与同一规则给出同样的输出。"""
    pinned = [entry for entry in events if entry.kind == "pinned"]
    history = [entry for entry in events if entry.kind != "pinned"]

    materials = _materials(pinned[-1] if pinned else None, rules)
    kept = _drop_repeated_inputs(history, rules)
    kept, collapsed_paths = _collapse_superseded_reads(kept, rules)
    kept = _fold_by_budget(kept, rules, already_collapsed=collapsed_paths)

    messages: list[dict[str, Any]] = []
    if materials is not None:
        messages.append(materials)
    messages.extend(entry.to_message() for entry in kept)
    request: dict[str, Any] = {"messages": messages}
    if tools is not None:
        request["tools"] = tools
    return request


def _materials(entry: Entry | None, rules: Rules) -> dict[str, Any] | None:
    """部门材料：契约类整段保留；引证类没有工作引用指向时只留摘要。

    没有一段被替换时原样返回这一条（视图与记录逐字节一致的保证）。
    """
    if entry is None:
        return None
    if not rules.pinned_reference_gate:
        return entry.to_message()
    work_refs = _work_reference_tokens(entry)
    parts: list[str] = []
    replaced: set[str] = set()
    for source, body in entry.sections:
        if source in CONTRACT_SECTIONS or source not in rules.gated_sections:
            parts.append(f"[{source}]\n{body}")
            continue
        if source in work_refs:
            parts.append(f"[{source}]\n{body}")
            continue
        replaced.add(source)
        stub = (f"[{source}]（未装入：这一次工作没有指向这一段，原文 {len(body)} 字符；需要在 "
                f"`{source}` 里查什么时按需读取）\n{body[:rules.pinned_stub_chars]}")
        if estimate_tokens(stub) >= estimate_tokens(body):
            # 这一段本来就不长：换成摘要省不下东西，反而多出一行说明
            replaced.discard(source)
            parts.append(f"[{source}]\n{body}")
            continue
        parts.append(stub)
    if not replaced:
        return entry.to_message()
    return {"role": entry.role or "developer", "content": "\n\n".join(parts)}


def _work_reference_tokens(entry: Entry) -> set[str]:
    """这次工作引用指向哪些材料：工作引用在 `current_work` 段里点名的来源。"""
    from . import references

    for source, body in entry.sections:
        if source == "current_work":
            names = {name for name in EVIDENCE_SECTIONS if name in body}
            return names
    return set()


def _drop_repeated_inputs(history: list[Entry], rules: Rules) -> list[Entry]:
    """R1：同一种部门输入只留最新一份原文，旧的折叠成一行。

    判据是「同一种输入」而不是「同样的文字」：回放数据里 830 条部门输入没有两条完全
    相同的文字，但都是 `[current_work]` 这一种输入的不同版本（只有进度字段在变）。
    旧版本的目标已经作废，留着它只会让模型读到过时的要求。
    """
    if not rules.input_single_copy:
        return list(history)
    latest: dict[str, int] = {}
    for position, entry in enumerate(history):
        if entry.kind == "input":
            latest[_input_label(entry)] = position
    kept: list[Entry] = []
    for position, entry in enumerate(history):
        if entry.kind == "input" and latest.get(_input_label(entry)) != position:
            text = rules.superseded_input_stub.format(step=entry.step_id)
            kept.append(Entry(**{**entry.__dict__, "text": text, "tokens": estimate_tokens(text),
                                 "meta": {**(entry.meta or {}), "collapsed": True}}))
            continue
        kept.append(entry)
    return kept


def _input_label(entry: Entry) -> str:
    """部门输入的种类：`[current_work]`、通知等。"""
    label = (entry.meta or {}).get("label")
    return label or "input"


def _collapse_superseded_reads(history: list[Entry], rules: Rules) -> tuple[list[Entry], set[int]]:
    """R2：同一路径的读取只留最新原文，旧的折叠成占位。

    只折叠「读」的结果（read_file、read_range）：写与改的结果承载「文件已改成什么」，
    不属于同一条内容的新旧关系。
    """
    if not rules.superseded_read_collapse:
        return list(history), set()
    read_calls: dict[str, str] = {}
    for entry in history:
        if entry.kind == "call" and entry.call_id:
            read_calls[entry.call_id] = entry.tool or ""
    latest: dict[str, int] = {}
    for position, entry in enumerate(history):
        path = (entry.meta or {}).get("path")
        if entry.kind != "tool" or not path:
            continue
        if read_calls.get(entry.call_id or "", entry.tool or "") not in ("read_file", "read_range"):
            continue
        latest[path] = position
    collapsed: set[int] = set()
    result: list[Entry] = []
    for position, entry in enumerate(history):
        path = (entry.meta or {}).get("path")
        if entry.kind == "tool" and path and latest.get(path, position) != position \
                and read_calls.get(entry.call_id or "", entry.tool or "") in ("read_file", "read_range"):
            collapsed.add(position)
            result.append(_placeholder(entry, DEFAULT_PLACEHOLDER.format(tool=entry.tool or "?", path=path)))
            continue
        result.append(entry)
    return result, collapsed


def _fold_by_budget(history: list[Entry], rules: Rules, *, already_collapsed: set[int]) -> list[Entry]:
    """R3 + R4 + R6：历史工具结果按新到旧累计，超出保留量从最旧的开始折叠。

    折叠以一轮为单位（R6）：一次模型输出与它的工具结果成对折叠成一条注记，调用与结果
    不会只剩一半（协议要求 function_call 与它的结果成对出现）。失败结果不折叠（R4），
    它的用量也不计入保留量。已经按 R2 折叠过的结果不重复计入。
    """
    rounds = _rounds(history)
    sized = []
    for index, members in enumerate(rounds):
        tokens = sum(history[position].tokens for position in members
                     if position not in already_collapsed)
        foldable = all(not _protected(history[position], rules) for position in members)
        # 只有「有工具结果的一轮」才值得按用量折叠：纯输入或纯文字的一轮不是这一条的对象
        has_tool = any(history[position].kind == "tool" for position in members)
        sized.append((index, members, tokens, foldable and has_tool))
    running = 0
    fold: set[int] = set()
    saved = 0
    for index, members, tokens, foldable in reversed(sized):
        running += tokens
        if running <= rules.tool_result_keep_tokens:
            continue
        if not foldable:
            continue
        fold.update(members)
        saved += tokens
    if saved and saved < rules.tool_result_clear_min_tokens:
        fold = set()
    if not fold:
        return list(history)
    result: list[Entry] = []
    folded_rounds = {index for index, members in enumerate(rounds)
                     if any(position in fold for position in members)}
    for index, members in enumerate(rounds):
        if index not in folded_rounds:
            result.extend(history[position] for position in members)
            continue
        tools = [history[position] for position in members if history[position].kind == "tool"]
        calls = [history[position] for position in members if history[position].kind == "call"]
        names = sorted({entry.tool or "?" for entry in calls} | {entry.tool or "?" for entry in tools})
        text = DEFAULT_FOLDED_ROUND.format(
            calls="、".join(names) or "工具",
            tokens=sum(history[position].tokens for position in members),
        )
        first = members[0]
        result.append(Entry(index=first, kind="folded", role="user", text=text,
                            tokens=estimate_tokens(text), step_id=history[first].step_id,
                            meta={"collapsed": True, "round": index}))
    return result


def _rounds(history: list[Entry]) -> list[tuple[int, ...]]:
    """把历史切成「轮」：从一条 assistant 输出（call 或 message）到它的工具结果为止。"""
    rounds: list[list[int]] = []
    current: list[int] = []
    for position, entry in enumerate(history):
        if entry.kind in ("call", "message"):
            if current:
                rounds.append(current)
            current = [position]
            continue
        if current:
            current.append(position)
        else:
            current = [position]
    if current:
        rounds.append(current)
    return [tuple(members) for members in rounds]


def _protected(entry: Entry, rules: Rules) -> bool:
    """不能折叠的条目：部门输入、模型文字回答、失败的工具结果。"""
    if entry.kind in ("input", "message"):
        return True
    if entry.kind == "tool" and entry.ok is False and rules.error_result_keep:
        return True
    return False


def _placeholder(entry: Entry, text: str) -> Entry:
    tokens = estimate_tokens(text)
    return Entry(**{**entry.__dict__, "text": text, "tokens": tokens, "kind": entry.kind,
                    "meta": {**(entry.meta or {}), "collapsed": True}})
