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
from harness.llm import ProviderUnavailable


def _content_filter_result():
    result = text_stop("")
    result.finish_reason = "content_filter"
    return result


def test_content_filter_retry_is_counted_before_later_natural_stop(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    llm = ScriptedLlm(
        [
            _content_filter_result(),
            tool_result("submit_acceptance", valid_acceptance_payload()),
            text_stop("cannot implement"),
            text_stop("still cannot implement"),
        ]
    )

    result = run_team(llm, workspace, runtime, "task-1", "implement VALUE")

    assert result.stopped_reason == "role_incomplete"
    assert result.content_filter_retries == 1


def test_content_filter_retry_is_counted_before_provider_failure(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    llm = ScriptedLlm(
        [
            _content_filter_result(),
            ProviderUnavailable("SECRET_PROVIDER_MESSAGE"),
        ]
    )

    result = run_team(llm, workspace, runtime, "task-1", "implement VALUE")

    assert result.stopped_reason == "provider_unavailable"
    assert result.content_filter_retries == 1


def test_unexpected_activation_failure_has_sanitized_phase_and_type(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    secret = "SECRET_ACTIVATION_MESSAGE"
    llm = ScriptedLlm([ValueError(secret)])
    events = []

    result = run_team(
        llm, workspace, runtime, "task-1", "implement VALUE", on_event=events.append
    )

    assert result.stopped_reason == "system_error:requirements_activation:ValueError"
    assert secret not in json.dumps([result, events], default=str)




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
    assert runtime.check_sequence == 2
    assert set(result.per_role) == {"requirements", "engineering", "quality"}
    assert [result.per_role[role]["calls"] for role in result.per_role] == [1, 1, 1]

    assert all("messages" not in event and "payload" not in event for event in events)
    assert secret not in json.dumps(events)
    assert {event["type"] for event in events if event["type"].startswith("team_")} == {
        "team_ticket",
        "team_transition",
        "team_stop",
    }


def test_on_ticket_exception_fails_closed_after_legal_issue(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    llm = ScriptedLlm(
        [tool_result("submit_acceptance", valid_acceptance_payload())]
    )

    secret = "SECRET_TICKET_CALLBACK"

    def fail_callback(_ticket):
        raise RuntimeError(secret)

    events = []
    result = run_team(
        llm,
        workspace,
        runtime,
        "task-1",
        "implement VALUE",
        on_ticket=fail_callback,
        on_event=events.append,
    )

    assert result.outcome == "failed"
    assert result.stopped_reason == "system_error:ticket_callback:RuntimeError"
    assert [ticket["kind"] for ticket in result.tickets] == ["acceptance"]
    assert secret not in json.dumps([result, events], default=str)
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
            text_stop("still cannot implement"),
        ]
    )

    result = run_team(llm, workspace, runtime, "task-1", "implement VALUE")

    assert result.stopped_reason == "role_incomplete"
    assert result.sessions["requirements"].activates == 1
    assert result.sessions["engineering"].activates == 2
    assert [ticket["kind"] for ticket in result.tickets] == ["acceptance"]
    assert "Error: payload field acceptance.summary is missing" in str(
        result.sessions["requirements"].messages
    )



def _clarification_payload():
    return {
        "blocked_requirement_ids": ["R-001"],
        "question": "Which value is required?",
        "interpretations": [
            {"choice": "forty-two", "observable_result": "write VALUE=42"},
            {"choice": "other", "observable_result": "write another value"},
        ],
        "why_blocking": "The implementation depends on the value.",
    }


def _defect_payload():
    return {
        "route": "engineering",
        "defects": [
            {
                "requirement_ids": ["R-001"],
                "severity": "major",
                "reproduction": ["run public_tests"],
                "expected": "pass",
                "actual": "fails quality review",
                "evidence_check_names": ["public_tests"],
            }
        ],
    }


def test_engineering_cannot_reuse_requirements_check_receipt(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    llm = ScriptedLlm(
        [
            multi_tool_result(
                [
                    call("run_check", {"name": "public_tests"}),
                    call("submit_acceptance", valid_acceptance_payload()),
                ]
            ),
            multi_tool_result(
                [
                    call("write_file", {"path": "answer.py", "content": "VALUE = 42\n"}),
                    call("submit_delivery", valid_delivery_payload()),
                ]
            ),
            text_stop("cannot provide fresh engineering evidence"),
            text_stop("still cannot provide fresh engineering evidence"),
        ]
    )

    result = run_team(llm, workspace, runtime, "task-1", "implement VALUE")

    assert result.outcome == "failed"
    assert result.stopped_reason == "role_incomplete"
    assert [ticket["kind"] for ticket in result.tickets] == ["acceptance"]
    assert "missing current activation receipt" in str(result.sessions["engineering"].messages)


def test_quality_cannot_reuse_engineering_check_receipt(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    llm = ScriptedLlm(
        [
            tool_result("submit_acceptance", valid_acceptance_payload()),
            multi_tool_result(
                [
                    call("write_file", {"path": "answer.py", "content": "VALUE = 42\n"}),
                    call("run_check", {"name": "public_tests"}),
                    call("submit_delivery", valid_delivery_payload()),
                ]
            ),
            tool_result("submit_release", valid_release_payload()),
            text_stop("cannot provide fresh quality evidence"),
            text_stop("still cannot provide fresh quality evidence"),
        ]
    )

    result = run_team(llm, workspace, runtime, "task-1", "implement VALUE")

    assert result.outcome == "failed"
    assert result.stopped_reason == "role_incomplete"
    assert [ticket["kind"] for ticket in result.tickets] == ["acceptance", "delivery"]
    assert "missing current activation receipt" in str(result.sessions["quality"].messages)


def test_clarification_is_bound_issued_and_stops_without_quality_transition(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    llm = ScriptedLlm(
        [
            tool_result("submit_acceptance", valid_acceptance_payload()),
            tool_result("submit_clarification", _clarification_payload()),
            text_stop("requirements cannot revise"),
            text_stop("requirements still cannot revise"),
        ]
    )

    result = run_team(llm, workspace, runtime, "task-1", "implement VALUE")

    assert result.outcome == "failed"
    assert result.stopped_reason == "role_incomplete"
    assert [ticket["kind"] for ticket in result.tickets] == ["acceptance", "clarification"]
    clarification = result.tickets[-1]
    assert clarification["parent_hash"] == result.tickets[0]["content_hash"]
    assert clarification["bindings"] == {
        "code_tree_hash": workspace.tree_hash(),
        "files": [],
    }
    assert result.transitions == ["requirements->engineering", "engineering->requirements"]


def test_defect_is_bound_to_fresh_quality_evidence_and_stops(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    llm = ScriptedLlm(
        [
            tool_result("submit_acceptance", valid_acceptance_payload()),
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
                    call("submit_defect", _defect_payload()),
                ]
            ),
            text_stop("engineering cannot fix"),
            text_stop("engineering still cannot fix"),
        ]
    )

    result = run_team(llm, workspace, runtime, "task-1", "implement VALUE")

    assert result.outcome == "failed"
    assert result.stopped_reason == "role_incomplete"
    assert [ticket["kind"] for ticket in result.tickets] == ["acceptance", "delivery", "defect"]
    defect = result.tickets[-1]
    assert defect["parent_hash"] == result.tickets[1]["content_hash"]
    assert [check["name"] for check in defect["bindings"]["checks"]] == ["public_tests"]


def test_defect_without_fresh_quality_check_is_rejected_for_correction(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    llm = ScriptedLlm(
        [
            tool_result("submit_acceptance", valid_acceptance_payload()),
            multi_tool_result(
                [
                    call("write_file", {"path": "answer.py", "content": "VALUE = 42\n"}),
                    call("run_check", {"name": "public_tests"}),
                    call("submit_delivery", valid_delivery_payload()),
                ]
            ),
            tool_result("submit_defect", _defect_payload()),
            text_stop("quality cannot substantiate defect"),
            text_stop("quality still cannot substantiate defect"),
        ]
    )

    result = run_team(llm, workspace, runtime, "task-1", "implement VALUE")

    assert result.stopped_reason == "role_incomplete"
    assert [ticket["kind"] for ticket in result.tickets] == ["acceptance", "delivery"]
    assert "missing current activation receipt" in str(result.sessions["quality"].messages)


def test_transition_callback_failure_preserves_issued_ticket_and_transition(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    llm = ScriptedLlm([tool_result("submit_acceptance", valid_acceptance_payload())])

    secret = "SECRET_TRANSITION_CALLBACK"

    def fail_transition(event):
        if event["type"] == "team_transition":
            raise RuntimeError(secret)

    events = []
    result = run_team(
        llm, workspace, runtime, "task-1", "implement VALUE", on_event=fail_transition
    )

    assert result.outcome == "failed"
    assert result.stopped_reason == "system_error:transition_callback:RuntimeError"
    assert [ticket["kind"] for ticket in result.tickets] == ["acceptance"]
    assert result.transitions == ["requirements->engineering"]
    assert secret not in json.dumps([result, events], default=str)



def test_failed_activation_uses_client_accounting_and_event_tool_count(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)

    class AccountingThenErrorLlm(ScriptedLlm):
        def chat(self, messages, tools, max_completion_tokens=8000, accounting_role=None):
            if self._index == 1:
                self.calls_made += 1
                self.prompt_tokens_total += 7
                self.completion_tokens_total += 3
                self.reasoning_tokens_total += 1
                usage = self.usage_by_role.setdefault(
                    accounting_role,
                    {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                     "reasoning_tokens": 0, "llm_duration_ms": 0},
                )
                usage.update(
                    calls=usage["calls"] + 1,
                    prompt_tokens=usage["prompt_tokens"] + 7,
                    completion_tokens=usage["completion_tokens"] + 3,
                    reasoning_tokens=usage["reasoning_tokens"] + 1,
                    llm_duration_ms=usage["llm_duration_ms"] + 4,
                )
                self._index += 1
                raise RuntimeError("chat boundary failed")
            return super().chat(
                messages,
                tools,
                max_completion_tokens=max_completion_tokens,
                accounting_role=accounting_role,
            )

    llm = AccountingThenErrorLlm(
        [
            multi_tool_result(
                [
                    call("run_check", {"name": "public_tests"}),
                    call("submit_acceptance", valid_acceptance_payload()),
                ]
            ),
            RuntimeError("unused"),
        ]
    )

    result = run_team(llm, workspace, runtime, "task-1", "implement VALUE")

    assert result.stopped_reason == "system_error:engineering_activation:RuntimeError"
    assert result.calls == 2
    assert result.prompt_tokens == 17
    assert result.completion_tokens == 8
    assert result.reasoning_tokens == 3
    assert result.duration_ms == 5
    assert result.tool_invocations == 2
    assert result.per_role["requirements"]["calls"] == 1
    assert result.per_role["engineering"]["calls"] == 1


def test_quality_can_correct_missing_evidence_with_new_receipt_same_activation(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    llm = ScriptedLlm(
        [
            tool_result("submit_acceptance", valid_acceptance_payload()),
            multi_tool_result(
                [
                    call("write_file", {"path": "answer.py", "content": "VALUE = 42\n"}),
                    call("run_check", {"name": "public_tests"}),
                    call("submit_delivery", valid_delivery_payload()),
                ]
            ),
            tool_result("submit_release", valid_release_payload()),
            multi_tool_result(
                [
                    call("run_check", {"name": "public_tests"}),
                    call("submit_release", valid_release_payload()),
                ]
            ),
        ]
    )

    result = run_team(llm, workspace, runtime, "task-1", "implement VALUE")

    assert result.outcome == "done"
    assert result.stopped_reason == "done"
    assert runtime.check_sequence == 2


def _empty_delivery_payload():
    payload = valid_delivery_payload()
    payload["changed_files"] = []
    payload["requirement_mapping"][0]["files"] = []
    return payload


def _release_with_defects(*ticket_ids):
    payload = valid_release_payload()
    payload["closed_defects"] = list(ticket_ids)
    return payload


def _delivery_calls(content, payload=None):
    return multi_tool_result(
        [
            call("write_file", {"path": "answer.py", "content": content}),
            call("run_check", {"name": "public_tests"}),
            call("submit_delivery", payload or valid_delivery_payload()),
        ]
    )


def _quality_defect(route="engineering"):
    payload = _defect_payload()
    payload["route"] = route
    return multi_tool_result(
        [
            call("run_check", {"name": "public_tests"}),
            call("submit_defect", payload),
        ]
    )


def _quality_release(*ticket_ids):
    return multi_tool_result(
        [
            call("run_check", {"name": "public_tests"}),
            call("submit_release", _release_with_defects(*ticket_ids)),
        ]
    )


def test_clarification_routes_through_revision_two_acceptance(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    revised = valid_acceptance_payload()
    revised["clarification_responses"] = ["Use forty-two."]
    llm = ScriptedLlm(
        [
            tool_result("submit_acceptance", valid_acceptance_payload()),
            tool_result("submit_clarification", _clarification_payload()),
            tool_result("submit_acceptance", revised),
            _delivery_calls("VALUE = 42\n"),
            _quality_release(),
        ]
    )

    result = run_team(llm, workspace, runtime, "task-1", "implement VALUE")

    assert result.outcome == "done"
    assert [ticket["kind"] for ticket in result.tickets] == [
        "acceptance", "clarification", "acceptance", "delivery", "release"
    ]
    assert result.tickets[2]["revision"] == 2
    assert result.tickets[2]["parent_hash"] == result.tickets[1]["content_hash"]
    assert result.tickets[3]["parent_hash"] == result.tickets[2]["content_hash"]
    assert result.transitions == [
        "requirements->engineering", "engineering->requirements",
        "requirements->engineering", "engineering->quality", "quality->done",
    ]


def test_engineering_defect_routes_back_and_release_closes_open_ticket(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    llm = ScriptedLlm(
        [
            tool_result("submit_acceptance", valid_acceptance_payload()),
            _delivery_calls("VALUE = 42\n"),
            _quality_defect(),
            _delivery_calls("VALUE = 42\n# fixed\n"),
            _quality_release("D-0001"),
        ]
    )

    result = run_team(llm, workspace, runtime, "task-1", "implement VALUE")

    assert result.outcome == "done"
    assert result.reworks == 1
    defect, delivery = result.tickets[2:4]
    assert delivery["parent_hash"] == defect["content_hash"]
    assert result.tickets[-1]["payload"]["closed_defects"] == ["D-0001"]
    assert "quality->engineering" in result.transitions


def test_requirements_defect_routes_through_new_acceptance(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    revised = valid_acceptance_payload()
    revised["summary"] = "revised VALUE behavior"
    llm = ScriptedLlm(
        [
            tool_result("submit_acceptance", valid_acceptance_payload()),
            _delivery_calls("VALUE = 42\n"),
            _quality_defect("requirements"),
            tool_result("submit_acceptance", revised),
            _delivery_calls("VALUE = 42\n# revised\n"),
            _quality_release("D-0001"),
        ]
    )

    result = run_team(llm, workspace, runtime, "task-1", "implement VALUE")

    assert result.outcome == "done"
    defect, acceptance, delivery = result.tickets[2:5]
    assert acceptance["parent_hash"] == defect["content_hash"]
    assert delivery["parent_hash"] == acceptance["content_hash"]
    assert result.transitions[2:4] == ["quality->requirements", "requirements->engineering"]


def test_natural_stop_gets_one_correction_activation_in_same_session(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    llm = ScriptedLlm(
        [
            text_stop("forgot the ticket"),
            tool_result("submit_acceptance", valid_acceptance_payload()),
            text_stop("cannot implement"),
            text_stop("still cannot implement"),
        ]
    )

    result = run_team(llm, workspace, runtime, "task-1", "implement VALUE")

    assert result.stopped_reason == "role_incomplete"
    assert result.sessions["requirements"].activates == 2
    assert result.sessions["engineering"].activates == 2
    correction = next(
        message["content"] for message in result.sessions["requirements"].messages
        if message["role"] == "user" and "expected_allowed_terminal" in message["content"]
    )
    assert "requirements" in correction and "submit_acceptance" in correction
    assert "forgot the ticket" not in correction


def test_qa_write_attempt_is_unavailable_and_workspace_stays_on_delivery(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    llm = ScriptedLlm(
        [
            tool_result("submit_acceptance", valid_acceptance_payload()),
            _delivery_calls("VALUE = 42\n"),
            multi_tool_result(
                [
                    call("write_file", {"path": "answer.py", "content": "VALUE = 0\n"}),
                    call("run_check", {"name": "public_tests"}),
                    call("submit_release", valid_release_payload()),
                ]
            ),
        ]
    )

    result = run_team(llm, workspace, runtime, "task-1", "implement VALUE")

    assert result.outcome == "done"
    assert runtime.read_file("answer.py") == "VALUE = 42\n"
    assert "tool not available in this stage: write_file" in str(result.sessions["quality"].messages)


def test_repeated_defect_identity_stalls_before_second_route(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    llm = ScriptedLlm(
        [
            tool_result("submit_acceptance", valid_acceptance_payload()),
            _delivery_calls("VALUE = 42\n"),
            _quality_defect(),
            multi_tool_result(
                [call("run_check", {"name": "public_tests"}),
                 call("submit_delivery", _empty_delivery_payload())]
            ),
            _quality_defect(),
        ]
    )

    result = run_team(llm, workspace, runtime, "task-1", "implement VALUE")

    assert result.stopped_reason == "stalled"
    assert result.reworks == 2
    assert result.transitions[-1] == "engineering->quality"


def test_second_consecutive_empty_delivery_stalls_without_quality_transition(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    runtime.write_file("answer.py", "VALUE = 42\n")
    second_defect = _defect_payload()
    second_defect["defects"][0]["actual"] = "a different failure"
    llm = ScriptedLlm(
        [
            tool_result("submit_acceptance", valid_acceptance_payload()),
            multi_tool_result([call("run_check", {"name": "public_tests"}),
                               call("submit_delivery", _empty_delivery_payload())]),
            multi_tool_result([call("run_check", {"name": "public_tests"}),
                               call("submit_defect", second_defect)]),
            multi_tool_result([call("run_check", {"name": "public_tests"}),
                               call("submit_delivery", _empty_delivery_payload())]),
        ]
    )

    result = run_team(llm, workspace, runtime, "task-1", "implement VALUE")
    assert result.stopped_reason == "stalled"
    assert [ticket["kind"] for ticket in result.tickets][-1] == "delivery"
    assert result.transitions[-1] == "quality->engineering"


def test_ninth_defect_hits_max_reworks_without_routing(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    script = [tool_result("submit_acceptance", valid_acceptance_payload()),
              _delivery_calls("VALUE = 42\n")]
    for index in range(1, 10):
        defect = _defect_payload()
        defect["defects"][0]["actual"] = f"failure {index}"
        script.append(multi_tool_result([call("run_check", {"name": "public_tests"}),
                                         call("submit_defect", defect)]))
        if index < 9:
            script.append(_delivery_calls(f"VALUE = 42\n# fix {index}\n"))
    result = run_team(ScriptedLlm(script), workspace, runtime, "task-1", "implement VALUE")

    assert result.stopped_reason == "max_reworks"
    assert result.reworks == 9
    assert [ticket["kind"] for ticket in result.tickets].count("defect") == 9
    assert result.transitions.count("quality->engineering") == 8


def test_team_events_and_per_role_metrics_include_every_activation(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    events = []
    llm = ScriptedLlm([
        text_stop("retry"), tool_result("submit_acceptance", valid_acceptance_payload()),
        _delivery_calls("VALUE = 42\n"), _quality_release(),
    ])

    result = run_team(llm, workspace, runtime, "task-1", "implement VALUE", on_event=events.append)

    assert result.outcome == "done"
    assert sum(role["calls"] for role in result.per_role.values()) == result.calls
    assert sum(event["type"] == "llm_call" for event in events) == result.calls
    assert sum(event["type"] == "role_activation" for event in events) == 4
    assert all({"activates", "message_count", "message_chars", "duration_ms"} <= set(metric)
               for metric in result.per_role.values())
    assert events[-1] == {"type": "team_stop", "reason": "done", "outcome": "done"}
    assert all(not ({"text", "args", "output", "messages", "payload"} & set(event)) for event in events)


def test_noncorrectable_stop_reasons_propagate_without_reactivation(tmp_path):
    for reason in (
        "provider_blocked", "provider_unavailable", "context_overflow",
        "budget_exhausted", "budget_accounting_error", "output_truncated", "max_steps",
    ):
        workspace, runtime = make_runtime_with_public_check(tmp_path / reason)
        stopped = text_stop("")
        stopped.stopped_reason = reason
        result = run_team(ScriptedLlm([stopped]), workspace, runtime, "task-1", "implement VALUE")
        assert result.stopped_reason == reason
        assert result.sessions["requirements"].activates == 1


def test_release_rejections_keep_quality_active_until_exact_current_evidence(tmp_path):
    workspace, runtime = make_runtime_with_public_check(tmp_path)
    wrong_requirements = valid_release_payload()
    wrong_requirements["verified_requirements"] = ["R-001"]
    llm = ScriptedLlm(
        [
            tool_result("submit_acceptance", valid_acceptance_payload()),
            _delivery_calls("VALUE = 42\n"),
            _quality_defect(),
            _delivery_calls("VALUE = 42\n# fixed\n"),
            multi_tool_result(
                [
                    call("run_check", {"name": "public_tests"}),
                    call("submit_release", wrong_requirements),
                    call("submit_release", valid_release_payload()),
                    call("submit_release", _release_with_defects("D-0001")),
                ]
            ),
        ]
    )

    result = run_team(llm, workspace, runtime, "task-1", "implement VALUE")

    assert result.outcome == "done"
    history = str(result.sessions["quality"].messages)
    assert "verified_requirements must exactly cover acceptance ids" in history
    assert "closed_defects must exactly cover open defect ids" in history
    assert result.sessions["quality"].activates == 2