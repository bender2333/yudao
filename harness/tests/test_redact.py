# 动作参数里的命令按 ADR-0038 只留凭据的名称（工单 #658）：事件与动作列表里没有密钥原文。
# 工单 #1659：运行命令的那一句话与命令原文是同一条规则——显示的是凭据的名称，事件里没有原文。

from harness.models import EventType, json_dumps
from harness.providers.call import ModelResponse
from harness.redact import call_arguments, redact_tool_args
from harness.tests.helpers import run_scripted

SECRET = "sk-secret-value-123456"
SENTENCE = f"用 {SECRET} 取回数据"


def _bash_call(request, command: str, *, intent: str | None = None) -> ModelResponse:
    identity = f"bash-{request.activation_id}-{request.step_id}"
    arguments = {"command": command} if intent is None else {"command": command, "intent": intent}
    return ModelResponse(output=[{"id": identity, "call_id": identity, "type": "function_call", "name": "bash",
                                  "arguments": json_dumps(arguments)}])


def test_arguments_without_a_command_are_unchanged():
    assert redact_tool_args({"path": "src/echo.py"}) == {"path": "src/echo.py"}
    assert redact_tool_args({}) == {}


def test_the_one_sentence_is_redacted_like_the_command(monkeypatch):
    # 工单 #1659：同一规则管命令原文与那句话
    monkeypatch.setenv("YUDAO_TEST_API_KEY", SECRET)
    args = redact_tool_args({"command": f"echo {SECRET}", "intent": f"用 {SECRET} 取回数据"})
    for value in args.values():
        assert SECRET not in value
        assert "${YUDAO_TEST_API_KEY}" in value


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


def test_the_recorded_one_sentence_keeps_the_credential_name(data_dir, monkeypatch):
    # 工单 #1659 验收第 5 条：一句话带已知凭据时显示凭据的名称，事件里没有原文
    monkeypatch.setenv("YUDAO_TEST_API_KEY", SECRET)
    system, projection = run_scripted(
        data_dir, [lambda request: _bash_call(request, "echo ready", intent=SENTENCE)])
    try:
        events = [event for event in system.store.list_events(projection.run_id)
                  if event.type == EventType.TOOL_STARTED]
        assert events
        written = json_dumps(events[0].payload["args"])
        assert SECRET not in written
        assert "${YUDAO_TEST_API_KEY}" in events[0].payload["args"]["intent"]
    finally:
        system.close()


def test_the_recorded_arguments_leave_out_the_one_sentence():
    # 工单 #1659：只被记录的那一项不进「同样的参数」比较，也不交给执行环境
    assert call_arguments({"command": "ls", "intent": "看目录"}) == {"command": "ls"}
    assert call_arguments({"path": "src/a.py"}) == {"path": "src/a.py"}
    assert call_arguments(None) is None
