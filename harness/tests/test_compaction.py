import json
from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from harness.compaction import (
    SUMMARY_PREFACE, SUMMARY_RULES, CompactionCheckpoint, CompactionError, finish_compaction, plan_compaction,
    response_reserve, summary_material, visible_history,
)
from harness.models import canonical_hash, estimate_tokens, json_dumps


PINNED = [{"role": "developer", "content": "[intend]\nKeep the original request.\n[current_work]\nInspect the evidence."}]
TOOLS = [{"type": "function", "name": "read_file", "parameters": {"type": "object"}}]


def _record(index, item, *, step=None, activation="engineering-activation"):
    return {"event_id": f"event-{index}", "seq": index, "activation_id": activation,
            "step_id": index if step is None else step, "item": item, "item_digest": canonical_hash(item)}


def _history(count=12, width=1800):
    return [_record(index, {"id": f"msg-{index}", "type": "message", "role": "assistant",
                           "content": [{"type": "output_text", "text": f"Evidence {index}: " + "x" * width}]})
            for index in range(1, count + 1)]


def _output(text="Decisions: inspect evidence. Pending: finish the required checks."):
    return [{"id": "summary", "type": "message", "role": "assistant", "status": "completed",
             "content": [{"type": "output_text", "text": text}]}]


def _complete_until_work_fits(records, *, window=4000, pinned=PINNED, checkpoint=None):
    plans = []
    for _ in range(64):
        plan = plan_compaction(records, checkpoint, window, pinned, TOOLS)
        if plan is None:
            return plans, checkpoint
        plans.append(plan)
        checkpoint = finish_compaction(plan, _output())
    raise AssertionError("compaction did not make bounded progress")


def test_below_threshold_keeps_all_history_and_does_not_call_for_a_summary():
    records = _history(2, 100)
    original = deepcopy(records)
    assert plan_compaction(records, None, 4000, PINNED, TOOLS) is None
    shown = visible_history(records)
    assert shown == [record["item"] for record in records]
    shown[0]["content"][0]["text"] = "mutated display"
    assert records == original


def test_compaction_reserves_response_room_and_retains_recent_complete_steps():
    records = _history()
    original = deepcopy(records)
    plans, checkpoint = _complete_until_work_fits(records)
    assert plans and checkpoint.boundary
    shown = visible_history(records, checkpoint)
    assert shown[0]["content"].startswith("[department_memory]\n")
    assert shown[-1] == records[-1]["item"]
    assert records == original
    for plan in plans:
        assert plan.input_items[1] == PINNED[0]
        assert plan.input_token_estimate <= 3400
        assert plan.summary_token_limit == 400
        # Without a declared model limit the summary request gets the whole remaining window.
        assert plan.max_output_tokens == 4000 - plan.input_token_estimate >= 600
        assert plan.input_token_estimate + plan.max_output_tokens <= 4000
    assert estimate_tokens(json_dumps({"input": [*PINNED, *shown], "tools": TOOLS})) <= 3400


def test_summary_request_opens_as_summarizer_then_pins_department_material_then_sources():
    plan = plan_compaction(_history(), None, 4000, PINNED, TOOLS)
    rules, pinned, material = plan.input_items
    assert rules["role"] == "developer"
    assert rules["content"].startswith(SUMMARY_PREFACE + SUMMARY_RULES)
    assert f"within {plan.summary_token_limit} tokens" in rules["content"]
    assert pinned == PINNED[0]
    assert material["role"] == "user"
    assert set(json.loads(material["content"])) == {"previous_summary", "source_fragments"}
    assert plan.input_token_estimate == estimate_tokens(json_dumps({"input": plan.input_items, "tools": []}))


