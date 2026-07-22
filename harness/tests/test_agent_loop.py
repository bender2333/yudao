"""Tests for harness.agent_loop with a scripted mock LlmClient (spec §5)."""

import copy
import json
import os
from dataclasses import dataclass

import pytest

from harness.agent_loop import AgentSession, activate, run_agent_loop
from harness.llm import (
    BudgetExhausted,
    CallResult,
    ContextOverflow,
    ProviderProtocolError,
    ProviderUnavailable,
)
from harness.tools import TOOL_DEFS, tool_defs_without_writes


# ── mock tool_call objects (shape mirrors the OpenAI SDK) ──
@dataclass
class _Fn:
    name: str
    arguments: str


@dataclass
class _ToolCall:
    id: str
    function: _Fn


def _tc(call_id, name, args: dict):
    return _ToolCall(id=call_id, function=_Fn(name=name, arguments=json.dumps(args)))


class MockLlmClient:
    """Returns scripted CallResults in order; tracks cumulative totals."""

    def __init__(self, script):
        self._script = list(script)
        self._i = 0
        self.message_snapshots = []
        self.calls_made = 0
        self.prompt_tokens_total = 0
        self.completion_tokens_total = 0
        self.reasoning_tokens_total = 0
        self.usage_by_role = {}

    def chat(
        self,
        messages,
        tools,
        max_completion_tokens=8000,
        accounting_role=None,
    ):
        self.message_snapshots.append(copy.deepcopy(messages))
        result = self._script[self._i]
        self._i += 1
        self.calls_made += 1
        self.prompt_tokens_total += result.prompt_tokens
        self.completion_tokens_total += result.completion_tokens
        self.reasoning_tokens_total += result.reasoning_tokens
        if accounting_role is not None:
            usage = self.usage_by_role.setdefault(
                accounting_role,
                {
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "reasoning_tokens": 0,
                    "llm_duration_ms": 0,
                },
            )
            usage["calls"] += 1
            usage["prompt_tokens"] += result.prompt_tokens
            usage["completion_tokens"] += result.completion_tokens
            usage["reasoning_tokens"] += result.reasoning_tokens
            usage["llm_duration_ms"] += result.duration_ms
        return result


def _cr(text="", tool_calls=None, finish="stop"):
    return CallResult(
        text=text,
        tool_calls=tool_calls or [],
        finish_reason=finish,
        prompt_tokens=10,
        completion_tokens=5,
        reasoning_tokens=2,
        duration_ms=1,
    )


def test_loop_executes_tool_then_stops_natural(tmp_path):
    ws = str(tmp_path)
    script = [
        _cr(
            text="",
            tool_calls=[_tc("call_1", "write_file", {"path": "out.txt", "content": "done"})],
            finish="tool_calls",
        ),
        _cr(text="All done.", tool_calls=[], finish="stop"),
    ]
    llm = MockLlmClient(script)
    result = run_agent_loop(llm, "sys", "do it", TOOL_DEFS, ws, max_steps=40)

    assert result.stopped_reason == "natural"
    assert result.final_text == "All done."
    assert result.tool_invocations == 1
    assert result.steps == 2
    # file actually written
    assert os.path.exists(os.path.join(ws, "out.txt"))
    with open(os.path.join(ws, "out.txt"), encoding="utf-8") as f:
        assert f.read() == "done"

    # event sequence: llm_call, tool_call, llm_call, stop
    types = [e["type"] for e in result.events]
    assert types == ["llm_call", "tool_call", "llm_call", "stop"]
    assert result.events[-1]["reason"] == "natural"
    # totals propagated
    assert result.calls == 2
    assert result.prompt_tokens == 20


def test_multiple_tool_calls_one_turn(tmp_path):
    ws = str(tmp_path)
    script = [
        _cr(
            tool_calls=[
                _tc("c1", "write_file", {"path": "a.txt", "content": "A"}),
                _tc("c2", "write_file", {"path": "b.txt", "content": "B"}),
            ],
            finish="tool_calls",
        ),
        _cr(text="two files written", finish="stop"),
    ]
    llm = MockLlmClient(script)
    result = run_agent_loop(llm, "sys", "do it", TOOL_DEFS, ws)
    assert result.tool_invocations == 2
    assert os.path.exists(os.path.join(ws, "a.txt"))
    assert os.path.exists(os.path.join(ws, "b.txt"))


