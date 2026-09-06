"""Deterministic W1 model-attempt collection and read-only query checks."""

from __future__ import annotations

import json
import math
import threading
from pathlib import Path
from http.client import HTTPConnection

import pytest

from harness.artifacts import ArtifactStore
from harness.adapters.base import Availability, ModelObservation
from harness.adapters.responses import ResponsesAdapter
from harness.models import ArtifactRef, EventType, Usage
from harness.observability import ObservabilityQuery
from harness.runtime import LoopSystem
from harness.tests.helpers import happy_script
from harness.tests.test_responses import _server, _stream, _submit_stream
from harness.web.server import serve
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.proposals import product_spec


def test_fake_run_exposes_attempt_identity_and_keeps_missing_usage_null(tmp_path: Path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(happy_script()))
    run_id = system.create_run("observe attempts")
    system.run_until_stop(run_id)
    query = ObservabilityQuery(system.store, system.artifacts)
    before = system.project(run_id).last_seq

    listing = query.list_model_attempts(run_id, limit=1)
    assert {"run_id", "version", "items", "total", "next_cursor"} <= set(listing)
    assert listing["total"] == 4
    assert listing["total_attempts"] == 4
    assert listing["running_attempts"] == 0
    assert listing["prepared_attempts"] == 0
    assert listing["items"][0]["status"] == "success"
    assert listing["items"][0]["id"]
    assert listing["items"][0]["logical_call_id"]
    assert listing["items"][0]["context_event_id"]
    assert listing["items"][0]["usage"]["input_tokens"] is None
    assert listing["items"][0]["usage"]["total_tokens"] is None
    assert listing["next_cursor"]
    assert query.list_model_attempts(run_id, cursor=listing["next_cursor"], limit=10)["total"] == 4

    usage = query.model_usage(run_id, limit=1)
    assert usage["total_attempts"] == 4
    assert usage["coverage"]["attempts"] == 4
    assert usage["coverage"]["reported_attempts"] == 0
    assert usage["totals"]["total_tokens"] is None
    assert usage["groups"]["departments"]
    assert system.project(run_id).last_seq == before


