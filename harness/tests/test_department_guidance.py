from __future__ import annotations

import json
import uuid

import pytest

from harness.collaboration import has_new_work
from harness.adapters.fake import FakeAdapter, FakeTurn, prompt_part
from harness.app.application import Application
from harness.app.project_queries import DepartmentWorkspace
from harness.models import EventType
from harness.proposals import (
    answer_turn, ask_turn, delivery_turn, guidance_response,
    product_spec, product_spec_turn, review_turn,
)
from harness.providers.call import ModelStreamEvent
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_api
from harness.tests.helpers import guidance_reply, quality_turns, recorded_context

ECHO = "import sys\nprint(sys.argv[1])\n"
ECHO_UPPER = "import sys\nprint(sys.argv[1].upper())\n"

# 这个文件里的脚本按部门给出，三个部门都写上（工单 #943）：质检在这些用例里不工作，给它的是空脚本。
# 脚本里没有它的名字时，假模型在它真的发请求时报「脚本用尽」，整个 run 以 provider_error 提前结束，
# 用例在到达要核对的那一步以前就失败（工单 #935 查出的成因，工单 #943 收尾）


def _guidance_id(request):
    return json.loads(prompt_part(request, "department_guidance"))[0]["id"]


def _tool_names(request):
    return [item["name"] for item in request.tools]


def _last_activation(system, run_id):
    return next(event for event in reversed(system.store.list_events(run_id))
                if event.type == EventType.DEPARTMENT_ACTIVATED)


def _guidance_results(request):
    part = prompt_part(request, "guidance_results")
    return [] if part is None else json.loads(part)


def test_guidance_is_persisted_bound_to_target_and_entered_before_request(tmp_path):
    # 脚本按部门给出（工单 #877：PRD 被接纳以后工程与质检同时工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    project_id = system.projects.register("指导", "把文本按行处理清楚")
    work_item_id, run_id = system.projects.start_work_item(project_id, "echo")
    system.activate_once(run_id)

    system.add_guidance(run_id, "engineering", "请优先检查错误输出的边界行为。")
    adapter.scripts["engineering"].append(lambda request: FakeTurn(proposal=guidance_response(
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

    application = Application(system)
    engineering = application.query("department.workspace", DepartmentWorkspace(
        project_id=project_id, department="engineering", work_item=work_item_id))
    assert engineering.data.guidance[0].text == guidance.text
    product = application.query("department.workspace", DepartmentWorkspace(
        project_id=project_id, department="product", work_item=work_item_id))
    assert not any(message.get("text") == guidance.text for message in product.data.messages)


def test_guidance_for_a_waiting_department_starts_a_full_round(tmp_path):
    # 验收第 1 条（在等待工作）：指导是接收部门关注的成果，它在这一轮开始一轮完整的工作，
    # 可以读取、写入、运行检查、询问与提交正式成果（循环结构第 6 节，工单 #560）；
    # 不为它另设一种只回应指导的轮次（工单 #556 的过渡做法已删除）
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [delivery_turn()], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    assert has_new_work(system.project(run_id), "quality")

    system.add_guidance(run_id, "engineering", "请说明本次交付的错误处理边界。")
    adapter.scripts["engineering"].append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), status="explained", text="已说明错误处理边界；该指导不改变产品要求。"
    )))
    result = system.activate_once(run_id)

    assert has_new_work(result, "quality")
    assert result.active_department == "engineering"
    assert result.department_guidance[0].status == "explained"
    names = _tool_names(adapter.invocations[-1])
    assert {"read_file", "write_file", "run_check", "ask", "submit_delivery",
            "submit_guidance_response"} <= set(names)


