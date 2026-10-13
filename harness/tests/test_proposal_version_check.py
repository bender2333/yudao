from dataclasses import replace

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.event_store import StreamVersionConflict, run_stream
from harness.models import EventType
from harness.proposals import (collaboration_request, delivery, delivery_turn, product_spec,
                                product_spec_turn, response_turn, review, review_turn)
from harness.runtime import LoopSystem
from harness.tests.helpers import from_another_thread
from harness.validation import evaluate_proposal

# 提案校验与提交：流程编排校验提案时记下读取的流版本，提交以它作为期望版本追加；校验以后另一方写入了这个 run，
# 写入口拒绝提交，流程编排按写入以后的状态重新校验与判断。测试包装公开的 WritePath.transact：记下每次判断使用的
# 流版本、写入口的拒绝，并在校验以后、提交读取之前从另一个线程完成一次用户操作。


def _write_after_validation(monkeypatch, system, operation):
    transact = system.writes.transact
    versions, done, conflicts = [], [], []

    def transact_after_validation(stream, decide, **options):
        if options.get("expected_version") is not None:
            versions.append(options["expected_version"])
            if len(versions) == 1:
                done.append(from_another_thread(operation))
        try:
            return transact(stream, decide, **options)
        except StreamVersionConflict as exc:
            conflicts.append(exc)
            raise

    monkeypatch.setattr(system.writes, "transact", transact_after_validation)
    return versions, done, conflicts


def _system(tmp_path, *script):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter(list(script)))
    return system, system.create_run("build an echo CLI")


def _events(system, run_id, event_type):
    return [event for event in system.store.list_events(run_id) if event.type == event_type]


def test_input_after_validation_rejects_the_commit_and_the_proposal_is_judged_again(tmp_path, monkeypatch):
    system, run_id = _system(tmp_path, product_spec(), product_spec(requirements=["Print uppercase output"]))
    versions, done, conflicts = _write_after_validation(
        monkeypatch, system, lambda: system.add_input(run_id, "Print uppercase output"))

    result = system.activate_once(run_id)

    [writer] = done
    assert not writer.errors
    # 写入口拒绝以校验时的版本作为期望版本的提交，说明流的实际版本
    [conflict] = conflicts
    assert (conflict.stream, conflict.expected, conflict.actual) == (run_stream(run_id), versions[0], versions[0] + 1)
    # 按写入以后的状态重新校验：激活开始以后输入改变，提案按 execution_basis 拒绝，与没有流版本核对时的结果相同
    assert versions == [versions[0], versions[0] + 1]
    [rejected] = _events(system, run_id, EventType.PROPOSAL_REJECTED)
    assert [error["field"] for error in rejected.payload["errors"]] == ["execution_basis"]
    assert not _events(system, run_id, EventType.SPEC_ACCEPTED)
    assert result.phase == "PRODUCT_SPEC" and result.input_version == 2
    accepted = system.activate_once(run_id)
    assert accepted.product_spec.input_version == 2
    assert accepted.canonical_state() == system.replay(run_id).canonical_state()


def test_a_cancel_after_validation_leaves_no_proposal_record(tmp_path, monkeypatch):
    system, run_id = _system(tmp_path, product_spec())
    versions, done, conflicts = _write_after_validation(monkeypatch, system, lambda: system.cancel(run_id))

    result = system.activate_once(run_id)

    [writer] = done
    assert not writer.errors
    assert len(conflicts) == 1 and len(versions) == 2
    assert result.phase == "FAILED" and result.stop_reason == "cancelled"
    assert not _events(system, run_id, EventType.PROPOSAL_SUBMITTED)


# 正式成果声明依据的版本（工单 #471）：ProductSpec、DeliverySpec、QAReview 都要写明它依据的当前版本，
# 声明缺失、类型不对或与 host 端当前版本不一致时整次提交被拒绝，错误指向声明的字段并给出当前版本。


