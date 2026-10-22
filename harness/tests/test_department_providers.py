from __future__ import annotations

import json
import sys
import time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from typing import Any, Callable, Iterator

import pytest
from openai import DEFAULT_CONNECTION_LIMITS

from harness.engine import StepLimits
from harness.models import ArtifactRef, EventType, json_dumps
from harness.providers import CredentialChain, CredentialMaterial, ProviderFacade, ResponsesConfig
from harness.proposals import delivery, product_spec, review
from harness.runtime import LoopSystem
from harness.smoke import summarize_run
from harness.tests.protocol_helpers import preset_base_urls

@dataclass(frozen=True)
class _Reply:
    body: bytes
    status: int = 200
    content_type: str = "text/event-stream"
    headers: dict[str, str] | None = None

Responder = Callable[[dict[str, Any], int], _Reply]
MILLISECOND_RETRIES = StepLimits(retry_initial_delay_sec=0.001, retry_max_delay_sec=0.001)

def _event(kind: str, **payload: Any) -> bytes:
    body = {"type": kind, **payload}
    return f"event: {kind}\ndata: {json.dumps(body)}\n\n".encode()

def _stream(output: list[dict[str, Any]], *, response_id: str, model: str, usage: bool = True) -> _Reply:
    raw_usage = (
        {
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        }
        if usage
        else None
    )
    response = {
        "id": response_id,
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "model": model,
        "output": output,
        "usage": raw_usage,
        "error": None,
        "incomplete_details": None,
    }
    frames = [
        _event(
            "response.created",
            response={**response, "status": "in_progress", "output": [], "usage": None},
            sequence_number=0,
        )
    ]
    for index, item in enumerate(output, start=1):
        frames.append(_event("response.output_item.done", item=item, output_index=index - 1, sequence_number=index))
    frames.append(_event("response.completed", response=response, sequence_number=len(frames)))
    return _Reply(b"".join(frames))

def _chat_stream(calls: list[dict[str, Any]], *, response_id: str, model: str) -> _Reply:
    # Chat Completions 流：每个工具调用一个增量块，随后是结束块与用量块
    def chunk(choices: list[dict[str, Any]], **extra: Any) -> bytes:
        body = {"id": response_id, "object": "chat.completion.chunk", "created": 1, "model": model,
                "choices": choices, **extra}
        return f"data: {json.dumps(body)}\n\n".encode()

    frames = [
        chunk([{"index": 0, "finish_reason": None, "delta": {"tool_calls": [{
            "index": index, "id": call["call_id"], "type": "function",
            "function": {"name": call["name"], "arguments": call["arguments"]},
        }]}}])
        for index, call in enumerate(calls)
    ]
    if calls:
        frames.append(chunk([{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]))
    else:
        # 压缩请求不带工具：只回摘要文本，以普通结束而不是工具调用结束
        frames.append(chunk([{"index": 0, "delta": {"content": "Compacted work summary."}}]))
        frames.append(chunk([{"index": 0, "delta": {}, "finish_reason": "stop"}]))
    frames.append(chunk([], usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}))
    frames.append(b"data: [DONE]\n\n")
    return _Reply(b"".join(frames))

def _messages_stream(calls: list[dict[str, Any]], *, message_id: str, model: str, text: str = "") -> _Reply:
    # Anthropic Messages 流：文本块与 tool_use 块依次开始、增量、结束
    frames = [_event("message_start", message={
        "id": message_id, "type": "message", "role": "assistant", "model": model, "content": [],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    })]
    blocks: list[tuple[dict[str, Any], dict[str, Any]]] = []
    if text:
        blocks.append(({"type": "text", "text": ""}, {"type": "text_delta", "text": text}))
    for call in calls:
        blocks.append(({"type": "tool_use", "id": call["call_id"], "name": call["name"], "input": {}},
                       {"type": "input_json_delta", "partial_json": call["arguments"]}))
    for index, (block, delta) in enumerate(blocks):
        frames.append(_event("content_block_start", index=index, content_block=block))
        frames.append(_event("content_block_delta", index=index, delta=delta))
        frames.append(_event("content_block_stop", index=index))
    frames.append(_event("message_delta", delta={"stop_reason": "tool_use" if calls else "end_turn"},
                         usage={"output_tokens": 1}))
    frames.append(_event("message_stop"))
    return _Reply(b"".join(frames))

def _error(status: int = 500) -> _Reply:
    return _Reply(
        b'{"error":{"code":"server_error","message":"transient"}}',
        status=status,
        content_type="application/json",
    )

def _call(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"item-{call_id}",
        "type": "function_call",
        "name": name,
        "call_id": call_id,
        "arguments": json.dumps(arguments, ensure_ascii=False, separators=(",", ":")),
        "status": "completed",
    }

def _message(message_id: str, text: str) -> dict[str, Any]:
    return {
        "id": message_id,
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }

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

def _spec_hash(body: dict[str, Any]) -> str | None:
    return _material_hash(body, "current_product_spec", "content_hash")

def _material_text(item: Any) -> str:
    # 三种协议的输入项形状不同：Responses 的 input 与 Chat 的 messages 用字符串正文，
    # Messages 协议把正文放在 content 块的 text 里
    content = item.get("content") if isinstance(item, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(block.get("text", "") for block in content if isinstance(block, dict))
    return ""

@contextmanager
def _provider_server(provider: str, key: str, responder: Responder) -> Iterator[tuple[ResponsesConfig, list[dict[str, Any]], list[BaseException]]]:
    captures: list[dict[str, Any]] = []
    errors: list[BaseException] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args: Any) -> None:
            return

        def do_POST(self) -> None:
            capture: dict[str, Any] = {"arrived": time.monotonic()}
            try:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                capture.update({
                    "body": body,
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "headers": {key.lower(): value for key, value in self.headers.items()},
                    "client_port": self.client_address[1],
                })
                captures.append(capture)
                reply = responder(body, len(captures))
            except BaseException as exc:
                errors.append(exc)
                reply = _error()
            # 开始送出回复的时刻：客户端在这之前收不到回复，连接最早从这以后才空闲
            capture["replied"] = time.monotonic()
            self.send_response(reply.status)
            self.send_header("Content-Type", reply.content_type)
            self.send_header("Content-Length", str(len(reply.body)))
            self.send_header("Connection", "keep-alive")
            for name, value in (reply.headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            try:
                self.wfile.write(reply.body)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    worker.start()
    config = ResponsesConfig(
        model=f"{provider}-configured",
        api_key=key,
        provider=provider,
        base_url=f"http://127.0.0.1:{server.server_port}/v1",
        timeout_sec=2,
    )
    try:
        yield config, captures, errors
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)

