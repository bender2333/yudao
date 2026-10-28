from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from harness.adapters.facade_adapter import FacadeAdapter
from harness.app.application import Application
from harness.providers import (
    CatalogValidationError,
    CredentialChain,
    ProviderFacade,
)
from harness.providers.presets import USER_AGENT
from harness.tests.api_helpers import running_api
from harness.tests.protocol_helpers import (
    chat_responder,
    complete,
    messages_responder,
    model_call,
    preset_base_urls,
    responses_responder,
)

# 工单 #84：调用协议属于模型访问定义，连接不声明协议（模型管理设计说明第 4.2、4.3 节）；服务方案预置表按协议列出请求基址（第 4.1 节）。
# 全部用例经运行系统整体进行：真实 HTTP 服务记录请求路径与请求头，模型回答由 FakeAdapter 给出。


def _valid_document(base_url: str = "http://127.0.0.1:8080/v1") -> dict:
    # 模型访问定义声明协议，连接不再声明协议
    return {
        "providers": [
            {
                "id": "provider-1",
                "name": "Provider 1",
                "base_url": base_url,
                "credential_ref": "KEY_1",
                "timeout_sec": 30.0,
            }
        ],
        "models": [
            {
                "id": "model-1",
                "provider_id": "provider-1",
                "model": "model-x",
                "protocol": "responses",
                "context_window": 32000,
                "max_output_tokens": 2048,
            }
        ],
        "bindings": {
            "product": {"provider_id": "provider-1", "model_id": "model-1"},
            "engineering": {"provider_id": "provider-1", "model_id": "model-1"},
            "quality": {"provider_id": "provider-1", "model_id": "model-1"},
        },
    }


def test_provider_definition_declaring_protocol_is_rejected_and_keeps_previous_catalog(tmp_path: Path):
    # 验收 1：在连接上声明协议的目录文件读取失败，错误指出字段位置，目录保持上一个有效版本
    config_file = tmp_path / "providers.json"
    config_file.write_text(json.dumps(_valid_document()), encoding="utf-8")

    facade = ProviderFacade(credentials=CredentialChain(overrides={"KEY_1": "secret-1"}))
    facade.load_document(config_file)
    original_revision = facade.catalog_revision()
    original_document = facade.to_document()

    invalid = _valid_document()
    invalid["providers"][0]["protocol"] = "responses"
    config_file.write_text(json.dumps(invalid), encoding="utf-8")

    with pytest.raises(CatalogValidationError) as exc_info:
        facade.load_document(config_file)

    assert any(issue.location == "providers[0].protocol" for issue in exc_info.value.issues)
    # 目录保持上一个有效版本：修订号与内容都没有变化
    assert facade.catalog_revision() == original_revision
    assert facade.to_document() == original_document
    providers = facade.providers_view()["providers"]
    assert len(providers) == 1
    assert "protocol" not in providers[0]
    models = facade.providers_view()["models"]
    assert len(models) == 1
    assert models[0]["protocol"] == "responses"

