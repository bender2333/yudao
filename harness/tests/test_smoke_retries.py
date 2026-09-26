import copy
import json

import pytest

from harness.adapters.base import ModelObservation, ModelResponse, ProviderError
from harness.adapters.fake import FakeAdapter
from harness.models import EventType
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.smoke import isolation_fields
from harness.tests.helpers import FAST_RETRIES


def _retry_run(tmp_path):
    adapter = FakeAdapter([ProviderError("temporary", retryable=True), product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    run_id = system.create_run("retry audit")
    result = system.activate_once(run_id)
    assert result.phase == "ENGINEERING"
    return system, run_id


def _mutated_events(system, run_id, monkeypatch):
    events = copy.deepcopy(system.store.list_events(run_id))
    monkeypatch.setattr(system.store, "list_events", lambda *_args, **_kwargs: events)
    return events


def test_native_retry_events_are_verified_by_model_input_audit(tmp_path, monkeypatch):
    system, run_id = _retry_run(tmp_path)

    fields = isolation_fields(system.store, system.artifacts, run_id)
    audit = fields["model_input_audit"]
    assert fields["context_isolated"] is True, audit
    assert audit["status"] == "verified", audit
    assert audit["prepared_count"] == 2
    assert audit["request_count"] == audit["attempt_count"] == 2
    assert audit["retry_count"] == 1
    assert audit["logical_request_count"] == 1

    events = system.store.list_events(run_id)
    assert sum(event.type == EventType.MODEL_ATTEMPT_FAILED for event in events) == 1
    assert sum(event.type == EventType.MODEL_RETRY_SCHEDULED for event in events) == 1


def test_model_input_audit_rejects_retry_event_without_max_attempts(tmp_path, monkeypatch):
    system, run_id = _retry_run(tmp_path)
    events = _mutated_events(system, run_id, monkeypatch)
    schedule = next(event for event in events if event.type == EventType.MODEL_RETRY_SCHEDULED)
    schedule.payload.pop("max_attempts")

    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]

    assert audit["status"] == "unverified"
    assert any("max_attempts" in note for note in audit["notes"])


def test_model_input_audit_rejects_retry_event_with_wrong_next_attempt(tmp_path, monkeypatch):
    system, run_id = _retry_run(tmp_path)
    events = _mutated_events(system, run_id, monkeypatch)
    schedule = next(event for event in events if event.type == EventType.MODEL_RETRY_SCHEDULED)
    schedule.payload["next_attempt"] = schedule.payload["attempt"] + 2

    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]

    assert audit["status"] == "unverified"
    assert any("invalid retryability or attempt" in note for note in audit["notes"])


@pytest.mark.parametrize("event_type,field", [
    (EventType.MODEL_ATTEMPT_FAILED, "attempt"),
    (EventType.MODEL_RETRY_SCHEDULED, "max_attempts"),
    (EventType.MODEL_REQUESTED, "attempt"),
    (EventType.MODEL_REQUESTED, "max_attempts"),
    (EventType.MODEL_REQUESTED, "root_step_id"),
    (EventType.MODEL_REQUESTED, "retry_of_step_id"),
])
def test_model_input_audit_rejects_missing_retry_metadata(tmp_path, monkeypatch, event_type, field):
    system, run_id = _retry_run(tmp_path)
    events = _mutated_events(system, run_id, monkeypatch)
    event = next(item for item in events if item.type == event_type)
    event.payload.pop(field)

    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]

    assert audit["status"] == "unverified"
    assert any(field in note for note in audit["notes"])


def test_failed_partial_output_is_removed_from_retry_history_and_late_residue_fails_audit(tmp_path, monkeypatch):
    partial = {
        "id": "failed-partial",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "partial output"}],
    }

    def fail_after_partial(request):
        request.observe(ModelObservation("failed-partial", "message", partial, "partial output"))
        raise ProviderError("stream disconnected", retryable=True)

    adapter = FakeAdapter([fail_after_partial, product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    run_id = system.create_run("partial retry audit")
    result = system.activate_once(run_id)
    assert result.phase == "ENGINEERING"
    assert "failed-partial" not in json.dumps(adapter.invocations[1].input_items)

    clean = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]
    assert clean["status"] == "verified", clean

    events = _mutated_events(system, run_id, monkeypatch)
    partial_event = next(event for event in events
                         if event.type == EventType.MODEL_MESSAGE
                         and event.payload.get("response_id") == "failed-partial")
    failure_index = next(index for index, event in enumerate(events)
                         if event.type == EventType.MODEL_ATTEMPT_FAILED)
    events.insert(failure_index + 1, copy.deepcopy(partial_event))
    residue = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]

    assert residue["status"] == "unverified"
    assert any("failed model step produced output" in note for note in residue["notes"])


def test_model_input_audit_counts_prepared_step_without_request_separately(tmp_path, monkeypatch):
    adapter = FakeAdapter([ModelResponse(), product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    run_id = system.create_run("prepared but not sent")
    original = system.orchestrator._begin_request

    def reject_second(activation, request):
        return False if request.step_id == 2 else original(activation, request)

    monkeypatch.setattr(system.orchestrator, "_begin_request", reject_second)
    result = system.activate_once(run_id)
    assert result.phase == "PRODUCT_SPEC"

    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]

    assert audit["prepared_count"] == 2
    assert audit["request_count"] == audit["attempt_count"] == 1
    assert audit["unrequested_count"] == 1
    assert audit["status"] == "verified", audit["notes"]
