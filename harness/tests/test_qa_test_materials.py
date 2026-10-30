# 质检在检查工作区里写测试的文件工具（工单 #645）：write_file 与 edit_range 只写 .yudao-qa-tests/。
# 写进去的内容按测试材料保存为新版本，进入之后的检查副本；写测试材料目录以外的路径被工具许可拒绝，
# 运行工作区与交付快照不变。工具的每次调用由假模型按真实路径发出（write_file、edit_range、run_check、
# submit_review 各是一次调用），照常经过工具许可与执行环境。

import asyncio
import json
import sys
from pathlib import Path

from harness.actions import Action
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.models import ArtifactRef, EventType, json_dumps
from harness.path_rules import QA_TESTS_DIR
from harness.proposals import delivery_turn, product_spec, review_turn
from harness.providers.call import ModelResponse
from harness.public_tree import capture_public_tree
from harness.runtime import LoopSystem
from harness.tree_archive import artifact_run, load_tree
from harness.watched_outputs import has_new_work

ECHO = "import sys\nprint(sys.argv[1])\n"


def _call(identity: str, name: str, arguments: dict) -> dict:
    # 假模型回复里的一次工具调用：与真实模型发出的调用同形
    return {"id": identity, "call_id": identity, "type": "function_call", "name": name,
            "arguments": json_dumps(arguments)}


def _tool_turn(identity: str, tool: str, **arguments) -> ModelResponse:
    return ModelResponse(output=[_call(identity, tool, arguments)])


def _review_turn(call, rationale: str, name: str, command: str) -> FakeTurn:
    # 这一步只提交放行：提案由构造函数生成，依据版本按请求里的当前交付填写；检查在上一步已经跑过
    turn = review_turn("release", rationale, checks={name: {"name": name, "command": command}})(call)
    return FakeTurn(proposal=turn.proposal)


def _python() -> str:
    return sys.executable.replace("\\", "/")


def _events(system: LoopSystem, run_id: str) -> list:
    return system.writes.read(f"run:{run_id}").events()


def _sealed_files(system: LoopSystem, run_id: str) -> dict[str, str]:
    # 封存的交付快照里的文件内容：质检的写入不该进入交付快照
    delivery = system.project(run_id).delivery_spec
    tree = load_tree(system.artifacts, artifact_run(delivery.tree_ref.path), delivery.tree_ref)
    return {item.path: item.data.decode("utf-8") for item in tree.files}


