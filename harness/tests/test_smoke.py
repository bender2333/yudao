import copy
import json
from dataclasses import asdict, replace

import pytest

from harness.adapters.responses import ResponsesConfig
from harness.adapters.fake import FakeTurn
from harness.artifacts import ArtifactStore
from harness.event_store import EventStore
from harness.models import ArtifactRef, EventType, canonical_hash, json_dumps
from harness.proposals import product_spec, delivery, review, collaboration_request, response_turn, delivery_turn, plan_turn, review_turn
from harness.smoke import isolation_fields, run_smoke, smoke_exit_code, summarize_run, _markdown, _receipt_evidence, _archive_evidence, _collaboration_evidence
from harness.tests.helpers import run_scripted


def test_smoke_requires_current_input_audit_and_host_receipts():
    base = {
        "phase": "DONE",
        "stop_reason": "released",
        "replay_consistent": True,
        "context_isolated": True,
        "model_input_audit": {"status": "verified"},
        "check_receipts": [{"name": "smoke", "exit_code": 0}],
        "check_receipts_verified": True,
        "delivery_archive": {"status": "verified"},
        "fake_used": False,
        "request_count": 2,
        "collaboration_audit": {"status": "verified", "pre_spec_consultation": True, "requirements_action": True},
    }
    assert smoke_exit_code({"available": True, "scenarios": {"happy": base, "collaboration": base}}) == 0
    assert smoke_exit_code({"available": False, "scenarios": {}}) == 2
    assert smoke_exit_code({"available": True, "scenarios": {"happy": dict(base, fake_used=True)}}) == 2
    for change in (
        {"check_receipts": []}, {"check_receipts_verified": False}, {"context_isolated": False},
        {"model_input_audit": None}, {"model_input_audit": {"status": "unverified"}},
        {"delivery_archive": None}, {"delivery_archive": {"status": "unverified"}},
    ):
        assert smoke_exit_code({"available": True, "scenarios": {"happy": dict(base, **change)}}) == 1
    assert smoke_exit_code({"available": True, "scenarios": {"collaboration": dict(base, request_count=0)}}) == 1
    for audit in (None, {"status": "unverified"}, {"status": "verified", "pre_spec_consultation": True},
                  {"status": "verified", "requirements_action": True}):
        assert smoke_exit_code({"available": True, "scenarios": {
            "collaboration": dict(base, collaboration_audit=audit),
        }}) == 1


@pytest.fixture
def native_run(data_dir):
    script = [
        product_spec(),
        plan_turn(),
        FakeTurn(writes={"src/echo.py": "import sys\nprint(sys.argv[1])\n"}),
        FakeTurn(checks={"smoke": 0}),
        delivery(),
        FakeTurn(checks={"smoke": 0}),
        review("release", "host checks passed"),
    ]
    system, projection = run_scripted(data_dir, script)
    assert projection.phase == "DONE"
    return system, projection.run_id


def test_native_audit_checks_every_step_and_actual_host_receipts(native_run):
    system, run_id = native_run
    summary = summarize_run(system, run_id, scenario="happy")
    assert summary["context_isolated"] is True, summary["context_isolation_notes"]
    assert summary["model_input_audit"]["status"] == "verified"
    assert summary["model_input_audit"]["request_count"] > 3
    assert summary["model_input_audit"]["activation_count"] == 4
    assert summary["check_receipts_verified"] is True, summary["check_receipt_notes"]
    assert summary["delivery_archive"]["status"] == "verified", summary["delivery_archive"]
    assert summary["delivery_archive"]["tree_digest"] == system.project(run_id).delivery_spec.code_tree_digest
    assert summary["replay_consistent"] is True
    assert summary["fake_used"] is True
    assert smoke_exit_code({"available": True, "scenarios": {"happy": summary}}) == 2


