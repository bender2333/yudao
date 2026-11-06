# 试用会话的事件、重新启动与 run 结束（工单 #1183；浏览器与 computer use 设计说明「试用会话」
# 「恢复契约」「事件、决定请求与查询」；总图第四节「动作」缝与「投影」缝）。
#
# 这个文件查六件事：
# 1. 会话开始时写 `trial_session_started`（选用命令的系统、端口、试用副本的树摘要与清单来源，
#    以及进程号与创建时间），`trial_stop` 写 `trial_session_ended`（结束方式：停止）；
# 2. run 进入终态时先结束会话再删除工作区（`cleanup_run` 的顺序），结束事件的结束方式是「run 结束」，
#    位置在 run 的终态事件之后——订阅方看到的位置因此递增，终态事件不会被当成旧位置丢掉；
# 3. 会话进行中重新启动 Yudao 进程：进行中的会话记为中断（结束方式：中断），没有遗留进程；
# 4. 上一次进程崩溃留下的进程树（有开始记录、没有结束记录）在启动时按进程号与创建时间结束，
#    补写一条结束事件，试用副本一起删掉；
# 5. 进程号已经被别的进程复用时（创建时间对不上）不结束它：只补写结束记录，进程照常活着。
#
# 层：集成层（真实进程树、真实重启、真实试用副本与端口）。守 R2（两个应用事件的种类与交换字段：
# 选用命令的系统、树摘要与清单来源、进程号与创建时间、结束方式）与 R3（阶段二：试用会话的中断记录、
# 遗留进程清理、run 结束时先结束会话再删工作区）。中断与重启那条自己起子进程（`--child`），
# 样板是 harness/tests/process_kill.py 与 test_mcp_lifecycle.py：先终止 Yudao 进程本身并等它退出，
# 再观察它留下的交付软件进程。

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import psutil
import pytest

from harness.adapters.fake import FakeAdapter
from harness.app.payloads import PAYLOADS
from harness.environment import inspection_root
from harness.event_store import EventStore, run_stream
from harness.models import TERMINAL_STATUSES, EventType
from harness.public_tree import capture_public_tree
from harness.runtime import LoopSystem
from harness.sessions import SessionFactory
from harness.trial_sessions import (END_INTERRUPTED, END_RUN_ENDED, END_STOPPED, TrialSessionTable,
                                    current_system)
from harness.write_path import NewEvent

pytestmark = pytest.mark.skipif(current_system() is None,
                                reason="trial launch commands are defined for windows and linux only")
REPO_ROOT = Path(__file__).resolve().parents[2]
# 等标记、等进程退出的上限（秒）：真实进程要走进程表，比内存里的操作慢
WAIT_SEC = 60.0


# ---------------------------------------------------------------------------
# 一条真实的进程树：启动命令自己起一个子进程，写下两个进程号以后一直服务到会话结束


def _launch(tree_report: Path, *, ready_timeout_sec: int = 120) -> dict[str, Any]:
    script = (
        "import http.server, json, os, subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time\\nwhile True: time.sleep(0.2)'])\n"
        f"json.dump({{'pid': os.getpid(), 'child': child.pid}}, "
        f"open({json.dumps(str(tree_report))}, 'w'))\n"
        "port = int(os.environ['PORT'])\n"
        "print('trial server listening on', port, flush=True)\n"
        "http.server.HTTPServer(('127.0.0.1', port), http.server.SimpleHTTPRequestHandler).serve_forever()\n"
    )
    return {"name": "web", "kind": "web",
            "commands": {str(current_system()): [sys.executable, "-c", script]},
            "ready_url": "http://127.0.0.1:{port}/", "ready_timeout_sec": ready_timeout_sec}


def _source_tree(parent: Path) -> Path:
    # 试用副本的来源：一个最小的公开树
    root = parent / "source"
    root.mkdir(exist_ok=True)
    (root / "index.html").write_text("<html>trial</html>\n", encoding="utf-8")
    return root


