from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from ..definitions import DEFINITIONS, ServicePreset, thaw

# 服务方案预置表是带版本的定义（definitions/service_presets.json），整张表带 revision 与来源，
# 不做远端热更（模型管理设计说明第 4.1 节）；新增服务方案等于在定义中新增一项
_TABLE = DEFINITIONS.service_presets
PRESET_TABLE_VERSION = _TABLE.revision
PRESET_TABLE_SOURCE = _TABLE.source

_PRESET_INDEX: Mapping[str, ServicePreset] = MappingProxyType({item.id: item for item in _TABLE.presets})


# Yudao 自己的客户端身份，不冒充其他编码代理
USER_AGENT = "Yudao-Loop-System/0.1 (+https://github.com/bender2333/yudao)"


def list_presets() -> list[dict[str, Any]]:
    # 与 get_preset 读同一份索引，测试替换其中一项时公开视图同步
    return [_public_preset(item) for item in _PRESET_INDEX.values()]


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


def preset_default_protocol(preset_id: str) -> str:
    # 服务方案的默认协议（设计说明第 4.1 节）：能力表中没有这个模型时预填它；
    # 不是预置方案（自定义服务）时返回空串，由调用方预填 Chat Completions
    item = _PRESET_INDEX.get(str(preset_id))
    return "" if item is None else item.default_protocol


def preset_base_url(preset_id: str, protocol: str) -> str:
    # 内置服务方案按访问定义的协议取请求基址（模型管理设计说明第 4.2 节）；没有该协议的基址或不是预置方案时返回空串，
    # 由调用方回落到连接的地址
    item = _PRESET_INDEX.get(str(preset_id))
    return "" if item is None else item.base_urls.get(str(protocol), "")


def preset_auth(preset_id: str) -> str:
    # 服务方案要求的认证方式，供连接测试与候选采集按方案取（模型管理设计说明第 4.1 节）
    item = _PRESET_INDEX.get(str(preset_id))
    return "" if item is None else item.auth


def build_identity_headers(header_profile: str, session_id: str) -> dict[str, str]:
    # Go 需要稳定会话标识与真实客户端身份；其他服务方案不带额外头
    if header_profile != "opencode-go":
        return {}
    headers = {"User-Agent": USER_AGENT}
    if session_id:
        headers["x-opencode-session"] = str(session_id)
    return headers


def _public_preset(item: ServicePreset) -> dict[str, Any]:
    # 每次交回新的字典；预置表只含接入规则，不带模型
    return {
        "id": item.id,
        "name": item.name,
        "default_protocol": item.default_protocol,
        "base_urls": thaw(item.base_urls),
        "models_url": item.models_url,
        "docs_url": item.docs_url,
        "header_profile": item.header_profile,
        "source": item.source,
        "notes": item.notes,
    }


__all__ = [
    "PRESET_TABLE_VERSION",
    "PRESET_TABLE_SOURCE",
    "USER_AGENT",
    "build_identity_headers",
    "get_preset",
    "list_presets",
    "preset_default_protocol",
    "preset_header_profile",
    "preset_models_url",
]
