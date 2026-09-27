"""组合 run 的模型输入审计：连续输入 v2 + 部门指导（guidance_only 激活）+ 专家协作 + 最终独立 QA 放行。"""

import copy
import json
from dataclasses import asdict

import pytest

from harness.adapters.fake import FakeAdapter, FakeTurn, prompt_part
from harness.tools import usable_when_guidance_only
from harness.models import ArtifactRef, EventType, canonical_hash, json_dumps
from harness.proposals import (
    collaboration_request, delivery_turn, guidance_response, plan_turn, product_spec, response_turn, review_turn,
)
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.smoke import isolation_fields
from harness.tests.helpers import recorded_context

INPUT_V2 = "Also print a status column in the export.\r\n"


def _guidance_ids(request):
    return [item["id"] for item in json.loads(prompt_part(request, "department_guidance"))]


def _list_files(request):
    return ModelResponse(output=[{
        "id": f"inspect-{request.step_id}", "call_id": f"inspect-{request.step_id}", "type": "function_call",
        "name": "list_files", "arguments": "{}",
    }])


@pytest.fixture
def combined_run(tmp_path):
    holder = {}

    def in_flight_changes(request):
        # 工程第一次请求在途时：两条工程指导 + 用户连续输入 v2；旧回复的 list_files 不得再执行。
        system = holder["system"]
        system.add_guidance(request.run_id, "engineering", "请解释当前导出格式的处理边界。")
        system.add_guidance(request.run_id, "engineering", "请在交付文件头部标注导出格式。")
        system.add_input(request.run_id, INPUT_V2)
        return _list_files(request)

    def remember_guidance_then_check(request):
        holder["guidance_ids"] = _guidance_ids(request)
        return FakeTurn(checks={"probe": 0})

    def explain_first(request):
        return FakeTurn(proposal=guidance_response(
            holder["guidance_ids"][0], status="explained", text="当前导出格式边界已由有效合同覆盖，无需改动。",
        ))

    def explain_second(request):
        return FakeTurn(proposal=guidance_response(
            _guidance_ids(request)[0], status="explained", text="将在交付时于文件头部标注导出格式。",
        ))

    adapter = FakeAdapter([
        product_spec(),
        in_flight_changes,
        remember_guidance_then_check, explain_first,
        explain_second,
        product_spec(
            requirements=["print the given argument to stdout", "print a status column in the export"],
            change_record={
                "changed": ["The export includes a status column"],
                "retained": ["Ordinary input is printed unchanged"],
                "retired": [],
                "rationale": "The user's additional original input asks for a status column.",
            },
        ),
        collaboration_request("product", "Is the status column part of the acceptance criteria?",
                              background="Engineering is planning the export.",
                              expected_result="Confirm the acceptance basis without changing files."),
        response_turn("answered", "The status column is part of the accepted requirements."),
        plan_turn(),
        delivery_turn(files={"src/echo.py": "# export-format: csv\nimport sys\nprint(sys.argv[1])\n"}),
        review_turn("release", "Independent quality check passed on the current delivery."),
    ])
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("build an export CLI", max_cycles=20)
    projection = system.run_until_stop(run_id)
    return system, adapter, run_id, projection


def test_combined_run_shape(combined_run):
    system, adapter, run_id, projection = combined_run
    assert projection.phase == "DONE" and projection.stop_reason == "released", (projection.stop_reason, projection.error)
    assert projection.input_version == projection.processed_input_version == 2
    assert projection.product_spec.revision == 2
    assert [item.status for item in projection.department_guidance] == ["explained", "explained"]
    assert [item.status for item in projection.responses] == ["answered"]
    events = system.store.list_events(run_id)
    assert any(event.type == EventType.TOOL_SKIPPED for event in events)
    guidance_only = [request for request in adapter.invocations
                     if recorded_context(system, request).manifest.guidance_only]
    assert {request.department for request in guidance_only} == {"engineering"}
    assert len({request.activation_id for request in guidance_only}) == 2
    assert all(usable_when_guidance_only(tool["name"]) for request in guidance_only for tool in request.tools)
    results = next(json.loads(text) for request in guidance_only
                   if (text := prompt_part(request, "guidance_results")) and json.loads(text))
    assert results[0]["name"] == "run_check"


def test_model_input_audit_verifies_combined_run(combined_run):
    system, _, run_id, _ = combined_run
    fields = isolation_fields(system.store, system.artifacts, run_id)
    assert fields["model_input_audit"]["status"] == "verified", fields["model_input_audit"]["notes"]
    assert fields["context_isolated"] is True
    # 产品 / 工程让出 / 两次 guidance_only / 产品处理 v2 / 工程发起协作 / 产品回应 / 工程计划 / 工程交付 / 质检
    assert fields["model_input_audit"]["activation_count"] == 10


