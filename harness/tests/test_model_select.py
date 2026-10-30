"""R2、R3：通过真实 HTTP、SQLite、文件与公开目录合同核对选用即启用。"""
from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

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


def command(client, operation, **values):
    return client.post(f"/api/commands/{operation}", json={"command_id": str(uuid.uuid4()), **values})


def wait_catalog(client, predicate):
    deadline = time.monotonic() + min(WAIT_FOR_HOST_WORK_SEC, 30)
    while time.monotonic() < deadline:
        result = catalog(client)
        if predicate(result):
            return result
        time.sleep(0.01)
    raise AssertionError(f"等待目录状态超时：{result}")


def wait_event(opened, predicate, *, after=0):
    arrived = threading.Event()
    found = []

    def receive(events):
        for event in events:
            if event.position > after and predicate(event):
                found.append(event)
                arrived.set()

    store = opened.application.system.store
    unsubscribe = store.subscribe(receive)
    try:
        receive(store.read(after, limit=10000))
        assert arrived.wait(30), "等待目录结果事件超时"
        return found[-1]
    finally:
        unsubscribe()


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


def test_cancel_and_reselect_ignores_the_old_final_response(tmp_path):
    # R3：旧测试最后一步到达前取消并重选，旧结果没有权限准入新的选用。
    normal = responder([{"id": "again", "limit": {"context": 32000, "output": 2048}}])
    old_entered, old_release, old_returned = threading.Event(), threading.Event(), threading.Event()
    new_entered, new_release = threading.Event(), threading.Event()

    def old_final(provider, handler):
        old_entered.set()
        assert old_release.wait(30), "等待旧模型测试结果放行"
        try:
            normal(provider, handler)
        finally:
            old_returned.set()

    def new_first(provider, handler):
        new_entered.set()
        assert new_release.wait(30), "等待重新选用的模型请求放行"
        normal(provider, handler)

    upstream = ScriptedProvider([normal, normal, normal, old_final, new_first, normal, normal])
    opened = Opened(tmp_path)
    try:
        with running_api(opened) as client:
            provider_id = connect(client, upstream)
            select(client, provider_id, "again")
            assert old_entered.wait(10)
            [old] = catalog(client)["selections"]
            cancelled = command(client, "catalog.model.remove", base_version=catalog(client)["revision"],
                                provider_id=provider_id, model_id=old["model_id"])
            assert cancelled.status_code == 200, cancelled.text
            assert catalog(client)["selections"] == [] and catalog(client)["models"] == []
            select(client, provider_id, "again")
            assert new_entered.wait(10)
            [new] = catalog(client)["selections"]
            assert new["sequence"] > old["sequence"]
            old_release.set()
            assert old_returned.wait(10)
            data = catalog(client)
            assert data["admissions"] == [] and data["bindings"] == {}
            assert data["selections"] == [new]
            new_release.set()
            data = wait_catalog(client, lambda data: bool(data["admissions"]))
            assert data["admissions"][0]["admitted"] is True
            results = [event for event in opened.application.system.store.read(0, limit=10000)
                       if event.type == CatalogEventType.CATALOG_TEST_FINISHED and event.payload["kind"] == "model"]
            assert [event.payload["selection_sequence"] for event in results] == [new["sequence"]]
    finally:
        old_release.set()
        new_release.set()
        upstream.close()


