from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from typing import Any, Callable, Iterator

import pytest

import harness.engine as engine
from harness.adapters.responses import ResponsesConfig
from harness.models import ArtifactRef, EventType, json_dumps
from harness.provider_catalog import CredentialMaterial, ModelDefinition, ProviderCatalog, ProviderDefinition
from harness.proposals import collaboration_request, collaboration_response, delivery, engineering_plan, product_spec, review
from harness.runtime import LoopSystem
from harness.smoke import summarize_run


@dataclass(frozen=True)
class _Reply:
    body: bytes
    status: int = 200
    content_type: str = "text/event-stream"
    headers: dict[str, str] | None = None


Responder = Callable[[dict[str, Any], int], _Reply]


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


@contextmanager
def _provider_server(provider: str, key: str, responder: Responder) -> Iterator[tuple[ResponsesConfig, list[dict[str, Any]], list[BaseException]]]:
    captures: list[dict[str, Any]] = []
    errors: list[BaseException] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args: Any) -> None:
            return

        def do_POST(self) -> None:
            try:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                captures.append({
                    "body": body,
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "client_port": self.client_address[1],
                })
                reply = responder(body, len(captures))
            except BaseException as exc:
                errors.append(exc)
                reply = _error()
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


def _pending_request_id(body: dict[str, Any]) -> str | None:
    raw = _part(body, "pending_request")
    return None if raw is None else json.loads(raw)["id"]


def _contract_hash(body: dict[str, Any]) -> str:
    raw = _part(body, "current_contract")
    assert raw is not None
    return json.loads(raw)["content_hash"]


def _catalog(
    product_url: str,
    engineering_url: str,
    *,
    product_context_window: int = 20_000,
    product_provider: str = "provider-a",
) -> ProviderCatalog:
    providers = [
        ProviderDefinition("provider-a", "Provider A", "responses", product_url, "credential-a", timeout_sec=10),
        ProviderDefinition("provider-b", "Provider B", "responses", engineering_url, "credential-b", timeout_sec=10),
    ]
    models = [
        ModelDefinition("model-a-product", "provider-a", "a-product", product_context_window, 1_000),
        ModelDefinition("model-a-quality", "provider-a", "a-quality", 20_000, 1_000),
        ModelDefinition("model-b-engineering", "provider-b", "b-engineering", 20_000, 1_000),
        ModelDefinition("model-b-product", "provider-b", "b-product", product_context_window, 1_000),
    ]
    product_model_id = "model-a-product" if product_provider == "provider-a" else "model-b-product"
    return ProviderCatalog(
        providers,
        models,
        {
            "product": {"provider_id": product_provider, "model_id": product_model_id},
            "engineering": {"provider_id": "provider-b", "model_id": "model-b-engineering"},
            "quality": {"provider_id": "provider-a", "model_id": "model-a-quality"},
        },
    )


def _credentials(product: str = "provider-a-key-v1") -> dict[str, CredentialMaterial]:
    return {
        "credential-a": CredentialMaterial(product, version="a-v1"),
        "credential-b": CredentialMaterial("provider-b-key-v1", version="b-v1"),
    }


def _public_run_data(system: LoopSystem, run_id: str) -> str:
    events = [event.__dict__ for event in system.store.list_events(run_id)]
    return json_dumps({"projection": system.project(run_id), "events": events})


