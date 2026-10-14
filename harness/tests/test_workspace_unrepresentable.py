# 工单 #104 的验收：公开树按项目的忽略规则取得，工作区出现无法表示的条目时暂停。
# 测试从 LoopSystem 整体驱动，使用真实的文件系统、真实的 Git 与真实的 bash 命令进程；FakeAdapter 只给出模型的回答。

import asyncio
import json
import os
import sys

import pytest

from harness.actions import Action
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.models import ArtifactRef, EventType, json_dumps
from harness.proposals import delivery, delivery_turn, product_spec, review_turn
from harness.public_tree import capture_public_tree
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.tools import tool_action
from harness.tree_archive import load_tree

REGISTRY = {"make-link": {"argv": ["python", "make_link.py"], "args": ["nested", "linked"],
                          "timeout_sec": 30, "output_limit": 4000}}

def _system(tmp_path, turns):
    return LoopSystem.for_testing(tmp_path / "data", FakeAdapter([product_spec(),*turns]))

def _write_command_body(workspace, outside):
    # bash 命令调用的脚本：在 node_modules 下建立指向工作区之外的目录链接
    workspace.write_file("make_link.py", (
        "import os, sys\n"
        "os.makedirs('node_modules', exist_ok=True)\n"
        f"os.symlink({str(outside)!r}, os.path.join('node_modules', sys.argv[1]))\n"
    ))

def _command_call(identity, name="make-link", args=None):
    # bash 的 cwd 是工作区根，命令串里直接带上脚本参数；登记命令进程已随 run_command 删除（工单 #484），
    # 这里证明的是同一件事：主机执行的命令在工作区里留下无法表示的链接以后 run 暂停
    argument = (args or ["nested"])[0]
    command = f'"{sys.executable.replace(chr(92), "/")}" make_link.py {argument}'
    return {"id": identity, "call_id": identity, "type": "function_call", "name": "bash",
            "arguments": json_dumps({"command": command})}

def _called(events, name):
    return [event for event in events
            if event.type == EventType.TOOL_CALLED and event.payload.get("name") == name]

def _paused(events):
    return next((event for event in events if event.type == EventType.RUN_PAUSED), None)

def _stop_message(events):
    # 停止说明：run_paused 载荷中的 message（D09：停止说明列出相对路径）
    pause = _paused(events)
    return "" if pause is None else pause.payload.get("message", "")

def _perform(environment, name, args, *, department="engineering"):
    receipt = asyncio.run(environment.perform(Action(
        action_id=f"probe:{name}:{json_dumps(args)}", kind=tool_action(name), tool=name,
        department=department, input=args)))
    return receipt