def test_all_existing_binding_keys_and_project_references_block_removal_and_defaults_are_preserved(tmp_path):
    # R3：目录的全部绑定键与真实项目设置都参与引用保护，自动默认只填写未设置的部门。
    models = [{"id": name, "limit": {"context": 32000, "output": 2048}} for name in ("existing", "next")]
    upstream = ScriptedProvider([responder(models)] * 20)
    opened = Opened(tmp_path)
    try:
        with running_api(opened) as client:
            provider_id = connect(client, upstream)
            select(client, provider_id, "existing")
            data = wait_catalog(client, lambda data: bool(data["admissions"]))
            first_id = data["models"][0]["id"]
            binding = {"provider_id": provider_id, "model_id": first_id}
            saved = command(client, "catalog.department_defaults.save", base_version=data["revision"],
                            bindings={"product": binding, "role.custom": binding})
            assert saved.status_code == 200, saved.text
            created = command(client, "project.create", name="引用保护", goal="验证项目的模型引用")
            assert created.status_code == 200, created.text
            project_id = created.json()["refs"]["project_id"]
            configured = command(client, "department_settings.save", base_version=0, project_id=project_id,
                                 department="engineering", **binding)
            assert configured.status_code == 200, configured.text
            rejected = command(client, "catalog.model.remove", base_version=catalog(client)["revision"],
                               provider_id=provider_id, model_id=first_id)
            assert rejected.status_code == 409 and rejected.json()["reason"] == "in_use", rejected.text
            for reference in ("bindings.product", "bindings.role.custom",
                              f"projects.{project_id}.department_settings.engineering"):
                assert reference in rejected.json()["message"]
            select(client, provider_id, "next")
            data = wait_catalog(client, lambda data: len(data["admissions"]) == 2)
            next_id = next(row["id"] for row in data["models"] if row["model"] == "next")
            assert data["bindings"]["product"]["model_id"] == first_id
            assert data["bindings"]["role.custom"]["model_id"] == first_id
            assert data["bindings"]["engineering"] == {
                "provider_id": provider_id, "model_id": next_id, "requested_tier": None}
            assert data["bindings"]["quality"]["model_id"] == next_id
            after = command(client, "catalog.model.remove", base_version=data["revision"],
                            provider_id=provider_id, model_id=first_id)
            assert after.status_code == 409
            assert f"projects.{project_id}.department_settings.engineering" in after.json()["message"]
    finally:
        upstream.close()


def test_key_change_keeps_admissions_and_tests_connection_then_address_change_retests_new_candidates(tmp_path):
    # R3：Key 测连而不重做准入；地址按新候选重新配置，移出列表的定义保留引用并显示原因。
    old_models = [{"id": name, "limit": {"context": 32000, "output": 2048}} for name in ("remain", "gone")]
    old = ScriptedProvider([responder(old_models)] * 24)
    new_normal = responder([{"id": "remain", "limit": {"context": 256000, "output": 16384}}])

    def new_held(provider, handler):
        if handler.body is not None and not handler.body.get("tools"):
            provider.held.set()
            assert provider.release.wait(30), "等待地址修改的重新测试放行"
        new_normal(provider, handler)

    new = ScriptedProvider([new_held] * 12)
    opened = Opened(tmp_path)
    try:
        with running_api(opened) as client:
            provider_id = connect(client, old)
            for name in ("remain", "gone"):
                select(client, provider_id, name)
            before = wait_catalog(client, lambda data: len(data["admissions"]) == 2 and not data["selections"])
            after_position = opened.application.system.store.end_position()
            count = len(old.requests)
            replaced = command(client, "catalog.connect", base_version=before["revision"],
                               base_url=old.base + "/v1", api_key="replacement-selection-secret")
            assert replaced.status_code == 200, replaced.text
            connected = wait_event(opened, lambda event: event.type == CatalogEventType.CATALOG_TEST_FINISHED
                                   and event.payload["kind"] == "connection", after=after_position)
            assert connected.payload["ok"] is True
            assert catalog(client)["admissions"] == before["admissions"]
            assert old.requests[count:] and all(body is None for body in old.requests[count:])
            provider = catalog(client)["providers"][0]
            fields = ("id", "name", "base_url", "credential_ref", "timeout_sec", "preset_id", "models_url")
            changed = command(client, "catalog.connection.save", base_version=catalog(client)["revision"],
                              provider={**{key: provider[key] for key in fields}, "base_url": new.base + "/v1"},
                              models=[{key: value for key, value in row.items() if key != "provider_id"}
                                      for row in before["models"]])
            assert changed.status_code == 200, changed.text
            assert new.held.wait(10), "地址修改后没有启动新候选的模型测试"
            pending = catalog(client)
            assert all(row["stale"] and not row["admitted"] for row in pending["admissions"])
            assert pending["bindings"] == before["bindings"]
            [missing] = [row for row in pending["selections"] if row["model"] == "gone"]
            assert missing["status"] == "not_in_list" and "不在新的模型列表中" in missing["error"]
            remain = next(row for row in pending["models"] if row["model"] == "remain")
            assert remain["context_window"] == 256000 and remain["max_output_tokens"] == 16384
            new.release.set()
            enabled = wait_catalog(client, lambda data: any(row["admitted"] for row in data["admissions"]))
            assert next(row for row in enabled["admissions"] if row["model"] == "remain")["admitted"] is True
            assert next(row for row in enabled["admissions"] if row["model"] == "gone")["stale"] is True
            assert enabled["bindings"] == before["bindings"]
            facts = opened.application.system.store.read(0, limit=10000)
            assert "replacement-selection-secret" not in json.dumps([event.payload for event in facts])
            assert "replacement-selection-secret" not in json.dumps(enabled)
    finally:
        old.close()
        new.close()


