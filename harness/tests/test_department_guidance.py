from __future__ import annotations

import json
import threading
from http.client import HTTPConnection

import pytest

from harness.adapters.fake import FakeAdapter, FakeTurn, prompt_part
from harness.models import EventType
from harness.observability import ObservabilityQuery
from harness.proposals import (
    collaboration_request, delivery_turn, engineering_plan, guidance_response, plan_turn,
    product_spec, response_turn, review_turn,
)
from harness.runtime import LoopSystem
from harness.tests.helpers import recorded_context
from harness.web.server import serve


def _guidance_id(request):
    return json.loads(prompt_part(request, "department_guidance"))[0]["id"]


def _tool_names(request):
    return [item["name"] for item in request.tools]


def _guidance_only(system, request):
    return recorded_context(system, request).manifest.guidance_only


def _last_activation(system, run_id):
    return next(event for event in reversed(system.store.list_events(run_id))
                if event.type == EventType.DEPARTMENT_ACTIVATED)


def _guidance_results(request):
    part = prompt_part(request, "guidance_results")
    return [] if part is None else json.loads(part)


def test_guidance_is_persisted_bound_to_target_and_entered_before_request(tmp_path):
    adapter = FakeAdapter([product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)

    system.add_guidance(run_id, "engineering", "请优先检查错误输出的边界行为。")
    adapter.script.append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), status="explained", text="已检查边界行为，当前指导不改变产品合同。"
    )))
    result = system.activate_once(run_id)

    guidance = result.department_guidance[0]
    assert guidance.department == "engineering"
    assert guidance.status == "explained"
    assert guidance.response_text == "已检查边界行为，当前指导不改变产品合同。"
    assert guidance.text in prompt_part(adapter.invocations[-1], "department_guidance")
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
        _guidance_id(request), status="explained", text="已说明错误处理边界；该指导不授权修改交付。"
    )))
    result = system.activate_once(run_id)

    assert result.phase == "QUALITY"
    assert result.active_department == "engineering"
    assert result.department_guidance[0].status == "explained"
    request = adapter.invocations[-1]
    assert _tool_names(request) == [
        "read_file", "list_files", "run_check", "submit_request", "submit_guidance_response",
    ]


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


def test_guidance_not_completed_by_activation_or_rejection(tmp_path):
    adapter = FakeAdapter([product_spec(goal="   ")])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.add_guidance(run_id, "product", "请补充输入校验的处理说明。")
    result = system.activate_once(run_id)

    guidance = result.department_guidance[0]
    assert guidance.status in {"received", "in_input"}
    assert guidance.status != "completed"
    assert result.rejections
    assert not any(event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED
                   for event in system.store.list_events(run_id))
    assert any(event.type == EventType.PROPOSAL_REJECTED for event in system.store.list_events(run_id))
    assert any(event.type == EventType.CONTEXT_ASSEMBLED for event in system.store.list_events(run_id))
    assert any(event.type == EventType.ACTIVATION_FINISHED for event in system.store.list_events(run_id))


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
@pytest.mark.parametrize("status", ["explained", "completed", "declined", "needs_work"])
def test_guidance_completed_requires_nonempty_response_text(tmp_path, text, status):
    adapter = FakeAdapter([])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.add_guidance(run_id, "product", "请说明当前验收边界。")
    adapter.script.append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), status=status, text=text,
    )))
    result = system.activate_once(run_id)

    assert result.department_guidance[0].status != "completed"
    assert result.department_guidance[0].status in {"received", "in_input"}
    assert result.rejections
    assert any(error["field"] == "text" for error in result.rejections[-1]["errors"])
    assert not any(event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED
                   for event in system.store.list_events(run_id))


