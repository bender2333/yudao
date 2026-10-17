# 模型尝试观测的模块层结论：用量数值的未知处理、取消与部分的尝试可独立过滤、部分输出只是观察、
# 用量汇总只累加上报的尝试、部门消息不含失败与取消的尝试、适配器失败保留流证据。
# 这些结论都由单次激活（activate_once）与 FakeAdapter 得出，不需要本机 Provider 服务与完整循环，登记为模块层。

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from harness.adapters.base import Availability, ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.app.application import Application
from harness.app.project_queries import DepartmentWorkspace, ProjectAttempts, ProjectUsage, RunAttempt, WorkItemMaterials
from harness.artifacts import ArtifactStore
from harness.models import EventType, Usage
from harness.proposals import product_spec
from harness.providers.call import ModelResponse, ModelStreamEvent
from harness.runtime import LoopSystem

from harness.tests.helpers import after_event
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC
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
        self.release.wait(WAIT_FOR_HOST_WORK_SEC)
        yield ModelResponse(
            finish_reason="aborted", error="aborted",
            provider=self.name, model=self.model,
        )


def test_stream_artifact_cleanup_closes_temp_file_before_cleanup(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")

    def broken_chunks():
        yield b"first"
        raise OSError("stream stopped")

    with pytest.raises(OSError, match="stream stopped"):
        store.put_stream("run", "sdk_stream_events", broken_chunks())
    assert not list((tmp_path / "artifacts" / "run").glob(".stream-*"))


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
    msg_event = threading.Event()
    after_event(system, EventType.MODEL_MESSAGE, lambda _: msg_event.set())
    worker = threading.Thread(target=system.activate_once, args=(run_id,), daemon=True)
    worker.start()
    assert msg_event.wait(WAIT_FOR_HOST_WORK_SEC)
    system.cancel(run_id)
    worker.join(timeout=WAIT_FOR_HOST_WORK_SEC)
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
    msg_event = threading.Event()
    after_event(system, EventType.MODEL_MESSAGE, lambda _: msg_event.set())
    worker = threading.Thread(target=system.activate_once, args=(run_id,), daemon=True)
    worker.start()
    assert msg_event.wait(WAIT_FOR_HOST_WORK_SEC)

    row = _attempts(application, project_id, work_item_id).data.attempts[0]
    assert row.status == "running"
    assert row.stage == "partial"
    assert row.usage["source"] in {"missing", "unknown"} or row.usage["reported"] is False
    detail = application.query("run.attempt", RunAttempt(run_id=run_id, attempt_id=row.attempt_id))
    assert detail.data.attempt["partial_output"] is True
    assert detail.data.attempt["output_item_count"] == 1
    assert detail.data.response is None

    system.cancel(run_id)
    worker.join(timeout=WAIT_FOR_HOST_WORK_SEC)
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
