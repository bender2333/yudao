from dataclasses import replace

from harness.actions import FactsQuery
from harness.adapters.fake import FakeAdapter
from harness.adjudication import WorkBasis, commit_decision, facts_query, proposal_decision, tool_permission
from harness.collaboration import has_new_work, pending_product_input
from harness.environment import LocalEnvironment
from harness.models import SessionRecord
from harness.proposals import delivery, delivery_turn, product_spec
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
    # 输入变了不再让这次提交作废（工单 #964、#561）：新的输入作为通知送达，这次提交照常接纳
    assert carried.accepted, carried.error_dicts
    other_contract = replace(projection, effective_contract=replace(projection.effective_contract,
                                                                     content_hash="sha256:other"))
    rebound = commit_decision(first, current=other_contract, current_facts=facts, **arguments)
    assert not rebound.accepted, "当前工作变了仍然拒绝"
    system.workspace(projection.run_id).write_file("src/echo.py", "print('changed after validation')\n")
    changed = commit_decision(first, current=projection, current_facts=environment.query(FactsQuery(tree=True)).tree,
                              **arguments)
    assert not changed.accepted
    assert changed.errors[0].message.startswith("The workspace snapshot changed")


def test_pending_product_input_counts_a_finished_or_empty_item_as_processed(tmp_path):
    # 工单 #561：放行等输入处理完的只读判断（工具许可按它决定等不等）在两种边界上不等——
    # 事项已经结束当作处理完（部门指导设计说明第 3 节），以及没有任何发给产品的输入与指导时
    # 没有要等的。守 R3（写到设计说明里的行为），只读投影与事件，不写事件
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec()]))
    run_id = system.create_run("echo")
    projection = system.activate_once(run_id)
    events = system.store.list_events(run_id)

    finished = replace(projection, status="done")
    assert pending_product_input(finished, events) is False
    empty = replace(projection, inputs=[], department_guidance=[])
    assert pending_product_input(empty, events) is False


def test_engineering_has_new_work_until_a_delivery_matches_the_current_contract(tmp_path):
    # 验收第 3 条（#1079，部门指导设计说明第 2.1 节第 2 点）：产品决定只重算合同、不产生
    # 新的 PRD 版本；工程最近一份交付依据的合同不是当前有效合同时它有新工作，按当前合同
    # 重新交付以后不再有新工作。守 R3：直接对投影断言，只读，不写事件
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [delivery_turn()]})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    projection = system.activate_once(run_id)
    [delivered] = projection.delivery_specs
    assert delivered.effective_contract_hash == projection.effective_contract.content_hash
    # 交付依据当前合同：工程没有新工作
    assert not has_new_work(projection, "engineering")

    # 产品决定重算合同（PRD 没有新版本）：交付依据的是旧合同，工程有新工作
    decided = replace(projection, effective_contract=replace(projection.effective_contract,
                                                             content_hash="sha256:decided"))
    assert decided.product_spec == projection.product_spec
    assert has_new_work(decided, "engineering")

    # 工程按新的合同重新交付以后不再有新工作
    redelivered = replace(decided, delivery_specs=[
        replace(delivered, content_hash="sha256:second", effective_contract_hash="sha256:decided")])
    assert not has_new_work(redelivered, "engineering")


def test_the_new_work_checks_hold_when_there_is_no_effective_contract(tmp_path):
    # 边界（工单 #1079，部门指导设计说明第 2.1 节第 2 点）：比合同的这一支只在
    # 合同与交付都算出来的时候决定；有效合同还没有算出来时工程与质检都没有这一项新工作，
    # PRD 的内容变了工程照旧有新工作。守 R3：直接对投影断言，只读
    adapter = FakeAdapter({"product": [product_spec()], "engineering": [delivery_turn()]})
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo")
    system.activate_once(run_id)
    projection = system.activate_once(run_id)

    # 交付依据的 PRD 内容与当前 PRD 不同：工程照旧有新工作（PRD 新版本的路径不变）
    other_spec = replace(projection.product_spec, content_hash="sha256:other")
    assert has_new_work(replace(projection, product_spec=other_spec), "engineering")

    # 有效合同还没有算出来：工程（交付与合同都算不出来）与质检都没有这一项新工作
    assert not has_new_work(replace(projection, effective_contract=None), "engineering")
    # 质检看的是「有没有交付要核验」：这里把交付也去掉，只看合同这一支
    no_delivery = replace(projection, effective_contract=None, delivery_spec=None, delivery_specs=[])
    assert not has_new_work(no_delivery, "quality")



