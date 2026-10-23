import json
import os

import pytest

from harness.collaboration import has_new_work
from harness.providers.call import ModelResponse
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.models import ArtifactRef, EventType, ProjectEventType, json_dumps
from harness.proposals import (delivery_turn, product_spec,
                               review, review_turn)
from harness.public_tree import capture_public_tree
from harness.environment import LocalEnvironment
from harness.runtime import LoopSystem
from harness.tests.helpers import perform
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

def test_ambiguous_expected_text_is_rejected_without_a_matching_start_line(tmp_path):
    # 工单 #719：原文出现多次时用 start_line 消歧；没有这样的一处就拒绝，并写明匹配了几次
    workspace, environment = _environment(tmp_path)
    workspace.write_file("src/a.py", "VALUE = 1\nOTHER = 2\nVALUE = 1\n")
    content_hash = _read_content_hash(environment, "src/a.py", 1, 1)
    before_bytes = (workspace.root / "src" / "a.py").read_bytes()
    before_digest = workspace.digest()
    # 不给 start_line：无法消歧
    result = perform(environment, "edit_range", {
        "path": "src/a.py",
        "expected_text": "VALUE = 1", "new_text": "VALUE = 2",
        "expected_digest": content_hash,
    })
    assert result.ok is False
    assert "ambiguous" in (result.error or "")
    assert "2 times" in (result.error or "")
    assert (workspace.root / "src" / "a.py").read_bytes() == before_bytes
    assert workspace.digest() == before_digest
    # start_line 指到没有匹配的那一行：同样拒绝
    wrong_line = perform(environment, "edit_range", {
        "path": "src/a.py", "start_line": 2, "end_line": 2,
        "expected_text": "VALUE = 1", "new_text": "VALUE = 2",
        "expected_digest": content_hash,
    })
    assert wrong_line.ok is False
    assert "ambiguous" in (wrong_line.error or "")
    assert (workspace.root / "src" / "a.py").read_bytes() == before_bytes
    assert workspace.digest() == before_digest


def test_ambiguous_expected_text_is_chosen_by_start_line(tmp_path):
    # 工单 #719：原文出现多次时，起点落在 start_line 的那一处被选中
    workspace, environment = _environment(tmp_path)
    workspace.write_file("src/a.py", "VALUE = 1\nOTHER = 2\nVALUE = 1\n")
    content_hash = _read_content_hash(environment, "src/a.py", 1, 1)
    result = perform(environment, "edit_range", {
        "path": "src/a.py", "start_line": 3, "end_line": 3,
        "expected_text": "VALUE = 1", "new_text": "VALUE = 3",
        "expected_digest": content_hash,
    })
    assert result.ok, result.error
    assert result.output["start_line"] == 3
    assert workspace.read_file("src/a.py") == "VALUE = 1\nOTHER = 2\nVALUE = 3\n"


def test_a_unique_text_is_edited_after_the_lines_above_it_moved(tmp_path):
    # 工单 #719：原文唯一时按原文定位，行号可以过期——文件上半部分改过以后下半部分的行号往后挪了，
    # 旧行号定位会把这次编辑拒掉
    workspace, environment = _environment(tmp_path)
    workspace.write_file("src/a.py", "HEADER = True\nVALUE = 1\nTAIL = 1\n")
    first = perform(environment, "edit_range", {
        "path": "src/a.py", "start_line": 1, "end_line": 1,
        "expected_text": "HEADER = True", "new_text": "HEADER = True\nEXTRA = 1",
    })
    assert first.ok, first.error
    # 仍按之前读到的行号编辑下半部分：原文唯一，仍然成功，落点跟着原文走
    second = perform(environment, "edit_range", {
        "path": "src/a.py", "start_line": 3, "end_line": 3,
        "expected_text": "TAIL = 1", "new_text": "TAIL = 2",
    })
    assert second.ok, second.error
    assert second.output["start_line"] == 4
    assert workspace.read_file("src/a.py") == "HEADER = True\nEXTRA = 1\nVALUE = 1\nTAIL = 2\n"

