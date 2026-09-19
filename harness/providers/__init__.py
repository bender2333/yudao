from __future__ import annotations

from .chat import ChatExecutionScope, invoke_chat
from .credentials import CredentialChain, CredentialMaterial, load_dotenv_dict, parse_dotenv_text
from .discovery import refresh_candidates
from .errors import (
    CatalogValidationError,
    CancelledError,
    ProviderError,
    RequestNotPersistedError,
    UnsupportedProtocolError,
    ValidationIssue,
)
from .facade import ProviderFacade
from .invoke import (
    CancelRegistry,
    InvokeResult,
    NullObserver,
    Observer,
    ProviderInput,
    ProviderMessage,
    ToolResult,
    ToolSpec,
    invoke_once,
    to_provider_input,
)
from .messages import MessagesExecutionScope, anthropic_base_url, invoke_messages
from .presets import (
    PRESET_TABLE_SOURCE,
    PRESET_TABLE_VERSION,
    USER_AGENT,
    build_identity_headers,
    get_preset,
    list_presets,
)
from .resolve import FrozenTarget, ResolveSnapshot, resolve_snapshot
from .responses import ResponsesConfig, ResponsesExecutionScope, check_availability, invoke_responses
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
    "invoke_chat",
    "invoke_messages",
    "invoke_responses",
    "ChatExecutionScope",
    "MessagesExecutionScope",
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
    "Observer",
    "NullObserver",
    "CancelRegistry",
    "invoke_once",
    "to_provider_input",
    "ResponsesConfig",
    "ResponsesExecutionScope",
    "check_availability",
    "ValidationIssue",
    "CatalogValidationError",
    "ProviderError",
    "CancelledError",
    "UnsupportedProtocolError",
    "RequestNotPersistedError",
]
