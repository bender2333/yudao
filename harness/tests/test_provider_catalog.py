import json

import pytest

from harness.provider_catalog import (
    CatalogValidationError,
    CredentialMaterial,
    ModelDefinition,
    ProviderCatalog,
    ProviderDefinition,
)


def _catalog(*, context_window=32_000, max_output_tokens=4_096):
    providers = [
        ProviderDefinition(
            id="provider-a", name="Provider A", protocol="responses",
            base_url="https://a.example/v1", credential_ref="credential-a",
        ),
        ProviderDefinition(
            id="provider-b", name="Provider B", protocol="responses",
            base_url="https://b.example/v1", credential_ref="credential-b",
        ),
        ProviderDefinition(
            id="provider-c", name="Provider C", protocol="responses",
            base_url="https://c.example/v1", credential_ref="credential-a",
        ),
    ]
    models = [
        ModelDefinition("model-a", "provider-a", "model-a", context_window, max_output_tokens),
        ModelDefinition("model-b", "provider-b", "model-b", context_window, max_output_tokens),
        ModelDefinition("model-c", "provider-c", "model-c", context_window, max_output_tokens),
    ]
    return ProviderCatalog(
        providers,
        models,
        {
            "product": {"provider_id": "provider-a", "model_id": "model-a"},
            "engineering": {"provider_id": "provider-b", "model_id": "model-b"},
            "quality": {"provider_id": "provider-c", "model_id": "model-c"},
        },
    )


def test_snapshot_freezes_three_distinct_targets_without_persisting_secrets():
    catalog = _catalog()
    calls = []

    def resolve(reference):
        calls.append(reference)
        return CredentialMaterial(f"secret-{len(calls)}", version=f"v{len(calls)}")

    snapshot = catalog.resolve_snapshot(resolve)

    assert snapshot.target("product").provider_id == "provider-a"
    assert snapshot.target("engineering").provider_id == "provider-b"
    assert snapshot.target("quality").model == "model-c"
    assert snapshot.target("product").api_key == "secret-1"
    assert calls == ["credential-a", "credential-b"]
    public = snapshot.public_dict()
    encoded = json.dumps(public)
    assert "secret-1" not in encoded
    assert public["departments"]["product"]["credential_ref"] == "credential-a"
    assert public["departments"]["product"]["credential_version"] == "v1"
    second = catalog.resolve_snapshot(resolve)
    assert calls == ["credential-a", "credential-b", "credential-a", "credential-b"]
    assert second.target("product").api_key == "secret-3"


def test_each_target_creates_an_independent_adapter_instance():
    catalog = ProviderCatalog(
        [ProviderDefinition("fake-provider", "Fake", "fake")],
        [ModelDefinition("fake-model", "fake-provider", "fake-script", 8_000, 1_000)],
        {department: {"provider_id": "fake-provider", "model_id": "fake-model"}
         for department in ("product", "engineering", "quality")},
    )
    snapshot = catalog.resolve_snapshot()
    first = snapshot.target("product").create_adapter()
    second = snapshot.target("product").create_adapter()

    assert first is not second
    assert first.name == second.name == "fake"


def test_unknown_unused_protocol_can_be_cataloged_but_bound_protocol_is_rejected():
    providers = [
        ProviderDefinition("unknown-provider", "Future", "chat-completions", "https://future.example/v1"),
        ProviderDefinition("fake-provider", "Fake", "fake"),
    ]
    models = [
        ModelDefinition("future-model", "unknown-provider", "future", 8_000, 1_000),
        ModelDefinition("fake-model", "fake-provider", "fake", 8_000, 1_000),
    ]
    catalog = ProviderCatalog(
        providers,
        models,
        {department: {"provider_id": "fake-provider", "model_id": "fake-model"}
         for department in ("product", "engineering", "quality")},
    )
    catalog.validate()
    assert {item["protocol"] for item in catalog.to_dict()["providers"]} == {"fake", "chat-completions"}

    with pytest.raises(CatalogValidationError) as caught:
        ProviderCatalog(
            providers,
            models,
            {"product": {"provider_id": "unknown-provider", "model_id": "future-model"},
             "engineering": {"provider_id": "fake-provider", "model_id": "fake-model"},
             "quality": {"provider_id": "fake-provider", "model_id": "fake-model"}},
        )
    assert any(issue.location == "bindings.product.provider_id" for issue in caught.value.issues)


