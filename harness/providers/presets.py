from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping


# 预置表是模块内数据，带版本与来源，不做远端热更（ADR-0003）
PRESET_TABLE_VERSION = "2026-09-19.1"
PRESET_TABLE_SOURCE = "https://opencode.ai/docs/go/ 与 https://opencode.ai/zen/go/v1/models（2026-09-19 采集）"


def _preset(
    preset_id: str,
    name: str,
    *,
    auth: str,
    endpoints: Mapping[str, str],
    models_url: str,
    docs_url: str,
    header_profile: str = "",
    source: str = "",
    notes: str = "",
    known_models: tuple[Mapping[str, str], ...] = (),
) -> dict[str, Any]:
    return {
        "id": preset_id,
        "name": name,
        "auth": auth,
        "endpoints": dict(endpoints),
        "models_url": models_url,
        "docs_url": docs_url,
        "header_profile": header_profile,
        "source": source,
        "notes": notes,
        "known_models": [dict(item) for item in known_models],
    }


# 每个模型访问定义只声明一条协议，同一服务下的不同模型可以走不同协议
_PRESETS: tuple[dict[str, Any], ...] = (
    _preset(
        "opencode-go",
        "OpenCode Go",
        auth="api_key",
        endpoints={
            "responses": "https://opencode.ai/zen/go/v1/responses",
            "chat_completions": "https://opencode.ai/zen/go/v1/chat/completions",
            "messages": "https://opencode.ai/zen/go/v1/messages",
        },
        models_url="https://opencode.ai/zen/go/v1/models",
        docs_url="https://opencode.ai/docs/go/",
        header_profile="opencode-go",
        source="https://opencode.ai/docs/go/#endpoints（2026-09-19）",
        notes=(
            "订阅套餐使用 API Key；请求需带真实客户端 User-Agent 与 x-opencode-session。"
            "模型列表只给 ID，协议与容量需按访问定义声明并测试准入。"
        ),
        known_models=(
            {"model_id": "gpt-5.6-luna", "protocol": "responses", "capability_source": "预置提示：官方端点示例（2026-09-19），未验证"},
            {"model_id": "glm-5.1", "protocol": "chat_completions", "capability_source": "预置提示：官方端点示例（2026-09-19），未验证"},
            {"model_id": "minimax-m2.7", "protocol": "messages", "capability_source": "预置提示：官方端点示例（2026-09-19），未验证"},
        ),
    ),
)

_PRESET_INDEX: Mapping[str, dict[str, Any]] = MappingProxyType(
    {item["id"]: item for item in _PRESETS}
)


# Yudao 自己的客户端身份，不冒充其他编码代理
USER_AGENT = "Yudao-Loop-System/0.1 (+https://github.com/bender2333/yudao)"


def list_presets() -> list[dict[str, Any]]:
    # 按声明顺序返回，OpenCode Go 是第一个落地的服务方案
    return [_public_preset(item) for item in _PRESETS]


def get_preset(preset_id: str) -> dict[str, Any] | None:
    item = _PRESET_INDEX.get(str(preset_id))
    return None if item is None else _public_preset(item)


def preset_exists(preset_id: str) -> bool:
    return str(preset_id) in _PRESET_INDEX


def preset_models_url(preset_id: str) -> str:
    item = _PRESET_INDEX.get(str(preset_id))
    return "" if item is None else str(item["models_url"])


def preset_header_profile(preset_id: str) -> str:
    item = _PRESET_INDEX.get(str(preset_id))
    return "" if item is None else str(item["header_profile"])


def preset_known_models(preset_id: str) -> dict[str, dict[str, str]]:
    # 预置提示只描述来源，不当成已验证能力
    item = _PRESET_INDEX.get(str(preset_id))
    if item is None:
        return {}
    return {
        str(hint["model_id"]): {
            "protocol": str(hint["protocol"]),
            "capability_source": str(hint["capability_source"]),
        }
        for hint in item["known_models"]
    }


def build_identity_headers(header_profile: str, session_id: str) -> dict[str, str]:
    # Go 需要稳定会话标识与真实客户端身份；其他服务方案不带额外头
    if header_profile != "opencode-go":
        return {}
    headers = {"User-Agent": USER_AGENT}
    if session_id:
        headers["x-opencode-session"] = str(session_id)
    return headers


def _public_preset(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "name": item["name"],
        "auth": item["auth"],
        "endpoints": dict(item["endpoints"]),
        "models_url": item["models_url"],
        "docs_url": item["docs_url"],
        "header_profile": item["header_profile"],
        "source": item["source"],
        "notes": item["notes"],
        "known_models": [dict(hint) for hint in item["known_models"]],
    }


__all__ = [
    "PRESET_TABLE_VERSION",
    "PRESET_TABLE_SOURCE",
    "USER_AGENT",
    "build_identity_headers",
    "get_preset",
    "list_presets",
    "preset_exists",
    "preset_header_profile",
    "preset_known_models",
    "preset_models_url",
]