def test_loop_rejects_tool_not_advertised_for_stage(tmp_path):
    ws = str(tmp_path)
    script = [
        _cr(
            tool_calls=[_tc("c1", "write_file", {"path": "forbidden.txt", "content": "x"})],
            finish="tool_calls",
        ),
        _cr(text="stopped", finish="stop"),
    ]

    result = run_agent_loop(
        MockLlmClient(script),
        "sys",
        "inspect only",
        tool_defs_without_writes(),
        ws,
    )

    assert not os.path.exists(os.path.join(ws, "forbidden.txt"))
    assert result.events[1]["output"].startswith("Error: tool not available")


def test_loop_costs_are_deltas_for_shared_client(tmp_path):
    llm = MockLlmClient([_cr(text="first"), _cr(text="second")])

    first = run_agent_loop(llm, "sys", "one", TOOL_DEFS, str(tmp_path))
    second = run_agent_loop(llm, "sys", "two", TOOL_DEFS, str(tmp_path))

    assert first.calls == second.calls == 1
    assert first.prompt_tokens == second.prompt_tokens == 10


def test_activate_continues_messages_in_place(tmp_path):
    llm = MockLlmClient(
        [
            _cr(
                tool_calls=[
                    _tc(
                        "c1",
                        "write_file",
                        {"path": "out.txt", "content": "first"},
                    )
                ],
                finish="tool_calls",
            ),
            _cr(text="first done"),
            _cr(text="second done"),
        ]
    )
    session = AgentSession("PLAN_EXECUTE", "sys", TOOL_DEFS)
    history = session.messages

    first = activate(session, "turn-1", llm=llm, handlers_ctx=str(tmp_path))
    second = activate(session, "turn-2", llm=llm, handlers_ctx=str(tmp_path))

    assert session.messages is history
    assert [message["role"] for message in history] == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
        "user",
        "assistant",
    ]
    assert llm.message_snapshots[2][:-1] == history[:5]
    assert llm.message_snapshots[2][-1] == {"role": "user", "content": "turn-2"}
    assert sum(message["role"] == "system" for message in history) == 1
    assert second.final_text == "second done"
    assert first.calls == 2 and second.calls == 1
    assert first.prompt_tokens == 20 and second.prompt_tokens == 10


def test_agent_sessions_keep_transcripts_isolated(tmp_path):
    llm = MockLlmClient([_cr(text="PLAN_PRIVATE"), _cr(text="VERIFY_PRIVATE")])
    plan = AgentSession("PLAN_EXECUTE", "plan-sys", TOOL_DEFS)
    verify = AgentSession("VERIFY", "verify-sys", TOOL_DEFS)

    activate(plan, "plan-turn", llm=llm, handlers_ctx=str(tmp_path))
    activate(verify, "verify-turn", llm=llm, handlers_ctx=str(tmp_path))

    plan_blob = json.dumps(plan.messages)
    verify_blob = json.dumps(verify.messages)
    assert plan.messages is not verify.messages
    assert "PLAN_PRIVATE" in plan_blob
    assert "VERIFY_PRIVATE" not in plan_blob and "verify-turn" not in plan_blob
    assert "VERIFY_PRIVATE" in verify_blob
    assert "PLAN_PRIVATE" not in verify_blob and "plan-turn" not in verify_blob
    assert plan.messages[0] == {"role": "system", "content": "plan-sys"}
    assert verify.messages[0] == {"role": "system", "content": "verify-sys"}
    assert AgentSession.__dataclass_fields__["messages"].init is False


def test_max_steps_forces_stop(tmp_path):
    ws = str(tmp_path)
    # always returns a tool_call -> never stops naturally
    script = [
        _cr(
            tool_calls=[_tc(f"c{i}", "list_dir", {})],
            finish="tool_calls",
        )
        for i in range(10)
    ]
    llm = MockLlmClient(script)
    result = run_agent_loop(llm, "sys", "loop forever", TOOL_DEFS, ws, max_steps=3)
    assert result.stopped_reason == "max_steps"
    assert result.steps == 3
    assert result.events[-1]["type"] == "stop"
    assert result.events[-1]["reason"] == "max_steps"


