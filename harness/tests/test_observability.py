"""Deterministic W1 model-attempt collection and read-only query checks.

旧控制台的模型尝试/用量/部门视图路由已经删除，这里的场景改由应用层查询验证：
project.attempts、project.usage、run.attempt、department.workspace 与 run.export
（对照 harness/tests/test_project_queries.py 与 test_issue_92.py 的同类覆盖）。
"""

from __future__ import annotations

import json
import math
import threading
from pathlib import Path

import pytest

from harness.app.application import Application
from harness.app.project_queries import (
    DepartmentWorkspace,
    ProjectAttempts,
    ProjectFlow,
    ProjectUsage,
    RunAttempt,
    RunExport,
    WorkItemMaterials,
)
from harness.artifacts import ArtifactStore
from harness.adapters.base import Availability, ProviderError
from harness.event_store import EventStore
from harness.providers.call import ModelResponse, ModelStreamEvent
from harness.tests.protocol_helpers import ResponsesAdapter
from harness.engine import StepLimits
from harness.models import ArtifactRef, EventType, Usage
from harness.runtime import LoopSystem
from harness.tests.helpers import happy_script
from harness.tests.saved_rewrite import rewrite_saved_event
from harness.tests.test_responses import _event, _response, _send, _server, _stream, _submit_stream
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.proposals import product_spec

GOAL = "把文本按行处理清楚"

def _app(system: LoopSystem) -> Application:
    return Application(system)

def _project_run(system: LoopSystem, task: str = "观察尝试") -> tuple[Application, str, str, str]:
    # 一个项目与一个事项：应用层查询按项目与事项读取读取模型
    project_id = system.projects.register("观测", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, task)
    application = _app(system)
    return application, project_id, work_item_id, run_id

def _attempts(application: Application, project_id: str, work_item_id: str, **filters):
    return application.query("project.attempts", ProjectAttempts(
        project_id=project_id, work_item=work_item_id, **filters))

def _usage(application: Application, project_id: str, work_item_id: str, **filters):
    return application.query("project.usage", ProjectUsage(
        project_id=project_id, work_item=work_item_id, **filters))

class _BlockingPartialAdapter:
    name = "stub"
    model = "stub-model"

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def availability(self):
        return Availability(True)

    def cancel(self, _attempt_id):
        self.release.set()

    async def stream(self, call):
        item = {
            "id": "partial-message",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "PARTIAL_OUTPUT"}],
        }
        yield ModelStreamEvent(kind="message", id=item["id"], payload=item, text="PARTIAL_OUTPUT",
                               provider=self.name, model=self.model)
        self.started.set()
        self.release.wait(5)
        yield ModelResponse(
            finish_reason="aborted", error="aborted",
            provider=self.name, model=self.model,
        )

def test_fake_run_exposes_attempt_identity_and_keeps_missing_usage_null(tmp_path: Path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(happy_script()))
    application, project_id, work_item_id, run_id = _project_run(system)
    system.run_until_stop(run_id)
    before = system.project(run_id).stream_version

    listing = _attempts(application, project_id, work_item_id, limit=1)
    assert listing.data.attempts
    assert listing.data.cursor
    first = listing.data.attempts[0]
    assert first.status == "success"
    assert first.attempt_id
    assert first.usage["input_tokens"] is None
    assert first.usage["total_tokens"] is None
    assert len(_attempts(application, project_id, work_item_id).data.attempts) == 4

    usage = _usage(application, project_id, work_item_id)
    assert usage.data.totals.attempts == 4
    assert usage.data.totals.reported == 0
    assert usage.data.totals.total_tokens is None
    assert usage.data.totals.cost is None
    assert usage.data.departments
    assert system.project(run_id).stream_version == before

