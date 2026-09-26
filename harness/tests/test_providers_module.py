from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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
    to_provider_input,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


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


class _LocalResponsesUpstream:
    # 本地 Responses 上游：普通请求立即完成；输入为 hold 的请求挂起，直到测试放行
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.held = Event()
        self.release = Event()
        upstream = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                return

            def do_POST(self) -> None:
                length = int(self.headers.get("content-length") or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                upstream.requests.append(body)
                if body["input"][-1]["content"] == "hold":
                    upstream.held.set()
                    upstream.release.wait(10)
                item = {"id": "msg-1", "type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": "ok"}]}
                frames = [
                    ("response.output_item.done", {"type": "response.output_item.done", "item": item}),
                    ("response.completed", {"type": "response.completed", "response": {
                        "id": "resp-1", "model": body["model"], "status": "completed", "output": [item],
                        "usage": {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4}}}),
                ]
                payload = "".join(f"event: {kind}\ndata: {json.dumps(data)}\n\n" for kind, data in frames)
                try:
                    self.send_response(200)
                    self.send_header("content-type", "text/event-stream")
                    self.end_headers()
                    self.wfile.write(payload.encode("utf-8"))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def close(self) -> None:
        self.release.set()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def test_provider_module_imports_without_web_or_department_kernel():
    # 独立模块：导入 Provider 模块只加载模块自身，不加载 Web、编排器与部门内核
    script = ("import json, sys; import harness.providers; "
              "print(json.dumps(sorted(name for name in sys.modules if name.startswith('harness'))))")
    completed = subprocess.run([sys.executable, "-c", script], cwd=REPO_ROOT,
                               capture_output=True, text=True, check=True)
    loaded = json.loads(completed.stdout)
    assert "harness.providers.facade" in loaded
    assert [name for name in loaded if name != "harness" and not name.startswith("harness.providers")] == []


def test_standalone_host_reads_config_resolves_invokes_and_cancels(tmp_path):
    # 独立宿主：读取配置文件、解析并冻结目标、完成一次调用、取消一次进行中的调用
    upstream = _LocalResponsesUpstream()
    try:
        config = tmp_path / "providers.json"
        config.write_text(json.dumps({
            "providers": [{"id": "p1", "name": "本地服务", "base_url": upstream.base_url,
                           "credential_ref": "LOCAL_REF", "timeout_sec": 10.0}],
            "models": [{"id": "m1", "provider_id": "p1", "model": "model-a", "protocol": "responses",
                        "context_window": 8000, "max_output_tokens": 256}],
            "bindings": {},
        }, ensure_ascii=False), encoding="utf-8")
        facade = ProviderFacade(credentials=CredentialChain(overrides={"LOCAL_REF": "local-secret"},
                                                            use_env=False))
        facade.load_document(config)
        frozen = facade.resolve_snapshot([{"key": "k", "provider_id": "p1", "model_id": "m1"}]).target("k")
        assert frozen.model == "model-a"
        observer = _RecordingObserver()
        result = facade.invoke_once(frozen, to_provider_input([{"role": "user", "content": "hi"}]),
                                    session_id="host-session", attempt_id="attempt-1", observer=observer)
        assert result.text == "ok"
        assert result.actual_model == "model-a"
        assert observer.confirms[0]["attempt_id"] == "attempt-1"
        assert upstream.requests[0]["model"] == "model-a"

        outcome: dict[str, str] = {}

        def held_call() -> None:
            try:
                facade.invoke_once(frozen, to_provider_input([{"role": "user", "content": "hold"}]),
                                   session_id="host-session", attempt_id="attempt-2")
            except ProviderError as exc:
                outcome["reason"] = exc.reason

        worker = threading.Thread(target=held_call)
        worker.start()
        assert upstream.held.wait(5)
        assert facade.cancel("attempt-other") is False
        assert facade.cancel("attempt-2") is True
        worker.join(5)
        assert not worker.is_alive()
        assert outcome == {"reason": "cancelled"}
    finally:
        upstream.close()
