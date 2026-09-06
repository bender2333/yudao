import copy
import json
from dataclasses import asdict

import pytest

from harness.adapters.responses import ResponsesConfig
from harness.adapters.fake import FakeTurn
from harness.artifacts import ArtifactStore
from harness.event_store import EventStore
from harness.models import EventType, canonical_hash, json_dumps
from harness.proposals import product_spec, delivery, review, ask_request, reaction, delivery_turn, review_turn
from harness.smoke import isolation_fields, run_smoke, smoke_exit_code, summarize_run, _markdown
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
        "fake_used": False,
        "ask_count": 1,
    }
    assert smoke_exit_code({"available": True, "scenarios": {"happy": base, "ask": base}}) == 0
    assert smoke_exit_code({"available": False, "scenarios": {}}) == 2
    assert smoke_exit_code({"available": True, "scenarios": {"happy": dict(base, fake_used=True)}}) == 2
    for change in (
        {"check_receipts": []}, {"check_receipts_verified": False}, {"context_isolated": False},
        {"model_input_audit": None}, {"model_input_audit": {"status": "unverified"}},
    ):
        assert smoke_exit_code({"available": True, "scenarios": {"happy": dict(base, **change)}}) == 1
    assert smoke_exit_code({"available": True, "scenarios": {"ask": dict(base, ask_count=0)}}) == 1


@pytest.fixture
def native_run(data_dir):
    script = [
        product_spec(),
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
    assert summary["model_input_audit"]["activation_count"] == 3
    assert summary["check_receipts_verified"] is True, summary["check_receipt_notes"]
    assert summary["replay_consistent"] is True
    assert summary["fake_used"] is True
    assert smoke_exit_code({"available": True, "scenarios": {"happy": summary}}) == 2


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


def test_audit_preserves_department_history_when_ask_returns_to_product(data_dir):
    system, projection = run_scripted(data_dir, [
        product_spec(), ask_request(), reaction("reply", "Treat dash-prefixed input as ordinary text."),
        delivery_turn(), review_turn("release", "host checks passed"),
    ])
    assert projection.phase == "DONE"
    fields = isolation_fields(system.store, system.artifacts, projection.run_id)
    assert fields["context_isolated"] is True, fields["model_input_audit"]["notes"]
    assert fields["model_input_audit"]["activation_count"] == 5


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