def test_guidance_received_during_model_request_becomes_a_notification(tmp_path):
    # 工单 #558：指导在工作期间到达时，它在这个会话的下一步作为通知加入历史；
    # 这次提交不再因为指导到达而作废（循环结构第 6 节）
    holder = {}

    def old_response(request):
        holder["system"].add_guidance(request.run_id, "product", "请补充输入校验的处理说明。")
        return FakeTurn(proposal=product_spec())

    adapter = FakeAdapter([old_response])
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("echo")
    result = system.activate_once(run_id)

    assert result.product_spec is not None
    assert result.department_guidance[0].status in {"received", "in_input"}
    assert any(event.type == EventType.SPEC_ACCEPTED for event in system.store.list_events(run_id))
    assert any(event.type == EventType.PROPOSAL_SUBMITTED for event in system.store.list_events(run_id))


def test_guidance_command_returns_persisted_target_record(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    project_id = system.projects.register("指导", "把文本按行处理清楚")
    work_item_id, run_id = system.projects.start_work_item(project_id, "echo")
    application = Application(system)
    with running_api(lambda: application) as client:
        sent = client.post("/api/commands/guidance.send", json={
            "command_id": str(uuid.uuid4()), "work_item_id": work_item_id, "department": "quality",
            "text": "请记录当前验收边界。"})
        assert sent.status_code == 200
        workspace = application.query("department.workspace", DepartmentWorkspace(
            project_id=project_id, department="quality", work_item=work_item_id))
        assert workspace.data.guidance[0].text == "请记录当前验收边界。"


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
    # 脚本按部门给出（工单 #877）
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.add_guidance(run_id, "engineering", "请优先检查错误输出的边界行为。")
    adapter.scripts["engineering"].append(lambda request: FakeTurn(proposal=guidance_response(
        "guidance-not-this-id", text="不能绑定到其他指导。",
    )))
    rejected = system.activate_once(run_id)
    assert rejected.department_guidance[0].status != "completed"
    assert rejected.department_guidance[0].status in {"received", "in_input"}
    assert any(error["field"] == "guidance_id" for error in rejected.rejections[-1]["errors"])

    adapter.scripts["engineering"].append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), status="explained", text="已检查边界行为，当前指导不改变产品合同。",
    )))
    done = system.activate_once(run_id)
    assert done.department_guidance[0].status == "explained"
    assert done.department_guidance[0].response_text == "已检查边界行为，当前指导不改变产品合同。"
    responded = next(event for event in system.store.list_events(run_id)
                     if event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED)
    assert responded.payload["guidance_id"] == done.department_guidance[0].id


def test_product_guidance_during_engineering_is_full_product_turn(tmp_path):
    # 脚本按部门给出（工单 #877）
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    assert has_new_work(system.project(run_id), "engineering")

    system.add_guidance(run_id, "product", "请确认未知参数是否需要写入验收。")
    adapter.scripts["product"].append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), status="explained", text="当前合同已覆盖该行为，无需改需求。",
    )))
    result = system.activate_once(run_id)
    request = adapter.invocations[-1]
    names = _tool_names(request)
    assert request.department == "product"
    assert "submit_product_spec" in names
    assert "submit_guidance_response" in names
    assert result.department_guidance[0].status == "explained"
    assert has_new_work(result, "engineering")

    adapter.scripts["engineering"].append(delivery_turn())
    resumed = system.activate_once(run_id)
    assert adapter.invocations[-1].department == "engineering"
    assert has_new_work(resumed, "quality")
    assert resumed.delivery_spec is not None


def test_product_guidance_revises_the_prd_and_engineering_starts_a_new_round(tmp_path):
    # 脚本按部门给出（工单 #877）
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [delivery_turn()], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo", max_cycles=12)
    system.activate_once(run_id)
    system.activate_once(run_id)
    before = system.project(run_id)
    assert has_new_work(before, "quality")
    old_delivery = before.delivery_spec.content_hash

    system.add_guidance(run_id, "product", "请把输出改为大写并更新验收。")
    adapter.scripts["product"].append(product_spec_turn(
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
    assert revised.delivery_specs[-1].content_hash == old_delivery
    assert has_new_work(revised, "quality")
    assert revised.department_guidance[0].status in {"received", "in_input"}

    adapter.scripts["product"].append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), text="已把大写输出写入产品要求。",
    )))
    responded = system.activate_once(run_id)
    assert responded.department_guidance[0].status == "completed"
    # 回应以后 PRD 有了新版本，工程开始一轮返工（工单 #556：工程关注 PRD 的新版本）
    assert has_new_work(responded, "engineering")
    assert responded.delivery_spec is None

    # 回应以后由关注的成果决定下一个谁工作：PRD 有了新版本，工程开始一轮返工（工单 #556）
    adapter.scripts["engineering"].append(delivery_turn())
    next_work = system.activate_once(run_id)
    assert adapter.invocations[-1].department == "engineering"
    assert next_work.delivery_spec is not None