def test_stream_artifact_cleanup_closes_temp_file_before_cleanup(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")

    def broken_chunks():
        yield b"first"
        raise OSError("stream stopped")

    with pytest.raises(OSError, match="stream stopped"):
        store.put_stream("run", "sdk_stream_events", broken_chunks())
    assert not list((tmp_path / "artifacts" / "run").glob(".stream-*"))

def _submit_call() -> dict:
    proposal = product_spec()
    proposal.pop("kind")
    return {"id": "fc-submit", "type": "function_call", "name": "submit_product_spec", "call_id": "call-submit",
            "arguments": json.dumps(proposal), "status": "completed"}

def test_invalid_usage_numbers_are_unknown_in_queries(tmp_path: Path):
    # 模型提供方上报的用量中的负数、小数与无穷大在查询中都是未知，0 保持为 0
    raw_usage = {
        "input_tokens": -1,
        "output_tokens": 1.5,
        "total_tokens": -3,
        "input_tokens_details": {"cached_tokens": math.inf, "cache_write_tokens": 0},
        "cost": -0.1,
        "currency": "CNY",
    }
    with _server([_stream([_submit_call()], usage=raw_usage, response_id="resp-invalid-usage")]) as (config, *_):
        system = LoopSystem.for_testing(tmp_path, ResponsesAdapter(config))
        application, project_id, work_item_id, run_id = _project_run(system, "invalid usage numbers")
        system.activate_once(run_id)

    row = _attempts(application, project_id, work_item_id).data.attempts[0]
    assert row.status == "success"
    # 保存的原始用量保留提供方上报的数值
    detail = application.query("run.attempt", RunAttempt(run_id=run_id, attempt_id=row.attempt_id))
    raw_ref = detail.data.artifact_refs["usage"]
    raw = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**raw_ref)))["usage"]
    assert (raw["input_tokens"], raw["output_tokens"], raw["total_tokens"], raw["cost"]) == (-1, 1.5, -3, -0.1)
    normalized = row.usage
    assert normalized["source"] == "reported"
    assert normalized["input_tokens"] is None
    assert normalized["output_tokens"] is None
    assert normalized["cache_read_tokens"] is None
    assert normalized["cache_write_tokens"] == 0
    assert normalized["total_tokens"] is None
    assert normalized["cost"] is None

def test_invalid_usage_numbers_in_saved_usage_summaries_are_unknown(tmp_path: Path):
    # 没有原始用量时按事件中保存的用量摘要读取：负数同样是未知，0 保持为 0
    usage = Usage(input_tokens=-1, output_tokens=-2, total_tokens=-3, cost=-0.1, cost_reported=True)
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([FakeTurn(proposal=product_spec(), usage=usage)]))
    application, project_id, work_item_id, run_id = _project_run(system, "negative usage summary")
    system.activate_once(run_id)

    row = _attempts(application, project_id, work_item_id).data.attempts[0]
    detail = application.query("run.attempt", RunAttempt(run_id=run_id, attempt_id=row.attempt_id))
    assert detail.data.artifact_refs["usage"] is None
    normalized = row.usage
    assert normalized["source"] == "reported"
    assert normalized["input_tokens"] is None
    assert normalized["output_tokens"] is None
    assert normalized["total_tokens"] is None
    assert normalized["cost"] is None
    assert normalized["cache_read_tokens"] == 0
    assert normalized["cache_write_tokens"] == 0

def test_cancelled_attempt_is_independently_filterable(tmp_path: Path):
    adapter = _BlockingPartialAdapter()
    system = LoopSystem.for_testing(tmp_path, adapter)
    application, project_id, work_item_id, run_id = _project_run(system, "cancelled attempt")
    worker = threading.Thread(target=system.activate_once, args=(run_id,), daemon=True)
    worker.start()
    assert adapter.started.wait(3)
    system.cancel(run_id)
    worker.join(timeout=3)
    assert not worker.is_alive()

    row = _attempts(application, project_id, work_item_id).data.attempts[0]
    assert row.status == "cancelled"
    assert row.stage == "cancelled"
    assert len(_attempts(application, project_id, work_item_id, status="cancelled").data.attempts) == 1
    assert _attempts(application, project_id, work_item_id, status="failed").data.attempts == []
    assert _usage(application, project_id, work_item_id, status="cancelled").data.totals.attempts == 1

