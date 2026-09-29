from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler

import pytest

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.definitions import DEFINITIONS
from harness.engine import tool_call_required_text
from harness.models import ArtifactRef, EventType, json_dumps
from harness.proposals import product_spec
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.smoke import isolation_fields
from harness.tests.helpers import department_history, list_files_turn
from harness.tests.test_event_sequence import HTTP_REPLIES

# 连续没有调用工具的回复最多追加说明的次数，取自定义
LIMIT = DEFINITIONS.limits.tool_call_required_limit
from harness.tests.protocol_helpers import (
    ScriptedProvider,
    bound_adapter,
    chat_responder,
    complete,
    facade_with,
    messages_responder,
    provider_system,
    responses_responder,
    send_reply,
    serve,
)
from harness.tests.helpers import FAST_RETRIES

REPLY = "我先整理一下需求，稍后提交。"


def _text_then_spec(tmp_path):
    adapter = FakeAdapter([FakeTurn(transcript=REPLY), product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo")
    return system, adapter, run_id


def _events(system, run_id, event_type):
    return [event for event in system.store.list_events(run_id) if event.type == event_type]


def _assert_replayable(system, run_id, result):
    assert result.canonical_state() == system.replay(run_id).canonical_state()
    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]
    assert audit["status"] == "verified", audit["notes"]


def test_text_only_reply_appends_user_message_to_history_and_events(tmp_path):
    system, adapter, run_id = _text_then_spec(tmp_path)
    result = system.activate_once(run_id)

    assert result.phase == "ENGINEERING" and result.product_spec is not None
    first, second = adapter.invocations
    appended = {"role": "user", "content": tool_call_required_text(1)}
    assert second.input_items[:len(first.input_items)] == first.input_items
    assert REPLY in json_dumps(second.input_items[-2]) and second.input_items[-2]["role"] == "assistant"
    assert second.input_items[-1] == appended

    [event] = _events(system, run_id, EventType.TOOL_CALL_REQUIRED)
    assert event.role == "product"
    assert event.payload["activation_id"] == first.activation_id and event.payload["step_id"] == first.step_id
    assert event.payload["count"] == 1 and event.payload["limit"] == LIMIT
    stored = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**event.payload["input_ref"])))
    assert stored == appended

    history = department_history(system, run_id, "product")
    position = next(index for index, record in enumerate(history) if record["event_id"] == event.event_id)
    assert history[position]["item"] == appended
    assert history[position - 1]["type"] == EventType.MODEL_MESSAGE and REPLY in json_dumps(history[position - 1]["item"])
    _assert_replayable(system, run_id, result)


def test_empty_reply_is_followed_by_the_same_user_message(tmp_path):
    adapter = FakeAdapter([ModelResponse(), product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo")
    result = system.activate_once(run_id)

    assert result.phase == "ENGINEERING"
    assert adapter.invocations[1].input_items[-1] == {"role": "user", "content": tool_call_required_text(1)}
    _assert_replayable(system, run_id, result)


def test_consecutive_text_only_replies_pause_the_run_and_keep_every_reply(tmp_path):
    replies = [f"第 {index} 次只回复文字" for index in range(1, LIMIT + 2)]
    adapter = FakeAdapter([FakeTurn(transcript=text) for text in replies])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo")
    result = system.activate_once(run_id)

    assert result.phase == "PAUSED" and result.stop_reason == "no_tool_call"
    assert result.product_spec is None
    assert len(adapter.invocations) == LIMIT + 1
    required = _events(system, run_id, EventType.TOOL_CALL_REQUIRED)
    assert [event.payload["count"] for event in required] == list(range(1, LIMIT + 1))
    for request in adapter.invocations[1:]:
        assert request.input_items[-1]["role"] == "user"
    # 每一次只含文字的回复都保留为事件，并留在部门历史中
    messages = [json_dumps(json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**event.payload["message_ref"]))))
                for event in _events(system, run_id, EventType.MODEL_MESSAGE)]
    history = json_dumps(department_history(system, run_id, "product"))
    for text in replies:
        assert any(text in message for message in messages)
        assert text in history
    [paused] = _events(system, run_id, EventType.RUN_PAUSED)
    assert paused.payload["stop_reason"] == "no_tool_call" and paused.payload["human_action"]
    _assert_replayable(system, run_id, result)


def test_tool_call_resets_the_count_of_replies_without_tool_calls(tmp_path):
    limit = LIMIT
    script = [*[FakeTurn(transcript="只回复文字") for _ in range(limit)], list_files_turn,
              FakeTurn(transcript="再次只回复文字"), product_spec()]
    adapter = FakeAdapter(script)
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo")
    result = system.activate_once(run_id)

    assert result.phase == "ENGINEERING" and result.product_spec is not None
    counts = [event.payload["count"] for event in _events(system, run_id, EventType.TOOL_CALL_REQUIRED)]
    assert counts == [*range(1, limit + 1), 1]
    _assert_replayable(system, run_id, result)


