import threading

import pytest

from harness.collaboration import has_new_work
from harness.adapters.fake import FakeAdapter
from harness.models import EventType
from harness.projects import WorkItemInProgressError
from harness.proposals import product_spec
from harness.runtime import LoopSystem, RunTerminalError
from harness.tests.helpers import after_event, from_another_thread, happy_script

# 同时到达的用户命令：写入口不持有锁，另一方的写入使提交被拒绝后按写入以后的状态重新判断。
# 这里的操作在写入方的判断以后、提交之前从另一个线程完成（包装公开的 EventStore.commit 与流程编排的公开方法）。


def _before_first_commit_of(monkeypatch, system, event_type, operation):
    # 第一次提交含有 event_type 的事件之前，从另一个线程完成 operation
    commit = system.store.commit
    started, done = [], []

    def commit_after_operation(stream, expected_version, events, *args, **kwargs):
        if not started and any(event.type == event_type for event in events):
            started.append(True)
            done.append(from_another_thread(operation))
        return commit(stream, expected_version, events, *args, **kwargs)

    monkeypatch.setattr(system.store, "commit", commit_after_operation)
    return done


def test_an_input_losing_to_a_stop_command_leaves_the_committed_original_published(tmp_path, monkeypatch):
    # 输入已经发布了自己的原始意图，提交之前 /stop 先提交：输入的提交被拒绝，重新判断时运行已经中止；
    # 发布的原始意图是已经提交的内容（含 /stop 的原文），与事件记录一致
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([]))
    run_id = system.create_run("original")
    done = _before_first_commit_of(monkeypatch, system, EventType.USER_INPUT_RECEIVED,
                                   lambda: system.add_input(run_id, "/stop"))

    with pytest.raises(RunTerminalError):
        system.add_input(run_id, " late input")

    [stopper] = done
    assert not stopper.errors
    current = system.project(run_id)
    assert current.status == "failed" and current.stop_reason == "cancelled"
    assert [item.text for item in current.inputs] == ["original", "/stop"]
    published = (tmp_path / "materials" / run_id / "intend.md").read_bytes()
    assert published == b"original/stop"
    assert published == system.artifacts.get_for_run(run_id, current.inputs[-1].intend_ref)


def test_two_inputs_at_once_both_enter_the_published_original_in_commit_order(tmp_path, monkeypatch):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([]))
    run_id = system.create_run("original")
    done = _before_first_commit_of(monkeypatch, system, EventType.USER_INPUT_RECEIVED,
                                   lambda: system.add_input(run_id, " first"))

    system.add_input(run_id, " second")

    [other] = done
    assert not other.errors
    current = system.project(run_id)
    assert [item.text for item in current.inputs] == ["original", " first", " second"]
    assert (tmp_path / "materials" / run_id / "intend.md").read_bytes() == b"original first second"


def test_a_cancellation_that_could_not_be_written_is_written_by_the_run_loop(tmp_path, monkeypatch):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec()]))
    run_id = system.create_run("original")
    commit = system.store.commit

    def fail_cancellation(stream, expected_version, events, *args, **kwargs):
        if any(event.type == EventType.RUN_FAILED for event in events):
            raise OSError("injected cancellation storage failure")
        return commit(stream, expected_version, events, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(system.store, "commit", fail_cancellation)
        with pytest.raises(OSError):
            system.cancel(run_id)
    # 中止已经生效，取消没有写入；没有正在进行的取消时，运行循环写入取消，不再激活部门
    assert has_new_work(system.project(run_id), "product")
    result = system.run_until_stop(run_id)
    assert result.status == "failed" and result.stop_reason == "cancelled"
    assert not system.test_adapter.invocations


@pytest.mark.parametrize("operation", ["activate_once", "run_until_stop"])
def test_a_run_cancelled_from_another_thread_during_a_model_call_returns_cancelled(tmp_path, monkeypatch, operation):
    # 激活的模型调用已经返回时取消才提交：激活收尾等待取消写入，结束事件在取消之后
    cancel_started, activation_returned, finish_committed = threading.Event(), threading.Event(), threading.Event()
    errors, cancellers = [], []

    def cancel():
        try:
            system.cancel(run_id)
        except Exception as exc:
            errors.append(exc)

    def cancel_during_call(_call):
        cancellers.append(threading.Thread(target=cancel))
        cancellers[0].start()
        assert cancel_started.wait(10)
        return product_spec()

    system = LoopSystem.for_testing(tmp_path, FakeAdapter([cancel_during_call]))
    run_id = system.create_run("original")
    commit = system.store.commit
    invoke = system.orchestrator._invoke_activation

    def commit_after_activation_returns(stream, expected_version, events, *args, **kwargs):
        types = {event.type for event in events}
        if EventType.RUN_FAILED in types:
            cancel_started.set()
            assert activation_returned.wait(10)
            # 激活收尾不等待取消时，它的结束事件在这段时间内提交，取消排在它之后
            finish_committed.wait(2)
        committed = commit(stream, expected_version, events, *args, **kwargs)
        if EventType.ACTIVATION_FINISHED in types:
            finish_committed.set()
        return committed

    async def invoke_then_signal(activation):
        await invoke(activation)
        activation_returned.set()

    monkeypatch.setattr(system.store, "commit", commit_after_activation_returns)
    monkeypatch.setattr(system.orchestrator, "_invoke_activation", invoke_then_signal)

    result = getattr(system, operation)(run_id)
    cancellers[0].join(10)

    assert not errors
    assert not cancellers[0].is_alive()
    assert result.status == "failed" and result.stop_reason == "cancelled"
    events = system.store.list_events(run_id)
    assert [event.type for event in events[-2:]] == [EventType.RUN_FAILED, EventType.ACTIVATION_FINISHED]
    assert system.project(run_id).sessions["product"].status == "closed"


def test_archiving_while_a_work_item_is_starting_is_rejected(tmp_path, monkeypatch):
    # 事项已经登记、它的 run 正在创建时归档与记录材料：事项算作进行中，拒绝
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(happy_script()))
    project_id = system.projects.register("项目", "逐行文本处理工具")
    create_run = system.orchestrator.create_run
    attempts = []

    def create_run_with_archive(*args, **kwargs):
        attempts.append(from_another_thread(lambda: system.projects.archive(project_id)))
        attempts.append(from_another_thread(lambda: system.projects.record_material(project_id, "材料")))
        return create_run(*args, **kwargs)

    monkeypatch.setattr(system.orchestrator, "create_run", create_run_with_archive)
    work_item_id, run_id = system.projects.start_work_item(project_id, "第一个事项")

    assert [type(error) for attempt in attempts for error in attempt.errors] == [WorkItemInProgressError] * 2
    project = system.projects.projection(project_id)
    assert not project.archived and project.materials == []
    assert project.work_item(work_item_id).status == "in_progress"
    assert has_new_work(system.project(run_id), "product")