def test_running_partial_output_is_in_attempt_detail_and_is_observation_only(tmp_path: Path):
    adapter = _BlockingPartialAdapter()
    system = LoopSystem.for_testing(tmp_path, adapter)
    application, project_id, work_item_id, run_id = _project_run(system, "partial attempt")
    worker = threading.Thread(target=system.activate_once, args=(run_id,), daemon=True)
    worker.start()
    assert adapter.started.wait(3)

    row = _attempts(application, project_id, work_item_id).data.attempts[0]
    assert row.status == "running"
    assert row.stage == "partial"
    assert row.usage["source"] in {"missing", "unknown"} or row.usage["reported"] is False
    detail = application.query("run.attempt", RunAttempt(run_id=run_id, attempt_id=row.attempt_id))
    assert detail.data.attempt["partial_output"] is True
    assert detail.data.attempt["output_item_count"] == 1
    assert detail.data.response is None

    system.cancel(run_id)
    worker.join(timeout=3)
    assert not worker.is_alive()
    cancelled = application.query("run.attempt", RunAttempt(run_id=run_id, attempt_id=row.attempt_id))
    assert cancelled.data.attempt["status"] == "cancelled"
    assert cancelled.data.attempt["partial_output"] is True
    # 部分输出只作为调用尝试的观察保留，不产生任何被接纳的材料
    materials = application.query("work_item.materials", WorkItemMaterials(
        project_id=project_id, work_item=work_item_id))
    assert materials.data.contracts == [] and materials.data.deliveries == []

def test_failed_partial_output_is_observation_only_but_attempt_keeps_it(tmp_path: Path):
    def fail_after_message(request):
        item = {
            "id": "failed-partial-message",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "FAILED_PARTIAL_OUTPUT"}],
        }
        yield ModelStreamEvent(kind="message", id=item["id"], payload=item, text="FAILED_PARTIAL_OUTPUT",
                               provider="stub", model="stub-model")
        raise ProviderError("stream failed", retryable=False)

    system = LoopSystem.for_testing(tmp_path, FakeAdapter([fail_after_message]))
    application, project_id, work_item_id, run_id = _project_run(system, "failed partial attempt")
    system.activate_once(run_id)
    row = _attempts(application, project_id, work_item_id).data.attempts[0]
    assert row.status == "failed"
    assert row.stage == "failed"
    detail = application.query("run.attempt", RunAttempt(run_id=run_id, attempt_id=row.attempt_id))
    assert detail.data.attempt["partial_output"] is True
    # 失败的模型消息只作为调用尝试的观察保留，不产生任何被接纳的材料
    materials = application.query("work_item.materials", WorkItemMaterials(
        project_id=project_id, work_item=work_item_id))
    assert materials.data.contracts == [] and materials.data.deliveries == []

def test_unreported_normalized_usage_keeps_unknown_source_and_is_not_counted_as_reported(tmp_path: Path):
    usage = Usage(total_tokens=7, reported=False)
    system = LoopSystem.for_testing(
        tmp_path,
        FakeAdapter([FakeTurn(proposal=product_spec(), usage=usage)]),
    )
    application, project_id, work_item_id, run_id = _project_run(system, "unreported usage")
    system.activate_once(run_id)

    row = _attempts(application, project_id, work_item_id).data.attempts[0]
    assert row.usage["source"] == "unknown"
    assert row.usage["reported"] is False
    assert row.usage["total_tokens"] == 7
    # 未上报的尝试不计入已上报的覆盖计数
    report = _usage(application, project_id, work_item_id)
    assert report.data.totals.reported == 0
    assert report.data.totals.attempts == 1

