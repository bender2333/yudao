import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from harness.collaboration import has_new_work
from harness.adapters.fake import FakeAdapter
from harness.compaction import SUMMARY_OUTPUT_TOKENS
from harness.contracts import current_contract_hash
from harness.definitions import DEFINITIONS
from harness.models import EventType, canonical_hash, json_dumps
from harness.engine import StepLimits
from harness.proposals import delivery_turn, product_spec
from harness.providers.call import ModelResponse, ModelStreamEvent
from harness.runtime import LoopSystem
from harness.tests.helpers import (
    FAST_RETRIES,
    compacted_runner as _runner,
    department_history,
    pinned_input_tokens,
    quality_turns,
    read_file_call as _read,
    recorded_context,
    summary_message as _message,
)
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

# 这个文件里等待压缩线程到达模型回调、等待会合点释放、等待这次激活收尾的墙钟界限，
# 只用来防止测试一直等待，按 #107 的裁定（架构师 2026-09-27 16:55，docs/architecture-issues.md）
# 设为远大于负载下正常用时的值。被等待的是一次激活走到压缩请求，正常用时数秒，
# 并发负载下更慢；这些界限不判定被测行为，被等待的动作是否发生由等待之后的断言核对。
_WAIT_LIMIT = WAIT_FOR_HOST_WORK_SEC


def test_compaction_preserves_originals_then_resumes_work_with_summary(tmp_path):
    system, adapter, run_id, original = _runner(tmp_path)
    result = system.activate_once(run_id)
    assert has_new_work(result, "engineering"), result.error
    assert result.compactions
    assert adapter.invocations[0].purpose == adapter.invocations[-1].purpose == "work"
    assert any(request.purpose == "compaction" for request in adapter.invocations)
    last = adapter.invocations[-1]
    assert "department_memory" in json_dumps(last.input_items)
    assert "FIRST_TOOL_ORIGINAL " * 100 not in json_dumps(last.input_items)
    events = system.store.list_events(run_id)
    raw_tool = next(event for event in events if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "read_file")
    assert system.artifacts.get_text(raw_tool.payload["output_ref"]["content_hash"]).count("FIRST_TOOL_ORIGINAL") == 2200
    for request, manifest in zip(adapter.invocations, result.manifests):
        pinned_index = 1 if request.purpose == "compaction" else 0
        assert request.input_items[pinned_index]["content"].startswith(f"[intend]\n{original}\n\n[current_work]\n")
        saved = json.loads(system.artifacts.get_text(manifest.request_ref["content_hash"]))
        assert canonical_hash(saved) == manifest.digest
        assert saved["input"] == request.input_items and saved["tools"] == request.tools
        if request.purpose == "compaction":
            assert not request.tools
            assert saved["max_output_tokens"] == request.max_output_tokens > 0
    source_ids = {record["event_id"] for record in department_history(system, run_id, "product")}
    summary_ids = {event.event_id for event in events if event.type == EventType.MODEL_MESSAGE and event.payload.get("purpose") == "compaction"}
    assert summary_ids and source_ids.isdisjoint(summary_ids)
    for record in result.compactions:
        assert record["run_id"] == run_id and record["department"] == "product"
        assert all(ref["event_id"] in source_ids for ref in record["source_refs"])
        assert system.artifacts.get_text(record["summary_ref"]["content_hash"]) == record["checkpoint"]["summary"]
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_compaction_checkpoint_survives_reactivation_and_new_controller(tmp_path):
    system, adapter, run_id, _ = _runner(tmp_path, reject_first_spec=True)
    first = system.activate_once(run_id)
    assert has_new_work(first, "product") and first.effective_contract is None
    assert first.rejections[-1]["errors"][0]["field"] == "acceptance_criteria"
    first_checkpoint = first.compactions[-1]["source_event_id"]
    system.workspace(run_id).write_file("large.txt", "SECOND_TOOL_ORIGINAL " * 2200)
    reloaded = LoopSystem.for_testing(tmp_path, adapter, resume_on_startup=False)
    result = reloaded.activate_once(run_id)
    assert has_new_work(result, "engineering"), result.error
    later = [record for record in result.compactions if record["source_event_id"] not in {item["source_event_id"] for item in first.compactions}]
    assert later
    assert later[0]["previous_compaction_event_id"] == first_checkpoint
    assert later[0]["effective_contract_hash"] == first.compactions[-1]["effective_contract_hash"] is None
    assert later[-1]["checkpoint"]["boundary"]
    assert recorded_context(reloaded, adapter.invocations[-1]).manifest.compaction_event_id == later[-1]["source_event_id"]
    assert "department_memory" in json_dumps(adapter.invocations[-1].input_items)
    assert result.canonical_state() == reloaded.replay(run_id).canonical_state()


