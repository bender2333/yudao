"""Exercise the official SDK against local HTTP/SSE, without a model service."""

import asyncio
import json
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

import pytest
import httpx
from openai import APIConnectionError, AsyncOpenAI, DefaultAsyncHttpxClient

from harness.adapters.base import ProviderError
from harness.providers import ResponsesConfig
from harness.tests.protocol_helpers import ConnectionLoop, ResponsesAdapter, model_call
from harness.context import ContextAssembler
from harness.department_prompts import DEFAULT_PROMPTS
from harness.models import ArtifactRef, DepartmentPrompt, RunProjection, hash_bytes
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.tests.helpers import FAST_RETRIES
from harness.tools import host_tool_definitions, tools_for


KEY = "local-sdk-test-key"
TEXT = {"id": "msg-one", "type": "message", "role": "assistant", "status": "completed",
        "content": [{"type": "output_text", "text": "Local model output", "annotations": []}]}
CALL = {"id": "fc-one", "type": "function_call", "name": "read_file", "call_id": "call-one",
        "arguments": '{"path":"proof.txt"}', "status": "completed"}
REASONING = {"id": "rs-one", "type": "reasoning", "summary": [], "encrypted_content": "opaque-causal-reasoning"}
RAW_USAGE = {"input_tokens": 100, "output_tokens": 30, "total_tokens": 130,
             "input_tokens_details": {"cached_tokens": 80}, "output_tokens_details": {"reasoning_tokens": 12}}
TOOLS = [{"type": "function", "name": "read_file", "description": "Read a file",
          "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
          "strict": False}]


def _submit_stream(response_id="resp-submit"):
    proposal = product_spec()
    proposal.pop("kind")
    call = {
        "id": "fc-submit",
        "type": "function_call",
        "name": "submit_product_spec",
        "call_id": "call-submit",
        "arguments": json.dumps(proposal),
        "status": "completed",
    }
    return _stream([call], response_id=response_id)


def _request(*, session_id="session", history=None, max_output_tokens=None, attempt_id="activation:1:attempt-1"):
    prompt_text = DEFAULT_PROMPTS["product"]
    prompt_hash = hash_bytes(prompt_text.encode("utf-8"))
    prompt_ref = ArtifactRef("department_prompt", prompt_hash, f"run/{prompt_hash[7:9]}/{prompt_hash[7:]}")
    projection = RunProjection(task="local request", department_prompts={
        "product": DepartmentPrompt("product", 1, prompt_text, prompt_ref, "initial-prompt"),
    })
    context = ContextAssembler().assemble(
        projection, department="product", session_id=session_id, activation_id="activation",
    )
    return model_call([*context.input_items, *(history or [])], TOOLS, session_id=session_id,
                      max_output_tokens=max_output_tokens, attempt_id=attempt_id)


def _decoded(observations):
    # 请求、输出条目与用量；解码后的流事件与完整响应对象是原始证据，不在这里核对
    return [event for event in observations if event.kind not in {"stream_event", "response"}]


def _event(kind, **body):
    return f"event: {kind}\ndata: {json.dumps({'type': kind, **body})}\n\n".encode()


def _response(output=None, *, status="completed", usage=RAW_USAGE, response_id="resp-one", error=None):
    return {"id": response_id, "object": "response", "created_at": 1, "status": status, "model": "local-model",
            "output": [TEXT] if output is None else output, "usage": usage, "error": error,
            "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None}


def _stream(output=None, *, status="completed", usage=RAW_USAGE, response_id="resp-one", duplicate=False, terminal=True):
    response = _response(output, status=status, usage=usage, response_id=response_id)
    frames = [_event("response.created", response={**response, "status": "in_progress", "output": [], "usage": None}, sequence_number=0)]
    for index, item in enumerate(response["output"]):
        frame = _event("response.output_item.done", item=item, output_index=index, sequence_number=index + 1)
        frames.append(frame)
        if duplicate:
            frames.append(frame)
    if terminal:
        frames.append(_event(f"response.{status}", response=response, sequence_number=len(frames)))
    return b"".join(frames)


def _send(handler, body, *, status=200, content_type="text/event-stream", headers=None):
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    for name, value in (headers or {}).items():
        handler.send_header(name, value)
    handler.end_headers()
    handler.wfile.write(body)
    handler.wfile.flush()


@contextmanager
def _server(replies):
    captures, paths, authorization = [], [], []
    received = Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captures.append(body)
            paths.append(self.path)
            authorization.append(self.headers.get("Authorization") == f"Bearer {KEY}")
            received.set()
            if len(captures) > len(replies):
                _send(self, b'{"error":{"message":"unexpected retry"}}', status=500, content_type="application/json")
                return
            reply = replies[len(captures) - 1]
            try:
                if callable(reply):
                    reply(self, body)
                else:
                    _send(self, reply)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    worker.start()
    config = ResponsesConfig(model="local-model", api_key=KEY, provider="local-stub",
                             base_url=f"http://127.0.0.1:{server.server_port}/v1", timeout_sec=5)
    try:
        yield config, captures, paths, authorization, received
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


@contextmanager
def _keepalive_server(key=KEY, replies=None):
    captures, client_ports, authorizations, request_meta, errors = [], [], [], [], []
    replies = [_stream([TEXT]), _stream([TEXT])] if replies is None else list(replies)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def handle(self):
            try:
                super().handle()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                captures.append(body)
                client_ports.append(self.client_address[1])
                authorizations.append(self.headers.get("Authorization"))
                request_meta.append({
                    "version": self.request_version,
                    "connection": self.headers.get("Connection"),
                    "close_before_response": self.close_connection,
                })
                reply = replies[len(captures) - 1]
                if callable(reply):
                    reply = reply(self, body)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(reply)))
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                self.wfile.write(reply)
                self.wfile.flush()
            except BaseException as exc:
                errors.append(exc)
                self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    worker.start()
    config = ResponsesConfig(model="local-model", api_key=key, provider="local-stub",
                             base_url=f"http://127.0.0.1:{server.server_port}/v1", timeout_sec=5)
    try:
        yield config, captures, client_ports, authorizations, request_meta, errors
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