def test_stream_artifact_cleanup_closes_temp_file_before_cleanup(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")

    def broken_chunks():
        yield b"first"
        raise OSError("stream stopped")

    with pytest.raises(OSError, match="stream stopped"):
        store.put_stream("run", "sdk_stream_events", broken_chunks())
    assert not list((tmp_path / "artifacts" / "run").glob(".stream-*"))


def test_invalid_usage_numbers_are_unknown_in_queries(tmp_path: Path):
    query = ObservabilityQuery(
        LoopSystem.for_testing(tmp_path, FakeAdapter([])).store,
        ArtifactStore(tmp_path / "artifacts"),
    )
    normalized = query._attempt_usage("run", {
        "raw_usage_ref": None,
        "usage_summary": {
            "input_tokens": -1,
            "output_tokens": 1.5,
            "cache_read_tokens": math.inf,
            "cache_write_tokens": 0,
            "total_tokens": -3,
            "cost": -0.1,
        },
        "duration_ms": -4,
    })
    assert normalized["input_tokens"] is None
    assert normalized["output_tokens"] is None
    assert normalized["cache_read_tokens"] is None
    assert normalized["cache_write_tokens"] == 0
    assert normalized["total_tokens"] is None
    assert normalized["cost"] is None
    assert normalized["latency_ms"] is None


def test_responses_capture_complete_sdk_json_and_decoded_events(tmp_path: Path):
    with _server([_submit_stream()]) as (config, *_):
        system = LoopSystem.for_testing(tmp_path, ResponsesAdapter(config))
        run_id = system.create_run("observe sdk")
        system.activate_once(run_id)

    query = ObservabilityQuery(system.store, system.artifacts)
    listing = query.list_model_attempts(run_id)
    row = listing["items"][0]
    assert row["status"] == "success"
    assert row["provider_response_id"] == "resp-submit"
    assert row["provider"] == "local-stub"
    assert row["model"] == "local-model"
    assert row["usage"]["input_tokens"] == 100
    assert row["usage"]["cache_read_tokens"] == 80
    assert row["usage"]["output_tokens"] == 30
    assert row["usage"]["total_tokens"] == 130
    assert row["usage"]["cache_write_tokens"] is None
    assert row["usage"]["latency_ms"] == row["duration_ms"]
    assert row["duration_ms"] is not None

    detail = query.model_attempt_detail(run_id, row["id"])
    assert detail["request"]["model"] == "local-model"
    assert detail["response"]["id"] == "resp-submit"
    assert detail["context"]["parts_ref"]["kind"] == "context_parts"
    assert detail["context"]["parts"]
    assert all(set(part) == {"source", "version", "text", "digest"} for part in detail["context"]["parts"])
    assert any(item["source"] == "sdk_decoded_stream" for item in detail["events"])
    assert detail["observed_scope"]["events"]
    assert sum(event.type == EventType.MODEL_REQUESTED for event in system.store.list_events(run_id)) == 1


def test_sdk_json_observation_redacts_configured_credential(tmp_path: Path):
    from harness.adapters.responses import _redact_sdk_json

    secret = "credential-sentinel"
    payload = _redact_sdk_json(
        {"error": {"message": f"failed with {secret}", "headers": {"authorization": secret}}, "text": secret},
        secrets=(secret,),
    )
    assert secret not in json.dumps(payload)
    assert payload["error"]["headers"] == "[REDACTED]"


def test_sse_response_message_and_stream_artifacts_are_redacted_end_to_end(tmp_path: Path):
    proposal = product_spec()
    proposal.pop("kind")
    call = {
        "id": "fc-secret-submit", "type": "function_call", "name": "submit_product_spec",
        "call_id": "call-secret-submit", "arguments": json.dumps(proposal), "status": "completed",
    }
    from harness.tests.test_responses import _send

    def reply(handler, _body):
        secret_message = {"id": "msg-secret", "type": "message", "role": "assistant",
                          "status": "completed", "content": [{"type": "output_text", "text": config.api_key}]}
        _send(handler, _stream([secret_message, call], response_id="secret-response"))

    with _server([reply]) as (config, *_):
        system = LoopSystem.for_testing(tmp_path, ResponsesAdapter(config))
        run_id = system.create_run("redacted observations")
        system.activate_once(run_id)
    query = ObservabilityQuery(system.store, system.artifacts)
    row = query.list_model_attempts(run_id)["items"][0]
    detail = query.model_attempt_detail(run_id, row["id"])
    serialized = json.dumps(detail, ensure_ascii=False)
    assert config.api_key not in serialized
    assert detail["response"]["id"] == "secret-response"
    assert detail["events"]
    stream_ref = detail["artifact_refs"]["events"]
    assert stream_ref is not None
    stream_text = system.artifacts.get_for_run(run_id, ArtifactRef(**stream_ref)).decode("utf-8")
    assert config.api_key not in stream_text


def test_context_parts_are_verified_and_missing_current_parts_do_not_fallback(tmp_path: Path):
    with _server([_submit_stream()]) as (config, *_):
        system = LoopSystem.for_testing(tmp_path, ResponsesAdapter(config))
        run_id = system.create_run("context parts")
        system.activate_once(run_id)
    query = ObservabilityQuery(system.store, system.artifacts)
    row = query.list_model_attempts(run_id)["items"][0]
    detail = query.model_attempt_detail(run_id, row["id"])
    parts_ref = detail["context"]["parts_ref"]
    path = system.artifacts.root / parts_ref["path"]
    path.unlink()
    with pytest.raises(ValueError, match="context parts artifact is unavailable"):
        query.model_attempt_detail(run_id, row["id"])


def test_department_prompt_does_not_fallback_when_adopted_version_is_missing(tmp_path: Path, monkeypatch):
    with _server([_submit_stream()]) as (config, *_):
        system = LoopSystem.for_testing(tmp_path, ResponsesAdapter(config))
        run_id = system.create_run("prompt identity")
        system.activate_once(run_id)
    events = system.store.list_events(run_id)
    activation = next(event for event in events if event.type == EventType.DEPARTMENT_ACTIVATED)
    activation.payload["prompt_hash"] = "sha256:" + "0" * 64
    monkeypatch.setattr(system.store, "list_events", lambda _run_id, after_seq=0: events if after_seq == 0 else [event for event in events if event.seq > after_seq])
    department = ObservabilityQuery(system.store, system.artifacts).department(run_id, "product")
    assert department["prompt"]["status"] == "unknown"
    assert department["prompt"]["text"] is None
    assert department["prompt_latest"]["text"]


def test_generic_adapter_failure_closes_raw_capture_and_keeps_stream_evidence(tmp_path: Path):
    class BrokenAdapter:
        name = "broken"
        model = "broken-model"

        def availability(self):
            return Availability(True)

        def abort(self, _session_id):
            return None

        def complete(self, request):
            request.observe_raw(ModelObservation(
                "raw-1", "stream_event", {"type": "response.created", "response": {"model": self.model}},
                source="sdk_decoded_stream", sequence=0,
            ))
            raise RuntimeError("decoder failed")

    system = LoopSystem.for_testing(tmp_path, BrokenAdapter())
    run_id = system.create_run("adapter failure")
    system.activate_once(run_id)
    query = ObservabilityQuery(system.store, system.artifacts)
    row = query.list_model_attempts(run_id)["items"][0]
    assert row["status"] == "failed"
    assert row["stage"] == "failed"
    assert row["actual_model"] == "broken-model"
    detail = query.model_attempt_detail(run_id, row["id"])
    assert any(event["source"] == "sdk_decoded_stream" for event in detail["events"])


def test_partial_stream_failure_keeps_stream_artifact_and_actual_identity(tmp_path: Path, monkeypatch):
    import harness.engine as engine

    monkeypatch.setattr(engine, "RETRY_INITIAL_DELAY_SEC", 0.01)
    monkeypatch.setattr(engine, "RETRY_MAX_DELAY_SEC", 0.01)

    with _server([_stream([], terminal=False), _submit_stream()]) as (config, *_):
        system = LoopSystem.for_testing(tmp_path, ResponsesAdapter(config))
        run_id = system.create_run("partial stream")
        system.activate_once(run_id)

    query = ObservabilityQuery(system.store, system.artifacts)
    failed = [item for item in query.list_model_attempts(run_id)["items"] if item["status"] == "failed"]
    assert failed
    failed_detail = query.model_attempt_detail(run_id, failed[0]["id"])
    assert failed_detail["events"]
    assert failed_detail["response"] is None
    assert failed_detail["attempt"]["stage"] == "failed"


def test_observability_routes_are_run_scoped_and_query_only(tmp_path: Path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(happy_script()))
    run_id = system.create_run("route checks")
    system.run_until_stop(run_id)
    before = system.project(run_id).last_seq
    server = serve(system, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        def get(path: str):
            connection = HTTPConnection(host, port)
            connection.request("GET", path)
            response = connection.getresponse()
            body = json.loads(response.read())
            connection.close()
            return response.status, body

        status, listing = get(f"/api/runs/{run_id}/model-attempts?department=product&status=success")
        assert status == 200 and listing["total"] == 1
        attempt_id = listing["items"][0]["id"]
        status, detail = get(f"/api/runs/{run_id}/model-attempts/{attempt_id.replace(':', '%3A')}")
        assert status == 200 and detail["attempt"]["id"] == attempt_id
        status, department = get(f"/api/runs/{run_id}/departments/product")
        assert status == 200 and department["contexts"][0]["id"] == attempt_id
        status, usage = get(f"/api/runs/{run_id}/model-usage?department=product")
        assert status == 200 and usage["total_attempts"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert system.project(run_id).last_seq == before
