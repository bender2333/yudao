import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from harness.watched_outputs import has_new_work
from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter
from harness.compaction import SUMMARY_OUTPUT_TOKENS
from harness.contracts import artifact_hash
from harness.definitions import DEFINITIONS
from harness.event_store import Command
from harness.models import EventType, canonical_hash, json_dumps
from harness.engine import StepLimits
from harness.projection import saved_decisions
from harness.proposals import answer_turn, ask_turn, delivery_turn, product_spec, review_turn
from harness.providers.call import CallUsage, ModelResponse, ModelStreamEvent
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
# 只用来防止测试一直等待，按 #107 的裁定（架构师 2026-09-27 16:55，docs/archive/architecture-issues-2026-09-10.md）
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


def _tight_window_runner(tmp_path, respond, *, headroom=1600, task="Original intent",
                         keys=("product", "engineering", "quality")):
    """窗口按固定材料的实测 token 数加余量推出（测试分层设计第 10 节第 3 条，不写死窗口）：

    历史超过压缩阈值，而未压缩的工作请求仍放得下。余量低于实测的可行区间时未压缩的工作请求放不下
    （这一步以 context_overflow 结束），高于区间时压缩不会被触发。假模型按脚本位取用，
    询问分支的脚本位是「部门:ask」（工单 #473）。
    """
    adapter = FakeAdapter({key: [respond] * 200 for key in keys})
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    measure_id = system.create_run(task, context_window=1_000_000)
    run_id = system.create_run(task, context_window=pinned_input_tokens(system, measure_id) + headroom)
    system.workspace(run_id).write_file("large.txt", "TOOL_OUTPUT " * 340)
    system.workspace(run_id).write_file("small.txt", "SMALL_TOOL_OUTPUT " * 4)
    return system, adapter, run_id