def test_guidance_response_binds_that_guidance_id(tmp_path):
    adapter = FakeAdapter([product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.add_guidance(run_id, "engineering", "请优先检查错误输出的边界行为。")
    adapter.script.append(lambda request: FakeTurn(proposal=guidance_response(
        "guidance-not-this-id", text="不能绑定到其他指导。",
    )))
    rejected = system.activate_once(run_id)
    assert rejected.department_guidance[0].status != "completed"
    assert rejected.department_guidance[0].status in {"received", "in_input"}
    assert any(error["field"] == "guidance_id" for error in rejected.rejections[-1]["errors"])

    adapter.script.append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), status="explained", text="已检查边界行为，当前指导不改变产品合同。",
    )))
    done = system.activate_once(run_id)
    assert done.department_guidance[0].status == "explained"
    assert done.department_guidance[0].response_text == "已检查边界行为，当前指导不改变产品合同。"
    responded = next(event for event in system.store.list_events(run_id)
                     if event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED)
    assert responded.payload["guidance_id"] == done.department_guidance[0].id


def test_product_guidance_during_engineering_is_full_product_turn(tmp_path):
    adapter = FakeAdapter([product_spec(), plan_turn()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    assert system.project(run_id).phase == "ENGINEERING"

    system.add_guidance(run_id, "product", "请确认未知参数是否需要写入验收。")
    adapter.script.append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), status="explained", text="当前合同已覆盖该行为，无需改需求。",
    )))
    result = system.activate_once(run_id)
    request = adapter.invocations[-1]
    names = _tool_names(request)
    assert request.department == "product"
    assert _guidance_only(system, request) is False
    assert "submit_product_spec" in names
    assert "submit_guidance_response" in names
    assert names != ["read_file", "list_files", "run_check", "submit_guidance_response"]
    yielded = _last_activation(system, run_id).payload["yielded_work"]
    assert yielded["phase"] == "ENGINEERING"
    assert yielded["effective_contract_hash"] == result.effective_contract.content_hash
    assert yielded["engineering_plan_hash"] == result.engineering_plan.content_hash
    assert result.department_guidance[0].status == "explained"
    assert result.phase == "ENGINEERING"

    adapter.script.append(plan_turn(reason="Continue engineering after product guidance."))
    resumed = system.activate_once(run_id)
    assert adapter.invocations[-1].department == "engineering"
    assert resumed.phase == "ENGINEERING"
    assert resumed.active_department == "engineering"


def test_quality_guidance_does_not_resume_superseded_delivery(tmp_path):
    adapter = FakeAdapter([product_spec(), plan_turn(), delivery_turn()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo", max_cycles=12)
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.activate_once(run_id)
    before = system.project(run_id)
    assert before.phase == "QUALITY"
    old_delivery = before.delivery_spec.content_hash

    system.add_guidance(run_id, "product", "请把输出改为大写并更新验收。")
    adapter.script.append(product_spec(
        requirements=["print the given argument in uppercase"],
        acceptance=["running the program with a word prints that word in uppercase"],
        change_record={
            "changed": ["Output casing"],
            "retained": ["Echo CLI"],
            "retired": [],
            "rationale": "Guidance requires uppercase output.",
        },
    ))
    first_yield = {
        "phase": "QUALITY",
        "effective_contract_hash": before.effective_contract.content_hash,
        "engineering_plan_hash": before.engineering_plan.content_hash,
        "delivery_spec_hash": old_delivery,
    }
    revised = system.activate_once(run_id)
    assert revised.delivery_spec is None
    assert revised.delivery_specs[-1].status == "superseded"
    assert revised.delivery_specs[-1].content_hash == old_delivery
    assert revised.phase == "QUALITY"
    assert revised.department_guidance[0].status in {"received", "in_input"}
    spec_activation = _last_activation(system, run_id)
    assert spec_activation.payload["yielded_work"] == first_yield
    assert revised.yielded_work == first_yield

    adapter.script.append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), text="已把大写输出写入产品要求。",
    )))
    responded = system.activate_once(run_id)
    assert responded.department_guidance[0].status == "completed"
    assert responded.phase == "ENGINEERING"
    assert responded.delivery_spec is None
    assert _last_activation(system, run_id).payload["yielded_work"] == first_yield
    responded_event = next(event for event in system.store.list_events(run_id)
                           if event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED)
    resume = next(event for event in system.store.list_events(run_id)
                  if event.type == EventType.TRANSITION and event.stream_version > responded_event.stream_version)
    assert resume.payload["from"] == "QUALITY"
    assert resume.payload["to"] == "ENGINEERING"
    assert resume.payload["yielded_work_resolved"] is True
    assert resume.payload["yielded_work"] == first_yield
    assert responded.yielded_work is None

    adapter.script.append(plan_turn(reason="Rebuild after product guidance changed the contract."))
    next_work = system.activate_once(run_id)
    assert next_work.phase == "ENGINEERING"
    assert next_work.active_department == "engineering"
    assert adapter.invocations[-1].department == "engineering"
    assert next_work.delivery_spec is None


