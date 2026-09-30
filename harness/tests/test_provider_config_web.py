from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.client import HTTPConnection
from pathlib import Path

from harness.models import DEPARTMENTS
from harness.providers import ProviderFacade
from harness.runtime import LoopSystem
from harness.web.server import serve

# OpenCode Go 连接的凭据：获取模型列表与连接测试都按协议带上它（#85）
GO_SECRET = "go-catalog-secret"


def _model_document(model_id, provider_id, *, model="fake-script",
                    context_window=32000, max_output_tokens=4096):
    return {
        "id": model_id,
        "provider_id": provider_id,
        "model": model,
        "context_window": context_window,
        "max_output_tokens": max_output_tokens,
    }


def _catalog_document(provider_id="fake-a", model_id="model-a", *, protocol="fake", **provider_fields):
    provider = {
        "id": provider_id,
        "name": provider_fields.get("name", provider_id),
        "protocol": protocol,
        "base_url": provider_fields.get("base_url", ""),
        "credential_ref": provider_fields.get("credential_ref", ""),
        "timeout_sec": provider_fields.get("timeout_sec", 600),
        "models_url": provider_fields.get("models_url", ""),
    }
    return {
        "providers": [provider],
        "models": [_model_document(
            model_id, provider_id,
            model=provider_fields.get("model", "fake-script"))],
        "bindings": {
            department: {"provider_id": provider_id, "model_id": model_id}
            for department in DEPARTMENTS
        },
    }


def write_document(path: Path, document) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def request(host, port, method, path, body=None, timeout=15):
    conn = HTTPConnection(host, port, timeout=timeout)
    headers = {}
    payload = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(payload))
    conn.request(method, path, payload, headers)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data.decode("utf-8")


def get_json(host, port, path):
    status, body = request(host, port, "GET", path)
    assert status == 200, body
    return json.loads(body)