@pytest.mark.parametrize("path,start,end", [
    ("src/missing.py", 1, 1),
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


def test_a_span_that_does_not_exist_is_located_by_the_text_instead(tmp_path):
    # 工单 #719：行号指向不存在的地方不再拒绝——原文唯一时按原文定位
    workspace, environment = _environment(tmp_path)
    workspace.write_file("src/a.py", "ONE = 1\nTWO = 2\n")
    result = perform(environment, "edit_range", {
        "path": "src/a.py", "start_line": 5, "end_line": 5,
        "expected_text": "ONE = 1", "new_text": "ONE = 9",
    })
    assert result.ok, result.error
    assert result.output["start_line"] == 1
    assert workspace.read_file("src/a.py") == "ONE = 9\nTWO = 2\n"

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
            {"id": "cmd-link", "call_id": "cmd-link", "type": "function_call", "name": "bash",
             "arguments": json_dumps({"command": "python make_link.py"})},
            _edit_call("edit-link", "src/linked.txt", 1, 1, "VALUE = 9", "VALUE = 2", None),
        ])

    system = LoopSystem.for_testing(tmp_path / "data", FakeAdapter([product_spec(),link_then_edit]))
    run_id = system.create_run("Edit a file that a command turned into a link")
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
                   if event.type == EventType.TOOL_CALLED and event.payload.get("name") == "bash")
    command_output = json.loads(system.artifacts.get_for_run(run_id, ArtifactRef(**command.payload["output_ref"])))
    assert command.payload["ok"] is True and command_output["exit_code"] == 0, command_output
    # bash 命令留下链接：命令的回执照常记录，主机随即核对公开树，运行以 workspace_unrepresentable 暂停，
    # 停止说明写这个链接在工作区内的相对路径；同一回答中的其余调用不执行
    pause = next(event for event in events if event.type == EventType.RUN_PAUSED)
    assert pause.payload["stop_reason"] == "workspace_unrepresentable"
    assert "src/linked.txt" in pause.payload["human_action"] or "src/linked.txt" in str(pause.payload)
    assert not any(event.type == EventType.TOOL_STARTED and event.payload.get("name") == "edit_range"
                   for event in events)
    assert not any(event.type == EventType.TOOL_CALLED and event.payload.get("name") == "edit_range"
                   for event in events)
    link = workspace.root / "src" / "linked.txt"
    assert link.is_symlink() and link.resolve() == outside.resolve()
    assert outside.read_text(encoding="utf-8") == "VALUE = 9\n"

def test_two_edits_in_one_activation_produce_a_complete_delivery_tree(tmp_path):
    adapter = FakeAdapter([product_spec(),])
    system = LoopSystem.for_testing(tmp_path, adapter)

    def work_turn(request):
        environment = LocalEnvironment(system.workspace(request.run_id))
        return ModelResponse(output=[
            _edit_call("edit-a", "src/a.py", 2, 2, "VALUE = 1", "VALUE = 2",
                       _read_content_hash(environment, "src/a.py", 2, 2)),
            _edit_call("edit-b", "src/b.py", 1, 1, "GREETING = 'hi'", "GREETING = 'hello'",
                       _read_content_hash(environment, "src/b.py", 1, 1)),
        ])

    # delivery_turn 按请求里的当前 ProductSpec 填依据版本（工单 #471）：脚本项是工厂而不是 FakeTurn 实例
    adapter.script.extend([work_turn, delivery_turn(
        summary="two range edits",
        files={"src/a.py": "HEADER = True\nVALUE = 2\nFOOTER = True\n",
               "src/b.py": "GREETING = 'hello'\n", "src/keep.py": "KEPT = True\n"},
        checks={"smoke": 0},
    )])
    run_id = system.create_run("Apply two range edits")
    # #470 删除工程计划以后，第二次激活就是工程写入轮次：文件要先存在，区间编辑才改得动
    workspace = system.workspace(run_id)
    workspace.write_file("src/a.py", "HEADER = True\nVALUE = 1\nFOOTER = True\n")
    workspace.write_file("src/b.py", "GREETING = 'hi'\n")
    workspace.write_file("src/keep.py", "KEPT = True\n")
    system.activate_once(run_id)
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
    passed = perform(environment, "run_check", {"name": "smoke", "command": "python check.py"})
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
    result = perform(environment, "run_check", {"name": "smoke", "command": "python fix.py"})
    assert result.ok is True
    assert result.output["exit_code"] == 0
    assert result.output["tree_changed"] is True
    assert result.output["snapshot_hash"] != original
    assert workspace.read_file("app.py") == "BROKEN = True\n"
    assert workspace.digest() == original
    assert "hacked.txt" not in workspace.list_files()
    assert workspace.snapshot().facts.latest_check("engineering", "smoke") is None

