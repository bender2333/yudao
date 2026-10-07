import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from harness.app.application import Application
from harness.models import CatalogEventType
from harness.tests.api_helpers import running_api
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

# 获取模型列表带凭据、连接测试对三种协议发送真实请求：
# 上游是测试内启动的真实 HTTP 服务，事件日志是真实 SQLite，不使用桩替身。

SECRET = "issue-85-secret-key"
REF = "ISSUE85_KEY"
UPSTREAM_BASE = "http://127.0.0.1:9/v1"


class _ModelsServer:
    # 真实的模型列表服务：要求认证才返回列表，并记录收到的请求头
    def __init__(self, payload=None, *, status=200) -> None:
        self.payload = payload if payload is not None else {"data": [{"id": "m1"}]}
        self.status = status
        self.requests: list[dict[str, str]] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def do_GET(self):
                headers = {key.lower(): value for key, value in self.headers.items()}
                server.requests.append(headers)
                authorized = (headers.get("authorization") == f"Bearer {SECRET}"
                              or headers.get("x-api-key") == SECRET)
                if not authorized:
                    self.send_response(401)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if server.status != 200:
                    self.send_response(server.status)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                body = json.dumps(server.payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}/models"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def __enter__(self):
        return self.base

    def __exit__(self, *_exc_info):
        self.server.shutdown()
        self.server.server_close()


class _Opened:
    def __init__(self, root, document) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.data_dir = root / "data"
        self.config = root / "providers.json"
        self.dotenv = root / ".env"
        self.dotenv.write_text(f"{REF}={SECRET}\n", encoding="utf-8")
        self.config.write_text(json.dumps(document), encoding="utf-8")
        self.applications: list[Application] = []

    def __call__(self) -> Application:
        application = Application.open(self.data_dir, provider_config=self.config, dotenv=self.dotenv)
        self.applications.append(application)
        return application

    @property
    def application(self) -> Application:
        return self.applications[-1]

    @property
    def store(self):
        return self.application.system.store


def _provider(provider_id="p1", *, protocol="responses", models_url="", preset_id=""):
    return {"id": provider_id, "name": provider_id, "protocol": protocol, "base_url": UPSTREAM_BASE,
            "credential_ref": REF, "timeout_sec": 20.0, "preset_id": preset_id, "models_url": models_url}


def _model(model_id="m1", provider_id="p1"):
    return {"id": model_id, "provider_id": provider_id, "model": "model-x",
            "context_window": 32000, "max_output_tokens": 2048, "capability_source": ""}


def _document(*, protocol="responses", models_url="", preset_id=""):
    return {"providers": [_provider(protocol=protocol, models_url=models_url, preset_id=preset_id)],
            "models": [_model()],
            "bindings": {}}


def _catalog(client):
    response = client.get("/api/queries/catalog")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _command(client, name, **body):
    return client.post(f"/api/commands/{name}", json={"command_id": str(uuid.uuid4()), **body})


def _catalog_events(store):
    return store.read(0, limit=100_000, types=[value for key, value in vars(CatalogEventType).items()
                                               if not key.startswith("_")])


