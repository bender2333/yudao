import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from harness.app.application import Application
from harness.models import CatalogEventType
from harness.tests.api_helpers import running_api
from harness.tests.protocol_helpers import responses_responder, serve

# 模型目录与凭据的查询与命令：真实启动 FastAPI 应用，目录文件与 .env 是真实文件，事件日志是真实 SQLite；
# 连接测试与模型测试经测试内启动的真实 HTTP 服务，不使用桩替身。

SECRET = "catalog-secret-key-1"
REF = "CATALOG_KEY"
DEPARTMENTS = ("product", "engineering", "quality")
UPSTREAM_BASE = "http://127.0.0.1:9/v1"


def _provider(provider_id="p1", *, base_url=UPSTREAM_BASE, models_url=""):
    return {"id": provider_id, "name": provider_id, "protocol": "responses", "base_url": base_url,
            "credential_ref": REF, "timeout_sec": 20.0, "preset_id": "", "models_url": models_url}


def _model(model_id="m1", *, model="model-x"):
    # 连接保存用的模型访问定义：所属连接由命令参数给出，协议取自连接；
    # 每一行带容量确认（工单 #86）
    return {"id": model_id, "model": model, "capacity_confirmed": True,
            "context_window": 32000, "max_output_tokens": 2048}


def _document_model(provider_id, model_id="m1"):
    # 目录文档中的定义自己带上所属连接；文档不带逐行容量确认标记（工单 #86）
    return {key: value for key, value in {**_model(model_id), "provider_id": provider_id}.items()
            if key != "capacity_confirmed"}


def _document(*, provider_id="p1", model_id="m1", base_url=UPSTREAM_BASE, models_url="", bindings=None):
    return {"providers": [_provider(provider_id, base_url=base_url, models_url=models_url)],
            "models": [_document_model(provider_id, model_id)],
            "bindings": dict(bindings or {})}


class _Opened:
    # 服务生命周期中建立的应用层；目录文件与 .env 由测试准备，测试经它读取事件日志核对结果
    def __init__(self, tmp_path, document=None) -> None:
        self.data_dir = tmp_path / "data"
        self.config = tmp_path / "providers.json"
        self.dotenv = tmp_path / ".env"
        self.dotenv.write_text(f"{REF}={SECRET}\n", encoding="utf-8")
        self.config.write_text(json.dumps(_document() if document is None else document), encoding="utf-8")
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


def _catalog(client):
    response = client.get("/api/queries/catalog")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _command(client, name, **body):
    return client.post(f"/api/commands/{name}", json={"command_id": str(uuid.uuid4()), **body})


def _catalog_events(store):
    return store.read(0, limit=100_000, types=[value for key, value in vars(CatalogEventType).items()
                                              if not key.startswith("_")])


