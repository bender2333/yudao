from __future__ import annotations

import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .errors import CatalogValidationError, ValidationIssue
from .presets import preset_exists


# 模型级协议，一个模型访问定义只声明一条，需要多协议建多条定义
SUPPORTED_PROTOCOLS = frozenset({"responses", "chat_completions", "messages", "fake"})
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")

# 推理档位全集，由低到高排列（ADR-0006）；模型访问定义声明其中的一个子集
REASONING_LEVELS = ("minimal", "low", "medium", "high", "xhigh", "max")
# 推理参数方式：一份声明只使用一种，只用于与它相符的协议（设计说明第 7.4 节）
REASONING_MODES = frozenset({"effort", "adaptive", "budget"})
# 推理参数方式与协议的相符关系
REASONING_MODE_PROTOCOLS: Mapping[str, frozenset[str]] = MappingProxyType({
    "effort": frozenset({"responses", "chat_completions"}),
    "adaptive": frozenset({"messages"}),
    "budget": frozenset({"messages"}),
})


# Provider 配置：一份服务连接，声明一种协议（ADR-0004）；地址保存该协议的请求基址
@dataclass(frozen=True)
class ProviderDefinition:
    id: str
    name: str
    protocol: str = ""
    base_url: str = ""
    credential_ref: str = ""
    timeout_sec: float = 600.0
    preset_id: str = ""
    models_url: str = ""

    def __post_init__(self) -> None:
        for name in ("id", "name", "base_url", "credential_ref", "preset_id", "models_url"):
            value = getattr(self, name)
            object.__setattr__(self, name, value.strip() if isinstance(value, str) else value)
        object.__setattr__(
            self, "protocol",
            self.protocol.strip().casefold() if isinstance(self.protocol, str) else self.protocol,
        )

    def public_dict(self) -> dict[str, Any]:
        # 非敏感字段，可落盘与导出
        return {
            "id": self.id,
            "name": self.name,
            "protocol": self.protocol,
            "base_url": self.base_url,
            "credential_ref": self.credential_ref,
            "timeout_sec": self.timeout_sec,
            "preset_id": self.preset_id,
            "models_url": self.models_url,
        }


# 模型访问定义：某份 Provider 配置下的一个模型访问定义，不声明协议（协议取自所属连接，ADR-0004）
# 容量是声明值：窗口可以未知（None），未知时只作候选，不可用于任务；输出上限必须有值。
# 准入记录不属于目录定义（工单 #86），保存在 ProviderFacade 的独立记录中
@dataclass(frozen=True)
class ModelDefinition:
    id: str
    provider_id: str
    model: str
    context_window: int | None
    max_output_tokens: int
    capability_source: str = ""
    # 是否接受要求调用工具：默认接受；声明不接受时，最后一次主机提示之后的请求不要求调用工具（#102）
    accepts_required_tool_call: bool = True
    # 推理档位声明（ADR-0006）：支持档位是全集的一个子集（按由低到高保存），默认档位属于支持档位，
    # 推理参数方式与所属连接的协议相符；三项一起声明，没有任何一项时不发送推理参数
    reasoning_levels: tuple[str, ...] = ()
    default_reasoning_level: str | None = None
    reasoning_mode: str = ""

    def __post_init__(self) -> None:
        for name in ("id", "provider_id", "model", "capability_source"):
            value = getattr(self, name)
            object.__setattr__(self, name, value.strip() if isinstance(value, str) else value)

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider_id": self.provider_id,
            "model": self.model,
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "capability_source": self.capability_source,
            "accepts_required_tool_call": self.accepts_required_tool_call,
            "reasoning_levels": list(self.reasoning_levels),
            "default_reasoning_level": self.default_reasoning_level,
            "reasoning_mode": self.reasoning_mode,
        }


