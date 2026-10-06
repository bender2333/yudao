from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .credentials import CredentialChain, CredentialMaterial
from .errors import CatalogValidationError, ValidationIssue
from .presets import preset_header_profile
from .store import (
    REASONING_LEVELS,
    SUPPORTED_PROTOCOLS,
    AdmissionRecord,
    ModelDefinition,
    ProviderDefinition,
    ProviderStore,
    admission_is_current,
)

def limit_reasoning_level(model: ModelDefinition, requested_tier: str | None) -> str | None:
    # 按模型声明限制请求档位（设计说明第 7.3 节）：请求档位为空时用默认档位；
    # 否则取不高于请求档位的最高支持档位，没有这样的档位时取最低支持档位；
    # 模型没有声明支持档位时不发送推理参数
    if not model.reasoning_levels:
        return None
    if requested_tier is None or not requested_tier.strip():
        return model.default_reasoning_level
    requested = requested_tier.strip()
    if requested not in REASONING_LEVELS:
        # 未知档位名按「没有不高于它的支持档位」处理，落到最低支持档位
        supported = [level for level in model.reasoning_levels if level in REASONING_LEVELS]
        return supported[0] if supported else model.reasoning_levels[0]
    not_above = [level for level in model.reasoning_levels if REASONING_LEVELS.index(level) <= REASONING_LEVELS.index(requested)]
    if not_above:
        return not_above[-1]
    return model.reasoning_levels[0]


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
    # 模型访问定义声明的是否接受要求调用工具（#102）
    accepts_required_tool_call: bool = True
    # 模型访问定义声明的输入方式（设计说明第 4.3 节）：步骤驱动按它决定这次请求提供的工具（第 5.6 节）
    input_modalities: tuple[str, ...] = ("text",)
    # 推理档位声明（ADR-0006）与本次请求实际发送的档位；未声明档位时不发送推理参数
    reasoning_levels: tuple[str, ...] = ()
    default_reasoning_level: str | None = None
    reasoning_mode: str = ""
    sent_tier: str | None = None
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
            "accepts_required_tool_call": self.accepts_required_tool_call,
            "input_modalities": list(self.input_modalities),
            "reasoning_levels": list(self.reasoning_levels),
            "default_reasoning_level": self.default_reasoning_level,
            "reasoning_mode": self.reasoning_mode,
            "sent_tier": self.sent_tier,
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
    for key, provider_id, model_id, requested_tier in normalized:
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
        if provider.protocol not in SUPPORTED_PROTOCOLS:
            issues.append(ValidationIssue(f"{location}.protocol", "协议不受支持"))
            continue
        if model.context_window is None:
            issues.append(ValidationIssue(f"{location}.model_id", "模型缺少 context_window，无法用于任务"))
            continue
        material = None
        if provider.protocol != "fake":
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
            protocol=provider.protocol,
            base_url=provider.base_url,
            model=model.model,
            context_window=model.context_window,
            max_output_tokens=model.max_output_tokens,
            timeout_sec=provider.timeout_sec,
            credential_ref=provider.credential_ref or None,
            capability_source=model.capability_source,
            accepts_required_tool_call=model.accepts_required_tool_call,
            input_modalities=model.input_modalities,
            reasoning_levels=model.reasoning_levels,
            default_reasoning_level=model.default_reasoning_level,
            reasoning_mode=model.reasoning_mode,
            sent_tier=limit_reasoning_level(model, requested_tier),
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
) -> list[tuple[str, Any, Any, Any]]:
    # 同时接受列表与映射，键为任意选择名；选择可以带请求档位（#87）
    normalized: list[tuple[str, Any, Any, Any]] = []
    if isinstance(selections, Mapping):
        for key, item in selections.items():
            if not isinstance(item, Mapping):
                normalized.append((str(key), None, None, None))
                continue
            provider_id = item.get("provider_id", item.get("providerId"))
            model_id = item.get("model_id", item.get("modelId"))
            requested_tier = item.get("requested_tier", item.get("requestedTier"))
            explicit_key = item.get("key", item.get("target_key", key))
            normalized.append((str(explicit_key), provider_id, model_id, requested_tier))
        return normalized
    for index, item in enumerate(selections):
        if not isinstance(item, Mapping):
            normalized.append((f"selections[{index}]", None, None, None))
            continue
        key = item.get("key", item.get("target_key", item.get("department", f"selections[{index}]")))
        provider_id = item.get("provider_id", item.get("providerId"))
        model_id = item.get("model_id", item.get("modelId"))
        requested_tier = item.get("requested_tier", item.get("requestedTier"))
        normalized.append((str(key), provider_id, model_id, requested_tier))
    return normalized


