"""Small SDK-shaped scripted fakes shared by harness tests."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from itertools import count
import sys

from harness.local_tools import CheckSpec, LocalToolRuntime
from harness.workspace import Workspace

from harness.llm import CallResult


@dataclass
class _Fn:
    name: str
    arguments: str


@dataclass
class _ToolCall:
    id: str
    function: _Fn


_CALL_IDS = count(1)


def call(name, args):
    return _ToolCall(
        id=f"call_{next(_CALL_IDS)}",
        function=_Fn(name=name, arguments=json.dumps(args)),
    )


def _result(*, text="", tool_calls=None, finish_reason="stop"):
    return CallResult(
        text=text,
        tool_calls=list(tool_calls or []),
        finish_reason=finish_reason,
        prompt_tokens=10,
        completion_tokens=5,
        reasoning_tokens=2,
        duration_ms=1,
    )


def text_stop(text):
    return _result(text=text)


def tool_result(name, args):
    return _result(tool_calls=[call(name, args)], finish_reason="tool_calls")


def multi_tool_result(calls):
    return _result(tool_calls=calls, finish_reason="tool_calls")


class ScriptedLlm:
    """Return scripted results while mirroring LlmClient accounting fields."""

    def __init__(self, script):
        self._script = list(script)
        self._index = 0
        self.message_snapshots = []
        self.tool_snapshots = []
        self.calls_made = 0
        self.prompt_tokens_total = 0
        self.completion_tokens_total = 0
        self.reasoning_tokens_total = 0
        self.usage_by_role = {}
        self.retry_attempts = 0

    def check_budget(self, *, before_call=False):
        return None

    def chat(
        self,
        messages,
        tools,
        max_completion_tokens=8000,
        accounting_role=None,
    ):
        self.message_snapshots.append(copy.deepcopy(messages))
        self.tool_snapshots.append(copy.deepcopy(tools))
        scripted = self._script[self._index]
        self._index += 1
        if isinstance(scripted, BaseException):
            raise scripted

        self.calls_made += 1
        self.prompt_tokens_total += scripted.prompt_tokens
        self.completion_tokens_total += scripted.completion_tokens
        self.reasoning_tokens_total += scripted.reasoning_tokens
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
            usage["prompt_tokens"] += scripted.prompt_tokens
            usage["completion_tokens"] += scripted.completion_tokens
            usage["reasoning_tokens"] += scripted.reasoning_tokens
            usage["llm_duration_ms"] += scripted.duration_ms
        return scripted


def make_runtime_with_public_check(tmp_path):
    workspace = Workspace(str(tmp_path / "workspace"))
    check = CheckSpec(
        (sys.executable, "-c", "import answer; assert answer.VALUE == 42"),
        5.0,
    )
    runtime = LocalToolRuntime(workspace, {"public_tests": check}, (), tmp_path / "audit")
    return workspace, runtime


def valid_acceptance_payload():
    return {
        "summary": "implement VALUE",
        "requirements": [
            {"id": "R-001", "behavior": "write VALUE=42", "evidence": "public_tests"}
        ],
        "edge_cases": [
            {"id": "E-001", "behavior": "module imports cleanly", "evidence": "public_tests"}
        ],
        "regressions_to_avoid": [
            {"id": "G-001", "behavior": "existing files remain importable", "evidence": "public_tests"}
        ],
        "fatal_conditions": [
            {"id": "F-001", "behavior": "tests are not modified", "evidence": "tree manifest"}
        ],
        "constraints": ["standard library only"],
        "non_goals": ["no CLI"],
        "clarification_responses": [],
    }


def valid_delivery_payload():
    return {
        "changed_files": ["answer.py"],
        "requirement_mapping": [
            {"requirement_id": "R-001", "files": ["answer.py"]}
        ],
        "check_names": ["public_tests"],
        "known_risks": [],
    }


def valid_release_payload():
    return {
        "verified_requirements": ["R-001", "E-001", "G-001", "F-001"],
        "check_names": ["public_tests"],
        "closed_defects": [],
        "decision": "release",
    }