# 准入记录：一次模型测试通过时写入的事实，与目录分开保存（工单 #86）。
# 后四个字段是测试时的受影响字段快照：地址、凭据引用、协议取自所属连接，上游模型 ID 取自定义；
# 有效性逐项比较，改连接字段则整条连接的定义全部回候选，改上游模型 ID 只影响该条定义
@dataclass(frozen=True)
class AdmissionRecord:
    model_id: str
    provider_id: str
    admitted_at: str
    admitted_model: str
    protocol: str
    base_url: str
    credential_ref: str
    model: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "provider_id": self.provider_id,
            "admitted_at": self.admitted_at,
            "admitted_model": self.admitted_model,
            "protocol": self.protocol,
            "base_url": self.base_url,
            "credential_ref": self.credential_ref,
            "model": self.model,
        }


def admission_is_current(record: AdmissionRecord, model: ModelDefinition,
                         provider: ProviderDefinition) -> bool:
    # 按受影响字段逐项比较：名称、超时、models_url 与容量不在比较之列，
    # 换同一引用下的 Key 不改动引用字段，因此都不影响准入有效性
    return (record.base_url == provider.base_url
            and record.credential_ref == provider.credential_ref
            and record.protocol == provider.protocol
            and record.model == model.model)


def _parse_admission_document(raw: Any) -> dict[str, AdmissionRecord]:
    # 独立准入文件的解析：只认文件自身结构，坏内容报错，不做兼容降级
    if not isinstance(raw, Mapping):
        raise CatalogValidationError((ValidationIssue("admissions", "应为 JSON 对象"),))
    unknown = sorted(set(raw) - {"admissions"}, key=str)
    if unknown:
        raise CatalogValidationError(tuple(
            ValidationIssue(f"admissions.{key}", "未知字段") for key in unknown
        ))
    items = raw.get("admissions", [])
    if not isinstance(items, list):
        raise CatalogValidationError((ValidationIssue("admissions", "应为数组"),))
    required = {"model_id", "provider_id", "admitted_at", "admitted_model",
                "protocol", "base_url", "credential_ref", "model"}
    records: dict[str, AdmissionRecord] = {}
    issues: list[ValidationIssue] = []
    for index, item in enumerate(items):
        location = f"admissions[{index}]"
        if not isinstance(item, Mapping):
            issues.append(ValidationIssue(location, "应为对象"))
            continue
        missing = sorted(required - set(item), key=str)
        if missing:
            issues.append(ValidationIssue(location, "缺少字段：" + ", ".join(missing)))
            continue
        extra = sorted(set(item) - required, key=str)
        if extra:
            issues.append(ValidationIssue(location, "未知字段：" + ", ".join(extra)))
            continue
        values = {key: item[key] for key in required}
        if any(not isinstance(value, str) for value in values.values()):
            issues.append(ValidationIssue(location, "字段必须是字符串"))
            continue
        if values["model_id"] in records:
            issues.append(ValidationIssue(f"{location}.model_id", "模型访问定义 ID 重复"))
            continue
        records[values["model_id"]] = AdmissionRecord(**values)
    if issues:
        raise CatalogValidationError(issues)
    return records