@pytest.mark.parametrize(
    "provider_kwargs,expected",
    [
        ({"protocol": "responses", "base_url": "https://user:pass@example/v1", "credential_ref": "key"}, "base_url"),
        ({"protocol": "responses", "base_url": "https://example/v1?api_key=secret", "credential_ref": "key"}, "base_url"),
        ({"protocol": "responses", "base_url": "https://example/v1", "credential_ref": ""}, "credential_ref"),
    ],
)
def test_responses_provider_rejects_credentials_in_url_and_missing_credential_reference(provider_kwargs, expected):
    provider = ProviderDefinition("provider", "Provider", **provider_kwargs)
    with pytest.raises(CatalogValidationError) as caught:
        ProviderCatalog(
            [provider], [ModelDefinition("model", "provider", "model", 8_000, 1_000)],
            {department: {"provider_id": "provider", "model_id": "model"}
             for department in ("product", "engineering", "quality")},
        )
    assert any(issue.location.endswith(expected) for issue in caught.value.issues)


def test_unknown_model_capacity_is_rejected_for_a_bound_department():
    with pytest.raises(CatalogValidationError) as caught:
        _catalog(context_window=None)
    assert any("context_window is required" in issue.message for issue in caught.value.issues)


def test_max_output_tokens_is_required_and_positive_in_json():
    raw = {
        "providers": [{"id": "fake", "name": "Fake", "protocol": "fake"}],
        "models": [{"id": "model", "provider_id": "fake", "model": "fake", "context_window": 100}],
        "bindings": {department: {"provider_id": "fake", "model_id": "model"}
                     for department in ("product", "engineering", "quality")},
    }
    with pytest.raises(CatalogValidationError) as caught:
        ProviderCatalog.from_dict(raw)
    assert any(issue.location == "models[0].max_output_tokens" for issue in caught.value.issues)


def test_malformed_array_or_object_identifiers_use_safe_array_locations():
    raw = {
        "providers": [{"id": ["secret-value"], "name": "Provider", "protocol": "fake"}],
        "models": [{"id": {"secret": "value"}, "provider_id": "provider", "model": "model",
                     "context_window": 100, "max_output_tokens": 10}],
        "bindings": {department: {"provider_id": "provider", "model_id": "model"}
                     for department in ("product", "engineering", "quality")},
    }
    with pytest.raises(CatalogValidationError) as caught:
        ProviderCatalog.from_dict(raw)
    assert all("secret-value" not in str(issue) and "secret" not in issue.location for issue in caught.value.issues)
    assert any(issue.location == "providers[0].id" for issue in caught.value.issues)
    assert any(issue.location == "models[0].id" for issue in caught.value.issues)


def test_malformed_protocol_is_reported_without_membership_type_error():
    raw = {
        "providers": [{"id": "provider", "name": "Provider", "protocol": ["responses"],
                       "base_url": "https://provider.example/v1", "credential_ref": "KEY"}],
        "models": [{"id": "model", "provider_id": "provider", "model": "model",
                     "context_window": 100, "max_output_tokens": 10}],
        "bindings": {department: {"provider_id": "provider", "model_id": "model"}
                     for department in ("product", "engineering", "quality")},
    }
    with pytest.raises(CatalogValidationError) as caught:
        ProviderCatalog.from_dict(raw)
    assert any(issue.location == "providers[0].protocol" for issue in caught.value.issues)


def test_json_round_trip_contains_only_non_sensitive_directory_fields(tmp_path):
    catalog = _catalog()
    path = tmp_path / "providers.json"
    path.write_text(json.dumps(catalog.to_dict()), encoding="utf-8")
    loaded = ProviderCatalog.load(path)
    assert loaded.to_dict() == catalog.to_dict()
    assert "api_key" not in json.dumps(loaded.to_dict())