def test_cost_totals_follow_reported_provider_values(tmp_path: Path):
    # 用量汇总的 cost 只累加上报的费用：未上报的尝试不计入，上报的费用按值求和
    def usage(currency: str, amount: float) -> Usage:
        return Usage(input_tokens=1, output_tokens=1, total_tokens=2, cost=amount, cost_reported=True)

    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        FakeTurn(proposal=product_spec(), usage=usage("CNY", 1.25)),
        FakeTurn(proposal=None, usage=usage("CNY", 2.75)),
    ]))
    application, project_id, work_item_id, run_id = _project_run(system, "cost totals")
    system.activate_once(run_id)
    system.activate_once(run_id)
    report = _usage(application, project_id, work_item_id)
    assert report.data.totals.reported == 2
    assert report.data.totals.input_tokens == 2

def test_usage_totals_count_only_reported_attempts(tmp_path: Path):
    # 用量汇总只累加上报的用量（设计说明第 4.3 节「未上报的项为空」，D09 规定不猜算用量）：
    # 未上报的尝试计入总数与用时，各项用量为空，也不进入上报计数
    reported_usage = Usage(input_tokens=11, output_tokens=3, cache_read_tokens=1, cache_write_tokens=2,
                           total_tokens=17, reported=True)
    unreported_usage = Usage(input_tokens=100, output_tokens=100, total_tokens=200, reported=False)
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        FakeTurn(proposal=product_spec(), usage=reported_usage),
        FakeTurn(proposal=None, usage=unreported_usage),
    ]))
    application, project_id, work_item_id, run_id = _project_run(system, "mixed usage")
    system.activate_once(run_id)
    system.activate_once(run_id)

    rows = _attempts(application, project_id, work_item_id).data.attempts
    assert [row.usage["source"] for row in rows] == ["reported", "unknown", "missing"]
    assert [row.status for row in rows] == ["success", "success", "failed"]

    report = _usage(application, project_id, work_item_id).data
    totals = report.totals
    assert totals.attempts == 3
    assert totals.reported == 1
    assert totals.input_tokens == 14
    assert totals.output_tokens == 3
    assert totals.cache_read_tokens == 1
    assert totals.cache_write_tokens == 2
    assert totals.total_tokens == 17
    assert totals.cost is None
    # 用时每次尝试都实际测到，与用量是否上报无关
    assert totals.latency_ms == sum(row.duration_ms for row in rows if row.duration_ms is not None)

    product = next(group for group in report.departments if group.key == "product")
    assert (product.attempts, product.reported, product.input_tokens, product.total_tokens) == (1, 1, 14, 17)
    engineering = next(group for group in report.departments if group.key == "engineering")
    assert (engineering.attempts, engineering.reported, engineering.input_tokens) == (2, 0, None)
    assert len(report.models) == 1
    assert (report.models[0].attempts, report.models[0].reported, report.models[0].input_tokens) == (3, 1, 14)

def test_unreported_usage_alone_leaves_every_usage_field_empty(tmp_path: Path):
    usage = Usage(input_tokens=5, output_tokens=6, total_tokens=11, reported=False)
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([FakeTurn(proposal=product_spec(), usage=usage)]))
    application, project_id, work_item_id, run_id = _project_run(system, "unreported only")
    system.activate_once(run_id)

    totals = _usage(application, project_id, work_item_id).data.totals
    assert totals.attempts == 1
    assert totals.reported == 0
    assert totals.input_tokens is None
    assert totals.output_tokens is None
    assert totals.cache_read_tokens is None
    assert totals.cache_write_tokens is None
    assert totals.total_tokens is None
    assert totals.cost is None
    assert totals.latency_ms is not None

