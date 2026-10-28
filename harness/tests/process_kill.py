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
#   {"proposal": {...}}      提交一种提案（product_spec、delivery_spec 等）
#   {"output": [...]}        一次回答的全部输出条目（自己写调用，例如指定编号的一次读取）
#   其余字段                  FakeTurn 的字段（checks、transcript、files 等）
#
# 终止位置有三条：
#   started=标记路径     检查与登记命令的真实进程写下 started 以后终止（工具执行到一半）
#   hold_after=事件种类  该事件提交以后进程停住（读取这类同步执行的工具只能停在这里），
#                        给出 hold_action 时只在那一个调用编号的事件上停
#   await_file=（路径，内容） 工作区文件变成这个内容、回执还没有写入的那一刻进程停住（工单 #308）
# 三条都不给时子进程运行到结束，不终止。
# 终止时先停 Yudao 进程本身、等它退出，再收掉它留下的子进程（工单 #338）：子进程是另起进程组启动的，
# 与 Yudao 进程不同组，同时终止时谁先死不确定，子进程先死会让这次动作的回执被写下来
#
# 子进程入口：python -m harness.tests.process_kill <数据目录> <脚本 JSON> <事项任务>
# 建档（工单 #317）的额外动作：--onboard 与 --onboard-source 接入已有项目并开始建档事项，取代 create_run；
# --settle 在 run 结束以后结算；--answer-revise 在结算以后回答「提出修改」并写下修改意见。
# --hold-after onboarding_revision_started 停在修改轮的事件提交以后、新 run 建立以前。

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
import traceback
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from harness.adapters.fake import SHARED_LIST_SCRIPT_PREFIX, FakeAdapter, FakeTurn
from harness.app.application import Application
from harness.app.project_queries import RunActions, RunRecovery
from harness.event_store import Command, EventStore
from harness.models import EventType, ProjectEventType
from harness.projection import saved_decisions
from harness.proposals import delivery_turn, product_spec_turn, review_turn
from harness.providers.call import ModelResponse
from harness.runtime import LoopSystem
from harness.tests.helpers import after_event, quality_turns

REPO_ROOT = Path(__file__).resolve().parents[2]
# 子进程启动、超时与等待退出的上限；真实进程要走文件系统与进程表，比内存里的操作慢
STARTUP_TIMEOUT_SEC = 300
_TURN_FACTORIES = {"product_spec": product_spec_turn, "delivery_spec": delivery_turn,
                   "qa_review": review_turn}
# 工厂自己按请求取依据版本，字段名与 shape 也不一样：这几项不进工厂参数
_FACTORY_SKIP_FIELDS = frozenset({"kind", "basis_product_spec_hash", "basis_delivery_spec_hash",
                                  "check_names", "known_risks"})


