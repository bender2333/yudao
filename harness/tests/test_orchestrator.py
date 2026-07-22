"""Tests for harness.orchestrator + stage_tools + terminal_tools (spec §7.2).

All offline: a scripted MockLlmClient drives the state machine.
"""

import copy
import json
from dataclasses import dataclass

import pytest

from harness.agent_loop import run_agent_loop
from harness.llm import (
    BudgetExhausted,
    CallResult,
    ContextOverflow,
    ProviderProtocolError,
    ProviderUnavailable,
)
from harness.orchestrator import (
    PLAN_SYSTEM,
    UNDERSTAND_SYSTEM,
    VERIFY_SYSTEM,
    run_multi,
)
from harness.stage_tools import (
    STAGE_TOOL_DEFS,
    parse_understanding,
    submit_understanding,
    submit_verdict,
)
from harness.tools import TOOL_DEFS, tool_defs_without_writes
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


class BudgetMockLlmClient(MockLlmClient):
    def __init__(self, script, max_calls):
        super().__init__(script)
        self.max_calls = max_calls

    def chat(
        self,
        messages,
        tools,
        max_completion_tokens=8000,
        accounting_role=None,
    ):
        if self.calls_made >= self.max_calls:
            raise BudgetExhausted(f"max_calls={self.max_calls} exceeded")
        return super().chat(
            messages,
            tools,
            max_completion_tokens,
            accounting_role,
        )


class ErrorOnCallMockLlmClient(MockLlmClient):
    def __init__(self, script, error_on_attempt):
        super().__init__(script)
        self.error_on_attempt = error_on_attempt
        self.attempts = 0

    def chat(
        self,
        messages,
        tools,
        max_completion_tokens=8000,
        accounting_role=None,
    ):
        self.attempts += 1
        if self.attempts == self.error_on_attempt:
            raise RuntimeError("provider unavailable")
        return super().chat(
            messages,
            tools,
            max_completion_tokens,
            accounting_role,
        )


class TypedErrorOnCallMockLlmClient(MockLlmClient):
    def __init__(self, script, error_on_attempt, error):
        super().__init__(script)
        self.error_on_attempt = error_on_attempt
        self.error = error
        self.attempts = 0

    def chat(
        self,
        messages,
        tools,
        max_completion_tokens=8000,
        accounting_role=None,
    ):
        self.attempts += 1
        if self.attempts == self.error_on_attempt:
            raise self.error
        return super().chat(
            messages,
            tools,
            max_completion_tokens,
            accounting_role,
        )


def _role_calls(llm, system):
    return [
        messages
        for messages in llm.message_snapshots
        if messages and messages[0].get("content") == system
    ]


# ── scripted stage terminals ──────────────────────────────
_U_ARGS = {
    "summary": "s",
    "requirements": "r",
    "constraints": "c",
    "done_criteria": "d",
}


def _understand_ok():
    return _cr(tool_calls=[_tc("u", "submit_understanding", _U_ARGS)], finish="tool_calls")


def _write_ok(path="out.py", content="print(1)\n"):
    """Create a non-empty deliverable (required by PLAN gate)."""
    return _cr(
        tool_calls=[_tc("w", "write_file", {"path": path, "content": content})],
        finish="tool_calls",
    )


def _ready_ok(content="print(1)\n"):
    """PLAN ready in one model turn: write deliverable + submit_ready."""
    return _cr(
        tool_calls=[
            _tc("w", "write_file", {"path": "out.py", "content": content}),
            _tc("p", "submit_ready", {"notes": "built + ran"}),
        ],
        finish="tool_calls",
    )


def _verdict(status, reason="because"):
    return _cr(
        tool_calls=[_tc("v", "submit_verdict", {"status": status, "reason": reason})],
        finish="tool_calls",
    )


def _text_stop(text):
    """A natural stop: model emits text, no tool_calls."""
    return _cr(text=text, finish="stop")


def _stopped(result, reason):
    result.stopped_reason = reason
    result.stop_detail = reason
    return result


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
    assert llm.message_snapshots[0] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "task"},
    ]
    assert [message["role"] for message in llm.message_snapshots[1]] == [
        "system",
        "user",
        "assistant",
        "tool",
    ]