def _revision(change_record, basis):
    # 修订版 ProductSpec 的提案：把变更记录写清，依据版本由参数给定
    return product_spec(requirements=["Print the argument and reject unknown flags"], change_record=change_record,
                        basis_product_spec_hash=basis)


CHANGE_RECORD = {
    "changed": ["Make unknown flag behavior explicit"], "retained": ["Echo valid input"],
    "retired": [], "rationale": "Clarify argument validation",
}


def _activate_until(system, run_id, revision):
    # 跑到产品规格出现指定的修订版为止，不做完整循环：后面的提交要检验的是过期依据
    projection = system.project(run_id)
    while projection.product_spec is None or projection.product_spec.revision < revision:
        projection = system.activate_once(run_id)
        assert projection.phase not in ("DONE", "FAILED"), projection.stop_reason
    return projection


def test_a_spec_that_declares_the_wrong_basis_is_rejected_with_the_current_version(tmp_path):
    # 修订版 ProductSpec 声明了别的 hash：整次提交被拒绝，错误给出 host 端的当前版本，模型重读后可以重交
    system, run_id = _system(tmp_path, product_spec())
    first = system.activate_once(run_id)
    assert first.product_spec is not None
    projection = system.project(run_id)
    decision = evaluate_proposal(phase="REWORK_PRODUCT", department="product",
                                 projection=replace(projection, phase="REWORK_PRODUCT"),
                                 facts=system.workspace(run_id).snapshot().facts,
                                 proposal=_revision(CHANGE_RECORD, "sha256:" + "0" * 64))
    assert not decision.accepted
    [error] = decision.error_dicts
    assert error["field"] == "basis_product_spec_hash"
    assert first.product_spec.content_hash in error["message"]


def test_a_first_spec_must_declare_a_null_basis(tmp_path):
    # 还没有当前 ProductSpec：第一份规格必须声明 null 依据，给了 hash 就拒绝
    system, run_id = _system(tmp_path, product_spec())
    projection = system.project(run_id)
    decision = evaluate_proposal(phase="PRODUCT_SPEC", department="product",
                                 projection=replace(projection, phase="PRODUCT_SPEC"),
                                 facts=system.workspace(run_id).snapshot().facts,
                                 proposal=_revision(CHANGE_RECORD, "sha256:" + "1" * 64))
    assert not decision.accepted
    [error] = decision.error_dicts
    assert error["field"] == "basis_product_spec_hash"
    assert "null" in error["message"]


def test_a_missing_basis_declaration_rejects_the_submission(tmp_path):
    system, run_id = _system(tmp_path, product_spec())
    projection = system.project(run_id)
    proposal = _revision(CHANGE_RECORD, None)
    without_field = {key: value for key, value in proposal.items() if key != "basis_product_spec_hash"}
    decision = evaluate_proposal(phase="PRODUCT_SPEC", department="product",
                                 projection=replace(projection, phase="PRODUCT_SPEC"),
                                 facts=system.workspace(run_id).snapshot().facts, proposal=without_field)
    assert not decision.accepted
    [error] = decision.error_dicts
    assert error["field"] == "basis_product_spec_hash"
    assert "required" in error["message"]


def test_a_spec_may_declare_the_current_basis(tmp_path):
    # 与当前版本一致的声明通过校验，修订版可以提交
    system, run_id = _system(tmp_path, product_spec())
    first = system.activate_once(run_id)
    projection = system.project(run_id)
    decision = evaluate_proposal(phase="REWORK_PRODUCT", department="product",
                                 projection=replace(projection, phase="REWORK_PRODUCT"),
                                 facts=system.workspace(run_id).snapshot().facts,
                                 proposal=_revision(CHANGE_RECORD, first.product_spec.content_hash))
    assert decision.accepted, decision.errors
    assert decision.artifact["revision"] == 2


