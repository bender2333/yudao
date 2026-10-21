# 事件序列按会话比较的探针（#469 验收 3）：跨会话交错通过，会话内 swap、交接边反向、
# 工具结果提前到回答之前失败并写明差异。比较器见 harness/tests/event_sequence.py 末尾的 compare_documents。
# 前三个探针直接读基准 JSON，在内存里变换事件数组的顺序后调 compare_documents：不重写基准文件，
# 不重新走事件规整，shared 与 artifacts 的标签编号保持稳定，只断言分组比较与因果边的差异点。
# 第四个探针用最小合成文档覆盖询问链（基准里询问链与同组事件交织，单步移动必然先碰到分组比较）；
# 第五、六个探针覆盖投影比较（#541）：只改投影字段、事件与投影同时改两种情况。

import copy
import json
from pathlib import Path

import pytest

from harness.tests.event_sequence import compare_documents

BASELINE_DIR = Path(__file__).resolve().parent / "event_sequences"


def _load(name):
    return json.loads((BASELINE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _swap(events, first, second):
    events[first], events[second] = events[second], events[first]


def test_cross_session_interleave_still_passes():
    # 调换两个会话之间事件交错的先后（会话内部顺序与因果关系不变）：产品组收尾的
    # activation_finished（<evt#16>）与工程组开头的 department_activated（<evt#17>）在数组里
    # 相邻且分属两组，调换后两组各自的内部顺序不变，transition → activation 边的方向也不变，
    # 应通过；工程组收尾（<evt#36>）与质检组开头（<evt#37>）同样调换一对（计划删除后编号前移）
    expected = _load("handoff_release")
    actual = copy.deepcopy(expected)
    events = actual["events"]
    first = next(i for i, e in enumerate(events) if e["event"] == "<evt#16>")
    second = next(i for i, e in enumerate(events) if e["event"] == "<evt#17>")
    assert second == first + 1
    _swap(events, first, second)
    third = next(i for i, e in enumerate(events) if e["event"] == "<evt#36>")
    fourth = next(i for i, e in enumerate(events) if e["event"] == "<evt#37>")
    assert fourth == third + 1
    _swap(events, third, fourth)
    compare_documents("handoff_release", expected, actual)


def test_intra_session_swap_fails_with_diff():
    # 调换工程会话内部两条相邻的工具事件（<evt#26> tool_started 与 <evt#27> tool_called，计划删除后编号前移）：
    # 会话内顺序变了，分组比较应失败并点名差异
    expected = _load("handoff_release")
    actual = copy.deepcopy(expected)
    events = actual["events"]
    first = next(i for i, e in enumerate(events) if e["event"] == "<evt#26>")
    second = next(i for i, e in enumerate(events) if e["event"] == "<evt#27>")
    assert events[first]["session_id"] == events[second]["session_id"] == "<ses_eng#1>"
    assert second == first + 1
    _swap(events, first, second)
    with pytest.raises(AssertionError) as raised:
        compare_documents("handoff_release", expected, actual)
    message = str(raised.value)
    assert "session <ses_eng#1>" in message, message
    assert "differs" in message, message


def test_handoff_edge_reversed_fails_with_diff():
    # 让交接的提交落在下一个部门开始之后：把工程组的 department_activated（<evt#17>）
    # 搬到产品组的 transition（<evt#15>）之前。搬家跨过的事件里没有工程组的事件，
    # 每个会话内部的相对顺序都不变，分组比较通过；但提交 → 下一个部门开始的因果边反向，
    # 应失败并点名因果边
    expected = _load("handoff_release")
    actual = copy.deepcopy(expected)
    events = actual["events"]
    transition = next(i for i, e in enumerate(events) if e["event"] == "<evt#15>")
    activation = next(i for i, e in enumerate(events) if e["event"] == "<evt#17>")
    assert events[transition]["type"] == "transition"
    assert events[activation]["type"] == "department_activated"
    assert transition < activation
    assert all(e.get("session_id") != "<ses_eng#1>" for e in events[transition:activation])
    item = events.pop(activation)
    events.insert(transition, item)
    with pytest.raises(AssertionError) as raised:
        compare_documents("handoff_release", expected, actual)
    message = str(raised.value)
    assert "causal edges differ" in message, message


def _ask_documents(moved=False):
    # 最小的询问链文档：工程询问 → 产品分支的第一条事件 → 产品回答 → 工程工具结果
    asked = {"event": "e1", "type": "ask_started", "session_id": "eng",
             "payload": {"branch_session_id": "pro-branch"}}
    start = {"event": "e2", "type": "department_activated", "session_id": "pro-branch",
             "payload": {}}
    answer = {"event": "e3", "type": "ask_answered", "session_id": "pro-branch",
              "payload": {"status": "answered"}}
    tool = {"event": "e4", "type": "tool_called", "session_id": "eng",
            "payload": {"name": "ask"}}
    events = [asked, start, answer, tool]
    if moved:
        events = [asked, start, tool, answer]
    return {"scenario": "ask", "covers": "ask", "projection": {},
            "events": [dict(e) for e in events]}


def test_tool_result_before_response_fails_with_diff():
    # 让工具结果出现在对应的回答之前：工具事件与回答分属两组，移动后每个会话内部的
    # 相对顺序都不变，分组比较通过；但回答 → 工具结果的因果边消失，应失败并点名因果边
    expected = _ask_documents()
    compare_documents("ask", expected, copy.deepcopy(expected))
    with pytest.raises(AssertionError) as raised:
        compare_documents("ask", expected, _ask_documents(moved=True))
    message = str(raised.value)
    assert "causal edges differ" in message, message


def test_projection_difference_fails_with_fields_line():
    # 只改投影的一个字段、事件不动（#541 步骤 3 第 1 项，把放行结果改为未完成）：投影是事件
    # 推出来的结果，事件一致时失败应落在投影上，并在 `fields:` 一行写明是哪个键
    expected = _load("handoff_release")
    actual = copy.deepcopy(expected)
    assert actual["projection"]["outcome"] == "done"
    actual["projection"]["outcome"] = "rework"
    with pytest.raises(AssertionError) as raised:
        compare_documents("handoff_release", expected, actual)
    message = str(raised.value)
    assert "handoff_release" in message, message
    assert "projection differs" in message, message
    assert "fields: outcome" in message, message


def test_event_difference_reported_before_projection():
    # 同时改质检 qa_submitted 事件的 payload.verdict 与投影的 outcome（#541 步骤 3 第 2 项）：
    # 两边都不一致时，信息先报事件，写明是哪个会话、会话内第几个事件与哪个字段，不报投影
    expected = _load("handoff_release")
    actual = copy.deepcopy(expected)
    index = next(i for i, e in enumerate(actual["events"]) if e["type"] == "qa_submitted")
    actual["events"][index]["payload"]["verdict"] = "rework_product"
    actual["projection"]["outcome"] = "rework"
    with pytest.raises(AssertionError) as raised:
        compare_documents("handoff_release", expected, actual)
    message = str(raised.value)
    assert "handoff_release" in message, message
    assert "session <ses_qua#1>" in message, message
    assert "event #" in message, message
    assert "payload.verdict" in message, message
    assert "projection differs" not in message, message


def test_payload_field_difference_fails_with_fields_line():
    # 只改一条事件的一个载荷字段（质检放行改为退回）：同一会话内同一位置的事件载荷不同，
    # 分组比较应失败，并在 `fields:` 一行点名是哪个字段（#532 步骤 5 第 3 条）
    expected = _load("handoff_release")
    actual = copy.deepcopy(expected)
    events = actual["events"]
    index = next(i for i, e in enumerate(events) if e["type"] == "qa_submitted")
    assert events[index]["payload"]["verdict"] == "release"
    events[index]["payload"]["verdict"] = "rework_product"
    with pytest.raises(AssertionError) as raised:
        compare_documents("handoff_release", expected, actual)
    message = str(raised.value)
    assert "handoff_release" in message, message
    assert "session <ses_qua#1>" in message, message
    assert "event #" in message, message
    assert "payload.verdict" in message, message
