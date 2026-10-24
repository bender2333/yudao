import asyncio
import json
import sys
from pathlib import Path
import pytest

from harness.collaboration import has_new_work
from harness.actions import Action
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.definitions import DEFINITIONS
from harness.environment import LocalEnvironment, QA_TESTS_DIR, inspection_root
from harness.event_store import Command
from harness.models import ArtifactRef, EventType, new_id
from harness.providers.call import ModelResponse
from harness.projection import saved_decisions
from harness.proposals import delivery_turn, product_spec, review_turn
from harness.public_tree import capture_public_tree
from harness.runtime import LoopSystem
from harness.tree_archive import load_tree, artifact_run


def test_qa_writes_test_and_runs_check(tmp_path: Path) -> None:
    test_py = f"{QA_TESTS_DIR}/test_smoke.py"
    test_content = "import sys\nprint('QA_SMOKE_PASS')\nsys.exit(0)\n"
    python_exe = sys.executable.replace("\\", "/")
    cmd = f'"{python_exe}" {test_py}'

    def qa_turn(call):
        turn = review_turn("release", "QA tests passed", checks={"qa_smoke": {"name": "qa_smoke", "command": cmd}})(call)
        return FakeTurn(
            writes={test_py: test_content},
            checks={"qa_smoke": {"name": "qa_smoke", "command": cmd}},
            proposal=turn.proposal
        )

    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        # 脚本按部门给出（工单 #877：PRD 被接纳以后工程与质检同时工作，
        # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [qa_turn],
    }))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)  # product
    system.activate_once(run_id)  # engineering
    system.activate_once(run_id)  # quality

    events = system.writes.read(f"run:{run_id}").events()
    saved_events = [e for e in events if e.type == EventType.QA_TESTS_SAVED]
    assert len(saved_events) == 1, f"Expected 1 qa_tests_saved event, got {len(saved_events)}"
    saved = saved_events[0]
    assert saved.payload["version"] == 1
    assert "content_hash" in saved.payload
    assert "archive_ref" in saved.payload
    assert saved.payload["activation_id"]

    check_started = next(e for e in events if e.type == EventType.TOOL_STARTED and e.department == "quality" and e.payload.get("name") == "run_check")
    assert saved.position < check_started.position, "qa_tests_saved must come before run_check's tool_started"

    check_called = next(e for e in events if e.type == EventType.TOOL_CALLED and e.department == "quality" and e.payload.get("name") == "run_check")
    assert check_called.payload.get("ok") is True
    output = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**check_called.payload["output_ref"])))
    assert "QA_SMOKE_PASS" in output.get("summary", "")
    assert output.get("qa_tests_hash") == saved.payload["content_hash"]
    qa_sub = next(e for e in events if e.type == EventType.QA_SUBMITTED)
    assert qa_sub.payload["checks"][0]["qa_tests_hash"] == saved.payload["content_hash"]


def test_next_session_has_saved_test_materials(tmp_path: Path) -> None:
    test_py = f"{QA_TESTS_DIR}/test_rework.py"
    test_content = "import sys\nprint('CHECK_V1_IN_SESSION_2')\nsys.exit(0)\n"
    python_exe = sys.executable.replace("\\", "/")
    cmd = f'"{python_exe}" {test_py}'

    def qa_turn_1(call):
        turn = review_turn("rework_engineering", "defects found", defects=[{"severity": "minor", "summary": "issue"}])(call)
        # proposal for rework
        return FakeTurn(
            writes={test_py: test_content},
            checks=turn.checks,
            proposal=turn.proposal
        )

    def qa_turn_2(call):
        turn = review_turn("release", "verified fixed delivery", checks={"verify_rework": {"name": "verify_rework", "command": cmd}})(call)
        return FakeTurn(
            checks=turn.checks,
            proposal=turn.proposal
        )

    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        # 脚本按部门给出（工单 #877）
        "product": [product_spec()],
        "engineering": [delivery_turn(summary="first delivery"), delivery_turn(summary="fixed delivery")],
        "quality": [qa_turn_1, qa_turn_2],
    }))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)  # product
    system.activate_once(run_id)  # engineering
    system.activate_once(run_id)  # quality rework
    system.activate_once(run_id)  # engineering 2
    system.activate_once(run_id)  # quality 2 (runs check on test_py in new session)

    events = system.writes.read(f"run:{run_id}").events()
    check_called = next(e for e in events if e.type == EventType.TOOL_CALLED and e.department == "quality" and e.payload.get("name") == "run_check" and (e.payload.get("args") or {}).get("name") == "verify_rework")
    assert check_called.payload.get("ok") is True
    output = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**check_called.payload["output_ref"])))
    assert "CHECK_V1_IN_SESSION_2" in output.get("summary", "")


