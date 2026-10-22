# 动作参数里的命令按 ADR-0038 只留凭据的名称（工单 #658）：事件与动作列表里没有密钥原文。

from harness.models import EventType, json_dumps
from harness.providers.call import ModelResponse
from harness.redact import redact_tool_args
from harness.tests.helpers import run_scripted

SECRET = "sk-secret-value-123456"


def _bash_call(request, command: str) -> ModelResponse:
    identity = f"bash-{request.activation_id}-{request.step_id}"
    return ModelResponse(output=[{"id": identity, "call_id": identity, "type": "function_call", "name": "bash",
                                  "arguments": json_dumps({"command": command})}])


def test_the_command_keeps_the_credential_name_instead_of_its_value(monkeypatch):
    monkeypatch.setenv("YUDAO_TEST_API_KEY", SECRET)
    redacted = redact_tool_args({"command": f"curl -H 'key: {SECRET}'"})
    assert redacted == {"command": "curl -H 'key: ${YUDAO_TEST_API_KEY}'"}


def test_arguments_without_a_command_are_unchanged():
    assert redact_tool_args({"path": "src/echo.py"}) == {"path": "src/echo.py"}
    assert redact_tool_args({}) == {}


def test_the_recorded_action_keeps_the_credential_name(data_dir, monkeypatch):
    monkeypatch.setenv("YUDAO_TEST_API_KEY", SECRET)
    system, projection = run_scripted(data_dir, [lambda request: _bash_call(request, f"echo {SECRET}")])
    try:
        events = [event for event in system.store.list_events(projection.run_id)
                  if event.type == EventType.TOOL_STARTED]
        assert events
        command = events[0].payload["args"]["command"]
        assert SECRET not in command
        assert "${YUDAO_TEST_API_KEY}" in command
    finally:
        system.close()
