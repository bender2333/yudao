from __future__ import annotations

import dataclasses
import json
from threading import Event

import pytest

from harness.providers import (
    CatalogValidationError,
    CredentialChain,
    ProviderError,
    ProviderFacade,
    ProviderInput,
    ProviderMessage,
    ProviderStore,
)


def _catalog(credential_ref: str = "TEST_REF", protocol: str = "responses") -> dict:
    return {
        "providers": [{
            "id": "p1", "name": "服务一",
            "base_url": "https://api.example.com/v1",
            "credential_ref": credential_ref, "timeout_sec": 30.0,
        }],
        "models": [{
            "id": "m1", "provider_id": "p1", "model": "model-a",
            "protocol": protocol, "context_window": 8000,
            "max_output_tokens": 512, "capability_source": "preset-v1",
        }],
    }


def _fake_catalog() -> dict:
    return {
        "providers": [{"id": "pf", "name": "测试服务"}],
        "models": [{
            "id": "mf", "provider_id": "pf", "model": "fake-model",
            "protocol": "fake", "context_window": 8000,
            "max_output_tokens": 512, "capability_source": "test",
        }],
    }


class _RecordingObserver:
    def __init__(self, confirm: bool = True) -> None:
        self.confirm_result = confirm
        self.confirms: list[dict] = []
        self.events: list[dict] = []

    def confirm_request(self, evidence) -> bool:
        self.confirms.append(dict(evidence))
        return self.confirm_result

    def on_event(self, event) -> None:
        self.events.append(dict(event))


def test_facade_surface_usable():
    facade = ProviderFacade()
    for name in ("load", "store", "persist", "validate", "public_view",
                 "resolve_snapshot", "invoke_once", "cancel",
                 "test_connection", "model_test", "record_admission",
                 "presets_public_view", "refresh_candidates",
                 "describe_readiness", "providers_view"):
        assert callable(getattr(facade, name)), name


def test_structural_save_without_ready_credential(tmp_path):
    # 结构合法但未就绪可保存，落盘只含非敏感部分
    facade = ProviderFacade(credentials=CredentialChain(use_env=False))
    revision = facade.store(_catalog(credential_ref="MISSING_REF"))
    assert revision >= 1
    facade.validate()
    target_file = tmp_path / "providers.json"
    facade.persist(target_file)
    on_disk = json.loads(target_file.read_text(encoding="utf-8"))
    assert "api_key" not in json.dumps(on_disk)
    assert on_disk["providers"][0]["credential_ref"] == "MISSING_REF"


def test_old_provider_level_protocol_rejected():
    facade = ProviderFacade()
    bad = _catalog()
    bad["providers"][0]["protocol"] = "responses"
    with pytest.raises(CatalogValidationError) as exc_info:
        facade.store(bad)
    assert any("protocol" in issue.location for issue in exc_info.value.issues)


def test_frozen_snapshot_immutable():
    facade = ProviderFacade(credentials={"TEST_REF": "secret-a"})
    facade.store(_catalog())
    snapshot = facade.resolve_snapshot([{"key": "alpha", "provider_id": "p1", "model_id": "m1"}])
    frozen = snapshot.target("alpha")
    revision_before = snapshot.revision
    with pytest.raises(dataclasses.FrozenInstanceError):
        frozen.model = "other"  # type: ignore[misc]
    with pytest.raises(TypeError):
        snapshot.targets["alpha"] = frozen  # type: ignore[index]
    facade.set_credential_override("TEST_REF", "secret-b")
    facade.save_model({
        "id": "m2", "provider_id": "p1", "model": "model-b",
        "protocol": "responses", "context_window": 8000,
        "max_output_tokens": 256, "capability_source": "preset-v1",
    })
    assert snapshot.revision == revision_before
    assert snapshot.target("alpha").model == "model-a"


def test_missing_credentials_reported_per_item():
    facade = ProviderFacade(credentials=CredentialChain(use_env=False))
    facade.store({
        "providers": [
            {"id": "pa", "name": "服务甲", "base_url": "https://a.example.com",
             "credential_ref": "REF_A"},
            {"id": "pb", "name": "服务乙", "base_url": "https://b.example.com",
             "credential_ref": "REF_B"},
        ],
        "models": [
            {"id": "ma", "provider_id": "pa", "model": "model-a",
             "protocol": "responses", "context_window": 8000, "max_output_tokens": 128},
            {"id": "mb", "provider_id": "pb", "model": "model-b",
             "protocol": "responses", "context_window": 8000, "max_output_tokens": 128},
        ],
    })
    with pytest.raises(CatalogValidationError) as exc_info:
        facade.resolve_snapshot([
            {"key": "first", "provider_id": "pa", "model_id": "ma"},
            {"key": "second", "provider_id": "pb", "model_id": "mb"},
        ])
    locations = [issue.location for issue in exc_info.value.issues]
    assert len(exc_info.value.issues) == 2
    assert any("first" in location for location in locations)
    assert any("second" in location for location in locations)


