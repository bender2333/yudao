from __future__ import annotations

import json

import pytest

from harness.providers import (
    CatalogValidationError,
    CredentialMaterial,
    ProviderFacade,
    ProviderStore,
)


def _document(**overrides):
    document = {
        "providers": [
            {"id": "provider-a", "name": "Provider A", "protocol": "responses",
             "base_url": "https://a.example/v1", "credential_ref": "credential-a"},
            {"id": "provider-b", "name": "Provider B", "protocol": "responses",
             "base_url": "https://b.example/v1", "credential_ref": "credential-b"},
        ],
        "models": [
            {"id": "model-a", "provider_id": "provider-a", "model": "model-a",
             "context_window": 32000, "max_output_tokens": 4096},
            {"id": "model-b", "provider_id": "provider-b", "model": "model-b",
             "context_window": 32000, "max_output_tokens": 4096},
        ],
        "bindings": {
            "product": {"provider_id": "provider-a", "model_id": "model-a"},
            "engineering": {"provider_id": "provider-b", "model_id": "model-b"},
            "quality": {"provider_id": "provider-a", "model_id": "model-a"},
        },
    }
    document.update(overrides)
    return document


def _facade(**credential_overrides):
    facade = ProviderFacade()
    facade.store_document(_document())
    for ref, secret in credential_overrides.items():
        facade.set_credential_override(ref, secret)
    admit_bound_models(facade)
    return facade


def admit_bound_models(facade, document=None):
    # 真实协议模型须先经模型测试准入才能用于任务；测试通过模块接口记录该事实
    bindings = (document or facade.to_document())["bindings"]
    view = facade.providers_view()
    models = {item["id"]: item for item in view["models"]}
    protocols = {item["id"]: item["protocol"] for item in view["providers"]}
    admitted: set[tuple[str, str]] = set()
    for item in bindings.values():
        provider_id, model_id = item.get("provider_id"), item.get("model_id")
        if (provider_id, model_id) in admitted:
            continue
        admitted.add((provider_id, model_id))
        model = models.get(model_id)
        if model is None or protocols.get(provider_id) == "fake":
            continue
        facade.record_admission(provider_id, model_id, admitted_model=model["model"])


def test_new_document_round_trip_contains_only_non_sensitive_fields(tmp_path):
    facade = ProviderFacade()
    revision = facade.store_document(_document())
    assert revision >= 1
    target = tmp_path / "providers.json"
    facade.persist_document(target)
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert set(saved) == {"providers", "models", "bindings", "revision"}
    assert "api_key" not in json.dumps(saved)
    assert saved["bindings"]["product"] == {"provider_id": "provider-a", "model_id": "model-a"}

    reloaded = ProviderFacade()
    reloaded.load_document(target)
    assert reloaded.to_document() == facade.to_document()
    assert "api_key" not in json.dumps(reloaded.to_document())


def test_model_definition_declares_whether_it_accepts_a_required_tool_call():
    # 模型访问定义声明是否接受要求调用工具（#102）：没有写入时为接受；声明不接受时随目录保存并重新读出，
    # 修改后准入保持，解析出的调用目标带着这一项；取值必须是 true 或 false
    facade = _facade(**{"credential-a": "secret-a", "credential-b": "secret-b"})
    assert facade.providers_view()["models"][0]["accepts_required_tool_call"] is True
    assert facade.resolve_departments().target("product").accepts_required_tool_call is True

    document = _document()
    document["models"][0]["accepts_required_tool_call"] = False
    facade = _facade(**{"credential-a": "secret-a", "credential-b": "secret-b"})
    facade.store_document(document)
    admit_bound_models(facade, document)
    admitted_at = next(item["admitted_at"] for item in facade.model_admissions()
                       if item["model_id"] == "model-a")
    assert admitted_at is not None
    assert facade.resolve_departments().target("product").accepts_required_tool_call is False

    reloaded = ProviderFacade()
    reloaded.store_document(facade.to_document())
    view = reloaded.providers_view()
    assert view["models"][0]["accepts_required_tool_call"] is False
    # 准入记录与目录分开保存（#86），不随目录文档重新读出
    assert reloaded.model_admissions() == []

    bad = _document()
    bad["models"][0]["accepts_required_tool_call"] = "yes"
    with pytest.raises(CatalogValidationError) as caught:
        ProviderFacade().store_document(bad)
    assert any(issue.location == "models[0].accepts_required_tool_call" for issue in caught.value.issues)


def test_providers_view_model_dict_carries_capability_source_and_tool_call_declaration():
    # 对外目录的模型字典同时给出能力来源与是否接受要求调用工具（#102）；
    # 模型测试记录准入以后两项都保持，前端模型列表才能继续显示能力来源
    document = _document()
    document["models"][0]["capability_source"] = "preset-v1"
    document["models"][0]["accepts_required_tool_call"] = False
    facade = ProviderFacade()
    facade.store_document(document)
    facade.set_credential_override("credential-a", "secret-a")
    model = facade.providers_view()["models"][0]
    assert model["capability_source"] == "preset-v1"
    assert model["accepts_required_tool_call"] is False

    admit_bound_models(facade, document)
    model = facade.providers_view()["models"][0]
    assert model["capability_source"] == "preset-v1"
    assert model["accepts_required_tool_call"] is False
    admission = next(item for item in facade.model_admissions() if item["model_id"] == "model-a")
    assert admission["admitted_at"] is not None
    assert admission["admitted_model"] == "model-a"