def _connections_kept_alive(captures: list[dict[str, Any]]) -> list[tuple[int, int]]:
    # Responses 的连接池使用 SDK 的默认连接限制（DEFAULT_CONNECTION_LIMITS），空闲超过保持时限的连接关闭。
    # 相邻两次请求之间，服务端开始送出回复到收到下一次请求的时间不短于客户端连接的空闲时间；这段时间短于
    # 保持时限时，两次请求必须使用同一个连接。运行按顺序发出请求，两次请求不会同时进行。返回这些相邻请求的端口
    keepalive = DEFAULT_CONNECTION_LIMITS.keepalive_expiry
    return [(earlier["client_port"], later["client_port"])
            for earlier, later in zip(captures, captures[1:])
            if 0 <= later["arrived"] - earlier["replied"] < keepalive]

def _part(body: dict[str, Any], name: str) -> str | None:
    # Work requests open with the pinned department material; tool-less compaction requests
    # open with the summarizer rules and pin the department material second.
    content = body["input"][1 if not body["tools"] else 0]["content"]
    marker = f"[{name}]\n"
    if marker not in content:
        return None
    value = content.split(marker, 1)[1]
    return value.split("\n\n[", 1)[0]

def _department(body: dict[str, Any]) -> str:
    raw = _part(body, "binding_refs")
    assert raw is not None
    return json.loads(raw)["department"]

def _contract_hash(body: dict[str, Any]) -> str:
    raw = _part(body, "current_contract")
    assert raw is not None
    return json.loads(raw)["content_hash"]

def _facade(
    product_url: str,
    engineering_url: str,
    *,
    product_context_window: int = 20_000,
    product_provider: str = "provider-a",
    credentials: dict | None = None,
    timeout_sec: float = 10,
) -> ProviderFacade:
    product_model_id = "model-a-product" if product_provider == "provider-a" else "model-b-product"
    facade = ProviderFacade(credentials=CredentialChain(use_env=False))
    facade.store_document({
        "providers": [
            {"id": "provider-a", "name": "Provider A", "base_url": product_url,
             "credential_ref": "credential-a", "timeout_sec": timeout_sec},
            {"id": "provider-b", "name": "Provider B", "base_url": engineering_url,
             "credential_ref": "credential-b", "timeout_sec": timeout_sec},
        ],
        "models": [
            {"id": "model-a-product", "provider_id": "provider-a", "model": "a-product",
             "protocol": "responses",
             "context_window": product_context_window, "max_output_tokens": 1_000},
            {"id": "model-a-quality", "provider_id": "provider-a", "model": "a-quality",
             "protocol": "responses",
             "context_window": 20_000, "max_output_tokens": 1_000},
            {"id": "model-b-engineering", "provider_id": "provider-b", "model": "b-engineering",
             "protocol": "responses",
             "context_window": 20_000, "max_output_tokens": 1_000},
            {"id": "model-b-product", "provider_id": "provider-b", "model": "b-product",
             "protocol": "responses",
             "context_window": product_context_window, "max_output_tokens": 1_000},
        ],
        "bindings": {
            "product": {"provider_id": product_provider, "model_id": product_model_id},
            "engineering": {"provider_id": "provider-b", "model_id": "model-b-engineering"},
            "quality": {"provider_id": "provider-a", "model_id": "model-a-quality"},
        },
    })
    for ref, material in (credentials or {}).items():
        facade.set_credential_override(ref, material)
    # 真实协议模型须先经模型测试准入才能用于任务，测试通过模块接口记录该事实
    entries = {item["id"]: item for item in facade.providers_view()["models"]}
    for provider_id, model_id in (
        ("provider-a", "model-a-product"), ("provider-a", "model-a-quality"),
        ("provider-b", "model-b-engineering"), ("provider-b", "model-b-product"),
    ):
        entry = entries.get(model_id)
        if entry is not None:
            facade.record_admission(provider_id, model_id, admitted_model=entry["model"])
    return facade

def _credentials(product: str = "provider-a-key-v1") -> dict[str, CredentialMaterial]:
    return {
        "credential-a": CredentialMaterial(product, version="a-v1"),
        "credential-b": CredentialMaterial("provider-b-key-v1", version="b-v1"),
    }

def _public_run_data(system: LoopSystem, run_id: str) -> str:
    events = [event.__dict__ for event in system.store.list_events(run_id)]
    return json_dumps({"projection": system.project(run_id), "events": events})