@contextmanager
def running_server(system):
    server = serve(system, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield server, host, port
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def catalog_system(tmp_path, document=None, *, credentials=None, dotenv=None, **kwargs):
    config = tmp_path / "providers.json"
    payload = _catalog_document(**kwargs) if document is None else document
    write_document(config, payload)
    facade = ProviderFacade(startup_mode="test")
    dotenv_path = tmp_path / ".env" if dotenv is not None else None
    if dotenv is not None:
        dotenv_path.write_text(dotenv, encoding="utf-8")
    facade.configure_paths(config, dotenv_path)
    facade.reload()
    for ref, secret in (credentials or {}).items():
        facade.set_credential_override(ref, secret)
    _admit_bound_models(facade)
    system = LoopSystem(tmp_path / "data", facade=facade)
    return system, config


def _admit_bound_models(facade):
    # 真实协议模型须先经模型测试准入；测试通过模块接口记录该事实
    view = facade.providers_view()
    models = {item["id"]: item for item in view["models"]}
    protocols = {item["id"]: item["protocol"] for item in view["providers"]}
    for binding in view["bindings"].values():
        model = models.get(binding.get("model_id"))
        if model is not None and protocols.get(binding.get("provider_id")) != "fake":
            facade.record_admission(binding["provider_id"], model["id"],
                                    admitted_model=model["model"])


def test_provider_page_assets_are_served(tmp_path):
    system, _config = catalog_system(tmp_path)
    with running_server(system) as (_server, host, port):
        html_status, html = request(host, port, "GET", "/")
        assert html_status == 200
        assert 'src="/static/provider-config.js"' in html
        js_status, js = request(host, port, "GET", "/static/provider-config.js")
        assert js_status == 200
        assert "模型与 Provider" in js
        assert "三部门绑定" in js
        assert "/api/provider-credentials" in js
        css_status, css = request(host, port, "GET", "/static/styles.css")
        assert css_status == 200
        assert "yp-provider-row" in css
        assert "@media (max-width: 720px)" in css


def test_list_create_update_and_bindings_round_trip(tmp_path):
    system, config = catalog_system(tmp_path)
    with running_server(system) as (_server, host, port):
        listed = get_json(host, port, "/api/providers")
        assert listed["providers"][0]["id"] == "fake-a"
        assert listed["providers"][0]["credential_configured"] is True
        assert "models" in listed["providers"][0]
        assert listed["revision"] >= 1
        secret_dump = json.dumps(listed)
        assert "api_key" not in secret_dump

        created = {
            "id": "fake-b",
            "name": "Second",
            "protocol": "fake",
            "models": [{
                "id": "model-b",
                "model": "other-script",
                "context_window": 16000,
                "max_output_tokens": 2048,
                "capacity_confirmed": True,
            }],
        }
        status, body = request(host, port, "POST", "/api/providers", created)
        assert status == 201, body
        payload = json.loads(body)
        assert any(item["id"] == "fake-b" for item in payload["providers"])

        status, body = request(host, port, "PUT", "/api/providers/fake-b", {
            "name": "Second renamed",
            "protocol": "fake",
            "timeout_sec": 30,
            "models": created["models"],
        })
        assert status == 200, body
        assert json.loads(body)["providers"]
        renamed = next(item for item in json.loads(body)["providers"] if item["id"] == "fake-b")
        assert renamed["name"] == "Second renamed"
        assert renamed["timeout_sec"] == 30

        bindings = {
            "product": {"provider_id": "fake-b", "model_id": "model-b"},
            "engineering": {"provider_id": "fake-a", "model_id": "model-a"},
            "quality": {"provider_id": "fake-a", "model_id": "model-a"},
        }
        status, body = request(host, port, "PUT", "/api/department-bindings", bindings)
        assert status == 200, body
        current = get_json(host, port, "/api/department-bindings")
        assert current["bindings"]["product"]["provider_id"] == "fake-b"
        assert current["bindings"]["product"]["context_window"] == 16000
        saved = json.loads(config.read_text(encoding="utf-8"))
        assert saved["bindings"]["product"]["provider_id"] == "fake-b"


def test_validation_and_delete_dependents(tmp_path):
    system, _config = catalog_system(tmp_path)
    with running_server(system) as (_server, host, port):
        status, body = request(host, port, "POST", "/api/providers", {
            "id": "bad id", "name": "Bad",
            "base_url": "https://example.com/v1", "credential_ref": "KEY",
        })
        assert status == 400, body

        status, body = request(host, port, "POST", "/api/providers", {
            "id": "ok", "name": "BadUrl",
            "base_url": "ftp://example.com", "credential_ref": "KEY",
        })
        assert status == 400, body

        status, body = request(host, port, "POST", "/api/providers", {
            "id": "ok", "name": "BadProto", "protocol": "grpc",
        })
        assert status == 400, body
        assert "protocol" in body

        # 模型访问定义不再声明协议（ADR-0004）：拒绝并指出字段位置
        status, body = request(host, port, "POST", "/api/providers", {
            "id": "ok2", "name": "ModelProto", "protocol": "responses",
            "models": [{
                "id": "model-x", "model": "m", "protocol": "responses",
                "context_window": 8000, "max_output_tokens": 4096,
            }],
        })
        assert status == 400, body
        assert "models[1].protocol" in body

        status, body = request(host, port, "PUT", "/api/providers/fake-a", {
            "name": "Still fake",
            "models": [{
                "id": "model-a", "model": "fake-script",
                "context_window": 0, "max_output_tokens": 4096,
            }],
        })
        assert status == 400, body

        status, body = request(host, port, "DELETE", "/api/providers/fake-a")
        assert status == 409, body
        payload = json.loads(body)
        assert payload["reason"] == "in_use"
        assert any(item.startswith("bindings.") for item in payload["dependents"])

        extra = {
            "id": "spare",
            "name": "Spare",
            "protocol": "fake",
        }
        status, body = request(host, port, "POST", "/api/providers", extra)
        assert status == 201, body
        status, body = request(host, port, "DELETE", "/api/providers/spare")
        assert status == 200, body
        remaining = get_json(host, port, "/api/providers")
        assert all(item["id"] != "spare" for item in remaining["providers"])


def test_import_keeps_old_catalog_on_invalid_document(tmp_path):
    system, config = catalog_system(tmp_path)
    before = config.read_text(encoding="utf-8")
    with running_server(system) as (_server, host, port):
        status, body = request(host, port, "POST", "/api/providers", {
            "providers": [{"id": "bad id", "name": "Bad"}],
            "models": [],
            "bindings": {},
        })
        assert status == 400, body
        assert "fake-a" in system.facade.providers_view()["providers"][0]["id"]
        assert config.read_text(encoding="utf-8") == before

        replacement = _catalog_document("fake-z", "model-z")
        status, body = request(host, port, "POST", "/api/providers", replacement)
        assert status == 200, body
        listed = json.loads(body)
        assert listed["providers"][0]["id"] == "fake-z"
        saved = json.loads(config.read_text(encoding="utf-8"))
        assert saved["providers"][0]["id"] == "fake-z"

        empty = {"providers": [], "models": [], "bindings": {}}
        status, body = request(host, port, "POST", "/api/providers", empty)
        assert status == 200, body
        assert json.loads(body)["providers"] == []
        health = get_json(host, port, "/api/health")
        assert health["provider_available"] is False


def test_moving_a_model_to_another_connection_keeps_one_owner_and_moves_bindings(tmp_path):
    def provider(provider_id):
        return {"id": provider_id, "name": provider_id, "protocol": "fake",
                "base_url": "", "credential_ref": "", "timeout_sec": 600}

    def bindings(provider_id):
        return {department: {"provider_id": provider_id, "model_id": "model-a"} for department in DEPARTMENTS}

    document = {
        "providers": [provider("fake-a"), provider("fake-b")],
        "models": [_model_document("model-a", "fake-a")],
        "bindings": bindings("fake-a"),
    }
    system, config = catalog_system(tmp_path, document)
    before = config.read_text(encoding="utf-8")
    with running_server(system) as (_server, host, port):
        # 只换归属而绑定仍指向旧归属：整份拒绝并指出绑定位置，原目录不变
        status, body = request(host, port, "POST", "/api/providers", {
            **document, "models": [_model_document("model-a", "fake-b")]})
        assert status == 400, body
        assert "bindings.product" in body
        assert config.read_text(encoding="utf-8") == before
        # 同名模型同时留在新旧两个归属：整份拒绝
        status, body = request(host, port, "POST", "/api/providers", {
            **document, "models": [_model_document("model-a", "fake-a"), _model_document("model-a", "fake-b")]})
        assert status == 400, body
        assert config.read_text(encoding="utf-8") == before
        # 移动：模型换到新归属，部门绑定跟随
        status, body = request(host, port, "POST", "/api/providers", {
            **document, "models": [_model_document("model-a", "fake-b")], "bindings": bindings("fake-b")})
        assert status == 200, body
        listed = get_json(host, port, "/api/providers")
    owners = {item["id"]: [model["id"] for model in item["models"]] for item in listed["providers"]}
    assert owners == {"fake-a": [], "fake-b": ["model-a"]}
    assert {binding["provider_id"] for binding in listed["bindings"].values()} == {"fake-b"}
    saved = json.loads(config.read_text(encoding="utf-8"))
    assert [(model["id"], model["provider_id"]) for model in saved["models"]] == [("model-a", "fake-b")]


def test_fake_test_connection_skips_network(tmp_path):
    system, _config = catalog_system(tmp_path)
    with running_server(system) as (_server, host, port):
        status, body = request(host, port, "POST", "/api/providers/fake-a/test")
        assert status == 200, body
        payload = json.loads(body)
        assert payload["ok"] is True
        assert payload["actual_model"] == "fake-script"
        assert isinstance(payload["elapsed_ms"], int)
        assert set(payload) == {"ok", "error", "actual_model", "elapsed_ms", "revision", "admitted", "protocol"}


def test_test_connection_reports_missing_credential_without_secrets(tmp_path):
    secret = "super-secret-test-key"
    # 连接测试读取模型列表地址：给出一份真实的上游，凭据缺失与凭据可用都能真实到达上游（#85）
    with models_server({"data": [{"id": "listed-model"}]}) as models_url:
        document = _catalog_document(
            "resp-a", "model-a", protocol="responses",
            base_url="https://provider.example/v1", credential_ref="YUDAO_TEST_KEY",
            model="listed-model", models_url=models_url,
        )
        system, _config = catalog_system(tmp_path, document)
        with running_server(system) as (_server, host, port):
            listed = get_json(host, port, "/api/providers")
            assert secret not in json.dumps(listed)
            assert listed["providers"][0]["credential_configured"] is False
            status, body = request(host, port, "POST", "/api/providers/resp-a/test")
            assert status == 200, body
            payload = json.loads(body)
            assert payload["ok"] is False
            assert "YUDAO_TEST_KEY" in payload["error"]
            assert secret not in body

            status, body = request(host, port, "POST", "/api/provider-credentials", {
                "ref": "YUDAO_TEST_KEY", "action": "set", "secret": secret,
            })
            assert status == 200, body
            assert secret not in body
            listed = get_json(host, port, "/api/providers")
            assert listed["providers"][0]["credential_configured"] is True
            status, body = request(host, port, "POST", "/api/providers/resp-a/test")
            assert status == 200, body
            payload = json.loads(body)
            # 该上游不校验凭据，配置凭据以后请求到达上游即通过
            assert payload["ok"] is True
            assert payload["actual_model"] == "listed-model"
            assert secret not in body


def test_replacing_catalog_only_affects_the_next_request(tmp_path):
    system, _config = catalog_system(tmp_path, provider_id="fake-a", model_id="model-a")
    run_id = system.create_run("resolve the call target per request")
    # 创建事项不再解析调用目标：还没有发出请求时没有绑定
    assert system.project(run_id).provider_bindings == {}
    system.activate_once(run_id)
    before = system.project(run_id).provider_bindings
    assert before["product"]["provider_config_id"] == "fake-a"
    with running_server(system) as (_server, host, port):
        status, body = request(host, port, "POST", "/api/providers", _catalog_document("fake-z", "model-z"))
        assert status == 200, body
        assert system.facade.providers_view()["providers"][0]["id"] == "fake-z"
    # 已经发出的请求记录不因目录替换改变；下一次解析按替换以后的目录
    assert system.project(run_id).provider_bindings == before
    resolved = system.facade.resolve_department_default("product")
    try:
        assert resolved.available is True
        assert resolved.public["provider_config_id"] == "fake-z"
    finally:
        system.facade.release_call_handle(resolved.handle_id)


def test_work_item_503_names_missing_credential(tmp_path):
    document = _catalog_document(
        "resp-a", "model-a", protocol="responses",
        base_url="https://provider.example/v1", credential_ref="YUDAO_MISSING_KEY",
    )
    system, _config = catalog_system(tmp_path, document)
    with running_server(system) as (_server, host, port):
        status, body = request(host, port, "POST", "/api/projects", {"name": "p", "goal": "g"})
        assert status == 201, body
        project_id = json.loads(body)["project_id"]
        status, body = request(host, port, "POST", f"/api/projects/{project_id}/work-items", {"text": "do work"})
        assert status == 503, body
        payload = json.loads(body)
        assert payload.get("reason") == "provider_unavailable"
        assert "YUDAO_MISSING_KEY" in payload["error"]
        assert "product" in payload["error"]


def test_unwritable_catalog_keeps_old_directory(tmp_path, monkeypatch):
    system, config = catalog_system(tmp_path)
    before = config.read_text(encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("harness.providers.facade.os.replace", boom)
    with running_server(system) as (_server, host, port):
        status, body = request(host, port, "POST", "/api/providers", {
            "id": "spare", "name": "Spare", "protocol": "fake",
        })
        assert status == 503, body
        assert all(item["id"] != "spare"
                   for item in system.facade.providers_view()["providers"])
        assert "fake-a" in [item["id"] for item in system.facade.providers_view()["providers"]]
        assert config.read_text(encoding="utf-8") == before


def test_credentials_memory_and_persisted_lifecycle(tmp_path):
    secret = "persisted-secret-value"
    document = _catalog_document(
        "resp-a", "model-a", protocol="responses",
        base_url="https://provider.example/v1", credential_ref="YUDAO_LIFE_KEY",
        model="listed-model",
    )
    dotenv_path = tmp_path / ".env"
    system, _config = catalog_system(tmp_path, document, dotenv="")
    with running_server(system) as (_server, host, port):
        status, body = request(host, port, "POST", "/api/provider-credentials", {
            "ref": "YUDAO_LIFE_KEY", "action": "set", "secret": secret,
        })
        assert status == 200, body
        payload = json.loads(body)
        assert payload["credential"]["source"] == "override"
        assert secret not in body
        health = get_json(host, port, "/api/health")
        assert health["provider_available"] is True

        status, body = request(host, port, "POST", "/api/provider-credentials", {
            "ref": "YUDAO_LIFE_KEY", "action": "set", "secret": secret, "persist": True,
        })
        assert status == 200, body
        assert dotenv_path.read_text(encoding="utf-8") == "YUDAO_LIFE_KEY=persisted-secret-value\n"

        status, body = request(host, port, "POST", "/api/provider-credentials", {
            "ref": "YUDAO_LIFE_KEY", "action": "clear_override",
        })
        assert status == 200, body
        payload = json.loads(body)
        assert payload["credential"]["source"] == "dotenv"
        health = get_json(host, port, "/api/health")
        assert health["provider_available"] is True

        status, body = request(host, port, "POST", "/api/provider-credentials", {
            "ref": "YUDAO_LIFE_KEY", "action": "remove_persisted",
        })
        assert status == 200, body
        assert "YUDAO_LIFE_KEY" not in dotenv_path.read_text(encoding="utf-8")
        health = get_json(host, port, "/api/health")
        assert health["provider_available"] is False

        status, body = request(host, port, "POST", "/api/provider-credentials", {
            "ref": "YUDAO_LIFE_KEY", "action": "set", "secret": "",
        })
        assert status == 400, body


def test_manual_reload_picks_up_disk_changes_and_reports_corruption(tmp_path):
    system, config = catalog_system(tmp_path)
    before_revision = system.facade.revision
    with running_server(system) as (_server, host, port):
        document = json.loads(config.read_text(encoding="utf-8"))
        document["models"].append(_model_document(
            "model-extra", "fake-a", model="extra-script"))
        config.write_text(json.dumps(document), encoding="utf-8")
        status, body = request(host, port, "POST", "/api/providers/reload")
        assert status == 200, body
        payload = json.loads(body)
        assert payload["ok"] is True
        assert payload["revision"] > before_revision
        listed = get_json(host, port, "/api/providers")
        assert any(item["id"] == "model-extra" for item in listed["models"])

        config.write_text("{ not json", encoding="utf-8")
        status, body = request(host, port, "POST", "/api/providers/reload")
        assert status == 200, body
        payload = json.loads(body)
        assert payload["ok"] is False
        assert payload["reload_error"]
        assert payload["revision"] == system.facade.revision
        listed = get_json(host, port, "/api/providers")
        assert any(item["id"] == "model-extra" for item in listed["models"])
        health = get_json(host, port, "/api/health")
        assert health["provider_reload_error"]
        assert health["provider_available"] is True


def test_health_reports_paths_revision_and_issues_without_secrets(tmp_path):
    secret = "health-secret-value"
    document = _catalog_document(
        "resp-a", "model-a", protocol="responses",
        base_url="https://provider.example/v1", credential_ref="YUDAO_HEALTH_KEY",
    )
    system, config = catalog_system(tmp_path, document,
                                    credentials={"YUDAO_HEALTH_KEY": secret})
    with running_server(system) as (_server, host, port):
        health = get_json(host, port, "/api/health")
        assert health["provider_config"] == str(config)
        assert health["provider_revision"] == system.facade.revision
        assert health["provider_reload_error"] is None
        assert health["provider_issues"] == []
        assert health["provider_available"] is True
        assert secret not in json.dumps(health)


def test_console_topbar_source_keeps_provider_entry_out_of_project_settings():
    app = (Path(__file__).resolve().parents[1] / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'data-action="providers"' in app
    assert "模型与 Provider" in app
    settings_start = app.index("function settingsMarkup")
    settings = app[settings_start:app.index("function overviewComposer")]
    assert "模型与 Provider" not in settings


@contextmanager
def models_server(payload, *, status=200):
    # 本地模型列表服务：真实 HTTP，不用桩替身
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    body = json.dumps(payload).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def do_GET(self):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/v1/models"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _go_document(models_url: str) -> dict:
    return {
        "providers": [{
            "id": "go", "name": "OpenCode Go", "protocol": "responses",
            "base_url": "https://opencode.ai/zen/go/v1",
            "credential_ref": "GO_KEY", "timeout_sec": 60, "preset_id": "opencode-go",
            "models_url": models_url,
        }],
        "models": [{
            "id": "go-luna", "provider_id": "go", "model": "gpt-5.6-luna",
            "context_window": 32000, "max_output_tokens": 2048,
            "capability_source": "preset-v1",
        }],
        "bindings": {},
    }


def test_provider_presets_endpoint_exposes_revision_and_go_endpoints(tmp_path):
    system, _config = catalog_system(tmp_path)
    with running_server(system) as (_server, host, port):
        payload = get_json(host, port, "/api/provider-presets")
    assert payload["revision"]
    assert payload["source"]
    preset = payload["presets"][0]
    assert preset["id"] == "opencode-go"
    assert preset["base_urls"] == {
        "responses": "https://opencode.ai/zen/go/v1",
        "chat_completions": "https://opencode.ai/zen/go/v1",
        "messages": "https://opencode.ai/zen/go/v1",
    }
    assert preset["models_url"].endswith("/zen/go/v1/models")
    assert preset["auth"] == "api_key"
    # 预置表只含接入规则，不带模型（#84）
    assert "known_models" not in preset
    assert "models" not in preset


def test_candidates_refresh_reads_models_url_without_persisting(tmp_path):
    upstream = models_server({"data": [{"id": "gpt-5.6-luna"}, {"id": "never-heard-of-it"}]})
    with upstream as models_url:
        # 获取模型列表按连接协议的认证方式带上凭据（#85）
        system, config = catalog_system(tmp_path, _go_document(models_url),
                                        credentials={"GO_KEY": GO_SECRET})
        before = config.read_text(encoding="utf-8")
        with running_server(system) as (_server, host, port):
            status, body = request(host, port, "POST", "/api/providers/go/candidates", {})
            assert status == 200, body
            payload = json.loads(body)
            listed = get_json(host, port, "/api/providers")
    assert payload["status"] == "ok"
    assert payload["source_url"] == models_url
    assert [item["id"] for item in payload["candidates"]] == ["gpt-5.6-luna", "never-heard-of-it"]
    # 候选只有上游模型 ID；协议与容量由访问定义与模型测试决定（#84）
    hint = next(item for item in payload["candidates"] if item["id"] == "gpt-5.6-luna")
    assert "protocol" not in hint
    assert "capability_source" not in hint
    # 候选不落盘、不自动成为可用模型
    assert config.read_text(encoding="utf-8") == before
    assert [item["id"] for item in listed["models"]] == ["go-luna"]


def test_candidates_report_unknown_when_upstream_unreachable(tmp_path):
    with models_server({"data": []}, status=500) as models_url:
        system, _config = catalog_system(tmp_path, _go_document(models_url))
        with running_server(system) as (_server, host, port):
            status, body = request(host, port, "POST", "/api/providers/go/candidates", {})
    assert status == 200, body
    payload = json.loads(body)
    assert payload["status"] == "unknown"
    assert payload["candidates"] == []
    assert payload["error"]


def test_model_test_records_admission_with_revision(tmp_path):
    system, config = catalog_system(tmp_path)
    with running_server(system) as (_server, host, port):
        before = get_json(host, port, "/api/providers")
        status, body = request(host, port, "POST", "/api/providers/fake-a/test",
                               {"model_id": "model-a", "kind": "model"})
        assert status == 200, body
        payload = json.loads(body)
        assert payload["ok"] is True
        assert payload["admitted"] is True
        assert payload["protocol"] == "fake"
        assert payload["revision"] > before["revision"]
        assert payload["persisted"] is True
        listed = get_json(host, port, "/api/providers")
        # 准入记录与目录分开返回（工单 #86）：目录定义上没有准入字段
        record = next(item for item in listed["admissions"] if item["model_id"] == "model-a")
        assert record["admitted"] is True
        assert record["admitted_at"]
        for model in listed["models"]:
            assert "admitted_at" not in model
            assert "admitted_revision" not in model

        # 准入结果落盘：独立进程（CLI/smoke）读取同一份准入文件也应看到准入
        reloaded = ProviderFacade(startup_mode="test")
        reloaded.configure_paths(config, None)
        reloaded.load_document(config)
        stored = next(item for item in reloaded.providers_view()["admissions"]
                      if item["model_id"] == "model-a")
        assert stored["admitted"] is True
        assert stored["admitted_at"] == record["admitted_at"]

        status, body = request(host, port, "POST", "/api/providers/fake-a/test",
                               {"kind": "model"})
        assert status == 400, body

        status, body = request(host, port, "POST", "/api/providers/fake-a/test",
                               {"model_id": "missing", "kind": "model"})
        assert status == 404, body


def test_unadmitted_real_model_blocks_task_readiness(tmp_path):
    document = _catalog_document(
        "resp-a", "model-a", protocol="responses",
        base_url="https://provider.example/v1", credential_ref="YUDAO_ADMIT_KEY",
    )
    system = ProviderFacade()
    system.store_document(document)
    system.set_credential_override("YUDAO_ADMIT_KEY", "secret")
    status = system.describe_readiness()
    assert status["available"] is False
    assert any("模型测试" in issue["message"] for issue in status["issues"])
    admitted = system.record_admission("resp-a", "model-a", admitted_model="listed-model")
    assert admitted["revision"] == system.revision
    assert admitted["admitted_model"] == "listed-model"
    assert system.describe_readiness()["available"] is True