def test_a_compaction_failure_in_an_ask_branch_does_not_make_it_unanswerable(tmp_path):
    """询问分支里的整理失败一次、下一次成功：询问拿到回答，不是「没能回答」（工单 #1155）。"""
    work_counts = {}
    branch_compactions = 0

    def respond(request):
        nonlocal branch_compactions
        branch = request.session_id.startswith("ses_ask_")
        if request.purpose == "compaction":
            if branch:
                branch_compactions += 1
                return _undeclared_tool_call(request) if branch_compactions <= 3 \
                    else ModelResponse(output=[_message(request)])
            return ModelResponse(output=[_message(request)])
        count = work_counts.get(request.activation_id, 0)
        work_counts[request.activation_id] = count + 1
        if request.department == "engineering":
            if count == 0:
                return ask_turn("product", "Is uppercase output required?")
            return delivery_turn()(request)
        if request.department == "quality":
            return review_turn("release", "checks passed on the current snapshot")(request)
        if branch:
            # 分支的工具里没有读取，历史从产品主线接过来：主线读过一次大文件，分支的第一步就要整理
            return answer_turn("Yes, print in uppercase.")(request)
        return _read(request, "large.txt") if count == 0 else product_spec()

    system, adapter, run_id = _tight_window_runner(
        tmp_path, respond, keys=("product", "engineering", "quality", "product:ask"))
    # PRD 被接纳以后工程才开始一轮，询问在那里发出（工单 #557）
    result = system.activate_once(run_id)
    assert result.product_spec is not None
    for _ in range(4):
        if any(event.type == EventType.ASK_ANSWERED for event in system.store.list_events(run_id)):
            break
        result = system.activate_once(run_id)
        assert result.status != "failed", result.error

    events = system.store.list_events(run_id)
    answered = [event for event in events if event.type == EventType.ASK_ANSWERED]
    assert answered, "询问没有写下回答"
    assert answered[-1].payload["status"] == "answered", answered[-1].payload
    assert answered[-1].payload["answer"] == "Yes, print in uppercase."
    # 分支的整理失败过（三次尝试用完），下一步按未压缩的历史照常发工作请求，回答照常交回
    branch_failures = [event for event in events if event.type == EventType.MODEL_ATTEMPT_FAILED
                       and event.payload.get("purpose") == "compaction"
                       and str(event.session_id).startswith("ses_ask_")]
    assert [event.payload["will_retry"] for event in branch_failures] == [True, True, False]
    branch_work = [request for request in adapter.invocations
                   if request.session_id.startswith("ses_ask_") and request.purpose == "work"]
    assert branch_work and "TOOL_OUTPUT " in json_dumps(branch_work[0].input_items)
    assert "department_memory" not in json_dumps(branch_work[0].input_items)
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_compaction_request_failure_keeps_the_step_and_sends_the_work_request_uncompressed(tmp_path):
    """整理请求三次尝试都回未声明的工具调用、没有文字：没有写检查点，这一步的工作请求按未压缩的历史
    照常发出，事项不停止；下一步再次发出整理请求（工单 #1155，设计说明第 8.7 节）。"""
    work_counts = {}
    compactions = 0

    def respond(request):
        nonlocal compactions
        if request.purpose == "compaction":
            compactions += 1
            return _undeclared_tool_call(request) if compactions <= 3 else ModelResponse(output=[_message(request)])
        count = work_counts.get(request.activation_id, 0)
        work_counts[request.activation_id] = count + 1
        return _read(request, "large.txt") if count == 0 else _read(request, "small.txt") if count == 1 \
            else product_spec()

    system, adapter, run_id = _tight_window_runner(tmp_path, respond)
    result = system.activate_once(run_id)
    assert result.status != "failed", result.error

    product = [request for request in adapter.invocations if request.department == "product"]
    # 三次尝试都没有文字：作为可重试失败记录，用尽以后这一步照常发工作请求，再下一步重新整理并成功
    assert [request.purpose for request in product] == ["work", "compaction", "compaction", "compaction",
                                                       "work", "compaction", "work"]
    assert [request.attempt for request in product if request.purpose == "compaction"][:3] == [1, 2, 3]
    events = system.store.list_events(run_id)
    failed = [event for event in events if event.type == EventType.MODEL_ATTEMPT_FAILED]
    assert [(event.payload["purpose"], event.payload["will_retry"]) for event in failed] == [
        ("compaction", True), ("compaction", True), ("compaction", False)]
    assert all(event.payload["reason"] == "compaction_failed" for event in failed)
    assert not any(event.type == EventType.TOOL_STARTED and event.payload.get("name") == CORRUPT_TOOL_NAME
                   for event in events)
    # 这一步的工作请求按未压缩的历史装配：原始工具输出在，摘要不在
    kept = product[4]
    assert "TOOL_OUTPUT " in json_dumps(kept.input_items)
    assert "department_memory" not in json_dumps(kept.input_items)
    # 那几次没有写检查点：这次激活只记下延迟以后成功的那一次压缩，它在工作请求之后
    assert len(result.compactions) == 1
    recorded = next(event for event in events if event.type == EventType.COMPACTION_RECORDED)
    requested = next(event for event in events if event.type == EventType.MODEL_REQUESTED
                     and event.payload["purpose"] == "work" and event.stream_version > failed[-1].stream_version)
    assert recorded.stream_version > requested.stream_version
    # 下一个工作请求接着用摘要
    assert "department_memory" in json_dumps(product[-1].input_items)
    assert has_new_work(result, "engineering")
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_summary_text_with_an_undeclared_tool_call_is_kept_without_retry(tmp_path):
    """整理回应同时带文字与一个 bash 调用：文字成为检查点，bash 没有执行、不在下一步的有效历史里，
    原始回应能从事件里查到；这一次不重试（工单 #1155，设计说明第 8.7 节）。"""
    summary_text = "Product memory: the large file was read; keep the original requirements."

    def respond(request):
        identity = f"corrupt-{request.activation_id}-{request.step_id}"
        return ModelResponse(output=[_message(request, summary_text),
                                     {"id": identity, "call_id": identity, "type": "function_call",
                                      "name": "bash", "arguments": json_dumps({"command": "echo hi"})}])

    system, adapter, run_id, _ = _runner(tmp_path, cancelled_summary=respond, step_limits=FAST_RETRIES)
    result = system.activate_once(run_id)

    attempts = [request for request in adapter.invocations if request.purpose == "compaction"]
    # 每次整理都直接拿文字作数，没有重试：每次都是新逻辑调用的第一次尝试
    assert attempts and all(request.attempt == 1 for request in attempts)
    assert result.compactions
    assert all(record["checkpoint"]["summary"] == summary_text for record in result.compactions)
    events = system.store.list_events(run_id)
    assert not any(event.type == EventType.MODEL_ATTEMPT_FAILED and event.payload.get("purpose") == "compaction"
                   for event in events)
    # 工具调用没有执行，也不在下一步的有效历史里
    assert not any(event.type == EventType.TOOL_STARTED and event.payload.get("name") == "bash" for event in events)
    assert "corrupt-" not in json_dumps(department_history(system, run_id, "product"))
    assert "corrupt-" not in json_dumps(adapter.invocations[-1].input_items)
    # 原始回应留作证据：丢掉了哪一个工具调用查得到
    evidence = [event for event in events if event.type == EventType.MODEL_MESSAGE
                and event.payload.get("response_id", "").startswith("corrupt-")]
    assert len(evidence) == len(attempts)
    saved = [json.loads(system.artifacts.get_text(event.payload["message_ref"]["content_hash"]))
             for event in evidence]
    assert all(item["type"] == "function_call" and item["name"] == "bash" for item in saved)
    assert not any(event.type == EventType.TOOL_CALLED and event.payload.get("name") == "bash" for event in events)
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_mixed_compaction_failures_enter_recovery_at_the_stall_limit_with_the_last_reason(tmp_path):
    """同一会话的整理连续失败（请求失败与「摘要为空」混在一起）达到 compaction.stalled_limit：
    事项进入待恢复，待恢复的决定请求写明连续的次数与最后一次的原因；答「停止事项」时以
    compaction_failed 结束（工单 #1155、#1238，设计说明第 8.7 节最后一条）。"""
    limit = DEFINITIONS.rule_value("compaction.stalled_limit")
    compactions = 0

    def respond(request):
        nonlocal compactions
        if request.purpose == "compaction":
            compactions += 1
            # 前三次是同一逻辑调用的三次尝试，都回未声明的工具调用；之后每次整理都回空摘要
            return _undeclared_tool_call(request) if compactions <= 3 else ModelResponse(output=[_message(request, "")])
        return _read(request, "large.txt")

    system, adapter, run_id = _tight_window_runner(tmp_path, respond)
    result = system.activate_once(run_id)

    # 达到上限：run 停在待恢复，没有结束
    assert (result.status, result.stop_reason) == ("running", None)
    [decision] = saved_decisions(system.store, statuses=("open",))[1]
    assert decision.request["reason"] == "compaction_failed"
    assert f"连续 {limit} 次没有推进" in decision.request["message"]
    assert "摘要为空或超过上限" in decision.request["message"]
    # 请求失败的那一次与两次空摘要计入同一个次数；停下以后不再发出新的整理请求
    assert compactions == 3 + limit - 1
    assert not result.compactions
    # 答「停止事项」：事项以 compaction_failed 结束，停止说明写明连续的次数与最后一次的原因
    _answer_recovery(system, "stop")
    failed = system.project(run_id)
    assert (failed.status, failed.stop_reason) == ("failed", "compaction_failed")
    assert f"连续 {limit} 次没有推进" in (failed.error or "")
    assert failed.canonical_state() == system.replay(run_id).canonical_state()


