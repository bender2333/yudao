import json
import os
import socket
import time
import uuid

import pytest

from harness.app.application import Application
from harness.models import CatalogEventType
from harness.tests.api_helpers import running_api
from harness.tests.protocol_helpers import ScriptedProvider, send_reply
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

# R2、R3：只经命令、查询与目录事件核对一步连接，使用真实 HTTP 服务、SQLite 与目录文件。
SECRET = "connect-key-do-not-publish"


class _Opened:
    def __init__(self, root, *, dotenv=None):
        self.data_dir = root / "data"
        self.config = root / "providers.json"
        self.dotenv = root / ".env" if dotenv is None else dotenv
        self.applications = []

    def __call__(self):
        app = Application.open(self.data_dir, provider_config=self.config, dotenv=self.dotenv)
        self.applications.append(app)
        return app

    @property
    def store(self):
        return self.applications[-1].system.store


def _catalog(client):
    response = client.get("/api/queries/catalog")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _command(client, name, **values):
    return client.post(f"/api/commands/{name}", json={"command_id": str(uuid.uuid4()), **values})


def _connect(client, base_url, *, api_key=SECRET):
    values = {"base_version": _catalog(client)["revision"], "base_url": base_url}
    if api_key is not None:
        values["api_key"] = api_key
    response = _command(client, "catalog.connect", **values)
    assert response.status_code == 200, response.text
    return response.json()


def _collected(opened, *, after=0):
    deadline = time.monotonic() + WAIT_FOR_HOST_WORK_SEC
    while time.monotonic() < deadline:
        events = opened.store.read(after, limit=10000, types=[CatalogEventType.CATALOG_CANDIDATES_COLLECTED])
        if events:
            return events[-1]
        time.sleep(0.01)
    raise AssertionError("等待 catalog_candidates_collected 超时")


def _json_reply(payload, *, status=200):
    def reply(_provider, handler):
        send_reply(handler, status, "application/json", json.dumps(payload).encode("utf-8"))
    return reply


def _assert_private(client, opened, *secrets):
    for query in ("catalog", "catalog.document"):
        response = client.get(f"/api/queries/{query}")
        assert response.status_code == 200, response.text
        assert all(secret not in response.text for secret in secrets)
    events = opened.store.read(0, limit=10000)
    assert all(secret not in json.dumps([event.payload for event in events]) for secret in secrets)
    assert all(secret not in opened.config.read_text(encoding="utf-8") for secret in secrets)


def test_connect_collects_over_one_hundred_mixed_candidates_and_survives_restart(tmp_path):
    models = []
    for index in range(124):
        limit = ({"context_length": 128000, "max_completion_tokens": 8192} if index % 2 else
                 {"limit": {"context": 256000, "output": 16000}})
        models.append({"id": f"maker-{index % 4}/model-{index}", **limit,
                       "modalities": {"input": ["text", "image"], "output": ["text"]},
                       "reasoning": bool(index % 2)})
    models.extend([{"id": "image-generation", "modalities": {"output": ["image"]}},
                   {"id": "unknown-vision-name"}])
    upstream = ScriptedProvider([_json_reply({"data": models}), _json_reply({"data": models})])
    opened = _Opened(tmp_path)
    try:
        with running_api(opened) as client:
            accepted = _connect(client, upstream.base + "/v1/")
            event = _collected(opened)
            catalog = _catalog(client)
            [provider] = catalog["providers"]
            assert accepted["refs"] == {"provider_id": provider["id"]}
            assert provider["id"] == provider["name"] == "127.0.0.1"
            assert provider["credential_ref"] == "HOST_127_0_0_1_KEY"
            assert provider["base_url"] == upstream.base + "/v1"
            assert provider["credential"]["persisted"] is True
            assert provider["credential"]["source"] == "dotenv"
            assert event.payload["status"] == "ok" and len(event.payload["candidates"]) == 126
            latest = provider["latest_candidates"]
            assert latest["fetched_at"] == event.payload["fetched_at"]
            assert [item["id"] for item in latest["candidates"]] == event.payload["candidate_ids"]
            saved_first = next(item for item in latest["candidates"] if item["id"] == "maker-0/model-0")
            assert saved_first["context_window"] == 256000 and saved_first["max_output_tokens"] == 16000
            assert saved_first["input_modalities"] == ["text", "image"]
            candidates = {item["id"]: item for item in event.payload["candidates"]}
            first, second = candidates["maker-0/model-0"], candidates["maker-1/model-1"]
            assert (first["context_window"], first["max_output_tokens"]) == (256000, 16000)
            assert (second["context_window"], second["max_output_tokens"]) == (128000, 8192)
            for candidate in (first, second):
                assert candidate["protocol"] == "chat_completions"
                assert candidate["context_window_source"] == candidate["max_output_tokens_source"] == "models_url"
                assert candidate["input_modalities"] == ["text", "image"]
                assert candidate["input_modalities_source"] == "models_url"
                assert candidate["source_details"]["context_window"]["source"] == "models_url"
                assert candidate["provider"] == candidate["id"].split("/")[0]
                assert candidate["applicable"] is True
            assert first["reasoning"] is False and second["reasoning"] is True
            assert candidates["image-generation"]["applicable"] is False
            assert candidates["unknown-vision-name"]["applicable"] is True
            assert candidates["unknown-vision-name"]["input_modalities"] == ["text"]
            assert candidates["unknown-vision-name"]["reasoning"] is None
            assert SECRET in opened.dotenv.read_text(encoding="utf-8")
            _assert_private(client, opened, SECRET)
        with running_api(opened) as client:
            [provider] = _catalog(client)["providers"]
            assert provider["credential"]["persisted"] is True
            assert provider["credential"]["configured"] is True
            assert provider["latest_candidates"] is None
            position = opened.store.end_position()
            _connect(client, upstream.base + "/v1", api_key=None)
            assert _collected(opened, after=position).payload["status"] == "ok"
            assert len(_catalog(client)["providers"]) == 1
    finally:
        upstream.close()


