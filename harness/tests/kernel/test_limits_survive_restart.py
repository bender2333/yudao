# 基础规则第三条的第四行：达到上限记为失败或暂停，恢复不重新计数，参数修改不让它继续。
#
# 已用的运行时间、激活次数与模型步数在每个安全节点写入事件（activation_finished），
# 进程重启以后从事件恢复，连续累计（循环与收敛设计说明第 3 节，工单 #350）。
# 这里用真实的子进程中断与重启核对：跨重启单调不减，累计时间不会重新从零计。
#
# 读事件日志、写数据目录、用子进程，属于集成层。

from harness.models import EventType
from harness.proposals import engineering_plan, product_spec
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


def _script() -> list[dict]:
    return [{"proposal": product_spec()}, {"proposal": engineering_plan()}]


def test_accumulated_usage_does_not_decrease_across_a_restart(tmp_path):
    data_dir = tmp_path / "data"
    with killed.interrupted(data_dir, _script(), hold_after=_HOLD) as run:
        before = _usage(run.before_events)
        after = _usage(run.after.store.list_events(run.run_id))
        assert before is not None, "中断之前没有记录过一次已用量"
        assert after is not None, "重启以后没有记录过一次已用量"
        elapsed, activations, steps = before
        assert elapsed is not None and activations >= 1 and steps >= 1, \
            f"重启之前的已用量不完整：{before}"
        assert after[0] >= elapsed, f"已用时间从 {elapsed}ms 变成 {after[0]}ms，重启以后重新计数了"
        assert after[1] >= activations, f"激活次数从 {activations} 变成 {after[1]}，重启以后重新计数了"
        assert after[2] >= steps, f"模型步数从 {steps} 变成 {after[2]}，重启以后重新计数了"


def test_usage_keeps_accumulating_after_a_restart_instead_of_restarting(tmp_path):
    # 重启以后的累计时间继续加上重启前的那一份，不是重新从零开始计时
    data_dir = tmp_path / "data"
    with killed.interrupted(data_dir, _script(), hold_after=_HOLD) as run:
        before = _usage(run.before_events)
        assert before is not None and before[0] > 0, \
            f"重启之前已经用掉 {before[0] if before else None}ms 运行时间，才能核对连续累计"
        after = _usage(run.after.store.list_events(run.run_id))
        assert after is not None
        assert after[0] > before[0], \
            f"重启以后累计时间 {after[0]}ms 没有超过重启之前的 {before[0]}ms"


def test_the_short_time_limit_still_bites_after_a_restart(tmp_path):
    # 达到上限记为失败：累计时间跨重启连续，短上限在重启以后仍然生效，不会因为重新计数而延长
    data_dir = tmp_path / "data"
    with killed.interrupted(data_dir, _script(), hold_after=_HOLD,
                            run_time_limit_sec=3) as run:
        projection = run.after.project(run.run_id)
        assert projection.run_time_limit_sec == 3, "上限在重启以后变了"
        after = _usage(run.after.store.list_events(run.run_id))
        assert after is not None
        limit_ms = projection.run_time_limit_sec * 1000
        assert after[0] <= limit_ms + 600_000, \
            f"重启后累计 {after[0]}ms，超过上限加一次调用的最长时限 {limit_ms + 600_000}ms"