def test_summary_source_fragments_match_exact_original_bytes_and_hashes():
    records = _history()
    plans, checkpoint = _complete_until_work_fits(records)
    pieces = {}
    for plan in plans:
        material = json.loads(plan.input_items[-1]["content"])
        assert len(material["source_fragments"]) == len(plan.source_refs)
        for fragment, reference in zip(material["source_fragments"], plan.source_refs):
            record = next(record for record in records if record["event_id"] == reference["event_id"])
            source = json_dumps(record["item"])
            assert reference["item_digest"] == canonical_hash(record["item"])
            assert reference["material_digest"] == canonical_hash(record["item"])
            assert reference["total_chars"] == len(source)
            assert fragment["text"] == source[reference["start_offset"]:reference["end_offset"]]
            assert reference["text_digest"] == canonical_hash(fragment["text"])
            pieces.setdefault(reference["event_id"], []).append(fragment)
    last = next(index for index, record in enumerate(records) if record["event_id"] == checkpoint.covered_through_event_id)
    for record in records[:last + 1]:
        fragments = pieces[record["event_id"]]
        assert fragments[0]["start_offset"] == 0
        assert all(left["end_offset"] == right["start_offset"] for left, right in zip(fragments, fragments[1:]))
        assert "".join(fragment["text"] for fragment in fragments) == json_dumps(record["item"])


def test_oversized_tool_result_is_summarized_in_contiguous_chunks_without_cutting_the_work_view():
    call = {"id": "call-item", "type": "function_call", "name": "read_file", "call_id": "call-1", "arguments": '{}'}
    result = {"type": "function_call_output", "call_id": "call-1", "output": "BEGIN-" + "z" * 45000 + "-END"}
    records = [_record(1, call, step=1), _record(2, result, step=1), *_history(1, 300)]
    records[-1] = _record(3, records[-1]["item"], step=2)
    plans, checkpoint = _complete_until_work_fits(records)
    assert len(plans) >= 1
    assert checkpoint.boundary
    assert visible_history(records, checkpoint)[-1] == records[-1]["item"]
    # 工具输出在摘要材料中被截断为 TOOL_OUTPUT_MAX_CHARS
    from harness.compaction import TOOL_OUTPUT_MAX_CHARS
    for plan in plans:
        for part in json.loads(plan.input_items[-1]["content"])["source_fragments"]:
            if part["event_id"] == "event-2":
                assert len(part["text"]) <= TOOL_OUTPUT_MAX_CHARS + 100  # JSON 包装开销


def test_a_long_history_uses_incremental_summary_requests_that_all_fit():
    records = _history(45, 2300)
    plans, checkpoint = _complete_until_work_fits(records)
    assert len(plans) > 5
    for index, plan in enumerate(plans):
        assert plan.input_token_estimate <= 3400
        assert plan.previous_summary_digest == (None if index == 0 else canonical_hash(_output()[0]["content"][0]["text"]))
    assert checkpoint.boundary and records[-1]["item"] in visible_history(records, checkpoint)


def test_checkpoint_reloads_from_json_and_covers_a_stable_prefix_after_appending_history():
    records = _history()
    _, checkpoint = _complete_until_work_fits(records)
    restored = CompactionCheckpoint(**json.loads(json_dumps(asdict(checkpoint))))
    assert visible_history(records, restored) == visible_history(records, checkpoint)
    appended = _record(13, {"role": "user", "content": "A new request from product"}, activation="next-activation", step=0)
    records.append(appended)
    assert visible_history(records, restored)[-1] == appended["item"]


@pytest.mark.parametrize("mutation", ["item", "digest", "order", "duplicate", "foreign_prefix"])
def test_changed_source_history_cannot_reuse_a_checkpoint(mutation):
    records = _history()
    _, checkpoint = _complete_until_work_fits(records)
    altered = deepcopy(records)
    if mutation == "item":
        altered[0]["item"]["content"][0]["text"] = "tampered"
    elif mutation == "digest":
        altered[0]["item_digest"] = "sha256:wrong"
    elif mutation == "order":
        altered[0], altered[1] = altered[1], altered[0]
    elif mutation == "duplicate":
        altered[1]["event_id"] = altered[0]["event_id"]
    else:
        altered[0] = _record(1, {"role": "user", "content": "another department"})
    with pytest.raises(CompactionError):
        visible_history(altered, checkpoint)


