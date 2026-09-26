from dataclasses import asdict

import pytest

import harness.orchestrator as orchestration
import harness.submissions as submissions
from harness.providers.call import ModelResponse
from harness.adapters.fake import FakeAdapter
from harness.models import EventType, json_dumps
from harness.proposals import collaboration_request, delivery_turn, plan_turn, product_spec, review_turn
from harness.public_tree import capture_public_tree, materialize_tree
from harness.runtime import LoopSystem
from harness.tree_archive import load_tree


def _call(identity, name, **arguments):
    return {"id": identity, "call_id": identity, "type": "function_call", "name": name,
            "arguments": json_dumps(arguments)}


def _engineering(tmp_path, actions, *, planned=True, scope=None):
    script = [product_spec()]
    if planned:
        script.append(plan_turn(scope=scope or ["src/"]))
    script.extend([ModelResponse(output=actions), collaboration_request()])
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(script))
    run_id = system.create_run("Refactor the echo implementation")
    system.activate_once(run_id)
    if planned:
        system.activate_once(run_id)
    workspace = system.workspace(run_id)
    workspace.write_file("src/old.py", "old source")
    workspace.write_file("src/keep.py", "preserved source")
    workspace.write_file("other/outside.py", "outside plan")
    return system, run_id, workspace


def test_accepted_delivery_restores_complete_tree_without_the_original_workspace(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec(), plan_turn(), delivery_turn()]))
    run_id = system.create_run("echo")
    workspace = system.workspace(run_id)
    (workspace.root / "assets").mkdir()
    (workspace.root / "assets" / "binary.dat").write_bytes(b"\x00\xff\x80binary\r\n")
    (workspace.root / ".project-config").write_bytes(b"hidden=true\r\n")
    (workspace.root / "empty" / "nested").mkdir(parents=True)
    for _ in range(3):
        result = system.activate_once(run_id)
    assert result.phase == "QUALITY", result.error
    delivery = result.delivery_spec
    assert delivery.files == ["src/echo.py"]
    event = system.store.get_event(delivery.created_event_id)
    assert event.payload["tree_ref"] == asdict(delivery.tree_ref)
    assert "file_refs" not in event.payload and "snapshot_ref" not in event.payload
    workspace.root.rename(tmp_path / "unavailable-original-workspace")
    tree = load_tree(system.artifacts, run_id, delivery.tree_ref)
    restored = materialize_tree(tree, tmp_path / "restored")
    assert (restored / "assets" / "binary.dat").read_bytes() == b"\x00\xff\x80binary\r\n"
    assert (restored / ".project-config").read_bytes() == b"hidden=true\r\n"
    assert (restored / "empty" / "nested").is_dir()
    assert not (restored / ".checks").exists()
    assert capture_public_tree(restored).digest == delivery.code_tree_digest
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_tree_changed_after_validation_cannot_be_accepted_or_rebound(tmp_path, monkeypatch):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec(), plan_turn(), delivery_turn()]))
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    evaluate = orchestration.evaluate_proposal
    store_tree = submissions.store_tree
    captured = []
    archived = []

    def mutate_after_validation(**arguments):
        decision = evaluate(**arguments)
        assert decision.accepted
        captured.append(arguments["snapshot"])
        system.workspace(run_id).write_file("src/echo.py", "changed after validation")
        return decision

    def archive_validated_tree(store, run, tree):
        assert tree is captured[0].tree
        ref = store_tree(store, run, tree)
        archived.append(ref)
        return ref

    monkeypatch.setattr(orchestration, "evaluate_proposal", mutate_after_validation)
    monkeypatch.setattr(submissions, "store_tree", archive_validated_tree)
    result = system.activate_once(run_id)
    assert result.phase == "ENGINEERING", result.error
    assert result.stop_reason is None
    assert result.delivery_spec is None
    assert len(captured) == 1
    assert len(archived) == 0
    events = system.store.list_events(run_id)
    assert not any(event.type == EventType.DELIVERY_ACCEPTED for event in events)
    assert not any(event.type == EventType.RUN_FAILED for event in events)
    rejected = [event for event in events if event.type == EventType.PROPOSAL_REJECTED]
    assert rejected
    assert any(item.get("field") == "execution_basis" for item in rejected[-1].payload["errors"])
    receipt = system.workspace(run_id).snapshot().checks[-1]
    assert receipt.snapshot_hash == captured[0].digest
    assert receipt.snapshot_hash != system.workspace(run_id).digest()
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_tree_changed_after_quality_validation_cannot_release_old_results(tmp_path, monkeypatch):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        product_spec(), plan_turn(), delivery_turn(), review_turn("release", "Verified the complete tree"),
    ]))
    run_id = system.create_run("echo")
    for _ in range(3):
        current = system.activate_once(run_id)
    accepted_tree_digest = current.delivery_spec.code_tree_digest
    evaluate = orchestration.evaluate_proposal

    def mutate_after_quality_validation(**arguments):
        decision = evaluate(**arguments)
        assert arguments["department"] == "quality" and decision.accepted
        assert arguments["snapshot"].digest == accepted_tree_digest
        system.workspace(run_id).write_file("src/unreviewed.py", "not part of the reviewed tree")
        return decision

    monkeypatch.setattr(orchestration, "evaluate_proposal", mutate_after_quality_validation)
    result = system.activate_once(run_id)
    assert result.phase == "QUALITY", result.error
    assert result.stop_reason is None
    assert result.last_review is None
    assert result.delivery_spec.code_tree_digest == accepted_tree_digest
    events = system.store.list_events(run_id)
    assert not any(event.type in {EventType.QA_SUBMITTED, EventType.RUN_DONE} for event in events)
    assert not any(event.type == EventType.RUN_FAILED for event in events)
    rejected = [event for event in events if event.type == EventType.PROPOSAL_REJECTED]
    assert rejected
    assert any(item.get("field") == "execution_basis" for item in rejected[-1].payload["errors"])
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_tree_archive_failure_has_a_persisted_host_error_and_no_accepted_delivery(tmp_path, monkeypatch):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec(), plan_turn(), delivery_turn()]))
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    put = system.artifacts.put

    def fail_tree(run, kind, *args, **kwargs):
        if kind == "tree_file":
            raise OSError("archive storage unavailable")
        return put(run, kind, *args, **kwargs)

    monkeypatch.setattr(system.artifacts, "put", fail_tree)
    result = system.activate_once(run_id)
    assert result.phase == "FAILED" and result.stop_reason == "host_commit_error"
    assert "archive storage unavailable" in result.error
    assert result.delivery_spec is None
    assert not any(event.type == EventType.DELIVERY_ACCEPTED for event in system.store.list_events(run_id))
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_delete_and_move_share_the_current_plan_and_record_their_actual_actions(tmp_path):
    actions = [_call("delete", "delete_file", path="src/old.py", reason="Remove the superseded implementation"),
               _call("move", "move_file", source="src/keep.py", destination="src/new.py", reason="Use the planned module name")]
    system, run_id, workspace = _engineering(tmp_path, actions)
    before = system.project(run_id)
    result = system.activate_once(run_id)
    assert result.phase == "ENGINEERING" and result.pending_request, result.error
    assert not (workspace.root / "src" / "old.py").exists()
    assert not (workspace.root / "src" / "keep.py").exists()
    assert workspace.read_file("src/new.py") == "preserved source"
    events = system.store.list_events(run_id)
    for identity in ("delete", "move"):
        started = next(event for event in events if event.type == EventType.TOOL_STARTED and event.payload["id"] == identity)
        completed = next(event for event in events if event.type == EventType.TOOL_CALLED and event.payload.get("id") == identity)
        assert completed.payload["ok"]
        assert started.payload["args"]["reason"]
        assert started.payload["effective_contract_hash"] == before.effective_contract.content_hash
        assert started.payload["engineering_plan_hash"] == before.engineering_plan.content_hash