def test_department_messages_exclude_failed_and_cancelled_attempts(tmp_path: Path):
    # 部门消息是部门上下文里的历史：失败与取消的尝试的部分输出不进入上下文，
    # 这两次尝试仍然出现在观测页（project.attempts 与 run.attempt）
    def fail_after_message(request):
        item = {
            "id": "failed-partial-message",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "FAILED_PARTIAL_OUTPUT"}],
        }
        yield ModelStreamEvent(kind="message", id=item["id"], payload=item, text="FAILED_PARTIAL_OUTPUT",
                               provider="stub", model="stub-model")
        raise ProviderError("stream failed", retryable=False)

    failed_system = LoopSystem.for_testing(tmp_path / "failed", FakeAdapter([fail_after_message]))
    application, project_id, work_item_id, run_id = _project_run(failed_system, "failed partial")
    failed_system.activate_once(run_id)

    row = _attempts(application, project_id, work_item_id).data.attempts[0]
    assert row.status == "failed"
    workspace = application.query("department.workspace", DepartmentWorkspace(
        project_id=project_id, department="product", work_item=work_item_id))
    assert not any("FAILED_PARTIAL_OUTPUT" in message["text"] for message in workspace.data.messages)
    assert not any(message["type"] == EventType.MODEL_MESSAGE for message in workspace.data.messages)

    cancelled_adapter = _BlockingPartialAdapter()
    cancelled_system = LoopSystem.for_testing(tmp_path / "cancelled", cancelled_adapter)
    application, project_id, work_item_id, run_id = _project_run(cancelled_system, "cancelled partial")
    worker = threading.Thread(target=cancelled_system.activate_once, args=(run_id,), daemon=True)
    worker.start()
    assert cancelled_adapter.started.wait(3)
    cancelled_system.cancel(run_id)
    worker.join(timeout=5)
    assert not worker.is_alive()

    row = _attempts(application, project_id, work_item_id).data.attempts[0]
    assert row.status == "cancelled"
    workspace = application.query("department.workspace", DepartmentWorkspace(
        project_id=project_id, department="product", work_item=work_item_id))
    assert not any("PARTIAL_OUTPUT" in message["text"] for message in workspace.data.messages)
    assert not any(message["type"] == EventType.MODEL_MESSAGE for message in workspace.data.messages)
    # 观测页仍然给出这次尝试与它的部分输出
    detail = application.query("run.attempt", RunAttempt(run_id=run_id, attempt_id=row.attempt_id))
    assert detail.data.attempt["status"] == "cancelled"
    assert detail.data.attempt["partial_output"] is True

def test_responses_capture_complete_sdk_json_and_decoded_events(tmp_path: Path):
    with _server([_submit_stream()]) as (config, *_):
        system = LoopSystem.for_testing(tmp_path, ResponsesAdapter(config))
        application, project_id, work_item_id, run_id = _project_run(system, "observe sdk")
        system.activate_once(run_id)

    row = _attempts(application, project_id, work_item_id).data.attempts[0]
    assert row.status == "success"
    assert row.requested_provider or row.actual_provider
    assert row.usage["input_tokens"] == 100
    assert row.usage["cache_read_tokens"] == 80
    assert row.usage["output_tokens"] == 30
    assert row.usage["total_tokens"] == 130
    assert row.usage["cache_write_tokens"] is None
    assert row.usage["latency_ms"] == row.duration_ms
    assert row.duration_ms is not None

    detail = application.query("run.attempt", RunAttempt(run_id=run_id, attempt_id=row.attempt_id))
    assert detail.data.request["model"] == "local-model"
    assert detail.data.response["id"] == "resp-submit"
    assert detail.data.artifact_refs["events"] is not None
    assert any(item["source"] == "sdk_decoded_stream" for item in detail.data.events)
    stream_events = [item for item in detail.data.events if item["source"] == "sdk_decoded_stream"]
    assert stream_events and all(item["event_group"] == "provider_stream" for item in stream_events)
    assert all(item["sequence_source"] == "provider" for item in stream_events)
    assert all("observed_at" in item for item in stream_events)
    assert all(item["time"] == item["observed_at"] for item in stream_events)
    assert detail.data.observed_scope["events"]
    assert sum(event.type == EventType.MODEL_REQUESTED for event in system.store.list_events(run_id)) == 1

