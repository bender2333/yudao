from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from harness.collaboration import has_new_work
from harness.providers.call import ModelResponse
from harness.adapters.fake import FakeAdapter
from harness.models import DEPARTMENTS, EventType, json_dumps
from harness.proposals import product_spec
from harness.providers import CredentialChain, ProviderFacade
from harness.runtime import LoopSystem
from harness.tests.helpers import FAST_RETRIES, department_history


# 故障现场截断参数原文：search 工具流式调用在 path 值之前中断
TRUNCATED_SEARCH_ARGUMENTS = '{"pattern": "def add", "path": '


def _recorded_call_arguments(records: list[dict]) -> list:
    return [
        record["item"]["arguments"] for record in records
        if isinstance(record.get("item"), dict) and record["item"].get("type") == "function_call"
    ]


def test_truncated_arguments_are_sanitized_before_history_replay(tmp_path):
    malformed = ModelResponse(output=[{
        "id": "call-truncated", "call_id": "call-truncated", "type": "function_call",
        "name": "search", "arguments": TRUNCATED_SEARCH_ARGUMENTS,
    }])
    adapter = FakeAdapter([malformed, product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    run_id = system.create_run("echo")

    result = system.activate_once(run_id)

    # 可恢复的参数错误不能变成硬失败，运行必须继续推进
    assert has_new_work(result, "engineering")
    assert len(adapter.invocations) == 2
    # 记入历史与下次请求回放的参数恒为有效 JSON 对象
    history = department_history(system, run_id, "product")
    assert history
    for raw in _recorded_call_arguments(history):
        assert isinstance(json.loads(raw), dict)
    replayed = [
        item["arguments"] for item in adapter.invocations[1].input_items
        if isinstance(item, dict) and item.get("type") == "function_call"
    ]
    assert replayed
    for raw in replayed:
        assert isinstance(json.loads(raw), dict)
    # 具体参数错误仍经工具结果回传给模型，且从未启动工具
    assert "invalid tool arguments" in json_dumps(adapter.invocations[1].input_items)
    events = system.store.list_events(run_id)
    assert not any(item.type == EventType.TOOL_STARTED and item.payload.get("id") == "call-truncated"
                   for item in events)
    assert any(item.type == EventType.TOOL_CALLED and item.payload.get("id") == "call-truncated"
               and item.payload.get("ok") is False for item in events)


def test_valid_tool_call_still_executes_with_original_arguments(tmp_path):
    arguments = json_dumps({"pattern": "def add"})
    valid = ModelResponse(output=[{
        "id": "call-search", "call_id": "call-search", "type": "function_call",
        "name": "search", "arguments": arguments,
    }])
    adapter = FakeAdapter([valid, product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    run_id = system.create_run("echo")

    result = system.activate_once(run_id)

    assert has_new_work(result, "engineering")
    events = system.store.list_events(run_id)
    called = next(item for item in events
                  if item.type == EventType.TOOL_CALLED and item.payload.get("id") == "call-search")
    assert called.payload.get("ok") is True
    replayed = [
        item["arguments"] for item in adapter.invocations[1].input_items
        if isinstance(item, dict) and item.get("type") == "function_call"
    ]
    assert [json.loads(raw) for raw in replayed] == [{"pattern": "def add"}]


# 以下经本地回环服务复现 chat 通道：首次返回截断调用流，断言第二次真实请求体
class _Capture:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.calls = 0


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b""
        capture = self.server.capture
        capture.requests.append(json.loads(raw.decode("utf-8")))
        capture.calls += 1
        if capture.calls == 1:
            chunks = _tool_chunks(
                capture.requests[0].get("model") or "target-model",
                "call-truncated", "search",
                ['{"pattern": "def add", ', '"path": '],
            )
        else:
            spec_args = {key: value for key, value in product_spec().items() if key != "kind"}
            chunks = _tool_chunks(
                capture.requests[0].get("model") or "target-model",
                "call-submit", "submit_product_spec",
                [json_dumps(spec_args)],
            )
        body = "".join(chunks).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()


def _chunk(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _tool_chunks(model: str, call_id: str, name: str, fragments: list[str]) -> list[str]:
    head = {"index": 0, "id": call_id, "type": "function",
            "function": {"name": name, "arguments": fragments[0]}}
    events = [_chunk({"id": "chat-1", "object": "chat.completion.chunk", "created": 1,
                      "model": model,
                      "choices": [{"index": 0, "delta": {"tool_calls": [head]},
                                   "finish_reason": None}]})]
    for fragment in fragments[1:]:
        events.append(_chunk({"id": "chat-1", "object": "chat.completion.chunk", "created": 1,
                              "model": model,
                              "choices": [{"index": 0, "delta": {"tool_calls": [
                                  {"index": 0, "function": {"arguments": fragment}}]},
                                          "finish_reason": None}]}))
    events.append(_chunk({"id": "chat-1", "object": "chat.completion.chunk", "created": 1,
                          "model": model,
                          "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]}))
    events.append(_chunk({"id": "chat-1", "object": "chat.completion.chunk", "created": 1,
                          "model": model, "choices": [],
                          "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17}}))
    events.append("data: [DONE]\n\n")
    return events


def test_truncated_chat_stream_never_replays_invalid_assistant_arguments(tmp_path):
    capture = _Capture()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.capture = capture
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        facade = ProviderFacade(credentials=CredentialChain(overrides={"GO_KEY": "local-secret"}))
        facade.store_document({
            "providers": [{
                "id": "go", "name": "Go", "base_url": base + "/v1",
                "credential_ref": "GO_KEY", "timeout_sec": 20.0, "preset_id": "",
            }],
            "models": [{
                "id": "m-go", "provider_id": "go", "model": "target-model",
                "protocol": "chat_completions",
                "context_window": 32000, "max_output_tokens": 2048,
                "capability_source": "preset-v1",
            }],
            "bindings": {},
        })
        facade.record_admission("go", "m-go", admitted_model="target-model")
        facade.save_bindings({department: {"provider_id": "go", "model_id": "m-go"}
                              for department in DEPARTMENTS})
        system = LoopSystem(tmp_path, facade=facade)
        run_id = system.create_run("echo")

        result = system.activate_once(run_id)
    finally:
        server.shutdown()
        server.server_close()

    assert has_new_work(result, "engineering")
    assert len(capture.requests) == 2
    second = capture.requests[1]
    assistant_calls = [call for message in second["messages"]
                       if message.get("role") == "assistant"
                       for call in message.get("tool_calls") or []]
    assert assistant_calls
    for call in assistant_calls:
        assert isinstance(json.loads(call["function"]["arguments"]), dict)
    # 截断原文不得出现在第二次请求中，错误仍可见
    wire = json.dumps(second, ensure_ascii=False)
    assert TRUNCATED_SEARCH_ARGUMENTS not in wire
    assert "invalid tool arguments" in wire
