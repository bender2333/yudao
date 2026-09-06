import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

import harness.engine as engine
from harness.adapters.base import ModelObservation, ModelResponse, ProviderError
from harness.adapters.fake import FakeAdapter
from harness.models import EventType, Usage, json_dumps
from harness.proposals import product_spec
from harness.runtime import LoopSystem


def _fast_retries(monkeypatch):
    monkeypatch.setattr(engine, "RETRY_INITIAL_DELAY_SEC", 0.01)
    monkeypatch.setattr(engine, "RETRY_MAX_DELAY_SEC", 0.02)


def _patch_engine_clock(monkeypatch, values):
    class Clock:
        def __init__(self, readings):
            self._readings = iter(readings)

        def monotonic(self):
            return next(self._readings)

        def sleep(self, _seconds):
            return None

    clock = Clock(values)
    monkeypatch.setattr(engine, "time", clock)
    return clock


def test_transient_failure_retries_same_logical_request_then_succeeds(tmp_path, monkeypatch):
    _fast_retries(monkeypatch)
    adapter = FakeAdapter([
        ProviderError("temporary connection failure", retryable=True,
                      diagnostics={"error_type": "connection"}),
        product_spec(),
    ])
    system = LoopSystem(tmp_path, adapter)
    run_id = system.create_run("echo")

    result = system.activate_once(run_id)

    assert result.phase == "ENGINEERING"
    first, second = adapter.invocations
    assert first.department == second.department == "product"
    assert first.activation_id == second.activation_id
    assert first.input_items == second.input_items and first.tools == second.tools
    assert (first.attempt, first.root_step_id, first.retry_of_step_id) == (1, 1, None)
    assert (second.attempt, second.root_step_id, second.retry_of_step_id) == (2, 1, 1)
    events = system.store.list_events(run_id)
    assert len([item for item in events if item.type == EventType.MODEL_ATTEMPT_FAILED]) == 1
    assert len([item for item in events if item.type == EventType.MODEL_RETRY_SCHEDULED]) == 1
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_retry_reuses_the_first_assembled_context(tmp_path, monkeypatch):
    _fast_retries(monkeypatch)
    adapter = FakeAdapter([ProviderError("temporary", retryable=True), product_spec()])
    system = LoopSystem(tmp_path, adapter)
    run_id = system.create_run("echo")
    assemble_calls = 0
    original_assemble = system.orchestrator.assembler.assemble

    def assemble(*args, **kwargs):
        nonlocal assemble_calls
        assemble_calls += 1
        return original_assemble(*args, **kwargs)

    monkeypatch.setattr(system.orchestrator.assembler, "assemble", assemble)
    result = system.activate_once(run_id)

    assert result.phase == "ENGINEERING"
    first, second = adapter.invocations
    assert assemble_calls == 2
    assert first.context is second.context
    assert first.input_items is second.input_items
    assert first.tools is second.tools
    assert first.input_items == second.input_items and first.tools == second.tools
    assert second.step_id == 2 and second.retry_of_step_id == 1


def test_retry_exhaustion_records_all_attempts_and_fails_once(tmp_path, monkeypatch):
    _fast_retries(monkeypatch)
    failures = [ProviderError("temporary", retryable=True) for _ in range(3)]
    adapter = FakeAdapter(failures)
    system = LoopSystem(tmp_path, adapter)
    run_id = system.create_run("echo")

    result = system.activate_once(run_id)

    assert result.phase == "FAILED" and result.stop_reason == "provider_error"
    assert [request.attempt for request in adapter.invocations] == [1, 2, 3]
    events = system.store.list_events(run_id)
    failed = [item for item in events if item.type == EventType.MODEL_ATTEMPT_FAILED]
    scheduled = [item for item in events if item.type == EventType.MODEL_RETRY_SCHEDULED]
    assert len(failed) == 3 and len(scheduled) == 2
    assert failed[-1].payload["will_retry"] is False


