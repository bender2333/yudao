import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.context import ContextAssembler
from harness.models import EventType, RunProjection, canonical_hash, estimate_tokens, json_dumps
from harness.proposals import collaboration_request, delivery_turn, plan_turn, product_spec, response_turn, review_turn
from harness.providers.call import CallUsage, ModelResponse
from harness.runtime import LoopSystem
from harness.tests.helpers import (FAST_RETRIES, WAIT_FOR_RELEASE, after_event, recorded_context,
                                   start_waiting_for_writes, wait_for_file)
from harness.tests.protocol_helpers import complete, model_call


def _call(identity, name, **args):
    return {"id": identity, "call_id": identity, "type": "function_call", "name": name,
            "arguments": json_dumps(args)}


def _submit(identity="submit"):
    proposal = product_spec()
    proposal.pop("kind")
    return _call(identity, "submit_product_spec", **proposal)


def test_fake_adapter_has_no_workspace_and_does_not_execute_tools(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter())
    run_id = system.create_run("echo")
    context = ContextAssembler().assemble(system.project(run_id), department="engineering",
                                          session_id="session", activation_id="activation")
    call = model_call(context.input_items, context.tools)
    adapter = FakeAdapter([FakeTurn(writes={"owned.txt": "content"})])
    response = complete(adapter, call)
    assert not hasattr(call, "workspace")
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
    system = LoopSystem.for_testing(tmp_path, adapter)
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
        assert event.context_digest == canonical_hash(saved) == recorded_context(system, request).manifest.digest
        assert event.payload["token_estimate"] == estimate_tokens(json_dumps(saved))
        assert event.payload["admitted"]
        assert event.payload["request_ref"]["content_hash"] in event.artifact_hashes
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_large_history_requests_compaction_and_rejects_submit_in_summary_response(tmp_path):
    # A tool call in a tool-less summary request is malformed provider output: it is retried
    # within the attempt limit and never executed, so three of them fail the compaction.
    adapter = FakeAdapter([ModelResponse(output=[_call("read-1", "read_file", path="proof.txt")],
                                         usage=CallUsage(total_tokens=100, reported=True)),
                           product_spec(), product_spec(), product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    run_id = system.create_run("echo", context_window=6000)
    system.workspace(run_id).write_file("proof.txt", "x" * 40000)
    result = system.activate_once(run_id)
    assert len(adapter.invocations) == 4
    assert all(request.purpose == "compaction" and request.tools == [] for request in adapter.invocations[1:])
    assert [request.attempt for request in adapter.invocations[1:]] == [1, 2, 3]
    assert result.stop_reason == "compaction_failed"
    assert result.token_used == 100
    assert len(result.manifests) == 4
    assert result.manifests[-1].admitted
    events = system.store.list_events(run_id)
    assert sum(event.type == EventType.MODEL_REQUESTED for event in events) == 4
    assert not any(event.type == EventType.SPEC_ACCEPTED for event in events)
    assert not any(event.type == EventType.TOOL_STARTED and event.payload.get("name") == "submit_product_spec"
                   for event in events)
    tool = next(event for event in events if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "read_file")
    assert tool.payload["input_item"]["call_id"] == "read-1"
    assert tool.payload["output_ref"]


def test_cancel_after_context_preparation_prevents_model_attempt(tmp_path, monkeypatch):
    # 请求装配完成以后，另一个线程取消运行：取消在开始请求之前取得写入锁，这一步不开始模型调用
    adapter = FakeAdapter([product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    cancelled = []
    waiting = []
    after_event(monkeypatch, system, EventType.CONTEXT_ASSEMBLED, lambda _event: waiting.append(
        start_waiting_for_writes(lambda: cancelled.append(system.cancel(run_id).stop_reason))))

    result = system.activate_once(run_id)

    [canceller] = waiting
    canceller.join()
    assert not canceller.errors
    assert cancelled == ["cancelled"]
    assert result.stop_reason == "cancelled"
    assert not adapter.invocations
    assert result.token_used == 0
    assert result.manifests[0].admitted
    assert not any(event.type == EventType.MODEL_REQUESTED for event in system.store.list_events(run_id))


def test_cancel_before_tool_start_rejects_new_side_effect(tmp_path):
    def cancel_during_request(_call):
        system.cancel(run_id)
        return ModelResponse(output=[_call("write-1", "write_file", path="new.txt", content="new")])

    adapter = FakeAdapter([product_spec(), cancel_during_request])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    result = system.activate_once(run_id)
    assert result.stop_reason == "cancelled"
    assert "new.txt" not in system.workspace(run_id).list_files()
    assert not any(event.type == EventType.TOOL_STARTED and event.payload["id"] == "write-1" for event in system.store.list_events(run_id))


def test_cancel_records_inflight_tool_but_does_not_start_following_tool(tmp_path):
    # 登记命令运行中取消运行：这个命令的结果照常记录，之后的工具不开始
    signals = tmp_path / "signals"
    signals.mkdir()
    registry = {"wait": {"argv": ["python", "-c", WAIT_FOR_RELEASE, str(signals)], "args": [],
                         "timeout_sec": 60, "output_limit": 4000}}
    first = {"id": "command-1", "call_id": "command-1", "type": "function_call", "name": "run_command",
             "arguments": json_dumps({"name": "wait"})}
    second = _call("write-2", "write_file", path="later.txt", content="later")
    adapter = FakeAdapter([product_spec(), plan_turn(scope=["later.txt"]), ModelResponse(output=[first, second])])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo", registered_commands=registry, command_versions={"wait": 1})
    system.activate_once(run_id)
    system.activate_once(run_id)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        try:
            wait_for_file(signals / "started")
            assert system.cancel(run_id).stop_reason == "cancelled"
            assert not future.done()
        finally:
            (signals / "release").write_text("go")
        result = future.result(timeout=30)
    assert "later.txt" not in system.workspace(run_id).list_files()
    events = system.store.list_events(run_id)
    assert any(event.type == EventType.TOOL_CALLED and event.payload.get("id") == "command-1" for event in events)
    assert not any(event.type == EventType.TOOL_STARTED and event.payload["id"] == "write-2" for event in events)
    assert result.stop_reason == "cancelled"
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_original_intend_is_preserved_verbatim_outside_the_delivery_tree(tmp_path):
    original = "  Original request\r\n\r\nKeep these spaces.  \n\t"
    adapter = FakeAdapter([product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter)
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
        FakeTurn(proposal=collaboration_request(), transcript="ENGINEERING_PRIVATE"),
        response_turn("answered", "The existing requirements define the current behavior."),
        plan_turn(), delivery_turn(), review_turn("release", "valid host evidence"),
    ])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("Original intent")
    system.activate_once(run_id)
    system.activate_once(run_id)
    # A fresh controller restores history from persisted events, not in-memory provider state.
    reloaded = LoopSystem.for_testing(tmp_path, adapter)
    result = reloaded.run_until_stop(run_id)
    assert result.phase == "DONE", result.error
    resumed_product = adapter.invocations[2]
    history = resumed_product.input_items[1:]
    assert history[0]["role"] == "user"
    assert "current_work" in history[0]["content"]
    assert private in history
    assert "ENGINEERING_PRIVATE" not in json_dumps(history)
    assert history[-1]["role"] == "user"
    assert "[pending_request]" in history[-1]["content"]
    assert "submit_response" in history[-1]["content"]
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
    assert "[current_product_decisions]" not in engineering.input_items[-1]["content"]
    assert "The existing requirements define the current behavior." in engineering.input_items[-1]["content"]
    assert engineering.input_items[-2]["type"] == "function_call_output"
    events = reloaded.store.list_events(run_id)
    assert any(event.type == EventType.TOOL_SKIPPED and event.payload["id"] == "skip-read" for event in events)
    assert not any(event.type == EventType.TOOL_STARTED and event.payload["id"] == "skip-read" for event in events)