def build_script(items: Sequence[dict[str, Any]] | Mapping[str, Sequence[dict[str, Any]]]) -> Any:
    # 把 JSON 脚本项变成 FakeAdapter 的脚本项：
    #   {"proposal": {...}}   提交一种提案（product_spec、delivery_spec 等）
    #   {"output": [...]}     一次回答的全部输出条目（自己写调用，例如指定编号的一次读取）
    #   其余字段              FakeTurn 的字段（checks、transcript、files 等）
    # 提案与检查可以写在同一项里：建档的结构说明与基线核验要求检查回执绑定同一次激活（design 第 4.1 节）。
    # 只有提案的项仍然直接给出提案对象，行为与 #307 建立时相同
    # 正式成果的提案（product_spec、delivery_spec、qa_review）换成工厂（工单 #471）：
    # 脚本项只写提案内容，依据版本由工厂从请求里的当前版本取
    # 脚本可以按会话给出（工单 #557）：给的是一个字典时每个会话各有一份脚本，
    # 同时运行的会话各自取用自己的，不按请求的先后顺序抢同一个队列
    if isinstance(items, Mapping):
        return {key: build_script(value) for key, value in items.items()}
    script: list[Any] = []
    for item in items:
        if "output" in item:
            script.append(ModelResponse(output=[dict(entry) for entry in item["output"]]))
            continue
        rest = {key: value for key, value in item.items() if key != "proposal"}
        proposal = dict(item["proposal"]) if "proposal" in item else None
        if (proposal or {}).get("kind") == "quality_auto":
            # 质检的脚本（工单 #557）：质检关注「PRD 被接纳」，它的轮数随 PRD 的版本数与交付的到达变化，
            # 每一轮按这一轮开始时有没有交付决定做什么（预测性探索或核验）。这一项给出若干轮，
            # 实际用掉几轮由运行决定
            script.extend(quality_turns(proposal.get("verdict", "release"),
                                        proposal.get("rationale", "checks passed on the current snapshot"),
                                        times=int(proposal.get("times", 4))))
            continue
        factory = _TURN_FACTORIES.get((proposal or {}).get("kind"))
        if factory is not None:
            # 依据字段交给工厂从请求里取：脚本项里写了的也丢掉，工厂读到的当前版本才是 host 端。
            # 只有交付提案带 writes/checks：脚本项的 writes（路径到内容）与 checks（检查名到进程）
            # 交给工厂生成 FakeTurn 的同名字段，质检提案的 checks 直接套在 FakeTurn 上
            fields = {key: value for key, value in proposal.items()
                      if key not in _FACTORY_SKIP_FIELDS}
            if factory is delivery_turn:
                # 提案的 files 只是文件名：内容由脚本项的 writes 给，没有 writes 时用工厂默认内容
                content = rest.pop("writes", {})
                fields["files"] = content or {name: "import sys\nprint(sys.argv[1])\n"
                                              for name in fields.pop("files", []) or ["src/echo.py"]}
                fields["checks"] = {name: 0 for name in fields.get("check_names") or []}
            script.append(lambda call, factory=factory, fields=fields, rest=rest: _with_fields(
                factory(**fields)(call), rest))
            continue
        if "proposal" not in item:
            script.append(FakeTurn(**item))
        elif rest:
            script.append(FakeTurn(proposal=proposal, **rest))
        else:
            script.append(proposal)
    return script

def _with_fields(turn: Any, rest: dict[str, Any]) -> FakeTurn:
    # product_spec_turn 返回的是提案 dict，另外两个工厂返回 FakeTurn：统一成 FakeTurn。
    # 工厂把提案里的 check_names 生成为 {name: 0} 的 checks、把 files 生成为 writes；
    # 脚本项另外给 writes/checks 时按脚本项的覆盖（值分别是路径到内容、检查名到进程）
    if not isinstance(turn, FakeTurn):
        turn = FakeTurn(proposal=turn)
    if not rest:
        return turn
    return replace(turn, **rest)


def _hold_after(system: LoopSystem, event_type: str, directory: Path, *,
                action_id: str | None = None, session_prefix: str | None = None) -> None:
    # 在指定事件提交以后停在这个位置：写下 hold 标记以后一直等待，由父进程终止这个进程。
    # 同步执行的工具（读取、写入、编辑、删除、移动）没有可以等待的子进程，只能在这一刻停住，
    # 这次动作的结果因此没有落盘；父进程见到 hold 标记以后终止，恢复时这次动作的结果未知。
    # 给出 action_id 时只在这个调用编号的那次事件上停（同一个工具的前几次调用不算）。
    # 给出 session_prefix 时只在这个会话的事件上停（工单 #475：停住某个会话的一次模型请求，
    # 用来观察会话进行中重新启动以后这个会话怎样继续）。
    # 恢复途中注册这个钩子时，停住的是恢复处置那一步；恢复不再自动重新执行动作（工单 #581）
    marker = directory / "hold"

    def hold(event: Any) -> None:
        if action_id is not None and str((event.payload or {}).get("id")) != action_id:
            return
        if session_prefix is not None and not str(event.session_id or "").startswith(session_prefix):
            return
        marker.write_text("holding", encoding="utf-8")
        while True:
            time.sleep(0.1)

    after_event(system, event_type, hold)


# 子进程这一侧的辅助