def test_same_normalized_address_reuses_connection_and_updates_key(tmp_path):
    # HTTPS 地址无法连接也不影响保存；规范化、沿用与候选失败各经公开合同核对。
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        first = _connect(client, "https://LOCALHOST:1/v1/")
        _collected(opened)
        position = opened.store.end_position()
        second = _connect(client, "localhost:1/v1", api_key="replacement-connect-key")
        _collected(opened, after=position)
        assert first["refs"] == second["refs"]
        [provider] = _catalog(client)["providers"]
        assert provider["base_url"] == "https://localhost:1/v1"
        assert provider["credential_ref"] == "LOCALHOST_KEY"
        text = opened.dotenv.read_text(encoding="utf-8")
        assert "replacement-connect-key" in text and SECRET not in text
        _assert_private(client, opened, SECRET, "replacement-connect-key")


def test_connect_uses_distinct_ids_names_and_credential_refs_for_same_host(tmp_path):
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        _connect(client, "http://localhost:1/a")
        _collected(opened)
        position = opened.store.end_position()
        _connect(client, "http://localhost:1/b")
        _collected(opened, after=position)
        providers = _catalog(client)["providers"]
        assert [item["id"] for item in providers] == ["localhost", "localhost-2"]
        assert [item["name"] for item in providers] == ["localhost", "localhost-2"]
        assert [item["credential_ref"] for item in providers] == ["LOCALHOST_KEY", "LOCALHOST_2_KEY"]


@pytest.mark.parametrize(("status", "payload", "reason", "message"), [
    (401, {"error": SECRET}, "credential_rejected", "服务拒绝了这个 API Key"),
    (403, {"error": SECRET}, "credential_rejected", "服务拒绝了这个 API Key"),
    (200, {"message": "not a list"}, "invalid_response", "对象"),
    (200, {"data": ["not a model"]}, "invalid_response", "有效 id"),
    (503, {"error": "unavailable"}, "http_status", "503"),
    (200, {"data": []}, "empty_list", "模型权限"),
])
def test_failed_collection_reports_a_specific_reason_and_keeps_the_connection(tmp_path, status, payload, reason, message):
    upstream = ScriptedProvider([_json_reply(payload, status=status)])
    opened = _Opened(tmp_path)
    try:
        with running_api(opened) as client:
            _connect(client, upstream.base + "/v1")
            event = _collected(opened)
            result = event.payload
            assert result["status"] == "unknown" and result["reason"] == reason
            assert result["source_url"] == upstream.base + "/v1/models"
            assert result["source_url"] in result["error"] and message in result["error"]
            if status in (401, 403):
                assert str(status) in result["error"]
                assert SECRET not in json.dumps(result)
            [provider] = _catalog(client)["providers"]
            assert provider["latest_candidates"]["reason"] == reason
            assert provider["credential"]["persisted"] is True
            _assert_private(client, opened, SECRET)
    finally:
        upstream.close()


def test_unreachable_collection_keeps_key_and_reports_the_address(tmp_path):
    # 真实套接字绑定但不监听，直到命令结束都保留端口，连接确定被拒绝。
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        address = f"http://127.0.0.1:{reserved.getsockname()[1]}/v1"
        opened = _Opened(tmp_path)
        with running_api(opened) as client:
            _connect(client, address)
            result = _collected(opened).payload
            assert result["reason"] == "unreachable"
            assert address + "/models" in result["error"]
            assert "连接被拒绝" in result["error"]
            assert _catalog(client)["providers"][0]["credential"]["persisted"] is True


@pytest.mark.parametrize("suffix", ["/chat/completions", "/responses", "/messages"])
def test_404_on_an_inference_address_explains_the_parent_address(tmp_path, suffix):
    upstream = ScriptedProvider([_json_reply({}, status=404)])
    opened = _Opened(tmp_path)
    try:
        with running_api(opened) as client:
            _connect(client, upstream.base + "/v1" + suffix)
            result = _collected(opened).payload
            assert result["reason"] == "http_status"
            assert "404" in result["error"] and "上一级" in result["error"]
            assert result["source_url"] in result["error"]
    finally:
        upstream.close()


