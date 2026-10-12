# Messages 协议历史的翻译规则：role 交替、连续回合合并、thinking 的位置、空文本块的丢弃。
# 这些结论由历史翻译函数直接得出，登记为单元层。

from harness.models import json_dumps
from harness.providers.invoke import ProviderInput, ProviderMessage
from harness.providers.messages import _messages_input


def test_messages_history_merges_consecutive_turns_into_alternating_roles():
    # Anthropic Messages 要求 role 交替，且每个 tool_result 紧跟对应的 tool_use 所在消息（设计说明第 7.6 节）：
    # 历史里连续的工具调用合并成一条 assistant 消息（多个 tool_use），连续的工具结果合并成一条 user 消息
    # （多个 tool_result）。分两轮工具调用的部门历史按这个形状翻译，真实上游才接受
    items = [
        {"type": "message", "role": "user", "content": "go"},
        {"type": "message", "role": "assistant", "content": "先查看代码。"},
        {"type": "function_call", "call_id": "t1", "name": "list_files", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "t1", "output": "a.py"},
        {"type": "function_call", "call_id": "t2", "name": "read_file",
         "arguments": json_dumps({"path": "a.py"})},
        {"type": "function_call_output", "call_id": "t2", "output": "print(1)"},
    ]
    _system, messages = _messages_input(ProviderInput(raw_request={"input": items, "tools": []},
                                                      max_output_tokens=2048))
    # role 严格交替
    roles = [message["role"] for message in messages]
    assert roles == ["user", "assistant", "user", "assistant", "user"]
    # 文本与第一个工具调用属于同一个 assistant 回合
    first_assistant = messages[1]["content"]
    assert first_assistant[0] == {"type": "text", "text": "先查看代码。"}
    assert first_assistant[1]["type"] == "tool_use" and first_assistant[1]["id"] == "t1"
    # 每个 tool_result 紧跟它对应的 tool_use 所在消息
    assert messages[2]["content"] == [{"type": "tool_result", "tool_use_id": "t1", "content": "a.py"}]
    assert messages[4]["content"] == [{"type": "tool_result", "tool_use_id": "t2", "content": "print(1)"}]


def test_messages_history_places_thinking_before_text_and_tool_use():
    # assistant 回合里 thinking 块在文本与工具调用之前，与上游返回的顺序一致：
    # 历史里的推理条目在文本消息之前，合并进同一个 assistant 回合时 thinking 仍排在最前
    items = [
        {"type": "message", "role": "user", "content": "go"},
        {"type": "reasoning", "call_id": "t1",
         "blocks": [{"type": "thinking", "thinking": "need read", "signature": "sig"}]},
        {"type": "message", "role": "assistant", "content": "I will read."},
        {"type": "function_call", "call_id": "t1", "name": "read_file",
         "arguments": json_dumps({"path": "a.py"})},
        {"type": "function_call_output", "call_id": "t1", "output": "print(1)"},
    ]
    _system, messages = _messages_input(ProviderInput(raw_request={"input": items, "tools": []},
                                                      max_output_tokens=1024))
    assistant = messages[1]["content"]
    assert [block["type"] for block in assistant] == ["thinking", "text", "tool_use"]
    assert assistant[0]["signature"] == "sig"
    assert assistant[1]["text"] == "I will read."
    assert assistant[2]["id"] == "t1"


def test_messages_history_skips_empty_text_blocks():
    # 空的用户消息不产生块，也不单独占一条消息，避免 Anthropic 拒绝空文本块
    _system, messages = _messages_input(ProviderInput(
        messages=(ProviderMessage(role="user", content="a"), ProviderMessage(role="user", content="")),
        max_output_tokens=1024))
    assert messages == [{"role": "user", "content": "a"}]
