"""Exercise the official SDK against local HTTP/SSE, without a model service."""

import json
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

import pytest

from harness.watched_outputs import has_new_work
from harness.adapters.base import ProviderError
from harness.providers import ResponsesConfig
from harness.tests.protocol_helpers import (
    STUB_CALL as CALL,
    STUB_KEY as KEY,
    STUB_REASONING as REASONING,
    STUB_TEXT as TEXT,
    STUB_TOOLS as TOOLS,
    STUB_USAGE as RAW_USAGE,
    ConnectionLoop,
    ResponsesAdapter,
    model_call,
    stub_event as _event,
    stub_server as _server,
    stub_stream as _stream,
    stub_submit_stream as _submit_stream,
    write_stub_reply as _send,
)
from harness.context import ContextAssembler
from harness.definitions import DEFINITIONS
from harness.models import ArtifactRef, DepartmentPrompt, RunProjection, hash_bytes
from harness.runtime import LoopSystem
from harness.tests.helpers import FAST_RETRIES
from harness.tightening import WATCHED_OUTPUTS


def _request(*, session_id="session", history=None, max_output_tokens=None, attempt_id="activation:1:attempt-1"):
    prompt_text = DEFINITIONS.role("product").prompt
    prompt_hash = hash_bytes(prompt_text.encode("utf-8"))
    prompt_ref = ArtifactRef("department_prompt", prompt_hash, f"run/{prompt_hash[7:9]}/{prompt_hash[7:]}")
    projection = RunProjection(task="local request")
    prompt = DepartmentPrompt("product", 1, prompt_text, prompt_ref, "initial-prompt")
    context = ContextAssembler( tightening=WATCHED_OUTPUTS).assemble(
        projection, department="product", session_id=session_id, activation_id="activation", prompt=prompt,
    )
    return model_call([*context.input_items, *(history or [])], TOOLS, session_id=session_id,
                      max_output_tokens=max_output_tokens, attempt_id=attempt_id)


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
                    # [DONE] 之后既不送完声明的长度，也不关闭连接
                    body = response + b"data: [DONE]\n\n"
                    self._send(body, content_length=len(body) + 10, keep_open=True)
                    terminal_sent.set()
                    release.wait(5)
                    self.close_connection = True
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
            assert body == {"model": "local-model", "input": request.input_items, "tools": TOOLS, "store": False,
                            "stream": True, "include": ["reasoning.encrypted_content"]}
            assert canary not in json.dumps(body)
        assert captures[1]["input"][-3:] == history


@pytest.mark.parametrize("failure_kind", ["connection", "timeout", "429", "500", "partial_stream"])
def test_local_http_transient_failure_retries_same_input_then_succeeds(tmp_path, failure_kind):
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
            # 请求时限 1 秒，服务端保持 2 秒不回复
            config = replace(config, timeout_sec=1)
        adapters.append(ResponsesAdapter(config))
        system = LoopSystem.for_testing(tmp_path, adapters[0], step_limits=FAST_RETRIES)
        run_id = system.create_run("local retry")
        result = system.activate_once(run_id)

    assert has_new_work(result, "engineering"), result.error
    assert len(captures) == 2 and captures[0] == captures[1]
    events = system.store.list_events(run_id)
    failed = [item for item in events if item.type == "model_attempt_failed"]
    assert len(failed) == 1 and failed[0].payload["retryable"] is True
    if failure_kind == "partial_stream":
        assert "call-one" not in json.dumps(captures[1])
        assert not any(item.type == "tool_started" and item.payload.get("id") == "call-one" for item in events)


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
    assert [event.id for event in observations if event.kind == "reasoning"] == ["rs-one"]
    assert [event.id for event in observations if event.kind == "message"] == ["fc-one", "msg-one"]
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


def test_connection_loop_keeps_same_url_different_credentials_separate():
    first_key = "first-provider-credential"
    second_key = "second-provider-credential"
    with _keepalive_server(key=first_key) as (config, captures, client_ports, authorizations, _meta, errors):
        second_config = replace(config, api_key=second_key, model="second-model")
        with ConnectionLoop() as loop:
            ResponsesAdapter(config, loop=loop).complete(_request(session_id="first"))
            ResponsesAdapter(second_config, loop=loop).complete(_request(session_id="second"))

    assert not errors
    assert len(captures) == 2
    assert len(set(client_ports)) == 2
    assert authorizations == [f"Bearer {first_key}", f"Bearer {second_key}"]


@pytest.mark.parametrize("status,code,reason", [
    (400, "context_length_exceeded", "context_overflow"),
    (401, "invalid_api_key", "provider_unavailable"),
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


@pytest.mark.parametrize("status", ["incomplete", "failed"])
def test_noncompleted_terminal_response_keeps_observations_but_cannot_complete(status):
    observations = []
    with _server([_stream(status=status)]) as (config, *_):
        with pytest.raises(ProviderError, match=status):
            ResponsesAdapter(config).complete(_request(), observations.append)
    assert len([event for event in observations if event.kind == "message"]) == 1
    assert [event.usage.total_tokens for event in observations if event.kind == "usage"] == [130]


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


