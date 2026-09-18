import json
import threading
from contextlib import contextmanager
from http.client import HTTPConnection
from pathlib import Path

from harness.adapters.base import ModelResponse
from harness.models import DEPARTMENTS
from harness.provider_catalog import ProviderCatalog
from harness.runtime import LoopSystem
from harness.web.server import serve



def _catalog_document(provider_id="fake-a", model_id="model-a", *, protocol="fake", **provider_fields):
    provider = {
        "id": provider_id,
        "name": provider_fields.get("name", provider_id),
        "protocol": protocol,
        "base_url": provider_fields.get("base_url", ""),
        "credential_ref": provider_fields.get("credential_ref", ""),
        "timeout_sec": provider_fields.get("timeout_sec", 600),
    }
    if protocol == "fake":
        provider["base_url"] = ""
        provider["credential_ref"] = ""
    return {
        "providers": [provider],
        "models": [{
            "id": model_id,
            "provider_id": provider_id,
            "model": provider_fields.get("model", "fake-script"),
            "context_window": 32000,
            "max_output_tokens": 4096,
        }],
        "bindings": {
            department: {"provider_id": provider_id, "model_id": model_id}
            for department in DEPARTMENTS
        },
    }


def write_catalog(path: Path, document=None, **kwargs) -> Path:
    payload = _catalog_document(**kwargs) if document is None else document
    path.write_text(json.dumps(payload), encoding="utf-8")
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
def running_server(system, provider_config=None):
    server = serve(system, host="127.0.0.1", port=0, provider_config=provider_config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield server, host, port
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def catalog_system(tmp_path, document=None, *, credentials=None, **kwargs):
    config = write_catalog(tmp_path / "providers.json", document, **kwargs)
    catalog = ProviderCatalog.load(config)
    system = LoopSystem(
        tmp_path / "data",
        provider_catalog=catalog,
        credentials=credentials or {},
        provider_config_path=config,
    )
    return system, config


def test_provider_page_assets_are_served(tmp_path):
    system, config = catalog_system(tmp_path)
    with running_server(system, config) as (_server, host, port):
        html_status, html = request(host, port, "GET", "/")
        assert html_status == 200
        assert 'src="/static/provider-config.js"' in html
        js_status, js = request(host, port, "GET", "/static/provider-config.js")
        assert js_status == 200
        assert "模型与 Provider" in js
        assert "三部门绑定" in js
        css_status, css = request(host, port, "GET", "/static/styles.css")
        assert css_status == 200
        assert "yp-provider-row" in css
        assert "@media (max-width: 720px)" in css


def test_list_create_update_and_bindings_round_trip(tmp_path):
    system, config = catalog_system(tmp_path)
    with running_server(system, config) as (_server, host, port):
        listed = get_json(host, port, "/api/providers")
        assert listed["providers"][0]["id"] == "fake-a"
        assert listed["providers"][0]["credential_configured"] is True
        assert "models" in listed["providers"][0]
        secret_dump = json.dumps(listed)
        assert "api_key" not in secret_dump

        created = {
            "id": "fake-b",
            "name": "Second",
            "protocol": "fake",
            "models": [{
                "id": "model-b",
                "provider_id": "fake-b",
                "model": "other-script",
                "context_window": 16000,
                "max_output_tokens": 2048,
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
    system, config = catalog_system(tmp_path)
    with running_server(system, config) as (_server, host, port):
        status, body = request(host, port, "POST", "/api/providers", {
            "id": "bad id", "name": "Bad", "protocol": "responses",
            "base_url": "https://example.com/v1", "credential_ref": "KEY",
        })
        assert status == 400, body

        status, body = request(host, port, "POST", "/api/providers", {
            "id": "ok", "name": "BadUrl", "protocol": "responses",
            "base_url": "ftp://example.com", "credential_ref": "KEY",
        })
        assert status == 400, body

        status, body = request(host, port, "POST", "/api/providers", {
            "id": "ok", "name": "BadProto", "protocol": "openai",
        })
        assert status == 400, body
        assert "协议" in body

        status, body = request(host, port, "PUT", "/api/providers/fake-a", {
            "name": "Still fake", "protocol": "fake",
            "models": [{
                "id": "model-a", "provider_id": "fake-a", "model": "fake-script",
                "context_window": 0, "max_output_tokens": 4096,
            }],
        })
        assert status == 400, body

        status, body = request(host, port, "DELETE", "/api/providers/fake-a")
        assert status == 409, body
        payload = json.loads(body)
        assert payload["reason"] == "in_use"
        assert any(item.startswith("bindings.") for item in payload["dependents"])
        assert json.loads(config.read_text(encoding="utf-8"))["providers"][0]["id"] == "fake-a"

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
    with running_server(system, config) as (_server, host, port):
        status, body = request(host, port, "POST", "/api/providers", {
            "providers": [], "models": [], "bindings": {},
        })
        assert status == 400, body
        assert system.provider_catalog.providers["fake-a"].id == "fake-a"
        assert config.read_text(encoding="utf-8") == before

        replacement = _catalog_document("fake-z", "model-z")
        status, body = request(host, port, "POST", "/api/providers", replacement)
        assert status == 200, body
        listed = json.loads(body)
        assert listed["providers"][0]["id"] == "fake-z"
        saved = json.loads(config.read_text(encoding="utf-8"))
        assert saved["providers"][0]["id"] == "fake-z"


def test_fake_test_connection_skips_network(tmp_path):
    system, config = catalog_system(tmp_path)
    with running_server(system, config) as (_server, host, port):
        status, body = request(host, port, "POST", "/api/providers/fake-a/test")
        assert status == 200, body
        payload = json.loads(body)
        assert payload["ok"] is True
        assert payload["actual_model"] == "fake-script"
        assert isinstance(payload["elapsed_ms"], int)
        assert set(payload) == {"ok", "error", "actual_model", "elapsed_ms"}



def test_test_connection_redacts_secrets_and_reports_missing_credential(tmp_path, monkeypatch):
    secret = "super-secret-test-key"
    document = _catalog_document(
        "resp-a", "model-a", protocol="responses",
        base_url="https://provider.example/v1", credential_ref="YUDAO_TEST_KEY",
        model="listed-model",
    )
    system, config = catalog_system(tmp_path, document, credentials={"YUDAO_TEST_KEY": secret})

    def fake_complete(self, request):
        assert secret not in json.dumps(request.input_items)
        return ModelResponse(model="actual-from-provider")

    monkeypatch.setattr("harness.adapters.responses.ResponsesAdapter.complete", fake_complete)
    with running_server(system, config) as (_server, host, port):
        listed = get_json(host, port, "/api/providers")
        assert secret not in json.dumps(listed)
        assert listed["providers"][0]["credential_configured"] is True
        status, body = request(host, port, "POST", "/api/providers/resp-a/test")
        assert status == 200, body
        payload = json.loads(body)
        assert payload["ok"] is True
        assert payload["actual_model"] == "actual-from-provider"
        assert secret not in body

    system.credentials = {}
    with running_server(system, config) as (_server, host, port):
        status, body = request(host, port, "POST", "/api/providers/resp-a/test")
        assert status == 200, body
        payload = json.loads(body)
        assert payload["ok"] is False
        assert "YUDAO_TEST_KEY" in payload["error"]
        assert secret not in body


def test_replacing_catalog_does_not_mutate_frozen_run(tmp_path):
    system, config = catalog_system(tmp_path, provider_id="fake-a", model_id="model-a")
    run_id = system.create_run("keep frozen snapshot")
    before = system.project(run_id).provider_bindings
    assert before["product"]["provider_id"] == "fake-a"
    with running_server(system, config) as (_server, host, port):
        status, body = request(host, port, "POST", "/api/providers", _catalog_document("fake-z", "model-z"))
        assert status == 200, body
        assert system.provider_catalog.providers["fake-z"].id == "fake-z"
    after = system.project(run_id).provider_bindings
    assert after == before
    assert after["product"]["provider_id"] == "fake-a"


def test_work_item_503_names_missing_credential(tmp_path):
    document = _catalog_document(
        "resp-a", "model-a", protocol="responses",
        base_url="https://provider.example/v1", credential_ref="YUDAO_MISSING_KEY",
    )
    system, config = catalog_system(tmp_path, document, credentials={})
    with running_server(system, config) as (_server, host, port):
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
    original = system.provider_catalog

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("harness.web.server.os.replace", boom)
    with running_server(system, config) as (_server, host, port):
        status, body = request(host, port, "POST", "/api/providers", {
            "id": "spare", "name": "Spare", "protocol": "fake",
        })
        assert status == 503, body
        assert system.provider_catalog is original
        assert "fake-a" in system.provider_catalog.providers


def test_console_topbar_source_keeps_provider_entry_out_of_project_settings():
    app = (Path(__file__).resolve().parents[1] / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'data-action="providers"' in app
    assert "模型与 Provider" in app
    settings_start = app.index("function settingsMarkup")
    settings = app[settings_start:app.index("function overviewComposer")]
    assert "模型与 Provider" not in settings