def test_changed_contract_rebuilds_compaction_from_preserved_original_sources(tmp_path):
    system, adapter, run_id, _ = _runner(tmp_path)
    first = system.activate_once(run_id)
    assert has_new_work(first, "engineering") and first.effective_contract is not None
    assert first.compactions[-1]["effective_contract_hash"] is None
    first_checkpoint = first.compactions[-1]["source_event_id"]
    source = next(event for event in system.store.list_events(run_id)
                  if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "read_file")
    original = system.artifacts.get_text(source.payload["output_ref"]["content_hash"])
    system.workspace(run_id).write_file("large.txt", "SECOND_TOOL_ORIGINAL " * 2200)
    reloaded = LoopSystem.for_testing(tmp_path, adapter, resume_on_startup=False)
    result = reloaded.activate_once(run_id)
    engineering = next(request for request in adapter.invocations if request.department == "engineering")
    assert "department_memory" not in json_dumps(engineering.input_items)
    assert "FIRST_TOOL_ORIGINAL" not in json_dumps(engineering.input_items)
    previous_ids = {item["source_event_id"] for item in first.compactions}
    later = [record for record in result.compactions if record["source_event_id"] not in previous_ids]
    assert later and later[0]["previous_compaction_event_id"] is None
    assert all(record["effective_contract_hash"] == first.effective_contract.content_hash for record in later)
    assert source.event_id in {ref["event_id"] for record in later for ref in record["source_refs"]}
    assert first_checkpoint in {record["source_event_id"] for record in result.compactions}
    assert system.artifacts.get_text(source.payload["output_ref"]["content_hash"]) == original
    assert original.count("FIRST_TOOL_ORIGINAL") == 2200
    assert later[-1]["checkpoint"]["boundary"]
    product_invocations = [r for r in adapter.invocations if r.department == "product"]
    assert recorded_context(reloaded, product_invocations[-1]).manifest.compaction_event_id == later[-1]["source_event_id"]
    assert result.canonical_state() == reloaded.replay(run_id).canonical_state()


def test_cancelled_compaction_keeps_observed_summary_without_adopting_it(tmp_path):
    entered, release = Event(), Event()

    def late_summary(request):
        item = _message(request, "LATE_SUMMARY_MUST_NOT_BE_ADOPTED")
        yield ModelStreamEvent(kind="message", id=item["id"], payload=item, text="LATE_SUMMARY_MUST_NOT_BE_ADOPTED")
        entered.set()
        assert release.wait(_WAIT_LIMIT)
        return ModelResponse(output=[item])

    system, adapter, run_id, _ = _runner(tmp_path, cancelled_summary=late_summary)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(system.activate_once, run_id)
        try:
            assert entered.wait(_WAIT_LIMIT)
            assert system.cancel(run_id).stop_reason == "cancelled"
        finally:
            release.set()
        result = future.result(timeout=_WAIT_LIMIT)
    assert result.stop_reason == "cancelled" and not result.compactions
    assert len(adapter.invocations) == 2
    events = system.store.list_events(run_id)
    assert any(event.type == EventType.MODEL_MESSAGE and event.payload.get("purpose") == "compaction" for event in events)
    assert "LATE_SUMMARY_MUST_NOT_BE_ADOPTED" not in json_dumps(department_history(system, run_id, "product"))


CORRUPT_TOOL_NAME = "thought\n<ctrl95><ctrl42>call:list_files"


def _undeclared_tool_call(request):
    identity = f"corrupt-{request.activation_id}-{request.step_id}"
    return ModelResponse(output=[{"id": identity, "call_id": identity, "type": "function_call",
                                  "name": CORRUPT_TOOL_NAME, "arguments": "{}"}])