def test_guidance_only_engineering_can_request_product(tmp_path):
    adapter = FakeAdapter([product_spec(), plan_turn(), delivery_turn()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.activate_once(run_id)
    assert system.project(run_id).phase == "QUALITY"

    system.add_guidance(run_id, "engineering", "验收需要产品确认未知参数的处理。")
    adapter.script.append(collaboration_request(
        "product", "未知参数应如何写入验收？",
        request_type="action", action="revise_requirements",
        background="Quality-phase engineering guidance cannot change the product contract.",
        expected_result="Product updates the effective requirements if needed.",
    ))
    result = system.activate_once(run_id)
    request = adapter.invocations[-1]
    names = _tool_names(request)
    assert request.department == "engineering"
    assert _guidance_only(system, request) is True
    assert "submit_request" in names
    assert "write_file" not in names
    assert "submit_delivery" not in names
    assert result.pending_request is not None
    assert result.pending_request.recipient == "product"
    assert result.department_guidance[0].status in {"received", "in_input"}


def test_guidance_only_engineering_cannot_write_during_quality(tmp_path):
    adapter = FakeAdapter([product_spec(), plan_turn(), delivery_turn()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.activate_once(run_id)
    original = system.workspace(run_id).read_file("src/echo.py")
    assert original

    system.add_guidance(run_id, "engineering", "请直接改交付文件以处理错误输出。")
    adapter.script.append(lambda request: FakeTurn(
        writes={"src/echo.py": "import sys\nprint('hijacked')\n"},
        proposal=guidance_response(
            _guidance_id(request), status="explained", text="指导不能授权修改交付，已拒绝写文件。",
        ),
    ))
    result = system.activate_once(run_id)
    request = adapter.invocations[-1]
    assert request.department == "engineering"
    assert _guidance_only(system, request) is True
    activation_id = request.activation_id
    write = next(event for event in system.store.list_events(run_id)
                 if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "write_file"
                 and event.payload.get("activation_id") == activation_id)
    assert write.payload["ok"] is False
    assert not any(event.type == EventType.TOOL_STARTED and event.payload.get("name") == "write_file"
                   and event.payload.get("activation_id") == activation_id
                   for event in system.store.list_events(run_id))
    assert system.workspace(run_id).read_file("src/echo.py") == original
    assert result.phase == "QUALITY"


def test_cancel_during_pending_guidance_does_not_mark_processed(tmp_path):
    holder = {}

    def cancel_during(request):
        holder["system"].cancel(request.run_id)
        return FakeTurn(proposal=guidance_response(
            _guidance_id(request), text="迟到的指导回应不能在取消后生效。",
        ))

    adapter = FakeAdapter([])
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("echo")
    system.add_guidance(run_id, "product", "请补充输入校验的处理说明。")
    adapter.script.append(cancel_during)
    result = system.activate_once(run_id)

    assert result.stop_reason == "cancelled"
    assert result.phase == "FAILED"
    assert result.department_guidance[0].status in {"received", "in_input"}
    assert result.department_guidance[0].status != "completed"
    assert not any(event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED
                   for event in system.store.list_events(run_id))


def test_qa_release_blocked_until_guidance_response(tmp_path):
    adapter = FakeAdapter([product_spec(), plan_turn(), delivery_turn()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo", max_cycles=12)
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.activate_once(run_id)
    assert system.project(run_id).phase == "QUALITY"

    system.add_guidance(run_id, "quality", "放行前请核对错误输出边界。")
    adapter.script.append(review_turn("release", "Attempt release before the guidance has a recorded response."))
    blocked = system.activate_once(run_id)
    assert blocked.phase == "QUALITY"
    assert blocked.last_review is None
    assert any(error["field"] == "guidance" for error in blocked.rejections[-1]["errors"])
    assert blocked.department_guidance[0].status in {"received", "in_input"}

    adapter.script.append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), status="explained", text="已核对错误输出边界，可以按当前交付独立复检。",
    )))
    responded = system.activate_once(run_id)
    assert responded.department_guidance[0].status == "explained"
    assert responded.phase == "QUALITY"

    adapter.script.append(review_turn("release", "Independent quality check after the guidance response."))
    done = system.activate_once(run_id)
    assert done.phase == "DONE"
    assert done.last_review.verdict == "release"


def test_qa_reject_then_guidance_completed_does_not_skip_quality(tmp_path):
    adapter = FakeAdapter([product_spec(), plan_turn(), delivery_turn()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo", max_cycles=12)
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.activate_once(run_id)
    assert system.project(run_id).phase == "QUALITY"

    system.add_guidance(run_id, "quality", "返工后仍需独立复检，不能把旧放行当作完成。")
    adapter.script.append(review_turn(
        "rework_engineering",
        "Empty input still prints nothing.",
        defects=[{"severity": "major", "summary": "Empty input is not rejected."}],
    ))
    rejected = system.activate_once(run_id)
    assert rejected.phase == "ENGINEERING"
    assert rejected.delivery_spec is None
    assert rejected.last_review.verdict == "rework_engineering"
    assert rejected.department_guidance[0].status in {"received", "in_input"}
    rework_activation = rejected.last_activations["quality"]
    assert not any(event.type == EventType.RUN_DONE for event in system.store.list_events(run_id))

    adapter.script.append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), status="explained", text="已记录返工原因；需要工程修复后再做独立质检。",
    )))
    responded = system.activate_once(run_id)
    assert responded.department_guidance[0].status == "explained"
    assert responded.phase == "ENGINEERING"
    assert responded.last_review.verdict == "rework_engineering"
    assert responded.last_activations["quality"] != rework_activation
    assert adapter.invocations[-1].department == "quality"
    assert _guidance_only(system, adapter.invocations[-1]) is True
    assert not any(event.type == EventType.RUN_DONE for event in system.store.list_events(run_id))

    adapter.script.append(plan_turn(reason="Fix empty-input handling after QA rework."))
    next_work = system.activate_once(run_id)
    assert next_work.phase == "ENGINEERING"
    assert next_work.active_department == "engineering"
    assert adapter.invocations[-1].department == "engineering"
    assert next_work.last_review.verdict == "rework_engineering"