class ProviderStore:
    # 非敏感目录：校验成功后整体发布，revision 单调递增
    def __init__(
        self,
        providers: Iterable[ProviderDefinition] = (),
        models: Iterable[ModelDefinition] = (),
        *,
        revision: int = 0,
        updated_at: str | None = None,
    ) -> None:
        self._provider_items = tuple(providers)
        self._model_items = tuple(models)
        self.providers: Mapping[str, ProviderDefinition] = MappingProxyType(_index_definitions(self._provider_items))
        self.models: Mapping[str, ModelDefinition] = MappingProxyType(_index_definitions(self._model_items))
        self.revision = int(revision)
        self.updated_at = updated_at or _utc_now()
        self._validate_definition_shape()

    @classmethod
    def empty(cls) -> ProviderStore:
        return cls((), ())

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> ProviderStore:
        providers, models = _parse_catalog(raw)
        revision = raw.get("revision", 1) if isinstance(raw, Mapping) else 1
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            revision = 1
        return cls(providers, models, revision=revision, updated_at=_utc_now())

    @classmethod
    def load(cls, path: str | Path) -> ProviderStore:
        source = Path(path)
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CatalogValidationError((ValidationIssue("catalog", "无法读取 Provider 目录"),)) from exc
        store = cls.from_dict(raw)
        return store

    def to_dict(self) -> dict[str, Any]:
        # 只含非敏感部分；准入记录由 ProviderFacade 单独保存，不随目录落盘
        return {
            "revision": self.revision,
            "providers": [self.providers[key].public_dict() for key in sorted(self.providers)],
            "models": [self.models[key].public_dict() for key in sorted(self.models)],
        }

    def public_view(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "updated_at": self.updated_at,
            "providers": [self.providers[key].public_dict() for key in sorted(self.providers)],
            "models": [self.models[key].public_dict() for key in sorted(self.models)],
        }

    def validate(self) -> None:
        # 只校验结构与引用，不解析凭据；结构合法但未就绪也可保存
        self._validate_definition_shape()

    def save_catalog(self, raw: Mapping[str, Any]) -> int:
        # 先校验后整体发布，revision 单调递增
        providers, models = _parse_catalog(raw)
        candidate = ProviderStore.__new__(ProviderStore)
        candidate._provider_items = tuple(providers)
        candidate._model_items = tuple(models)
        candidate.providers = MappingProxyType(_index_definitions(candidate._provider_items))
        candidate.models = MappingProxyType(_index_definitions(candidate._model_items))
        candidate._validate_definition_shape()
        self._provider_items = candidate._provider_items
        self._model_items = candidate._model_items
        self.providers = candidate.providers
        self.models = candidate.models
        self.revision += 1
        self.updated_at = _utc_now()
        return self.revision

    def save_provider(self, raw: Mapping[str, Any]) -> int:
        parsed, issues = _parse_provider(raw, "providers")
        if issues:
            raise CatalogValidationError(issues)
        assert parsed is not None
        items = [item for item in self._provider_items if item.id != parsed.id] + [parsed]
        candidate_items = tuple(items)
        mapping: dict[str, ProviderDefinition] = _index_definitions(candidate_items)
        old_providers, old_items = self.providers, self._provider_items
        self.providers, self._provider_items = MappingProxyType(mapping), candidate_items
        try:
            self._validate_definition_shape()
        except Exception:
            self.providers, self._provider_items = old_providers, old_items
            raise
        self.revision += 1
        self.updated_at = _utc_now()
        return self.revision

    def save_model(self, raw: Mapping[str, Any]) -> int:
        parsed, issues = _parse_model(raw, "models")
        if issues:
            raise CatalogValidationError(issues)
        assert parsed is not None
        items = [item for item in self._model_items if item.id != parsed.id] + [parsed]
        candidate_items = tuple(items)
        mapping: dict[str, ModelDefinition] = _index_definitions(candidate_items)
        old_models, old_items = self.models, self._model_items
        self.models, self._model_items = MappingProxyType(mapping), candidate_items
        try:
            self._validate_definition_shape()
        except Exception:
            self.models, self._model_items = old_models, old_items
            raise
        self.revision += 1
        self.updated_at = _utc_now()
        return self.revision

    def bump_revision(self) -> int:
        # 不改变定义只推进目录修订号：部门默认等目录内容修改时使用
        self.revision += 1
        self.updated_at = _utc_now()
        return self.revision



    def persist(self, path: str | Path) -> Path:
        # 校验成功后写临时文件再原子替换，落盘成功才返回
        self._validate_definition_shape()
        target = Path(path)
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        parent = target.parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(parent) if str(parent) not in ("", ".") else None,
                                         prefix=target.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return target

    def _validate_definition_shape(self) -> None:
        issues: list[ValidationIssue] = []
        provider_ids: set[str] = set()
        provider_by_id: dict[str, ProviderDefinition] = {}
        for index, provider in enumerate(self._provider_items):
            location = f"providers[{index}]"
            if not isinstance(provider, ProviderDefinition):
                issues.append(ValidationIssue(location, "应为 Provider 配置"))
                continue
            if not _valid_identifier(provider.id):
                issues.append(ValidationIssue(f"{location}.id", "必须是非空简单标识符"))
            if _hashable(provider.id) and provider.id in provider_ids:
                issues.append(ValidationIssue(f"{location}.id", "Provider 配置 ID 重复"))
            if _hashable(provider.id):
                provider_ids.add(provider.id)
                provider_by_id.setdefault(provider.id, provider)
            if not isinstance(provider.name, str) or not provider.name:
                issues.append(ValidationIssue(f"{location}.name", "必须是非空字符串"))
            if not isinstance(provider.protocol, str) or provider.protocol not in SUPPORTED_PROTOCOLS:
                issues.append(ValidationIssue(f"{location}.protocol", "协议不受支持"))
            if not isinstance(provider.timeout_sec, (int, float)) or isinstance(provider.timeout_sec, bool) \
                    or not math.isfinite(float(provider.timeout_sec)) or provider.timeout_sec <= 0:
                issues.append(ValidationIssue(f"{location}.timeout_sec", "必须是正的有限数值"))
            if provider.base_url and not _valid_url(provider.base_url):
                issues.append(ValidationIssue(f"{location}.base_url", "必须是 HTTP(S) URL 且不能携带凭据"))
            if provider.credential_ref and not _valid_identifier(provider.credential_ref):
                issues.append(ValidationIssue(f"{location}.credential_ref", "必须是凭据引用"))
            if provider.preset_id and not preset_exists(provider.preset_id):
                issues.append(ValidationIssue(f"{location}.preset_id", "服务方案不存在"))
            if provider.models_url and not _valid_url(provider.models_url):
                issues.append(ValidationIssue(f"{location}.models_url", "必须是 HTTP(S) URL 且不能携带凭据"))
        model_ids: set[str] = set()
        for index, model in enumerate(self._model_items):
            location = f"models[{index}]"
            if not isinstance(model, ModelDefinition):
                issues.append(ValidationIssue(location, "应为模型访问定义"))
                continue
            if not _valid_identifier(model.id):
                issues.append(ValidationIssue(f"{location}.id", "必须是非空简单标识符"))
            if _hashable(model.id) and model.id in model_ids:
                issues.append(ValidationIssue(f"{location}.id", "模型访问定义 ID 重复"))
            if _hashable(model.id):
                model_ids.add(model.id)
            if not _valid_identifier(model.provider_id):
                issues.append(ValidationIssue(f"{location}.provider_id", "必须是 Provider 配置标识"))
            elif _hashable(model.provider_id) and model.provider_id not in provider_ids:
                issues.append(ValidationIssue(f"{location}.provider_id", "Provider 配置不存在"))
            if not isinstance(model.model, str) or not model.model.strip():
                issues.append(ValidationIssue(f"{location}.model", "必须是非空字符串"))
            _validate_positive_int(model.context_window, f"{location}.context_window", issues, allow_none=True)
            _validate_positive_int(model.max_output_tokens, f"{location}.max_output_tokens", issues, allow_none=False)
            if model.context_window is not None and model.max_output_tokens is not None \
                    and isinstance(model.context_window, int) and isinstance(model.max_output_tokens, int) \
                    and model.max_output_tokens > model.context_window:
                issues.append(ValidationIssue(f"{location}.max_output_tokens", "不能超过 context_window"))
            if not isinstance(model.capability_source, str):
                issues.append(ValidationIssue(f"{location}.capability_source", "必须为字符串"))
            if not isinstance(model.accepts_required_tool_call, bool):
                issues.append(ValidationIssue(f"{location}.accepts_required_tool_call", "必须为 true 或 false"))
            _validate_reasoning_declaration(model, location, provider_by_id, issues)
        if issues:
            raise CatalogValidationError(issues)

