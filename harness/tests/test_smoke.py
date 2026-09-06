import json

import pytest

from harness.adapters.omp_isolation import (
    CAPTURE_SCHEMA, CAPTURE_SEMANTIC, ISOLATION_FLAGS, POLICY_ID, overlay_sha256,
)
from harness.event_store import EventStore
from harness.models import EventType
from harness.smoke import isolation_fields, smoke_exit_code, _markdown


def test_smoke_requires_host_receipts_and_rejects_fake():
    base = {
        "phase": "DONE",
        "stop_reason": "released",
        "replay_consistent": True,
        "context_isolated": True,
        "check_receipts": [{"name": "smoke", "exit_code": 0}],
        "fake_used": False,
        "ask_count": 1,
    }
    assert smoke_exit_code({"available": True, "scenarios": {"happy": base, "ask": base}}) == 0
    assert smoke_exit_code({"available": False, "scenarios": {}}) == 2
    assert smoke_exit_code({"available": True, "scenarios": {"happy": dict(base, fake_used=True)}}) == 2
    assert smoke_exit_code({"available": True, "scenarios": {"happy": dict(base, check_receipts=[])}}) == 1
    assert smoke_exit_code({"available": True, "scenarios": {"ask": dict(base, ask_count=0)}}) == 1
    assert smoke_exit_code({"available": True, "scenarios": {"happy": dict(base, context_isolated=False)}}) == 1


def _manifest(store, activation="act"):
    store.append(
        "run",
        EventType.CONTEXT_ASSEMBLED,
        state_before="CREATED",
        state_after="PRODUCT_SPEC",
        session_id="ses",
        context_digest="manifest-digest",
        payload={
            "activation_id": activation,
            "department": "product",
            "injected": [{"source": "proposal_contract"}],
            "excluded": [
                {"source": "other_department_transcript"},
                {"source": "historical_transcript"},
                {"source": "omp_autodiscovery"},
            ],
        },
    )


def test_manifest_boundary_without_capture_is_not_isolation(tmp_path):
    store = EventStore(tmp_path / "events.sqlite")
    _manifest(store)
    fields = isolation_fields(store, "run")
    assert fields["manifest_boundary"] is True
    assert fields["omp_policy_capture"]["status"] == "unverified"
    assert fields["omp_launch_policy"]["byte_identical_to_manifest"] is False
    assert fields["context_isolated"] is False
    assert any("not sufficient" in note for note in fields["context_isolation_notes"])


def test_failed_run_without_assembly_does_not_claim_manifest_boundary(tmp_path):
    store = EventStore(tmp_path / "events.sqlite")
    fields = isolation_fields(store, "run")
    assert fields["manifest_boundary"] is False
    assert fields["omp_policy_capture"]["status"] == "unverified"
    assert fields["context_isolated"] is False


def test_smoke_markdown_separates_manifest_and_capture():
    report = {
        "adapter": "omp",
        "provider": "local-canary",
        "model": "canary-model",
        "available": True,
        "scenarios": {
            "happy": {
                "run_id": "run",
                "phase": "FAILED",
                "stop_reason": "provider_error",
                "replay_consistent": True,
                "manifest_boundary": True,
                "omp_launch_policy": {
                    "policy_id": "overlay-disabled-9-discovery-providers+host-system-prompt+isolation-flags",
                    "omp_generated": ["environment", "footer"],
                    "byte_identical_to_manifest": False,
                },
                "omp_policy_capture": {"status": "unverified"},
                "context_isolated": False,
                "context_isolation_notes": ["isolation not verified; manifest boundary is not sufficient"],
                "fake_used": False,
            }
        },
    }
    text = _markdown(report)
    assert "manifest boundary: `True`" in text
    assert "omp policy capture: `unverified`" in text
    assert "context isolated: `False`" in text
    assert "byte identical to manifest: `False`" in text
    assert "omp generated sections: `environment, footer`" in text


