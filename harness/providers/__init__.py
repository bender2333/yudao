from __future__ import annotations

# 三种协议的实现随 Provider 模块一起导入，各自的 SDK 一次性初始化在服务启动时完成（D09）
from . import chat, messages, responses
from .call import CallUsage, ModelCall, ModelResponse, ModelStreamEvent
from .credentials import CredentialChain, CredentialMaterial, load_dotenv_dict, parse_dotenv_text
from .discovery import effective_models_url, probe_connection, refresh_candidates
from .errors import (
    CatalogValidationError,
    CancelledError,
    ProviderError,
    UnsupportedProtocolError,
    ValidationIssue,
)
from .facade import ProviderFacade
from .invoke import (
    CancelRegistry,
    InvokeResult,
    ProviderInput,
    ProviderMessage,
    ToolResult,
    ToolSpec,
    check_target_availability,
    to_provider_input,
)
from .messages import anthropic_base_url
from .presets import (
    PRESET_TABLE_SOURCE,
    PRESET_TABLE_VERSION,
    USER_AGENT,
    build_identity_headers,
    get_preset,
    list_presets,
)
from .resolve import CallTargetResolution, FrozenTarget, ResolveSnapshot, resolve_snapshot
from .responses import ProviderConnections, ResponsesConfig, check_availability
from .selection import (
    DEPARTMENT_DEFAULT_SOURCE,
    PROJECT_DEPARTMENT_SETTING_SOURCE,
    ModelSelection,
    SelectionResolution,
    merge_selection,
)
from . import capabilities, suggested
from .store import DEFAULT_TIMEOUT_SEC, ModelDefinition, ProviderDefinition, ProviderStore, SUPPORTED_PROTOCOLS
from .tls import ssl_context

__all__ = [
    "ssl_context",
    "DEFAULT_TIMEOUT_SEC",
    "capabilities",
    "suggested",
    "ProviderFacade",
    "ProviderStore",
    "ProviderDefinition",
    "ModelDefinition",
    "SUPPORTED_PROTOCOLS",
    "PRESET_TABLE_VERSION",
    "PRESET_TABLE_SOURCE",
    "USER_AGENT",
    "list_presets",
    "get_preset",
    "build_identity_headers",
    "effective_models_url",
    "probe_connection",
    "refresh_candidates",
    "ModelCall",
    "ModelStreamEvent",
    "ModelResponse",
    "CallUsage",
    "ProviderConnections",
    "anthropic_base_url",
    "CredentialChain",
    "CredentialMaterial",
    "load_dotenv_dict",
    "parse_dotenv_text",
    "FrozenTarget",
    "ResolveSnapshot",
    "resolve_snapshot",
    "CallTargetResolution",
    "ModelSelection",
    "SelectionResolution",
    "merge_selection",
    "DEPARTMENT_DEFAULT_SOURCE",
    "PROJECT_DEPARTMENT_SETTING_SOURCE",
    "ProviderInput",
    "ProviderMessage",
    "ToolSpec",
    "ToolResult",
    "InvokeResult",
    "CancelRegistry",
    "to_provider_input",
    "check_target_availability",
    "ResponsesConfig",
    "check_availability",
    "ValidationIssue",
    "CatalogValidationError",
    "ProviderError",
    "CancelledError",
    "UnsupportedProtocolError",
]