def test_a_compaction_that_progresses_clears_the_stall_count(tmp_path):
    """中间有一次推进时计数归零：不生效的次数加起来超过 compaction.stalled_limit，但中间推进过一次，
    事项不因此停止（工单 #1155）。"""
    limit = DEFINITIONS.rule_value("compaction.stalled_limit")
    work_counts = {}
    logical_calls = 0

    def respond(request):
        nonlocal logical_calls
        if request.purpose == "compaction":
            if request.attempt == 1:
                logical_calls += 1
            # 第一次整理失败，第二次推进，第三次与第四次不生效，第五次起再推进
            if logical_calls == 1:
                return _undeclared_tool_call(request)
            if logical_calls == 2 or logical_calls >= 5:
                return ModelResponse(output=[_message(request)])
            return ModelResponse(output=[_message(request, "")])
        count = work_counts.get(request.activation_id, 0)
        work_counts[request.activation_id] = count + 1
        return _read(request, "large.txt") if count < 3 else product_spec()

    system, adapter, run_id = _tight_window_runner(tmp_path, respond)
    result = system.activate_once(run_id)

    assert result.status != "failed", result.error
    # 失败的次数加起来超过上限，中间那一次推进把计数清零
    assert logical_calls >= limit + 2
    assert result.compactions
    assert has_new_work(result, "engineering")
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_truncated_summary_is_not_adopted_and_the_run_stops_on_overflow(tmp_path):
    """被输出上限截断的整理回应是一次终局的上游回应：不采用、不重试、不写检查点。这一次压缩因此不生效
    （设计说明第 8.7 节第一条），这一步的工作请求按未压缩的历史装配；这个窗口里放不下，所以按第 8.7 节
    第三条以上下文超限结束，而不是把整项按模型服务故障停下（工单 #1213）。"""
    def truncated(request):
        item = _message(request, "Decisions: the first half of the memory and then")
        item["status"] = "incomplete"
        return ModelResponse(output=[item], finish_reason="incomplete", error="max_output_tokens")

    system, adapter, run_id, _ = _runner(tmp_path, cancelled_summary=truncated, step_limits=FAST_RETRIES)
    result = system.activate_once(run_id)

    # 停止原因来自「未压缩的历史放不下」，不是单次调用的失败分类（归类在 #604）
    assert result.status == "failed" and result.stop_reason == "context_overflow", result.error
    assert not result.compactions
    attempts = [request for request in adapter.invocations if request.purpose == "compaction"]
    assert len(attempts) == 1
    events = system.store.list_events(run_id)
    assert not any(event.type == EventType.COMPACTION_RECORDED for event in events)
    assert not any(event.type == EventType.MODEL_RETRY_SCHEDULED for event in events)
    failed = [event for event in events if event.type == EventType.MODEL_ATTEMPT_FAILED]
    assert len(failed) == 1 and failed[0].payload["purpose"] == "compaction"
    assert failed[0].payload["reason"] == "provider_error"
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
    # 上下文窗口按这个场景的需要设置（测试分层设计说明第 10 节第 3 条）：开始时的请求（部门提示与
    # 工程可用的工具说明）装得下、留出余量，压缩只发生在询问带回新合同以后；窗口不随工具说明的长短调整
    run_id = system.create_run("build echo", context_window=7000)
    for index in range(1, read_count + 1):
        system.workspace(run_id).write_file(f"part{index}.txt", "x" * 1200)

    first = system.activate_once(run_id)
    assert first.product_spec is not None and first.product_spec.revision == 1
    second = system.activate_once(run_id)
    assert second.product_spec is not None and second.product_spec.revision == 2

    compactions = second.compactions
    assert len(compactions) >= 2, compactions
    contract = artifact_hash(system.project(run_id).effective_contract)
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


