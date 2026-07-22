"""Contract tests for private, persistent role sessions."""

import inspect
import json
from dataclasses import FrozenInstanceError, fields

import pytest

from harness.llm import ProviderUnavailable
from harness.role_session import RoleSession
from harness.tests.fakes import ScriptedLlm, text_stop, tool_result


def _tool(name="finish"):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "test tool",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def test_role_session_has_fixed_fields_and_initial_system_message():
    session = RoleSession("engineering", "engineering system", [])

    assert [field.name for field in fields(RoleSession)] == [
        "role",
        "system",
        "tools",
        "messages",
        "activates",
    ]
    assert RoleSession.__dataclass_fields__["messages"].init is False
    assert session.messages == [{"role": "system", "content": "engineering system"}]
    assert session.activates == 0
    assert "keep_history" not in inspect.signature(session.activate).parameters
    assert "messages" not in inspect.signature(RoleSession).parameters


def test_role_session_constructor_and_field_bindings_are_frozen():
    first = RoleSession("requirements", "requirements system", [])
    second = RoleSession("engineering", "engineering system", [])

    assert list(inspect.signature(RoleSession).parameters) == ["role", "system", "tools"]
    for name, value in [
        ("role", "engineering"),
        ("system", "replacement"),
        ("tools", []),
        ("messages", second.messages),
        ("activates", 1),
    ]:
        with pytest.raises((FrozenInstanceError, AttributeError)):
            setattr(first, name, value)

    first.messages.append({"role": "assistant", "content": "PRIVATE_R"})
    assert first.messages is not second.messages
    assert "PRIVATE_R" not in json.dumps(second.messages)

@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("", "system", []), "role"),
        (("   ", "system", []), "role"),
        ((1, "system", []), "role"),
        (("role", "", []), "system"),
        (("role", "  ", []), "system"),
        (("role", 1, []), "system"),
        (("role", "system", ()), "tools"),
        (("role", "system", None), "tools"),
    ],
)
def test_role_session_rejects_invalid_constructor_values(args, message):
    with pytest.raises((TypeError, ValueError), match=message):
        RoleSession(*args)


def test_role_session_reentry_keeps_private_history_and_accounts_by_role(tmp_path):
    session = RoleSession("engineering", "engineering system", [])
    llm = ScriptedLlm([text_stop("first"), text_stop("second")])

    first = session.activate("handoff one", llm=llm, handlers_ctx=str(tmp_path))
    first_len = len(session.messages)
    second = session.activate("handoff two", llm=llm, handlers_ctx=str(tmp_path))

    assert first.stopped_reason == second.stopped_reason == "natural"
    assert first.calls == second.calls == 1
    assert first.prompt_tokens == second.prompt_tokens == 10
    assert len(session.messages) > first_len
    assert [message for message in session.messages if message["role"] == "user"] == [
        {"role": "user", "content": "handoff one"},
        {"role": "user", "content": "handoff two"},
    ]
    assert sum(message["role"] == "system" for message in session.messages) == 1
    assert "first" in json.dumps(llm.message_snapshots[1])
    assert session.activates == 2
    assert llm.usage_by_role["engineering"] == {
        "calls": 2,
        "prompt_tokens": 20,
        "completion_tokens": 10,
        "reasoning_tokens": 4,
        "llm_duration_ms": 2,
    }


def test_role_sessions_never_share_messages_or_tools():
    source_tools = [_tool()]
    requirements = RoleSession("requirements", "r", source_tools)
    engineering = RoleSession("engineering", "e", source_tools)

    requirements.messages.append({"role": "assistant", "content": "PRIVATE_R"})
    requirements.tools[0]["function"]["name"] = "requirements_only"

    assert "PRIVATE_R" not in json.dumps(engineering.messages)
    assert requirements.messages is not engineering.messages
    assert requirements.tools is not engineering.tools
    assert engineering.tools[0]["function"]["name"] == "finish"


def test_constructor_copies_tools_and_scripted_llm_only_snapshots_them(tmp_path):
    source_tools = [_tool()]
    session = RoleSession("engineering", "system", source_tools)
    source_tools[0]["function"]["name"] = "changed_outside"
    llm = ScriptedLlm([text_stop("done")])

    session.activate("handoff", llm=llm, handlers_ctx=str(tmp_path))
    llm.tool_snapshots[0][0]["function"]["name"] = "changed_in_fake"

    assert session.tools[0]["function"]["name"] == "finish"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"user_turn": ""}, "user_turn"),
        ({"user_turn": "  "}, "user_turn"),
        ({"user_turn": 1}, "user_turn"),
        ({"handlers_ctx": 1}, "handlers_ctx"),
        ({"max_steps": 0}, "max_steps"),
        ({"max_steps": -1}, "max_steps"),
        ({"max_steps": True}, "max_steps"),
        ({"max_steps": 1.0}, "max_steps"),
    ],
)
def test_invalid_activate_arguments_do_not_increment_activates(tmp_path, kwargs, message):
    session = RoleSession("engineering", "system", [])
    arguments = {
        "user_turn": "handoff",
        "llm": ScriptedLlm([text_stop("unused")]),
        "handlers_ctx": str(tmp_path),
    }
    arguments.update(kwargs)

    with pytest.raises((TypeError, ValueError), match=message):
        session.activate(**arguments)

    assert session.activates == 0
    assert session.messages == [{"role": "system", "content": "system"}]


def test_provider_stop_counts_activation_and_preserves_history_for_reentry(tmp_path):
    session = RoleSession("engineering", "system", [])
    llm = ScriptedLlm([text_stop("first"), ProviderUnavailable("offline")])

    first = session.activate("handoff one", llm=llm, handlers_ctx=str(tmp_path))
    second = session.activate("handoff two", llm=llm, handlers_ctx=str(tmp_path))

    assert first.stopped_reason == "natural"
    assert second.stopped_reason == "provider_unavailable"
    assert session.activates == 2
    assert "first" in json.dumps(session.messages)
    assert session.messages[-1] == {"role": "user", "content": "handoff two"}
    assert "first" in json.dumps(llm.message_snapshots[1])


def test_terminal_tools_and_extra_handlers_are_forwarded_to_same_loop(tmp_path):
    session = RoleSession("engineering", "system", [_tool()])
    llm = ScriptedLlm([tool_result("finish", {})])
    contexts = []

    result = session.activate(
        "handoff",
        llm=llm,
        handlers_ctx=str(tmp_path),
        terminal_tools={"finish"},
        extra_handlers={"finish": lambda: contexts.append(str(tmp_path)) or "accepted"},
    )

    assert result.stopped_reason == "terminal"
    assert result.terminal_call == {"name": "finish", "args": {}}
    assert contexts == [str(tmp_path)]
    assert session.messages[-1] == {
        "role": "tool",
        "tool_call_id": llm.tool_snapshots[0] and llm._script[0].tool_calls[0].id,
        "content": "accepted",
    }