def test_expired_budget_prevents_tool_dispatch(tmp_path):
    llm = MockLlmClient(
        [
            _cr(
                tool_calls=[
                    _tc(
                        "w",
                        "write_file",
                        {"path": "forbidden.txt", "content": "x"},
                    )
                ],
                finish="tool_calls",
            )
        ]
    )

    def expired():
        raise BudgetExhausted("expired")

    llm.check_budget = expired

    result = run_agent_loop(llm, "sys", "task", TOOL_DEFS, str(tmp_path))

    assert result.stopped_reason == "budget_exhausted"
    assert not (tmp_path / "forbidden.txt").exists()


def test_events_carry_no_key(tmp_path):
    ws = str(tmp_path)
    script = [_cr(text="hi", finish="stop")]
    llm = MockLlmClient(script)
    result = run_agent_loop(llm, "sys", "task", TOOL_DEFS, ws)
    blob = json.dumps(result.events)
    assert "sk-" not in blob


def test_content_filter_retries_same_context_without_recording_empty_assistant(tmp_path):
    llm = MockLlmClient(
        [_cr(text="", finish="content_filter"), _cr(text="done", finish="stop")]
    )
    messages = [{"role": "system", "content": "system"}]

    result = run_agent_loop(
        llm=llm,
        system="system",
        user="task",
        tools=[],
        handlers_ctx=str(tmp_path),
        messages=messages,
    )

    assert result.stopped_reason == "natural"
    assert result.calls == 2
    assert result.content_filter_retries == 1
    assert llm.message_snapshots[0] == llm.message_snapshots[1]
    assert [message["role"] for message in messages] == ["system", "user", "assistant"]
    assert sum(event["type"] == "llm_call" for event in result.events) == 2
    assert any(event["type"] == "provider_retry" for event in result.events)


def test_repeated_content_filter_stops_before_tool_dispatch(tmp_path):
    filtered_tool_call = [_tc("blocked", "write_file", {"path": "blocked", "content": "x"})]
    llm = MockLlmClient(
        [
            _cr(tool_calls=filtered_tool_call, finish="content_filter"),
            _cr(tool_calls=filtered_tool_call, finish="content_filter"),
            _cr(text="unexpected third call", finish="stop"),
        ]
    )
    messages = [{"role": "system", "content": "system"}]

    result = run_agent_loop(
        llm=llm,
        system="system",
        user="task",
        tools=TOOL_DEFS,
        handlers_ctx=str(tmp_path),
        messages=messages,
    )

    assert result.stopped_reason == "provider_blocked"
    assert result.calls == 2
    assert result.content_filter_retries == 1
    assert llm.message_snapshots[0] == llm.message_snapshots[1]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert not any(event["type"] == "tool_call" for event in result.events)
    assert all(event.get("reason") != "natural" for event in result.events)
    assert not (tmp_path / "blocked").exists()


def test_content_filter_retry_allowance_resets_for_new_context(tmp_path):
    llm = MockLlmClient(
        [
            _cr(finish="content_filter"),
            _cr(tool_calls=[_tc("list", "list_dir", {})], finish="tool_calls"),
            _cr(finish="content_filter"),
            _cr(text="done", finish="stop"),
        ]
    )

    result = run_agent_loop(llm, "system", "task", TOOL_DEFS, str(tmp_path))

    assert result.stopped_reason == "natural"
    assert result.calls == 4
    assert result.content_filter_retries == 2
    assert llm.message_snapshots[0] == llm.message_snapshots[1]
    assert llm.message_snapshots[2] == llm.message_snapshots[3]


def test_budget_stop_precedes_content_filter_retry(tmp_path):
    response = _cr(finish="content_filter")
    response.stopped_reason = "budget_exhausted"
    messages = [{"role": "system", "content": "system"}]

    result = run_agent_loop(
        MockLlmClient([response]),
        "system",
        "task",
        [],
        str(tmp_path),
        messages=messages,
    )

    assert result.stopped_reason == "budget_exhausted"
    assert result.content_filter_retries == 0
    assert [message["role"] for message in messages] == ["system", "user"]
    assert not any(event["type"] == "provider_retry" for event in result.events)


