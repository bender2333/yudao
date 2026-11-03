# 服务方案预置表与模型能力表（definitions/service_presets.json、definitions/model_capabilities.json）：
# 类型、加载与核对。它们只用于预填与界面显示（模型管理设计说明第 4.1、4.3 节），裁决用不到，因此不在内核
# 模块里（工单 #1452）。结构与它们之间的引用照旧整份拒绝：任何一项不合法都抛出 DefinitionError，
# 写明文件与项；程序在启动时加载定义的那一步报出，与内核校验报错的样子相同。
# 内核（definitions/__init__.py）只把这两份文件解析一次算进定义的版本，不导入这里。

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from . import DEFINITIONS_DIR, DefinitionError, DuplicateKey, frozen, location, unique_keys


class _Entry(BaseModel):
    # 与内核的定义类型同一套设置：不认识的字段不合法、校验以后不可改写、严格按 JSON 的类型
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


Protocol = Literal["responses", "chat_completions", "messages"]


class ServicePreset(_Entry):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    auth: str = Field(min_length=1)
    # 获取模型列表与连接测试使用的认证方式（设计说明第 4.3 节）；默认协议：模型没有单独声明协议时预填（设计说明第 4.1 节）
    default_protocol: Protocol
    # 按协议的请求基址，请求路径由各协议适配器拼接
    base_urls: Mapping[Protocol, str]
    models_url: str
    docs_url: str
    header_profile: str
    source: str
    notes: str
    # 这个服务方案在 models.dev 中对应的 provider ID，模型能力表的提取脚本据此取材；
    # 「自定义」不使用预置表，在能力表中没有条目，不填这一项
    models_dev_id: str = ""

    freeze_base_urls = frozen("base_urls")


class ServicePresets(_Entry):
    # 服务方案预置表（设计说明第 4.1 节）：整张表的 revision 与来源随界面显示；每个服务方案一项
    revision: str = Field(min_length=1)
    source: str = Field(min_length=1)
    presets: tuple[ServicePreset, ...]


class ModelCapability(_Entry):
    # 模型能力表中的一条：取自 models.dev 的快照，只保留设计说明第 4.1 节的字段。
    # models.dev 中 modalities 可以缺少，缺少时不记录输入方式与输出方式（空元组）
    model: str = Field(min_length=1)
    # 调用协议：取自这个模型的 provider.npm，没有单独声明时取服务商接入包。
    # 接入包没有对应的协议时为空（None）：容量与输入方式照常记录。
    protocol: Protocol | None = None
    # 模型自己声明的接入包（provider.npm）；没有声明时不记录（空串）。
    npm: str = ""
    input_modalities: tuple[str, ...] = ()
    output_modalities: tuple[str, ...] = ()
    context_window: int | None = None
    max_output_tokens: int | None = None
    max_input_tokens: int | None = None
    tool_call: bool = False
    reasoning: bool = False


class CapabilityProvider(_Entry):
    # 服务商的接口地址与接入包；接口地址取自 models.dev，官方服务商由提取脚本的补充表补上。
    api: str = ""
    npm: str = Field(min_length=1)
    models: tuple[ModelCapability, ...]


class ModelCapabilities(_Entry):
    # 版本 2 增加全部服务商资料；presets 保留原服务方案的模型，旧文件按版本 1 读取。
    version: int = Field(default=1, ge=1, le=2)
    providers: Mapping[str, CapabilityProvider] = Field(default_factory=dict)
    presets: Mapping[str, tuple[ModelCapability, ...]]
    revision: str = Field(min_length=1)
    snapshot_date: str = Field(min_length=1)
    source: str = Field(min_length=1)
    # 来源文件（取回的 models.dev api.json，或用本地文件生成时的那份）的 SHA-256。
    source_sha256: str = ""

    freeze_presets = frozen("presets")
    freeze_providers = frozen("providers")


class Catalogs(BaseModel):
    # 两份应用侧的定义：服务方案预置表与模型能力表
    model_config = ConfigDict(frozen=True, extra="forbid")

    service_presets: ServicePresets
    model_capabilities: ModelCapabilities