def test_http_provider_bindings_route_full_ask_and_engineering_rework(tmp_path):
    counts = {"product": 0, "engineering": 0, "quality": 0}
    delivery_file = "import sys\nprint(sys.argv[1])\n"
    repaired_file = "import sys\nprint(sys.argv[1].upper())\n"

    def provider_a(body: dict[str, Any], _count: int) -> _Reply:
        department = _department(body)
        assert department in {"product", "quality"}
        counts[department] += 1
        if department == "product":
            if counts[department] == 1:
                payload = product_spec()
                payload.pop("kind")
                return _stream([_call("product-spec", "submit_product_spec", payload)],
                               response_id="a-product-spec", model="a-product-actual")
            payload = {"answer": "The output check should cover a normal argument."}
            return _stream([_call(f"product-answer-{counts[department]}", "answer", payload)],
                           response_id=f"a-product-answer-{counts[department]}", model="a-product-actual")

        verdict = "rework_engineering" if counts[department] == 1 else "release"
        payload = review(
            verdict,
            "The first delivery needs an uppercase output check." if verdict.startswith("rework") else "The repaired delivery passes.",
            checks=["smoke"],
            defects=[{"severity": "major", "summary": "Output is not uppercase."}] if verdict.startswith("rework") else [],
            basis_delivery_spec_hash=_material_hash(body, "current_delivery_spec", "content_hash"),
        )
        payload.pop("kind")
        calls = [
            _call(
                f"quality-check-{counts[department]}",
                "run_check",
                {"name": "smoke", "command": f"\"{sys.executable.replace(chr(92), '/')}\" -c \"print('quality')\""},
            ),
            _call(f"quality-review-{counts[department]}", "submit_review", payload),
        ]
        return _stream(calls, response_id=f"a-quality-{counts[department]}", model="a-quality-actual")

    def provider_b(body: dict[str, Any], _count: int) -> _Reply:
        department = _department(body)
        assert department == "engineering"
        counts[department] += 1
        if counts[department] == 1:
            payload = {
                "recipient": "product",
                "question": "What should the smoke check cover?",
                "background": "Need clarification for check.",
                "expected": "Give the minimum acceptance behavior.",
            }
            return _stream([_call("engineering-ask", "ask", payload)],
                           response_id="b-ask", model="b-engineering-actual")

        content = delivery_file if counts[department] == 2 else repaired_file
        payload = delivery(check_names=["smoke"],
                           basis_product_spec_hash=_spec_hash(body))
        payload.pop("kind")
        calls = [
            _call(f"write-{counts[department]}", "write_file", {"path": "src/echo.py", "content": content}),
            _call(
                f"engineering-check-{counts[department]}",
                "run_check",
                {"name": "smoke", "command": f"\"{sys.executable.replace(chr(92), '/')}\" -c \"print('engineering')\""},
            ),
            _call(f"delivery-{counts[department]}", "submit_delivery", payload),
        ]
        return _stream(calls, response_id=f"b-delivery-{counts[department]}", model="b-engineering-actual")

    with _provider_server("provider-a", "provider-a-key-v1", provider_a) as (config_a, captures_a, errors_a), \
            _provider_server("provider-b", "provider-b-key-v1", provider_b) as (config_b, captures_b, errors_b):
        system = LoopSystem(
            tmp_path,
            facade=_facade(config_a.base_url, config_b.base_url, credentials=_credentials()),
        )
        run_id = system.create_run("build an echo command")
        result = system.run_until_stop(run_id)

        assert not errors_a and not errors_b
        assert config_a.base_url != config_b.base_url
        assert result.phase == "DONE", result.error
        assert result.rework_count == 1
        assert any(event.type == EventType.ASK_ANSWERED for event in system.store.list_events(run_id))
        assert counts == {"product": 2, "engineering": 3, "quality": 2}
        assert [item["path"] for item in captures_a] == ["/v1/responses"] * len(captures_a)
        assert [item["path"] for item in captures_b] == ["/v1/responses"] * len(captures_b)
        assert [_department(item["body"]) for item in captures_a] == ["product", "product", "quality", "quality"]
        assert [_department(item["body"]) for item in captures_b] == ["engineering"] * 3
        assert all(item["authorization"] == "Bearer provider-a-key-v1" for item in captures_a)
        assert all(item["authorization"] == "Bearer provider-b-key-v1" for item in captures_b)
        assert [item["body"]["model"] for item in captures_a] == ["a-product", "a-product", "a-quality", "a-quality"]
        assert [item["body"]["model"] for item in captures_b] == ["b-engineering"] * 3
        timeline = [(item["client_port"], round(item["arrived"], 2), round(item["replied"], 2))
                    for item in captures_a + captures_b]
        kept_alive = _connections_kept_alive(captures_a) + _connections_kept_alive(captures_b)
        assert kept_alive, timeline
        assert all(earlier == later for earlier, later in kept_alive), timeline
        assert {item["client_port"] for item in captures_a}.isdisjoint(
            item["client_port"] for item in captures_b
        )
        assert result.provider_bindings["product"]["provider_config_id"] == "provider-a"
        assert result.provider_bindings["engineering"]["provider_config_id"] == "provider-b"
        assert result.provider_bindings["quality"]["provider_config_id"] == "provider-a"
        requests = result.model_requests
        assert [(item["provider_config_id"], item["requested_model"]) for item in requests] == [
            ("provider-a", "a-product"), ("provider-b", "b-engineering"),
            ("provider-a", "a-product"), ("provider-b", "b-engineering"),
            ("provider-a", "a-quality"),
            ("provider-b", "b-engineering"), ("provider-a", "a-quality"),
        ]
        assert all(item["actual_model"] for item in requests)
        public = _public_run_data(system, run_id)
        assert "provider-a-key-v1" not in public and "provider-b-key-v1" not in public
        captures_by_provider = {"provider-a": captures_a, "provider-b": captures_b}
        positions = {provider: 0 for provider in captures_by_provider}
        contexts = [event for event in system.store.list_events(run_id) if event.type == EventType.CONTEXT_ASSEMBLED]
        assert len(contexts) == len(captures_a) + len(captures_b)
        for event in contexts:
            provider = event.payload["provider_config_id"]
            captured = captures_by_provider[provider][positions[provider]]
            positions[provider] += 1
            persisted = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**event.payload["request_ref"])))
            assert persisted["input"] == captured["body"]["input"]
            assert persisted["tools"] == captured["body"]["tools"]
            assert persisted.get("max_output_tokens") == captured["body"].get("max_output_tokens")
            assert "authorization" not in json_dumps(persisted).casefold()
            assert "provider-a-key-v1" not in json_dumps(persisted)
            assert "provider-b-key-v1" not in json_dumps(persisted)
        audit = summarize_run(system, run_id, scenario="d18-local-http")
        assert audit["model_input_audit"]["status"] == "verified", audit["model_input_audit"]
        assert audit["manifest_boundary"] is True
        assert audit["context_isolated"] is True
        assert audit["replay_consistent"] is True
        assert audit["fake_used"] is False
        assert audit["ask_audit"]["status"] == "verified", audit["ask_audit"]

