from __future__ import annotations

import json

from harness.collaboration import has_new_work
from harness.providers.call import ModelResponse
from harness.adapters.fake import FakeAdapter
from harness.models import EventType, json_dumps
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.tests.helpers import FAST_RETRIES, department_history


# 故障现场截断参数原文：search 工具流式调用在 path 值之前中断
TRUNCATED_SEARCH_ARGUMENTS = '{"pattern": "def add", "path": '


def _recorded_call_arguments(records: list[dict]) -> list:
    return [
        record["item"]["arguments"] for record in records
        if isinstance(record.get("item"), dict) and record["item"].get("type") == "function_call"
    ]


def test_truncated_arguments_are_sanitized_before_history_replay(tmp_path):
    malformed = ModelResponse(output=[{
        "id": "call-truncated", "call_id": "call-truncated", "type": "function_call",
        "name": "search", "arguments": TRUNCATED_SEARCH_ARGUMENTS,
    }])
    adapter = FakeAdapter([malformed, product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    run_id = system.create_run("echo")

    result = system.activate_once(run_id)

    # 可恢复的参数错误不能变成硬失败，运行必须继续推进
    assert has_new_work(result, "engineering")
    assert len(adapter.invocations) == 2
    # 记入历史与下次请求回放的参数恒为有效 JSON 对象
    history = department_history(system, run_id, "product")
    assert history
    for raw in _recorded_call_arguments(history):
        assert isinstance(json.loads(raw), dict)
    replayed = [
        item["arguments"] for item in adapter.invocations[1].input_items
        if isinstance(item, dict) and item.get("type") == "function_call"
    ]
    assert replayed
    for raw in replayed:
        assert isinstance(json.loads(raw), dict)
    # 具体参数错误仍经工具结果回传给模型，且从未启动工具
    assert "invalid tool arguments" in json_dumps(adapter.invocations[1].input_items)
    events = system.store.list_events(run_id)
    assert not any(item.type == EventType.TOOL_STARTED and item.payload.get("id") == "call-truncated"
                   for item in events)
    assert any(item.type == EventType.TOOL_CALLED and item.payload.get("id") == "call-truncated"
               and item.payload.get("ok") is False for item in events)


def test_valid_tool_call_still_executes_with_original_arguments(tmp_path):
    arguments = json_dumps({"pattern": "def add"})
    valid = ModelResponse(output=[{
        "id": "call-search", "call_id": "call-search", "type": "function_call",
        "name": "search", "arguments": arguments,
    }])
    adapter = FakeAdapter([valid, product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    run_id = system.create_run("echo")

    result = system.activate_once(run_id)

    assert has_new_work(result, "engineering")
    events = system.store.list_events(run_id)
    called = next(item for item in events
                  if item.type == EventType.TOOL_CALLED and item.payload.get("id") == "call-search")
    assert called.payload.get("ok") is True
    replayed = [
        item["arguments"] for item in adapter.invocations[1].input_items
        if isinstance(item, dict) and item.get("type") == "function_call"
    ]
    assert [json.loads(raw) for raw in replayed] == [{"pattern": "def add"}]


