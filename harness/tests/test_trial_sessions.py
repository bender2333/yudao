# 试用会话：起停交付的网页（浏览器与 computer use 设计说明「试用会话」「试用工具」与「恢复契约」，
# 工单 #1182；总图第四节「动作」缝的 trial 类别）。
#
# 这个文件查六件事：
# 1. 工程用网页启动方式调用 trial_start：按本机系统选用命令、启动真实的小网页、等到就绪，回执带会话身份、
#    端口、就绪地址、试用副本的树摘要与启动输出；trial_output 读末尾，trial_stop 结束进程树并删掉副本；
# 2. 同时进行的两个会话得到不同的端口；
# 3. 缺少试用需要的程序时就绪不建立会话，回执写明缺少的程序；
# 4. 就绪超时与进程提前退出得到真实的失败回执，带启动输出，会话不建立；
# 5. 质检按当前交付说明里的名称开始会话，试用副本的树摘要等于交付快照的摘要（工程改了工作区也不影响）；
#    名称不存在或交付说明没有 launch 时核对不通过，原因写明已有的名称或没有写启动方式；本机系统没有
#    启动命令时原因写明缺少哪个系统的命令；
# 6. 结束本部门原来的会话：同一个部门再开始一次时，前一个会话的副本被删掉。
#
# 层：集成层（真实网页服务、真实端口与子进程）。守 R3：试用会话从清单建立副本、按系统选用命令、
# 等到就绪才交回会话记录，失败时不建立会话。

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from harness.actions import Action
from harness.adapters.fake import FakeAdapter
from harness.environment import LocalEnvironment
from harness.models import EventType
from harness.proposals import delivery_turn, product_spec
from harness.providers.call import ModelResponse
from harness.public_tree import capture_public_tree
from harness.runtime import LoopSystem
from harness.tools import tool_cancellable, tool_verification
from harness.trial_sessions import TrialSessionTable, current_system, resolve_trial_call

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "tiny_web_app"
# 试用会话只在本机与控制主机两类位置上：系统不是 windows 或 linux 的机器没有启动命令的约定
pytestmark = pytest.mark.skipif(current_system() is None,
                                reason="trial launch commands are defined for windows and linux only")
# 小网页的启动命令：安装依赖、构建，再启动从 PORT 读端口的服务（设计说明第 3.3 节）
_WEB_COMMAND = "npm install --no-audit --no-fund --offline && npm run build && npm start"


def _launch(*, name: str = "web", systems: tuple[str, ...] | None = None,
            ready_timeout_sec: int = 120, kind: str = "web",
            ready_url: str | None = "http://127.0.0.1:{port}/") -> dict[str, Any]:
    systems = systems or (("windows", "linux") if current_system() else ())
    commands = {
        system: (["cmd", "/c", f"echo launch-system={system} && {_WEB_COMMAND}"] if system == "windows"
                 else ["sh", "-c", f"echo launch-system={system} && {_WEB_COMMAND}"])
        for system in systems
    }
    return {"name": name, "kind": kind, "commands": commands,
            "ready_url": ready_url, "ready_timeout_sec": ready_timeout_sec}


def _action(tool: str, args: dict[str, Any], *, department: str = "engineering") -> Action:
    return Action(action_id=f"test:{tool}", kind="trial", tool=tool, department=department, input=args,
                  verification=tool_verification(tool), cancellable=tool_cancellable(tool))


def _perform(environment: LocalEnvironment, tool: str, args: dict[str, Any], *,
             department: str = "engineering"):
    return asyncio.run(environment.perform(_action(tool, args, department=department)))


def _web_workspace(tmp_path: Path, name: str = "run-1") -> Path:
    # 一个含真实小网页的运行工作区：工程的试用副本从它封存
    root = tmp_path / "runs" / name
    root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FIXTURE, root)
    return root


def _environment(root: Path, *, trials: TrialSessionTable | None = None,
                 run_id: str = "run-1") -> LocalEnvironment:
    return LocalEnvironment.open(root, run_id=run_id,
                                 trials=trials if trials is not None else TrialSessionTable(probe=lambda: []))


def _python(argv_source: str) -> list[str]:
    return [sys.executable, "-c", argv_source]