def test_dotenv_write_failure_saves_neither_connection_nor_key(tmp_path):
    # .env 路径本身为目录，真实文件系统会拒绝原子替换；Windows 与 POSIX 都可复现。
    blocked = tmp_path / "blocked.env"
    blocked.mkdir()
    opened = _Opened(tmp_path, dotenv=blocked)
    with running_api(opened) as client:
        before = _catalog(client)
        response = _command(client, "catalog.connect", base_version=before["revision"],
                            base_url="http://localhost:1/v1", api_key=SECRET)
        assert response.status_code == 409, response.text
        assert response.json()["reason"] == "catalog_invalid"
        assert "凭据" in response.json()["message"] and "失败" in response.json()["message"]
        after = _catalog(client)
        assert after["providers"] == [] and after["revision"] == before["revision"]
        assert blocked.is_dir() and not list(blocked.iterdir())
        assert not opened.config.exists()
        assert not opened.applications[-1].system.facade.credential_status("LOCALHOST_KEY")["configured"]


@pytest.mark.skipif(os.name != "nt", reason="Windows 的只读文件禁止原子替换")
def test_a_readonly_dotenv_saves_neither_key_nor_connection_and_leaves_no_secret_file(tmp_path):
    # R3：真实文件权限导致写入失败，原 Key、目录与临时文件都不含这次未保存的 Key。
    opened = _Opened(tmp_path)
    original = "OTHER_KEY=unrelated-key\n"
    opened.dotenv.write_text(original, encoding="utf-8")
    opened.dotenv.chmod(0o444)
    try:
        with running_api(opened) as client:
            before = _catalog(client)
            response = _command(client, "catalog.connect", base_version=before["revision"],
                                base_url="http://localhost:1/v1", api_key=SECRET)
            assert response.status_code == 409, response.text
            assert response.json()["reason"] == "catalog_invalid"
            assert "失败" in response.json()["message"]
            assert _catalog(client)["providers"] == []
            assert opened.dotenv.read_text(encoding="utf-8") == original
            assert not list(tmp_path.glob(".env.*.tmp"))
            assert not opened.config.exists()
    finally:
        opened.dotenv.chmod(0o600)


def test_deleting_connection_removes_its_persisted_key_and_keeps_other_keys(tmp_path):
    opened = _Opened(tmp_path)
    opened.dotenv.write_text("OTHER_KEY=unrelated-key\n", encoding="utf-8")
    with running_api(opened) as client:
        _connect(client, "http://localhost:1/v1")
        _collected(opened)
        response = _command(client, "catalog.connection.delete", base_version=_catalog(client)["revision"],
                            provider_id="localhost")
        assert response.status_code == 200, response.text
        assert _catalog(client)["providers"] == []
        text = opened.dotenv.read_text(encoding="utf-8")
        assert "LOCALHOST_KEY" not in text and SECRET not in text and "OTHER_KEY=unrelated-key" in text
    with running_api(opened) as client:
        assert _catalog(client)["providers"] == []


@pytest.mark.skipif(os.name != "posix", reason="Windows 使用目录 ACL")
def test_saving_key_restricts_an_existing_dotenv_file_to_the_owner(tmp_path):
    opened = _Opened(tmp_path)
    opened.dotenv.write_text("OTHER_KEY=unrelated-key\n", encoding="utf-8")
    opened.dotenv.chmod(0o644)
    with running_api(opened) as client:
        _connect(client, "http://localhost:1/v1")
        _collected(opened)
        assert opened.dotenv.stat().st_mode & 0o777 == 0o600


def test_connect_requires_a_key_for_a_new_connection(tmp_path):
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        response = _command(client, "catalog.connect", base_version=_catalog(client)["revision"],
                            base_url="http://localhost:1/v1")
        assert response.status_code == 409 and response.json()["reason"] == "catalog_invalid"
        assert "API Key" in response.json()["message"]
        assert _catalog(client)["providers"] == [] and not opened.dotenv.exists()


def test_connect_command_replay_returns_the_same_result_without_repeating_the_collection(tmp_path):
    # R2：相同命令身份与内容的重发，连接、凭据和上游读取都只做一次。
    upstream = ScriptedProvider([_json_reply({"data": [{"id": "model"}]})])
    opened = _Opened(tmp_path)
    try:
        with running_api(opened) as client:
            request = {"command_id": str(uuid.uuid4()), "base_version": _catalog(client)["revision"],
                       "base_url": upstream.base + "/v1", "api_key": SECRET}
            first = client.post("/api/commands/catalog.connect", json=request)
            assert first.status_code == 200, first.text
            _collected(opened)
            version = _catalog(client)["providers"][0]["credential"]["version"]
            second = client.post("/api/commands/catalog.connect", json=request)
            assert second.status_code == 200, second.text
            assert second.json() == {**first.json(), "duplicate": True}
            assert _catalog(client)["providers"][0]["credential"]["version"] == version
            assert len(upstream.requests) == 1
            assert len(opened.store.read(0, limit=10000, types=[CatalogEventType.CATALOG_CANDIDATES_COLLECTED])) == 1
    finally:
        upstream.close()
