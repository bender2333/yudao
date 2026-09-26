import json
import os

import pytest

from harness.providers.call import ModelResponse
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.models import ArtifactRef, EventType, ProjectEventType, json_dumps
from harness.proposals import delivery, delivery_turn, plan_turn, product_spec, review, review_turn
from harness.public_tree import capture_public_tree
from harness.environment import LocalEnvironment
from harness.runtime import LoopSystem
from harness.tests.helpers import perform
from harness.tools import TOOL_DEFS, tools_for
from harness.tree_archive import load_tree
from harness.workspace import Workspace


def _environment(root):
    workspace = Workspace(root)
    return workspace, LocalEnvironment(workspace)


def _read_content_hash(environment, path, start=1, end=None):
    args = {"path": path, "start_line": start}
    if end is not None:
        args["end_line"] = end
    seen = perform(environment, "read_range", args)
    assert seen.ok, seen.error
    return seen.output["content_hash"]


def _edit_call(identity, path, start, end, expected, new, digest):
    return {
        "id": identity, "call_id": identity, "type": "function_call", "name": "edit_range",
        "arguments": json_dumps({
            "path": path, "start_line": start, "end_line": end,
            "expected_text": expected, "new_text": new, "expected_digest": digest,
        }),
    }


def test_edit_range_is_an_engineering_only_write_tool():
    assert TOOL_DEFS["edit_range"]["kind"] == "environment" and TOOL_DEFS["edit_range"]["action"] == "write"
    assert TOOL_DEFS["edit_range"]["departments"] == ("engineering",)
    assert "edit_range" in tools_for("engineering")
    assert "edit_range" not in tools_for("product")
    assert "edit_range" not in tools_for("quality")


def test_successful_edit_replaces_exactly_the_requested_span(tmp_path):
    workspace, environment = _environment(tmp_path)
    workspace.write_file("src/a.py", "HEADER = True\nVALUE = 1\nFOOTER = True\n")
    content_hash = _read_content_hash(environment, "src/a.py", 1, 3)
    result = perform(environment, "edit_range", {
        "path": "src/a.py", "start_line": 2, "end_line": 2,
        "expected_text": "VALUE = 1", "new_text": "VALUE = 2\nDOUBLED = True",
        "expected_digest": content_hash,
    })
    assert result.ok, result.error
    assert result.output["path"] == "src/a.py"
    assert (result.output["start_line"], result.output["end_line"]) == (2, 3)
    assert result.output["digest"] == workspace.digest()
    # 回执的新摘要与区间可直接复核
    reread = perform(environment, "read_range", {"path": "src/a.py", "start_line": 1})
    assert reread.ok, reread.error
    assert reread.output["digest"] == result.output["digest"]
    assert [entry["text"] for entry in reread.output["lines"]] == [
        "HEADER = True", "VALUE = 2", "DOUBLED = True", "FOOTER = True",
    ]
    assert workspace.read_file("src/a.py") == "HEADER = True\nVALUE = 2\nDOUBLED = True\nFOOTER = True\n"


def test_changed_file_since_read_is_rejected_without_modification(tmp_path):
    workspace, environment = _environment(tmp_path)
    workspace.write_file("src/a.py", "VALUE = 1\nTAIL = 1\n")
    stale_hash = _read_content_hash(environment, "src/a.py", 1, 2)
    before_bytes = (workspace.root / "src" / "a.py").read_bytes()
    before_digest = workspace.digest()
    # 文件已被他人改动：摘要与原文都不再对得上
    workspace.write_file("src/a.py", "VALUE = 9\nTAIL = 1\n")
    changed_digest = workspace.digest()
    changed_hash = _read_content_hash(environment, "src/a.py", 1, 2)
    assert changed_digest != before_digest
    rejected = perform(environment, "edit_range", {
        "path": "src/a.py", "start_line": 1, "end_line": 1,
        "expected_text": "VALUE = 1", "new_text": "VALUE = 2",
        "expected_digest": stale_hash,
    })
    assert rejected.ok is False
    assert "re-read" in (rejected.error or "")
    # 摘要对得上但原文写错同样拒绝
    wrong_text = perform(environment, "edit_range", {
        "path": "src/a.py", "start_line": 1, "end_line": 1,
        "expected_text": "VALUE = 1", "new_text": "VALUE = 2",
        "expected_digest": changed_hash,
    })
    assert wrong_text.ok is False
    assert "re-read" in (wrong_text.error or "")
    assert (workspace.root / "src" / "a.py").read_bytes() == before_bytes.replace(b"VALUE = 1", b"VALUE = 9")
    assert workspace.digest() == changed_digest