def _validate_reasoning_declaration(model: ModelDefinition, location: str,
                                    provider_by_id: Mapping[str, ProviderDefinition],
                                    issues: list[ValidationIssue]) -> None:
    # 推理档位声明（ADR-0006）：三项一起声明，部分声明直接拒绝；默认档位属于支持档位；
    # 推理参数方式取值受限并与所属连接的协议相符（设计说明第 7.1、7.4 节）
    declared = (bool(model.reasoning_levels), model.default_reasoning_level is not None,
                bool(model.reasoning_mode))
    if any(declared) and not all(declared):
        if not model.reasoning_levels:
            issues.append(ValidationIssue(f"{location}.reasoning_levels", "声明推理档位时必须同时给出支持档位"))
        if model.default_reasoning_level is None:
            issues.append(ValidationIssue(f"{location}.default_reasoning_level", "声明推理档位时必须同时给出默认档位"))
        if not model.reasoning_mode:
            issues.append(ValidationIssue(f"{location}.reasoning_mode", "声明推理档位时必须同时给出推理参数方式"))
        return
    if not declared[0]:
        return
    known = set(model.reasoning_levels)
    unknown = sorted(known - set(REASONING_LEVELS), key=str)
    if unknown:
        issues.append(ValidationIssue(
            f"{location}.reasoning_levels", "包含不支持的档位：" + "、".join(unknown)))
    if len(model.reasoning_levels) != len(known):
        issues.append(ValidationIssue(f"{location}.reasoning_levels", "支持档位不能重复"))
    if model.default_reasoning_level not in known:
        issues.append(ValidationIssue(
            f"{location}.default_reasoning_level", "默认档位必须属于支持档位"))
    if model.reasoning_mode not in REASONING_MODES:
        issues.append(ValidationIssue(f"{location}.reasoning_mode", "推理参数方式不受支持"))
        return
    provider = provider_by_id.get(model.provider_id)
    if provider is not None and provider.protocol and provider.protocol not in REASONING_MODE_PROTOCOLS[model.reasoning_mode]:
        issues.append(ValidationIssue(
            f"{location}.reasoning_mode",
            f"推理参数方式 {model.reasoning_mode} 与连接协议 {provider.protocol} 不相符"))


