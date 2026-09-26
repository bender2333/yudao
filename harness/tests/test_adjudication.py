from dataclasses import replace

from harness.adapters.fake import FakeAdapter
from harness.adjudication import WorkBasis, commit_decision, proposal_decision, tool_permission
from harness.proposals import engineering_plan, plan_turn, product_spec
from harness.runtime import LoopSystem

REGISTRY = {"unit": {"argv": ["python", "-c", "print('ok')"], "args": ["--fast"]}}


def _engineering(tmp_path):
    # 产品要求与工程计划都已接纳，工程部门正在工作；计划范围是 src/
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([product_spec(), plan_turn(scope=["src/"])]))
    run_id = system.create_run("echo", registered_commands=REGISTRY, command_versions={"unit": 1})
    system.activate_once(run_id)
    projection = system.activate_once(run_id)
    assert projection.phase == "ENGINEERING" and projection.engineering_plan is not None
    return system, projection


def _permission(system, projection, name, args, *, basis=None, aborted=False, guidance_only=False):
    return tool_permission(
        projection, {"id": "call", "name": name, "args": args}, department="engineering",
        guidance_only=guidance_only, basis=basis or WorkBasis.current(projection, "engineering"),
        aborted=aborted, workspace=system.workspace(projection.run_id),
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
    assert guidance.reason == "This guidance activation cannot change files or submit normal department work."
    outside = _permission(system, projection, "write_file", {"path": "docs/notes.md", "content": ""})
    assert not outside.allowed and not outside.stopped
    assert "outside the current engineering plan scope" in outside.reason
    unknown = _permission(system, projection, "run_command", {"name": "deploy"})
    assert unknown.reason == "unknown registered command: deploy; only project-registered commands may run"
    extra = _permission(system, projection, "run_command", {"name": "unit", "args": ["--slow"]})
    assert extra.reason == "argument not allowlisted for unit: --slow"


def test_commit_decision_rejects_results_whose_basis_or_workspace_changed(tmp_path):
    system, projection = _engineering(tmp_path)
    workspace = system.workspace(projection.run_id)
    proposal = engineering_plan(scope=["src/", "tests/"], reason="Tests need their own directory")
    snapshot = workspace.snapshot()
    events = system.store.list_events(projection.run_id)
    first = proposal_decision(projection, department="engineering", proposal=proposal, snapshot=snapshot,
                              events=events)
    assert first.accepted, first.error_dicts
    arguments = dict(department="engineering", proposal=proposal,
                     basis=WorkBasis.current(projection, "engineering"), started=projection,
                     evaluated=projection, snapshot=snapshot, events=events)
    assert commit_decision(first, current=projection, current_snapshot=snapshot, **arguments).accepted
    newer_input = replace(projection, input_version=projection.input_version + 1)
    stale = commit_decision(first, current=newer_input, current_snapshot=snapshot, **arguments)
    assert [error.field for error in stale.errors] == ["execution_basis"]
    workspace.write_file("src/echo.py", "print('changed after validation')\n")
    changed = commit_decision(first, current=projection, current_snapshot=workspace.snapshot(), **arguments)
    assert not changed.accepted
    assert changed.errors[0].message.startswith("The workspace snapshot changed")


def test_registered_command_permission_carries_its_execution_basis(tmp_path):
    system, projection = _engineering(tmp_path)
    permission = _permission(system, projection, "run_command", {"name": "unit", "args": ["--fast"]})
    assert permission.allowed
    assert permission.command_basis == {
        "registered_name": "unit",
        "registered_argv": ["python", "-c", "print('ok')", "--fast"],
        "snapshot_hash": system.workspace(projection.run_id).snapshot().digest,
    }