def test_qa_writes_test_and_runs_check(tmp_path: Path) -> None:
    test_py = f"{QA_TESTS_DIR}/test_smoke.py"
    test_content = "import sys\nprint('QA_SMOKE_PASS')\nsys.exit(0)\n"
    command = f'"{_python()}" {test_py}'

    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        # 脚本按部门给出（工单 #877：PRD 被接纳以后工程与质检同时工作，
        # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [
            lambda call: _tool_turn("qa-write", "write_file", path=test_py, content=test_content),
            lambda call: _tool_turn("qa-check", "run_check", name="qa_smoke", command=command),
            lambda call: _review_turn(call, "QA tests passed", "qa_smoke", command),
        ],
    }))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)  # product
    system.activate_once(run_id)  # engineering
    system.activate_once(run_id)  # quality：写测试、跑检查、放行

    events = _events(system, run_id)
    # 写入经过工具许可并被执行：工具开始事件在调用结果之前
    started = next(e for e in events if e.type == EventType.TOOL_STARTED and e.payload.get("id") == "qa-write")
    written = next(e for e in events if e.type == EventType.TOOL_CALLED and e.payload.get("id") == "qa-write")
    assert written.payload["ok"] is True, written.payload.get("error")
    assert started.position < written.position
    # 写进测试材料目录的内容保存为测试材料的新版本
    saved_events = [e for e in events if e.type == EventType.QA_TESTS_SAVED]
    assert len(saved_events) == 1, f"Expected 1 qa_tests_saved event, got {len(saved_events)}"
    saved = saved_events[0]
    assert saved.payload["version"] == 1
    assert "content_hash" in saved.payload
    assert "archive_ref" in saved.payload
    assert saved.payload["activation_id"]

    # 之后的检查副本带上这份测试材料：回执绑定它的版本，命令在副本里跑通了写下的测试
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
    command = f'"{_python()}" {test_py}'
    smoke = f'"{_python()}" -c "raise SystemExit(0)"'

    def write_tests(call):
        return _tool_turn("qa-write", "write_file", path=test_py, content=test_content)

    def rework(call):
        # 这一轮退回返工：列出的检查要有本轮的回执，所以同一步先跑检查再提交
        turn = review_turn("rework_engineering", "defects found",
                           checks={"smoke": {"name": "smoke", "command": smoke}},
                           defects=[{"severity": "minor", "summary": "issue"}])(call)
        return ModelResponse(output=[
            _call("qa-smoke", "run_check", {"name": "smoke", "command": smoke}),
            _call("qa-rework", "submit_review", {key: value for key, value in turn.proposal.items() if key != "kind"}),
        ])

    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        # 脚本按部门给出（工单 #877）
        "product": [product_spec()],
        "engineering": [delivery_turn(summary="first delivery"), delivery_turn(summary="fixed delivery")],
        "quality": [write_tests, rework,
                    review_turn("release", "verified fixed delivery",
                                checks={"verify_rework": {"name": "verify_rework", "command": command}})],
    }))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)  # product
    system.activate_once(run_id)  # engineering
    system.activate_once(run_id)  # quality：写测试、退回返工
    system.activate_once(run_id)  # engineering 2
    system.activate_once(run_id)  # quality 2：新的检查工作区里有保存下来的测试材料

    events = _events(system, run_id)
    check_called = next(e for e in events if e.type == EventType.TOOL_CALLED and e.department == "quality" and e.payload.get("name") == "run_check" and (e.payload.get("args") or {}).get("name") == "verify_rework")
    assert check_called.payload.get("ok") is True
    output = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**check_called.payload["output_ref"])))
    assert "CHECK_V1_IN_SESSION_2" in output.get("summary", "")


def test_qa_tests_dir_excluded_from_public_tree_and_delivery_and_engineering(tmp_path: Path) -> None:
    test_py = f"{QA_TESTS_DIR}/test_secret.py"

    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        # 脚本按部门给出（工单 #877）
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [lambda call: _tool_turn("qa-write", "write_file", path=test_py, content="secret tests\n")],
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


def test_qa_write_outside_the_test_materials_is_denied(tmp_path: Path) -> None:
    # 验收第 2 条：质检写测试材料目录以外的路径被工具许可拒绝并说明原因；
    # 运行工作区与交付快照不变，这一轮工作照常继续（写测试材料、跑检查、放行都走通）
    test_py = f"{QA_TESTS_DIR}/test_smoke.py"
    test_content = "import sys\nprint('QA_SMOKE_PASS')\nsys.exit(0)\n"
    command = f'"{_python()}" {test_py}'
    tampered = "print('tampered')\n"

    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [
            lambda call: _tool_turn("qa-write-outside", "write_file", path="src/echo.py", content=tampered),
            lambda call: _tool_turn("qa-write-tests", "write_file", path=test_py, content=test_content),
            lambda call: _tool_turn("qa-check", "run_check", name="qa_smoke", command=command),
            lambda call: _review_turn(call, "checks passed on the current snapshot", "qa_smoke", command),
        ],
    }))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)  # product
    system.activate_once(run_id)  # engineering
    projection = system.activate_once(run_id)  # quality
    assert projection.status == "done", projection.stop_reason

    events = _events(system, run_id)
    outside = next(e for e in events
                   if e.type == EventType.TOOL_CALLED and (e.payload or {}).get("id") == "qa-write-outside")
    assert outside.department == "quality"
    assert outside.payload["ok"] is False
    # 拒绝原因说明质检只能写测试材料目录
    assert QA_TESTS_DIR in outside.payload["error"] and "quality" in outside.payload["error"]
    assert not any(e.type == EventType.TOOL_STARTED and e.payload.get("id") == "qa-write-outside" for e in events)
    # 写测试材料目录里的路径照常执行：这一次拒绝只针对目录以外的路径
    inside = next(e for e in events
                  if e.type == EventType.TOOL_CALLED and (e.payload or {}).get("id") == "qa-write-tests")
    assert inside.payload["ok"] is True, inside.payload.get("error")
    # 运行工作区与交付快照里仍然是工程写的文件
    assert (system.workspace_root / run_id / "src" / "echo.py").read_text(encoding="utf-8") == ECHO
    assert _sealed_files(system, run_id)["src/echo.py"] == ECHO