def test_http_provider_bindings_route_full_consultation_and_engineering_rework(tmp_path):
    counts = {"product": 0, "engineering": 0, "quality": 0}
    delivery_file = "import sys\nprint(sys.argv[1])\n"
    repaired_file = "import sys\nprint(sys.argv[1].upper())\n"

    def provider_a(body: dict[str, Any], _count: int) -> _Reply:
        department = _department(body)
        assert department in {"product", "quality"}
        counts[department] += 1
        if department == "product":
            request_id = _pending_request_id(body)
            if request_id is not None:
                payload = collaboration_response(request_id, "answered", "The output check should cover a normal argument.")
                payload.pop("kind")
                return _stream([_call(f"product-response-{counts[department]}", "submit_response", payload)],
                               response_id=f"a-product-response-{counts[department]}", model="a-product-actual")
            payload = product_spec()
            payload.pop("kind")
            return _stream([_call("product-spec", "submit_product_spec", payload)],
                           response_id="a-product-spec", model="a-product-actual")

        verdict = "rework_engineering" if counts[department] == 1 else "release"
        payload = review(
            verdict,
            "The first delivery needs an uppercase output check." if verdict.startswith("rework") else "The repaired delivery passes.",
            checks=["smoke"],
            defects=[{"severity": "major", "summary": "Output is not uppercase."}] if verdict.startswith("rework") else [],
        )
        payload.pop("kind")
        calls = [
            _call(
                f"quality-check-{counts[department]}",
                "collect_evidence",
                {"name": "smoke", "argv": [sys.executable, "-c", "print('quality')"]},
            ),
            _call(f"quality-review-{counts[department]}", "submit_review", payload),
        ]
        return _stream(calls, response_id=f"a-quality-{counts[department]}", model="a-quality-actual")

    def provider_b(body: dict[str, Any], _count: int) -> _Reply:
        department = _department(body)
        assert department == "engineering"
        counts[department] += 1
        if counts[department] == 1:
            payload = collaboration_request(
                "product",
                "What should the smoke check cover?",
                expected_result="Give the minimum acceptance behavior.",
            )
            payload.pop("kind")
            return _stream([_call("engineering-consultation", "submit_request", payload)],
                           response_id="b-consultation", model="b-engineering-actual")
        if counts[department] == 2:
            payload = engineering_plan()
            payload.pop("kind")
            return _stream([_call("engineering-plan", "submit_plan", payload)],
                           response_id="b-plan", model="b-engineering-actual")
        content = delivery_file if counts[department] == 3 else repaired_file
        payload = delivery(files=["src/echo.py"], check_names=["smoke"])
        payload.pop("kind")
        calls = [
            _call(f"write-{counts[department]}", "write_file", {"path": "src/echo.py", "content": content}),
            _call(
                f"engineering-check-{counts[department]}",
                "run_check",
                {"name": "smoke", "argv": [sys.executable, "-c", "print('engineering')"]},
            ),
            _call(f"delivery-{counts[department]}", "submit_delivery", payload),
        ]
        return _stream(calls, response_id=f"b-delivery-{counts[department]}", model="b-engineering-actual")

    with _provider_server("provider-a", "provider-a-key-v1", provider_a) as (config_a, captures_a, errors_a), \
            _provider_server("provider-b", "provider-b-key-v1", provider_b) as (config_b, captures_b, errors_b):
        system = LoopSystem(
            tmp_path,
            provider_catalog=_catalog(config_a.base_url, config_b.base_url),
            credentials=_credentials(),
        )
        run_id = system.create_run("build an echo command")
        result = system.run_until_stop(run_id)

        assert not errors_a and not errors_b
        assert config_a.base_url != config_b.base_url
        assert result.phase == "DONE", result.error
        assert result.rework_count == 1
        assert result.requests[-1].status == "answered"
        assert counts == {"product": 2, "engineering": 4, "quality": 2}
        assert [item["path"] for item in captures_a] == ["/v1/responses"] * len(captures_a)
        assert [item["path"] for item in captures_b] == ["/v1/responses"] * len(captures_b)
        assert [_department(item["body"]) for item in captures_a] == ["product", "product", "quality", "quality"]
        assert [_department(item["body"]) for item in captures_b] == ["engineering"] * 4
        assert all(item["authorization"] == "Bearer provider-a-key-v1" for item in captures_a)
        assert all(item["authorization"] == "Bearer provider-b-key-v1" for item in captures_b)
        assert [item["body"]["model"] for item in captures_a] == ["a-product", "a-product", "a-quality", "a-quality"]
        assert [item["body"]["model"] for item in captures_b] == ["b-engineering"] * 4
        assert len({item["client_port"] for item in captures_a}) == 1
        assert len({item["client_port"] for item in captures_b}) == 1
        assert {item["client_port"] for item in captures_a}.isdisjoint(
            item["client_port"] for item in captures_b
        )
        assert result.provider_bindings["product"]["provider_id"] == "provider-a"
        assert result.provider_bindings["engineering"]["provider_id"] == "provider-b"
        assert result.provider_bindings["quality"]["provider_id"] == "provider-a"
        requests = result.model_requests
        assert [(item["provider_config_id"], item["requested_model"]) for item in requests] == [
            ("provider-a", "a-product"), ("provider-b", "b-engineering"),
            ("provider-a", "a-product"), ("provider-b", "b-engineering"),
            ("provider-b", "b-engineering"), ("provider-a", "a-quality"),
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
        assert audit["collaboration_audit"]["status"] == "verified", audit["collaboration_audit"]


def test_provider_credentials_are_frozen_per_run_and_rotated_for_new_runs(tmp_path):
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
            provider_catalog=_catalog(config_a.base_url, config_b.base_url),
            credentials=credentials,
        )
        first_run = original.create_run("first task")
        credentials["credential-b"] = CredentialMaterial("provider-b-key-v2", version="b-v2")
        updated_catalog = _catalog(
            config_a.base_url,
            config_b.base_url,
            product_provider="provider-b",
        )
        updated = LoopSystem(tmp_path, provider_catalog=updated_catalog, credentials=credentials)
        second_run = updated.create_run("second task")

        first = original.activate_once(first_run)
        second = updated.activate_once(second_run)

        assert not errors_a and not errors_b
        assert [_department(item["body"]) for item in captures_a] == ["product"]
        assert [item["authorization"] for item in captures_a] == ["Bearer provider-a-key-v1"]
        assert [item["authorization"] for item in captures_b] == ["Bearer provider-b-key-v2"]
        assert first.provider_bindings["product"]["credential_version"] == "a-v1"
        assert second.provider_bindings["product"]["credential_version"] == "b-v2"
        assert first.provider_bindings["product"]["provider_id"] == "provider-a"
        assert second.provider_bindings["product"]["provider_id"] == "provider-b"
        assert first.provider_bindings["product"]["model"] == "a-product"
        assert second.provider_bindings["product"]["model"] == "b-product"
        public = _public_run_data(original, first_run) + _public_run_data(updated, second_run)
        assert "provider-a-key-v1" not in public
        assert "provider-b-key-v2" not in public


