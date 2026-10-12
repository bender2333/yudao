# 工单 #384：自定义服务不填写模型列表地址时按「服务地址 + /models」读取模型列表（设计说明第 9.1 节）；
# 读取失败时界面写明请求的地址与状态码或连接失败原因。
# 全部是真实行为：真实启动的 FastAPI 应用、真实命令、真实的模型列表上游（测试内启动的本机 HTTP 服务）
# 与真实的不可达端口，不使用桩替身。

import json
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from harness.app.application import Application
from harness.models import CatalogEventType
from harness.tests.api_helpers import running_api
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

SECRET = "issue-384-secret-key"
REF = "ISSUE384_KEY"
PROVIDER_ID = "p384"


class _ModelsServer:
    # 模型列表上游：真实的本机 HTTP 服务，固定回复给定状态码与 JSON 正文
    def __init__(self, payload, *, status=200):
        self.payload = payload
        self.status = status
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def do_GET(self):
                body = json.dumps(server.payload).encode("utf-8")
                self.send_response(server.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def _closed_port() -> int:
    # 真实的不可达端口：绑定以后立刻释放，这个端口上没有服务在听
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _provider(base_url, *, models_url=""):
    return {"id": PROVIDER_ID, "name": "工单 384 服务", "base_url": base_url,
            "credential_ref": REF, "timeout_sec": 5.0, "preset_id": "", "models_url": models_url}


def _model():
    # 保存命令用的定义：每行带容量确认
    return {"id": "m384", "model": "upstream-384", "protocol": "responses", "capacity_confirmed": True,
            "context_window": 32000, "max_output_tokens": 2048}


def _document_model():
    # 目录文件里的定义：带上所属连接，不带命令用的逐行确认标记
    return {key: value for key, value in {**_model(), "provider_id": PROVIDER_ID}.items()
            if key != "capacity_confirmed"}


def _document(base_url, *, models_url=""):
    return {"providers": [_provider(base_url, models_url=models_url)],
            "models": [_document_model()]}


class _Opened:
    def __init__(self, tmp_path, document) -> None:
        self.data_dir = tmp_path / "data"
        self.config = tmp_path / "providers.json"
        self.dotenv = tmp_path / ".env"
        self.dotenv.write_text(f"{REF}={SECRET}\n", encoding="utf-8")
        self.config.write_text(json.dumps(document), encoding="utf-8")
        self.applications: list[Application] = []

    def __call__(self) -> Application:
        application = Application.open(self.data_dir, provider_config=self.config, dotenv=self.dotenv)
        self.applications.append(application)
        return application

    @property
    def store(self):
        return self.applications[-1].system.store


def _catalog(client):
    response = client.get("/api/queries/catalog")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _command(client, name, **body):
    return client.post(f"/api/commands/{name}", json={"command_id": str(uuid.uuid4()), **body})


def _catalog_events(store):
    return store.read(0, limit=100_000, types=[value for key, value in vars(CatalogEventType).items()
                                              if not key.startswith("_")])


def _wait_for(store, predicate, *, description="catalog event"):
    deadline = time.monotonic() + WAIT_FOR_HOST_WORK_SEC
    while time.monotonic() < deadline:
        matched = [event for event in _catalog_events(store) if predicate(event)]
        if matched:
            return matched
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {description}")


def _save(client, base_url, *, models_url=""):
    response = _command(client, "catalog.connection.save", base_version=_catalog(client)["revision"],
                        provider=_provider(base_url, models_url=models_url), models=[_model()])
    assert response.status_code == 200, response.text


def _collected(client, opened, models_url=None):
    # 发一次获取模型列表命令，等它的结果事件，返回事件正文；
    # 同一测试里会连续发多次，只认发出命令以后新追加的那一条
    events = _catalog_events(opened.store)
    seen = events[-1].position if events else 0
    response = _command(client, "catalog.candidates.collect", base_version=_catalog(client)["revision"],
                        provider_id=PROVIDER_ID, models_url=models_url)
    assert response.status_code == 200, response.text
    [event] = _wait_for(opened.store, lambda item: item.position > seen and item.type.endswith("candidates_collected")
                        and item.payload.get("status") is not None,
                        description="candidates collected")
    return event.payload


def test_custom_service_without_models_url_reads_base_url_plus_models(tmp_path):
    # 验收第 1 条：自定义服务不填写模型列表地址时，按服务地址 + /models 读取
    upstream = _ModelsServer({"data": [{"id": "upstream-384"}]})
    try:
        opened = _Opened(tmp_path, _document(upstream.base))
        with running_api(opened) as client:
            payload = _collected(client, opened)
            assert payload["status"] == "ok", payload["error"]
            assert payload["source_url"] == f"{upstream.base}/models"
            assert payload["candidate_ids"] == ["upstream-384"]
    finally:
        upstream.close()


def test_saved_models_url_is_used_and_clearing_it_returns_to_the_default(tmp_path):
    # 验收第 1 条：填写的地址被使用；清空以后回到默认地址
    upstream = _ModelsServer({"data": [{"id": "upstream-384"}]})
    try:
        opened = _Opened(tmp_path, _document(upstream.base, models_url=f"{upstream.base}/explicit"))
        with running_api(opened) as client:
            explicit = _collected(client, opened)
            assert explicit["source_url"] == f"{upstream.base}/explicit"

            _save(client, upstream.base, models_url="")
            defaulted = _collected(client, opened)
            assert defaulted["source_url"] == f"{upstream.base}/models"

            # 命令上给出的地址覆盖保存值
            overridden = _collected(client, opened, models_url=f"{upstream.base}/override")
            assert overridden["source_url"] == f"{upstream.base}/override"
    finally:
        upstream.close()


def test_default_models_url_follows_a_changed_service_address(tmp_path):
    # 验收第 1 条：服务地址改了以后，没有填写过的模型列表地址随之变化
    upstream = _ModelsServer({"data": [{"id": "upstream-384"}]})
    try:
        opened = _Opened(tmp_path, _document(upstream.base))
        with running_api(opened) as client:
            assert _collected(client, opened)["source_url"] == f"{upstream.base}/models"
            _save(client, f"{upstream.base}/v2")
            assert _collected(client, opened)["source_url"] == f"{upstream.base}/v2/models"
    finally:
        upstream.close()


def test_failure_names_the_requested_url_and_status_code(tmp_path):
    # 验收第 2 条：上游返回 404 时写明请求的地址与状态码
    upstream = _ModelsServer({"error": "not found"}, status=404)
    try:
        opened = _Opened(tmp_path, _document(upstream.base))
        with running_api(opened) as client:
            payload = _collected(client, opened)
            assert payload["status"] == "unknown"
            assert f"{upstream.base}/models" in payload["error"]
            assert "404" in payload["error"]
    finally:
        upstream.close()


def test_failure_names_the_requested_url_and_connection_reason(tmp_path):
    # 验收第 2 条：端口上没有服务时写明请求的地址与连接失败原因
    address = f"http://127.0.0.1:{_closed_port()}"
    opened = _Opened(tmp_path, _document(address))
    with running_api(opened) as client:
        payload = _collected(client, opened)
        assert payload["status"] == "unknown"
        assert f"{address}/models" in payload["error"]
        assert "连接" in payload["error"]


def test_connection_test_failure_names_the_requested_url(tmp_path):
    # 验收第 2 条：连接测试同样写明请求的地址
    address = f"http://127.0.0.1:{_closed_port()}"
    opened = _Opened(tmp_path, _document(address))
    with running_api(opened) as client:
        events = _catalog_events(opened.store)
        seen = events[-1].position if events else 0
        response = _command(client, "catalog.connection.test", base_version=_catalog(client)["revision"],
                            provider_id=PROVIDER_ID)
        assert response.status_code == 200, response.text
        [event] = _wait_for(opened.store, lambda item: item.position > seen
                            and item.payload.get("kind") == "connection",
                            description="connection test finished")
        assert event.payload["ok"] is False
        assert event.payload["source_url"] == f"{address}/models"
        assert f"{address}/models" in event.payload["error"]