def test_each_run_resolves_credentials_from_its_own_source(tmp_path):
    def product_response(body: dict[str, Any], count: int) -> _Reply:
        assert _department(body) == "product"
        payload = product_spec()
        payload.pop("kind")
        return _stream([_call(f"product-{count}", "submit_product_spec", payload)],
                       response_id=f"product-{count}", model="a-product-actual")

    with _provider_server("provider-a", "provider-a-key-v1", product_response) as (config_a, captures_a, errors_a), \
            _provider_server("provider-b", "provider-b-key-v2", product_response) as (config_b, captures_b, errors_b):
        credentials = _credentials()
        original = LoopSystem(
            tmp_path,
            facade=_facade(config_a.base_url, config_b.base_url, credentials=credentials),
            resume_on_startup=False,
        )
        first_run = original.create_run("first task")
        credentials["credential-b"] = CredentialMaterial("provider-b-key-v2", version="b-v2")
        updated = LoopSystem(tmp_path, facade=_facade(
            config_a.base_url,
            config_b.base_url,
            product_provider="provider-b",
            credentials=credentials,
        ), resume_on_startup=False)
        second_run = updated.create_run("second task")

        first = original.activate_once(first_run)
        second = updated.activate_once(second_run)

        assert not errors_a and not errors_b
        assert [_department(item["body"]) for item in captures_a] == ["product"]
        assert [item["authorization"] for item in captures_a] == ["Bearer provider-a-key-v1"]
        assert [item["authorization"] for item in captures_b] == ["Bearer provider-b-key-v2"]
        assert first.provider_bindings["product"]["credential_version"] == "a-v1"
        assert second.provider_bindings["product"]["credential_version"] == "b-v2"
        assert first.provider_bindings["product"]["provider_config_id"] == "provider-a"
        assert second.provider_bindings["product"]["provider_config_id"] == "provider-b"
        assert first.provider_bindings["product"]["requested_model"] == "a-product"
        assert second.provider_bindings["product"]["requested_model"] == "b-product"
        public = _public_run_data(original, first_run) + _public_run_data(updated, second_run)
        assert "provider-a-key-v1" not in public
        assert "provider-b-key-v2" not in public

def test_shared_provider_adapters_keep_two_active_runs_isolated(tmp_path):
    # 两个运行共用 Provider 适配器：要取消的运行的请求一直保持，另一个运行在这期间完成激活；
    # 之后取消要取消的运行，再释放请求。等待上限只用来防止测试一直等待，远大于正常用时，请求时限同样放宽
    wait_limit_sec = 120
    entered_cancel = Event()
    release_cancel = Event()
    replied_cancel = Event()

    def shared(body: dict[str, Any], _count: int) -> _Reply:
        task = body["input"][0]["content"]
        if "cancel-me" in task:
            entered_cancel.set()
            release_cancel.wait(wait_limit_sec)
            replied_cancel.set()
            return _error()
        payload = product_spec()
        payload.pop("kind")
        return _stream([_call("other-product", "submit_product_spec", payload)],
                       response_id="other-success", model="a-product-actual")

    with _provider_server("provider-a", "provider-a-key", shared) as (config_a, captures_a, errors_a), \
            _provider_server("provider-b", "provider-b-key", lambda _body, _count: _error()) as (config_b, _captures_b, _errors_b):
        system = LoopSystem(tmp_path, facade=_facade(
            config_a.base_url, config_b.base_url, timeout_sec=wait_limit_sec, credentials={
                "credential-a": CredentialMaterial("provider-a-key", version="a-v1"),
                "credential-b": CredentialMaterial("provider-b-key", version="b-v1"),
            }))
        cancel_run = system.create_run("cancel-me")
        other_run = system.create_run("finish-me")
        with ThreadPoolExecutor(max_workers=2) as pool:
            cancelled_future = pool.submit(system.activate_once, cancel_run)
            successful_future = pool.submit(system.activate_once, other_run)
            try:
                assert entered_cancel.wait(wait_limit_sec)
                successful = successful_future.result(timeout=wait_limit_sec)
                # 另一个运行完成激活时，要取消的运行的请求仍被保持，它的激活仍在等待回复
                assert not replied_cancel.is_set()
                assert not cancelled_future.done()
                cancelled = system.cancel(cancel_run)
            finally:
                release_cancel.set()
            cancelled_result = cancelled_future.result(timeout=wait_limit_sec)

        assert not errors_a
        assert successful.phase == "ENGINEERING"
        assert cancelled.phase == "FAILED" and cancelled.stop_reason == "cancelled"
        assert cancelled_result.stop_reason == "cancelled"
        assert len(captures_a) == 2
        assert all(item["authorization"] == "Bearer provider-a-key" for item in captures_a)
        assert all(item["body"]["model"] == "a-product" for item in captures_a)
        assert system.project(other_run).phase == "ENGINEERING"