def test_open_collaboration_blocks_cross_department_guidance_schedule(tmp_path):
    adapter = FakeAdapter([collaboration_request("engineering")])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    pending = system.activate_once(run_id)
    assert pending.pending_request.recipient == "engineering"

    system.add_guidance(run_id, "quality", "请先核对此次交付的验收边界。")
    adapter.script.append(response_turn("answered", "Keep the original acceptance as written."))
    result = system.activate_once(run_id)
    assert adapter.invocations[-1].department == "engineering"
    activated = [event for event in system.store.list_events(run_id)
                 if event.type == EventType.DEPARTMENT_ACTIVATED]
    assert activated[-1].role == "engineering"
    assert not any(event.role == "quality" for event in activated)
    assert result.department_guidance[0].department == "quality"
    assert result.department_guidance[0].status == "received"
    assert result.pending_request is None
    assert result.responses[-1].status == "answered"


def test_explain_only_completed_without_result_ids_still_completes(tmp_path):
    adapter = FakeAdapter([product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.add_guidance(run_id, "engineering", "请说明当前错误输出边界，无需改文件。")
    adapter.script.append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), status="explained", text="当前合同已覆盖该边界，无需变更。", result_event_ids=[],
    )))
    result = system.activate_once(run_id)
    assert result.department_guidance[0].status == "explained"
    responded = next(event for event in system.store.list_events(run_id)
                     if event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED)
    assert responded.payload["status"] == "explained"
    assert responded.payload["result_event_ids"] == []