def _answer_revise(system: LoopSystem, project_id: str | None, note: str) -> str | None:
    # 子进程里回答等待中的初始 PRD 请求「提出修改」：决定请求在项目流中，不属于任何 run。
    # 返回新建的修改轮 run 编号（调用方一般在事件提交以后就停住，用不到它）
    _position, open_decisions = saved_decisions(system.store, statuses=("open",))
    candidates = [item for item in open_decisions if item.kind == "initial_prd"
                  and (project_id is None or item.project_id == project_id)]
    [decision] = candidates
    command = Command(str(uuid.uuid4()), "decision.answer", f"sha256:revise:{decision.version}", "user:local")
    return system.orchestrator.answer_decision(
        decision.decision_id, "revise", note, base_version=decision.version, command=command)


def _hold_before_receipt(data_dir: Path, directory: Path, path: str, content: str,
                         *, action_id: str | None = None) -> None:
    # 工单 #308：在这个工作区文件变成指定内容、回执还没有写入的那一刻停住。
    # 文件写入与回执写在同一个进程的同一个调用栈上（engine.py：执行动作以后立刻写回执），
    # 由外部进程盯着文件系统来制造这个时刻是抢不到的，因此用 sys.setprofile 在本线程内
    # 拦住回执的写入动作：写入回执的函数刚开始执行的那一刻，文件已经在磁盘上，回执还没有写。
    # 拦住以后本线程一直等待，由父进程终止本进程（工单 #338）
    from harness.recording import StepRecorder

    code = StepRecorder.tool_called.__code__
    marker = directory / "await-file"

    def profile(frame: Any, event: str, _arg: Any) -> None:
        if event != "call" or frame.f_code is not code:
            return
        call = frame.f_locals.get("call")
        if action_id is not None and str((call or {}).get("id")) != action_id:
            return
        workspace = _workspace_of(data_dir, frame, path)
        if workspace is None or workspace.read_text(encoding="utf-8") != content:
            return
        marker.write_text("awaited", encoding="utf-8")
        sys.setprofile(None)
        while True:
            time.sleep(0.1)

    sys.setprofile(profile)


def _workspace_of(data_dir: Path, frame: Any, path: str) -> Path | None:
    # 回执写入点上的 request 带着 run 编号，工作区就在这个数据目录下的 workspaces/<run 编号>
    run_id = getattr(frame.f_locals.get("request"), "run_id", None)
    if run_id is None:
        return None
    candidate = data_dir / "workspaces" / str(run_id) / path
    return candidate if candidate.exists() else None


def _failed_attempt(system: LoopSystem, run_id: str) -> dict[str, Any]:
    # 运行因为模型侧的失败结束时，写明是哪一次请求出的问题（工单 #935）：
    # 「运行提前结束」这句话本身看不出原因，读者只看到 stop_reason，
    # 不知道是哪个会话失败、按部门给出的脚本是不是用尽了
    failed = [event for event in system.store.list_events(run_id)
              if event.type == EventType.MODEL_ATTEMPT_FAILED]
    if not failed:
        return {}
    event = failed[-1]
    department = event.department or ""
    session = event.session_id or ""
    return {"failed_session": f"{session}（{department}）" if department else session,
            "failed_error": event.error or ""}