@pytest.mark.parametrize("planned,actions", [
    (False, [_call("no-plan-delete", "delete_file", path="src/old.py", reason="Remove old source"),
             _call("no-plan-move", "move_file", source="src/keep.py", destination="src/new.py", reason="Move source")]),
    (True, [_call("outside-delete", "delete_file", path="other/outside.py", reason="Remove outside source"),
            _call("outside-source", "move_file", source="other/outside.py", destination="src/from-outside.py", reason="Move source"),
            _call("outside-destination", "move_file", source="src/keep.py", destination="other/from-inside.py", reason="Move source")]),
])
def test_delete_and_both_move_endpoints_require_current_plan_scope(tmp_path, planned, actions):
    system, run_id, workspace = _engineering(tmp_path, actions, planned=planned)
    before = workspace.snapshot().tree
    system.activate_once(run_id)
    assert workspace.snapshot().tree == before
    events = system.store.list_events(run_id)
    for action in actions:
        completed = next(event for event in events if event.type == EventType.TOOL_CALLED and event.payload.get("id") == action["id"])
        assert not completed.payload["ok"]
        assert "plan" in completed.payload["error"]
        assert not any(event.type == EventType.TOOL_STARTED and event.payload["id"] == action["id"] for event in events)


def test_product_cannot_start_delete_or_move_actions(tmp_path):
    actions = [_call("product-delete", "delete_file", path="src/old.py", reason="Delete"),
               _call("product-move", "move_file", source="src/keep.py", destination="src/new.py", reason="Move")]
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([ModelResponse(output=actions), product_spec()]))
    run_id = system.create_run("echo")
    workspace = system.workspace(run_id)
    workspace.write_file("src/old.py", "old source")
    workspace.write_file("src/keep.py", "preserved source")
    before = workspace.snapshot().tree
    result = system.activate_once(run_id)
    assert result.phase == "ENGINEERING", result.error
    assert workspace.snapshot().tree == before
    events = system.store.list_events(run_id)
    for action in actions:
        completed = next(event for event in events if event.type == EventType.TOOL_CALLED and event.payload.get("id") == action["id"])
        assert not completed.payload["ok"]
        assert "product cannot use" in completed.payload["error"]
        assert not any(event.type == EventType.TOOL_STARTED and event.payload["id"] == action["id"] for event in events)


