from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from harness.collaboration import has_new_work
from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter
from harness.models import EventType, json_dumps
from harness.proposals import product_spec
from harness.providers.call import CallUsage, ModelResponse, ModelStreamEvent
from harness.runtime import LoopSystem
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

# 本文件里等待一次激活收尾或等待对方线程到达会合点的墙钟界限只用来防止测试一直等待，按 #107 的裁定
# （架构师 2026-09-27 16:55，docs/archive/architecture-issues-2026-09-10.md）设为远大于正常用时的值。
# 收尾包含 Git 版本库写入一次版本，正常用时数秒；这些界限不判定被测行为，
# 被等待的动作是否发生由收尾之后的断言核对。
_WAIT_LIMIT = WAIT_FOR_HOST_WORK_SEC


def _message(identity, usage):
    return ModelStreamEvent(
        kind="message", id=identity,
        payload={"id": identity, "type": "message", "role": "assistant",
                 "content": [{"type": "output_text", "text": "same complete response"}]},
        text="same complete response", usage=usage, provider="test", model="test-model",
    )


def test_cancel_does_not_wait_for_provider_or_accept_its_late_error(tmp_path):
    entered, release = Event(), Event()

    def turn(request):
        entered.set()
        assert release.wait(_WAIT_LIMIT)
        raise ProviderError("late provider failure")

    system = LoopSystem.for_testing(tmp_path, FakeAdapter([turn]))
    run_id = system.create_run("echo")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        try:
            assert entered.wait(_WAIT_LIMIT)
            assert system.cancel(run_id).stop_reason == "cancelled"
            assert not future.done()
        finally:
            release.set()
        result = future.result(timeout=_WAIT_LIMIT)
    assert result.status == "failed" and result.stop_reason == "cancelled"
    assert "late provider failure" not in (result.error or "")
    assert sum(event.type == EventType.RUN_FAILED for event in system.store.list_events(run_id)) == 1


@pytest.mark.parametrize("finish", ["success", "timeout", "cancelled"])
def test_completed_observations_are_live_and_survive_later_stop(tmp_path, finish):
    observed, release = Event(), Event()
    usage = CallUsage(input_tokens=20, output_tokens=30, cache_read_tokens=60, total_tokens=110, cost=0.25,
                      cost_reported=True, reported=True)
    first = ModelResponse(output=[
        {"id": "first", "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "same complete response"}]},
        {"id": "read-1", "call_id": "read-1", "type": "function_call", "name": "read_file", "arguments": '{"path":"proof.txt"}'},
    ], usage=usage)

    def turn(call):
        yield _message("second", usage)
        observed.set()
        assert release.wait(_WAIT_LIMIT)
        if finish == "timeout":
            raise ProviderError("controlled timeout")
        if finish == "cancelled":
            raise ProviderError("late abort", reason="cancelled")
        payload = product_spec()
        payload.pop("kind")
        return ModelResponse(output=[{"id": "submit-1", "call_id": "submit-1", "type": "function_call",
                                      "name": "submit_product_spec", "arguments": json_dumps(payload)}], usage=usage)

    system = LoopSystem.for_testing(tmp_path, FakeAdapter([first, turn]))
    run_id = system.create_run("echo")
    system.workspace(run_id).write_file("proof.txt", "durable tool evidence")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        try:
            assert observed.wait(_WAIT_LIMIT)
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
        result = future.result(timeout=_WAIT_LIMIT)
    messages = [event for event in system.store.list_events(run_id) if event.type == EventType.MODEL_MESSAGE]
    assert result.tool_count == (2 if finish == "success" else 1)
    if finish == "success":
        assert has_new_work(result, "engineering")
        assert result.token_used == 220 and result.cost == 0.5
        assert len(messages) == 4
    else:
        assert result.status == "failed"
        assert result.token_used == 220 and result.cost == 0.5
        assert len(messages) == 3
    assert "durable tool evidence" in system.artifacts.get_text(tool.payload["output_ref"]["content_hash"])
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_provider_usage_does_not_interrupt_a_model_call_or_the_round_of_work(tmp_path):
    observed, release = Event(), Event()
    continued = []

    def turn(call):
        yield _message("first", CallUsage(total_tokens=3000, reported=True))
        observed.set()
        assert release.wait(_WAIT_LIMIT)
        if call.attempt_id not in adapter.cancelled:
            continued.append("next model round")
        return product_spec()

    adapter = FakeAdapter([turn])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        try:
            assert observed.wait(_WAIT_LIMIT)
            current = system.project(run_id)
            assert has_new_work(current, "product") and current.stop_reason is None
            assert current.token_used == 3000
            assert not future.done()
            assert not adapter.cancelled
        finally:
            release.set()
        result = future.result(timeout=_WAIT_LIMIT)
    assert continued
    assert has_new_work(result, "engineering") and result.stop_reason is None
    assert result.product_spec is not None
    assert not any(event.type == EventType.RUN_PAUSED for event in system.store.list_events(run_id))
    assert not any(event.type == EventType.RUN_FAILED for event in system.store.list_events(run_id))


def test_cancel_of_another_run_does_not_abort_current_invocation(tmp_path):
    observed, release = Event(), Event()

    def turn(call):
        observed.set()
        assert release.wait(_WAIT_LIMIT)
        assert call.attempt_id not in adapter.cancelled
        return product_spec()

    adapter = FakeAdapter([turn])
    system = LoopSystem.for_testing(tmp_path, adapter)
    active = system.create_run("active")
    abandoned = system.create_run("abandoned")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, active)
        try:
            assert observed.wait(_WAIT_LIMIT)
            assert system.cancel(abandoned).stop_reason == "cancelled"
            assert not adapter.cancelled
        finally:
            release.set()
        assert has_new_work(future.result(timeout=_WAIT_LIMIT), "engineering")


@pytest.mark.parametrize("reason", ["provider_error", "max_cycles"])
def test_stop_preserves_reported_vendor_and_model_separately_from_adapter(tmp_path, reason):
    response = ModelResponse(
        output=[{"id": "submit", "call_id": "submit", "type": "function_call", "name": "submit_product_spec",
                 "arguments": json_dumps(product_spec())}],
        usage=CallUsage(total_tokens=10000, reported=True),
        provider="actual-vendor", model="actual-model",
    )
    # 脚本按部门给出（工单 #877：PRD 被接纳以后工程与质检同时工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）
    failing = ProviderError("late failure")
    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        "product": [response],
        "engineering": [failing],
        "quality": [failing],
    }))
    result = system.run_until_stop(system.create_run("echo", max_cycles=1 if reason == "max_cycles" else 8))
    assert result.stop_reason == reason
    assert result.provider == "actual-vendor"
    if reason == "provider_error":
        assert result.model is None and result.actual_model is None
    else:
        assert result.model == "actual-model" and result.actual_model == "actual-model"
    assert result.adapter == "fake"
    stop = next(event for event in system.store.list_events(result.run_id)
                if event.type in {EventType.RUN_FAILED, EventType.RUN_PAUSED})
    assert stop.provider == "actual-vendor"
    if reason == "provider_error":
        assert stop.model is None
    else:
        assert stop.model == "actual-model"