# ── three routing edges ───────────────────────────────────
def test_pass_on_first_round(tmp_path):
    ws = Workspace(str(tmp_path / "w"))
    script = [_understand_ok(), _ready_ok(), _verdict("pass")]
    result = run_multi(MockLlmClient(script), ws, "task")
    assert result.outcome == "done"
    assert result.rounds == 1
    assert result.verdict["status"] == "pass"
    assert result.session_model == "persistent"
    assert [s.stage for s in result.stages] == ["UNDERSTAND", "PLAN_EXECUTE", "VERIFY"]
    assert result.calls == 3
    assert result.prompt_tokens == 30
    assert [s.loop.calls for s in result.stages] == [1, 1, 1]


def test_reject_execution_reruns_plan(tmp_path):
    ws = Workspace(str(tmp_path / "w"))
    script = [
        _understand_ok(), _ready_ok(), _verdict("reject_execution", "bug"),
        _ready_ok("print(2)\n"), _verdict("pass"),
    ]
    llm = MockLlmClient(script)
    result = run_multi(llm, ws, "task")
    assert result.outcome == "done"
    assert result.rounds == 2
    # after reject_execution we go back to PLAN_EXECUTE, not UNDERSTAND
    stages = [s.stage for s in result.stages]
    assert stages == ["UNDERSTAND", "PLAN_EXECUTE", "VERIFY", "PLAN_EXECUTE", "VERIFY"]
    plan_calls = _role_calls(llm, PLAN_SYSTEM)
    assert len(plan_calls) == 2
    assert len(plan_calls[1]) > len(plan_calls[0])
    assert "submit_ready" in json.dumps(plan_calls[1])
    assert sum(message["role"] == "system" for message in plan_calls[1]) == 1
    assert result.sessions["PLAN_EXECUTE"].activates == 2


def test_cold_session_model_resets_plan_history(tmp_path):
    ws = Workspace(str(tmp_path / "w"))
    script = [
        _understand_ok(),
        _ready_ok(),
        _verdict("reject_execution", "bug"),
        _ready_ok("print(2)\n"),
        _verdict("pass"),
    ]
    llm = MockLlmClient(script)

    result = run_multi(llm, ws, "task", session_model="cold")

    plan_calls = _role_calls(llm, PLAN_SYSTEM)
    assert result.outcome == "done"
    assert result.session_model == "cold"
    assert result.sessions["PLAN_EXECUTE"].activates == 2
    assert [message["role"] for message in plan_calls[1]] == ["system", "user"]
    assert [handoff["kind"] for handoff in result.handoffs] == [
        "NewMission",
        "ExecuteAgainstUnderstanding",
        "VerifyAgainstUnderstanding",
        "RejectToPlan",
        "VerifyAgainstUnderstanding",
    ]


def test_invalid_session_model_fails_before_llm_call(tmp_path):
    llm = MockLlmClient([])

    with pytest.raises(ValueError, match="session_model"):
        run_multi(
            llm,
            Workspace(str(tmp_path / "w")),
            "task",
            session_model="unknown",
        )

    assert llm.calls_made == 0


def test_reject_understanding_reruns_understand(tmp_path):
    ws = Workspace(str(tmp_path / "w"))
    script = [
        _understand_ok(), _ready_ok(), _verdict("reject_understanding", "wrong"),
        _understand_ok(), _ready_ok("print(2)\n"), _verdict("pass"),
    ]
    llm = MockLlmClient(script)
    result = run_multi(llm, ws, "task")
    assert result.outcome == "done"
    assert result.rounds == 2
    stages = [s.stage for s in result.stages]
    assert stages == [
        "UNDERSTAND", "PLAN_EXECUTE", "VERIFY",
        "UNDERSTAND", "PLAN_EXECUTE", "VERIFY",
    ]
    understand_calls = _role_calls(llm, UNDERSTAND_SYSTEM)
    assert len(understand_calls) == 2
    assert len(understand_calls[1]) > len(understand_calls[0])
    assert "submit_understanding" in json.dumps(understand_calls[1])
    assert sum(message["role"] == "system" for message in understand_calls[1]) == 1
    assert result.sessions["UNDERSTAND"].activates == 2


