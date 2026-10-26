# 质检的放行等发给产品的输入处理完（工单 #561，部门指导设计说明第 2.1 节「放行怎么等」、第 3 节「处理完只有一个说法」、
# 第 4 节第 8 条）。等待留在步骤驱动的安全节点上：不返回模型、不写事件、不占步数，重启以后没有处置的工具调用重新执行。
# 这些用例只经命令、事件流与查询检查做成了什么（测试分层设计说明第 13 节）：等待不写事件、不占步数、
# 工具调用先有许可、边界（取消与运行时间）照常生效守 R1；放行等到输入处理完、修订 PRD 以后拒绝并通知、
# 缺陷记录不等守 R3。

from __future__ import annotations

import json
import time
from dataclasses import asdict

from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn, prompt_part
from harness.event_store import run_stream
from harness.models import EventType, json_dumps
from harness.projection import saved_decisions
from harness.proposals import (
    answer_turn, ask_turn, delivery_turn, product_decision, product_spec, product_spec_turn, review_turn,
)
from harness.providers.call import ModelStreamEvent
from harness.runtime import LoopSystem
from harness.tests.helpers import after_event, from_another_thread, quality_turns
from harness.write_path import NewEvent

CHANGE_RECORD = {
    "changed": ["Print the argument in uppercase"],
    "retained": ["Accept one command-line argument"],
    "retired": ["Preserve original letter casing"],
    "rationale": "The user asked for uppercase output.",
}
UNAVAILABLE = "Missing configuration: provider credential"


def _events(system: LoopSystem, run_id: str):
    return system.store.list_events(run_id)


def _position(system: LoopSystem, run_id: str, predicate) -> int:
    return next(event.position for event in _events(system, run_id) if predicate(event))


def _quality_events(system: LoopSystem, run_id: str, kind: str):
    return [event for event in _events(system, run_id)
            if event.type == kind and event.department == "quality"]


def _wait_for_the_release_attempt(holder, run_id):
    # 产品这一轮等质检把放行前面的检查跑完再继续：放行的调用排在检查之后，许可在这里紧接着做，
    # 所以这一轮结束时放行一定已经在等待；等待期间交出流式片段，让质检的会话得到调度
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if any(event.type == EventType.TOOL_CALLED and event.department == "quality"
               and (event.payload or {}).get("name") == "run_check"
               for event in _events(holder["system"], run_id)):
            holder["release_attempted"] = True
            return
        yield ModelStreamEvent(kind="stream_event", id="evt-wait")


def _wait_for_the_defect_record(holder, run_id):
    # 产品这一轮等质检把缺陷记录提交出去以后再结束：缺陷记录不等输入处理完
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if any(event.type == EventType.TOOL_CALLED and event.department == "quality"
               and (event.payload or {}).get("name") == "submit_review"
               for event in _events(holder["system"], run_id)):
            holder["defect_submitted"] = True
            return
        yield ModelStreamEvent(kind="stream_event", id="evt-wait")


def test_a_release_waits_until_the_product_round_ends(tmp_path):
    # 验收第 1 条（1）：质检提交放行时产品正在一轮工作中处理用户的新输入，放行等到这一轮结束再裁决；
    # 产品没有修订 PRD，放行被接纳（反例 8 的前两句）
    holder: dict[str, object] = {}

    def process_the_input(request):
        yield from _wait_for_the_release_attempt(holder, request.run_id)
        return FakeTurn(transcript="输出保持小写，产品要求不变。")

    adapter = FakeAdapter({
        "product": [product_spec(), process_the_input],
        "engineering": [delivery_turn()],
        "quality": quality_turns("release", "checks passed on the current delivery"),
    }, stream_gap_sec=0.01)
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.add_guidance(run_id, "product", "请确认输出保持小写，产品要求不变。")
    projection = system.run_until_stop(run_id)

    # 质检确实先发出了放行调用，产品这一轮还在工作
    assert holder.get("release_attempted")
    # 这一轮正常结束，主机写已回答：输入处理完了
    assert projection.department_guidance[0].status == "answered"
    product_end = max(event.position for event in _events(system, run_id)
                      if event.type == EventType.ACTIVATION_FINISHED and event.department == "product")
    [release] = _quality_events(system, run_id, EventType.PROPOSAL_SUBMITTED)
    assert release.position > product_end
    # 产品没有修订 PRD：放行被接纳，事项结束
    assert projection.status == "done"
    assert projection.last_review.verdict == "release"


