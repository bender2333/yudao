import json
import threading
from pathlib import Path

import pytest

import harness.interactions as interactions
from harness.adapters.fake import FakeAdapter
from harness.write_path import NewEvent
from harness.git_versions import GitVersionError
from harness.models import EventType, GIT_VERSION_EVENTS
from harness.proposals import delivery_turn, plan_turn, product_spec, review_turn
from harness.public_tree import TreeError, capture_public_tree, materialize_tree
from harness.runtime import CancelledInputSaveError, LoopSystem, RunTerminalError
from harness.tree_archive import load_tree
from harness.validation import evaluate_proposal


CHANGE_RECORD = {
    "changed": ["Print the argument in uppercase"],
    "retained": ["Accept one argument"],
    "retired": ["Preserve letter casing"],
    "rationale": "Apply the new user input",
}


def _revision():
    return product_spec(requirements=["Print the argument in uppercase"], change_record=CHANGE_RECORD)


def _formal(system, run_id):
    return [event for event in system.store.list_events(run_id) if event.type in GIT_VERSION_EVENTS]


def _commit_spec(system, run_id, proposal):
    projection = system.project(run_id)
    snapshot = system.workspace(run_id).snapshot()
    decision = evaluate_proposal(phase=projection.phase, department="product", projection=projection,
                                 facts=snapshot.facts, proposal=proposal, events=system.store.list_events(run_id))
    assert decision.accepted, decision.error_dicts
    return system.orchestrator.submissions.commit(
        projection=projection, snapshot=snapshot, workspace_root=system.workspace(run_id).root,
        artifact=decision.artifact, department="product", parent_event_id=projection.last_event_id,
        session_id=projection.sessions["product"].session_id, provider="fake", model="fake",
    )


def test_new_input_and_requirement_diff_form_one_accepted_history_through_redelivery(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        product_spec(), plan_turn(), delivery_turn(), _revision(), plan_turn(reason="Apply the uppercase requirement"),
        delivery_turn(files={"src/echo.py": "import sys\nprint(sys.argv[1].upper())\n"}),
        review_turn("release", "Uppercase output was independently verified"),
    ]))
    run_id = system.create_run("  build echo\r\n", max_cycles=12)
    for _ in range(3):
        before = system.activate_once(run_id)
    old_spec_event = system.store.get_event(before.product_spec.created_event_id)
    old_code = system.git_versions.read_file(run_id, before.git_version, "code/src/echo.py")
    system.update_prompt(run_id, "quality", "Inspect the current requirement carefully")
    assert system.project(run_id).git_version == before.git_version
    system.workspace(run_id).write_file("src/echo.py", "unfinished engineering change")
    received = system.add_input(run_id, "Print uppercase now")
    assert system.git_versions.read_file(run_id, received.git_version, "intend.md") == b"  build echo\r\nPrint uppercase now"
    assert system.git_versions.read_file(run_id, received.git_version, "code/src/echo.py") == old_code
    changed = system.activate_once(run_id)
    spec_event = system.store.get_event(changed.product_spec.created_event_id)
    contract_event = system.store.get_event(changed.effective_contract.created_event_id)
    assert spec_event.payload["git_version"] == contract_event.payload["git_version"]
    assert spec_event.payload["git_version"]["parent_commit"] == received.git_version["commit"]
    patch = system.git_versions.diff(run_id, changed.git_version)
    assert "specs/product.json" in patch and "PRD.md" in patch and "Print the argument in uppercase" in patch
    old_spec = json.loads(system.git_versions.read_file(run_id, old_spec_event.payload["git_version"], "specs/product.json"))
    assert old_spec["revision"] == 1 and old_spec["change_record"] is None
    current = system.run_until_stop(run_id)
    assert current.phase == "DONE", current.error
    assert len(current.git_versions) == 9
    parent = None
    for entry in current.git_versions:
        assert entry["parent_commit"] == parent
        parent = entry["commit"]
    files = system.git_versions.read_files(run_id, current.git_version)
    assert set(files) == {
        "intend.md", "PRD.md", "PLAN.md", "specs/product.json", "specs/contract.json",
        "specs/plan.json", "specs/delivery.json", "specs/delivery-tree.json", "specs/qa.json", "code/src/echo.py",
    }
    for event_type, path in ((EventType.SPEC_ACCEPTED, "specs/product.json"),
                             (EventType.PLAN_ACCEPTED, "specs/plan.json"),
                             (EventType.DELIVERY_ACCEPTED, "specs/delivery.json"),
                             (EventType.QA_SUBMITTED, "specs/qa.json")):
        event = [item for item in _formal(system, run_id) if item.type == event_type][-1]
        assert json.loads(files[path]) == {key: value for key, value in event.payload.items() if key != "git_version"}
    assert current.canonical_state() == system.replay(run_id).canonical_state()


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


