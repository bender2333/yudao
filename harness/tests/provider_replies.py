# 测试内启动的本机模型服务按请求顺序回放的流式回复脚本：三种协议各一份构造，加上在测试里
# 直接写出回复与断开连接的辅助。事件序列基准的场景、请求时限的测试与只回复文字的测试共用。

import json
from http.server import BaseHTTPRequestHandler
from typing import Any

from harness.models import json_dumps
from harness.proposals import delivery, product_spec, review
from harness.tests.protocol_helpers import ScriptedProvider, send_reply, sse

# 检查命令一律写成 ["python", ...]，由主机解析解释器，基准中不出现本机路径
ECHO = "import sys\nprint(sys.argv[1])\n"


def _submission(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "kind"}


# 交接一次需要的三段脚本：产品提交规格、工程写文件并自检、质检复核并放行
HTTP_SCRIPT: list[list[tuple[str, dict[str, Any]]]] = [
    [("submit_product_spec", _submission(product_spec()))],
    [("write_file", {"path": "src/echo.py", "content": ECHO}),
     ("run_check", {"name": "smoke", "argv": ["python", "-c", "print('smoke ok')"]}),
     ("submit_delivery", _submission(delivery(check_names=["smoke"])))],
    [("run_check", {"name": "smoke", "argv": ["python", "-c", "print('smoke ok')"]}),
     ("submit_review", _submission(review("release", "checks passed on the current snapshot")))],
]


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
