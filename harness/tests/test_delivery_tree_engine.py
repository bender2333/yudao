from dataclasses import asdict

from harness.providers.call import ModelResponse
from harness.adapters.fake import FakeAdapter
from harness.models import EventType, json_dumps
from harness.proposals import delivery_turn, product_spec
from harness.public_tree import capture_public_tree, materialize_tree
from harness.runtime import LoopSystem
from harness.tree_archive import load_tree

def _call(identity, name, **arguments):
    return {"id": identity, "call_id": identity, "type": "function_call", "name": name,
            "arguments": json_dumps(arguments)}

def _engineering(tmp_path, actions):
    script = [product_spec()]
    script.extend([ModelResponse(output=actions), delivery_turn()])
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(script))
    run_id = system.create_run("Refactor the echo implementation")
    system.activate_once(run_id)
    workspace = system.workspace(run_id)
    workspace.write_file("src/old.py", "old source")
    workspace.write_file("src/keep.py", "preserved source")
    workspace.write_file("other/outside.py", "outside source")
    return system, run_id, workspace

def test_accepted_delivery_restores_complete_tree_without_the_original_workspace(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec(), delivery_turn()]))
    run_id = system.create_run("echo")
    workspace = system.workspace(run_id)
    (workspace.root / "assets").mkdir()
    (workspace.root / "assets" / "binary.dat").write_bytes(b"\x00\xff\x80binary\r\n")
    (workspace.root / ".project-config").write_bytes(b"hidden=true\r\n")
    (workspace.root / "empty" / "nested").mkdir(parents=True)
    for _ in range(2):
        result = system.activate_once(run_id)
    assert result.phase == "QUALITY", result.error
    delivery = result.delivery_spec
    # 清单由主机从封存的交付快照得出：公开树的全部文件，按路径排序（工单 #677）
    assert delivery.files == [".project-config", "assets/binary.dat", "src/echo.py"]
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

def test_tree_archive_failure_has_a_persisted_host_error_and_no_accepted_delivery(tmp_path, monkeypatch):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec(), delivery_turn()]))
    run_id = system.create_run("echo")
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

def test_delete_and_move_share_the_current_contract_and_record_their_actual_actions(tmp_path):
    actions = [_call("delete", "delete_file", path="src/old.py", reason="Remove the superseded implementation"),
               _call("move", "move_file", source="src/keep.py", destination="src/new.py", reason="Use the current module name")]
    system, run_id, workspace = _engineering(tmp_path, actions)
    before = system.project(run_id)
    result = system.activate_once(run_id)
    assert result.phase == "QUALITY", result.error
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

def test_delete_and_move_record_their_actual_actions(tmp_path):
    actions = [_call("no-plan-delete", "delete_file", path="src/old.py", reason="Remove old source"),
               _call("no-plan-move", "move_file", source="src/keep.py", destination="src/new.py", reason="Move source")]
    system, run_id, workspace = _engineering(tmp_path, actions)
    system.activate_once(run_id)
    assert not (workspace.root / "src" / "old.py").exists()
    assert not (workspace.root / "src" / "keep.py").exists()
    assert workspace.read_file("src/new.py") == "preserved source"

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

def test_leading_space_paths_stay_literal_paths(tmp_path):
    actions = [_call("spaced-delete", "delete_file", path=" src/old.py", reason="Delete the named legacy file"),
               _call("spaced-move", "move_file", source=" src/keep.py", destination=" src/new.py", reason="Move the named source")]
    system, run_id, workspace = _engineering(tmp_path, actions)
    workspace.write_file(" src/old.py", "spaced old source")
    workspace.write_file(" src/keep.py", "spaced preserved source")
    result = system.activate_once(run_id)
    assert result.phase == "QUALITY", result.error
    assert workspace.read_file("src/old.py") == "old source"
    assert workspace.read_file("src/keep.py") == "preserved source"
    assert not (workspace.root / " src" / "old.py").exists()
    assert not (workspace.root / " src" / "keep.py").exists()
    assert workspace.read_file(" src/new.py") == "spaced preserved source"