def test_pause_and_resume_preserves_qa_tests(tmp_path: Path) -> None:
    test_py = f"{QA_TESTS_DIR}/test_paused.py"
    test_content = "import sys\nprint('RESUMED_QA_TEST_OK')\nsys.exit(0)\n"
    python_exe = sys.executable.replace("\\", "/")
    cmd = f'"{python_exe}" {test_py}'
    limit = DEFINITIONS.rule_value("tool_call_required_limit")

    # Turn with write_file, then plain text replies to trigger no_tool_call pause
    def qa_write_step(call):
        return FakeTurn(writes={test_py: test_content}, transcript="wrote test")

    def plain_reply(call):
        return FakeTurn(transcript="thinking...")

    def qa_resumed_step(call):
        turn = review_turn("release", "resumed release", checks={"resume_check": {"name": "resume_check", "command": cmd}})(call)
        return FakeTurn(
            checks={"resume_check": {"name": "resume_check", "command": cmd}},
            proposal=turn.proposal
        )

    script = {
        # 脚本按部门给出（工单 #877）：质检的轮数不随其他部门变化，
        # 质检自己的脚本按它自己的先后排列
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [qa_write_step, *[plain_reply for _ in range(limit + 1)], qa_resumed_step],
    }
    adapter = FakeAdapter(script)
    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("build echo")
    system.activate_once(run_id)  # product
    system.activate_once(run_id)  # engineering
    proj = system.run_until_stop(run_id)
    assert proj.status == "paused" and proj.stop_reason == "no_tool_call"

    # User answers decision to continue
    _pos, decisions = saved_decisions(system.store, statuses=("open",))
    run_decisions = [d for d in decisions if d.run_id == run_id]
    assert len(run_decisions) == 1
    d = run_decisions[0]
    command_obj = Command(new_id("cmd"), "decision.answer", f"sha256:continue:{d.version}", "user:local")
    system.orchestrator.answer_decision(d.decision_id, "continue", None, base_version=d.version, command=command_obj)

    result = system.run_until_stop(run_id)
    assert result.status == "done"

    events = system.writes.read(f"run:{run_id}").events()
    check_called = next(e for e in events if e.type == EventType.TOOL_CALLED and e.department == "quality" and e.payload.get("name") == "run_check" and (e.payload.get("args") or {}).get("name") == "resume_check")
    assert check_called.payload.get("ok") is True
    output = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**check_called.payload["output_ref"])))
    assert "RESUMED_QA_TEST_OK" in output.get("summary", "")


def test_qa_tests_dir_excluded_from_public_tree_and_delivery_and_engineering(tmp_path: Path) -> None:
    test_py = f"{QA_TESTS_DIR}/test_secret.py"

    def qa_turn(call):
        turn = review_turn("rework_engineering", "check private tree")(call)
        return FakeTurn(
            writes={test_py: "secret tests\n"},
            proposal=turn.proposal
        )

    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        # 脚本按部门给出（工单 #877）
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [qa_turn],
    }))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)  # product
    system.activate_once(run_id)  # engineering
    system.activate_once(run_id)  # quality writes test

    # 1. Public tree does not include QA_TESTS_DIR when directory exists
    dummy_dir = tmp_path / "dummy_repo"
    dummy_dir.mkdir()
    (dummy_dir / QA_TESTS_DIR).mkdir()
    (dummy_dir / QA_TESTS_DIR / "test.py").write_text("qa test", encoding="utf-8")
    (dummy_dir / "app.py").write_text("code", encoding="utf-8")
    tree = capture_public_tree(dummy_dir)
    assert QA_TESTS_DIR not in tree.directories
    assert not any(f.path.startswith(QA_TESTS_DIR) for f in tree.files)

    # 2. Delivery snapshot does not contain QA_TESTS_DIR
    proj = system.project(run_id)
    del_tree = load_tree(system.artifacts, artifact_run(proj.delivery_spec.tree_ref.path), proj.delivery_spec.tree_ref)
    assert QA_TESTS_DIR not in del_tree.directories
    assert not any(f.path.startswith(QA_TESTS_DIR) for f in del_tree.files)

    # 3. Engineering workspace does not contain QA_TESTS_DIR
    eng_root = system.workspace_root / run_id
    assert not (eng_root / QA_TESTS_DIR).exists()

    # 4. Engineering file tools reading/writing QA_TESTS_DIR are rejected
    env = system.environment(run_id)
    write_act = Action(
        action_id="act-1", kind="write", tool="write_file", department="engineering",
        input={"path": f"{QA_TESTS_DIR}/forbidden.py", "content": "bad"}
    )
    receipt = asyncio.run(env.perform(write_act))
    assert receipt.status == "failed"
    assert "质检的测试材料" in str(receipt.error)

    read_act = Action(
        action_id="act-2", kind="read", tool="read_file", department="engineering",
        input={"path": f"{QA_TESTS_DIR}/forbidden.py"}
    )
    receipt = asyncio.run(env.perform(read_act))
    assert receipt.status == "failed"
    assert "质检的测试材料" in str(receipt.error)


