import threading
from pathlib import Path

import pytest

import harness.interactions as interactions
from harness.adapters.fake import FakeAdapter
from harness.event_store import run_stream
from harness.write_path import NewEvent
from harness.git_versions import GitVersionError
from harness.models import EventType, GIT_VERSION_EVENTS
from harness.proposals import product_spec
from harness.public_tree import TreeError
from harness.runtime import CancelledInputSaveError, LoopSystem, RunTerminalError
from harness.validation import evaluate_proposal
from harness.tightening import WATCHED_OUTPUTS

CHANGE_RECORD = {
    "changed": ["Print the argument in uppercase"],
    "retained": ["Accept one argument"],
    "retired": ["Preserve letter casing"],
    "rationale": "Apply the new user input",
}


def _revision_proposal(basis):
    # 直接提交用的修订提案：依据版本由调用方给出
    return product_spec(requirements=["Print the argument in uppercase"], change_record=CHANGE_RECORD,
                        basis_product_spec_hash=basis)

def _formal(system, run_id):
    return [event for event in system.store.list_events(run_id) if event.type in GIT_VERSION_EVENTS]

def _commit_spec(system, run_id, proposal):
    projection = system.project(run_id)
    snapshot = system.workspace(run_id).snapshot()
    decision = evaluate_proposal(department="product", projection=projection,
                                 facts=snapshot.facts, proposal=proposal, events=system.store.list_events(run_id), tightening=WATCHED_OUTPUTS)
    assert decision.accepted, decision.error_dicts
    return system.writes.transact(run_stream(run_id), lambda transaction: system.orchestrator.submissions.prepare(
        transaction, projection=projection, snapshot=snapshot, environment=system.environment(run_id),
        artifact=decision.artifact, department="product", parent_event_id=projection.last_event_id,
        session_id=projection.sessions["product"].session_id, provider="fake", model="fake",
    ).append(transaction))


@pytest.mark.parametrize("operation", ["initial", "input", "spec"])
def test_git_preparation_failure_does_not_accept_or_publish_materials(tmp_path, monkeypatch, operation):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter())
    run_id = "git_failure"
    if operation != "initial":
        system.create_run("original", run_id=run_id)
    events = system.store.list_events(run_id)

    def fail(*args, **kwargs):
        raise GitVersionError("injected Git storage failure")

    monkeypatch.setattr(system.git_versions, "prepare", fail)
    with pytest.raises(GitVersionError):
        if operation == "initial":
            system.create_run("not accepted", run_id=run_id)
        elif operation == "input":
            system.add_input(run_id, "not accepted")
        else:
            _commit_spec(system, run_id, product_spec())
    assert system.store.list_events(run_id) == events
    material = tmp_path / "materials" / run_id
    assert not (material / "PRD.md").exists()
    if operation == "initial":
        assert not (material / "intend.md").exists()
    else:
        assert (material / "intend.md").read_bytes() == b"original"

def _failing_append(store, event_type):
    # 存储提交含有这种事件的一批事件时失败，整批都不写入
    commit = store.commit

    def failing_commit(stream, expected_version, events, *args, **kwargs):
        if any(event.type == event_type for event in events):
            raise OSError(f"injected {event_type} persistence failure")
        return commit(stream, expected_version, events, *args, **kwargs)

    return failing_commit


def test_spec_and_contract_sqlite_failure_rolls_back_entire_acceptance(tmp_path, monkeypatch):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec()]))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    received = system.add_input(run_id, "Print uppercase")
    # 新输入交给产品工作（与激活开始时流程编排写入的事件相同），产品规格的修订才能接纳
    system.writes.append(run_stream(run_id), NewEvent(
        EventType.PRODUCT_INPUT_ASSIGNED, actor="system", department="product",
        state_before=received.status, state_after="running",
        payload={"through_version": received.input_version}))
    before = system.project(run_id)
    assert before.product_work_input_version == before.input_version == 2
    original_prd = (tmp_path / "materials" / run_id / "PRD.md").read_bytes()
    candidates = []
    prepare = system.git_versions.prepare

    def prepare_candidate(*args, **kwargs):
        revision = prepare(*args, **kwargs)
        candidates.append(revision)
        return revision

    monkeypatch.setattr(system.git_versions, "prepare", prepare_candidate)
    with monkeypatch.context() as failure:
        failure.setattr(system.store, "commit", _failing_append(system.store, EventType.CONTRACT_ACCEPTED))
        with pytest.raises(OSError):
            _commit_spec(system, run_id, _revision_proposal(before.product_spec.content_hash))
    assert system.project(run_id).canonical_state() == before.canonical_state()
    assert (tmp_path / "materials" / run_id / "PRD.md").read_bytes() == original_prd
    assert b'"revision": 2' in system.git_versions.read_file(run_id, candidates[0], "specs/product.json")
    accepted = _commit_spec(system, run_id, _revision_proposal(before.product_spec.content_hash))
    current = system.project(run_id)
    assert accepted.payload["git_version"]["parent_commit"] == before.git_version["commit"]
    assert candidates[0]["commit"] not in {item["commit"] for item in current.git_versions}
    assert current.product_spec.revision == 2 and current.effective_contract.revision == 2


