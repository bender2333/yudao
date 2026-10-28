"""视图的性质测试：确定性、配对完整、顺序不变、规则的单调性。

不用 hypothesis：它不在项目的开发依赖里（`pyproject.toml` 的 dev 组），而 CI 用
`uv sync --frozen` 装依赖。这里用固定种子的伪随机生成器造日志，性质本身与随机源无关：
同一个种子在任何机器上给出同一批样本，失败可复现。

不读事件库、不调模型、不导入 harness（`evals/tests/test_no_harness_import.py` 管这一条）。
"""

from __future__ import annotations

import dataclasses
import json
import os
import random

import pytest

from evals.context.items import Entry, estimate_tokens, normalize_request
from evals.context.replay import IDENTITY
from evals.context.view import Rules, canonical_bytes, view

SECTIONS = ("intend", "current_work", "department_rules", "proposal_contract")
RULES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "context", "rule-set.json")


def _pinned(step: int, *, evidence: str = "x" * 400) -> Entry:
    body = "\n\n".join([
        f"[{SECTIONS[0]}]\n写一个命令行小工具 textstats.py，读取文本文件并统计行数、词数与字符数。",
        f"[{SECTIONS[1]}]\n{{\"current_goal\":\"统计行词字符\",\"phase\":\"ENGINEERING\",\"step\":{step}}}",
        f"[{SECTIONS[2]}]\n部门规则：只用标准库；检查通过以后再提交交付。",
        f"[{SECTIONS[3]}]\n提交交付时写明逐条覆盖与检查命令。",
        f"[current_delivery_spec]\n{evidence}",
    ])
    from evals.context.items import split_sections

    return Entry(index=0, kind="pinned", role="developer", text=body,
                 tokens=sum(estimate_tokens(part) for _, part in split_sections(body)),
                 step_id=step, sections=split_sections(body), source=SECTIONS[0],
                 raw={"role": "developer", "content": body})


def _input(step: int, goal: str) -> Entry:
    text = f"[current_work]\n{{\"current_goal\":\"{goal}\",\"phase\":\"ENGINEERING\",\"step\":{step}}}"
    return Entry(index=0, kind="input", role="user", text=text, tokens=estimate_tokens(text),
                 step_id=step, meta={"label": "current_work"}, raw={"role": "user", "content": text})


def _call(step: int, call_id: str, tool: str, arguments: dict) -> Entry:
    raw = {"role": "assistant", "content": None,
           "tool_calls": [{"id": call_id, "type": "function",
                           "function": {"name": tool, "arguments": json.dumps(arguments)}}]}
    text = json.dumps(raw["tool_calls"], ensure_ascii=False, separators=(",", ":"))
    return Entry(index=0, kind="call", role="assistant", text=text, tokens=estimate_tokens(text),
                 step_id=step, call_id=call_id, tool=tool, raw=raw,
                 meta={"arguments": json.dumps(arguments),
                       "calls": [{"call_id": call_id, "tool": tool,
                                  "arguments": json.dumps(arguments)}]})


def _tool(step: int, call_id: str, tool: str, content: str, *, ok: bool | None = True,
          path: str | None = None) -> Entry:
    raw = {"role": "tool", "tool_call_id": call_id, "content": content}
    return Entry(index=0, kind="tool", role="tool", text=content, tokens=estimate_tokens(content),
                 step_id=step, call_id=call_id, tool=tool, ok=ok, raw=raw,
                 meta={"path": path, "arguments": json.dumps({"path": path}) if path else None})


def journal(seed: int, rounds: int = 6) -> list[Entry]:
    """造一份日志：部门材料 + 若干轮（输入、调用、结果），带重复读取、失败结果与重复输入。"""
    rng = random.Random(seed)
    events: list[Entry] = [_pinned(1)]
    goal = f"目标-{seed}"
    for step in range(1, rounds + 1):
        events.append(_input(step, goal))
        style = rng.choice(["read", "read", "bash", "fail"])
        call_id = f"call_{seed}_{step}"
        if style == "read":
            path = rng.choice(["textstats.py", "README.md"])
            events.append(_call(step, call_id, "read_file", {"path": path}))
            events.append(_tool(step, call_id, "read_file", "内容" * rng.randint(5, 400), path=path))
        elif style == "bash":
            events.append(_call(step, call_id, "bash", {"command": f"python -m pytest -k {seed}"}))
            events.append(_tool(step, call_id, "bash", '{"ok":true,"output":"1 passed"}' * rng.randint(1, 40)))
        else:
            events.append(_call(step, call_id, "edit_range", {"path": "textstats.py"}))
            events.append(_tool(step, call_id, "edit_range",
                                '{"ok":false,"error":"file changed since the read"}', ok=False,
                                path="textstats.py"))
    # 每一步的视图都以一条部门材料开头、只有一条（与记录下来的请求同形），
    # 所以这里把材料留在开头，历史按顺序跟在后面
    return events


def test_view_is_deterministic_byte_for_byte():
    """同事件、同规则版本：逐字节相同的请求（200 份随机日志）。"""
    rules = Rules()
    for seed in range(200):
        events = journal(seed, rounds=1 + seed % 8)
        first = canonical_bytes(view(events, rules, tools=[{"type": "function", "name": "read_file"}]))
        second = canonical_bytes(view(list(events), rules, tools=[{"type": "function", "name": "read_file"}]))
        assert first == second
        # 规则版本只由规则决定：同一份规则取值给出同一个版本号
        assert dataclasses.replace(rules).version() == rules.version()