def test_guidance_round_changes_the_running_workspace_and_delivers(tmp_path):
    # 验收第 2 条：发给在等待工作的工程的修改要求，工程在这一轮里修改运行工作区并提交交付，
    # 质检随之核验（循环结构第 6 节，工单 #560）
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [delivery_turn()], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    original = system.workspace(run_id).read_file("src/echo.py")
    assert original

    system.add_guidance(run_id, "engineering", "请把输出改为大写并重新交付。")
    adapter.scripts["engineering"].append(delivery_turn(
        summary="uppercase output",
        files={"src/echo.py": "import sys\nprint(sys.argv[1].upper())\n"},
    ))
    result = system.activate_once(run_id)
    assert adapter.invocations[-1].department == "engineering"
    changed = system.workspace(run_id).read_file("src/echo.py")
    assert changed != original and "upper" in changed
    assert result.delivery_spec is not None and result.delivery_spec.status == "active"
    assert has_new_work(result, "quality")

    adapter.scripts["engineering"].append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), status="explained", text="已按指导修改运行工作区并重新交付。",
    )))
    system.activate_once(run_id)

    adapter.scripts["quality"].append(review_turn("release", "checks passed on the current delivery"))
    released = system.activate_once(run_id)
    assert adapter.invocations[-1].department == "quality"
    assert released.status == "done"
    assert released.last_review.verdict == "release"


def test_guidance_arriving_while_a_round_waits_for_an_answer_is_delivered_at_its_next_step(tmp_path):
    # 验收第 1 条（停在一次询问上等待回答）：指导加入它的历史，它收到回答、继续工作的那一步看到
    holder = {}
    seen = {}

    def branch_answer(request):
        holder["system"].add_guidance(request.run_id, "engineering", "拿到回答以后先核对输出边界。")
        return answer_turn("输出保持小写。")(request)

    def after_the_answer(request):
        seen["guidance"] = prompt_part(request, "department_guidance")
        return delivery_turn()(request)

    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [ask_turn("product", "Should the output stay lowercase?"), after_the_answer],
        "product:ask": [branch_answer],
        "quality": [],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    result = system.activate_once(run_id)

    delivered = json.loads(seen["guidance"])
    assert [item["text"] for item in delivered] == ["拿到回答以后先核对输出边界。"]
    assert result.delivery_spec is not None


def test_guidance_for_one_department_is_delivered_in_receive_order(tmp_path):
    # 验收第 4 条：同一个部门连续收到两段指导，按接收的顺序处理
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.add_guidance(run_id, "engineering", "先核对错误输出的边界。")
    system.add_guidance(run_id, "engineering", "再核对空输入的边界。")

    adapter.scripts["engineering"].append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), status="explained", text="先处理第一段指导。",
    )))
    first = system.activate_once(run_id)
    delivered = json.loads(prompt_part(adapter.invocations[-1], "department_guidance"))
    assert [item["text"] for item in delivered] == ["先核对错误输出的边界。", "再核对空输入的边界。"]
    assert [item["version"] for item in delivered] == [1, 2]
    # 两段指导按接收的顺序进入这一轮的模型输入；这一轮先处理了第一段
    assert [item.status for item in first.department_guidance] == ["explained", "in_input"]

    adapter.scripts["engineering"].append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), status="explained", text="再处理第二段指导。",
    )))
    second = system.activate_once(run_id)
    assert adapter.invocations[-1].department == "engineering"
    remaining = json.loads(prompt_part(adapter.invocations[-1], "department_guidance"))
    assert [item["text"] for item in remaining] == ["再核对空输入的边界。"]
    assert [item.status for item in second.department_guidance] == ["explained", "explained"]