def test_persistence_and_reload_survives_new_loopsystem(tmp_path: Path) -> None:
    test_v1 = f"{QA_TESTS_DIR}/test_v1.py"
    test_v2 = f"{QA_TESTS_DIR}/test_v2.py"

    def qa_turn_1(call):
        turn = review_turn("rework_engineering", "defects found", defects=[{"severity": "minor", "summary": "issue"}])(call)
        return FakeTurn(
            writes={test_v1: "v1"},
            checks=turn.checks,
            proposal=turn.proposal
        )

    def qa_turn_2(call):
        turn = review_turn("release", "v2 verified")(call)
        return FakeTurn(
            writes={test_v2: "v2"},
            checks=turn.checks,
            proposal=turn.proposal
        )

    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        # 脚本按部门给出（工单 #877）
        "product": [product_spec()],
        "engineering": [delivery_turn(summary="first delivery"), delivery_turn(summary="second delivery")],
        "quality": [qa_turn_1, qa_turn_2],
    }))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)  # product
    system.activate_once(run_id)  # engineering
    system.activate_once(run_id)  # quality v1
    system.activate_once(run_id)  # engineering 2
    system.activate_once(run_id)  # quality v2

    proj_before = system.project(run_id)
    assert proj_before.qa_tests_version == 2
    hash_v2 = proj_before.qa_tests_hash

    # Create fresh LoopSystem on the same data directory
    reloaded = LoopSystem.for_testing(tmp_path, FakeAdapter([]), resume_on_startup=False)
    proj_after = reloaded.project(run_id)
    assert proj_after.qa_tests_version == 2
    assert proj_after.qa_tests_hash == hash_v2
    assert proj_after.qa_tests_archive_ref is not None

    # New inspection environment created from reloaded system places version 2
    env = reloaded.orchestrator._new_inspection_environment(run_id, "quality")
    assert (env.workspace.root / test_v2).exists()
    assert (env.workspace.root / test_v2).read_text(encoding="utf-8") == "v2"


def test_no_event_when_unchanged_or_empty_initial(tmp_path: Path) -> None:
    def qa_turn_1(call):
        turn = review_turn("rework_engineering", "check done",
                           checks={"smoke": {"name": "smoke", "command": 'python -c "exit(0)"'}},
                           defects=[{"severity": "minor", "summary": "need rework"}])(call)
        return FakeTurn(
            checks={"smoke": {"name": "smoke", "command": 'python -c "exit(0)"'}},
            proposal=turn.proposal
        )

    def qa_turn_2(call):
        turn = review_turn("release", "release done",
                           checks={"smoke": {"name": "smoke", "command": 'python -c "exit(0)"'}})(call)
        return FakeTurn(
            writes={f"{QA_TESTS_DIR}/test_a.py": "def test_a(): pass\n"},
            checks={"smoke": {"name": "smoke", "command": 'python -c "exit(0)"'}},
            proposal=turn.proposal
        )

    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        # 脚本按部门给出（工单 #877）
        "product": [product_spec()],
        "engineering": [delivery_turn(), delivery_turn(summary="delivery 2")],
        "quality": [qa_turn_1, qa_turn_2],
    }))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)  # product
    system.activate_once(run_id)  # engineering
    system.activate_once(run_id)  # quality turn 1 (empty, no qa_tests_saved)

    events_1 = system.writes.read(f"run:{run_id}").events()
    saved_1 = [e for e in events_1 if e.type == EventType.QA_TESTS_SAVED]
    assert len(saved_1) == 0, "No qa_tests_saved should be written when initially empty"

    system.activate_once(run_id)  # engineering 2
    system.activate_once(run_id)  # quality turn 2 (writes test_a.py and runs smoke check)

    events_2 = system.writes.read(f"run:{run_id}").events()
    saved_2 = [e for e in events_2 if e.type == EventType.QA_TESTS_SAVED]
    assert len(saved_2) == 1, "Exactly 1 qa_tests_saved should be written (version 1), smoke check did not change it"
    assert saved_2[0].payload["version"] == 1