def test_engineering_write_then_completed_without_tool_id_is_host_bound(tmp_path):
    adapter = FakeAdapter([product_spec(), plan_turn()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    assert system.project(run_id).phase == "ENGINEERING"

    system.add_guidance(run_id, "engineering", "请修改错误输出处理。")
    adapter.script.append(lambda request: FakeTurn(
        writes={"src/echo.py": "import sys\nprint(sys.argv[1])\n"},
        proposal=guidance_response(_guidance_id(request), text="已修改文件，但未引用主机结果。"),
    ))
    result = system.activate_once(run_id)
    request = adapter.invocations[-1]
    assert request.department == "engineering"
    assert _guidance_only(system, request) is False
    write = next(event for event in system.store.list_events(run_id)
                 if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "write_file"
                 and event.payload.get("activation_id") == request.activation_id)
    assert write.payload["ok"] is True
    assert result.department_guidance[0].status == "completed", result.rejections
    responded = next(event for event in system.store.list_events(run_id)
                     if event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED)
    assert write.event_id in responded.payload["result_event_ids"]


def test_engineering_write_then_completed_with_tool_id_is_accepted(tmp_path):
    holder = {}

    def complete_with_write(request):
        projection = holder["system"].project(request.run_id)
        guidance_id = next(item.id for item in projection.department_guidance
                           if item.department == "engineering" and item.status in {"received", "in_input"})
        write = next(event for event in holder["system"].store.list_events(request.run_id)
                     if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "write_file"
                     and event.payload.get("activation_id") == request.activation_id
                     and event.payload.get("ok"))
        return FakeTurn(proposal=guidance_response(
            guidance_id, text="已按指导写入当前工程文件。",
            result_event_ids=[write.event_id],
        ))

    adapter = FakeAdapter([product_spec(), plan_turn()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.add_guidance(run_id, "engineering", "请修改错误输出处理。")
    adapter.script.append(FakeTurn(writes={"src/echo.py": "import sys\nprint(sys.argv[1])\n"}))
    adapter.script.append(complete_with_write)
    result = system.activate_once(run_id)
    assert result.department_guidance[0].status == "completed", result.rejections
    responded = next(event for event in system.store.list_events(run_id)
                     if event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED)
    write = system.store.get_event(responded.payload["result_event_ids"][0])
    assert write.type == EventType.TOOL_CALLED and write.payload["name"] == "write_file"
    assert write.payload["ok"] is True


def test_write_then_later_empty_completed_still_binds_tool_id(tmp_path):
    adapter = FakeAdapter([product_spec(), plan_turn()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.add_guidance(run_id, "engineering", "请修改错误输出处理。")
    adapter.script.append(lambda request: FakeTurn(
        writes={"src/echo.py": "import sys\nprint(sys.argv[1])\n"},
        proposal=guidance_response(_guidance_id(request), text=""),
    ))
    first = system.activate_once(run_id)
    assert first.department_guidance[0].status in {"received", "in_input"}
    write = next(event for event in system.store.list_events(run_id)
                 if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "write_file"
                 and event.payload.get("ok"))
    adapter.script.append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), text="已按先前写入处理。", result_event_ids=[],
    )))
    done = system.activate_once(run_id)
    assert done.department_guidance[0].status == "completed", done.rejections
    request = adapter.invocations[-1]
    assert any(item["event_id"] == write.event_id for item in _guidance_results(request))
    responded = next(event for event in system.store.list_events(run_id)
                     if event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED)
    assert write.event_id in responded.payload["result_event_ids"]


@pytest.mark.parametrize("result_event_ids", [["unknown-event-id"], None])
def test_guidance_completed_rejects_unknown_or_cross_run_result_ids(tmp_path, result_event_ids):
    other = LoopSystem.for_testing(tmp_path / "other", FakeAdapter([product_spec()]))
    other_run = other.create_run("other")
    other.activate_once(other_run)
    foreign_id = other.store.list_events(other_run)[0].event_id
    ids = [foreign_id] if result_event_ids is None else result_event_ids

    adapter = FakeAdapter([])
    system = LoopSystem.for_testing(tmp_path / "main", adapter)
    run_id = system.create_run("echo")
    system.add_guidance(run_id, "product", "请说明当前验收边界。")
    adapter.script.append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), text="引用了无效结果。", result_event_ids=ids,
    )))
    result = system.activate_once(run_id)
    assert result.department_guidance[0].status in {"received", "in_input"}
    assert result.rejections
    assert any(error["field"] == "result_event_ids" for error in result.rejections[-1]["errors"])
    assert not any(event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED
                   for event in system.store.list_events(run_id))