def test_provider_timeout_retries_when_single_request_and_logical_budgets_allow(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "RETRY_INITIAL_DELAY_SEC", 0.01)
    monkeypatch.setattr(engine, "RETRY_MAX_DELAY_SEC", 0.01)
    monkeypatch.setattr(engine, "RETRY_BUDGET_SEC", 0.02)
    _patch_engine_clock(monkeypatch, [0.0, 0.0])
    waited = []
    monkeypatch.setattr(engine, "_wait_for_retry", lambda delay, _stopped: (waited.append(delay) or True))
    adapter = FakeAdapter([
        ProviderError("single request timed out", reason="provider_timeout", retryable=True),
        product_spec(),
    ])
    system = LoopSystem(tmp_path, adapter)
    result = system.activate_once(system.create_run("echo"))

    assert result.phase == "ENGINEERING"
    assert len(adapter.invocations) == 2
    assert waited == [0.01]
    failed = next(item for item in system.store.list_events(result.run_id)
                  if item.type == EventType.MODEL_ATTEMPT_FAILED)
    assert failed.payload["reason"] == "provider_timeout"
    assert failed.payload["will_retry"] is True


def test_retry_budget_resets_for_each_logical_request(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "RETRY_INITIAL_DELAY_SEC", 0.01)
    monkeypatch.setattr(engine, "RETRY_MAX_DELAY_SEC", 0.01)
    monkeypatch.setattr(engine, "RETRY_BUDGET_SEC", 0.02)
    # A large elapsed time before the second logical request must not consume its
    # budget; only the elapsed time since that request started is relevant.
    _patch_engine_clock(monkeypatch, [0.0, 0.0, 100.0, 100.0])
    waited = []
    monkeypatch.setattr(engine, "_wait_for_retry", lambda delay, _stopped: (waited.append(delay) or True))
    read_call = {
        "id": "read-step",
        "type": "function_call",
        "call_id": "read-step",
        "name": "read_file",
        "arguments": json_dumps({"path": "proof.txt"}),
    }
    adapter = FakeAdapter([
        ProviderError("first timeout", reason="provider_timeout", retryable=True),
        ModelResponse(output=[read_call]),
        ProviderError("second timeout", reason="provider_timeout", retryable=True),
        product_spec(),
    ])
    system = LoopSystem(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.workspace(run_id).write_file("proof.txt", "evidence")

    result = system.activate_once(run_id)

    assert result.phase == "ENGINEERING"
    assert len(adapter.invocations) == 4
    assert [request.attempt for request in adapter.invocations] == [1, 2, 1, 2]
    assert [request.step_id for request in adapter.invocations] == [1, 2, 3, 4]
    assert waited == [0.01, 0.01]
    events = system.store.list_events(run_id)
    assert len([item for item in events if item.type == EventType.MODEL_RETRY_SCHEDULED]) == 2


def test_retry_budget_blocks_delay_that_would_cross_logical_request_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "RETRY_INITIAL_DELAY_SEC", 0.02)
    monkeypatch.setattr(engine, "RETRY_MAX_DELAY_SEC", 0.02)
    monkeypatch.setattr(engine, "RETRY_BUDGET_SEC", 0.1)
    _patch_engine_clock(monkeypatch, [0.0, 0.09])
    waited = []
    monkeypatch.setattr(engine, "_wait_for_retry", lambda delay, _stopped: (waited.append(delay) or True))
    adapter = FakeAdapter([ProviderError("temporary", retryable=True), product_spec()])
    system = LoopSystem(tmp_path, adapter)
    run_id = system.create_run("echo")

    result = system.activate_once(run_id)

    assert result.phase == "FAILED" and result.stop_reason == "provider_error"
    assert len(adapter.invocations) == 1
    assert waited == []
    events = system.store.list_events(run_id)
    assert not any(item.type == EventType.MODEL_RETRY_SCHEDULED for item in events)
    failed = next(item for item in events if item.type == EventType.MODEL_ATTEMPT_FAILED)
    assert failed.payload["will_retry"] is False