def test_provider_config_requires_a_protocol():
    # 连接声明一种协议（ADR-0004）；缺少时指出字段位置
    document = _document()
    del document["providers"][0]["protocol"]
    facade = ProviderFacade()
    with pytest.raises(CatalogValidationError) as caught:
        facade.store_document(document)
    assert any(issue.location == "providers[0].protocol" for issue in caught.value.issues)


def test_model_definition_declaring_protocol_is_rejected_without_migration():
    # 模型访问定义不再声明协议（ADR-0004）：指出字段位置，不迁移
    document = _document()
    document["models"][0]["protocol"] = "responses"
    facade = ProviderFacade()
    with pytest.raises(CatalogValidationError) as caught:
        facade.store_document(document)
    assert any(issue.location == "models[0].protocol" for issue in caught.value.issues)


def test_model_without_protocol_is_accepted():
    facade = ProviderFacade()
    assertion = facade.store_document(_document())
    assert assertion >= 1
    view = facade.providers_view()
    assert "protocol" not in view["models"][0]
    assert view["providers"][0]["protocol"] == "responses"


def test_snapshot_freezes_three_targets_without_persisting_secrets():
    facade = _facade(**{"credential-a": CredentialMaterial("secret-a", version="a-v1"),
                        "credential-b": CredentialMaterial("secret-b", version="b-v1")})
    snapshot = facade.resolve_departments()
    assert snapshot.target("product").provider_id == "provider-a"
    assert snapshot.target("engineering").provider_id == "provider-b"
    assert snapshot.target("product").api_key == "secret-a"
    assert snapshot.target("product").credential_version == "a-v1"
    encoded = json.dumps(snapshot.public_dict())
    assert "secret-a" not in encoded and "secret-b" not in encoded
    assert "api_key" not in encoded


def test_each_target_is_independent_and_frozen_after_publish():
    facade = _facade(**{"credential-a": "secret-a", "credential-b": "secret-b"})
    snapshot = facade.resolve_departments()
    revision_before = facade.revision
    facade.save_model({
        "id": "model-c", "provider_id": "provider-a", "model": "model-c",
        "context_window": 8000, "max_output_tokens": 512,
    })
    assert facade.revision > revision_before
    assert snapshot.target("product").model == "model-a"
    assert facade.resolve_departments().target("product").model == "model-a"


def test_missing_credentials_reported_per_item():
    facade = ProviderFacade()
    facade.store_document(_document())
    with pytest.raises(CatalogValidationError) as caught:
        facade.resolve_departments()
    locations = [issue.location for issue in caught.value.issues]
    assert len(caught.value.issues) == 3
    assert any("product" in location for location in locations)
    assert any("engineering" in location for location in locations)
    assert any("quality" in location for location in locations)


def test_dangling_binding_references_are_rejected():
    facade = ProviderFacade()
    with pytest.raises(CatalogValidationError):
        facade.store_document(_document(bindings={
            "product": {"provider_id": "provider-a", "model_id": "missing-model"},
        }))
    facade.store_document(_document(bindings={
        "product": {"provider_id": "provider-a", "model_id": "model-a"},
    }))
    admit_bound_models(facade)
    with pytest.raises(CatalogValidationError):
        facade.save_bindings({"product": {"provider_id": "provider-a", "model_id": "missing-model"}})
    facade.save_bindings({"product": {"provider_id": "provider-a", "model_id": "model-a"}})
    assert facade.get_bindings()["product"] == {"provider_id": "provider-a", "model_id": "model-a"}


def test_unknown_model_capacity_is_rejected_for_a_bound_department():
    facade = ProviderFacade()
    document = _document()
    document["models"][0]["context_window"] = None
    facade.store_document(document)
    facade.set_credential_override("credential-a", "secret-a")
    facade.set_credential_override("credential-b", "secret-b")
    with pytest.raises(CatalogValidationError) as caught:
        facade.resolve_departments()
    assert any("context_window" in issue.location or "context_window" in issue.message
               for issue in caught.value.issues)


def test_max_output_tokens_is_required_and_positive():
    facade = ProviderFacade()
    document = _document()
    del document["models"][0]["max_output_tokens"]
    with pytest.raises(CatalogValidationError) as caught:
        facade.store_document(document)
    assert any(issue.location == "models[0].max_output_tokens" for issue in caught.value.issues)


def test_malformed_identifiers_use_safe_array_locations():
    facade = ProviderFacade()
    document = _document()
    document["providers"][0]["id"] = ["secret-value"]
    with pytest.raises(CatalogValidationError) as caught:
        facade.store_document(document)
    assert all("secret-value" not in str(issue) and "secret" not in issue.location
               for issue in caught.value.issues)
    assert any(issue.location == "providers[0].id" for issue in caught.value.issues)


def test_secret_never_in_public_views_or_readiness():
    secret = "super-secret-value-xyz"
    facade = _facade(**{"credential-a": secret, "credential-b": "other"})
    view = facade.providers_view()
    assert secret not in json.dumps(view, ensure_ascii=False)
    readiness = facade.describe_readiness()
    assert readiness["available"] is True
    assert secret not in json.dumps(readiness, ensure_ascii=False)
    assert readiness["departments"]["product"]["credential_version"] == "override"
    assert "api_key" not in readiness["departments"]["product"]


def test_store_rejects_base_url_with_credentials_and_missing_reference():
    facade = ProviderFacade()
    bad_url = _document()
    bad_url["providers"][0]["base_url"] = "https://user:pass@a.example/v1"
    with pytest.raises(CatalogValidationError) as caught:
        facade.store_document(bad_url)
    assert any(issue.location.endswith("base_url") for issue in caught.value.issues)
    assert ProviderStore.empty().public_view()["providers"] == []
