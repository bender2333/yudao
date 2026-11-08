# 故障矩阵第 10 行的「重启不重置已用时间与次数」：进程重启以后从事件恢复，连续累计
# （恢复契约与故障矩阵 docs/design/recovery-contract-and-fault-matrix.md「故障矩阵」；基础规则第三条）。
# 工单 #350：已用的运行时间与次数在每个安全节点写入事件，进程重启以后从事件恢复，连续累计；
# 等待（等待模型服务、等待用户决定、等待机器、等待桌面）期间不计入运行时间。
# 两条重启场景都用真实的子进程终止，不模拟抛异常，不用 mock；等待场景是同进程的真实等待。
# 中断与重启的辅助代码在 harness/tests/process_kill.py。

import json
import sys
import time
import uuid

from harness.adapters.base import ProviderError
from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.event_store import Command
from harness.models import EventType, Usage
from harness.proposals import delivery, delivery_turn, judgement, product_spec, review, review_turn
from harness.projection import saved_decisions
from harness.runtime import LoopSystem
from harness.tests import process_kill as killed
from harness.tests.helpers import after_event, quality_turns

ECHO = "import sys\nprint(sys.argv[1])\n"
CHECKS = {"smoke": {"command": f"\"{sys.executable.replace(chr(92), chr(47))}\" -c \"print('smoke ok')\""}}
# 中断以前的激活不跑检查；重启以后两个部门的真实检查都跑完，受控时钟再把运行时间推过上限。
# 质检用信号等待工程检查完成，保证两个激活覆盖同一运行段，核对并发结算也保留这一段时间。
# 上限取 30 秒只需要远大于中断之前那一次真实激活的用时；达到上限的时点由检查回执的事件决定，
# 不再靠一次睡满的检查把墙钟等过上限（工单 #1462，与工单 #1520 同一做法）。
TIME_LIMIT_SEC = 30


def _overlapping_checks(tmp_path):
    signals = tmp_path / "check-signals"
    signals.mkdir()
    script = tmp_path / "overlapping-checks.py"
    script.write_text("""import sys
import time
from pathlib import Path

signals = Path(sys.argv[1])
department = sys.argv[2]
timeout = float(sys.argv[3])

def wait_for(name):
    deadline = time.monotonic() + timeout
    while not (signals / name).exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"waiting for {name}")
        time.sleep(0.01)

if department == "engineering":
    wait_for("quality-ready")
    (signals / "engineering-finished").touch()
else:
    (signals / "quality-ready").touch()
    wait_for("engineering-finished")
""", encoding="utf-8")
    command = (f'"{sys.executable.replace(chr(92), chr(47))}" "{script.as_posix()}" '
               f'"{signals.as_posix()}"')
    return {department: {"command": f"{command} {department} {killed.STARTUP_TIMEOUT_SEC}"}
            for department in ("engineering", "quality")}


class _RunClock:
    # 运行时间读的时钟（工单 #1520）：读数由测试推到哪儿，「运行时间用完」就发生在哪儿，与真实时长无关。
    # 只替换运行时间的累计与判断（LoopSystem.for_testing 的 run_clock）；真实等待与 latency_ms 仍是真实时钟
    def __init__(self) -> None:
        self.seconds = 0.0

    def __call__(self) -> float:
        return self.seconds


def _call(identity, name, arguments):
    return {"id": identity, "call_id": identity, "type": "function_call", "name": name,
            "arguments": json.dumps(arguments)}

def _usage(events):
    # 最后一个 activation_finished 记下的累计已用量；没有这样的事件时为空
    finished = [event for event in events if event.type == EventType.ACTIVATION_FINISHED]
    if not finished:
        return None
    payload = finished[-1].payload or {}
    return (payload.get("elapsed_ms"), payload.get("activations"), payload.get("model_steps"))

def _event_counts(events):
    activations = len([event for event in events if event.type == EventType.DEPARTMENT_ACTIVATED])
    steps = len([event for event in events if event.type == EventType.MODEL_REQUESTED])
    return activations, steps

