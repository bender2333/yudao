from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from .presets import USER_AGENT, preset_known_models, preset_models_url
from .store import ProviderDefinition
from .tls import certificate_verification_failed, service_address, ssl_context


# 候选模型只服务本次设置页会话，不落盘、不自动绑定
def refresh_candidates(
    provider: ProviderDefinition,
    *,
    models_url_override: str | None = None,
    timeout_sec: float = 30.0,
) -> dict[str, Any]:
    source_url = _effective_models_url(provider, models_url_override)
    fetched_at = datetime.now(timezone.utc).isoformat()
    if not source_url:
        return _unknown(provider, "", fetched_at, "未提供模型列表地址，请填写或选择带模型列表的服务方案")
    try:
        with httpx.Client(timeout=timeout_sec, verify=ssl_context()) as client:
            response = client.get(source_url, headers={"User-Agent": USER_AGENT})
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
        hints = preset_known_models(provider.preset_id)
        candidates = _parse_candidates(payload, hints)
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


def _effective_models_url(provider: ProviderDefinition, override: str | None) -> str:
    if isinstance(override, str) and override.strip():
        return override.strip()
    if provider.models_url:
        return provider.models_url
    return preset_models_url(provider.preset_id)


def _parse_candidates(payload: Any, hints: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
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
        hint = hints.get(model_id, {})
        candidates.append({
            "id": model_id,
            "protocol": hint.get("protocol") or None,
            "capability_source": hint.get("capability_source") or None,
        })
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


__all__ = ["refresh_candidates"]
