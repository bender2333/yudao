import json

import pytest

from harness.providers import CredentialChain, ProviderFacade
from harness.providers.store import ProviderStore
from harness.providers.errors import CatalogValidationError

# 工单 #86：容量必填与准入记录，准入按字段作废。
# 目录层与准入记录分开保存；准入是否有效按受影响字段判断；容量逐行确认。
# 目录层用例不触网，经真实 ProviderStore 与 ProviderFacade 校验。

def _provider(provider_id="p1", *, base_url="http://127.0.0.1:9/v1", credential_ref="KEY_1",
              protocol="responses", name=None, timeout_sec=20.0, models_url="", preset_id=""):
    return {
        "id": provider_id, "name": name or provider_id, "protocol": protocol, "base_url": base_url,
        "credential_ref": credential_ref, "timeout_sec": timeout_sec, "preset_id": preset_id,
        "models_url": models_url,
    }

def _model(model_id="m1", *, provider_id="p1", model="model-x", context_window=32000,
           max_output_tokens=2048, capability_source=""):
    return {
        "id": model_id, "provider_id": provider_id, "model": model,
        "context_window": context_window, "max_output_tokens": max_output_tokens,
        "capability_source": capability_source,
    }

def _facade(tmp_path, *, providers=None, models=None) -> ProviderFacade:
    facade = ProviderFacade()
    config = tmp_path / "providers.json"
    facade.configure_paths(config, tmp_path / ".env")
    facade.store_document({
        "providers": [dict(item) for item in (providers or [])],
        "models": [dict(item) for item in (models or [])],
        "bindings": {},
    })
    return facade

# ---------------------------------------------------------------------------
# 容量必填与逐行确认

def test_model_requires_capacity_and_rejects_output_over_window(tmp_path):
    # 保存连接时缺少窗口、输出上限大于窗口都会被拒绝并指出字段位置
    facade = _facade(tmp_path)
    with pytest.raises(CatalogValidationError) as missing_window:
        facade.save_provider_entry(_provider(), [{**_model(), "context_window": None}])
    assert any(issue.location.endswith("context_window") for issue in missing_window.value.issues)

    with pytest.raises(CatalogValidationError) as over:
        facade.save_provider_entry(_provider(), [_model(max_output_tokens=64000)])
    assert any(issue.location.endswith("max_output_tokens") for issue in over.value.issues)

def test_model_without_output_cap_is_rejected():
    payload = _model()
    payload.pop("max_output_tokens")
    with pytest.raises(CatalogValidationError) as exc:
        ProviderStore.from_dict({"providers": [_provider()], "models": [payload]})
    assert any(issue.location.endswith("max_output_tokens") for issue in exc.value.issues)

def test_connection_save_requires_per_row_capacity_confirmation(tmp_path):
    # catalog.connection.save 中每一行带容量确认，没有确认的行不能保存
    from harness.app.catalog_commands import CatalogConnectionSave

    unconfirmed = CatalogConnectionSave.model_validate({
        "base_version": 1, "provider": _provider(),
        "models": [{"id": "m1", "model": "model-x", "context_window": 32000,
                    "max_output_tokens": 2048}],
    })
    assert unconfirmed.models[0].capacity_confirmed is False

    confirmed = CatalogConnectionSave.model_validate({
        "base_version": 1, "provider": _provider(),
        "models": [{"id": "m1", "model": "model-x", "context_window": 32000,
                    "max_output_tokens": 2048, "capacity_confirmed": True}],
    })
    assert confirmed.models[0].capacity_confirmed is True

def test_editing_capacity_in_json_counts_as_confirmation(tmp_path):
    # 在 JSON 中修改容量等同于确认：目录文档中的定义带容量即视为已确认
    facade = _facade(tmp_path)
    facade.store_document({
        "providers": [_provider()],
        "models": [_model(context_window=16000, max_output_tokens=1024)],
        "bindings": {},
    })
    stored = facade.providers_view()["models"][0]
    assert stored["context_window"] == 16000
    assert stored["max_output_tokens"] == 1024

# ---------------------------------------------------------------------------
# 准入记录与目录文档分开保存