@contextmanager
def _tail_server(mode, *, timeout_sec=5):
    captures, client_ports, terminal_sent, release, errors = [], [], Event(), Event(), []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def handle(self):
            try:
                super().handle()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                captures.append(body)
                client_ports.append(self.client_address[1])
                response = _stream([TEXT])
                if len(captures) > 1:
                    self._send(response)
                    return
                if mode == "delayed":
                    tail = b": delayed tail\n\n"
                    terminal_end = response.find(b"\n\n", response.rfind(b"event: response.completed")) + 2
                    first, second = response[:terminal_end], response[terminal_end:] + tail
                    self._send(first, content_length=len(response) + len(tail), keep_open=True)
                    terminal_sent.set()
                    time.sleep(0.02)
                    self.wfile.write(second)
                    self.wfile.flush()
                    return
                if mode == "done":
                    self._send(response + b"data: [DONE]\n\n", keep_open=True)
                    terminal_sent.set()
                    return
                if mode == "hold":
                    self._send(response, content_length=len(response) + 10, keep_open=True)
                    terminal_sent.set()
                    release.wait(5)
                    self.close_connection = True
                    return
                if mode == "truncated":
                    self._send(response, content_length=len(response) + 10, keep_open=True)
                    terminal_sent.set()
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                self._send(response)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return
            except BaseException as exc:
                errors.append(exc)
                self.close_connection = True

        def _send(self, response, *, content_length=None, keep_open=False):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(response) if content_length is None else content_length))
            self.send_header("Connection", "keep-alive" if keep_open else "close")
            self.end_headers()
            self.wfile.write(response)
            self.wfile.flush()
            if not keep_open:
                self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    worker.start()
    config = ResponsesConfig(model="local-model", api_key=KEY, provider="local-stub",
                             base_url=f"http://127.0.0.1:{server.server_port}/v1", timeout_sec=timeout_sec)
    try:
        yield config, captures, client_ports, terminal_sent, release, errors
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def _mock_transport(monkeypatch, handler):
    def client_factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("harness.providers.responses.DefaultAsyncHttpxClient", client_factory)


async def _trace_failure(request, event_name, error):
    trace = request.extensions.get("trace")
    assert trace is not None
    await trace(f"{event_name}.started", {})
    await trace(f"{event_name}.failed", {"exception": error})


def test_sdk_sends_exact_host_context_and_preserves_stateless_tool_protocol(tmp_path, monkeypatch):
    canary = "UNRELATED_AGENT_CONTEXT_682947"
    for name in ["AGENTS.md", "CLAUDE.md", ".env", "models.yml"]:
        (tmp_path / name).write_text(canary, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path))
    monkeypatch.setenv("YUDAO_OMP_COMMAND", canary)
    with _server([_stream([REASONING, CALL]), _stream([TEXT], response_id="resp-two")]) as (config, captures, paths, auth, _):
        adapter = ResponsesAdapter(config)
        first = _request()
        original_input = list(first.input_items)
        result = adapter.complete(first)
        assert len(captures) == 1
        assert result.output == [REASONING, CALL]
        assert not (tmp_path / "proof.txt").exists()
        assert result.provider == "local-stub" and result.model == "local-model"
        assert first.input_items == original_input
        history = [*result.output, {"type": "function_call_output", "call_id": CALL["call_id"], "output": "host evidence"}]
        second = _request(history=history)
        adapter.complete(second)
        assert paths == ["/v1/responses", "/v1/responses"]
        assert all(auth)
        for body, request in zip(captures, [first, second]):
            assert body == {"model": "local-model", "input": request.input_items, "tools": TOOLS, "store": False, "stream": True}
            assert canary not in json.dumps(body)
        assert captures[1]["input"][-3:] == history


