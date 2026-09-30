from __future__ import annotations

import json

import pytest

from harness.providers import CredentialChain, ProviderFacade


SECRET = "yudao-resolve-call-secret-45"

PUBLIC_FIELDS = {
    "provider_config_id",
    "model_id",
    "provider_name",
    "protocol",
    "base_url",
    "requested_provider",
    "requested_protocol",
    "requested_model",
    "credential_ref",
    "credential_version",
    "context_window",
    "configured_max_output_tokens",
    "accepts_required_tool_call",
    "requested_tier",
    "sent_tier",
}


def _facade(document, **overrides):
    facade = ProviderFacade(credentials=CredentialChain(use_env=False))
    facade.store_document(document)
    for ref, secret in overrides.items():
        facade.set_credential_override(ref, secret)
    return facade


def _responses_document():
    return {
        "providers": [
            {
                "id": "provider-a",
                "name": "Provider A",
                "protocol": "responses",
                "base_url": "https://a.example/v1",
                "credential_ref": "credential-a",
            },
        ],
        "models": [
            {
                "id": "model-a",
                "provider_id": "provider-a",
                "model": "upstream-a",
                "context_window": 32000,
                "max_output_tokens": 4096,
            },
        ],
        "bindings": {
            "product": {"provider_id": "provider-a", "model_id": "model-a"},
            "engineering": {"provider_id": "provider-a", "model_id": "model-a"},
            "quality": {"provider_id": "provider-a", "model_id": "model-a"},
        },
    }


def test_resolved_public_result_has_no_secret():
    facade = _facade(_responses_document(), **{"credential-a": SECRET})
    facade.record_admission("provider-a", "model-a", admitted_model="upstream-a")

    resolved = facade.resolve_call_target("model-a", requested_tier=None)

    assert resolved.available is True
    assert resolved.reason == "" and resolved.message == ""
    assert resolved.handle_id and SECRET not in resolved.handle_id
    assert set(resolved.public) == PUBLIC_FIELDS
    assert dict(resolved.public) == {
        "provider_config_id": "provider-a",
        "model_id": "model-a",
        "provider_name": "Provider A",
        "protocol": "responses",
        "base_url": "https://a.example/v1",
        "requested_provider": "provider-a",
        "requested_protocol": "responses",
        "requested_model": "upstream-a",
        "credential_ref": "credential-a",
        "credential_version": "override",
        "context_window": 32000,
        "configured_max_output_tokens": 4096,
        "accepts_required_tool_call": True,
        "requested_tier": None,
        "sent_tier": None,
    }
    rendered = json.dumps(dict(resolved.public), ensure_ascii=False)
    assert SECRET not in rendered and SECRET not in repr(resolved)
    assert "api_key" not in resolved.public and not hasattr(resolved, "api_key")
    assert "reasoning" not in rendered and "reasoning_effort" not in rendered

    released = facade.release_call_handle(resolved.handle_id)
    assert dict(released) == dict(resolved.public)
    assert SECRET not in json.dumps(dict(released), ensure_ascii=False)
    with pytest.raises(KeyError):
        facade.release_call_handle(resolved.handle_id)

    frozen = facade.resolve_departments().target("product")
    assert frozen.api_key == SECRET


def _unavailable_reasons(facade, model_id, requested_tier=None):
    resolved = facade.resolve_call_target(model_id, requested_tier)
    assert resolved.available is False
    assert resolved.reason == "provider_unavailable"
    assert resolved.handle_id is None
    assert set(resolved.public) == PUBLIC_FIELDS
    assert SECRET not in json.dumps(dict(resolved.public), ensure_ascii=False)
    with pytest.raises(KeyError):
        facade.release_call_handle("target_missing")
    return resolved


def test_missing_definition_is_unavailable():
    facade = _facade(_responses_document(), **{"credential-a": SECRET})
    facade.record_admission("provider-a", "model-a", admitted_model="upstream-a")

    resolved = _unavailable_reasons(facade, "model-missing")

    assert resolved.message == "模型访问定义不存在"
    assert resolved.public["model_id"] == "model-missing"


def test_model_without_admission_is_unavailable():
    facade = _facade(_responses_document(), **{"credential-a": SECRET})

    resolved = _unavailable_reasons(facade, "model-a")

    assert "准入" in resolved.message
    assert resolved.public["requested_model"] == "upstream-a"


def test_unknown_window_is_unavailable():
    document = _responses_document()
    document["models"][0]["context_window"] = None
    facade = _facade(document, **{"credential-a": SECRET})
    facade.record_admission("provider-a", "model-a", admitted_model="upstream-a")

    resolved = _unavailable_reasons(facade, "model-a")

    assert "context_window" in resolved.message
    assert resolved.public["context_window"] is None


def test_missing_credential_material_is_unavailable():
    facade = _facade(_responses_document())
    facade.record_admission("provider-a", "model-a", admitted_model="upstream-a")

    resolved = _unavailable_reasons(facade, "model-a")

    assert "credential-a" in resolved.message and "凭据" in resolved.message
    assert resolved.public["credential_ref"] == "credential-a"
    assert resolved.public["credential_version"] is None


def test_fake_protocol_needs_neither_admission_nor_credential():
    document = _responses_document()
    document["providers"][0]["protocol"] = "fake"
    document["models"][0]["model"] = "fake-script"
    facade = _facade(document)

    resolved = facade.resolve_call_target("model-a")

    assert resolved.available is True
    assert resolved.public["protocol"] == "fake"
    assert resolved.public["credential_version"] is None
    released = facade.release_call_handle(resolved.handle_id)
    assert dict(released) == dict(resolved.public)


def test_requested_tier_is_recorded_without_limiting_or_encoding():
    facade = _facade(_responses_document(), **{"credential-a": SECRET})
    facade.record_admission("provider-a", "model-a", admitted_model="upstream-a")

    resolved = facade.resolve_call_target("model-a", "high")

    assert resolved.available is True
    assert resolved.public["requested_tier"] == "high"
    assert resolved.public["sent_tier"] is None
    rendered = json.dumps(dict(resolved.public), ensure_ascii=False)
    assert "reasoning" not in rendered and "effort" not in rendered
    facade.release_call_handle(resolved.handle_id)