def test_opencode_go_three_protocols_paths_and_identity_headers():
    # 验收 2：OpenCode Go 三种协议各保存一份连接，地址是同一个请求基址；
    # 模型请求分别到达 /v1/responses、/v1/chat/completions、/v1/messages，并带有必需请求头。
    # Chat Completions 与 Messages 的请求体都带 max_tokens，所以按请求路径分发回复
    by_path = {
        "/v1/responses": responses_responder,
        "/v1/chat/completions": chat_responder,
        "/v1/messages": messages_responder,
    }
    captured: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:
            return

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captured.append({"path": self.path,
                             "headers": {key.lower(): value for key, value in self.headers.items()},
                             "body": body})
            status, content_type, chunks = by_path[self.path](body)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(sum(len(chunk) for chunk in chunks)))
            self.end_headers()
            for chunk in chunks:
                self.wfile.write(chunk)
            self.wfile.flush()

        def do_GET(self) -> None:
            # 连接测试读取模型列表地址：三种协议都在本机上游取得，不访问真实的 opencode.ai
            body = json.dumps({"data": [{"id": "model-x"}]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        shared_base = f"http://127.0.0.1:{server.server_address[1]}/v1"
        # 三种协议的请求路径都拼在这个本机地址后面：连接测试与模型调用都不到真实的 opencode.ai
        with preset_base_urls(shared_base, models_url=shared_base + "/v1/models"):
            connections = (
                ("go-responses", "m-responses", "responses", "model-resp", "/v1/responses"),
                ("go-chat", "m-chat", "chat_completions", "model-chat", "/v1/chat/completions"),
                ("go-messages", "m-messages", "messages", "model-msg", "/v1/messages"),
            )
            document = {
                "providers": [
                    {"id": provider_id, "name": provider_id,
                     "base_url": shared_base, "credential_ref": "SHARED_KEY",
                     "preset_id": "opencode-go", "timeout_sec": 30.0,
                     "models_url": shared_base + "/v1/models"}
                    for provider_id, _model_id, _protocol, _upstream, _path in connections
                ],
                "models": [
                    {"id": model_id, "provider_id": provider_id, "model": upstream,
                     "protocol": protocol,
                     "context_window": 32000, "max_output_tokens": 2048}
                    for provider_id, model_id, protocol, upstream, _path in connections
                ],
                "bindings": {},
            }
            facade = ProviderFacade(credentials=CredentialChain(overrides={"SHARED_KEY": "go-secret"}))
            facade.store_document(document)
            adapter = FacadeAdapter(facade)

            for provider_id, model_id, protocol, _upstream, expected_path in connections:
                # 连接测试经公开接口证明地址与凭据可用（三种协议同一套缺失项检查）
                connection = facade.test_connection(provider_id)
                assert connection["ok"] is True, connection
                assert "protocol" not in connection
                facade.record_admission(provider_id, model_id, admitted_model="admitted-model")
                session_id = f"session-{provider_id}"
                target = facade.resolve_snapshot(
                    [{"key": "test", "provider_id": provider_id, "model_id": model_id}]
                ).target("test")
                # 调用目标的协议取自访问定义，地址取自该定义在预置表中按协议的请求基址
                assert target.protocol == protocol
                assert target.base_url == shared_base
                call = model_call([{"role": "user", "content": "hi"}],
                                  max_output_tokens=1024, session_id=session_id)
                resolution = facade.resolve_call_target(model_id)
                assert resolution.available, resolution.message
                facade.bind_call_key(resolution.handle_id, call.logical_call_id)
                complete(adapter, call)
                facade.release_call_handle(call.logical_call_id)

                assert captured[-1]["path"] == expected_path
                assert captured[-1]["headers"].get("user-agent") == USER_AGENT
                assert captured[-1]["headers"].get("x-opencode-session") == session_id
    finally:
        server.shutdown()
        server.server_close()


def test_catalog_query_returns_presets_revision_and_source_without_models(tmp_path: Path):
    # 验收 4：catalog 查询返回预置表的 revision 与来源；预置表中没有模型、容量、推理档位或准入
    class Opened:
        def __init__(self, directory: Path) -> None:
            self.data_dir = directory / "data"
            self.config = directory / "providers.json"
            self.dotenv = directory / ".env"
            self.dotenv.write_text("KEY_1=secret-1\n", encoding="utf-8")
            self.config.write_text(json.dumps(_valid_document()), encoding="utf-8")
            self.applications: list[Application] = []

        def __call__(self) -> Application:
            application = Application.open(self.data_dir, provider_config=self.config, dotenv=self.dotenv)
            self.applications.append(application)
            return application

    with running_api(Opened(tmp_path)) as client:
        response = client.get("/api/queries/catalog")
        assert response.status_code == 200, response.text
        presets = response.json()["data"]["presets"]
        assert presets["revision"]
        assert presets["source"]

        opencode_go = next(item for item in presets["presets"] if item["id"] == "opencode-go")
        # 三种协议的请求基址都是同一个
        for protocol in ("responses", "chat_completions", "messages"):
            assert opencode_go["base_urls"][protocol] == "https://opencode.ai/zen/go/v1"

        for preset in presets["presets"]:
            # 预置表只含接入规则，不带模型、容量、推理档位或准入
            forbidden = {"models", "known_models", "admitted", "capacity", "context_window",
                         "max_output_tokens", "reasoning", "reasoning_levels"}
            assert not (forbidden & set(preset)), sorted(forbidden & set(preset))
            assert preset["models_url"]
            assert preset["docs_url"]
            assert preset["source"]