def test_a_release_is_rejected_after_the_product_revises_the_prd(tmp_path):
    # 验收第 1 条（3）：放行等到产品的这一轮结束以后才裁决，产品修订了 PRD，
    # 放行因交付依据的是旧版本被拒绝；质检下一步看到新版本的通知
    holder: dict[str, object] = {}
    seen: dict[str, str | None] = {}

    def revise_the_prd(request):
        yield from _wait_for_the_release_attempt(holder, request.run_id)
        return product_spec_turn(
            requirements=["print the given argument in uppercase"],
            acceptance=["running the program with a word prints that word in uppercase"],
            change_record=CHANGE_RECORD,
        )(request)

    quality_round = quality_turns("release", "checks passed on the current delivery")[0]

    def observe_the_notification(request):
        seen["notification"] = prompt_part(request, "work_notification")
        return quality_round(request)

    adapter = FakeAdapter({
        "product": [product_spec(), revise_the_prd],
        "engineering": [delivery_turn(), delivery_turn()],
        "quality": [review_turn("release", "checks passed on the current delivery"), observe_the_notification]
                   + quality_turns("release", "checks passed on the current delivery"),
    }, stream_gap_sec=0.01)
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("build echo", max_cycles=16)
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.add_guidance(run_id, "product", "请把输出改为大写并更新验收。")
    projection = system.run_until_stop(run_id)

    assert holder.get("release_attempted")
    product_end = max(event.position for event in _events(system, run_id)
                      if event.type == EventType.ACTIVATION_FINISHED and event.department == "product")
    rejected = [event for event in _events(system, run_id)
                if event.type == EventType.PROPOSAL_REJECTED and event.department == "quality"]
    assert rejected, "放行没有被裁决"
    assert rejected[0].position > product_end
    # 质检下一步看到 PRD 新版本的通知：修订号与改动（新的交付可能同时到达，也一并通知）
    notification = json.loads(seen["notification"])
    revised = [item for item in notification if item["kind"] == "product_spec_revised"]
    assert len(revised) == 1
    assert revised[0]["revision"] == 2
    # 新交付到达以后照常核验并放行
    assert projection.status == "done", projection.error
    assert projection.last_review.verdict == "release"


def test_the_wait_writes_no_events_and_takes_no_model_steps(tmp_path):
    # 验收第 3 条：等待期间质检的会话不写事件、不多用模型步数（产品自己那一轮的事件除外）；
    # 醒来以后才写下这一次调用的结果
    holder: dict[str, object] = {}

    def process_the_input(request):
        yield from _wait_for_the_release_attempt(holder, request.run_id)
        return FakeTurn(transcript="输出保持小写，产品要求不变。")

    adapter = FakeAdapter({
        "product": [product_spec(), process_the_input],
        "engineering": [delivery_turn()],
        "quality": quality_turns("release", "checks passed on the current delivery"),
    }, stream_gap_sec=0.01)
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.add_guidance(run_id, "product", "请确认输出保持小写，产品要求不变。")
    projection = system.run_until_stop(run_id)
    assert projection.status == "done"

    events = _events(system, run_id)
    release_attempt = next(event.position for event in events
                           if event.type == EventType.TOOL_CALLED and event.department == "quality"
                           and (event.payload or {}).get("name") == "run_check")
    product_end = max(event.position for event in events
                      if event.type == EventType.ACTIVATION_FINISHED and event.department == "product")
    assert release_attempt < product_end
    during = [event for event in events if release_attempt < event.position < product_end]
    # 等待期间质检没有任何事件：没有 tool_started、tool_called，也没有新的模型请求
    assert [event.type for event in during if event.department == "quality"] == []
    steps_before = len([event for event in events
                        if event.type == EventType.MODEL_REQUESTED and event.department == "quality"
                        and event.position < release_attempt])
    steps_during = len([event for event in events
                        if event.type == EventType.MODEL_REQUESTED and event.department == "quality"
                        and event.position < product_end])
    assert steps_before == steps_during
    # 醒来以后才写工具开始与结果
    after = [event.type for event in events
             if event.position > product_end and event.department == "quality"]
    assert after[:2] == [EventType.TOOL_STARTED, EventType.TOOL_CALLED]