def test_role_handoffs_do_not_share_private_transcripts(tmp_path):
    ws = Workspace(str(tmp_path / "w"))
    script = [
        _cr(
            text="UNDERSTAND_PRIVATE_TRACE",
            tool_calls=[_tc("u", "submit_understanding", _U_ARGS)],
            finish="tool_calls",
        ),
        _cr(
            text="PLAN_PRIVATE_TRACE",
            tool_calls=[
                _tc("w1", "write_file", {"path": "out.py", "content": "print(1)\n"}),
                _tc("p1", "submit_ready", {"notes": "PLAN_NOTES_PRIVATE_TRACE"}),
            ],
            finish="tool_calls",
        ),
        _cr(
            text="VERIFY_PRIVATE_TRACE",
            tool_calls=[
                _tc(
                    "v1",
                    "submit_verdict",
                    {"status": "reject_execution", "reason": "fix bug"},
                )
            ],
            finish="tool_calls",
        ),
        _ready_ok("print(2)\n"),
        _verdict("pass"),
    ]
    llm = MockLlmClient(script)

    result = run_multi(llm, ws, "ORIGINAL_TASK_L0")

    plan_calls = _role_calls(llm, PLAN_SYSTEM)
    verify_calls = _role_calls(llm, VERIFY_SYSTEM)
    first_plan = json.dumps(plan_calls[0])
    first_verify = json.dumps(verify_calls[0])
    second_plan = json.dumps(plan_calls[1])
    assert result.outcome == "done"
    assert "## Summary" in first_plan
    assert "ORIGINAL_TASK_L0" not in first_plan
    assert "UNDERSTAND_PRIVATE_TRACE" not in first_plan
    assert "## Summary" in first_verify
    assert "ORIGINAL_TASK_L0" not in first_verify
    assert "PLAN_PRIVATE_TRACE" not in first_verify
    assert "PLAN_NOTES_PRIVATE_TRACE" not in first_verify
    assert "fix bug" in second_plan
    assert "VERIFY_PRIVATE_TRACE" not in second_plan
    assert len({id(session.messages) for session in result.sessions.values()}) == 3


def test_max_rounds_escalates(tmp_path):
    ws = Workspace(str(tmp_path / "w"))
    # every round rejects execution -> never converges
    script = [_understand_ok()]
    for attempt in range(4):
        script += [
            _ready_ok(f"print({attempt})\n"),
            _verdict("reject_execution", "still bad"),
        ]
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


def test_submit_understanding_wrong_type_errors():
    out = submit_understanding(
        "ws", summary=1, requirements="r", constraints="c", done_criteria="d"
    )
    assert out.startswith("Error:")


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


def test_tool_defs_without_writes_excludes_mutations():
    names = {t["function"]["name"] for t in tool_defs_without_writes()}
    assert "write_file" not in names
    assert "edit_file" not in names
    assert "read_file" in names and "bash" in names and "list_dir" in names


# ── natural-stop hooks + gates ────────────────────────────
def test_understand_natural_stop_extracts_structured(tmp_path):
    """UNDERSTAND natural stop → one extract call into submit_understanding fields."""
    ws = Workspace(str(tmp_path / "w"))
    script = [
        _text_stop("Need a script foo.py that prints hi."),  # UNDERSTAND natural
        _understand_ok(),                                    # extract → structured
        _ready_ok(),
        _verdict("pass"),
    ]
    events = []
    result = run_multi(MockLlmClient(script), ws, "task", on_event=events.append)
    assert result.outcome == "done"
    assert "## Summary" in (result.understanding or "")
    assert "## Done-criteria" in (result.understanding or "")
    assert [s.stage for s in result.stages] == ["UNDERSTAND", "PLAN_EXECUTE", "VERIFY"]
    assert result.calls == 4
    assert [s.loop.calls for s in result.stages] == [2, 1, 1]
    assert sum(event["type"] == "llm_call" for event in events) == result.calls
    assert any(event.get("kind") == "extract" for event in events)


