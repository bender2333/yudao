"""The native loop owns each request, tool execution and durable model evidence."""

import json

from harness.tests.helpers import FAST_RETRIES
from harness.models import EventType, canonical_hash
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.tests.protocol_helpers import (
    STUB_CALL as CALL,
    STUB_REASONING as REASONING,
    STUB_TEXT as TEXT,
    STUB_USAGE as RAW_USAGE,
    ResponsesAdapter,
    stub_event as _event,
    stub_response as _response,
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
            assert result.phase == "ENGINEERING", result.error
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
        system.workspace(run_id).write_file("proof.txt", "second-result")
        _send(handler, _stream([CALL], response_id="resp-two"))

    with _server([_stream([CALL]), repeat_call, _stream([SUBMIT], response_id="resp-three")]) as (config, captures, *_):
        system = LoopSystem.for_testing(tmp_path / "data", ResponsesAdapter(config))
        try:
            run_id = system.create_run("distinct executions")
            system.workspace(run_id).write_file("proof.txt", "first-result")
            result = system.activate_once(run_id)
            assert result.phase == "ENGINEERING", result.error
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


def test_later_stream_timeout_preserves_prior_usage_tool_and_all_partial_messages(tmp_path):
    def partial_then_hold(handler, _body):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.end_headers()
        handler.wfile.write(_stream([TEXT], terminal=False))
        handler.wfile.flush()
        # 部分消息送出后不再发送任何字节，连接保持到客户端按请求时限自行关闭
        handler.rfile.read(1)

    # 请求时限沿用捕获服务的 5 秒；成功回复立即发送，三次部分流都由服务端保持到客户端超时
    with _server([_stream([CALL]), partial_then_hold, partial_then_hold, partial_then_hold]) as (config, captures, *_):
        system = LoopSystem.for_testing(tmp_path / "data", ResponsesAdapter(config), step_limits=FAST_RETRIES)
        try:
            run_id = system.create_run("later timeout")
            system.workspace(run_id).write_file("proof.txt", "survives-timeout")
            result = system.activate_once(run_id)
            assert result.phase == "FAILED" and result.stop_reason == "provider_timeout"
            assert "timed out" in result.error
            assert result.token_used >= 130
            events = system.store.list_events(run_id)
            reports = [event.payload for event in events if event.payload.get("name") == "provider_usage"]
            assert reports[0]["total_tokens"] == RAW_USAGE["total_tokens"]
            assert len([event for event in events if event.type == EventType.MODEL_MESSAGE]) == 4
            assert len([event for event in events if event.type == EventType.MODEL_ATTEMPT_FAILED]) == 3
            assert len(captures) == 4
            assert not any(event.type == EventType.SPEC_ACCEPTED for event in events)
            tool = next(event for event in events if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "read_file")
            assert _artifact(system, tool.payload["output_ref"]) == "survives-timeout"
            _assert_request_audit(system, run_id, captures)
            assert result.canonical_state() == system.replay(run_id).canonical_state()
        finally:
            system.store.close()


def test_failed_first_model_request_still_has_durable_exact_input(tmp_path):
    def fail(handler, _body):
        _send(handler, b'{"error":{"code":"server_error","message":"local failure"}}',
              status=500, content_type="application/json")

    with _server([fail, fail, fail]) as (config, captures, *_):
        system = LoopSystem.for_testing(tmp_path / "data", ResponsesAdapter(config), step_limits=FAST_RETRIES)
        try:
            run_id = system.create_run("failed provider request")
            result = system.activate_once(run_id)
            assert result.phase == "FAILED" and result.stop_reason == "provider_error"
            assert len(captures) == 3
            events = system.store.list_events(run_id)
            assert len([event for event in events if event.type == EventType.MODEL_ATTEMPT_FAILED]) == 3
            _assert_request_audit(system, run_id, captures)
            assert result.canonical_state() == system.replay(run_id).canonical_state()
        finally:
            system.store.close()


def test_http_500_retry_then_success_reaches_native_loop(tmp_path):
    def fail(handler, _body):
        _send(handler, b'{"error":{"code":"server_error","message":"transient"}}',
              status=500, content_type="application/json")

    with _server([fail, _stream([SUBMIT], response_id="retry-success")]) as (config, captures, *_):
        system = LoopSystem.for_testing(tmp_path / "data", ResponsesAdapter(config), step_limits=FAST_RETRIES)
        try:
            run_id = system.create_run("HTTP retry to success")
            result = system.activate_once(run_id)
            assert result.phase == "ENGINEERING", result.error
            assert len(captures) == 2
            events = system.store.list_events(run_id)
            assert len([event for event in events if event.type == EventType.MODEL_ATTEMPT_FAILED]) == 1
            assert len([event for event in events if event.type == EventType.MODEL_RETRY_SCHEDULED]) == 1
            assert result.canonical_state() == system.replay(run_id).canonical_state()
        finally:
            system.store.close()


def test_partial_http_stream_is_audit_only_and_absent_from_retry_input(tmp_path):
    partial = {**CALL, "id": "partial-call", "call_id": "partial-call"}

    with _server([_stream([partial], terminal=False), _stream([SUBMIT], response_id="partial-success")]) as (config, captures, *_):
        system = LoopSystem.for_testing(tmp_path / "data", ResponsesAdapter(config), step_limits=FAST_RETRIES)
        try:
            run_id = system.create_run("partial stream retry")
            result = system.activate_once(run_id)
            assert result.phase == "ENGINEERING", result.error
            assert len(captures) == 2
            assert "partial-call" not in json.dumps(captures[1]["input"])
            events = system.store.list_events(run_id)
            assert any(event.type == EventType.MODEL_MESSAGE and event.payload.get("response_id") == "partial-call" for event in events)
            assert not any(event.type == EventType.TOOL_STARTED and event.payload.get("id") == "partial-call" for event in events)
            assert result.canonical_state() == system.replay(run_id).canonical_state()
        finally:
            system.store.close()


def test_missing_provider_usage_is_not_estimated_and_does_not_stop_work(tmp_path):
    with _server([_stream([SUBMIT], usage=None)]) as (config, captures, *_):
        system = LoopSystem.for_testing(tmp_path / "data", ResponsesAdapter(config))
        try:
            run_id = system.create_run("provider did not report usage")
            result = system.activate_once(run_id)
            assert result.phase == "ENGINEERING", result.error
            contexts = _assert_request_audit(system, run_id, captures)
            assert result.token_used == 0
            assert contexts[0].payload["token_estimate"] > 0
            reports = [event.payload for event in system.store.list_events(run_id)
                       if event.payload.get("name") == "provider_usage"]
            assert reports[-1]["source"] == "unreported"
        finally:
            system.store.close()


def test_host_failure_to_record_a_stream_event_names_the_actual_error_type(tmp_path, monkeypatch):
    # 主机记录流事件失败：流事件累计超过内存上限时转存临时文件，临时目录不存在，转存失败；
    # 尝试失败的记录写明实际的异常类型
    created = _response([TEXT], response_id="resp-large")
    large_delta = _event("response.output_text.delta", item_id="msg-one", output_index=0, content_index=0,
                         delta="x" * (1024 * 1024 + 1), logprobs=[], sequence_number=1)
    body = (_event("response.created", response={**created, "status": "in_progress", "output": [], "usage": None},
                   sequence_number=0)
            + large_delta
            + _event("response.completed", response=created, sequence_number=2))
    with _server([body]) as (config, captures, *_):
        system = LoopSystem.for_testing(tmp_path / "data", ResponsesAdapter(config))
        try:
            run_id = system.create_run("stream capture failure")
            monkeypatch.setattr("tempfile.tempdir", str(tmp_path / "missing-temp"))
            result = system.activate_once(run_id)
            assert result.phase == "FAILED" and result.stop_reason == "provider_error"
            assert len(captures) == 1
            failed = [event for event in system.store.list_events(run_id) if event.type == EventType.MODEL_ATTEMPT_FAILED]
            assert [event.error for event in failed] == ["model adapter failed: FileNotFoundError"]
            assert failed[0].payload["diagnostics"] == {"error_type": "adapter_failure"}
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
            assert result.phase == "FAILED" and result.stop_reason == "provider_error"
            assert len(captures) == 1
            assert not any(event.type == EventType.TOOL_STARTED for event in system.store.list_events(run_id))
        finally:
            system.store.close()
