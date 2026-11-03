# 试用会话：起停交付的网页（浏览器与 computer use 设计说明「试用会话」「试用工具」与「恢复契约」，
# 工单 #1182；总图第四节「动作」缝的 trial 类别）。
#
# 这个文件查六件事：
# 1. 工程用网页启动方式调用 trial_start：按本机系统选用命令、启动真实的小网页、等到就绪，回执带会话身份、
#    端口、就绪地址、试用副本的树摘要与启动输出；trial_output 读末尾，trial_stop 结束进程树并删掉副本；
# 2. 同时进行的两个会话得到不同的端口；
# 3. 缺少试用需要的程序时就绪不建立会话，回执写明缺少的程序；
# 4. 就绪超时与进程提前退出得到真实的失败回执，带启动输出，会话不建立；失败回执的启动输出按规则登记的
#    tool_output_limit 截断；
# 5. 质检按当前交付说明里的名称开始会话，试用副本的树摘要等于交付快照的摘要（工程改了工作区也不影响）；
#    名称不存在或交付说明没有 launch 时核对不通过，原因写明已有的名称或没有写启动方式；本机系统没有
#    启动命令时原因写明缺少哪个系统的命令；真实激活里 `Workspaces` 交给执行环境的那两处接线
#    （当前交付说明的 launch、交付快照）也能区分：关掉以后质检要么拿不到名称，要么副本来源变成工作区封存；
#    检查工作区按会话保留以后重新打开的那条路径（`inspection_environment`）同样绑定交付快照；
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
from harness.artifacts import ArtifactStore
from harness.definitions import DEFINITIONS
from harness.environment import LocalEnvironment, Workspaces, inspection_root
from harness.models import EventType
from harness.proposals import delivery_turn, product_spec
from harness.providers.call import ModelResponse
from harness.public_tree import capture_public_tree
from harness.runtime import LoopSystem
from harness.tools import tool_cancellable, tool_verification
from harness.tree_archive import artifact_run, load_tree, store_tree
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
                 run_id: str = "run-1", parameters: dict[str, Any] | None = None) -> LocalEnvironment:
    return LocalEnvironment.open(root, run_id=run_id, parameters=parameters,
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


def test_a_failed_receipt_cuts_the_launch_output_at_the_tool_output_limit(tmp_path):
    # 失败回执带回来的启动输出按这个 run 冻结的 tool_output_limit 截断（工单 #1182 的验收第 6 条）。
    # 冻结值与定义里的初值不同（1000 与 4000），所以这条能区分「执行环境把这个 run 的上限传进去」与
    # 「碰巧用了定义里的 4000」；打印得比上限多的程序只交回末尾这一段
    root = _web_workspace(tmp_path)
    frozen_limit = int(DEFINITIONS.rule_value("tool_output_limit"))
    limit = 1000
    assert limit != frozen_limit
    environment = _environment(root, parameters={"tool_output_limit": limit})
    command = _python(
        "import sys\n"
        f"sys.stdout.write('x' * {frozen_limit * 2})\n"
        "sys.stdout.write('\\nBOOT FAILED\\n')\n"
        "sys.exit(3)\n")
    launch = {"name": "web", "kind": "web",
              "commands": {str(current_system()): command},
              "ready_url": "http://127.0.0.1:{port}/", "ready_timeout_sec": 30}

    receipt = _perform(environment, "trial_start", {"launch": launch})

    assert receipt.ok is False and receipt.status == "failed"
    output = receipt.output["output"]
    assert "BOOT FAILED" in output, "失败回执没有带启动输出的末尾"
    assert len(output) <= limit, f"启动输出没有按这个 run 的上限截断（{len(output)} > {limit}）"


def test_the_workspaces_hand_the_delivery_launch_and_snapshot_to_quality(tmp_path):
    # 真实激活里 `Workspaces` 交给执行环境的那两处接线（工单 #1182 与设计说明第 3.4 节）：当前交付说明的
    # launch 与这次检查的交付快照。关掉 `bind_launch_methods` 时质检的 trial_open 拿不到名称（回执写着
    # the DeliverySpec has no launch method），关掉 `_attach_trial_source` 时副本来源变成 workspace_seal、
    # 副本从检查工作区建立；现有的用例都自己 bind，区分不了这两处接线
    server = _python(
        "import http.server, os\n"
        "port = int(os.environ['PORT'])\n"
        "print('tiny server listening on', port, flush=True)\n"
        "http.server.HTTPServer(('127.0.0.1', port), http.server.SimpleHTTPRequestHandler).serve_forever()\n")
    launch = {"name": "web", "kind": "web", "commands": {str(current_system()): server},
              "ready_url": "http://127.0.0.1:{port}/", "ready_timeout_sec": 120}
    open_call = {"id": "t1", "call_id": "t1", "type": "function_call", "name": "trial_open",
                 "arguments": json.dumps({"launch_name": "web"}, ensure_ascii=False)}
    stop_call = {"id": "t2", "call_id": "t2", "type": "function_call", "name": "trial_stop",
                 "arguments": "{}"}
    adapter = FakeAdapter({
        "product": [product_spec()],
        "engineering": [delivery_turn(files={"index.html": "<html>ok</html>\n"}, checks={"smoke": 0},
                                      launch=[launch])],
        "quality": [ModelResponse(output=[open_call, stop_call])],
    })
    system_under_test = LoopSystem.for_testing(tmp_path, adapter)
    # 程序核对换成注入的那份：这条用例查的是接线，不等 npm/npx 的探测
    system_under_test.orchestrator._workspaces.trials = TrialSessionTable(probe=lambda: [])
    run_id = system_under_test.create_run("build a page")
    for _ in range(3):
        try:
            system_under_test.activate_once(run_id)
        except Exception:  # noqa: BLE001 - 假模型脚本用完以后这一轮以失败结束，两个调用已经写下
            break

    events = system_under_test.store.list_events(run_id)
    opened = next(event for event in events
                  if event.type == EventType.TOOL_CALLED and (event.payload or {}).get("id") == "t1")
    assert opened.payload.get("ok") is True, opened.payload.get("error")
    record = json.loads(system_under_test.artifacts.get_text(
        opened.payload["output_ref"]["content_hash"]))
    session = record["session"]
    assert session["launch_name"] == "web"
    # 副本来源是交付快照，不是质检自己的检查工作区：关掉 `_attach_trial_source` 时这一项变成 workspace_seal
    assert session["copy_source"] == "delivery_snapshot", "试用副本不是从交付快照建立的"
    # 副本的内容就是这份交付的清单：实现自己在启动之前核对过副本的树摘要等于来源的摘要
    delivery_ref = system_under_test.project(run_id).delivery_spec.tree_ref
    delivered = load_tree(system_under_test.artifacts, artifact_run(delivery_ref.path), delivery_ref)
    assert [item.path for item in delivered.files] == ["index.html"]
    assert session["tree_digest"] == delivered.digest, "试用副本的树摘要不等于交付快照的摘要"
    stopped = next(event for event in events
                   if event.type == EventType.TOOL_CALLED and (event.payload or {}).get("id") == "t2")
    assert stopped.payload.get("ok") is True
    assert not Path(session["copy"]).exists(), "会话结束以后试用副本还在"


class _UsedSession:
    """只回一条「这个会话用过文件工具」的记录：检查工作区按会话保留的那一支（工单 #558）。"""

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id

    def read(self, stream: Any) -> Any:
        event = SimpleNamespace(type=EventType.TOOL_CALLED, session_id=self._session_id,
                                payload={"name": "write_file"})
        return SimpleNamespace(events=lambda: [event])


def test_a_retained_inspection_workspace_still_takes_the_trial_copy_from_the_delivery(tmp_path):
    # 检查工作区按会话保留（工单 #558）：会话用过文件工具以后，后面一次激活走 `session_inspection` →
    # `inspection_environment`，那是 `Workspaces` 绑定试用副本来源的另一个位置。那条路径同样得把交付快照
    # 交给执行环境，否则质检的试用副本会从它自己的检查工作区封存（那里带着它写的检查文件）
    artifacts = ArtifactStore(tmp_path / "artifacts")
    delivered = capture_public_tree(FIXTURE)
    tree_ref = store_tree(artifacts, "run-1", delivered)
    launch = _launch()
    delivery = SimpleNamespace(tree_ref=tree_ref, content_hash="sha256:" + "1" * 64, launch=[launch])

    def view(run_id: str) -> Any:
        return SimpleNamespace(run_id=run_id, delivery_spec=delivery, baseline=None, snapshot=None,
                               branch_sessions=set(), sessions={}, parameters=None,
                               qa_tests_archive_ref=None)

    workspaces = Workspaces(tmp_path / "runs", view=view, writes=_UsedSession("ses_1"),
                            artifacts=artifacts, definitions=DEFINITIONS)
    workspaces.trials = TrialSessionTable(probe=lambda: [])
    workspaces.new_inspection("run-1", "quality", session_id="ses_1")
    # 质检在自己的检查工作区里写的东西不在交付快照里
    workspace_root = inspection_root(tmp_path / "runs" / "run-1", "ses_1")
    (workspace_root / "qa-extra.txt").write_text("not part of the delivery\n", encoding="utf-8")

    environment = workspaces.session_inspection("run-1", "quality", session_id="ses_1")
    environment.bind_launch_methods([launch])

    receipt = _perform(environment, "trial_open", {"launch_name": "web"}, department="quality")

    assert receipt.ok is True, receipt.error
    session = receipt.output["session"]
    assert session["copy_source"] == "delivery_snapshot", "试用副本不是从交付快照建立的"
    assert session["tree_digest"] == delivered.digest, "试用副本的树摘要不等于交付快照的摘要"
    assert not (Path(session["copy"]) / "qa-extra.txt").exists(), "副本里带上了质检的检查文件"
    _perform(environment, "trial_stop", {}, department="quality")


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
