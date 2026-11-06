# 基础规则第三条的第四行：达到上限记为失败或暂停，恢复不重新计数，参数修改不让它继续。
#
# 已用的运行时间、激活次数与模型步数在每个安全节点写入事件（activation_finished），
# 进程重启以后从事件恢复，连续累计（循环与收敛 docs/design/loops-and-convergence.md「一定会停」，工单 #350）。
# 这里用真实的子进程中断与重启核对：跨重启单调不减，累计时间不会重新从零计。
#
# 读事件日志、写数据目录、用子进程，属于集成层。

import sys

from harness.models import EventType
from harness.proposals import product_spec
from harness.tests import process_kill as killed

# 中断点：一次激活结束以后。此时已用量已经写入事件，进程停在安全节点上
_HOLD = "activation_finished"


def _usage(events) -> tuple[int, int, int] | None:
    # 最后一次激活结束记录的已用量三元组
    finished = [event for event in events if event.type == EventType.ACTIVATION_FINISHED]
    if not finished:
        return None
    payload = finished[-1].payload or {}
    return payload.get("elapsed_ms"), payload.get("activations"), payload.get("model_steps")


def _script() -> dict[str, list[dict]]:
    # 脚本按部门给出（工单 #877：PRD 被接纳以后工程与质检同时工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化）。
    return {
        "product": [{"proposal": product_spec()}],
        "engineering": [{"transcript": "继续工程工作"}],
        "quality": [{"transcript": "继续质检工作"}],
    }


def _tail() -> dict[str, list[dict]]:
    # 重启以后继续用的脚本，同样按部门给出：工程交付、质检核验
    return {
        "engineering": [{"proposal": {"kind": "delivery_spec", "summary": "implemented echo CLI",
                                      "check_names": ["smoke"], "known_risks": []}}],
        "quality": [{"proposal": {"kind": "quality_auto", "verdict": "release",
                                  "rationale": "checks passed on the current snapshot", "times": 4}}],
    }


def test_accumulated_usage_does_not_decrease_across_a_restart(tmp_path):
    data_dir = tmp_path / "data"
    with killed.interrupted(data_dir, _script(), tail=_tail(), hold_after=_HOLD) as run:
        before = _usage(run.before_events)
        after = _usage(run.after.store.list_events(run.run_id))
        assert before is not None, "中断之前没有记录过一次已用量"
        assert after is not None, "重启以后没有记录过一次已用量"
        elapsed, activations, steps = before
        assert elapsed is not None and activations >= 1 and steps >= 1, \
            f"重启之前的已用量不完整：{before}"
        assert after[0] > elapsed, f"已用时间从 {elapsed}ms 变成 {after[0]}ms，重启以后重新计数了"
        assert after[1] >= activations, f"激活次数从 {activations} 变成 {after[1]}，重启以后重新计数了"
        assert after[2] >= steps, f"模型步数从 {steps} 变成 {after[2]}，重启以后重新计数了"


def test_the_short_time_limit_still_bites_after_a_restart(tmp_path):
    # 达到上限记为失败：累计时间跨重启连续，短上限在重启以后仍然生效，不会因为重新计数而延长。
    # 重启以后的工程检查真的运行 4 秒，越过 3 秒的运行时间上限，运行在下一个安全节点以 time_limit 结束
    # （与 harness/tests/test_issue_350_usage_resumes.py::test_accumulated_time_reaches_a_short_limit_after_restart 同一做法）
    data_dir = tmp_path / "data"
    with killed.interrupted(data_dir, _script(), tail=_slow_tail(tmp_path), hold_after=_HOLD,
                            run_time_limit_sec=3) as run:
        stops = [(event.payload or {}).get("stop_reason") for event in run.before_events]
        assert "time_limit" not in stops, f"中断时 run 已经以运行时间上限停止，停止原因 {stops}"
        projection = run.after.project(run.run_id)
        assert projection.run_time_limit_sec == 3, "上限在重启以后变了"
        assert (projection.status, projection.stop_reason) == ("failed", "time_limit"), \
            f"重启后累计时间越过 3 秒的上限，运行应当以 time_limit 停止：{projection.status}/{projection.stop_reason}"
        after = _usage(run.after.store.list_events(run.run_id))
        assert after is not None
        limit_ms = projection.run_time_limit_sec * 1000
        assert after[0] >= limit_ms, f"重启后累计 {after[0]}ms，达到 {limit_ms}ms 的运行时间上限"


def _slow_tail(tmp_path) -> dict[str, list[dict]]:
    # 重启以后继续用的脚本：工程的交付检查是一个真实运行 4 秒的进程，越过 3 秒的运行时间上限
    script = tmp_path / "slow-check.py"
    script.write_text("import time\n\ntime.sleep(4)\n", encoding="utf-8")
    command = f'"{sys.executable.replace(chr(92), chr(47))}" "{script.as_posix()}"'
    return {
        "engineering": [{"proposal": {"kind": "delivery_spec", "summary": "implemented echo CLI",
                                      "check_names": ["slow"], "known_risks": []},
                         "checks": {"slow": {"command": command}}}],
        "quality": [{"proposal": {"kind": "quality_auto", "verdict": "release",
                                  "rationale": "checks passed on the current snapshot", "times": 4}}],
    }