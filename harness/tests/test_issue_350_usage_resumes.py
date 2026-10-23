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
from harness.proposals import delivery, delivery_turn, product_spec, review, review_turn
from harness.projection import saved_decisions
from harness.runtime import LoopSystem
from harness.tests import process_kill as killed
from harness.tests.helpers import quality_turns

ECHO = "import sys\nprint(sys.argv[1])\n"
CHECKS = {"smoke": {"command": f"\"{sys.executable.replace(chr(92), chr(47))}\" -c \"print('smoke ok')\""}}
# 短的运行时间上限与跨过上限的那次检查：中断以前那次激活不跑检查，累计只有这一次的激活时间，
# 离上限足够远；上限取 3 秒，重启以后的检查睡满 4 秒（中断前那次激活实测不到 0.2 秒），这一次检查本身就越过上限，
# 因此「达到上限」由这一次检查保证，与中断前经过了多长时间、机器快慢都无关（工单 #410）
TIME_LIMIT_SEC = 3
SLOW_CHECK = {"slow": {"command": f"\"{sys.executable.replace(chr(92), chr(47))}\" -c \"import time; time.sleep(4)\""}}

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
    script = [{"proposal": product_spec()},
              {"output": [_call("call-read", "read_file", {"path": "notes.txt"})]}]
    tail = [{"proposal": delivery(check_names=["smoke"]), "writes": {"src/echo.py": ECHO},
             "checks": CHECKS},
            {"proposal": review("release", "checks passed on the current snapshot"), "checks": CHECKS}]

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
    # 记录的累计（累计在进程终止与重启之间连续）并且达到上限
    data_dir = tmp_path / "data"
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    script = {"product": [{"proposal": product_spec()}]}
    tail = {"engineering": [{"proposal": delivery(check_names=["slow"]), "checks": SLOW_CHECK}],
            "quality": [{"proposal": {"kind": "quality_auto"}}]}

    with killed.interrupted(data_dir, script, tail=tail, run_time_limit_sec=TIME_LIMIT_SEC,
                            hold_after="activation_finished") as run:
        before_usage = _usage(run.before_events)
        assert before_usage is not None, "中断以前至少完成过一次激活，累计已用量已经写入事件"
        before_elapsed = before_usage[0]
        stops = [(event.payload or {}).get("stop_reason") for event in run.before_events]
        assert "time_limit" not in stops, f"中断时 run 已经以运行时间上限停止，停止原因 {stops}"

        finished = run.after.project(run.run_id)
        assert (finished.status, finished.stop_reason) == ("failed", "time_limit")

        after = run.after.store.list_events(run.run_id)
        after_usage = _usage(after)
        assert after_usage is not None, "重启以后的激活结束事件记下了累计已用量"
        assert after_usage[0] >= before_elapsed, \
            f"重启后累计 {after_usage[0]}ms 不小于终止前记录的 {before_elapsed}ms，重启没有重新计数"
        assert after_usage[0] >= TIME_LIMIT_SEC * 1000, \
            f"重启后累计 {after_usage[0]}ms，达到 {TIME_LIMIT_SEC} 秒的运行时间上限"
        assert after_usage[1:] == _event_counts(after), "累计次数与事件数一致"

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
