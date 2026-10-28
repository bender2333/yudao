from __future__ import annotations

import json
import time
import uuid

from harness.watched_outputs import has_new_work, is_waiting
from harness.adapters.fake import FakeAdapter, FakeTurn, prompt_part
from harness.app.application import Application
from harness.app.project_queries import DepartmentWorkspace
from harness.engine import StepLimits
from harness.models import EventType
from harness.proposals import (
    answer_turn, ask_turn, delivery_turn,
    product_spec, product_spec_turn, review_turn,
)
from harness.providers.call import ModelResponse, ModelStreamEvent
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_api
from harness.tests.helpers import after_event, from_another_thread, guidance_reply, quality_turns
from harness.tools import tools_for

ECHO = "import sys\nprint(sys.argv[1])\n"
ECHO_UPPER = "import sys\nprint(sys.argv[1].upper())\n"

# 这个文件里的脚本按部门给出，三个部门都写上（工单 #943）：质检在这些用例里不工作，给它的是空脚本。
# 脚本里没有它的名字时，假模型在它真的发请求时报「脚本用尽」，整个 run 以 provider_error 提前结束，
# 用例在到达要核对的那一步以前就失败（工单 #935 查出的成因，工单 #943 收尾）
# 指导不再由部门提交正式回应（工单 #1038）：它作为关注的成果让部门开始一轮工作，这一轮正常结束时
# 主机写已回答事件（工单 #1039）；只有指导、没有要做的工作时，不调用工具的文字回复就是这一轮的收尾。


def _tool_names(request):
    return [item["name"] for item in request.tools]


def test_guidance_is_persisted_bound_to_target_and_entered_before_request(tmp_path):
    # 脚本按部门给出（工单 #877：PRD 被接纳以后工程与质检同时工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [delivery_turn()], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    project_id = system.projects.register("指导", "把文本按行处理清楚")
    work_item_id, run_id = system.projects.start_work_item(project_id, "echo")
    system.activate_once(run_id)
    system.activate_once(run_id)

    system.add_guidance(run_id, "engineering", "请优先检查错误输出的边界行为。")
    # 发出以后是已接收：还没有进入任何一轮的模型输入
    assert system.project(run_id).department_guidance[0].status == "received"
    adapter.scripts["engineering"].append(guidance_reply("已检查边界行为，当前指导不改变产品合同。"))
    result = system.activate_once(run_id)

    guidance = result.department_guidance[0]
    assert guidance.department == "engineering"
    # 收到它的那一轮工作正常结束（以文字回答）以后是已回答，主机在同一个事务里写（工单 #1039）
    assert guidance.status == "answered"
    assert guidance.outcome == "text_reply"
    assert guidance.text in prompt_part(adapter.invocations[-1], "department_guidance")
    events = system.store.list_events(run_id)
    assert any(event.type == EventType.DEPARTMENT_GUIDANCE_RECEIVED for event in events)
    applied = next(event for event in events if event.type == EventType.DEPARTMENT_GUIDANCE_APPLIED)
    assert guidance.id in applied.payload["guidance_ids"]
    [responded] = [event for event in events if event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED]
    assert responded.payload == {
        "guidance_id": guidance.id,
        "activation_id": applied.payload["activation_id"],
        "outcome": "text_reply",
    }

    application = Application(system)
    engineering = application.query("department.workspace", DepartmentWorkspace(
        project_id=project_id, department="engineering", work_item=work_item_id))
    assert engineering.data.guidance[0].text == guidance.text
    assert engineering.data.guidance[0].status == "answered"
    assert engineering.data.guidance[0].outcome == "text_reply"
    product = application.query("department.workspace", DepartmentWorkspace(
        project_id=project_id, department="product", work_item=work_item_id))
    assert not any(message.get("text") == guidance.text for message in product.data.messages)


