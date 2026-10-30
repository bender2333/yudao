"""R2、R3：通过真实 HTTP、SQLite、文件与公开目录合同核对选用即启用。"""
from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from harness.app.application import Application
from harness.models import CatalogEventType
from harness.tests.api_helpers import running_api
from harness.tests.protocol_helpers import ScriptedProvider, model_test_responder, send_reply
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

SECRET = "selection-key-do-not-publish"


class Opened:
    def __init__(self, root):
        self.data_dir = root / "data"
        self.config = root / "providers.json"
        self.dotenv = root / ".env"
        self.applications = []

    def __call__(self):
        application = Application.open(self.data_dir, provider_config=self.config, dotenv=self.dotenv)
        self.applications.append(application)
        return application

    @property
    def application(self):
        return self.applications[-1]


def catalog(client):
    response = client.get("/api/queries/catalog")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def command(client, name, **values):
    return client.post(f"/api/commands/{name}", json={"command_id": str(uuid.uuid4()), **values})


def wait_catalog(client, predicate):
    deadline = time.monotonic() + min(WAIT_FOR_HOST_WORK_SEC, 30)
    while time.monotonic() < deadline:
        result = catalog(client)
        if predicate(result):
            return result
        time.sleep(0.01)
    raise AssertionError(f"等待目录状态超时：{result}")


def responder(models):
    def respond(_provider, handler):
        if handler.body is None:
            send_reply(handler, 200, "application/json", json.dumps({"data": models}).encode())
            return
        status, content_type, chunks = model_test_responder(
            handler.body, protocol="chat_completions", actual_model=handler.body["model"])
        send_reply(handler, status, content_type, b"".join(chunks))
    return respond


def connect(client, upstream):
    response = command(client, "catalog.connect", base_version=catalog(client)["revision"],
                       base_url=upstream.base + "/v1", api_key=SECRET)
    assert response.status_code == 200, response.text
    provider_id = response.json()["refs"]["provider_id"]
    wait_catalog(client, lambda data: data["providers"][0]["latest_candidates"] is not None)
    return provider_id


def select(client, provider_id, model, **values):
    response = command(client, "catalog.model.select", base_version=catalog(client)["revision"],
                       provider_id=provider_id, model=model, **values)
    assert response.status_code == 200, response.text
    return response


def test_select_completes_and_tests_upstream_capacity_then_preserves_it_on_restart(tmp_path):
    # R3：一次选用产生可用定义、来源、独立准入与默认设置；重启保持已完成的事实。
    upstream = ScriptedProvider([responder([
        {"id": "maker/ready", "limit": {"context": 128000, "output": 8192},
         "modalities": {"input": ["text", "image"], "output": ["text"]}}
    ])] * 12)
    opened = Opened(tmp_path)
    try:
        with running_api(opened) as client:
            provider_id = connect(client, upstream)
            select(client, provider_id, "maker/ready")
            data = wait_catalog(client, lambda data: any(row["admitted"] for row in data["admissions"]))
            [model] = data["models"]
            assert model["context_window"] == 128000 and model["max_output_tokens"] == 8192
            assert model["input_modalities"] == ["text", "image"]
            assert model["source_details"]["context_window"]["source"] == "models_url"
            assert model["source_details"]["max_output_tokens"]["source"] == "models_url"
            assert data["bindings"] == {
                department: {"provider_id": provider_id, "model_id": model["id"], "requested_tier": None}
                for department in ("product", "engineering", "quality")}
            assert data["selections"] == []
            # 重复选用复用已准入定义，不再次向上游发出模型测试请求。
            count = len(upstream.requests)
            select(client, provider_id, "maker/ready")
            assert catalog(client)["models"] == data["models"]
            assert len(upstream.requests) == count
            facts = opened.application.system.store.read(0, limit=10000)
            assert any(event.type == CatalogEventType.CATALOG_TEST_FINISHED for event in facts)
            assert SECRET not in json.dumps([event.payload for event in facts])
            assert SECRET not in json.dumps(data)
        with running_api(opened) as client:
            restarted = catalog(client)
            assert restarted["models"] == data["models"]
            assert restarted["admissions"][0]["admitted"] is True
            assert restarted["bindings"] == data["bindings"]
            assert restarted["selections"] == []
    finally:
        upstream.close()


def test_unknown_capacity_continues_with_manual_values_and_manual_add_uses_the_same_flow(tmp_path):
    # R3：未知容量保持候选；填写缺少的参数与手动添加都经过同样的真实模型测试。
    upstream = ScriptedProvider([responder([{"id": "unknown"}])] * 20)
    opened = Opened(tmp_path)
    try:
        with running_api(opened) as client:
            provider_id = connect(client, upstream)
            select(client, provider_id, "unknown")
            data = catalog(client)
            [pending] = data["selections"]
            assert pending["status"] == "capacity_unknown"
            assert pending["missing"] == ["context_window", "max_output_tokens"]
            assert data["models"][0]["max_output_tokens"] is None
            assert not data["admissions"] and not data["bindings"]
            assert upstream.requests == [None]
            select(client, provider_id, "unknown", context_window=64000, max_output_tokens=4096)
            data = wait_catalog(client, lambda data: any(row["admitted"] for row in data["admissions"]))
            model = data["models"][0]
            assert model["context_window"] == 64000 and model["max_output_tokens"] == 4096
            assert model["source_details"]["context_window"]["source"] == "manual"
            assert model["source_details"]["max_output_tokens"]["source"] == "manual"
            original = data["bindings"]
            select(client, provider_id, "not-in-list", protocol="chat_completions",
                   context_window=32000, max_output_tokens=2048)
            data = wait_catalog(client, lambda data: len([row for row in data["admissions"] if row["admitted"]]) == 2)
            manual = next(row for row in data["models"] if row["model"] == "not-in-list")
            assert manual["source_details"]["protocol"]["source"] == "manual"
            assert manual["source_details"]["context_window"]["source"] == "manual"
            assert data["bindings"] == original
            assert any(row and row["model"] == "not-in-list" for row in upstream.requests)
    finally:
        upstream.close()


