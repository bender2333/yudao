# 工单 #384：自定义服务不填写模型列表地址时按「服务地址 + /models」读取模型列表
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
    return {"id": "m384", "model": "upstream-384", "protocol": "responses",
            "context_window": 32000, "max_output_tokens": 2048}


def _document_model():
    return {**_model(), "provider_id": PROVIDER_ID}


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


def _wait_for(store, predicate, *, after=0, description="catalog event"):
    # 等一条目录事件（工单 #1436）：订阅写入口的提交通知，由事件到达决定先后，不按轮询的时机赌。
    # after 是这次命令登记的位置（命令被接受时返回的 position）：只有它之后追加的事件才算这次命令的结果，
    # 保存引起的、在这次命令登记之前就落下的另一次收集因此不算在内。返回第一条符合的事件
    deadline = time.monotonic() + WAIT_FOR_HOST_WORK_SEC
    found = []
    signal = threading.Event()

    def receive(events):
        found.extend(event for event in events if event.position > after and predicate(event))
        if found:
            signal.set()

    unsubscribe = store.subscribe(receive)
    try:
        while not found:
            # 结果可能在订阅之前就写完了：先看已经写下的事件，再等下一次提交
            receive(_catalog_events(store))
            if found:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(f"timed out waiting for {description}")
            signal.wait(remaining)
            signal.clear()
        return found[0]
    finally:
        unsubscribe()


def _save(client, base_url, *, models_url=""):
    response = _command(client, "catalog.connection.save", base_version=_catalog(client)["revision"],
                        provider=_provider(base_url, models_url=models_url), models=[_model()])
    assert response.status_code == 200, response.text


def _collected(client, opened, models_url=None):
    # 发一次获取模型列表命令，等这条命令自己的结果事件，返回事件正文。
    # 判据是命令自己的编号：命令被接受时返回的 position 是它在目录流里登记的位置，结果事件写在它后面
    # （原来按「上一次看到的位置」划范围再 [event] = 取出唯一一条；改动连接地址以后目录自己会再收集一次，
    # 见 harness/app/application.py 的 _apply_source_change，两条结果都落在范围里时用例当场失败，工单 #1436）
    response = _command(client, "catalog.candidates.collect", base_version=_catalog(client)["revision"],
                        provider_id=PROVIDER_ID, models_url=models_url)
    assert response.status_code == 200, response.text
    event = _wait_for(opened.store, lambda item: item.type.endswith("candidates_collected")
                      and item.payload.get("status") is not None,
                      after=response.json()["position"], description="candidates collected")
    return event.payload


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


def test_connection_test_failure_names_the_requested_url(tmp_path):
    # 验收第 2 条：连接测试同样写明请求的地址
    address = f"http://127.0.0.1:{_closed_port()}"
    opened = _Opened(tmp_path, _document(address))
    with running_api(opened) as client:
        response = _command(client, "catalog.connection.test", base_version=_catalog(client)["revision"],
                            provider_id=PROVIDER_ID)
        assert response.status_code == 200, response.text
        event = _wait_for(opened.store, lambda item: item.payload.get("kind") == "connection",
                          after=response.json()["position"], description="connection test finished")
        assert event.payload["ok"] is False
        assert event.payload["source_url"] == f"{address}/models"
        assert f"{address}/models" in event.payload["error"]