def test_concurrency_rule_consumes_current_values_and_rejects_values_outside_one_to_eight(tmp_path):
    # R2、R3：规则的界限为 1..8，改动现值会实际改变等待队列可以开始的模型数。
    condition = threading.Condition()
    entered = set()
    release = threading.Event()
    normal = responder([{"id": f"config-{index}", "limit": {"context": 32000, "output": 2048}}
                        for index in range(3)])

    def gated(provider, handler):
        if handler.body is not None and not handler.body.get("tools"):
            with condition:
                entered.add(handler.body["model"])
                condition.notify_all()
            assert release.wait(30), "等待规则并发测试放行"
        normal(provider, handler)

    upstream = ScriptedProvider([gated] * 20)
    opened = Opened(tmp_path)
    try:
        with running_api(opened) as client:
            provider_id = connect(client, upstream)
            for value in (0, 9):
                rejected = command(client, "parameter.set", name="provider.model_test_max_concurrent", value=value,
                                   reason="核对设计界限", modified_by="selection-test")
                assert rejected.status_code == 409 and rejected.json()["reason"] == "out_of_bounds"
            changed = command(client, "parameter.set", name="provider.model_test_max_concurrent", value=1,
                              reason="核对单个模型测试名额", modified_by="selection-test")
            assert changed.status_code == 200, changed.text
            for index in range(3):
                select(client, provider_id, f"config-{index}")
            with condition:
                assert condition.wait_for(lambda: len(entered) == 1, timeout=10)
            states = catalog(client)["selections"]
            assert sorted(row["status"] for row in states) == ["testing", "waiting", "waiting"]
            raised = command(client, "parameter.set", name="provider.model_test_max_concurrent", value=8,
                             reason="核对上界并放行等待模型", modified_by="selection-test")
            assert raised.status_code == 200, raised.text
            with condition:
                assert condition.wait_for(lambda: len(entered) == 3, timeout=10)
            assert all(row["status"] == "testing" for row in catalog(client)["selections"])
            release.set()
            enabled = wait_catalog(client, lambda data: len(data["admissions"]) == 3)
            assert all(row["admitted"] for row in enabled["admissions"])
    finally:
        release.set()
        upstream.close()


def test_removed_admission_cannot_reappear_when_the_same_model_is_selected_after_restart(tmp_path):
    # R3：取消未被引用的已准入定义后，旧的磁盘准入不能授权重启后的新选用。
    normal = responder([{"id": "recreated", "limit": {"context": 32000, "output": 2048}}])

    def held(provider, handler):
        provider.held.set()
        assert provider.release.wait(30), "等待重建的定义完成新测试"
        normal(provider, handler)

    upstream = ScriptedProvider([normal, normal, normal, normal, held, normal, normal])
    opened = Opened(tmp_path)
    try:
        with running_api(opened) as client:
            provider_id = connect(client, upstream)
            select(client, provider_id, "recreated")
            data = wait_catalog(client, lambda data: bool(data["admissions"]))
            cleared = command(client, "catalog.department_defaults.save", base_version=data["revision"], bindings={})
            assert cleared.status_code == 200, cleared.text
            removed = command(client, "catalog.model.remove", base_version=catalog(client)["revision"],
                              provider_id=provider_id, model_id=data["models"][0]["id"])
            assert removed.status_code == 200, removed.text
        with running_api(opened) as client:
            select(client, provider_id, "recreated", protocol="chat_completions",
                   context_window=32000, max_output_tokens=2048)
            assert upstream.held.wait(10)
            assert catalog(client)["admissions"] == []
            assert catalog(client)["bindings"] == {}
            upstream.release.set()
            data = wait_catalog(client, lambda data: bool(data["admissions"]))
            assert data["admissions"][0]["admitted"] is True
    finally:
        upstream.close()


