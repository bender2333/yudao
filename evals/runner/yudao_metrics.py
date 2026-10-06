"""Yudao 一侧的指标与过程检查点：全部从导出的事件日志计算，不使用模型。

设计说明第 5.1 节（过程检查点）与第 5.2 节（指标）：结束状态与原因、循环次数、
返工次数、部门之间询问次数、模型请求数、输入与输出用量、耗时。数据来源只有
`run.export` 的投影、事件与用量三部分，以及运行器自己的一次 `replay.check`。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from metrics import FAILURE_MARKERS

MODEL_SERVICE_FAILURE = "model_service_failure"
TIME_LIMIT = "time_limit"
# 写入工作区的环境工具：只有这四个会改文件（第 5.1 节第 3 项）
WRITE_TOOLS = frozenset({"write_file", "edit_range", "delete_file", "move_file"})


def collect(export, outcome, replay=None):
    """从一次 `run.export` 与运行器结果算指标与过程检查点。"""
    projection = export["projection"]
    events = export["events"]
    model_service_failure = _is_model_service_failure(events)
    status, reason = _end_state(projection, outcome, model_service_failure)
    checkpoints = checkpoints_of(events, status, replay, outcome)

    return {
        "end_status": status,
        "end_reason": reason,
        "outcome": projection.get("outcome"),
        "stop_reason": projection.get("stop_reason"),
        "phase": projection.get("phase"),
        "cycles": int(projection.get("cycle_count") or 0),
        "rework": int(projection.get("rework_count") or 0),
        "collaboration": _count(events, "collaboration_requested"),
        "model_requests": _requests(export),
        "input_tokens": _usage(export, "input_tokens"),
        "output_tokens": _usage(export, "output_tokens"),
        "cache_read_tokens": _usage(export, "cache_read_tokens"),
        "cache_write_tokens": _usage(export, "cache_write_tokens"),
        "total_tokens": _usage(export, "total_tokens"),
        "cost": _usage_float(export, "cost"),
        "model_latency_ms": _usage(export, "latency_ms"),
        "elapsed_seconds": round(float(outcome["elapsed_seconds"]), 1),
        "timed_out": bool(outcome["timed_out"]),
        "model_service_failure": model_service_failure,
        "empty_model_responses": _empty_responses(export),
        "checkpoints": checkpoints,
    }


def _end_state(projection, outcome, model_service_failure):
    """结束状态与原因：放行为 released，其余为 ended；到时间上限记 `time_limit`（第 5.2 节）。"""
    if outcome["timed_out"]:
        return "ended", TIME_LIMIT
    if model_service_failure:
        return "ended", MODEL_SERVICE_FAILURE
    if projection.get("outcome") == "released":
        return "released", projection.get("stop_reason") or "released"
    return "ended", projection.get("stop_reason") or projection.get("outcome") or "unknown"


def _usage_totals(export):
    """用量在 `usage.totals` 下：模型服务没有分项统计时那一项是 null，按 0 计入。"""
    return export.get("usage", {}).get("totals") or {}


def _usage(export, name):
    value = _usage_totals(export).get(name)
    return int(value) if isinstance(value, (int, float)) else 0


def _usage_float(export, name):
    value = _usage_totals(export).get(name)
    return float(value) if isinstance(value, (int, float)) else 0.0


def _requests(export):
    """模型请求数：投影的 request_count 在没有分项统计时是 0，用事件与用量里的请求数。"""
    recorded = int(export["projection"].get("request_count") or 0)
    if recorded:
        return recorded
    attempts = _usage_totals(export).get("attempts")
    if isinstance(attempts, int) and attempts:
        return attempts
    return _count(export["events"], "model_requested")



def _empty_responses(export):
    """成功但没有任何输出项的模型调用：这类调用被主机当成一次正常回复，连续多次以后按
    `no_tool_call` 暂停，停止原因与真实原因不符，报告把它单独写出来。"""
    return sum(1 for attempt in export.get("attempts", [])
               if attempt.get("status") == "success" and attempt.get("output_item_count") == 0)

def _count(events, event_type):
    return sum(1 for event in events if event["type"] == event_type)


def checkpoints_of(events, status, replay, outcome):
    """第 5.1 节的五项过程检查点，逐项给出结论与依据。"""
    released = status == "released"
    return {
        "ended_within_limit": {
            "passed": not outcome["timed_out"],
            "detail": ("运行在时间上限内结束" if not outcome["timed_out"]
                       else "运行到时间上限，被运行器结束"),
        },
        "quality_release_bound_to_delivery": {
            "passed": released,
            "detail": _release_binding(events),
        },
        "no_write_before_plan_accepted": {
            "passed": _no_write_before_plan(events),
            "detail": _write_order_detail(events),
        },
        "replay_consistent": {
            "passed": bool(replay and replay["consistent"]),
            "detail": ("重放结果与记录一致" if replay and replay["consistent"]
                       else "重放结果与记录不一致：" + "、".join(replay["differences"]) if replay
                       else "没有取到重放结果"),
        },
        "no_false_release": {
            "passed": _no_false_release(released, outcome),
            "detail": _false_release_detail(released, outcome),
        },
    }


def _no_false_release(released, outcome):
    """误放行只发生在质检放行以后：没有放行就不存在误放行，隐藏检查的失败由评分报告写出。"""
    return not (released and outcome.get("hidden_failures"))


def _false_release_detail(released, outcome):
    failures = outcome.get("hidden_failures")
    if not released:
        return "没有放行，不存在误放行" + ("；隐藏检查的失败条目：" + "、".join(failures)
                                     if failures else "")
    if not failures:
        return "质检放行且隐藏检查中无失败条目"
    return "质检误放行，失败的隐藏检查：" + "、".join(failures)


def _release_binding(events):
    reviews = [event for event in events if event["type"] == "qa_submitted"]
    deliveries = [event for event in events if event["type"] == "delivery_accepted"]
    if not reviews or not deliveries:
        return "没有质检提交或没有封存的交付"
    review, delivery = reviews[-1], deliveries[-1]
    if review["payload"].get("code_snapshot_hash") != delivery["payload"].get("code_snapshot_hash"):
        return "放行引用的交付快照与最后一次封存的交付不同"
    if not review["payload"].get("checks"):
        return "放行没有引用质检自己取得的检查回执"
    return "放行绑定最后封存的交付树，检查回执由质检自己取得"


def _no_write_before_plan(events):
    for event in events:
        if event["type"] == "tool_called" and event["payload"].get("name") in WRITE_TOOLS:
            return False
        if event["type"] == "plan_accepted":
            return True
    return True


def _write_order_detail(events):
    first_write = None
    for event in events:
        if event["type"] == "tool_called" and event["payload"].get("name") in WRITE_TOOLS:
            first_write = event
            break
    if first_write is None:
        return "工程没有写入文件"
    plan = next((event for event in events if event["type"] == "plan_accepted"), None)
    if plan is None:
        return "工程在计划被接纳以前写入了文件（位置 " + str(first_write.get("position")) + "）"
    return "工程在计划被接纳（位置 " + str(plan.get("position")) + "）以后写入文件"


def _is_model_service_failure(events):
    """模型服务故障：凭据被拒、连接失败、限流与服务端错误（provider 侧故障）。"""
    for event in events:
        if event["type"] not in ("model_attempt_failed", "run_paused", "run_failed"):
            continue
        text = json.dumps(event["payload"], ensure_ascii=False).lower()
        if any(marker in text for marker in FAILURE_MARKERS):
            return True
    return False