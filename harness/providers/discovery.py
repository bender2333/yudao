from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import httpx

from . import capabilities
from .presets import USER_AGENT, preset_auth, preset_default_protocol, preset_models_url, preset_id_for_base_url
from .store import ProviderDefinition
from .tls import certificate_verification_failed, service_address, ssl_context


# 候选结果由服务进程保存，不落盘、不自动绑定。
def refresh_candidates(
    provider: ProviderDefinition,
    *,
    models_url_override: str | None = None,
    api_key: str = "",
    timeout_sec: float = 30.0,
) -> dict[str, Any]:
    source_url = effective_models_url(provider, models_url_override)
    fetched_at = datetime.now(timezone.utc).isoformat()
    if not source_url:
        return _unknown(provider, "", fetched_at, "未提供模型列表地址，请填写或选择带模型列表的服务方案",
                        "unreachable")
    if not api_key.strip():
        return _unknown(provider, source_url, fetched_at,
                        f"模型列表请求 {source_url}：凭据引用 {provider.credential_ref or '（未填写）'} 无法解析，请在模型管理中配置凭据",
                        "credential_missing")
    try:
        headers = {**_auth_headers(provider, api_key), "User-Agent": USER_AGENT}
        with httpx.Client(timeout=timeout_sec, verify=ssl_context()) as client:
            response = client.get(source_url, headers=headers)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403):
            return _unknown(provider, source_url, fetched_at,
                            f"模型列表请求 {source_url} 返回 HTTP {status}：服务拒绝了这个 API Key",
                            "credential_rejected")
        hint = ""
        if status == 404 and any(provider.base_url.endswith(suffix) for suffix in
                                 ("/chat/completions", "/responses", "/messages")):
            hint = "；请将服务地址填写到当前推理接口的上一级"
        return _unknown(provider, source_url, fetched_at,
                        f"模型列表请求 {source_url} 返回 HTTP {status}{hint}", "http_status")
    except httpx.HTTPError as exc:
        if certificate_verification_failed(exc):
            return _unknown(provider, source_url, fetched_at,
                            f"模型列表请求 {source_url} 失败：证书校验失败（{service_address(source_url)}）", "unreachable")
        return _unknown(provider, source_url, fetched_at,
                        f"模型列表请求 {source_url} 连接失败：{_connection_reason(exc)}", "unreachable")
    except ValueError:
        received = response.headers.get("content-type", "未声明内容类型")
        return _unknown(provider, source_url, fetched_at,
                        f"模型列表请求 {source_url} 返回的内容不是合法 JSON（内容类型：{received}）", "invalid_response")
    try:
        candidates = _parse_candidates(payload, provider.preset_id, base_url=provider.base_url)
    except ValueError as exc:
        return _unknown(provider, source_url, fetched_at,
                        f"模型列表请求 {source_url} 返回的不是模型列表：{exc}", "invalid_response")
    if not candidates:
        return _unknown(provider, source_url, fetched_at,
                        f"模型列表请求 {source_url} 已连接，但服务没有返回任何模型；请检查 API Key 的模型权限", "empty_list")
    return {
        "provider_id": provider.id,
        "source_url": source_url,
        "fetched_at": fetched_at,
        "status": "ok",
        "candidates": candidates,
        "error": None,
        "reason": None,
    }


# 连接测试只读取模型列表地址，证明地址与凭据可用，不改变任何准入
def probe_connection(
    provider: ProviderDefinition,
    *,
    api_key: str = "",
    timeout_sec: float = 30.0,
) -> dict[str, Any]:
    source_url = effective_models_url(provider)
    if not source_url:
        return {"ok": False, "source_url": "",
                "reason": "no_models_url", "message": "连接与服务方案都没有模型列表地址，不提供连接测试"}
    headers = {**_auth_headers(provider, api_key), "User-Agent": USER_AGENT}
    try:
        with httpx.Client(timeout=timeout_sec, verify=ssl_context()) as client:
            response = client.get(source_url, headers=headers)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        reason = "credential_rejected" if status in (401, 403) else "upstream_error"
        return {"ok": False, "source_url": source_url, "reason": reason,
                "message": f"模型列表请求 {source_url} 返回 HTTP {status}"}
    except httpx.HTTPError as exc:
        if certificate_verification_failed(exc):
            return {"ok": False, "source_url": source_url, "reason": "upstream_error",
                    "message": f"模型列表请求 {source_url} 失败：证书校验失败（{service_address(source_url)}）"}
        return {"ok": False, "source_url": source_url, "reason": "upstream_error",
                "message": f"模型列表请求 {source_url} 连接失败：{_connection_reason(exc)}"}
    return {"ok": True, "source_url": source_url, "reason": "", "message": ""}


def _auth_headers(provider: ProviderDefinition, api_key: str) -> dict[str, str]:
    # 模型列表地址要求认证时按服务方案规定的认证方式带上凭据（设计说明第 4.2 节）：
    # 内置方案取预置表的 auth，自定义服务使用 Bearer；没有凭据时不带认证头，由上游决定拒绝
    if not api_key:
        return {}
    if preset_auth(provider.preset_id) == "x-api-key":
        return {"x-api-key": api_key}
    return {"Authorization": f"Bearer {api_key}"}