def test_restart_keeps_accumulated_time_and_counts(tmp_path):
    # 验收一：run 在运行中被终止进程，重启以后自动继续，已用的运行时间、激活次数与模型步数
    # 与终止之前连续，恢复不重新计数
    data_dir = tmp_path / "data"
    # 脚本按部门给出（工单 #878：PRD 被接纳以后工程与质检同时工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）：
    # 子进程里产品提交规格、工程读取文件；重启以后父进程里工程交付、质检核验
    # 质检也要给脚本（工单 #943：工单 #935 查出的同一处隐患。PRD 被接纳以后质检会话也发起模型请求，
    # 没有它的脚本时假模型报「脚本用尽」，整个 run 以 provider_error 提前结束，
    # 用例在到达中断点以前就失败；这里的日志是空的，风险窗口比 #935 窄，但成因相同）
    script = {"product": [{"proposal": product_spec()}],
              "engineering": [{"output": [_call("call-read", "read_file", {"path": "notes.txt"})]}],
              "quality": [{"proposal": {"kind": "quality_auto"}}]}
    tail = {"engineering": [{"proposal": delivery(check_names=["smoke"]), "writes": {"src/echo.py": ECHO},
                             "checks": CHECKS}],
            "quality": [{"proposal": judgement("smoke")},
                        {"proposal": review("release", "checks passed on the current snapshot"),
                         "checks": CHECKS}]}

    with killed.interrupted(data_dir, script, tail=tail,
                            workspace_files={"notes.txt": "re-execute reads the same bytes\n"},
                            hold_after="tool_started", hold_action="call-read") as run:
        before = run.before_events
        before_usage = _usage(before)
        assert before_usage is not None, "终止以前至少完成过一次激活，已用量应当已经写入事件"
        before_elapsed, before_activations, before_steps = before_usage
        settled = max(index for index, event in enumerate(before)
                      if event.type == EventType.ACTIVATION_FINISHED)
        assert (before_activations, before_steps) == _event_counts(before[:settled + 1]), "写入的累计次数与已结束的事件数一致"

        finished = run.after.run_until_stop(run.run_id)
        assert finished.status == "done", "重启以后自动继续到放行"

        # 结果确实交还了模型（工单 #943）：运行因为提供方报错提前结束的时候，
        # 重启与交还都没有发生，「已用的时间连续」就成了一句空话
        verified = [event.payload for event in killed.events(run.after, run.run_id, "action_verified")
                    if (event.payload or {}).get("id") == "call-read"]
        assert len(verified) == 1, "这一次读取的结果交还了模型"
        assert verified[0]["resolution"] == "handed_back"
        assert verified[0]["ok"] is False
        # 读取没有被再运行：整个 run 里只有最初那一次调用
        started = [event.payload for event in killed.events(run.after, run.run_id, "tool_started")
                   if (event.payload or {}).get("id") == "call-read"]
        assert len(started) == 1

        after = run.after.store.list_events(run.run_id)
        after_elapsed, after_activations, after_steps = _usage(after)
        assert after_elapsed >= before_elapsed, "已用时间在重启前后单调不减"
        assert after_activations >= before_activations, "激活次数在重启前后单调不减"
        assert after_steps >= before_steps, "模型步数在重启前后单调不减"
        after_counts = _event_counts(after)
        assert (after_activations, after_steps) == after_counts, "累计次数与事件数一致"
        added = after[len(before):]
        unsettled = [event for event in before[settled + 1:] + added
                     if event.type == EventType.DEPARTMENT_ACTIVATED]
        assert after_activations == before_activations + len(unsettled), "累计激活数恰好推进了上个检查点以后的新增激活"