def test_retryable_attempts_stop_at_the_32_step_limit(tmp_path, monkeypatch):
    _fast_retries(monkeypatch)

    def transient_until_step_limit(request):
        if request.step_id % 3 == 0:
            return ModelResponse()
        return ProviderError("temporary", retryable=True)

    adapter = FakeAdapter([transient_until_step_limit] * engine.MAX_MODEL_STEPS)
    system = LoopSystem(tmp_path, adapter)
    result = system.activate_once(system.create_run("echo"))

    assert result.phase == "PAUSED" and result.stop_reason == "model_steps_exhausted"
    assert len(adapter.invocations) == engine.MAX_MODEL_STEPS
    assert [request.step_id for request in adapter.invocations] == list(range(1, engine.MAX_MODEL_STEPS + 1))


@pytest.mark.parametrize("reason", ["context_overflow", "provider_error", "cancelled"])
def test_nonretryable_provider_error_is_never_retried(tmp_path, monkeypatch, reason):
    _fast_retries(monkeypatch)
    adapter = FakeAdapter([ProviderError("permanent", reason=reason), product_spec()])
    system = LoopSystem(tmp_path, adapter)
    run_id = system.create_run("echo")

    result = system.activate_once(run_id)

    assert len(adapter.invocations) == 1
    assert result.stop_reason == reason
    events = system.store.list_events(run_id)
    assert len([item for item in events if item.type == EventType.MODEL_ATTEMPT_FAILED]) == 1
    assert not any(item.type == EventType.MODEL_RETRY_SCHEDULED for item in events)


def test_cancel_interrupts_retry_backoff_without_next_attempt(tmp_path, monkeypatch):
    scheduled = Event()
    monkeypatch.setattr(engine, "RETRY_INITIAL_DELAY_SEC", 5.0)
    adapter = FakeAdapter([ProviderError("temporary", retryable=True), product_spec()])
    system = LoopSystem(tmp_path, adapter)
    run_id = system.create_run("echo")
    original = system.orchestrator._record_retry_scheduled

    def record(*args):
        result = original(*args)
        scheduled.set()
        return result

    monkeypatch.setattr(system.orchestrator, "_record_retry_scheduled", record)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        assert scheduled.wait(3)
        started = time.monotonic()
        system.cancel(run_id)
        result = future.result(timeout=2)

    assert result.stop_reason == "cancelled"
    assert time.monotonic() - started < 1.0
    assert len(adapter.invocations) == 1


def test_failed_stream_observations_and_tool_calls_are_audit_only(tmp_path, monkeypatch):
    _fast_retries(monkeypatch)
    partial = {
        "id": "failed-call",
        "call_id": "failed-call",
        "type": "function_call",
        "name": "write_file",
        "arguments": json_dumps({"path": "must-not-exist.txt", "content": "partial"}),
    }

    def fail_after_partial(request):
        request.observe(ModelObservation("failed-call", "message", partial, provider="stub", model="stub"))
        request.observe(ModelObservation(
            "failed-usage", "usage", {"usage": {"total_tokens": 7}}, usage=Usage(total_tokens=7),
            provider="stub", model="stub",
        ))
        raise ProviderError("stream disconnected", retryable=True,
                            diagnostics={"error_type": "stream_incomplete"})

    adapter = FakeAdapter([fail_after_partial, product_spec()])
    system = LoopSystem(tmp_path, adapter)
    run_id = system.create_run("echo")

    result = system.activate_once(run_id)

    assert result.phase == "ENGINEERING"
    assert "must-not-exist.txt" not in system.workspace(run_id).list_files()
    history = system.orchestrator._department_history_records(run_id, "product")
    assert "failed-call" not in json_dumps(history)
    events = system.store.list_events(run_id)
    assert any(item.type == EventType.MODEL_MESSAGE and item.payload.get("response_id") == "failed-call" for item in events)
    failed = next(item for item in events if item.type == EventType.MODEL_ATTEMPT_FAILED)
    assert failed.error == "stream disconnected"
    assert not any(item.get("response_id") == "failed-call" for item in history)
    assert not any(item.type == EventType.TOOL_STARTED and item.payload.get("id") == "failed-call" for item in events)
    assert "failed-call" not in json_dumps(adapter.invocations[1].input_items)
    assert "must-not-exist.txt" not in json_dumps(adapter.invocations[1].input_items)
    assert result.token_used == 7


