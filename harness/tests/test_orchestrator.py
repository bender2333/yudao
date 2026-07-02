"""Tests for harness.orchestrator + stage_tools + terminal_tools (spec §7.2).

All offline: a scripted MockLlmClient drives the state machine.
"""

import json
from dataclasses import dataclass

from harness.agent_loop import run_agent_loop
from harness.llm import CallResult
from harness.orchestrator import run_multi
from harness.stage_tools import (
    STAGE_TOOL_DEFS,
    parse_understanding,
    submit_understanding,
    submit_verdict,
)
from harness.tools import TOOL_DEFS
from harness.workspace import Workspace


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


class MockLlmClient:
    def __init__(self, script):
        self._script = list(script)
        self._i = 0
        self.calls_made = 0
        self.prompt_tokens_total = 0
        self.completion_tokens_total = 0
        self.reasoning_tokens_total = 0

    def chat(self, messages, tools, max_completion_tokens=8000):
        result = self._script[self._i]
        self._i += 1
        self.calls_made += 1
        self.prompt_tokens_total += result.prompt_tokens
        self.completion_tokens_total += result.completion_tokens
        self.reasoning_tokens_total += result.reasoning_tokens
        return result


# ── scripted stage terminals ──────────────────────────────
_U_ARGS = {
    "summary": "s",
    "requirements": "r",
    "constraints": "c",
    "done_criteria": "d",
}


def _understand_ok():
    return _cr(tool_calls=[_tc("u", "submit_understanding", _U_ARGS)], finish="tool_calls")


def _ready_ok():
    return _cr(tool_calls=[_tc("p", "submit_ready", {"notes": "built + ran"})], finish="tool_calls")


def _verdict(status, reason="because"):
    return _cr(
        tool_calls=[_tc("v", "submit_verdict", {"status": status, "reason": reason})],
        finish="tool_calls",
    )


# ── terminal_tools primitive ──────────────────────────────
def test_terminal_tool_stops_loop(tmp_path):
    ws = str(tmp_path)
    script = [_verdict("pass", "looks good")]
    llm = MockLlmClient(script)
    result = run_agent_loop(
        llm, "sys", "verify", TOOL_DEFS + STAGE_TOOL_DEFS["VERIFY"], ws,
        terminal_tools={"submit_verdict"},
    )
    assert result.stopped_reason == "terminal"
    assert result.terminal_call["name"] == "submit_verdict"
    assert result.terminal_call["args"]["status"] == "pass"
    assert result.tool_invocations == 1


def test_solo_path_unchanged_without_terminal_tools(tmp_path):
    """Regression: no terminal_tools -> milestone-1 behavior (natural stop)."""
    ws = str(tmp_path)
    script = [
        _cr(tool_calls=[_tc("c1", "write_file", {"path": "a.txt", "content": "A"})], finish="tool_calls"),
        _cr(text="done", finish="stop"),
    ]
    llm = MockLlmClient(script)
    result = run_agent_loop(llm, "sys", "task", TOOL_DEFS, ws)
    assert result.stopped_reason == "natural"
    assert result.terminal_call is None
    types = [e["type"] for e in result.events]
    assert types == ["llm_call", "tool_call", "llm_call", "stop"]


# ── three routing edges ───────────────────────────────────
def test_pass_on_first_round(tmp_path):
    ws = Workspace(str(tmp_path / "w"))
    script = [_understand_ok(), _ready_ok(), _verdict("pass")]
    result = run_multi(MockLlmClient(script), ws, "task")
    assert result.outcome == "done"
    assert result.rounds == 1
    assert result.verdict["status"] == "pass"
    assert [s.stage for s in result.stages] == ["UNDERSTAND", "PLAN_EXECUTE", "VERIFY"]


def test_reject_execution_reruns_plan(tmp_path):
    ws = Workspace(str(tmp_path / "w"))
    script = [
        _understand_ok(), _ready_ok(), _verdict("reject_execution", "bug"),
        _ready_ok(), _verdict("pass"),
    ]
    result = run_multi(MockLlmClient(script), ws, "task")
    assert result.outcome == "done"
    assert result.rounds == 2
    # after reject_execution we go back to PLAN_EXECUTE, not UNDERSTAND
    stages = [s.stage for s in result.stages]
    assert stages == ["UNDERSTAND", "PLAN_EXECUTE", "VERIFY", "PLAN_EXECUTE", "VERIFY"]


def test_reject_understanding_reruns_understand(tmp_path):
    ws = Workspace(str(tmp_path / "w"))
    script = [
        _understand_ok(), _ready_ok(), _verdict("reject_understanding", "wrong"),
        _understand_ok(), _ready_ok(), _verdict("pass"),
    ]
    result = run_multi(MockLlmClient(script), ws, "task")
    assert result.outcome == "done"
    assert result.rounds == 2
    stages = [s.stage for s in result.stages]
    assert stages == [
        "UNDERSTAND", "PLAN_EXECUTE", "VERIFY",
        "UNDERSTAND", "PLAN_EXECUTE", "VERIFY",
    ]


def test_max_rounds_escalates(tmp_path):
    ws = Workspace(str(tmp_path / "w"))
    # every round rejects execution -> never converges
    script = []
    for _ in range(4):
        script += [_understand_ok(), _ready_ok(), _verdict("reject_execution", "still bad")]
    # extra padding in case
    script += [_understand_ok(), _ready_ok(), _verdict("reject_execution", "x")]
    result = run_multi(MockLlmClient(script), ws, "task", max_rounds=4)
    assert result.outcome == "escalated"
    assert result.rounds == 4