def _system(data_dir: Path) -> LoopSystem:
    return LoopSystem.for_testing(data_dir, FakeAdapter([]), resume_on_startup=False)


def _run(system: LoopSystem) -> str:
    return system.create_run("build the trial page")


def _trials(system: LoopSystem) -> TrialSessionTable:
    # 这个进程的会话表（Workspaces 与会话工厂共用同一张）：程序探测换成注入的那一份，
    # 这些用例查的是会话与事件，不等 npm/npx 的探测
    table = TrialSessionTable(probe=lambda: [])
    system.orchestrator._workspaces.trials = table
    return table


def _start(trials: TrialSessionTable, system: LoopSystem, run_id: str, tree_report: Path) -> dict[str, Any]:
    source = capture_public_tree(_source_tree(tree_report.parent))
    receipt = asyncio.run(trials.start(
        run_id=run_id, department="engineering", launch=_launch(tree_report),
        source_tree=source, run_root=system.workspace_root / run_id, source="workspace_seal",
        output_limit=4000, stop=None))
    return receipt["session"]


def _payloads(system: LoopSystem, run_id: str, event_type: str) -> list[dict[str, Any]]:
    return [dict(event.payload or {}) for event in system.store.list_events(run_id)
            if event.type == event_type]


def _events(system: LoopSystem, run_id: str, event_type: str) -> list[Any]:
    return [event for event in system.store.list_events(run_id) if event.type == event_type]


def _tree_pids(report: Path) -> tuple[int, int]:
    data = json.loads(report.read_text(encoding="utf-8"))
    return int(data["pid"]), int(data["child"])


def _alive(pid: int) -> bool:
    return psutil.pid_exists(pid) and psutil.Process(pid).is_running()


def _gone(pid: int, *, timeout: float = 20.0) -> bool:
    # 结束进程是异步的：等到它真的不在了，最多等 timeout 秒
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return not _alive(pid)


def _wait_for_file(path: Path, *, timeout: float = WAIT_SEC) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.05)
    raise TimeoutError(f"没有等到 {path}")


# ---------------------------------------------------------------------------
# 验收一：两个应用事件带齐交换字段


def test_starting_and_stopping_a_session_writes_the_two_events(tmp_path):
    system = _system(tmp_path / "data")
    try:
        run_id = _run(system)
        trials = _trials(system)
        tree_report = tmp_path / "tree.json"
        session = _start(trials, system, run_id, tree_report)

        started = _payloads(system, run_id, EventType.TRIAL_SESSION_STARTED)
        assert len(started) == 1, "会话建立以后没有写 trial_session_started"
        payload = started[0]
        assert payload["session_id"] == session["session_id"]
        assert payload["department"] == "engineering" and payload["kind"] == "web"
        assert payload["launch_name"] == "web"
        # 选用命令的系统随事件保存（docs/design/browser-and-computer-use.md「事件、决定请求与查询」）
        assert payload["system"] == current_system()
        assert payload["port"] == session["port"] and payload["ready_url"] == session["ready_url"]
        assert payload["tree_digest"] == session["tree_digest"]
        assert payload["source"] == "workspace_seal"
        # 进程号与创建时间两项都有：启动扫描按这两项结束遗留进程
        assert isinstance(payload["pid"], int) and isinstance(payload["create_time"], float)
        assert abs(psutil.Process(payload["pid"]).create_time() - payload["create_time"]) < 1.0

        # 结束会话（工具路径）：一条结束事件，结束方式是停止
        trials.stop(run_id, "engineering")
        ended = _payloads(system, run_id, EventType.TRIAL_SESSION_ENDED)
        assert len(ended) == 1, "会话结束以后没有写 trial_session_ended"
        assert ended[0]["session_id"] == session["session_id"]
        assert ended[0]["reason"] == END_STOPPED and ended[0]["ended"] is True
        # 整棵进程树都结束了
        launcher, child = _tree_pids(tree_report)
        assert _gone(launcher) and _gone(child)
        # 两种事件都有载荷类型（读旧事件与其他事件一样宽容）
        assert EventType.TRIAL_SESSION_STARTED in PAYLOADS and EventType.TRIAL_SESSION_ENDED in PAYLOADS
    finally:
        system.close()