def test_snapshot_gated_guidance_results_after_a_no_op_write_are_verified(tmp_path):
    """写操作之后、下一次检查之前仍有待处理指导且检查结果可认领：审计靠记录下来的快照重建，而不是推断。"""

    holder = {}
    code = "import sys\nprint(sys.argv[1])\n"

    def remember_guidance_write_and_check(request):
        holder["guidance_ids"] = _guidance_ids(request)
        return FakeTurn(writes={"src/echo.py": code}, checks={"probe": 0})

    adapter = FakeAdapter([product_spec(), plan_turn()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build an echo CLI")
    system.activate_once(run_id)
    system.activate_once(run_id)
    assert system.project(run_id).phase == "ENGINEERING"

    system.add_guidance(run_id, "engineering", "请先核对当前文件，再说明处理边界。")
    adapter.script.extend([
        remember_guidance_write_and_check,
        FakeTurn(writes={"src/echo.py": code}),  # 内容相同的再次写入：树不变，但它是最后一次成功的工具操作
        lambda request: FakeTurn(proposal=guidance_response(
            holder["guidance_ids"][0], status="explained", text="已核对文件与检查结果，边界无需变更。",
        )),
    ])
    result = system.activate_once(run_id)
    assert result.department_guidance[0].status == "explained"
    last = adapter.invocations[-1]
    assert recorded_context(system, last).manifest.guidance_only is False and last.step_id == 3
    results = json.loads(prompt_part(last, "guidance_results"))
    assert {item["name"] for item in results} == {"write_file", "run_check"}
    assembled = [event for event in system.store.list_events(run_id) if event.type == EventType.CONTEXT_ASSEMBLED]
    assert all(isinstance(event.payload.get("snapshot_hash"), str) and event.payload["snapshot_hash"] for event in assembled)
    fields = isolation_fields(system.store, system.artifacts, run_id)
    assert fields["model_input_audit"]["status"] == "verified", fields["model_input_audit"]["notes"]


@pytest.mark.parametrize("mutation,expected", [
    ("other_snapshot", "pinned developer input differs"),
    ("missing_snapshot", "does not record the workspace snapshot"),
])
def test_model_input_audit_rejects_tampered_or_missing_snapshot_record(combined_run, monkeypatch, mutation, expected):
    system, _, run_id, _ = combined_run
    events = _mutable_events(system, run_id, monkeypatch)
    assembled = next(
        event for event in events if event.type == EventType.CONTEXT_ASSEMBLED
        and any(part["source"] == "guidance_results" and json.loads(part["text"])
                for part in json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**event.payload["parts_ref"]))))
    )
    if mutation == "other_snapshot":
        assembled.payload["snapshot_hash"] = canonical_hash("another workspace")
    else:
        del assembled.payload["snapshot_hash"]
    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]
    assert audit["status"] == "unverified"
    assert any(expected in note for note in audit["notes"]), audit["notes"]


def _mutable_events(system, run_id, monkeypatch):
    events = copy.deepcopy(system.store.list_events(run_id))
    monkeypatch.setattr(system.store, "list_events", lambda *_args, **_kwargs: events)
    return events


def _rehash_request(system, events, assembled, request):
    ref = system.artifacts.put(assembled.run_id, "model_request", json_dumps(request), media_type="application/json")
    assembled.payload["request_ref"] = asdict(ref)
    assembled.payload["digest"] = assembled.context_digest = canonical_hash(request)
    assembled.artifact_hashes = [ref.content_hash]
    attempted = next(item for item in events if item.type == EventType.MODEL_REQUESTED
                     and item.payload["activation_id"] == assembled.payload["activation_id"]
                     and item.payload["step_id"] == assembled.payload["step_id"])
    attempted.context_digest = assembled.context_digest


@pytest.mark.parametrize("mutation,expected", [
    ("private_text_in_guidance", "pinned developer input differs"),
    ("full_tools_in_guidance_only", "guidance_only does not match"),
])
def test_model_input_audit_rejects_tampered_guidance_request(combined_run, monkeypatch, mutation, expected):
    system, _, run_id, _ = combined_run
    events = _mutable_events(system, run_id, monkeypatch)
    activated = next(event for event in events if event.type == EventType.DEPARTMENT_ACTIVATED
                     and event.payload.get("guidance_only") is True)
    if mutation == "private_text_in_guidance":
        assembled = next(event for event in events if event.type == EventType.CONTEXT_ASSEMBLED
                         and event.payload["activation_id"] == activated.payload["activation_id"]
                         and event.payload["step_id"] == 1)
        request = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**assembled.payload["request_ref"])))
        request["input"][0]["content"] = request["input"][0]["content"].replace(
            "[department_guidance]\n", "[department_guidance]\n[product_private_transcript] PRIVATE_PRODUCT_CANARY\n", 1,
        )
        _rehash_request(system, events, assembled, request)
    else:
        activated.payload["guidance_only"] = False
    audit = isolation_fields(system.store, system.artifacts, run_id)["model_input_audit"]
    assert audit["status"] == "unverified"
    assert any(expected in note for note in audit["notes"]), audit["notes"]