def test_reported_upstream_usage_triggers_compaction_when_the_local_estimate_does_not(tmp_path):
    """上一次工作请求上游回报的用量超过压缩阈值、本地估算没有超过：下一步先发出整理请求；
    压缩以后历史换成摘要，不再因为压缩之前的回报用量重复压缩（设计说明第 8.2 节、第 8.4 节）。"""
    window = {}
    work_counts = {}

    def respond(request):
        if request.purpose == "compaction":
            return ModelResponse(output=[_message(request)])
        count = work_counts.get(request.activation_id, 0)
        work_counts[request.activation_id] = count + 1
        if count == 0:
            # 上游回报：这次请求用满了窗口；本地估算远低于阈值（只读了小文件）
            return _read(request, "small.txt").model_copy(
                update={"usage": CallUsage(input_tokens=window["value"], reported=True)})
        return product_spec()

    adapter = FakeAdapter({"product": [respond] * 200})
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    measure_id = system.create_run("Original intent", context_window=1_000_000)
    window["value"] = pinned_input_tokens(system, measure_id) + 1600
    run_id = system.create_run("Original intent", context_window=window["value"])
    system.workspace(run_id).write_file("small.txt", "SMALL_TOOL_OUTPUT " * 4)
    result = system.activate_once(run_id)

    product = [request for request in adapter.invocations if request.department == "product"]
    assert [request.purpose for request in product] == ["work", "compaction", "work"]
    assert result.compactions and result.product_spec is not None
    # 请求事件记下判断用的两项数值：本地估算与上一次工作请求的上游回报用量
    assembled = [event.payload for event in system.store.list_events(run_id)
                 if event.type == EventType.CONTEXT_ASSEMBLED and event.department == "product"]
    assert assembled[0]["previous_usage_tokens"] is None
    assert assembled[1]["purpose"] == "compaction"
    assert assembled[1]["previous_usage_tokens"] == window["value"]
    assert assembled[1]["input_token_estimate"] < window["value"] * 85 // 100
    # 压缩以后这一步只用本地估算：压缩之前的回报用量不再算进来
    assert assembled[2]["purpose"] == "work" and assembled[2]["previous_usage_tokens"] is None
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_repeated_empty_summaries_enter_recovery_at_the_stall_limit(tmp_path):
    """整理每次都返回空摘要：连续 compaction.stalled_limit 次没有推进以后进入待恢复，答「停止事项」
    时以压缩失败结束（工单 #840、#1238）。"""
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

    # 连续达到上限以后进入待恢复，不是结束运行
    assert (result.status, result.stop_reason) == ("running", None)
    [decision] = saved_decisions(system.store, statuses=("open",))[1]
    assert decision.request["reason"] == "compaction_failed"
    # 待恢复的说明写明连续的次数与最后一次的原因
    assert f"连续 {limit} 次没有推进" in decision.request["message"]
    assert "摘要为空" in decision.request["message"]
    # 停下以后不再发出新的压缩请求
    assert len(compaction_requests) == limit
    assert not result.compactions
    assert not any(event.type == EventType.COMPACTION_RECORDED
                   for event in system.store.list_events(run_id))
    _answer_recovery(system, "stop")
    failed = system.project(run_id)
    assert (failed.status, failed.stop_reason) == ("failed", "compaction_failed")
    assert failed.canonical_state() == system.replay(run_id).canonical_state()


