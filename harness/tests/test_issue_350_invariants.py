# 工单 #350 的三条性质测试：
# 1. 每个 run 流以带原因的结束或等待事件收尾，原因属于停止原因的封闭清单；
# 2. 扣除声明的等待以后，已用时间不超过上限加一次调用的最长时限；
# 3. 计数在进程重启前后单调不减。
# 性质一读全部事件序列基准（44 个 JSON）；性质二、三用真实的子进程中断与重启录制，不用 mock。

import json
from pathlib import Path

from harness.models import TERMINAL_PHASES, EventType
from harness.proposals import engineering_plan, product_spec
from harness.tests import process_kill as killed

BASELINE_DIR = Path(__file__).parent / "event_sequences"
# 非终态的场景：录制在 run 结束以前停止，尾部是未收尾的激活结束，投影不在终态
PREFIX_SCENARIOS = {
    "compaction_success",
    "http_chat_stream_broken_then_success",
    "http_messages_stream_broken_then_success",
    "http_responses_retry_after_then_success",
    "http_responses_server_error_then_success",
    "http_responses_stream_broken_then_success",
    "http_responses_timeout_then_success",
    "invalid_tool_arguments",
    "retry_then_success",
    "text_only_reply",
}


def _reasons():
    return set(json.loads((Path(__file__).parents[2] / "harness" / "definitions" / "stop_reasons.json").read_text(encoding="utf-8")))


def test_every_baseline_has_a_reasoned_stop_event():
    # 性质一：到终态的 run 必有一条带封闭清单原因的结束事件（run_done、run_paused 或 run_failed）；
    # 激活结算是同一事务里后写的记录，不在收尾位置要求里
    reasons = _reasons()
    assert len(reasons) == 17
    checked = 0
    for path in sorted(BASELINE_DIR.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        events = document["events"]
        assert events, f"{path.name} 没有录到事件"
        stops = [event for event in events
                 if event["type"] in ("run_done", "run_paused", "run_failed")]
        phase = document["projection"].get("phase")
        if phase in TERMINAL_PHASES:
            assert stops, f"{path.name} 已到终态却没有结束事件"
            for stop in stops:
                reason = (stop.get("payload") or {}).get("stop_reason")
                assert reason in reasons, f"{path.name} 的停止原因 {reason!r} 不在封闭清单里"
                assert stop.get("stop_reason") == reason, f"{path.name} 的事件停止原因与载荷不一致"
            checked += 1
        else:
            assert path.stem in PREFIX_SCENARIOS, f"{path.name} 非终态却不在已知的前缀录制清单里"
    assert checked > 30, f"终态基准只有 {checked} 个"


def test_recorded_time_stays_within_limit_plus_one_call(tmp_path):
    # 性质二：扣除声明的等待以后，已用时间不超过上限加一次调用的最长时限
    data_dir = tmp_path / "data"
    script = [{"proposal": product_spec()}, {"proposal": engineering_plan()}]
    with killed.interrupted(data_dir, script, hold_after="activation_finished") as run:
        events = run.after.store.list_events(run.run_id)
        finished = [event for event in events if event.type == EventType.ACTIVATION_FINISHED]
        assert finished, "至少完成过一次激活"
        elapsed_ms = (finished[-1].payload or {}).get("elapsed_ms")
        assert elapsed_ms is not None
        projection = run.after.project(run.run_id)
        limit_ms = projection.run_time_limit_sec * 1000
        assert elapsed_ms <= limit_ms + 600_000, f"累计 {elapsed_ms}ms 超过上限加一次调用的最长时限"


def test_counts_do_not_decrease_across_a_restart(tmp_path):
    # 性质三：计数在进程重启前后单调不减
    data_dir = tmp_path / "data"
    script = [{"proposal": product_spec()}, {"proposal": engineering_plan()}]
    with killed.interrupted(data_dir, script, hold_after="activation_finished") as run:
        before = [event for event in run.before_events if event.type == EventType.ACTIVATION_FINISHED]
        after = [event for event in run.after.store.list_events(run.run_id)
                 if event.type == EventType.ACTIVATION_FINISHED]
        assert before and after
        before_usage = ((before[-1].payload or {}).get("elapsed_ms"),
                        (before[-1].payload or {}).get("activations"),
                        (before[-1].payload or {}).get("model_steps"))
        after_usage = ((after[-1].payload or {}).get("elapsed_ms"),
                       (after[-1].payload or {}).get("activations"),
                       (after[-1].payload or {}).get("model_steps"))
        assert after_usage[0] >= before_usage[0], "已用时间单调不减"
        assert after_usage[1] >= before_usage[1], "激活次数单调不减"
        assert after_usage[2] >= before_usage[2], "模型步数单调不减"
