# 内核不变式第五条（harness/definitions/kernel-manifest.json 的 rules[4]，工单 #358）：
# 验证者提交独立判断之前看不到作者的解释。
#
# 不变式的形状（验证的独立性设计说明第 4 节）：对每份交付，上下文清单里含有工程内容解释部分的
# 验证者请求，位置都晚于这份交付的独立判断事件；工程内容包括交付说明、直接的问答与历史中的问答记录
# 三条通道。反例覆盖预测性探索（还没有交付）到正式核验的同一条历史。
#
# 两层核对：
# ①纯函数层（harness/context.py 的 quality_engineering_content）：解释部分的可见性由
#   independent_judgement_committed（或 qa_submitted，#554 的既有口径）按交付摘要决定——
#   事件在交付的判断之前时解释不进入请求材料；
# ②真实循环层（本文件的第二个用例）：交付到达以后质检先交独立判断（门：没有判断的结论被拒绝），
#   判断提交以后的核验请求里才出现解释部分（summary/known_risks 属于交付说明的解释部分）。
#
# 用真实存储与真实事件日志（LoopSystem.for_testing），不开子进程、不连网络，属于模块层。
# 守第 13 节的 R1（事实只经写入口写入：独立判断经提案路径与门写入）与 R3（先判断后看解释）。

import json

from harness.adapters.fake import FakeAdapter, prompt_part
from harness.models import EventType
from harness.proposals import delivery_turn, judgement_turn, product_spec, review_turn
from harness.runtime import LoopSystem

MARKER_SUMMARY = "SECRET_EXPLANATION_SUMMARY"
MARKER_RISK = "SECRET_EXPLANATION_RISK"


def _delivery_with_explanation() -> object:
    from harness.proposals import delivery

    return delivery(summary=MARKER_SUMMARY, known_risks=[MARKER_RISK])


def test_the_explanation_stays_hidden_until_the_independent_judgement_is_committed(tmp_path):
    # ①纯函数层：没有独立判断事件时，装配给质检的交付说明只带事实部分；
    # 判断事件写进日志以后（按交付摘要对应），解释部分才可并进它之后的请求
    from harness.context import quality_engineering_content
    from harness.kernel_events import Event
    from harness.models import ArtifactRef, DeliverySpec, EventType

    run_id = "run_judge"
    delivery = DeliverySpec(
        id="del_1", run_id=run_id, revision=1, parent_hash=None,
        content_hash="sha256:" + "1" * 64, issuer="engineering", status="active",
        created_event_id="evt_delivery", product_spec_hash="sha256:" + "2" * 64,
        effective_contract_hash="sha256:" + "3" * 64, summary=MARKER_SUMMARY,
        files=["src/echo.py"], check_names=["smoke"], checks=[], known_risks=[MARKER_RISK],
        code_tree_digest="sha256:" + "4" * 64,
        tree_ref=ArtifactRef(kind="tree", content_hash="sha256:" + "1" * 64, path="tree"),
    )
    delivery_accepted = Event(
        event_id="evt_delivery", run_id=run_id, type=EventType.DELIVERY_ACCEPTED, role=None,
        parent_event_id=None, state_before="running", state_after="running",
        payload={"content_hash": delivery.content_hash}, artifact_hashes=[], session_id=None,
        provider=None, model=None, context_digest=None, stop_reason=None, error=None,
        created_at="2026-10-31T00:00:00Z", position=1, stream=f"run:{run_id}", stream_version=1,
        project_id=None, work_item_id=None, department="engineering")
    before = quality_engineering_content([delivery_accepted], delivery=delivery)
    assert before["explanation_visible"] is False
    assert "summary" not in before["delivery"] and "known_risks" not in before["delivery"]

    # 独立判断事件按交付摘要写进日志：解释部分对这份交付可见；对另一份交付仍然不可见
    judgement = Event(
        event_id="evt_judgement", run_id=run_id, type=EventType.INDEPENDENT_JUDGEMENT_COMMITTED, role=None,
        parent_event_id=None, state_before="running", state_after="running",
        payload={"kind": "independent_judgement", "product_spec_hash": delivery.product_spec_hash,
                 "delivery_spec_hash": delivery.content_hash, "checks": ["smoke"],
                 "criteria_count": 1, "criteria": []},
        artifact_hashes=[], session_id="ses_quality", provider=None, model=None,
        context_digest=None, stop_reason=None, error=None, created_at="2026-10-31T00:00:01Z",
        position=2, stream=f"run:{run_id}", stream_version=2, project_id=None,
        work_item_id=None, department="quality")
    after = quality_engineering_content([delivery_accepted, judgement], delivery=delivery)
    assert after["explanation_visible"] is True
    assert after["delivery"]["summary"] == MARKER_SUMMARY

    other = DeliverySpec(**{**delivery.__dict__, "content_hash": "sha256:" + "9" * 64})
    unchanged = quality_engineering_content([delivery_accepted, judgement], delivery=other)
    assert unchanged["explanation_visible"] is False


def test_the_verifier_judges_before_it_sees_the_explanation(tmp_path):
    # ②真实循环层：交付到达以后，质检先交独立判断；判断提交以前的请求里没有解释部分，
    # 判断提交以后的核验请求里才有（门：没有独立判断的结论被拒绝，字段级错误写明缺什么）
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(_script()))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)   # 产品提交 PRD
    system.activate_once(run_id)   # 工程交付（交付说明里带解释）
    system.activate_once(run_id)   # 质检交独立判断
    system.activate_once(run_id)   # 质检核验并放行
    projection = system.project(run_id)
    assert projection.status == "done", projection.stop_reason

    events = system.store.list_events(run_id)
    judgements = [event for event in events if event.type == EventType.INDEPENDENT_JUDGEMENT_COMMITTED]
    deliveries = [event for event in events if event.type == EventType.DELIVERY_ACCEPTED]
    assert len(judgements) == 1 and len(deliveries) == 1
    [delivery] = deliveries
    assert judgements[0].payload["delivery_spec_hash"] == delivery.payload["content_hash"]

    # 门：质检的请求按内容分界——判断提交以前装配的请求没有解释部分，以后的才有
    calls = [request for request in system.test_adapter.invocations if request.department == "quality"]
    assert len(calls) == 2
    before = _text(calls[0])
    after = _text(calls[1])
    assert MARKER_SUMMARY not in before and MARKER_RISK not in before, "判断提交以前的请求里出现了解释部分"
    assert MARKER_SUMMARY in after and MARKER_RISK in after

    # 解释部分只经门进入：事件日志里判断以前的请求材料不带它（防回退护栏）
    contexts = [event for event in events if event.type == EventType.CONTEXT_ASSEMBLED
                and event.department == "quality"]
    assert len(contexts) == 2


def _script():
    return {
        "product": [product_spec()],
        "engineering": [delivery_turn(summary=MARKER_SUMMARY, known_risks=[MARKER_RISK])],
        "quality": [judgement_turn(), review_turn("release", "the judgement stands")],
    }


def _text(call) -> str:
    parts: list[str] = []
    for item in call.input_items:
        if isinstance(item.get("content"), str):
            parts.append(item["content"])
        elif isinstance(item.get("output"), str):
            parts.append(item["output"])
    return "\n".join(parts)
