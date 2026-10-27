from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from harness.watched_outputs import has_new_work
from harness.models import ArtifactRef, EventType, json_dumps
from harness.proposals import product_spec
from harness.providers import CredentialChain, ProviderFacade
from harness.runtime import LoopSystem
from harness.tests.helpers import department_history

# 三种协议的推理内容保存与回放（工单 #88，设计说明第 7.6 节）：
# 本机 HTTP 服务在第一轮流里返回推理内容，记录第二流的真实请求体，核对回放

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
            chunk({"reasoning_content": "先看代码，再提交。"}),
            chunk({"content": "先查看代码。"}),
            chunk({"tool_calls": [{"index": 0, "id": "call-list", "type": "function",
                                   "function": {"name": "list_files", "arguments": "{}"}}],
                   "reasoning_content": "决定了工具。"}),
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
        events.append(event("content_block_start", {"index": 0,
                                                    "content_block": {"type": "thinking", "thinking": ""}}))
        events.append(event("content_block_delta", {"index": 0, "delta": {"type": "thinking_delta",
                                                                          "thinking": "先看代码。"}}))
        events.append(event("content_block_delta", {"index": 0, "delta": {"type": "signature_delta",
                                                                          "signature": "sig-abc"}}))
        events.append(event("content_block_stop", {"index": 0}))
        events.append(event("content_block_start", {"index": 1,
                                                    "content_block": {"type": "tool_use", "id": "call-list",
                                                                      "name": "list_files", "input": {}}}))
        events.append(event("content_block_delta", {"index": 1, "delta": {"type": "input_json_delta",
                                                                          "partial_json": "{}"}}))
        events.append(event("content_block_stop", {"index": 1}))
    else:
        events.append(event("content_block_start", {"index": 0, "content_block": {
            "type": "tool_use", "id": "call-submit", "name": "submit_product_spec", "input": {}}}))
        events.append(event("content_block_delta", {"index": 0, "delta": {
            "type": "input_json_delta", "partial_json": _spec_arguments()}}))
        events.append(event("content_block_stop", {"index": 0}))
    events.append(event("message_delta", {"delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 7}}))
    events.append(event("message_stop", {}))
    return "".join(events)

def _responses_body(call_number: int, model: str) -> str:
    def event(kind: str, payload: dict) -> str:
        return f"event: {kind}\ndata: {json.dumps({'type': kind, **payload}, ensure_ascii=False)}\n\n"
    reasoning = {"id": "rs-1", "type": "reasoning", "summary": [{"type": "summary_text", "text": "先看代码"}],
                 "encrypted_content": "CIPHER-1"}
    if call_number == 1:
        items = [reasoning, {"id": "call-list", "type": "function_call", "call_id": "call-list",
                             "name": "list_files", "arguments": "{}"}]
    else:
        items = [{"id": "call-submit", "type": "function_call", "call_id": "call-submit",
                  "name": "submit_product_spec", "arguments": _spec_arguments()}]
    response = {"id": f"resp-{call_number}", "model": model, "status": "completed", "output": items,
                "usage": {"input_tokens": 9, "output_tokens": 2, "total_tokens": 11}}
    return event("response.completed", {"response": response})

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
        system = LoopSystem(tmp_path, facade=facade)
        run_id = system.create_run("echo")
        result = system.activate_once(run_id)
        history = department_history(system, run_id, "product")
    finally:
        server.shutdown()
        server.server_close()
    return result, capture.requests, history, system, run_id

def _reasoning_items(history: list[dict]) -> list[dict]:
    return [record["item"] for record in history if record["item"].get("type") == "reasoning"]

def _assert_reasoning_visible(system: LoopSystem, run_id: str, text: str) -> None:
    # 推理内容写入部门历史并在事件中可以查看：本部门的 model_reasoning 事件带着保存它的工件，
    # 工件里是这条推理内容的原文
    events = [event for event in system.store.list_events(run_id)
              if event.type == EventType.MODEL_REASONING and event.department == "product"]
    assert events
    items = [json.loads(system.artifacts.get_for_run(
        run_id, ArtifactRef(**event.payload["reasoning_ref"])).decode("utf-8")) for event in events]
    assert any(text in json_dumps(item) for item in items)

def test_chat_reasoning_content_is_saved_and_replayed_on_the_same_model(tmp_path):
    result, requests, history, system, run_id = _run_product_activation(
        tmp_path, _chat_body, "chat_completions")

    assert has_new_work(result, "engineering")
    reasoning = _reasoning_items(history)
    # 同一轮回答的推理块累积成一条 assistant 消息上的 reasoning_content
    assert [item["reasoning_content"] for item in reasoning] == ["先看代码，再提交。决定了工具。"]
    _assert_reasoning_visible(system, run_id, "先看代码，再提交。决定了工具。")
    # 第二次真实请求体：助手消息原样带上推理内容
    messages = requests[1]["messages"]
    replayed = [message for message in messages if message.get("reasoning_content")]
    assert len(replayed) == 1
    assert replayed[0]["reasoning_content"] == "先看代码，再提交。决定了工具。"

def test_messages_thinking_and_signature_are_saved_and_replayed_on_the_same_model(tmp_path):
    result, requests, history, system, run_id = _run_product_activation(tmp_path, _messages_body, "messages")

    assert has_new_work(result, "engineering")
    reasoning = _reasoning_items(history)
    assert len(reasoning) == 1
    assert reasoning[0]["call_id"] == "call-list"
    assert reasoning[0]["blocks"] == [{"type": "thinking", "thinking": "先看代码。", "signature": "sig-abc"}]
    _assert_reasoning_visible(system, run_id, "先看代码。")
    messages = requests[1]["messages"]
    assistant = [message for message in messages if isinstance(message.get("content"), list)
                 and any(block.get("type") == "thinking" for block in message["content"])]
    assert len(assistant) == 1
    assert assistant[0]["content"][0] == {"type": "thinking", "thinking": "先看代码。", "signature": "sig-abc"}
    assert assistant[0]["content"][1]["type"] == "tool_use"
    assert assistant[0]["content"][1]["id"] == "call-list"

def test_responses_reasoning_item_is_saved_and_replayed_on_the_same_model(tmp_path):
    result, requests, history, system, run_id = _run_product_activation(tmp_path, _responses_body, "responses")

    assert has_new_work(result, "engineering")
    reasoning = _reasoning_items(history)
    assert len(reasoning) == 1
    assert reasoning[0]["encrypted_content"] == "CIPHER-1"
    _assert_reasoning_visible(system, run_id, "先看代码")
    # 重放事件得到的部门历史与运行时相同
    assert system.project(run_id).canonical_state() == system.replay(run_id).canonical_state()
    # 第一次请求带 include 要求上游返回加密推理内容
    assert requests[0]["include"] == ["reasoning.encrypted_content"]
    # 第二次请求的 input 原样带上 reasoning 条目
    replayed = [item for item in requests[1]["input"] if item.get("type") == "reasoning"]
    assert replayed and replayed[0]["encrypted_content"] == "CIPHER-1"

def _delivery_arguments() -> str:
    from harness.proposals import delivery
    return json_dumps({key: value for key, value in delivery().items() if key != "kind"})

def _department(body: dict) -> str:
    parts: list[str] = []
    for item in body.get("input", []):
        content = item.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for segment in content:
                if isinstance(segment, dict) and isinstance(segment.get("text"), str):
                    parts.append(segment["text"])
    import re
    match = re.search(r'"department":"(\w+)"', "\n".join(parts))
    return match.group(1) if match else ""

def _reasoning_call_item(call_id: str, name: str, arguments: str) -> list[dict]:
    # 推理条目先于它伴随的工具调用，回放时保持这个顺序
    return [{"id": f"rs-{call_id}", "type": "reasoning", "summary": [],
             "encrypted_content": "CIPHER-1"},
            {"id": call_id, "type": "function_call", "call_id": call_id, "name": name, "arguments": arguments}]

def _department_responses_body(body: dict, model: str) -> str:
    def event(kind: str, payload: dict) -> str:
        return f"event: {kind}\ndata: {json.dumps({'type': kind, **payload}, ensure_ascii=False)}\n\n"
    if _department(body) == "engineering":
        items = _reasoning_call_item("eng-delivery", "submit_delivery", _delivery_arguments())
        response_id = "resp-delivery"
    elif _has_department_history_pair(body):
        items = _reasoning_call_item("product-spec", "submit_product_spec", _spec_arguments())
        response_id = "resp-spec"
    else:
        items = _reasoning_call_item("product-read", "read_file", json_dumps({"path": "proof.txt"}))
        response_id = "resp-read"
    response = {"id": response_id, "model": model, "status": "completed", "output": items,
                "usage": {"input_tokens": 9, "output_tokens": 2, "total_tokens": 11}}
    return event("response.completed", {"response": response})

def _has_department_history_pair(body: dict) -> bool:
    return any(item.get("type") == "function_call_output" for item in body.get("input", [])
               if isinstance(item, dict))

def test_switching_model_drops_reasoning_and_protocol_item_ids_but_keeps_pairs(tmp_path):
    # 运行中更换上游模型：产品先做一次工具调用，换模型后下一次请求不再带推理内容与协议专用条目 ID，
    # 工具调用与结果仍然成对
    facade_holder: dict[str, Any] = {}

    def responder(_n: int, model: str) -> str:
        body = capture.requests[-1]
        response = _department_responses_body(body, model)
        if _has_department_history_pair(body) is False and body.get("model") == "target-model":
            # 产品第一次调用（工具调用）之后换模型，下一次逻辑调用按新模型解析
            facade_holder["swap"]()
        return response

    capture = _Capture(responder)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.capture = capture
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}/v1"

    def document(model: str) -> dict:
        return {
            "providers": [{"id": "go", "name": "Go", "base_url": base,
                           "credential_ref": "GO_KEY", "timeout_sec": 20.0, "preset_id": ""}],
            "models": [{"id": "m-go", "provider_id": "go", "model": model,
                        "protocol": "responses",
                        "context_window": 32000, "max_output_tokens": 2048, "capability_source": "preset-v1"}],
            "bindings": {department: {"provider_id": "go", "model_id": "m-go"}
                         for department in ("product", "engineering", "quality")},
        }

    try:
        facade = ProviderFacade(credentials=CredentialChain(overrides={"GO_KEY": "local-secret"}))
        facade.store_document(document("target-model"))
        facade.record_admission("go", "m-go", admitted_model="target-model")

        def swap() -> None:
            facade.store_document(document("other-model"))
            facade.record_admission("go", "m-go", admitted_model="other-model")

        facade_holder["swap"] = swap
        system = LoopSystem(tmp_path, facade=facade)
        run_id = system.create_run("echo")
        system.activate_once(run_id)
    finally:
        server.shutdown()
        server.server_close()

    assert len(capture.requests) >= 2
    second = next(request for request in capture.requests if request["model"] == "other-model")
    items = second["input"]
    # 上一个模型的推理内容与协议专用条目 ID 都被丢弃
    assert not any(item.get("type") == "reasoning" for item in items)
    assert not any("id" in item for item in items if item.get("type") in {"message", "function_call"})
    # 工具调用与结果仍然成对
    call_ids = [item["call_id"] for item in items if item.get("type") == "function_call"]
    output_ids = [item["call_id"] for item in items if item.get("type") == "function_call_output"]
    assert call_ids and call_ids == output_ids