def _parse_catalog(raw: Mapping[str, Any]) -> tuple[list[ProviderDefinition], list[ModelDefinition]]:
    if not isinstance(raw, Mapping):
        raise CatalogValidationError((ValidationIssue("catalog", "应为 JSON 对象"),))
    allowed = {"providers", "models", "revision"}
    unknown = sorted(set(raw) - allowed, key=str)
    issues: list[ValidationIssue] = [ValidationIssue(f"catalog.{key}", "未知字段") for key in unknown]
    # 一份连接声明一种协议；模型访问定义声明协议时直接报可定位问题（ADR-0004）
    providers: list[ProviderDefinition] = []
    models: list[ModelDefinition] = []
    provider_items = raw.get("providers", [])
    model_items = raw.get("models", [])
    if not isinstance(provider_items, list):
        issues.append(ValidationIssue("providers", "应为数组"))
    else:
        for index, item in enumerate(provider_items):
            parsed, item_issues = _parse_provider(item, f"providers[{index}]")
            issues.extend(item_issues)
            if parsed is not None:
                providers.append(parsed)
    if not isinstance(model_items, list):
        issues.append(ValidationIssue("models", "应为数组"))
    else:
        for index, item in enumerate(model_items):
            parsed, item_issues = _parse_model(item, f"models[{index}]")
            issues.extend(item_issues)
            if parsed is not None:
                models.append(parsed)
    if issues:
        raise CatalogValidationError(issues)
    return providers, models


