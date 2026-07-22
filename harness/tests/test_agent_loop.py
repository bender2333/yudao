"""Contract tests for the explicit agent-loop dispatcher."""

import copy
import json
from dataclasses import dataclass

import pytest

from harness.agent_loop import LoopStopped, run_agent_loop
from harness.llm import (
    BudgetAccountingError,
    BudgetExhausted,
    CallResult,
    ContextOverflow,
    ProviderProtocolError,
    ProviderUnavailable,
)


def _tool(name="write_file"):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "test tool",
            "parameters": {"type": "object"},
        },
    }


TOOL_DEFS = [_tool("write_file"), _tool("read_file")]


@dataclass
class _Fn:
    name: str
    arguments: str


@dataclass
class _ToolCall:
    id: str
    function: _Fn


def _tc(call_id, name, args):
    raw = args if isinstance(args, str) else json.dumps(args)
    return _ToolCall(call_id, _Fn(name, raw))


def _result(text="", tool_calls=None, finish="stop"):
    return CallResult(
        text=text,
        tool_calls=tool_calls or [],
        finish_reason=finish,
        prompt_tokens=10,
        completion_tokens=5,
        reasoning_tokens=2,
        duration_ms=1,
    )


class ScriptedLlm:
    def __init__(self, script):
        self.script = list(script)
        self.snapshots = []
        self.calls_made = 0
        self.prompt_tokens_total = 0
        self.completion_tokens_total = 0
        self.reasoning_tokens_total = 0

    def chat(self, messages, tools, accounting_role=None):
        self.snapshots.append(copy.deepcopy(messages))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        self.calls_made += 1
        self.prompt_tokens_total += item.prompt_tokens
        self.completion_tokens_total += item.completion_tokens
        self.reasoning_tokens_total += item.reasoning_tokens
        return item


def recording_dispatch(calls, outputs=None):
    outputs = outputs or {}

    def dispatch(name, args):
        calls.append((name, args))
        return outputs.get(name, "ok")

    return dispatch

def test_dispatch_tool_must_be_callable():
    with pytest.raises(TypeError, match="dispatch_tool"):
        run_agent_loop(ScriptedLlm([]), "system", "task", [], None)



def test_dispatcher_receives_exact_name_and_args():
    calls = []
    result = run_agent_loop(
        ScriptedLlm([
            _result(tool_calls=[_tc("1", "write_file", {"path": "a", "content": "x"})], finish="tool_calls"),
            _result("done"),
        ]),
        "system", "task", TOOL_DEFS, recording_dispatch(calls),
    )
    assert calls == [("write_file", {"path": "a", "content": "x"})]
    assert result.stopped_reason == "natural"


@pytest.mark.parametrize("raw", ['{"path":', "[]", '"scalar"', "1", "null"])
def test_bad_json_or_non_object_does_not_call_dispatcher(raw):
    calls = []
    messages = [{"role": "system", "content": "system"}]
    result = run_agent_loop(
        ScriptedLlm([
            _result(tool_calls=[_tc("bad", "write_file", raw)], finish="tool_calls"),
            _result("done"),
        ]),
        "system", "task", TOOL_DEFS, recording_dispatch(calls), messages=messages,
    )
    assert calls == []
    assert result.tool_invocations == 0
    assert messages[-2]["content"] == "Error: invalid tool arguments"


def test_tool_absent_from_allowed_defs_does_not_call_dispatcher():
    calls = []
    result = run_agent_loop(
        ScriptedLlm([
            _result(tool_calls=[_tc("1", "write_file", {})], finish="tool_calls"),
            _result("done"),
        ]),
        "system", "task", [_tool("read_file")], recording_dispatch(calls),
    )
    assert calls == []
    assert result.events[1]["output"].startswith("Error: tool not available")


def test_unknown_allowed_name_is_left_to_dispatcher():
    calls = []
    result = run_agent_loop(
        ScriptedLlm([
            _result(tool_calls=[_tc("1", "custom", {})], finish="tool_calls"),
            _result("done"),
        ]),
        "system", "task", [_tool("custom")],
        recording_dispatch(calls, {"custom": "Error: unknown tool: custom"}),
    )
    assert calls == [("custom", {})]
    assert result.stopped_reason == "natural"


def test_multiple_tools_are_dispatched_in_order():
    calls = []
    result = run_agent_loop(
        ScriptedLlm([
            _result(tool_calls=[_tc("1", "write_file", {"n": 1}), _tc("2", "read_file", {"n": 2})], finish="tool_calls"),
            _result("done"),
        ]),
        "system", "task", TOOL_DEFS, recording_dispatch(calls),
    )
    assert calls == [("write_file", {"n": 1}), ("read_file", {"n": 2})]
    assert result.tool_invocations == 2


def test_ordinary_dispatcher_exception_is_sanitized_system_error():
    secret = "private-handler-detail"
    messages = [{"role": "system", "content": "system"}]

    def dispatch(_name, _args):
        raise RuntimeError(secret)

    result = run_agent_loop(
        ScriptedLlm([_result(tool_calls=[_tc("1", "write_file", {})], finish="tool_calls")]),
        "system", "task", TOOL_DEFS, dispatch, messages=messages,
    )
    assert result.stopped_reason == "system_error"
    assert secret not in json.dumps([result.events, messages])