# ---------------------------------------------------------------------------
# 验收二：run 结束时先结束会话再删工作区，结束事件写在终态事件之后


class _RecordingTrials(TrialSessionTable):
    """记下 stop_run 发生在什么时候：cleanup_run 的第二步是删检查工作区。"""

    def __init__(self, order: list[str]) -> None:
        super().__init__(probe=lambda: [])
        self._order = order

    def stop_run(self, run_id: str | None, *, reason: str = END_RUN_ENDED) -> list[dict[str, Any]]:
        self._order.append(f"sessions:{run_id}:{reason}")
        return super().stop_run(run_id, reason=reason)


def test_cleanup_run_ends_the_sessions_before_it_deletes_the_workspace(tmp_path, monkeypatch):
    order: list[str] = []
    factory = SessionFactory(tmp_path / "workspaces")
    factory.trials = _RecordingTrials(order)
    factory.create_run_sessions("run-1")

    def record_cleanup(root: Any, session_id: str) -> None:
        order.append(f"workspace:{Path(root).name}")

    monkeypatch.setattr("harness.sessions.cleanup_inspection_workspace", record_cleanup)

    factory.cleanup_run("run-1")

    assert order[0] == f"sessions:run-1:{END_RUN_ENDED}", f"没有先结束会话：{order}"
    # 三个部门的检查工作区都在会话结束之后才删
    assert order[1:] == ["workspace:run-1"] * 3, order


def test_a_run_end_ends_the_sessions_and_writes_the_ended_event_after_the_terminal_event(tmp_path):
    system = _system(tmp_path / "data")
    try:
        run_id = _run(system)
        trials = _trials(system)
        tree_report = tmp_path / "tree.json"
        session = _start(trials, system, run_id, tree_report)
        copy = Path(session["copy"])
        assert copy.exists()
        # 这个 run 的一个检查工作区：run 结束时它要被删掉
        department_session = system.orchestrator.sessions.get(run_id, "engineering").session_id
        inspection = inspection_root(system.workspace_root / run_id, department_session)
        inspection.mkdir(parents=True)
        (inspection / "work.txt").write_text("checking\n", encoding="utf-8")

        # 订阅方看到的位置：run 的终态事件先写、会话结束的事件后写。反过来的话事件流的转发会把
        # 终态事件当成旧位置丢掉（app/event_stream.py 只在位置大于上一条时转发）
        positions: list[int] = []

        def record(events: Any) -> None:
            positions.extend(event.position for event in events)

        unsubscribe = system.store.subscribe(record)
        try:
            system.cancel(run_id)
        finally:
            unsubscribe()

        assert system.project(run_id).status in TERMINAL_STATUSES
        assert positions == sorted(positions), f"订阅方看到的位置不是递增的：{positions}"

        terminal = _events(system, run_id, EventType.RUN_FAILED)
        assert terminal, "取消以后 run 没有进入终态"
        ended = _events(system, run_id, EventType.TRIAL_SESSION_ENDED)
        assert len(ended) == 1, "run 结束时没有写会话的结束事件"
        assert ended[0].payload["reason"] == END_RUN_ENDED
        assert ended[0].payload["ended"] is True
        assert ended[0].position > terminal[0].position, "结束事件写在终态事件前面"
        # 会话的进程树结束了、试用副本删掉了、检查工作区也删掉了
        launcher, child = _tree_pids(tree_report)
        assert _gone(launcher) and _gone(child)
        assert not copy.exists(), "run 结束以后试用副本还在"
        assert not inspection.exists(), "run 结束以后检查工作区还在"
        # 表里不再有这个 run 的会话
        assert trials.session_of(run_id, "engineering") is None
    finally:
        system.close()


