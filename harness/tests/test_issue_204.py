# 工单 #204 的验收：run 因模型连续不调用工具（no_tool_call）或者工作区出现无法表示的条目
# （workspace_unrepresentable）而暂停时发出决定请求，用户回答以后从暂停位置继续，或者停止事项。
# 测试从 LoopSystem 整体驱动，使用真实的文件系统、真实的 Git 与真实的 bash 命令进程；FakeAdapter 只给出模型的回答。

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.app.application import Application
from harness.app.decision_queries import DecisionsList
from harness.definitions import DEFINITIONS
from harness.event_store import Command
from harness.models import EventType, new_id
from harness.projection import saved_decisions
from harness.proposals import delivery_turn, judgement_turn, product_spec, review_turn
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.tests.helpers import TOOL_CALL_REQUIRED_LIMIT as LIMIT, explore_turn, quality_turns


def _events(system, run_id, event_type):
    return [event for event in system.store.list_events(run_id) if event.type == event_type]

def _open_decisions(system, run_id):
    # 按保存的投影列出这个 run 未回答的决定请求
    _position, decisions = saved_decisions(system.store, statuses=("open",))
    return [decision for decision in decisions if decision.run_id == run_id]

def _answer(system, decision, option):
    command = Command(new_id("cmd"), "decision.answer", f"sha256:{option}:{decision.version}", "user:local")
    return system.orchestrator.answer_decision(decision.decision_id, option, None,
                                               base_version=decision.version, command=command)

def _plain_reply():
    # 部门回复文字、没有调用工具；连续若干次以后主机要求调用工具，fake 回答仍不调用工具，run 以 no_tool_call 暂停
    return lambda _call: FakeTurn(transcript="先整理一下思路，稍后提交。")

def _completion_script():
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    return {
        "engineering": [delivery_turn()],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }

def _no_tool_call_run(tmp_path, tail=None):
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    script = {"product": [_plain_reply() for _ in range(LIMIT + 1)],
              "engineering": [], "quality": []}
    if tail is not None:
        for department, turns in tail.items():
            script[department] = script[department] + list(turns)
    system = LoopSystem.for_testing(tmp_path / "data", FakeAdapter(script))
    run_id = system.create_run("build echo")
    result = system.run_until_stop(run_id)
    return system, run_id, result

def test_pause_decision_is_listed_by_the_query_with_its_options(tmp_path):
    # 首页与项目页面的决定卡片据 decisions.list 显示选项：暂停请求经查询返回，选项与说明齐全
    system, run_id, _result = _no_tool_call_run(tmp_path)
    [decision] = _open_decisions(system, run_id)
    application = Application(system)
    listed = application.query("decisions.list", DecisionsList(status=["open"]))
    [view] = [item for item in listed.data.decisions if item.decision_id == decision.decision_id]
    assert (view.kind, view.blocks, view.run_id) == ("no_tool_call", "run", run_id)
    assert [option.id for option in view.request.options] == ["continue", "stop"]
    assert [option.label for option in view.request.options] == ["处理以后继续执行", "停止事项"]
    assert view.request.stop_reason == "no_tool_call"
    application.close()

def test_no_tool_call_without_handling_pauses_again_with_a_new_request(tmp_path):
    # 没有处理（模型仍不调用工具）就回答继续：从原位置继续以后再次暂停，并发出新的决定请求
    script = [_plain_reply() for _ in range(2 * (LIMIT + 1))]
    system = LoopSystem.for_testing(tmp_path / "data", FakeAdapter(script))
    run_id = system.create_run("build echo")
    assert system.run_until_stop(run_id).stop_reason == "no_tool_call"
    [first] = _open_decisions(system, run_id)
    assert _answer(system, first, "continue") == run_id
    result = system.run_until_stop(run_id)

    assert result.status == "paused" and result.stop_reason == "no_tool_call"
    opened = _open_decisions(system, run_id)
    assert len(opened) == 1, [decision.decision_id for decision in opened]
    assert opened[0].decision_id != first.decision_id
    assert len(_events(system, run_id, EventType.DECISION_REQUESTED)) == 2
    system.close()

def test_no_tool_call_stop_keeps_the_run_paused_with_the_same_reason(tmp_path):
    # 回答停止：事项停止，停止原因保持暂停时的原因
    system, run_id, _result = _no_tool_call_run(tmp_path)
    [decision] = _open_decisions(system, run_id)
    assert _answer(system, decision, "stop") is None
    projection = system.project(run_id)
    assert projection.status == "paused" and projection.stop_reason == "no_tool_call"
    # 停止以后没有继续事件，也没有新的决定请求
    assert _events(system, run_id, EventType.RUN_CONTINUED) == []
    assert _open_decisions(system, run_id) == []
    system.close()

def test_second_no_tool_call_pause_after_the_first_continue_is_a_fresh_count(tmp_path):
    # 继续以后连续不调用工具的计数从零开始：继续之后再连续 LIMIT 次仍不调用工具也不暂停，
    # 第 LIMIT+1 次换成提交产品要求并走完三部门
    script = {"product": [*[_plain_reply() for _ in range(LIMIT + 1)],
                        *[_plain_reply() for _ in range(LIMIT)], product_spec()],
              **_completion_script()}
    system = LoopSystem.for_testing(tmp_path / "data", FakeAdapter(script))
    run_id = system.create_run("build echo")
    assert system.run_until_stop(run_id).stop_reason == "no_tool_call"
    [first] = _open_decisions(system, run_id)
    assert _answer(system, first, "continue") == run_id
    finished = system.run_until_stop(run_id)

    # 继续以后的 LIMIT 次只回复文字没有触发暂停，第 LIMIT+1 次换成了提交产品要求
    assert finished.status == "done", (finished.status, finished.stop_reason)
    assert finished.stop_reason != "no_tool_call"
    system.close()


