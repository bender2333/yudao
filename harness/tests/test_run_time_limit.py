import time
from unittest.mock import patch

import pytest

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.engine import StepLimits
from harness.models import DEFAULT_MAX_CYCLES, DEFAULT_RUN_TIME_LIMIT_SEC, EventType
from harness.proposals import delivery_turn, plan_turn, product_spec, review_turn
from harness.runtime import LoopSystem
from harness.tests.helpers import happy_script, list_files_turn, run_scripted


def test_time_limit_stops_run_with_failed_state(data_dir):
    # 运行时间限制为 1 秒，适配器包含足够多的回合以超过限制
    script = [product_spec(), plan_turn(), delivery_turn(),
              *[FakeTurn(proposal=None, transcript="working") for _ in range(100)]]
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    run_id = system.create_run("echo", run_time_limit_sec=1, max_cycles=999)
    # 让时间流逝
    system.orchestrator._run_start_times[run_id] = time.monotonic() - 2
    result = system.activate_once(run_id)
    assert result.phase == "FAILED"
    assert result.stop_reason == "time_limit"
    assert result.human_action is not None
    assert "time_limit" in (result.waiting_reason or "")


def test_time_limit_checked_between_activations(data_dir):
    script = [product_spec(), plan_turn(), delivery_turn(),
              review_turn("release", "ok")]
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    run_id = system.create_run("echo", run_time_limit_sec=1)
    # 第一次激活正常完成
    result = system.activate_once(run_id)
    assert result.phase == "ENGINEERING"
    # 模拟时间超过限制
    system.orchestrator._run_start_times[run_id] = time.monotonic() - 2
    result = system.activate_once(run_id)
    assert result.phase == "FAILED"
    assert result.stop_reason == "time_limit"


def test_loosened_defaults_allow_more_than_old_cycle_limit(data_dir):
    # 旧默认值 max_cycles=8，新默认值 999999
    # 用 10 个激活（超过旧限制 8），验证不会暂停
    script = [
        product_spec(),
        *[list_files_turn for _ in range(50)],
        plan_turn(),
        delivery_turn(),
        review_turn("release", "ok"),
    ]
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    run_id = system.create_run("echo")
    # 默认 max_cycles 应该是 DEFAULT_MAX_CYCLES
    projection = system.project(run_id)
    assert projection.max_cycles == DEFAULT_MAX_CYCLES
    assert projection.run_time_limit_sec == DEFAULT_RUN_TIME_LIMIT_SEC
    result = system.run_until_stop(run_id)
    assert result.phase == "DONE"


def test_loosened_step_limit_allows_more_than_32_steps(data_dir):
    # 最大模型步数的默认值是 999999（StepLimits），不再是 32
    # 用超过 32 个步骤后提交，验证不会暂停
    many_steps = [list_files_turn for _ in range(40)]
    script = [
        product_spec(),
        *many_steps,
        plan_turn(),
        delivery_turn(),
        review_turn("release", "ok"),
    ]
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    run_id = system.create_run("echo")
    result = system.run_until_stop(run_id)
    assert result.phase == "DONE"


def test_small_cycle_limit_still_pauses(data_dir):
    script = [product_spec(), plan_turn(), delivery_turn(),
              review_turn("release", "ok")]
    _, projection = run_scripted(data_dir, script, max_cycles=1, run_time_limit_sec=7200)
    assert projection.phase == "PAUSED"
    assert projection.stop_reason == "max_cycles"


def test_small_step_limit_still_pauses(data_dir):
    script = [
        FakeTurn(proposal=None, transcript="step1"),
        FakeTurn(proposal=None, transcript="step2"),
        FakeTurn(proposal=None, transcript="step3"),
        FakeTurn(proposal=None, transcript="step4"),
    ]
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script), step_limits=StepLimits(max_model_steps=3))
    run_id = system.create_run("echo", run_time_limit_sec=7200)
    result = system.activate_once(run_id)
    assert result.phase == "PAUSED"
    assert result.stop_reason == "model_steps_exhausted"


def test_convergence_with_defaults_always_terminates(data_dir):
    # 验证在默认配置下，有限的适配器脚本始终到达终态
    script = happy_script()
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    run_id = system.create_run("echo")
    result = system.run_until_stop(run_id)
    from harness.models import TERMINAL_PHASES
    assert result.phase in TERMINAL_PHASES


def test_convergence_with_long_script_reaches_terminal(data_dir):
    # 用较长脚本验证收敛：即使有很多步骤，最终仍到达终态
    long_script = [
        product_spec(),
        *[list_files_turn for _ in range(100)],
        plan_turn(),
        delivery_turn(),
        review_turn("release", "ok"),
    ]
    system = LoopSystem.for_testing(data_dir, FakeAdapter(long_script))
    run_id = system.create_run("echo", run_time_limit_sec=7200)
    result = system.run_until_stop(run_id)
    from harness.models import TERMINAL_PHASES
    assert result.phase in TERMINAL_PHASES


def test_time_limit_event_recorded(data_dir):
    script = [product_spec(), plan_turn(), delivery_turn(),
              *[FakeTurn(proposal=None, transcript="working") for _ in range(50)]]
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    run_id = system.create_run("echo", run_time_limit_sec=1, max_cycles=999)
    system.orchestrator._run_start_times[run_id] = time.monotonic() - 2
    system.activate_once(run_id)
    events = system.store.list_events(run_id)
    failed_events = [e for e in events if e.type == EventType.RUN_FAILED]
    assert len(failed_events) == 1
    assert failed_events[0].stop_reason == "time_limit"
    assert failed_events[0].payload["stop_reason"] == "time_limit"


def test_time_limit_stored_in_run_created_event(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    run_id = system.create_run("echo", run_time_limit_sec=3600)
    events = system.store.list_events(run_id)
    created = [e for e in events if e.type == EventType.RUN_CREATED]
    assert len(created) == 1
    assert created[0].payload["run_time_limit_sec"] == 3600


def test_run_time_limit_sec_projected(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    run_id = system.create_run("echo", run_time_limit_sec=1800)
    projection = system.project(run_id)
    assert projection.run_time_limit_sec == 1800


def test_per_request_timeout_still_applies_inside_step(data_dir):
    # 单步内的 per-request timeout 仍然生效（由适配器层控制）
    # 这里验证即使时间限制很长，provider 超时错误仍正常处理
    from harness.adapters.base import ProviderError
    script = [FakeTurn(raise_error=ProviderError("timeout", retryable=False))]
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    run_id = system.create_run("echo", run_time_limit_sec=7200)
    result = system.activate_once(run_id)
    assert result.phase == "FAILED"
    assert result.stop_reason == "provider_error"


def test_explicit_small_max_cycles_with_large_time_limit(data_dir):
    # 明确设置小的 max_cycles 和大的时间限制，验证 max_cycles 仍然生效
    script = [product_spec(), plan_turn(), delivery_turn(),
              review_turn("release", "ok")]
    _, projection = run_scripted(data_dir, script, max_cycles=1, run_time_limit_sec=7200)
    assert projection.phase == "PAUSED"
    assert projection.stop_reason == "max_cycles"