def _wait_for(store, predicate, *, timeout=WAIT_FOR_HOST_WORK_SEC, description="catalog event"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        matched = [event for event in _catalog_events(store) if predicate(event)]
        if matched:
            return matched
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {description}")


def _set_credential(client, secret):
    # 换一个凭据：经命令写入，与界面改凭据走同一条路径
    version = _catalog(client)["providers"][0]["credential"]["version"]
    response = _command(client, "credential.set", base_version=version, ref=REF, secret=secret)
    assert response.status_code == 200, response.text
    return version + 1


def _assert_no_secret(client, opened, secret=SECRET):
    dumped = json.dumps([event.payload for event in _catalog_events(opened.store)], ensure_ascii=False)
    assert secret not in dumped
    for path in ("catalog", "catalog.document"):
        response = client.get(f"/api/queries/{path}")
        assert response.status_code == 200, response.text
        assert secret not in response.text


def test_collect_candidates_sends_the_credential_and_reports_source_and_time(tmp_path):
    server = _ModelsServer({"data": [{"id": "m1"}, {"id": "m9"}]})
    with server as models_url:
        opened = _Opened(tmp_path, _document(models_url=models_url))
        with running_api(opened) as client:
            current = _catalog(client)["revision"]
            collected = _command(client, "catalog.candidates.collect", base_version=current, provider_id="p1")
            assert collected.status_code == 200, collected.text
            [event] = _wait_for(opened.store, lambda item: item.type == CatalogEventType.CATALOG_CANDIDATES_COLLECTED,
                                description="catalog_candidates_collected")
            assert event.payload["status"] == "ok"
            assert set(event.payload["candidate_ids"]) == {"m1", "m9"}
            assert event.payload["source_url"] == models_url
            assert event.payload["fetched_at"]
            assert event.payload["error"] is None
            # 上游收到了凭据：Responses 协议用 Bearer
            assert server.requests
            assert server.requests[-1].get("authorization") == f"Bearer {SECRET}"
            _assert_no_secret(client, opened)


def test_collect_candidates_keeps_upstream_window_and_output_limit(tmp_path):
    payload = {"data": [{"id": "m1", "limit": {"context": 128000, "output": 8192}}, {"id": "m2"}]}
    server = _ModelsServer(payload)
    with server as models_url:
        opened = _Opened(tmp_path, _document(models_url=models_url))
        with running_api(opened) as client:
            current = _catalog(client)["revision"]
            collected = _command(client, "catalog.candidates.collect", base_version=current, provider_id="p1")
            assert collected.status_code == 200, collected.text
            [event] = _wait_for(opened.store, lambda item: item.type == CatalogEventType.CATALOG_CANDIDATES_COLLECTED,
                                description="catalog_candidates_collected")
            assert set(event.payload["candidate_ids"]) == {"m1", "m2"}
            # 预填值带来源（#146）：窗口与输出上限取上游模型列表，输入方式取能力表；
            # 这个连接的服务方案是自定义，能力表没有记录，输入方式预填为只有文本
            assert event.payload["candidates"][0] == {
                "id": "m1", "context_window": 128000, "context_window_source": "models_url",
                "max_output_tokens": 8192, "max_output_tokens_source": "models_url",
                "input_modalities": ["text"], "input_modalities_source": "default"}
            assert event.payload["candidates"][1] == {
                "id": "m2", "input_modalities": ["text"], "input_modalities_source": "default"}
            _assert_no_secret(client, opened)


def test_collect_candidates_is_unknown_when_upstream_rejects_the_credential(tmp_path):
    server = _ModelsServer()
    with server as models_url:
        opened = _Opened(tmp_path, _document(models_url=models_url))
        with running_api(opened) as client:
            _set_credential(client, "issue-85-wrong-key")
            current = _catalog(client)["revision"]
            collected = _command(client, "catalog.candidates.collect", base_version=current, provider_id="p1")
            assert collected.status_code == 200, collected.text
            [event] = _wait_for(opened.store, lambda item: item.type == CatalogEventType.CATALOG_CANDIDATES_COLLECTED,
                                description="catalog_candidates_collected")
            assert event.payload["status"] == "unknown"
            assert event.payload["candidate_ids"] == []
            assert event.payload["error"]
            # 上游不可用时不沿用上一次的结果
            assert event.payload["source_url"] == models_url
            _assert_no_secret(client, opened)


def test_collect_candidates_is_unknown_without_a_models_url(tmp_path):
    opened = _Opened(tmp_path, _document(models_url=""))
    with running_api(opened) as client:
        current = _catalog(client)["revision"]
        collected = _command(client, "catalog.candidates.collect", base_version=current, provider_id="p1")
        assert collected.status_code == 200, collected.text
        [event] = _wait_for(opened.store, lambda item: item.type == CatalogEventType.CATALOG_CANDIDATES_COLLECTED,
                            description="catalog_candidates_collected")
        assert event.payload["status"] == "unknown"
        assert event.payload["candidate_ids"] == []
        assert event.payload["error"]
        _assert_no_secret(client, opened)


def test_collect_candidates_rejects_an_unknown_connection(tmp_path):
    server = _ModelsServer()
    with server as models_url:
        opened = _Opened(tmp_path, _document(models_url=models_url))
        with running_api(opened) as client:
            current = _catalog(client)["revision"]
            collected = _command(client, "catalog.candidates.collect", base_version=current, provider_id="missing")
            assert collected.status_code == 409, collected.text
            assert collected.json()["reason"] == "not_found"
            assert not [event for event in _catalog_events(opened.store)
                        if event.type == CatalogEventType.CATALOG_CANDIDATES_COLLECTED]
            assert not server.requests


def test_connection_test_sends_a_real_request_for_each_protocol(tmp_path):
    expectations = (("responses", "authorization"), ("chat_completions", "authorization"),
                    ("messages", "x-api-key"))
    for protocol, expected_header in expectations:
        server = _ModelsServer()
        with server as models_url:
            opened = _Opened(tmp_path / protocol, _document(protocol=protocol, models_url=models_url))
            with running_api(opened) as client:
                current = _catalog(client)["revision"]
                tested = _command(client, "catalog.connection.test", base_version=current, provider_id="p1")
                assert tested.status_code == 200, tested.text
                [event] = _wait_for(
                    opened.store, lambda item: item.payload.get("kind") == "connection",
                    description=f"catalog_test_finished (connection, {protocol})")
                assert event.payload["ok"] is True, event.payload
                assert event.payload["protocol"] == protocol
                assert event.payload["admitted"] is None
                assert event.payload["error"] is None
                # 上游确实收到了带凭据的请求
                assert server.requests, protocol
                assert expected_header in server.requests[-1], protocol
                assert server.requests[-1][expected_header] == (
                    f"Bearer {SECRET}" if expected_header == "authorization" else SECRET)


def test_connection_test_without_models_uses_saved_address_and_credential(tmp_path):
    server = _ModelsServer()
    with server as models_url:
        document = _document(models_url=models_url)
        document["models"] = []
        opened = _Opened(tmp_path, document)
        with running_api(opened) as client:
            before = _catalog(client)
            assert before["models"] == []
            tested = _command(client, "catalog.connection.test", base_version=before["revision"], provider_id="p1")
            assert tested.status_code == 200, tested.text
            [event] = _wait_for(opened.store, lambda item: item.payload.get("kind") == "connection",
                                description="empty connection test")
            assert event.payload["ok"] is True
            assert event.payload["source_url"] == models_url
            assert len(server.requests) == 1
            assert server.requests[0]["authorization"] == f"Bearer {SECRET}"
            assert _catalog(client)["admissions"] == []


def test_connection_test_fails_when_the_credential_is_wrong(tmp_path):
    server = _ModelsServer()
    with server as models_url:
        opened = _Opened(tmp_path, _document(models_url=models_url))
        with running_api(opened) as client:
            current = _catalog(client)["revision"]
            tested = _command(client, "catalog.connection.test", base_version=current, provider_id="p1")
            assert tested.status_code == 200, tested.text
            [ok] = _wait_for(opened.store, lambda item: item.payload.get("kind") == "connection",
                             description="catalog_test_finished (connection)")
            assert ok.payload["ok"] is True

            _set_credential(client, "issue-85-wrong-key")
            revision = _catalog(client)["revision"]
            tested = _command(client, "catalog.connection.test", base_version=revision, provider_id="p1")
            assert tested.status_code == 200, tested.text
            failed = _wait_for(opened.store, lambda item: item.payload.get("kind") == "connection"
                               and not item.payload["ok"], description="failed connection test")
            assert failed[0].payload["error"]
            assert failed[0].payload["admitted"] is None
            _assert_no_secret(client, opened)


def test_connection_test_keeps_admission_unchanged(tmp_path):
    server = _ModelsServer()
    with server as models_url:
        opened = _Opened(tmp_path, _document(models_url=models_url))
        with running_api(opened) as client:
            before = _catalog(client)
            # 准入记录与目录分开返回（工单 #86）：连接测试前后都没有准入记录
            assert before["admissions"] == []
            tested = _command(client, "catalog.connection.test", base_version=before["revision"], provider_id="p1")
            assert tested.status_code == 200, tested.text
            [event] = _wait_for(opened.store, lambda item: item.payload.get("kind") == "connection",
                                description="catalog_test_finished (connection)")
            assert event.payload["ok"] is True
            after = _catalog(client)
            assert after["revision"] == before["revision"]
            assert after["admissions"] == []
            _assert_no_secret(client, opened)


def test_connection_test_without_a_models_url_reports_the_reason(tmp_path):
    opened = _Opened(tmp_path, _document(models_url=""))
    with running_api(opened) as client:
        current = _catalog(client)["revision"]
        tested = _command(client, "catalog.connection.test", base_version=current, provider_id="p1")
        assert tested.status_code == 200, tested.text
        [event] = _wait_for(opened.store, lambda item: item.payload.get("kind") == "connection",
                            description="catalog_test_finished (connection)")
        assert event.payload["ok"] is False
        assert event.payload["error"]
        _assert_no_secret(client, opened)


def test_connection_test_rejects_an_unknown_connection(tmp_path):
    server = _ModelsServer()
    with server as models_url:
        opened = _Opened(tmp_path, _document(models_url=models_url))
        with running_api(opened) as client:
            current = _catalog(client)["revision"]
            tested = _command(client, "catalog.connection.test", base_version=current, provider_id="missing")
            assert tested.status_code == 409, tested.text
            assert tested.json()["reason"] == "not_found"
            assert not [event for event in _catalog_events(opened.store)
                        if event.payload.get("kind") == "connection"]
            assert not server.requests
