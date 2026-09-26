"""Deterministic W1 model-attempt collection and read-only query checks."""

from __future__ import annotations

import json
import math
import threading
from pathlib import Path
from http.client import HTTPConnection

import pytest

from harness.artifacts import ArtifactStore
from harness.adapters.base import Availability, ModelObservation, ModelResponse, ProviderError
from harness.tests.protocol_helpers import ResponsesAdapter
from harness.engine import StepLimits
from harness.models import ArtifactRef, EventType, Usage
from harness.observability import ObservabilityQuery, _detail_events, _usage_totals
from harness.runtime import LoopSystem
from harness.tests.helpers import happy_script
from harness.tests.test_responses import _server, _stream, _submit_stream
from harness.web.server import serve
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.proposals import product_spec


class _BlockingPartialAdapter:
    name = "stub"
    model = "stub-model"

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def availability(self):
        return Availability(True)

    def abort(self, _session_id):
        self.release.set()

    def complete(self, request):
        item = {
            "id": "partial-message",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "PARTIAL_OUTPUT"}],
        }
        request.observe(ModelObservation(
            item["id"], "message", item, "PARTIAL_OUTPUT",
            provider=self.name, model=self.model,
        ))
        self.started.set()
        self.release.wait(5)
        return ModelResponse(
            finish_reason="aborted", error="aborted",
            provider=self.name, model=self.model,
        )


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
    assert usage["totals"]["cost"] is None
    assert usage["cost_status"] == "missing"
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


def test_cancelled_attempt_is_independently_filterable(tmp_path: Path):
    adapter = _BlockingPartialAdapter()
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("cancelled attempt")
    worker = threading.Thread(target=system.activate_once, args=(run_id,), daemon=True)
    worker.start()
    assert adapter.started.wait(3)
    system.cancel(run_id)
    worker.join(timeout=3)
    assert not worker.is_alive()

    query = ObservabilityQuery(system.store, system.artifacts)
    row = query.list_model_attempts(run_id)["items"][0]
    assert row["status"] == "cancelled"
    assert row["stage"] == "cancelled"
    assert query.list_model_attempts(run_id, status="cancelled")["total"] == 1
    assert query.list_model_attempts(run_id, status="failed")["total"] == 0
    assert query.model_usage(run_id, status="cancelled")["total_attempts"] == 1


def test_running_partial_output_is_in_attempt_detail_and_failed_output_is_not_department_history(tmp_path: Path):
    adapter = _BlockingPartialAdapter()
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("partial attempt")
    worker = threading.Thread(target=system.activate_once, args=(run_id,), daemon=True)
    worker.start()
    assert adapter.started.wait(3)

    query = ObservabilityQuery(system.store, system.artifacts)
    row = query.list_model_attempts(run_id)["items"][0]
    assert row["status"] == "running"
    assert row["stage"] == "partial"
    assert row["partial_output"] is True
    assert row["output_item_count"] == 1
    detail = query.model_attempt_detail(run_id, row["id"])
    assert detail["response"] is None
    assert detail["event_order"] == "source_grouped"
    assert any(event["type"] == EventType.MODEL_MESSAGE for event in detail["events"])
    assert any(event["event_group"] == "event_store" for event in detail["events"])

    system.cancel(run_id)
    worker.join(timeout=3)
    assert not worker.is_alive()
    cancelled = query.model_attempt_detail(run_id, row["id"])
    assert cancelled["attempt"]["status"] == "cancelled"
    assert cancelled["attempt"]["partial_output"] is True
    assert any(event["type"] == EventType.MODEL_MESSAGE for event in cancelled["events"])
    department = query.department(run_id, "product")
    assert not any(message["text"] == "PARTIAL_OUTPUT" for message in department["messages"])


