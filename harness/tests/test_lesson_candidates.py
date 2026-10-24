from dataclasses import asdict, replace

import pytest

from harness.adapters.base import ProviderError
from harness.app.application import Application
from harness.app.project_queries import EventDetail, ReplayCheck, RunExport
from harness.context import ContextAssembler
from harness.definitions import DEFINITIONS
from harness.models import DEPARTMENTS, ArtifactRef, DepartmentPrompt, EventType, json_dumps
from harness.projection import replay_events
from harness.proposals import (delivery_turn, product_spec, review, review_turn)
from harness.tests.helpers import explore_turn, happy_script, quality_turns, recorded_context, run_scripted

def rework_script():
    # 质检的结论只有缺陷记录与放行（工单 #555）：缺陷记录之后工程返工一轮，候选记的是这次结论
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）：
    # 质检在交付到达以前还有一轮预测性探索，脚本项给足几轮
    return {
        "product": [product_spec()],
        "engineering": [
            delivery_turn(),
            delivery_turn(summary="handle empty input"),
        ],
        "quality": quality_turns("rework_engineering", "QA reported missing empty-input handling", defects=[
            {"severity": "minor", "summary": "Empty input needs review"},
        ]),
    }

def assert_candidate_does_not_change_execution(system, projection):
    events = system.store.list_events(projection.run_id)
    without_candidates = replay_events([
        event for event in events if event.type != EventType.LESSON_CANDIDATE_RECORDED
    ]).to_dict()
    # 比较的是此刻的投影：同时运行以后，事项结束的时候别的会话的收尾事件可能还没有写下来，
    # 停止时读到的那份投影因此早于事件日志（工单 #557）
    actual = system.project(projection.run_id).to_dict()
    for field in ("lesson_candidates", "last_event_id", "stream_version"):
        actual.pop(field)
        without_candidates.pop(field)
    assert actual == without_candidates

def test_qa_candidate_preserves_actual_source_contract_and_evidence(tmp_path):
    script = rework_script()
    system, result = run_scripted(tmp_path, script)
    assert result.status == "done"
    assert len(result.lesson_candidates) == 1
    candidate = result.lesson_candidates[0]
    source = system.store.get_event(candidate.source_event_id)
    recorded = system.store.get_event(candidate.created_event_id)
    assert source.type == candidate.source_type == EventType.QA_SUBMITTED
    assert source.run_id == candidate.run_id == result.run_id
    assert source.stream_version < recorded.stream_version
    assert recorded.parent_event_id == source.event_id
    assert candidate.status == "unverified"
    assert candidate.observation == {key: source.payload[key] for key in ("verdict", "rationale", "defects")}
    assert candidate.product_spec_hash == result.product_specs[0].content_hash
    assert candidate.delivery_spec_hash == result.delivery_specs[0].content_hash
    assert candidate.checks == source.payload["checks"]
    assert candidate.checks
    assert candidate.evidence_refs
    for ref in candidate.evidence_refs:
        assert system.artifacts.get(ref)
    # #481 以后，质检的 run_check 写在质检会话的检查工作区里，run 结束即删除；
    # 质检回执的持久来源是 QA_SUBMITTED 事件的 payload，每条都在质检会话语境下绑定
    # （harness.validation._receipt_evidence：receipt 不带 department，事件本身就是质检提交）。
    # 仍然逐条核对候选的检查与质检真实回执相符，只是改从事件里取
    receipts = list(source.payload["checks"])
    assert receipts
    for check in candidate.checks:
        assert any(all(check[key] == receipt[key] for key in (
            "name", "snapshot_hash", "product_spec_hash", "delivery_spec_hash", "activation_id"
        )) for receipt in receipts)
    # 三个部门都工作过：产品提交要求、工程交付、质检起草测试用例并核验。
    # 质检在交付到达以前还有一轮预测性探索（工单 #557），因此这里不数模型调用的次数
    departments = [call.department for call in system.test_adapter.invocations]
    assert set(departments) == {"product", "engineering", "quality"}
    assert departments.count("product") == 1 and departments.count("engineering") == 2
    assert_candidate_does_not_change_execution(system, result)
    assert system.replay(result.run_id).canonical_state() == system.project(result.run_id).canonical_state()
    before = result.stream_version
    assert system.run_until_stop(result.run_id).stream_version == before
    assert system.activate_once(result.run_id).stream_version == before

def test_candidate_is_never_injected_into_department_context(tmp_path):
    rules = {department: DEFINITIONS.role(department).prompt for department in DEPARTMENTS}
    system, result = run_scripted(tmp_path, rework_script())
    candidate = result.lesson_candidates[0]
    for department in DEPARTMENTS:
        assembler = ContextAssembler()
        prompt = DepartmentPrompt(department, 0, DEFINITIONS.role(department).prompt,
                                  ArtifactRef(kind="department_prompt", content_hash="", path=""), "")
        args = {"department": department, "session_id": "test-session", "activation_id": "test-activation",
                "prompt": prompt}
        with_candidate = assembler.assemble(result, **args)
        without_candidate = assembler.assemble(replace(result, lesson_candidates=[]), **args)
        assert with_candidate == without_candidate
    for invocation in system.test_adapter.invocations:
        assert candidate.id not in json_dumps(invocation.input_items)
        assert candidate.suggestion not in json_dumps(invocation.input_items)
        injected = recorded_context(system, invocation).manifest.injected
        assert all("lesson" not in item.source for item in injected)
    assert {department: DEFINITIONS.role(department).prompt for department in DEPARTMENTS} == rules
    assert (system.test_adapter.name, system.test_adapter.model) == ("fake", "fake-script")