def test_shared_provider_adapters_keep_two_active_runs_isolated(tmp_path):
    entered_cancel = Event()
    release_cancel = Event()

    def shared(body: dict[str, Any], _count: int) -> _Reply:
        task = body["input"][0]["content"]
        if "cancel-me" in task:
            entered_cancel.set()
            release_cancel.wait(5)
            return _error()
        payload = product_spec()
        payload.pop("kind")
        return _stream([_call("other-product", "submit_product_spec", payload)],
                       response_id="other-success", model="a-product-actual")

    with _provider_server("provider-a", "provider-a-key", shared) as (config_a, captures_a, errors_a), \
            _provider_server("provider-b", "provider-b-key", lambda _body, _count: _error()) as (config_b, _captures_b, _errors_b):
        system = LoopSystem(tmp_path, provider_catalog=_catalog(config_a.base_url, config_b.base_url), credentials={
            "credential-a": CredentialMaterial("provider-a-key", version="a-v1"),
            "credential-b": CredentialMaterial("provider-b-key", version="b-v1"),
        })
        cancel_run = system.create_run("cancel-me")
        other_run = system.create_run("finish-me")
        with ThreadPoolExecutor(max_workers=2) as pool:
            cancelled_future = pool.submit(system.activate_once, cancel_run)
            successful_future = pool.submit(system.activate_once, other_run)
            assert entered_cancel.wait(3)
            successful = successful_future.result(timeout=5)
            cancelled = system.cancel(cancel_run)
            release_cancel.set()
            cancelled_result = cancelled_future.result(timeout=5)

        assert not errors_a
        assert successful.phase == "ENGINEERING"
        assert cancelled.phase == "FAILED" and cancelled.stop_reason == "cancelled"
        assert cancelled_result.stop_reason == "cancelled"
        assert len(captures_a) == 2
        assert all(item["authorization"] == "Bearer provider-a-key" for item in captures_a)
        assert all(item["body"]["model"] == "a-product" for item in captures_a)
        assert system.project(other_run).phase == "ENGINEERING"