def test_restart_resolves_the_current_credentials_for_the_next_request(tmp_path):
    # 上游拒绝凭据（HTTP 401）：请求带着重启后解析出的 Key 发出，运行进入待恢复，不因「凭据已不在本进程」结束
    def rejecting(_body: dict[str, Any], _count: int) -> _Reply:
        return _error(401)

    with _provider_server("provider-a", "provider-a-key", rejecting) as (config_a, captures_a, errors_a), \
            _provider_server("provider-b", "provider-b-key", rejecting) as (config_b, _captures_b, _errors_b):
        original = LoopSystem(tmp_path, facade=_facade(
            config_a.base_url, config_b.base_url, credentials={
                "credential-a": CredentialMaterial("provider-a-key", version="a-v1"),
                "credential-b": CredentialMaterial("provider-b-key", version="b-v1"),
            }))
        run_id = original.create_run("resolve the credentials in this process")
        original.store.close()

        restarted = LoopSystem(
            tmp_path,
            facade=_facade(
                config_a.base_url, config_b.base_url, credentials={
                    "credential-a": CredentialMaterial("provider-a-new-key", version="a-v2"),
                    "credential-b": CredentialMaterial("provider-b-new-key", version="b-v2"),
                }),
        )
        result = restarted.activate_once(run_id)

        # 重启以后按当前凭据来源解析：这次请求带着新的 Key 发往部门默认绑定的目标
        assert not errors_a
        assert [item["authorization"] for item in captures_a] == ["Bearer provider-a-new-key"]
        assert result.outcome == "running" and result.stop_reason is None
        requests = [event for event in restarted.store.list_events(run_id)
                    if event.type == EventType.MODEL_REQUESTED]
        assert [(item.payload["provider_config_id"], item.payload["credential_version"]) for item in requests] == [
            ("provider-a", "a-v2")]
        assert not any(event.type == EventType.RUN_FAILED for event in restarted.store.list_events(run_id))
        public = _public_run_data(restarted, run_id)
        for secret in ("provider-a-key", "provider-a-new-key", "provider-b-new-key"):
            assert secret not in public

def test_retry_stays_on_the_bound_provider_and_model(tmp_path):
    def retrying(body: dict[str, Any], count: int) -> _Reply:
        assert _department(body) == "product"
        if count == 1:
            return _error()
        payload = product_spec()
        payload.pop("kind")
        return _stream([_call("retry-product", "submit_product_spec", payload)],
                       response_id="retry-success", model="a-product-actual")

    with _provider_server("provider-a", "provider-a-key", retrying) as (config_a, captures_a, errors_a), \
            _provider_server("provider-b", "provider-b-key", lambda _body, _count: _error()) as (config_b, captures_b, errors_b):
        system = LoopSystem(tmp_path, facade=_facade(
            config_a.base_url, config_b.base_url, credentials={
                "credential-a": CredentialMaterial("provider-a-key", version="a-v1"),
                "credential-b": CredentialMaterial("provider-b-key", version="b-v1"),
            }), step_limits=MILLISECOND_RETRIES)
        run_id = system.create_run("retry this task")
        result = system.activate_once(run_id)

        assert not errors_a and not errors_b
        assert result.phase == "ENGINEERING", result.error
        assert len(captures_a) == 2 and not captures_b
        assert all(item["authorization"] == "Bearer provider-a-key" for item in captures_a)
        assert [item["body"]["model"] for item in captures_a] == ["a-product", "a-product"]
        requests = [item for item in result.model_requests if item["purpose"] == "work"]
        assert [item["attempt"] for item in requests] == [1, 2]
        assert [item["retry_of_step_id"] for item in requests] == [None, 1]
        assert all(item["provider_config_id"] == "provider-a" for item in requests)
        scheduled = [event for event in system.store.list_events(result.run_id) if event.type == EventType.MODEL_RETRY_SCHEDULED]
        assert len(scheduled) == 1
        assert scheduled[0].payload["provider_config_id"] == "provider-a"
        assert scheduled[0].payload["requested_model"] == "a-product"
        contexts = [event for event in system.store.list_events(result.run_id) if event.type == EventType.CONTEXT_ASSEMBLED]
        for event, captured in zip(contexts, captures_a):
            persisted = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**event.payload["request_ref"])))
            assert persisted["input"] == captured["body"]["input"]
            assert persisted["tools"] == captured["body"]["tools"]
            assert persisted.get("max_output_tokens") == captured["body"].get("max_output_tokens")
            assert "authorization" not in json_dumps(persisted).casefold()
            assert "provider-a-key" not in json_dumps(persisted)

def test_missing_returned_model_remains_unknown_in_request_trace(tmp_path):
    def without_model(body: dict[str, Any], _count: int) -> _Reply:
        assert _department(body) == "product"
        payload = product_spec()
        payload.pop("kind")
        return _stream([_call("product-without-model", "submit_product_spec", payload)],
                       response_id="without-model", model="")

    with _provider_server("provider-a", "provider-a-key", without_model) as (config_a, captures_a, errors_a), \
            _provider_server("provider-b", "provider-b-key", lambda _body, _count: _error()) as (config_b, _captures_b, _errors_b):
        system = LoopSystem(tmp_path, facade=_facade(
            config_a.base_url, config_b.base_url, credentials={
                "credential-a": CredentialMaterial("provider-a-key", version="a-v1"),
                "credential-b": CredentialMaterial("provider-b-key", version="b-v1"),
            }))
        run_id = system.create_run("trace missing actual model")
        result = system.activate_once(run_id)

        assert not errors_a and len(captures_a) == 1
        assert result.phase == "ENGINEERING", result.error
        assert result.model_requests[0]["requested_model"] == "a-product"
        assert result.model_requests[0]["actual_model"] is None
        assert result.actual_model is None

def test_terminal_returned_models_are_recorded_for_unreported_multi_step_work(tmp_path):
    def unreported(body: dict[str, Any], count: int) -> _Reply:
        assert _department(body) == "product"
        if count < 3:
            return _stream(
                [_message(f"progress-{count}", f"Progress update {count}.")],
                response_id=f"progress-response-{count}",
                model=f"a-product-actual-{count}",
                usage=False,
            )
        payload = product_spec()
        payload.pop("kind")
        return _stream(
            [_call("product-final", "submit_product_spec", payload)],
            response_id="product-final-response",
            model="a-product-actual-3",
            usage=False,
        )

    with _provider_server("provider-a", "provider-a-key", unreported) as (config_a, captures_a, errors_a), \
            _provider_server("provider-b", "provider-b-key", lambda _body, _count: _error()) as (config_b, _captures_b, _errors_b):
        system = LoopSystem(tmp_path, facade=_facade(
            config_a.base_url, config_b.base_url, credentials={
                "credential-a": CredentialMaterial("provider-a-key", version="a-v1"),
                "credential-b": CredentialMaterial("provider-b-key", version="b-v1"),
            }))
        run_id = system.create_run("retain returned models without usage")
        result = system.activate_once(run_id)

        assert not errors_a
        assert result.phase == "ENGINEERING", result.error
        assert len(captures_a) == 3
        assert [item["purpose"] for item in result.model_requests] == ["work", "work", "work"]
        assert [item["actual_model"] for item in result.model_requests] == [
            "a-product-actual-1", "a-product-actual-2", "a-product-actual-3",
        ]
        assert result.actual_model == "a-product-actual-3"
        assert result.token_used == 0