@pytest.mark.parametrize("protocol", ["responses", "chat_completions", "messages"])
def test_failed_tool_test_can_retry_through_the_same_bounded_selection_flow(protocol, tmp_path):
    # R3：手动声明三种协议均使用真实两组测试；不调用工具时失败，重新测试生成新的选用序号。
    listing = responder([{"id": "retry", "limit": {"context": 32000, "output": 2048}}])

    def reply(without_tools=False):
        def respond(_provider, handler):
            body = {**handler.body, "tools": []} if without_tools else handler.body
            status, content_type, chunks = model_test_responder(body, protocol=protocol, actual_model="retry")
            send_reply(handler, status, content_type, b"".join(chunks))
        return respond

    upstream = ScriptedProvider([listing, reply(), reply(True), reply(), reply(), reply()])
    opened = Opened(tmp_path)
    try:
        with running_api(opened) as client:
            provider_id = connect(client, upstream)
            select(client, provider_id, "retry", protocol=protocol)
            failed = wait_catalog(client, lambda data: data["selections"]
                                  and data["selections"][0]["status"] == "failed")
            assert not failed["admissions"] and not failed["bindings"]
            [attempt] = failed["selections"]
            assert "工具往返" in attempt["error"]
            retried = command(client, "catalog.model.test", base_version=failed["revision"],
                              provider_id=provider_id, model_id=attempt["model_id"])
            assert retried.status_code == 200, retried.text
            enabled = wait_catalog(client, lambda data: bool(data["admissions"]))
            assert enabled["admissions"][0]["admitted"] is True
            assert enabled["models"][0]["protocol"] == protocol
            event = wait_event(opened, lambda event: event.type == CatalogEventType.CATALOG_TEST_FINISHED
                               and event.payload["admitted"] is True)
            assert event.payload["selection_sequence"] > attempt["sequence"]
    finally:
        upstream.close()


def test_non_text_candidates_and_invalid_capacity_are_rejected_without_selecting(tmp_path):
    # R2、R3：输出非文本的候选与无效容量无法越过选用命令，失败不产生定义或准入。
    upstream = ScriptedProvider([responder([
        {"id": "picture", "limit": {"context": 32000, "output": 2048},
         "modalities": {"output": ["image"]}}, {"id": "unknown"}])])
    opened = Opened(tmp_path)
    try:
        with running_api(opened) as client:
            provider_id = connect(client, upstream)
            for model, values, status in (("picture", {}, 409),
                                           ("unknown", {"context_window": 0, "max_output_tokens": 10}, 422),
                                           ("unknown", {"context_window": 10, "max_output_tokens": 20}, 409)):
                rejected = command(client, "catalog.model.select", base_version=catalog(client)["revision"],
                                   provider_id=provider_id, model=model, **values)
                assert rejected.status_code == status, rejected.text
            data = catalog(client)
            assert data["models"] == [] and data["admissions"] == [] and data["selections"] == []
            assert upstream.requests == [None]
    finally:
        upstream.close()


def test_manual_capacity_fills_only_fields_missing_from_the_upstream_list(tmp_path):
    # R3：窗口与输出上限各自按来源优先级补全，手填的批量值只补缺少的字段。
    upstream = ScriptedProvider([responder([
        {"id": "known-window", "limit": {"context": 256000}},
        {"id": "known-output", "limit": {"output": 8192}}])] * 12)
    opened = Opened(tmp_path)
    try:
        with running_api(opened) as client:
            provider_id = connect(client, upstream)
            for name in ("known-window", "known-output"):
                select(client, provider_id, name, context_window=32000, max_output_tokens=4096)
            enabled = wait_catalog(client, lambda data: len(data["admissions"]) == 2)
            window = next(row for row in enabled["models"] if row["model"] == "known-window")
            assert window["context_window"] == 256000 and window["max_output_tokens"] == 4096
            assert window["source_details"]["context_window"]["source"] == "models_url"
            assert window["source_details"]["max_output_tokens"]["source"] == "manual"
            output = next(row for row in enabled["models"] if row["model"] == "known-output")
            assert output["context_window"] == 32000 and output["max_output_tokens"] == 8192
            assert output["source_details"]["context_window"]["source"] == "manual"
            assert output["source_details"]["max_output_tokens"]["source"] == "models_url"
    finally:
        upstream.close()