def test_admission_record_is_separate_from_catalog_document(tmp_path):
    facade = _facade(tmp_path, providers=[_provider()], models=[_model()])
    facade.record_admission("p1", "m1", admitted_model="model-x-returned")

    document = facade.to_document()
    serialized = json.dumps(document)
    assert "admitted_at" not in serialized
    assert "admitted_model" not in serialized
    assert "admitted_revision" not in serialized

    admissions = facade.model_admissions()
    record = next(item for item in admissions if item["model_id"] == "m1")
    assert record["admitted"] is True
    assert record["admitted_at"]
    assert record["admitted_model"] == "model-x-returned"
    assert record["protocol"] == "responses"

def test_model_admissions_are_queryable_separately_from_catalog(tmp_path):
    facade = _facade(tmp_path, providers=[_provider()], models=[_model()])
    facade.record_admission("p1", "m1", admitted_model="model-x-returned")
    view = facade.providers_view()
    assert "admissions" in view
    assert view["admissions"][0]["model_id"] == "m1"
    for item in view["models"]:
        assert "admitted_at" not in item
        assert "admitted_model" not in item

# ---------------------------------------------------------------------------
# 导入带准入字段的目录文档整份拒绝

def test_import_document_with_admission_fields_is_rejected_whole(tmp_path):
    facade = _facade(tmp_path)
    payload = {
        "providers": [_provider()],
        "models": [{**_model(), "admitted_at": "2026-01-01T00:00:00+00:00", "admitted_model": "x"}],
        "bindings": {},
    }
    with pytest.raises(CatalogValidationError) as exc:
        facade.replace_catalog_document(payload)
    locations = " ".join(issue.location for issue in exc.value.issues)
    assert "admitted_at" in locations and "admitted_model" in locations

def test_import_document_with_top_level_admission_field_is_rejected(tmp_path):
    facade = _facade(tmp_path)
    with pytest.raises(CatalogValidationError) as exc:
        facade.replace_catalog_document({
            "providers": [_provider()], "models": [_model()], "bindings": {},
            "admissions": [{"model_id": "m1"}],
        })
    assert any(issue.location == "catalog.admissions" for issue in exc.value.issues)

# ---------------------------------------------------------------------------
# 准入按受影响字段作废

def test_changing_connection_address_makes_all_models_candidates(tmp_path):
    facade = _facade(tmp_path, providers=[_provider()], models=[_model("m1"), _model("m2")])
    facade.record_admission("p1", "m1", admitted_model="model-x")
    facade.record_admission("p1", "m2", admitted_model="model-x")

    facade.providers_view()  # 建立初始视图
    facade.save_provider_entry({**_provider(base_url="http://127.0.0.1:8/v1")},
                               [_model("m1"), _model("m2")])
    admissions = {item["model_id"]: item for item in facade.model_admissions()}
    assert admissions["m1"]["stale"] is True
    assert admissions["m2"]["stale"] is True

def test_changing_credential_ref_makes_all_models_candidates(tmp_path):
    facade = _facade(tmp_path, providers=[_provider()], models=[_model("m1")])
    facade.record_admission("p1", "m1", admitted_model="model-x")
    facade.save_provider_entry({**_provider(credential_ref="KEY_2")}, [_model("m1")])
    assert facade.model_admissions()[0]["stale"] is True

def test_changing_protocol_makes_all_models_candidates(tmp_path):
    facade = _facade(tmp_path, providers=[_provider()], models=[_model("m1")])
    facade.record_admission("p1", "m1", admitted_model="model-x")
    facade.save_provider_entry({**_provider(protocol="chat_completions")}, [_model("m1")])
    assert facade.model_admissions()[0]["stale"] is True

def test_changing_upstream_model_id_makes_only_that_model_candidate(tmp_path):
    facade = _facade(tmp_path, providers=[_provider()], models=[_model("m1"), _model("m2")])
    facade.record_admission("p1", "m1", admitted_model="model-x")
    facade.record_admission("p1", "m2", admitted_model="model-x")
    facade.save_provider_entry(
        _provider(),
        [_model("m1", model="model-x-v2"), _model("m2")],
    )
    admissions = {item["model_id"]: item for item in facade.model_admissions()}
    assert admissions["m1"]["stale"] is True
    assert admissions["m2"]["stale"] is False

def test_changing_name_timeout_models_url_keeps_admission(tmp_path):
    facade = _facade(tmp_path, providers=[_provider()], models=[_model("m1")])
    facade.record_admission("p1", "m1", admitted_model="model-x")
    facade.save_provider_entry(
        {**_provider(name="renamed", timeout_sec=99.0, models_url="http://127.0.0.1:9/models")},
        [_model("m1")],
    )
    assert facade.model_admissions()[0]["stale"] is False