def effective_models_url(provider: ProviderDefinition, override: str | None = None) -> str:
    # 用户写入的模型列表地址优先；自定义服务随连接地址计算默认值。
    if isinstance(override, str) and override.strip():
        return override.strip()
    if provider.models_url:
        return provider.models_url
    if provider.preset_id:
        return preset_models_url(provider.preset_id)
    return provider.base_url.rstrip("/") + "/models"


# 上游模型列表描述容量（窗口与输出上限）的写法，按次序取到第一个有效的就停（设计说明第 4.3 节）。
# 固定路径：limit.context / limit.output（OpenCode 一类）、context_length / max_completion_tokens（OpenRouter 一类的顶层写法）、
# top_provider 下的同名字段、capabilities.contextWindow / capabilities.maxOutput。
# 各家另有的别名按同样的次序追加：model_info 里以 .context_length 结尾的键（Ollama）、max_context_window_tokens（GitHub Copilot）、
# max_model_len（vLLM）、loaded_context_length 与 max_context_length（LM Studio）、context_window_tokens（OpenAI 兼容网关）；
# 输出上限另有顶层的 max_output_tokens 与 capabilities.limit.output。
# 路径的末段写成 "*<后缀>" 时表示「容器里任意以该后缀结尾的键」（Ollama 的 model_info 用它）。
_UPSTREAM_LIMIT_PATHS: dict[str, tuple[tuple[str, ...], ...]] = {
    "context_window": (("limit", "context"), ("context_length",),
                       ("top_provider", "context_length"), ("capabilities", "contextWindow"),
                       ("model_info", "*.context_length"), ("model_info", "*.num_ctx"),
                       ("max_context_window_tokens",), ("max_model_len",),
                       ("loaded_context_length",), ("max_context_length",),
                       ("context_window_tokens",)),
    "max_output_tokens": (("limit", "output"), ("max_completion_tokens",),
                          ("top_provider", "max_completion_tokens"), ("capabilities", "maxOutput"),
                          ("max_output_tokens",), ("capabilities", "limit", "output")),
    "max_input_tokens": (("limit", "input"),),
}

# 路径末段以 _SUFFIX_MARK 开头时，那一段是后缀而不是键名
_SUFFIX_MARK = "*"


def _is_positive_int(value: Any) -> bool:
    # 只有正整数算容量：布尔、小数、0 与负数都当没有
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _first_positive_int(item: Mapping[str, Any], paths: tuple[tuple[str, ...], ...]) -> int | None:
    # 按次序取第一个有效的正整数字：布尔、小数、0 与负数都当没有，取不到时返回 None
    for path in paths:
        if path[-1].startswith(_SUFFIX_MARK):
            value = _first_positive_int_by_suffix(item, path[:-1], path[-1][len(_SUFFIX_MARK):])
        else:
            value = _value_at(item, path)
        if _is_positive_int(value):
            return value
    return None


def _first_positive_int_by_suffix(item: Mapping[str, Any], container_path: tuple[str, ...],
                                   suffix: str) -> int | None:
    # 容器里任意以该后缀结尾的键（Ollama 的 model_info）：按容器里的次序取第一个正整数
    container = _value_at(item, container_path)
    if not isinstance(container, Mapping):
        return None
    for key, value in container.items():
        if isinstance(key, str) and key.endswith(suffix) and _is_positive_int(value):
            return value
    return None