@pytest.mark.parametrize("changed", ["effective_contract", "engineering_plan"])
def test_receipt_audit_rejects_new_contract_or_plan_even_with_unchanged_spec_and_tree(native_run, monkeypatch, changed):
    system, run_id = native_run
    projection = system.project(run_id)
    receipts = [asdict(item) for item in system.workspace(run_id).receipts()]
    changed_item = replace(getattr(projection, changed), content_hash=canonical_hash("new accepted content"))
    changed_projection = replace(projection, **{changed: changed_item})
    monkeypatch.setattr(system, "project", lambda _run_id: changed_projection)
    valid, notes = _receipt_evidence(system, run_id, receipts)
    assert valid is False
    assert "engineering: no successful host check bound to the final contract and snapshot" in notes
    assert "quality: no successful host check bound to the final contract and snapshot" in notes


def test_archive_audit_restores_from_persisted_bytes_after_workspace_changes(native_run, monkeypatch):
    system, run_id = native_run
    system.workspace(run_id).write_file("src/echo.py", "changed after delivery\n")

    def no_workspace(_run_id):
        raise AssertionError("archive audit must not read the current workspace")

    monkeypatch.setattr(system, "workspace", no_workspace)
    result = _archive_evidence(system, run_id)
    assert result["status"] == "verified", result
    assert result["files"] == 1


@pytest.mark.parametrize("damage", ["missing", "modified"])
def test_archive_audit_rejects_missing_or_modified_persisted_bytes(native_run, damage):
    system, run_id = native_run
    delivery = system.project(run_id).delivery_spec
    archive = json.loads(system.artifacts.get_for_run(run_id, delivery.tree_ref))
    blob = system.artifacts.root / archive["blobs"][0]["artifact"]["path"]
    if damage == "missing":
        blob.unlink()
    else:
        blob.write_bytes(b"changed artifact bytes")
    result = _archive_evidence(system, run_id)
    assert result["status"] == "unverified"
    assert result["notes"]


def test_archive_audit_rejects_unrelated_delivery_digest(native_run, monkeypatch):
    system, run_id = native_run
    projection = system.project(run_id)
    delivery = replace(projection.delivery_spec, code_tree_digest=canonical_hash("unrelated tree"))
    monkeypatch.setattr(system, "project", lambda _run_id: replace(projection, delivery_spec=delivery))
    assert _archive_evidence(system, run_id)["status"] == "unverified"


@pytest.fixture
def collaboration_run(data_dir):
    from harness.demo import run_demo

    return run_demo(data_dir)


def test_collaboration_audit_requires_actual_consultation_and_accepted_action_results(collaboration_run):
    system, run_id = collaboration_run
    audit = _collaboration_evidence(system, run_id)
    assert audit["status"] == "verified", audit
    assert audit["pre_spec_consultation"] is True
    assert audit["requirements_action"] is True
    assert audit["directions"] == ["product->engineering", "engineering->product", "quality->engineering"]


def test_model_input_audit_tracks_new_input_and_prompt_versions(collaboration_run):
    system, run_id = collaboration_run
    summary = summarize_run(system, run_id, scenario="collaboration")
    assert summary["model_input_audit"]["status"] == "verified", summary["model_input_audit"]
    assert summary["check_receipts_verified"] is True
    assert summary["delivery_archive"]["status"] == "verified"
    assert {request.input_version for request in system.adapter.invocations} == {1, 2}
    assert {request.prompt_version for request in system.adapter.invocations if request.department == "product"} == {1, 2}


@pytest.mark.parametrize("field", ["input_version", "prompt_version", "prompt_hash"])
@pytest.mark.parametrize("event_type", [EventType.DEPARTMENT_ACTIVATED, EventType.CONTEXT_ASSEMBLED,
                                      EventType.MODEL_MESSAGE, EventType.TOOL_CALLED])
def test_model_input_audit_rejects_forged_adopted_versions(native_run, monkeypatch, field, event_type):
    system, run_id = native_run
    events = _events_for_mutation(system, run_id, monkeypatch)
    event = next(item for item in events if item.type == event_type and item.payload.get("activation_id"))
    event.payload[field] = "forged-prompt" if field == "prompt_hash" else 999
    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]
    assert audit["status"] == "unverified", audit
    assert any(field in note for note in audit["notes"])