def test_a_delivery_bound_to_a_stale_spec_is_rejected(tmp_path):
    # 工程拿着已过期的 ProductSpec 提交交付：整次提交被拒绝，错误指向依据字段并给出当前版本
    system, run_id = _system(tmp_path, product_spec(), delivery_turn(),
                              review_turn("rework_product", "the contract missed empty input",
                                          defects=[{"severity": "major", "summary": "empty input not covered"}]),
                              product_spec_turn(acceptance=["empty input prints a blank line"],
                                                change_record=CHANGE_RECORD))
    revised = _activate_until(system, run_id, 2)
    assert revised.phase == "ENGINEERING"
    assert revised.product_specs[0].content_hash != revised.product_spec.content_hash
    stale_delivery = FakeTurn(proposal=delivery(
        summary="implemented echo CLI", check_names=["smoke"],
        basis_product_spec_hash=revised.product_specs[0].content_hash), checks={"smoke": 0})
    system.test_adapter.script = [stale_delivery]
    accepted_before = len(_events(system, run_id, EventType.DELIVERY_ACCEPTED))
    result = system.activate_once(run_id)
    [error] = [item for rejection in result.rejections for item in rejection["errors"]]
    assert error["field"] == "basis_product_spec_hash"
    assert revised.product_spec.content_hash in error["message"]
    assert len(_events(system, run_id, EventType.DELIVERY_ACCEPTED)) == accepted_before


def test_a_review_bound_to_a_stale_delivery_is_rejected(tmp_path):
    # 质检拿着已被返工取代的 DeliverySpec 提交复核：整次提交被拒绝
    system, run_id = _system(tmp_path, product_spec(), delivery_turn(), review_turn(
        "rework_engineering", "naming does not match the requirements",
        defects=[{"severity": "minor", "summary": "naming"}]),
        delivery_turn(summary="revised implementation"))
    # 跑到质检阶段且已有两个交付版本：第一个已被返工取代，不是当前版本
    projection = system.project(run_id)
    while projection.phase != "QUALITY" or len(projection.delivery_specs) < 2:
        projection = system.activate_once(run_id)
        assert projection.phase not in ("DONE", "FAILED"), projection.stop_reason
    stale_review = FakeTurn(proposal=review(
        "release", "the superseded delivery passed", checks=["smoke"],
        basis_delivery_spec_hash=projection.delivery_specs[0].content_hash), checks={"smoke": 0})
    system.test_adapter.script = [stale_review]
    submitted_before = len(_events(system, run_id, EventType.QA_SUBMITTED))
    rejected = system.activate_once(run_id)
    [error] = [item for rejection in rejected.rejections for item in rejection["errors"]]
    assert error["field"] == "basis_delivery_spec_hash"
    assert projection.delivery_spec.content_hash in error["message"]
    assert len(_events(system, run_id, EventType.QA_SUBMITTED)) == submitted_before


def test_a_review_of_a_delivery_bound_to_a_superseded_spec_is_rejected(tmp_path):
    # 放行前的最后一道关：交付本身依据的是已被取代的产品规格，依据字段写对了也不放行
    system, run_id = _system(tmp_path, product_spec(), delivery_turn())
    while system.project(run_id).phase != "QUALITY":
        projection = system.activate_once(run_id)
        assert projection.phase not in ("DONE", "FAILED"), projection.stop_reason
    projection = system.project(run_id)
    superseded = replace(projection.delivery_spec, product_spec_hash="sha256:" + "0" * 64)
    decision = evaluate_proposal(phase="QUALITY", department="quality",
                                 projection=replace(projection, delivery_spec=superseded),
                                 facts=system.workspace(run_id).snapshot().facts,
                                 proposal=review("release", "releasing a stale-bound delivery",
                                                 checks=["smoke"],
                                                 basis_delivery_spec_hash=projection.delivery_spec.content_hash))
    assert not decision.accepted
    assert "product_spec_hash" in [error["field"] for error in decision.error_dicts]