def test_changed_tree_after_delivery_rejects_the_stale_release(tmp_path):
    # 质检在交付 A 上退回一次重交付：工程重新封存交付 B 以后，质检带着依据旧交付 A 的放行结论
    # 与这一次激活里重新跑过的检查提交。检查证据绑的是新快照，依据版本绑的是旧交付，
    # #481 之后质检的检查工作区每次激活从最新封存交付建立，运行工作区的改动不影响这次判断
    def stale_release(call):
        # 质检这一步面对的是新封存的交付，放行结论却声明依据退回前的那份旧交付
        return FakeTurn(
            proposal=review("release", "stale verdict on the old tree", checks=["smoke"],
                            basis_delivery_spec_hash=original),
            checks={"smoke": 0},
        )

    adapter = FakeAdapter([
        product_spec(),
        delivery_turn(),
        review_turn("rework_engineering", "The implementation does not match the requirement.",
                    defects=[{"severity": "minor", "summary": "needs revision"}]),
        delivery_turn("revised echo", files={"src/echo.py": "import sys\nprint(str(sys.argv[1]))\n"}),
        stale_release,
    ])

    system = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system.create_run("echo", max_cycles=12)
    for _ in range(2):
        pending = system.activate_once(run_id)
    assert has_new_work(pending, "quality")
    original = pending.delivery_spec.content_hash
    original_digest = pending.delivery_spec.code_tree_digest
    rework = system.activate_once(run_id)
    assert has_new_work(rework, "engineering")
    delivered = system.activate_once(run_id)
    # 新的交付让质检开始一轮工作（工单 #556：质检关注新的交付）
    assert has_new_work(delivered, "quality")
    assert delivered.delivery_spec.content_hash != original
    assert delivered.delivery_spec.code_tree_digest != original_digest
    result = system.activate_once(run_id)
    assert has_new_work(result, "quality"), result.error
    assert result.last_review.verdict == "rework_engineering"
    errors = result.rejections[-1]["errors"]
    assert [error["field"] for error in errors] == ["basis_delivery_spec_hash"]
    assert f"submitted artifact is based on {original!r}" in errors[0]["message"]
    assert delivered.delivery_spec.content_hash in errors[0]["message"]
    # 拒绝的原因不是缺少检查：这一次激活里质检真实跑过 smoke，回执绑的是新交付快照
    assert not any(error["field"] == "checks" for error in errors)
    events = system.store.list_events(run_id)
    assert not any(event.type == EventType.RUN_DONE for event in events)
    assert not any(event.type == EventType.QA_SUBMITTED and event.payload.get("verdict") == "release" for event in events)
    rejected = [event for event in events if event.type == EventType.PROPOSAL_REJECTED]
    assert rejected
    assert result.canonical_state() == system.replay(run_id).canonical_state()

def test_adopted_baseline_applies_to_next_work_item_and_replay_verifies(data_dir):
    adapter = FakeAdapter([
        product_spec(),delivery_turn(summary="v1"), review_turn("release", "ok v1"),
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
        product_spec(),second_work,
        # delivery_turn 按请求里的当前 ProductSpec 填依据版本（工单 #471）：脚本项是工厂而不是 FakeTurn 实例
        delivery_turn(
            summary="v2", files={"src/echo.py": "import sys\nprint(sys.argv[1].upper())\n"},
            checks={"smoke": 0},
        ),
        review_turn("release", "ok v2"),
    ])
    _work_item_1, run_1 = system.projects.start_work_item(project_id, "第一步：echo CLI")
    assert system.run_until_stop(run_1).status == "done"
    assert system.projects.settle(run_1).type == ProjectEventType.DELIVERABLE_ADOPTED
    first_adoption = system.projects.projection(project_id).current_adoption
    _work_item_2, run_2 = system.projects.start_work_item(project_id, "第二步：输出大写")
    # 新事项继承已采纳基线
    assert system.project(run_2).baseline["adoption_id"] == first_adoption.adoption_id
    assert system.project(run_2).workspace_digest == first_adoption.code_tree_digest
    assert capture_public_tree(system.workspace(run_2).root).digest == first_adoption.code_tree_digest
    assert system.run_until_stop(run_2).status == "done"
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
