from __future__ import annotations

import copy
import json
from dataclasses import fields
from types import SimpleNamespace

import pytest

from harness.run_solo import SOLO_LOOP_SYSTEM, SOLO_SYSTEM, SoloResult, run_solo, run_solo_loop
from harness.tests.fakes import (
    ScriptedLlm,
    call,
    make_runtime_with_public_check,
    multi_tool_result,
    text_stop,
    tool_result,
)


def valid_done_payload():
    return {
        "changed_files": ["answer.py"],
        "check_names": ["public_tests"],
        "known_risks": [],
    }


def successful_calls(content="VALUE = 42\n"):
    return multi_tool_result(
        [
            call("write_file", {"path": "answer.py", "content": content}),
            call("run_check", {"name": "public_tests"}),
            call("submit_done", valid_done_payload()),
        ]
    )


def test_solo_result_fields_are_exact():
    assert [field.name for field in fields(SoloResult)] == [
        "outcome",
        "stopped_reason",
        "session",
        "completion",
        "calls",
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
        "duration_ms",
        "tool_invocations",
        "transient_retry_attempts",
        "content_filter_retries",
        "per_role",
    ]


def test_solo_prompts_keep_legacy_and_explicit_completion_separate():
    legacy = SOLO_SYSTEM.lower()
    loop = SOLO_LOOP_SYSTEM.lower()
    assert "submit_done" not in legacy
    assert "brief final summary" in legacy
    assert "private" in loop and "persistent" in loop and "history" in loop
    assert "immutable" in loop and "original task" in loop
    assert "current workspace" in loop and "registered checks" in loop
    assert "local tools" in loop and "submit_done" in loop
    assert all(word not in loop for word in ("department", "engineering", "quality", "requirements"))




