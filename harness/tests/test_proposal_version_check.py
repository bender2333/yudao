from harness.adapters.fake import FakeAdapter
from harness.event_store import StreamVersionConflict, run_stream
from harness.models import EventType
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.tests.helpers import from_another_thread

# 提案校验与提交：流程编排校验提案时记下读取的流版本，提交以它作为期望版本追加；校验以后另一方写入了这个 run，
# 写入口拒绝提交，流程编排按写入以后的状态重新校验与判断。测试包装公开的 WritePath.read（校验时读取运行状态）
# 与 WritePath.transact（记下写入口的拒绝），在校验以后、提交之前从另一个线程完成一次用户操作。


def _write_after_validation(monkeypatch, system, operation):
    read, transact = system.writes.read, system.writes.transact
    versions, done, conflicts = [], [], []

    def read_then_operate(stream):
        snapshot = read(stream)
        versions.append(snapshot.version)
        if len(versions) == 1:
            done.append(from_another_thread(operation))
        return snapshot

    def transact_recording_conflicts(stream, decide, **options):
        try:
            return transact(stream, decide, **options)
        except StreamVersionConflict as exc:
            conflicts.append(exc)
            raise

    monkeypatch.setattr(system.writes, "read", read_then_operate)
    monkeypatch.setattr(system.writes, "transact", transact_recording_conflicts)
    return versions, done, conflicts


def _system(tmp_path, *script):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(list(script)))
    return system, system.create_run("build an echo CLI")


def _events(system, run_id, event_type):
    return [event for event in system.store.list_events(run_id) if event.type == event_type]


def test_input_after_validation_rejects_the_commit_and_the_proposal_is_judged_again(tmp_path, monkeypatch):
    system, run_id = _system(tmp_path, product_spec(), product_spec(requirements=["Print uppercase output"]))
    versions, done, conflicts = _write_after_validation(
        monkeypatch, system, lambda: system.add_input(run_id, "Print uppercase output"))

    result = system.activate_once(run_id)

    [writer] = done
    assert not writer.errors
    # 写入口拒绝以校验时的版本作为期望版本的提交，说明流的实际版本
    [conflict] = conflicts
    assert (conflict.stream, conflict.expected, conflict.actual) == (run_stream(run_id), versions[0], versions[0] + 1)
    # 按写入以后的状态重新校验：激活开始以后输入改变，提案按 execution_basis 拒绝，与没有流版本核对时的结果相同
    assert versions == [versions[0], versions[0] + 1]
    [rejected] = _events(system, run_id, EventType.PROPOSAL_REJECTED)
    assert [error["field"] for error in rejected.payload["errors"]] == ["execution_basis"]
    assert not _events(system, run_id, EventType.SPEC_ACCEPTED)
    assert result.phase == "PRODUCT_SPEC" and result.input_version == 2
    accepted = system.activate_once(run_id)
    assert accepted.product_spec.input_version == 2
    assert accepted.canonical_state() == system.replay(run_id).canonical_state()


def test_a_prompt_update_after_validation_is_judged_again_and_the_proposal_is_accepted(tmp_path, monkeypatch):
    system, run_id = _system(tmp_path, product_spec())
    versions, done, conflicts = _write_after_validation(
        monkeypatch, system, lambda: system.update_prompt(run_id, "product", "A revised product prompt"))

    result = system.activate_once(run_id)

    [writer] = done
    assert not writer.errors
    assert len(conflicts) == 1 and versions == [versions[0], versions[0] + 1]
    # 提示词不改变激活的依据：重新校验以后提案仍然有效，接纳
    assert result.phase == "ENGINEERING" and result.product_spec is not None
    assert not _events(system, run_id, EventType.PROPOSAL_REJECTED)
    types = [event.type for event in system.store.list_events(run_id)]
    assert types.index(EventType.DEPARTMENT_PROMPT_UPDATED) < types.index(EventType.PROPOSAL_SUBMITTED)
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_a_cancel_after_validation_leaves_no_proposal_record(tmp_path, monkeypatch):
    system, run_id = _system(tmp_path, product_spec())
    versions, done, conflicts = _write_after_validation(monkeypatch, system, lambda: system.cancel(run_id))

    result = system.activate_once(run_id)

    [writer] = done
    assert not writer.errors
    assert len(conflicts) == 1 and len(versions) == 2
    assert result.phase == "FAILED" and result.stop_reason == "cancelled"
    assert not _events(system, run_id, EventType.PROPOSAL_SUBMITTED)
    assert not _events(system, run_id, EventType.SPEC_ACCEPTED)
