import json
from dataclasses import replace

from harness.adapters.fake import FakeAdapter, FakeTurn, prompt_part
from harness.event_store import StreamVersionConflict, run_stream
from harness.models import EventType, json_dumps
from harness.proposals import (answer_turn, ask_turn, delivery, delivery_turn, guidance_response,
                                product_spec, product_spec_turn, review, review_turn)
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


def _system_asking_product(tmp_path):
    # 质检要求有问题时询问产品，产品在回答里修订 PRD（工单 #555）：结论只有缺陷记录与放行，
    # 要求有问题时不再把工作退回产品。脚本按会话给：产品的询问分支回答并修订 PRD。
    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [
            ask_turn(recipient="product", question="验收标准漏了空输入，请修订 PRD。"),
            review_turn("rework_engineering", "the contract missed empty input",
                        defects=[{"severity": "major", "summary": "empty input not covered"}]),
        ],
        "product:ask": [answer_turn(
            answer="已补上空输入的验收标准。",
            requirements=["print the given argument to stdout"],
            acceptance=["empty input prints a blank line"],
            change_record=CHANGE_RECORD)],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    return system, system.create_run("build an echo CLI")


def _system_with_guided_revision(tmp_path):
    # 产品修订 PRD：质检的结论不再把工作退回产品（工单 #555），产品的修订由用户的指导触发，
    # 修订以后事项仍在工程阶段，工程按新合同继续工作。
    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [],
    })
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build an echo CLI")
    system.activate_once(run_id)
    system.add_guidance(run_id, "product", "请把验收标准写清空输入的行为。")
    adapter.scripts["product"] = [
        product_spec_turn(acceptance=["empty input prints a blank line"], change_record=CHANGE_RECORD),
        lambda request: FakeTurn(proposal=guidance_response(
            _guidance_id(request), status="explained", text="已按新的验收标准修订产品要求。")),
    ]
    return system, run_id


def _guidance_id(request):
    return json.loads(prompt_part(request, "department_guidance"))[0]["id"]


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
    system, run_id = _system_with_guided_revision(tmp_path)
    revised = _activate_until(system, run_id, 2)
    assert revised.phase == "ENGINEERING"
    assert revised.product_specs[0].content_hash != revised.product_spec.content_hash
    stale_delivery = FakeTurn(proposal=delivery(
        summary="implemented echo CLI", check_names=["smoke"],
        basis_product_spec_hash=revised.product_specs[0].content_hash), checks={"smoke": 0})
    system.activate_once(run_id)  # 产品回应指导，指导不再是待处理
    system.test_adapter.scripts = {"engineering": [stale_delivery]}
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


def _basis_errors(projection):
    return [item for rejection in projection.rejections for item in rejection["errors"]]


def test_a_first_spec_that_declares_a_hash_is_rejected_by_the_host(tmp_path):
    # 第一份规格声明了不存在的依据：activate_once 的提交判断拒绝，错误要求 null
    system, run_id = _system(tmp_path, product_spec(basis_product_spec_hash="sha256:" + "1" * 64))
    rejected = system.activate_once(run_id)
    [error] = _basis_errors(rejected)
    assert error["field"] == "basis_product_spec_hash" and "null" in error["message"]
    assert not _events(system, run_id, EventType.SPEC_ACCEPTED)
    assert rejected.product_spec is None


def test_a_spec_that_omits_the_basis_is_rejected_by_the_host(tmp_path):
    # 依据字段整个缺失：提交判断拒绝，错误指明字段必需
    proposal = product_spec()
    del proposal["basis_product_spec_hash"]
    system, run_id = _system(tmp_path, proposal)
    rejected = system.activate_once(run_id)
    [error] = _basis_errors(rejected)
    assert error["field"] == "basis_product_spec_hash" and "required" in error["message"]
    assert not _events(system, run_id, EventType.SPEC_ACCEPTED)


def test_a_revision_with_a_stale_basis_is_rejected_by_the_host_and_can_be_resubmitted(tmp_path):
    # 产品拿着过期版本提交修订：activate_once 整次拒绝，错误给出当前版本；
    # 拒绝的原因与当前版本作为 validation_feedback 交回，产品读过反馈以后按当前版本重交，修订被接纳
    system, run_id = _system_with_guided_revision(tmp_path)
    projection = _activate_until(system, run_id, 2)
    assert projection.phase == "ENGINEERING"
    current_hash = projection.product_spec.content_hash
    # 修订提交必须来自产品会话：用指导把产品请回工作，脚本按会话给
    system.add_guidance(run_id, "product", "请再确认一次验收边界。")
    system.test_adapter.scripts = {"product": [FakeTurn(proposal=_revision(CHANGE_RECORD, "sha256:" + "0" * 64))]}
    rejected = system.activate_once(run_id)
    [error] = _basis_errors(rejected)
    assert error["field"] == "basis_product_spec_hash" and current_hash in error["message"]
    assert [item["field"] for item in _basis_errors(rejected)] == ["basis_product_spec_hash"]
    assert rejected.pending_feedback["product"]["errors"][0]["field"] == "basis_product_spec_hash"

    def resubmit(call):
        feedback = json.loads(prompt_part(call, "validation_feedback") or "{}")
        assert current_hash in json_dumps(feedback)
        assert current_hash in prompt_part(call, "current_product_spec")
        return _revision(CHANGE_RECORD, current_hash)
    system.test_adapter.scripts = {"product": [resubmit]}
    accepted = system.activate_once(run_id)
    assert accepted.product_spec.revision == 3
    assert accepted.product_spec.parent_hash == current_hash
    assert accepted.product_spec.status == "active"
    [event] = _events(system, run_id, EventType.SPEC_ACCEPTED)[-1:]
    assert event.payload["revision"] == 3 and event.payload["parent_hash"] == current_hash
    assert accepted.pending_feedback == {}