def test_ambiguous_expected_text_is_rejected_without_modification(tmp_path):
    workspace, environment = _environment(tmp_path)
    workspace.write_file("src/a.py", "VALUE = 1\nOTHER = 2\nVALUE = 1\n")
    content_hash = _read_content_hash(environment, "src/a.py", 1, 1)
    before_bytes = (workspace.root / "src" / "a.py").read_bytes()
    before_digest = workspace.digest()
    result = perform(environment, "edit_range", {
        "path": "src/a.py", "start_line": 1, "end_line": 1,
        "expected_text": "VALUE = 1", "new_text": "VALUE = 2",
        "expected_digest": content_hash,
    })
    assert result.ok is False
    assert "ambiguous" in (result.error or "")
    assert (workspace.root / "src" / "a.py").read_bytes() == before_bytes
    assert workspace.digest() == before_digest


@pytest.mark.parametrize("path,start,end", [
    ("src/missing.py", 1, 1),
    ("src/a.py", 5, 5),
    ("src/a.py", 2, 4),
    ("src", 1, 1),
])
def test_missing_target_is_rejected_without_modification(tmp_path, path, start, end):
    workspace, environment = _environment(tmp_path)
    workspace.write_file("src/a.py", "ONE = 1\nTWO = 2\n")
    before_digest = workspace.digest()
    before_files = workspace.list_files()
    result = perform(environment, "edit_range", {
        "path": path, "start_line": start, "end_line": end,
        "expected_text": "ONE = 1", "new_text": "ONE = 9",
    })
    assert result.ok is False
    assert result.error
    assert workspace.digest() == before_digest
    assert workspace.list_files() == before_files


def test_encoding_difference_is_rejected_without_modification(tmp_path):
    workspace, environment = _environment(tmp_path)
    raw_path = workspace.root / "src" / "bin.py"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(b"VALUE = \xff\xfe\n")
    before_bytes = raw_path.read_bytes()
    binary = perform(environment, "edit_range", {
        "path": "src/bin.py", "start_line": 1, "end_line": 1,
        "expected_text": "VALUE = x", "new_text": "VALUE = y",
    })
    assert binary.ok is False
    assert "encoding" in (binary.error or "").lower()
    workspace.write_file("src/a.py", "VALUE = 1\n")
    surrogate = perform(environment, "edit_range", {
        "path": "src/a.py", "start_line": 1, "end_line": 1,
        "expected_text": "VALUE = 1", "new_text": "VALUE = \ud800",
    })
    assert surrogate.ok is False
    assert "encoding" in (surrogate.error or "").lower()
    assert raw_path.read_bytes() == before_bytes
    assert workspace.read_file("src/a.py") == "VALUE = 1\n"


@pytest.mark.parametrize("rel", [
    ".checks/receipts.jsonl",
    ".git/HEAD",
    "../outside.txt",
    "bad?name",
    "file.",
])
def test_unsafe_paths_are_rejected_without_modification(tmp_path, rel):
    workspace, environment = _environment(tmp_path)
    workspace.write_file("ok.txt", "needle\n")
    before_digest = workspace.digest()
    result = perform(environment, "edit_range", {
        "path": rel, "start_line": 1, "end_line": 1,
        "expected_text": "needle", "new_text": "changed",
    })
    assert result.ok is False
    assert result.error
    assert workspace.read_file("ok.txt") == "needle\n"
    assert workspace.digest() == before_digest