def test_stream_events_keep_provider_order_and_type_in_attempt_detail(tmp_path: Path):
    # 调用尝试详情中的提供方流事件按提供方送出的先后编号，类型与原文取自事件本身，时间是收到事件的时刻
    with _server([_submit_stream()]) as (config, *_):
        system = LoopSystem.for_testing(tmp_path, ResponsesAdapter(config))
        application, project_id, work_item_id, run_id = _project_run(system, "stream order")
        system.activate_once(run_id)

    row = _attempts(application, project_id, work_item_id).data.attempts[0]
    detail = application.query("run.attempt", RunAttempt(run_id=run_id, attempt_id=row.attempt_id))
    events = [item for item in detail.data.events if item["source"] == "sdk_decoded_stream"]
    assert [item["type"] for item in events] == ["response.created", "response.output_item.done", "response.completed"]
    assert [item["sequence"] for item in events] == [0, 1, 2]
    for item in events:
        assert item["event_id"] is None
        assert item["summary"] == item["type"] == item["raw"]["type"]
        assert item["event_group"] == "provider_stream"
        assert item["sequence_source"] == "provider"
        assert item["observed_at"] is not None
        assert item["time"] == item["observed_at"]

def test_sdk_json_observation_redacts_configured_credential(tmp_path: Path):
    # 提供方回复中的凭据原文与敏感键（headers）在保存的 SDK JSON 与流事件中都被替换
    def reply(handler, _body):
        response = _response([_submit_call()], response_id="resp-redacted", error={
            "code": "server_error", "message": f"failed with {config.api_key}",
            "headers": {"authorization": config.api_key},
        })
        _send(handler, b"".join([
            _event("response.created", response={**response, "status": "in_progress", "output": [], "usage": None},
                   sequence_number=0),
            _event("response.output_item.done", item=response["output"][0], output_index=0, sequence_number=1),
            _event("response.completed", response=response, sequence_number=2),
        ]))

    with _server([reply]) as (config, *_):
        system = LoopSystem.for_testing(tmp_path, ResponsesAdapter(config))
        application, project_id, work_item_id, run_id = _project_run(system, "redacted sdk json")
        system.activate_once(run_id)

    row = _attempts(application, project_id, work_item_id).data.attempts[0]
    detail = application.query("run.attempt", RunAttempt(run_id=run_id, attempt_id=row.attempt_id))
    serialized = json.dumps(detail.data.model_dump(mode="json"), ensure_ascii=False)
    assert config.api_key not in serialized
    assert detail.data.response["error"]["headers"] == "[REDACTED]"
    assert detail.data.response["error"]["message"] == "failed with [REDACTED]"
    stream_ref = detail.data.artifact_refs["events"]
    stream_text = system.artifacts.get_for_run(run_id, ArtifactRef(**stream_ref)).decode("utf-8")
    assert config.api_key not in stream_text