# ---------------------------------------------------------------------------
# 验收三：会话进行中重新启动 Yudao 进程，会话记为中断，没有遗留进程


def _child_main(data_dir: Path, ready: Path) -> None:
    # 子进程：打开数据目录，建一个 run，开始一个真实的试用会话（事件走生产路径），
    # 写下标记以后一直等着被终止
    system = _system(data_dir)
    run_id = _run(system)
    trials = _trials(system)
    tree_report = ready.parent / "tree.json"
    source = capture_public_tree(_source_tree(ready.parent))
    asyncio.run(trials.start(run_id=run_id, department="engineering", launch=_launch(tree_report),
                             source_tree=source, run_root=system.workspace_root / run_id,
                             source="workspace_seal", output_limit=4000, stop=None))
    session = trials.session_of(run_id, "engineering")
    ready.write_text(json.dumps({"run_id": run_id, "session_id": session.session_id},
                                ensure_ascii=False), encoding="utf-8")
    while True:
        time.sleep(0.2)


def _spawn_child(data_dir: Path, ready: Path, log: Path) -> subprocess.Popen:
    environment = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    spawn = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    with log.open("wb") as output:
        return subprocess.Popen([sys.executable, "-m", "harness.tests.test_trial_session_recovery",
                                 "--child", str(data_dir), str(ready)],
                                cwd=str(REPO_ROOT), env=environment, stdout=output,
                                stderr=subprocess.STDOUT, **spawn)


def _kill(process: subprocess.Popen) -> None:
    # 先终止 Yudao 进程本身、等它退出（样板 harness/tests/process_kill.py）
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        process.kill()
    process.wait(WAIT_SEC)


def _open_after_kill(data_dir: Path) -> LoopSystem:
    deadline = time.monotonic() + WAIT_SEC
    while True:
        try:
            return _system(data_dir)
        except Exception:  # noqa: BLE001 - 进程刚退出时事件库的文件还可能被短暂占用
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.2)


def _observe(data_dir: Path, run_id: str) -> list[Any]:
    # 终止以后、任何系统打开它以前，只读地读出这个 run 的事件
    deadline = time.monotonic() + WAIT_SEC
    while True:
        try:
            store = EventStore(data_dir / "events.sqlite", read_only=True)
        except Exception:  # noqa: BLE001 - 同上
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.2)
            continue
        try:
            return store.list_events(run_id)
        finally:
            store.close()


def test_a_restart_marks_the_session_interrupted_and_leaves_no_process(tmp_path):
    data_dir = tmp_path / "data"
    marker = tmp_path / "marker"
    marker.mkdir()
    ready = marker / "ready"
    log = tmp_path / "yudao.log"
    process = _spawn_child(data_dir, ready, log)
    try:
        _wait_for_file(ready)
        _wait_for_file(marker / "tree.json")
    finally:
        _kill(process)
    run_id = json.loads(ready.read_text(encoding="utf-8"))["run_id"]

    # 终止以后：开始记录在，结束记录不在
    observed = _observe(data_dir, run_id)
    started = [event for event in observed if event.type == EventType.TRIAL_SESSION_STARTED]
    assert len(started) == 1, "终止以前应当有一条会话开始事件"
    assert [event for event in observed if event.type == EventType.TRIAL_SESSION_ENDED] == [], \
        "终止以前不应当有会话结束的记录"
    launcher, child = _tree_pids(marker / "tree.json")
    assert _gone(launcher, timeout=30) and _gone(child, timeout=30), "交付软件的进程树没有随 Yudao 进程一起结束"

    restarted = _open_after_kill(data_dir)
    try:
        ended = _payloads(restarted, run_id, EventType.TRIAL_SESSION_ENDED)
        assert len(ended) == 1, "重新启动以后没有补写会话的结束记录"
        assert ended[0]["session_id"] == started[0].payload["session_id"]
        assert ended[0]["reason"] == END_INTERRUPTED
        assert ended[0]["pid"] == started[0].payload["pid"]
        # 会话记为中断以后，这个 run 的会话表里没有它
        assert restarted.orchestrator._workspaces.trials.session_of(run_id, "engineering") is None
        assert _gone(launcher) and _gone(child)
    finally:
        restarted.close()