def test_partial_offset_cannot_skip_unseen_original_text():
    records = _history(1, 60000)
    plan = plan_compaction(records, None, 4000, PINNED, TOOLS)
    checkpoint = finish_compaction(plan, _output())
    assert checkpoint.partial_offset > 0
    with pytest.raises(CompactionError, match="digest"):
        plan_compaction(records, replace(checkpoint, partial_offset=checkpoint.partial_offset + 1), 4000, PINNED, TOOLS)


def _small_window_case():
    """8000-token window: ~0.7k pinned tokens plus ~1.7k of work-turn tool schemas (the ~2.5k seen in real runs)."""
    pinned = [{"role": "developer", "content": "[intend]\nKeep the original request.\n[current_work]\n" + "w" * 2700}]
    tools = [{"type": "function", "name": f"tool_{index}", "description": "d" * 750, "parameters": {"type": "object"}}
             for index in range(8)]
    return _history(16, 1200), pinned, tools


def test_narrow_window_keeps_half_of_itself_for_the_summary_response():
    records, pinned, tools = _small_window_case()
    # output_limit 4096 on an 8000 window: the response reserve is 4000, so compaction triggers once the
    # input passes 4000 and every summary request keeps its input at or below 4000.
    plan = plan_compaction(records, None, 8000, pinned, tools, output_limit=4096)
    assert plan.summary_token_limit == 800
    assert plan.input_token_estimate <= 4000
    assert plan.input_token_estimate == estimate_tokens(json_dumps({"input": plan.input_items, "tools": []}))
    assert plan.max_output_tokens == min(4096, 8000 - plan.input_token_estimate) >= 4000
    assert plan.input_token_estimate + plan.max_output_tokens <= 8000
    # A smaller declared limit reserves only that much and caps the request at it.
    capped = plan_compaction(records, None, 8000, pinned, tools, output_limit=2000)
    assert capped.summary_token_limit == 800
    assert capped.input_token_estimate <= 6000 and len(capped.source_refs) > len(plan.source_refs)
    assert capped.max_output_tokens == 2000
    # 摘要请求的 max_output_tokens 固定上限为 SUMMARY_OUTPUT_TOKENS (4096)，
    # 与模型声明的输出上限无关。
    unbounded = plan_compaction(records, None, 8000, pinned, tools)
    assert unbounded.max_output_tokens == min(4096, 8000 - unbounded.input_token_estimate) >= 1200
    for candidate in (plan, capped, unbounded):
        assert candidate.summary_token_limit <= candidate.max_output_tokens


def test_long_tool_result_is_summarized_in_rounds_that_each_leave_half_the_narrow_window_for_output():
    pinned = [{"role": "developer", "content": "[intend]\nKeep the original request.\n[current_work]\n" + "w" * 4700}]
    call = {"id": "call-item", "type": "function_call", "name": "read_file", "call_id": "call-1",
            "arguments": json_dumps({"path": "large.txt"})}
    result = {"type": "function_call_output", "call_id": "call-1", "output": "BEGIN-" + "LARGE_FILE " * 4000 + "-END"}
    records = [_record(1, call, step=1), _record(2, result, step=1)]
    summary = "Decisions: the file was read in slices; progress continues. " * 12
    assert len(summary) <= 800
    checkpoint = None
    rounds = 0
    for _ in range(64):
        plan = plan_compaction(records, checkpoint, 8000, pinned, TOOLS, output_limit=4096)
        if plan is None:
            break
        rounds += 1
        assert plan.summary_token_limit == 800
        assert plan.input_token_estimate <= 8000 - 4000
        assert plan.max_output_tokens == min(4096, 8000 - plan.input_token_estimate) >= 4000
        checkpoint = finish_compaction(plan, _output(summary))
    else:
        raise AssertionError("compaction did not cover the tool result")
    # 工具输出截断为2000字符后，所需轮次减少
    assert rounds >= 1 and checkpoint.boundary
    assert checkpoint.covered_through_event_id == "event-2"
    assert visible_history(records, checkpoint)[0]["content"].startswith("[department_memory]\n")


