"""Yudao 一侧的指标与过程检查点：全部从导出的事件日志计算，不使用模型。

设计依据：`docs/design/evaluation-scenarios.md` docs/design/evaluation-scenarios.md「过程检查点与指标」、「报告与版本比较」；版本比较与
对照实验约束见 `docs/design/rules-and-parameters.md` docs/design/rules-and-parameters.md「对照」。
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from metrics import FAILURE_MARKERS

MODEL_SERVICE_FAILURE = "model_service_failure"
TIME_LIMIT = "time_limit"
#：no_tool_call / 取消 / 达到限额 / 服务故障 / 进程退出
# 都不能通过「放行」这一项；放行等于 `status == "done"` 且 `stop_reason == "released"`
RELEASE_STOP_REASONS = frozenset({"released"})
RELEASE_STATUSES = frozenset({"done"})
BLOCKING_DECISION_SCOPES = frozenset({"run", "work_item"})
# 没有核验角色的形态以开环完成结束（harness/models.py 的 OPEN_LOOP_STOP_REASON）：这五项检查点对它不适用
OPEN_LOOP_STOP_REASON = "open_loop"
OPEN_LOOP_NOT_APPLICABLE = "不适用：这份形态没有核验角色"
CHECKPOINT_KEYS = ("ended_within_limit", "quality_release_bound_to_delivery", "replay_consistent",
                   "no_false_release", "release_coverage")

# 用量字段：模型未上报时为未知，进度时按 `notes[].reason` 写明原因
USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens",
                "cache_write_tokens", "total_tokens", "cost", "model_latency_ms")
# 冻结参数只通过 `run_created` 事件的 `parameters_version` 摘要给出。
# 摘要本身不携带参数现值，run.export 之外无法读取；读不到时这一项写「未核实」，
# 不引用仓库内任何规则文件（评测工具与 harness 分层）。

def collect(export, outcome, replay=None, parameters_version=None):
    """从一次 `run.export` 与运行器结果算指标与过程检查点。"""
    projection = export["projection"]
    events = export["events"]
    model_service_failure = _is_model_service_failure(events)
    status, reason = _end_state(projection, outcome, model_service_failure, events)
    checkpoints = checkpoints_of(events, status, replay, outcome, parameters_version,
                                 model_service_failure)
    open_loop = recorded_open_loop(events)
    role_choice = _role_choice_metrics(events)

    return {
        "end_status": status,
        "end_reason": reason,
        "outcome": projection.get("status"),
        "stop_reason": projection.get("stop_reason"),
        "status": projection.get("status"),
        "cycles": int(projection.get("cycle_count") or 0),
        "rework": int(projection.get("rework_count") or 0),
        "collaboration": _count(events, "ask_started"),
        **role_choice,
        "model_requests": _requests(export),
        # 用量字段缺失为未知：缺失不参与均值与噪声
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
        "open_loop": open_loop,
        "open_loop_readings": open_loop_readings(events) if open_loop else None,
        "outer_loop_states": _outer_loop_states(events),
        "activation_rounds": _activation_rounds(export),
        "checkpoints": checkpoints,
    }


def onboarding_metrics(export, elapsed_seconds=None):
    """建档的模型请求数、用量与耗时（场景 2，docs/design/evaluation-scenarios.md「指标」）：单独列出，不计入事项的指标。

    数值从建档 run 的 `run.export` 算，与事项的指标同一套字段与未知值规则（缺的记未知，
    不记零）；耗时取事件日志里第一条到最后一件事的间隔，取不到时用运行器量到的墙钟时间。
    """
    if export is None:
        return {"model_requests": 0, "input_tokens": None, "output_tokens": None,
                "total_tokens": None, "cost": None, "elapsed_seconds": _round_seconds(elapsed_seconds),
                "status": None, "stop_reason": None}
    return {
        "model_requests": _requests(export),
        "input_tokens": _usage(export, "input_tokens"),
        "output_tokens": _usage(export, "output_tokens"),
        "total_tokens": _usage(export, "total_tokens"),
        "cost": _usage_float(export, "cost"),
        "elapsed_seconds": _event_span_seconds(export) if _event_span_seconds(export) is not None
        else _round_seconds(elapsed_seconds),
        "status": export["projection"].get("status"),
        "stop_reason": export["projection"].get("stop_reason"),
    }


def _round_seconds(value):
    return None if value is None else round(float(value), 1)


def _event_span_seconds(export):
    """事件日志里第一条到最后一件事的间隔：导出有写入时间时用它量耗时，没有时为空。"""
    times = [event.get("created_at") for event in export.get("events", [])]
    stamps = [datetime.fromisoformat(value) for value in times
              if isinstance(value, str) and value]
    if len(stamps) < 2:
        return None
    return round((max(stamps) - min(stamps)).total_seconds(), 1)


def _open_blocking_decision_reason(events):
    """从事件流读取最后一条未回答、未撤销且阻塞事项运行的决定请求原因。"""
    open_requests = {}
    for index, event in enumerate(events):
        event_type = event.get("type")
        payload = event.get("payload") or {}
        if event_type == "decision_requested":
            decision_id = (event.get("event_id")
                           or event.get("decision_id")
                           or payload.get("decision_id"))
            key = decision_id if isinstance(decision_id, str) and decision_id else index
            open_requests[key] = payload
        elif event_type in ("decision_answered", "decision_withdrawn"):
            decision_id = (payload.get("decision_id")
                           or event.get("decision_id")
                           or event.get("parent_event_id"))
            if isinstance(decision_id, str) and decision_id:
                open_requests.pop(decision_id, None)
    reason = None
    for payload in open_requests.values():
        if payload.get("blocks") not in BLOCKING_DECISION_SCOPES:
            continue
        candidate = payload.get("reason")
        if not isinstance(candidate, str) or not candidate.strip():
            candidate = payload.get("kind")
        if isinstance(candidate, str) and candidate.strip():
            reason = candidate
    return reason


def _end_state(projection, outcome, model_service_failure, events=()):
    """计算结束状态与结束原因：
    - 超时记录 `time_limit`；
    - 模型服务故障记录 `model_service_failure`；
    - `status == "done"` 且 `stop_reason == "released"` 记录放行；
    - 投影缺少 `stop_reason` 且事件流包含未回答、未撤销的阻塞型决定请求时，记录 `ended` 与最后一条该类请求的原因；
    - 其余情况记录 `ended` 与投影中的停止原因或状态。
    """
    status = projection.get("status")
    stop_reason = projection.get("stop_reason")
    if outcome["timed_out"]:
        return "ended", TIME_LIMIT
    if model_service_failure:
        return "ended", MODEL_SERVICE_FAILURE
    if status in RELEASE_STATUSES and stop_reason in RELEASE_STOP_REASONS:
        return "released", stop_reason
    if not stop_reason:
        blocking_reason = _open_blocking_decision_reason(events)
        if blocking_reason is not None:
            return "ended", blocking_reason
    return "ended", stop_reason or status or "unknown"


def _usage_totals(export):
    """用量在 `usage.totals` 下：模型服务没有分项统计时那一项是 None，按未知计入。"""
    return export.get("usage", {}).get("totals") or {}


def _usage(export, name):
    """单值用量：None / 缺失 / 非数值为未知只有来源明确上报才算有效。"""
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


def _role_choice_metrics(events):
    """从事件流统计 `role_choice` 决定请求次数与总题数，及已回答次数与题数。"""
    requested_questions_by_id = {}
    requests = 0
    questions = 0
    answered_ids = set()
    answered_requests = 0
    answered_questions = 0

    for index, event in enumerate(events):
        event_type = event.get("type")
        payload = event.get("payload") or {}
        if event_type == "decision_requested":
            if payload.get("kind") != "role_choice":
                continue
            requests += 1
            raw_questions = payload.get("questions")
            q_count = len(raw_questions) if isinstance(raw_questions, list) else 0
            questions += q_count
            decision_id = (event.get("event_id")
                           or event.get("decision_id")
                           or payload.get("decision_id"))
            key = decision_id if isinstance(decision_id, str) and decision_id else index
            requested_questions_by_id[key] = q_count
        elif event_type == "decision_answered":
            decision_id = (payload.get("decision_id")
                           or event.get("decision_id")
                           or event.get("parent_event_id"))
            if decision_id in requested_questions_by_id and decision_id not in answered_ids:
                answered_ids.add(decision_id)
                answered_requests += 1
                answered_questions += requested_questions_by_id[decision_id]

    return {
        "role_choice_requests": requests,
        "role_choice_questions": questions,
        "role_choice_answered_requests": answered_requests,
        "role_choice_answered_questions": answered_questions,
    }


# ---------------------------------------------------------------------------
# 第一次与最终两份交付：两份评分由运行器交给评分器

# 质检带来的提高（docs/design/evaluation-scenarios.md「Yudao 对单个 agent」中「高于」看质检这一段）的四种取值
IMPROVEMENT_IMPROVED = "improved"          # 最终交付比第一次多通过至少 1 条隐藏检查
IMPROVEMENT_NONE = "none"                  # 没有多通过
IMPROVEMENT_NOT_COUNTED = "not_counted"    # 第一次交付已经全部通过，这次运行不计入
IMPROVEMENT_NO_CONCLUSION = "no_conclusion"  # 导出里没有质检提交，没有结论可观察


COMPLETION_ARTIFACT_KIND = "completion"


def _is_archived_delivery(event):
    """识别封存交付事件：成果驱动的 `delivery_accepted` 与直做交完成的 `artifact_accepted`。"""
    kind = event.get("type")
    if kind == "delivery_accepted":
        return True
    if kind != "artifact_accepted":
        return False
    payload = event.get("payload") or {}
    if payload.get("artifact_kind") != COMPLETION_ARTIFACT_KIND:
        return False
    return "artifact_ref" not in payload or isinstance(payload.get("artifact_ref"), dict)


def delivery_metrics(export, final_scores, first_scores):
    """第一次交付与最终交付的完成度、通过的检查，以及质检带来的提高。

    `final_scores` 与 `first_scores` 是评分器对两份封存交付的结果（没有交付时评分器
    把每条隐藏检查记成「没有做」，两份评分相同）。每次运行的这两个值由运行器读取：
    只有一次交付时两份相同，没有交付时都是「没有做」。
    """
    delivered = any(_is_archived_delivery(event) for event in export.get("events", []))
    concluded = qa_concluded(export)
    first = _delivery_summary(first_scores, delivered)
    final = _delivery_summary(final_scores, delivered)
    return {
        "first": first,
        "final": final,
        "qa_within_limit": concluded,
        "qa_improvement": _qa_improvement(first, final, concluded),
    }


def qa_concluded(export):
    """质检是否在时间上限以内给出结论：导出里有 `qa_submitted` 事件。

    导出是这一运行在时间上限以内写下的全部事件，导出里有质检提交就是它在时限以内
    给出了结论；时限到达时运行被结束，之后不会再有事件。
    """
    return any(event.get("type") == "qa_submitted" for event in export.get("events", []))


def _delivery_summary(scores, delivered):
    """一份交付的评分摘要：完成度、正确性与通过的隐藏检查条数。"""
    checks = (scores or {}).get("checks") or []
    passed = [check["id"] for check in checks if check.get("status") == "pass"]
    return {
        "delivered": delivered,
        "completion": (scores or {}).get("completion"),
        "correctness": (scores or {}).get("correctness"),
        "passed_checks": len(passed),
        "total_checks": len(checks),
        "all_passed": bool(checks) and len(passed) == len(checks),
    }


def _qa_improvement(first, final, concluded):
    """质检带来的提高（docs/design/evaluation-scenarios.md「Yudao 对单个 agent」中「高于」看质检这一段）：最终交付比第一次交付多通过的隐藏检查条数。"""
    if not concluded:
        return {"status": IMPROVEMENT_NO_CONCLUSION, "passed_gain": None,
                "detail": "导出中没有质检提交（qa_submitted）：质检没有给出结论"}
    if first["all_passed"]:
        return {"status": IMPROVEMENT_NOT_COUNTED, "passed_gain": None,
                "detail": "第一次交付已经通过全部 " + str(first["total_checks"])
                          + " 条隐藏检查：这次运行不计入质检带来的提高"}
    gain = final["passed_checks"] - first["passed_checks"]
    if gain >= 1:
        return {"status": IMPROVEMENT_IMPROVED, "passed_gain": gain,
                "detail": "最终交付比第一次交付多通过 " + str(gain) + " 条隐藏检查"}
    return {"status": IMPROVEMENT_NONE, "passed_gain": gain,
            "detail": "最终交付没有比第一次交付多通过隐藏检查（" + str(gain) + " 条）"}



# ---------------------------------------------------------------------------
# 过程检查点：五项


def checkpoints_of(events, status, replay, outcome, parameters_version=None,
                   model_service_failure=False):
    """的五项过程检查点：三项同检 + recheck_ratio + 覆盖比例。

    没有核验角色的形态（`run_created` 事件记着 `open_loop`）本来就以开环完成结束，这五项
    是对有放行的运行定的，对它不适用：五项都写「不适用」，另读两样
    （docs/design/evaluation-scenarios.md「Yudao 的过程检查点」）。
    """
    if recorded_open_loop(events):
        return {key: {"passed": None, "applicable": False,
                      "detail": OPEN_LOOP_NOT_APPLICABLE} for key in CHECKPOINT_KEYS}
    released = status == "released"
    return {
        "ended_within_limit": _check_release_and_limit(events, outcome, status, parameters_version,
                                                       model_service_failure),
        "quality_release_bound_to_delivery": _check_release_binding(events, parameters_version, released),
        "replay_consistent": _check_replay(replay),
        "no_false_release": _check_false_release(released, outcome),
        "release_coverage": _check_release_coverage(events, released),
    }


def recorded_open_loop(events):
    """这次运行是不是在没有核验角色的形态下：`run_created` 事件记着 `open_loop`（服务在创建时记下的事实）。"""
    for event in events:
        if event.get("type") == "run_created":
            return bool((event.get("payload") or {}).get("open_loop"))
    return False


def open_loop_readings(events):
    """没有核验角色的形态只读两样：是否以开环完成结束、记录上有没有写成放行。写成放行算没过。"""
    status = _status_from_events(events)
    stop_reason = _stop_reason_from_events(events)
    ended = status in RELEASE_STATUSES and stop_reason == OPEN_LOOP_STOP_REASON
    released = stop_reason in RELEASE_STOP_REASONS or _latest_qa_release(events) is not None
    if released:
        detail = "记录上写成了放行：这份形态没有核验角色，不该有放行"
    elif ended:
        detail = "以开环完成结束，记录上没有写成放行"
    else:
        detail = "没有以开环完成结束（结束原因 " + str(stop_reason or status or "未知") + "）"
    return {"ended_open_loop": ended, "recorded_as_release": released,
            "passed": ended and not released, "detail": detail}


def _check_release_and_limit(events, outcome, status, parameters_version,
                             model_service_failure=False):
    """：放行等于状态 done 且停止原因 released，另核质检放行与冻结限额。"""
    end_status = _status_from_events(events)
    stop_reason = _stop_reason_from_events(events)
    reasons = []
    if outcome.get("timed_out"):
        reasons.append("运行到时间上限，被运行器结束")
    if outcome.get("model_service_failure") or model_service_failure:
        reasons.append("模型服务故障被运行器结束")
    if outcome.get("process_exit_failed"):
        reasons.append("运行器进程退出码非零")
    if end_status not in RELEASE_STATUSES:
        reasons.append("状态不是 done（实际为 " + str(end_status or "未知") + "）")
    if stop_reason not in RELEASE_STOP_REASONS:
        reasons.append("停止原因不是 released（实际为 " + str(stop_reason or "未知") + "）")
    if not _latest_qa_release(events):
        reasons.append("没有当前交付快照的质检放行")
    limit_check = _within_frozen_limits(events, parameters_version)
    if limit_check["reason"]:
        reasons.append(limit_check["reason"])
    passed = (status == "released") and not reasons
    return {"passed": passed,
            "detail": ("运行在冻结限额内以放行结束：状态 done、停止原因 released、"
                       "质检已放行、用量未超限额"
                       if passed else "运行未通过放行判定：" + "；".join(reasons))}


def _status_from_events(events):
    for event in reversed(events):
        if event.get("type") in ("run_done", "run_paused", "run_failed"):
            payload = event.get("payload") or {}
            return payload.get("status") or event.get("state_after")
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
    """：
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