@pytest.mark.parametrize("field", ["text", "byte_start", "byte_end"])
def test_model_input_audit_rejects_changed_received_original(collaboration_run, monkeypatch, field):
    system, run_id = collaboration_run
    events = _events_for_mutation(system, run_id, monkeypatch)
    event = next(item for item in events if item.type == EventType.USER_INPUT_RECEIVED)
    event.payload[field] = "rewritten original" if field == "text" else 999
    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]
    assert audit["status"] == "unverified", audit
    assert any("input bytes or range" in note for note in audit["notes"])


def test_model_input_audit_uses_activation_prompt_after_inflight_edit(tmp_path):
    from harness.adapters.base import ModelResponse
    from harness.adapters.fake import FakeAdapter
    from harness.runtime import LoopSystem

    def update(request):
        system.update_prompt(request.run_id, "engineering", "  NEW_ENGINEERING_PROMPT\r\n")
        return ModelResponse(output=[{
            "id": "inspect", "call_id": "inspect", "type": "function_call", "name": "list_files",
            "arguments": "{}",
        }])

    system = LoopSystem(tmp_path, FakeAdapter([product_spec(), update, plan_turn(), collaboration_request()]))
    run_id = system.create_run("echo")
    for _ in range(3):
        system.activate_once(run_id)
    first, second, third = system.adapter.invocations[1:]
    assert first.activation_id == second.activation_id and first.prompt_version == second.prompt_version == 1
    assert third.activation_id != first.activation_id and third.prompt_version == 2
    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]
    assert audit["status"] == "verified", audit


def test_collaboration_audit_rejects_results_from_another_request(collaboration_run, monkeypatch):
    system, run_id = collaboration_run
    projection = system.project(run_id)
    result_id = projection.responses[1].result_event_ids[0]
    events = copy.deepcopy(system.store.list_events(run_id))
    next(event for event in events if event.event_id == result_id).payload["request_id"] = "unrelated-request"
    monkeypatch.setattr(system, "project", lambda _run_id: projection)
    monkeypatch.setattr(system.store, "list_events", lambda *_args, **_kwargs: events)
    audit = _collaboration_evidence(system, run_id)
    assert audit["status"] == "unverified"
    assert audit["requirements_action"] is False
    assert any("result is not bound" in note for note in audit["notes"])


@pytest.mark.parametrize("event_type", [EventType.DEPARTMENT_ACTIVATED, EventType.CONTEXT_ASSEMBLED])
@pytest.mark.parametrize("field", ["request_id", "effective_contract_hash", "engineering_plan_hash", "all"])
def test_model_input_audit_rejects_changed_work_basis(collaboration_run, monkeypatch, event_type, field):
    system, run_id = collaboration_run
    events = _events_for_mutation(system, run_id, monkeypatch)
    event = next(item for item in events if item.type == event_type and item.payload.get("request_id"))
    fields = ["request_id", "effective_contract_hash", "engineering_plan_hash"] if field == "all" else [field]
    for name in fields:
        event.payload[name] = "wrong-" + name
    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]
    assert audit["status"] == "unverified"
    assert any(any(name in note for name in fields) for note in audit["notes"])


def test_model_input_audit_rejects_private_material_in_rehashed_pinned_text(collaboration_run, monkeypatch):
    system, run_id = collaboration_run
    events = _events_for_mutation(system, run_id, monkeypatch)
    event = [item for item in events if item.type == EventType.CONTEXT_ASSEMBLED and item.role == "quality"][-1]
    request = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**event.payload["request_ref"])))
    request["input"][0]["content"] += "\n\n[private_engineering_transcript]\nUNRELATED_PRIVATE_HISTORY_CANARY"
    ref = system.artifacts.put(run_id, "model_request", json_dumps(request), media_type="application/json")
    event.payload["request_ref"] = asdict(ref)
    event.payload["digest"] = event.context_digest = canonical_hash(request)
    event.artifact_hashes = [ref.content_hash]
    attempted = next(item for item in events if item.type == EventType.MODEL_REQUESTED
                     and item.payload["activation_id"] == event.payload["activation_id"]
                     and item.payload["step_id"] == event.payload["step_id"])
    attempted.context_digest = event.context_digest
    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]
    assert audit["status"] == "unverified"
    assert any("pinned developer input differs" in note for note in audit["notes"])


