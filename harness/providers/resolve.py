from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .credentials import CredentialChain
from .errors import CatalogValidationError, ValidationIssue
from .presets import preset_header_profile
from .store import SUPPORTED_PROTOCOLS, ProviderStore


# 冻结目标：任务创建时取得的不可变调用目标，只持有认证句柄
@dataclass(frozen=True)
class FrozenTarget:
    target_key: str
    provider_id: str
    provider_name: str
    model_id: str
    protocol: str
    base_url: str
    model: str
    context_window: int
    max_output_tokens: int
    timeout_sec: float
    credential_ref: str | None = None
    capability_source: str = ""
    header_profile: str = ""
    preset_id: str = ""
    revision: int = 0
    credential_version: str | None = field(default=None, repr=False, compare=False)
    api_key: str = field(default="", repr=False, compare=False)

    def public_dict(self) -> dict[str, Any]:
        # 公开身份不含 api_key 与 credential_version
        return {
            "target_key": self.target_key,
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "model_id": self.model_id,
            "protocol": self.protocol,
            "base_url": self.base_url,
            "model": self.model,
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "timeout_sec": self.timeout_sec,
            "credential_ref": self.credential_ref,
            "capability_source": self.capability_source,
            "header_profile": self.header_profile,
            "preset_id": self.preset_id,
            "revision": self.revision,
        }


@dataclass(frozen=True)
class ResolveSnapshot:
    # 同一 revision 下一致的目标集合，不可变
    targets: Mapping[str, FrozenTarget]
    revision: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "targets", MappingProxyType(dict(self.targets)))

    def target(self, key: str) -> FrozenTarget:
        try:
            return self.targets[key]
        except KeyError as exc:
            raise KeyError(f"unknown target: {key}") from exc

    def public_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "targets": {key: self.targets[key].public_dict() for key in sorted(self.targets)},
        }


def resolve_snapshot(
    store: ProviderStore,
    selections: Sequence[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]],
    credentials: CredentialChain | Mapping[str, Any] | None = None,
) -> ResolveSnapshot:
    # 接受任意选择列表，不硬编码部门；一次读取一致配置与凭据
    chain = _coerce_chain(credentials)
    normalized = _normalize_selections(selections)
    issues: list[ValidationIssue] = []
    targets: dict[str, FrozenTarget] = {}
    seen: set[str] = set()
    for key, provider_id, model_id in normalized:
        location = f"selections.{key}"
        if key in seen:
            issues.append(ValidationIssue(location, "选择键重复"))
            continue
        seen.add(key)
        provider = store.providers.get(provider_id) if isinstance(provider_id, str) else None
        model = store.models.get(model_id) if isinstance(model_id, str) else None
        if provider is None:
            issues.append(ValidationIssue(f"{location}.provider_id", "Provider 配置不存在"))
            continue
        if model is None:
            issues.append(ValidationIssue(f"{location}.model_id", "模型访问定义不存在"))
            continue
        if model.provider_id != provider.id:
            issues.append(ValidationIssue(location, "模型访问定义不属于该 Provider 配置"))
            continue
        if model.protocol not in SUPPORTED_PROTOCOLS:
            issues.append(ValidationIssue(f"{location}.protocol", "协议不受支持"))
            continue
        if model.context_window is None:
            issues.append(ValidationIssue(f"{location}.model_id", "模型缺少 context_window，无法用于任务"))
            continue
        material = None
        if model.protocol != "fake":
            if not provider.credential_ref:
                issues.append(ValidationIssue(f"{location}.credential", "凭据引用无法解析"))
                continue
            material = chain.resolve(provider.credential_ref) if chain is not None else None
            if material is None or not material.secret.strip():
                issues.append(ValidationIssue(f"{location}.credential", "凭据引用无法解析"))
                continue
        targets[key] = FrozenTarget(
            target_key=key,
            provider_id=provider.id,
            provider_name=provider.name,
            model_id=model.id,
            protocol=model.protocol,
            base_url=provider.base_url,
            model=model.model,
            context_window=model.context_window,
            max_output_tokens=model.max_output_tokens,
            timeout_sec=provider.timeout_sec,
            credential_ref=provider.credential_ref or None,
            capability_source=model.capability_source,
            header_profile=preset_header_profile(provider.preset_id),
            preset_id=provider.preset_id,
            revision=store.revision,
            credential_version=(material.version if material is not None else None),
            api_key=(material.secret if material is not None else ""),
        )
    if issues:
        raise CatalogValidationError(issues)
    return ResolveSnapshot(targets=targets, revision=store.revision)


def _normalize_selections(
    selections: Sequence[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]],
) -> list[tuple[str, Any, Any]]:
    # 同时接受列表与映射，键为任意选择名
    normalized: list[tuple[str, Any, Any]] = []
    if isinstance(selections, Mapping):
        for key, item in selections.items():
            if not isinstance(item, Mapping):
                normalized.append((str(key), None, None))
                continue
            provider_id = item.get("provider_id", item.get("providerId"))
            model_id = item.get("model_id", item.get("modelId"))
            explicit_key = item.get("key", item.get("target_key", key))
            normalized.append((str(explicit_key), provider_id, model_id))
        return normalized
    for index, item in enumerate(selections):
        if not isinstance(item, Mapping):
            normalized.append((f"selections[{index}]", None, None))
            continue
        key = item.get("key", item.get("target_key", item.get("department", f"selections[{index}]")))
        provider_id = item.get("provider_id", item.get("providerId"))
        model_id = item.get("model_id", item.get("modelId"))
        normalized.append((str(key), provider_id, model_id))
    return normalized


def _coerce_chain(credentials: CredentialChain | Mapping[str, Any] | None) -> CredentialChain | None:
    if credentials is None:
        return CredentialChain()
    if isinstance(credentials, CredentialChain):
        return credentials
    if isinstance(credentials, Mapping):
        return CredentialChain(overrides=credentials)
    return CredentialChain()