# ---------------------------------------------------------------------------
# 子进程入口：运行一个事项直到结束或被外部终止

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("script", type=Path, help="脚本的 JSON 文件，每一项是一个回答")
    parser.add_argument("task", help="事项任务")
    parser.add_argument("--resume-only", action="store_true",
                        help="不创建事项，只让启动恢复继续已有的 run（重启已有的数据目录）")
    parser.add_argument("--run-time-limit", type=int, default=None,
                        help="run 的运行时间上限（秒），给出时按这个上限创建 run（工单 #350）")
    parser.add_argument("--hold-after", type=str, default=None,
                        help="该事件提交以后进程停在这个位置（写下 hold 标记以后等待被终止）")
    parser.add_argument("--hold-dir", type=Path, default=None, help="hold 标记所在的目录")
    parser.add_argument("--hold-action", type=str, default=None,
                        help="只在这个调用编号的那次事件上停住")
    parser.add_argument("--hold-session", type=str, default=None,
                        help="只在这个会话编号前缀的事件上停住（工单 #475：会话进行中重新启动）")
    parser.add_argument("--workspace-files", type=Path, default=None,
                        help="工作区种子文件的 JSON（路径到内容），在事项开始以前写入")
    parser.add_argument("--onboard", action="store_true",
                        help="接入已有项目并开始建档事项（取代 create_run），源目录由 --onboard-source 给出")
    parser.add_argument("--onboard-source", type=Path, default=None, help="建档的源目录")
    parser.add_argument("--project-name", default="已有项目", help="建档项目的名称")
    parser.add_argument("--settle", action="store_true", help="run 运行到停止以后结算这一次 run")
    parser.add_argument("--answer-revise", default=None,
                        help="结算以后回答等待中的初始 PRD 请求：给出修改意见")
    parser.add_argument("--await-file", type=str, default=None,
                        help="这个工作区文件变成下面的目标内容以后立刻终止进程（写入已落盘、回执未写）")
    parser.add_argument("--await-dir", type=Path, default=None,
                        help="工作区所在目录（data_dir/workspaces），await-file 的根目录")
    parser.add_argument("--await-content", type=str, default=None,
                        help="await-file 变成的内容")
    args = parser.parse_args()

    items = json.loads(args.script.read_text(encoding="utf-8"))
    # 挂起钩子要在系统开始运行以前注册。恢复发生在打开数据目录的时候，因此挂起时先不自动恢复，
    # 注册完钩子再恢复：这样恢复处置的那一步也能在指定事件上停住（恢复不再自动重新执行动作，工单 #581）
    system = LoopSystem.for_testing(args.data_dir, FakeAdapter(build_script(items)),
                                    resume_on_startup=args.hold_after is None)
    if args.hold_after is not None:
        _hold_after(system, args.hold_after, args.hold_dir, action_id=args.hold_action,
                    session_prefix=args.hold_session)
    if args.resume_only:
        try:
            print(json.dumps({"run_id": None, "status": "resumed",
                              "resumed": list(system.resume_startup_runs())}, ensure_ascii=False), flush=True)
        finally:
            system.close()
        return
    project_id = None
    if args.onboard:
        if args.onboard_source is None:
            parser.error("--onboard requires --onboard-source")
        # 建档事项的 run 由接入时创建：目标就是事项的工作请求
        project_id, _work_item_id, run_id = system.projects.onboard(
            args.project_name, args.task, "src", str(args.onboard_source))
    else:
        options = {} if args.run_time_limit is None else {"run_time_limit_sec": args.run_time_limit}
        run_id = system.create_run(args.task, **options)
    if args.await_file is not None:
        # 工单 #308、#338：在回执写入的那一刻自己停住，等父进程来终止
        _hold_before_receipt(args.data_dir, args.await_dir, args.await_file, args.await_content,
                             action_id=args.hold_action)
    if args.workspace_files is not None:
        workspace = system.workspace(run_id)
        for path, content in json.loads(args.workspace_files.read_text(encoding="utf-8")).items():
            workspace.write_file(path, content)
    try:
        result = system.run_until_stop(run_id)
        print(json.dumps({"run_id": run_id, "status": result.status,
                          "stop_reason": result.stop_reason, "error": result.error,
                          **_failed_attempt(system, run_id)}, ensure_ascii=False), flush=True)
        if args.settle:
            system.projects.settle(run_id)
        if args.answer_revise is not None:
            _answer_revise(system, project_id, args.answer_revise)
    finally:
        system.close()


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# 父进程这一侧：启动、在指定位置终止、重新打开

def _spawn(data_dir: Path, script: Path, task: str, log: Path, *,
           hold_after: str | None = None, hold_dir: Path | None = None,
           hold_action: str | None = None, hold_session: str | None = None,
           workspace_files: Path | None = None,
           onboard: Path | None = None, settle: bool = False,
           answer_revise: str | None = None,
           await_file: tuple[str, str] | None = None, await_dir: Path | None = None,
           resume_only: bool = False, run_time_limit_sec: int | None = None) -> subprocess.Popen:
    environment = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    spawn = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    argv = [sys.executable, "-m", "harness.tests.process_kill"]
    if resume_only:
        argv.append("--resume-only")
    argv.extend([str(data_dir), str(script), task])
    if hold_after is not None:
        argv.extend(["--hold-after", hold_after, "--hold-dir", str(hold_dir)])
        if hold_action is not None:
            argv.extend(["--hold-action", hold_action])
        if hold_session is not None:
            argv.extend(["--hold-session", hold_session])
    if workspace_files is not None:
        argv.extend(["--workspace-files", str(workspace_files)])
    if onboard is not None:
        argv.extend(["--onboard", "--onboard-source", str(onboard)])
    if run_time_limit_sec is not None:
        argv.extend(["--run-time-limit", str(run_time_limit_sec)])
    if settle:
        argv.append("--settle")
    if answer_revise is not None:
        argv.extend(["--answer-revise", answer_revise])
    if await_file is not None:
        argv.extend(["--await-file", await_file[0], "--await-dir", str(await_dir),
                     "--await-content", await_file[1]])
    with log.open("wb") as output:
        return subprocess.Popen(argv, cwd=REPO_ROOT, env=environment, stdout=output,
                                stderr=subprocess.STDOUT, **spawn)


