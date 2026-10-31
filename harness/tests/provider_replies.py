# 测试内启动的本机模型服务按请求顺序回放的流式回复脚本：三种协议各一份构造，加上在测试里
# 直接写出回复与断开连接的辅助。事件序列基准的场景、请求时限的测试与只回复文字的测试共用。

import json
from http.server import BaseHTTPRequestHandler
from typing import Any

from harness.models import json_dumps
from harness.path_rules import QA_TESTS_DIR
from harness.proposals import delivery, judgement, product_spec, review
from harness.tests.protocol_helpers import ScriptedProvider, send_reply, sse

# 检查命令一律写成 ["python", ...]，由主机解析解释器，基准中不出现本机路径
ECHO = "import sys\nprint(sys.argv[1])\n"


def _submission(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "kind"}


def _material_text(item: Any) -> str:
    # 三种协议的输入项形状不同：Responses 的 input 与 Chat 的 messages 用字符串正文，
    # Messages 协议把正文放在 content 块的 text 里
    content = item.get("content") if isinstance(item, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(block.get("text", "") for block in content if isinstance(block, dict))
    return ""


def _material_hash(body: dict[str, Any], source: str, field: str) -> str | None:
    # 从本机服务收到的请求里取出装配好的部门材料中的 content_hash（工单 #471）：
    # 服务回放的提交据此声明它依据的版本，与真实模型从上下文读到的一样
    items = body.get("input") or body.get("messages") or []
    material = "\n\n".join(_material_text(item) for item in items)
    for segment in ("\n\n" + material).split("\n\n[")[1:]:
        name, separator, text = segment.partition("]\n")
        if separator and name == source:
            return json.loads(text).get(field)
    return None


def request_department(body: dict[str, Any]) -> str:
    # 请求里带的工具给出提出请求的部门（工单 #557：同时运行的会话各自取用自己的脚本，
    # 不按请求的先后顺序分配）
    names: set[str] = set()
    for tool in body.get("tools") or []:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function")
        name = function.get("name") if isinstance(function, dict) else tool.get("name")
        if isinstance(name, str):
            names.add(name)
    if "submit_product_spec" in names:
        return "product"
    if "submit_delivery" in names:
        return "engineering"
    return "quality"


# 回复里的调用身份在各部门之间不重复（工单 #557）：同时运行的会话各自发请求，
# 身份重复会让控制核心把别人的工具开始当成本次已经开始
REPLY_INDEX_BASE = {"product": 0, "engineering": 100, "quality": 200}


def reply_index(department: str, counter: int) -> int:
    """这个部门的第几次请求对应的回复编号：各部门一段，编号互不重叠。"""
    return REPLY_INDEX_BASE[department] + counter


def http_script(body: dict[str, Any]) -> dict[str, list[list[tuple[str, dict[str, Any]]]]]:
    # 按部门给出的脚本（工单 #471、#557）：提交依据的版本取自本次请求装配好的部门材料，
    # 与真实模型从上下文读到的当前版本是同一个。
    # 同时运行以后质检有两段：PRD 被接纳以后还没有交付，质检先起草测试用例，
    # 交付到达以后质检核验并放行。
    spec_hash = _material_hash(body, "current_product_spec", "content_hash")
    delivery_hash = _material_hash(body, "current_delivery_spec", "content_hash")
    return {
        "product": [
            [("submit_product_spec", _submission(product_spec()))],
        ],
        "engineering": [
            [("write_file", {"path": "src/echo.py", "content": ECHO}),
             ("run_check", {"name": "smoke", "command": "python -c \"print('smoke ok')\""}),
             ("submit_delivery", _submission(delivery(check_names=["smoke"], basis_product_spec_hash=spec_hash)))],
        ],
        "quality": [
            [("write_file", {"path": f"{QA_TESTS_DIR}/test_echo.py",
                             "content": "import sys\nprint('QA_TEST_DRAFTED')\nsys.exit(0)\n"}),
             ("submit_review", _submission(review("release", "按 PRD 起草了测试用例；还没有交付可以核验")))],
            # 交付到达以后先交独立判断，再核验并放行（先判断后看解释的门，工单 #358）
            [("run_check", {"name": "smoke", "command": "python -c \"print('smoke ok')\""}),
             ("submit_independent_judgement",
              _submission(judgement(checks=["smoke"], basis_delivery_spec_hash=delivery_hash)))],
            [("run_check", {"name": "smoke", "command": "python -c \"print('smoke ok')\""}),
             ("submit_review", _submission(review("release", "checks passed on the current snapshot",
                                                  basis_delivery_spec_hash=delivery_hash)))],
        ],
    }


HTTP_SCRIPT: list[list[tuple[str, dict[str, Any]]]] = http_script({})["product"]


def _sse_event(kind: str, payload: dict[str, Any]) -> str:
    return f"event: {kind}\ndata: {json.dumps({'type': kind, **payload})}\n\n"


def responses_reply(index: int, calls: list[tuple[str, dict[str, Any]]], *, text: str = "",
                    reasoning: str = "", finish_reason: str = "") -> bytes:
    # 一条正常结束的 Responses 流式回复：可见输出项是回答文字与工具调用，推理条目单独成项
    output: list[dict[str, Any]] = []
    if reasoning:
        output.append({"id": f"item-{index}-reasoning", "type": "reasoning", "status": "completed",
                       "summary": [], "encrypted_content": f"CIPHER-{index}"})
    if text:
        output.append({"id": f"item-{index}-message", "type": "message", "role": "assistant",
                       "status": "completed",
                       "content": [{"type": "output_text", "text": text, "annotations": []}]})
    output.extend({"id": f"item-{index}-{number}", "type": "function_call", "status": "completed",
                   "call_id": f"call-{index}-{number}", "name": name, "arguments": json_dumps(arguments)}
                  for number, (name, arguments) in enumerate(calls, start=1))
    # 结束原因在 Responses 协议里写作 status 与 incomplete_details：给了原因即未到终态
    status = "completed" if not finish_reason else "incomplete"
    response = {"id": f"resp-{index}", "object": "response", "created_at": 1, "status": status,
                "model": "scenario-model-actual", "output": output, "error": None,
                "incomplete_details": None if not finish_reason else {"reason": finish_reason},
                "usage": {"input_tokens": 100 + index, "output_tokens": 10, "total_tokens": 110 + index,
                          "input_tokens_details": {"cached_tokens": 0},
                          "output_tokens_details": {"reasoning_tokens": 0}}}
    frames = [_sse_event("response.created", {"response": {**response, "status": "in_progress", "output": [],
                                                           "usage": None}, "sequence_number": 0})]
    for number, item in enumerate(output, start=1):
        frames.append(_sse_event("response.output_item.done",
                                 {"item": item, "output_index": number - 1, "sequence_number": number}))
    frames.append(_sse_event("response.completed", {"response": response, "sequence_number": len(frames)}))
    return sse(*frames)


def chat_reply(index: int, calls: list[tuple[str, dict[str, Any]]], *, text: str = "",
               reasoning: str = "", finish_reason: str = "") -> bytes:
    # 一条正常结束的 Chat Completions 流式回复：结束原因默认按有没有工具调用取 stop 或 tool_calls
    def chunk(payload: dict[str, Any]) -> str:
        return f"data: {json.dumps({'id': f'chat-{index}', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'scenario-model-actual', **payload})}\n\n"

    deltas: list[dict[str, Any]] = []
    if reasoning:
        deltas.append({"role": "assistant", "reasoning_content": reasoning})
    if text:
        deltas.append({"content": text})
    frames = [chunk({"choices": [{"index": 0, "delta": delta, "finish_reason": None}]}) for delta in deltas]
    frames.extend(chunk({"choices": [{"index": 0, "delta": {"tool_calls": [
        {"index": number, "id": f"call-{index}-{number}", "type": "function",
         "function": {"name": name, "arguments": json_dumps(arguments)}}]}, "finish_reason": None}]})
        for number, (name, arguments) in enumerate(calls))
    last = finish_reason or ("tool_calls" if calls else "stop")
    frames.append(chunk({"choices": [{"index": 0, "delta": {}, "finish_reason": last}]}))
    frames.append(chunk({"choices": [], "usage": {"prompt_tokens": 100 + index, "completion_tokens": 10,
                                                  "total_tokens": 110 + index}}))
    frames.append("data: [DONE]\n\n")
    return sse(*frames)


def messages_reply(index: int, calls: list[tuple[str, dict[str, Any]]], *, text: str = "",
                   reasoning: str = "", finish_reason: str = "") -> bytes:
    # 一条正常结束的 Messages 流式回复：thinking 与文字块排在工具块之前，工具块的身份与编号不变
    frames = [_sse_event("message_start", {"message": {
        "id": f"msg-{index}", "type": "message", "role": "assistant", "model": "scenario-model-actual",
        "content": [], "usage": {"input_tokens": 100 + index, "output_tokens": 1}}})]
    blocks = 0
    if reasoning:
        frames.extend([
            _sse_event("content_block_start", {"index": blocks, "content_block": {
                "type": "thinking", "thinking": ""}}),
            _sse_event("content_block_delta", {"index": blocks, "delta": {
                "type": "thinking_delta", "thinking": reasoning}}),
            _sse_event("content_block_stop", {"index": blocks}),
        ])
        blocks += 1
    if text:
        frames.extend([
            _sse_event("content_block_start", {"index": blocks, "content_block": {
                "type": "text", "text": ""}}),
            _sse_event("content_block_delta", {"index": blocks, "delta": {
                "type": "text_delta", "text": text}}),
            _sse_event("content_block_stop", {"index": blocks}),
        ])
        blocks += 1
    for number, (name, arguments) in enumerate(calls):
        frames.extend([
            _sse_event("content_block_start", {"index": blocks + number, "content_block": {
                "type": "tool_use", "id": f"toolu-{index}-{number}", "name": name, "input": {}}}),
            _sse_event("content_block_delta", {"index": blocks + number, "delta": {
                "type": "input_json_delta", "partial_json": json_dumps(arguments)}}),
            _sse_event("content_block_stop", {"index": blocks + number}),
        ])
    stop_reason = finish_reason or ("tool_use" if calls else "end_turn")
    frames.append(_sse_event("message_delta", {"delta": {"stop_reason": stop_reason},
                                               "usage": {"output_tokens": 10}}))
    frames.append(_sse_event("message_stop", {}))
    return sse(*frames)


HTTP_REPLIES = {"responses": responses_reply, "chat_completions": chat_reply, "messages": messages_reply}

# 空输出的结束原因：三种协议各按自己协议里的写法给出，值本身要能在诊断里看到
EMPTY_FINISH_REASONS = {"responses": "", "chat_completions": "length", "messages": "max_tokens"}


def empty_reply(protocol: str, *, reasoning: str = ""):
    # 流正常结束、没有任何可见输出项（没有文字、没有工具调用）；只有推理内容时同样属于这一类（工单 #305）
    def reply(_provider: ScriptedProvider, handler: BaseHTTPRequestHandler) -> None:
        body = HTTP_REPLIES[protocol](1, [], text="", reasoning=reasoning,
                                      finish_reason=EMPTY_FINISH_REASONS[protocol])
        send_reply(handler, 200, "text/event-stream", body)

    return reply


def product_spec_reply(protocol: str):
    # 产品部门提交规格的完整流式回复
    def reply(_provider: ScriptedProvider, handler: BaseHTTPRequestHandler) -> None:
        send_reply(handler, 200, "text/event-stream", HTTP_REPLIES[protocol](1, HTTP_SCRIPT[0]))

    return reply


def http_error(status: int, code: str, *headers: tuple[str, str]):
    def reply(_provider: ScriptedProvider, handler: BaseHTTPRequestHandler) -> None:
        body = json.dumps({"error": {"code": code, "type": "server_error", "message": "scenario failure"}})
        send_reply(handler, status, "application/json", body.encode("utf-8"), headers=headers)

    return reply


def messages_credential_rejected(_provider: ScriptedProvider, handler: BaseHTTPRequestHandler) -> None:
    # Messages 的错误码是 error.type：凭据拒绝用 authentication_error，与 Responses/Chat 的 code 形状不同
    body = json.dumps({"type": "error", "error": {"type": "authentication_error", "message": "scenario failure"}})
    send_reply(handler, 401, "application/json", body.encode("utf-8"))


# 流式回复送出一段输出之后连接关闭：声明的长度没有送完，回复在中途断开
PARTIAL_OUTPUT = "partial output before the connection broke"


def broken_responses_stream(_provider: ScriptedProvider, handler: BaseHTTPRequestHandler) -> None:
    # 送出 response.created 与一条完整的输出之后断开
    created = {"id": "resp-broken", "object": "response", "created_at": 1, "status": "in_progress",
               "model": "scenario-model-actual", "output": [], "usage": None, "error": None,
               "incomplete_details": None}
    item = {"id": "partial-message", "type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": PARTIAL_OUTPUT, "annotations": []}]}
    body = sse(_sse_event("response.created", {"response": created, "sequence_number": 0}),
               _sse_event("response.output_item.done", {"item": item, "output_index": 0, "sequence_number": 1}))
    send_reply(handler, 200, "text/event-stream", body, declared_length=len(body) + 4096)