def test_length_finish_is_not_natural(tmp_path):
    result = run_agent_loop(
        MockLlmClient([_cr(text="partial", finish="length")]),
        "system",
        "task",
        [],
        str(tmp_path),
    )

    assert result.stopped_reason == "output_truncated"


def test_unknown_finish_without_tools_is_provider_protocol_error(tmp_path):
    result = run_agent_loop(
        MockLlmClient([_cr(text="partial", finish="unexpected")]),
        "system",
        "task",
        [],
        str(tmp_path),
    )

    assert result.stopped_reason == "provider_protocol_error"


@pytest.mark.parametrize(
    ("exception_type", "stopped_reason"),
    [
        (ProviderUnavailable, "provider_unavailable"),
        (ProviderProtocolError, "provider_protocol_error"),
        (ContextOverflow, "context_overflow"),
    ],
)
def test_typed_provider_failure_stops_loop(
    tmp_path, exception_type, stopped_reason
):
    llm = MockLlmClient([])

    def fail(*args, **kwargs):
        raise exception_type("provider failed")

    llm.chat = fail

    result = run_agent_loop(llm, "system", "task", [], str(tmp_path))

    assert result.stopped_reason == stopped_reason
    assert [event["type"] for event in result.events] == ["provider_error", "stop"]


@pytest.mark.parametrize(
    ("exception_type", "stopped_reason"),
    [
        (ProviderUnavailable, "provider_unavailable"),
        (ProviderProtocolError, "provider_protocol_error"),
        (ContextOverflow, "context_overflow"),
    ],
)
def test_extra_handler_provider_failure_stops_without_leaking_detail(
    tmp_path, exception_type, stopped_reason
):
    secret_detail = "provider-private-detail"
    llm = MockLlmClient(
        [
            _cr(tool_calls=[_tc("extra", "list_dir", {})], finish="tool_calls"),
            _cr(text="unexpected natural stop", finish="stop"),
        ]
    )
    messages = [{"role": "system", "content": "system"}]

    def fail():
        raise exception_type(secret_detail)

    result = run_agent_loop(
        llm,
        "system",
        "task",
        TOOL_DEFS,
        str(tmp_path),
        extra_handlers={"list_dir": fail},
        messages=messages,
    )

    assert result.stopped_reason == stopped_reason
    assert result.calls == 1
    assert all(event.get("reason") != "natural" for event in result.events)
    assert secret_detail not in json.dumps([result.events, messages])


@pytest.mark.parametrize(
    ("finish_reason", "stopped_reason"),
    [
        ("length", "output_truncated"),
        ("unexpected", "provider_protocol_error"),
    ],
)
def test_non_tool_finish_with_tool_calls_stops_before_dispatch(
    tmp_path, finish_reason, stopped_reason
):
    messages = [{"role": "system", "content": "system"}]
    result = run_agent_loop(
        MockLlmClient(
            [
                _cr(
                    text="partial",
                    tool_calls=[
                        _tc("write", "write_file", {"path": "blocked", "content": "x"})
                    ],
                    finish=finish_reason,
                )
            ]
        ),
        "system",
        "task",
        TOOL_DEFS,
        str(tmp_path),
        terminal_tools={"write_file"},
        messages=messages,
    )

    assert result.stopped_reason == stopped_reason
    assert result.calls == 1
    assert result.tool_invocations == 0
    assert [message["role"] for message in messages] == ["system", "user"]
    assert not any(event["type"] == "tool_call" for event in result.events)
    assert not (tmp_path / "blocked").exists()


def test_content_filter_retry_not_counted_when_next_call_hits_budget(tmp_path):
    llm = MockLlmClient([_cr(finish="content_filter")])
    unbudgeted_chat = llm.chat

    def max_one_call(*args, **kwargs):
        if llm.calls_made >= 1:
            raise BudgetExhausted("max_calls=1 exceeded")
        return unbudgeted_chat(*args, **kwargs)

    llm.chat = max_one_call

    result = run_agent_loop(llm, "system", "task", [], str(tmp_path))

    assert result.stopped_reason == "budget_exhausted"
    assert result.calls == 1
    assert result.content_filter_retries == 0
    assert not any(event["type"] == "provider_retry" for event in result.events)