def test_qa_modifying_test_materials_rejects_release_with_old_receipt_until_rerun(tmp_path: Path) -> None:
    test_py = f"{QA_TESTS_DIR}/test_check.py"
    content_v1 = "import sys\nprint('V1')\nsys.exit(0)\n"
    content_v2 = "import sys\nprint('V2')\nsys.exit(0)\n"
    python_exe = sys.executable.replace("\\", "/")
    cmd = f'"{python_exe}" {test_py}'

    def qa_step_1(call):
        return FakeTurn(
            writes={test_py: content_v1},
            checks={"qa_check": {"name": "qa_check", "command": cmd}},
            transcript="wrote v1 and ran check",
        )

    def qa_step_2(call):
        turn = review_turn("release", "attempt release with v1 receipt",
                           checks={"qa_check": {"name": "qa_check", "command": cmd}})(call)
        return FakeTurn(
            writes={test_py: content_v2},
            proposal=turn.proposal,
            transcript="wrote v2 and proposed release",
        )

    def qa_step_3(call):
        turn = review_turn("release", "release with rerun check",
                           checks={"qa_check": {"name": "qa_check", "command": cmd}})(call)
        return FakeTurn(
            checks={"qa_check": {"name": "qa_check", "command": cmd}},
            proposal=turn.proposal,
            transcript="reran check and proposed release",
        )

    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        # 脚本按部门给出（工单 #877）：质检的脚本按它自己的先后排列
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [qa_step_1, qa_step_2, qa_step_3],
    }))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)  # product
    system.activate_once(run_id)  # engineering
    proj_qa1 = system.activate_once(run_id)  # quality steps 1 and 2

    # Verify step 2's proposal was rejected because test materials changed
    events = system.writes.read(f"run:{run_id}").events()
    rejected_events = [e for e in events if e.type == EventType.PROPOSAL_REJECTED]
    assert len(rejected_events) == 1
    rejected = rejected_events[0]
    errors = rejected.payload.get("errors", [])
    assert any(err.get("field") == "checks" and "测试材料已经改变，用当前的测试材料重新运行检查" in err.get("message", "")
               for err in errors), f"Expected checks error message, got: {errors}"
    assert has_new_work(proj_qa1, "quality")

    # Now step 3 runs in next activation: reruns check and release is accepted
    proj_qa2 = system.activate_once(run_id)
    assert proj_qa2.status == "done"

    events_final = system.writes.read(f"run:{run_id}").events()
    qa_submitted_events = [e for e in events_final if e.type == EventType.QA_SUBMITTED]
    assert len(qa_submitted_events) == 1
    qa_sub = qa_submitted_events[0]
    checks = qa_sub.payload.get("checks", [])
    assert len(checks) == 1
    assert checks[0]["qa_tests_hash"] == proj_qa2.qa_tests_hash
    assert checks[0]["qa_tests_hash"] is not None


def test_qa_emptying_test_materials_allows_release(tmp_path: Path) -> None:
    test_py = f"{QA_TESTS_DIR}/test_check.py"
    content = "import sys\nprint('PASS')\nsys.exit(0)\n"
    python_exe = sys.executable.replace("\\", "/")
    cmd = f'"{python_exe}" {test_py}'
    pass_cmd = f'"{python_exe}" -c "import sys; sys.exit(0)"'
    clean_cmd = f'"{python_exe}" -c "import os; os.remove(\'{test_py}\')"'
    def qa_step_1(call):
        return FakeTurn(
            writes={test_py: content},
            checks={"qa_check": {"name": "qa_check", "command": cmd}},
            transcript="wrote test and ran check",
        )

    def qa_step_2(call):
        turn = review_turn("release", "release after emptying qa tests",
                           checks={"pass_check": {"name": "pass_check", "command": pass_cmd}})(call)
        c1 = {"id": "c1", "call_id": "c1", "type": "function_call", "name": "bash",
              "arguments": json.dumps({"command": clean_cmd})}
        c2 = {"id": "c2", "call_id": "c2", "type": "function_call", "name": "run_check",
              "arguments": json.dumps({"name": "pass_check", "command": pass_cmd})}
        submit_args = {k: v for k, v in turn.proposal.items() if k != "kind"}
        c3 = {"id": "c3", "call_id": "c3", "type": "function_call", "name": "submit_review",
              "arguments": json.dumps(submit_args)}
        return ModelResponse(
            output=[c1, c2, c3],
            provider="fake",
            model="fake-script",
        )

    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        # 脚本按部门给出（工单 #877）
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [qa_step_1, qa_step_2],
    }))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)  # product
    system.activate_once(run_id)  # engineering
    proj = system.activate_once(run_id)  # quality step 1 & 2

    assert proj.status == "done"

    events = system.writes.read(f"run:{run_id}").events()
    saved_events = [e for e in events if e.type == EventType.QA_TESTS_SAVED]
    assert len(saved_events) == 2, f"Expected 2 qa_tests_saved events, got {len(saved_events)}"
    assert saved_events[0].payload["version"] == 1
    assert saved_events[0].payload["content_hash"] is not None
    assert saved_events[1].payload["version"] == 2
    assert saved_events[1].payload["content_hash"] is None
    assert proj.qa_tests_hash is None

    qa_sub = next(e for e in events if e.type == EventType.QA_SUBMITTED)
    assert qa_sub.payload["checks"][0]["qa_tests_hash"] is None