def _kill(process: subprocess.Popen, signals: Path | None = None) -> None:
    # 先终止 Yudao 进程本身、等它退出，再收掉它留下的子进程（工单 #338）。
    # 检查与 bash 命令的子进程由执行环境另起进程组启动，与 Yudao 进程不同组：一次性按进程树
    # 终止时谁先死是不确定的，子进程先死会让 Yudao 进程活着走完执行后的路径，把这一次动作的
    # 回执写下来，测试就看不到「结果未知」。先终止 Yudao 进程并等它退出，再收掉子进程，
    # 两者之间就不再有竞争
    if process.poll() is not None:
        return
    child = _child_pid(signals)
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        os.kill(process.pid, signal.SIGKILL)
    # process.wait 返回就是进程已经退出。不再用进程号探测：Windows 上父进程还握着这个进程的句柄，
    # 按进程号打开总能成功，探测会一直等满 10 秒才放弃
    process.wait(STARTUP_TIMEOUT_SEC)
    from harness.tests.helpers import wait_until_stopped
    if child is None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(child), "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        try:
            os.kill(child, signal.SIGKILL)
        except OSError:
            pass
    wait_until_stopped(child)


def _child_pid(signals: Path | None) -> int | None:
    # 检查与登记命令的子进程自己写下的进程号（helpers.WAIT_FOR_RELEASE）
    if signals is None:
        return None
    try:
        return int((signals / "child.pid").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _log_text(log: Path) -> str:
    return log.read_text(encoding="utf-8", errors="replace")


def _assert_no_shared_list_script(log: Path) -> None:
    # 子进程里的违反写进子进程的输出（工单 #879）：假模型发现一条列表脚本被工程与质检同时取用时
    # 把这件事写进输出，父进程读到以后让用例失败（失败落在用例上，不是模型服务的错误）
    text = _log_text(log)
    if SHARED_LIST_SCRIPT_PREFIX not in text:
        return
    line = next(line for line in text.splitlines() if SHARED_LIST_SCRIPT_PREFIX in line)
    raise AssertionError(f"子进程里的假模型脚本被工程与质检同时取用：{line}")


def _wait_for_marker(marker: Path, process: subprocess.Popen, log: Path) -> None:
    # 等待工具执行中的进程写下标记；进程在此之前退出时报告它的日志
    # 工单 #935：子进程打印的运行结果里带着停止原因与出错的会话（见 main），
    # 「运行提前结束」这句话本身看不出原因，这里把它写明
    deadline = time.monotonic() + STARTUP_TIMEOUT_SEC
    while time.monotonic() < deadline:
        if marker.exists():
            return
        if process.poll() is not None:
            raise AssertionError(
                f"the run ended before the interrupt point: {_log_text(log)}"
                "（运行在到达中断点以前就结束了；上面的 JSON 写着停止原因与出错的会话）")
        time.sleep(0.05)
    raise TimeoutError(f"the interrupt point was not reached: {_log_text(log)}")


def _first_run_id(store: EventStore) -> str:
    # 写入的第一个 run（run 的编号由 run_created 事件给出）
    return next(item for item in store.list_run_ids()
                if any(event.type == EventType.RUN_CREATED for event in store.list_events(item)))


def _onboarding_run_id(store: EventStore, revision: bool) -> str:
    # 建档场景的 run 编号：修改轮取 onboarding_revision_started 里的编号（最后一条），
    # 第一轮取建档事项 work_item_created 里的编号
    project_id = store.list_project_ids()[0]
    events = store.list_project_events(project_id)
    if revision:
        started = [event for event in events
                   if event.type == ProjectEventType.ONBOARDING_REVISION_STARTED]
        assert started, "没有 onboarding_revision_started 事件"
        return str(started[-1].payload["run_id"])
    created = [event for event in events
               if event.type == ProjectEventType.WORK_ITEM_CREATED
               and event.payload.get("kind") == "onboarding"]
    assert created, "没有建档事项的 work_item_created 事件"
    return str(created[-1].payload["run_id"])


def _open_after_kill(path: Path) -> EventStore:
    # 进程刚被终止时，GitHub 的 Windows 运行机上事件库的文件还会被别的进程短暂占用（2026-10-18
    # run 39103301202：终止以后立刻只读打开，10 个用例都报 disk I/O error；原先 _kill 里按进程号
    # 探测的等待总是等满 10 秒，掩盖了这一点）。在等待上限内重试，能读出来就继续
    deadline = time.monotonic() + STARTUP_TIMEOUT_SEC
    while True:
        try:
            return EventStore(path, read_only=True)
        except sqlite3.OperationalError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.2)


