from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from harness.adapters.base import AdapterObservation, AdapterResult, ProviderError
from harness.adapters.fake import FakeAdapter
from harness.models import EventType, Usage
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.tools import ToolRuntime


def _message(request, identity, usage):
    request.observe(AdapterObservation(
        identity, "message", {"role": "assistant", "content": "same complete response", "timestamp": 1},
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
    usage = Usage(input_tokens=20, output_tokens=30, cache_read_tokens=60, total_tokens=110, cost=0.25)

    def turn(request):
        _message(request, "first", usage)
        tool = ToolRuntime(request.workspace).execute("product", "read_file", {"path": "proof.txt"})
        call = {"id": "read-1", "name": "read_file", "ok": tool.ok, "output": tool.output}
        request.observe(AdapterObservation("read-1", "tool", call))
        observed.set()
        assert release.wait(5)
        if finish == "timeout":
            raise ProviderError("controlled timeout")
        if finish == "cancelled":
            raise ProviderError("late abort", reason="cancelled")
        _message(request, "second", usage)
        return AdapterResult(product_spec(), transcript="same complete responses", tool_calls=[call], usage=usage.plus(usage))

    system = LoopSystem(tmp_path, FakeAdapter([turn]))
    run_id = system.create_run("echo")
    system.workspace(run_id).write_file("proof.txt", "durable tool evidence")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        try:
            assert observed.wait(5)
            live = system.project(run_id)
            events = system.store.list_events(run_id)
            assert not future.done()
            assert live.token_used == 110 and live.cost == 0.25 and live.tool_count == 1
            message = next(event for event in events if event.type == EventType.MODEL_MESSAGE)
            tool = next(event for event in events if event.payload.get("name") == "read_file")
            assert "same complete response" in system.artifacts.get_text(message.payload["message_ref"]["content_hash"])
            assert "durable tool evidence" in system.artifacts.get_text(tool.payload["output_ref"]["content_hash"])
            if finish == "cancelled":
                assert system.cancel(run_id).stop_reason == "cancelled"
        finally:
            release.set()
        result = future.result(timeout=5)
    messages = [event for event in system.store.list_events(run_id) if event.type == EventType.MODEL_MESSAGE]
    assert result.tool_count == 1
    if finish == "success":
        assert result.phase == "ENGINEERING"
        assert result.token_used == 220 and result.cost == 0.5
        assert len(messages) == 2
    else:
        assert result.phase == "FAILED"
        assert result.token_used == 110 and result.cost == 0.25
        assert len(messages) == 1
    assert "durable tool evidence" in system.artifacts.get_text(tool.payload["output_ref"]["content_hash"])
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_budget_pauses_inside_invoke_and_late_error_cannot_override_it(tmp_path):
    observed, release = Event(), Event()
    continued = []

    def turn(request):
        _message(request, "first", Usage(total_tokens=3000))
        observed.set()
        assert release.wait(5)
        if not request.abort_flag.is_set():
            continued.append("next model round")
        raise ProviderError("provider acknowledged abort", reason="cancelled")

    adapter = FakeAdapter([turn])
    system = LoopSystem(tmp_path, adapter)
    run_id = system.create_run("echo", token_budget=3000)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        try:
            assert observed.wait(5)
            current = system.project(run_id)
            assert current.phase == "PAUSED" and current.stop_reason == "budget_exhausted"
            assert current.token_used == 3000
            assert not future.done()
            assert adapter.invocations[0].abort_flag.is_set()
        finally:
            release.set()
        result = future.result(timeout=5)
    assert not continued
    assert result.phase == "PAUSED" and result.stop_reason == "budget_exhausted"
    assert result.product_spec is None
    assert sum(event.type == EventType.RUN_PAUSED for event in system.store.list_events(run_id)) == 1
    assert not any(event.type == EventType.RUN_FAILED for event in system.store.list_events(run_id))


def test_final_report_replaces_initial_estimate_and_stops_before_handoff(tmp_path):
    system = LoopSystem(tmp_path, FakeAdapter([AdapterResult(product_spec(), usage=Usage(total_tokens=1_000_000))]))
    result = system.activate_once(system.create_run("echo", token_budget=5000))
    assert result.token_used == 1_000_000
    assert result.phase == "PAUSED" and result.stop_reason == "budget_exhausted"
    assert result.product_spec is None
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