def _first_present(mapping, primary, fallback):
    """优先读取现行键；仅当现行键缺失或为 None 时回退旧键，避免 0/0.0 误触发回退。"""
    value = mapping.get(primary)
    return mapping.get(fallback) if value is None else value


def _check_release_coverage(events, released):
    """：放行记录附检验覆盖比例、模型阅读条件数、开环条件数。
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
    covered = _first_present(coverage, "coverage_ratio", "covered_ratio")
    model_read = _first_present(coverage, "model_reading", "model_read_count")
    open_loop = _first_present(coverage, "open", "open_loop_count")
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
        open_conditions = _first_present(payload, "open_criteria", "open_loop_conditions") or []
        reasons.append("存在开环条件：" + "、".join(open_conditions))
    return {"passed": not reasons, "applicable": True,
            "covered_ratio": covered, "model_read_count": model_read,
            "open_loop_count": open_loop,
            "detail": ("覆盖比例 " + str(covered)
                       + "，模型阅读条件数 " + str(model_read)
                       + "，开环条件数 " + str(open_loop)
                       + ("；" + "；".join(reasons) if reasons else ""))}


# --- 外环状态与按轮按角色读数 -----------------------------------------

REVIEW_SUBMISSION_TYPES = frozenset({"qa_submitted", "baseline_review_accepted"})
REWORK_VERDICTS = frozenset({"rework", "rework_engineering", "rework_product"})
ACCEPT_EVENT_TYPES = frozenset({
    "spec_accepted",
    "contract_accepted",
    "product_decision_accepted",
    "delivery_accepted",
    "structure_accepted",
})
TERMINAL_EVENT_TYPES = frozenset({"run_done", "run_paused", "run_failed"})
DEFAULT_VERIFIER_DEPARTMENTS = frozenset({"quality", "verifier"})
ATTEMPT_EVENT_TYPES = frozenset({"model_requested", "model_attempt_finished", "model_attempt_failed"})
ROUND_TOKEN_FIELDS = ("input_tokens", "output_tokens", "total_tokens")
USAGE_PRESENCE_FIELDS = ("input_tokens", "output_tokens", "total_tokens",
                         "cache_read_tokens", "cache_write_tokens", "cost")


def _positive_int(value):
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _non_negative_number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _is_review_submission(event_type, payload):
    if event_type in REVIEW_SUBMISSION_TYPES:
        return True
    return event_type == "artifact_accepted" and payload.get("artifact_kind") == "completion_review"


def _discover_outer_loop_roles(events):
    """识别询问子分支会话与承担核验职能的部门。"""
    branch_sessions = set()
    verifier_departments = set(DEFAULT_VERIFIER_DEPARTMENTS)
    for event in events:
        event_type = event.get("type")
        payload = event.get("payload") or {}
        if event_type == "ask_started":
            branch_sid = payload.get("branch_session_id")
            if isinstance(branch_sid, str) and branch_sid:
                branch_sessions.add(branch_sid)
        elif _is_review_submission(event_type, payload):
            department = event.get("department") or payload.get("department")
            if isinstance(department, str) and department:
                verifier_departments.add(department)
    return branch_sessions, verifier_departments


def _outer_loop_states(events):
    """从原始事件流统计外环各状态走到次数及每次停止的原因。"""
    branch_sessions, verifier_departments = _discover_outer_loop_roles(events)
    ask_started = 0
    ask_answered = 0
    decision_requested = 0
    decision_answered = 0
    decision_withdrawn = 0
    verifier_activations = 0
    verifier_activation_ids = set()
    verifier_sessions = set()
    review_submissions = 0
    unmatched_reviews = 0
    rework = 0
    accepted = 0
    accept_events = {}
    stop_reasons = []
    stop_events = {}

    for event in events:
        event_type = event.get("type")
        payload = event.get("payload") or {}
        if event_type == "ask_started":
            ask_started += 1
        elif event_type == "ask_answered":
            ask_answered += 1
        elif event_type == "decision_requested":
            blocks = payload.get("blocks")
            if blocks is None or blocks in BLOCKING_DECISION_SCOPES:
                decision_requested += 1
        elif event_type == "decision_answered":
            decision_answered += 1
        elif event_type == "decision_withdrawn":
            decision_withdrawn += 1
        elif event_type == "department_activated":
            department = event.get("department") or payload.get("department")
            session_id = event.get("session_id")
            if department in verifier_departments and session_id not in branch_sessions:
                verifier_activations += 1
                aid = payload.get("activation_id")
                if isinstance(aid, str) and aid:
                    verifier_activation_ids.add(aid)
                if isinstance(session_id, str) and session_id:
                    verifier_sessions.add(session_id)
        elif _is_review_submission(event_type, payload):
            review_submissions += 1
            aid = payload.get("activation_id")
            sid = event.get("session_id")
            in_activation = (
                (isinstance(aid, str) and aid in verifier_activation_ids)
                or (isinstance(sid, str) and sid in verifier_sessions)
                or (aid is None and sid is None and verifier_activations > 0)
            )
            if not in_activation:
                unmatched_reviews += 1
            verdict = payload.get("verdict")
            if verdict in REWORK_VERDICTS:
                rework += 1
            elif event_type == "baseline_review_accepted":
                accepted += 1
                accept_events[event_type] = accept_events.get(event_type, 0) + 1
        elif event_type in ACCEPT_EVENT_TYPES or event_type == "artifact_accepted":
            accepted += 1
            accept_events[event_type] = accept_events.get(event_type, 0) + 1
        elif event_type in TERMINAL_EVENT_TYPES:
            reason = (
                event.get("stop_reason")
                or payload.get("stop_reason")
                or payload.get("status")
                or event.get("state_after")
                or event_type
            )
            stop_reasons.append(str(reason))
            stop_events[event_type] = stop_events.get(event_type, 0) + 1

    return {
        "asking": ask_started,
        "waiting_user": decision_requested,
        "verifying": verifier_activations + unmatched_reviews,
        "rework": rework,
        "accepted": accepted,
        "stopped": len(stop_reasons),
        "stop_reasons": stop_reasons,
        "breakdown": {
            "ask_started": ask_started,
            "ask_answered": ask_answered,
            "decision_requested": decision_requested,
            "decision_answered": decision_answered,
            "decision_withdrawn": decision_withdrawn,
            "verifier_activations": verifier_activations,
            "review_submissions": review_submissions,
            "accept_events": accept_events,
            "stop_events": stop_events,
        },
    }


def _usage_is_reported(usage):
    if not isinstance(usage, dict) or not usage:
        return False
    if "reported" in usage:
        return bool(usage["reported"])
    return any(_non_negative_number(usage.get(field)) is not None for field in USAGE_PRESENCE_FIELDS)


def _merge_usage(existing, incoming):
    if _usage_is_reported(incoming):
        return incoming
    if _usage_is_reported(existing):
        return existing
    if isinstance(incoming, dict) and incoming:
        return incoming
    return existing


def _parse_iso_timestamp(value):
    if not isinstance(value, str) or not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _attempt_duration_ms(attempt):
    direct = _non_negative_number(attempt.get("duration_ms"))
    if direct is not None:
        return int(round(direct))
    started = _parse_iso_timestamp(attempt.get("started_at"))
    finished = _parse_iso_timestamp(attempt.get("finished_at"))
    if started is not None and finished is not None:
        try:
            delta_ms = (finished - started).total_seconds() * 1000.0
        except TypeError:
            delta_ms = None
        if delta_ms is not None and delta_ms >= 0:
            return int(round(delta_ms))
    usage = attempt.get("usage")
    if isinstance(usage, dict):
        latency = _non_negative_number(usage.get("latency_ms"))
        if latency is not None:
            return int(round(latency))
    return None


def _merge_attempt_fields(target, incoming):
    for key in ("activation_id", "session_id", "department", "logical_call_id",
                "root_step_id", "step_id", "purpose", "started_at", "finished_at"):
        value = incoming.get(key)
        if value is not None and target.get(key) is None:
            target[key] = value
    if incoming.get("purpose") and incoming["purpose"] != "work":
        target["purpose"] = incoming["purpose"]
    if incoming.get("finished_at") is not None:
        target["finished_at"] = incoming["finished_at"]
    if incoming.get("duration_ms") is not None:
        target["duration_ms"] = incoming["duration_ms"]
    if incoming.get("work_round") is not None:
        target["work_round"] = incoming["work_round"]
    target["usage"] = _merge_usage(target.get("usage"), incoming.get("usage"))


def _resolve_activation_for_event(state, activation_id, session_id, department):
    if isinstance(activation_id, str) and activation_id in state["by_id"]:
        return state["by_id"][activation_id]
    if isinstance(session_id, str) and session_id in state["open_by_session"]:
        return state["open_by_session"][session_id]
    if isinstance(department, str) and department in state["open_by_dept"]:
        return state["open_by_dept"][department]
    return None


def _scan_events_for_rounds(events):
    """按时间顺序解析激活轮次、询问分支归属以及事件侧的模型调用尝试。"""
    state = {
        "activations": [],
        "by_id": {},
        "open_by_session": {},
        "open_by_dept": {},
        "branch_round_by_session": {},
        "current_round": 0,
        "attempts": [],
        "by_attempt_id": {},
        "pending_no_id": {},
    }

    for event in events:
        event_type = event.get("type")
        payload = event.get("payload") or {}
        sid = event.get("session_id")
        dept = event.get("department") or payload.get("department")
        aid = payload.get("activation_id")

        if event_type == "ask_started":
            branch_sid = payload.get("branch_session_id")
            if isinstance(branch_sid, str) and branch_sid:
                caller = _resolve_activation_for_event(state, aid, sid, dept)
                caller_round = caller["round"] if caller is not None else max(state["current_round"], 1)
                state["branch_round_by_session"][branch_sid] = caller_round
            continue

        if event_type == "department_activated":
            seq = len(state["activations"]) + 1
            act_id = aid if isinstance(aid, str) and aid else f"act#{seq}"
            ask_branch = isinstance(sid, str) and sid in state["branch_round_by_session"]
            cycle = _positive_int(payload.get("cycle"))
            if ask_branch:
                round_no = (cycle if cycle is not None
                            else state["branch_round_by_session"].get(sid, max(state["current_round"], 1)))
            elif cycle is not None:
                state["current_round"] = max(state["current_round"], cycle)
                round_no = cycle
            else:
                state["current_round"] += 1
                round_no = state["current_round"]
            act = {
                "sequence": seq,
                "round": round_no,
                "ask_branch": ask_branch,
                "activation_id": act_id,
                "session_id": sid,
                "department": dept,
                "fallback_compaction_recorded": 0,
            }
            state["activations"].append(act)
            state["by_id"][act_id] = act
            if isinstance(sid, str) and sid:
                state["open_by_session"][sid] = act
            if isinstance(dept, str) and dept:
                state["open_by_dept"][dept] = act
            continue

        if event_type == "activation_finished":
            if isinstance(sid, str) and sid in state["open_by_session"]:
                if not aid or state["open_by_session"][sid]["activation_id"] == aid:
                    state["open_by_session"].pop(sid, None)
            if isinstance(dept, str) and dept in state["open_by_dept"]:
                if not aid or state["open_by_dept"][dept]["activation_id"] == aid:
                    state["open_by_dept"].pop(dept, None)
            continue

        if event_type == "compaction_recorded":
            target = _resolve_activation_for_event(state, aid, sid, dept)
            if target is not None:
                target["fallback_compaction_recorded"] += 1
            continue

        if event_type in ATTEMPT_EVENT_TYPES:
            resolved = _resolve_activation_for_event(state, aid, sid, dept)
            resolved_aid = resolved["activation_id"] if resolved is not None else aid
            step_id = payload.get("step_id") if payload.get("step_id") is not None else payload.get("step")
            purpose = payload.get("purpose") or "work"
            started_at = payload.get("started_at")
            finished_at = payload.get("finished_at")
            if event_type == "model_requested" and started_at is None:
                started_at = event.get("created_at")
            if event_type != "model_requested" and finished_at is None:
                finished_at = event.get("created_at")

            record = {
                "activation_id": resolved_aid,
                "session_id": sid,
                "department": dept or (resolved["department"] if resolved is not None else None),
                "logical_call_id": payload.get("logical_call_id"),
                "root_step_id": payload.get("root_step_id"),
                "step_id": step_id,
                "purpose": purpose,
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_ms": payload.get("duration_ms"),
                "usage": payload.get("usage"),
                "work_round": _positive_int(payload.get("cycle")),
            }
            attempt_id = payload.get("attempt_id")
            if isinstance(attempt_id, str) and attempt_id:
                existing = state["by_attempt_id"].get(attempt_id)
                if existing is None:
                    state["by_attempt_id"][attempt_id] = record
                    state["attempts"].append(record)
                else:
                    _merge_attempt_fields(existing, record)
            else:
                pending_key = (resolved_aid, sid, dept, step_id, purpose)
                queue = state["pending_no_id"].setdefault(pending_key, [])
                if event_type == "model_requested":
                    state["attempts"].append(record)
                    queue.append(record)
                elif queue:
                    _merge_attempt_fields(queue.pop(0), record)
                else:
                    state["attempts"].append(record)

    return state


def _merge_export_attempts(state, export_attempts):
    """把 export['attempts'] 中的详细记录合并进来，已按 attempt_id 采集的不重复计。"""
    for item in export_attempts or ():
        if not isinstance(item, dict):
            continue
        attempt_id = item.get("id") or item.get("attempt_id")
        step_id = item.get("step_id") if item.get("step_id") is not None else item.get("step")
        record = {
            "activation_id": item.get("activation_id"),
            "session_id": item.get("session_id"),
            "department": item.get("department"),
            "logical_call_id": item.get("logical_call_id"),
            "root_step_id": item.get("root_step_id"),
            "step_id": step_id,
            "purpose": item.get("purpose") or "work",
            "started_at": item.get("started_at"),
            "finished_at": item.get("finished_at"),
            "duration_ms": item.get("duration_ms"),
            "usage": item.get("usage"),
            "work_round": _positive_int(item.get("work_round")),
        }
        if isinstance(attempt_id, str) and attempt_id:
            existing = state["by_attempt_id"].get(attempt_id)
            if existing is None:
                state["by_attempt_id"][attempt_id] = record
                state["attempts"].append(record)
            else:
                _merge_attempt_fields(existing, record)
        else:
            state["attempts"].append(record)


def _logical_call_key(attempt, index, purpose):
    logical_call_id = attempt.get("logical_call_id")
    if isinstance(logical_call_id, str) and logical_call_id:
        return logical_call_id
    if attempt.get("root_step_id") is not None:
        return f"root:{purpose}:{attempt['root_step_id']}"
    if attempt.get("step_id") is not None:
        return f"step:{purpose}:{attempt['step_id']}"
    return f"idx:{purpose}:{index}"


def _summarize_activation(act, act_attempts):
    work_calls = set()
    compaction_calls = set()
    compaction_attempts = 0
    compaction_durations_ms = []
    reported_requests = 0
    token_sums = {field: 0 for field in ROUND_TOKEN_FIELDS}
    has_token = {field: False for field in ROUND_TOKEN_FIELDS}

    for index, attempt in enumerate(act_attempts):
        purpose = attempt.get("purpose") or "work"
        logical_key = _logical_call_key(attempt, index, purpose)
        if purpose == "compaction":
            compaction_calls.add(logical_key)
            compaction_attempts += 1
            duration = _attempt_duration_ms(attempt)
            if duration is not None:
                compaction_durations_ms.append(duration)
        else:
            work_calls.add(logical_key)

        usage = attempt.get("usage")
        if _usage_is_reported(usage):
            reported_requests += 1
            for field in ROUND_TOKEN_FIELDS:
                value = usage.get(field)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    token_sums[field] += int(value)
                    has_token[field] = True

    compaction_requests = (len(compaction_calls) if compaction_attempts > 0
                           else act["fallback_compaction_recorded"])
    if compaction_durations_ms:
        compaction_duration_ms = sum(compaction_durations_ms)
        compaction_duration_seconds = round(compaction_duration_ms / 1000.0, 1)
        compaction_max_duration_ms = max(compaction_durations_ms)
    elif compaction_attempts == 0 and compaction_requests == 0:
        compaction_duration_ms = 0
        compaction_duration_seconds = 0.0
        compaction_max_duration_ms = 0
    else:
        compaction_duration_ms = None
        compaction_duration_seconds = None
        compaction_max_duration_ms = None

    model_requests = len(act_attempts)
    return {
        "sequence": act["sequence"],
        "round": act["round"],
        "ask_branch": act["ask_branch"],
        "activation_id": act["activation_id"],
        "department": act["department"],
        "work_steps": len(work_calls),
        "model_requests": model_requests,
        "usage_reported_requests": reported_requests,
        "usage_reported_ratio": (round(reported_requests / model_requests, 4)
                                 if model_requests > 0 else None),
        "input_tokens": token_sums["input_tokens"] if has_token["input_tokens"] else None,
        "output_tokens": token_sums["output_tokens"] if has_token["output_tokens"] else None,
        "total_tokens": token_sums["total_tokens"] if has_token["total_tokens"] else None,
        "compaction_requests": compaction_requests,
        "compaction_attempts": compaction_attempts,
        "compaction_duration_ms": compaction_duration_ms,
        "compaction_duration_seconds": compaction_duration_seconds,
        "compaction_max_duration_ms": compaction_max_duration_ms,
    }


def _activation_rounds(export):
    """按每次 `model_attempt_*` 真实归属的激活轮次统计各部门工作步数、用量与压缩耗时。"""
    events = export.get("events") or []
    state = _scan_events_for_rounds(events)
    _merge_export_attempts(state, export.get("attempts"))

    attempts_by_act = {}
    for attempt in state["attempts"]:
        aid = attempt.get("activation_id")
        if isinstance(aid, str) and aid in state["by_id"]:
            key = aid
        else:
            fallback_id = aid if isinstance(aid, str) and aid else f"unscoped:{attempt.get('work_round') or 1}:{attempt.get('department') or ''}"
            if fallback_id not in state["by_id"]:
                seq = len(state["activations"]) + 1
                round_no = attempt.get("work_round") or max(state["current_round"], 1)
                act = {
                    "sequence": seq,
                    "round": round_no,
                    "ask_branch": False,
                    "activation_id": fallback_id,
                    "session_id": attempt.get("session_id"),
                    "department": attempt.get("department"),
                    "fallback_compaction_recorded": 0,
                }
                state["activations"].append(act)
                state["by_id"][fallback_id] = act
            key = fallback_id
        attempts_by_act.setdefault(key, []).append(attempt)

    return [_summarize_activation(act, attempts_by_act.get(act["activation_id"], ()))
            for act in state["activations"]]


# --- 模型服务故障 --------------------------------------------------

def _is_model_service_failure(events):
    """模型服务故障：凭据被拒、连接失败、限流与服务端错误（provider 侧故障）。"""
    for event in events:
        event_type = event.get("type")
        if event_type not in ("model_attempt_failed", "run_paused", "run_failed"):
            continue
        payload = event.get("payload") or {}
        if event_type == "run_failed":
            stop_reason = event.get("stop_reason") or payload.get("stop_reason")
            if stop_reason == "provider_error":
                return True
        text = json.dumps(payload, ensure_ascii=False).lower()
        if any(marker in text for marker in FAILURE_MARKERS):
            return True
    return False