@pytest.mark.parametrize(
    ("exception", "reason"),
    [
        (LoopStopped("nested_stop"), "nested_stop"),
        (BudgetExhausted("secret"), "budget_exhausted"),
        (BudgetAccountingError("secret"), "budget_accounting_error"),
        (ProviderUnavailable("secret"), "provider_unavailable"),
        (ProviderProtocolError("secret"), "provider_protocol_error"),
        (ContextOverflow("secret"), "context_overflow"),
    ],
)
def test_classified_dispatcher_exceptions_preserve_stop_category(exception, reason):
    def dispatch(_name, _args):
        raise exception

    result = run_agent_loop(
        ScriptedLlm([_result(tool_calls=[_tc("1", "write_file", {})], finish="tool_calls")]),
        "system", "task", TOOL_DEFS, dispatch,
    )
    assert result.stopped_reason == reason
    assert "secret" not in json.dumps(result.events)


def test_budget_is_checked_before_dispatch():
    calls = []
    llm = ScriptedLlm([_result(tool_calls=[_tc("1", "write_file", {})], finish="tool_calls")])

    def expired():
        raise BudgetExhausted("expired")

    llm.check_budget = expired
    result = run_agent_loop(llm, "system", "task", TOOL_DEFS, recording_dispatch(calls))
    assert result.stopped_reason == "budget_exhausted"
    assert calls == []


def test_terminal_acceptance_skips_remaining_tools():
    calls = []
    messages = [{"role": "system", "content": "system"}]
    result = run_agent_loop(
        ScriptedLlm([_result(tool_calls=[
            _tc("before", "write_file", {"n": 1}),
            _tc("done", "submit_done", {"marker": "yes"}),
            _tc("after", "read_file", {"secret": "skip"}),
        ], finish="tool_calls")]),
        "system", "task", TOOL_DEFS + [_tool("submit_done")],
        recording_dispatch(calls, {"submit_done": "accepted"}),
        terminal_tools={"submit_done"}, messages=messages,
    )
    assert result.stopped_reason == "terminal"
    assert result.terminal_call == {"name": "submit_done", "args": {"marker": "yes"}}
    assert calls == [("write_file", {"n": 1}), ("submit_done", {"marker": "yes"})]
    assert messages[-1]["content"] == "Skipped: terminal tool already accepted"


def test_rejected_terminal_continues_with_remaining_tools():
    calls = []
    result = run_agent_loop(
        ScriptedLlm([
            _result(tool_calls=[_tc("done", "submit_done", {}), _tc("after", "read_file", {})], finish="tool_calls"),
            _result("done"),
        ]),
        "system", "task", TOOL_DEFS + [_tool("submit_done")],
        recording_dispatch(calls, {"submit_done": "Error: rejected"}),
        terminal_tools={"submit_done"},
    )
    assert result.stopped_reason == "natural"
    assert calls == [("submit_done", {}), ("read_file", {})]


def test_max_steps_and_usage_are_reported():
    calls = []
    llm = ScriptedLlm([_result(tool_calls=[_tc(str(i), "read_file", {})], finish="tool_calls") for i in range(3)])
    result = run_agent_loop(llm, "system", "task", TOOL_DEFS, recording_dispatch(calls), max_steps=2)
    assert result.stopped_reason == "max_steps"
    assert result.calls == 2
    assert result.prompt_tokens == 20


def test_content_filter_retry_reuses_context_and_then_succeeds():
    llm = ScriptedLlm([_result(finish="content_filter"), _result("done")])
    result = run_agent_loop(llm, "system", "task", [], lambda _name, _args: "unused")
    assert result.stopped_reason == "natural"
    assert result.content_filter_retries == 1
    assert llm.snapshots[0] == llm.snapshots[1]


def test_second_content_filter_stops_provider_blocked():
    llm = ScriptedLlm([_result(finish="content_filter"), _result(finish="content_filter")])
    result = run_agent_loop(llm, "system", "task", [], lambda _name, _args: "unused")
    assert result.stopped_reason == "provider_blocked"
    assert result.calls == 2


@pytest.mark.parametrize(
    ("exception", "reason"),
    [
        (ProviderUnavailable("x"), "provider_unavailable"),
        (ProviderProtocolError("x"), "provider_protocol_error"),
        (ContextOverflow("x"), "context_overflow"),
    ],
)
def test_provider_failures_are_classified(exception, reason):
    result = run_agent_loop(ScriptedLlm([exception]), "system", "task", [], lambda _n, _a: "unused")
    assert result.stopped_reason == reason
    assert [event["type"] for event in result.events] == ["provider_error", "stop"]


@pytest.mark.parametrize(("finish", "reason"), [("length", "output_truncated"), ("odd", "provider_protocol_error")])
def test_non_tool_finish_is_classified(finish, reason):
    result = run_agent_loop(ScriptedLlm([_result("partial", finish=finish)]), "system", "task", [], lambda _n, _a: "unused")
    assert result.stopped_reason == reason