def test_a_delivery_with_a_stale_basis_is_rejected_then_resubmitted_with_the_current_version(tmp_path):
    # 交付链闭环：工程拿着过期规格提交被拒，拒绝的原因与当前版本作为工具结果交回，
    # 读过反馈以后按当前版本重交，交付被接纳并进入质检
    system, run_id = _system_with_guided_revision(tmp_path)
    projection = _activate_until(system, run_id, 2)
    assert projection.phase == "ENGINEERING"
    current_hash = projection.product_spec.content_hash
    files = {"src/echo.py": "import sys\nprint(sys.argv[1])\n"}
    stale = FakeTurn(proposal=delivery(
        summary="implemented echo CLI", check_names=["smoke"],
        basis_product_spec_hash=projection.product_specs[0].content_hash),
        writes=files, checks={"smoke": 0})
    accepted_before = len(_events(system, run_id, EventType.DELIVERY_ACCEPTED))
    system.activate_once(run_id)  # 产品回应指导，指导不再是待处理
    system.test_adapter.scripts = {"engineering": [stale]}
    rejected = system.activate_once(run_id)
    [error] = _basis_errors(rejected)
    assert error["field"] == "basis_product_spec_hash" and current_hash in error["message"]
    assert rejected.pending_feedback["engineering"]["errors"][0]["field"] == "basis_product_spec_hash"
    assert len(_events(system, run_id, EventType.DELIVERY_ACCEPTED)) == accepted_before

    def resubmit(call):
        feedback = json.loads(prompt_part(call, "validation_feedback") or "{}")
        assert current_hash in json_dumps(feedback)
        assert current_hash in prompt_part(call, "current_product_spec")
        return FakeTurn(proposal=delivery(
            summary="implemented echo CLI", check_names=["smoke"], basis_product_spec_hash=current_hash),
            writes=files, checks={"smoke": 0})

    system.test_adapter.scripts = {"engineering": [resubmit]}
    accepted = system.activate_once(run_id)
    assert len(_events(system, run_id, EventType.DELIVERY_ACCEPTED)) == accepted_before + 1
    assert accepted.delivery_spec is not None
    assert accepted.delivery_spec.product_spec_hash == current_hash
    [event] = _events(system, run_id, EventType.DELIVERY_ACCEPTED)[-1:]
    assert event.payload["product_spec_hash"] == current_hash
    assert accepted.phase == "QUALITY"
    assert accepted.pending_feedback == {}


def test_a_review_with_a_stale_basis_is_rejected_then_resubmitted_with_the_current_version(tmp_path):
    # 质检提交过期的交付依据被拒，读过反馈以后按当前版本重交，放行进入 DONE
    system, run_id = _system(tmp_path, product_spec(), delivery_turn(),
                              review_turn("rework_engineering", "naming does not match the requirements",
                                          defects=[{"severity": "minor", "summary": "naming"}]),
                              delivery_turn(summary="revised implementation"))
    projection = system.project(run_id)
    while projection.phase != "QUALITY" or len(projection.delivery_specs) < 2:
        projection = system.activate_once(run_id)
        assert projection.phase not in ("DONE", "FAILED"), projection.stop_reason
    current_hash = projection.delivery_spec.content_hash
    stale = FakeTurn(proposal=review(
        "release", "the superseded delivery passed", checks=["smoke"],
        basis_delivery_spec_hash=projection.delivery_specs[0].content_hash), checks={"smoke": 0})
    submitted_before = len(_events(system, run_id, EventType.QA_SUBMITTED))
    system.test_adapter.script = [stale]
    rejected = system.activate_once(run_id)
    [error] = _basis_errors(rejected)
    assert error["field"] == "basis_delivery_spec_hash" and current_hash in error["message"]
    assert rejected.pending_feedback["quality"]["errors"][0]["field"] == "basis_delivery_spec_hash"
    assert len(_events(system, run_id, EventType.QA_SUBMITTED)) == submitted_before

    def resubmit(call):
        feedback = json.loads(prompt_part(call, "validation_feedback") or "{}")
        assert current_hash in json_dumps(feedback)
        assert current_hash in prompt_part(call, "current_delivery_spec")
        return FakeTurn(proposal=review(
            "release", "the current delivery passed", checks=["smoke"],
            basis_delivery_spec_hash=current_hash), checks={"smoke": 0})

    system.test_adapter.script = [resubmit]
    accepted = system.activate_once(run_id)
    assert len(_events(system, run_id, EventType.QA_SUBMITTED)) == submitted_before + 1
    assert accepted.phase == "DONE"
    assert accepted.delivery_spec.content_hash == current_hash
    [event] = _events(system, run_id, EventType.QA_SUBMITTED)[-1:]
    assert event.payload["delivery_spec_hash"] == current_hash
    assert accepted.pending_feedback == {}
