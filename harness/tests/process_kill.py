# 真实的进程中断与重启（工单 #307，恢复契约第 4、5 节）。这套辅助给 #307、#317、#308 与 #143 共用：
# 事项在真实的子进程里运行到指定的时刻被终止，再用同一个数据目录重新打开系统，恢复走的是启动时的自动继续。
# 模型回答由 FakeAdapter 的脚本给出（确定性脚本，不是替身）；检查与登记命令都是真实进程。
#
# 接口保持小：
#     result = interrupted(data_dir, script, *, started=标记路径, hold_after=..., hold_action=...)
# 返回的对象带 before（终止前打开的系统）、after（重启后、启动恢复已经跑过的系统）与 before_events
# （终止以后、重新打开之前读出的事件），都可以直接查询。
#
# 脚本是一项回答的序列，每一项是 JSON：
#   {"proposal": {...}}      提交一种提案（product_spec、engineering_plan 等）
#   {"output": [...]}        一次回答的全部输出条目（自己写调用，例如指定编号的一次读取）
#   其余字段                  FakeTurn 的字段（checks、transcript、files 等）
#
# 终止位置有两条：
#   started=标记路径     检查与登记命令的真实进程写下 started 以后终止（工具执行到一半）
#   hold_after=事件种类  该事件提交以后进程停住（读取这类同步执行的工具只能停在这里），
#                        给出 hold_action 时只在那一个调用编号的事件上停
# 两条都不给时子进程运行到结束，不终止。
#
# 子进程入口：python -m harness.tests.process_kill <数据目录> <脚本 JSON> <事项任务> [登记注册表 JSON]

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Sequence

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.app.application import Application
from harness.app.project_queries import RunActions, RunRecovery
from harness.models import EventType
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.tests.helpers import after_event

REPO_ROOT = Path(__file__).resolve().parents[2]
# 子进程启动、超时与等待退出的上限；真实进程要走文件系统与进程表，比内存里的操作慢
STARTUP_TIMEOUT_SEC = 300


def build_script(items: Sequence[dict[str, Any]]) -> list[Any]:
    # 把 JSON 脚本项变成 FakeAdapter 的脚本项：
    #   {"proposal": {...}}   提交一种提案（product_spec、engineering_plan 等）
    #   {"output": [...]}     一次回答的全部输出条目（自己写调用，例如指定编号的一次读取）
    #   其余字段              FakeTurn 的字段（checks、transcript、files 等）
    script: list[Any] = []
    for item in items:
        if "proposal" in item:
            script.append(dict(item["proposal"]))
        elif "output" in item:
            script.append(ModelResponse(output=[dict(entry) for entry in item["output"]]))
        else:
            script.append(FakeTurn(**item))
    return script


def _hold_after(system: LoopSystem, event_type: str, directory: Path, *,
                action_id: str | None = None) -> None:
    # 在指定事件提交以后停在这个位置：写下 hold 标记以后一直等待，由父进程终止这个进程。
    # 同步执行的工具（读取、写入、编辑、删除、移动）没有可以等待的子进程，只能在这一刻停住，
    # 这次动作的结果因此没有落盘；父进程见到 hold 标记以后终止，恢复时这次动作的结果未知。
    # 给出 action_id 时只在这个调用编号的那次事件上停（同一个工具的前几次调用不算）。
    # 恢复途中注册这个钩子时，停住的是恢复自动重新执行的那一次尝试
    marker = directory / "hold"

    def hold(event: Any) -> None:
        if action_id is not None and str((event.payload or {}).get("id")) != action_id:
            return
        marker.write_text("holding", encoding="utf-8")
        while True:
            time.sleep(0.1)

    after_event(system, event_type, hold)