_SYSTEM_INIT_FILE = Path(LoopSystem.__init__.__code__.co_filename).name
_STORE_INIT_FILE = Path(EventStore.__init__.__code__.co_filename).name


def _failed_on_the_store_open(error: BaseException) -> bool:
    # 这次失败发生在「构造系统时第一次打开事件库」这一步吗。构造系统的调用链是
    # for_testing → LoopSystem.__init__ → EventStore.__init__，紧跟 __init__ 的下一帧在
    # event_store.py 里就是这一步失败。启动序列里的某一步失败时（补做结算、补建 run、启动恢复）
    # 中间还会多一层，那时重来会让这些步骤做两次，因此不重试
    frames = traceback.extract_tb(error.__traceback__)
    for index, frame in enumerate(frames):
        if frame.name != "__init__" or Path(frame.filename).name != _SYSTEM_INIT_FILE:
            continue
        following = frames[index + 1] if index + 1 < len(frames) else None
        return following is not None and Path(following.filename).name == _STORE_INIT_FILE
    return False


def _open_system_after_kill(data_dir: Path, adapter: FakeAdapter, *,
                            resume_on_startup: bool) -> LoopSystem:
    # 进程刚被终止时，GitHub 的 Windows 运行机上事件库的文件还会被短暂占用（2026-10-18
    # run 39103301202）。探测性的只读打开与可写打开各自重试（_open_after_kill，以及 2026-10-23
    # run 39998093540 加的可写探测）都只包住「探测」那一次：探测成功、关掉以后，系统自己打开
    # 事件库（同样是可写打开，含设置 WAL）照样会失败（2026-10-28 的两条：main 6eaf09ec
    # run 40596572672 与 main 30ed23a3 run 40606862926，都在 PRAGMA journal_mode=WAL 上报
    # disk I/O error）。所以重试放在系统打开事件库这一步上，不再赌「探测成功以后文件就不再被占用」。
    #
    # 等的是：被终止的进程留下的占用释放。Windows 上进程退出与被它占着的文件真正可以再打开
    # 之间有一小段间隔（句柄回收、WAL 的 -wal 与 -shm 文件收尾都晚于进程退出）。每 0.2 秒试
    # 一次，等到 STARTUP_TIMEOUT_SEC 为止；超过上限照常抛出原来的错误，不吞掉。
    #
    # 这样重试不会让启动序列做两次：打开事件库是 LoopSystem 启动序列里第一件有副作用的事
    # （在它以前只有 data_dir 的 mkdir，幂等），这一步失败时补做结算、补建 run 与启动恢复
    # 都还没有开始，整个构造可以重来。失败在启动序列里的某一步时不重试（见
    # _failed_on_the_store_open），那种情况下重来才会让它们做两次
    deadline = time.monotonic() + STARTUP_TIMEOUT_SEC
    retries = 0
    while True:
        try:
            return LoopSystem.for_testing(data_dir, adapter, resume_on_startup=resume_on_startup)
        except sqlite3.OperationalError as error:
            if not _failed_on_the_store_open(error) or time.monotonic() >= deadline:
                raise
            retries += 1
            print(f"打开事件库失败，第 {retries} 次重试：{error}", file=sys.stderr, flush=True)
            time.sleep(0.2)