def test_undeclared_tool_call_in_summary_is_a_retryable_failure_that_never_executes(tmp_path):
    compaction_count = 0

    def summary(request):
        nonlocal compaction_count
        compaction_count += 1
        return _undeclared_tool_call(request) if compaction_count == 1 else ModelResponse(output=[_message(request)])

    system, adapter, run_id, _ = _runner(tmp_path, cancelled_summary=summary, step_limits=FAST_RETRIES)
    result = system.activate_once(run_id)

    assert has_new_work(result, "engineering"), result.error
    assert result.compactions
    attempts = [request for request in adapter.invocations if request.purpose == "compaction"]
    assert attempts[0].tools == attempts[1].tools == []
    assert attempts[0].input_items == attempts[1].input_items
    assert (attempts[0].attempt, attempts[1].attempt) == (1, 2)
    events = system.store.list_events(run_id)
    requested = [event.payload for event in events
                 if event.type == EventType.MODEL_REQUESTED and event.payload["purpose"] == "compaction"]
    assert attempts[0].logical_call_id == attempts[1].logical_call_id
    assert requested[0]["root_step_id"] == requested[1]["root_step_id"]
    assert requested[1]["retry_of_step_id"] == attempts[0].step_id
    failed = [event for event in events if event.type == EventType.MODEL_ATTEMPT_FAILED]
    assert len(failed) == 1
    assert failed[0].payload["purpose"] == "compaction"
    assert failed[0].payload["reason"] == "compaction_failed"
    assert failed[0].payload["retryable"] is True and failed[0].payload["will_retry"] is True
    assert failed[0].payload["diagnostics"] == {"error_type": "undeclared_tool_call", "tool_names": [CORRUPT_TOOL_NAME]}
    assert len([event for event in events if event.type == EventType.MODEL_RETRY_SCHEDULED]) == 1
    # Nothing executed: no tool admission, no tool result, only the token accounting record.
    assert not any(event.type == EventType.TOOL_STARTED and event.payload.get("name") == CORRUPT_TOOL_NAME for event in events)
    assert all(event.payload.get("name") == "provider_usage" for event in events
               if event.type in {EventType.TOOL_CALLED, EventType.TOOL_SKIPPED} and event.payload.get("purpose") == "compaction")
    # The corrupt output stays as evidence but never becomes department history or summary source.
    evidence = [event for event in events if event.type == EventType.MODEL_MESSAGE
                and event.payload.get("response_id", "").startswith("corrupt-")]
    assert len(evidence) == 1
    saved = json.loads(system.artifacts.get_text(evidence[0].payload["message_ref"]["content_hash"]))
    assert saved["type"] == "function_call" and saved["name"] == CORRUPT_TOOL_NAME
    assert "corrupt-" not in json_dumps(department_history(system, run_id, "product"))
    assert "corrupt-" not in json_dumps([record["source_refs"] for record in result.compactions])
    assert "corrupt-" not in json_dumps(adapter.invocations[-1].input_items)
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_three_undeclared_tool_calls_fail_compaction_and_keep_every_attempt_as_evidence(tmp_path):
    system, adapter, run_id, _ = _runner(tmp_path, cancelled_summary=_undeclared_tool_call, step_limits=FAST_RETRIES)
    result = system.activate_once(run_id)

    assert result.status == "failed" and result.stop_reason == "compaction_failed"
    assert not result.compactions
    attempts = [request for request in adapter.invocations if request.purpose == "compaction"]
    assert [request.attempt for request in attempts] == [1, 2, 3]
    assert len({request.logical_call_id for request in attempts}) == 1
    events = system.store.list_events(run_id)
    failed = [event for event in events if event.type == EventType.MODEL_ATTEMPT_FAILED]
    assert [event.payload["will_retry"] for event in failed] == [True, True, False]
    assert all(event.payload["reason"] == "compaction_failed" and event.payload["retryable"] is True for event in failed)
    assert len([event for event in events if event.type == EventType.MODEL_RETRY_SCHEDULED]) == 2
    evidence = [event for event in events if event.type == EventType.MODEL_MESSAGE
                and event.payload.get("response_id", "").startswith("corrupt-")]
    assert len(evidence) == 3
    assert not any(event.type == EventType.TOOL_STARTED and event.payload.get("name") == CORRUPT_TOOL_NAME for event in events)
    assert all(event.payload.get("name") == "provider_usage" for event in events
               if event.type in {EventType.TOOL_CALLED, EventType.TOOL_SKIPPED} and event.payload.get("purpose") == "compaction")
    raw_tool = next(event for event in events if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "read_file")
    assert system.artifacts.get_text(raw_tool.payload["output_ref"]["content_hash"]).count("FIRST_TOOL_ORIGINAL") == 2200
    history = department_history(system, run_id, "product")
    assert raw_tool.event_id in {record["event_id"] for record in history}
    assert "corrupt-" not in json_dumps(history)
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_truncated_summary_is_rejected_without_retry_or_checkpoint(tmp_path):
    """A summary cut off by the output limit is a terminal provider response: never adopted, never retried."""
    def truncated(request):
        item = _message(request, "Decisions: the first half of the memory and then")
        item["status"] = "incomplete"
        return ModelResponse(output=[item], finish_reason="incomplete", error="max_output_tokens")

    system, adapter, run_id, _ = _runner(tmp_path, cancelled_summary=truncated, step_limits=FAST_RETRIES)
    result = system.activate_once(run_id)

    assert result.status == "failed" and result.stop_reason == "provider_error"
    assert not result.compactions
    attempts = [request for request in adapter.invocations if request.purpose == "compaction"]
    assert len(attempts) == 1
    events = system.store.list_events(run_id)
    assert not any(event.type == EventType.COMPACTION_RECORDED for event in events)
    assert not any(event.type == EventType.MODEL_RETRY_SCHEDULED for event in events)
    failed = [event for event in events if event.type == EventType.MODEL_ATTEMPT_FAILED]
    assert len(failed) == 1 and failed[0].payload["purpose"] == "compaction"
    assert failed[0].payload["retryable"] is False and failed[0].payload["will_retry"] is False
    assert "the first half" not in json_dumps(department_history(system, run_id, "product"))
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_step_limit_pauses_during_partial_compaction_without_work_request(tmp_path):
    system, adapter, run_id, _ = _runner(tmp_path, step_limits=StepLimits(max_model_steps=2))
    result = system.activate_once(run_id)
    assert result.status == "paused" and result.stop_reason == "model_steps_exhausted"
    assert len(adapter.invocations) == 2
    assert adapter.invocations[-1].purpose == "compaction"
    assert result.compactions
    # 工具输出截断后，压缩可能在单轮内完成（boundary=True）或跨多轮（boundary=False）
    # 只要压缩被记录且步骤耗尽暂停即可
    assert result.product_spec is None


