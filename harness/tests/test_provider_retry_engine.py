import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter
from harness.watched_outputs import has_new_work
from harness.engine import StepLimits
from harness.models import EventType, json_dumps
from harness.proposals import product_spec
from harness.providers.call import CallUsage, ModelResponse, ModelStreamEvent
from harness.runtime import LoopSystem
from harness.tests.helpers import FAST_RETRIES, after_event, department_history
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC


def test_transient_failure_retries_same_logical_request_then_succeeds(tmp_path):
    adapter = FakeAdapter([
        ProviderError("temporary connection failure", retryable=True,
                      diagnostics={"error_type": "connection"}),
        product_spec(),
    ])
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    run_id = system.create_run("echo")

    result = system.activate_once(run_id)

    assert has_new_work(result, "engineering")
    first, second = adapter.invocations
    assert first.department == second.department == "product"
    assert first.activation_id == second.activation_id
    assert first.input_items == second.input_items and first.tools == second.tools
    assert (first.attempt, second.attempt) == (1, 2)
    assert first.logical_call_id == second.logical_call_id == f"{first.activation_id}:root-1:work"
    events = system.store.list_events(run_id)
    requested = [item.payload for item in events if item.type == EventType.MODEL_REQUESTED]
    assert [(item["attempt"], item["root_step_id"], item["retry_of_step_id"]) for item in requested] == [
        (1, 1, None), (2, 1, 1)]
    assert len([item for item in events if item.type == EventType.MODEL_ATTEMPT_FAILED]) == 1
    assert len([item for item in events if item.type == EventType.MODEL_RETRY_SCHEDULED]) == 1
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_retry_exhaustion_records_all_attempts_and_fails_once(tmp_path):
    failures = [ProviderError("temporary", retryable=True) for _ in range(3)]
    adapter = FakeAdapter(failures)
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    run_id = system.create_run("echo")

    result = system.activate_once(run_id)

    assert result.status == "failed" and result.stop_reason == "provider_error"
    assert [request.attempt for request in adapter.invocations] == [1, 2, 3]
    events = system.store.list_events(run_id)
    failed = [item for item in events if item.type == EventType.MODEL_ATTEMPT_FAILED]
    scheduled = [item for item in events if item.type == EventType.MODEL_RETRY_SCHEDULED]
    assert len(failed) == 3 and len(scheduled) == 2
    assert failed[-1].payload["will_retry"] is False


def test_retry_after_over_max_stops_without_waiting(tmp_path):
    adapter = FakeAdapter([
        ProviderError("temporary", retryable=True, diagnostics={"retry_after_sec": 60.1}),
        product_spec(),
    ])
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    run_id = system.create_run("echo")

    started = time.monotonic()
    result = system.activate_once(run_id)

    assert time.monotonic() - started < 30
    assert result.status == "failed" and result.stop_reason == "retry_after_too_long"
    assert len(adapter.invocations) == 1
    events = system.store.list_events(run_id)
    assert not any(item.type == EventType.MODEL_RETRY_SCHEDULED for item in events)
    failed = next(item for item in events if item.type == EventType.MODEL_ATTEMPT_FAILED)
    assert failed.payload["will_retry"] is False
    assert failed.payload["reason"] == "retry_after_too_long"
    assert failed.payload["diagnostics"]["retry_after_sec"] == 60.1


