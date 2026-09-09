import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from harness.adapters.base import ModelObservation, ModelResponse
from harness.adapters.fake import FakeAdapter
from harness.models import EventType, canonical_hash, json_dumps
from harness.proposals import collaboration_request, product_spec, response_turn
from harness.runtime import LoopSystem


def _message(request, text="Product memory: prior evidence was read; keep the original requirements."):
    return {"id": f"summary-{request.activation_id}-{request.step_id}", "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": text}]}


def _read(request, path):
    identity = f"read-{request.activation_id}-{request.step_id}"
    return ModelResponse(output=[{"id": identity, "call_id": identity, "type": "function_call", "name": "read_file",
                                  "arguments": json_dumps({"path": path})}])


def _runner(tmp_path, *, cancelled_summary=None, reject_first_spec=False):
    work_counts = {}
    rejected_spec = False

    def respond(request):
        nonlocal rejected_spec
        if request.purpose == "compaction":
            if cancelled_summary is not None:
                return cancelled_summary(request)
            return ModelResponse(output=[_message(request)])
        count = work_counts.get(request.activation_id, 0)
        work_counts[request.activation_id] = count + 1
        if request.department == "engineering":
            return collaboration_request()
        if count == 0:
            return _read(request, "large.txt")
        if reject_first_spec and not rejected_spec:
            rejected_spec = True
            return product_spec() | {"acceptance_criteria": []}
        return product_spec() if request.request_id is None else response_turn("answered", "The original requirements remain applicable.")(request)

    adapter = FakeAdapter([respond] * 100)
    system = LoopSystem.for_testing(tmp_path, adapter)
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
        pinned_index = 1 if request.purpose == "compaction" else 0
        assert request.input_items[pinned_index]["content"].startswith(f"[intend]\n{original}\n\n[current_work]\n")
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
    system, adapter, run_id, _ = _runner(tmp_path, reject_first_spec=True)
    first = system.activate_once(run_id)
    assert first.phase == "PRODUCT_SPEC" and first.effective_contract is None
    assert first.rejections[-1]["errors"][0]["field"] == "acceptance_criteria"
    first_checkpoint = first.compactions[-1]["source_event_id"]
    system.workspace(run_id).write_file("large.txt", "SECOND_TOOL_ORIGINAL " * 2200)
    reloaded = LoopSystem.for_testing(tmp_path, adapter)
    result = reloaded.activate_once(run_id)
    assert result.phase == "ENGINEERING", result.error
    later = [record for record in result.compactions if record["source_event_id"] not in {item["source_event_id"] for item in first.compactions}]
    assert later
    assert later[0]["previous_compaction_event_id"] == first_checkpoint
    assert later[0]["effective_contract_hash"] == first.compactions[-1]["effective_contract_hash"] is None
    assert later[0]["engineering_plan_hash"] == first.compactions[-1]["engineering_plan_hash"] is None
    assert later[-1]["checkpoint"]["boundary"]
    assert adapter.invocations[-1].context.manifest.compaction_event_id == later[-1]["source_event_id"]
    assert "department_memory" in json_dumps(adapter.invocations[-1].input_items)
    assert result.canonical_state() == reloaded.replay(run_id).canonical_state()


def test_changed_contract_rebuilds_compaction_from_preserved_original_sources(tmp_path):
    system, adapter, run_id, _ = _runner(tmp_path)
    first = system.activate_once(run_id)
    assert first.phase == "ENGINEERING" and first.effective_contract is not None
    assert first.compactions[-1]["effective_contract_hash"] is None
    first_checkpoint = first.compactions[-1]["source_event_id"]
    source = next(event for event in system.store.list_events(run_id)
                  if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "read_file")
    original = system.artifacts.get_text(source.payload["output_ref"]["content_hash"])
    system.activate_once(run_id)
    engineering = next(request for request in adapter.invocations if request.department == "engineering")
    assert "department_memory" not in json_dumps(engineering.input_items)
    assert "FIRST_TOOL_ORIGINAL" not in json_dumps(engineering.input_items)
    system.workspace(run_id).write_file("large.txt", "SECOND_TOOL_ORIGINAL " * 2200)
    reloaded = LoopSystem.for_testing(tmp_path, adapter)
    result = reloaded.activate_once(run_id)
    assert result.phase == "ENGINEERING", result.error
    previous_ids = {item["source_event_id"] for item in first.compactions}
    later = [record for record in result.compactions if record["source_event_id"] not in previous_ids]
    assert later and later[0]["previous_compaction_event_id"] is None
    assert all(record["effective_contract_hash"] == first.effective_contract.content_hash for record in later)
    assert source.event_id in {ref["event_id"] for record in later for ref in record["source_refs"]}
    assert first_checkpoint in {record["source_event_id"] for record in result.compactions}
    assert system.artifacts.get_text(source.payload["output_ref"]["content_hash"]) == original
    assert original.count("FIRST_TOOL_ORIGINAL") == 2200
    assert later[-1]["checkpoint"]["boundary"]
    assert adapter.invocations[-1].context.manifest.compaction_event_id == later[-1]["source_event_id"]
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


CORRUPT_TOOL_NAME = "thought\n<ctrl95><ctrl42>call:list_files"