def test_failed_http_attempt_keeps_requested_identity_without_actual_model(tmp_path):
    def always_fails(body: dict[str, Any], _count: int) -> _Reply:
        assert _department(body) == "product"
        return _error()

    with _provider_server("provider-a", "provider-a-key", always_fails) as (config_a, captures_a, errors_a), \
            _provider_server("provider-b", "provider-b-key", lambda _body, _count: _error()) as (config_b, _captures_b, _errors_b):
        system = LoopSystem(tmp_path, facade=_facade(
            config_a.base_url, config_b.base_url, credentials={
                "credential-a": CredentialMaterial("provider-a-key", version="a-v1"),
                "credential-b": CredentialMaterial("provider-b-key", version="b-v1"),
            }), step_limits=MILLISECOND_RETRIES)
        run_id = system.create_run("provider failure has no response model")
        result = system.activate_once(run_id)

        assert not errors_a
        assert result.phase == "FAILED" and result.stop_reason == "provider_error"
        assert len(captures_a) == 3
        assert all(item["authorization"] == "Bearer provider-a-key" for item in captures_a)
        assert all(item["body"]["model"] == "a-product" for item in captures_a)
        assert [item["attempt"] for item in result.model_requests] == [1, 2, 3]
        assert all(item["provider_config_id"] == "provider-a" for item in result.model_requests)
        assert all(item["requested_model"] == "a-product" for item in result.model_requests)
        assert all(item["actual_model"] is None for item in result.model_requests)
        failures = [event for event in system.store.list_events(run_id) if event.type == EventType.MODEL_ATTEMPT_FAILED]
        assert len(failures) == 3
        assert all(event.provider == "provider-a" and event.model is None for event in failures)
        assert all(event.payload["requested_model"] == "a-product" for event in failures)

def test_cancelled_http_request_keeps_bound_identity_without_a_response(tmp_path):
    entered = Event()
    release = Event()

    def blocked(_body: dict[str, Any], _count: int) -> _Reply:
        entered.set()
        release.wait(5)
        return _error()

    with _provider_server("provider-a", "provider-a-key", blocked) as (config_a, captures_a, errors_a), \
            _provider_server("provider-b", "provider-b-key", lambda _body, _count: _error()) as (config_b, _captures_b, _errors_b):
        system = LoopSystem(tmp_path, facade=_facade(
            config_a.base_url, config_b.base_url, credentials={
                "credential-a": CredentialMaterial("provider-a-key", version="a-v1"),
                "credential-b": CredentialMaterial("provider-b-key", version="b-v1"),
            }))
        run_id = system.create_run("cancel this task")
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(system.activate_once, run_id)
            assert entered.wait(3)
            cancelled = system.cancel(run_id)
            release.set()
            result = future.result(timeout=5)

        assert cancelled.stop_reason == "cancelled"
        assert result.stop_reason == "cancelled"
        assert not errors_a
        assert len(captures_a) == 1
        events = system.store.list_events(run_id)
        failure = next(event for event in events if event.type == EventType.MODEL_ATTEMPT_FAILED)
        assert failure.provider == "provider-a" and failure.model is None
        assert failure.payload["provider_config_id"] == "provider-a"
        assert failure.payload["requested_model"] == "a-product"
        assert not any(event.type == EventType.MODEL_MESSAGE for event in events)
        public = _public_run_data(system, run_id)
        assert "provider-a-key" not in public and "provider-b-key" not in public

def test_small_bound_model_uses_its_own_compaction_request(tmp_path):
    state = {"read": False, "compactions": 0}

    def compacting(body: dict[str, Any], _count: int) -> _Reply:
        assert _department(body) == "product"
        if not body["tools"]:
            state["compactions"] += 1
            return _stream([_message(f"summary-{state['compactions']}", "The large file was read and is ready for the product decision.")],
                           response_id=f"compact-{state['compactions']}", model="a-product-actual")
        if not state["read"]:
            state["read"] = True
            return _stream([
                _call("read-large", "read_file", {"path": "large.txt"}),
            ], response_id="read-large", model="a-product-actual")
        payload = product_spec()
        payload.pop("kind")
        return _stream([_call("product-after-compaction", "submit_product_spec", payload)],
                       response_id="product-after-compaction", model="a-product-actual")

    with _provider_server("provider-a", "provider-a-key", compacting) as (config_a, captures_a, errors_a), \
            _provider_server("provider-b", "provider-b-key", lambda _body, _count: _error()) as (config_b, _captures_b, _errors_b):
        system = LoopSystem(
            tmp_path,
            facade=_facade(
                config_a.base_url, config_b.base_url, product_context_window=6_000,
                credentials={
                    "credential-a": CredentialMaterial("provider-a-key", version="a-v1"),
                    "credential-b": CredentialMaterial("provider-b-key", version="b-v1"),
                }),
        )
        run_id = system.create_run("compact product history")
        system.workspace(run_id).write_file("large.txt", "ORIGINAL " * 5_000)
        result = system.activate_once(run_id)

        assert not errors_a
        assert result.phase == "ENGINEERING", result.error
        assert state["read"] and state["compactions"] >= 1
        assert len(captures_a) == len(result.model_requests)
        assert all(item["body"]["model"] == "a-product" for item in captures_a)
        purposes = [item["purpose"] for item in result.model_requests]
        assert purposes[0] == purposes[-1] == "work"
        assert all(purpose == "compaction" for purpose in purposes[1:-1])
        assert result.compactions
        # Each summary request spends what the 6000-token window leaves after its input, capped by the
        # model's declared 1000; the old fixed 15% reserve would have allowed only 900.
        compaction_manifests = [manifest for manifest in result.manifests if manifest.purpose == "compaction"]
        assert len(compaction_manifests) == len(result.compactions)
        for manifest, item in zip(compaction_manifests, result.compactions):
            assert manifest.max_output_tokens == item["max_output_tokens"]
            assert manifest.max_output_tokens == min(1_000, 6_000 - manifest.input_token_estimate) > 900
            assert manifest.input_token_estimate + manifest.max_output_tokens <= 6_000
        assert all(item["provider_config_id"] == "provider-a" for item in result.compactions)
        assert all(item["model_id"] == "model-a-product" for item in result.compactions)
        assert all(item["body"]["tools"] == [] for item, purpose in zip(captures_a[1:-1], purposes[1:-1]))
        assert all(manifest.budget == 6_000 for manifest in result.manifests)
        audit = summarize_run(system, run_id, scenario="d18-small-window")
        assert audit["model_input_audit"]["status"] == "verified", audit["model_input_audit"]
        assert audit["manifest_boundary"] is True
        assert audit["context_isolated"] is True
        assert audit["replay_consistent"] is True