def test_symlink_is_rejected_without_modification(tmp_path):
    workspace, environment = _environment(tmp_path / "workspace")
    workspace.write_file("real.txt", "VALUE = 1\n")
    outside = tmp_path / "outside.txt"
    outside.write_text("VALUE = 9\n", encoding="utf-8")
    before_digest = workspace.digest()
    link = workspace.root / "linked.txt"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("symbolic links are unavailable")
    result = perform(environment, "edit_range", {
        "path": "linked.txt", "start_line": 1, "end_line": 1,
        "expected_text": "VALUE = 9", "new_text": "VALUE = 2",
    })
    assert result.ok is False
    assert "Links and reparse points are not supported" in (result.error or "")
    assert outside.read_text(encoding="utf-8") == "VALUE = 9\n"
    assert link.is_symlink() and link.resolve() == outside.resolve()
    assert workspace.read_file("real.txt") == "VALUE = 1\n"
    # 公开树不表示链接，工作区含链接时没有摘要；移除链接后其余公开字节与编辑前一致
    link.unlink()
    assert workspace.digest() == before_digest


def test_link_made_by_a_command_during_a_run_is_refused_as_a_tool_result(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("VALUE = 9\n", encoding="utf-8")
    try:
        os.symlink(outside, tmp_path / "link-probe")
    except OSError:
        pytest.skip("symbolic links are unavailable")

    def link_then_edit(request):
        return ModelResponse(output=[
            {"id": "cmd-link", "call_id": "cmd-link", "type": "function_call", "name": "run_command",
             "arguments": json_dumps({"name": "make-link"})},
            _edit_call("edit-link", "src/linked.txt", 1, 1, "VALUE = 9", "VALUE = 2", None),
        ])

    system = LoopSystem.for_testing(tmp_path / "data", FakeAdapter([product_spec(), plan_turn(), link_then_edit]))
    registry = {"make-link": {"argv": ["python", "make_link.py"], "args": [], "timeout_sec": 30, "output_limit": 4000}}
    run_id = system.create_run("Edit a file that a command turned into a link",
                               registered_commands=registry, command_versions={"make-link": 1})
    workspace = system.workspace(run_id)
    workspace.write_file("make_link.py", (
        "import os\n"
        "os.makedirs('src', exist_ok=True)\n"
        f"os.symlink({str(outside)!r}, 'src/linked.txt')\n"
    ))
    for _ in range(3):
        system.activate_once(run_id)
    events = system.store.list_events(run_id)
    command = next(event for event in events
                   if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "run_command")
    command_output = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**command.payload["output_ref"])))
    assert command.payload["ok"] is True and command_output["exit_code"] == 0, command_output
    link = workspace.root / "src" / "linked.txt"
    assert link.is_symlink() and link.resolve() == outside.resolve()
    # 工具许可阶段拒绝：编辑没有开始执行，拒绝原因作为该调用的工具结果交回部门
    assert not any(event.type == EventType.TOOL_STARTED and event.payload.get("name") == "edit_range"
                   for event in events)
    edit = next(event for event in events
                if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "edit_range")
    assert edit.payload["ok"] is False
    assert "Links and reparse points are not supported" in edit.payload["error"]
    assert edit.payload["input_item"]["call_id"] == "edit-link"
    assert json.loads(edit.payload["input_item"]["output"]) == {
        "ok": False, "output": None, "error": edit.payload["error"],
    }
    assert outside.read_text(encoding="utf-8") == "VALUE = 9\n"


