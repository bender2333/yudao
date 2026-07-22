"""Contract tests for private, persistent role sessions."""

import inspect
import json
from dataclasses import FrozenInstanceError, fields

import pytest

from harness.llm import ProviderUnavailable
from harness.role_session import RoleSession
from harness.tests.fakes import ScriptedLlm, text_stop, tool_result


def _tool(name="finish"):
    return {"type": "function", "function": {"name": name, "description": "test", "parameters": {"type": "object"}}}


def noop_dispatch(_name, _args):
    return "ok"


def test_role_session_has_fixed_fields_and_initial_system_message():
    session = RoleSession("engineering", "engineering system", [])
    assert [field.name for field in fields(RoleSession)] == ["role", "system", "tools", "messages", "activates"]
    assert session.messages == [{"role": "system", "content": "engineering system"}]
    assert session.activates == 0
    assert "dispatch_tool" in inspect.signature(session.activate).parameters
    assert "handlers_ctx" not in inspect.signature(session.activate).parameters
    assert "extra_handlers" not in inspect.signature(session.activate).parameters


def test_role_session_constructor_and_field_bindings_are_frozen():
    first = RoleSession("requirements", "requirements system", [])
    second = RoleSession("engineering", "engineering system", [])
    assert list(inspect.signature(RoleSession).parameters) == ["role", "system", "tools"]
    for name, value in [("role", "engineering"), ("system", "replacement"), ("tools", []), ("messages", second.messages), ("activates", 1)]:
        with pytest.raises((FrozenInstanceError, AttributeError)):
            setattr(first, name, value)


@pytest.mark.parametrize("args", [("", "system", []), ("role", "", []), ("role", "system", None)])
def test_role_session_rejects_invalid_constructor_values(args):
    with pytest.raises((TypeError, ValueError)):
        RoleSession(*args)


def test_reentry_keeps_private_history_and_accounts_by_role():
    session = RoleSession("engineering", "engineering system", [])
    llm = ScriptedLlm([text_stop("first"), text_stop("second")])
    first = session.activate("handoff one", llm=llm, dispatch_tool=noop_dispatch)
    second = session.activate("handoff two", llm=llm, dispatch_tool=noop_dispatch)
    assert first.stopped_reason == second.stopped_reason == "natural"
    assert [message for message in session.messages if message["role"] == "user"] == [
        {"role": "user", "content": "handoff one"},
        {"role": "user", "content": "handoff two"},
    ]
    assert sum(message["role"] == "system" for message in session.messages) == 1
    assert "first" in json.dumps(llm.message_snapshots[1])
    assert session.activates == 2


def test_constructor_copies_tools():
    source = [_tool()]
    session = RoleSession("engineering", "system", source)
    source[0]["function"]["name"] = "changed"
    assert session.tools[0]["function"]["name"] == "finish"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"user_turn": ""}, "user_turn"),
        ({"user_turn": 1}, "user_turn"),
        ({"dispatch_tool": None}, "dispatch_tool"),
        ({"max_steps": 0}, "max_steps"),
        ({"max_steps": True}, "max_steps"),
    ],
)
def test_invalid_activate_arguments_do_not_increment_activates(kwargs, message):
    session = RoleSession("engineering", "system", [])
    arguments = {"user_turn": "handoff", "llm": ScriptedLlm([text_stop("unused")]), "dispatch_tool": noop_dispatch}
    arguments.update(kwargs)
    with pytest.raises((TypeError, ValueError), match=message):
        session.activate(**arguments)
    assert session.activates == 0
    assert session.messages == [{"role": "system", "content": "system"}]


def test_provider_stop_counts_activation_and_preserves_history_for_reentry():
    session = RoleSession("engineering", "system", [])
    llm = ScriptedLlm([text_stop("first"), ProviderUnavailable("offline")])
    first = session.activate("handoff one", llm=llm, dispatch_tool=noop_dispatch)
    second = session.activate("handoff two", llm=llm, dispatch_tool=noop_dispatch)
    assert first.stopped_reason == "natural"
    assert second.stopped_reason == "provider_unavailable"
    assert session.activates == 2


def test_explicit_dispatcher_is_forwarded_to_same_loop():
    session = RoleSession("engineering", "system", [_tool()])
    llm = ScriptedLlm([tool_result("finish", {"marker": "x"})])
    calls = []

    def dispatch(name, args):
        calls.append((name, args))
        return "accepted"

    result = session.activate("handoff", llm=llm, dispatch_tool=dispatch, terminal_tools={"finish"})
    assert result.stopped_reason == "terminal"
    assert result.terminal_call == {"name": "finish", "args": {"marker": "x"}}
    assert calls == [("finish", {"marker": "x"})]