@pytest.fixture
def isolation_evidence(tmp_path, monkeypatch):
    store = EventStore(tmp_path / "events.sqlite")
    path = tmp_path / "capture.json"
    monkeypatch.setattr("harness.adapters.omp_isolation.capture_evidence_path", lambda: path)
    launch = {
        "host_launch": True, "usage_only": True, "run_id": "run",
        "session_id": "ses", "activation_id": "act", "context_digest": "manifest-digest",
        "policy_id": POLICY_ID, "overlay_sha256": overlay_sha256(),
        "flags": list(ISOLATION_FLAGS), "process_started": True, "verifiable": True,
        "runtime": {"files": [{"sha256": "a" * 64}]}, "launch_args_sha256": "b" * 64,
        "prompt_sources": {"host_system_prompt": {"manifest_digest": "manifest-digest"}},
    }
    capture = {
        "schema": CAPTURE_SCHEMA, "semantic": CAPTURE_SEMANTIC, "policy_id": POLICY_ID,
        "verified": True, "canaries_present": False, "host_tools_registered": True,
        "host_tools_roundtrip": True, "custom_prompt_in_system": True, "request_count": 2,
        "overlay_sha256": overlay_sha256(), "flags": list(ISOLATION_FLAGS),
        "runtime_sha256": ["a" * 64], "launch_args_sha256": "b" * 64,
    }
    path.write_text(json.dumps(capture), encoding="utf-8")
    yield store, path, launch, capture
    store.close()


def _launch(store, launch):
    store.append("run", EventType.CONTEXT_ASSEMBLED, state_before="PRODUCT_SPEC", state_after="PRODUCT_SPEC", session_id="ses", context_digest="manifest-digest", payload=launch)


def test_verified_probe_cannot_certify_historical_or_partially_observed_run(isolation_evidence):
    store, _, launch, _ = isolation_evidence
    _manifest(store)
    assert isolation_fields(store, "run")["context_isolated"] is False
    _launch(store, launch)
    fields = isolation_fields(store, "run")
    assert fields["context_isolated"] is True
    assert fields["omp_policy_capture"]["semantic"] == CAPTURE_SEMANTIC
    _manifest(store, "act-missing-launch")
    assert isolation_fields(store, "run")["context_isolated"] is False


@pytest.mark.parametrize("field,value", [
    ("schema", "old"), ("verified", False), ("canaries_present", True),
    ("canaries_present", None), ("runtime_sha256", []), ("runtime_sha256", ["c" * 64]),
    ("overlay_sha256", "c" * 64), ("flags", 1), ("launch_args_sha256", "c" * 64),
    ("host_tools_registered", False), ("host_tools_roundtrip", False), ("request_count", 1),
])
def test_invalid_or_mismatched_capture_is_unverified(isolation_evidence, field, value):
    store, path, launch, capture = isolation_evidence
    _manifest(store)
    _launch(store, launch)
    capture[field] = value
    path.write_text(json.dumps(capture), encoding="utf-8")
    assert isolation_fields(store, "run")["context_isolated"] is False


@pytest.mark.parametrize("field,value", [
    ("run_id", "unrelated"), ("activation_id", "unrelated"),
    ("session_id", "unrelated"), ("context_digest", "unrelated"),
    ("process_started", False), ("runtime", {"files": []}),
    ("prompt_sources", {}), ("verifiable", False),
])
def test_unknown_or_unbound_launch_is_unverified(isolation_evidence, field, value):
    store, _, launch, _ = isolation_evidence
    _manifest(store)
    launch[field] = value
    _launch(store, launch)
    assert isolation_fields(store, "run")["context_isolated"] is False


def test_missing_or_broken_capture_is_unverified(isolation_evidence):
    store, path, launch, _ = isolation_evidence
    _manifest(store)
    _launch(store, launch)
    path.unlink()
    assert isolation_fields(store, "run")["context_isolated"] is False
    path.write_text("invalid json", encoding="utf-8")
    assert isolation_fields(store, "run")["context_isolated"] is False
