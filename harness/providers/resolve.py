from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .credentials import CredentialChain, CredentialMaterial
from .errors import CatalogValidationError, ValidationIssue
from .presets import preset_header_profile
from .store import SUPPORTED_PROTOCOLS, ModelDefinition, ProviderDefinition, ProviderStore


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


def call_target_public(
    model_id: Any,
    requested_tier: str | None = None,
    *,
    model: ModelDefinition | None = None,
    provider: ProviderDefinition | None = None,
    material: CredentialMaterial | None = None,
) -> dict[str, Any]:
    # 调用目标的公开部分：进入请求事件与界面，不含密钥；解析尚未确定的项为空值
    return {
        "provider_config_id": None if provider is None else provider.id,
        "model_id": model.id if model is not None else (model_id if isinstance(model_id, str) else None),
        "provider_name": None if provider is None else provider.name,
        "protocol": None if model is None else model.protocol,
        "base_url": None if provider is None else provider.base_url,
        "requested_provider": None if provider is None else provider.id,
        "requested_protocol": None if model is None else model.protocol,
        "requested_model": None if model is None else model.model,
        "credential_ref": None if provider is None else (provider.credential_ref or None),
        "credential_version": None if material is None else material.version,
        "context_window": None if model is None else model.context_window,
        "configured_max_output_tokens": None if model is None else model.max_output_tokens,
        "requested_tier": requested_tier,
        "sent_tier": None,
    }


@dataclass(frozen=True)
class CallTargetResolution:
    # 一次模型调用的调用目标解析结果：public 是进入事件与界面的公开部分，不含密钥；
    # 成功时 handle_id 指向 Provider 模块内部持有的目标，执行调用时才从凭据来源取出材料
    available: bool
    reason: str
    message: str
    public: Mapping[str, Any]
    handle_id: str | None = None


def resolve_call_target(
    store: ProviderStore,
    credentials: CredentialChain | None,
    model_id: Any,
    requested_tier: str | None = None,
) -> tuple[CallTargetResolution, FrozenTarget | None]:
    # 每次模型请求之前解析调用目标：只接收模型访问定义引用与请求档位，不接收部门。
    # 检查定义存在、所属连接存在、协议受支持、窗口已知、准入有效、凭据引用可解析；
    # fake 只用于确定性测试，不要求准入与凭据。请求档位本次原样记录，不限制到支持范围也不编码（#87）
    def unavailable(message: str, public: dict[str, Any]) -> tuple[CallTargetResolution, None]:
        return CallTargetResolution(False, "provider_unavailable", message, public), None

    if not isinstance(model_id, str) or not model_id.strip():
        return unavailable("没有可用的模型访问定义", call_target_public(model_id, requested_tier))
    model = store.models.get(model_id)
    if model is None:
        return unavailable("模型访问定义不存在", call_target_public(model_id, requested_tier))
    provider = store.providers.get(model.provider_id)
    public = call_target_public(model_id, requested_tier, model=model, provider=provider)
    if provider is None:
        return unavailable("Provider 配置不存在", public)
    if model.protocol not in SUPPORTED_PROTOCOLS:
        return unavailable("协议不受支持", public)
    if model.context_window is None:
        return unavailable("模型缺少 context_window，无法用于任务", public)
    material = None
    if model.protocol != "fake":
        if not model.admitted:
            return unavailable(f"模型 {model.id} 尚未通过模型测试准入，请先执行模型测试", public)
        if not provider.credential_ref:
            return unavailable("Provider 配置没有凭据引用", public)
        material = credentials.resolve(provider.credential_ref) if credentials is not None else None
        if material is None or not material.secret.strip():
            return unavailable(f"凭据引用 {provider.credential_ref} 无法解析，请在模型管理中配置凭据", public)
    target = FrozenTarget(
        target_key=model.id,
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
    resolved = call_target_public(model_id, requested_tier, model=model, provider=provider, material=material)
    return CallTargetResolution(True, "", "", resolved), target
