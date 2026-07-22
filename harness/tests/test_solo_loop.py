from __future__ import annotations

import copy
from dataclasses import fields

import pytest

from harness.run_solo import SOLO_SYSTEM, SoloResult, run_solo_loop
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


def test_solo_system_describes_only_the_solo_boundary():
    lowered = SOLO_SYSTEM.lower()
    assert "private" in lowered and "persistent" in lowered and "history" in lowered
    assert "immutable" in lowered and "original task" in lowered
    assert "current workspace" in lowered and "registered checks" in lowered
    assert "local tools" in lowered and "submit_done" in lowered
    assert all(word not in lowered for word in ("department", "engineering", "quality", "requirements"))


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