@pytest.mark.parametrize("failure_kind", ["connection", "timeout", "429", "500", "partial_stream"])
def test_local_http_transient_failure_retries_same_input_then_succeeds(tmp_path, monkeypatch, failure_kind):
    adapters = []

    def failure(handler, _body):
        if failure_kind == "connection":
            handler.connection.shutdown(socket.SHUT_RDWR)
            handler.connection.close()
        elif failure_kind == "timeout":
            # First request arrived, so CONNECT already succeeded. Raise the retry
            # budget immediately and stay silent past the client deadline; do not
            # wait for the retry on this handler.
            adapters[0].config = replace(adapters[0].config, timeout_sec=5)
            time.sleep(2)
        elif failure_kind == "partial_stream":
            _send(handler, _stream([CALL], terminal=False))
        else:
            status = int(failure_kind)
            _send(handler, json.dumps({"error": {"code": "rate_limit_exceeded" if status == 429 else "server_error"}}).encode(),
                  status=status, content_type="application/json")

    def success(handler, _body):
        _send(handler, _submit_stream())

    with _server([failure, success]) as (config, captures, *_):
        if failure_kind == "timeout":
            # Local plaintext HTTP does not need certifi. Skip it so CONNECT fits
            # in a 1s budget on Windows, then let the server outlast that deadline.
            monkeypatch.setattr("harness.providers.responses.DefaultAsyncHttpxClient",
                                lambda **kwargs: DefaultAsyncHttpxClient(verify=False, **kwargs))
            config = replace(config, timeout_sec=1)
        adapters.append(ResponsesAdapter(config))
        system = LoopSystem.for_testing(tmp_path, adapters[0], step_limits=FAST_RETRIES)
        run_id = system.create_run("local retry")
        result = system.activate_once(run_id)

    assert result.phase == "ENGINEERING", result.error
    assert len(captures) == 2 and captures[0] == captures[1]
    events = system.store.list_events(run_id)
    failed = [item for item in events if item.type == "model_attempt_failed"]
    assert len(failed) == 1 and failed[0].payload["retryable"] is True
    if failure_kind == "partial_stream":
        assert "call-one" not in json.dumps(captures[1])
        assert not any(item.type == "tool_started" and item.payload.get("id") == "call-one" for item in events)


def test_server_overloaded_stream_error_retries_after_partial_output_without_running_tools(tmp_path):
    partial = _stream([CALL], terminal=False) + _event(
        "error", code="server_is_overloaded", message=KEY,
    )
    with _server([partial, _submit_stream()]) as (config, captures, *_):
        system = LoopSystem.for_testing(tmp_path, ResponsesAdapter(config), step_limits=FAST_RETRIES)
        result = system.activate_once(system.create_run("retry provider overload"))

    assert result.phase == "ENGINEERING", result.error
    assert len(captures) == 2
    assert "call-one" not in json.dumps(captures[1])
    events = system.store.list_events(result.run_id)
    failed = [event for event in events if event.type == "model_attempt_failed"]
    assert len(failed) == 1
    assert failed[0].payload["retryable"] is True
    assert failed[0].payload["diagnostics"]["error_code"] == "server_is_overloaded"
    assert not any(event.type == "tool_started" and event.payload.get("id") == "call-one" for event in events)


def test_server_overloaded_stream_error_is_exhausted_at_three_attempts(tmp_path):
    overload = _event("error", code="server_is_overloaded", message="overloaded")
    with _server([overload, overload, overload]) as (config, captures, *_):
        system = LoopSystem.for_testing(tmp_path, ResponsesAdapter(config), step_limits=FAST_RETRIES)
        result = system.activate_once(system.create_run("provider overload exhaustion"))

    assert result.phase == "FAILED" and result.stop_reason == "provider_error"
    assert len(captures) == 3
    events = system.store.list_events(result.run_id)
    failed = [event for event in events if event.type == "model_attempt_failed"]
    scheduled = [event for event in events if event.type == "model_retry_scheduled"]
    assert len(failed) == 3 and len(scheduled) == 2
    assert all(event.payload["retryable"] is True for event in failed)
    assert all(event.payload["diagnostics"]["error_code"] == "server_is_overloaded" for event in failed)
    assert failed[-1].payload["will_retry"] is False


@pytest.mark.parametrize("nested", [False, True])
def test_server_overloaded_stream_error_shapes_are_retryable_and_sanitized(nested):
    body = {"code": "server_is_overloaded", "type": "server_error", "message": KEY}
    event = _event("error", **({"error": body} if nested else {"code": body["code"], "message": body["message"]}))
    with _server([event]) as (config, captures, *_):
        with pytest.raises(ProviderError) as caught:
            ResponsesAdapter(config).complete(_request())

    assert caught.value.retryable is True
    assert caught.value.reason == "provider_error"
    assert caught.value.diagnostics == {"error_code": "server_is_overloaded"}
    assert KEY not in str(caught.value) and KEY not in str(caught.value.diagnostics)
    assert len(captures) == 1


def test_completed_items_and_final_usage_are_observed_once():
    observations = []
    with _server([_stream([REASONING, CALL, TEXT], duplicate=True)]) as (config, *_):
        result = ResponsesAdapter(config).complete(_request(), observations.append)
    assert [event.id for event in observations if event.kind == "message"] == ["rs-one", "fc-one", "msg-one"]
    reports = [event for event in observations if event.kind == "usage"]
    assert len(reports) == 1 and reports[0].usage == result.usage
    assert reports[0].payload["usage"] == RAW_USAGE
    assert result.usage.input_tokens == 20
    assert result.usage.cache_read_tokens == 80
    assert result.usage.output_tokens == 30
    assert result.usage.total_tokens == 130
    assert result.usage.cost == 0.0
    assert result.usage.cost_reported is False
    assert result.usage.reported is True
    assert result.output == [REASONING, CALL, TEXT]


def test_request_observation_matches_the_json_body_sent_by_httpx():
    observations = []
    with _server([_stream([TEXT])]) as (config, captures, *_):
        ResponsesAdapter(config).complete(_request(attempt_id="logical-request:1:attempt-1"), observations.append)
    requests = [event for event in observations if event.kind == "request"]
    assert len(requests) == 1
    assert requests[0].id == "logical-request:1:attempt-1"
    assert requests[0].payload == captures[0]
    assert requests[0].provider == "local-stub"
    assert requests[0].model == "local-model"
    assert "Authorization" not in requests[0].payload