# 工单 #1213：整理请求自己的失败不止「回应带未声明的工具调用」一种。空响应（上游流正常结束却没有
# 输出项）与请求失败（上游故障、连接失败）都按设计说明第 8.7 节第一条处理：这一次压缩不生效、
# 不写检查点，这一步的工作请求按未压缩的历史照常发送，下一步再次尝试压缩。


def _empty_output_failure():
    # 上游流正常结束却没有输出项：Provider 给出的可重试失败（工单 #305），整理请求收到它算一次请求失败
    return ProviderError("Model response contained no output items", reason="empty_output", retryable=True,
                         diagnostics={"error_type": "empty_output", "finish_reason": "completed",
                                      "usage_reported": False, "output_tokens": None,
                                      "max_output_tokens": 4096, "has_reasoning": False})


def _upstream_unavailable_failure():
    # 上游 5xx：可重试的请求失败，三次尝试用完以后交给内核（工单 #305）
    return ProviderError("Upstream returned 503", reason="provider_unavailable", retryable=True,
                         diagnostics={"error_type": "http_status", "status": 503})


def test_empty_summary_replies_keep_the_step_and_send_the_work_request_uncompressed(tmp_path):
    """整理请求三次尝试都回空响应（没有输出项）：没有写检查点，这一步的工作请求按未压缩的历史照常
    发出，事项不停止；下一步再次发出整理请求并成功（工单 #1213，设计说明第 8.7 节第一条）。"""
    work_counts = {}
    compactions = 0

    def respond(request):
        nonlocal compactions
        if request.purpose == "compaction":
            compactions += 1
            return _empty_output_failure() if compactions <= 3 else ModelResponse(output=[_message(request)])
        count = work_counts.get(request.activation_id, 0)
        work_counts[request.activation_id] = count + 1
        return _read(request, "large.txt") if count == 0 else _read(request, "small.txt") if count == 1 \
            else product_spec()

    system, adapter, run_id = _tight_window_runner(tmp_path, respond)
    result = system.activate_once(run_id)
    assert result.status != "failed", result.error

    product = [request for request in adapter.invocations if request.department == "product"]
    # 三次空响应作为可重试失败记录，用尽以后这一步照常发工作请求，再下一步重新整理并成功
    assert [request.purpose for request in product] == ["work", "compaction", "compaction", "compaction",
                                                        "work", "compaction", "work"]
    assert [request.attempt for request in product if request.purpose == "compaction"][:3] == [1, 2, 3]
    events = system.store.list_events(run_id)
    failed = [event for event in events if event.type == EventType.MODEL_ATTEMPT_FAILED]
    assert [(event.payload["purpose"], event.payload["will_retry"]) for event in failed] == [
        ("compaction", True), ("compaction", True), ("compaction", False)]
    assert [event.payload["reason"] for event in failed] == ["empty_output"] * 3
    assert all(event.payload["diagnostics"]["error_type"] == "empty_output" for event in failed)
    # 这一步的工作请求按未压缩的历史装配：原始工具输出在，摘要不在
    kept = product[4]
    assert "TOOL_OUTPUT " in json_dumps(kept.input_items)
    assert "department_memory" not in json_dumps(kept.input_items)
    # 空响应那三次没有写检查点：这次激活只记下延迟以后成功的那一次压缩，它在工作请求之后
    assert len(result.compactions) == 1
    recorded = next(event for event in events if event.type == EventType.COMPACTION_RECORDED)
    requested = next(event for event in events if event.type == EventType.MODEL_REQUESTED
                     and event.payload["purpose"] == "work" and event.stream_version > failed[-1].stream_version)
    assert recorded.stream_version > requested.stream_version
    # 下一个工作请求接着用摘要
    assert "department_memory" in json_dumps(product[-1].input_items)
    assert has_new_work(result, "engineering")
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_mixed_empty_and_failed_compaction_requests_enter_recovery_at_the_stall_limit(tmp_path):
    """同一会话的整理连续失败（空响应与请求失败混在一起）达到 compaction.stalled_limit：事项进入
    待恢复，待恢复的说明写明连续的次数与最后一次的原因，答「停止事项」时以 compaction_failed 结束
    （工单 #1213、#1238）。"""
    limit = DEFINITIONS.rule_value("compaction.stalled_limit")
    work_counts = {}
    compactions = 0

    def respond(request):
        nonlocal compactions
        if request.purpose == "compaction":
            compactions += 1
            # 每次逻辑调用的第一次尝试回空响应，后两次回上游 503：一个逻辑调用三次尝试用完，记一次没有推进
            return _empty_output_failure() if compactions % 3 == 1 else _upstream_unavailable_failure()
        # 第一次读大文件把历史顶过压缩阈值；之后的步骤只添一点点历史，未压缩的工作请求仍放得下
        count = work_counts.get(request.activation_id, 0)
        work_counts[request.activation_id] = count + 1
        return _read(request, "large.txt") if count == 0 else _read(request, "small.txt")

    system, adapter, run_id = _tight_window_runner(tmp_path, respond)
    result = system.activate_once(run_id)

    assert (result.status, result.stop_reason) == ("running", None)
    [decision] = saved_decisions(system.store, statuses=("open",))[1]
    assert decision.request["reason"] == "compaction_failed"
    # 待恢复的说明写明连续的次数与最后一次的原因
    assert f"连续 {limit} 次没有推进" in decision.request["message"]
    assert "Upstream returned 503" in decision.request["message"]
    # 空响应与请求失败计入同一个次数，停下以后不再发出新的整理请求
    assert compactions == 3 * limit
    assert not result.compactions
    assert not any(event.type == EventType.COMPACTION_RECORDED for event in system.store.list_events(run_id))
    _answer_recovery(system, "stop")
    failed = system.project(run_id)
    assert (failed.status, failed.stop_reason) == ("failed", "compaction_failed")
    assert failed.canonical_state() == system.replay(run_id).canonical_state()


