import time
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
from harness.tests.helpers import after_event

# 等待一次激活收尾或等待对方线程到达会合点的墙钟界限只用来防止测试一直等待，按 #107 的裁定
# （架构师 2026-09-27 16:55，docs/architecture-issues.md）设为远大于正常用时的值，与 #112 实施方案的
# 120 秒同一口径。收尾含一次版本存储写入，正常用时数秒。
_WAIT_LIMIT = 120


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


def test_input_during_retry_backoff_is_used_by_next_activation(tmp_path):
    # 重试等待 30 秒：新输入在等待中提交，等待立即结束，这次激活不再重试
    scheduled = Event()
    adapter = FakeAdapter([ProviderError("temporary", retryable=True), product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter,
                                    step_limits=StepLimits(retry_initial_delay_sec=30, retry_max_delay_sec=30))
    run_id = system.create_run("original task")
    after_event(system, EventType.MODEL_RETRY_SCHEDULED, lambda _event: scheduled.set())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        assert scheduled.wait(_WAIT_LIMIT)
        system.add_input(run_id, "NEW USER ORIGINAL\nwith exact spacing")
        first_result = future.result(timeout=_WAIT_LIMIT)

    assert first_result.phase == "PRODUCT_SPEC"
    assert len(adapter.invocations) == 1
    second_result = system.activate_once(run_id)

    assert second_result.phase == "ENGINEERING"
    assert len(adapter.invocations) == 2
    content = adapter.invocations[1].input_items[0]["content"]
    assert "[intend]\noriginal taskNEW USER ORIGINAL\nwith exact spacing\n\n" in content
    assert "NEW USER ORIGINAL\nwith exact spacing" in content


@pytest.mark.parametrize("action", ["input", "guidance"])
def test_input_or_guidance_during_a_long_retry_wait_ends_the_wait_at_once(tmp_path, action):
    # 重试等待 30 秒；等待期间到达的新输入或指导使激活立即回到安全节点并停止，不等到间隔结束
    scheduled = Event()
    adapter = FakeAdapter([ProviderError("temporary", retryable=True), product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter,
                                    step_limits=StepLimits(retry_initial_delay_sec=30, retry_max_delay_sec=30))
    run_id = system.create_run("original task")
    after_event(system, EventType.MODEL_RETRY_SCHEDULED, lambda _event: scheduled.set())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        assert scheduled.wait(_WAIT_LIMIT)
        started = time.monotonic()
        if action == "input":
            system.add_input(run_id, "NEW USER ORIGINAL")
        else:
            system.add_guidance(run_id, "product", "Keep the output short")
        result = future.result(timeout=20)

    # 界限 20 秒明显小于配置的 30 秒等待：要证明的是等待没有被走满，结束以后由阶段与停止原因核对；
    # 20 秒同时远大于正常用时（唤醒到激活结束含一次版本存储写入，并发负载下数秒），
    # 按 #107 的裁定（docs/architecture-issues.md，架构师 2026-09-27 16:55）取这一数量级
    assert time.monotonic() - started < 20
    assert result.phase == "PRODUCT_SPEC" and result.stop_reason is None
    assert len(adapter.invocations) == 1


class _CancelFailsAdapter(FakeAdapter):
    # 取消调用尝试时出错的模型接入
    def cancel(self, attempt_id):
        raise RuntimeError("the model adapter could not cancel the attempt")


def test_cancel_wakes_a_long_retry_wait_even_when_cancelling_the_attempt_fails(tmp_path):
    # 取消时模型接入取消调用尝试出错：错误交给取消的调用方，重试等待仍然立即醒来，不再重试
    scheduled = Event()
    adapter = _CancelFailsAdapter([ProviderError("temporary", retryable=True), product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter,
                                    step_limits=StepLimits(retry_initial_delay_sec=30, retry_max_delay_sec=30))
    run_id = system.create_run("original task")
    after_event(system, EventType.MODEL_RETRY_SCHEDULED, lambda _event: scheduled.set())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        assert scheduled.wait(_WAIT_LIMIT)
        started = time.monotonic()
        with pytest.raises(RuntimeError, match="could not cancel"):
            system.cancel(run_id)
        future.result(timeout=20)

    # 界限 20 秒明显小于配置的 30 秒等待：要证明的是等待没有被走满，结束以后由阶段与停止原因核对；
    # 20 秒同时远大于正常用时（唤醒到激活结束含一次版本存储写入，并发负载下数秒），
    # 按 #107 的裁定（docs/architecture-issues.md，架构师 2026-09-27 16:55）取这一数量级
    assert time.monotonic() - started < 20
    assert len(adapter.invocations) == 1


def test_run_time_limit_ends_a_long_retry_wait(tmp_path):
    # 运行时间在重试等待期间用完：等待到运行时间用完就结束，运行以 time_limit 停止
    adapter = FakeAdapter([ProviderError("temporary", retryable=True), product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter,
                                    step_limits=StepLimits(retry_initial_delay_sec=30, retry_max_delay_sec=30))
    run_id = system.create_run("original task", run_time_limit_sec=1)

    started = time.monotonic()
    result = system.activate_once(run_id)

    assert time.monotonic() - started < 10
    assert result.phase == "FAILED" and result.stop_reason == "time_limit"
    assert len(adapter.invocations) == 1
    assert any(item.type == EventType.MODEL_RETRY_SCHEDULED for item in system.store.list_events(run_id))


@pytest.mark.parametrize("action", ["input", "cancel"])
def test_input_or_cancel_after_a_retryable_failure_prevents_the_retry(tmp_path, action):
    adapter = FakeAdapter([ProviderError("temporary", retryable=True), product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("original task")

    def interleave(event):
        # 这次尝试已经按将要重试记录，重试安排之前到达新输入或取消
        assert event.payload["will_retry"] is True
        if action == "input":
            system.add_input(run_id, "NEW USER ORIGINAL")
        else:
            system.cancel(run_id)

    after_event(system, EventType.MODEL_ATTEMPT_FAILED, interleave)
    result = system.activate_once(run_id)

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
