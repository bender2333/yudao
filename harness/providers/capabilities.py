# 模型能力表的只读访问（模型管理设计说明第 4.1、4.3 节）。
# 随发布加载一次索引；候选与选用补全按连接地址识别服务商，再精确查上游 ID。

from __future__ import annotations

from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from ..definitions import DEFINITIONS, ModelCapabilities, ModelCapability, ServicePresets
from .presets import normalized_base_url, preset_id_for_base_url

_TABLE = DEFINITIONS.model_capabilities
CAPABILITY_TABLE_REVISION = _TABLE.revision
CAPABILITY_TABLE_SNAPSHOT_DATE = _TABLE.snapshot_date
CAPABILITY_TABLE_SOURCE = _TABLE.source
CAPABILITY_TABLE_SOURCE_SHA256 = _TABLE.source_sha256


def _public_entry(entry: ModelCapability) -> dict[str, Any]:
    # 公开视图的字段与旧版一致：协议可能为空（接入包没有对应的协议），其余字段照常。
    return {
        "model": entry.model, "protocol": entry.protocol,
        "input_modalities": list(entry.input_modalities), "output_modalities": list(entry.output_modalities),
        "context_window": entry.context_window, "max_output_tokens": entry.max_output_tokens,
        "tool_call": entry.tool_call, "reasoning": entry.reasoning,
    }


class CapabilityIndex:
    def __init__(self, table: ModelCapabilities, presets: ServicePresets) -> None:
        self.table = table
        self.presets = presets
        # 版本 2 的索引按服务商；版本 1 的旧文件只有预置方案的条目，按方案 ID 保留原来的读法。
        self._index = MappingProxyType({
            provider_id: MappingProxyType({entry.model: entry for entry in provider.models})
            for provider_id, provider in table.providers.items()
        })
        self._legacy = MappingProxyType({
            preset_id: MappingProxyType({entry.model: entry for entry in rows})
            for preset_id, rows in table.presets.items()
        })
        # 接口主机 → 服务商；同一个主机对应几个服务商时都不取（地址不足以确定服务商）。
        hosts: dict[str, str | None] = {}
        for provider_id, provider in table.providers.items():
            address = normalized_base_url(provider.api)
            host = urlsplit(address).hostname
            if host and "{" not in host:
                hosts[host] = None if host in hosts else provider_id
        self._hosts = MappingProxyType(hosts)

    def recognize_provider(self, base_url: str) -> str | None:
        # 连接地址等于预置表中某个服务方案的请求基址时取这个方案对应的服务商；
        # 否则主机与某个服务商的接口地址相同时取这个服务商；识别不出时什么都不取。
        preset_id = preset_id_for_base_url(base_url, self.presets.presets)
        if preset_id:
            return next(preset.models_dev_id or None for preset in self.presets.presets if preset.id == preset_id)
        host = urlsplit(normalized_base_url(base_url)).hostname
        return self._hosts.get(host) if host else None

    def capability(self, provider_id: str, model: str) -> ModelCapability | None:
        index = self._index.get(provider_id, self._legacy.get(provider_id))
        return None if index is None else index.get(model)

    def lookup(self, base_url: str, model: str) -> ModelCapability | None:
        # 查找只在识别出的服务商之内按上游模型 ID 精确进行，不去掉前缀，也不跨服务商借用。
        provider_id = self.recognize_provider(base_url)
        return None if provider_id is None else self.capability(provider_id, model)

    def source_details(self, source: str, provider_id: str = "") -> dict[str, str]:
        detail = {"source": source}
        if source == "capability_table":
            preset = next((item for item in self.presets.presets if item.id == provider_id), None)
            detail.update(provider=preset.models_dev_id if preset is not None else provider_id,
                          revision=self.table.revision)
        return detail


CAPABILITY_INDEX = CapabilityIndex(_TABLE, DEFINITIONS.service_presets)


def table_public() -> dict[str, Any]:
    # 整张表的公开信息：revision、快照日期、来源与来源文件的 SHA-256，以及预置服务方案的条目。
    return {
        "version": _TABLE.version,
        "revision": CAPABILITY_TABLE_REVISION,
        "snapshot_date": CAPABILITY_TABLE_SNAPSHOT_DATE,
        "source": CAPABILITY_TABLE_SOURCE,
        "source_sha256": CAPABILITY_TABLE_SOURCE_SHA256,
        "presets": {preset_id: [_public_entry(entry) for entry in rows]
                    for preset_id, rows in _TABLE.presets.items()},
    }


def entries(provider_id: str) -> tuple[ModelCapability, ...]:
    index = CAPABILITY_INDEX._index.get(provider_id, CAPABILITY_INDEX._legacy.get(provider_id))
    return () if index is None else tuple(index[model] for model in sorted(index))


def capability(provider_id: str, model: str) -> ModelCapability | None:
    return CAPABILITY_INDEX.capability(str(provider_id), str(model))


def recognize_provider(base_url: str) -> str | None:
    return CAPABILITY_INDEX.recognize_provider(base_url)


def lookup(base_url: str, model: str) -> ModelCapability | None:
    return CAPABILITY_INDEX.lookup(base_url, model)


def source_details(source: str, provider_id: str = "") -> dict[str, str]:
    return CAPABILITY_INDEX.source_details(source, provider_id)