def _observe(data_dir: Path, onboarding: bool, revision: bool) -> dict[str, Any]:
    # 只读地读出终止以后、任何系统打开它以前的事件与决定请求：LoopSystem 打开数据目录时会补做结算与补建
    # 缺少的 run，「补做之前」的状态只能这样取得。读出的是一份快照，连接随即关闭，之后回读它得到的
    # 仍然是补做以后的状态
    store = _open_after_kill(Path(data_dir) / "events.sqlite")
    try:
        run_id = _onboarding_run_id(store, revision) if onboarding else _first_run_id(store)
        project_ids = store.list_project_ids()
        project_id = project_ids[0] if project_ids else None
        return {
            "run_id": run_id,
            "project_id": project_id,
            "events": store.list_events(run_id),
            "first_round_events": (store.list_events(_onboarding_run_id(store, False))
                                   if revision and project_id is not None else []),
            "project_events": ([] if project_id is None
                               else store.list_project_events(project_id)),
            "open_decisions": ([] if project_id is None else saved_decisions(
                store, projects=(project_id,), statuses=("open",))[1]),
        }
    finally:
        store.close()


class Interrupted:
    # 一次真实的中断与重启。observed 是以只读连接读出的终止以后、任何系统打开数据目录以前的事件与决定请求
    # （快照）；before 是终止后打开的系统，after 是重新打开的系统（启动恢复已经跑过）。
    # 终止前的断言读 observed，重启后的断言直接查 after
    def __init__(self, before: LoopSystem, after: LoopSystem, observed: dict[str, Any], log: Path) -> None:
        self.before = before
        self.after = after
        self.log = log
        self.observed = observed
        self.run_id = str(observed["run_id"])
        self.before_events: list[Any] = observed["events"]

    def close(self) -> None:
        self.after.close()
        self.before.close()

    def __enter__(self) -> "Interrupted":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def interrupted(data_dir: Path, script: Sequence[dict[str, Any]] | Mapping[str, Sequence[dict[str, Any]]], *,
                tail: Sequence[dict[str, Any]] | Mapping[str, Sequence[dict[str, Any]]] | None = None,
                task: str = "build echo",
                workspace_files: dict[str, str] | None = None,
                started: Path | None = None,
                hold_after: str | None = None,
                hold_action: str | None = None,
                hold_session: str | None = None,
                await_file: tuple[str, str] | None = None,
                onboard: Path | None = None,
                settle: bool = False,
                answer_revise: str | None = None,
                resume_after: bool = True,
                revision: bool = False,
                run_time_limit_sec: int | None = None) -> Interrupted:
    # resume_after 为假时 after 打开以后不走启动恢复（连续中断的场景用 restarted 的子进程恢复，
    # 父进程不再碰这份日志，避免重复恢复污染事件）
    # 在真实子进程里运行一个事项，在指定的时刻终止它，再用同一个数据目录重新打开系统走启动恢复。
    # tail 是重启以后模型继续用的脚本（中断前的脚本已经用完）
    # 建档（工单 #317）给 onboard：子进程接入这个源目录并开始建档事项，取代 create_run；
    # settle 让子进程在 run 结束以后结算，answer_revise 让它在结算以后回答「提出修改」；
    # revision 为真时 run_id 取修改轮的 run（onboarding_revision_started 里的编号），
    # 否则取建档事项的 run（work_item_created 里的编号）
    # await_file 是（路径，内容）：工作区文件变成这个内容、回执还没有写入的那一刻子进程停住
    # （工单 #308 的自动核实路径，工单 #338 起在回执写入点上拦住，不再靠外部进程抢这一刻）；
    # 父进程见到标记以后终止它
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    work = data_dir.parent
    log = work / "run.log"
    hold_dir = work / "hold"
    hold_dir.mkdir(exist_ok=True)

    script_file = work / "script.json"
    # 脚本按会话给出时是一个字典（工单 #557），按队列给出时是一个列表
    script_file.write_text(json.dumps(script if isinstance(script, Mapping) else list(script),
                                     ensure_ascii=False), encoding="utf-8")
    files_file = None
    if workspace_files is not None:
        files_file = work / "workspace-files.json"
        files_file.write_text(json.dumps(workspace_files, ensure_ascii=False), encoding="utf-8")

    await_dir = None if await_file is None else data_dir / "workspaces"
    process = _spawn(data_dir, script_file, task, log, hold_after=hold_after,
                     hold_dir=hold_dir, hold_action=hold_action, hold_session=hold_session,
                     workspace_files=files_file,
                     onboard=onboard, settle=settle, answer_revise=answer_revise,
                     await_file=None if await_file is None else (await_file[0], await_file[1]),
                     await_dir=await_dir, run_time_limit_sec=run_time_limit_sec)
    try:
        if await_file is not None:
            _wait_for_marker(await_dir / "await-file", process, log)
        elif started is not None:
            _wait_for_marker(Path(started), process, log)
        elif hold_after is not None:
            _wait_for_marker(hold_dir / "hold", process, log)
        else:
            process.wait(STARTUP_TIMEOUT_SEC)
    finally:
        _kill(process, None if started is None else Path(started).parent)

    _assert_no_shared_list_script(log)

    # 只读地观察终止以后、任何系统打开数据目录以前的事件
    observed = _observe(data_dir, onboard is not None, revision)
    before = _open_system_after_kill(data_dir, FakeAdapter([]), resume_on_startup=False)
    after = _open_system_after_kill(data_dir, FakeAdapter(build_script(tail or [])),
                                    resume_on_startup=resume_after)
    return Interrupted(before, after, observed, log)