def _undeclared_tool_call(request):
    identity = f"corrupt-{request.activation_id}-{request.step_id}"
    return ModelResponse(output=[{"id": identity, "call_id": identity, "type": "function_call",
                                  "name": CORRUPT_TOOL_NAME, "arguments": "{}"}])


def _fast_retries(monkeypatch):
    import harness.engine as engine

    monkeypatch.setattr(engine, "RETRY_INITIAL_DELAY_SEC", 0.01)
    monkeypatch.setattr(engine, "RETRY_MAX_DELAY_SEC", 0.02)


def test_undeclared_tool_call_in_summary_is_a_retryable_failure_that_never_executes(tmp_path, monkeypatch):
    _fast_retries(monkeypatch)
    compaction_count = 0

    def summary(request):
        nonlocal compaction_count
        compaction_count += 1
        return _undeclared_tool_call(request) if compaction_count == 1 else ModelResponse(output=[_message(request)])

    system, adapter, run_id, _ = _runner(tmp_path, cancelled_summary=summary)
    result = system.activate_once(run_id)

    assert result.phase == "ENGINEERING", result.error
    assert result.compactions
    attempts = [request for request in adapter.invocations if request.purpose == "compaction"]
    assert attempts[0].tools == attempts[1].tools == []
    assert attempts[0].input_items == attempts[1].input_items
    assert (attempts[0].attempt, attempts[1].attempt) == (1, 2)
    assert attempts[0].root_step_id == attempts[1].root_step_id and attempts[1].retry_of_step_id == attempts[0].step_id
    events = system.store.list_events(run_id)
    failed = [event for event in events if event.type == EventType.MODEL_ATTEMPT_FAILED]
    assert len(failed) == 1
    assert failed[0].payload["purpose"] == "compaction"
    assert failed[0].payload["reason"] == "compaction_failed"
    assert failed[0].payload["retryable"] is True and failed[0].payload["will_retry"] is True
    assert failed[0].payload["diagnostics"] == {"error_type": "undeclared_tool_call", "tool_names": [CORRUPT_TOOL_NAME]}
    assert len([event for event in events if event.type == EventType.MODEL_RETRY_SCHEDULED]) == 1
    # Nothing executed: no tool admission, no tool result, only the token accounting record.
    assert not any(event.type == EventType.TOOL_STARTED and event.payload.get("name") == CORRUPT_TOOL_NAME for event in events)
    assert all(event.payload.get("name") == "provider_usage" for event in events
               if event.type in {EventType.TOOL_CALLED, EventType.TOOL_SKIPPED} and event.payload.get("purpose") == "compaction")
    # The corrupt output stays as evidence but never becomes department history or summary source.
    evidence = [event for event in events if event.type == EventType.MODEL_MESSAGE
                and event.payload.get("response_id", "").startswith("corrupt-")]
    assert len(evidence) == 1
    saved = json.loads(system.artifacts.get_text(evidence[0].payload["message_ref"]["content_hash"]))
    assert saved["type"] == "function_call" and saved["name"] == CORRUPT_TOOL_NAME
    assert "corrupt-" not in json_dumps(system.orchestrator._department_history_records(run_id, "product"))
    assert "corrupt-" not in json_dumps([record["source_refs"] for record in result.compactions])
    assert "corrupt-" not in json_dumps(adapter.invocations[-1].input_items)
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_three_undeclared_tool_calls_fail_compaction_and_keep_every_attempt_as_evidence(tmp_path, monkeypatch):
    _fast_retries(monkeypatch)
    system, adapter, run_id, _ = _runner(tmp_path, cancelled_summary=_undeclared_tool_call)
    result = system.activate_once(run_id)

    assert result.phase == "FAILED" and result.stop_reason == "compaction_failed"
    assert not result.compactions
    attempts = [request for request in adapter.invocations if request.purpose == "compaction"]
    assert [request.attempt for request in attempts] == [1, 2, 3]
    assert len({request.root_step_id for request in attempts}) == 1
    events = system.store.list_events(run_id)
    failed = [event for event in events if event.type == EventType.MODEL_ATTEMPT_FAILED]
    assert [event.payload["will_retry"] for event in failed] == [True, True, False]
    assert all(event.payload["reason"] == "compaction_failed" and event.payload["retryable"] is True for event in failed)
    assert len([event for event in events if event.type == EventType.MODEL_RETRY_SCHEDULED]) == 2
    evidence = [event for event in events if event.type == EventType.MODEL_MESSAGE
                and event.payload.get("response_id", "").startswith("corrupt-")]
    assert len(evidence) == 3
    assert not any(event.type == EventType.TOOL_STARTED and event.payload.get("name") == CORRUPT_TOOL_NAME for event in events)
    assert all(event.payload.get("name") == "provider_usage" for event in events
               if event.type in {EventType.TOOL_CALLED, EventType.TOOL_SKIPPED} and event.payload.get("purpose") == "compaction")
    raw_tool = next(event for event in events if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "read_file")
    assert system.artifacts.get_text(raw_tool.payload["output_ref"]["content_hash"]).count("FIRST_TOOL_ORIGINAL") == 2200
    history = system.orchestrator._department_history_records(run_id, "product")
    assert raw_tool.event_id in {record["event_id"] for record in history}
    assert "corrupt-" not in json_dumps(history)
    assert result.canonical_state() == system.replay(run_id).canonical_state()


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