def test_model_input_audit_rejects_forged_injected_source_metadata(native_run, monkeypatch):
    system, run_id = native_run
    events = _events_for_mutation(system, run_id, monkeypatch)
    event = next(item for item in events if item.type == EventType.CONTEXT_ASSEMBLED)
    event.payload["injected"][0]["digest"] = canonical_hash("different source")
    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]
    assert audit["status"] == "unverified"
    assert any("injected source metadata" in note for note in audit["notes"])


def test_model_input_audit_rebuilds_summary_scope_after_contract_changes(tmp_path):
    from harness.tests.test_compaction_engine import _runner

    system, adapter, run_id, _ = _runner(tmp_path)
    first = system.activate_once(run_id)
    assert first.compactions[-1]["effective_contract_hash"] is None
    system.activate_once(run_id)
    final = system.activate_once(run_id)
    later = [item for item in final.compactions if item["effective_contract_hash"] is not None]
    assert later and later[0]["previous_compaction_event_id"] is None
    assert adapter.invocations[-1].purpose == "work"
    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]
    assert audit["status"] == "verified", audit["notes"]


def test_failed_run_without_requests_has_no_context_evidence(tmp_path):
    store = EventStore(tmp_path / "events.sqlite")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    fields = isolation_fields(store, artifacts, "run")
    assert fields["manifest_boundary"] is False
    assert fields["model_input_audit"]["status"] == "unverified"
    assert fields["context_isolated"] is False


def _events_for_mutation(system, run_id, monkeypatch):
    events = copy.deepcopy(system.store.list_events(run_id))
    monkeypatch.setattr(system.store, "list_events", lambda *_args, **_kwargs: events)
    return events


@pytest.mark.parametrize("field,value", [
    ("request_ref", None), ("activation_id", "foreign-activation"),
    ("session_id", "foreign-session"), ("department", "quality"),
    ("step_id", 100), ("digest", "sha256:wrong"),
])
def test_unbound_or_missing_request_cannot_certify_run(native_run, monkeypatch, field, value):
    system, run_id = native_run
    events = _events_for_mutation(system, run_id, monkeypatch)
    event = next(item for item in events if item.type == EventType.CONTEXT_ASSEMBLED)
    event.payload[field] = value
    fields = isolation_fields(system.store, system.artifacts, run_id)
    assert fields["context_isolated"] is False
    assert fields["model_input_audit"]["status"] == "unverified"


@pytest.mark.parametrize("mutation,expected", [
    ("foreign_history", "department's recorded outputs"), ("extra_tool", "actual tool schemas"),
    ("hidden_instructions", "unexpected model input fields"), ("changed_intend", "verbatim task"),
])
def test_actual_inputs_are_checked_even_when_artifact_hash_is_valid(native_run, monkeypatch, mutation, expected):
    system, run_id = native_run
    events = _events_for_mutation(system, run_id, monkeypatch)
    event = next(item for item in events if item.type == EventType.CONTEXT_ASSEMBLED)
    request = json.loads(system.artifacts.get_text(event.payload["request_ref"]["content_hash"]))
    if mutation == "foreign_history":
        request["input"].append({"role": "assistant", "content": "other department private history"})
    elif mutation == "extra_tool":
        request["tools"].append({"type": "function", "name": "write_file", "parameters": {}})
    elif mutation == "hidden_instructions":
        request["instructions"] = "untracked instructions"
    else:
        request["input"][0]["content"] = "Changed original task\n" + request["input"][0]["content"]
    ref = system.artifacts.put(run_id, "model_request", json_dumps(request), media_type="application/json")
    event.payload["request_ref"] = asdict(ref)
    event.payload["digest"] = canonical_hash(request)
    event.context_digest = canonical_hash(request)
    event.artifact_hashes = [ref.content_hash]
    attempted = next(item for item in events if item.type == EventType.MODEL_REQUESTED)
    attempted.context_digest = canonical_hash(request)
    fields = isolation_fields(system.store, system.artifacts, run_id)
    assert fields["context_isolated"] is False
    assert any(expected in note for note in fields["model_input_audit"]["notes"])


