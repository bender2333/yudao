from __future__ import annotations

import json

import pytest

from harness.providers import (
    CatalogValidationError,
    CredentialMaterial,
    ProviderFacade,
    ProviderStore,
)
from harness.definitions import DEFINITIONS
from harness.providers import capabilities
from harness.providers.discovery import _parse_candidates
from harness.providers.presets import preset_auth, preset_default_protocol


def _document(**overrides):
    document = {
        "providers": [
            {"id": "provider-a", "name": "Provider A",
             "base_url": "https://a.example/v1", "credential_ref": "credential-a"},
            {"id": "provider-b", "name": "Provider B",
             "base_url": "https://b.example/v1", "credential_ref": "credential-b"},
        ],
        "models": [
            {"id": "model-a", "provider_id": "provider-a", "model": "model-a",
             "protocol": "responses",
             "context_window": 32000, "max_output_tokens": 4096},
            {"id": "model-b", "provider_id": "provider-b", "model": "model-b",
             "protocol": "responses",
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
    protocols = {item["id"]: item.get("protocol") for item in view["models"]}
    admitted: set[tuple[str, str]] = set()
    for item in bindings.values():
        provider_id, model_id = item.get("provider_id"), item.get("model_id")
        if (provider_id, model_id) in admitted:
            continue
        admitted.add((provider_id, model_id))
        model = models.get(model_id)
        if model is None or protocols.get(model_id) == "fake":
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


def test_reasoning_declaration_round_trips_and_reaches_the_call_target():
    # 模型访问定义声明支持档位、默认档位与推理参数方式（#87）：随目录保存并重新读出，
    # 解析出的调用目标带着三项声明
    document = _document()
    document["models"][0]["reasoning_levels"] = ["low", "medium"]
    document["models"][0]["default_reasoning_level"] = "low"
    document["models"][0]["reasoning_mode"] = "effort"
    facade = _facade(**{"credential-a": "secret-a", "credential-b": "secret-b"})
    facade.store_document(document)
    view_model = facade.providers_view()["models"][0]
    assert view_model["reasoning_levels"] == ["low", "medium"]
    assert view_model["default_reasoning_level"] == "low"
    assert view_model["reasoning_mode"] == "effort"

    reloaded = ProviderFacade()
    reloaded.store_document(facade.to_document())
    model = reloaded.providers_view()["models"][0]
    assert model["reasoning_levels"] == ["low", "medium"]
    assert model["default_reasoning_level"] == "low"
    assert model["reasoning_mode"] == "effort"

def test_reasoning_declaration_default_must_be_a_supported_level():
    # 默认档位不属于支持档位时拒绝保存，错误指出字段位置（#87）
    document = _document()
    document["models"][0]["reasoning_levels"] = ["low"]
    document["models"][0]["default_reasoning_level"] = "high"
    document["models"][0]["reasoning_mode"] = "effort"
    with pytest.raises(CatalogValidationError) as caught:
        ProviderFacade().store_document(document)
    assert any(issue.location == "models[0].default_reasoning_level" for issue in caught.value.issues)

def test_reasoning_declaration_mode_must_match_the_connection_protocol():
    # 推理参数方式与连接协议不相符时拒绝保存，错误指出字段位置（#87）
    document = _document()
    document["models"][0]["reasoning_levels"] = ["low"]
    document["models"][0]["default_reasoning_level"] = "low"
    document["models"][0]["reasoning_mode"] = "adaptive"
    with pytest.raises(CatalogValidationError) as caught:
        ProviderFacade().store_document(document)
    assert any(issue.location == "models[0].reasoning_mode" for issue in caught.value.issues)

def test_reasoning_declaration_requires_all_three_parts():
    # 三项一起声明：只给支持档位时指出缺默认档位与推理参数方式（#87）
    document = _document()
    document["models"][0]["reasoning_levels"] = ["low"]
    with pytest.raises(CatalogValidationError) as caught:
        ProviderFacade().store_document(document)
    locations = {issue.location for issue in caught.value.issues}
    assert "models[0].default_reasoning_level" in locations
    assert "models[0].reasoning_mode" in locations

def test_reasoning_declaration_rejects_unknown_levels():
    document = _document()
    document["models"][0]["reasoning_levels"] = ["low", "ultra"]
    document["models"][0]["default_reasoning_level"] = "low"
    document["models"][0]["reasoning_mode"] = "effort"
    with pytest.raises(CatalogValidationError) as caught:
        ProviderFacade().store_document(document)
    assert any(issue.location == "models[0].reasoning_levels" for issue in caught.value.issues)

def test_changing_reasoning_mode_invalidates_admission_but_levels_do_not():
    # 修改推理参数方式使该定义回到候选；修改支持档位与默认档位保持准入（#87）
    document = _document()
    document["models"][0]["reasoning_levels"] = ["low", "medium"]
    document["models"][0]["default_reasoning_level"] = "low"
    document["models"][0]["reasoning_mode"] = "effort"
    facade = _facade(**{"credential-a": "secret-a", "credential-b": "secret-b"})
    facade.store_document(document)
    admit_bound_models(facade, document)
    assert facade.model_admissions()[0]["admitted"] is True

    kept = _document()
    kept["models"][0]["reasoning_levels"] = ["low", "medium", "high"]
    kept["models"][0]["default_reasoning_level"] = "medium"
    kept["models"][0]["reasoning_mode"] = "effort"
    facade.store_document(kept)
    admission = next(item for item in facade.model_admissions() if item["model_id"] == "model-a")
    assert admission["admitted"] is True
    assert admission["stale"] is False

def test_department_default_requested_tier_must_be_a_known_level():
    # 部门默认保存的请求档位只核对它属于档位全集（#87）：不属于全集时指出字段位置，
    # 超出所选模型支持档位的档位保存被接受，由每次请求按新模型限制
    document = _document()
    document["models"][0]["reasoning_levels"] = ["low", "medium"]
    document["models"][0]["default_reasoning_level"] = "low"
    document["models"][0]["reasoning_mode"] = "effort"
    document["bindings"]["product"]["requested_tier"] = "extreme"
    facade = ProviderFacade()
    with pytest.raises(CatalogValidationError) as caught:
        facade.store_document(document)
    assert any(issue.location == "bindings.product.requested_tier" for issue in caught.value.issues)

    document["bindings"]["product"]["requested_tier"] = "high"
    facade = ProviderFacade()
    facade.store_document(document)
    facade.set_credential_override("credential-a", "secret-a")
    assert facade.resolve_department_default("product").public["requested_tier"] == "high"

def test_swapping_to_a_model_with_other_levels_keeps_the_saved_tier_and_limits_the_request():
    # 运行中把部门默认换成支持档位不同的模型：保存被接受，原请求档位保留；
    # 下一次解析按新模型的支持档位限制，公开部分同时给出请求档位与实际发送的档位（#87）
    document = _document()
    document["models"][0]["reasoning_levels"] = ["medium", "high"]
    document["models"][0]["default_reasoning_level"] = "medium"
    document["models"][0]["reasoning_mode"] = "effort"
    document["models"][1]["reasoning_levels"] = ["low"]
    document["models"][1]["default_reasoning_level"] = "low"
    document["models"][1]["reasoning_mode"] = "effort"
    document["bindings"]["product"]["requested_tier"] = "high"
    facade = ProviderFacade()
    facade.store_document(document)
    facade.set_credential_override("credential-a", "secret-a")
    facade.set_credential_override("credential-b", "secret-b")
    admit_bound_models(facade, document)
    assert facade.resolve_department_default("product").public["sent_tier"] == "high"

    document["bindings"]["product"] = {"provider_id": "provider-b", "model_id": "model-b",
                                       "requested_tier": "high"}
    facade.store_document(document)
    assert facade.get_bindings()["product"]["requested_tier"] == "high"
    public = facade.resolve_department_default("product").public
    assert public["requested_tier"] == "high"
    assert public["sent_tier"] == "low"

def test_narrowing_supported_levels_keeps_a_referencing_binding_accepted():
    # 收窄某个模型的支持档位：仍有部门默认引用它、请求档位落在被移除的档位上时，
    # 这次目录修改仍被接受，下一次请求按收窄后的支持档位限制（#87）
    document = _document()
    document["models"][0]["reasoning_levels"] = ["low", "medium", "high"]
    document["models"][0]["default_reasoning_level"] = "low"
    document["models"][0]["reasoning_mode"] = "effort"
    document["bindings"]["product"]["requested_tier"] = "high"
    document["bindings"]["quality"]["requested_tier"] = "high"
    facade = ProviderFacade()
    facade.store_document(document)
    facade.set_credential_override("credential-a", "secret-a")

    document["models"][0]["reasoning_levels"] = ["low", "medium"]
    facade.store_document(document)
    assert facade.get_bindings()["product"]["requested_tier"] == "high"
    public = facade.resolve_department_default("product").public
    assert public["requested_tier"] == "high"
    assert public["sent_tier"] == "medium"

def test_provider_config_rejects_a_protocol():
    # 连接不再声明调用协议（ADR-0033）；出现时指出字段位置
    document = _document()
    document["providers"][0]["protocol"] = "responses"
    facade = ProviderFacade()
    with pytest.raises(CatalogValidationError) as caught:
        facade.store_document(document)
    assert any(issue.location == "providers[0].protocol" for issue in caught.value.issues)


def test_model_definition_requires_a_protocol():
    # 模型访问定义必须声明协议（ADR-0033）：缺少时指出字段位置
    document = _document()
    del document["models"][0]["protocol"]
    facade = ProviderFacade()
    with pytest.raises(CatalogValidationError) as caught:
        facade.store_document(document)
    assert any(issue.location == "models[0].protocol" for issue in caught.value.issues)


def test_model_with_protocol_is_accepted():
    facade = ProviderFacade()
    assertion = facade.store_document(_document())
    assert assertion >= 1
    view = facade.providers_view()
    assert view["models"][0]["protocol"] == "responses"
    assert "protocol" not in view["providers"][0]


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
        "protocol": "responses",
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


def test_a_department_without_a_model_is_named_in_chinese_with_where_to_set_it():
    # 工单 #319 第 6 项：质检的部门默认没有选模型时，用户看到的是中文说明与两个去处，
    # 里面没有部门标识（quality）与英文的内部提示
    facade = ProviderFacade()
    facade.store_document(_document(bindings={
        "product": {"provider_id": "provider-a", "model_id": "model-a"},
        "engineering": {"provider_id": "provider-b", "model_id": "model-b"},
    }))
    readiness = facade.describe_readiness()
    assert readiness["available"] is False
    assert readiness["reason"] == "provider_unavailable"
    assert readiness["message"] == (
        "质检部门还没有选择模型，到系统的模型管理页设置部门默认，或在本项目的设置页为这个项目选择")
    assert "quality" not in readiness["message"]
    assert readiness["issues"] == [{"location": "bindings.quality", "message": "质检部门还没有选择模型"}]


def test_every_department_without_a_model_is_named_in_one_message():
    facade = ProviderFacade()
    facade.store_document(_document(bindings={}))
    readiness = facade.describe_readiness()
    assert readiness["available"] is False
    for name in ("产品", "工程", "质检"):
        assert f"{name}部门还没有选择模型" in readiness["message"]
    for identifier in ("product", "engineering", "quality"):
        assert identifier not in readiness["message"]


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


def test_preset_declares_the_default_protocol_and_the_auth_for_models_and_tests():
    # 服务方案预置表带默认协议与认证方式（设计说明第 4.1 节）：OpenCode Go 是 Chat Completions
    preset = next(item for item in DEFINITIONS.service_presets.presets if item.id == "opencode-go")
    assert preset.default_protocol == "chat_completions"
    assert preset.auth == "api_key"
    assert preset_default_protocol("opencode-go") == "chat_completions"
    assert preset_auth("opencode-go") == "api_key"
    # 自定义服务不在预置表里：取不到默认协议与认证方式，由调用方预填 Chat Completions
    assert preset_default_protocol("") == ""
    assert preset_auth("") == ""
    assert preset_default_protocol("custom") == ""


def test_candidate_prefill_carries_the_protocol_and_its_source():
    # 候选带预填的协议与来源（设计说明第 4.3 节）：能力表优先，其次是服务方案的默认协议
    known = _parse_candidates({"data": [{"id": "grok-4.7"}, {"id": "glm-5.3-flash"},
                                        {"id": "清单里没有的模型"}]}, "opencode-go")
    by_id = {item["id"]: item for item in known}
    assert by_id["grok-4.7"]["protocol"] == "responses"
    assert by_id["grok-4.7"]["protocol_source"] == "capability_table"
    assert by_id["glm-5.3-flash"]["protocol"] == "chat_completions"
    assert by_id["清单里没有的模型"]["protocol"] == "chat_completions"
    assert by_id["清单里没有的模型"]["protocol_source"] == "preset_default"
    # 自定义服务不在能力表里：预填 Chat Completions，来源 default
    custom = _parse_candidates({"data": [{"id": "任意模型"}]}, "")
    assert custom[0]["protocol"] == "chat_completions"
    assert custom[0]["protocol_source"] == "default"
    assert capabilities.capability("", "任意模型") is None