def test_request_observation_failure_stops_before_network_send():
    def reject(_observation):
        raise OSError("request evidence could not be persisted")

    with _server([_stream([TEXT])]) as (config, captures, *_):
        with pytest.raises(OSError, match="request evidence could not be persisted"):
            ResponsesAdapter(config).complete(_request(), reject)
    assert captures == []


@pytest.mark.parametrize(
    "kind,event_name,expected_phase,expected_cause",
    [
        ("connection", "connection.connect_tcp", "connect_tcp", "ConnectError"),
        ("tls", "connection.start_tls", "start_tls", "SSLCertVerificationError"),
        ("read", "http11.receive_response_body", "receive_response_body", "ReadError"),
        ("timeout", "http11.receive_response_headers", "receive_response_headers", "ReadTimeout"),
    ],
)
def test_transport_failure_diagnostics_capture_safe_trace_boundary(
    monkeypatch, kind, event_name, expected_phase, expected_cause,
):
    secret = "transport-diagnostic-secret"
    calls = []

    async def failure(request):
        calls.append(request)
        if kind == "tls":
            error = httpx.ConnectError(secret, request=request)
            trace_error = ssl.SSLCertVerificationError(secret)
        elif kind == "read":
            error = httpx.ReadError(secret, request=request)
            trace_error = error
        elif kind == "timeout":
            error = httpx.ReadTimeout(secret, request=request)
            trace_error = error
        else:
            error = httpx.ConnectError(secret, request=request)
            trace_error = error
        await _trace_failure(request, event_name, trace_error)
        raise error

    _mock_transport(monkeypatch, failure)
    config = ResponsesConfig(model="local-model", api_key=KEY,
                             base_url="http://mock.test/v1", timeout_sec=5)
    with pytest.raises(ProviderError) as caught:
        ResponsesAdapter(config).complete(_request())

    diagnostics = caught.value.diagnostics
    assert len(calls) == 1
    assert caught.value.retryable is True
    assert diagnostics == {
        "error_type": "timeout" if kind == "timeout" else "connection",
        "trace_available": True,
        "transport_phase": expected_phase,
        "transport_event": f"{event_name}.failed",
        "cause_type": expected_cause,
    }
    assert secret not in repr(diagnostics)


def test_transport_failure_without_trace_keeps_boundary_unknown_and_makes_one_call(monkeypatch):
    secret = "untraced-transport-secret"
    calls = []

    async def failure(request):
        calls.append(request)
        raise httpx.ConnectError(secret, request=request)

    _mock_transport(monkeypatch, failure)
    config = ResponsesConfig(model="local-model", api_key=KEY,
                             base_url="http://mock.test/v1", timeout_sec=5)
    with pytest.raises(ProviderError) as caught:
        ResponsesAdapter(config).complete(_request())

    diagnostics = caught.value.diagnostics
    assert len(calls) == 1
    assert caught.value.retryable is True
    assert diagnostics["trace_available"] is False
    assert diagnostics["transport_phase"] == "unknown"
    assert diagnostics["transport_event"] == "unknown"
    assert diagnostics["cause_type"] == "ConnectError"
    assert secret not in repr(diagnostics)


def test_transport_trace_state_is_isolated_between_adapter_calls(monkeypatch):
    calls = []

    async def fail_once_then_succeed(request):
        calls.append(request)
        if len(calls) == 1:
            error = httpx.ConnectError("first failure", request=request)
            await _trace_failure(request, "connection.connect_tcp", error)
            raise error
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=_stream([TEXT]))

    _mock_transport(monkeypatch, fail_once_then_succeed)
    config = ResponsesConfig(model="local-model", api_key=KEY,
                             base_url="http://mock.test/v1", timeout_sec=5)
    adapter = ResponsesAdapter(config)
    with pytest.raises(ProviderError) as caught:
        adapter.complete(_request(session_id="first"))
    result = adapter.complete(_request(session_id="second"))

    assert len(calls) == 2
    assert caught.value.diagnostics["transport_phase"] == "connect_tcp"
    assert result.output == [TEXT]


def test_connection_loop_reuses_http11_connection_across_adapters():
    with _keepalive_server() as (config, captures, client_ports, authorizations, meta, errors):
        with ConnectionLoop() as loop:
            first = ResponsesAdapter(config, loop=loop).complete(_request(session_id="first"))
            second = ResponsesAdapter(config, loop=loop).complete(_request(session_id="second"))

    assert not errors
    assert first.output == second.output == [TEXT]
    assert len(captures) == 2
    assert len(set(client_ports)) == 1, meta
    assert authorizations == [f"Bearer {KEY}", f"Bearer {KEY}"]


def test_connection_loop_keeps_same_url_different_credentials_separate():
    first_key = "first-provider-credential"
    second_key = "second-provider-credential"
    with _keepalive_server(key=first_key) as (config, captures, client_ports, authorizations, _meta, errors):
        second_config = replace(config, api_key=second_key, model="second-model")
        with ConnectionLoop() as loop:
            ResponsesAdapter(config, loop=loop).complete(_request(session_id="first"))
            ResponsesAdapter(second_config, loop=loop).complete(_request(session_id="second"))
            assert len(loop.connections._clients) == 2

    assert not errors
    assert len(captures) == 2
    assert len(set(client_ports)) == 2
    assert authorizations == [f"Bearer {first_key}", f"Bearer {second_key}"]