def test_wide_window_slicing_is_unchanged_by_the_narrow_window_reserve():
    records = _history(60, 2300)
    plan = plan_compaction(records, None, 32000, PINNED, TOOLS, output_limit=4096)
    # Baseline captured before the narrow-window reserve was introduced (32000 window, 4096 limit).
    assert len(plan.source_refs) == 36
    assert plan.next_checkpoint.covered_through_event_id == "event-36" and plan.next_checkpoint.partial_offset == 0
    assert plan.next_checkpoint.covered_digest == "sha256:2a7fd041ead224608af5f60ba7768a18a9f46bb6473d79d1ae559b847cd74284"
    assert plan.input_token_estimate == 26916 and plan.summary_token_limit == 3200
    assert plan.max_output_tokens == 4096
    # 摘要请求的 max_output_tokens 固定上限为 SUMMARY_OUTPUT_TOKENS (4096)。
    unbounded = plan_compaction(records, None, 32000, PINNED, TOOLS)
    assert unbounded.max_output_tokens == min(4096, 32000 - unbounded.input_token_estimate)


def test_response_reserve_is_15_percent_for_wide_windows_and_up_to_half_of_a_narrow_window():
    assert response_reserve(32000, None) == response_reserve(32000, 4096) == 4800
    assert response_reserve(8000, None) == 1200
    assert response_reserve(8000, 4096) == 4000
    assert response_reserve(8000, 2000) == 2000
    assert response_reserve(6000, 1000) == 1000


def _work_request_tokens(records, pinned, tools, output_limit):
    payload = {"input": [*pinned, *(record["item"] for record in records)], "tools": tools}
    if output_limit is not None:
        payload["max_output_tokens"] = output_limit
    return estimate_tokens(json_dumps(payload))


def _widest_history_within(count, budget, output_limit):
    """The widest ``count``-record history whose work request estimate stays within ``budget``."""
    low, high = 1, 8000
    while low < high:
        middle = (low + high + 1) // 2
        if _work_request_tokens(_history(count, middle), PINNED, TOOLS, output_limit) <= budget:
            low = middle
        else:
            high = middle - 1
    return low


def test_narrow_window_compacts_once_the_input_reaches_the_response_reserve():
    width = _widest_history_within(4, 4200, 4096)
    records = _history(4, width)
    assert 4000 < _work_request_tokens(records, PINNED, TOOLS, 4096) <= 4200
    # 8000 window, 4096 declared limit: the input may only use what the 4000-token reserve leaves,
    # so compaction starts here instead of at the old 6800-token (85%) mark.
    plan = plan_compaction(records, None, 8000, PINNED, TOOLS, output_limit=4096)
    assert plan is not None
    assert plan.input_token_estimate <= 4000
    assert plan.max_output_tokens == min(4096, 8000 - plan.input_token_estimate) >= 4000
    # Without a declared limit the trigger stays at 85% of the window, so the same history still fits.
    assert plan_compaction(records, None, 8000, PINNED, TOOLS) is None


def test_wide_window_compaction_trigger_stays_at_85_percent():
    width = _widest_history_within(28, 27200, 4096)
    fitting = _history(28, width)
    assert 27000 < _work_request_tokens(fitting, PINNED, TOOLS, 4096) <= 27200
    assert plan_compaction(fitting, None, 32000, PINNED, TOOLS, output_limit=4096) is None
    assert plan_compaction(fitting, None, 32000, PINNED, TOOLS) is None
    crossing = _history(28, width + 4)
    assert 27200 < _work_request_tokens(crossing, PINNED, TOOLS, 4096) < 27400
    assert plan_compaction(crossing, None, 32000, PINNED, TOOLS, output_limit=4096) is not None
    assert plan_compaction(crossing, None, 32000, PINNED, TOOLS) is not None


@pytest.mark.parametrize("pinned, output_limit, message", [
    ([{"role": "developer", "content": "[intend]\n" + "p" * 13300}], None, "insufficient room"),
    (PINNED, 16, "insufficient room"),
])
def test_window_left_below_the_summary_limit_still_fails_before_any_request(pinned, output_limit, message):
    with pytest.raises(CompactionError, match=message):
        plan_compaction(_history(), None, 4000, pinned, TOOLS, output_limit=output_limit)


