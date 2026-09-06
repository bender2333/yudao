import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from harness.adapters.base import ModelRequest, ModelResponse
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.context import ContextAssembler
from harness.models import EventType, RunProjection, Usage, canonical_hash, estimate_tokens, json_dumps
from harness.proposals import ask_request, delivery_turn, plan_turn, product_spec, reaction, review_turn
from harness.runtime import LoopSystem
from harness.tools import ToolRuntime


def _call(identity, name, **args):
    return {"id": identity, "call_id": identity, "type": "function_call", "name": name,
            "arguments": json_dumps(args)}


def _submit(identity="submit"):
    proposal = product_spec()
    proposal.pop("kind")
    return _call(identity, "submit_product_spec", **proposal)


def test_fake_adapter_has_no_workspace_and_does_not_execute_tools(tmp_path):
    context = ContextAssembler().assemble(RunProjection(task="echo"), department="engineering",
                                          session_id="session", activation_id="activation")
    request = ModelRequest("run", "engineering", "session", "activation", 1, context, context.tools, Event())
    adapter = FakeAdapter([FakeTurn(writes={"owned.txt": "content"})])
    response = adapter.complete(request)
    assert not hasattr(request, "workspace")
    assert not hasattr(adapter, "invoke")
    assert response.output[0]["name"] == "write_file"
    assert json.loads(response.output[0]["arguments"]) == {"path": "owned.txt", "content": "content"}
    assert not (tmp_path / "owned.txt").exists()


