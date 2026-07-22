from __future__ import annotations

import copy
import json

from harness.tests.fakes import (
    ScriptedLlm,
    call,
    make_runtime_with_public_check,
    multi_tool_result,
    tool_result,
    text_stop,
    valid_acceptance_payload,
    valid_delivery_payload,
    valid_release_payload,
)
from harness.work_order_loop import TeamState, run_team


def test_team_happy_path_binds_tickets_to_real_tree_and_receipts(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    secret = "PAYLOAD_SECRET_MUST_NOT_LEAK"
    acceptance = valid_acceptance_payload()
    acceptance["summary"] += secret
    llm = ScriptedLlm(
        [
            tool_result("submit_acceptance", acceptance),
            multi_tool_result(
                [
                    call("write_file", {"path": "answer.py", "content": "VALUE = 42\n"}),
                    call("run_check", {"name": "public_tests"}),
                    call("submit_delivery", valid_delivery_payload()),
                ]
            ),
            multi_tool_result(
                [
                    call("run_check", {"name": "public_tests"}),
                    call("submit_release", valid_release_payload()),
                ]
            ),
        ]
    )
    ticket_callbacks = []
    events = []

    def on_ticket(ticket):
        ticket_callbacks.append(copy.deepcopy(ticket))
        ticket["kind"] = "corrupted"

    result = run_team(
        llm=llm,
        workspace=workspace,
        runtime=runtime,
        task_id="task-1",
        task="implement VALUE",
        on_ticket=on_ticket,
        on_event=events.append,
    )

    assert TeamState.DONE.value == "done"
    assert result.outcome == "done"
    assert result.stopped_reason == "done"
    assert [ticket["kind"] for ticket in result.tickets] == ["acceptance", "delivery", "release"]
    assert [ticket["kind"] for ticket in ticket_callbacks] == ["acceptance", "delivery", "release"]
    assert result.transitions == [
        "requirements->engineering",
        "engineering->quality",
        "quality->done",
    ]
    assert set(result.sessions) == {"requirements", "engineering", "quality"}
    assert len({id(session.messages) for session in result.sessions.values()}) == 3
    assert [session.activates for session in result.sessions.values()] == [1, 1, 1]

    manifest_files = [item["path"] for item in workspace.tree_manifest()]
    acceptance_ticket, delivery_ticket, release_ticket = result.tickets
    assert acceptance_ticket["parent_hash"] is None
    assert acceptance_ticket["bindings"]["files"] == []
    assert delivery_ticket["parent_hash"] == acceptance_ticket["content_hash"]
    assert delivery_ticket["bindings"]["code_tree_hash"] == workspace.tree_hash()
    assert delivery_ticket["bindings"]["files"] == manifest_files
    assert delivery_ticket["bindings"]["changed_files"] == ["answer.py"]
    assert release_ticket["parent_hash"] == delivery_ticket["content_hash"]
    assert release_ticket["bindings"]["code_tree_hash"] == workspace.tree_hash()
    assert release_ticket["bindings"]["files"] == manifest_files
    assert release_ticket["bindings"]["checks"][0]["name"] == "public_tests"
    assert release_ticket["bindings"]["checks"][0]["exit_code"] == 0

    assert result.calls == 3
    assert result.prompt_tokens == 30
    assert result.completion_tokens == 15
    assert result.reasoning_tokens == 6
    assert result.duration_ms >= 3
    assert result.tool_invocations == 6
    assert result.transient_retry_attempts == 0
    assert result.content_filter_retries == 0
    assert set(result.per_role) == {"requirements", "engineering", "quality"}
    assert [result.per_role[role]["calls"] for role in result.per_role] == [1, 1, 1]

    assert all("messages" not in event and "payload" not in event for event in events)
    assert secret not in json.dumps(events)
    assert {event["type"] for event in events if event["type"].startswith("team_")} == {
        "team_ticket",
        "team_transition",
    }


def test_on_ticket_exception_fails_closed_after_legal_issue(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    llm = ScriptedLlm(
        [tool_result("submit_acceptance", valid_acceptance_payload())]
    )

    def fail_callback(_ticket):
        raise ValueError("callback secret")

    result = run_team(
        llm,
        workspace,
        runtime,
        "task-1",
        "implement VALUE",
        on_ticket=fail_callback,
    )

    assert result.outcome == "failed"
    assert result.stopped_reason == "system_error"
    assert [ticket["kind"] for ticket in result.tickets] == ["acceptance"]


def test_invalid_terminal_can_be_corrected_in_same_activation(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    invalid = valid_acceptance_payload()
    del invalid["summary"]
    llm = ScriptedLlm(
        [
            tool_result("submit_acceptance", invalid),
            tool_result("submit_acceptance", valid_acceptance_payload()),
            text_stop("cannot implement"),
        ]
    )

    result = run_team(llm, workspace, runtime, "task-1", "implement VALUE")

    assert result.stopped_reason == "natural"
    assert result.sessions["requirements"].activates == 1
    assert result.sessions["engineering"].activates == 1
    assert [ticket["kind"] for ticket in result.tickets] == ["acceptance"]
    assert "Error: payload field acceptance.summary is missing" in str(
        result.sessions["requirements"].messages
    )