_MIXED_SECRETS = {"credential-p": "secret-messages-p", "credential-e": "secret-chat-e",
                  "credential-q": "secret-responses-q"}

def _mixed_protocol_facade(product_url: str, engineering_url: str, quality_url: str) -> ProviderFacade:
    # 三个部门各绑一条协议：产品 Messages（小窗口触发压缩）、工程 Chat Completions、质检 Responses
    facade = ProviderFacade(credentials=CredentialChain(use_env=False))
    facade.store_document({
        "providers": [
            {"id": "provider-p", "name": "Messages 服务", "base_url": product_url,
             "credential_ref": "credential-p", "timeout_sec": 10, "preset_id": "opencode-go"},
            {"id": "provider-e", "name": "Chat 服务",
             "base_url": engineering_url,
             "credential_ref": "credential-e", "timeout_sec": 10, "preset_id": "opencode-go"},
            {"id": "provider-q", "name": "Responses 服务",
             "base_url": quality_url,
             "credential_ref": "credential-q", "timeout_sec": 10, "preset_id": "opencode-go"},
        ],
        "models": [
            {"id": "model-p", "provider_id": "provider-p", "model": "p-model",
             "protocol": "messages",
             "context_window": 6_000, "max_output_tokens": 1_000},
            {"id": "model-e", "provider_id": "provider-e", "model": "e-model",
             "protocol": "chat_completions",
             "context_window": 20_000, "max_output_tokens": 1_000},
            {"id": "model-q", "provider_id": "provider-q", "model": "q-model",
             "protocol": "responses",
             "context_window": 20_000, "max_output_tokens": 1_000},
        ],
        "bindings": {
            "product": {"provider_id": "provider-p", "model_id": "model-p"},
            "engineering": {"provider_id": "provider-e", "model_id": "model-e"},
            "quality": {"provider_id": "provider-q", "model_id": "model-q"},
        },
    })
    for ref, secret in _MIXED_SECRETS.items():
        facade.set_credential_override(ref, CredentialMaterial(secret, version=f"{ref}-v1"))
    for provider_id, model_id, model in (("provider-p", "model-p", "p-model"),
                                         ("provider-e", "model-e", "e-model"),
                                         ("provider-q", "model-q", "q-model")):
        facade.record_admission(provider_id, model_id, admitted_model=model)
    return facade

