import json
from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from harness.compaction import (
    SUMMARY_PREFACE, SUMMARY_RULES, CompactionCheckpoint, CompactionError, finish_compaction, plan_compaction,
    summary_material, visible_history,
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
        assert plan.max_output_tokens == 600
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
    assert plan.input_token_estimate == estimate_tokens(json_dumps({
        "input": plan.input_items, "tools": [], "max_output_tokens": plan.max_output_tokens,
    }))


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
    assert len(plans) > 2
    assert any(plan.next_checkpoint.partial_event_id == "event-2" for plan in plans)
    for previous, current in zip(plans, plans[1:]):
        assert json.loads(current.input_items[-1]["content"])["previous_summary"] == finish_compaction(previous, _output()).summary
    for plan in plans:
        if not plan.next_checkpoint.boundary:
            with pytest.raises(CompactionError, match="finish the current"):
                visible_history(records, finish_compaction(plan, _output()))
    assert checkpoint.boundary
    assert visible_history(records, checkpoint)[-1] == records[-1]["item"]
    fragments = [part for plan in plans for part in json.loads(plan.input_items[-1]["content"])["source_fragments"]
                 if part["event_id"] == "event-2"]
    assert "".join(fragment["text"] for fragment in fragments) == json_dumps(result)


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


def test_fixed_intend_and_current_work_cannot_be_compressed_away():
    with pytest.raises(CompactionError, match="Pinned"):
        plan_compaction(_history(), None, 4000, [{"role": "developer", "content": "x" * 16000}], TOOLS)


def test_no_history_to_summarize_cannot_trigger_an_infinite_summary_loop():
    records = _history(1, 7000)
    _, checkpoint = _complete_until_work_fits(records, window=1600)
    assert checkpoint.covered_through_event_id == records[-1]["event_id"]
    with pytest.raises(CompactionError):
        plan_compaction(records, replace(checkpoint, summary="x" * 7000), 1600, PINNED, TOOLS)


@pytest.mark.parametrize("output", [[], _output(""), _output("x" * 1700),
    [{"type": "function_call", "name": "submit_delivery", "arguments": "{}"}],
    [{"type": "message", "role": "assistant", "status": "incomplete", "content": []}],
    [{"type": "message", "role": "assistant", "content": [{"type": "refusal", "refusal": "No"}]}],
])
def test_invalid_summary_is_rejected_without_committing_a_checkpoint(output):
    plan = plan_compaction(_history(), None, 4000, PINNED, TOOLS)
    with pytest.raises(CompactionError):
        finish_compaction(plan, output)
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
