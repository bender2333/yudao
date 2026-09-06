from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from harness.adapters.base import ModelObservation, ModelResponse, ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.models import EventType, Usage, json_dumps
from harness.proposals import product_spec
from harness.runtime import LoopSystem


def _message(request, identity, usage):
    request.observe(ModelObservation(
        identity, "message", {"id": identity, "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "same complete response"}]},
        "same complete response", usage, "test", "test-model",
    ))


def test_cancel_between_validation_and_commit_preserves_terminal_state(tmp_path, monkeypatch):
    import harness.orchestrator as module

    validated, release = Event(), Event()
    evaluate = module.evaluate_proposal

    def blocked_validation(**kwargs):
        decision = evaluate(**kwargs)
        validated.set()
        assert release.wait(5)
        return decision

    monkeypatch.setattr(module, "evaluate_proposal", blocked_validation)
    system = LoopSystem(tmp_path, FakeAdapter([product_spec()]))
    run_id = system.create_run("echo")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        try:
            assert validated.wait(5)
            cancelled = system.cancel(run_id)
            assert cancelled.phase == "FAILED"
            assert cancelled.stop_reason == "cancelled"
        finally:
            release.set()
        result = future.result(timeout=5)
    events = system.store.list_events(run_id)
    assert result.phase == "FAILED" and result.stop_reason == "cancelled"
    assert not any(event.type == EventType.SPEC_ACCEPTED for event in events)
    assert sum(event.type == EventType.RUN_FAILED for event in events) == 1
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_cancel_does_not_wait_for_provider_or_accept_its_late_error(tmp_path):
    entered, release = Event(), Event()

    def turn(request):
        entered.set()
        assert release.wait(5)
        raise ProviderError("late provider failure")

    system = LoopSystem(tmp_path, FakeAdapter([turn]))
    run_id = system.create_run("echo")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        try:
            assert entered.wait(5)
            assert system.cancel(run_id).stop_reason == "cancelled"
            assert not future.done()
        finally:
            release.set()
        result = future.result(timeout=5)
    assert result.phase == "FAILED" and result.stop_reason == "cancelled"
    assert "late provider failure" not in (result.error or "")
    assert sum(event.type == EventType.RUN_FAILED for event in system.store.list_events(run_id)) == 1


@pytest.mark.parametrize("finish", ["success", "timeout", "cancelled"])
def test_completed_observations_are_live_and_survive_later_stop(tmp_path, finish):
    observed, release = Event(), Event()
    usage = Usage(input_tokens=20, output_tokens=30, cache_read_tokens=60, total_tokens=110, cost=0.25, cost_reported=True)
    first = ModelResponse(output=[
        {"id": "first", "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "same complete response"}]},
        {"id": "read-1", "call_id": "read-1", "type": "function_call", "name": "read_file", "arguments": '{"path":"proof.txt"}'},
    ], usage=usage)

    def turn(request):
        _message(request, "second", usage)
        observed.set()
        assert release.wait(5)
        if finish == "timeout":
            raise ProviderError("controlled timeout")
        if finish == "cancelled":
            raise ProviderError("late abort", reason="cancelled")
        payload = product_spec()
        payload.pop("kind")
        return ModelResponse(output=[{"id": "submit-1", "call_id": "submit-1", "type": "function_call",
                                      "name": "submit_product_spec", "arguments": json_dumps(payload)}], usage=usage)

    system = LoopSystem(tmp_path, FakeAdapter([first, turn]))
    run_id = system.create_run("echo")
    system.workspace(run_id).write_file("proof.txt", "durable tool evidence")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        try:
            assert observed.wait(5)
            live = system.project(run_id)
            events = system.store.list_events(run_id)
            assert not future.done()
            assert live.token_used == 220 and live.cost == 0.5 and live.tool_count == 1
            message = next(event for event in events if event.type == EventType.MODEL_MESSAGE)
            tool = next(event for event in events if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "read_file")
            assert "same complete response" in system.artifacts.get_text(message.payload["message_ref"]["content_hash"])
            assert "durable tool evidence" in system.artifacts.get_text(tool.payload["output_ref"]["content_hash"])
            if finish == "cancelled":
                assert system.cancel(run_id).stop_reason == "cancelled"
        finally:
            release.set()
        result = future.result(timeout=5)
    messages = [event for event in system.store.list_events(run_id) if event.type == EventType.MODEL_MESSAGE]
    assert result.tool_count == (2 if finish == "success" else 1)
    if finish == "success":
        assert result.phase == "ENGINEERING"
        assert result.token_used == 220 and result.cost == 0.5
        assert len(messages) == 4
    else:
        assert result.phase == "FAILED"
        assert result.token_used == 220 and result.cost == 0.5
        assert len(messages) == 3
    assert "durable tool evidence" in system.artifacts.get_text(tool.payload["output_ref"]["content_hash"])
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_provider_usage_does_not_interrupt_a_model_call_or_handoff(tmp_path):
    observed, release = Event(), Event()
    continued = []

    def turn(request):
        _message(request, "first", Usage(total_tokens=3000))
        observed.set()
        assert release.wait(5)
        if not request.abort_flag.is_set():
            continued.append("next model round")
        return product_spec()

    adapter = FakeAdapter([turn])
    system = LoopSystem(tmp_path, adapter)
    run_id = system.create_run("echo")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        try:
            assert observed.wait(5)
            current = system.project(run_id)
            assert current.phase == "PRODUCT_SPEC" and current.stop_reason is None
            assert current.token_used == 3000
            assert not future.done()
            assert not adapter.invocations[0].abort_flag.is_set()
        finally:
            release.set()
        result = future.result(timeout=5)
    assert continued
    assert result.phase == "ENGINEERING" and result.stop_reason is None
    assert result.product_spec is not None
    assert not any(event.type == EventType.RUN_PAUSED for event in system.store.list_events(run_id))
    assert not any(event.type == EventType.RUN_FAILED for event in system.store.list_events(run_id))


def test_large_provider_usage_is_recorded_without_stopping_handoff(tmp_path):
    system = LoopSystem(tmp_path, FakeAdapter([FakeTurn(product_spec(), usage=Usage(total_tokens=1_000_000))]))
    result = system.activate_once(system.create_run("echo"))
    assert result.token_used == 1_000_000
    assert result.phase == "ENGINEERING" and result.stop_reason is None
    assert result.product_spec is not None
    assert result.canonical_state() == system.replay(result.run_id).canonical_state()


def test_cancel_of_another_run_does_not_abort_current_invocation(tmp_path):
    observed, release = Event(), Event()

    def turn(request):
        observed.set()
        assert release.wait(5)
        assert not request.abort_flag.is_set()
        return product_spec()

    adapter = FakeAdapter([turn])
    system = LoopSystem(tmp_path, adapter)
    active = system.create_run("active")
    abandoned = system.create_run("abandoned")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, active)
        try:
            assert observed.wait(5)
            assert system.cancel(abandoned).stop_reason == "cancelled"
            assert not adapter._aborted
        finally:
            release.set()
        assert future.result(timeout=5).phase == "ENGINEERING"


@pytest.mark.parametrize("reason", ["provider_error", "max_cycles"])
def test_stop_preserves_reported_vendor_and_model_separately_from_adapter(tmp_path, reason):
    response = ModelResponse(
        output=[{"id": "submit", "call_id": "submit", "type": "function_call", "name": "submit_product_spec",
                 "arguments": json_dumps(product_spec())}],
        usage=Usage(total_tokens=10000),
        provider="actual-vendor", model="actual-model",
    )
    system = LoopSystem(tmp_path, FakeAdapter([response, ProviderError("late failure")]))
    result = system.run_until_stop(system.create_run("echo", max_cycles=1 if reason == "max_cycles" else 8))
    assert result.stop_reason == reason
    assert result.provider == "actual-vendor" and result.model == "actual-model"
    assert result.adapter == "fake"
    stop = next(event for event in system.store.list_events(result.run_id)
                if event.type in {EventType.RUN_FAILED, EventType.RUN_PAUSED})
    assert stop.provider == "actual-vendor" and stop.model == "actual-model"