def test_guidance_to_a_finished_item_is_rejected(data_dir):
    # 验收第 1 条（事项已结束）：拒收，用户的草稿留在界面上；这里核对命令交回的原因
    system = LoopSystem.for_testing(data_dir, FakeAdapter({"product": [], "engineering": [], "quality": []}))
    project_id = system.projects.register("指导", "把文本按行处理清楚")
    work_item_id, run_id = system.projects.start_work_item(project_id, "echo")
    system.cancel(run_id)
    application = Application(system)
    with running_api(lambda: application) as client:
        rejected = client.post("/api/commands/guidance.send", json={
            "command_id": str(uuid.uuid4()), "work_item_id": work_item_id,
            "department": "engineering", "text": "事项结束以后发出的指导。",
        })
        assert rejected.status_code == 409
        assert rejected.json()["reason"] == "run_terminal"
        assert system.project(run_id).department_guidance == []


def test_product_guidance_revision_is_delivered_to_the_working_department_and_starts_the_waiting_one(tmp_path):
    # 验收第 3 条：发给产品的指导修订了 PRD，正在工作的部门在下一步收到通知，
    # 在等待工作的工程开始一轮工作（循环结构第 6 节，工单 #560）
    holder = {}
    seen = {}

    def work_through_the_revision(request):
        # 工程一轮工作中收到产品指导：产品以这段指导开始一轮工作并修订 PRD
        holder["system"].add_guidance(request.run_id, "product", "请把输出改为大写并更新验收。")
        for _ in range(200):
            if len(holder["system"].project(request.run_id).effective_contracts) >= 2:
                break
            yield ModelStreamEvent(kind="stream_event", id="evt-wait")
        return FakeTurn(writes={"src/echo.py": ECHO})

    def submit_after_the_notification(request):
        seen["notification"] = prompt_part(request, "work_notification")
        return delivery_turn(files={"src/echo.py": ECHO_UPPER})(request)

    adapter = FakeAdapter({
        "product": [
            product_spec(),
            product_spec_turn(
                requirements=["print the given argument in uppercase"],
                acceptance=["running the program with a word prints that word in uppercase"],
                change_record={"changed": ["Output casing"], "retained": ["Echo CLI"], "retired": [],
                               "rationale": "Guidance requires uppercase output."},
            ),
            guidance_reply("已按指导修订产品要求。"),
        ],
        "engineering": [work_through_the_revision, submit_after_the_notification,
                        guidance_reply("已按修订后的产品要求交付。")],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }, stream_gap_sec=0.01)
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("echo")
    projection = system.run_until_stop(run_id)

    notification = json.loads(seen["notification"])
    assert [item["kind"] for item in notification] == ["product_spec_revised"]
    assert notification[0]["revision"] == 2
    assert projection.status == "done", projection.stop_reason
    assert projection.last_review.verdict == "release"


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
    assert result.status == "failed"
    assert result.department_guidance[0].status in {"received", "in_input"}
    assert result.department_guidance[0].status != "completed"
    assert not any(event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED
                   for event in system.store.list_events(run_id))


def test_qa_release_blocked_until_guidance_response(tmp_path):
    # 脚本按部门给出（工单 #877）：质检的脚本按它自己的先后排列
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [delivery_turn()], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo", max_cycles=12)
    system.activate_once(run_id)
    system.activate_once(run_id)
    assert has_new_work(system.project(run_id), "quality")

    system.add_guidance(run_id, "quality", "放行前请核对错误输出边界。")
    adapter.scripts["quality"].append(review_turn("release", "Attempt release before the guidance has a recorded response."))
    blocked = system.activate_once(run_id)
    assert has_new_work(blocked, "quality")
    assert blocked.last_review is None
    assert any(error["field"] == "guidance" for error in blocked.rejections[-1]["errors"])
    assert blocked.department_guidance[0].status in {"received", "in_input"}

    adapter.scripts["quality"].append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), status="explained", text="已核对错误输出边界，可以按当前交付独立复检。",
    )))
    responded = system.activate_once(run_id)
    assert responded.department_guidance[0].status == "explained"
    assert has_new_work(responded, "quality")

    adapter.scripts["quality"].append(review_turn("release", "Independent quality check after the guidance response."))
    done = system.activate_once(run_id)
    assert done.status == "done"
    assert done.last_review.verdict == "release"