def test_failed_partial_output_is_observation_only_but_detail_keeps_it(tmp_path: Path):
    def fail_after_message(request):
        item = {
            "id": "failed-partial-message",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "FAILED_PARTIAL_OUTPUT"}],
        }
        request.observe(ModelObservation(
            item["id"], "message", item, "FAILED_PARTIAL_OUTPUT",
            provider="stub", model="stub-model",
        ))
        raise ProviderError("stream failed", retryable=False)

    system = LoopSystem.for_testing(tmp_path, FakeAdapter([fail_after_message]))
    run_id = system.create_run("failed partial attempt")
    system.activate_once(run_id)
    query = ObservabilityQuery(system.store, system.artifacts)
    row = query.list_model_attempts(run_id)["items"][0]
    assert row["status"] == "failed"
    assert row["stage"] == "failed"
    assert row["partial_output"] is True
    detail = query.model_attempt_detail(run_id, row["id"])
    assert any(event["type"] == EventType.MODEL_MESSAGE for event in detail["events"])
    department = query.department(run_id, "product")
    assert not any(message["text"] == "FAILED_PARTIAL_OUTPUT" for message in department["messages"])


def test_unreported_normalized_usage_keeps_unknown_source_and_is_excluded_from_provider_totals(tmp_path: Path):
    usage = Usage(total_tokens=7, reported=False)
    system = LoopSystem.for_testing(
        tmp_path,
        FakeAdapter([FakeTurn(proposal=product_spec(), usage=usage)]),
    )
    run_id = system.create_run("estimated usage")
    system.activate_once(run_id)

    query = ObservabilityQuery(system.store, system.artifacts)
    row = query.list_model_attempts(run_id)["items"][0]
    assert row["usage"]["source"] == "unknown"
    assert row["usage"]["reported"] is False
    assert row["usage"]["total_tokens"] == 7
    summary = query.model_usage(run_id)
    assert summary["coverage"]["reported_attempts"] == 0
    assert summary["coverage"]["estimated_attempts"] == 0
    assert summary["totals"]["total_tokens"] is None
    assert summary["estimated_totals"]["total_tokens"] is None

    estimated = query._attempt_usage(run_id, {
        "raw_usage_ref": None,
        "usage_summary": {"total_tokens": 9, "reported": False, "source": "estimated"},
        "duration_ms": None,
    })
    assert estimated["source"] == "estimated"
    assert estimated["total_tokens"] == 9
    estimated_totals = _usage_totals([{"status": "completed", "usage": estimated}], source="estimated")
    assert estimated_totals["total_tokens"] == 9


def test_usage_totals_reported_cost_sums_same_currency():
    total = _usage_totals([
        {"status": "completed", "usage": {"source": "reported", "cost": 1.25, "currency": "CNY"}},
        {"status": "completed", "usage": {"source": "reported", "cost": 2.75, "currency": "CNY"}},
    ], source="reported")
    assert total["cost"] == 4.0
    assert total["currency"] == "CNY"
    assert total["cost_status"] == "reported"


def test_usage_totals_mixed_currency_leaves_cost_null():
    total = _usage_totals([
        {"status": "completed", "usage": {"source": "reported", "cost": 1, "currency": "CNY"}},
        {"status": "completed", "usage": {"source": "reported", "cost": 2, "currency": "USD"}},
    ], source="reported")
    assert total["cost"] is None
    assert total["currency"] is None
    assert total["cost_status"] == "mixed_currency"


def test_usage_totals_missing_cost_is_not_zero():
    total = _usage_totals([
        {"status": "completed", "usage": {"source": "reported", "input_tokens": 4}},
        {"status": "completed", "usage": {"source": "reported", "output_tokens": 2}},
    ], source="reported")
    assert total["cost"] is None
    assert total["cost_status"] == "missing"


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
    assert detail["event_order"] == "source_grouped"
    stream_events = [item for item in detail["events"] if item["source"] == "sdk_decoded_stream"]
    assert stream_events and all(item["event_group"] == "provider_stream" for item in stream_events)
    assert all(item["sequence_source"] == "provider" for item in stream_events)
    assert all("observed_at" in item for item in stream_events)
    assert all(item["time"] == item["observed_at"] for item in stream_events)
    assert detail["observed_scope"]["events"]
    assert sum(event.type == EventType.MODEL_REQUESTED for event in system.store.list_events(run_id)) == 1