def test_connection_loop_drops_failed_keepalive_connection_before_next_request():
    def close_connection(handler, _body):
        handler.close_connection = True
        handler.connection.shutdown(socket.SHUT_RDWR)
        handler.connection.close()

    with _keepalive_server(replies=[close_connection, _stream([TEXT])]) as (
        config, captures, client_ports, _authorizations, _meta, errors,
    ):
        with ConnectionLoop() as loop:
            with pytest.raises(ProviderError):
                ResponsesAdapter(config, loop=loop).complete(_request(session_id="failed"))
            result = ResponsesAdapter(config, loop=loop).complete(_request(session_id="recovered"))

    assert result.output == [TEXT]
    assert len(captures) == 2
    assert len(set(client_ports)) == 2
    assert errors


def test_connection_loop_closes_clients_when_it_closes(monkeypatch):
    closed = []
    original_close = AsyncOpenAI.close

    async def close(client):
        closed.append(client)
        await original_close(client)

    monkeypatch.setattr(AsyncOpenAI, "close", close)
    with _keepalive_server() as (config, _captures, _client_ports, _authorizations, _meta, _errors):
        loop = ConnectionLoop()
        ResponsesAdapter(config, loop=loop).complete(_request())
        assert closed == []
        loop.close()
    assert len(closed) == 1


def test_completed_stream_with_segmented_eof_is_reused_and_does_not_observe_tail():
    first_observations, second_observations = [], []
    with _tail_server("delayed") as (config, captures, client_ports, terminal_sent, _release, errors):
        with ConnectionLoop() as loop:
            first = ResponsesAdapter(config, loop=loop).complete(
                _request(session_id="first"), first_observations.append,
            )
            assert terminal_sent.is_set()
            second = ResponsesAdapter(config, loop=loop).complete(
                _request(session_id="second"), second_observations.append,
            )

    assert not errors
    assert first.output == second.output == [TEXT]
    assert len(captures) == 2
    assert len(set(client_ports)) == 1
    assert [event.kind for event in _decoded(first_observations)] == ["request", "message", "usage"]
    assert [event.kind for event in _decoded(second_observations)] == ["request", "message", "usage"]


def test_completed_stream_with_done_marker_finishes_promptly_but_does_not_reuse_connection():
    with _tail_server("done") as (config, captures, client_ports, terminal_sent, _release, errors):
        with ConnectionLoop() as loop:
            started = time.monotonic()
            first = ResponsesAdapter(config, loop=loop).complete(_request(session_id="first"))
            assert terminal_sent.is_set()
            second = ResponsesAdapter(config, loop=loop).complete(_request(session_id="second"))

    assert not errors
    assert first.output == second.output == [TEXT]
    assert len(captures) == 2
    assert len(set(client_ports)) == 2
    assert time.monotonic() - started < 1


def test_terminal_near_request_deadline_is_not_reclassified_during_drain(monkeypatch):
    monkeypatch.setattr("openai._base_client.get_platform", lambda: "test")
    monkeypatch.setattr("harness.providers.responses._STREAM_DRAIN_TIMEOUT_SEC", 0.5)
    body = _stream([TEXT])
    closed = Event()

    class HoldingStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(0)
            yield body
            await asyncio.Event().wait()

        async def aclose(self):
            closed.set()

    async def delayed_response(_request):
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            stream=HoldingStream(),
        )

    _mock_transport(monkeypatch, delayed_response)
    config = ResponsesConfig(model="local-model", api_key=KEY,
                             base_url="http://mock.test/v1", timeout_sec=0.3)
    started = time.monotonic()
    with ConnectionLoop() as loop:
        result = ResponsesAdapter(config, loop=loop).complete(_request())

    assert result.output == [TEXT]
    assert result.usage.reported is True
    assert closed.is_set()
    assert time.monotonic() - started < 3


def test_completed_stream_tail_read_error_keeps_terminal_success_and_closes_connection():
    with _tail_server("truncated") as (config, captures, client_ports, terminal_sent, _release, errors):
        with ConnectionLoop() as loop:
            result = ResponsesAdapter(config, loop=loop).complete(_request())

    assert terminal_sent.is_set()
    assert result.output == [TEXT]
    assert len(captures) == 1
    assert len(client_ports) == 1
    assert not errors


def test_cancel_during_completed_stream_drain_has_priority_and_closes_the_loop():
    request = _request(session_id="tail-cancel")

    with _tail_server("hold") as (config, captures, _ports, terminal_sent, release, errors):
        loop = ConnectionLoop()
        adapter = ResponsesAdapter(config, loop=loop)

        def invoke():
            with loop:
                return adapter.complete(request)

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(invoke)
                assert terminal_sent.wait(3)
                adapter.cancel(request.attempt_id)
                with pytest.raises(ProviderError) as caught:
                    future.result(timeout=2)
                assert caught.value.reason == "cancelled"
        finally:
            release.set()

    assert len(captures) == 1
    assert not errors


def test_stream_item_observation_does_not_invent_the_returned_model():
    observations = []
    with _server([_stream([TEXT])]) as (config, *_):
        result = ResponsesAdapter(config).complete(_request(), observations.append)
    messages = [event for event in observations if event.kind == "message"]
    usage = [event for event in observations if event.kind == "usage"]
    assert len(messages) == 1 and messages[0].model is None
    assert len(usage) == 1 and usage[0].model == "local-model"
    assert result.model == "local-model"