def test_guidance_completed_rejects_proposal_rejected_as_result(tmp_path):
    adapter = FakeAdapter([])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.add_guidance(run_id, "product", "请补充输入校验的处理说明。")
    adapter.script.append(product_spec(goal="   "))
    rejected = system.activate_once(run_id)
    assert rejected.rejections
    rejected_id = next(event.event_id for event in system.store.list_events(run_id)
                       if event.type == EventType.PROPOSAL_REJECTED)

    adapter.script.append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), text="把拒收当成了完成证据。", result_event_ids=[rejected_id],
    )))
    again = system.activate_once(run_id)
    assert again.department_guidance[0].status in {"received", "in_input"}
    assert any(error["field"] == "result_event_ids" for error in again.rejections[-1]["errors"])
    assert not any(event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED
                   for event in system.store.list_events(run_id))


@pytest.mark.parametrize("kind", ["delivery", "check"])
def test_old_delivery_or_check_cannot_complete_guidance_after_spec_change(tmp_path, kind):
    adapter = FakeAdapter([product_spec(), plan_turn(), delivery_turn()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo", max_cycles=12)
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.activate_once(run_id)
    before = system.project(run_id)
    assert before.phase == "QUALITY"
    old_delivery_id = before.delivery_spec.created_event_id
    old_check_id = next(
        event.event_id for event in system.store.list_events(run_id)
        if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "run_check"
        and event.payload.get("ok") and event.role == "engineering"
    )
    cited = old_delivery_id if kind == "delivery" else old_check_id

    system.add_guidance(run_id, "product", "请把输出改为大写并更新验收。")
    adapter.script.append(product_spec(
        requirements=["print the given argument in uppercase"],
        acceptance=["running the program with a word prints that word in uppercase"],
        change_record={
            "changed": ["Output casing"],
            "retained": ["Echo CLI"],
            "retired": [],
            "rationale": "Guidance requires uppercase output.",
        },
    ))
    revised = system.activate_once(run_id)
    assert revised.delivery_spec is None
    assert revised.delivery_specs[-1].status == "superseded"

    adapter.script.append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), text="已把大写输出写入产品要求。",
    )))
    responded = system.activate_once(run_id)
    assert responded.department_guidance[0].status == "completed"
    assert responded.phase == "ENGINEERING"

    system.add_guidance(run_id, "engineering", "请按新合同处理交付。")
    adapter.script.append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), text="沿用旧交付或旧检查即可。", result_event_ids=[cited],
    )))
    rejected = system.activate_once(run_id)
    guidance = next(item for item in rejected.department_guidance if item.department == "engineering")
    assert guidance.status in {"received", "in_input"}
    assert rejected.rejections
    assert any(error["field"] == "result_event_ids" for error in rejected.rejections[-1]["errors"])
    assert not any(
        event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED and event.payload.get("guidance_id") == guidance.id
        for event in system.store.list_events(run_id)
    )


def test_completed_without_host_action_after_guidance_is_rejected(tmp_path):
    adapter = FakeAdapter([product_spec(), plan_turn()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.add_guidance(run_id, "engineering", "请创建 src/guidance-proof.txt，内容为 VERIFIED。")
    adapter.script.append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request),
        text="已创建 src/guidance-proof.txt，内容为 VERIFIED。",
        result_event_ids=[],
    )))
    result = system.activate_once(run_id)

    assert result.department_guidance[0].status in {"received", "in_input"}
    assert result.rejections
    assert any(error["field"] == "result_event_ids" for error in result.rejections[-1]["errors"])
    assert "src/guidance-proof.txt" not in system.workspace(run_id).list_files()
    assert not any(event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED
                   for event in system.store.list_events(run_id))
    assert not any(
        event.type == EventType.TOOL_CALLED and event.payload.get("name") == "write_file"
        and event.payload.get("ok")
        for event in system.store.list_events(run_id)
    )