def test_two_edits_in_one_activation_produce_a_complete_delivery_tree(tmp_path):
    adapter = FakeAdapter([product_spec(), plan_turn(scope=["src/"])])
    system = LoopSystem.for_testing(tmp_path, adapter)

    def work_turn(request):
        environment = LocalEnvironment(system.workspace(request.run_id))
        return ModelResponse(output=[
            _edit_call("edit-a", "src/a.py", 2, 2, "VALUE = 1", "VALUE = 2",
                       _read_content_hash(environment, "src/a.py", 2, 2)),
            _edit_call("edit-b", "src/b.py", 1, 1, "GREETING = 'hi'", "GREETING = 'hello'",
                       _read_content_hash(environment, "src/b.py", 1, 1)),
        ])

    adapter.script.extend([work_turn, FakeTurn(
        proposal=delivery("two range edits", files=["src/a.py", "src/b.py"], check_names=["smoke"]),
        checks={"smoke": 0},
    )])
    run_id = system.create_run("Apply two range edits")
    system.activate_once(run_id)
    system.activate_once(run_id)
    workspace = system.workspace(run_id)
    workspace.write_file("src/a.py", "HEADER = True\nVALUE = 1\nFOOTER = True\n")
    workspace.write_file("src/b.py", "GREETING = 'hi'\n")
    workspace.write_file("src/keep.py", "KEPT = True\n")
    system.activate_once(run_id)
    result = system.activate_once(run_id)
    assert result.delivery_spec is not None, result.error
    events = system.store.list_events(run_id)
    edits = [event for event in events
             if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "edit_range"]
    assert len(edits) == 2 and all(event.payload["ok"] for event in edits)
    # 交付保存的是完整代码树，不只是改动的文件
    tree = load_tree(system.artifacts, run_id, result.delivery_spec.tree_ref)
    assert tree.digest == result.delivery_spec.code_tree_digest == workspace.digest()
    assert {item.path for item in tree.files} == {"src/a.py", "src/b.py", "src/keep.py"}
    assert workspace.read_file("src/a.py") == "HEADER = True\nVALUE = 2\nFOOTER = True\n"
    assert workspace.read_file("src/b.py") == "GREETING = 'hello'\n"
    assert workspace.read_file("src/keep.py") == "KEPT = True\n"
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_stale_pass_verdict_cannot_be_reused_after_tree_changes(tmp_path):
    workspace, environment = _environment(tmp_path)
    workspace.write_file("app.py", "print('ok')\n")
    workspace.write_file("check.py", "raise SystemExit(0)\n")
    passed = perform(environment, "run_check", {"name": "smoke", "argv": ["python", "check.py"]})
    assert passed.ok and passed.output["exit_code"] == 0, passed.error
    assert workspace.snapshot().facts.latest_check("engineering", "smoke") is not None
    content_hash = _read_content_hash(environment, "app.py", 1, 1)
    edited = perform(environment, "edit_range", {
        "path": "app.py", "start_line": 1, "end_line": 1,
        "expected_text": "print('ok')", "new_text": "print('changed')",
        "expected_digest": content_hash,
    })
    assert edited.ok, edited.error
    # 树已变，绑定旧树的通过结论不能沿用
    assert workspace.snapshot().facts.latest_check("engineering", "smoke") is None


def test_mutated_check_copy_does_not_become_the_tested_delivery(tmp_path):
    workspace, environment = _environment(tmp_path)
    workspace.write_file("app.py", "BROKEN = True\n")
    workspace.write_file(
        "fix.py",
        "from pathlib import Path\n"
        "p = Path('app.py')\n"
        "p.write_text('FIXED = True\\n')\n"
        "assert 'FIXED' in p.read_text()\n",
    )
    original = workspace.digest()
    result = perform(environment, "run_check", {"name": "smoke", "argv": ["python", "fix.py"]})
    assert result.ok is True
    assert result.output["exit_code"] == 0
    assert result.output["tree_changed"] is True
    assert result.output["snapshot_hash"] != original
    assert workspace.read_file("app.py") == "BROKEN = True\n"
    assert workspace.digest() == original
    assert "hacked.txt" not in workspace.list_files()
    assert workspace.snapshot().facts.latest_check("engineering", "smoke") is None


