from dataclasses import replace

from harness.actions import FactsQuery
from harness.adapters.fake import FakeAdapter
from harness.adjudication import WorkBasis, commit_decision, facts_query, proposal_decision, tool_permission
from harness.collaboration import has_new_work
from harness.environment import LocalEnvironment
from harness.models import SessionRecord
from harness.proposals import delivery, product_spec
from harness.runtime import LoopSystem


def _engineering(tmp_path):
    # 产品要求已接纳，工程部门正在工作：直接依据有效合同写文件
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec()]))
    run_id = system.create_run("echo")
    projection = system.activate_once(run_id)
    # 产品要求已接纳：工程按关注的成果开始一轮工作（工单 #556）
    assert has_new_work(projection, "engineering") and projection.effective_contract is not None
    # 部门按关注的成果开始一轮工作（工单 #556）：工程这一轮在工作，
    # 会话的记录是「工作中」
    projection = replace(projection, sessions={**projection.sessions, "engineering": SessionRecord(
        session_id="ses_eng", department="engineering", status="active")})
    return system, projection

def _environment(system, projection):
    return LocalEnvironment(system.workspace(projection.run_id))

def _permission(system, projection, name, args, *, basis=None, aborted=False):
    # 工具许可依据的工作区事实由执行环境按 U 给出的查询取得
    call = {"id": "call", "name": name, "args": args}
    return tool_permission(
        projection, call, department="engineering",
        basis=basis or WorkBasis.current(projection, "engineering"),
        aborted=aborted, facts=_environment(system, projection).query(facts_query(call)),
    )

def test_tool_permission_stops_after_cancel_end_and_defers_a_proposal_before_the_new_input(tmp_path):
    # 工单 #558：有效合同与指导变了不再停止这次激活（它们作为通知送达，部门接着工作）；
    # 工单 #964：用户输入变了也不再停止这一轮，它作为通知在这个会话的下一步送达；
    # 模型还没有看见新输入时，正式成果这次先不做（推迟到下一步），其它工具照常执行
    system, projection = _engineering(tmp_path)
    write = ("write_file", {"path": "src/echo.py", "content": "print(1)\n"})
    assert _permission(system, projection, *write).allowed
    assert _permission(system, projection, *write, aborted=True).stopped
    assert _permission(system, replace(projection, status="failed"), *write).stopped
    newer_input = replace(WorkBasis.current(projection, "engineering"), input_version=projection.input_version - 1)
    assert _permission(system, projection, *write, basis=newer_input).allowed
    other_contract = replace(WorkBasis.current(projection, "engineering"), effective_contract_hash="sha256:other")
    assert _permission(system, projection, *write, basis=other_contract).allowed
    other_guidance = replace(WorkBasis.current(projection, "engineering"), guidance_version=99)
    assert _permission(system, projection, *write, basis=other_guidance).allowed
    # 正式成果等模型看见新输入以后再提交
    deferred = _permission(system, projection, "submit_delivery", {}, basis=newer_input)
    assert deferred.reason and deferred.deferred and not deferred.allowed
    assert "has not entered this session's model input yet" in deferred.reason


def test_commit_decision_rejects_results_whose_workspace_changed(tmp_path):
    # 工单 #558：依据变了不再让这次提交作废（PRD 的新版本与指导作为通知送达，部门接着工作）；
    # 工单 #964：新的用户输入同样不再作废这次提交（它作为通知送达，部门接着工作）；
    # 校验以后工作区改变仍然拒绝：回执不能重新绑定到已经改变的快照上
    system, projection = _engineering(tmp_path)
    environment = _environment(system, projection)
    ws = system.workspace(projection.run_id)
    ws.bind_check(
        activation_id=projection.last_activations.get("engineering"),
        product_spec_hash=projection.product_spec.content_hash,
        delivery_spec_hash=None,
        effective_contract_hash=projection.effective_contract.content_hash,
    )
    ws.write_file("src/echo.py", "print(1)\n")
    ws.record_check("engineering", "pytest", 0, "ok")
    proposal = delivery(check_names=["pytest"],
                        basis_product_spec_hash=projection.product_spec.content_hash)
    facts = environment.query(FactsQuery(tree=True)).tree
    events = system.store.list_events(projection.run_id)
    first = proposal_decision(projection, department="engineering", proposal=proposal, facts=facts,
                              events=events)
    assert first.accepted, first.error_dicts
    arguments = dict(department="engineering", proposal=proposal,
                     evaluated=projection, facts=facts, events=events)
    assert commit_decision(first, current=projection, current_facts=facts, **arguments).accepted
    newer_input = replace(projection, input_version=projection.input_version + 1)
    carried = commit_decision(first, current=newer_input, current_facts=facts, **arguments)
    # 输入变了不再让这次提交作废（工单 #964）：拒绝的理由换成「输入还没有被产品处理」
    assert [error.field for error in carried.errors] == ["kind"]
    other_contract = replace(projection, effective_contract=replace(projection.effective_contract,
                                                                     content_hash="sha256:other"))
    rebound = commit_decision(first, current=other_contract, current_facts=facts, **arguments)
    assert not rebound.accepted, "当前工作变了仍然拒绝"
    system.workspace(projection.run_id).write_file("src/echo.py", "print('changed after validation')\n")
    changed = commit_decision(first, current=projection, current_facts=environment.query(FactsQuery(tree=True)).tree,
                              **arguments)
    assert not changed.accepted
    assert changed.errors[0].message.startswith("The workspace snapshot changed")