def _parse_provider(raw: Any, location: str) -> tuple[ProviderDefinition | None, list[ValidationIssue]]:
    if not isinstance(raw, Mapping):
        return None, [ValidationIssue(location, "应为对象")]
    allowed = {"id", "name", "protocol", "base_url", "credential_ref", "timeout_sec", "preset_id", "models_url"}
    issues = [ValidationIssue(f"{location}.{key}", "未知字段") for key in sorted(set(raw) - allowed, key=str)]
    required = {"id", "name", "protocol"}
    missing = required - set(raw)
    issues.extend(ValidationIssue(f"{location}.{key}", "缺少必填项") for key in sorted(missing))
    if issues:
        return None, issues
    return ProviderDefinition(
        id=raw["id"], name=raw["name"], protocol=raw["protocol"],
        base_url=raw.get("base_url", ""), credential_ref=raw.get("credential_ref", ""),
        timeout_sec=raw.get("timeout_sec", 600.0),
        preset_id=raw.get("preset_id", ""), models_url=raw.get("models_url", ""),
    ), issues


def _parse_model(raw: Any, location: str) -> tuple[ModelDefinition | None, list[ValidationIssue]]:
    if not isinstance(raw, Mapping):
        return None, [ValidationIssue(location, "应为对象")]
    # protocol 仍是已知字段，但模型访问定义不再声明协议（ADR-0004）：看到它时指出字段位置，
    # 其余未知字段（含准入字段）按未知字段处理（工单 #86）
    allowed = {
        "id", "provider_id", "model", "context_window", "max_output_tokens",
        "capability_source", "accepts_required_tool_call", "protocol",
        "reasoning_levels", "default_reasoning_level", "reasoning_mode",
    }
    issues = [ValidationIssue(f"{location}.{key}", "未知字段")
              for key in sorted(set(raw) - allowed, key=str)]
    if "protocol" in raw:
        issues.append(ValidationIssue(
            f"{location}.protocol", "模型访问定义不再声明协议，请在 Provider 配置上声明"))
    required = {"id", "provider_id", "model", "max_output_tokens"}
    missing = required - set(raw)
    issues.extend(ValidationIssue(f"{location}.{key}", "缺少必填项") for key in sorted(missing))
    if issues:
        return None, issues
    levels = raw.get("reasoning_levels", ())
    if isinstance(levels, list) and all(isinstance(item, str) for item in levels):
        # 支持档位去重后按全集由低到高保存；取值本身由形状校验核对
        seen = set(levels)
        levels = tuple(level for level in REASONING_LEVELS if level in seen)
    default_level = raw.get("default_reasoning_level")
    if isinstance(default_level, str):
        default_level = default_level.strip() or None
    elif default_level is not None:
        default_level = None
        issues.append(ValidationIssue(f"{location}.default_reasoning_level", "必须为档位名或 null"))
    mode = raw.get("reasoning_mode", "")
    if isinstance(mode, str):
        mode = mode.strip()
    return ModelDefinition(
        id=raw["id"], provider_id=raw["provider_id"], model=raw["model"],
        context_window=raw.get("context_window"),
        max_output_tokens=raw["max_output_tokens"], capability_source=raw.get("capability_source", ""),
        accepts_required_tool_call=raw.get("accepts_required_tool_call", True),
        reasoning_levels=levels if isinstance(levels, tuple) else (),
        default_reasoning_level=default_level,
        reasoning_mode=mode if isinstance(mode, str) else "",
    ), issues


def _index_definitions(items: Iterable[Any]) -> dict[Any, Any]:
    indexed: dict[Any, Any] = {}
    for item in items:
        identifier = getattr(item, "id", None)
        if _hashable(identifier):
            indexed[identifier] = item
    return indexed


def _hashable(value: Any) -> bool:
    try:
        hash(value)
    except TypeError:
        return False
    return True


def _valid_identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(_IDENTIFIER_RE.fullmatch(value))


def _valid_url(value: Any) -> bool:
    # 地址只做形状校验，不携带凭据，不做网络探测
    if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
        return False
    from urllib.parse import urlsplit
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def _validate_positive_int(value: Any, location: str, issues: list[ValidationIssue], *, allow_none: bool) -> None:
    if value is None and allow_none:
        return
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        issues.append(ValidationIssue(location, "必须是正整数"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