def test_changed_tree_after_delivery_rejects_the_stale_release(tmp_path):
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([
        product_spec(), plan_turn(), delivery_turn(),
        FakeTurn(proposal=review("release", "stale verdict on the old tree")),
    ]))
    run_id = system.create_run("echo")
    for _ in range(3):
        system.activate_once(run_id)
    assert system.project(run_id).delivery_spec is not None
    accepted_digest = system.project(run_id).delivery_spec.code_tree_digest
    workspace = system.workspace(run_id)
    environment = LocalEnvironment(workspace)
    content_hash = _read_content_hash(environment, "src/echo.py", 2, 2)
    edited = perform(environment, "edit_range", {
        "path": "src/echo.py", "start_line": 2, "end_line": 2,
        "expected_text": "print(sys.argv[1])", "new_text": "print(sys.argv[1].upper())",
        "expected_digest": content_hash,
    })
    assert edited.ok, edited.error
    assert workspace.digest() != accepted_digest
    result = system.activate_once(run_id)
    assert result.phase == "QUALITY", result.error
    assert result.last_review is None
    events = system.store.list_events(run_id)
    assert not any(event.type in {EventType.QA_SUBMITTED, EventType.RUN_DONE} for event in events)
    rejected = [event for event in events if event.type == EventType.PROPOSAL_REJECTED]
    assert rejected
    assert result.canonical_state() == system.replay(run_id).canonical_state()


def test_adopted_baseline_applies_to_next_work_item_and_replay_verifies(data_dir):
    adapter = FakeAdapter([
        product_spec(), plan_turn(), delivery_turn(summary="v1"), review_turn("release", "ok v1"),
    ])
    system = LoopSystem.for_testing(data_dir, adapter)
    project_id = system.projects.register("Echo", "做一个可以长期演进的逐行文本处理工具。")

    def second_work(request):
        environment = LocalEnvironment(system.workspace(request.run_id))
        return ModelResponse(output=[
            _edit_call("edit-v2", "src/echo.py", 2, 2,
                       "print(sys.argv[1])", "print(sys.argv[1].upper())",
                       _read_content_hash(environment, "src/echo.py", 2, 2)),
        ])

    adapter.script.extend([
        product_spec(), plan_turn(), second_work,
        FakeTurn(
            proposal=delivery("v2", files=["src/echo.py"], check_names=["smoke"]),
            checks={"smoke": 0},
        ),
        review_turn("release", "ok v2"),
    ])
    _work_item_1, run_1 = system.projects.start_work_item(project_id, "第一步：echo CLI")
    assert system.run_until_stop(run_1).phase == "DONE"
    assert system.projects.settle(run_1).type == ProjectEventType.DELIVERABLE_ADOPTED
    first_adoption = system.projects.projection(project_id).current_adoption
    _work_item_2, run_2 = system.projects.start_work_item(project_id, "第二步：输出大写")
    # 新事项继承已采纳基线
    assert system.project(run_2).baseline["adoption_id"] == first_adoption.adoption_id
    assert system.project(run_2).workspace_digest == first_adoption.code_tree_digest
    assert capture_public_tree(system.workspace(run_2).root).digest == first_adoption.code_tree_digest
    assert system.run_until_stop(run_2).phase == "DONE"
    assert system.projects.settle(run_2).type == ProjectEventType.DELIVERABLE_ADOPTED
    project = system.projects.projection(project_id)
    assert project.current_adoption.run_id == run_2
    assert project.current_adoption.previous_adoption_id == first_adoption.adoption_id
    assert project.current_adoption.code_tree_digest != first_adoption.code_tree_digest
    assert project.current_adoption.code_tree_digest == system.workspace(run_2).digest()
    archived = load_tree(system.artifacts, run_2, ArtifactRef(**project.current_adoption.tree_ref))
    archived_text = next(item.data for item in archived.files if item.path == "src/echo.py")
    assert archived_text.replace(b"\r\n", b"\n") == b"import sys\nprint(sys.argv[1].upper())\n"
    assert system.replay(run_2).canonical_state() == system.project(run_2).canonical_state()