def test_missing_usage_is_unknown_not_a_provider_estimate():
    with _server([_stream(usage=None)]) as (config, *_):
        result = ResponsesAdapter(config).complete(_request())
    assert result.usage.reported is False and result.usage.total_tokens == 0


def test_compaction_output_limit_is_sent_to_the_sdk_without_hidden_prompt_changes():
    with _server([_stream()]) as (config, captures, *_):
        request = _request().model_copy(update={"purpose": "compaction", "max_output_tokens": 320, "tools": []})
        ResponsesAdapter(config).complete(request)
        assert captures[0] == {"model": "local-model", "input": request.input_items, "tools": [],
                               "store": False, "stream": True, "max_output_tokens": 320}


def test_nullable_reasoning_content_is_preserved_through_sdk_and_next_request():
    reasoning = {**REASONING, "content": None, "encrypted_content": None}
    observations = []
    with _server([_stream([reasoning, CALL]), _stream([TEXT], response_id="resp-two")]) as (config, captures, *_):
        adapter = ResponsesAdapter(config)
        result = adapter.complete(_request(), observations.append)
        assert result.output == [reasoning, CALL]
        message = next(event for event in observations if event.kind == "message")
        assert message.payload == reasoning and message.text == ""
        next_request = _request(history=[*result.output, {"type": "function_call_output", "call_id": CALL["call_id"], "output": "proof"}])
        adapter.complete(next_request)
        assert captures[1]["input"][-3] == reasoning


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_null_terminal_output_is_explicit_error_and_preserves_usage(status):
    response = {**_response(status=status), "output": None}
    observations = []
    with _server([_event(f"response.{status}", response=response, sequence_number=0)]) as (config, *_):
        with pytest.raises(ProviderError) as caught:
            ResponsesAdapter(config).complete(_request(), observations.append)
        assert caught.value.reason == "provider_error"
        assert "output" in str(caught.value) or "failed" in str(caught.value)
    assert [event.usage.total_tokens for event in observations if event.kind == "usage"] == [130]


@pytest.mark.parametrize("status,code,reason", [
    (400, "context_length_exceeded", "context_overflow"),
    (401, "invalid_api_key", "provider_error"),
    (429, "rate_limit_exceeded", "provider_error"),
    (500, "server_error", "provider_error"),
])
def test_http_errors_are_explicit_sanitized_and_never_retried(status, code, reason):
    secret = "credential-that-provider-echoed"

    def failure(handler, _body):
        _send(handler, json.dumps({"error": {"code": code, "message": secret, "type": "invalid_request_error"}}).encode(),
              status=status, content_type="application/json")

    with _server([failure]) as (config, captures, *_):
        with pytest.raises(ProviderError) as caught:
            ResponsesAdapter(config).complete(_request())
        assert caught.value.reason == reason
        assert secret not in str(caught.value) and KEY not in str(caught.value)
        assert str(status) in str(caught.value)
        assert len(captures) == 1


@pytest.mark.parametrize("retry_after", ["61", "120"])
def test_http_retry_after_preserves_long_server_delay_for_engine(retry_after):
    def failure(handler, _body):
        _send(handler, b'{"error":{"code":"rate_limit_exceeded"}}', status=429,
              content_type="application/json", headers={"Retry-After": retry_after})

    with _server([failure]) as (config, *_):
        with pytest.raises(ProviderError) as caught:
            ResponsesAdapter(config).complete(_request())
    assert caught.value.retryable is True
    assert caught.value.diagnostics["retry_after_sec"] == float(retry_after)


def test_http_429_insufficient_quota_is_permanent_and_keeps_only_safe_diagnostics():
    leaked_code = "quota-secret-should-not-be-stored"

    def failure(handler, _body):
        _send(handler, json.dumps({"error": {"code": "insufficient_quota", "message": leaked_code}}).encode(),
              status=429, content_type="application/json")

    with _server([failure]) as (config, *_):
        with pytest.raises(ProviderError) as caught:
            ResponsesAdapter(config).complete(_request())
    assert caught.value.retryable is False
    assert caught.value.diagnostics == {
        "status_code": 429,
        "error_code": "insufficient_quota",
        "request_observation_id": "activation:1:attempt-1",
    }
    assert leaked_code not in str(caught.value.diagnostics)


def test_unknown_provider_error_code_is_not_persisted():
    leaked_code = "provider-echoed-secret-code"

    def failure(handler, _body):
        _send(handler, json.dumps({"error": {"code": leaked_code, "message": "opaque"}}).encode(),
              status=500, content_type="application/json")

    with _server([failure]) as (config, *_):
        with pytest.raises(ProviderError) as caught:
            ResponsesAdapter(config).complete(_request())
    assert caught.value.retryable is True
    assert caught.value.diagnostics == {
        "status_code": 500,
        "request_observation_id": "activation:1:attempt-1",
    }
    assert leaked_code not in str(caught.value)


def test_http_400_keeps_bounded_redacted_error_identity():
    secret = "credential-that-provider-echoed"
    observations = []

    def failure(handler, _body):
        _send(
            handler,
            json.dumps({
                "error": {
                    "code": "unknown_parameter",
                    "type": "invalid_request_error",
                    "param": "store",
                    "message": secret,
                }
            }).encode(),
            status=400,
            content_type="application/json",
        )

    with _server([failure]) as (config, *_):
        with pytest.raises(ProviderError) as caught:
            ResponsesAdapter(config).complete(_request(), observations.append)
    diagnostics = caught.value.diagnostics
    request_obs = next(event for event in observations if event.kind == "request")
    assert caught.value.retryable is False
    assert diagnostics == {
        "status_code": 400,
        "error_code": "unknown_parameter",
        "error_type": "invalid_request_error",
        "param": "store",
        "request_observation_id": request_obs.id,
    }
    assert request_obs.id == "activation:1:attempt-1"
    assert secret not in str(caught.value) and secret not in str(diagnostics)
    assert KEY not in str(diagnostics)