def test_malformed_tool_arguments_are_nonretryable_protocol_failure(tmp_path, monkeypatch):
    _fast_retries(monkeypatch)
    malformed = ModelResponse(output=[{
        "id": "bad-call", "call_id": "bad-call", "type": "function_call",
        "name": "read_file", "arguments": "{broken-json",
    }])
    adapter = FakeAdapter([malformed, product_spec()])
    system = LoopSystem(tmp_path, adapter)
    run_id = system.create_run("echo")

    result = system.activate_once(run_id)

    assert result.phase == "FAILED" and result.stop_reason == "provider_error"
    assert len(adapter.invocations) == 1
    events = system.store.list_events(run_id)
    failed = next(item for item in events if item.type == EventType.MODEL_ATTEMPT_FAILED)
    assert failed.payload["retryable"] is False
    assert failed.payload["will_retry"] is False
    assert not any(item.type == EventType.MODEL_MESSAGE and item.payload.get("response_id") == "bad-call" for item in events)
    assert not any(item.type == EventType.TOOL_STARTED and item.payload.get("id") == "bad-call" for item in events)


@pytest.mark.parametrize("response", [
    ModelResponse(finish_reason="failed", error="terminal failure"),
    ModelResponse(output=[{"type": "message"}]),
    ModelResponse(output=[{"id": "same", "type": "message"}, {"id": "same", "type": "reasoning"}]),
    ModelResponse(output=[{
        "id": "bad-call", "type": "function_call", "call_id": "", "name": "read_file",
        "arguments": "{}",
    }]),
    ModelResponse(output=[{
        "id": "bad-call", "type": "function_call", "call_id": "bad-call", "name": "",
        "arguments": "{}",
    }]),
    ModelResponse(output=[{
        "id": "bad-call", "type": "function_call", "call_id": "bad-call", "name": "read_file",
        "arguments": "[]",
    }]),
])
def test_invalid_response_is_rejected_before_recording_and_never_retried(tmp_path, monkeypatch, response):
    _fast_retries(monkeypatch)
    adapter = FakeAdapter([response, product_spec()])
    system = LoopSystem(tmp_path, adapter)
    recorded = []
    monkeypatch.setattr(system.orchestrator, "_reconcile_response", lambda *_args: recorded.append(True))
    run_id = system.create_run("echo")

    result = system.activate_once(run_id)

    assert result.phase == "FAILED" and result.stop_reason in {"provider_error", "cancelled"}
    assert len(adapter.invocations) == 1
    assert recorded == []
    events = system.store.list_events(run_id)
    failure = next(item for item in events if item.type == EventType.MODEL_ATTEMPT_FAILED)
    assert failure.payload["retryable"] is False and failure.payload["will_retry"] is False
    assert not any(item.type == EventType.MODEL_RETRY_SCHEDULED for item in events)
    assert not any(item.type == EventType.TOOL_STARTED for item in events)


def test_compaction_uses_the_same_retry_path(tmp_path, monkeypatch):
    from harness.tests.test_compaction_engine import _message, _read

    _fast_retries(monkeypatch)
    work_count = 0
    compaction_count = 0

    def respond(request):
        nonlocal work_count, compaction_count
        if request.purpose == "compaction":
            compaction_count += 1
            if compaction_count == 1:
                raise ProviderError("temporary compaction failure", retryable=True)
            return ModelResponse(output=[_message(request)])
        work_count += 1
        return _read(request, "large.txt") if work_count == 1 else product_spec()

    adapter = FakeAdapter([respond] * 8)
    system = LoopSystem(tmp_path, adapter)
    run_id = system.create_run("echo", context_window=6000)
    system.workspace(run_id).write_file("large.txt", "ORIGINAL " * 5000)

    result = system.activate_once(run_id)

    assert result.phase == "ENGINEERING" and result.compactions
    attempts = [request for request in adapter.invocations if request.purpose == "compaction"]
    assert len(attempts) >= 2
    assert attempts[0].input_items == attempts[1].input_items
    assert attempts[0].tools == attempts[1].tools == []
    assert attempts[0].root_step_id == attempts[1].root_step_id