@pytest.mark.parametrize("scope,allowed", [([" src/"], True), (["src/"], False)])
def test_leading_space_paths_use_their_exact_planned_directory(tmp_path, scope, allowed):
    actions = [_call("spaced-delete", "delete_file", path=" src/old.py", reason="Delete the named legacy file"),
               _call("spaced-move", "move_file", source=" src/keep.py", destination=" src/new.py", reason="Move the named source")]
    system, run_id, workspace = _engineering(tmp_path, actions, scope=scope)
    workspace.write_file(" src/old.py", "spaced old source")
    workspace.write_file(" src/keep.py", "spaced preserved source")
    result = system.activate_once(run_id)
    assert result.phase == "ENGINEERING" and result.pending_request, result.error
    assert result.engineering_plan.scope == scope
    assert workspace.read_file("src/old.py") == "old source"
    assert workspace.read_file("src/keep.py") == "preserved source"
    if allowed:
        assert not (workspace.root / " src" / "old.py").exists()
        assert not (workspace.root / " src" / "keep.py").exists()
        assert workspace.read_file(" src/new.py") == "spaced preserved source"
    else:
        assert workspace.read_file(" src/old.py") == "spaced old source"
        assert workspace.read_file(" src/keep.py") == "spaced preserved source"
        assert not (workspace.root / " src" / "new.py").exists()
    events = system.store.list_events(run_id)
    for action in actions:
        completed = next(event for event in events if event.type == EventType.TOOL_CALLED and event.payload.get("id") == action["id"])
        assert completed.payload["ok"] is allowed
        started = [event for event in events if event.type == EventType.TOOL_STARTED and event.payload["id"] == action["id"]]
        assert bool(started) is allowed