def test_cancel_while_the_release_waits_cancels_the_item_without_a_release(tmp_path):
    # 验收第 2 条：等待期间取消，事项取消、没有放行
    holder: dict[str, object] = {}

    def cancel_during_the_wait(request):
        yield from _wait_for_the_release_attempt(holder, request.run_id)
        holder["system"].cancel(request.run_id)
        return FakeTurn(transcript="取消以后这段回复不改变任何结果。")

    adapter = FakeAdapter({
        "product": [product_spec(), cancel_during_the_wait],
        "engineering": [delivery_turn()],
        "quality": quality_turns("release", "checks passed on the current delivery"),
    }, stream_gap_sec=0.01)
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.add_guidance(run_id, "product", "请确认输出保持小写，产品要求不变。")
    projection = system.run_until_stop(run_id)

    assert holder.get("release_attempted")
    assert projection.status == "failed"
    assert projection.stop_reason == "cancelled"
    # 没有放行，也没有提交放行的记录
    assert projection.last_review is None
    assert _quality_events(system, run_id, EventType.PROPOSAL_SUBMITTED) == []


def test_running_out_of_time_while_the_release_waits_ends_the_run(tmp_path):
    # 验收第 2 条：运行时间用完在等待期间照常生效，事项以 time_limit 结束，没有放行
    holder: dict[str, object] = {}

    def keep_the_round_open(request):
        yield from _wait_for_the_release_attempt(holder, request.run_id)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if holder["system"].project(request.run_id).status in {"done", "paused", "failed"}:
                break
            yield ModelStreamEvent(kind="stream_event", id="evt-wait")
        return FakeTurn(transcript="这一轮被运行时间用完了。")

    adapter = FakeAdapter({
        "product": [product_spec(), keep_the_round_open],
        "engineering": [delivery_turn()],
        "quality": quality_turns("release", "checks passed on the current delivery"),
    }, stream_gap_sec=0.01)
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("build echo", run_time_limit_sec=2)
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.add_guidance(run_id, "product", "请确认输出保持小写，产品要求不变。")
    projection = system.run_until_stop(run_id)

    assert holder.get("release_attempted")
    assert projection.status == "failed"
    assert projection.stop_reason == "time_limit"
    assert projection.last_review is None
    assert _quality_events(system, run_id, EventType.PROPOSAL_SUBMITTED) == []