def test_accumulated_time_reaches_a_short_limit_after_restart(tmp_path):
    # 验收二：短的运行时间上限，进程终止并重启以后按累计的已用时间达到上限，以运行时间上限的停止原因停止。
    # 断言只核对事件推出的关系：中断时 run 还没有以运行时间上限停止；重启以后的累计不小于终止前
    # 记录的累计（累计在进程终止与重启之间连续）并且达到上限。
    # 工单 #1462：中断点（第一个 activation_finished）排在第一个安全节点之后，机器忙时激活自己的用时
    # 可以越过短上限，运行会在中断以前停下。修法按测试分层 docs/design/test-pyramid.md「测试的写法」第 7 条：
    # 重启以后不再按墙钟等出上限，改由受控时钟在检查回执提交以后把累计推过上限（与工单 #1520 同一做法）
    data_dir = tmp_path / "data"
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    script = {"product": [{"proposal": product_spec()}]}
    checks = _overlapping_checks(tmp_path)
    tail = {"engineering": [{"proposal": delivery(check_names=["slow"]),
                             "checks": {"slow": checks["engineering"]}}],
            "quality": [{"checks": {"synchronize": checks["quality"]}},
                        {"proposal": {"kind": "quality_auto"}}]}
    clock = _RunClock()

    with killed.interrupted(data_dir, script, tail=tail, run_time_limit_sec=TIME_LIMIT_SEC,
                            hold_after="activation_finished", resume_after=False) as run:
        before_usage = _usage(run.before_events)
        assert before_usage is not None, "中断以前至少完成过一次激活，累计已用量已经写入事件"
        before_elapsed = before_usage[0]
        stops = [(event.payload or {}).get("stop_reason") for event in run.before_events]
        assert "time_limit" not in stops, f"中断时 run 已经以运行时间上限停止，停止原因 {stops}"

        # 重启以后自己打开系统，交进受控时钟：两个部门的真实检查都跑完（质检的检查等工程的检查写完信号，
        # 它的回执因此排在工程检查之后）时，订阅方把时钟推过上限，下一个安全节点一定看见运行时间用完，
        # 上限与真实用时都不参与判定。这样「中断在达到上限之前」由事件与时钟决定，不再靠一次长睡
        run.after.close()
        after = LoopSystem.for_testing(data_dir, FakeAdapter(killed.build_script(tail)),
                                       run_clock=clock, resume_on_startup=False)
        try:
            def reach_the_limit(event):
                payload = event.payload or {}
                if payload.get("name") != "run_check" or event.department != "quality":
                    return
                clock.seconds = float(TIME_LIMIT_SEC + 1)

            after_event(after, EventType.TOOL_CALLED, reach_the_limit)
            resumed = after.resume_startup_runs()
            assert run.run_id in resumed, "重启以后取得了这个 run 的执行权并继续"

            finished = after.project(run.run_id)
            assert (finished.status, finished.stop_reason) == ("failed", "time_limit")

            after_events = after.store.list_events(run.run_id)
            # 受控时钟由质检检查的回执推动：两个部门的检查都在运行时间用完以前跑完、并通过，
            # 达到上限不是因为检查被跳过（#1520 的同一口径：先后落在事件日志上）
            receipts = [index for index, event in enumerate(after_events)
                        if event.type == EventType.TOOL_CALLED
                        and (event.payload or {}).get("name") == "run_check"]
            assert len(receipts) == 2, f"两个部门的检查各自写下一条回执，实际 {receipts}"
            assert all((after_events[index].payload or {}).get("ok") is True for index in receipts), \
                "两个部门的检查都通过"
            failed_at = next(index for index, event in enumerate(after_events)
                             if event.type == EventType.RUN_FAILED)
            assert failed_at > receipts[-1], "两个部门的检查都在运行时间用完以前跑完"
        finally:
            after.close()

        after_usage = _usage(after_events)
        assert after_usage is not None, "重启以后的激活结束事件记下了累计已用量"
        assert after_usage[0] >= before_elapsed, \
            f"重启后累计 {after_usage[0]}ms 不小于终止前记录的 {before_elapsed}ms，重启没有重新计数"
        assert after_usage[0] >= TIME_LIMIT_SEC * 1000, \
            f"重启后累计 {after_usage[0]}ms，达到 {TIME_LIMIT_SEC} 秒的运行时间上限"
        assert after_usage[1:] == _event_counts(after_events), "累计次数与事件数一致"

def test_waiting_for_a_decision_is_excluded_from_run_time(tmp_path):
    # 验收三：等待用户决定期间不计入运行时间
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    script = {
        "product": [FakeTurn(proposal=product_spec(), usage=Usage(input_tokens=100, output_tokens=20))],
        "engineering": [ProviderError("model is not available", reason="provider_unavailable"),
                        delivery_turn(files={"src/echo.py": ECHO}, checks=CHECKS)],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }
    data_dir = tmp_path / "data"
    system = LoopSystem.for_testing(data_dir, FakeAdapter(script))
    try:
        wall_started = time.monotonic()
        run_id = system.create_run("build an echo CLI")
        blocked = system.run_until_stop(run_id)
        assert blocked.status == "running", "模型引用不可用时等待用户决定"

        # 等待 5 秒就够：累计只记录不含等待的那几段，整段墙钟比累计至少多出这一段等待，
        # 与机器快慢无关（工单 #410）
        waited_sec = 5
        time.sleep(waited_sec)

        _position, decisions = saved_decisions(system.store, statuses=("open",))
        assert len(decisions) == 1
        [decision] = decisions
        command = Command(str(uuid.uuid4()), "decision.answer", "sha256:continue:1", "user:local")
        system.orchestrator.answer_decision(decision.decision_id, "continue", None, base_version=1,
                                            command=command)
        assert system.run_until_stop(run_id).status == "done"

        # 核对等待没有计入运行时间：累计的已用时间小于这一整段过程实际经过的墙钟时间。
        # 这条关系与机器快慢无关，负载重时墙钟变长而累计不计入等待，两边的差距只会更大
        wall_ms = int((time.monotonic() - wall_started) * 1000)
        elapsed_ms, _activations, _steps = _usage(system.store.list_events(run_id))
        assert elapsed_ms is not None
        assert elapsed_ms < wall_ms, \
            f"整段经过 {wall_ms}ms，其中等待 {waited_sec} 秒，累计运行时间只有 {elapsed_ms}ms"
    finally:
        system.close()
