"""统一 Provider/模型目录、部门绑定及任务级解析快照。

目录文件只保存非敏感连接配置和凭据引用。宿主在创建任务时通过
``resolve_snapshot`` 解析凭据，解析结果只存在于当前进程内存中；快照的
``to_dict`` 永远不会包含凭据内容。
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from .models import DEPARTMENTS


SUPPORTED_PROTOCOLS = frozenset({"responses", "fake"})
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


@dataclass(frozen=True)
class ValidationIssue:
    """一个不含敏感值的目录校验问题。"""

    location: str
    message: str


class CatalogValidationError(ValueError):
    """目录或部门绑定不能安全解析时抛出的错误。"""

    def __init__(self, issues: Iterable[ValidationIssue]) -> None:
        self.issues = tuple(issues)
        if not self.issues:
            self.issues = (ValidationIssue("catalog", "invalid provider catalog"),)
        super().__init__("; ".join(f"{issue.location}: {issue.message}" for issue in self.issues))


@dataclass(frozen=True)
class CredentialMaterial:
    """宿主解析出的凭据，只能存活在内存中的目标对象里。"""

    secret: str = field(repr=False, compare=False)
    version: str | None = None


CredentialResolver = Callable[[str], CredentialMaterial | str | None]
CredentialSource = CredentialResolver | Mapping[str, CredentialMaterial | str]


@dataclass(frozen=True)
class ProviderDefinition:
    id: str
    name: str
    protocol: str
    base_url: str = ""
    credential_ref: str = ""
    timeout_sec: float = 600.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", self.id.strip() if isinstance(self.id, str) else self.id)
        object.__setattr__(self, "name", self.name.strip() if isinstance(self.name, str) else self.name)
        object.__setattr__(self, "protocol", self.protocol.strip().casefold()
                           if isinstance(self.protocol, str) else self.protocol)
        object.__setattr__(self, "base_url", self.base_url.strip() if isinstance(self.base_url, str) else self.base_url)
        object.__setattr__(self, "credential_ref", self.credential_ref.strip()
                           if isinstance(self.credential_ref, str) else self.credential_ref)

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "protocol": self.protocol,
            "base_url": self.base_url,
            "credential_ref": self.credential_ref,
            "timeout_sec": self.timeout_sec,
        }


@dataclass(frozen=True)
class ModelDefinition:
    id: str
    provider_id: str
    model: str
    context_window: int | None
    max_output_tokens: int

    def __post_init__(self) -> None:
        for name in ("id", "provider_id", "model"):
            value = getattr(self, name)
            object.__setattr__(self, name, value.strip() if isinstance(value, str) else value)

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider_id": self.provider_id,
            "model": self.model,
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
        }


@dataclass(frozen=True)
class DepartmentBinding:
    department: str
    provider_id: str
    model_id: str

    def __post_init__(self) -> None:
        for name in ("department", "provider_id", "model_id"):
            value = getattr(self, name)
            object.__setattr__(self, name, value.strip() if isinstance(value, str) else value)

    def public_dict(self) -> dict[str, str]:
        return {"provider_id": self.provider_id, "model_id": self.model_id}


@dataclass(frozen=True)
class ResolvedProviderTarget:
    """一个部门在任务创建时冻结的实际请求目标。

    ``api_key`` 是唯一的敏感字段，故意从 repr、比较和 ``public_dict`` 中排除。
    """

    department: str
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
    credential_version: str | None = None
    api_key: str = field(default="", repr=False, compare=False)

    def public_dict(self) -> dict[str, Any]:
        return {
            "department": self.department,
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
            "credential_version": self.credential_version,
        }

    def create_adapter(
        self,
        *,
        fake_script: Sequence[Any] | None = None,
        execution_scope: Any | None = None,
    ):
        """为一次激活创建独立适配器实例，不共享活动请求状态。"""

        if self.protocol == "responses":
            from .adapters.responses import ResponsesAdapter
            from .adapters.responses import ResponsesConfig

            return ResponsesAdapter(
                ResponsesConfig(
                    model=self.model,
                    api_key=self.api_key,
                    provider=self.provider_id,
                    base_url=self.base_url,
                    timeout_sec=self.timeout_sec,
                ),
                execution_scope=execution_scope,
            )
        if self.protocol == "fake":
            from .adapters.fake import FakeAdapter

            return FakeAdapter(fake_script)
        raise ValueError(f"unsupported provider protocol: {self.protocol}")

@dataclass(frozen=True)
class ProviderCatalogSnapshot:
    """三部门任务级目标快照；仅公开非敏感字段。"""

    targets: Mapping[str, ResolvedProviderTarget]

    def __post_init__(self) -> None:
        normalized = dict(self.targets)
        object.__setattr__(self, "targets", MappingProxyType(normalized))

    def target(self, department: str) -> ResolvedProviderTarget:
        try:
            return self.targets[department]
        except KeyError as exc:
            raise KeyError(f"unknown department: {department}") from exc

    def public_dict(self) -> dict[str, Any]:
        return {
            "departments": {
                department: self.targets[department].public_dict()
                for department in DEPARTMENTS
                if department in self.targets
            }
        }

class ProviderCatalog:
    """Provider、模型及三部门默认绑定的统一目录。"""

    def __init__(
        self,
        providers: Iterable[ProviderDefinition],
        models: Iterable[ModelDefinition],
        bindings: Mapping[str, DepartmentBinding | Mapping[str, Any]],
    ) -> None:
        self._provider_items = tuple(providers)
        self._model_items = tuple(models)
        self.providers = MappingProxyType(_index_definitions(self._provider_items))
        self.models = MappingProxyType(_index_definitions(self._model_items))
        self.bindings = MappingProxyType(_normalize_bindings(bindings))
        self._validate_definition_shape()

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ProviderCatalog":
        if not isinstance(raw, Mapping):
            raise CatalogValidationError((ValidationIssue("catalog", "expected a JSON object"),))
        allowed = {"providers", "models", "bindings"}
        unknown = sorted(set(raw) - allowed, key=str)
        issues: list[ValidationIssue] = [ValidationIssue(f"catalog.{key}", "unknown field") for key in unknown]
        providers: list[ProviderDefinition] = []
        models: list[ModelDefinition] = []
        bindings: dict[str, DepartmentBinding | Mapping[str, Any]] = {}
        provider_items = raw.get("providers")
        model_items = raw.get("models")
        raw_bindings = raw.get("bindings")
        if not isinstance(provider_items, list):
            issues.append(ValidationIssue("providers", "must be an array"))
        else:
            for index, item in enumerate(provider_items):
                parsed, item_issues = _parse_provider(item, f"providers[{index}]")
                issues.extend(item_issues)
                if parsed is not None:
                    providers.append(parsed)
        if not isinstance(model_items, list):
            issues.append(ValidationIssue("models", "must be an array"))
        else:
            for index, item in enumerate(model_items):
                parsed, item_issues = _parse_model(item, f"models[{index}]")
                issues.extend(item_issues)
                if parsed is not None:
                    models.append(parsed)
        if not isinstance(raw_bindings, Mapping):
            issues.append(ValidationIssue("bindings", "must be an object"))
        else:
            for department, item in raw_bindings.items():
                if not isinstance(department, str):
                    issues.append(ValidationIssue("bindings", "department names must be strings"))
                    continue
                parsed, item_issues = _parse_binding(item, f"bindings.{department}", department)
                issues.extend(item_issues)
                if parsed is not None:
                    bindings[department] = parsed
        if issues:
            raise CatalogValidationError(issues)
        return cls(providers, models, bindings)

    @classmethod
    def load(cls, path: str | Path) -> "ProviderCatalog":
        source = Path(path)
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CatalogValidationError((ValidationIssue("catalog", "cannot read provider catalog"),)) from exc
        return cls.from_dict(raw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "providers": [self.providers[key].public_dict() for key in sorted(self.providers)],
            "models": [self.models[key].public_dict() for key in sorted(self.models)],
            "bindings": {
                department: self.bindings[department].public_dict()
                for department in DEPARTMENTS
                if department in self.bindings
            },
        }

    def validate(self) -> None:
        """校验目录定义和三部门绑定，但不尝试解析宿主凭据。"""

        self._validate_definition_shape()

    def resolve_snapshot(self, credentials: CredentialSource | None = None) -> ProviderCatalogSnapshot:
        """解析全部部门绑定，生成本任务固定使用的目标快照。"""

        issues = self._binding_issues()
        if issues:
            raise CatalogValidationError(issues)
        targets: dict[str, ResolvedProviderTarget] = {}
        credential_issues: list[ValidationIssue] = []
        credential_cache: dict[str, CredentialMaterial | None] = {}
        for department in DEPARTMENTS:
            binding = self.bindings[department]
            provider = self.providers[binding.provider_id]
            model = self.models[binding.model_id]
            material = None
            if provider.protocol == "responses":
                if provider.credential_ref not in credential_cache:
                    credential_cache[provider.credential_ref] = _resolve_credential(
                        credentials, provider.credential_ref,
                    )
                material = credential_cache[provider.credential_ref]
                if material is None or not isinstance(material.secret, str) or not material.secret.strip():
                    credential_issues.append(ValidationIssue(
                        f"departments.{department}.credential",
                        "credential reference cannot be resolved",
                    ))
                    continue
            targets[department] = ResolvedProviderTarget(
                department=department,
                provider_id=provider.id,
                provider_name=provider.name,
                model_id=model.id,
                protocol=provider.protocol,
                base_url=provider.base_url,
                model=model.model,
                context_window=model.context_window,  # type: ignore[arg-type]
                max_output_tokens=model.max_output_tokens,
                timeout_sec=provider.timeout_sec,
                credential_ref=provider.credential_ref or None,
                credential_version=(
                    None if material is None or not isinstance(material.version, str)
                    else material.version
                ),
                api_key="" if material is None else material.secret,
            )
        if credential_issues:
            raise CatalogValidationError(credential_issues)
        return ProviderCatalogSnapshot(targets)

    def _validate_definition_shape(self) -> None:
        issues: list[ValidationIssue] = []
        provider_ids: set[str] = set()
        for index, provider in enumerate(self._provider_items):
            location = f"providers[{index}]"
            if not isinstance(provider, ProviderDefinition):
                issues.append(ValidationIssue(location, "must be a provider definition"))
                continue
            if not _valid_identifier(provider.id):
                issues.append(ValidationIssue(f"{location}.id", "must be a simple non-empty identifier"))
            if _hashable(provider.id) and provider.id in provider_ids:
                issues.append(ValidationIssue(f"{location}.id", "duplicate provider id"))
            if _hashable(provider.id):
                provider_ids.add(provider.id)
            if not isinstance(provider.name, str) or not provider.name:
                issues.append(ValidationIssue(f"{location}.name", "must be a non-empty string"))
            if not isinstance(provider.protocol, str) or not provider.protocol:
                issues.append(ValidationIssue(f"{location}.protocol", "must be a non-empty string"))
            if not isinstance(provider.timeout_sec, (int, float)) or isinstance(provider.timeout_sec, bool) \
                    or not math.isfinite(float(provider.timeout_sec)) or provider.timeout_sec <= 0:
                issues.append(ValidationIssue(f"{location}.timeout_sec", "must be positive and finite"))
            if provider.protocol == "responses":
                if not _valid_url(provider.base_url):
                    issues.append(ValidationIssue(f"{location}.base_url", "must be an HTTP(S) URL without credentials"))
                if not _valid_identifier(provider.credential_ref):
                    issues.append(ValidationIssue(f"{location}.credential_ref", "must be a non-empty credential reference"))
            elif provider.protocol == "fake":
                if provider.base_url:
                    issues.append(ValidationIssue(f"{location}.base_url", "fake provider must not define a URL"))
                if provider.credential_ref:
                    issues.append(ValidationIssue(f"{location}.credential_ref", "fake provider must not define credentials"))
            elif provider.base_url and not _valid_url(provider.base_url):
                issues.append(ValidationIssue(f"{location}.base_url", "must be an HTTP(S) URL without credentials"))
            if isinstance(provider.protocol, str) and provider.protocol not in SUPPORTED_PROTOCOLS and provider.credential_ref \
                    and not _valid_identifier(provider.credential_ref):
                issues.append(ValidationIssue(f"{location}.credential_ref", "must be a credential reference"))

        model_ids: set[str] = set()
        for index, model in enumerate(self._model_items):
            location = f"models[{index}]"
            if not isinstance(model, ModelDefinition):
                issues.append(ValidationIssue(location, "must be a model definition"))
                continue
            if not _valid_identifier(model.id):
                issues.append(ValidationIssue(f"{location}.id", "must be a simple non-empty identifier"))
            if _hashable(model.id) and model.id in model_ids:
                issues.append(ValidationIssue(f"{location}.id", "duplicate model id"))
            if _hashable(model.id):
                model_ids.add(model.id)
            if not _valid_identifier(model.provider_id):
                issues.append(ValidationIssue(f"{location}.provider_id", "must be a provider identifier"))
            if not isinstance(model.model, str) or not model.model.strip():
                issues.append(ValidationIssue(f"{location}.model", "must be a non-empty string"))
            _validate_positive_int(model.context_window, f"{location}.context_window", issues, allow_none=True)
            _validate_positive_int(model.max_output_tokens, f"{location}.max_output_tokens", issues, allow_none=False)
            if model.context_window is not None and model.max_output_tokens is not None \
                    and isinstance(model.context_window, int) and isinstance(model.max_output_tokens, int) \
                    and model.max_output_tokens > model.context_window:
                issues.append(ValidationIssue(f"{location}.max_output_tokens", "must not exceed context_window"))

        issues.extend(self._binding_issues())
        if issues:
            raise CatalogValidationError(issues)

    def _binding_issues(self) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for department in DEPARTMENTS:
            binding = self.bindings.get(department)
            if binding is None:
                issues.append(ValidationIssue(f"bindings.{department}", "department binding is required"))
                continue
            provider = _mapping_get(self.providers, binding.provider_id)
            model = _mapping_get(self.models, binding.model_id)
            if provider is None:
                issues.append(ValidationIssue(
                    f"bindings.{department}.provider_id", "provider does not exist",
                ))
            if model is None:
                issues.append(ValidationIssue(
                    f"bindings.{department}.model_id", "model does not exist",
                ))
            if provider is not None and model is not None and model.provider_id != provider.id:
                issues.append(ValidationIssue(
                    f"bindings.{department}", "model belongs to a different provider",
                ))
            if provider is not None and (
                    not isinstance(provider.protocol, str) or provider.protocol not in SUPPORTED_PROTOCOLS):
                issues.append(ValidationIssue(
                    f"bindings.{department}.provider_id", "provider protocol is unsupported",
                ))
            if model is not None and model.context_window is None:
                issues.append(ValidationIssue(
                    f"bindings.{department}.model_id", "model context_window is required for a task",
                ))
        for department in self.bindings:
            if department not in DEPARTMENTS:
                issues.append(ValidationIssue(f"bindings.{department}", "unknown department"))
        return issues


def _normalize_bindings(
    bindings: Mapping[str, DepartmentBinding | Mapping[str, Any]],
) -> dict[str, DepartmentBinding]:
    normalized: dict[str, DepartmentBinding] = {}
    issues: list[ValidationIssue] = []
    for department, raw in bindings.items():
        if isinstance(raw, DepartmentBinding):
            binding = raw
            if binding.department != department:
                issues.append(ValidationIssue(f"bindings.{department}", "department key does not match binding"))
            normalized[department] = binding
            continue
        parsed, item_issues = _parse_binding(raw, f"bindings.{department}", department)
        issues.extend(item_issues)
        if parsed is not None:
            normalized[department] = parsed
    if issues:
        raise CatalogValidationError(issues)
    return normalized


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


def _mapping_get(mapping: Mapping[Any, Any], key: Any) -> Any:
    return mapping.get(key) if _hashable(key) else None


def _parse_provider(raw: Any, location: str) -> tuple[ProviderDefinition | None, list[ValidationIssue]]:
    if not isinstance(raw, Mapping):
        return None, [ValidationIssue(location, "must be an object")]
    allowed = {"id", "name", "protocol", "base_url", "credential_ref", "timeout_sec"}
    issues = [ValidationIssue(f"{location}.{key}", "unknown field")
              for key in sorted(set(raw) - allowed, key=str)]
    required = {"id", "name", "protocol"}
    missing = required - set(raw)
    issues.extend(ValidationIssue(f"{location}.{key}", "is required") for key in sorted(missing))
    if issues:
        return None, issues
    provider = ProviderDefinition(
        id=raw["id"], name=raw["name"], protocol=raw["protocol"],
        base_url=raw.get("base_url", ""), credential_ref=raw.get("credential_ref", ""),
        timeout_sec=raw.get("timeout_sec", 600.0),
    )
    return provider, issues


def _parse_model(raw: Any, location: str) -> tuple[ModelDefinition | None, list[ValidationIssue]]:
    if not isinstance(raw, Mapping):
        return None, [ValidationIssue(location, "must be an object")]
    allowed = {"id", "provider_id", "model", "context_window", "max_output_tokens"}
    issues = [ValidationIssue(f"{location}.{key}", "unknown field")
              for key in sorted(set(raw) - allowed, key=str)]
    required = {"id", "provider_id", "model", "max_output_tokens"}
    missing = required - set(raw)
    issues.extend(ValidationIssue(f"{location}.{key}", "is required") for key in sorted(missing))
    if issues:
        return None, issues
    return ModelDefinition(
        id=raw["id"], provider_id=raw["provider_id"], model=raw["model"],
        context_window=raw.get("context_window"), max_output_tokens=raw["max_output_tokens"],
    ), issues


def _parse_binding(raw: Any, location: str, department: str) -> tuple[DepartmentBinding | None, list[ValidationIssue]]:
    if not isinstance(raw, Mapping):
        return None, [ValidationIssue(location, "must be an object")]
    allowed = {"provider_id", "model_id"}
    issues = [ValidationIssue(f"{location}.{key}", "unknown field")
              for key in sorted(set(raw) - allowed, key=str)]
    required = allowed - set(raw)
    issues.extend(ValidationIssue(f"{location}.{key}", "is required") for key in sorted(required))
    if issues:
        return None, issues
    return DepartmentBinding(department, raw["provider_id"], raw["model_id"]), issues


def _valid_identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(_IDENTIFIER_RE.fullmatch(value))


def _valid_url(value: Any) -> bool:
    if not isinstance(value, str) or not value or any(ord(char) < 32 for char in value):
        return False
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
        issues.append(ValidationIssue(location, "must be a positive integer"))


def _resolve_credential(source: CredentialSource | None, reference: str) -> CredentialMaterial | None:
    if source is None:
        return None
    try:
        value = source(reference) if callable(source) else source.get(reference)
    except Exception:
        return None
    if value is None:
        return None
    if isinstance(value, CredentialMaterial):
        return value
    if isinstance(value, str):
        return CredentialMaterial(value)
    return None


__all__ = [
    "SUPPORTED_PROTOCOLS",
    "CatalogValidationError",
    "CredentialMaterial",
    "DepartmentBinding",
    "ModelDefinition",
    "ProviderCatalog",
    "ProviderCatalogSnapshot",
    "ProviderDefinition",
    "ResolvedProviderTarget",
    "ValidationIssue",
]