def test_understand_natural_stop_empty_escalates(tmp_path):
    """Empty natural stop on UNDERSTAND → escalate (no free-text artifact)."""
    ws = Workspace(str(tmp_path / "w"))
    script = [_text_stop("")]
    result = run_multi(MockLlmClient(script), ws, "task")
    assert result.outcome == "escalated"
    assert result.stages[0].terminal_call is None


def test_plan_natural_stop_proceeds_with_deliverables(tmp_path):
    """PLAN natural stop is OK only when non-empty files exist."""
    ws = Workspace(str(tmp_path / "w"))
    script = [
        _understand_ok(),
        _write_ok(),  # create deliverable
        _text_stop("Implemented out.py and ran it."),  # PLAN natural
        _verdict("pass"),
    ]
    result = run_multi(MockLlmClient(script), ws, "task")
    assert result.outcome == "done"
    assert [s.stage for s in result.stages] == ["UNDERSTAND", "PLAN_EXECUTE", "VERIFY"]


def test_plan_natural_stop_without_files_escalates(tmp_path):
    """PLAN natural stop with empty workspace → escalate (no pretend ready)."""
    ws = Workspace(str(tmp_path / "w"))
    script = [
        _understand_ok(),
        _text_stop("I am done but wrote nothing."),
    ]
    result = run_multi(MockLlmClient(script), ws, "task")
    assert result.outcome == "escalated"
    assert result.stages[-1].stage == "PLAN_EXECUTE"
    assert result.stages[-1].terminal_call is None


def test_plan_ready_without_files_escalates(tmp_path):
    """submit_ready alone without writing deliverables → escalate at PLAN gate."""
    ws = Workspace(str(tmp_path / "w"))
    script = [
        _understand_ok(),
        # terminal ready but no write_file → empty workspace
        _cr(
            tool_calls=[_tc("p", "submit_ready", {"notes": "pretend ready"})],
            finish="tool_calls",
        ),
    ]
    result = run_multi(MockLlmClient(script), ws, "task")
    assert result.outcome == "escalated"
    assert result.stages[-1].stage == "PLAN_EXECUTE"


def test_plan_ready_with_only_stale_file_escalates(tmp_path):
    ws = Workspace(str(tmp_path / "w"))
    (tmp_path / "w" / "old.txt").write_text("old", encoding="utf-8")
    script = [
        _understand_ok(),
        _cr(
            tool_calls=[_tc("p", "submit_ready", {"notes": "reused old output"})],
            finish="tool_calls",
        ),
        _verdict("pass"),
    ]

    result = run_multi(MockLlmClient(script), ws, "task")

    assert result.outcome == "escalated"
    assert result.stages[-1].stage == "PLAN_EXECUTE"


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
    events = []
    result = run_multi(MockLlmClient(script), ws, "task", on_event=events.append)
    assert result.outcome == "done"
    assert result.verdict["status"] == "pass"
    assert sum(event["type"] == "llm_call" for event in events) == result.calls
    assert any(event.get("kind") == "router" for event in events)


def test_verify_router_rejects_pass_without_reason(tmp_path):
    ws = Workspace(str(tmp_path / "w"))
    script = [
        _understand_ok(),
        _ready_ok(),
        _text_stop("Everything passed."),
        _verdict("pass", ""),
    ]

    result = run_multi(MockLlmClient(script), ws, "task", max_rounds=1)

    assert result.outcome == "escalated"
    assert result.verdict["status"] == "reject_execution"


def test_verify_natural_stop_defaults_reject(tmp_path):
    """If the verify text is empty, default to reject_execution — NEVER a false pass."""
    ws = Workspace(str(tmp_path / "w"))
    script = [
        _understand_ok(),
        _ready_ok(),
        _text_stop(""),  # VERIFY natural stop with no conclusion text -> default reject
        _ready_ok("print(2)\n"),
        _verdict("pass"),  # round 2: plan again then pass
    ]
    result = run_multi(MockLlmClient(script), ws, "task", max_rounds=3)
    assert result.outcome == "done"
    stages = [s.stage for s in result.stages]
    assert stages == ["UNDERSTAND", "PLAN_EXECUTE", "VERIFY", "PLAN_EXECUTE", "VERIFY"]