@pytest.mark.parametrize("with_delivery", [False, True])
def test_failure_candidate_has_only_existing_evidence_and_keeps_failure(tmp_path, with_delivery):
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）：
    # 产品的请求失败时没有成果，交付以后失败时失败候选引用这份交付作为已有的证据
    script = {
        "product": [product_spec()] if with_delivery else [ProviderError("controlled connection failure")],
        "engineering": ([delivery_turn()] if with_delivery else []) + [
            ProviderError("controlled connection failure")],
        # 质检只起草测试用例（预测性探索），这一轮没有交付可以核验，提交的结论被拒绝；
        # 交付到达以后质检开始新一轮，那时工程已经失败
        "quality": [explore_turn()],
    }
    system, result = run_scripted(tmp_path, script)
    assert result.status == "failed"
    assert result.stop_reason == "provider_error"
    assert len(result.lesson_candidates) == 1
    candidate = result.lesson_candidates[0]
    source = system.store.get_event(candidate.source_event_id)
    assert source.type == EventType.RUN_FAILED
    assert candidate.observation == {"stop_reason": source.stop_reason, "message": source.error}
    assert candidate.status == "unverified"
    if with_delivery:
        assert candidate.product_spec_hash == result.product_spec.content_hash
        assert candidate.delivery_spec_hash == result.delivery_spec.content_hash
        assert candidate.checks == result.delivery_spec.checks
        assert candidate.evidence_refs == [result.delivery_spec.tree_ref]
        assert all(system.artifacts.get(ref) for ref in candidate.evidence_refs)
    else:
        assert candidate.product_spec_hash is None
        assert candidate.delivery_spec_hash is None
        assert candidate.checks == candidate.evidence_refs == []
    # 模型的调用：没有交付时只有产品那一次（请求失败，事项因此失败）；
    # 有交付时产品提交要求、工程交付
    assert [call.department for call in system.test_adapter.invocations].count("product") == 1
    assert_candidate_does_not_change_execution(system, result)
    assert system.replay(result.run_id).canonical_state() == system.project(result.run_id).canonical_state()

def test_success_cancel_pause_and_rejected_review_do_not_invent_candidates(tmp_path):
    _system, success = run_scripted(tmp_path / "success", happy_script())
    assert success.status == "done" and success.lesson_candidates == []
    system, paused = run_scripted(tmp_path / "pause", [product_spec()], max_cycles=1)
    assert paused.status == "paused" and paused.lesson_candidates == []
    run_id = system.create_run("cancelled by developer")
    cancelled = system.cancel(run_id)
    assert cancelled.stop_reason == "cancelled" and cancelled.lesson_candidates == []
    invalid = review("rework_engineering", "unverified rejected opinion", defects=[{"severity": "minor", "summary": "claim"}])
    invalid["defects"] = None
    # #470 删除工程计划以后，工程激活不再先提交计划：轮次上限回到 3，
    # 质检的整次提交被拒绝以后没有下一段脚本，运行按上限暂停，不因为脚本耗尽失败
    # 脚本按部门给出（工单 #877）：PRD 被接纳以后工程与质检同时工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化
    _system, rejected = run_scripted(
        tmp_path / "rejected",
        {
            "product": [product_spec()],
            "engineering": [delivery_turn()],
            "quality": [invalid],
        },
        max_cycles=3,
    )
    assert rejected.status == "paused" and rejected.rejections
    assert rejected.lesson_candidates == []

def test_release_with_defect_keeps_existing_rejection_and_does_not_create_candidate(tmp_path):
    # 脚本按部门给出（工单 #877）：质检的脚本按它自己的先后排列
    system, result = run_scripted(tmp_path, {
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [
            review_turn("release", "nonblocking observation", defects=[{"severity": "minor", "summary": "naming could improve"}]),
            review_turn("release", "no defects remain"),
        ],
    })
    assert result.status == "done"
    assert result.lesson_candidates == []
    assert result.rejections[0]["errors"] == [{"field": "defects", "message": "release requires an empty defect list"}]
    # #470 删除工程计划以后，工程激活只提交一次计划，模型调用少一次：产品、交付、两次质检
    assert len(system.test_adapter.invocations) == 4
    assert_candidate_does_not_change_execution(system, result)

def test_evidence_source_export_and_replay_keep_the_same_candidate(tmp_path):
    system, result = run_scripted(tmp_path, rework_script())
    candidate = result.lesson_candidates[0]
    application = Application(system)
    before = result.stream_version

    exported = application.query("run.export", RunExport(run_id=result.run_id))
    assert exported.data.projection["lesson_candidates"] == result.to_dict()["lesson_candidates"]
    detail = application.query("event.detail", EventDetail(event_id=candidate.created_event_id))
    source = application.query("event.detail", EventDetail(event_id=candidate.source_event_id))
    assert detail.data.event["payload"]["source_event_id"] == source.data.event["event_id"]
    assert source.data.event["payload"]["rationale"] == candidate.observation["rationale"]
    assert (detail.data.event["payload"]["source_event_id"]
            in [item["event_id"] for item in exported.data.events])
    assert source.data.event["event_id"] in [item["event_id"] for item in exported.data.events]
    assert source.data.artifacts["git_version"]["commit"] == source.data.event["payload"]["git_version"]["commit"]
    assert json_dumps(exported.data.projection["lesson_candidates"]) == json_dumps(
        system.replay(result.run_id).lesson_candidates)
    checked = application.query("replay.check", ReplayCheck(run_id=result.run_id))
    assert checked.data.consistent is True
    assert system.project(result.run_id).stream_version == before