def test_a_model_unavailable_stops_the_wait_without_a_release(tmp_path):
    # 验收第 2 条：等待期间产品那一轮遇到模型不可用，写出阻塞整个事项的决定请求，
    # 质检的等待停下、没有放行（工单 #561 第三次分诊第 2 条，参照工单 #856 的用例）。
    # 等待用的安全节点与等待模型服务重试是同一个，停止判断读阻塞整个事项的决定请求
    # （部门指导设计说明第 2.1 节第 1 点）；步数上限不在等待期间判，因为等待不调用模型
    holder: dict[str, object] = {}

    def model_unavailable_while_the_release_waits(request):
        # 等质检的放行确实走进等待，这一轮再遇到模型不可用：决定请求写出时放行正在等
        yield from _wait_for_the_release_attempt(holder, request.run_id)
        raise ProviderError(UNAVAILABLE, reason="provider_unavailable")

    adapter = FakeAdapter({
        "product": [product_spec(), model_unavailable_while_the_release_waits],
        "engineering": [delivery_turn()],
        "quality": quality_turns("release", "checks passed on the current delivery"),
    }, stream_gap_sec=0.01)
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("build echo", max_cycles=16)
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.add_guidance(run_id, "product", "请确认输出保持小写，产品要求不变。")
    projection = system.run_until_stop(run_id)

    assert holder.get("release_attempted")
    # 产品那一轮写出了阻塞整个事项的决定请求：范围是整个事项，部门的模型不可用
    _position, decisions = saved_decisions(system.store, statuses=("open",))
    assert len(decisions) == 1, [decision.decision_id for decision in decisions]
    [decision] = decisions
    assert (decision.request["kind"], decision.request["blocks"]) == ("model_unavailable", "run")
    assert decision.request["department"] == "product"
    # 等待停下：放行没有裁决、没有放行，事项也没有以取消或运行时间用完结束
    assert projection.status == "running", projection.stop_reason
    assert projection.last_review is None
    assert _quality_events(system, run_id, EventType.PROPOSAL_SUBMITTED) == []


def test_a_defect_record_does_not_wait_for_the_product_input(tmp_path):
    # 验收第 5 条：质检提交缺陷记录不等，输入没处理完时也能提交
    holder: dict[str, object] = {}

    def process_the_input(request):
        yield from _wait_for_the_defect_record(holder, request.run_id)
        return FakeTurn(transcript="产品的要求没有因此改变。")

    adapter = FakeAdapter({
        "product": [product_spec(), process_the_input],
        "engineering": [delivery_turn(), delivery_turn()],
        "quality": [review_turn("rework_engineering", "the delivery misses the acceptance criterion",
                                defects=[{"severity": "major", "summary": "uppercase output missing"}])]
                   + quality_turns("release", "checks passed on the current delivery"),
    }, stream_gap_sec=0.01)
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("build echo", max_cycles=16)
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.add_guidance(run_id, "product", "请确认输出保持小写，产品要求不变。")
    projection = system.run_until_stop(run_id)

    assert holder.get("defect_submitted")
    product_end = max(event.position for event in _events(system, run_id)
                      if event.type == EventType.ACTIVATION_FINISHED and event.department == "product")
    defect = next(event for event in _events(system, run_id) if event.type == EventType.QA_SUBMITTED)
    # 缺陷记录在产品这一轮结束以前就提交并裁决了
    assert defect.position < product_end
    assert defect.payload["verdict"] == "rework_engineering"
    assert projection.last_review.verdict == "release"


def test_a_release_that_waits_survives_a_restart(tmp_path):
    # 验收第 1 条（4）：放行在等产品这一轮结束的时候进程退出；重启以后这条没有处置的工具调用重新执行，
    # 仍然等到产品处理完，然后照常裁决
    first = LoopSystem.for_testing(tmp_path, FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [],
    }))
    run_id = first.create_run("build echo")
    first.activate_once(run_id)
    first.activate_once(run_id)
    before = first.project(run_id)
    assert before.delivery_spec is not None
    session_id = before.sessions["quality"].session_id
    # 输入在质检提交放行以前到达：放行要等产品这一轮结束
    first.add_guidance(run_id, "product", "请确认输出保持小写，产品要求不变。")
    # 中断前的状态：质检的模型响应已经保存，这条提交放行的调用既没有 tool_started 也没有结果
    item = {
        "id": "release-wait", "call_id": "release-wait", "type": "function_call",
        "name": "submit_review",
        "arguments": json_dumps({
            "verdict": "release",
            "rationale": "checks passed on the current delivery",
            "checks": {},
            "defects": [],
            "basis_delivery_spec_hash": before.delivery_spec.content_hash,
        }),
    }
    ref = first.artifacts.put(run_id, "model_message", json.dumps(item, ensure_ascii=False),
                              media_type="application/json")
    first.writes.append(run_stream(run_id), NewEvent(
        EventType.MODEL_MESSAGE, actor="department:quality", department="quality",
        state_before="running", state_after="running", session_id=session_id,
        payload={"message_ref": asdict(ref), "message_index": 1,
                 "activation_id": "act_release_wait", "step_id": 1, "purpose": "work"}))
    first.close()

    restarted = LoopSystem.for_testing(tmp_path, FakeAdapter({
        "product": [FakeTurn(transcript="输出保持小写，产品要求不变。")],
        "engineering": [],
        "quality": [review_turn("release", "checks passed on the current delivery", checks={})],
    }), resume_on_startup=False)
    restarted.orchestrator.resume_incomplete_run(run_id)
    projection = restarted.run_until_stop(run_id)

    events = _events(restarted, run_id)
    product_end = max(event.position for event in events
                      if event.type == EventType.ACTIVATION_FINISHED and event.department == "product")
    [recovered] = [event for event in events
                   if event.type == EventType.TOOL_CALLED and (event.payload or {}).get("id") == "release-wait"]
    # 这条调用重新执行过：等到产品这一轮结束才写工具开始与结果
    assert recovered.payload["name"] == "submit_review"
    assert recovered.payload["ok"] is True
    assert recovered.position > product_end
    assert projection.status == "done", projection.error
    assert projection.last_review.verdict == "release"
    restarted.close()


