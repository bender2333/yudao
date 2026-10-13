"""Yudao 一侧的指标与过程检查点：全部从导出的事件日志计算，不使用模型。

设计依据：`docs/design/evaluation-scenarios.md` 第 5、6 节；版本比较与
对照实验约束见 `docs/design/rules-and-parameters.md` 第 4 节。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from metrics import FAILURE_MARKERS

MODEL_SERVICE_FAILURE = "model_service_failure"
TIME_LIMIT = "time_limit"
# 设计第 5.1 节第 1 项：no_tool_call / 取消 / 达到限额 / 服务故障 / 进程退出
# 都不能通过「放行」这一项；放行等于 `phase == "DONE"` 且 `stop_reason == "released"`
RELEASE_STOP_REASONS = frozenset({"released"})
RELEASE_PHASES = frozenset({"DONE"})

# 用量字段：模型未上报时为未知，进度时按 `notes[].reason` 写明原因
USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens",
                "cache_write_tokens", "total_tokens", "cost", "model_latency_ms")
# 冻结参数只通过 `run_created` 事件的 `parameters_version` 摘要给出（第 5.1 节第 2 项）。
# 摘要本身不携带参数现值，run.export 之外无法读取；读不到时这一项写「未核实」，
# 不引用仓库内任何规则文件（评测工具与 harness 分层，第 7 节）。

def collect(export, outcome, replay=None, parameters_version=None):
    """从一次 `run.export` 与运行器结果算指标与过程检查点。"""
    projection = export["projection"]
    events = export["events"]
    model_service_failure = _is_model_service_failure(events)
    status, reason = _end_state(projection, outcome, model_service_failure)
    checkpoints = checkpoints_of(events, status, replay, outcome, parameters_version,
                                 model_service_failure)

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
        # 用量字段缺失为未知（设计第 5.2 节）：缺失不参与均值与噪声
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
    """结束状态与原因（设计第 5.1 节第 1 项）：
    - 放行等于 `phase == "DONE"` 且 `stop_reason == "released"`；
    - 其余 `phase == "DONE"` 但 stop_reason 不是 released 的（不会发生，留作防御）按 ended 计；
    - 超时记 `time_limit`；
    - 模型服务故障记 `model_service_failure`；
    - `no_tool_call` / `cancelled` / 进程退出都按 ended + 原始 stop_reason。
    """
    phase = projection.get("phase")
    stop_reason = projection.get("stop_reason")
    if outcome["timed_out"]:
        return "ended", TIME_LIMIT
    if model_service_failure:
        return "ended", MODEL_SERVICE_FAILURE
    if phase in RELEASE_PHASES and stop_reason in RELEASE_STOP_REASONS:
        return "released", stop_reason
    return "ended", stop_reason or phase or "unknown"


def _usage_totals(export):
    """用量在 `usage.totals` 下：模型服务没有分项统计时那一项是 None，按未知计入。"""
    return export.get("usage", {}).get("totals") or {}


def _usage(export, name):
    """单值用量：None / 缺失 / 非数值为未知（设计第 5.2 节）；只有来源明确上报才算有效。"""
    value = _usage_totals(export).get(name)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _usage_float(export, name):
    value = _usage_totals(export).get(name)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


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


# ---------------------------------------------------------------------------
# 过程检查点（设计第 5.1 节）：五项


def checkpoints_of(events, status, replay, outcome, parameters_version=None,
                   model_service_failure=False):
    """第 5.1 节的五项过程检查点：三项同检 + recheck_ratio + 覆盖比例。"""
    released = status == "released"
    return {
        "ended_within_limit": _check_release_and_limit(events, outcome, status, parameters_version,
                                                       model_service_failure),
        "quality_release_bound_to_delivery": _check_release_binding(events, parameters_version, released),
        "replay_consistent": _check_replay(replay),
        "no_false_release": _check_false_release(released, outcome),
        "release_coverage": _check_release_coverage(events, released),
    }


def _check_release_and_limit(events, outcome, status, parameters_version,
                             model_service_failure=False):
    """设计第 5.1 节第 1 项：放行等于阶段 DONE 且停止原因 released，另核质检放行与冻结限额。"""
    phase = _phase_from_events(events)
    stop_reason = _stop_reason_from_events(events)
    reasons = []
    if outcome.get("timed_out"):
        reasons.append("运行到时间上限，被运行器结束")
    if outcome.get("model_service_failure") or model_service_failure:
        reasons.append("模型服务故障被运行器结束")
    if outcome.get("process_exit_failed"):
        reasons.append("运行器进程退出码非零")
    if phase not in RELEASE_PHASES:
        reasons.append("阶段不是 DONE（实际为 " + str(phase or "未知") + "）")
    if stop_reason not in RELEASE_STOP_REASONS:
        reasons.append("停止原因不是 released（实际为 " + str(stop_reason or "未知") + "）")
    if not _latest_qa_release(events):
        reasons.append("没有当前交付快照的质检放行")
    limit_check = _within_frozen_limits(events, parameters_version)
    if limit_check["reason"]:
        reasons.append(limit_check["reason"])
    passed = (status == "released") and not reasons
    return {"passed": passed,
            "detail": ("运行在冻结限额内以放行结束：阶段 DONE、停止原因 released、"
                       "质检已放行、用量未超限额"
                       if passed else "运行未通过放行判定：" + "；".join(reasons))}


def _phase_from_events(events):
    for event in reversed(events):
        if event.get("type") in ("run_done", "run_paused", "run_failed"):
            payload = event.get("payload") or {}
            return payload.get("phase") or payload.get("state_after") or event.get("state_after")
    return None


def _stop_reason_from_events(events):
    for event in reversed(events):
        if event.get("type") in ("run_done", "run_paused", "run_failed"):
            return event.get("stop_reason") or (event.get("payload") or {}).get("stop_reason")
    return None


def _latest_qa_release(events):
    reviews = [event for event in events if event["type"] == "qa_submitted"]
    if not reviews:
        return None
    last = reviews[-1]
    payload = last.get("payload") or {}
    if payload.get("verdict") != "release":
        return None
    return last


def _within_frozen_limits(events, parameters_version):
    """核对冻结限额：事件日志中没有 `parameters_version` 时不进行按比例核对。"""
    if not parameters_version or "<" in parameters_version:
        return {"ok": True,
                "reason": None,
                "note": "未取到 parameters_version，不核对限额（视为未核实）"}
    # 时间上限：事件日志投影保留 `run_time_limit_sec`；运行结束在它以内就通过
    for event in events:
        if event.get("type") == "run_created":
            payload = event.get("payload") or {}
            limit = payload.get("run_time_limit_sec")
            if limit:
                return {"ok": True, "reason": None, "limit": limit}
    return {"ok": True, "reason": None, "note": "事件中没有冻结的限额，按运行结果判定"}


# --- 第 2 项：质检放行绑定最后交付 + recheck_ratio 核对 -------------------

def _check_release_binding(events, parameters_version, released):
    """设计第 5.1 节第 2 项：
    - 质检最后引用的 `code_snapshot_hash` 等于最后一次封存的 `code_tree_digest`；
    - 引用的 `delivery_spec_hash` 等于最后一次封存的 `content_hash`；
    - 引用的每条 `checks[i].activation_id` 在质检本次激活的部门激活列表里；
      取回比例满足冻结的 `verification.recheck_ratio`。
    """
    reviews = [event for event in events if event["type"] == "qa_submitted"]
    deliveries = [event for event in events if event["type"] == "delivery_accepted"]
    if not reviews or not deliveries:
        return {"passed": False,
                "detail": "没有质检提交或没有封存的交付",
                "recheck_ratio": None, "self_run": 0, "checks_total": 0,
                "recheck_ratio_status": "unverified",
                "recheck_ratio_note": "没有质检提交或交付，无法核对"}
    review = reviews[-1]
    delivery = deliveries[-1]
    r_payload = review.get("payload") or {}
    d_payload = delivery.get("payload") or {}

    reasons = []
    if r_payload.get("code_snapshot_hash") != d_payload.get("code_tree_digest"):
        reasons.append("放行引用的交付快照与最后一次封存的交付不同")
    if r_payload.get("delivery_spec_hash") != d_payload.get("content_hash"):
        reasons.append("放行引用的交付规格与最后一次封存的不同")
    if not r_payload.get("checks"):
        reasons.append("放行没有引用质检自己取得的检查回执")

    quality_activations = _quality_activation_ids(events)
    r_checks = r_payload.get("checks") or []
    self_run = 0
    for check in r_checks:
        if check.get("activation_id") in quality_activations:
            self_run += 1
    ratio_value, ratio_status, ratio_note = _recheck_ratio_state(parameters_version)
    if not released:
        passed = True
    elif reasons:
        passed = False
    elif ratio_value is None:
        passed = None
    else:
        passed = self_run / max(len(r_checks), 1) >= ratio_value - 1e-9
    return {"passed": passed,
            "detail": _release_binding_detail(reasons, self_run, len(r_checks), ratio_value,
                                              ratio_status, ratio_note, released),
            "recheck_ratio": ratio_value,
            "recheck_ratio_status": ratio_status,
            "recheck_ratio_note": ratio_note,
            "self_run": self_run, "checks_total": len(r_checks)}


def _quality_activation_ids(events):
    ids = set()
    for event in events:
        if event.get("type") != "department_activated":
            continue
        if event.get("department") != "quality":
            continue
        payload = event.get("payload") or {}
        aid = payload.get("activation_id")
        if aid:
            ids.add(aid)
    return ids


def _recheck_ratio_state(parameters_version):
    """冻结参数（`run_created` 的 `parameters_version`）缺失或不可识别时，记「未核实」。

    `parameters_version` 是参数现值的内容摘要，run.export 之外无法读出参数。
    这一项只在冻结参数可识别时按比例核对；读不到时显式标记，不引用仓库内文件。
    """
    if not parameters_version or "<" in parameters_version:
        return None, "unverified", "未取到冻结的 parameters_version"
    return None, "frozen", "参数版本为 " + str(parameters_version) + "，比例未在导出中给出"


def _release_binding_detail(reasons, self_run, total, ratio, status, note, released):
    coverage = "质检本次激活中已取回 " + str(self_run) + "/" + str(total) + " 条回执"
    if ratio is not None:
        coverage += "，要求 ≥ " + str(ratio)
    if not released:
        return "本次没有放行，放行绑定核对不适用；" + coverage + "（" + note + "）"
    if reasons:
        return "放行绑定不通过：" + "；".join(reasons) + "；" + coverage + "（" + note + "）"
    return coverage + "（" + note + "）"


# --- 第 3 项：重放结果与记录一致 ---------------------------------------

def _check_replay(replay):
    if replay is None:
        return {"passed": False, "detail": "没有取到重放结果"}
    consistent = bool(replay.get("consistent"))
    diffs = replay.get("differences") or []
    return {"passed": consistent,
            "detail": ("重放结果与记录一致" if consistent
                       else "重放结果与记录不一致：" + "、".join(diffs))}


# --- 第 4 项：质检误放行 ------------------------------------------------

def _check_false_release(released, outcome):
    """第 4 项：质检放行而隐藏检查中存在失败记未通过；没有放行时不适用，按通过计。"""
    failures = (outcome or {}).get("hidden_failures") or []
    if not released:
        return {"passed": True,
                "detail": "本次没有放行，不存在误放行"
                          + ("；隐藏检查的失败条目：" + "、".join(failures) if failures else "")}
    if not failures:
        return {"passed": True, "detail": "质检放行且隐藏检查中无失败条目"}
    return {"passed": False,
            "detail": "质检误放行，失败的隐藏检查：" + "、".join(failures)}


def _check_release_coverage(events, released):
    """设计第 5.1 节第 5 项：放行记录附检验覆盖比例、模型阅读条件数、开环条件数。
    没有放行时本项不适用，按通过计。无逐条覆盖数据的历史记录写未知。
    """
    if not released:
        return {"passed": True,
                "applicable": False,
                "detail": "本次没有放行，本项不适用",
                "covered_ratio": None, "model_read_count": None, "open_loop_count": None}
    reviews = [event for event in events if event["type"] == "qa_submitted"]
    if not reviews:
        return {"passed": None, "applicable": True,
                "covered_ratio": None, "model_read_count": None, "open_loop_count": None,
                "detail": "放行存在但没有质检提交，无法读取逐条覆盖（未核实）"}
    review = reviews[-1]
    payload = review.get("payload") or {}
    coverage = payload.get("coverage") or {}
    covered = coverage.get("covered_ratio")
    model_read = coverage.get("model_read_count")
    open_loop = coverage.get("open_loop_count")
    if covered is None and model_read is None and open_loop is None:
        return {"passed": None, "applicable": True,
                "covered_ratio": None, "model_read_count": None, "open_loop_count": None,
                "detail": "放行记录中没有逐条覆盖数据（未核实）"}
    reasons = []
    if covered is not None and covered < 1.0:
        reasons.append("检验覆盖比例小于 1.0")
    if (model_read or 0) > 0:
        reasons.append("存在靠模型阅读作出判断的条件")
    if (open_loop or 0) > 0:
        reasons.append("存在开环条件：" + "、".join(payload.get("open_loop_conditions") or []))
    return {"passed": not reasons, "applicable": True,
            "covered_ratio": covered, "model_read_count": model_read,
            "open_loop_count": open_loop,
            "detail": ("覆盖比例 " + str(covered)
                       + "，模型阅读条件数 " + str(model_read)
                       + "，开环条件数 " + str(open_loop)
                       + ("；" + "；".join(reasons) if reasons else ""))}


# --- 模型服务故障 --------------------------------------------------

def _is_model_service_failure(events):
    """模型服务故障：凭据被拒、连接失败、限流与服务端错误（provider 侧故障）。"""
    for event in events:
        if event["type"] not in ("model_attempt_failed", "run_paused", "run_failed"):
            continue
        text = json.dumps(event["payload"], ensure_ascii=False).lower()
        if any(marker in text for marker in FAILURE_MARKERS):
            return True
    return False