def _await_file(directory: Path, path: str, content: str, pid: int) -> None:
    # 工单 #308：这个文件的内容变成指定内容以后立刻终止进程（写入已经落盘、回执还没有写），
    # 用来观察自动核实按动作前快照确认动作已经完成的那一条路径。
    # 终止由一个另起的看门狗进程做：写入与回执写在同一个进程里，同进程的另一个线程
    # 抢不到这段窗口，因此看门狗盯住文件系统，看到内容就终止本进程
    marker = directory / "await-file"
    script = (
        "import os,signal,sys,time\n"
        "from pathlib import Path\n"
        "root=Path(sys.argv[1]); path=sys.argv[2]; content=sys.argv[3]\n"
        "marker=Path(sys.argv[4]); pid=int(sys.argv[5])\n"
        "deadline=time.time()+120\n"
        "while time.time()<deadline:\n"
        "    hit=False\n"
        "    for workspace in sorted(root.glob('*')):\n"
        "        try:\n"
        "            hit=(workspace/path).read_text(encoding='utf-8')==content\n"
        "        except OSError:\n"
        "            continue\n"
        "        if hit:\n"
        "            break\n"
        "    if hit:\n"
        "        marker.write_text('awaited',encoding='utf-8')\n"
        "        os.kill(pid,signal.SIGKILL if os.name!='nt' else signal.SIGTERM)\n"
        "        os._exit(0)\n"
        "    time.sleep(0.002)\n"
    )
    subprocess.Popen([sys.executable, "-c", script, str(directory), path, content, str(marker), str(pid)],
                     cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     **({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
                        if os.name == "nt" else {"start_new_session": True}))
    while True:
        time.sleep(0.05)


# ---------------------------------------------------------------------------
# 子进程入口：运行一个事项直到结束或被外部终止

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("script", type=Path, help="脚本的 JSON 文件，每一项是一个回答")
    parser.add_argument("task", help="事项任务")
    parser.add_argument("registered_commands", type=Path, nargs="?", default=None,
                        help="登记注册表的 JSON 文件，没有时省略")
    parser.add_argument("--resume-only", action="store_true",
                        help="不创建事项，只让启动恢复继续已有的 run（重启已有的数据目录）")
    parser.add_argument("--hold-after", type=str, default=None,
                        help="该事件提交以后进程停在这个位置（写下 hold 标记以后等待被终止）")
    parser.add_argument("--hold-dir", type=Path, default=None, help="hold 标记所在的目录")
    parser.add_argument("--hold-action", type=str, default=None,
                        help="只在这个调用编号的那次事件上停住")
    parser.add_argument("--workspace-files", type=Path, default=None,
                        help="工作区种子文件的 JSON（路径到内容），在事项开始以前写入")
    parser.add_argument("--await-file", type=str, default=None,
                        help="这个工作区文件变成下面的目标内容以后立刻终止进程（写入已落盘、回执未写）")
    parser.add_argument("--await-dir", type=Path, default=None,
                        help="工作区所在目录（data_dir/workspaces），await-file 的根目录")
    parser.add_argument("--await-content", type=str, default=None,
                        help="await-file 变成的内容")
    args = parser.parse_args()

    items = json.loads(args.script.read_text(encoding="utf-8"))
    registry = (json.loads(args.registered_commands.read_text(encoding="utf-8"))
                if args.registered_commands else None)
    # 挂起钩子要在系统开始运行以前注册。恢复发生在打开数据目录的时候，因此挂起时先不自动恢复，
    # 注册完钩子再恢复：这样恢复途中自动重新执行的那一次尝试也能在指定事件上停住
    system = LoopSystem.for_testing(args.data_dir, FakeAdapter(build_script(items)),
                                    resume_on_startup=args.hold_after is None)
    if args.hold_after is not None:
        _hold_after(system, args.hold_after, args.hold_dir, action_id=args.hold_action)
    if args.resume_only:
        try:
            print(json.dumps({"run_id": None, "phase": "resumed",
                              "resumed": list(system.resume_startup_runs())}, ensure_ascii=False), flush=True)
        finally:
            system.close()
        return
    run_id = system.create_run(args.task, registered_commands=registry,
                               command_versions=None if registry is None
                               else {name: 1 for name in registry})
    if args.await_file is not None:
        # 工单 #308：另起看门狗进程盯着工作区，看到目标内容落盘就终止本进程（回执来不及写）
        threading.Thread(target=_await_file,
                         args=(args.await_dir, args.await_file, args.await_content, os.getpid()),
                         daemon=True).start()
    if args.workspace_files is not None:
        workspace = system.workspace(run_id)
        for path, content in json.loads(args.workspace_files.read_text(encoding="utf-8")).items():
            workspace.write_file(path, content)
    try:
        result = system.run_until_stop(run_id)
        print(json.dumps({"run_id": run_id, "phase": result.phase,
                          "stop_reason": result.stop_reason}, ensure_ascii=False), flush=True)
    finally:
        system.close()


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# 父进程这一侧：启动、在指定位置终止、重新打开

def _spawn(data_dir: Path, script: Path, task: str, registry: Path | None, log: Path, *,
           hold_after: str | None = None, hold_dir: Path | None = None,
           hold_action: str | None = None, workspace_files: Path | None = None,
           await_file: tuple[str, str] | None = None, await_dir: Path | None = None,
           resume_only: bool = False) -> subprocess.Popen:
    environment = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    spawn = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    argv = [sys.executable, "-m", "harness.tests.process_kill"]
    if resume_only:
        argv.append("--resume-only")
    argv.extend([str(data_dir), str(script), task])
    if registry is not None:
        argv.append(str(registry))
    if hold_after is not None:
        argv.extend(["--hold-after", hold_after, "--hold-dir", str(hold_dir)])
        if hold_action is not None:
            argv.extend(["--hold-action", hold_action])
    if workspace_files is not None:
        argv.extend(["--workspace-files", str(workspace_files)])
    if await_file is not None:
        argv.extend(["--await-file", await_file[0], "--await-dir", str(await_dir),
                     "--await-content", await_file[1]])
    with log.open("wb") as output:
        return subprocess.Popen(argv, cwd=REPO_ROOT, env=environment, stdout=output,
                                stderr=subprocess.STDOUT, **spawn)


def _kill(process: subprocess.Popen) -> None:
    # 终止整个进程树：Windows 用 taskkill /T /F，其他系统给进程组发 SIGKILL（与 test_system_stop.py 相同）
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(STARTUP_TIMEOUT_SEC)


def _log_text(log: Path) -> str:
    return log.read_text(encoding="utf-8", errors="replace")


def _wait_for_marker(marker: Path, process: subprocess.Popen, log: Path) -> None:
    # 等待工具执行中的进程写下标记；进程在此之前退出时报告它的日志
    deadline = time.monotonic() + STARTUP_TIMEOUT_SEC
    while time.monotonic() < deadline:
        if marker.exists():
            return
        if process.poll() is not None:
            raise AssertionError(f"the run ended before the interrupt point: {_log_text(log)}")
        time.sleep(0.05)
    raise TimeoutError(f"the interrupt point was not reached: {_log_text(log)}")


class Interrupted:
    # 一次真实的中断与重启。before 是终止前打开的系统，after 是重新打开的系统（启动恢复已经跑过）。
    # 两个系统共享同一份事件日志：终止前的断言读 before_events（恢复之前读出的快照），
    # 重启后的断言直接查 after
    def __init__(self, before: LoopSystem, after: LoopSystem, run_id: str, log: Path) -> None:
        self.before = before
        self.after = after
        self.run_id = run_id
        self.log = log
        self.before_events: list[Any] = []

    def close(self) -> None:
        self.after.close()
        self.before.close()

    def __enter__(self) -> "Interrupted":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def interrupted(data_dir: Path, script: Sequence[dict[str, Any]], *,
                tail: Sequence[dict[str, Any]] | None = None,
                task: str = "build echo",
                registered_commands: dict[str, Any] | None = None,
                workspace_files: dict[str, str] | None = None,
                started: Path | None = None,
                hold_after: str | None = None,
                hold_action: str | None = None,
                await_file: tuple[str, str] | None = None,
                resume_after: bool = True) -> Interrupted:
    # resume_after 为假时 after 打开以后不走启动恢复（连续中断的场景用 restarted 的子进程恢复，
    # 父进程不再碰这份日志，避免重复恢复污染事件）
    # 在真实子进程里运行一个事项，在指定的时刻终止它，再用同一个数据目录重新打开系统走启动恢复。
    # tail 是重启以后模型继续用的脚本（中断前的脚本已经用完）
    # await_file 是（路径，内容）：这个文件变成这个内容以后子进程自己终止（写入已落盘、回执未写，
    # 工单 #308 的自动核实路径）；父进程只等着进程自己退出
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    work = data_dir.parent
    log = work / "run.log"
    hold_dir = work / "hold"
    hold_dir.mkdir(exist_ok=True)

    script_file = work / "script.json"
    script_file.write_text(json.dumps(list(script), ensure_ascii=False), encoding="utf-8")
    registry_file = None
    if registered_commands is not None:
        registry_file = work / "registry.json"
        registry_file.write_text(json.dumps(registered_commands, ensure_ascii=False), encoding="utf-8")
    files_file = None
    if workspace_files is not None:
        files_file = work / "workspace-files.json"
        files_file.write_text(json.dumps(workspace_files, ensure_ascii=False), encoding="utf-8")

    process = _spawn(data_dir, script_file, task, registry_file, log, hold_after=hold_after,
                     hold_dir=hold_dir, hold_action=hold_action, workspace_files=files_file,
                     await_file=None if await_file is None else (await_file[0], await_file[1]),
                     await_dir=None if await_file is None else data_dir / "workspaces")
    try:
        if await_file is not None:
            process.wait(STARTUP_TIMEOUT_SEC)
        elif started is not None:
            _wait_for_marker(Path(started), process, log)
        elif hold_after is not None:
            _wait_for_marker(hold_dir / "hold", process, log)
        else:
            process.wait(STARTUP_TIMEOUT_SEC)
    finally:
        if process.poll() is None:
            _kill(process)

    before = LoopSystem.for_testing(data_dir, FakeAdapter([]), resume_on_startup=False)
    run_id = next(item for item in before.store.list_run_ids()
                  if any(event.type == EventType.RUN_CREATED
                         for event in before.store.list_events(item)))
    before_events = before.store.list_events(run_id)
    after = LoopSystem.for_testing(data_dir, FakeAdapter(build_script(tail or [])),
                                   resume_on_startup=resume_after)
    result = Interrupted(before, after, run_id, log)
    result.before_events = before_events
    return result


def restarted(data_dir: Path, script: Sequence[dict[str, Any]], *,
              started: Path | None = None,
              kill: bool = True,
              resume_after: bool = True,
              restart_round: int = 2,
              hold_after: str | None = None,
              hold_action: str | None = None) -> Interrupted:
    # 重新启动一个已经存在的数据目录：启动恢复继续未结束的 run，在指定的时刻终止它。
    # 用于连续中断：一次自动重新执行以后再次中断，重启后观察有没有新的尝试或者决定请求。
    # script 是这一次重启以后模型继续用的脚本；kill 为假时让子进程运行到停止（不终止）。
    # resume_after 为假时 after 打开以后不走启动恢复（父进程不再碰这份日志，避免重复恢复污染事件）。
    # hold_after 与 hold_action 让恢复途中（自动重新执行的那一次尝试）在指定事件上停住再被终止
    data_dir = Path(data_dir)
    work = data_dir.parent
    log = work / f"restart-{restart_round}.log"
    script_file = work / f"restart-script-{restart_round}.json"
    script_file.write_text(json.dumps(list(script), ensure_ascii=False), encoding="utf-8")
    hold_dir = work / f"hold-{restart_round}"
    hold_dir.mkdir(exist_ok=True)

    process = _spawn(data_dir, script_file, "restart", None, log, resume_only=True,
                     hold_after=hold_after, hold_dir=hold_dir, hold_action=hold_action)
    try:
        if hold_after is not None:
            _wait_for_marker(hold_dir / "hold", process, log)
        elif started is not None:
            _wait_for_marker(Path(started), process, log)
        else:
            process.wait(STARTUP_TIMEOUT_SEC)
    finally:
        if kill and process.poll() is None:
            _kill(process)

    before = LoopSystem.for_testing(data_dir, FakeAdapter([]), resume_on_startup=False)
    run_id = next(item for item in before.store.list_run_ids()
                  if any(event.type == EventType.RUN_CREATED
                         for event in before.store.list_events(item)))
    before_events = before.store.list_events(run_id)
    after = LoopSystem.for_testing(data_dir, FakeAdapter([]), resume_on_startup=resume_after)
    result = Interrupted(before, after, run_id, log)
    result.before_events = before_events
    return result


# ---------------------------------------------------------------------------
# 查询：两个系统都可以用的最小读取

def events(system: LoopSystem, run_id: str, event_type: str | None = None) -> list[Any]:
    items = system.store.list_events(run_id)
    return items if event_type is None else [item for item in items if item.type == event_type]


def tool_attempts(system: LoopSystem, run_id: str, action_id: str) -> list[dict[str, Any]]:
    # 一个逻辑动作的每一次尝试：tool_started 的载荷，带上这一次尝试的结果事件种类
    started = [event for event in events(system, run_id, EventType.TOOL_STARTED)
               if str((event.payload or {}).get("id")) == action_id]
    called = events(system, run_id, EventType.TOOL_CALLED)
    attempts: list[dict[str, Any]] = []
    for event in started:
        payload = dict(event.payload or {})
        attempts.append({**payload, "event_id": event.event_id, "result_type": next(
            (item.type for item in called
             if str((item.payload or {}).get("id")) == action_id
             and str((item.payload or {}).get("activation_id")) == payload.get("activation_id")), None)})
    return attempts


def unknown_action_requests(system: LoopSystem, run_id: str) -> list[dict[str, Any]]:
    return [event.payload for event in events(system, run_id, EventType.DECISION_REQUESTED)
            if (event.payload or {}).get("kind") == "unknown_action"]


def run_actions(system: LoopSystem, run_id: str) -> list[Any]:
    return Application(system).query("run.actions", RunActions(run_id=run_id)).data.actions


def run_recovery(system: LoopSystem, run_id: str) -> Any:
    return Application(system).query("run.recovery", RunRecovery(run_id=run_id)).data