def test_the_work_request_after_a_failed_compaction_fails_on_its_own_path(tmp_path):
    """整理请求失败以后紧接着的工作请求如果自己也失败：它走普通的请求失败路径停下，不在别处被吞成
    「这一次压缩不生效」（工单 #1213「改完反问一句」，设计说明第 8.7 节第一条只讲整理请求）。"""
    compactions = 0

    def respond(request):
        nonlocal compactions
        if request.purpose == "compaction":
            compactions += 1
            return _empty_output_failure()
        # 第一次工作请求读到的大文件把历史顶过压缩阈值；之后的工作请求同样回空响应，用尽三次停止
        return _read(request, "large.txt") if compactions == 0 else _empty_output_failure()

    system, adapter, run_id = _tight_window_runner(tmp_path, respond)
    result = system.activate_once(run_id)

    assert result.status == "failed" and result.stop_reason == "provider_error", result.error
    assert "no output items" in (result.error or "")
    assert compactions == 3
    work = [request for request in adapter.invocations
            if request.department == "product" and request.purpose == "work"]
    assert [request.attempt for request in work[1:]] == [1, 2, 3]
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_compaction_request_overflow_still_stops_the_run(tmp_path):
    """整理请求的失败原因是 context_overflow 时照旧以上下文超限停止，不被吞成「不生效」（工单 #1213，
    设计说明第 8.7 节第三条）。"""
    def respond(request):
        if request.purpose == "compaction":
            return ProviderError("prompt is too long", reason="context_overflow", retryable=False,
                                 diagnostics={"error_type": "context_length"})
        return _read(request, "large.txt")

    system, adapter, run_id = _tight_window_runner(tmp_path, respond)
    result = system.activate_once(run_id)

    assert result.status == "failed" and result.stop_reason == "context_overflow", result.error
    # 没有走「不生效」那条路：一次请求就停下，不再重试也不再整理
    assert len([request for request in adapter.invocations if request.purpose == "compaction"]) == 1
    assert not result.compactions
    # 上下文超限不进入待恢复（工单 #1238）：没有待回答的决定请求
    assert not saved_decisions(system.store, statuses=("open",))[1]
    assert result.canonical_state() == system.replay(run_id).canonical_state()


