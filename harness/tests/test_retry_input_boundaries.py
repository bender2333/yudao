from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from harness.adapters.base import ProviderError
from harness.providers.call import ModelResponse
from harness.adapters.fake import FakeAdapter
from harness.engine import StepLimits
from harness.models import EventType
from harness.proposals import product_spec
from harness.runtime import LoopSystem


def test_retryable_failure_after_new_input_returns_to_product_without_retry(tmp_path):
    run_id_holder = []

    def fail_after_input(_request):
        system.add_input(run_id_holder[0], "NEW USER ORIGINAL")
        raise ProviderError("temporary connection failure", retryable=True)

    adapter = FakeAdapter([fail_after_input, product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("original task")
    run_id_holder.append(run_id)

    result = system.activate_once(run_id)

    events = system.store.list_events(run_id)
    failed = [item for item in events if item.type == EventType.MODEL_ATTEMPT_FAILED]
    assert result.phase == "PRODUCT_SPEC"
    assert result.stop_reason is None
    assert result.input_version == 2
    assert len(adapter.invocations) == 1
    assert not any(item.type == EventType.RUN_FAILED for item in events)
    assert not any(item.type == EventType.MODEL_RETRY_SCHEDULED for item in events)
    assert len(failed) == 1 and failed[0].payload["will_retry"] is False


def test_input_during_retry_backoff_is_used_by_next_activation(tmp_path, monkeypatch):
    scheduled = Event()
    adapter = FakeAdapter([ProviderError("temporary", retryable=True), product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter,
                                    step_limits=StepLimits(retry_initial_delay_sec=0.2, retry_max_delay_sec=0.2))
    run_id = system.create_run("original task")
    original = system.orchestrator._record_retry_scheduled

    def record(*args):
        result = original(*args)
        scheduled.set()
        return result

    monkeypatch.setattr(system.orchestrator, "_record_retry_scheduled", record)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        assert scheduled.wait(5)
        system.add_input(run_id, "NEW USER ORIGINAL\nwith exact spacing")
        first_result = future.result(timeout=5)

    assert first_result.phase == "PRODUCT_SPEC"
    assert len(adapter.invocations) == 1
    second_result = system.activate_once(run_id)

    assert second_result.phase == "ENGINEERING"
    assert len(adapter.invocations) == 2
    content = adapter.invocations[1].input_items[0]["content"]
    assert "[intend]\noriginal taskNEW USER ORIGINAL\nwith exact spacing\n\n" in content
    assert "NEW USER ORIGINAL\nwith exact spacing" in content


@pytest.mark.parametrize("action", ["input", "cancel"])
def test_retry_schedule_admission_rechecks_interleaved_input_or_cancel(tmp_path, monkeypatch, action):
    entered = Event()
    release = Event()
    adapter = FakeAdapter([ProviderError("temporary", retryable=True), product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("original task")
    original = system.orchestrator._record_retry_scheduled

    def block_before_admission(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(system.orchestrator, "_record_retry_scheduled", block_before_admission)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        assert entered.wait(5)
        if action == "input":
            system.add_input(run_id, "NEW USER ORIGINAL")
        else:
            system.cancel(run_id)
        release.set()
        result = future.result(timeout=5)

    events = system.store.list_events(run_id)
    assert len(adapter.invocations) == 1
    assert not any(item.type == EventType.MODEL_RETRY_SCHEDULED for item in events)
    if action == "input":
        assert result.phase == "PRODUCT_SPEC"
        assert not any(item.type == EventType.RUN_FAILED for item in events)
    else:
        assert result.phase == "FAILED" and result.stop_reason == "cancelled"


def test_model_attempts_are_bounded_by_model_steps(tmp_path):
    def transient_until_step_limit(request):
        if request.step_id % 3 == 0:
            return ModelResponse()
        return ProviderError("temporary", retryable=True)

    adapter = FakeAdapter([transient_until_step_limit] * 10)
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=StepLimits(max_model_steps=5))
    result = system.activate_once(system.create_run("original task"))

    assert result.phase == "PAUSED" and result.stop_reason == "model_steps_exhausted"
    assert len(adapter.invocations) == 5
    assert [request.step_id for request in adapter.invocations] == [1, 2, 3, 4, 5]
    assert [request.attempt for request in adapter.invocations] == [1, 2, 3, 1, 2]
    assert len(adapter.invocations) < 5 * 3
