# Chat Completions 与 Messages 协议历史的翻译规则：系统提示合并、role 交替、连续回合合并、推理内容位置与空文本处理。
# 这些结论由历史翻译函数直接得出，登记为单元层。

from harness.models import json_dumps
from harness.providers.chat import _chat_messages
from harness.providers.invoke import ProviderInput, ProviderMessage, ToolImage, ToolResult
from harness.providers.messages import _messages_input


def test_messages_history_merges_consecutive_turns_into_alternating_roles():
    # Anthropic Messages 要求 role 交替，且每个 tool_result 紧跟对应的 tool_use 所在消息：
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


def test_chat_messages_translates_developer_material_and_preserves_tool_and_reasoning_order():
    # 保护 R3：单条 developer 常驻材料加 user 与工具往返时，系统提示置于 messages[0]，工具调用、结果图像与推理内容位置保持不变
    items = [
        {"role": "developer", "content": "[intend]\n实现回声命令"},
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "开始执行"}]},
        {"type": "reasoning", "reasoning_content": "先查看目录"},
        {"type": "function_call", "call_id": "call-1", "name": "list_files", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "call-1", "output": [
            {"type": "input_text", "text": "main.py"},
            {"type": "input_image", "image_url": "data:image/png;base64,QUJD"},
        ]},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "已完成查看"}]},
    ]
    messages = _chat_messages(ProviderInput(raw_request={"input": items, "tools": []}, max_output_tokens=1024))
    assert messages[0] == {"role": "system", "content": "[intend]\n实现回声命令"}
    assert [message["role"] for message in messages] == ["system", "user", "assistant", "tool", "user", "assistant"]
    assert all(message["role"] != "developer" for message in messages)
    assert messages[1] == {"role": "user", "content": "开始执行"}
    assert messages[2]["reasoning_content"] == "先查看目录"
    assert [call["id"] for call in messages[2]["tool_calls"]] == ["call-1"]
    assert messages[3] == {"role": "tool", "tool_call_id": "call-1", "content": "main.py"}
    assert messages[4]["content"][0] == {"type": "text", "text": "工具调用 call-1 的结果图像"}
    assert messages[5] == {"role": "assistant", "content": "已完成查看"}

    # 保护 R3：遇到 developer 或 system 消息前先冲刷挂起的工具调用并清空未伴随 assistant 的推理内容
    interleaved = [
        {"type": "function_call", "call_id": "call-a", "name": "read_file", "arguments": '{"path":"a.py"}'},
        {"role": "developer", "content": "第一段指令"},
        {"type": "function_call_output", "call_id": "call-a", "output": "print(1)"},
        {"type": "reasoning", "reasoning_content": "孤立推理内容"},
        {"role": "system", "content": "第二段指令"},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "继续处理"}]},
    ]
    merged = _chat_messages(ProviderInput(raw_request={"input": interleaved, "tools": []}, max_output_tokens=1024))
    assert merged == [
        {"role": "system", "content": "第一段指令\n第二段指令"},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call-a", "type": "function",
            "function": {"name": "read_file", "arguments": '{"path":"a.py"}'},
        }]},
        {"role": "tool", "tool_call_id": "call-a", "content": "print(1)"},
        {"role": "assistant", "content": "继续处理"},
    ]


def test_chat_messages_merges_compaction_developer_pair_and_fallback_messages():
    # 保护 R3：整理请求形状（两条相邻 developer 消息后接一条 user 历史切片）与回退分支均合并为开头单条 system 消息
    compaction_items = [
        {"role": "developer", "content": "整理规则"},
        {"role": "developer", "content": "[intend]\n常驻材料"},
        {"role": "user", "content": '{"previous_summary":null,"source_fragments":[]}'},
    ]
    compaction_messages = _chat_messages(ProviderInput(
        raw_request={"input": compaction_items, "tools": []}, max_output_tokens=2048))
    assert compaction_messages == [
        {"role": "system", "content": "整理规则\n[intend]\n常驻材料"},
        {"role": "user", "content": '{"previous_summary":null,"source_fragments":[]}'},
    ]

    fallback_messages = _chat_messages(ProviderInput(
        messages=(
            ProviderMessage(role="system", content="系统规则"),
            ProviderMessage(role="developer", content="常驻材料"),
            ProviderMessage(role="user", content="历史切片", name="requester"),
        ),
        tool_results=(
            ToolResult(
                call_id="call-1", name="read_file", output="ok",
                images=(ToolImage(media_type="image/png", data="QUJD"),),
            ),
        ),
        max_output_tokens=2048,
    ))
    assert fallback_messages[0] == {"role": "system", "content": "系统规则\n常驻材料"}
    assert [message["role"] for message in fallback_messages] == ["system", "user", "tool", "user"]
    assert fallback_messages[1] == {"role": "user", "content": "历史切片", "name": "requester"}
    assert fallback_messages[2] == {"role": "tool", "tool_call_id": "call-1", "content": "ok"}


def test_chat_messages_skips_empty_system_and_developer_texts():
    # 保护 R3：空的 system 与 developer 文本在两个分支中均不产生空 system 消息，也不留下多余换行
    raw_only_empty = _chat_messages(ProviderInput(
        raw_request={"input": [
            {"role": "system", "content": ""},
            {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": ""}]},
            {"role": "user", "content": "hi"},
        ], "tools": []},
        max_output_tokens=512,
    ))
    assert raw_only_empty == [{"role": "user", "content": "hi"}]

    raw_mixed = _chat_messages(ProviderInput(
        raw_request={"input": [
            {"role": "developer", "content": ""},
            {"role": "developer", "content": "整理规则"},
            {"role": "system", "content": ""},
            {"role": "developer", "content": "常驻材料"},
            {"role": "user", "content": "切片"},
        ], "tools": []},
        max_output_tokens=512,
    ))
    assert raw_mixed == [
        {"role": "system", "content": "整理规则\n常驻材料"},
        {"role": "user", "content": "切片"},
    ]

    fallback_empty = _chat_messages(ProviderInput(
        messages=(
            ProviderMessage(role="system", content=""),
            ProviderMessage(role="developer", content=""),
            ProviderMessage(role="user", content="hi"),
        ),
        max_output_tokens=512,
    ))
    assert fallback_empty == [{"role": "user", "content": "hi"}]
    assert _chat_messages(ProviderInput(messages=(ProviderMessage(role="developer", content=""),))) == []
