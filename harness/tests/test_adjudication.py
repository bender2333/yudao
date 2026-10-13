from dataclasses import replace

from harness.actions import FactsQuery
from harness.adapters.fake import FakeAdapter
from harness.adjudication import WorkBasis, commit_decision, facts_query, proposal_decision, tool_permission
from harness.environment import LocalEnvironment
from harness.proposals import collaboration_request, product_spec
from harness.runtime import LoopSystem

REGISTRY = {"unit": {"argv": ["python", "-c", "print('ok')"], "args": ["--fast"]}}

def _engineering(tmp_path):
    # 产品要求已接纳，工程部门正在工作：直接依据有效合同写文件
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec()]))
    run_id = system.create_run("echo", registered_commands=REGISTRY, command_versions={"unit": 1})
    projection = system.activate_once(run_id)
    assert projection.phase == "ENGINEERING" and projection.effective_contract is not None
    return system, projection

def _environment(system, projection):
    return LocalEnvironment(system.workspace(projection.run_id))

def _permission(system, projection, name, args, *, basis=None, aborted=False, guidance_only=False):
    # 工具许可依据的工作区事实由执行环境按 U 给出的查询取得
    call = {"id": "call", "name": name, "args": args}
    return tool_permission(
        projection, call, department="engineering",
        guidance_only=guidance_only, basis=basis or WorkBasis.current(projection, "engineering"),
        aborted=aborted, facts=_environment(system, projection).query(facts_query(call)),
    )

def test_tool_permission_stops_after_cancel_end_or_changed_basis(tmp_path):
    system, projection = _engineering(tmp_path)
    write = ("write_file", {"path": "src/echo.py", "content": "print(1)\n"})
    assert _permission(system, projection, *write).allowed
    assert _permission(system, projection, *write, aborted=True).stopped
    assert _permission(system, replace(projection, phase="FAILED"), *write).stopped
    newer_input = replace(WorkBasis.current(projection, "engineering"), input_version=projection.input_version - 1)
    assert _permission(system, projection, *write, basis=newer_input).stopped
    other_contract = replace(WorkBasis.current(projection, "engineering"), effective_contract_hash="sha256:other")
    assert _permission(system, projection, *write, basis=other_contract).stopped

def test_tool_permission_denies_with_a_reason_the_model_receives(tmp_path):
    system, projection = _engineering(tmp_path)
    assert _permission(system, projection, "submit_review", {}).reason == "engineering cannot use submit_review"
    guidance = _permission(system, projection, "write_file", {"path": "src/echo.py", "content": ""}, guidance_only=True)
    outside = _permission(system, projection, "write_file", {"path": "docs/notes.md", "content": ""})
    assert outside.allowed
    missing_command = _permission(system, projection, "bash", {})
    assert missing_command.reason is None

def test_commit_decision_rejects_results_whose_basis_or_workspace_changed(tmp_path):
    system, projection = _engineering(tmp_path)
    environment = _environment(system, projection)
    proposal = collaboration_request()
    facts = environment.query(FactsQuery(tree=True)).tree
    events = system.store.list_events(projection.run_id)
    first = proposal_decision(projection, department="engineering", proposal=proposal, facts=facts,
                              events=events)
    assert first.accepted, first.error_dicts
    arguments = dict(department="engineering", proposal=proposal,
                     basis=WorkBasis.current(projection, "engineering"), started=projection,
                     evaluated=projection, facts=facts, events=events)
    assert commit_decision(first, current=projection, current_facts=facts, **arguments).accepted
    newer_input = replace(projection, input_version=projection.input_version + 1)
    stale = commit_decision(first, current=newer_input, current_facts=facts, **arguments)
    assert [error.field for error in stale.errors] == ["execution_basis"]
    other_contract = replace(projection, effective_contract=replace(projection.effective_contract,
                                                                     content_hash="sha256:other"))
    rebound = commit_decision(first, current=other_contract, current_facts=facts, **arguments)
    assert [error.field for error in rebound.errors] == ["execution_basis"]
    system.workspace(projection.run_id).write_file("src/echo.py", "print('changed after validation')\n")
    changed = commit_decision(first, current=projection, current_facts=environment.query(FactsQuery(tree=True)).tree,
                              **arguments)
    assert not changed.accepted
    assert changed.errors[0].message.startswith("The workspace snapshot changed")


def test_bash_permission_has_no_command_registry_basis(tmp_path):
    system, projection = _engineering(tmp_path)
    permission = _permission(system, projection, "bash", {"command": "python -c \"print('ok')\""})
    assert permission.allowed
    # bash 不核对命令登记表，许可不再带登记执行依据
    assert permission.command_basis == {}

def test_write_permission_uses_the_canonical_path_from_the_environment(tmp_path):
    system, projection = _engineering(tmp_path)
    call = {"id": "call", "name": "move_file", "args": {"source": "src/a.py", "destination": "src/b.py", "reason": "r"}}
    query = facts_query(call)
    assert query == FactsQuery(paths=("src/a.py", "src/b.py"))
    system.workspace(projection.run_id).write_file("src/a.py", "a\n")
    facts = _environment(system, projection).query(query)
    assert facts.paths["src/a.py"].canonical == "src/a.py" and facts.paths["src/a.py"].kind == "file"
    assert facts.paths["src/b.py"].kind == "missing"
    assert facts_query({"id": "call", "name": "read_file", "args": {"path": "src/a.py"}}) == FactsQuery()
    # 祖先是文件的路径在工作区中不能表示：拒绝原因就是执行环境给出的原因
    inner = _permission(system, projection, "write_file", {"path": "src/a.py/inner.py", "content": ""})
    reason = _environment(system, projection).query(FactsQuery(paths=("src/a.py/inner.py",))).paths["src/a.py/inner.py"].error
    assert reason is not None and "not a directory" in reason
    assert inner.reason == reason and not inner.stopped
