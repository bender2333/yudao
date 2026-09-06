"""Exercise the official SDK against local HTTP/SSE, without a model service."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

import pytest

from harness.adapters.base import ModelRequest, ProviderError
from harness.adapters.responses import ResponsesAdapter, ResponsesConfig
from harness.context import ContextAssembler
from harness.models import RunProjection


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


def _request(*, session_id="session", observations=None, history=None):
    context = ContextAssembler().assemble(
        RunProjection(task="local request"), department="product", session_id=session_id, activation_id="activation",
    )
    if history:
        context.input_items.extend(history)
    return ModelRequest("run", "product", session_id, "activation", 1, context, TOOLS, Event(), observations)


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


def _send(handler, body, *, status=200, content_type="text/event-stream"):
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
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


def test_completed_items_and_final_usage_are_observed_once():
    observations = []
    with _server([_stream([REASONING, CALL, TEXT], duplicate=True)]) as (config, *_):
        result = ResponsesAdapter(config).complete(_request(observations=observations.append))
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


def test_missing_usage_is_unknown_not_a_provider_estimate():
    with _server([_stream(usage=None)]) as (config, *_):
        result = ResponsesAdapter(config).complete(_request())
    assert result.usage.reported is False and result.usage.total_tokens == 0


def test_nullable_reasoning_content_is_preserved_through_sdk_and_next_request():
    reasoning = {**REASONING, "content": None, "encrypted_content": None}
    observations = []
    with _server([_stream([reasoning, CALL]), _stream([TEXT], response_id="resp-two")]) as (config, captures, *_):
        adapter = ResponsesAdapter(config)
        result = adapter.complete(_request(observations=observations.append))
        assert result.output == [reasoning, CALL]
        assert observations[0].payload == reasoning and observations[0].text == ""
        next_request = _request(history=[*result.output, {"type": "function_call_output", "call_id": CALL["call_id"], "output": "proof"}])
        adapter.complete(next_request)
        assert captures[1]["input"][-3] == reasoning


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_null_terminal_output_is_explicit_error_and_preserves_usage(status):
    response = {**_response(status=status), "output": None}
    observations = []
    with _server([_event(f"response.{status}", response=response, sequence_number=0)]) as (config, *_):
        with pytest.raises(ProviderError) as caught:
            ResponsesAdapter(config).complete(_request(observations=observations.append))
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


@pytest.mark.parametrize("status", ["incomplete", "failed"])
def test_noncompleted_terminal_response_keeps_observations_but_cannot_complete(status):
    observations = []
    with _server([_stream(status=status)]) as (config, *_):
        with pytest.raises(ProviderError, match=status):
            ResponsesAdapter(config).complete(_request(observations=observations.append))
    assert len([event for event in observations if event.kind == "message"]) == 1
    assert [event.usage.total_tokens for event in observations if event.kind == "usage"] == [130]


def test_stream_disconnect_does_not_turn_partial_output_into_success():
    observations = []
    with _server([_stream(terminal=False)]) as (config, captures, *_):
        with pytest.raises(ProviderError, match="ended before"):
            ResponsesAdapter(config).complete(_request(observations=observations.append))
        assert len(captures) == 1
    assert [event.id for event in observations] == ["msg-one"]


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
            with pytest.raises(ProviderError, match="timed out"):
                ResponsesAdapter(replace(config, timeout_sec=0.8)).complete(_request(observations=observations.append))
            assert len(captures) == 1
        assert len(observations) == int(headers_sent)
    finally:
        release.set()


@pytest.mark.parametrize("via_flag", [False, True])
@pytest.mark.parametrize("headers_sent", [False, True])
def test_cancel_interrupts_silent_network_only_for_the_active_request(via_flag, headers_sent):
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
                adapter.abort("unrelated-session")
                assert not future.done()
                started = time.monotonic()
                if via_flag:
                    request.abort_flag.set()
                else:
                    adapter.abort(request.session_id)
                with pytest.raises(ProviderError) as caught:
                    future.result(timeout=2)
                assert caught.value.reason == "cancelled"
                assert time.monotonic() - started < 1.5
            release.set()
            assert adapter.complete(_request(session_id="next-session")).output == [TEXT]
            assert len(captures) == 2
    finally:
        release.set()


def test_pre_cancelled_request_never_reaches_provider():
    with _server([]) as (config, captures, *_):
        request = _request()
        request.abort_flag.set()
        with pytest.raises(ProviderError) as caught:
            ResponsesAdapter(config).complete(request)
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


def test_config_uses_only_explicit_model_environment(monkeypatch):
    for key in ["YUDAO_MODEL_NAME", "YUDAO_MODEL_API_KEY", "YUDAO_MODEL_PROVIDER", "YUDAO_MODEL_BASE_URL", "YUDAO_MODEL_TIMEOUT_SEC"]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-implicitly-used")
    adapter = ResponsesAdapter()
    assert adapter.availability().available is False
    assert adapter.availability().reason == "provider_unavailable"
    with pytest.raises(ProviderError) as caught:
        adapter.complete(_request())
    assert caught.value.reason == "provider_unavailable"
    monkeypatch.setenv("YUDAO_MODEL_NAME", "configured-model")
    monkeypatch.setenv("YUDAO_MODEL_API_KEY", KEY)
    monkeypatch.setenv("YUDAO_MODEL_PROVIDER", "configured-provider")
    monkeypatch.setenv("YUDAO_MODEL_BASE_URL", "http://127.0.0.1:1234/v1")
    monkeypatch.setenv("YUDAO_MODEL_TIMEOUT_SEC", "45")
    config = ResponsesConfig.from_env()
    assert config.model == "configured-model" and config.provider == "configured-provider"
    assert config.timeout_sec == 45 and config.base_url == "http://127.0.0.1:1234/v1"
    assert KEY not in repr(config)
    assert ResponsesAdapter(config).availability().available is True


@pytest.mark.parametrize("timeout", ["0", "-1", "invalid", "nan", "inf"])
def test_invalid_timeout_is_unavailable_without_exposing_secrets(monkeypatch, timeout):
    monkeypatch.setenv("YUDAO_MODEL_NAME", "local-model")
    monkeypatch.setenv("YUDAO_MODEL_API_KEY", KEY)
    monkeypatch.setenv("YUDAO_MODEL_TIMEOUT_SEC", timeout)
    availability = ResponsesAdapter().availability()
    assert availability.available is False and availability.reason == "provider_unavailable"
    assert KEY not in availability.message