def _value_at(item: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    # 按路径取嵌套字段；中间任一层不是对象时当作没有这个字段
    value: Any = item
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _parse_candidates(payload: Any, preset_id: str, *, base_url: str | None = None,
                      capability_index: capabilities.CapabilityIndex | None = None) -> list[dict[str, Any]]:
    # 候选的来源规则由设计说明第 4.3 节规定；没有明确的输出类型时保持适用。
    items = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        kind = _content_kind(items if isinstance(payload, dict) and "data" in payload else payload)
        raise ValueError(f"收到{kind}，需要模型数组或含 data 数组的对象")
    candidates: list[dict[str, Any]] = []
    index = capability_index if capability_index is not None else capabilities.CAPABILITY_INDEX
    provider_id = index.recognize_provider(base_url) if base_url is not None else preset_id
    effective_preset = preset_id_for_base_url(base_url, index.presets.presets) if base_url is not None else preset_id

    seen: set[str] = set()
    for item in items:
        model_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        model_id = model_id.strip()
        if model_id in seen:
            continue
        seen.add(model_id)
        # 上游列表带窗口与输出上限时带上这两项，来源是上游模型列表。上游的写法有四种，按
        # _UPSTREAM_LIMIT_PATHS 的次序取到第一个有效的就停；窗口与输出上限各自独立取
        candidate: dict[str, Any] = {"id": model_id}
        entry = index.lookup(base_url, model_id) if base_url is not None else index.capability(provider_id or "", model_id)
        # 协议先取能力表（识别出的服务商之内，模型自己声明的接入包优先）；
        # 能力表里没有这个模型或它的协议为空时，内置服务方案取方案的默认协议，其余取 Chat Completions。
        if entry is not None and entry.protocol:
            candidate["protocol"], candidate["protocol_source"] = entry.protocol, "capability_table"
        elif effective_preset:
            candidate["protocol"], candidate["protocol_source"] = (
                preset_default_protocol(effective_preset), "preset_default")
        else:
            candidate["protocol"], candidate["protocol_source"] = ("chat_completions", "default")
        for field, paths in _UPSTREAM_LIMIT_PATHS.items():
            value = _first_positive_int(item, paths)
            if value is not None:
                candidate[field] = value
                candidate[f"{field}_source"] = "models_url"

        for field in ("context_window", "max_output_tokens", "max_input_tokens"):
            if field not in candidate and entry is not None and getattr(entry, field) is not None:
                candidate[field] = getattr(entry, field)
                candidate[f"{field}_source"] = "capability_table"
        inputs = _modalities(item, "input")
        input_source = "models_url"
        if inputs is None:
            inputs = list(entry.input_modalities) if entry is not None and entry.input_modalities else None
            input_source = "capability_table" if inputs is not None else "default"
        candidate["input_modalities"] = ["text", "image"] if inputs and "image" in inputs else ["text"]
        candidate["input_modalities_source"] = input_source
        outputs = _modalities(item, "output")
        output_source = "models_url"
        if outputs is None:
            outputs = list(entry.output_modalities) if entry is not None and entry.output_modalities else None
            output_source = "capability_table" if outputs is not None else "default"
        if outputs is not None:
            candidate["output_modalities"] = outputs
            candidate["output_modalities_source"] = output_source
        reasoning = item.get("reasoning")
        if not isinstance(reasoning, bool):
            reasoning = _value_at(item, ("capabilities", "reasoning"))
        if isinstance(reasoning, bool):
            candidate["reasoning"], candidate["reasoning_source"] = reasoning, "models_url"
        else:
            candidate["reasoning"] = entry.reasoning if entry is not None else None
            candidate["reasoning_source"] = "capability_table" if entry is not None else "default"
        candidate["provider"] = model_id.split("/", 1)[0] if "/" in model_id else None
        candidate["applicable"] = outputs is None or "text" in outputs
        candidate["applicable_source"] = output_source
        candidate["source_details"] = {
            field.removesuffix("_source"): index.source_details(source, provider_id or "")
            for field, source in candidate.items() if field.endswith("_source")
        }
        candidates.append(candidate)
    if items and not candidates:
        raise ValueError("收到数组，但其中没有带有效 id 的模型对象")
    candidates.sort(key=lambda entry: entry["id"])
    return candidates


def _modalities(item: Mapping[str, Any], direction: str) -> list[str] | None:
    for path in (("modalities", direction), (f"{direction}_modalities",),
                 ("architecture", f"{direction}_modalities")):
        value = _value_at(item, path)
        if isinstance(value, list) and value and all(isinstance(part, str) and part for part in value):
            return value
    return None


def _content_kind(value: Any) -> str:
    if isinstance(value, dict):
        return "对象"
    if isinstance(value, list):
        return "数组"
    if isinstance(value, str):
        return "字符串"
    if value is None:
        return "空值"
    return "布尔值" if isinstance(value, bool) else "数值"


def _connection_reason(exc: httpx.HTTPError) -> str:
    # 连接失败的原因写成用户看得懂的中文：无法解析主机、连接被拒绝、超时（设计说明第 9.1 节）
    if isinstance(exc, httpx.TimeoutException):
        return "请求超时"
    seen: set[int] = set()
    cause: BaseException | None = exc
    texts: list[str] = []
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        texts.append(f"{type(cause).__name__}: {cause}")
        if type(cause).__name__ == "gaierror":
            return "无法解析主机"
        if isinstance(cause, ConnectionRefusedError):
            return "连接被拒绝"
        if isinstance(cause, TimeoutError):
            return "请求超时"
        cause = cause.__cause__ or cause.__context__
    joined = "\n".join(texts).lower()
    if any(token in joined for token in ("name or service not known", "nodename nor servname",
                                         "getaddrinfo", "name resolution", "temporary failure",
                                         "无法解析", "dns")):
        return "无法解析主机"
    if any(token in joined for token in ("refused", "拒绝", "10061", "10060", "timed out", "timeout")):
        if "timed out" in joined or "timeout" in joined:
            return "请求超时"
        return "连接被拒绝"
    return f"连接失败：{exc}"


def _unknown(provider: ProviderDefinition, source_url: str, fetched_at: str, error: str,
             reason: str) -> dict[str, Any]:
    # 上游不可用时候选未知，不沿用上次结果
    return {
        "provider_id": provider.id,
        "source_url": source_url,
        "fetched_at": fetched_at,
        "status": "unknown",
        "candidates": [],
        "error": error,
        "reason": reason,
    }


__all__ = ["effective_models_url", "probe_connection", "refresh_candidates"]