def test_sqlite_input_failure_leaves_only_candidate_and_next_parent_is_still_accepted(tmp_path, monkeypatch):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter())
    run_id = system.create_run("original")
    before = system.project(run_id)
    candidates = []
    prepare = system.git_versions.prepare

    def prepare_candidate(*args, **kwargs):
        revision = prepare(*args, **kwargs)
        candidates.append(revision)
        return revision

    monkeypatch.setattr(system.git_versions, "prepare", prepare_candidate)
    with monkeypatch.context() as failure:
        failure.setattr(system.store, "commit", _failing_append(system.store, EventType.USER_INPUT_RECEIVED))
        with pytest.raises(OSError):
            system.add_input(run_id, "rejected")
    assert system.project(run_id).canonical_state() == before.canonical_state()
    assert (tmp_path / "materials" / run_id / "intend.md").read_bytes() == b"original"
    assert system.git_versions.read_file(run_id, candidates[-1], "intend.md") == b"originalrejected"
    accepted = system.add_input(run_id, "accepted")
    assert accepted.git_version["parent_commit"] == before.git_version["commit"]
    assert candidates[0]["commit"] not in {item["commit"] for item in accepted.git_versions}


def test_spec_and_contract_sqlite_failure_rolls_back_entire_acceptance(tmp_path, monkeypatch):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec()]))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    received = system.add_input(run_id, "Print uppercase")
    # 新输入交给产品工作（与激活开始时流程编排写入的事件相同），产品规格的修订才能接纳
    system.orchestrator.writes.append(run_id, NewEvent(
        EventType.PRODUCT_INPUT_ASSIGNED, role="product", state_before=received.phase, state_after="PRODUCT_SPEC",
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
            _commit_spec(system, run_id, _revision())
    assert system.project(run_id).canonical_state() == before.canonical_state()
    assert (tmp_path / "materials" / run_id / "PRD.md").read_bytes() == original_prd
    assert b'"revision": 2' in system.git_versions.read_file(run_id, candidates[0], "specs/product.json")
    accepted = _commit_spec(system, run_id, _revision())
    current = system.project(run_id)
    assert accepted.payload["git_version"]["parent_commit"] == before.git_version["commit"]
    assert candidates[0]["commit"] not in {item["commit"] for item in current.git_versions}
    assert current.product_spec.revision == 2 and current.effective_contract.revision == 2


def test_git_delivery_and_archive_share_binary_bytes_and_complete_directory_manifest(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec(), plan_turn(), delivery_turn()]))
    run_id = system.create_run("build echo")
    workspace = system.workspace(run_id)
    (workspace.root / "empty").mkdir()
    (workspace.root / "data").mkdir()
    binary = b"\x00\xff\r\n\x1a"
    (workspace.root / "data" / "binary.dat").write_bytes(binary)
    (workspace.root / ".git").mkdir()
    (workspace.root / ".git" / "config").write_bytes(b"private git config")
    for _ in range(3):
        current = system.activate_once(run_id)
    assert current.delivery_spec is not None, current.error
    archived = load_tree(system.artifacts, run_id, current.delivery_spec.tree_ref)
    files = system.git_versions.read_files(run_id, current.git_version)
    assert json.loads(files["specs/delivery-tree.json"]) == archived.manifest
    assert archived.digest == current.delivery_spec.code_tree_digest
    assert {path.removeprefix("code/"): data for path, data in files.items() if path.startswith("code/")} == {
        item.path: item.data for item in archived.files
    }
    assert files["code/data/binary.dat"] == binary
    restored = materialize_tree(archived, tmp_path / "restored")
    assert (restored / "empty").is_dir() and (restored / "data" / "binary.dat").read_bytes() == binary
    assert capture_public_tree(restored) == archived
    assert not any(".git" in path or ".checks" in path for path in files)