def test_stage_without_terminal_escalates(tmp_path):
    ws = Workspace(str(tmp_path / "w"))
    # understanding loop never calls terminal -> hits max_steps
    script = [
        _cr(tool_calls=[_tc("c", "list_dir", {})], finish="tool_calls")
        for _ in range(5)
    ]
    result = run_multi(MockLlmClient(script), ws, "task", max_steps=3)
    assert result.outcome == "escalated"
    assert result.stages[0].terminal_call is None


# ── stage_tools validation ────────────────────────────────
def test_submit_understanding_empty_field_errors():
    out = submit_understanding("ws", summary="", requirements="r", constraints="c", done_criteria="d")
    assert out.startswith("Error:") and "summary" in out


def test_submit_understanding_ok():
    out = submit_understanding("ws", summary="s", requirements="r", constraints="c", done_criteria="d")
    assert out == "understanding recorded"


def test_submit_verdict_invalid_status():
    assert submit_verdict("ws", status="maybe", reason="x") == "Error: invalid status"


def test_submit_verdict_missing_reason():
    assert submit_verdict("ws", status="pass", reason="").startswith("Error:")


def test_empty_field_does_not_terminate_loop(tmp_path):
    """An Error回执 from a terminal tool must NOT stop the loop."""
    ws = str(tmp_path)
    script = [
        # first call: bad submit (empty field) -> Error, loop continues
        _cr(
            tool_calls=[_tc("u1", "submit_understanding",
                            {"summary": "", "requirements": "r", "constraints": "c", "done_criteria": "d"})],
            finish="tool_calls",
        ),
        # second call: valid submit -> terminal
        _cr(tool_calls=[_tc("u2", "submit_understanding", _U_ARGS)], finish="tool_calls"),
    ]
    llm = MockLlmClient(script)
    result = run_agent_loop(
        llm, "sys", "understand", TOOL_DEFS + STAGE_TOOL_DEFS["UNDERSTAND"], ws,
        terminal_tools={"submit_understanding"},
    )
    assert result.stopped_reason == "terminal"
    assert result.steps == 2


def test_parse_understanding_assembles_text():
    text = parse_understanding(_U_ARGS)
    assert "## Summary" in text and "## Done-criteria" in text


# ── natural-stop hooks (the milestone-2.1 fix) ────────────
def _text_stop(text):
    """A natural stop: model emits text, no tool_calls."""
    return _cr(text=text, finish="stop")


def test_understand_natural_stop_uses_text(tmp_path):
    """UNDERSTAND stops naturally (no submit_understanding) -> its text becomes
    the understanding, and the pipeline proceeds instead of escalating."""
    ws = Workspace(str(tmp_path / "w"))
    script = [
        _text_stop("The task needs a script foo.py that prints hi."),  # UNDERSTAND natural
        _ready_ok(),                                                   # PLAN terminal
        _verdict("pass"),                                              # VERIFY terminal
    ]
    result = run_multi(MockLlmClient(script), ws, "task")
    assert result.outcome == "done"
    assert result.understanding.startswith("The task needs")
    assert [s.stage for s in result.stages] == ["UNDERSTAND", "PLAN_EXECUTE", "VERIFY"]


def test_plan_natural_stop_proceeds(tmp_path):
    """PLAN stops naturally (no submit_ready) -> proceeds to VERIFY."""
    ws = Workspace(str(tmp_path / "w"))
    script = [
        _understand_ok(),
        _text_stop("Implemented foo.py and ran it, prints hi."),  # PLAN natural
        _verdict("pass"),
    ]
    result = run_multi(MockLlmClient(script), ws, "task")
    assert result.outcome == "done"
    assert [s.stage for s in result.stages] == ["UNDERSTAND", "PLAN_EXECUTE", "VERIFY"]


def test_verify_natural_stop_recovers_verdict_via_router(tmp_path):
    """VERIFY stops naturally -> the on_stop hook makes ONE classification call
    that recovers a routing verdict (here: pass)."""
    ws = Workspace(str(tmp_path / "w"))
    script = [
        _understand_ok(),
        _ready_ok(),
        _text_stop("All criteria met: ran it, output correct."),  # VERIFY natural
        _verdict("pass", "router classification"),                # hook's router call
    ]
    result = run_multi(MockLlmClient(script), ws, "task")
    assert result.outcome == "done"
    assert result.verdict["status"] == "pass"


def test_verify_natural_stop_router_defaults_to_reject(tmp_path):
    """If the verify text is empty / router yields nothing usable, default to
    reject_execution — NEVER a false pass."""
    ws = Workspace(str(tmp_path / "w"))
    script = [
        _understand_ok(),
        _ready_ok(),
        _text_stop(""),  # VERIFY natural stop with no conclusion text -> default reject
        # (empty text short-circuits to default; router call not consumed)
        _ready_ok(), _verdict("pass"),  # round 2: plan again then pass
    ]
    result = run_multi(MockLlmClient(script), ws, "task", max_rounds=3)
    # first verify defaulted to reject_execution -> back to PLAN_EXECUTE -> pass
    assert result.outcome == "done"
    stages = [s.stage for s in result.stages]
    assert stages == ["UNDERSTAND", "PLAN_EXECUTE", "VERIFY", "PLAN_EXECUTE", "VERIFY"]

