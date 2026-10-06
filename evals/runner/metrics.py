"""OpenCode 一侧的指标收集：结束状态与原因、请求数、用量、耗时。

数据来源只有 `opencode run --format json` 的输出与运行器计时（第 5.2 节）。
"""

MODEL_SERVICE_FAILURE = "model_service_failure"


def collect(outcome, events, run_dir=None):
    """从一次运行的输出与计时算指标。"""
    requests = []
    errors = []
    for event in events:
        kind = event.get("type")
        if kind == "step_finish":
            part = event.get("part") or {}
            requests.append({
                "tokens": part.get("tokens") or {},
                "cost": part.get("cost") or 0,
                "reason": part.get("reason", ""),
            })
        elif kind == "error":
            errors.append(_error_text(event.get("error")))

    tokens = _sum_tokens([item["tokens"] for item in requests])
    model_service_failure = _is_model_service_failure(errors)

    if outcome["timed_out"]:
        status, reason = "ended", "time_limit"
    elif model_service_failure:
        status, reason = "ended", MODEL_SERVICE_FAILURE
    elif outcome["returncode"] == 0:
        status, reason = "ended", "stop"
    else:
        status, reason = "ended", "nonzero_exit"

    return {
        "status": status,
        "reason": reason,
        "timed_out": outcome["timed_out"],
        "returncode": outcome["returncode"],
        "request_count": len(requests),
        "input_tokens": tokens["input"],
        "output_tokens": tokens["output"],
        "cache_read_tokens": tokens["cache_read"],
        "cache_write_tokens": tokens["cache_write"],
        "cost": sum(float(item["cost"] or 0) for item in requests),
        "elapsed_seconds": round(outcome["elapsed_seconds"], 3),
        "errors": errors,
        "model_service_failure": model_service_failure,
    }


def _error_text(error):
    if not isinstance(error, dict):
        return str(error)
    text = str(error.get("name") or "")
    data = error.get("data")
    if isinstance(data, dict) and "message" in data:
        text = text + ": " + str(data["message"])
    return text


# 模型服务故障：凭据被拒、连接失败、限流与服务端错误（provider 侧的故障），
# 这类运行单独记录并补跑，不计入结果。
_FAILURE_MARKERS = (
    "apierror",
    "providerautherror",
    "providererror",
    "connectionerror",
    "overloaded",
    "rate_limit",
    "rate limit",
    "too many requests",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
    "internal server error",
    "fetch failed",
    "econnreset",
    "etimedout",
    "socket hang up",
    "http 429",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
)


def _is_model_service_failure(errors):
    for text in errors:
        lowered = text.lower()
        if any(marker in lowered for marker in _FAILURE_MARKERS):
            return True
    return False


def _sum_tokens(token_list):
    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    for tokens in token_list:
        cache = tokens.get("cache") or {}
        totals["input"] += int(tokens.get("input") or 0)
        totals["output"] += int(tokens.get("output") or 0)
        totals["cache_read"] += int(cache.get("read") or 0)
        totals["cache_write"] += int(cache.get("write") or 0)
    return totals