@pytest.mark.parametrize("reason", ["context_overflow", "provider_error", "cancelled"])
def test_nonretryable_provider_error_is_never_retried(tmp_path, reason):
    adapter = FakeAdapter([ProviderError("permanent", reason=reason), product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    run_id = system.create_run("echo")

    result = system.activate_once(run_id)

    assert len(adapter.invocations) == 1
    assert result.stop_reason == reason
    events = system.store.list_events(run_id)
    assert len([item for item in events if item.type == EventType.MODEL_ATTEMPT_FAILED]) == 1
    assert not any(item.type == EventType.MODEL_RETRY_SCHEDULED for item in events)


# 工单 #1133：这条用例原先用「取消到这一轮结束不到 1 秒」证明取消打断了重试的退避等待，
# 运行机负载下一次测到 1.34 秒就失败。现在判定落在事件上：这一轮自己记下的用时
# （ACTIVATION_FINISHED 的 latency_ms）小于它自己安排的退避（MODEL_RETRY_SCHEDULED 的 delay_sec），
# 就是「退避没有被走满」；取消写进了事件、事件里没有第二次尝试，就是「取消打断了等待、没有下一次尝试」。
# 两处间隔都不判定被测行为：等事件的上限只用来防止测试一直等待（#107 的裁定、#233 集中的口径）；
# 会合界限给「立即」一个量级上限，比配置的退避小、比负载下正常用时大两个数量级
# （与 test_retry_input_boundaries.py 的 30 秒等待配 20 秒界限同一口径）。
_BACKOFF_SEC = 30.0
_INTERRUPTED_WITHIN_SEC = 20.0


def test_cancel_interrupts_retry_backoff_without_next_attempt(tmp_path):
    scheduled = Event()
    adapter = FakeAdapter([ProviderError("temporary", retryable=True), product_spec()])
    system = LoopSystem.for_testing(
        tmp_path, adapter,
        step_limits=StepLimits(retry_initial_delay_sec=_BACKOFF_SEC, retry_max_delay_sec=_BACKOFF_SEC))
    run_id = system.create_run("echo")
    after_event(system, EventType.MODEL_RETRY_SCHEDULED, lambda _event: scheduled.set())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        assert scheduled.wait(WAIT_FOR_HOST_WORK_SEC)
        system.cancel(run_id)
        try:
            result = future.result(timeout=_INTERRUPTED_WITHIN_SEC)
        except TimeoutError:
            # 会合不到就是等待没有被提前结束：退避会自己走满，这一轮才结束
            result = None

    assert result is not None, (f"取消没有在 {_INTERRUPTED_WITHIN_SEC} 秒内结束这一轮："
                                f"{_BACKOFF_SEC} 秒的退避等待没有被提前结束")
    assert result.stop_reason == "cancelled"
    assert len(adapter.invocations) == 1

    events = system.store.list_events(run_id)
    kinds = [item.type for item in events]
    requested = [item.payload for item in events if item.type == EventType.MODEL_REQUESTED]
    failed = [item.payload for item in events if item.type == EventType.MODEL_ATTEMPT_FAILED]
    retry = [item.payload for item in events if item.type == EventType.MODEL_RETRY_SCHEDULED]
    cancelled = [item.payload for item in events if item.type == EventType.RUN_FAILED]
    finished = [item.payload for item in events if item.type == EventType.ACTIVATION_FINISHED]
    # 只发起过第一次尝试，重试已经安排：第二次尝试排在退避之后
    assert [item["attempt"] for item in requested] == [1]
    assert [item["attempt"] for item in failed] == [1] and failed[0]["will_retry"] is True
    assert [(item["attempt"], item["next_attempt"], item["delay_sec"]) for item in retry] == [
        (1, 2, _BACKOFF_SEC)]
    # 取消的结果写进了事件，位置在重试安排之后、这一轮的结束之前
    assert [item["stop_reason"] for item in cancelled] == ["cancelled"]
    assert kinds.index(EventType.MODEL_RETRY_SCHEDULED) < kinds.index(EventType.RUN_FAILED)
    assert kinds.index(EventType.RUN_FAILED) < kinds.index(EventType.ACTIVATION_FINISHED)
    # 退避没有被走满：这一轮自己记下的用时小于它自己安排的退避
    assert finished[-1]["stop_reason"] == "cancelled"
    assert finished[-1]["latency_ms"] < retry[0]["delay_sec"] * 1000
    # 取消之后没有发起下一次尝试：整个事件流里没有 attempt 大于 1 的请求或失败
    assert [item["attempt"] for item in requested + failed if item["attempt"] > 1] == []


def test_failed_stream_observations_and_tool_calls_are_audit_only(tmp_path):
    partial = {
        "id": "failed-call",
        "call_id": "failed-call",
        "type": "function_call",
        "name": "write_file",
        "arguments": json_dumps({"path": "must-not-exist.txt", "content": "partial"}),
    }

    def fail_after_partial(request):
        yield ModelStreamEvent(kind="message", id="failed-call", payload=partial, provider="stub", model="stub")
        yield ModelStreamEvent(kind="usage", id="failed-usage", payload={"usage": {"total_tokens": 7}},
                               usage=CallUsage(total_tokens=7, reported=True), provider="stub", model="stub")
        raise ProviderError("stream disconnected", retryable=True,
                            diagnostics={"error_type": "stream_incomplete"})

    adapter = FakeAdapter([fail_after_partial, product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    run_id = system.create_run("echo")

    result = system.activate_once(run_id)

    assert has_new_work(result, "engineering")
    assert "must-not-exist.txt" not in system.workspace(run_id).list_files()
    history = department_history(system, run_id, "product")
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


@pytest.mark.parametrize("raw_arguments", ["{broken-json", "[]", None])
def test_malformed_tool_arguments_are_returned_to_model_without_starting_tool(tmp_path, raw_arguments):
    malformed = ModelResponse(output=[{
        "id": "bad-call", "call_id": "bad-call", "type": "function_call",
        "name": "read_file", "arguments": raw_arguments,
    }])
    adapter = FakeAdapter([malformed, product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    run_id = system.create_run("echo")

    result = system.activate_once(run_id)

    # 产品要求被接纳以后工程有新的工作（工单 #556：工程关注 PRD 的新版本）
    assert has_new_work(result, "engineering")
    assert len(adapter.invocations) == 2
    events = system.store.list_events(run_id)
    assert any(item.type == EventType.MODEL_MESSAGE and item.payload.get("response_id") == "bad-call" for item in events)
    assert not any(item.type == EventType.TOOL_STARTED and item.payload.get("id") == "bad-call" for item in events)
    assert any(item.type == EventType.TOOL_CALLED and item.payload.get("id") == "bad-call"
               and item.payload.get("ok") is False for item in events)
    assert "invalid tool arguments" in json_dumps(adapter.invocations[1].input_items)


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
])
def test_invalid_response_is_rejected_before_recording_and_never_retried(tmp_path, response):
    adapter = FakeAdapter([response, product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    run_id = system.create_run("echo")

    result = system.activate_once(run_id)

    assert result.status == "failed" and result.stop_reason in {"provider_error", "cancelled"}
    assert len(adapter.invocations) == 1
    events = system.store.list_events(run_id)
    assert not any(item.type == EventType.MODEL_MESSAGE for item in events)
    failure = next(item for item in events if item.type == EventType.MODEL_ATTEMPT_FAILED)
    assert failure.payload["retryable"] is False and failure.payload["will_retry"] is False
    assert not any(item.type == EventType.MODEL_RETRY_SCHEDULED for item in events)
    assert not any(item.type == EventType.TOOL_STARTED for item in events)


def test_compaction_uses_the_same_retry_path(tmp_path):
    from harness.tests.helpers import read_file_call as _read, summary_message as _message

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
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    run_id = system.create_run("echo", context_window=6000)
    system.workspace(run_id).write_file("large.txt", "ORIGINAL " * 5000)

    result = system.activate_once(run_id)

    assert has_new_work(result, "engineering") and result.compactions
    attempts = [request for request in adapter.invocations if request.purpose == "compaction"]
    assert len(attempts) >= 2
    assert attempts[0].input_items == attempts[1].input_items
    assert attempts[0].tools == attempts[1].tools == []
    assert attempts[0].logical_call_id == attempts[1].logical_call_id