# ---------------------------------------------------------------------------
# 验收四：上一次进程崩溃留下的进程树在启动时结束，补写结束记录
#
# 这一条不真杀进程：会话由这个测试进程开始（它的进程树因此不受 Yudao 作业对象的约束），
# 然后只关闭事件库，模拟「进程崩溃、结束记录没有写下来」。启动扫描按开始记录里的进程号与创建时间
# 结束这棵树——与真崩溃留下的现场是同一个形状


def test_a_leftover_tree_is_ended_and_recorded_on_the_next_startup(tmp_path):
    data_dir = tmp_path / "data"
    system = _system(data_dir)
    run_id = _run(system)
    trials = _trials(system)
    tree_report = tmp_path / "tree.json"
    session = _start(trials, system, run_id, tree_report)
    copy = Path(session["copy"])
    launcher, child = _tree_pids(tree_report)
    assert _alive(launcher) and _alive(child)
    system.store.close()  # 模拟崩溃：结束记录没有写下来

    restarted = _open_after_kill(data_dir)
    try:
        ended = _payloads(restarted, run_id, EventType.TRIAL_SESSION_ENDED)
        assert len(ended) == 1, "启动时没有补写会话的结束记录"
        assert ended[0]["reason"] == END_INTERRUPTED
        assert ended[0]["pid"] == session["process_id"]
        assert ended[0]["ended"] is True, "这一次应当真的结束了仍然存活的进程"
        # 整棵进程树都结束了，试用副本也删掉了
        assert _gone(launcher) and _gone(child)
        assert not copy.exists(), "遗留会话的试用副本还在"
    finally:
        restarted.close()


def test_a_reused_process_number_is_not_killed(tmp_path):
    # 进程号已经被别的进程复用（创建时间对不上）：只补写结束记录，进程照常活着
    data_dir = tmp_path / "data"
    system = _system(data_dir)
    run_id = _run(system)
    unrelated = psutil.Popen([sys.executable, "-c", "import time\nwhile True: time.sleep(0.2)"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        def decide(transaction: Any) -> None:
            transaction.append(NewEvent(
                EventType.TRIAL_SESSION_STARTED, state_before=transaction.projection.status,
                state_after=transaction.projection.status, actor="system",
                payload={"session_id": "trial_gone", "department": "engineering", "kind": "web",
                         "launch_name": "web", "system": str(current_system()), "port": 1,
                         "ready_url": "http://127.0.0.1:1/", "tree_digest": "sha256:" + "0" * 64,
                         "source": "workspace_seal", "pid": unrelated.pid,
                         # 会话记录里那个进程的创建时间：与现在这个进程对不上
                         "create_time": 1.0}))

        system.writes.transact(run_stream(run_id), decide)
        system.store.close()

        restarted = _open_after_kill(data_dir)
        try:
            ended = _payloads(restarted, run_id, EventType.TRIAL_SESSION_ENDED)
            assert len(ended) == 1 and ended[0]["ended"] is False
            assert _alive(unrelated.pid), "创建时间对不上时仍然结束了这个进程"
        finally:
            restarted.close()
    finally:
        if unrelated.poll() is None:
            unrelated.kill()
            unrelated.wait(30)


# ---------------------------------------------------------------------------
# 子进程入口（中断与重启那条用）

def main() -> None:
    if len(sys.argv) != 4 or sys.argv[1] != "--child":
        raise SystemExit("usage: python -m harness.tests.test_trial_session_recovery --child <data> <ready>")
    _child_main(Path(sys.argv[2]), Path(sys.argv[3]))


if __name__ == "__main__":
    main()