def test_verify_can_consult_understanding(tmp_path):
    """VERIFY freely calls consult_understanding; answer is promoted into understanding."""
    ws = Workspace(str(tmp_path / "w"))
    script = [
        _understand_ok(),
        _ready_ok(),
        # VERIFY: first calls consult_understanding (ambiguity)...
        _cr(
            tool_calls=[
                _tc(
                    "cq",
                    "consult_understanding",
                    {
                        "question": (
                            "does line count include a file with no trailing newline?"
                        )
                    },
                )
            ],
            finish="tool_calls",
        ),
        # ...the consult sub-loop answers naturally...
        _text_stop("Yes: count a final line without trailing newline as one line."),
        # ...back in VERIFY, now it submits a verdict.
        _verdict("pass", "resolved via consult"),
    ]
    llm = MockLlmClient(script)
    result = run_multi(llm, ws, "task")
    assert result.outcome == "done"
    assert result.consults == 1
    assert result.consult_errors == 0
    assert result.verdict["status"] == "pass"
    assert result.calls == 5
    assert [s.loop.calls for s in result.stages] == [1, 1, 3]
    understand_calls = _role_calls(llm, UNDERSTAND_SYSTEM)
    assert len(understand_calls) == 2
    assert len(understand_calls[1]) > len(understand_calls[0])
    assert "submit_understanding" in json.dumps(understand_calls[1])
    assert "does line count include" in json.dumps(understand_calls[1])
    assert result.sessions["UNDERSTAND"].activates == 2
    assert result.sessions["PLAN_EXECUTE"].activates == 1
    assert result.sessions["VERIFY"].activates == 1
    assert sum(session.activates for session in result.sessions.values()) == 4
    assert result.per_role["UNDERSTAND"]["calls"] == 2
    assert result.per_role["PLAN_EXECUTE"]["calls"] == 1
    assert result.per_role["VERIFY"]["calls"] == 2
    for metric in (
        "calls",
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
    ):
        assert getattr(result, metric) == sum(
            role[metric] for role in result.per_role.values()
        )
    assert [handoff["kind"] for handoff in result.handoffs] == [
        "NewMission",
        "ExecuteAgainstUnderstanding",
        "VerifyAgainstUnderstanding",
        "ConsultRequest",
        "ConsultAnswer",
    ]
    request, answer = result.handoffs[-2:]
    assert request["source"] == "VERIFY" and request["target"] == "UNDERSTAND"
    assert answer["source"] == "UNDERSTAND" and answer["target"] == "VERIFY"
    assert any(
        message.get("content") == request["content"]
        for message in result.sessions["UNDERSTAND"].messages
    )
    assert any(
        message.get("content") == answer["content"]
        for message in result.sessions["VERIFY"].messages
    )
    # Promotion: clarification is part of the shared understanding artifact.
    assert "## Clarification" in (result.understanding or "")
    assert "trailing newline" in (result.understanding or "")


def test_cold_consult_resets_understand_history(tmp_path):
    ws = Workspace(str(tmp_path / "w"))
    llm = MockLlmClient(
        [
            _understand_ok(),
            _ready_ok(),
            _cr(
                tool_calls=[
                    _tc(
                        "cq",
                        "consult_understanding",
                        {"question": "clarify the line rule"},
                    )
                ],
                finish="tool_calls",
            ),
            _text_stop("Count the final line."),
            _verdict("pass"),
        ]
    )

    result = run_multi(llm, ws, "task", session_model="cold")

    understand_calls = _role_calls(llm, UNDERSTAND_SYSTEM)
    assert result.outcome == "done"
    assert result.consults == 1
    assert [message["role"] for message in understand_calls[1]] == [
        "system",
        "user",
    ]