def test_mixed_protocol_task_keeps_work_compaction_retry_and_session_with_each_department(tmp_path):
    state = {"read": False}

    def product(body: dict[str, Any], count: int) -> _Reply:
        # 压缩请求不带工具；工作请求先读大文件，压缩后提交规格
        assert body["model"] == "p-model"
        if not body.get("tools"):
            return _messages_stream([], message_id=f"p-compact-{count}", model="p-model-actual",
                                    text="The large file was read and is ready for the product decision.")
        if not state["read"]:
            state["read"] = True
            return _messages_stream([_call("read-large", "read_file", {"path": "large.txt"})],
                                    message_id="p-read", model="p-model-actual")
        payload = product_spec()
        payload.pop("kind")
        return _messages_stream([_call("product-spec", "submit_product_spec", payload)],
                                message_id="p-spec", model="p-model-actual")

    def engineering(body: dict[str, Any], count: int) -> _Reply:
        assert body["model"] == "e-model"
        if count == 1:
            return _error()
        if not body.get("tools"):
            return _chat_stream([], response_id=f"e-compact-{count}", model="e-model-actual")
        # 第一次交付拿过期依据被拒，下一次激活按当前版本重交（工单 #471）：
        # 被拒的提交留在本部门历史里，工程的第三次请求看得到它，别的部门看不到
        basis = "stale" if count == 2 else _spec_hash(body)
        payload = delivery(check_names=["smoke"],
                           basis_product_spec_hash=basis)
        payload.pop("kind")
        return _chat_stream([
            _call("write-echo", "write_file", {"path": "src/echo.py", "content": "import sys\nprint(sys.argv[1])\n"}),
            _call("engineering-check", "run_check",
                  {"name": "smoke", "command": f"\"{sys.executable.replace(chr(92), '/')}\" -c \"print('engineering')\""}),
            _call("engineering-delivery", "submit_delivery", payload),
        ], response_id=f"e-delivery-{count}", model="e-model-actual")

    def quality(body: dict[str, Any], count: int) -> _Reply:
        assert body["model"] == "q-model"
        payload = review("release", "The delivery passes.", checks=["smoke"], defects=[],
                         basis_delivery_spec_hash=_material_hash(body, "current_delivery_spec", "content_hash"))
        return _stream([
            _call("quality-check", "run_check",
                  {"name": "smoke", "command": f"\"{sys.executable.replace(chr(92), '/')}\" -c \"print('quality')\""}),
            _call("quality-review", "submit_review", payload),
        ], response_id=f"q-review-{count}", model="q-model-actual")

    with _provider_server("provider-p", "unused", product) as (config_p, captures_p, errors_p), \
            _provider_server("provider-e", "unused", engineering) as (config_e, captures_e, errors_e), \
            _provider_server("provider-q", "unused", quality) as (config_q, captures_q, errors_q):
        # 三条连接都带服务方案：请求基址按各自访问定义的协议取自预置表（ADR-0033），
        # 测试把预置表中这三种协议的基址分别指向各自部门的本机上游
        with preset_base_urls({"messages": config_p.base_url,
                               "chat_completions": config_e.base_url,
                               "responses": config_q.base_url}):
            system = LoopSystem(tmp_path, facade=_mixed_protocol_facade(
                config_p.base_url, config_e.base_url, config_q.base_url), step_limits=MILLISECOND_RETRIES)
            run_id = system.create_run("build an echo command")
            system.workspace(run_id).write_file("large.txt", "ORIGINAL " * 5_000)
            result = system.run_until_stop(run_id)
            other_run = system.create_run("a second task")

    assert not errors_p and not errors_e and not errors_q
    assert result.phase == "DONE", result.error
    # 每条协议按自己的路径与认证方式发送
    assert {item["path"] for item in captures_p} == {"/v1/messages"}
    assert {item["path"] for item in captures_e} == {"/v1/chat/completions"}
    assert {item["path"] for item in captures_q} == {"/v1/responses"}
    assert {item["headers"].get("x-api-key") for item in captures_p} == {_MIXED_SECRETS["credential-p"]}
    assert {item["authorization"] for item in captures_e} == {f"Bearer {_MIXED_SECRETS['credential-e']}"}
    assert {item["authorization"] for item in captures_q} == {f"Bearer {_MIXED_SECRETS['credential-q']}"}

    # 工作、压缩与重试都记在发起请求的部门及其绑定的连接、协议与模型上
    bound = {"product": ("provider-p", "model-p", "messages", "p-model"),
             "engineering": ("provider-e", "model-e", "chat_completions", "e-model"),
             "quality": ("provider-q", "model-q", "responses", "q-model")}
    requests = result.model_requests
    assert len(requests) == len(captures_p) + len(captures_e) + len(captures_q)
    for item in requests:
        assert (item["provider_config_id"], item["model_id"], item["requested_protocol"],
                item["requested_model"]) == bound[item["department"]]
    product_purposes = [item["purpose"] for item in requests if item["department"] == "product"]
    assert product_purposes[0] == product_purposes[-1] == "work"
    assert set(product_purposes[1:-1]) == {"compaction"}
    assert result.compactions
    assert {(item["department"], item["provider_config_id"], item["model_id"]) for item in result.compactions} == {
        ("product", "provider-p", "model-p")}
    assert all(not item["body"].get("tools") for item in captures_p[1:-1])
    engineering_requests = [item for item in requests if item["department"] == "engineering"]
    assert [item["attempt"] for item in engineering_requests] == [1, 2, 1]
    assert engineering_requests[1]["retry_of_step_id"] == engineering_requests[0]["step_id"]
    scheduled = [event for event in system.store.list_events(run_id) if event.type == EventType.MODEL_RETRY_SCHEDULED]
    assert [(event.department, event.payload["provider_config_id"]) for event in scheduled] == [("engineering", "provider-e")]
    assert [item["purpose"] for item in requests if item["department"] == "quality"] == ["work"]

    # 模型输出按统一输出项记录，跨激活回放的历史里只有真实的消息、工具调用与结果
    for event in system.store.list_events(run_id):
        if event.type == EventType.MODEL_MESSAGE:
            item = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**event.payload["message_ref"])))
            assert item.get("type") in {"message", "function_call"}, item
    delivery_messages = captures_e[-1]["body"]["messages"]
    assert all(message.get("content") != "" for message in delivery_messages)
    # 上一次激活的 write_file、run_check 与被拒的提交都在历史里：最后一条工具调用是这次交付，
    # 它的结果紧随其后，之前的结果也都在同一份跨激活历史里
    call_index = next(index for index, message in enumerate(delivery_messages)
                      if message.get("tool_calls") and any(
                          call["id"] == "engineering-delivery" for call in message["tool_calls"]))
    assert [call["id"] for call in delivery_messages[call_index]["tool_calls"]] == [
        "write-echo", "engineering-check", "engineering-delivery"]
    tool_messages = [message for message in delivery_messages if message["role"] == "tool"]
    assert [message["tool_call_id"] for message in tool_messages] == [
        "write-echo", "engineering-check", "engineering-delivery"]
    assert all(message.get("content") != "" for message in tool_messages)

    # 会话身份：同部门跨激活、重试与压缩不变；部门之间、任务之间互相隔离
    def run_sessions(target_run: str) -> dict[str, str]:
        created = next(event for event in system.store.list_events(target_run) if event.type == EventType.RUN_CREATED)
        return created.payload["sessions"]

    sessions = run_sessions(run_id)
    assert {item["headers"]["x-opencode-session"] for item in captures_p} == {sessions["product"]}
    assert {item["headers"]["x-opencode-session"] for item in captures_e} == {sessions["engineering"]}
    assert {item["headers"]["x-opencode-session"] for item in captures_q} == {sessions["quality"]}
    assert len(set(sessions.values())) == 3
    assert set(run_sessions(other_run).values()).isdisjoint(sessions.values())

    public = _public_run_data(system, run_id)
    assert not any(secret in public for secret in _MIXED_SECRETS.values())
    audit = summarize_run(system, run_id, scenario="mixed-protocols")
    assert audit["model_input_audit"]["status"] == "verified", audit["model_input_audit"]["notes"]
    assert audit["context_isolated"] is True
    assert audit["replay_consistent"] is True
    assert audit["fake_used"] is False
