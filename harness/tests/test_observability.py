"""Deterministic W1 model-attempt collection and read-only query checks.

旧控制台的模型尝试/用量/部门视图路由已经删除，这里的场景改由应用层查询验证：
project.attempts、project.usage、run.attempt、department.workspace 与 run.export
（对照 harness/tests/test_project_queries.py 与 test_issue_92.py 的同类覆盖）。
"""

from __future__ import annotations

import json
import math
from pathlib import Path


from harness.app.application import Application
from harness.app.project_queries import ProjectAttempts, ProjectUsage, RunAttempt, RunExport
from harness.tests.protocol_helpers import (
    ResponsesAdapter,
    stub_event as _event,
    stub_response as _response,
    stub_server as _server,
    stub_stream as _stream,
    write_stub_reply as _send,
)
from harness.models import ArtifactRef
from harness.runtime import LoopSystem
from harness.tests.helpers import happy_script
from harness.adapters.fake import FakeAdapter
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
    # 三个部门都工作过：产品提交要求、工程交付、质检起草测试用例并核验。
    # 同时运行以后模型调用的次数随会话的先后变化，这里断言的是结果（工单 #557）
    attempts = _attempts(application, project_id, work_item_id).data.attempts
    assert {item.department for item in attempts} == {"product", "engineering", "quality"}

    usage = _usage(application, project_id, work_item_id)
    assert usage.data.totals.attempts == len(attempts)
    assert usage.data.totals.reported == 0
    assert usage.data.totals.total_tokens is None
    assert usage.data.totals.cost is None
    assert usage.data.departments
    assert system.project(run_id).stream_version == before


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


def test_observability_export_contains_attempt_context_and_usage_without_mutating_run(tmp_path: Path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(happy_script()))
    application, project_id, work_item_id, run_id = _project_run(system, "export observations")
    system.run_until_stop(run_id)
    before = system.project(run_id).stream_version

    exported = application.query("run.export", RunExport(run_id=run_id))

    assert exported.data.run_id == run_id
    # 导出的尝试与查询读到的是同一批：三个部门都工作过（工单 #557）
    assert len(exported.data.attempts) == len(_attempts(application, project_id, work_item_id).data.attempts)
    assert exported.data.usage["totals"]["attempts"] == len(exported.data.attempts)
    assert system.project(run_id).stream_version == before