def test_qa_reject_then_guidance_completed_does_not_skip_quality(tmp_path):
    # 脚本按部门给出（工单 #877）：质检的脚本按它自己的先后排列
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [delivery_turn()], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo", max_cycles=12)
    system.activate_once(run_id)
    system.activate_once(run_id)
    assert has_new_work(system.project(run_id), "quality")

    system.add_guidance(run_id, "quality", "返工后仍需独立复检，不能把旧放行当作完成。")
    adapter.scripts["quality"].append(review_turn(
        "rework_engineering",
        "Empty input still prints nothing.",
        defects=[{"severity": "major", "summary": "Empty input is not rejected."}],
    ))
    rejected = system.activate_once(run_id)
    assert has_new_work(rejected, "engineering")
    assert rejected.delivery_spec is None
    assert rejected.last_review.verdict == "rework_engineering"
    assert rejected.department_guidance[0].status in {"received", "in_input"}
    rework_activation = rejected.last_activations["quality"]
    assert not any(event.type == EventType.RUN_DONE for event in system.store.list_events(run_id))

    # 指导与缺陷记录都是新的工作，按定义里的部门顺序安排：工程先返工（工单 #560：指导不再插到前面）
    adapter.scripts["engineering"].append(delivery_turn())
    reworked = system.activate_once(run_id)
    assert adapter.invocations[-1].department == "engineering"
    assert reworked.delivery_spec is not None
    assert reworked.last_review.verdict == "rework_engineering"
    assert reworked.department_guidance[0].status in {"received", "in_input"}

    adapter.scripts["quality"].append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), status="explained", text="已记录返工原因；需要工程修复后再做独立质检。",
    )))
    responded = system.activate_once(run_id)
    assert responded.department_guidance[0].status == "explained"
    assert responded.last_activations["quality"] != rework_activation
    assert adapter.invocations[-1].department == "quality"
    assert not any(event.type == EventType.RUN_DONE for event in system.store.list_events(run_id))
    assert has_new_work(responded, "quality")


def test_explain_only_completed_without_result_ids_still_completes(tmp_path):
    # 脚本按部门给出（工单 #877）
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.add_guidance(run_id, "engineering", "请说明当前错误输出边界，无需改文件。")
    adapter.scripts["engineering"].append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), status="explained", text="当前合同已覆盖该边界，无需变更。", result_event_ids=[],
    )))
    result = system.activate_once(run_id)
    assert result.department_guidance[0].status == "explained"
    responded = next(event for event in system.store.list_events(run_id)
                     if event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED)
    assert responded.payload["status"] == "explained"
    assert responded.payload["result_event_ids"] == []


def test_engineering_write_then_completed_without_tool_id_is_host_bound(tmp_path):
    # 脚本按部门给出（工单 #877）
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    assert has_new_work(system.project(run_id), "engineering")

    system.add_guidance(run_id, "engineering", "请修改错误输出处理。")
    adapter.scripts["engineering"].append(lambda request: FakeTurn(
        writes={"src/echo.py": "import sys\nprint(sys.argv[1])\n"},
        proposal=guidance_response(_guidance_id(request), text="已修改文件，但未引用主机结果。"),
    ))
    result = system.activate_once(run_id)
    request = adapter.invocations[-1]
    assert request.department == "engineering"
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

    # 脚本按部门给出（工单 #877）
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.add_guidance(run_id, "engineering", "请修改错误输出处理。")
    adapter.scripts["engineering"].append(FakeTurn(writes={"src/echo.py": "import sys\nprint(sys.argv[1])\n"}))
    adapter.scripts["engineering"].append(complete_with_write)
    result = system.activate_once(run_id)
    assert result.department_guidance[0].status == "completed", result.rejections
    responded = next(event for event in system.store.list_events(run_id)
                     if event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED)
    write = system.store.get_event(responded.payload["result_event_ids"][0])
    assert write.type == EventType.TOOL_CALLED and write.payload["name"] == "write_file"
    assert write.payload["ok"] is True