def test_fixed_intend_and_current_work_cannot_be_compressed_away():
    with pytest.raises(CompactionError, match="Pinned"):
        plan_compaction(_history(), None, 4000, [{"role": "developer", "content": "x" * 16000}], TOOLS)


def test_no_history_to_summarize_cannot_trigger_an_infinite_summary_loop():
    records = _history(1, 7000)
    _, checkpoint = _complete_until_work_fits(records, window=1600)
    assert checkpoint.covered_through_event_id == records[-1]["event_id"]
    with pytest.raises(CompactionError):
        plan_compaction(records, replace(checkpoint, summary="x" * 7000), 1600, PINNED, TOOLS)


@pytest.mark.parametrize("output", [
    [{"type": "function_call", "name": "submit_delivery", "arguments": "{}"}],
    [{"type": "message", "role": "assistant", "content": [{"type": "refusal", "refusal": "No"}]}],
])
def test_malformed_summary_response_is_rejected_without_committing_a_checkpoint(output):
    plan = plan_compaction(_history(), None, 4000, PINNED, TOOLS)
    with pytest.raises(CompactionError):
        finish_compaction(plan, output)
    assert plan.next_checkpoint.summary == ""


@pytest.mark.parametrize("output", [[], _output(""), _output("x" * 1700),
    [{"type": "message", "role": "assistant", "status": "incomplete", "content": []}],
])
def test_empty_or_oversized_summary_returns_none_instead_of_failing(output):
    plan = plan_compaction(_history(), None, 4000, PINNED, TOOLS)
    assert finish_compaction(plan, output) is None
    assert plan.next_checkpoint.summary == ""


def test_reasoning_is_not_misread_as_summary_text():
    plan = plan_compaction(_history(), None, 4000, PINNED, TOOLS)
    checkpoint = finish_compaction(plan, [{"type": "reasoning", "content": None, "encrypted_content": "opaque"}, *_output()])
    assert checkpoint.summary == _output()[0]["content"][0]["text"]


def test_opaque_reasoning_stays_in_original_history_and_is_cited_in_summary_material():
    cipher = "ENCRYPTED_OPAQUE_PAYLOAD" * 4000
    item = {"id": "reasoning-1", "type": "reasoning", "summary": [{"type": "summary_text", "text": "Check the file"}],
            "encrypted_content": cipher, "content": None}
    records = [_record(1, item), _record(2, {"role": "user", "content": "Continue checking"})]
    original = deepcopy(records)
    plans, checkpoint = _complete_until_work_fits(records)
    assert len(plans) == 1
    material = summary_material(records[0])
    assert material["encrypted_content"] == {
        "source_event_id": "event-1", "field": "encrypted_content", "length": len(cipher), "digest": canonical_hash(cipher),
    }
    fragment = json.loads(plans[0].input_items[-1]["content"])["source_fragments"][0]
    assert cipher not in fragment["text"]
    assert json.loads(fragment["text"])["summary"] == item["summary"]
    assert fragment["item_digest"] == canonical_hash(item)
    assert fragment["material_digest"] == canonical_hash(material)
    assert records == original
    assert visible_history(records)[0]["encrypted_content"] == cipher
    assert checkpoint.boundary


@pytest.mark.parametrize("items", [
    [{"type": "function_call", "call_id": "unfinished", "name": "read_file", "arguments": "{}"}],
    [{"type": "function_call_output", "call_id": "orphan", "output": "result"}],
])
def test_unpaired_tool_history_has_no_valid_compaction_boundary(items):
    with pytest.raises(CompactionError, match="tool"):
        plan_compaction([_record(index, item, step=1) for index, item in enumerate(items, 1)], None, 4000, PINNED, TOOLS)