def test_engineering_starts_the_tiny_web_app_and_waits_until_ready(tmp_path):
    root = _web_workspace(tmp_path)
    environment = _environment(root)
    system = current_system()
    launch = _launch()

    receipt = _perform(environment, "trial_start", {"launch": launch})

    assert receipt.ok is True and receipt.status == "completed", receipt.error
    output = receipt.output
    session = output["session"]
    # 回执带会话身份、种类、端口、就绪地址、试用副本的树摘要与启动输出（设计说明第 3.4 节）
    assert session["session_id"].startswith("trial_")
    assert session["kind"] == "web" and session["launch_name"] == "web"
    assert session["system"] == system
    assert isinstance(session["port"], int) and session["port"] > 0
    assert session["ready_url"] == f"http://127.0.0.1:{session['port']}/"
    assert session["tree_digest"] == capture_public_tree(root).digest
    assert f"launch-system={system}" in output["output"], "没有用本机系统的启动命令"
    assert "tiny web app listening on" in output["output"]
    assert output["truncated"] is False

    # trial_output 取回末尾部分，给出截断标记
    read = _perform(environment, "trial_output", {})
    assert read.ok is True
    assert read.output["session_id"] == session["session_id"]
    assert "tiny web app listening on" in read.output["output"]
    assert read.output["truncated"] is False
    tail = _perform(environment, "trial_output", {"bytes": 8})
    assert tail.output["truncated"] is True and len(tail.output["output"]) <= 8

    # trial_stop 结束进程树、删掉试用副本、交回结束方式
    stopped = _perform(environment, "trial_stop", {})
    assert stopped.ok is True
    assert stopped.output["ended"] is True and stopped.output["reason"] == "stopped"
    assert stopped.output["session"]["ended_reason"] == "stopped"
    assert not Path(session["copy"]).exists(), "会话结束以后试用副本还在"
    assert _perform(environment, "trial_output", {}).output["session_id"] is None
    assert _perform(environment, "trial_stop", {}).output["ended"] is False


def test_two_sessions_in_flight_get_different_ports(tmp_path):
    trials = TrialSessionTable(probe=lambda: [])
    engineering = _environment(_web_workspace(tmp_path, "run-a"), trials=trials, run_id="run-a")
    quality_root = _web_workspace(tmp_path, "run-b")
    quality_tree = capture_public_tree(quality_root)
    inspection = quality_root / "inspection"
    inspection.mkdir()
    quality = LocalEnvironment.open(inspection, run_id="run-b", trials=trials)
    quality.bind_trial_source(quality_tree)
    quality.bind_launch_methods([_launch()])

    started = _perform(engineering, "trial_start", {"launch": _launch()})
    try:
        opened = _perform(quality, "trial_open", {"launch_name": "web"}, department="quality")
        assert started.ok and opened.ok, (started.error, opened.error)
        first = started.output["session"]
        second = opened.output["session"]
        assert first["port"] != second["port"], "同时进行的两个会话拿到了同一个端口"
        assert first["ready_url"] != second["ready_url"]
    finally:
        _perform(engineering, "trial_stop", {})
        _perform(quality, "trial_stop", {}, department="quality")


def test_a_missing_program_is_named_and_no_session_is_established(tmp_path):
    missing = [{"program": "Playwright MCP 0.0.83", "detail": "not installed"}]
    environment = _environment(_web_workspace(tmp_path),
                               trials=TrialSessionTable(probe=lambda: missing))

    receipt = _perform(environment, "trial_start", {"launch": _launch()})

    assert receipt.ok is False and receipt.status == "failed"
    assert "Playwright MCP 0.0.83" in receipt.error
    assert receipt.output["missing_programs"] == missing
    assert receipt.output["session"] is None
    assert _perform(environment, "trial_output", {}).output["session_id"] is None


def test_an_early_exit_is_a_failed_receipt_with_the_launch_output(tmp_path):
    root = _web_workspace(tmp_path)
    environment = _environment(root)
    command = _python("import sys; print('boot failed'); sys.exit(3)")
    launch = {"name": "web", "kind": "web",
              "commands": {str(current_system()): command},
              "ready_url": "http://127.0.0.1:{port}/", "ready_timeout_sec": 30}

    receipt = _perform(environment, "trial_start", {"launch": launch})

    assert receipt.ok is False and receipt.status == "failed"
    assert "exited with code 3" in receipt.error
    assert "boot failed" in receipt.output["output"]
    assert receipt.output["session"]["status"] == "ended"
    assert _perform(environment, "trial_output", {}).output["session_id"] is None


def test_a_readiness_timeout_is_a_failed_receipt_with_the_launch_output(tmp_path):
    root = _web_workspace(tmp_path)
    environment = _environment(root)
    command = _python("import time; print('starting slowly', flush=True); time.sleep(60)")
    launch = {"name": "web", "kind": "web",
              "commands": {str(current_system()): command},
              "ready_url": "http://127.0.0.1:{port}/", "ready_timeout_sec": 10}

    started = time.monotonic()
    receipt = _perform(environment, "trial_start", {"launch": launch})
    elapsed = time.monotonic() - started

    # 就绪时限的最小值取自规则登记的界限（10 秒）；到点以后不再等
    assert elapsed >= 10
    assert receipt.ok is False and receipt.status == "failed"
    assert "did not become ready" in receipt.error
    assert "starting slowly" in receipt.output["output"]
    assert _perform(environment, "trial_output", {}).output["session_id"] is None