def test_write_then_later_empty_completed_still_binds_tool_id(tmp_path):
    # 脚本按部门给出（工单 #877）
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.add_guidance(run_id, "engineering", "请修改错误输出处理。")
    adapter.scripts["engineering"].append(lambda request: FakeTurn(
        writes={"src/echo.py": "import sys\nprint(sys.argv[1])\n"},
        proposal=guidance_response(_guidance_id(request), text=""),
    ))
    first = system.activate_once(run_id)
    assert first.department_guidance[0].status in {"received", "in_input"}
    write = next(event for event in system.store.list_events(run_id)
                 if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "write_file"
                 and event.payload.get("ok"))
    adapter.scripts["engineering"].append(lambda request: FakeTurn(proposal=guidance_response(
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
    # 脚本按部门给出（工单 #877）
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [delivery_turn()], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo", max_cycles=12)
    system.activate_once(run_id)
    system.activate_once(run_id)
    before = system.project(run_id)
    assert has_new_work(before, "quality")
    old_delivery_id = before.delivery_spec.created_event_id
    old_check_id = next(
        event.event_id for event in system.store.list_events(run_id)
        if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "run_check"
        and event.payload.get("ok") and event.department == "engineering"
    )
    cited = old_delivery_id if kind == "delivery" else old_check_id

    system.add_guidance(run_id, "product", "请把输出改为大写并更新验收。")
    adapter.scripts["product"].append(product_spec_turn(
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

    adapter.scripts["product"].append(lambda request: FakeTurn(proposal=guidance_response(
        _guidance_id(request), text="已把大写输出写入产品要求。",
    )))
    responded = system.activate_once(run_id)
    assert responded.department_guidance[0].status == "completed"
    assert has_new_work(responded, "engineering")

    system.add_guidance(run_id, "engineering", "请按新合同处理交付。")
    adapter.scripts["engineering"].append(lambda request: FakeTurn(proposal=guidance_response(
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
    # 脚本按部门给出（工单 #877）
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.add_guidance(run_id, "engineering", "请创建 src/guidance-proof.txt，内容为 VERIFIED。")
    adapter.scripts["engineering"].append(lambda request: FakeTurn(proposal=guidance_response(
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
    # 脚本按部门给出（工单 #877）
    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [FakeTurn(
            writes={"src/echo.py": "import sys\nprint(sys.argv[1])\n"},
            proposal=guidance_response("guidance-not-yet", text=""),
        )],
        "quality": [],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    written = system.activate_once(run_id)
    assert has_new_work(written, "engineering"), written.stop_reason
    old_write = next(
        event for event in system.store.list_events(run_id)
        if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "write_file"
        and event.payload.get("ok")
    )
    system.add_guidance(run_id, "engineering", "请创建 src/guidance-proof.txt，内容为 VERIFIED。")
    adapter.scripts["engineering"].append(lambda request: FakeTurn(proposal=guidance_response(
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
    # 脚本按部门给出（工单 #877）
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.add_guidance(run_id, "engineering", "请说明当前错误输出边界，无需改文件。")
    adapter.scripts["engineering"].append(lambda request: FakeTurn(proposal=guidance_response(
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
    # 脚本按部门给出（工单 #877）
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.add_guidance(run_id, "engineering", "请创建 src/guidance-a.txt，内容为 A。")
    system.add_guidance(run_id, "engineering", "请创建 src/guidance-b.txt，内容为 B。")
    adapter.scripts["engineering"].append(lambda request: FakeTurn(
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
    adapter.scripts["engineering"].append(lambda request: FakeTurn(proposal=guidance_response(
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