def test_legacy_stream_events_keep_unknown_time_and_provider_sequence():
    events = _detail_events([], [{"sequence": 7, "event": {"type": "response.created"}}])
    assert events == [{
        "event_id": None,
        "time": None,
        "type": "response.created",
        "summary": "response.created",
        "raw": {"type": "response.created"},
        "source": "sdk_decoded_stream",
        "event_group": "provider_stream",
        "sequence": 7,
        "sequence_source": "provider",
        "observed_at": None,
    }]


def test_sdk_json_observation_redacts_configured_credential(tmp_path: Path):
    from harness.providers.responses import _redact_sdk_json

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
    assert row["error_class"] == "provider_error"
    assert row["diagnostics"]["error_type"] == "adapter_failure"
    assert detail["attempt"]["error_class"] == "provider_error"


def test_list_model_attempts_filters_provider_and_models(tmp_path: Path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(happy_script()))
    run_id = system.create_run("filter attempts")
    system.run_until_stop(run_id)
    query = ObservabilityQuery(system.store, system.artifacts)
    listing = query.list_model_attempts(run_id)
    row = listing["items"][0]
    provider = row["requested_provider"]
    requested = row["requested_model"]
    actual = row["actual_model"]
    assert provider
    assert query.list_model_attempts(run_id, provider=provider)["total"] == listing["total"]
    assert query.list_model_attempts(run_id, provider="missing-provider")["total"] == 0
    assert query.list_model_attempts(run_id, requested_model=requested)["total"] >= 1
    if actual:
        assert query.list_model_attempts(run_id, actual_model=actual)["total"] >= 1
        assert query.model_usage(run_id, actual_model=actual)["total_attempts"] == query.list_model_attempts(run_id, actual_model=actual)["total_attempts"]
    assert query.list_model_attempts(run_id, actual_model="no-such-model")["total"] == 0


def test_compaction_coverage_exposes_seq_range_and_covered_through():
    from harness.views import compaction_coverage

    coverage = compaction_coverage({
        "source_event_id": "cmp-1",
        "checkpoint": {"covered_through_event_id": "evt-9"},
        "source_refs": [
            {"event_id": "evt-1", "seq": 4},
            {"event_id": "evt-9", "seq": 12},
        ],
    })
    assert coverage["compaction_event_id"] == "cmp-1"
    assert coverage["covered_through_event_id"] == "evt-9"
    assert coverage["covered_through_seq"] == 12
    assert coverage["source_seq_from"] == 4
    assert coverage["source_seq_through"] == 12


def test_partial_stream_failure_keeps_stream_artifact_and_actual_identity(tmp_path: Path):
    with _server([_stream([], terminal=False), _submit_stream()]) as (config, *_):
        system = LoopSystem.for_testing(tmp_path, ResponsesAdapter(config),
                                        step_limits=StepLimits(retry_initial_delay_sec=0.01, retry_max_delay_sec=0.01))
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


def test_observability_export_contains_attempt_context_and_usage_without_mutating_run(tmp_path: Path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(happy_script()))
    run_id = system.create_run("export observations")
    system.run_until_stop(run_id)
    before = system.project(run_id).last_seq

    exported = ObservabilityQuery(system.store, system.artifacts).export_run(run_id)

    assert exported["run_id"] == run_id
    assert len(exported["attempts"]) == 4
    assert exported["attempts"][0]["context"]["parts"]
    assert "request" in exported["attempts"][0]
    assert exported["usage"]["total_attempts"] == 4
    assert set(exported["departments"]) == {"product", "engineering", "quality"}
    assert system.project(run_id).last_seq == before