def test_pre_guidance_write_cannot_complete_new_guidance(tmp_path):
    adapter = FakeAdapter([
        product_spec(),
        plan_turn(),
        FakeTurn(
            writes={"src/echo.py": "import sys\nprint(sys.argv[1])\n"},
            proposal=engineering_plan(reason="Continue after writing the current echo CLI."),
        ),
    ])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    written = system.activate_once(run_id)
    assert written.phase == "ENGINEERING", written.stop_reason
    old_write = next(
        event for event in system.store.list_events(run_id)
        if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "write_file"
        and event.payload.get("ok")
    )
    system.add_guidance(run_id, "engineering", "请创建 src/guidance-proof.txt，内容为 VERIFIED。")
    adapter.script.append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request),
        text="已按先前写入完成新文件。",
        result_event_ids=[old_write.event_id],
    )))
    result = system.activate_once(run_id)

    assert result.department_guidance[0].status in {"received", "in_input"}
    assert result.rejections
    assert any(error["field"] == "result_event_ids" for error in result.rejections[-1]["errors"])
    assert "src/guidance-proof.txt" not in system.workspace(run_id).list_files()
    request = adapter.invocations[-1]
    assert all(item["event_id"] != old_write.event_id for item in _guidance_results(request))
    assert not any(event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED
                   for event in system.store.list_events(run_id))


def test_explained_without_tools_is_recorded_as_explained(tmp_path):
    adapter = FakeAdapter([product_spec()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.add_guidance(run_id, "engineering", "请说明当前错误输出边界，无需改文件。")
    adapter.script.append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request),
        status="explained",
        text="当前合同已覆盖该边界，无需变更。",
        result_event_ids=[],
    )))
    result = system.activate_once(run_id)
    assert result.department_guidance[0].status == "explained"
    responded = next(event for event in system.store.list_events(run_id)
                     if event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED)
    assert responded.payload["status"] == "explained"
    assert responded.payload["result_event_ids"] == []


def test_one_write_cannot_complete_two_guidance_items(tmp_path):
    adapter = FakeAdapter([product_spec(), plan_turn()])
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.add_guidance(run_id, "engineering", "请创建 src/guidance-a.txt，内容为 A。")
    system.add_guidance(run_id, "engineering", "请创建 src/guidance-b.txt，内容为 B。")
    adapter.script.append(lambda request: FakeTurn(
        writes={"src/guidance-a.txt": "A\n"},
        proposal=guidance_response(_guidance_id(request), text="已创建 src/guidance-a.txt。"),
    ))
    first = system.activate_once(run_id)
    first_item = next(item for item in first.department_guidance if item.text.endswith("A。"))
    second_item = next(item for item in first.department_guidance if item.text.endswith("B。"))
    assert first_item.status == "completed"
    assert second_item.status in {"received", "in_input"}
    write = next(
        event for event in system.store.list_events(run_id)
        if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "write_file"
        and event.payload.get("ok")
    )
    assert "src/guidance-a.txt" in system.workspace(run_id).list_files()
    adapter.script.append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request),
        text="同一写入也完成了第二条指导。",
        result_event_ids=[],
    )))
    second = system.activate_once(run_id)
    remaining = next(item for item in second.department_guidance if item.id == second_item.id)
    assert remaining.status in {"received", "in_input"}
    assert second.rejections
    assert any(error["field"] == "result_event_ids" for error in second.rejections[-1]["errors"])
    assert write.event_id in next(
        event.payload["result_event_ids"]
        for event in system.store.list_events(run_id)
        if event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED
        and event.payload.get("guidance_id") == first_item.id
    )


def test_guidance_tool_contract_lists_explained_and_requires_host_results_for_completed():
    from harness.tools import TOOL_SCHEMAS
    from harness.context import PROPOSAL_CONTRACTS

    tool = TOOL_SCHEMAS["submit_guidance_response"]
    status = tool["parameters"]["properties"]["status"]["enum"]
    assert status == ["explained", "completed", "declined", "needs_work"]
    assert "empty is allowed" not in tool["description"]
    contract = PROPOSAL_CONTRACTS["product"]["kinds"]["department_guidance_response"]
    assert contract["status"] == ["explained", "completed", "declined", "needs_work"]