def test_view_does_not_mutate_its_input():
    events = journal(7, rounds=5)
    snapshot = [entry.to_dict() for entry in events]
    view(events, Rules(), tools=[])
    assert [entry.to_dict() for entry in events] == snapshot


def test_identity_rules_reproduce_the_recorded_request():
    """规则全关时，视图必须还原记录下来的条目（这是回放忠实的前提）。"""
    for seed in range(50):
        events = journal(seed, rounds=1 + seed % 6)
        rebuilt = view(events, IDENTITY, tools=[])
        recorded = [entry.to_message() for entry in events]
        assert rebuilt["messages"] == recorded


def test_tool_calls_stay_paired_with_their_results():
    """折叠不会留下配不上的一半：每个结果都有同名调用，每个调用都有结果或整轮消失。"""
    rules = Rules(tool_result_keep_tokens=200, tool_result_clear_min_tokens=0)
    for seed in range(100):
        request = view(journal(seed, rounds=1 + seed % 8), rules, tools=[])
        pending: dict[str, str] = {}
        for message in request["messages"]:
            if message.get("role") == "assistant" and message.get("tool_calls"):
                for call in message["tool_calls"]:
                    pending[call["id"]] = call["function"]["name"]
            elif message.get("role") == "tool":
                assert message["tool_call_id"] in pending, message
                del pending[message["tool_call_id"]]
            elif message.get("role") == "user" and message.get("content", "").startswith("（这一轮已折叠"):
                # 整轮折叠：这一轮的调用与结果一起消失，不留一半
                assert not pending
        assert not pending, pending


def test_materials_are_always_first_and_keep_contract_sections():
    for seed in range(100):
        request = view(journal(seed), Rules(), tools=[])
        first = request["messages"][0]
        assert first["role"] == "developer"
        for section in SECTIONS:
            assert f"[{section}]" in first["content"]


def test_order_of_surviving_entries_is_the_journal_order():
    events = journal(11, rounds=8)
    request = view(events, Rules(), tools=[])
    wanted = [entry.text for entry in events if entry.kind != "pinned"]
    seen = [json.dumps(message, ensure_ascii=False, sort_keys=True) for message in request["messages"][1:]]
    positions = []
    for text in wanted:
        for index, line in enumerate(seen):
            if text[:40] in line:
                positions.append(index)
                break
    assert positions == sorted(positions)


def test_raising_the_keep_budget_never_saves_more():
    """保留量越大，留下的原文越多：用量随保留量单调不降。"""
    events = journal(3, rounds=10)
    small = _tokens(view(events, Rules(tool_result_keep_tokens=100, tool_result_clear_min_tokens=0), tools=[]))
    medium = _tokens(view(events, Rules(tool_result_keep_tokens=800, tool_result_clear_min_tokens=0), tools=[]))
    large = _tokens(view(events, Rules(tool_result_keep_tokens=10 ** 9, tool_result_clear_min_tokens=0), tools=[]))
    assert small <= medium <= large


def test_superseded_reads_leave_one_original():
    events = [
        _pinned(1),
        _input(1, "目标"),
        _call(1, "c1", "read_file", {"path": "textstats.py"}),
        _tool(1, "c1", "read_file", "第一版内容" * 50, path="textstats.py"),
        _call(2, "c2", "read_file", {"path": "textstats.py"}),
        _tool(2, "c2", "read_file", "第二版内容" * 50, path="textstats.py"),
    ]
    request = view(events, Rules(), tools=[])
    contents = [message.get("content") or "" for message in request["messages"] if message["role"] == "tool"]
    assert any("第二版内容" in content for content in contents)
    assert not any("第一版内容" in content for content in contents)


def test_error_results_are_never_collapsed():
    events = [_pinned(1), _input(1, "目标")]
    for step in range(1, 12):
        events.append(_call(step, f"c{step}", "edit_range", {"path": "a.py"}))
        events.append(_tool(step, f"c{step}", "edit_range",
                            '{"ok":false,"error":"file changed since the read"}', ok=False, path="a.py"))
    tight = Rules(tool_result_keep_tokens=1, tool_result_clear_min_tokens=0)
    request = view(events, tight, tools=[])
    hits = [message for message in request["messages"]
            if message["role"] == "tool" and "file changed since the read" in (message.get("content") or "")]
    assert len(hits) == 11


def test_rules_file_matches_the_dataclass():
    """规则文件与代码里的字段一一对应，缺一个就报错（规则版本不能悄悄漂移）。"""
    with open(RULES_PATH, encoding="utf-8") as handle:
        document = json.load(handle)
    parsed = Rules.from_dict(document["values"])
    assert parsed == Rules()
    assert len(document["records"]) >= 7
    for record in document["records"]:
        for key in ("name", "form", "kind", "input", "output", "default", "origin"):
            assert record.get(key), record
    with pytest.raises(ValueError):
        Rules.from_dict({**document["values"], "no_such_rule": 1})


def _tokens(request: dict) -> int:
    return sum(estimate_tokens(json.dumps(message, ensure_ascii=False)) for message in request["messages"])