def test_product_spec_change_record_schema_has_object_type_for_responses():
    tools = [
        {"type": "function", "name": item["name"], "description": item["description"],
         "parameters": item["parameters"], "strict": False}
        for item in host_tool_definitions(tools_for("product"))
    ]

    def inspect(handler, body):
        spec = next(item for item in body["tools"] if item["name"] == "submit_product_spec")
        change_record = spec["parameters"]["properties"]["change_record"]
        if "anyOf" in change_record or not isinstance(change_record.get("type"), str):
            _send(
                handler,
                json.dumps({
                    "error": {
                        "type": "invalid_request_error",
                        "status": "INVALID_ARGUMENT",
                        "message": "submit_product_spec parameters.change_record schema didn't specify the schema type field",
                    }
                }).encode(),
                status=400,
                content_type="application/json",
            )
            return
        _send(handler, _stream())

    with _server([inspect]) as (config, captures, *_):
        request = _request().model_copy(update={"tools": tools})
        result = ResponsesAdapter(config).complete(request)
    assert result.output
    spec = next(item for item in captures[0]["tools"] if item["name"] == "submit_product_spec")
    change_record = spec["parameters"]["properties"]["change_record"]
    assert change_record["type"] == "object"
    assert "anyOf" not in change_record
    assert "goal" in spec["parameters"]["required"]
    assert "change_record" not in spec["parameters"]["required"]


def test_http_400_gemini_status_keeps_sanitized_type_without_message():
    secret = "Invalid JSON payload received. Unknown name store echoed " + KEY

    def failure(handler, _body):
        _send(
            handler,
            json.dumps({
                "error": {
                    "code": 400,
                    "message": secret,
                    "status": "INVALID_ARGUMENT",
                    "param": "tools[0].parameters",
                }
            }).encode(),
            status=400,
            content_type="application/json",
        )

    with _server([failure]) as (config, *_):
        with pytest.raises(ProviderError) as caught:
            ResponsesAdapter(config).complete(_request())
    diagnostics = caught.value.diagnostics
    assert diagnostics["status_code"] == 400
    assert diagnostics["error_type"] == "invalid_argument"
    assert diagnostics["param"] == "tools[0].parameters"
    assert diagnostics["request_observation_id"] == "activation:1:attempt-1"
    assert "error_code" not in diagnostics
    assert secret not in str(caught.value) and KEY not in str(diagnostics)
    assert "message" not in diagnostics


def test_observation_host_io_error_is_not_reclassified_as_retryable_connection():
    def fail_observation(_observation):
        raise OSError("host persistence failed")

    with _server([_stream()]) as (config, *_):
        with pytest.raises(OSError, match="host persistence failed"):
            ResponsesAdapter(config).complete(_request(), fail_observation)


def test_sdk_connection_error_with_local_protocol_cause_is_not_retryable(monkeypatch):
    class FailingResponses:
        async def create(self, **_kwargs):
            error = APIConnectionError(
                message="connection error",
                request=httpx.Request("POST", "http://local.test/v1/responses"),
            )
            error.__cause__ = httpx.LocalProtocolError("invalid header")
            raise error

    class FailingClient:
        def __init__(self, **_kwargs):
            self.responses = FailingResponses()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr("harness.providers.responses.AsyncOpenAI", FailingClient)
    with pytest.raises(ProviderError) as caught:
        ResponsesAdapter(ResponsesConfig(model="local-model", api_key=KEY)).complete(_request())
    assert caught.value.retryable is False
    assert caught.value.diagnostics == {"error_type": "provider_protocol"}


@pytest.mark.parametrize("status", ["incomplete", "failed"])
def test_noncompleted_terminal_response_keeps_observations_but_cannot_complete(status):
    observations = []
    with _server([_stream(status=status)]) as (config, *_):
        with pytest.raises(ProviderError, match=status):
            ResponsesAdapter(config).complete(_request(), observations.append)
    assert len([event for event in observations if event.kind == "message"]) == 1
    assert [event.usage.total_tokens for event in observations if event.kind == "usage"] == [130]


def test_stream_disconnect_does_not_turn_partial_output_into_success():
    observations = []
    with _server([_stream(terminal=False)]) as (config, captures, *_):
        with pytest.raises(ProviderError, match="ended before") as caught:
            ResponsesAdapter(config).complete(_request(), observations.append)
        assert len(captures) == 1
        assert caught.value.diagnostics["error_type"] == "stream_incomplete"
        assert caught.value.diagnostics["transport_phase"] == "response_closed"
        assert caught.value.diagnostics["trace_available"] is True
    assert [event.id for event in _decoded(observations) if event.kind != "request"] == ["msg-one"]


@pytest.mark.parametrize("nested", [False, True])
def test_stream_error_maps_context_overflow_without_echoing_the_error_body(nested):
    details = {"code": "context_length_exceeded", "message": KEY, "param": None, "sequence_number": 0}
    body = _event("error", **({"error": details} if nested else details))
    with _server([body]) as (config, captures, *_):
        with pytest.raises(ProviderError) as caught:
            ResponsesAdapter(config).complete(_request())
        assert caught.value.reason == "context_overflow"
        assert KEY not in str(caught.value)
        assert len(captures) == 1