# ---------------------------------------------------------------------------
# 整理连续失败进入待恢复（工单 #1238，模型管理设计说明第 8.7 节最后一条）
#
# 交付已经收下以后，质检的整理连续没有推进：run 不结束，进入待恢复，发出待恢复的决定请求（reason 为
# compaction_failed）。用户可以换这个部门的模型以后选「继续执行」，事项从这次整理接着进行；选「停止事项」
# 时事项以 compaction_failed 结束。

def _delivery_then_stalled_quality(tmp_path, *, stall_compactions: int):
    """交付已收下、质检的整理连续不生效的运行：产品提出 PRD，工程交付（交付被收下），质检的第一步读一个
    大文件把历史顶过压缩阈值，之后的整理都回空摘要（不生效）；前 stall_compactions 次整理这样回，
    之后回真正的摘要。质检提交放行结论的那一轮在读完文件以后的第四步，整理出事的这几步到不了。

    窗口在交付收下以后按质检部门的固定材料实测 token 数加余量推出（测试分层设计第 10 节第 3 条，
    不写死数字）：质检的固定材料里有 PRD 与交付，交付之前量不全。
    """
    work_counts = {}
    compactions = []
    state = {"large_read": False}

    def respond(request):
        if request.purpose == "compaction":
            compactions.append(request)
            return ModelResponse(output=[_message(request, "")]) if len(compactions) <= stall_compactions \
                else ModelResponse(output=[_message(request)])
        count = work_counts.get(request.activation_id, 0)
        work_counts[request.activation_id] = count + 1
        if request.department == "quality":
            if "delivery_spec" not in json_dumps(request.input_items):
                # 还没有交付：预测性探索，提交的结论被拒绝，这一轮在这里结束
                return review_turn("release", "还没有交付可以核验")(request)
            if not state["large_read"]:
                state["large_read"] = True
                return _read(request, "large.txt")
            if count >= 3:
                return review_turn("release", "checks passed on the current snapshot")(request)
            return _read(request, "small.txt")
        if request.department == "engineering":
            return delivery_turn()(request)
        return product_spec()

    adapter = FakeAdapter({department: [respond] * 200 for department in ("product", "engineering", "quality")})
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=FAST_RETRIES)
    run_id = system.create_run("Original intent", context_window=1_000_000)
    system.workspace(run_id).write_file("large.txt", "TOOL_OUTPUT " * 340)
    system.workspace(run_id).write_file("small.txt", "SMALL_TOOL_OUTPUT " * 4)
    return system, adapter, run_id, compactions


def _delivery_accepted(system, run_id):
    # 驱动到交付被收下：之后才量得出质检的固定材料，量出来再声明这次运行的窗口
    for _ in range(6):
        system.activate_once(run_id)
        if system.project(run_id).delivery_specs:
            break
    projection = system.project(run_id)
    assert (projection.status, len(projection.delivery_specs)) == ("running", 1)
    system.orchestrator._test_context_windows[run_id] = pinned_input_tokens(system, run_id, "quality") + 1600
    return projection


def _answer_recovery(system, option: str) -> str | None:
    # 只经公开接口回答待恢复：按保存的投影取未回答的决定请求，经流程编排的回答入口回答
    [decision] = list(saved_decisions(system.store, statuses=("open",))[1])
    command = Command(str(uuid.uuid4()), "decision.answer", f"sha256:{option}:{decision.version}", "user:local")
    return system.orchestrator.answer_decision(decision.decision_id, option, None,
                                               base_version=decision.version, command=command)