def _coerce_chain(credentials: CredentialChain | Mapping[str, Any] | None) -> CredentialChain | None:
    if credentials is None:
        return CredentialChain()
    if isinstance(credentials, CredentialChain):
        return credentials
    if isinstance(credentials, Mapping):
        return CredentialChain(overrides=credentials)
    return CredentialChain()


# 调用目标的公开字段名：进入请求事件与界面的公开部分由它们组成，不含密钥；
# 观察与分析从事件载荷按下标取出这些字段（工单 #92）
CALL_TARGET_FIELDS = (
    "provider_config_id", "model_id", "provider_name", "protocol", "base_url",
    "requested_provider", "requested_protocol", "requested_model", "credential_ref", "credential_version",
    "context_window", "configured_max_output_tokens", "accepts_required_tool_call", "input_modalities",
    "reasoning_levels", "default_reasoning_level", "reasoning_mode", "requested_tier", "sent_tier",
)

def call_target_public(
    model_id: Any,
    requested_tier: str | None = None,
    *,
    model: ModelDefinition | None = None,
    provider: ProviderDefinition | None = None,
    material: CredentialMaterial | None = None,
    sent_tier: str | None = None,
) -> dict[str, Any]:
    # 调用目标的公开部分：进入请求事件与界面，不含密钥；解析尚未确定的项为空值
    return {
        "provider_config_id": None if provider is None else provider.id,
        "model_id": model.id if model is not None else (model_id if isinstance(model_id, str) else None),
        "provider_name": None if provider is None else provider.name,
        "protocol": None if provider is None else provider.protocol,
        "base_url": None if provider is None else provider.base_url,
        "requested_provider": None if provider is None else provider.id,
        "requested_protocol": None if provider is None else provider.protocol,
        "requested_model": None if model is None else model.model,
        "credential_ref": None if provider is None else (provider.credential_ref or None),
        "credential_version": None if material is None else material.version,
        "context_window": None if model is None else model.context_window,
        "configured_max_output_tokens": None if model is None else model.max_output_tokens,
        "accepts_required_tool_call": None if model is None else model.accepts_required_tool_call,
        "input_modalities": [] if model is None else list(model.input_modalities),
        "reasoning_levels": [] if model is None else list(model.reasoning_levels),
        "default_reasoning_level": None if model is None else model.default_reasoning_level,
        "reasoning_mode": None if model is None else (model.reasoning_mode or None),
        "requested_tier": requested_tier,
        "sent_tier": sent_tier,
    }


# 调用目标里合同要求必须是文本的字段（CallTarget 把它们声明为非空字符串）：待恢复决定请求与
# 自动重新执行（工单 #307）都按它判断解析结果是否已经确定
CALL_TARGET_REQUIRED_STRINGS = (
    "provider_name", "protocol", "requested_provider", "requested_protocol", "requested_model",
)


def event_call_target(public: Mapping[str, Any], *, selection_source: str | None) -> dict[str, Any]:
    # 写入请求、尝试与压缩事件的调用目标：解析的公开部分加选择来源，不含密钥
    return {**public, "selection_source": selection_source}


def decision_call_target(public: Mapping[str, Any]) -> dict[str, Any] | None:
    # 待恢复决定请求里的调用目标：身份还没有解析出来时不填，原因与说明写在请求文本里
    payload = event_call_target(public, selection_source=None)
    if any(not isinstance(payload.get(key), str) for key in CALL_TARGET_REQUIRED_STRINGS):
        return None
    return payload


