# 工单 #562：从候选建立访问定义时直接采用预填容量（应用层）
# 1. 窗口、输出上限与协议取候选预填值，来源随定义保存；
# 2. 缺少容量的候选必须在请求中给出才能保存，否则拒绝并写明缺少哪一项；
# 3. 修改窗口保持准入。
# 全部是真实行为：真实启动的 FastAPI 应用、真实命令、上游为测试内启动的本机真实 HTTP 服务，不使用 mock。

from __future__ import annotations

import json
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from harness.app.application import Application
from harness.app.catalog_commands import ModelInput
from harness.models import CatalogEventType
from harness.tests.api_helpers import running_api
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

SECRET = "issue-562-secret-key"
REF = "ISSUE562_KEY"
PROVIDER_ID = "p562"


class _ModelsServer:
    # 模型列表上游：真实的本机 HTTP 服务，固定回复给定状态码与 JSON 正文
    def __init__(self, payload: Any, *, status: int = 200) -> None:
        self.payload = payload
        self.status = status
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                return

            def do_GET(self) -> None:
                body = json.dumps(server.payload).encode("utf-8")
                self.send_response(server.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def _provider(base_url: str, *, models_url: str = "") -> dict[str, Any]:
    return {
        "id": PROVIDER_ID,
        "name": "工单 562 测试连接",
        "base_url": base_url,
        "credential_ref": REF,
        "timeout_sec": 10.0,
        "preset_id": "",
        "models_url": models_url,
    }


def _document(base_url: str, *, models_url: str = "") -> dict[str, Any]:
    return {
        "providers": [_provider(base_url, models_url=models_url)],
        "models": [],
        "bindings": {},
    }


class _Opened:
    def __init__(self, tmp_path: Any, document: dict[str, Any]) -> None:
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
    def application(self) -> Application:
        return self.applications[-1]

    @property
    def store(self) -> Any:
        return self.applications[-1].system.store


def _catalog(client: Any) -> dict[str, Any]:
    response = client.get("/api/queries/catalog")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _command(client: Any, name: str, **body: Any) -> Any:
    return client.post(f"/api/commands/{name}", json={"command_id": str(uuid.uuid4()), **body})


def _catalog_events(store: Any) -> list[Any]:
    return store.read(0, limit=100_000, types=[value for key, value in vars(CatalogEventType).items()
                                              if not key.startswith("_")])


def _wait_for(store: Any, predicate: Any, *, description: str = "catalog event") -> list[Any]:
    deadline = time.monotonic() + WAIT_FOR_HOST_WORK_SEC
    while time.monotonic() < deadline:
        matched = [event for event in _catalog_events(store) if predicate(event)]
        if matched:
            return matched
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {description}")


def _collect_candidates(client: Any, opened: _Opened, *, provider_id: str = PROVIDER_ID) -> list[dict[str, Any]]:
    current = _catalog(client)["revision"]
    seen_positions = [event.position for event in _catalog_events(opened.store)]
    last_position = max(seen_positions) if seen_positions else -1
    response = _command(client, "catalog.candidates.collect", base_version=current, provider_id=provider_id)
    assert response.status_code == 200, response.text
    [event] = _wait_for(
        opened.store,
        lambda ev: ev.position > last_position and ev.type == CatalogEventType.CATALOG_CANDIDATES_COLLECTED,
        description="catalog_candidates_collected",
    )
    assert event.payload["status"] == "ok", event.payload["error"]
    return event.payload["candidates"]


def test_definition_from_candidate_uses_prefilled_capacity_and_source(tmp_path: Any) -> None:
    # 验收第 1 条：从候选建立的定义保存时容量取预填值，来源写明
    upstream = _ModelsServer({
        "data": [
            {"id": "model-with-limits", "limit": {"context": 128000, "output": 4096}},
        ]
    })
    try:
        opened = _Opened(tmp_path, _document(upstream.base))
        with running_api(opened) as client:
            candidates = _collect_candidates(client, opened)
            candidate = next(item for item in candidates if item["id"] == "model-with-limits")
            assert candidate["context_window"] == 128000
            assert candidate["max_output_tokens"] == 4096

            # 从候选建立模型访问定义
            model_input = ModelInput.from_candidate(candidate)
            assert model_input.id == "model-with-limits"
            assert model_input.model == "model-with-limits"
            assert model_input.context_window == 128000
            assert model_input.max_output_tokens == 4096
            assert "窗口：上游模型列表" in model_input.capability_source
            assert "输出上限：上游模型列表" in model_input.capability_source

            # 直接保存访问定义，无需单独「接受容量」命令
            current = _catalog(client)["revision"]
            saved = _command(
                client,
                "catalog.connection.save",
                base_version=current,
                provider=_provider(upstream.base),
                models=[model_input.model_dump()],
            )
            assert saved.status_code == 200, saved.text

            # 保存后的定义中容量取预填值，来源随定义保存
            catalog_data = _catalog(client)
            saved_model = next(item for item in catalog_data["models"] if item["id"] == "model-with-limits")
            assert saved_model["context_window"] == 128000
            assert saved_model["max_output_tokens"] == 4096
            assert "窗口：上游模型列表" in saved_model["capability_source"]
            assert "输出上限：上游模型列表" in saved_model["capability_source"]
    finally:
        upstream.close()


def test_candidate_missing_capacity_refuses_to_save_and_names_missing_fields(tmp_path: Any) -> None:
    # 验收第 1 条：两处都没有窗口或输出上限的候选，必须在请求里给出才能保存，否则拒绝并写明缺少哪一项
    upstream = _ModelsServer({
        "data": [
            {"id": "model-without-limits"},
        ]
    })
    try:
        opened = _Opened(tmp_path, _document(upstream.base))
        with running_api(opened) as client:
            candidates = _collect_candidates(client, opened)
            candidate = next(item for item in candidates if item["id"] == "model-without-limits")
            assert candidate.get("context_window") is None
            assert candidate.get("max_output_tokens") is None

            # 未补充容量直接提交保存：拒绝并写明缺少 context_window 与 max_output_tokens
            model_missing = ModelInput.from_candidate(candidate)
            current = _catalog(client)["revision"]
            rejected = _command(
                client,
                "catalog.connection.save",
                base_version=current,
                provider=_provider(upstream.base),
                models=[model_missing.model_dump()],
            )
            assert rejected.status_code == 409, rejected.text
            assert rejected.json()["reason"] == "catalog_invalid"
            err = rejected.json()["message"]
            assert "context_window" in err, f"错误中应指出缺少 context_window: {err}"
            assert "max_output_tokens" in err, f"错误中应指出缺少 max_output_tokens: {err}"

            # 在请求里给出容量后可以保存
            model_filled = ModelInput.from_candidate(
                candidate,
                context_window=64000,
                max_output_tokens=2048,
                capability_source="手动",
            )
            saved = _command(
                client,
                "catalog.connection.save",
                base_version=current,
                provider=_provider(upstream.base),
                models=[model_filled.model_dump()],
            )
            assert saved.status_code == 200, saved.text
            catalog_data = _catalog(client)
            saved_model = next(item for item in catalog_data["models"] if item["id"] == "model-without-limits")
            assert saved_model["context_window"] == 64000
            assert saved_model["max_output_tokens"] == 2048
            assert saved_model["capability_source"] == "手动"
    finally:
        upstream.close()


def test_missing_single_capacity_field_names_that_specific_field(tmp_path: Any) -> None:
    # 验收第 1 条细节：分别测试只缺 context_window 或只缺 max_output_tokens 时准确指出对应字段
    upstream = _ModelsServer({"data": [{"id": "model-single-check"}]})
    try:
        opened = _Opened(tmp_path, _document(upstream.base))
        with running_api(opened) as client:
            candidates = _collect_candidates(client, opened)
            candidate = candidates[0]

            # 只填窗口，缺少输出上限
            current = _catalog(client)["revision"]
            only_window = ModelInput.from_candidate(candidate, context_window=32000)
            rejected1 = _command(
                client,
                "catalog.connection.save",
                base_version=current,
                provider=_provider(upstream.base),
                models=[only_window.model_dump()],
            )
            assert rejected1.status_code == 409, rejected1.text
            assert rejected1.json()["reason"] == "catalog_invalid"
            err1 = rejected1.json()["message"]
            assert "max_output_tokens" in err1
            assert "context_window" not in err1

            # 只填输出上限，缺少窗口
            only_output = ModelInput.from_candidate(candidate, max_output_tokens=2048)
            rejected2 = _command(
                client,
                "catalog.connection.save",
                base_version=current,
                provider=_provider(upstream.base),
                models=[only_output.model_dump()],
            )
            assert rejected2.status_code == 409, rejected2.text
            assert rejected2.json()["reason"] == "catalog_invalid"
            err2 = rejected2.json()["message"]
            assert "context_window" in err2
            assert "max_output_tokens" not in err2
    finally:
        upstream.close()


def test_modifying_window_keeps_admission(tmp_path: Any) -> None:
    # 验收第 2 条：修改窗口以后定义仍然准入
    upstream = _ModelsServer({
        "data": [
            {"id": "model-admitted", "limit": {"context": 128000, "output": 4096}},
        ]
    })
    try:
        opened = _Opened(tmp_path, _document(upstream.base))
        with running_api(opened) as client:
            candidates = _collect_candidates(client, opened)
            candidate = next(item for item in candidates if item["id"] == "model-admitted")
            model_input = ModelInput.from_candidate(candidate)

            current = _catalog(client)["revision"]
            saved = _command(
                client,
                "catalog.connection.save",
                base_version=current,
                provider=_provider(upstream.base),
                models=[model_input.model_dump()],
            )
            assert saved.status_code == 200, saved.text

            # 模拟模型测试通过，写入准入记录
            opened.application.system.facade.record_admission(PROVIDER_ID, "model-admitted", admitted_model="model-admitted")
            admissions_before = opened.application.system.facade.model_admissions()
            rec = next(item for item in admissions_before if item["model_id"] == "model-admitted")
            assert rec["admitted"] is True
            assert rec["stale"] is False

            # 修改窗口大小
            current = _catalog(client)["revision"]
            modified = model_input.model_copy(update={"context_window": 256000, "capability_source": "手动"})
            save_modified = _command(
                client,
                "catalog.connection.save",
                base_version=current,
                provider=_provider(upstream.base),
                models=[modified.model_dump()],
            )
            assert save_modified.status_code == 200, save_modified.text

            # 修改窗口后准入仍然保持
            admissions_after = opened.application.system.facade.model_admissions()
            rec_after = next(item for item in admissions_after if item["model_id"] == "model-admitted")
            assert rec_after["admitted"] is True
            assert rec_after["stale"] is False

            catalog_after = _catalog(client)
            model_after = next(item for item in catalog_after["models"] if item["id"] == "model-admitted")
            assert model_after["context_window"] == 256000
    finally:
        upstream.close()
