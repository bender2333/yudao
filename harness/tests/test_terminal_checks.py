from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter
from harness.engine import StepLimits
from harness.models import EventType
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.tests.helpers import FAST_RETRIES, from_another_thread

# 终态写入带核对：步骤驱动交回带原因的停止结果以后，流程编排在一个事务中写入终态，并核对作出停止判断以后
# 有没有用户的命令或输入写入。测试在写终态的事务判断完成、提交之前，让另一个线程写入用户的操作：
# 写入口拒绝这次提交，流程编排按写入以后的状态重新判断。


def _write_during_terminal(monkeypatch, system, operation):
    # 包装公开的 WritePath.transact：第一次出现写入终态的判断时，在它提交之前从另一个线程完成 operation
    transact = system.writes.transact
    started = []
    done = []

    def transact_with_operation(stream, decide, **options):
        def decide_then_operate(transaction):
            result = decide(transaction)
            terminal = any(event.type in {EventType.RUN_FAILED, EventType.RUN_PAUSED} for event in transaction.appended)
            if terminal and not started:
                started.append(True)
                done.append(from_another_thread(operation))
            return result

        return transact(stream, decide_then_operate, **options)

    monkeypatch.setattr(system.writes, "transact", transact_with_operation)
    return done


def _retries_exhausted(tmp_path, *later):
    adapter = FakeAdapter([ProviderError("temporary", retryable=True) for _ in range(3)] + list(later))
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    return system, adapter, system.create_run("original task")


def _types(system, run_id):
    return [event.type for event in system.store.list_events(run_id)]


def test_input_written_before_the_failure_commits_keeps_the_run_going(tmp_path, monkeypatch):
    system, adapter, run_id = _retries_exhausted(tmp_path, product_spec())
    done = _write_during_terminal(monkeypatch, system, lambda: system.add_input(run_id, "Use uppercase output"))

    stopped = system.activate_once(run_id)

    [writer] = done
    assert not writer.errors
    # 新输入使重试用完的失败判断过期：运行没有结束，下一次激活处理新输入
    assert stopped.phase == "PRODUCT_SPEC" and stopped.stop_reason is None
    assert EventType.RUN_FAILED not in _types(system, run_id)
    assert stopped.input_version == 2 and len(adapter.invocations) == 3
    resumed = system.activate_once(run_id)
    assert resumed.phase == "ENGINEERING" and resumed.product_spec.input_version == 2
    assert resumed.canonical_state() == system.replay(run_id).canonical_state()


def test_guidance_written_before_the_failure_commits_keeps_the_run_going(tmp_path, monkeypatch):
    system, _adapter, run_id = _retries_exhausted(tmp_path)
    done = _write_during_terminal(monkeypatch, system,
                                  lambda: system.add_guidance(run_id, "product", "Keep the output short"))

    stopped = system.activate_once(run_id)

    [writer] = done
    assert not writer.errors
    assert stopped.phase == "PRODUCT_SPEC" and EventType.RUN_FAILED not in _types(system, run_id)
    assert [item.status for item in stopped.department_guidance] == ["received"]


def test_a_prompt_update_does_not_change_the_failure(tmp_path, monkeypatch):
    system, _adapter, run_id = _retries_exhausted(tmp_path)
    done = _write_during_terminal(monkeypatch, system,
                                  lambda: system.update_prompt(run_id, "product", "A revised product prompt"))

    failed = system.activate_once(run_id)

    [writer] = done
    assert not writer.errors
    # 提示词不改变激活的依据：重新判断以后仍然以重试用完的原因失败，提示词的修改在失败之前
    assert failed.phase == "FAILED" and failed.stop_reason == "provider_error"
    types = _types(system, run_id)
    assert types.index(EventType.DEPARTMENT_PROMPT_UPDATED) < types.index(EventType.RUN_FAILED)
    assert types.count(EventType.RUN_FAILED) == 1


def test_a_stop_command_written_before_the_failure_commits_leaves_only_the_cancellation(tmp_path, monkeypatch):
    system, _adapter, run_id = _retries_exhausted(tmp_path)
    done = _write_during_terminal(monkeypatch, system, lambda: system.add_input(run_id, "/stop"))

    stopped = system.activate_once(run_id)

    [writer] = done
    assert not writer.errors
    assert stopped.phase == "FAILED" and stopped.stop_reason == "cancelled"
    failures = [event for event in system.store.list_events(run_id) if event.type == EventType.RUN_FAILED]
    assert [event.stop_reason for event in failures] == ["cancelled"]


def test_input_written_before_the_time_limit_commits_still_ends_the_run(tmp_path, monkeypatch):
    # 运行时间用完以后在安全节点停止；写入 time_limit 之前到达的新输入不改变运行时间用完
    adapter = FakeAdapter([ProviderError("temporary", retryable=True), product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter,
                                    step_limits=StepLimits(retry_initial_delay_sec=30, retry_max_delay_sec=30))
    run_id = system.create_run("original task", run_time_limit_sec=1)
    done = _write_during_terminal(monkeypatch, system, lambda: system.add_input(run_id, "A late input"))

    failed = system.activate_once(run_id)

    [writer] = done
    assert not writer.errors
    assert failed.phase == "FAILED" and failed.stop_reason == "time_limit"
    types = _types(system, run_id)
    assert types.index(EventType.USER_INPUT_RECEIVED) < types.index(EventType.RUN_FAILED)
    assert failed.canonical_state() == system.replay(run_id).canonical_state()