def test_tool_history_must_match_recorded_result(native_run, monkeypatch):
    system, run_id = native_run
    events = _events_for_mutation(system, run_id, monkeypatch)
    event = next(item for item in events if item.type == EventType.TOOL_CALLED and item.payload.get("input_item"))
    event.payload["input_item"]["output"] = json_dumps({"ok": True, "output": "unrecorded", "error": None})
    fields = isolation_fields(system.store, system.artifacts, run_id)
    assert fields["context_isolated"] is False
    assert any("recorded result" in note for note in fields["model_input_audit"]["notes"])


def test_consistently_relabelled_steps_must_still_match_activation_event(native_run, monkeypatch):
    system, run_id = native_run
    events = _events_for_mutation(system, run_id, monkeypatch)
    activated = next(event for event in events if event.type == EventType.DEPARTMENT_ACTIVATED)
    identity = activated.payload["activation_id"]
    for event in events:
        if event.type != EventType.DEPARTMENT_ACTIVATED and event.payload.get("activation_id") == identity:
            event.payload["activation_id"] = "unrelated-activation"
    fields = isolation_fields(system.store, system.artifacts, run_id)
    assert fields["context_isolated"] is False
    assert any("department activation" in note for note in fields["model_input_audit"]["notes"])


def test_audit_does_not_replace_missing_run_artifact_with_another_runs_copy(native_run):
    system, run_id = native_run
    event = next(item for item in system.store.list_events(run_id) if item.type == EventType.CONTEXT_ASSEMBLED)
    original = system.artifacts.root / event.payload["request_ref"]["path"]
    system.artifacts.put("another-run", "model_request", original.read_bytes(), media_type="application/json")
    original.unlink()
    fields = isolation_fields(system.store, system.artifacts, run_id)
    assert fields["context_isolated"] is False
    assert fields["model_input_audit"]["status"] == "unverified"


def test_audit_preserves_department_history_when_request_returns_to_product(data_dir):
    system, projection = run_scripted(data_dir, [
        product_spec(), collaboration_request(), response_turn("answered", "The existing requirements do not distinguish flags."),
        plan_turn(), delivery_turn(), review_turn("release", "host checks passed"),
    ])
    assert projection.phase == "DONE"
    fields = isolation_fields(system.store, system.artifacts, projection.run_id)
    assert fields["context_isolated"] is True, fields["model_input_audit"]["notes"]
    assert fields["model_input_audit"]["activation_count"] == 6


def test_audit_rejects_missing_new_work_message_after_product_reactivation(data_dir, monkeypatch):
    system, projection = run_scripted(data_dir, [
        product_spec(), collaboration_request(), response_turn("answered", "The existing requirements do not distinguish flags."),
        plan_turn(), delivery_turn(), review_turn("release", "host checks passed"),
    ])
    events = _events_for_mutation(system, projection.run_id, monkeypatch)
    assembled = [event for event in events if event.type == EventType.CONTEXT_ASSEMBLED and event.role == "product"][1]
    request = json.loads(system.artifacts.get_text(assembled.payload["request_ref"]["content_hash"]))
    assert request["input"][-1]["role"] == "user"
    request["input"].pop()
    ref = system.artifacts.put(projection.run_id, "model_request", json_dumps(request), media_type="application/json")
    assembled.payload["request_ref"] = asdict(ref)
    assembled.payload["digest"] = canonical_hash(request)
    assembled.context_digest = canonical_hash(request)
    assembled.artifact_hashes = [ref.content_hash]
    attempted = next(event for event in events if event.type == EventType.MODEL_REQUESTED
                     and event.payload["activation_id"] == assembled.payload["activation_id"]
                     and event.payload["step_id"] == assembled.payload["step_id"])
    attempted.context_digest = canonical_hash(request)
    fields = isolation_fields(system.store, system.artifacts, projection.run_id)
    assert fields["context_isolated"] is False
    assert any("department's recorded outputs" in note for note in fields["model_input_audit"]["notes"])


@pytest.fixture
def compacted_run(tmp_path):
    from harness.tests.test_compaction_engine import _runner

    system, _, run_id, _ = _runner(tmp_path)
    result = system.activate_once(run_id)
    assert result.phase == "ENGINEERING"
    assert len(result.compactions) > 1
    return system, run_id


