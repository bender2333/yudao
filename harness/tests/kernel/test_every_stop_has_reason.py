# 基础规则第六条的前半：每个 run 以封闭清单里的原因结束或进入等待。
#
# 到终态的 run 必有一条带封闭清单原因的结束事件（run_done、run_paused 或 run_failed），
# 等待中的 run 必有一条 run_waiting 之外的在途状态：决定请求（decision_requested）
# 或尚未收尾的激活。停止原因是 stop_reasons.json 这份封闭清单，写入口按它核对
# （write_path._check_stop_reason），清单以外的原因写不进去。
#
# 对全部事件序列基准执行（44 个场景）：基准是真实运行录下来的事件序列，读静态文件，
# 不重跑运行，属于单元层。

import json
from pathlib import Path

from harness.models import TERMINAL_STATUSES

BASELINE_DIR = Path(__file__).resolve().parents[1] / "event_sequences"
STOP_REASONS = Path(__file__).resolve().parents[3] / "harness" / "definitions" / "stop_reasons.json"
_STOP_EVENTS = ("run_done", "run_paused", "run_failed")
# 非终态的场景：录制在 run 结束以前停止，尾部是未收尾的激活，投影不在终态
_PREFIX_SCENARIOS = {
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


def _reasons() -> dict:
    return json.loads(STOP_REASONS.read_text(encoding="utf-8"))


def test_every_baseline_ends_with_a_reasoned_stop_event_or_waits():
    reasons = _reasons()
    # 封闭清单的项数：18 项（第 18 项是 user_cancelled，用户放弃建档，工单 #707，
    # 依据是决策记录「M0 走查问题的五项口径」第 2 项）
    assert len(reasons) == 19, f"停止原因的封闭清单有 {len(reasons)} 项"
    checked = 0
    for path in sorted(BASELINE_DIR.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        events = document["events"]
        assert events, f"{path.name} 没有录到事件"
        stops = [event for event in events if event["type"] in _STOP_EVENTS]
        status = document["projection"].get("status")
        if status in TERMINAL_STATUSES:
            assert stops, f"{path.name} 已到终态却没有结束事件"
            for stop in stops:
                reason = (stop.get("payload") or {}).get("stop_reason")
                assert reason in reasons, f"{path.name} 的停止原因 {reason!r} 不在封闭清单里"
                assert stop.get("stop_reason") == reason, f"{path.name} 的事件停止原因与载荷不一致"
                outcome = reasons[reason]["outcome"]
                assert stop["type"] == f"run_{outcome}", \
                    f"{path.name} 的原因 {reason!r} 的去向是 {outcome}，事件却是 {stop['type']}"
            checked += 1
        else:
            # 进入等待：要么在等用户的决定，要么录制停在未收尾的激活上
            waiting = [event for event in events if event["type"] == "decision_requested"]
            assert path.stem in _PREFIX_SCENARIOS or waiting, \
                f"{path.name} 非终态，既不在已知的前缀录制清单里，也没有在等决定"
    assert checked > 30, f"终态基准只有 {checked} 个"


def test_every_stop_reason_is_in_the_closed_list():
    # 写入口按这份清单核对结束事件（write_path._check_stop_reason），终止事件只能带清单里的原因
    reasons = _reasons()
    for path in sorted(BASELINE_DIR.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for event in document["events"]:
            if event["type"] in _STOP_EVENTS:
                assert event.get("stop_reason") in reasons, \
                    f"{path.name} 的结束事件带有清单外的停止原因 {event.get('stop_reason')!r}"