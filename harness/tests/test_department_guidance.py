from __future__ import annotations

import json
import threading
from http.client import HTTPConnection

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.models import EventType
from harness.observability import ObservabilityQuery
from harness.proposals import delivery_turn, guidance_response, plan_turn, product_spec
from harness.runtime import LoopSystem
from harness.web.server import serve


def _guidance_id(request):
    part = next(part for part in request.context.parts if part.source == "department_guidance")
    return json.loads(part.text)[0]["id"]


def test_guidance_is_persisted_bound_to_target_and_entered_before_request(tmp_path):
    adapter = FakeAdapter([product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)

    system.add_guidance(run_id, "engineering", "请优先检查错误输出的边界行为。")
    adapter.script.append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), text="已检查边界行为，当前指导不改变产品合同。"
    )))
    result = system.activate_once(run_id)

    guidance = result.department_guidance[0]
    assert guidance.department == "engineering"
    assert guidance.status == "completed"
    assert guidance.response_text == "已检查边界行为，当前指导不改变产品合同。"
    assert any(part.source == "department_guidance" and guidance.text in part.text
               for part in adapter.invocations[-1].context.parts)
    events = system.store.list_events(run_id)
    assert any(event.type == EventType.DEPARTMENT_GUIDANCE_RECEIVED for event in events)
    applied = next(event for event in events if event.type == EventType.DEPARTMENT_GUIDANCE_APPLIED)
    assert guidance.id in applied.payload["guidance_ids"]
    assert any(event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED for event in events)

    query = ObservabilityQuery(system.store, system.artifacts)
    department = query.department(run_id, "engineering")
    assert department["guidance"][0]["text"] == guidance.text
    assert not any(item.get("text") == guidance.text for item in query.department(run_id, "product")["messages"])


def test_guidance_for_previous_department_gets_a_read_only_activation_before_release(tmp_path):
    adapter = FakeAdapter([product_spec(), plan_turn(), delivery_turn()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.activate_once(run_id)
    assert system.project(run_id).phase == "QUALITY"

    system.add_guidance(run_id, "engineering", "请说明本次交付的错误处理边界。")
    adapter.script.append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), text="已说明错误处理边界；该指导不授权修改交付。"
    )))
    result = system.activate_once(run_id)

    assert result.phase == "QUALITY"
    assert result.active_department == "engineering"
    assert result.department_guidance[0].status == "completed"
    request = adapter.invocations[-1]
    assert [item["name"] for item in request.tools] == ["read_file", "list_files", "run_check", "submit_guidance_response"]


def test_guidance_received_during_model_request_invalidates_old_submission(tmp_path):
    holder = {}

    def old_response(request):
        holder["system"].add_guidance(request.run_id, "product", "请补充输入校验的处理说明。")
        return FakeTurn(proposal=product_spec())

    adapter = FakeAdapter([old_response])
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("echo")
    result = system.activate_once(run_id)

    assert result.product_spec is None
    assert result.department_guidance[0].status == "received"
    assert not any(event.type == EventType.SPEC_ACCEPTED for event in system.store.list_events(run_id))
    assert any(event.type == EventType.PROPOSAL_SUBMITTED for event in system.store.list_events(run_id)) is False


def test_guidance_http_command_returns_persisted_target_record(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([]))
    run_id = system.create_run("echo")
    server = serve(system, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        connection = HTTPConnection(host, port)
        body = json.dumps({"text": "请记录当前验收边界。"}).encode("utf-8")
        connection.request(
            "POST",
            f"/api/runs/{run_id}/departments/quality/guidance",
            body=body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        assert response.status == 201
        assert payload["department"] == "quality"
        assert payload["guidance_id"]

        connection = HTTPConnection(host, port)
        connection.request("GET", f"/api/runs/{run_id}/departments/quality")
        response = connection.getresponse()
        department = json.loads(response.read())
        connection.close()
        assert response.status == 200
        assert department["guidance"][0]["id"] == payload["guidance_id"]
        assert department["guidance"][0]["text"] == "请记录当前验收边界。"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
