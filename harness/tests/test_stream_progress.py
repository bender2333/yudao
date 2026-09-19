"""Bounded host-side progress facts for provider streams."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from harness.tests.protocol_helpers import ResponsesAdapter
from harness.models import ArtifactRef, EventType
from harness.tests.test_responses import _server, _submit_stream
from harness.runtime import LoopSystem


def test_stream_artifact_records_host_observed_time_and_progress_stages(tmp_path: Path):
    with _server([_submit_stream()]) as (config, *_):
        system = LoopSystem.for_testing(tmp_path, ResponsesAdapter(config))
        run_id = system.create_run("stream progress")
        system.activate_once(run_id)

    events = system.store.list_events(run_id)
    progress = [event for event in events if event.type == EventType.MODEL_STREAM_PROGRESS]
    finished = next(event for event in events if event.type == EventType.MODEL_ATTEMPT_FINISHED)
    assert progress
    assert progress[0].payload["attempt_id"] == finished.payload["attempt_id"]
    assert progress[0].payload["first_observed_at"]
    assert any(event.payload["stage"] == "response_created" for event in progress)
    assert any(event.payload["stage"] == "output_item_done" for event in progress)
    for event in progress:
        datetime.fromisoformat(event.payload["observed_at"])
        assert event.payload["source"] == "sdk_decoded_stream"
        assert "event" not in event.payload

    ref = ArtifactRef(**finished.payload["stream_events_ref"])
    lines = [json.loads(line) for line in system.artifacts.get_for_run(run_id, ref).decode("utf-8").splitlines()]
    assert lines
    assert all(item["observed_at"] for item in lines)
    assert all("event" in item for item in lines)
    assert all("observed_at" not in item["event"] for item in lines)
