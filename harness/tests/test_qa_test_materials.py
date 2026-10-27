import asyncio
import json
import sys
from pathlib import Path

from harness.watched_outputs import has_new_work
from harness.actions import Action
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.environment import QA_TESTS_DIR
from harness.models import ArtifactRef, EventType
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