def test_malformed_stream_json_is_an_explicit_provider_error():
    with _server([b'event: response.completed\ndata: {broken-json\n\n']) as (config, captures, *_):
        with pytest.raises(ProviderError, match="malformed stream JSON"):
            ResponsesAdapter(config).complete(_request())
        assert len(captures) == 1


def test_terminal_response_returns_without_waiting_for_server_to_close():
    release = Event()

    def keep_open(handler, _body):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(_stream())
        handler.wfile.flush()
        release.wait(5)

    try:
        with _server([keep_open]) as (config, *_):
            with ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(ResponsesAdapter(config).complete, _request()).result(timeout=2)
            assert result.output == [TEXT]
    finally:
        release.set()


@pytest.mark.parametrize("headers_sent", [False, True])
def test_silent_network_times_out_and_keeps_completed_output(headers_sent):
    release = Event()
    observations = []

    def silence(handler, _body):
        if headers_sent:
            handler.send_response(200)
            handler.send_header("Content-Type", "text/event-stream")
            handler.end_headers()
            handler.wfile.write(_stream(terminal=False))
            handler.wfile.flush()
        release.wait(5)

    try:
        with _server([silence]) as (config, captures, *_):
            with pytest.raises(ProviderError, match="timed out") as caught:
                ResponsesAdapter(replace(config, timeout_sec=0.8)).complete(_request(), observations.append)
            assert caught.value.reason == "provider_timeout"
            assert len(captures) == 1
            assert len([event for event in _decoded(observations) if event.kind != "request"]) == int(headers_sent)
    finally:
        release.set()


@pytest.mark.parametrize("headers_sent", [False, True])
def test_cancel_interrupts_silent_network_only_for_the_active_request(headers_sent):
    release = Event()

    def silence(handler, _body):
        if headers_sent:
            handler.send_response(200)
            handler.send_header("Content-Type", "text/event-stream")
            handler.end_headers()
            handler.wfile.flush()
        release.wait(5)

    try:
        with _server([silence, _stream()]) as (config, captures, _, _, received):
            adapter = ResponsesAdapter(replace(config, timeout_sec=30))
            request = _request()
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(adapter.complete, request)
                assert received.wait(3)
                adapter.cancel("unrelated-attempt")
                assert not future.done()
                started = time.monotonic()
                adapter.cancel(request.attempt_id)
                with pytest.raises(ProviderError) as caught:
                    future.result(timeout=2)
                assert caught.value.reason == "cancelled"
                assert caught.value.diagnostics is None
                assert time.monotonic() - started < 1.5
            release.set()
            next_request = _request(session_id="next-session", attempt_id="activation:2:attempt-1")
            assert adapter.complete(next_request).output == [TEXT]
            assert len(captures) == 2
    finally:
        release.set()


def test_pre_cancelled_request_never_reaches_provider():
    with _server([]) as (config, captures, *_):
        request = _request()
        adapter = ResponsesAdapter(config)
        adapter.cancel(request.attempt_id)
        with pytest.raises(ProviderError) as caught:
            adapter.complete(request)
        assert caught.value.reason == "cancelled" and captures == []


def test_concurrent_request_is_rejected_without_disturbing_registered_request():
    release = Event()

    def silence(handler, _body):
        release.wait(5)
        _send(handler, _stream())

    try:
        with _server([silence]) as (config, captures, _, _, received):
            adapter = ResponsesAdapter(config)
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(adapter.complete, _request())
                assert received.wait(3)
                with pytest.raises(ProviderError, match="already has an active"):
                    adapter.complete(_request(session_id="other-session"))
                assert not pending.done() and len(captures) == 1
                release.set()
                assert pending.result(timeout=2).output == [TEXT]
    finally:
        release.set()


def test_config_requires_explicit_values_and_never_reads_environment(monkeypatch):
    monkeypatch.setenv("YUDAO_MODEL_NAME", "must-not-be-used")
    monkeypatch.setenv("YUDAO_MODEL_API_KEY", "must-not-be-used")
    adapter = ResponsesAdapter(ResponsesConfig())
    assert adapter.availability().available is False
    assert adapter.availability().reason == "provider_unavailable"
    with pytest.raises(ProviderError) as caught:
        adapter.complete(_request())
    assert caught.value.reason == "provider_unavailable"
    config = ResponsesConfig(model="configured-model", api_key=KEY, provider="configured-provider",
                             base_url="http://127.0.0.1:1234/v1", timeout_sec=45)
    assert config.model == "configured-model" and config.provider == "configured-provider"
    assert config.timeout_sec == 45 and config.base_url == "http://127.0.0.1:1234/v1"
    assert KEY not in repr(config)
    assert ResponsesAdapter(config).availability().available is True


@pytest.mark.parametrize("timeout", ["0", "-1", "invalid", "nan", "inf"])
def test_invalid_timeout_is_unavailable_without_exposing_secrets(monkeypatch, timeout):
    availability = ResponsesAdapter(ResponsesConfig(model="local-model", api_key=KEY,
                                                     timeout_sec=float(timeout) if timeout not in {"invalid"} else 0.0)).availability()
    assert availability.available is False and availability.reason == "provider_unavailable"
    assert KEY not in availability.message
