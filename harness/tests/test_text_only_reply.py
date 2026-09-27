from __future__ import annotations

import json

import pytest

from harness.adapters.facade_adapter import FacadeAdapter
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.definitions import DEFINITIONS
from harness.engine import tool_call_required_text
from harness.models import ArtifactRef, EventType, json_dumps
from harness.proposals import product_spec
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.smoke import _model_input_audit
from harness.tests.helpers import department_history, list_files_turn

# 连续没有调用工具的回复最多追加说明的次数，取自定义
LIMIT = DEFINITIONS.limits.tool_call_required_limit
from harness.tests.protocol_helpers import (
    bound_target,
    chat_responder,
    complete,
    facade_with,
    messages_responder,
    responses_responder,
    serve,
)

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
    audit = _model_input_audit(system.store, system.artifacts, run_id)
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
        complete(FacadeAdapter(facade, bound_target(facade)), call)
    finally:
        server.shutdown()
        server.server_close()
    body = capture.requests[0]
    wire = body["input"] if protocol == "responses" else body["messages"]
    assert wire[-1]["role"] == "user", wire[-1]
    assert REPLY in json.dumps(wire[-2], ensure_ascii=False) and wire[-2]["role"] == "assistant"