def test_failed_consult_does_not_pollute_understanding(tmp_path):
    ws = Workspace(str(tmp_path / "w"))
    consult = _cr(
        tool_calls=[
            _tc("cq", "consult_understanding", {"question": "what is ambiguous?"})
        ],
        finish="tool_calls",
    )
    stuck = [
        _cr(tool_calls=[_tc(f"l{i}", "list_dir", {})], finish="tool_calls")
        for i in range(8)
    ]
    script = [_understand_ok(), _ready_ok(), consult, *stuck, _verdict("pass")]

    result = run_multi(MockLlmClient(script), ws, "task")

    assert result.outcome == "done"
    assert result.consults == 0
    assert result.consult_errors == 1
    assert result.sessions["UNDERSTAND"].activates == 2
    assert "## Clarification" not in (result.understanding or "")
    assert [handoff["kind"] for handoff in result.handoffs].count("ConsultRequest") == 1
    assert all(handoff["kind"] != "ConsultAnswer" for handoff in result.handoffs)


def test_consult_provider_error_is_counted(tmp_path):
    ws = Workspace(str(tmp_path / "w"))
    consult = _cr(
        tool_calls=[_tc("cq", "consult_understanding", {"question": "clarify"})],
        finish="tool_calls",
    )
    llm = ErrorOnCallMockLlmClient(
        [_understand_ok(), _ready_ok(), consult, _verdict("pass")],
        error_on_attempt=4,
    )

    result = run_multi(llm, ws, "task")

    assert result.outcome == "done"
    assert result.consults == 0
    assert result.consult_errors == 1
    assert "## Clarification" not in (result.understanding or "")


def test_main_stage_budget_exhaustion_escalates(tmp_path):
    ws = Workspace(str(tmp_path / "w"))
    llm = BudgetMockLlmClient([_understand_ok(), _write_ok()], max_calls=2)

    result = run_multi(llm, ws, "task")

    assert result.outcome == "escalated"
    assert result.stopped_reason == "budget_exhausted"
    assert result.calls == 2
    assert sum(role["calls"] for role in result.per_role.values()) == 2


def test_consult_budget_exhaustion_escalates(tmp_path):
    ws = Workspace(str(tmp_path / "w"))
    consult = _cr(
        tool_calls=[_tc("cq", "consult_understanding", {"question": "clarify"})],
        finish="tool_calls",
    )
    llm = BudgetMockLlmClient(
        [_understand_ok(), _ready_ok(), consult],
        max_calls=3,
    )

    result = run_multi(llm, ws, "task")

    assert result.outcome == "escalated"
    assert result.stopped_reason == "budget_exhausted"
    assert result.consults == 0
    assert result.consult_errors == 1
    assert result.sessions["UNDERSTAND"].activates == 2
    assert result.calls == 3
    assert sum(role["calls"] for role in result.per_role.values()) == 3


def test_understand_extract_budget_exhaustion_is_not_swallowed(tmp_path):
    ws = Workspace(str(tmp_path / "w"))
    llm = BudgetMockLlmClient([_text_stop("a concrete understanding")], max_calls=1)

    result = run_multi(llm, ws, "task")

    assert result.outcome == "escalated"
    assert result.stopped_reason == "budget_exhausted"
    assert result.calls == 1


def test_understand_extract_post_response_budget_exhaustion_stops(tmp_path):
    ws = Workspace(str(tmp_path / "w"))
    events = []
    llm = MockLlmClient(
        [
            _text_stop("a concrete understanding"),
            _stopped(_understand_ok(), "budget_exhausted"),
        ]
    )

    result = run_multi(llm, ws, "task", on_event=events.append)

    assert result.outcome == "escalated"
    assert result.stopped_reason == "budget_exhausted"
    assert result.calls == 2
    assert sum(event["type"] == "llm_call" for event in events) == 2


def test_verify_router_budget_exhaustion_is_not_default_reject(tmp_path):
    ws = Workspace(str(tmp_path / "w"))
    llm = BudgetMockLlmClient(
        [
            _understand_ok(),
            _ready_ok(),
            _text_stop("All criteria passed with evidence."),
        ],
        max_calls=3,
    )

    result = run_multi(llm, ws, "task", max_rounds=1)

    assert result.outcome == "escalated"
    assert result.stopped_reason == "budget_exhausted"
    assert result.verdict is None
    assert result.calls == 3