def test_five_selections_share_three_test_slots_reuse_inflight_and_first_pass_wins(tmp_path):
    # R3：真实请求的进入与放行信号决定顺序，等候项不会越过同时测试上限。
    names = [f"model-{index}" for index in range(5)]
    entered = set()
    condition = threading.Condition()
    releases = {name: threading.Event() for name in names}
    normal = responder([{"id": name, "limit": {"context": 32000, "output": 2048}} for name in names])

    def gated(provider, handler):
        if handler.body is not None and not handler.body.get("tools"):
            name = handler.body["model"]
            with condition:
                entered.add(name)
                condition.notify_all()
            assert releases[name].wait(30), "等待测试放行模型请求"
        normal(provider, handler)

    upstream = ScriptedProvider([gated] * 30)
    opened = Opened(tmp_path)
    try:
        with running_api(opened) as client:
            provider_id = connect(client, upstream)
            for name in names:
                select(client, provider_id, name)
            with condition:
                assert condition.wait_for(lambda: len(entered) == 3, timeout=30)
            data = catalog(client)
            assert sorted(row["status"] for row in data["selections"]) == ["testing"] * 3 + ["waiting"] * 2
            assert len({row["sequence"] for row in data["selections"]}) == 5
            first_attempt = next(row for row in data["selections"] if row["model"] == names[1])
            count = len(upstream.requests)
            select(client, provider_id, names[1])
            assert next(row for row in catalog(client)["selections"] if row["model"] == names[1]) == first_attempt
            assert len(upstream.requests) == count
            releases[names[1]].set()
            data = wait_catalog(client, lambda data: bool(data["bindings"]))
            winner = next(row["id"] for row in data["models"] if row["model"] == names[1])
            assert {row["model_id"] for row in data["bindings"].values()} == {winner}
            with condition:
                assert condition.wait_for(lambda: len(entered) == 4, timeout=30)
            data = catalog(client)
            assert sum(row["status"] == "testing" for row in data["selections"]) == 3
            assert sum(row["status"] == "waiting" for row in data["selections"]) == 1
            for release in releases.values():
                release.set()
            data = wait_catalog(client, lambda data: len(data["admissions"]) == 5 and not data["selections"])
            assert all(row["admitted"] for row in data["admissions"])
            assert {row["model_id"] for row in data["bindings"].values()} == {winner}
    finally:
        for release in releases.values():
            release.set()
        upstream.close()


def test_live_progress_matches_catalog_and_unfinished_selections_are_candidates_after_restart(tmp_path):
    # R2、R3：实时消息与刷新查询表达同一份进程状态；它不会成为可重放的目录事实。
    normal = responder([{"id": "pending", "limit": {"context": 64000, "output": 4096}}])

    def held(provider, handler):
        if handler.body is not None:
            provider.held.set()
            assert provider.release.wait(30), "等待重启取消进行中的模型请求"
        normal(provider, handler)

    upstream = ScriptedProvider([normal, held, *[normal] * 8])
    opened = Opened(tmp_path)
    ready = threading.Event()

    def progress(client):
        deadline = time.monotonic() + 15
        with client.stream("GET", "/api/events", params={"live": 1}) as response:
            response.raise_for_status()
            ready.set()
            kind = None
            for line in response.iter_lines():
                if time.monotonic() > deadline:
                    raise AssertionError("等待选用进度超时")
                if line.startswith("event:"):
                    kind = line.partition(":")[2].strip()
                elif line.startswith("data:") and kind == "catalog_selection":
                    data = json.loads(line.partition(":")[2].strip())
                    if data["selections"] and data["selections"][0]["status"] == "testing":
                        return data
        raise AssertionError("没有收到选用测试的实时状态")

    try:
        with running_api(opened) as client:
            assert "CatalogSelectionProgress" in client.get("/openapi.json").json()["components"]["schemas"]
            provider_id = connect(client, upstream)
            with ThreadPoolExecutor(max_workers=1) as pool:
                received = pool.submit(progress, client)
                assert ready.wait(10)
                select(client, provider_id, "pending")
                assert upstream.held.wait(10)
                payload = received.result(timeout=10)
                data = catalog(client)
                assert payload["selections"] == data["selections"]
                assert data["selections"][0]["sequence"] > 0
            facts = opened.application.system.store.read(0, limit=10000)
            assert all(event.type != "catalog_selection" for event in facts)
            assert all(event.payload.get("status") not in {"completing", "waiting", "testing"} for event in facts)
        with running_api(opened) as client:
            restarted = catalog(client)
            assert restarted["selections"] == []
            assert restarted["models"] == data["models"]
            assert not restarted["admissions"] and not restarted["bindings"]
            select(client, provider_id, "pending")
            enabled = wait_catalog(client, lambda result: bool(result["admissions"]))
            assert enabled["admissions"][0]["admitted"] is True
    finally:
        upstream.close()