def test_restart_cannot_rebind_an_existing_run_to_new_credentials(tmp_path):
    def unexpected(_body: dict[str, Any], _count: int) -> _Reply:
        return _error()

    with _provider_server("provider-a", "provider-a-key", unexpected) as (config_a, captures_a, errors_a), \
            _provider_server("provider-b", "provider-b-key", unexpected) as (config_b, _captures_b, _errors_b):
        catalog = _catalog(config_a.base_url, config_b.base_url)
        credentials = {
            "credential-a": CredentialMaterial("provider-a-key", version="a-v1"),
            "credential-b": CredentialMaterial("provider-b-key", version="b-v1"),
        }
        original = LoopSystem(tmp_path, provider_catalog=catalog, credentials=credentials)
        run_id = original.create_run("must remain on its frozen target")
        original.store.close()

        restarted = LoopSystem(
            tmp_path,
            provider_catalog=catalog,
            credentials={
                "credential-a": CredentialMaterial("provider-a-new-key", version="a-v2"),
                "credential-b": CredentialMaterial("provider-b-new-key", version="b-v2"),
            },
        )
        result = restarted.activate_once(run_id)

        assert result.phase == "FAILED" and result.stop_reason == "provider_credentials_lost"
        assert not errors_a and not captures_a
        public = _public_run_data(restarted, run_id)
        assert "provider-a-key" not in public
        assert "provider-a-new-key" not in public
        assert "provider-b-new-key" not in public


def test_retry_stays_on_the_bound_provider_and_model(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "RETRY_INITIAL_DELAY_SEC", 0.001)
    monkeypatch.setattr(engine, "RETRY_MAX_DELAY_SEC", 0.001)

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
        system = LoopSystem(tmp_path, provider_catalog=_catalog(config_a.base_url, config_b.base_url), credentials={
            "credential-a": CredentialMaterial("provider-a-key", version="a-v1"),
            "credential-b": CredentialMaterial("provider-b-key", version="b-v1"),
        })
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
        system = LoopSystem(tmp_path, provider_catalog=_catalog(config_a.base_url, config_b.base_url), credentials={
            "credential-a": CredentialMaterial("provider-a-key", version="a-v1"),
            "credential-b": CredentialMaterial("provider-b-key", version="b-v1"),
        })
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
        system = LoopSystem(tmp_path, provider_catalog=_catalog(config_a.base_url, config_b.base_url), credentials={
            "credential-a": CredentialMaterial("provider-a-key", version="a-v1"),
            "credential-b": CredentialMaterial("provider-b-key", version="b-v1"),
        })
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


def test_failed_http_attempt_keeps_requested_identity_without_actual_model(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "RETRY_INITIAL_DELAY_SEC", 0.001)
    monkeypatch.setattr(engine, "RETRY_MAX_DELAY_SEC", 0.001)

    def always_fails(body: dict[str, Any], _count: int) -> _Reply:
        assert _department(body) == "product"
        return _error()

    with _provider_server("provider-a", "provider-a-key", always_fails) as (config_a, captures_a, errors_a), \
            _provider_server("provider-b", "provider-b-key", lambda _body, _count: _error()) as (config_b, _captures_b, _errors_b):
        system = LoopSystem(tmp_path, provider_catalog=_catalog(config_a.base_url, config_b.base_url), credentials={
            "credential-a": CredentialMaterial("provider-a-key", version="a-v1"),
            "credential-b": CredentialMaterial("provider-b-key", version="b-v1"),
        })
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
        system = LoopSystem(tmp_path, provider_catalog=_catalog(config_a.base_url, config_b.base_url), credentials={
            "credential-a": CredentialMaterial("provider-a-key", version="a-v1"),
            "credential-b": CredentialMaterial("provider-b-key", version="b-v1"),
        })
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
            provider_catalog=_catalog(config_a.base_url, config_b.base_url, product_context_window=6_000),
            credentials={
                "credential-a": CredentialMaterial("provider-a-key", version="a-v1"),
                "credential-b": CredentialMaterial("provider-b-key", version="b-v1"),
            },
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