def test_the_product_can_ask_quality_while_the_release_waits(tmp_path):
    # 验收第 4 条：放行在等产品处理输入的时候，产品这一轮询问质检——询问在它的分支会话里得到回答，
    # ASK_ANSWERED 的状态是 answered，没有死锁；放行在这一轮结束以后照常裁决
    holder: dict[str, object] = {}

    def ask_while_the_release_waits(request):
        # 等质检先走进放行的等待，再提出询问：问的时候质检正在等这一轮结束
        yield from _wait_for_the_release_attempt(holder, request.run_id)
        return ask_turn("quality", "大写输出是否覆盖了验收条件？")

    def end_the_round(request):
        return FakeTurn(transcript="大写输出已经覆盖验收条件，产品要求不变。")

    adapter = FakeAdapter({
        "product": [product_spec(), ask_while_the_release_waits, end_the_round],
        "engineering": [delivery_turn()],
        "quality": quality_turns("release", "checks passed on the current delivery"),
        "quality:ask": [answer_turn("大写输出已经覆盖验收条件，不需要修改 PRD。")],
    }, stream_gap_sec=0.01)
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("build echo")
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.add_guidance(run_id, "product", "请确认大写输出覆盖了验收条件。")
    projection = system.run_until_stop(run_id)

    events = _events(system, run_id)
    [answered] = [event for event in events if event.type == EventType.ASK_ANSWERED]
    # 分支会话给出了回答，不是 unable：等待中的放行没有把询问挡在分支外面
    assert answered.payload["status"] == "answered"
    assert answered.payload["recipient"] == "quality"
    assert "大写输出" in answered.payload["answer"]
    product_end = max(event.position for event in events
                      if event.type == EventType.ACTIVATION_FINISHED and event.department == "product")
    [release] = _quality_events(system, run_id, EventType.PROPOSAL_SUBMITTED)
    assert release.position > product_end
    assert projection.department_guidance[0].status == "answered"
    assert projection.status == "done", projection.error
    assert projection.last_review.verdict == "release"