def restarted(data_dir: Path, script: Sequence[dict[str, Any]] | Mapping[str, Sequence[dict[str, Any]]], *,
              started: Path | None = None,
              kill: bool = True,
              resume_after: bool = True,
              revision: bool = False,
              restart_round: int = 2,
              hold_after: str | None = None,
              hold_action: str | None = None) -> Interrupted:
    # 重新启动一个已经存在的数据目录：启动恢复继续未结束的 run，在指定的时刻终止它。
    # 用于连续中断：一次恢复处置以后再次中断，重启后观察有没有新的尝试或者决定请求。
    # script 是这一次重启以后模型继续用的脚本；kill 为假时让子进程运行到停止（不终止）。
    # resume_after 为假时 after 打开以后不走启动恢复（父进程不再碰这份日志，避免重复恢复污染事件）。
    # revision 为真时 run_id 取修改轮的 run（建档场景，见 interrupted）。
    # hold_after 与 hold_action 让恢复处置中的那一步在指定事件上停住再被终止（恢复不再自动重新执行动作）
    data_dir = Path(data_dir)
    work = data_dir.parent
    log = work / f"restart-{restart_round}.log"
    script_file = work / f"restart-script-{restart_round}.json"
    # 脚本按会话给出时是一个字典（工单 #557），按队列给出时是一个列表
    script_file.write_text(json.dumps(script if isinstance(script, Mapping) else list(script),
                                     ensure_ascii=False), encoding="utf-8")
    hold_dir = work / f"hold-{restart_round}"
    hold_dir.mkdir(exist_ok=True)
    process = _spawn(data_dir, script_file, "restart", log, resume_only=True,
                     hold_after=hold_after, hold_dir=hold_dir, hold_action=hold_action)
    try:
        if hold_after is not None:
            _wait_for_marker(hold_dir / "hold", process, log)
        elif started is not None:
            _wait_for_marker(Path(started), process, log)
        else:
            process.wait(STARTUP_TIMEOUT_SEC)
    finally:
        if kill:
            _kill(process, None if started is None else Path(started).parent)

    _assert_no_shared_list_script(log)

    # revision 为真时 run_id 取修改轮的 run（建档场景，见 interrupted）
    observed = _observe(data_dir, revision, revision)
    before = _open_system_after_kill(data_dir, FakeAdapter([]), resume_on_startup=False)
    after = _open_system_after_kill(data_dir, FakeAdapter([]), resume_on_startup=resume_after)
    return Interrupted(before, after, observed, log)


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