def test_sse_response_message_and_stream_artifacts_are_redacted_end_to_end(tmp_path: Path):
    proposal = product_spec()
    proposal.pop("kind")
    call = {
        "id": "fc-secret-submit", "type": "function_call", "name": "submit_product_spec",
        "call_id": "call-secret-submit", "arguments": json.dumps(proposal), "status": "completed",
    }

    def reply(handler, _body):
        secret_message = {"id": "msg-secret", "type": "message", "role": "assistant",
                          "status": "completed", "content": [{"type": "output_text", "text": config.api_key}]}
        _send(handler, _stream([secret_message, call], response_id="secret-response"))

    with _server([reply]) as (config, *_):
        system = LoopSystem.for_testing(tmp_path, ResponsesAdapter(config))
        application, project_id, work_item_id, run_id = _project_run(system, "redacted observations")
        system.activate_once(run_id)
    row = _attempts(application, project_id, work_item_id).data.attempts[0]
    detail = application.query("run.attempt", RunAttempt(run_id=run_id, attempt_id=row.attempt_id))
    serialized = json.dumps(detail.data.model_dump(mode="json"), ensure_ascii=False)
    assert config.api_key not in serialized
    assert detail.data.response["id"] == "secret-response"
    assert detail.data.events
    stream_ref = detail.data.artifact_refs["events"]
    assert stream_ref is not None
    stream_text = system.artifacts.get_for_run(run_id, ArtifactRef(**stream_ref)).decode("utf-8")
    assert config.api_key not in stream_text

def test_context_parts_are_verified_and_missing_current_parts_do_not_fallback(tmp_path: Path):
    with _server([_submit_stream()]) as (config, *_):
        system = LoopSystem.for_testing(tmp_path, ResponsesAdapter(config))
        application, project_id, work_item_id, run_id = _project_run(system, "context parts")
        system.activate_once(run_id)
    row = _attempts(application, project_id, work_item_id).data.attempts[0]
    detail = application.query("run.attempt", RunAttempt(run_id=run_id, attempt_id=row.attempt_id))
    parts_ref = detail.data.context["parts_ref"]
    path = system.artifacts.root / parts_ref["path"]
    path.unlink()
    with pytest.raises(ValueError, match="context parts artifact is unavailable"):
        application.query("run.attempt", RunAttempt(run_id=run_id, attempt_id=row.attempt_id))

def test_department_prompt_reports_the_version_recorded_by_the_model_request(tmp_path: Path):
    with _server([_submit_stream()]) as (config, *_):
        system = LoopSystem.for_testing(tmp_path, ResponsesAdapter(config))
        application, project_id, work_item_id, run_id = _project_run(system, "prompt identity")
        system.activate_once(run_id)
    workspace = application.query("department.workspace", DepartmentWorkspace(
        project_id=project_id, department="product", work_item=work_item_id))
    recorded = next(item["prompt_version"] for item in system.project(run_id).model_requests
                    if item.get("department") == "product")
    assert workspace.data.department_setting.used_version == recorded

def test_generic_adapter_failure_closes_raw_capture_and_keeps_stream_evidence(tmp_path: Path):
    class BrokenAdapter:
        name = "broken"
        model = "broken-model"

        def availability(self):
            return Availability(True)

        def cancel(self, _attempt_id):
            return None

        async def stream(self, call):
            yield ModelStreamEvent(kind="stream_event", id="raw-1",
                                   payload={"type": "response.created", "response": {"model": self.model}},
                                   source="sdk_decoded_stream", sequence=0, stage="response_created",
                                   model=self.model)
            raise RuntimeError("decoder failed")

    system = LoopSystem.for_testing(tmp_path, BrokenAdapter())
    application, project_id, work_item_id, run_id = _project_run(system, "adapter failure")
    system.activate_once(run_id)
    row = _attempts(application, project_id, work_item_id).data.attempts[0]
    assert row.status == "failed"
    assert row.stage == "failed"
    assert row.actual_model == "broken-model"
    detail = application.query("run.attempt", RunAttempt(run_id=run_id, attempt_id=row.attempt_id))
    assert any(event["source"] == "sdk_decoded_stream" for event in detail.data.events)
    assert detail.data.attempt["error_class"] == "provider_error"
    assert detail.data.attempt["diagnostics"]["error_type"] == "adapter_failure"