def _wait_for(store, predicate, *, timeout=15.0, description="catalog event"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        matched = [event for event in _catalog_events(store) if predicate(event)]
        if matched:
            return matched
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {description}")


def _payload_of(event):
    return event.payload


def _assert_no_secret(client, opened, secret=SECRET):
    dumped = json.dumps([event.payload for event in _catalog_events(opened.store)], ensure_ascii=False)
    assert secret not in dumped
    for path in ("catalog", "catalog.document"):
        response = client.get(f"/api/queries/{path}")
        assert response.status_code == 200, response.text
        assert secret not in response.text


def _write_document(path, document):
    path.write_text(json.dumps(document), encoding="utf-8")


def test_startup_backfills_catalog_revised_and_stale_base_is_rejected(tmp_path):
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        # 启动时目录修订号与最后一条 catalog_revised 不同：补写一条
        [startup] = _wait_for(opened.store, lambda event: event.payload["operation"] == "startup",
                              timeout=5.0, description="startup catalog_revised")
        before = _catalog(client)
        assert startup.payload["revision"] == before["revision"] >= 1
        assert startup.actor == "system" and startup.command_id is None

        # 保存连接：事件带新修订号，查询返回同一修订号
        provider = _provider("p2")
        response = _command(client, "catalog.connection.save", base_version=before["revision"],
                            provider=provider, models=[_model("m2")])
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["refs"] == {"provider_id": "p2"} and body["duplicate"] is False
        [saved] = _wait_for(opened.store, lambda event: event.payload.get("operation") == "save_connection",
                            timeout=5.0, description="save_connection catalog_revised")
        after = _catalog(client)
        assert saved.payload["revision"] == after["revision"] > before["revision"]
        assert saved.payload["provider_id"] == "p2" and saved.payload["base_revision"] == before["revision"]
        assert saved.command_id == body["command_id"] and saved.actor == "user:local"
        assert [item["id"] for item in after["providers"]] == ["p1", "p2"]
        _assert_no_secret(client, opened)

        # 基于旧修订号的保存被拒绝
        stale = _command(client, "catalog.connection.save", base_version=before["revision"],
                         provider=_provider("p3"), models=[_model("m3")])
        assert stale.status_code == 409, stale.text
        assert stale.json()["reason"] == "stale_base"
        assert stale.json()["current_version"] == after["revision"]
        assert _catalog(client)["revision"] == after["revision"]


def test_connection_delete_lists_referrers_and_removes_the_definitions(tmp_path):
    bindings = {department: {"provider_id": "p1", "model_id": "m1"} for department in DEPARTMENTS}
    opened = _Opened(tmp_path, _document(bindings=bindings))
    with running_api(opened) as client:
        current = _catalog(client)["revision"]

        # 仍被部门默认引用：拒绝并列出引用方
        referenced = _command(client, "catalog.connection.delete", base_version=current, provider_id="p1")
        assert referenced.status_code == 409, referenced.text
        payload = referenced.json()
        assert payload["reason"] == "in_use" and payload["current_version"] is None
        assert "bindings.product" in payload["message"] and "bindings.quality" in payload["message"]
        assert _catalog(client)["revision"] == current

        # 旧修订号：stale_base
        spare = _command(client, "catalog.connection.save", base_version=current,
                         provider=_provider("p2"), models=[_model("m2")])
        assert spare.status_code == 200, spare.text
        latest = _catalog(client)["revision"]
        stale = _command(client, "catalog.connection.delete", base_version=current, provider_id="p2")
        assert stale.status_code == 409 and stale.json()["reason"] == "stale_base"
        assert stale.json()["current_version"] == latest

        # 没有引用时连同定义一起删除
        deleted = _command(client, "catalog.connection.delete", base_version=latest, provider_id="p2")
        assert deleted.status_code == 200, deleted.text
        [event] = _wait_for(opened.store, lambda item: item.payload.get("operation") == "delete_connection",
                            timeout=5.0, description="delete_connection catalog_revised")
        after = _catalog(client)
        assert event.payload["revision"] == after["revision"] > latest
        assert [item["id"] for item in after["providers"]] == ["p1"]
        assert [item["id"] for item in after["models"]] == ["m1"]


def test_document_import_and_department_defaults_write_events(tmp_path):
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        current = _catalog(client)["revision"]
        # 保存部门默认要求所选定义已准入（工单 #86）：先经模块接口记录模型测试通过的事实
        opened.application.system.facade.record_admission("p1", "m1", admitted_model="model-x")
        bindings = {department: {"provider_id": "p1", "model_id": "m1"} for department in DEPARTMENTS}
        defaults = _command(client, "catalog.department_defaults.save", base_version=current, bindings=bindings)
        assert defaults.status_code == 200, defaults.text
        [bound] = _wait_for(opened.store, lambda item: item.payload.get("operation") == "department_defaults",
                            timeout=5.0, description="department_defaults catalog_revised")
        after_defaults = _catalog(client)
        assert bound.payload["revision"] == after_defaults["revision"] > current
        assert set(after_defaults["bindings"]) == set(DEPARTMENTS)

        # 导入整份文档：整体替换，事件与查询返回同一修订号。
        # 先清空部门默认：导入移除仍被默认引用的定义会整份拒绝（工单 #90），
        # 清空以后导入就可以把目录整体换成另一份
        cleared = _command(client, "catalog.department_defaults.save",
                           base_version=after_defaults["revision"], bindings={})
        assert cleared.status_code == 200, cleared.text
        current = _catalog(client)["revision"]
        # 部门默认只能引用已准入的定义（设计说明第 4.6 节）：导入前先保存新连接并记录它的准入
        added = _command(client, "catalog.connection.save", base_version=current,
                         provider=_provider("p3"), models=[_model("m3")])
        assert added.status_code == 200, added.text
        opened.application.system.facade.record_admission("p3", "m3", admitted_model="model-x")
        current = _catalog(client)["revision"]
        imported = _command(client, "catalog.document.save", base_version=current,
                            document={"providers": [_provider("p3")], "models": [_document_model("p3", "m3")],
                                      "bindings": {department: {"provider_id": "p3", "model_id": "m3"}
                                                   for department in DEPARTMENTS}})
        assert imported.status_code == 200, imported.text
        [event] = _wait_for(opened.store, lambda item: item.payload.get("operation") == "save_document",
                            timeout=5.0, description="save_document catalog_revised")
        after = _catalog(client)
        assert event.payload["revision"] == after["revision"] > current
        assert [item["id"] for item in after["providers"]] == ["p3"]
        assert set(after["bindings"]) == set(DEPARTMENTS)
        assert {binding["model_id"] for binding in after["bindings"].values()} == {"m3"}
        document = client.get("/api/queries/catalog.document").json()["data"]
        assert [item["id"] for item in document["providers"]] == ["p3"]
        assert document["revision"] == after["revision"]
        _assert_no_secret(client, opened)


def test_department_defaults_carry_the_requested_tier(tmp_path):
    # 部门默认保存可为空的请求档位（设计说明第 5.1 节，工单 #87）：请求档位只核对它属于档位全集，
    # 保存后查询把它交回；超出所选模型支持档位的档位照常保存，不属于档位全集时整份拒绝并指出字段位置
    document = _document()
    document["models"][0]["reasoning_levels"] = ["low", "medium"]
    document["models"][0]["default_reasoning_level"] = "low"
    document["models"][0]["reasoning_mode"] = "effort"
    opened = _Opened(tmp_path, document)
    with running_api(opened) as client:
        current = _catalog(client)["revision"]
        opened.application.system.facade.record_admission("p1", "m1", admitted_model="model-x")

        bindings = {department: {"provider_id": "p1", "model_id": "m1", "requested_tier": "medium"}
                    for department in DEPARTMENTS}
        saved = _command(client, "catalog.department_defaults.save", base_version=current, bindings=bindings)
        assert saved.status_code == 200, saved.text
        catalog = _catalog(client)
        assert catalog["bindings"]["product"]["requested_tier"] == "medium"
        assert catalog["models"][0]["reasoning_levels"] == ["low", "medium"]
        assert catalog["models"][0]["default_reasoning_level"] == "low"
        assert catalog["models"][0]["reasoning_mode"] == "effort"

        # 超出所选模型支持档位的档位属于档位全集，保存被接受（下一次请求按模型限制）
        above = _command(client, "catalog.department_defaults.save", base_version=catalog["revision"],
                         bindings={department: {"provider_id": "p1", "model_id": "m1",
                                                "requested_tier": "high"}
                                   for department in DEPARTMENTS})
        assert above.status_code == 200, above.text
        assert _catalog(client)["bindings"]["product"]["requested_tier"] == "high"

        rejected = _command(client, "catalog.department_defaults.save",
                            base_version=_catalog(client)["revision"],
                            bindings={department: {"provider_id": "p1", "model_id": "m1",
                                                   "requested_tier": "extreme"}
                                      for department in DEPARTMENTS})
        assert rejected.status_code >= 400
        assert "bindings.product.requested_tier" in rejected.text

def test_connection_save_accepts_the_reasoning_declaration(tmp_path):
    # 连接保存带模型访问定义时可写入推理档位声明（工单 #87）；默认档位不属于支持档位时拒绝
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        current = _catalog(client)["revision"]
        model = {**_model("m1"), "reasoning_levels": ["low", "medium"],
                 "default_reasoning_level": "low", "reasoning_mode": "effort"}
        saved = _command(client, "catalog.connection.save", base_version=current,
                         provider=_provider("p1"), models=[model])
        assert saved.status_code == 200, saved.text
        assert _catalog(client)["models"][0]["reasoning_mode"] == "effort"

        bad = {**_model("m1"), "reasoning_levels": ["low"], "default_reasoning_level": "high",
               "reasoning_mode": "effort"}
        rejected = _command(client, "catalog.connection.save", base_version=_catalog(client)["revision"],
                            provider=_provider("p1"), models=[bad])
        assert rejected.status_code >= 400
        assert "default_reasoning_level" in rejected.text

def test_model_test_admits_and_connection_test_does_not(tmp_path):
    server, _capture, base = serve(responses_responder)
    # 连接测试读取模型列表地址：该连接没有地址时不提供连接测试，这里给出一份真实的上游
    with _models_server({"data": [{"id": "model-x"}]}) as models_url:
        try:
            opened = _Opened(tmp_path, _document(base_url=base + "/v1", models_url=models_url))
            with running_api(opened) as client:
                current = _catalog(client)["revision"]
                tested = _command(client, "catalog.model.test", base_version=current, provider_id="p1",
                                  model_id="m1")
                assert tested.status_code == 200, tested.text
                [finished] = _wait_for(opened.store,
                                       lambda item: item.payload.get("kind") == "model", timeout=15.0,
                                       description="catalog_test_finished (model)")
                assert finished.payload["ok"] is True and finished.payload["admitted"] is True
                assert finished.payload["model_id"] == "m1" and finished.payload["error"] is None
                assert finished.payload["base_revision"] == current
                admitted = next(item for item in _catalog(client)["admissions"]
                                if item["model_id"] == "m1")
                assert admitted["admitted"] is True and admitted["admitted_at"] is not None

                # 连接测试不改变准入
                before_connection = _catalog(client)
                tested = _command(client, "catalog.connection.test",
                                  base_version=before_connection["revision"], provider_id="p1")
                assert tested.status_code == 200, tested.text
                [connection] = _wait_for(opened.store,
                                         lambda item: item.payload.get("kind") == "connection", timeout=15.0,
                                         description="catalog_test_finished (connection)")
                assert connection.payload["ok"] is True and connection.payload["admitted"] is None
                assert connection.payload["base_revision"] == before_connection["revision"]
                assert next(item for item in _catalog(client)["admissions"]
                            if item["model_id"] == "m1")["admitted_at"] == admitted["admitted_at"]
                _assert_no_secret(client, opened)
        finally:
            server.shutdown()
            server.server_close()


def test_candidates_collect_reads_the_models_url_and_writes_an_event(tmp_path):
    with _models_server({"data": [{"id": "m1"}, {"id": "m9"}]}) as models_url:
        opened = _Opened(tmp_path, _document(models_url=models_url))
        with running_api(opened) as client:
            current = _catalog(client)["revision"]
            collected = _command(client, "catalog.candidates.collect", base_version=current, provider_id="p1")
            assert collected.status_code == 200, collected.text
            [event] = _wait_for(opened.store, lambda item: item.type == CatalogEventType.CATALOG_CANDIDATES_COLLECTED,
                                timeout=15.0, description="catalog_candidates_collected")
            assert event.payload["status"] == "ok" and event.payload["provider_id"] == "p1"
            assert set(event.payload["candidate_ids"]) == {"m1", "m9"}
            assert event.payload["source_url"] == models_url
            assert event.payload["base_revision"] == current
            assert _catalog(client)["revision"] == current
            _assert_no_secret(client, opened)


def test_credential_commands_keep_keys_out_of_events_and_queries(tmp_path):
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        current = _catalog(client)
        credential = current["providers"][0]["credential"]
        assert (credential["ref"], credential["source"]) == (REF, "dotenv")
        assert credential["version"] == 0

        replacement = "catalog-secret-key-2"
        saved = _command(client, "credential.set", base_version=credential["version"], ref=REF,
                         secret=replacement, persist=True)
        assert saved.status_code == 200, saved.text
        [changed] = _wait_for(opened.store, lambda item: item.type == CatalogEventType.CREDENTIAL_CHANGED,
                              timeout=5.0, description="credential_changed")
        assert (changed.payload["ref"], changed.payload["action"], changed.payload["persisted"]) == (
            REF, "set", True)
        assert changed.payload["version"] == 1
        assert replacement in opened.dotenv.read_text(encoding="utf-8")
        assert _catalog(client)["providers"][0]["credential"]["version"] == 1
        _assert_no_secret(client, opened, secret=replacement)

        # 过期凭据版本被拒绝
        stale = _command(client, "credential.set", base_version=0, ref=REF, secret="catalog-secret-key-3")
        assert stale.status_code == 409, stale.text
        assert stale.json()["reason"] == "stale_base" and stale.json()["current_version"] == 1

        cleared = _command(client, "credential.clear_override", base_version=1, ref=REF)
        assert cleared.status_code == 200, cleared.text
        [cleared_event] = _wait_for(opened.store, lambda item: item.payload.get("action") == "clear_override",
                                    timeout=5.0, description="credential_changed (clear_override)")
        assert cleared_event.payload["version"] == 2
        assert _catalog(client)["providers"][0]["credential"]["source"] == "dotenv"

        removed = _command(client, "credential.remove_persisted", base_version=2, ref=REF)
        assert removed.status_code == 200, removed.text
        [removed_event] = _wait_for(opened.store, lambda item: item.payload.get("action") == "remove_persisted",
                                    timeout=5.0, description="credential_changed (remove_persisted)")
        assert removed_event.payload["version"] == 3 and removed_event.payload["persisted"] is True
        final = _catalog(client)["providers"][0]["credential"]
        assert final["configured"] is False and final["version"] == 3
        _assert_no_secret(client, opened, secret=replacement)


def test_external_file_change_is_appended_as_catalog_revised(tmp_path):
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        current = _catalog(client)["revision"]
        _write_document(opened.config, {"providers": [_provider("p9")], "models": [_document_model("p9", "m9")],
                                        "bindings": {}})
        [event] = _wait_for(opened.store, lambda item: item.payload.get("operation") == "reload",
                            timeout=15.0, description="外部修改的 catalog_revised")
        after = _catalog(client)
        assert event.payload["revision"] == after["revision"] > current
        assert [item["id"] for item in after["providers"]] == ["p9"]


def test_reload_command_appends_only_when_the_file_changed(tmp_path):
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        opened.application.system.facade.stop_watching()
        current = _catalog(client)["revision"]
        unchanged = _command(client, "catalog.reload", base_version=current)
        assert unchanged.status_code == 200, unchanged.text
        assert [item.payload["operation"] for item in _catalog_events(opened.store)] == ["startup"]

        _write_document(opened.config, {"providers": [_provider("p4")], "models": [_document_model("p4", "m4")],
                                        "bindings": {}})
        reloaded = _command(client, "catalog.reload", base_version=current)
        assert reloaded.status_code == 200, reloaded.text
        [event] = _wait_for(opened.store, lambda item: item.payload.get("operation") == "reload",
                            timeout=5.0, description="reload catalog_revised")
        after = _catalog(client)
        assert event.payload["revision"] == after["revision"] > current
        assert event.payload["base_revision"] == current
        assert [item["id"] for item in after["providers"]] == ["p4"]

        # 追加类命令：提交时依据的修订号已经不是最新时仍被接受，事件记录依据的版本
        saved = _command(client, "catalog.connection.save", base_version=after["revision"],
                         provider=_provider("p5"), models=[_model("m5")])
        assert saved.status_code == 200, saved.text
        latest = _catalog(client)["revision"]
        assert latest > after["revision"]
        _write_document(opened.config, {"providers": [_provider("p6")], "models": [_document_model("p6", "m6")],
                                        "bindings": {}})
        stale = _command(client, "catalog.reload", base_version=after["revision"])
        assert stale.status_code == 200, stale.text
        [second] = _wait_for(opened.store,
                             lambda item: item.payload.get("operation") == "reload"
                             and item.payload["base_revision"] == after["revision"],
                             timeout=5.0, description="按旧修订号提交的 reload")
        assert second.payload["revision"] == _catalog(client)["revision"] > latest


def test_duplicate_command_identity_does_not_apply_the_change_again(tmp_path):
    # 同一命令身份再次提交只返回原来的结果，不再执行；内容不同时拒绝，也不执行
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        current = _catalog(client)["revision"]

        def post(name, body):
            return client.post(f"/api/commands/{name}", json=body)

        command_id = str(uuid.uuid4())
        body = {"command_id": command_id, "base_version": current,
                "provider": _provider("p2"), "models": [_model("m2")]}
        first = post("catalog.connection.save", body)
        assert first.status_code == 200, first.text
        assert first.json()["duplicate"] is False
        after_first = _catalog(client)
        file_after_first = opened.config.read_text(encoding="utf-8")

        again = post("catalog.connection.save", body)
        assert again.status_code == 200, again.text
        assert again.json()["duplicate"] is True and again.json()["position"] == first.json()["position"]
        assert _catalog(client)["revision"] == after_first["revision"]
        assert opened.config.read_text(encoding="utf-8") == file_after_first

        reused = post("catalog.connection.save", {**body, "provider": _provider("p3"), "models": [_model("m3")]})
        assert reused.status_code == 409 and reused.json()["reason"] == "command_id_reused"
        assert _catalog(client)["revision"] == after_first["revision"]
        assert opened.config.read_text(encoding="utf-8") == file_after_first

        delete_body = {"command_id": str(uuid.uuid4()), "base_version": after_first["revision"], "provider_id": "p2"}
        removed = post("catalog.connection.delete", delete_body)
        assert removed.status_code == 200, removed.text
        after_delete = _catalog(client)
        assert [item["id"] for item in after_delete["providers"]] == ["p1"]
        repeated_delete = post("catalog.connection.delete", delete_body)
        assert repeated_delete.status_code == 200, repeated_delete.text
        assert repeated_delete.json()["duplicate"] is True
        assert _catalog(client)["revision"] == after_delete["revision"]

        # 凭据命令同样不重复执行：版本不再推进，.env 不重写
        credential = _catalog(client)["providers"][0]["credential"]
        credential_body = {"command_id": str(uuid.uuid4()), "base_version": credential["version"], "ref": REF,
                           "secret": "catalog-secret-key-9", "persist": True}
        set_once = post("credential.set", credential_body)
        assert set_once.status_code == 200, set_once.text
        version = _catalog(client)["providers"][0]["credential"]["version"]
        dotenv_text = opened.dotenv.read_text(encoding="utf-8")
        set_again = post("credential.set", credential_body)
        assert set_again.status_code == 200, set_again.text
        assert set_again.json()["duplicate"] is True
        assert _catalog(client)["providers"][0]["credential"]["version"] == version
        assert opened.dotenv.read_text(encoding="utf-8") == dotenv_text

        # 重读命令同样不重复执行：第一次重读之后文件被外部修改，重复提交不再发布这次修改
        opened.application.system.facade.stop_watching()
        reload_body = {"command_id": str(uuid.uuid4()), "base_version": _catalog(client)["revision"]}
        first_reload = post("catalog.reload", reload_body)
        assert first_reload.status_code == 200, first_reload.text
        before_file_change = _catalog(client)
        _write_document(opened.config, {"providers": [_provider("p8")], "models": [_document_model("p8", "m8")],
                                        "bindings": {}})
        repeated_reload = post("catalog.reload", reload_body)
        assert repeated_reload.status_code == 200, repeated_reload.text
        assert repeated_reload.json()["duplicate"] is True
        unchanged = _catalog(client)
        assert unchanged["revision"] == before_file_change["revision"]
        assert [item["id"] for item in unchanged["providers"]] == ["p1"]


# ---------------------------------------------------------------------------
# 测试内的真实上游


class _ModelsServer:
    # 模型列表服务：真实 HTTP GET，返回固定 JSON
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
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}/models"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def __enter__(self):
        return self.base

    def __exit__(self, *_exc_info):
        self.server.shutdown()
        self.server.server_close()


def _models_server(payload, *, status=200):
    return _ModelsServer(payload, status=status)