def test_qa_modifying_test_materials_rejects_release_with_old_receipt_until_rerun(tmp_path: Path) -> None:
    test_py = f"{QA_TESTS_DIR}/test_check.py"
    content_v1 = "import sys\nprint('V1')\nsys.exit(0)\n"
    command = f'"{_python()}" {test_py}'
    check_spec = {"name": "qa_check", "command": command}

    def write_v1(call):
        return _tool_turn("qa-write", "write_file", path=test_py, content=content_v1)

    def check_v1(call):
        return _tool_turn("qa-check-1", "run_check", **check_spec)

    def edit_and_release(call):
        # 区间编辑改掉测试材料，然后用改之前的回执放行：提案被拒绝
        turn = review_turn("release", "attempt release with v1 receipt", checks={"qa_check": check_spec})(call)
        return ModelResponse(output=[
            _call("qa-edit", "edit_range", {"path": test_py, "expected_text": "print('V1')",
                                            "new_text": "print('V2')"}),
            _call("qa-release-1", "submit_review",
                  {key: value for key, value in turn.proposal.items() if key != "kind"}),
        ])

    def check_v2_and_release(call):
        turn = review_turn("release", "release with rerun check", checks={"qa_check": check_spec})(call)
        return ModelResponse(output=[
            _call("qa-check-2", "run_check", check_spec),
            _call("qa-release-2", "submit_review",
                  {key: value for key, value in turn.proposal.items() if key != "kind"}),
        ])

    system = LoopSystem.for_testing(tmp_path, FakeAdapter({
        # 脚本按部门给出（工单 #877）：质检的脚本按它自己的先后排列
        "product": [product_spec()],
        "engineering": [delivery_turn()],
        "quality": [write_v1, check_v1, edit_and_release, check_v2_and_release],
    }))
    run_id = system.create_run("build echo")
    system.activate_once(run_id)  # product
    system.activate_once(run_id)  # engineering
    proj_qa1 = system.activate_once(run_id)  # quality：写 v1、跑检查、改材料后放行被拒

    # 两次保存测试材料：write_file 保存 v1，edit_range 保存 v2，两份的内容摘要不同
    saved_events = [e for e in _events(system, run_id) if e.type == EventType.QA_TESTS_SAVED]
    assert [e.payload["version"] for e in saved_events] == [1, 2]
    assert saved_events[0].payload["content_hash"] != saved_events[1].payload["content_hash"]

    # 改过测试材料以后用旧回执放行：提案被拒绝，这一轮结束时还有工作
    rejected_events = [e for e in _events(system, run_id) if e.type == EventType.PROPOSAL_REJECTED]
    assert len(rejected_events) == 1
    errors = rejected_events[0].payload.get("errors", [])
    assert any(err.get("field") == "checks" and "测试材料已经改变，用当前的测试材料重新运行检查" in err.get("message", "")
               for err in errors), f"Expected checks error message, got: {errors}"
    assert has_new_work(proj_qa1, "quality")

    # 下一步用改过以后的测试材料重新跑检查再放行：接纳
    proj_qa2 = system.activate_once(run_id)
    assert proj_qa2.status == "done"

    events_final = _events(system, run_id)
    qa_submitted_events = [e for e in events_final if e.type == EventType.QA_SUBMITTED]
    assert len(qa_submitted_events) == 1
    qa_sub = qa_submitted_events[0]
    checks = qa_sub.payload.get("checks", [])
    assert len(checks) == 1
    assert checks[0]["qa_tests_hash"] == proj_qa2.qa_tests_hash
    assert checks[0]["qa_tests_hash"] is not None
    # 重新跑的检查在副本里跑的是编辑以后的测试：输出里是 V2
    rerun = next(e for e in events_final if e.type == EventType.TOOL_CALLED and (e.payload or {}).get("id") == "qa-check-2")
    output = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**rerun.payload["output_ref"])))
    assert "V2" in output.get("summary", "")