def test_empty_compaction_summary_allows_retry_in_the_next_compaction(tmp_path):
    """一次空摘要以后可以重新尝试压缩：下一次整理接上上一次的检查点（工单 #840）。"""
    summaries = []

    def respond(request):
        if request.purpose == "compaction":
            summaries.append(request)
            # 第二次整理返回空摘要（不生效，不留下检查点），第三次接上第一次的检查点
            if len(summaries) == 2:
                return ModelResponse(output=[_message(request, "")])
            return ModelResponse(output=[_message(request, "Product memory: prior evidence was read.")])
        if request.department == "engineering":
            return delivery_turn()(request)
        return _read(request, "large.txt")

    adapter = FakeAdapter([respond] * 200)
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=StepLimits(max_model_steps=32))
    # 窗口由固定材料的实测 token 数推出，理由与 test_single_empty_summary_does_not_fail_the_run_and_department_continues 相同
    measure_id = system.create_run("Original intent", context_window=1_000_000)
    window = pinned_input_tokens(system, measure_id) + SUMMARY_OUTPUT_TOKENS * 2
    run_id = system.create_run("Original intent", context_window=window)
    system.workspace(run_id).write_file("large.txt", "TOOL_OUTPUT " * (window * 8 // 11))
    result = system.activate_once(run_id)

    # 一次空摘要不终止运行
    assert result.status != "failed"
    assert len(summaries) >= 3
    assert len(result.compactions) >= 2
    # 空的那一次没有留下检查点：后一次整理接上前一次记录的检查点
    assert result.compactions[1]["previous_compaction_event_id"] == result.compactions[0]["source_event_id"]
    assert all(record["checkpoint"]["summary"] for record in result.compactions)


# 工单 #840：工程询问产品，产品在回答里修订 PRD（合同换版本），工程接着工作到历史超过阈值。
_REVISION_SUMMARY = "Engineering memory: the earlier reads are summarized."


def _ask_product(call):
    # 工程的一次询问：问产品要不要改需求
    identity = f"ask-{call.activation_id}-{call.step_id}"
    return ModelResponse(output=[{
        "id": identity, "call_id": identity, "type": "function_call", "name": "ask",
        "arguments": json_dumps({
            "recipient": "product",
            "question": "Should the output be uppercase?",
            "background": "Clarification needed",
            "expected": "Specification update",
        }),
    }])


def _prd_revision_answer(call):
    # 产品在询问分支里修订 PRD 并回答：依据取本次请求里的当前 PRD 版本
    current = json.loads(
        next(item["content"] for item in call.input_items
             if "[current_product_spec]" in item.get("content", ""))
        .split("[current_product_spec]\n")[1].split("\n\n")[0])
    identity = f"ans-{call.activation_id}-{call.step_id}"
    return ModelResponse(output=[{
        "id": identity, "call_id": identity, "type": "function_call", "name": "answer",
        "arguments": json_dumps({
            "answer": "Yes, print in uppercase.",
            "goal": "build an echo CLI",
            "requirements": ["print the given argument in uppercase to stdout"],
            "acceptance_criteria": ["running the program with a word prints that word in uppercase"],
            "change_record": {
                "changed": ["print the given argument in uppercase to stdout"],
                "retained": ["single file implementation"],
                "retired": [],
                "rationale": "Clarification revision.",
            },
            "basis_product_spec_hash": current["content_hash"],
        }),
    }])


def test_compaction_after_prd_revision_continues_the_previous_checkpoint(tmp_path):
    """询问带回新合同以后，连续的压缩接上同一次会话的上一次，覆盖范围往前走（工单 #840）。

    记录器与引擎用同一份工作依据：询问以后记录的压缩事件与工具结果都带新合同。
    """
    reads = {"count": 0}
    read_count = 14

    def engineering(call):
        if call.purpose == "compaction":
            return ModelResponse(output=[_message(call, _REVISION_SUMMARY)])
        index = reads["count"]
        reads["count"] += 1
        if index == 0:
            return _ask_product(call)
        if index <= read_count:
            return _read(call, f"part{index}.txt")
        return delivery_turn()(call)

    adapter = FakeAdapter({
        "product": [product_spec()],
        "product:ask": [_prd_revision_answer],
        "engineering": [engineering] * 200,
        "quality": quality_turns("release", "the delivery implements the revised PRD"),
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo", context_window=6000)
    for index in range(1, read_count + 1):
        system.workspace(run_id).write_file(f"part{index}.txt", "x" * 1200)

    first = system.activate_once(run_id)
    assert first.product_spec is not None and first.product_spec.revision == 1
    second = system.activate_once(run_id)
    assert second.product_spec is not None and second.product_spec.revision == 2

    compactions = second.compactions
    assert len(compactions) >= 2, compactions
    contract = current_contract_hash(system.project(run_id))
    events = system.store.list_events(run_id)
    order = {event.event_id: event.stream_version for event in events}
    covered = []
    for index, record in enumerate(compactions):
        # 询问以后记录的压缩事件带新合同
        assert record["effective_contract_hash"] == contract
        if index:
            # 第二次及以后的压缩接上上一次
            assert record["previous_compaction_event_id"] == compactions[index - 1]["source_event_id"]
        covered.append(order[record["checkpoint"]["covered_through_event_id"]])
    # 覆盖范围往前走：每一次覆盖到的位置都在上一次之后
    assert covered == sorted(covered) and len(set(covered)) == len(covered)

    # 询问以后记录的工具结果带新合同
    asked = next(index for index, event in enumerate(events) if event.type == EventType.ASK_ANSWERED)
    tool_results = [event for event in events[asked:]
                    if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "read_file"]
    assert tool_results
    for event in tool_results:
        assert event.payload["effective_contract_hash"] == contract
    assert second.canonical_state() == system.replay(run_id).canonical_state()


def test_repeated_empty_summaries_stop_the_run_with_compaction_failed(tmp_path):
    """整理每次都返回空摘要：连续 compaction.stalled_limit 次以后以压缩失败停止（工单 #840）。"""
    limit = DEFINITIONS.rule_value("compaction.stalled_limit")
    compaction_requests = []

    def respond(request):
        if request.purpose == "compaction":
            compaction_requests.append(request)
            return ModelResponse(output=[_message(request, "")])
        return _read(request, "large.txt")

    adapter = FakeAdapter([respond] * 100)
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=StepLimits(max_model_steps=32))
    original = "Original intent"
    measure_id = system.create_run(original, context_window=1_000_000)
    window = pinned_input_tokens(system, measure_id) + SUMMARY_OUTPUT_TOKENS * 2
    run_id = system.create_run(original, context_window=window)
    system.workspace(run_id).write_file("large.txt", "TOOL_OUTPUT " * (window * 8 // 11))
    result = system.activate_once(run_id)

    # 连续达到上限以后以压缩失败停止
    assert result.status == "failed" and result.stop_reason == "compaction_failed", result.error
    # 停止说明写明连续的次数与最后一次的原因
    assert f"连续 {limit} 次没有推进" in (result.error or "")
    assert "摘要为空" in (result.error or "")
    # 停止以后不再发出新的压缩请求
    assert len(compaction_requests) == limit
    assert not result.compactions
    assert not any(event.type == EventType.COMPACTION_RECORDED
                   for event in system.store.list_events(run_id))
    assert result.canonical_state() == system.replay(run_id).canonical_state()