def test_each_step_assembles_auditable_input_with_only_current_activation_history(tmp_path):
    reasoning = {"id": "reason-1", "type": "reasoning", "summary": [], "encrypted_content": "PRIVATE_CHAIN"}
    lookup = _call("read-1", "read_file", path="proof.txt")
    adapter = FakeAdapter([
        ModelResponse(output=[reasoning, lookup]),
        ModelResponse(output=[_submit(), _call("after-submit", "read_file", path="must-not-read.txt")]),
        plan_turn(), delivery_turn(), review_turn("release", "valid host evidence"),
    ])
    system = LoopSystem(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.workspace(run_id).write_file("proof.txt", "CAUSAL_TOOL_OUTPUT")
    result = system.run_until_stop(run_id)
    assert result.phase == "DONE"
    assert [request.step_id for request in adapter.invocations] == [1, 2, 1, 1, 1]
    assert adapter.invocations[1].input_items[2:4] == [reasoning, lookup]
    tool_input = adapter.invocations[1].input_items[4]
    assert tool_input["call_id"] == "read-1"
    assert json.loads(tool_input["output"])["output"] == "CAUSAL_TOOL_OUTPUT"
    for request in adapter.invocations[2:]:
        assert "PRIVATE_CHAIN" not in json_dumps(request.input_items)
        assert "CAUSAL_TOOL_OUTPUT" not in json_dumps(request.input_items)
        assert request.input_items[-1]["role"] == "user"
    assert len(adapter.invocations[2].input_items) == len(adapter.invocations[4].input_items) == 2
    assert any(item.get("name") == "submit_plan" for item in adapter.invocations[3].input_items)
    events = system.store.list_events(run_id)
    assert not any(event.type == EventType.TOOL_STARTED and event.payload["id"] == "after-submit" for event in events)
    contexts = [event for event in events if event.type == EventType.CONTEXT_ASSEMBLED]
    assert len(contexts) == len(adapter.invocations)
    for event, request in zip(contexts, adapter.invocations):
        saved = json.loads(system.artifacts.get_text(event.payload["request_ref"]["content_hash"]))
        assert saved == {"input": request.input_items, "tools": request.tools}
        assert event.context_digest == canonical_hash(saved) == request.context.manifest.digest
        assert event.payload["token_estimate"] == estimate_tokens(json_dumps(saved))
        assert event.payload["admitted"]
        assert event.payload["request_ref"]["content_hash"] in event.artifact_hashes
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_large_history_requests_compaction_and_rejects_submit_in_summary_response(tmp_path):
    adapter = FakeAdapter([ModelResponse(output=[_call("read-1", "read_file", path="proof.txt")],
                                         usage=Usage(total_tokens=100)), product_spec()])
    system = LoopSystem(tmp_path, adapter)
    run_id = system.create_run("echo", context_window=6000)
    system.workspace(run_id).write_file("proof.txt", "x" * 40000)
    result = system.activate_once(run_id)
    assert len(adapter.invocations) == 2
    assert adapter.invocations[1].purpose == "compaction"
    assert adapter.invocations[1].tools == []
    assert result.stop_reason == "compaction_failed"
    assert result.token_used == 100
    assert len(result.manifests) == 2
    assert result.manifests[-1].admitted
    events = system.store.list_events(run_id)
    assert sum(event.type == EventType.MODEL_REQUESTED for event in events) == 2
    assert not any(event.type == EventType.SPEC_ACCEPTED for event in events)
    tool = next(event for event in events if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "read_file")
    assert tool.payload["input_item"]["call_id"] == "read-1"
    assert tool.payload["output_ref"]


def test_cancel_after_context_preparation_prevents_model_attempt(tmp_path, monkeypatch):
    prepared, release = Event(), Event()
    adapter = FakeAdapter([product_spec()])
    system = LoopSystem(tmp_path, adapter)
    run_id = system.create_run("echo")
    begin = system.orchestrator._begin_request

    def delayed_begin(activation, request):
        prepared.set()
        assert release.wait(5)
        return begin(activation, request)

    monkeypatch.setattr(system.orchestrator, "_begin_request", delayed_begin)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        try:
            assert prepared.wait(5)
            assert system.cancel(run_id).stop_reason == "cancelled"
        finally:
            release.set()
        result = future.result(timeout=5)
    assert not adapter.invocations
    assert result.token_used == 0
    assert result.manifests[0].admitted
    assert not any(event.type == EventType.MODEL_REQUESTED for event in system.store.list_events(run_id))


def test_cancel_before_tool_start_rejects_new_side_effect(tmp_path, monkeypatch):
    pending, release = Event(), Event()
    adapter = FakeAdapter([product_spec(), ModelResponse(output=[_call("write-1", "write_file", path="new.txt", content="new")])])
    system = LoopSystem(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    begin = system.orchestrator._begin_tool

    def delayed_begin(activation, call):
        pending.set()
        assert release.wait(5)
        return begin(activation, call)

    monkeypatch.setattr(system.orchestrator, "_begin_tool", delayed_begin)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        try:
            assert pending.wait(5)
            assert system.cancel(run_id).stop_reason == "cancelled"
        finally:
            release.set()
        future.result(timeout=5)
    assert "new.txt" not in system.workspace(run_id).list_files()
    assert not any(event.type == EventType.TOOL_STARTED and event.payload["id"] == "write-1" for event in system.store.list_events(run_id))


def test_cancel_records_inflight_tool_but_does_not_start_following_tool(tmp_path, monkeypatch):
    entered, release = Event(), Event()
    first = _call("write-1", "write_file", path="started.txt", content="started")
    second = _call("write-2", "write_file", path="later.txt", content="later")
    adapter = FakeAdapter([product_spec(), plan_turn(scope=["started.txt", "later.txt"]), ModelResponse(output=[first, second])])
    system = LoopSystem(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    execute = ToolRuntime.execute

    def delayed_execute(runtime, department, name, args=None):
        if name == "write_file":
            entered.set()
            assert release.wait(5)
        return execute(runtime, department, name, args)

    monkeypatch.setattr(ToolRuntime, "execute", delayed_execute)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        try:
            assert entered.wait(5)
            assert system.cancel(run_id).stop_reason == "cancelled"
            assert not future.done()
        finally:
            release.set()
        result = future.result(timeout=5)
    assert system.workspace(run_id).read_file("started.txt") == "started"
    assert "later.txt" not in system.workspace(run_id).list_files()
    events = system.store.list_events(run_id)
    assert any(event.type == EventType.TOOL_CALLED and event.payload.get("id") == "write-1" for event in events)
    assert not any(event.type == EventType.TOOL_STARTED and event.payload["id"] == "write-2" for event in events)
    assert result.stop_reason == "cancelled"
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_original_intend_is_preserved_verbatim_outside_the_delivery_tree(tmp_path):
    original = "  Original request\r\n\r\nKeep these spaces.  \n\t"
    adapter = FakeAdapter([product_spec()])
    system = LoopSystem(tmp_path, adapter)
    run_id = system.create_run(original)
    result = system.activate_once(run_id)
    assert result.task == original
    assert (tmp_path / "materials" / run_id / "intend.md").read_bytes() == original.encode("utf-8")
    assert system.artifacts.get_text(result.intend_ref["content_hash"]) == original
    assert "intend.md" not in system.workspace(run_id).list_files()
    assert adapter.invocations[0].input_items[0]["content"].startswith(f"[intend]\n{original}\n\n[current_work]\n")
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_reactivated_department_restores_its_received_work_outputs_and_complete_submit_pairs(tmp_path):
    private = {"id": "product-private", "type": "reasoning", "summary": [], "encrypted_content": "PRODUCT_PRIVATE"}
    skipped = _call("skip-read", "read_file", path="never-read.txt")
    adapter = FakeAdapter([
        ModelResponse(output=[private, _submit(), skipped]),
        FakeTurn(proposal=ask_request(), transcript="ENGINEERING_PRIVATE"),
        reaction("accept", "Keep current behavior"),
        plan_turn(), delivery_turn(), review_turn("release", "valid host evidence"),
    ])
    system = LoopSystem(tmp_path, adapter)
    run_id = system.create_run("Original intent")
    system.activate_once(run_id)
    system.activate_once(run_id)
    # A fresh controller restores history from persisted events, not in-memory provider state.
    reloaded = LoopSystem(tmp_path, adapter)
    result = reloaded.run_until_stop(run_id)
    assert result.phase == "DONE", result.error
    resumed_product = adapter.invocations[2]
    history = resumed_product.input_items[1:]
    assert history[0]["role"] == "user"
    assert "current_work" in history[0]["content"]
    assert private in history
    assert "ENGINEERING_PRIVATE" not in json_dumps(history)
    assert history[-1]["role"] == "user"
    assert "[pending_ask]" in history[-1]["content"]
    assert "submit_reaction" in history[-1]["content"]
    assert history[-2]["type"] == "function_call_output"
    assert any(item.get("call_id") == "submit" and item["type"] == "function_call_output" for item in history)
    skipped_result = next(item for item in history if item.get("call_id") == "skip-read" and item["type"] == "function_call_output")
    assert json.loads(skipped_result["output"])["ok"] is False
    assert "Not executed" in skipped_result["output"]
    call_ids = [item["call_id"] for item in history if item.get("type") == "function_call"]
    output_ids = [item["call_id"] for item in history if item.get("type") == "function_call_output"]
    assert call_ids == output_ids
    engineering = adapter.invocations[3]
    assert "ENGINEERING_PRIVATE" in json_dumps(engineering.input_items)
    assert "PRODUCT_PRIVATE" not in json_dumps(engineering.input_items)
    assert engineering.input_items[-1]["role"] == "user"
    assert "[current_product_decisions]" in engineering.input_items[-1]["content"]
    assert "产品回复已经到达" in engineering.input_items[-1]["content"]
    assert engineering.input_items[-2]["type"] == "function_call_output"
    events = reloaded.store.list_events(run_id)
    assert any(event.type == EventType.TOOL_SKIPPED and event.payload["id"] == "skip-read" for event in events)
    assert not any(event.type == EventType.TOOL_STARTED and event.payload["id"] == "skip-read" for event in events)