def test_input_arriving_while_quality_works_alone_starts_the_product(tmp_path):
    # 验收第 1 条（5）与反例 8 的最后一句：质检独自核验的时候输入到达，运行到停止的循环被唤醒、产品
    # 立刻开始一轮处理它；放行等这一轮结束以后裁决，不用等到运行时间用完
    holder: dict[str, object] = {}
    quality_round = quality_turns("release", "checks passed on the current delivery")[0]

    def release_after_the_input_arrives(request):
        # 质检独自工作：先交出流式片段，再让输入到达（这时产品没有被启动），然后提交放行
        yield ModelStreamEvent(kind="stream_event", id="evt-alone")
        holder["system"].add_guidance(request.run_id, "product", "请确认输出保持小写，产品要求不变。")
        holder["input_added"] = True
        return quality_round(request)

    adapter = FakeAdapter({
        "product": [product_spec(), FakeTurn(transcript="输出保持小写，产品要求不变。")],
        "engineering": [delivery_turn()],
        "quality": [release_after_the_input_arrives]
                   + quality_turns("release", "checks passed on the current delivery"),
    }, stream_gap_sec=0.01)
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("build echo", run_time_limit_sec=8)
    system.activate_once(run_id)
    system.activate_once(run_id)
    projection = system.run_until_stop(run_id)

    events = _events(system, run_id)
    assert holder.get("input_added")
    [guidance] = [event for event in events if event.type == EventType.DEPARTMENT_GUIDANCE_RECEIVED]
    product_finished = [event for event in events
                        if event.type == EventType.ACTIVATION_FINISHED and event.department == "product"]
    # 产品被启动了一轮专门处理这条输入，这一轮在指导到达以后结束
    assert len(product_finished) == 2
    product_end = max(event.position for event in product_finished)
    assert guidance.position < product_end
    # 放行在这一轮结束以后才生效，事项完成：没有等到运行时间用完
    [release] = _quality_events(system, run_id, EventType.PROPOSAL_SUBMITTED)
    assert release.position > product_end
    assert projection.stop_reason != "time_limit"
    assert projection.status == "done", projection.error
    assert projection.last_review.verdict == "release"


def test_a_release_is_rejected_after_the_product_makes_a_decision(tmp_path):
    # 验收第 1 条（3）与反例 8 的第一句：产品决定也重算合同，交付随之过期，放行被拒绝。
    # 放行仍然等产品这一轮结束才裁决：产品决定是这一轮交回的正式成果，没有以文字回答结束之前
    # 放行不生效（部门指导设计说明第 2.1 节）。拒绝以后怎么重新交付不在这条用例里，裁决出来
    # 就取消事项，不再进入下一轮
    holder: dict[str, object] = {}

    def decide_while_the_release_waits(request):
        yield from _wait_for_the_release_attempt(holder, request.run_id)
        return product_decision(
            "Uppercase all output",
            "输入要求输出大写，作为补充决定写进合同。",
        )

    adapter = FakeAdapter({
        "product": [product_spec(), decide_while_the_release_waits],
        "engineering": [delivery_turn(), delivery_turn()],
        "quality": [review_turn("release", "checks passed on the current delivery")]
                   + quality_turns("release", "checks passed on the current delivery"),
    }, stream_gap_sec=0.01)
    system = LoopSystem.for_testing(tmp_path, adapter)
    holder["system"] = system
    run_id = system.create_run("build echo", max_cycles=16)
    system.activate_once(run_id)
    system.activate_once(run_id)
    system.add_guidance(run_id, "product", "请把输出改为大写，作为补充决定写下来。")
    after_event(system, EventType.PROPOSAL_REJECTED,
                lambda event: from_another_thread(lambda: system.cancel(run_id)))
    projection = system.run_until_stop(run_id)

    events = _events(system, run_id)
    [decision] = [event for event in events if event.type == EventType.PRODUCT_DECISION_ACCEPTED]
    product_end = max(event.position for event in events
                      if event.type == EventType.ACTIVATION_FINISHED and event.department == "product")
    # 产品决定在这一轮里被接纳，这一轮随后结束
    assert decision.position < product_end
    [rejected] = _quality_events(system, run_id, EventType.PROPOSAL_REJECTED)
    # 放行等到这一轮结束才裁决；产品决定重算合同，交付随之不再有效，放行被拒绝
    assert rejected.position > product_end
    assert [error["field"] for error in rejected.payload["errors"]] == ["delivery_spec"]
    assert rejected.payload["errors"][0]["message"] == "no active DeliverySpec"
    assert projection.stop_reason == "cancelled"
    assert projection.last_review is None