def test_verify_router_post_response_budget_exhaustion_stops(tmp_path):
    ws = Workspace(str(tmp_path / "w"))
    events = []
    llm = MockLlmClient(
        [
            _understand_ok(),
            _ready_ok(),
            _text_stop("All criteria passed with evidence."),
            _stopped(_verdict("pass"), "budget_exhausted"),
        ]
    )

    result = run_multi(llm, ws, "task", on_event=events.append)

    assert result.outcome == "escalated"
    assert result.stopped_reason == "budget_exhausted"
    assert result.verdict is None
    assert result.calls == 4
    assert sum(event["type"] == "llm_call" for event in events) == 4


def test_verdict_reason_is_truncated_before_handoff(tmp_path):
    ws = Workspace(str(tmp_path / "w"))
    tail = "VERIFY_ONLY_TAIL"
    reason = "x" * 2000 + tail
    events = []
    llm = MockLlmClient(
        [
            _understand_ok(),
            _ready_ok(),
            _verdict("reject_execution", reason),
            _ready_ok("print(2)\n"),
            _verdict("pass"),
        ]
    )

    result = run_multi(llm, ws, "task", on_event=events.append)

    reject = next(
        handoff for handoff in result.handoffs
        if handoff["kind"] == "RejectToPlan"
    )
    assert "x" * 2000 in reject["content"]
    assert tail not in reject["content"]
    assert reject["reason_truncated"] is True
    assert reject["reason_original_chars"] == len(reason)
    assert tail not in json.dumps(result.sessions["PLAN_EXECUTE"].messages)
    assert tail in json.dumps(result.sessions["VERIFY"].messages)
    event = next(e for e in events if e["type"] == "verdict_reason_truncated")
    assert event == {
        "type": "verdict_reason_truncated",
        "original_chars": len(reason),
        "kept_chars": 2000,
    }


@pytest.mark.parametrize(
    ("exception_type", "stopped_reason"),
    [
        (ProviderUnavailable, "provider_unavailable"),
        (ProviderProtocolError, "provider_protocol_error"),
        (ContextOverflow, "context_overflow"),
    ],
)
def test_understand_extract_propagates_provider_failure(
    tmp_path, exception_type, stopped_reason
):
    secret_detail = "provider-private-detail"
    events = []
    llm = TypedErrorOnCallMockLlmClient(
        [_text_stop("structured understanding")],
        error_on_attempt=2,
        error=exception_type(secret_detail),
    )

    result = run_multi(
        llm,
        Workspace(str(tmp_path / "w")),
        "task",
        on_event=events.append,
    )

    assert result.stopped_reason == stopped_reason
    assert result.stopped_reason != "understand_incomplete"
    assert result.understanding is None
    provider_stops = [
        event["type"]
        for event in events
        if event["type"] in {"provider_error", "stop"}
    ]
    assert provider_stops[-2:] == ["provider_error", "stop"]
    transcript = {role: session.messages for role, session in result.sessions.items()}
    assert secret_detail not in json.dumps([events, transcript])


@pytest.mark.parametrize(
    ("exception_type", "stopped_reason"),
    [
        (ProviderUnavailable, "provider_unavailable"),
        (ProviderProtocolError, "provider_protocol_error"),
        (ContextOverflow, "context_overflow"),
    ],
)
def test_verify_router_propagates_provider_failure_without_default_verdict(
    tmp_path, exception_type, stopped_reason
):
    secret_detail = "provider-private-detail"
    events = []
    llm = TypedErrorOnCallMockLlmClient(
        [_understand_ok(), _ready_ok(), _text_stop("verification conclusion")],
        error_on_attempt=4,
        error=exception_type(secret_detail),
    )

    result = run_multi(
        llm,
        Workspace(str(tmp_path / "w")),
        "task",
        max_rounds=1,
        on_event=events.append,
    )

    assert result.stopped_reason == stopped_reason
    assert result.verdict is None
    provider_stops = [
        event["type"]
        for event in events
        if event["type"] in {"provider_error", "stop"}
    ]
    assert provider_stops[-2:] == ["provider_error", "stop"]
    transcript = {role: session.messages for role, session in result.sessions.items()}
    assert secret_detail not in json.dumps([events, transcript])