def test_guidance_goes_from_received_to_in_input_to_answered(tmp_path):
    # 验收第 1 条：指导的三个状态各有证据。发出以后是已接收；进入部门的模型输入以后是已进入模型输入；
    # 收到它的那一轮正常结束以后是已回答，事件记 activation_id 与 outcome（工单 #1039）
    holder = {}
    seen = {}

    def record_the_state_during_the_request(request):
        # 模型调用开始时指导的应用事件已经写好，此刻读投影就是已进入模型输入
        seen["status"] = holder["system"].project(request.run_id).department_guidance[0].status
        return guidance_reply("当前合同已覆盖该边界，无需变更。")(request)

    adapter = FakeAdapter({"product": [product_spec()], "engineering": [delivery_turn(), record_the_state_during_the_request],
                           "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.activate_once(run_id)

    system.add_guidance(run_id, "engineering", "请说明当前错误输出边界，无需改文件。")
    assert system.project(run_id).department_guidance[0].status == "received"
    result = system.activate_once(run_id)

    assert seen["status"] == "in_input"
    guidance = result.department_guidance[0]
    assert guidance.status == "answered"
    assert guidance.outcome == "text_reply"
    applied = next(event for event in system.store.list_events(run_id)
                   if event.type == EventType.DEPARTMENT_GUIDANCE_APPLIED)
    assert guidance.answered_activation_id == applied.payload["activation_id"]
    [responded] = [event for event in system.store.list_events(run_id)
                   if event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED]
    assert responded.payload["activation_id"] == applied.payload["activation_id"]
    assert responded.payload["outcome"] == "text_reply"


def test_guidance_for_a_waiting_department_starts_a_full_round(tmp_path):
    # 验收第 1 条（在等待工作）：指导是接收部门关注的成果，它在这一轮开始一轮完整的工作，
    # 可以读取、写入、运行检查、询问与提交正式成果（循环结构第 6 节，工单 #560）；
    # 不为它另设一种只回应指导的轮次（工单 #556 的过渡做法已删除），也没有提交回应的工具（工单 #1038）
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [delivery_turn()], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    assert has_new_work(system.project(run_id), "quality")

    system.add_guidance(run_id, "engineering", "请说明本次交付的错误处理边界。")
    adapter.scripts["engineering"].append(guidance_reply("已说明错误处理边界；该指导不改变产品要求。"))
    result = system.activate_once(run_id)

    assert has_new_work(result, "quality")
    assert result.active_department == "engineering"
    # 这一轮以文字回答结束：主机写已回答（工单 #1039）
    assert result.department_guidance[0].status == "answered"
    names = _tool_names(adapter.invocations[-1])
    assert {"read_file", "write_file", "run_check", "ask", "submit_delivery"} <= set(names)
    # 待处理指导不再带来额外的提交工具：这一轮提供的工具正好是角色的工具清单（工单 #1038）
    assert names == list(tools_for("engineering"))


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
    # 指导在这一轮提交以后才作为通知送达，这一轮没有把它送进模型输入：它停在已接收，
    # 由收到它的下一轮工作结束时的已回答接上（工单 #1039）
    assert result.department_guidance[0].status == "received"
    assert not any(event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED
                   for event in system.store.list_events(run_id))
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


def test_product_guidance_during_engineering_is_full_product_turn(tmp_path):
    # 脚本按部门给出（工单 #877）
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    assert has_new_work(system.project(run_id), "engineering")

    system.add_guidance(run_id, "product", "请确认未知参数是否需要写入验收。")
    adapter.scripts["product"].append(guidance_reply("当前合同已覆盖该行为，无需改需求。"))
    result = system.activate_once(run_id)
    request = adapter.invocations[-1]
    names = _tool_names(request)
    assert request.department == "product"
    assert "submit_product_spec" in names
    # 待处理指导不再带来额外的提交工具：这一轮提供的工具正好是角色的工具清单（工单 #1038）
    assert names == list(tools_for("product"))
    # 这一轮以文字回答结束，主机写已回答（工单 #1039）
    assert result.department_guidance[0].status == "answered"
    assert result.department_guidance[0].outcome == "text_reply"
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
    # 收到指导的那一轮以提交被接纳结束：主机写已回答，事件记 proposal_accepted（工单 #1039）
    assert revised.department_guidance[0].status == "answered"
    assert revised.department_guidance[0].outcome == "proposal_accepted"

    # 由关注的成果决定下一个谁工作：PRD 有了新版本，工程开始一轮返工（工单 #556）
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
    # 这一轮就是指导的处理：交付被接纳以后主机写已回答，工程不再为它开始第二轮（工单 #1039）
    assert result.department_guidance[0].status == "answered"
    assert result.department_guidance[0].outcome == "proposal_accepted"

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
    # 验收第 3 条（工单 #1039）：询问分支的会话结束不写已回答；写它的是收到指导的那一轮主线会话。
    # 分支里结束的那一次激活是另一个会话，没有它的回答记录
    assert result.department_guidance[0].status == "answered"
    assert result.department_guidance[0].outcome == "proposal_accepted"
    applied = next(event for event in system.store.list_events(run_id)
                   if event.type == EventType.DEPARTMENT_GUIDANCE_APPLIED)
    branch_activations = {event.payload["activation_id"] for event in system.store.list_events(run_id)
                          if event.type == EventType.ACTIVATION_FINISHED
                          and event.payload["activation_id"] != applied.payload["activation_id"]}
    assert branch_activations
    responded = [event.payload["activation_id"] for event in system.store.list_events(run_id)
                 if event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED]
    assert responded == [applied.payload["activation_id"]]
    assert not branch_activations & set(responded)


def test_a_round_that_ends_the_item_still_writes_answered(tmp_path):
    # 验收第 1 条：收到指导的那一轮以放行结束、事项随这一轮完成，同样写已回答。
    # 这一轮的结束状态是已完成，不是暂停或失败，所以不算「这一轮没有正常结束」
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [delivery_turn()],
                           "quality": [review_turn("release", "checks passed on the current delivery")]})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.add_guidance(run_id, "quality", "请按当前交付核验并放行。")
    result = system.activate_once(run_id)

    assert result.status == "done"
    assert result.last_review.verdict == "release"
    assert result.department_guidance[0].status == "answered"
    assert result.department_guidance[0].outcome == "proposal_accepted"
    [responded] = [event for event in system.store.list_events(run_id)
                   if event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED]
    assert responded.payload["outcome"] == "proposal_accepted"


