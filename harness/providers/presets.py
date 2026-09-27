from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from ..definitions import DEFINITIONS, ServicePreset

# 服务方案预置表是带版本的定义（definitions/service_presets.json），整张表带 revision 与来源，
# 不做远端热更（ADR-0003）；新增服务方案等于在定义中新增一项
_TABLE = DEFINITIONS.service_presets
PRESET_TABLE_VERSION = _TABLE.revision
PRESET_TABLE_SOURCE = _TABLE.source

_PRESET_INDEX: Mapping[str, ServicePreset] = MappingProxyType({item.id: item for item in _TABLE.presets})


# Yudao 自己的客户端身份，不冒充其他编码代理
USER_AGENT = "Yudao-Loop-System/0.1 (+https://github.com/bender2333/yudao)"


def list_presets() -> list[dict[str, Any]]:
    # 按声明顺序返回，OpenCode Go 是第一个落地的服务方案
    return [_public_preset(item) for item in _TABLE.presets]


def get_preset(preset_id: str) -> dict[str, Any] | None:
    item = _PRESET_INDEX.get(str(preset_id))
    return None if item is None else _public_preset(item)


def preset_exists(preset_id: str) -> bool:
    return str(preset_id) in _PRESET_INDEX


def preset_models_url(preset_id: str) -> str:
    item = _PRESET_INDEX.get(str(preset_id))
    return "" if item is None else item.models_url


def preset_header_profile(preset_id: str) -> str:
    item = _PRESET_INDEX.get(str(preset_id))
    return "" if item is None else item.header_profile


def preset_known_models(preset_id: str) -> dict[str, dict[str, str]]:
    # 预置提示只描述来源，不当成已验证能力
    item = _PRESET_INDEX.get(str(preset_id))
    if item is None:
        return {}
    return {
        hint.model_id: {"protocol": hint.protocol, "capability_source": hint.capability_source}
        for hint in item.known_models
    }


def build_identity_headers(header_profile: str, session_id: str) -> dict[str, str]:
    # Go 需要稳定会话标识与真实客户端身份；其他服务方案不带额外头
    if header_profile != "opencode-go":
        return {}
    headers = {"User-Agent": USER_AGENT}
    if session_id:
        headers["x-opencode-session"] = str(session_id)
    return headers


def _public_preset(item: ServicePreset) -> dict[str, Any]:
    # 每次交回新的字典，调用方改不到定义
    return item.model_dump(mode="json")


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