_FILES: dict[str, tuple[str, TypeAdapter[Any]]] = {
    "service_presets.json": ("service_presets", TypeAdapter(ServicePresets)),
    "model_capabilities.json": ("model_capabilities", TypeAdapter(ModelCapabilities)),
}


def load_catalogs(directory: Path = DEFINITIONS_DIR) -> Catalogs:
    # 读取并校验 directory 中的这两份定义；不合法时抛出 DefinitionError，错误写明文件与项
    issues: list[tuple[str, str, str]] = []
    parts: dict[str, Any] = {}
    for file, (field, adapter) in _FILES.items():
        path = directory / file
        if not path.is_file():
            issues.append((file, "（整个文件）", "定义文件不存在"))
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            issues.append((file, f"第 {exc.start} 个字节", "不是 UTF-8 编码的文本"))
            continue
        except OSError as exc:
            issues.append((file, "（整个文件）", f"无法读取：{exc.strerror or exc}"))
            continue
        try:
            json.loads(text, object_pairs_hook=unique_keys)
        except json.JSONDecodeError as exc:
            issues.append((file, f"第 {exc.lineno} 行第 {exc.colno} 列", f"不是合法的 JSON：{exc.msg}"))
            continue
        except DuplicateKey as exc:
            issues.append((file, exc.key, "重复的键"))
            continue
        try:
            parts[field] = adapter.validate_json(text, strict=True)
        except ValidationError as exc:
            issues.extend((file, location(error["loc"]), error["msg"]) for error in exc.errors())
    if issues:
        raise DefinitionError(issues)
    issues = _references(parts["service_presets"], parts["model_capabilities"])
    if issues:
        raise DefinitionError(issues)
    return Catalogs(service_presets=parts["service_presets"], model_capabilities=parts["model_capabilities"])


def _references(presets: ServicePresets, capabilities: ModelCapabilities) -> list[tuple[str, str, str]]:
    # 类型以外的核对：服务方案的编号不重复，模型能力表与服务方案预置表互相对得上
    # （工单 #1452 从内核的 definitions/__init__.py 移来，核对的内容与报出的文件、项不变）
    issues: list[tuple[str, str, str]] = []
    identities = [preset.id for preset in presets.presets]
    for index, identity in enumerate(identities):
        if identities.index(identity) != index:
            issues.append(("service_presets.json", f"presets[{index}].id", f"重复的服务方案 {identity}"))
    preset_ids = {preset.id for preset in presets.presets}
    for preset_id in sorted(set(capabilities.presets) - preset_ids):
        issues.append(("model_capabilities.json", f"presets.{preset_id}", "能力表中有预置表没有的服务方案"))
    for index, preset_id in enumerate(capabilities.presets):
        if preset_id not in preset_ids:
            continue
        models = [capability.model for capability in capabilities.presets[preset_id]]
        for position, model in enumerate(models):
            if models.index(model) != position:
                issues.append(("model_capabilities.json", f"presets.{preset_id}[{position}].model",
                               f"同一个服务方案中模型 {model} 重复"))
    for index, preset in enumerate(presets.presets):
        if preset.models_dev_id and preset.id not in capabilities.presets:
            issues.append(("model_capabilities.json", f"presets.{preset.id}",
                           f"预置表第 {index + 1} 项（{preset.id}）记录了 models_dev_id，能力表却缺少这个服务方案"))
        if capabilities.version == 2 and preset.models_dev_id:
            provider = capabilities.providers.get(preset.models_dev_id)
            if provider is None:
                issues.append(("model_capabilities.json", f"providers.{preset.models_dev_id}", "能力表缺少预置方案对应的服务商"))
            elif capabilities.presets.get(preset.id) != provider.models:
                issues.append(("model_capabilities.json", f"presets.{preset.id}", "服务方案与对应服务商的模型资料不一致"))
    for provider_id, provider in capabilities.providers.items():
        models = [entry.model for entry in provider.models]
        for position, model in enumerate(models):
            if models.index(model) != position:
                issues.append(("model_capabilities.json", f"providers.{provider_id}.models[{position}].model",
                               f"同一个服务商中模型 {model} 重复"))
    return issues


# 随发布加载一次：服务方案预置表与模型能力表在程序启动时读取并校验
CATALOGS = load_catalogs()