def broken_chat_stream(_provider: ScriptedProvider, handler: BaseHTTPRequestHandler) -> None:
    # 送出一块文字增量之后断开
    chunk = {"id": "chat-broken", "object": "chat.completion.chunk", "created": 1, "model": "scenario-model-actual",
             "choices": [{"index": 0, "delta": {"role": "assistant", "content": PARTIAL_OUTPUT},
                          "finish_reason": None}]}
    body = sse(f"data: {json.dumps(chunk)}\n\n")
    send_reply(handler, 200, "text/event-stream", body, declared_length=len(body) + 4096)


def broken_messages_stream(_provider: ScriptedProvider, handler: BaseHTTPRequestHandler) -> None:
    # 送出 message_start 与一个文字块的开始和增量之后断开
    body = sse(
        _sse_event("message_start", {"message": {
            "id": "msg-broken", "type": "message", "role": "assistant", "model": "scenario-model-actual",
            "content": [], "usage": {"input_tokens": 100, "output_tokens": 1}}}),
        _sse_event("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
        _sse_event("content_block_delta", {"index": 0, "delta": {
            "type": "text_delta", "text": PARTIAL_OUTPUT}}),
    )
    send_reply(handler, 200, "text/event-stream", body, declared_length=len(body) + 4096)


BROKEN_STREAMS = {"responses": broken_responses_stream, "chat_completions": broken_chat_stream,
                  "messages": broken_messages_stream}