@dataclass(frozen=True)
class CallTargetResolution:
    # 一次模型调用的调用目标解析结果：public 是进入事件与界面的公开部分，不含密钥；
    # 成功时 handle_id 指向 Provider 模块内部持有的目标，执行调用时才从凭据来源取出材料。
    # selection_source 是提供模型访问定义的那一层（部门默认或项目部门设置，设计说明第 5.3 节）
    available: bool
    reason: str
    message: str
    public: Mapping[str, Any]
    handle_id: str | None = None
    selection_source: str | None = None

@dataclass(frozen=True)
class EffectiveModelResolution:
    # 本部门当前生效的模型及来源（设计说明第 9.3 节）：按第 5.3 节的选择规则与当前目录计算，
    # 不发送请求、不保留调用句柄。state 取 effective、unusable、unset 三者之一；
    # unusable 与 unset 时不返回其他连接或模型。resolution 是解析结果，unset 时为空。
    state: str
    resolution: CallTargetResolution | None


def resolve_call_target(
    store: ProviderStore,
    credentials: CredentialChain | None,
    model_id: Any,
    requested_tier: str | None = None,
    admissions: Mapping[str, AdmissionRecord] | None = None,
) -> tuple[CallTargetResolution, FrozenTarget | None]:
    # 每次模型请求之前解析调用目标：只接收模型访问定义引用与请求档位，不接收部门。
    # 检查定义存在、所属连接存在、协议受支持、窗口已知、准入有效、凭据引用可解析；
    # fake 只用于确定性测试，不要求准入与凭据。准入有效性按受影响字段逐项比较（工单 #86）。
    # 请求档位原样记录，实际发送的档位按模型声明限制到支持范围（设计说明第 7.3 节），
    # 编码在协议适配器完成
    def unavailable(message: str, public: dict[str, Any]) -> tuple[CallTargetResolution, None]:
        return CallTargetResolution(False, "provider_unavailable", message, public), None

    if not isinstance(model_id, str) or not model_id.strip():
        return unavailable("没有可用的模型访问定义", call_target_public(model_id, requested_tier))
    model = store.models.get(model_id)
    if model is None:
        return unavailable("模型访问定义不存在", call_target_public(model_id, requested_tier))
    provider = store.providers.get(model.provider_id)
    public = call_target_public(model_id, requested_tier, model=model, provider=provider,
                                sent_tier=limit_reasoning_level(model, requested_tier))
    if provider is None:
        return unavailable("Provider 配置不存在", public)
    if provider.protocol not in SUPPORTED_PROTOCOLS:
        return unavailable("协议不受支持", public)
    if model.context_window is None:
        return unavailable("模型缺少 context_window，无法用于任务", public)
    material = None
    if provider.protocol != "fake":
        record = None if admissions is None else admissions.get(model.id)
        if record is None:
            return unavailable(f"模型 {model.id} 尚未通过模型测试准入，请先执行模型测试", public)
        if not admission_is_current(record, model, provider):
            return unavailable(f"模型 {model.id} 的准入已作废，请重新执行模型测试", public)
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
        protocol=provider.protocol,
        base_url=provider.base_url,
        model=model.model,
        context_window=model.context_window,
        max_output_tokens=model.max_output_tokens,
        timeout_sec=provider.timeout_sec,
        credential_ref=provider.credential_ref or None,
        capability_source=model.capability_source,
        accepts_required_tool_call=model.accepts_required_tool_call,
        input_modalities=model.input_modalities,
        reasoning_levels=model.reasoning_levels,
        default_reasoning_level=model.default_reasoning_level,
        reasoning_mode=model.reasoning_mode,
        sent_tier=limit_reasoning_level(model, requested_tier),
        header_profile=preset_header_profile(provider.preset_id),
        preset_id=provider.preset_id,
        revision=store.revision,
        credential_version=(material.version if material is not None else None),
        api_key=(material.secret if material is not None else ""),
    )
    resolved = call_target_public(model_id, requested_tier, model=model, provider=provider,
                                  material=material,
                                  sent_tier=limit_reasoning_level(model, requested_tier))
    return CallTargetResolution(True, "", "", resolved), target