@pytest.mark.parametrize("protocol,responder", [
    ("responses", responses_responder),
    ("chat_completions", chat_responder),
    ("messages", messages_responder),
])
def test_request_after_text_only_reply_ends_with_user_message_on_the_wire(tmp_path, protocol, responder):
    system, adapter, run_id = _text_then_spec(tmp_path)
    system.activate_once(run_id)
    # 运行系统产生的第二次请求，经真实 Provider 模块按协议编码后发到本机捕获服务；
    # 测试装配没有冻结模型上限，这里补上 Messages 协议必需的 max_tokens
    call = adapter.invocations[1].model_copy(update={"max_output_tokens": 1024})
    server, capture, base = serve(responder)
    try:
        facade = facade_with(base + "/v1", protocol=protocol)
        complete(bound_adapter(facade), call)
    finally:
        server.shutdown()
        server.server_close()
    body = capture.requests[0]
    wire = body["input"] if protocol == "responses" else body["messages"]
    assert wire[-1]["role"] == "user", wire[-1]
    assert REPLY in json.dumps(wire[-2], ensure_ascii=False) and wire[-2]["role"] == "assistant"


def _text_only_activation(tmp_path, replies=LIMIT):
    # 连续只回复文字直到计数达到限额，最后一次以提交提案结束
    adapter = FakeAdapter([*[FakeTurn(transcript="只回复文字") for _ in range(replies)], product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    return system, adapter, system.create_run("build echo")


def test_the_request_after_the_last_host_hint_requires_a_tool_call(tmp_path):
    # 连续三次只回复文字以后，第四次请求要求调用工具（#102）；之前的请求都是自动，请求事件记录这一项
    system, adapter, run_id = _text_only_activation(tmp_path)
    result = system.activate_once(run_id)
    assert result.phase == "ENGINEERING" and result.product_spec is not None
    choices = [call.tool_choice for call in adapter.invocations]
    assert choices == ["auto"] * LIMIT + ["required"]
    assert [event.payload["tool_choice"] for event in _events(system, run_id, EventType.MODEL_REQUESTED)] == choices
    _assert_replayable(system, run_id, result)


def test_a_tool_call_in_the_required_request_continues_the_run_and_resets_the_count(tmp_path):
    # 要求调用工具的请求里调用了工具（#102）：运行继续，计数归零，之后的请求回到自动
    script = [*[FakeTurn(transcript="只回复文字") for _ in range(LIMIT)], list_files_turn, product_spec()]
    adapter = FakeAdapter(script)
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo")
    result = system.activate_once(run_id)
    assert result.phase == "ENGINEERING" and result.product_spec is not None
    assert adapter.invocations[LIMIT].tool_choice == "required"
    assert adapter.invocations[LIMIT + 1].tool_choice == "auto"


@pytest.mark.parametrize("protocol,responder,expected", [
    ("responses", responses_responder, "required"),
    ("chat_completions", chat_responder, "required"),
    ("messages", messages_responder, {"type": "any"}),
])
def test_required_tool_choice_is_encoded_per_protocol(tmp_path, protocol, responder, expected):
    # 三种协议的请求体中 tool_choice 的取值（#102）：由测试内启动的真实 HTTP 服务记录；自动的请求不带这一项
    system, adapter, run_id = _text_only_activation(tmp_path)
    system.activate_once(run_id)
    calls = [adapter.invocations[LIMIT], adapter.invocations[0]]
    server, capture, base = serve(responder)
    try:
        facade = facade_with(base + "/v1", protocol=protocol)
        for call in calls:
            complete(bound_adapter(facade), call.model_copy(update={"max_output_tokens": 1024}))
    finally:
        server.shutdown()
        server.server_close()
    assert capture.requests[0]["tool_choice"] == expected
    assert "tool_choice" not in capture.requests[1]


def _text_only_stream(protocol: str):
    # 只回复文字的流式回复：与提交提案的回复同形，只是没有工具调用
    def reply(_provider: ScriptedProvider, handler: BaseHTTPRequestHandler) -> None:
        send_reply(handler, 200, "text/event-stream", HTTP_REPLIES[protocol](1, []))

    return reply


@pytest.mark.parametrize("protocol", ["responses", "chat_completions", "messages"])
def test_a_model_declared_without_a_required_tool_call_sends_auto_and_pauses(data_dir, protocol):
    # 模型访问定义声明不接受要求调用工具时不发送（#102）：请求仍是自动，连续第 LIMIT+1 次以 no_tool_call 暂停。
    # 经真实 Provider 模块与本机 HTTP 服务，三种协议都不带 tool_choice
    provider = ScriptedProvider([_text_only_stream(protocol) for _ in range(LIMIT + 1)])
    try:
        system, run_id = provider_system(data_dir, provider.base, protocol,
                                         accepts_required_tool_call=False, step_limits=FAST_RETRIES)
        try:
            result = system.activate_once(run_id)
        finally:
            system.close()
    finally:
        provider.close()
    assert result.phase == "PAUSED" and result.stop_reason == "no_tool_call"
    assert len(provider.requests) == LIMIT + 1
    assert all("tool_choice" not in (body or {}) for body in provider.requests)