@pytest.mark.parametrize("path", [".git/config", "src/.git/config", ".GIT/config", "src/.GiT/HEAD"])
def test_git_metadata_is_not_accessible_to_workspace_tools(tmp_path, path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter())
    run_id = system.create_run("build echo")
    with pytest.raises(TreeError):
        system.workspace(run_id).write_file(path, "must not write")


def test_nonformal_event_cannot_advance_git_version_projection(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter())
    run_id = system.create_run("build echo")
    before = system.project(run_id)
    system.orchestrator.writes.append(run_id, NewEvent(
        EventType.MODEL_MESSAGE, role="product", state_before=before.phase, state_after=before.phase,
        payload={"git_version": {"commit": "unaccepted"}}))
    after = system.project(run_id)
    assert after.git_version == before.git_version and after.git_versions == before.git_versions


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
            system.update_prompt(run_id, "product", "The run is already cancelled")
        assert system.test_adapter.cancelled == {system.test_adapter.invocations[0].attempt_id}
        current = system.project(run_id)
        assert current.git_version == before.git_version and current.input_version == before.input_version
        assert not [event for event in _formal(system, run_id) if event.type == EventType.USER_INPUT_RECEIVED]
        if failure != "cancellation_event":
            assert current.phase == "FAILED" and current.stop_reason == "cancelled"
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
        system.update_prompt(run_id, "product", "Do not resume stopped work")


@pytest.mark.parametrize("git_fails", [False, True])
def test_cancel_notifies_model_before_waiting_for_git_storage(tmp_path, monkeypatch, git_fails):
    model_entered, model_release = threading.Event(), threading.Event()
    git_entered, git_release = threading.Event(), threading.Event()
    activation_errors, cancel_results = [], []

    class LateResponseAdapter(FakeAdapter):
        async def stream(self, call):
            items = [item async for item in super().stream(call)]
            model_entered.set()
            assert model_release.wait(10)
            for item in items:
                yield item

    system = LoopSystem.for_testing(tmp_path, LateResponseAdapter([product_spec()]))
    run_id = system.create_run("original")
    prepare = system.git_versions.prepare

    def blocked_git(*args, **kwargs):
        git_entered.set()
        assert git_release.wait(10)
        if git_fails:
            raise GitVersionError("Git could not save the input")
        return prepare(*args, **kwargs)

    def activate():
        try:
            system.activate_once(run_id)
        except Exception as exc:
            activation_errors.append(exc)

    def cancel():
        try:
            cancel_results.append(system.add_input(run_id, " /cancel\r\n"))
        except Exception as exc:
            cancel_results.append(exc)

    worker = threading.Thread(target=activate)
    cancelling = threading.Thread(target=cancel)
    worker.start()
    try:
        assert model_entered.wait(10)
        monkeypatch.setattr(system.git_versions, "prepare", blocked_git)
        cancelling.start()
        assert git_entered.wait(10)
        # 保存命令版本的 Git 操作还在等待时，进行中的调用尝试已经收到取消
        request = system.test_adapter.invocations[0]
        assert request.attempt_id in system.test_adapter.cancelled
        assert cancelling.is_alive()
        assert not [event for event in _formal(system, run_id) if event.type == EventType.USER_INPUT_RECEIVED]
        model_release.set()
    finally:
        git_release.set()
        model_release.set()
        if cancelling.ident is not None:
            cancelling.join(10)
        worker.join(10)
    assert not worker.is_alive() and not cancelling.is_alive() and not activation_errors
    assert len(cancel_results) == 1
    assert isinstance(cancel_results[0], CancelledInputSaveError) == git_fails
    current = system.project(run_id)
    assert current.phase == "FAILED" and current.stop_reason == "cancelled"
    assert current.product_spec is None and len(system.test_adapter.invocations) == 1
    assert current.input_version == (1 if git_fails else 2)
