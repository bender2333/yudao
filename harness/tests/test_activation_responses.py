"""The native loop owns each request, tool execution and durable model evidence."""

import json

from harness.watched_outputs import has_new_work
from harness.models import EventType, canonical_hash
from harness.proposals import product_spec
from harness.environment import inspection_root
from harness.runtime import LoopSystem
from harness.tests.protocol_helpers import (
    STUB_CALL as CALL,
    STUB_REASONING as REASONING,
    STUB_USAGE as RAW_USAGE,
    ResponsesAdapter,
    stub_server as _server,
    stub_stream as _stream,
    write_stub_reply as _send,
)


SUBMIT = {"id": "fc-submit", "type": "function_call", "name": "submit_product_spec", "call_id": "call-submit",
          "arguments": json.dumps(product_spec()), "status": "completed"}


def _artifact(system, ref):
    return json.loads(system.artifacts.get_text(ref["content_hash"]))


def _expected_request(captured: dict) -> dict:
    # 记录下来的请求与发到提供方的请求一致：调用目标声明了输出上限时它随请求发出
    expected = {"input": captured["input"], "tools": captured["tools"]}
    if captured.get("max_output_tokens") is not None:
        expected["max_output_tokens"] = captured["max_output_tokens"]
    return expected


def _assert_request_audit(system, run_id, captures):
    events = [event for event in system.store.list_events(run_id) if event.type == EventType.CONTEXT_ASSEMBLED]
    attempted = [event for event in system.store.list_events(run_id) if event.type == EventType.MODEL_REQUESTED]
    assert len(events) == len(captures)
    assert len(attempted) == len(captures)
    for event, dispatched, captured in zip(events, attempted, captures):
        persisted = _artifact(system, event.payload["request_ref"])
        assert persisted == _expected_request(captured)
        assert canonical_hash(persisted) == event.context_digest
        assert event.payload["admitted"] is True
        assert dispatched.payload["attempted"] is True
        assert dispatched.context_digest == event.context_digest
        assert dispatched.payload["step_id"] == event.payload["step_id"]
    return events


def test_native_loop_executes_tool_and_persists_exact_inputs_before_each_request(tmp_path):
    live_audits = []
    system = None
    run_id = None
    canary = "UNREQUESTED_WORKSPACE_INSTRUCTION_451899"

    def second_response(handler, request):
        contexts = [event for event in system.store.list_events(run_id) if event.type == EventType.CONTEXT_ASSEMBLED]
        live_audits.append(_artifact(system, contexts[-1].payload["request_ref"]) == _expected_request(request))
        _send(handler, _stream([SUBMIT], response_id="resp-two"))

    with _server([_stream([REASONING, CALL], duplicate=True), second_response]) as (config, captures, *_):
        system = LoopSystem.for_testing(tmp_path / "data", ResponsesAdapter(config))
        try:
            run_id = system.create_run("local tool roundtrip")
            system.workspace(run_id).write_file("proof.txt", "host-read-evidence")
            system.workspace(run_id).write_file("AGENTS.md", canary)
            result = system.activate_once(run_id)
            assert has_new_work(result, "engineering"), result.error
            assert result.token_used == 260
            assert result.cost == 0
            assert live_audits == [True]
            assert len(captures) == 2
            assert canary not in json.dumps(captures)
            replayed = [item for item in captures[1]["input"] if item.get("type") == "reasoning"]
            assert len(replayed) == 1
            assert replayed[0]["encrypted_content"] == REASONING["encrypted_content"]
            last_two = captures[1]["input"][-3:-1]
            assert last_two[0]["type"] == "reasoning" and last_two[1]["type"] == "function_call"
            assert last_two[1]["call_id"] == CALL["call_id"]
            assert "host-read-evidence" in captures[1]["input"][-1]["output"]
            contexts = _assert_request_audit(system, run_id, captures)
            assert [event.payload["step_id"] for event in contexts] == [1, 2]
            events = system.store.list_events(run_id)
            assert len([event for event in events if event.type == EventType.MODEL_MESSAGE]) == 3
            tools = [event for event in events if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "read_file"]
            assert len(tools) == 1
            assert _artifact(system, tools[0].payload["output_ref"]) == "host-read-evidence"
            reports = [event.payload for event in events if event.payload.get("name") == "provider_usage"]
            assert [report["total_tokens"] for report in reports] == [130, 260]
            assert reports[-1]["input_tokens"] == 40
            assert reports[-1]["cache_read_tokens"] == 160
            assert reports[-1]["output_tokens"] == 60
            assert all(report["cost_reported"] is False for report in reports)
            assert [report["step_id"] for report in reports] == [1, 2]
            assert [_artifact(system, report["raw_usage_ref"])["usage"] for report in reports] == [RAW_USAGE, RAW_USAGE]
            assert result.canonical_state() == system.replay(run_id).canonical_state()
        finally:
            system.store.close()