@pytest.mark.parametrize("path", [".git/config", "src/.git/config", ".GIT/config", "src/.GiT/HEAD"])
def test_git_metadata_is_not_accessible_to_workspace_tools(tmp_path, path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter())
    run_id = system.create_run("build echo")
    with pytest.raises(TreeError):
        system.workspace(run_id).write_file(path, "must not write")


@pytest.mark.parametrize("command", [" /cancel\r\n", "\n/stop  "])
@pytest.mark.parametrize("failure", ["git", "material", "input_event", "cancellation_event", "adapter_abort"])
def test_cancel_stops_active_model_when_command_version_cannot_be_saved(tmp_path, monkeypatch, command, failure):
    entered, released = threading.Event(), threading.Event()
    errors = []

    class LateResponseAdapter(FakeAdapter):
        async def stream(self, call):
            items = [item async for item in super().stream(call)]
            entered.set()
            assert released.wait(10)
            for item in items:
                yield item

    system = LoopSystem.for_testing(tmp_path, LateResponseAdapter([product_spec()]))
    run_id = system.create_run("original")
    before = system.project(run_id)

    def activate():
        try:
            system.activate_once(run_id)
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=activate)
    worker.start()
    try:
        assert entered.wait(10)
        commit = system.store.commit
        replace = interactions.os.replace

        def fail(*args, **kwargs):
            raise GitVersionError("injected input version storage failure")

        def fail_publication(source, destination):
            # 发布新的原始意图失败，其余文件照常替换
            if Path(destination).name == "intend.md":
                raise OSError("injected material publication failure")
            return replace(source, destination)

        def fail_event(stream, expected_version, events, *args, **kwargs):
            if any(event.type == EventType.USER_INPUT_RECEIVED or (
                    failure == "cancellation_event" and event.type == EventType.RUN_FAILED) for event in events):
                raise OSError("injected event storage failure")
            return commit(stream, expected_version, events, *args, **kwargs)

        with monkeypatch.context() as patch:
            if failure in {"git", "adapter_abort"}:
                patch.setattr(system.git_versions, "prepare", fail)
            elif failure == "material":
                patch.setattr(interactions.os, "replace", fail_publication)
            else:
                patch.setattr(system.store, "commit", fail_event)
            if failure == "adapter_abort":
                cancel = system.test_adapter.cancel
                attempts = []

                def cancel_after_transient_error(attempt_id):
                    attempts.append(attempt_id)
                    if len(attempts) == 1:
                        raise RuntimeError("injected transient cancel notification failure")
                    cancel(attempt_id)

                patch.setattr(system.test_adapter, "cancel", cancel_after_transient_error)
            with pytest.raises(CancelledInputSaveError) as caught:
                system.add_input(run_id, command)
        assert caught.value.cancelled and caught.value.run_id == run_id
        assert caught.value.cancellation_recorded == (failure != "cancellation_event")
        # 取消已经生效：运行不再接受任何修改
        with pytest.raises(RunTerminalError):
            system.add_guidance(run_id, "product", "The run is already cancelled")
        assert system.test_adapter.cancelled == {system.test_adapter.invocations[0].attempt_id}
        current = system.project(run_id)
        assert current.git_version == before.git_version and current.input_version == before.input_version
        assert not [event for event in _formal(system, run_id) if event.type == EventType.USER_INPUT_RECEIVED]
        if failure != "cancellation_event":
            assert current.status == "failed" and current.stop_reason == "cancelled"
            cancelled = [event for event in system.store.list_events(run_id) if event.type == EventType.RUN_FAILED][-1]
            assert cancelled.payload["input_save_failure"]["text"] == command
            assert "git_version" not in cancelled.payload
    finally:
        released.set()
        worker.join(10)
    assert not worker.is_alive() and not errors
    assert system.project(run_id).product_spec is None
    assert not [event for event in _formal(system, run_id) if event.type == EventType.SPEC_ACCEPTED]
    assert len(system.test_adapter.invocations) == 1
    system.activate_once(run_id)
    assert len(system.test_adapter.invocations) == 1
    with pytest.raises(RunTerminalError):
        system.add_input(run_id, "Do not resume stopped work")
    with pytest.raises(RunTerminalError):
        system.add_guidance(run_id, "product", "Do not resume stopped work")