def test_project_attempts_filters_provider_and_models(tmp_path: Path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(happy_script()))
    application, project_id, work_item_id, run_id = _project_run(system, "filter attempts")
    system.run_until_stop(run_id)
    all_rows = _attempts(application, project_id, work_item_id).data.attempts
    assert all_rows
    row = all_rows[0]
    provider = row.requested_provider
    requested = row.requested_model
    actual = row.actual_model
    assert provider
    filtered = _attempts(application, project_id, work_item_id, provider=provider).data.attempts
    assert len(filtered) == len(all_rows)
    assert _attempts(application, project_id, work_item_id, provider="missing-provider").data.attempts == []
    assert _attempts(application, project_id, work_item_id, requested_model=requested).data.attempts
    if actual:
        assert _attempts(application, project_id, work_item_id, actual_model=actual).data.attempts
        assert (_usage(application, project_id, work_item_id, actual_model=actual).data.totals.attempts
                == len(_attempts(application, project_id, work_item_id, actual_model=actual).data.attempts))
    assert _attempts(application, project_id, work_item_id, actual_model="no-such-model").data.attempts == []

def test_compaction_coverage_exposes_seq_range_and_covered_through():
    from harness.views import compaction_coverage

    coverage = compaction_coverage({
        "source_event_id": "cmp-1",
        "checkpoint": {"covered_through_event_id": "evt-9"},
        "source_refs": [
            {"event_id": "evt-1", "seq": 4},
            {"event_id": "evt-9", "seq": 12},
        ],
    })
    assert coverage["compaction_event_id"] == "cmp-1"
    assert coverage["covered_through_event_id"] == "evt-9"
    assert coverage["covered_through_seq"] == 12
    assert coverage["source_seq_from"] == 4
    assert coverage["source_seq_through"] == 12

def test_partial_stream_failure_keeps_stream_artifact_and_actual_identity(tmp_path: Path):
    with _server([_stream([], terminal=False), _submit_stream()]) as (config, *_):
        system = LoopSystem.for_testing(tmp_path, ResponsesAdapter(config),
                                        step_limits=StepLimits(retry_initial_delay_sec=0.01, retry_max_delay_sec=0.01))
        application, project_id, work_item_id, run_id = _project_run(system, "partial stream")
        system.activate_once(run_id)

    failed = [item for item in _attempts(application, project_id, work_item_id).data.attempts
              if item.status == "failed"]
    assert failed
    failed_detail = application.query("run.attempt", RunAttempt(run_id=run_id, attempt_id=failed[0].attempt_id))
    assert failed_detail.data.events
    assert failed_detail.data.response is None
    assert failed_detail.data.attempt["stage"] == "failed"

def test_project_queries_are_run_scoped_and_query_only(tmp_path: Path):
    # 查询按项目与事项读取：状态筛选只返回该状态，用量与尝试计数一致，查询不改变投影
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(happy_script()))
    application, project_id, work_item_id, run_id = _project_run(system, "route checks")
    system.run_until_stop(run_id)
    before = system.project(run_id).stream_version
    success = _attempts(application, project_id, work_item_id, department="product", status="success")
    assert success.data.attempts
    assert all(item.status == "success" and item.department == "product" for item in success.data.attempts)
    attempt_id = success.data.attempts[0].attempt_id
    detail = application.query("run.attempt", RunAttempt(run_id=run_id, attempt_id=attempt_id))
    assert detail.data.attempt["id"] == attempt_id
    usage = _usage(application, project_id, work_item_id, department="product")
    assert usage.data.totals.attempts == len(success.data.attempts)
    assert system.project(run_id).stream_version == before

def test_observability_export_contains_attempt_context_and_usage_without_mutating_run(tmp_path: Path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(happy_script()))
    application, project_id, work_item_id, run_id = _project_run(system, "export observations")
    system.run_until_stop(run_id)
    before = system.project(run_id).stream_version

    exported = application.query("run.export", RunExport(run_id=run_id))

    assert exported.data.run_id == run_id
    assert len(exported.data.attempts) == 4
    assert exported.data.usage["totals"]["attempts"] == 4
    assert system.project(run_id).stream_version == before