def test_same_provider_call_id_in_different_steps_executes_each_host_call(tmp_path):
    system = None
    run_id = None

    def repeat_call(handler, _body):
        # 同一个 call_id 的两次调用都执行在本会话的检查工作区里（工单 #481）：
        # 产品会话在自己的检查工作区里运行，改写检查工作区才会改变第二次调用的结果。
        # 检查工作区按会话一个（工单 #473），路径的最后一段是会话标识
        session_id = system.orchestrator.sessions.get(run_id, "product").session_id
        product_root = inspection_root(system.workspace_root / run_id, session_id)
        product_root.mkdir(parents=True, exist_ok=True)
        product_root.joinpath("proof.txt").write_text("second-result", encoding="utf-8")
        _send(handler, _stream([CALL], response_id="resp-two"))

    with _server([_stream([CALL]), repeat_call, _stream([SUBMIT], response_id="resp-three")]) as (config, captures, *_):
        system = LoopSystem.for_testing(tmp_path / "data", ResponsesAdapter(config))
        try:
            run_id = system.create_run("distinct executions")
            # 检查工作区从激活开始时的运行快照建立：先写运行工作区，产品会话才读得到第一份内容；
            # 两步之间改写检查工作区里的同一份文件，第二次调用读到的是另一份内容
            system.workspace(run_id).write_file("proof.txt", "first-result")
            result = system.activate_once(run_id)
            assert has_new_work(result, "engineering"), result.error
            tools = [event for event in system.store.list_events(run_id)
                     if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "read_file"]
            assert [_artifact(system, event.payload["output_ref"]) for event in tools] == ["first-result", "second-result"]
            assert [event.payload["step_id"] for event in tools] == [1, 2]
            assert result.token_used == 390
            assert "first-result" in captures[1]["input"][-1]["output"]
            assert "second-result" in captures[2]["input"][-1]["output"]
            _assert_request_audit(system, run_id, captures)
        finally:
            system.store.close()


def test_missing_provider_usage_is_not_estimated_and_does_not_stop_work(tmp_path):
    with _server([_stream([SUBMIT], usage=None)]) as (config, captures, *_):
        system = LoopSystem.for_testing(tmp_path / "data", ResponsesAdapter(config))
        try:
            run_id = system.create_run("provider did not report usage")
            result = system.activate_once(run_id)
            assert has_new_work(result, "engineering"), result.error
            contexts = _assert_request_audit(system, run_id, captures)
            assert result.token_used == 0
            assert contexts[0].payload["token_estimate"] > 0
            reports = [event.payload for event in system.store.list_events(run_id)
                       if event.payload.get("name") == "provider_usage"]
            assert reports[-1]["source"] == "unreported"
        finally:
            system.store.close()


def test_duplicate_call_ids_in_one_response_are_rejected_before_any_tool_starts(tmp_path):
    duplicate = {**CALL, "id": "fc-other", "arguments": '{"path":"second.txt"}'}
    with _server([_stream([CALL, duplicate]), _stream([SUBMIT], response_id="resp-two")]) as (config, captures, *_):
        system = LoopSystem.for_testing(tmp_path / "data", ResponsesAdapter(config))
        try:
            run_id = system.create_run("ambiguous provider call identity")
            system.workspace(run_id).write_file("proof.txt", "first output")
            system.workspace(run_id).write_file("second.txt", "second output")
            result = system.activate_once(run_id)
            assert result.status == "failed" and result.stop_reason == "provider_error"
            assert len(captures) == 1
            assert not any(event.type == EventType.TOOL_STARTED for event in system.store.list_events(run_id))
        finally:
            system.store.close()