def test_quality_starts_a_copy_of_the_delivery_snapshot_by_its_launch_name(tmp_path):
    snapshot = capture_public_tree(FIXTURE)
    workspace = tmp_path / "inspections" / "run-1" / "session-quality"
    environment = LocalEnvironment.establish(workspace, snapshot, run_id="run-1",
                                             trials=TrialSessionTable(probe=lambda: []))
    environment.bind_trial_source(snapshot)
    environment.bind_launch_methods([_launch()])
    # 质检在自己的检查工作区里写下的文件不在交付快照里：试用副本按交付快照建立
    (workspace / "qa-extra.txt").write_text("not part of the delivery\n", encoding="utf-8")
    assert capture_public_tree(workspace).digest != snapshot.digest

    receipt = _perform(environment, "trial_open", {"launch_name": "web"}, department="quality")

    assert receipt.ok is True, receipt.error
    session = receipt.output["session"]
    assert session["launch_name"] == "web" and session["copy_source"] == "delivery_snapshot"
    assert session["tree_digest"] == snapshot.digest, "试用副本的树摘要不等于交付快照的摘要"
    assert not (Path(session["copy"]) / "qa-extra.txt").exists()
    _perform(environment, "trial_stop", {}, department="quality")


def test_a_launch_name_the_delivery_spec_does_not_carry_is_refused_with_the_names():
    delivery = SimpleNamespace(launch=[_launch(name="web"), _launch(name="cli")])

    launch, reason = resolve_trial_call("trial_open", {"launch_name": "missing"}, delivery)

    assert launch is None
    assert "no launch method named 'missing'" in reason
    assert "web" in reason and "cli" in reason


def test_a_delivery_spec_without_a_launch_method_is_refused():
    launch, reason = resolve_trial_call("trial_open", {"launch_name": "web"},
                                        SimpleNamespace(launch=[]))

    assert launch is None and reason == "the DeliverySpec has no launch method"


def test_a_launch_without_a_command_for_this_system_is_refused_naming_it():
    system = current_system()
    other = "linux" if system == "windows" else "windows"
    launch = _launch(systems=(other,))

    resolved, reason = resolve_trial_call("trial_start", {"launch": launch}, None)

    assert resolved is None
    assert f"no command for {system}" in reason
    assert f"commands cover: {other}" in reason


def test_the_tool_permission_refuses_a_launch_without_this_systems_command(tmp_path):
    # 交付说明只有另一个系统的命令时，本机控制主机上的 trial_start 被工具许可拒绝：动作没有交给执行环境，
    # 也没有工具开始事件；原因写明缺少哪个系统的命令（工单 #1182 的验收第 2 条）
    system = current_system()
    other = "linux" if system == "windows" else "windows"
    launch = _launch(systems=(other,))
    call = {"id": "c1", "call_id": "c1", "type": "function_call", "name": "trial_start",
            "arguments": json.dumps({"launch": launch}, ensure_ascii=False)}
    adapter = FakeAdapter({"product": [product_spec()],
                           "engineering": [ModelResponse(output=[call]), delivery_turn()]})
    system_under_test = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system_under_test.create_run("build a page")
    system_under_test.activate_once(run_id)
    system_under_test.activate_once(run_id)

    events = system_under_test.store.list_events(run_id)
    recorded = next(event for event in events
                    if event.type == EventType.TOOL_CALLED and (event.payload or {}).get("id") == "c1")
    assert recorded.payload["refused"] is True
    assert f"no command for {system}" in recorded.payload["refused_reason"]
    assert not any(event.type == EventType.TOOL_STARTED and (event.payload or {}).get("id") == "c1"
                   for event in events), "被拒绝的调用有工具开始事件"


def test_the_tool_permission_refuses_a_launch_name_the_delivery_spec_does_not_carry(tmp_path):
    # 质检按当前交付说明里的名称开始会话：名称不存在时被工具许可拒绝，原因写明交付说明中已有的名称
    # （工单 #1182 的验收第 3 条）
    call = {"id": "c2", "call_id": "c2", "type": "function_call", "name": "trial_open",
            "arguments": json.dumps({"launch_name": "missing"}, ensure_ascii=False)}
    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn(files={"src/page.py": "print('hi')\n"}, checks={"smoke": 0},
                                      launch=[_launch()])],
        "quality": [ModelResponse(output=[call])],
    })
    system_under_test = LoopSystem.for_testing(tmp_path, adapter)
    run_id = system_under_test.create_run("build a page")
    for _ in range(3):
        try:
            system_under_test.activate_once(run_id)
        except Exception:  # noqa: BLE001 - 假模型脚本用完以后这一轮以失败结束，被拒绝的回执已经写下
            break

    events = system_under_test.store.list_events(run_id)
    recorded = next(event for event in events
                    if event.type == EventType.TOOL_CALLED and (event.payload or {}).get("id") == "c2")
    assert recorded.payload["refused"] is True
    assert "no launch method named 'missing'" in recorded.payload["refused_reason"]
    assert "web" in recorded.payload["refused_reason"]


def test_starting_again_replaces_the_previous_session_of_the_department(tmp_path):
    environment = _environment(_web_workspace(tmp_path))

    first = _perform(environment, "trial_start", {"launch": _launch()})
    try:
        second = _perform(environment, "trial_start", {"launch": _launch()})
        assert first.ok and second.ok, (first.error, second.error)
        assert not Path(first.output["session"]["copy"]).exists(), "被替换的会话副本还在"
        assert second.output["session"]["session_id"] != first.output["session"]["session_id"]
    finally:
        _perform(environment, "trial_stop", {})