def _workspace_and_command(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        os.symlink(outside, tmp_path / "link-probe")
    except OSError:
        pytest.skip("symbolic links are unavailable")
    system = _system(tmp_path, [])
    run_id = system.create_run("probe", registered_commands=REGISTRY, command_versions={"make-link": 1})
    workspace = system.workspace(run_id)
    workspace.write_file(".gitignore", "node_modules/\n")
    _write_command_body(workspace, outside)
    return system, run_id, workspace

def test_ignored_link_does_not_pause_and_never_enters_snapshot_seal_or_delivery(tmp_path):
    def work(request):
        return ModelResponse(output=[_command_call("cmd-link", "make-link", ["nested"])])
    # delivery_turn 按请求里的当前 ProductSpec 填依据版本（工单 #471）：FakeTurn 是脚本项而不是实例
    system = _system(tmp_path, [work, delivery_turn(
        summary="with ignored dependency link", files={"src/echo.py": "import sys\nprint(sys.argv[1])\n"},
        checks={"smoke": 0}), review_turn("release", "ok")])
    run_id = system.create_run("Dependencies with links do not affect the public tree",
                               registered_commands=REGISTRY, command_versions={"make-link": 1})
    workspace = system.workspace(run_id)
    workspace.write_file(".gitignore", "node_modules/\n")
    _write_command_body(workspace, tmp_path / "outside.txt")
    (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")
    assert system.run_until_stop(run_id).phase == "DONE"
    events = system.store.list_events(run_id)
    assert _paused(events) is None
    # 快照、封存与交付都不包含 node_modules
    tree = capture_public_tree(workspace.root, True)
    assert not any(item.path.startswith("node_modules") for item in tree.files)
    assert not any(path.startswith("node_modules") for path in tree.directories)
    delivery_spec = system.project(run_id).delivery_spec
    sealed = load_tree(system.artifacts, run_id, delivery_spec.tree_ref)
    assert not any(item.path.startswith("node_modules") for item in sealed.files)
    # 目录与搜索工具看不到它：list_files 没有任何 node_modules 路径，搜索它没有任何命中
    environment = system.environment(run_id)
    assert not any(path.startswith("node_modules") for path in environment.workspace.list_files())
    seen = _perform(environment, "search", {"pattern": "secret", "path": "node_modules"})
    assert seen.ok is True
    assert seen.output["matches"] == [] and seen.output["total_matches"] == 0
    reading = _perform(environment, "read_file", {"path": "node_modules/nested"})
    assert reading.ok is False

def test_link_outside_ignored_paths_pauses_after_the_command_receipt(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("VALUE = 9\n", encoding="utf-8")
    try:
        os.symlink(outside, tmp_path / "link-probe")
    except OSError:
        pytest.skip("symbolic links are unavailable")

    def link_and_then(request):
        return ModelResponse(output=[
            _command_call("cmd-link", "make-link", ["linked"]),
            {"id": "read-after", "call_id": "read-after", "type": "function_call", "name": "read_file",
             "arguments": json_dumps({"path": "make_link.py"})},
        ])

    system = _system(tmp_path, [link_and_then])
    run_id = system.create_run("A link outside ignore rules pauses the run",
                               registered_commands=REGISTRY, command_versions={"make-link": 1})
    workspace = system.workspace(run_id)
    _write_command_body(workspace, outside)
    system.run_until_stop(run_id)
    events = system.store.list_events(run_id)
    # 回执照常记录
    commands = _called(events, "bash")
    assert len(commands) == 1 and commands[0].payload["ok"] is True
    # 然后暂停，停止说明写链接在工作区内的相对路径
    pause = _paused(events)
    assert pause is not None and pause.payload["stop_reason"] == "workspace_unrepresentable"
    assert "node_modules/linked" in _stop_message(events)
    # 模型可见的回执与停止说明不含主机绝对路径
    assert str(tmp_path) not in _stop_message(events)
    assert str(tmp_path) not in json_dumps(commands[0].payload)

def test_link_during_request_assembly_pauses_with_the_same_reason(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    try:
        os.symlink(outside, tmp_path / "link-probe")
    except OSError:
        pytest.skip("symbolic links are unavailable")

    system = _system(tmp_path, [])
    run_id = system.create_run("A link during request assembly pauses the run",
                               registered_commands=REGISTRY, command_versions={"make-link": 1})
    workspace = system.workspace(run_id)
    # 在第一步的请求装配之前建立链接
    os.symlink(outside, workspace.root / "linked.txt")
    system.run_until_stop(run_id)
    events = system.store.list_events(run_id)
    pause = _paused(events)
    assert pause is not None and pause.payload["stop_reason"] == "workspace_unrepresentable"
    assert "linked.txt" in _stop_message(events)

def test_link_at_proposal_commit_pauses_with_the_same_reason(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    try:
        os.symlink(outside, tmp_path / "link-probe")
    except OSError:
        pytest.skip("symbolic links are unavailable")

    system = _system(tmp_path, [delivery_turn(
        summary="submit and pause", files={"src/echo.py": "import sys\nprint(sys.argv[1])\n"},
        checks={"smoke": 0})])
    run_id = system.create_run("A link at proposal commit pauses the run",
                               registered_commands=REGISTRY, command_versions={"make-link": 1})
    workspace = system.workspace(run_id)
    # 提案提交（提交判断读取工作区事实、交付封存取得公开树）时建立链接
    from harness.tests.helpers import after_event
    planted = []
    def plant(event):
        if not planted:
            planted.append(True)
            os.symlink(outside, workspace.root / "committed-link.txt")
    after_event(system, EventType.PROPOSAL_SUBMITTED, plant)
    system.run_until_stop(run_id)
    events = system.store.list_events(run_id)
    pause = _paused(events)
    assert pause is not None and pause.payload["stop_reason"] == "workspace_unrepresentable"
    assert "committed-link.txt" in _stop_message(events)

def test_write_to_an_ignored_path_is_refused_with_the_ignore_rule_reason(tmp_path):
    try:
        os.symlink(tmp_path / "nowhere", tmp_path / "link-probe")
    except OSError:
        pytest.skip("symbolic links are unavailable")
    system = _system(tmp_path, [])
    run_id = system.create_run("Ignored paths refuse writes", registered_commands=REGISTRY,
                               command_versions={"make-link": 1})
    workspace = system.workspace(run_id)
    workspace.write_file(".gitignore", "node_modules/\n")
    environment = system.environment(run_id)
    receipt = _perform(environment, "write_file",
                       {"path": "node_modules/pkg/inside.txt", "content": "x"})
    assert receipt.ok is False
    assert "Excluded by the project's ignore rules" in (receipt.error or "")
    assert not os.path.lexists(workspace.root / "node_modules")
    assert str(workspace.root) not in (receipt.error or "")

def test_read_of_an_ignored_regular_file_is_refused_with_the_ignore_rule_reason(tmp_path):
    try:
        os.symlink(tmp_path / "nowhere", tmp_path / "link-probe")
    except OSError:
        pytest.skip("symbolic links are unavailable")
    system = _system(tmp_path, [])
    run_id = system.create_run("Ignored paths refuse reads", registered_commands=REGISTRY,
                               command_versions={"make-link": 1})
    workspace = system.workspace(run_id)
    workspace.write_file(".gitignore", "node_modules/\n")
    (workspace.root / "node_modules").mkdir()
    (workspace.root / "node_modules" / "dep.js").write_text("const dep = 1;\n", encoding="utf-8")
    environment = system.environment(run_id)
    # 常规文件按路径阅读同样被拒绝，原因写明被忽略规则排除并使用相对路径
    reading = _perform(environment, "read_file", {"path": "node_modules/dep.js"})
    assert reading.ok is False
    assert "Excluded by the project's ignore rules" in (reading.error or "")
    assert "node_modules/dep.js" in (reading.error or "")
    assert str(workspace.root) not in (reading.error or "")
    # read_range 走同一个判断
    ranged = _perform(environment, "read_range",
                      {"path": "node_modules/dep.js", "start_line": 1, "end_line": 1})
    assert ranged.ok is False
    assert "Excluded by the project's ignore rules" in (ranged.error or "")
    assert "node_modules/dep.js" in (ranged.error or "")
    assert str(workspace.root) not in (ranged.error or "")
    # 未被忽略的常规文件仍可阅读
    normal = _perform(environment, "read_file", {"path": ".gitignore"})
    assert normal.ok is True and normal.output == "node_modules/\n"

def test_delivery_adoption_tree_excludes_ignored_directories(tmp_path):
    try:
        os.symlink(tmp_path / "nowhere", tmp_path / "link-probe")
    except OSError:
        pytest.skip("symbolic links are unavailable")
    system = _system(tmp_path, [delivery_turn(summary="adopt", files={"src/echo.py": "print('x')\n"}),
                                 review_turn("release", "ok")])
    run_id = system.create_run("Adoption excludes ignored directories", registered_commands=REGISTRY,
                               command_versions={"make-link": 1})
    workspace = system.workspace(run_id)
    workspace.write_file(".gitignore", "node_modules/\n")
    (workspace.root / "node_modules").mkdir()
    (workspace.root / "node_modules" / "dep.js").write_text("// dependency\n", encoding="utf-8")
    (workspace.root / "src").mkdir()
    (workspace.root / "src" / "echo.py").write_text("print('x')\n", encoding="utf-8")
    assert system.run_until_stop(run_id).phase == "DONE"
    tree = capture_public_tree(workspace.root, True)
    assert [item.path for item in tree.files] == [".gitignore", "src/echo.py"]