def test_a_compaction_stall_after_the_delivery_enters_recovery_and_keeps_the_delivery(tmp_path):
    """整理连续 compaction.stalled_limit 次没有推进：run 进入待恢复，有一条待回答的决定请求（reason 为
    compaction_failed），停在这次整理之前；已经收下的交付与已完成的工作都还在投影里（工单 #1238）。"""
    limit = DEFINITIONS.rule_value("compaction.stalled_limit")
    system, adapter, run_id, compactions = _delivery_then_stalled_quality(tmp_path, stall_compactions=limit)
    _delivery_accepted(system, run_id)
    # 质检读大文件、整理连续不生效
    result = system.activate_once(run_id)

    # 待恢复：run 没有结束，有一条未回答、阻塞整个 run 的决定请求
    assert (result.status, result.stop_reason) == ("running", None)
    [decision] = saved_decisions(system.store, statuses=("open",))[1]
    assert (decision.kind, decision.request["blocks"], decision.request["department"]) == \
        ("model_unavailable", "run", "quality")
    assert decision.request["reason"] == "compaction_failed"
    # 说明写明部门、模型、连续的次数与最后一次的原因
    assert decision.request["department"] == "quality"
    assert decision.request["target"]["requested_model"]
    assert f"连续 {limit} 次没有推进" in decision.request["description"]
    assert "摘要为空或超过上限" in decision.request["description"]
    # 已收下的交付与已完成的工作都在
    assert len(result.delivery_specs) == 1 and result.delivery_spec is not None
    assert result.product_spec is not None
    # 停在这次整理之前：达到上限以后不再发整理请求，也没有运行失败
    assert len(compactions) == limit
    assert not any(event.type == EventType.RUN_FAILED for event in system.store.list_events(run_id))
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_answering_continue_after_a_compaction_stall_clears_the_stall_count(tmp_path):
    """答「继续执行」：连续次数清零（这一轮从零数），部门重新整理并写下检查点，事项继续；清零的证据是
    之后又失败了两次也没有再次进入待恢复，第三次整理成功以后事项走到放行（工单 #1238）。"""
    limit = DEFINITIONS.rule_value("compaction.stalled_limit")
    system, adapter, run_id, compactions = _delivery_then_stalled_quality(tmp_path,
                                                                         stall_compactions=limit + 2)
    _delivery_accepted(system, run_id)
    system.activate_once(run_id)
    assert len(compactions) == limit
    failed_so_far = len(system.project(run_id).compactions)

    assert _answer_recovery(system, "continue") == run_id
    assert not saved_decisions(system.store, statuses=("open",))[1]
    result = system.activate_once(run_id)

    # 清零：又失败两次（达到上限要三次）没有再次进入待恢复，第三次整理成功，事项从这次整理接着走
    assert (result.status, result.stop_reason) != ("failed", "compaction_failed"), result.error
    assert len(compactions) >= limit + 3
    assert len(result.compactions) > failed_so_far
    assert not saved_decisions(system.store, statuses=("open",))[1]
    # 已收下的交付与已完成的工作都还在
    assert len(result.delivery_specs) == 1 and result.product_spec is not None
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_answering_stop_at_a_compaction_stall_ends_the_run_with_compaction_failed(tmp_path):
    """答「停止事项」：事项以 compaction_failed 结束，停止说明写明连续的次数与最后一次的原因；
    已收下的交付留在投影里，不再发出整理请求（工单 #1238）。"""
    limit = DEFINITIONS.rule_value("compaction.stalled_limit")
    system, adapter, run_id, compactions = _delivery_then_stalled_quality(tmp_path, stall_compactions=limit)
    _delivery_accepted(system, run_id)
    system.activate_once(run_id)
    assert len(compactions) == limit

    assert _answer_recovery(system, "stop") is None
    projection = system.project(run_id)

    assert (projection.status, projection.stop_reason) == ("failed", "compaction_failed")
    assert f"连续 {limit} 次没有推进" in (projection.error or "")
    assert "摘要为空或超过上限" in (projection.error or "")
    assert len(projection.delivery_specs) == 1
    events = system.store.list_events(run_id)
    [failed_event] = [event for event in events if event.type == EventType.RUN_FAILED]
    assert failed_event.stop_reason == "compaction_failed"
    assert events[events.index(failed_event) - 1].type == EventType.DECISION_ANSWERED
    # 结束以后不再开始新的激活，也不再整理
    system.activate_once(run_id)
    assert len(compactions) == limit
    assert projection.canonical_state() == system.replay(run_id).canonical_state()