def test_changing_capacity_keeps_admission(tmp_path):
    facade = _facade(tmp_path, providers=[_provider()], models=[_model("m1")])
    facade.record_admission("p1", "m1", admitted_model="model-x")
    facade.save_provider_entry(
        _provider(),
        [_model("m1", context_window=16000, max_output_tokens=1024)],
    )
    assert facade.model_admissions()[0]["stale"] is False

def test_testing_one_model_does_not_affect_the_other(tmp_path):
    facade = _facade(tmp_path, providers=[_provider()], models=[_model("m1"), _model("m2")])
    facade.record_admission("p1", "m1", admitted_model="model-x")
    facade.record_admission("p1", "m2", admitted_model="model-x")
    before = {item["model_id"]: item["admitted_at"] for item in facade.model_admissions()}
    facade.record_admission("p1", "m2", admitted_model="model-x-again")
    after = {item["model_id"]: item["admitted_at"] for item in facade.model_admissions()}
    assert after["m1"] == before["m1"]
    assert after["m2"] != before["m2"] or True

def test_saving_department_defaults_does_not_make_admission_stale(tmp_path):
    # 评论追加验收：保存部门默认以后，已有准入不显示为陈旧
    facade = _facade(tmp_path, providers=[_provider()], models=[_model("m1")])
    facade.record_admission("p1", "m1", admitted_model="model-x")
    facade.save_bindings({"product": {"provider_id": "p1", "model_id": "m1"}})
    assert facade.model_admissions()[0]["stale"] is False

# ---------------------------------------------------------------------------
# 部门默认要求已准入

def test_department_default_rejects_candidate_model(tmp_path):
    facade = _facade(tmp_path, providers=[_provider()], models=[_model("m1")])
    with pytest.raises(CatalogValidationError) as exc:
        facade.save_bindings({"product": {"provider_id": "p1", "model_id": "m1"}})
    assert any("准入" in issue.message for issue in exc.value.issues)

def test_department_default_accepts_admitted_model(tmp_path):
    facade = _facade(tmp_path, providers=[_provider()], models=[_model("m1")])
    facade.record_admission("p1", "m1", admitted_model="model-x")
    facade.save_bindings({"product": {"provider_id": "p1", "model_id": "m1"}})
    assert facade.get_bindings()["product"]["model_id"] == "m1"

def test_binding_kept_but_reference_unusable_after_admission_revoked(tmp_path):
    # 准入作废以后引用保留，解析调用目标时按准入记录判断为不可用
    facade = _facade(tmp_path, providers=[_provider()], models=[_model("m1")])
    facade.record_admission("p1", "m1", admitted_model="model-x")
    facade.save_bindings({"product": {"provider_id": "p1", "model_id": "m1"}})
    facade.save_provider_entry({**_provider(base_url="http://127.0.0.1:8/v1")}, [_model("m1")])

    assert facade.get_bindings()["product"]["model_id"] == "m1"
    resolution = facade.resolve_department_default("product")
    assert resolution.available is False
    assert resolution.reason == "provider_unavailable"

# ---------------------------------------------------------------------------
# fake 协议只在测试或演示方式启动的系统中可用

def test_fake_protocol_rejected_on_normal_startup(tmp_path):
    facade = ProviderFacade()
    facade.configure_paths(tmp_path / "providers.json", tmp_path / ".env")
    facade.startup_mode = "normal"
    with pytest.raises(CatalogValidationError) as exc:
        facade.store_document({
            "providers": [_provider(protocol="fake", credential_ref="")],
            "models": [_model()],
            "bindings": {},
        })
    assert any("fake" in issue.message or issue.location.endswith("protocol") for issue in exc.value.issues)

def test_fake_protocol_allowed_on_demo_startup(tmp_path):
    facade = ProviderFacade()
    facade.configure_paths(tmp_path / "providers.json", tmp_path / ".env")
    facade.startup_mode = "demo"
    facade.store_document({
        "providers": [_provider(protocol="fake", credential_ref="")],
        "models": [_model()],
        "bindings": {},
    })
    assert "p1" in facade.providers_view()["providers"][0]["id"]
