from __future__ import annotations

import json
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from harness.collaboration import has_new_work
from harness.models import json_dumps
from harness.proposals import product_spec
from harness.providers import CredentialChain, ProviderFacade
from harness.runtime import LoopSystem
from harness.tests.helpers import department_history


# 本地回环服务按协议回放两轮流：第一轮文字加两个并行工具调用，第二轮提交产品要求；
# 断言第二次真实请求体中历史回放的形状
class _Capture:
    def __init__(self, responder) -> None:
        self.responder = responder
        self.requests: list[dict] = []


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b""
        capture = self.server.capture
        capture.requests.append(json.loads(raw.decode("utf-8")))
        body = capture.responder(len(capture.requests), capture.requests[-1].get("model") or "target-model")
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))
        self.wfile.flush()


def _spec_arguments() -> str:
    return json_dumps({key: value for key, value in product_spec().items() if key != "kind"})


def _chat_body(call_number: int, model: str) -> str:
    def chunk(delta: dict, finish: str | None = None) -> str:
        return "data: " + json.dumps({"id": "chat-1", "object": "chat.completion.chunk", "created": 1,
                                      "model": model,
                                      "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}) + "\n\n"
    if call_number == 1:
        events = [
            chunk({"content": "先查看代码。"}),
            chunk({"tool_calls": [{"index": 0, "id": "call-list", "type": "function",
                                   "function": {"name": "list_files", "arguments": "{}"}}]}),
            chunk({"tool_calls": [{"index": 1, "id": "call-search", "type": "function",
                                   "function": {"name": "search", "arguments": '{"pattern": "def"}'}}]}),
            chunk({}, "tool_calls"),
        ]
    else:
        events = [
            chunk({"tool_calls": [{"index": 0, "id": "call-submit", "type": "function",
                                   "function": {"name": "submit_product_spec", "arguments": _spec_arguments()}}]}),
            chunk({}, "tool_calls"),
        ]
    usage = {"id": "chat-1", "object": "chat.completion.chunk", "created": 1, "model": model, "choices": [],
             "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17}}
    return "".join(events) + "data: " + json.dumps(usage) + "\n\n" + "data: [DONE]\n\n"


def _messages_body(call_number: int, model: str) -> str:
    def event(kind: str, payload: dict) -> str:
        return f"event: {kind}\ndata: {json.dumps({'type': kind, **payload}, ensure_ascii=False)}\n\n"
    events = [event("message_start", {"message": {
        "id": f"msg-{call_number}", "type": "message", "role": "assistant", "model": model, "content": [],
        "usage": {"input_tokens": 11, "output_tokens": 1}}})]
    if call_number == 1:
        blocks = [("text", "先查看代码。"), ("call-list", "list_files", "{}"),
                  ("call-search", "search", '{"pattern": "def"}')]
    else:
        blocks = [("call-submit", "submit_product_spec", _spec_arguments())]
    for index, block in enumerate(blocks):
        if block[0] == "text":
            events.append(event("content_block_start", {"index": index,
                                                        "content_block": {"type": "text", "text": ""}}))
            events.append(event("content_block_delta", {"index": index,
                                                        "delta": {"type": "text_delta", "text": block[1]}}))
        else:
            events.append(event("content_block_start", {"index": index, "content_block": {
                "type": "tool_use", "id": block[0], "name": block[1], "input": {}}}))
            events.append(event("content_block_delta", {"index": index, "delta": {
                "type": "input_json_delta", "partial_json": block[2]}}))
        events.append(event("content_block_stop", {"index": index}))
    events.append(event("message_delta", {"delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 7}}))
    events.append(event("message_stop", {}))
    return "".join(events)


def _run_product_activation(tmp_path, responder, protocol: str):
    capture = _Capture(responder)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.capture = capture
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        facade = ProviderFacade(credentials=CredentialChain(overrides={"GO_KEY": "local-secret"}))
        facade.store_document({
            "providers": [{
                "id": "go", "name": "Go",
                "base_url": f"http://127.0.0.1:{server.server_address[1]}/v1",
                "credential_ref": "GO_KEY", "timeout_sec": 20.0, "preset_id": "",
            }],
            "models": [{
                "id": "m-go", "provider_id": "go", "model": "target-model",
                "protocol": protocol,
                "context_window": 32000, "max_output_tokens": 2048,
                "capability_source": "preset-v1",
            }],
            "bindings": {department: {"provider_id": "go", "model_id": "m-go"}
                         for department in ("product", "engineering", "quality")},
        })
        facade.record_admission("go", "m-go", admitted_model="target-model")
        # 与正式运行同一装配路径：事项冻结三部门目标，请求带模型输出上限
        system = LoopSystem(tmp_path, facade=facade)
        run_id = system.create_run("echo")
        result = system.activate_once(run_id)
        history = department_history(system, run_id, "product")
    finally:
        server.shutdown()
        server.server_close()
    return result, capture.requests, history


def _assert_history_items_are_responses_shaped(history: list[dict]) -> None:
    # 部门历史只保存内核可回放的条目：部门输入是带角色的文字消息，模型输出是 Responses 形状条目，
    # 每个模型输出条目按身份只记一次
    assert history
    for record in history:
        item = record["item"]
        if "type" in item:
            assert item["type"] in {"message", "function_call", "function_call_output"}, item
        else:
            assert item.get("role") in {"developer", "user"} and isinstance(item.get("content"), str) \
                and item["content"], item
    model_items = [record["item"]["id"] for record in history
                   if record["item"].get("type") in {"message", "function_call"}]
    assert model_items
    assert len(model_items) == len(set(model_items))


def test_chat_history_replay_sends_each_tool_result_once_without_empty_turns(tmp_path):
    result, requests, history = _run_product_activation(tmp_path, _chat_body, "chat_completions")

    assert has_new_work(result, "engineering")
    assert len(requests) == 2
    messages = requests[1]["messages"]
    tool_ids = Counter(message["tool_call_id"] for message in messages if message["role"] == "tool")
    assert tool_ids == Counter({"call-list": 1, "call-search": 1})
    for message in messages:
        if message["role"] != "assistant":
            assert isinstance(message["content"], str) and message["content"], message
    calls = [call["id"] for message in messages if message["role"] == "assistant"
             for call in message.get("tool_calls") or []]
    assert calls == ["call-list", "call-search"]
    assert sum(1 for message in messages if message["role"] == "assistant" and message.get("content") == "先查看代码。") == 1
    _assert_history_items_are_responses_shaped(history)


def test_messages_history_replay_sends_each_tool_result_once_without_empty_turns(tmp_path):
    result, requests, history = _run_product_activation(tmp_path, _messages_body, "messages")

    assert has_new_work(result, "engineering")
    assert len(requests) == 2
    messages = requests[1]["messages"]
    results = Counter(block["tool_use_id"] for message in messages if isinstance(message["content"], list)
                      for block in message["content"] if block.get("type") == "tool_result")
    assert results == Counter({"call-list": 1, "call-search": 1})
    for message in messages:
        if isinstance(message["content"], str):
            assert message["content"], message
    uses = [block["id"] for message in messages if isinstance(message["content"], list)
            for block in message["content"] if block.get("type") == "tool_use"]
    assert uses == ["call-list", "call-search"]
    _assert_history_items_are_responses_shaped(history)