def test_a_limit_that_stops_the_round_does_not_write_answered(tmp_path):
    # 验收第 3 条（工单 #1039）：模型步数上限让这一轮停下不算正常结束，指导停在已进入模型输入
    def list_files(request):
        identity = f"list-{request.activation_id}-{request.step_id}"
        return ModelResponse(output=[{"id": identity, "call_id": identity, "type": "function_call",
                                      "name": "list_files", "arguments": "{}"}])

    adapter = FakeAdapter({"product": [product_spec()], "engineering": [delivery_turn(), list_files], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter, step_limits=StepLimits(max_model_steps=1))
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.add_guidance(run_id, "engineering", "请核对错误输出的边界。")
    result = system.activate_once(run_id)

    assert result.status == "paused"
    assert result.stop_reason == "model_steps_exhausted"
    assert result.department_guidance[0].status == "in_input"
    assert not any(event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED
                   for event in system.store.list_events(run_id))


def test_running_out_of_time_does_not_write_answered(tmp_path):
    # 验收第 3 条（工单 #1039）：运行时间用完不算这一轮正常结束，指导停在已进入模型输入
    def slow_spec(request):
        time.sleep(3.2)
        return product_spec()

    adapter = FakeAdapter({"product": [slow_spec], "engineering": [delivery_turn()], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo", run_time_limit_sec=3)
    system.add_guidance(run_id, "product", "请补充输入校验的处理说明。")
    result = system.activate_once(run_id)

    assert result.status == "failed"
    assert result.stop_reason == "time_limit"
    assert result.department_guidance[0].status == "in_input"
    assert not any(event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED
                   for event in system.store.list_events(run_id))


def test_guidance_for_one_department_is_delivered_in_receive_order(tmp_path):
    # 验收第 4 条：同一个部门连续收到两段指导，按接收的顺序进入它的模型输入；
    # 收到它们的那一轮工作就是它们的处理（工单 #1038）
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [delivery_turn()], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.add_guidance(run_id, "engineering", "先核对错误输出的边界。")
    system.add_guidance(run_id, "engineering", "再核对空输入的边界。")

    adapter.scripts["engineering"].append(guidance_reply("两段指导都已核对。"))
    result = system.activate_once(run_id)
    delivered = json.loads(prompt_part(adapter.invocations[-1], "department_guidance"))
    assert [item["text"] for item in delivered] == ["先核对错误输出的边界。", "再核对空输入的边界。"]
    assert [item["version"] for item in delivered] == [1, 2]
    # 验收第 4 条：一轮里收到两条指导，结束时各写一条已回答（工单 #1039）
    assert [item.status for item in result.department_guidance] == ["answered", "answered"]
    assert [item.outcome for item in result.department_guidance] == ["text_reply", "text_reply"]
    responded = [event.payload for event in system.store.list_events(run_id)
                 if event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED]
    assert [(item["guidance_id"], item["outcome"]) for item in responded] == [
        (result.department_guidance[0].id, "text_reply"),
        (result.department_guidance[1].id, "text_reply"),
    ]
    assert len({item["activation_id"] for item in responded}) == 1


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
    # 验收第 3 条：取消不算处理完。已经接收的指导保留可查，停在已进入模型输入，没有已回答的记录
    holder = {}

    def cancel_during(request):
        holder["system"].cancel(request.run_id)
        return FakeTurn(transcript="取消以后这段回复不改变指导的状态。")

    adapter = FakeAdapter([])
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("echo")
    system.add_guidance(run_id, "product", "请补充输入校验的处理说明。")
    adapter.script.append(cancel_during)
    result = system.activate_once(run_id)

    assert result.stop_reason == "cancelled"
    assert result.status == "failed"
    # 取消以后指导停在已进入模型输入：它已经在这一次的模型输入里，但这一轮没有正常结束
    assert result.department_guidance[0].status == "in_input"
    assert any(event.type == EventType.DEPARTMENT_GUIDANCE_APPLIED
               for event in system.store.list_events(run_id))
    assert not any(event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED
                   for event in system.store.list_events(run_id))


def test_a_guidance_only_round_ends_with_a_text_reply(tmp_path):
    # 验收第 1 条（工单 #1037）：工程在等待工作时收到一段指导，这一轮关注的成果里只有指导；
    # 脚本回复纯文字，这一轮正常结束，部门回到等待，没有 tool_call_required 事件，事项继续运行
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [delivery_turn()], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    delivered = system.activate_once(run_id)
    assert delivered.delivery_spec is not None and is_waiting(delivered, "engineering")

    system.add_guidance(run_id, "engineering", "请说明错误输出的边界行为，不需要改文件。")
    adapter.scripts["engineering"].append(
        lambda request: FakeTurn(transcript="错误输出写到 stderr，退出码为 1。"))
    result = system.activate_once(run_id)

    assert adapter.invocations[-1].department == "engineering"
    # 这一轮只有一次模型调用：文字回复以后不追加提醒，也不再调用模型
    assert [call.department for call in adapter.invocations].count("engineering") == 2
    assert result.status == "running"
    assert is_waiting(result, "engineering")
    assert not any(event.type == EventType.TOOL_CALL_REQUIRED
                   for event in system.store.list_events(run_id))
    # 这一轮正常结束，主机写已回答：指导从已进入模型输入变成已回答，事件记 activation_id 与 outcome
    assert result.department_guidance[0].status == "answered"
    assert result.department_guidance[0].outcome == "text_reply"
    assert result.department_guidance[0].answered_activation_id
    [responded] = [event for event in system.store.list_events(run_id)
                   if event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED]
    assert responded.payload["guidance_id"] == result.department_guidance[0].id
    assert responded.payload["outcome"] == "text_reply"


def test_guidance_arriving_during_an_ongoing_round_does_not_end_it_with_a_text_reply(tmp_path):
    # 验收第 3 条（工单 #1037）：指导作为通知送达一轮正在进行的工作时，纯文字回复不结束这一轮；
    # 这一轮开始时还有新的 PRD，关注的成果不只有指导，仍按「要求调用工具」处理
    holder = {}
    seen = {}

    def reply_text_while_guidance_arrives(request):
        holder["system"].add_guidance(request.run_id, "engineering", "交付前说明错误输出的边界。")
        return FakeTurn(transcript="我先说明边界，然后继续交付。")

    def deliver_after_the_notification(request):
        seen["guidance"] = prompt_part(request, "department_guidance")
        return delivery_turn()(request)

    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [reply_text_while_guidance_arrives, deliver_after_the_notification],
        "quality": [],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    result = system.activate_once(run_id)

    # 文字回复不结束这一轮：工程在下一步收到提醒与指导，接着交付
    assert result.delivery_spec is not None
    assert [item["text"] for item in json.loads(seen["guidance"])] == ["交付前说明错误输出的边界。"]
    required = [event for event in system.store.list_events(run_id)
                if event.type == EventType.TOOL_CALL_REQUIRED]
    assert [(event.department, event.payload["count"]) for event in required] == [("engineering", 1)]
    assert is_waiting(result, "engineering")
    # 验收第 2 条（工单 #1039）：指导作为通知送达一轮正在进行的工作，那一轮正常结束时同样写已回答，
    # 不是只有「以指导开始的一轮」才写；这一轮以交付被接纳结束
    assert result.department_guidance[0].status == "answered"
    assert result.department_guidance[0].outcome == "proposal_accepted"
    applied = next(event for event in system.store.list_events(run_id)
                   if event.type == EventType.DEPARTMENT_GUIDANCE_APPLIED)
    [responded] = [event for event in system.store.list_events(run_id)
                   if event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED]
    assert responded.payload["activation_id"] == applied.payload["activation_id"]
    assert responded.payload["outcome"] == "proposal_accepted"


def test_guidance_arriving_during_a_write_keeps_the_write_and_reaches_the_next_step(tmp_path):
    # 反例 2：模型要求写入文件、写入工具正在进行时收到指导——已经写入的内容保留，
    # 下一步看到真实的工作区与这条指导
    holder = {}
    seen = {}
    written = "import sys\nprint(sys.argv[1].upper())\n"

    def deliver_after_the_notification(request):
        seen["guidance"] = prompt_part(request, "department_guidance")
        seen["workspace"] = holder["system"].workspace(request.run_id).read_file("src/echo.py")
        # 交付只补一个说明文件：这一轮不再改写 src/echo.py，写入的内容留在工作区里
        return delivery_turn(summary="uppercase output", files={"src/notes.txt": "输出改为大写。\n"})(request)

    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [FakeTurn(writes={"src/echo.py": written}), deliver_after_the_notification],
        "quality": [],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("echo")
    system.activate_once(run_id)

    # 写入工具开始时把指导交给工程：这时写入还在进行，指导已经到达
    after_event(system, EventType.TOOL_STARTED,
                lambda event: from_another_thread(
                    lambda: system.add_guidance(run_id, "engineering", "请把输出改为大写并重新交付。"))
                if (event.department, (event.payload or {}).get("name")) == ("engineering", "write_file")
                else None)
    result = system.activate_once(run_id)

    # 写入保留：工作区里就是这次写入的内容，下一步看到的也是它
    assert seen["workspace"] == written
    assert system.workspace(run_id).read_file("src/echo.py") == written
    written_events = [event for event in system.store.list_events(run_id)
                      if event.type == EventType.TOOL_CALLED
                      and (event.payload or {}).get("name") == "write_file"]
    assert written_events[0].payload["args"] == {"path": "src/echo.py", "content": written}
    assert all(event.payload["ok"] for event in written_events)
    # 指导在写入这条调用之后才进入模型输入
    applied = next(event for event in system.store.list_events(run_id)
                   if event.type == EventType.DEPARTMENT_GUIDANCE_APPLIED)
    assert applied.position > written_events[0].position
    # 指导在下一步的模型输入里，这一轮正常结束以后写已回答
    assert [item["text"] for item in json.loads(seen["guidance"])] == ["请把输出改为大写并重新交付。"]
    assert result.department_guidance[0].status == "answered"
    assert result.delivery_spec is not None and result.delivery_spec.status == "active"


def test_cancel_arriving_with_guidance_cancels_at_once_and_keeps_the_guidance(tmp_path):
    # 反例 6：取消与指导几乎同时到达——取消立即生效，已经接收的指导保留可查，不算处理过
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [delivery_turn()], "quality": []})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)

    after_event(system, EventType.DEPARTMENT_GUIDANCE_RECEIVED,
                lambda event: from_another_thread(lambda: system.cancel(run_id)))
    system.add_guidance(run_id, "engineering", "请把输出改为大写并重新交付。")
    result = system.run_until_stop(run_id)

    # 取消立即生效：事项以取消结束，工程与质检都没有再开始工作
    assert result.status == "failed"
    assert result.stop_reason == "cancelled"
    assert not any(event.type == EventType.MODEL_REQUESTED and event.department != "product"
                   for event in system.store.list_events(run_id))
    # 已经接收的指导保留可查：没有丢掉，也没有被当成处理过
    assert result.department_guidance[0].status == "received"
    assert result.department_guidance[0].text == "请把输出改为大写并重新交付。"
    assert not any(event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED
                   for event in system.store.list_events(run_id))

