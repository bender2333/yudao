from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import httpx

from . import capabilities
from .presets import USER_AGENT, preset_auth, preset_models_url
from .store import ProviderDefinition
from .tls import certificate_verification_failed, service_address, ssl_context


# 候选模型只服务本次设置页会话，不落盘、不自动绑定
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
        return _unknown(provider, "", fetched_at, "未提供模型列表地址，请填写或选择带模型列表的服务方案")
    if not api_key.strip():
        return _unknown(provider, source_url, fetched_at,
                        f"凭据引用 {provider.credential_ref or '（未填写）'} 无法解析，请在模型管理中配置凭据")
    try:
        headers = {**_auth_headers(provider, api_key), "User-Agent": USER_AGENT}
        with httpx.Client(timeout=timeout_sec, verify=ssl_context()) as client:
            response = client.get(source_url, headers=headers)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        return _unknown(provider, source_url, fetched_at, f"模型列表返回 HTTP {exc.response.status_code}")
    except httpx.HTTPError as exc:
        if certificate_verification_failed(exc):
            return _unknown(provider, source_url, fetched_at,
                            f"模型列表请求失败：证书校验失败（{service_address(source_url)}）")
        return _unknown(provider, source_url, fetched_at, f"模型列表请求失败：{type(exc).__name__}")
    except ValueError:
        return _unknown(provider, source_url, fetched_at, "模型列表不是合法 JSON")
    try:
        candidates = _parse_candidates(payload, provider.preset_id)
    except ValueError as exc:
        return _unknown(provider, source_url, fetched_at, str(exc))
    if not candidates:
        return _unknown(provider, source_url, fetched_at, "模型列表为空")
    return {
        "provider_id": provider.id,
        "source_url": source_url,
        "fetched_at": fetched_at,
        "status": "ok",
        "candidates": candidates,
        "error": None,
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
                "message": f"模型列表返回 HTTP {status}"}
    except httpx.HTTPError as exc:
        if certificate_verification_failed(exc):
            return {"ok": False, "source_url": source_url, "reason": "upstream_error",
                    "message": f"模型列表请求失败：证书校验失败（{service_address(source_url)}）"}
        return {"ok": False, "source_url": source_url, "reason": "upstream_error",
                "message": f"模型列表请求失败：{type(exc).__name__}"}
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


def _parse_candidates(payload: Any, preset_id: str) -> list[dict[str, Any]]:
    # 候选带预填值与来源（设计说明第 4.3 节）：窗口与输出上限先取上游模型列表（来源 models_url），
    # 其次取模型能力表（来源 capability_table），两处都没有时留空；输入方式取能力表，
    # 包含 image 时预填文本与图像，不包含 image、能力表没有记录或服务方案为自定义时只有文本。
    # 不按模型名称推测
    items = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError("模型列表缺少 data 数组")
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        model_id = item.get("id") if isinstance(item, dict) else None
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        model_id = model_id.strip()
        if model_id in seen:
            continue
        seen.add(model_id)
        # 上游列表带窗口与输出上限时（limit.context 与 limit.output）带上这两项，来源是上游模型列表
        candidate: dict[str, Any] = {"id": model_id}
        limits = item.get("limit") if isinstance(item, dict) else None
        if isinstance(limits, Mapping):
            window = limits.get("context")
            output = limits.get("output")
            if isinstance(window, int) and not isinstance(window, bool) and window > 0:
                candidate["context_window"] = window
                candidate["context_window_source"] = "models_url"
            if isinstance(output, int) and not isinstance(output, bool) and output > 0:
                candidate["max_output_tokens"] = output
                candidate["max_output_tokens_source"] = "models_url"
        entry = capabilities.capability(preset_id, model_id) if preset_id else None
        for field in ("context_window", "max_output_tokens"):
            if field not in candidate and entry is not None and getattr(entry, field) is not None:
                candidate[field] = getattr(entry, field)
                candidate[f"{field}_source"] = "capability_table"
        modalities = ["text"]
        if entry is not None and "image" in entry.input_modalities:
            modalities = ["text", "image"]
        candidate["input_modalities"] = modalities
        candidate["input_modalities_source"] = "capability_table" if entry is not None else "default"
        candidates.append(candidate)
    candidates.sort(key=lambda entry: entry["id"])
    return candidates


def _unknown(provider: ProviderDefinition, source_url: str, fetched_at: str, error: str) -> dict[str, Any]:
    # 上游不可用时候选未知，不沿用上次结果
    return {
        "provider_id": provider.id,
        "source_url": source_url,
        "fetched_at": fetched_at,
        "status": "unknown",
        "candidates": [],
        "error": error,
    }


__all__ = ["effective_models_url", "probe_connection", "refresh_candidates"]