def test_compaction_audit_checks_partial_sources_and_resumed_input(compacted_run):
    system, run_id = compacted_run
    fields = isolation_fields(system.store, system.artifacts, run_id)
    assert fields["context_isolated"] is True, fields["model_input_audit"]["notes"]
    assert fields["model_input_audit"]["compaction_count"] > 1


@pytest.mark.parametrize("mutation,expected", [
    ("source_ref", "recorded compaction plan"), ("coverage", "checkpoint coverage"),
    ("summary", "bounded model output"), ("work_input", "department's recorded outputs"),
])
def test_compaction_audit_rejects_invented_sources_summary_or_visible_history(compacted_run, monkeypatch, mutation, expected):
    system, run_id = compacted_run
    events = _events_for_mutation(system, run_id, monkeypatch)
    compacted = next(event for event in events if event.type == EventType.COMPACTION_RECORDED)
    if mutation == "source_ref":
        compacted.payload["source_refs"][0]["event_id"] = "another-department-event"
    elif mutation == "coverage":
        compacted.payload["checkpoint"]["covered_digest"] = canonical_hash("unrelated history")
    elif mutation == "summary":
        ref = system.artifacts.put(run_id, "department_summary", "An invented summary", media_type="text/plain")
        compacted.payload["summary_ref"] = asdict(ref)
        compacted.artifact_hashes.append(ref.content_hash)
    else:
        assembled = next(event for event in reversed(events)
                         if event.type == EventType.CONTEXT_ASSEMBLED and event.payload["purpose"] == "work")
        request = json.loads(system.artifacts.get_text(assembled.payload["request_ref"]["content_hash"]))
        request["input"][1]["content"] = "Another department's unrelated summary"
        ref = system.artifacts.put(run_id, "model_request", json_dumps(request), media_type="application/json")
        assembled.payload["request_ref"] = asdict(ref)
        assembled.payload["digest"] = canonical_hash(request)
        assembled.context_digest = canonical_hash(request)
        assembled.artifact_hashes = [ref.content_hash]
        attempted = next(event for event in events if event.type == EventType.MODEL_REQUESTED
                         and event.payload["activation_id"] == assembled.payload["activation_id"]
                         and event.payload["step_id"] == assembled.payload["step_id"])
        attempted.context_digest = canonical_hash(request)
    fields = isolation_fields(system.store, system.artifacts, run_id)
    assert fields["context_isolated"] is False
    assert any(expected in note for note in fields["model_input_audit"]["notes"])


def test_unmatched_host_receipt_does_not_pass(native_run, monkeypatch):
    system, run_id = native_run
    events = _events_for_mutation(system, run_id, monkeypatch)
    events[:] = [event for event in events
                 if not (event.type == EventType.TOOL_CALLED and event.payload.get("name") == "run_check")]
    summary = summarize_run(system, run_id, scenario="happy")
    assert summary["check_receipts_verified"] is False
    assert any("no matching host execution" in note for note in summary["check_receipt_notes"])


def test_smoke_does_not_merge_a_previous_runtime_report(tmp_path, monkeypatch):
    (tmp_path / "smoke-report.json").write_text(json.dumps({"scenarios": {"old": {"phase": "DONE"}}}), encoding="utf-8")
    monkeypatch.setattr(ResponsesConfig, "from_env", classmethod(lambda cls: ResponsesConfig()))
    report = run_smoke(tmp_path)
    assert report["adapter"] == "responses"
    assert report["available"] is False
    assert report["scenarios"] == {}


def test_smoke_markdown_reports_model_input_audit():
    text = _markdown({
        "adapter": "responses", "available": True,
        "scenarios": {"happy": {
            "manifest_boundary": True, "model_input_audit": {"status": "unverified", "request_count": 2},
            "context_isolated": False, "check_receipts_verified": False,
        }},
    })
    assert "model input audit: `unverified`" in text
    assert "model requests: `2`" in text
    assert "context isolated: `False`" in text
    assert "host receipts verified: `False`" in text
    assert "omp" not in text.lower()