def _write_command_body(workspace, outside):
    # bash 命令调用的脚本：在 node_modules 下建立指向工作区之外的链接
    workspace.write_file("make_link.py", (
        "import os, sys\n"
        "os.makedirs('node_modules', exist_ok=True)\n"
        f"os.symlink({str(outside)!r}, os.path.join('node_modules', sys.argv[1]))\n"
    ))

def _command_call(identity, argument="nested"):
    # bash 的 cwd 是工作区根，命令串里直接带上脚本参数；登记命令进程已随 run_command 删除（工单 #484），
    # 这里证明的是同一件事：主机执行的命令在工作区里留下无法表示的链接以后 run 暂停
    command = f'"{sys.executable.replace(chr(92), "/")}" make_link.py {argument}'
    return {"id": identity, "call_id": identity, "type": "function_call", "name": "bash",
            "arguments": json.dumps({"command": command})}


def _short_data_dir(tmp_path):
    # 数据目录放在比 tmp_path 更短的路径下：忽略规则探测库建在检查工作区旁边，libgit2 在 Windows 上
    # 对这个仓库路径的长度上限约 190 个字符；运行机的 pytest 临时目录（popen-gw 加长用例名）会超过它
    return Path(tempfile.mkdtemp(prefix="d", dir=tmp_path.parent)) / "data"

def _workspace_unrepresentable_run(tmp_path, tail):
    outside = tmp_path / "outside.txt"
    outside.write_text("VALUE = 9\n", encoding="utf-8")
    try:
        os.symlink(outside, tmp_path / "link-probe")
    except OSError:
        pytest.skip("symbolic links are unavailable")

    def link_then(request):
        return ModelResponse(output=[_command_call("cmd-link", "linked")])

    # 产品先提交产品要求，工步建立链接（node_modules/linked）导致公开树无法表示
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）：
    # 质检在 PRD 被接纳以后与工程同时开始一轮工作，它的检查工作区来自事项开始时的项目起点
    # （不读运行工作区），这一轮与链接无关；交付到达以后质检开始新一轮，给出放行
    system = LoopSystem.for_testing(_short_data_dir(tmp_path), FakeAdapter({
        "product": [product_spec()],
        "engineering": [link_then, tail],
        "quality": [explore_turn(), judgement_turn(), review_turn("release", "checks passed on the current snapshot")],
    }))
    run_id = system.create_run("A link pauses the run")
    workspace = system.workspace(run_id)
    _write_command_body(workspace, outside)
    result = system.run_until_stop(run_id)
    return system, run_id, workspace, result

def test_workspace_unrepresentable_pause_requests_a_decision_with_the_paths(tmp_path):
    system, run_id, workspace, result = _workspace_unrepresentable_run(tmp_path, delivery_turn())
    assert result.status == "paused" and result.stop_reason == "workspace_unrepresentable"
    [pause] = _events(system, run_id, EventType.RUN_PAUSED)
    assert pause.payload["stop_reason"] == result.stop_reason
    [decision] = _open_decisions(system, run_id)
    request = decision.request
    assert (request["kind"], request["blocks"]) == ("workspace_unrepresentable", "run")
    assert [option["id"] for option in request["options"]] == ["continue", "stop"]
    assert [option["label"] for option in request["options"]] == ["处理以后继续执行", "停止事项"]
    # 说明写明停止原因与人工处理说明，条目按工作区内的相对路径列出
    assert DEFINITIONS.stop_reason("workspace_unrepresentable").human_action in request["description"]
    assert "node_modules/linked" in request["facts"]
    assert all(not os.path.isabs(item) for item in request["facts"])
    system.close()

def test_workspace_unrepresentable_continue_after_ignoring_the_entry_completes(tmp_path):
    # 把条目加入忽略规则以后回答继续，run 从原位置（ENGINEERING）继续并完成
    system, run_id, workspace, result = _workspace_unrepresentable_run(tmp_path, delivery_turn())
    [decision] = _open_decisions(system, run_id)
    workspace.write_file(".gitignore", "node_modules/\n")
    assert _answer(system, decision, "continue") == run_id
    finished = system.run_until_stop(run_id)
    assert finished.status == "done", (finished.status, finished.stop_reason)
    [continued] = _events(system, run_id, EventType.RUN_CONTINUED)
    assert continued.payload["stop_reason"] == "workspace_unrepresentable"
    system.close()

def test_max_cycles_pause_does_not_request_a_decision(tmp_path):
    # max_cycles 暂停不发出这个请求
    system = LoopSystem.for_testing(tmp_path / "data", FakeAdapter([product_spec(), *_completion_script()]))
    run_id = system.create_run("build echo", max_cycles=1)
    result = system.run_until_stop(run_id)
    assert result.status == "paused" and result.stop_reason == "max_cycles"
    assert _open_decisions(system, run_id) == []
    assert _events(system, run_id, EventType.DECISION_REQUESTED) == []
    system.close()