def test_solo_requires_explicit_done_with_current_check(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    result = run_solo_loop(
        ScriptedLlm([successful_calls()]), workspace, runtime, "task-1", "implement VALUE"
    )

    assert result.outcome == "done"
    assert result.stopped_reason == "completed"
    assert result.session.role == "solo"
    assert result.session.activates == 1
    assert result.completion == {
        "kind": "solo_done",
        "payload": valid_done_payload(),
        "bindings": {
            "code_tree_hash": workspace.tree_hash(),
            "files": ["answer.py"],
            "changed_files": ["answer.py"],
            "checks": [
                {
                    "name": "public_tests",
                    "tree_hash": workspace.tree_hash(),
                    "exit_code": 0,
                    "timed_out": False,
                    "stdout_digest": result.completion["bindings"]["checks"][0]["stdout_digest"],
                    "stderr_digest": result.completion["bindings"]["checks"][0]["stderr_digest"],
                    "duration_ms": result.completion["bindings"]["checks"][0]["duration_ms"],
                }
            ],
        },
    }
    exposed = result.completion
    exposed["payload"]["known_risks"].append("mutated")
    assert "mutated" not in result.session.messages[-1]["content"]


def test_two_natural_stops_fail_role_incomplete(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    result = run_solo_loop(
        ScriptedLlm([text_stop("done"), text_stop("still done")]),
        workspace,
        runtime,
        "task-1",
        "implement VALUE",
    )

    assert result.outcome == "failed"
    assert result.stopped_reason == "role_incomplete"
    assert result.completion is None
    assert result.session.activates == 2
    assert "correction" in result.session.messages[-2]["content"]


def test_invalid_terminal_can_be_corrected_in_same_activation(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    invalid = valid_done_payload()
    invalid["changed_files"] = ["wrong.py"]
    llm = ScriptedLlm(
        [
            multi_tool_result(
                [
                    call("write_file", {"path": "answer.py", "content": "VALUE = 42\n"}),
                    call("run_check", {"name": "public_tests"}),
                    call("submit_done", invalid),
                    call("submit_done", valid_done_payload()),
                ]
            )
        ]
    )

    result = run_solo_loop(llm, workspace, runtime, "task-1", "implement VALUE")

    assert result.outcome == "done"
    assert result.session.activates == 1
    assert "Error: changed_files must exactly match the workspace diff" in str(result.session.messages)


@pytest.mark.parametrize("mode", ["missing", "stale", "nonzero", "baseline"])
def test_receipt_rejections_can_be_corrected_in_same_activation(tmp_path, mode):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    if mode == "baseline":
        runtime.write_file("answer.py", "VALUE = 42\n")
        runtime.run_check("public_tests")

    payload = valid_done_payload()
    calls = []
    if mode == "missing":
        calls.extend([
            call("write_file", {"path": "answer.py", "content": "VALUE = 42\n"}),
            call("submit_done", payload),
        ])
    elif mode == "stale":
        calls.extend([
            call("write_file", {"path": "answer.py", "content": "VALUE = 42\n"}),
            call("run_check", {"name": "public_tests"}),
            call("write_file", {"path": "answer.py", "content": "VALUE = 42\n# changed\n"}),
            call("submit_done", payload),
        ])
    elif mode == "nonzero":
        calls.extend([
            call("write_file", {"path": "answer.py", "content": "VALUE = 0\n"}),
            call("run_check", {"name": "public_tests"}),
            call("submit_done", payload),
            call("write_file", {"path": "answer.py", "content": "VALUE = 42\n"}),
        ])
    else:
        calls.extend([
            call("write_file", {"path": "answer.py", "content": "VALUE = 42\n# changed\n"}),
            call("submit_done", payload),
        ])
    calls.extend([
        call("run_check", {"name": "public_tests"}),
        call("submit_done", payload),
    ])

    result = run_solo_loop(
        ScriptedLlm([multi_tool_result(calls)]),
        workspace,
        runtime,
        "task-1",
        "implement VALUE",
    )

    assert result.outcome == "done"
    assert "Error:" in str(result.session.messages)


@pytest.mark.parametrize(
    ("calls", "reason"),
    [
        ([call("submit_done", {"changed_files": []})], "payload_invalid"),
        (
            [
                call("write_file", {"path": "answer.py", "content": "VALUE = 42\n"}),
                call("submit_done", {**valid_done_payload(), "changed_files": ["wrong.py"]}),
            ],
            "changed_files_mismatch",
        ),
        (
            [
                call("write_file", {"path": "answer.py", "content": "VALUE = 42\n"}),
                call("submit_done", {**valid_done_payload(), "check_names": ["unknown"]}),
            ],
            "receipt_missing_current_activation",
        ),
        (
            [
                call("write_file", {"path": "answer.py", "content": "VALUE = 0\n"}),
                call("run_check", {"name": "public_tests"}),
                call("submit_done", valid_done_payload()),
            ],
            "check_failed",
        ),
    ],
)
def test_completion_rejections_use_stable_sanitized_codes(tmp_path, calls, reason):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    events = []

    result = run_solo_loop(
        ScriptedLlm([multi_tool_result(calls), text_stop("not complete")]),
        workspace,
        runtime,
        "task-1",
        "implement VALUE",
        on_event=events.append,
    )

    rejected = [event for event in events if event["type"] == "completion_rejected"]
    assert rejected == [{"type": "completion_rejected", "kind": "solo_done", "reason": reason}]
    serialized = json.dumps(events)
    assert all(not ({"payload", "args", "output", "message"} & set(event)) for event in events)
    assert "VALUE" not in serialized


def test_correction_activation_requires_a_new_receipt(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    llm = ScriptedLlm(
        [
            multi_tool_result(
                [
                    call("write_file", {"path": "answer.py", "content": "VALUE = 42\n"}),
                    call("run_check", {"name": "public_tests"}),
                ]
            ),
            text_stop("finished without submit"),
            multi_tool_result(
                [
                    call("submit_done", valid_done_payload()),
                    call("run_check", {"name": "public_tests"}),
                    call("submit_done", valid_done_payload()),
                ]
            ),
        ]
    )

    result = run_solo_loop(llm, workspace, runtime, "task-1", "implement VALUE")

    assert result.outcome == "done"
    assert result.session.activates == 2
    assert "missing current activation receipt" in str(result.session.messages)


def test_changed_files_are_the_exact_run_diff(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    runtime.write_file("seed.py", "OLD = True\n")
    payload = valid_done_payload()
    payload["changed_files"] = ["answer.py", "seed.py"]
    llm = ScriptedLlm(
        [
            multi_tool_result(
                [
                    call("write_file", {"path": "answer.py", "content": "VALUE = 42\n"}),
                    call("run_check", {"name": "public_tests"}),
                    call("submit_done", payload),
                    call("submit_done", valid_done_payload()),
                ]
            )
        ]
    )

    result = run_solo_loop(llm, workspace, runtime, "task-1", "implement VALUE")

    assert result.outcome == "done"
    assert result.completion["bindings"]["changed_files"] == ["answer.py"]


@pytest.mark.parametrize(
    "reason",
    [
        "provider_blocked",
        "provider_unavailable",
        "budget_exhausted",
        "budget_accounting_error",
        "context_overflow",
        "output_truncated",
        "max_steps",
    ],
)
def test_noncorrectable_stop_reasons_propagate(reason, tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    stopped = text_stop("")
    stopped.stopped_reason = reason

    result = run_solo_loop(
        ScriptedLlm([stopped]), workspace, runtime, "task-1", "implement VALUE"
    )

    assert result.outcome == "failed"
    assert result.stopped_reason == reason
    assert result.session.activates == 1


def test_metrics_and_events_are_solo_only_and_sanitized(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    events = []
    llm = ScriptedLlm([text_stop("retry"), successful_calls()])
    llm.retry_attempts = 3

    result = run_solo_loop(
        llm, workspace, runtime, "task-1", "implement VALUE", on_event=events.append
    )

    assert result.calls == result.per_role["solo"]["calls"] == 2
    assert set(result.per_role) == {"solo"}
    assert result.transient_retry_attempts == 0
    assert result.tool_invocations == 3
    assert sum(event["type"] == "llm_call" for event in events) == result.calls
    assert sum(event["type"] == "solo_activation" for event in events) == 2
    assert any(event["type"] == "completion_accepted" for event in events)
    assert events[-1] == {"type": "solo_stop", "reason": "completed", "outcome": "done"}
    assert all(not ({"text", "args", "output", "messages", "payload"} & set(event)) for event in events)
    assert not hasattr(result, "sessions")
    assert not hasattr(result, "tickets")


def test_completion_is_not_published_when_acceptance_callback_fails(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    events = []

    def explode_on_acceptance(event):
        events.append(event)
        if event["type"] == "completion_accepted":
            raise RuntimeError("SECRET")

    result = run_solo_loop(
        ScriptedLlm([successful_calls()]),
        workspace,
        runtime,
        "task-1",
        "implement VALUE",
        on_event=explode_on_acceptance,
    )

    assert result.outcome == "failed"
    assert result.stopped_reason == "system_error:event_callback:RuntimeError"
    assert result.completion is None
    serialized = json.dumps(
        {"result": {"outcome": result.outcome, "reason": result.stopped_reason}, "events": events, "session": result.session.messages}
    )
    assert "SECRET" not in serialized


def test_event_callback_exception_fails_closed_without_message(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)

    def explode(_event):
        raise RuntimeError("secret callback text")

    result = run_solo_loop(
        ScriptedLlm([successful_calls()]),
        workspace,
        runtime,
        "task-1",
        "implement VALUE",
        on_event=explode,
    )

    assert result.outcome == "failed"
    assert result.stopped_reason == "system_error:event_callback:RuntimeError"
    assert "secret" not in result.stopped_reason


@pytest.mark.parametrize(
    "kwargs,error",
    [
        ({"workspace": object()}, TypeError),
        ({"runtime": object()}, ValueError),
        ({"task_id": ""}, ValueError),
        ({"task": ""}, ValueError),
        ({"max_steps": 0}, ValueError),
        ({"max_steps": True}, ValueError),
    ],
)
def test_input_validation(tmp_path, kwargs, error):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    arguments = dict(
        llm=ScriptedLlm([]),
        workspace=workspace,
        runtime=runtime,
        task_id="task-1",
        task="implement VALUE",
    )
    arguments.update(kwargs)
    with pytest.raises(error):
        run_solo_loop(**arguments)