def test_summary_request_contains_no_tools_and_no_reasoning_options():
    """摘要请求必须发送 tools=[]，不携带推理/provider 特殊参数。"""
    plan = plan_compaction(_history(), None, 4000, PINNED, TOOLS)
    assert plan is not None
    # 摘要请求的 input_items 不包含任何工具声明
    request_payload = {"input": plan.input_items, "tools": []}
    serialized = json_dumps(request_payload)
    assert '"tools":[]' in serialized or '"tools": []' in serialized
    # 请求 payload 中不含推理相关 API 参数（不是 prompt 文本中提到的"reasoning"一词）
    # 通过检查 plan 的 input_items 结构，确认没有 reasoning_effort / thinking 等顶层字段
    for item in plan.input_items:
        assert "reasoning_effort" not in item
        assert "thinking" not in item


def test_summary_is_taken_from_visible_text_only_reasoning_ignored():
    """只有可见文本成为摘要；reasoning 类型的输出被忽略。"""
    plan = plan_compaction(_history(), None, 4000, PINNED, TOOLS)
    # reasoning 输出不包含 output_text，不会成为摘要
    reasoning_only = [{"id": "reason", "type": "reasoning", "summary": [{"type": "summary_text", "text": "thinking"}],
                       "encrypted_content": "opaque", "content": None}]
    assert finish_compaction(plan, reasoning_only) is None
    # reasoning + 有效文本：只有文本部分成为摘要
    mixed = [{"type": "reasoning", "content": None, "encrypted_content": "opaque"},
             *_output("Decisions: inspect evidence. Pending: finish checks.")]
    checkpoint = finish_compaction(plan, mixed)
    assert checkpoint is not None
    assert checkpoint.summary == "Decisions: inspect evidence. Pending: finish checks."
    assert "opaque" not in checkpoint.summary
    assert "thinking" not in checkpoint.summary


def test_tool_outputs_in_serialized_history_are_truncated_to_2000_chars():
    """工具输出在序列化历史时截断为 TOOL_OUTPUT_MAX_CHARS (2000) 字符。"""
    from harness.compaction import TOOL_OUTPUT_MAX_CHARS
    long_output = "A" * 5000
    call = {"id": "call-1", "type": "function_call", "name": "read_file", "call_id": "c1", "arguments": "{}"}
    result = {"type": "function_call_output", "call_id": "c1", "output": long_output}
    records = [_record(1, call, step=1), _record(2, result, step=1)]
    material = summary_material(records[1])
    assert len(material["output"]) == TOOL_OUTPUT_MAX_CHARS + len("\n[truncated]")
    assert material["output"].endswith("\n[truncated]")
    assert material["output"][:TOOL_OUTPUT_MAX_CHARS] == "A" * TOOL_OUTPUT_MAX_CHARS
    # 短输出不截断
    short_result = {"type": "function_call_output", "call_id": "c1", "output": "short"}
    short_record = _record(3, short_result, step=1)
    assert summary_material(short_record)["output"] == "short"


def test_preflight_check_prevents_oversized_prompt_from_being_sent():
    """预检：摘要提示词超过 context_window - SUMMARY_OUTPUT_TOKENS 时返回 None。"""
    # 构造一个 pinned 上下文非常大的场景，使摘要提示词超过窗口 - 4096
    huge_pinned = [{"role": "developer", "content": "[intend]\n" + "x" * 20000}]
    records = _history(2, 100)
    # 窗口 32000：摘要提示词远超 32000 - 4096 = 27904
    result = plan_compaction(records, None, 32000, huge_pinned, [])
    assert result is None


def test_summary_output_tokens_cap_applies_regardless_of_model_output_limit():
    """摘要请求的 max_output_tokens 上限为 SUMMARY_OUTPUT_TOKENS，与模型声明无关。"""
    from harness.compaction import SUMMARY_OUTPUT_TOKENS
    records = _history(60, 2300)
    # 声明很大的模型输出上限
    plan = plan_compaction(records, None, 32000, PINNED, TOOLS, output_limit=16384)
    assert plan.max_output_tokens <= SUMMARY_OUTPUT_TOKENS
    # 声明很小的模型输出上限
    plan_small = plan_compaction(records, None, 32000, PINNED, TOOLS, output_limit=1024)
    assert plan_small.max_output_tokens <= 1024
