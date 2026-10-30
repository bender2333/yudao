"""两边的运行条件之一：被测模型的容量（评测场景设计第 3 节「模型的容量」）。

上下文窗口与单次输出上限取模型服务的模型列表（`YUDAO_EVAL_BASE_URL` 加 `/models`）
为这个模型报告的值（`context_length`、`max_completion_tokens`），列表没有报告时用运行器
参数 `--context-window`、`--max-output-tokens`，两者都没有时报错。Yudao 一侧写进模型
访问定义，OpenCode 一侧写进运行配置的模型限额，两处用同一对数，报告写明取值与来源。

凭据只从环境变量读（用户环境变量 `YUDAO_EVAL_BASE_URL`、`YUDAO_EVAL_API_KEY`），
不写进代码、事件、日志与提交。
"""

import json
import os
import urllib.request

MODEL_SERVICE_BASE_URL_ENV = "YUDAO_EVAL_BASE_URL"
MODEL_SERVICE_API_KEY_ENV = "YUDAO_EVAL_API_KEY"
TIMEOUT_SECONDS = 120.0

# 模型列表里报告容量的字段与运行器里的名字
FIELDS = (("context_window", "context_length"), ("max_output_tokens", "max_completion_tokens"))
SOURCE_LABELS = {"model_list": "模型服务的模型列表", "argument": "运行器参数"}
ARGUMENTS = {"context_window": "--context-window", "max_output_tokens": "--max-output-tokens"}


def models_url(base_url):
    """模型列表的地址：模型服务地址加 `/models`。"""
    return base_url.rstrip("/") + "/models"


def service_settings():
    """模型服务的地址与凭据（运行配置第 4 节）。"""
    base_url = (os.environ.get(MODEL_SERVICE_BASE_URL_ENV) or "").strip()
    if not base_url:
        raise RuntimeError("the model service address is not in " + MODEL_SERVICE_BASE_URL_ENV)
    api_key = (os.environ.get(MODEL_SERVICE_API_KEY_ENV) or "").strip()
    if not api_key:
        raise RuntimeError("the model service credential is not in " + MODEL_SERVICE_API_KEY_ENV)
    return base_url.rstrip("/"), api_key


def fetch_model_list(base_url, api_key):
    """取回模型服务的模型列表（地址加 `/models`）。"""
    request = urllib.request.Request(models_url(base_url),
                                     headers={"Authorization": "Bearer " + api_key})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def reported_limits(payload, model_id):
    """模型列表为这个模型报告的容量：没有报告、或列表里没有这个模型时，两项都为 None。"""
    items = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError("the model list has no data array")
    for item in items:
        if not isinstance(item, dict) or item.get("id") != model_id:
            continue
        return {name: _positive_int(item.get(field)) for name, field in FIELDS}
    return {name: None for name, _field in FIELDS}


def resolve_limits(model_id, reported, context_window=None, max_output_tokens=None):
    """列表报告的值优先，其次运行器参数；两者都没有时报错（第 3 节「模型的容量」）。

    返回四项：两个取值与各自的来源（`model_list` 或 `argument`），报告照这两项写。
    """
    given = {"context_window": context_window, "max_output_tokens": max_output_tokens}
    limits = {}
    for name, _field in FIELDS:
        reported_value = reported.get(name)
        if reported_value is not None:
            limits[name] = reported_value
            limits[name + "_source"] = "model_list"
            continue
        if given[name] is None:
            raise RuntimeError("the model list does not report " + name + " for " + model_id
                               + "; give " + ARGUMENTS[name])
        value = _positive_int(given[name])
        if value is None:
            raise RuntimeError(ARGUMENTS[name] + " must be a positive integer")
        limits[name] = value
        limits[name + "_source"] = "argument"
    return limits


def model_limits(model_id, context_window=None, max_output_tokens=None,
                 base_url=None, api_key=None):
    """取一次被测模型的容量：两个运行器都经这里取值，两边的条件因此相同。"""
    if base_url is None or api_key is None:
        configured_url, configured_key = service_settings()
        base_url = configured_url if base_url is None else base_url
        api_key = configured_key if api_key is None else api_key
    return resolve_limits(model_id, reported_limits(fetch_model_list(base_url, api_key), model_id),
                          context_window, max_output_tokens)


def describe(limits):
    """报告里的一句话：两项取值与来源。"""
    return ("上下文窗口 " + str(limits["context_window"]) + "（"
            + SOURCE_LABELS[limits["context_window_source"]] + "），单次输出上限 "
            + str(limits["max_output_tokens"]) + "（"
            + SOURCE_LABELS[limits["max_output_tokens_source"]] + "）")


def _positive_int(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value
