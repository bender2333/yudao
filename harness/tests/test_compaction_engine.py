import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from harness.adapters.base import ModelObservation, ModelResponse
from harness.adapters.fake import FakeAdapter
from harness.models import EventType, canonical_hash, json_dumps
from harness.proposals import ask_request, product_spec, reaction
from harness.runtime import LoopSystem


def _message(request, text="Product memory: prior evidence was read; keep the original requirements."):
    return {"id": f"summary-{request.activation_id}-{request.step_id}", "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": text}]}


def _read(request, path):
    identity = f"read-{request.activation_id}-{request.step_id}"
    return ModelResponse(output=[{"id": identity, "call_id": identity, "type": "function_call", "name": "read_file",
                                  "arguments": json_dumps({"path": path})}])


def _runner(tmp_path, *, cancelled_summary=None):
    work_counts = {}

    def respond(request):
        if request.purpose == "compaction":
            if cancelled_summary is not None:
                return cancelled_summary(request)
            return ModelResponse(output=[_message(request)])
        count = work_counts.get(request.activation_id, 0)
        work_counts[request.activation_id] = count + 1
        if request.department == "engineering":
            return ask_request()
        if count == 0:
            return _read(request, "large.txt")
        return product_spec() if "[pending_ask]" not in request.context.prompt_text else reaction("accept", "Keep original behavior")

    adapter = FakeAdapter([respond] * 100)
    system = LoopSystem(tmp_path, adapter)
    original = "  Original intent\r\nDo not rewrite this. \n"
    run_id = system.create_run(original, context_window=6000)
    system.workspace(run_id).write_file("large.txt", "FIRST_TOOL_ORIGINAL " * 2200)
    return system, adapter, run_id, original


def test_compaction_preserves_originals_then_resumes_work_with_summary(tmp_path):
    system, adapter, run_id, original = _runner(tmp_path)
    result = system.activate_once(run_id)
    assert result.phase == "ENGINEERING", result.error
    assert result.compactions
    assert adapter.invocations[0].purpose == adapter.invocations[-1].purpose == "work"
    assert any(request.purpose == "compaction" for request in adapter.invocations)
    last = adapter.invocations[-1]
    assert "department_memory" in json_dumps(last.input_items)
    assert "FIRST_TOOL_ORIGINAL " * 100 not in json_dumps(last.input_items)
    events = system.store.list_events(run_id)
    raw_tool = next(event for event in events if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "read_file")
    assert system.artifacts.get_text(raw_tool.payload["output_ref"]["content_hash"]).count("FIRST_TOOL_ORIGINAL") == 2200
    for request, manifest in zip(adapter.invocations, result.manifests):
        assert request.input_items[0]["content"].startswith(f"[intend]\n{original}\n\n[current_work]\n")
        saved = json.loads(system.artifacts.get_text(manifest.request_ref["content_hash"]))
        assert canonical_hash(saved) == manifest.digest
        assert saved["input"] == request.input_items and saved["tools"] == request.tools
        if request.purpose == "compaction":
            assert not request.tools
            assert saved["max_output_tokens"] == request.max_output_tokens > 0
    source_ids = {record["event_id"] for record in system.orchestrator._department_history_records(run_id, "product")}
    summary_ids = {event.event_id for event in events if event.type == EventType.MODEL_MESSAGE and event.payload.get("purpose") == "compaction"}
    assert summary_ids and source_ids.isdisjoint(summary_ids)
    for record in result.compactions:
        assert record["run_id"] == run_id and record["department"] == "product"
        assert all(ref["event_id"] in source_ids for ref in record["source_refs"])
        assert system.artifacts.get_text(record["summary_ref"]["content_hash"]) == record["checkpoint"]["summary"]
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_compaction_checkpoint_survives_reactivation_and_new_controller(tmp_path):
    system, adapter, run_id, _ = _runner(tmp_path)
    first = system.activate_once(run_id)
    first_checkpoint = first.compactions[-1]["source_event_id"]
    system.activate_once(run_id)
    engineering = next(request for request in adapter.invocations if request.department == "engineering")
    assert "department_memory" not in json_dumps(engineering.input_items)
    assert "FIRST_TOOL_ORIGINAL" not in json_dumps(engineering.input_items)
    system.workspace(run_id).write_file("large.txt", "SECOND_TOOL_ORIGINAL " * 2200)
    reloaded = LoopSystem(tmp_path, adapter)
    result = reloaded.activate_once(run_id)
    assert result.phase == "ENGINEERING", result.error
    later = [record for record in result.compactions if record["source_event_id"] not in {item["source_event_id"] for item in first.compactions}]
    assert later
    assert later[0]["previous_compaction_event_id"] == first_checkpoint
    assert later[-1]["checkpoint"]["boundary"]
    assert adapter.invocations[-1].context.manifest.compaction_event_id == later[-1]["source_event_id"]
    assert "department_memory" in json_dumps(adapter.invocations[-1].input_items)
    assert result.canonical_state() == reloaded.replay(run_id).canonical_state()


def test_cancelled_compaction_keeps_observed_summary_without_adopting_it(tmp_path):
    entered, release = Event(), Event()

    def late_summary(request):
        item = _message(request, "LATE_SUMMARY_MUST_NOT_BE_ADOPTED")
        request.observe(ModelObservation(item["id"], "message", item, "LATE_SUMMARY_MUST_NOT_BE_ADOPTED"))
        entered.set()
        assert release.wait(5)
        return ModelResponse(output=[item])

    system, adapter, run_id, _ = _runner(tmp_path, cancelled_summary=late_summary)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        try:
            assert entered.wait(5)
            assert system.cancel(run_id).stop_reason == "cancelled"
        finally:
            release.set()
        result = future.result(timeout=5)
    assert result.stop_reason == "cancelled" and not result.compactions
    assert len(adapter.invocations) == 2
    events = system.store.list_events(run_id)
    assert any(event.type == EventType.MODEL_MESSAGE and event.payload.get("purpose") == "compaction" for event in events)
    assert "LATE_SUMMARY_MUST_NOT_BE_ADOPTED" not in json_dumps(system.orchestrator._department_history_records(run_id, "product"))


def test_step_limit_pauses_during_partial_compaction_without_work_request(tmp_path, monkeypatch):
    import harness.engine as engine

    monkeypatch.setattr(engine, "MAX_MODEL_STEPS", 2)
    system, adapter, run_id, _ = _runner(tmp_path)
    result = system.activate_once(run_id)
    assert result.phase == "PAUSED" and result.stop_reason == "model_steps_exhausted"
    assert len(adapter.invocations) == 2
    assert adapter.invocations[-1].purpose == "compaction"
    assert result.compactions and not result.compactions[-1]["checkpoint"]["boundary"]
    assert result.product_spec is None
