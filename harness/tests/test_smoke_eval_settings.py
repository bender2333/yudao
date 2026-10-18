"""smoke 没有给出 --provider-config 时，用 YUDAO_EVAL_* 三个环境变量建立 Provider 目录（工单 #593）。

连接测试与模型测试换成本地桩，不访问网络；凭据用假值，只检查它不出现在目录、报告与文件里。
"""

import json
from pathlib import Path

import pytest

import harness.smoke as smoke
from harness.providers import ProviderFacade
from harness.smoke import (EVAL_API_KEY_ENV, EVAL_BASE_URL_ENV, EVAL_ENV_NAMES, EVAL_MODEL_DEFINITION_ID,
                           EVAL_MODEL_ENV, EVAL_PROVIDER_ID, eval_catalog_document, run_smoke)

SECRET = "sk-fake-secret-value-for-test"
DEPARTMENTS = ("product", "engineering", "quality")


@pytest.fixture
def eval_env(monkeypatch):
    monkeypatch.setenv(EVAL_BASE_URL_ENV, "https://models.example/v1/")
    monkeypatch.setenv(EVAL_API_KEY_ENV, SECRET)
    monkeypatch.setenv(EVAL_MODEL_ENV, "fake/model-x")


@pytest.fixture
def no_eval_env(monkeypatch):
    for name in EVAL_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def stubbed_admission(monkeypatch):
    """连接测试与模型测试换成桩；模型测试通过时和真实实现一样写入准入记录。"""
    calls = []

    def test_connection(self, provider_id):
        calls.append(("connection", provider_id))
        return {"ok": True}

    def model_test(self, provider_id, model_id):
        calls.append(("model", provider_id, model_id))
        self.record_admission(provider_id, model_id, admitted_model="fake/model-x")
        return {"ok": True, "admitted": True, "error": None}

    monkeypatch.setattr(ProviderFacade, "test_connection", test_connection)
    monkeypatch.setattr(ProviderFacade, "model_test", model_test)
    monkeypatch.setattr(smoke, "_run_scenario", lambda system, name: {"scenario": name, "phase": "DONE"})
    return calls


def test_catalog_has_one_connection_one_model_and_three_bindings(eval_env):
    document = eval_catalog_document()
    assert [item["id"] for item in document["providers"]] == [EVAL_PROVIDER_ID]
    assert document["providers"][0]["base_url"] == "https://models.example/v1"
    assert document["models"][0]["protocol"] == "chat_completions"
    assert [item["id"] for item in document["models"]] == [EVAL_MODEL_DEFINITION_ID]
    assert document["models"][0]["model"] == "fake/model-x"
    assert set(document["bindings"]) == set(DEPARTMENTS)
    assert all(binding == {"provider_id": EVAL_PROVIDER_ID, "model_id": EVAL_MODEL_DEFINITION_ID}
               for binding in document["bindings"].values())


def test_catalog_holds_the_credential_only_as_a_reference(eval_env):
    document = eval_catalog_document()
    assert document["providers"][0]["credential_ref"] == EVAL_API_KEY_ENV
    assert SECRET not in json.dumps(document)


@pytest.mark.parametrize("missing", EVAL_ENV_NAMES)
def test_catalog_names_the_missing_variable(eval_env, monkeypatch, missing):
    monkeypatch.delenv(missing)
    with pytest.raises(ValueError, match=missing):
        eval_catalog_document()


def test_smoke_builds_the_catalog_from_the_variables(tmp_path, eval_env, stubbed_admission):
    data_dir = tmp_path / "smoke"
    report = run_smoke(data_dir, scenarios=["happy"], startup_mode="test")
    assert report["available"] is True, report
    assert report["provider_config"] == "环境变量"
    assert set(report["provider_bindings"]) == set(DEPARTMENTS)
    assert stubbed_admission == [("connection", EVAL_PROVIDER_ID),
                                 ("model", EVAL_PROVIDER_ID, EVAL_MODEL_DEFINITION_ID)]
    # 目录与准入只在内存里，数据目录里不出现目录文件，报告与文件里没有凭据取值
    assert not (data_dir / "providers.json").exists()
    for path in data_dir.rglob("*"):
        if path.is_file():
            assert SECRET not in path.read_text(encoding="utf-8", errors="ignore"), path
    assert SECRET not in json.dumps(report, ensure_ascii=False)


def test_smoke_stops_when_the_connection_test_fails(tmp_path, eval_env, stubbed_admission, monkeypatch):
    monkeypatch.setattr(ProviderFacade, "test_connection",
                        lambda self, provider_id: {"ok": False, "message": "unreachable"})
    report = run_smoke(tmp_path / "smoke", scenarios=["happy"], startup_mode="test")
    assert report["available"] is False
    assert "连接测试未通过" in report["error"] and "unreachable" in report["error"]
    assert report["scenarios"] == {}


def test_smoke_uses_the_given_catalog_file_even_with_the_variables(tmp_path, eval_env, stubbed_admission):
    config = tmp_path / "providers.json"
    config.write_text(json.dumps({
        "providers": [{"id": "fake-provider", "name": "Fake", "base_url": ""}],
        "models": [{"id": "fake-model", "provider_id": "fake-provider", "model": "fake-script",
                    "protocol": "fake", "context_window": 32_000, "max_output_tokens": 4_096}],
        "bindings": {department: {"provider_id": "fake-provider", "model_id": "fake-model"}
                     for department in DEPARTMENTS},
    }), encoding="utf-8")
    report = run_smoke(tmp_path / "smoke", provider_config=config, scenarios=["happy"], startup_mode="test")
    assert Path(report["provider_config"]) == config
    assert stubbed_admission == []
    assert report["available"] is True, report


def test_smoke_names_the_missing_variables_without_any_catalog(tmp_path, no_eval_env, monkeypatch):
    monkeypatch.setenv(EVAL_BASE_URL_ENV, "https://models.example/v1")
    report = run_smoke(tmp_path / "smoke", scenarios=["happy"])
    assert report["available"] is False
    assert report["stop_reason"] == "provider_config_missing"
    assert EVAL_API_KEY_ENV in report["error"] and EVAL_MODEL_ENV in report["error"]
    assert EVAL_BASE_URL_ENV not in report["error"]
