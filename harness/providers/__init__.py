from __future__ import annotations

# 三种协议的实现随 Provider 模块一起导入，各自的 SDK 一次性初始化在服务启动时完成（D09）
from . import chat, messages, responses
from .call import CallUsage, ModelCall, ModelResponse, ModelStreamEvent
from .credentials import CredentialChain, CredentialMaterial, load_dotenv_dict, parse_dotenv_text
from .discovery import refresh_candidates
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
from .resolve import FrozenTarget, ResolveSnapshot, resolve_snapshot
from .responses import ProviderConnections, ResponsesConfig, check_availability
from .store import ModelDefinition, ProviderDefinition, ProviderStore, SUPPORTED_PROTOCOLS

__all__ = [
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