def test_cancel_only_affects_current_attempt():
    facade = ProviderFacade()
    facade.store(_fake_catalog())
    snapshot = facade.resolve_snapshot([{"key": "k", "provider_id": "pf", "model_id": "mf"}])
    frozen = snapshot.target("k")
    event_a = Event()
    event_b = Event()
    observer = _RecordingObserver()
    assert facade.cancel("attempt-a") is False
    event_a.set()
    with pytest.raises(ProviderError) as exc_info:
        facade.invoke_once(
            frozen, ProviderInput(messages=(ProviderMessage(role="user", content="hi"),)),
            session_id="s1", attempt_id="attempt-a", abort_event=event_a, observer=observer,
        )
    assert exc_info.value.reason == "cancelled"
    assert not event_b.is_set()
    result = facade.invoke_once(
        frozen, ProviderInput(messages=(ProviderMessage(role="user", content="hi"),)),
        session_id="s1", attempt_id="attempt-b", abort_event=event_b, observer=observer,
    )
    assert result.finish_reason == "completed"
    assert result.text == "hi"


def test_unsupported_protocol_rejected_before_request():
    facade = ProviderFacade(credentials={"TEST_REF": "secret-a"})
    facade.store(_catalog(protocol="responses"))
    snapshot = facade.resolve_snapshot([{"key": "k", "provider_id": "p1", "model_id": "m1"}])
    # 未知协议直接构造冻结目标，验证请求前拒绝而不是落到网络调用
    frozen = dataclasses.replace(snapshot.target("k"), protocol="bogus")
    observer = _RecordingObserver()
    with pytest.raises(ProviderError) as exc_info:
        facade.invoke_once(
            frozen, ProviderInput(messages=(ProviderMessage(role="user", content="hi"),)),
            session_id="s1", attempt_id="a1", abort_event=Event(), observer=observer,
        )
    assert exc_info.value.reason == "unsupported_protocol"
    assert observer.confirms == []


def test_unpersisted_request_is_not_sent():
    facade = ProviderFacade()
    facade.store(_fake_catalog())
    snapshot = facade.resolve_snapshot([{"key": "k", "provider_id": "pf", "model_id": "mf"}])
    observer = _RecordingObserver(confirm=False)
    with pytest.raises(ProviderError) as exc_info:
        facade.invoke_once(
            snapshot.target("k"),
            ProviderInput(messages=(ProviderMessage(role="user", content="hi"),)),
            session_id="s1", attempt_id="a1", abort_event=Event(), observer=observer,
        )
    assert exc_info.value.reason == "request_not_persisted"
    assert observer.events == []


def test_secret_never_in_public_view_or_logs():
    secret = "super-secret-value-xyz"
    facade = ProviderFacade(credentials={"TEST_REF": secret})
    facade.store(_catalog())
    view = facade.public_view()
    assert secret not in json.dumps(view, ensure_ascii=False)
    snapshot = facade.resolve_snapshot([{"key": "k", "provider_id": "p1", "model_id": "m1"}])
    frozen = snapshot.target("k")
    assert secret not in repr(frozen)
    assert "api_key" not in frozen.public_dict()
    assert secret not in json.dumps(snapshot.public_dict(), ensure_ascii=False)
    assert secret not in json.dumps(ProviderStore.empty().public_view(), ensure_ascii=False)


def test_connection_and_model_tests_on_fake():
    facade = ProviderFacade()
    facade.store(_fake_catalog())
    connection = facade.test_connection({"key": "k", "provider_id": "pf", "model_id": "mf"})
    assert connection["ok"] is True
    assert connection["kind"] == "connection"
    model = facade.model_test("pf", "mf")
    assert model["ok"] is True
    assert model["admitted"] is True
    assert model["protocol"] == "fake"
    assert model["revision"] == facade.revision
    stored = next(item for item in facade.providers_view()["models"] if item["id"] == "mf")
    assert stored["admitted_revision"] == facade.revision
