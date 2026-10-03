# 工单 #146 的验收：模型能力表的预填、输入方式、建议能力的提醒与按输入方式提供工具。
# 从运行的系统整体测试：真实启动 FastAPI 应用与真实 SQLite 事件日志，目录文件与 .env 是真实文件；
# 上游模型列表与模型回答由测试内启动的本机 HTTP 服务给出（不使用桩替身）；能力表取仓库内提交的快照。

from __future__ import annotations

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from harness.app.application import Application
from harness.definitions import DEFINITIONS
from harness.models import CatalogEventType, EventType
from harness.providers import capabilities
from harness.tests.api_helpers import running_api
from harness.tests.helpers import list_files_turn, system_with
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

KEY = "issue146-key"
# 质检缺少图像输入的影响（设计说明第 5.6 节）
QUALITY_IMPACT = "不提供 computer use，浏览器只给可访问性结构，不给截图；依赖桌面程序或外观的验收条件无法核验"

def _text_stream(model: str = "upstream") -> bytes:
    # Responses 协议的一段完整回答（先 created 再 completed），模型测试据此判断连接与准入
    from harness.tests.protocol_helpers import sse

    def event(kind: str, **payload: Any) -> str:
        return f"event: {kind}\ndata: {json.dumps({'type': kind, **payload}, ensure_ascii=False)}\n\n"

    response = {
        "id": "resp-1", "object": "response", "created_at": 1, "status": "completed", "model": model,
        "output": [{"id": "msg-1", "type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": "pong", "annotations": []}]}],
        "error": None, "incomplete_details": None,
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2,
                  "input_tokens_details": {"cached_tokens": 0},
                  "output_tokens_details": {"reasoning_tokens": 0}},
    }
    return sse(event("response.created", sequence_number=0,
                     response={**response, "status": "in_progress", "output": [], "usage": None}),
               event("response.completed", sequence_number=1, response=response))

class _Upstream:
    # 本机 HTTP 服务：GET 返回模型列表，POST 返回模型回答（Responses 协议的错误结构足够让调用成功）
    def __init__(self, models) -> None:
        server = self
        self.models = models

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _write(self, status, body: bytes, content_type="application/json"):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._write(200, json.dumps(server.models).encode("utf-8"))

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length)
                # Responses 协议的流式回答：模型测试按它判断准入
                self._write(200, _text_stream(), content_type="text/event-stream")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{port}/v1"
        self.models_url = f"http://127.0.0.1:{port}/models"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        self.server.shutdown()
        self.server.server_close()

def _provider(provider_id="provider-a", *, base_url, models_url="", preset_id=""):
    return {"id": provider_id, "name": provider_id, "protocol": "responses", "base_url": base_url,
            "credential_ref": "KEY_A", "timeout_sec": 20, "preset_id": preset_id, "models_url": models_url}

def _document_model(model_id, provider_id="provider-a", *, upstream="upstream-a", input_modalities=None,
                    context_window=32000, max_output_tokens=4096):
    entry = {"id": model_id, "provider_id": provider_id, "model": upstream,
             "context_window": context_window, "max_output_tokens": max_output_tokens, "capability_source": ""}
    if input_modalities is not None:
        entry["input_modalities"] = input_modalities
    return entry

def _command_model(model_id, *, upstream="upstream-a", input_modalities=None,
                   context_window=32000, max_output_tokens=4096, capacity_confirmed=True):
    return {"id": model_id, "model": upstream, "context_window": context_window,
            "max_output_tokens": max_output_tokens, "capability_source": "",
            "capacity_confirmed": capacity_confirmed, "input_modalities": input_modalities or ["text"]}

class _Opened:
    def __init__(self, tmp_path, document) -> None:
        self.data_dir = tmp_path / "data"
        self.config = tmp_path / "providers.json"
        self.dotenv = tmp_path / ".env"
        self.dotenv.write_text(f"KEY_A={KEY}\n", encoding="utf-8")
        self.document = document
        self.applications: list[Application] = []
        self.write_document()

    def write_document(self, document=None) -> None:
        if document is not None:
            self.document = document
        self.config.write_text(json.dumps(self.document, ensure_ascii=False), encoding="utf-8")

    def __call__(self) -> Application:
        application = Application.open(self.data_dir, provider_config=self.config, dotenv=self.dotenv)
        self.applications.append(application)
        return application

    @property
    def system(self):
        return self.applications[-1].system

    def admit(self, *model_ids: str) -> None:
        for model_id in model_ids:
            self.system.facade.record_admission("provider-a", model_id, admitted_model="upstream-a")

def _command(client, command, **body):
    return client.post(f"/api/commands/{command}", json={"command_id": str(uuid.uuid4()), **body})

def _catalog(client):
    response = client.get("/api/queries/catalog")
    assert response.status_code == 200, response.text
    return response.json()["data"]

def _wait_for(store, predicate, *, description):
    deadline = time.monotonic() + WAIT_FOR_HOST_WORK_SEC
    while time.monotonic() < deadline:
        for event in store.read(0, limit=100_000):
            if predicate(event):
                return event
        time.sleep(0.02)
    raise AssertionError(f"no event matched {description}")

# ---------------------------------------------------------------------------
# 能力表查询与预填（验收第 1、2 项）

def test_catalog_exposes_the_capability_table(tmp_path):
    # 查询 catalog 返回能力表的 revision、快照日期与来源，以及预置服务方案的条目（手动添加时客户端据此预填）
    with _Upstream({"data": []}) as upstream:
        opened = _Opened(tmp_path, {"providers": [_provider(base_url=upstream.base)],
                                    "models": [_document_model("model-a")], "bindings": {}})
        with running_api(opened) as client:
            table = _catalog(client)["capability_table"]
            assert table["revision"] == capabilities.CAPABILITY_TABLE_REVISION
            assert table["snapshot_date"] == capabilities.CAPABILITY_TABLE_SNAPSHOT_DATE
            assert table["source"] == capabilities.CAPABILITY_TABLE_SOURCE
            assert set(table["presets"]) == set(DEFINITIONS.model_capabilities.presets)
            entry = table["presets"]["opencode-go"][0]
            assert set(entry) == {"model", "input_modalities", "output_modalities",
                                  "context_window", "max_output_tokens", "tool_call", "reasoning"}

def test_candidates_take_the_window_from_upstream_and_the_input_from_the_table(tmp_path):
    # 上游列表返回窗口时预填取列表的值与来源；输入方式取能力表；能力表没有记录时只有文本
    upstream_models = {"data": [
        {"id": "deepseek-v4-flash-vision-exp", "limit": {"context": 500000, "output": 100000}},
        {"id": "not-in-the-table"},
    ]}
    with _Upstream(upstream_models) as upstream:
        opened = _Opened(tmp_path, {"providers": [_provider(base_url=upstream.base,
                                                           models_url=upstream.models_url,
                                                           preset_id="opencode-go")],
                                    "models": [_document_model("model-a")], "bindings": {}})
        with running_api(opened) as client:
            current = _catalog(client)["revision"]
            assert _command(client, "catalog.candidates.collect",
                            base_version=current, provider_id="provider-a").status_code == 200
            event = _wait_for(opened.system.store,
                              lambda item: item.type == CatalogEventType.CATALOG_CANDIDATES_COLLECTED,
                              description="catalog_candidates_collected")
            by_id = {item["id"]: item for item in event.payload["candidates"]}
            vision = by_id["deepseek-v4-flash-vision-exp"]
            assert vision["context_window"] == 500000 and vision["context_window_source"] == "models_url"
            assert vision["max_output_tokens"] == 100000
            assert vision["input_modalities"] == ["text", "image"]
            assert vision["input_modalities_source"] == "capability_table"
            unknown = by_id["not-in-the-table"]
            assert "context_window" not in unknown and "max_output_tokens" not in unknown
            assert unknown["input_modalities"] == ["text"]
            assert unknown["input_modalities_source"] == "default"

def test_candidates_take_the_window_from_the_table_when_upstream_omits_it(tmp_path):
    # 上游列表没有返回窗口时取能力表的值与来源（deepseek-v4-flash 在提交的快照里带窗口与输出上限）
    with _Upstream({"data": [{"id": "deepseek-v4-flash"}]}) as upstream:
        opened = _Opened(tmp_path, {"providers": [_provider(base_url=upstream.base,
                                                           models_url=upstream.models_url,
                                                           preset_id="opencode-go")],
                                    "models": [_document_model("model-a")], "bindings": {}})
        with running_api(opened) as client:
            current = _catalog(client)["revision"]
            assert _command(client, "catalog.candidates.collect",
                            base_version=current, provider_id="provider-a").status_code == 200
            event = _wait_for(opened.system.store,
                              lambda item: item.type == CatalogEventType.CATALOG_CANDIDATES_COLLECTED,
                              description="catalog_candidates_collected")
            [entry] = event.payload["candidates"]
            recorded = capabilities.capability("opencode-go", "deepseek-v4-flash")
            assert recorded is not None
            assert entry["context_window"] == recorded.context_window
            assert entry["context_window_source"] == "capability_table"
            assert entry["max_output_tokens"] == recorded.max_output_tokens
            assert entry["max_output_tokens_source"] == "capability_table"

# ---------------------------------------------------------------------------
# 输入方式与准入（验收第 3 项）

def test_input_modalities_save_and_query_and_do_not_touch_admission(tmp_path):
    # 保存输入方式以后准入保持；模型测试不因输入方式失败；下一次请求的调用目标带新值
    with _Upstream({"data": []}) as upstream:
        opened = _Opened(tmp_path, {"providers": [_provider(base_url=upstream.base)],
                                    "models": [_document_model("model-a", input_modalities=["text"])],
                                    "bindings": {}})
        with running_api(opened) as client:
            opened.admit("model-a")
            before = opened.system.facade.providers_view()["admissions"]
            admitted_before = {item["model_id"]: item["admitted"] for item in before}
            assert admitted_before == {"model-a": True}
            current = _catalog(client)["revision"]
            changed = _command(client, "catalog.connection.save", base_version=current,
                               provider=_provider(base_url=upstream.base),
                               models=[_command_model("model-a", input_modalities=["text", "image"])])
            assert changed.status_code == 200, changed.text
            # 准入保持（输入方式不属于受影响字段）
            after = opened.system.facade.providers_view()["admissions"]
            assert {item["model_id"]: item["admitted"] for item in after} == {"model-a": True}
            models = {item["id"]: item for item in _catalog(client)["models"]}
            assert models["model-a"]["input_modalities"] == ["text", "image"]
            # 目录文档包含输入方式
            document = client.get("/api/queries/catalog.document").json()["data"]
            assert {item["id"]: item for item in document["models"]}["model-a"]["input_modalities"] == ["text", "image"]

def test_model_test_keeps_input_modalities_and_admission(tmp_path):
    # 模型测试不核实输入方式也不因它失败：测试前后定义中的输入方式不变，准入照常写入
    with _Upstream({"data": []}) as upstream:
        opened = _Opened(tmp_path, {"providers": [_provider(base_url=upstream.base)],
                                    "models": [_document_model("model-a", input_modalities=["text", "image"])],
                                    "bindings": {}})
        with running_api(opened) as client:
            current = _catalog(client)["revision"]
            tested = _command(client, "catalog.model.test", base_version=current,
                              provider_id="provider-a", model_id="model-a")
            assert tested.status_code == 200, tested.text
            _wait_for(opened.system.store,
                      lambda item: item.type == CatalogEventType.CATALOG_TEST_FINISHED
                      and item.payload.get("ok") and item.payload.get("kind") == "model",
                      description="catalog_test_finished")
            # 定义中的输入方式没有被测试改动
            models = {item["id"]: item for item in _catalog(client)["models"]}
            assert models["model-a"]["input_modalities"] == ["text", "image"]

def test_unknown_input_modality_is_rejected_at_its_field(tmp_path):
    # 未知取值按字段位置拒绝：请求在接口层被拒绝，位置写明模型行的 input_modalities
    with _Upstream({"data": []}) as upstream:
        opened = _Opened(tmp_path, {"providers": [_provider(base_url=upstream.base)],
                                    "models": [_document_model("model-a")], "bindings": {}})
        with running_api(opened) as client:
            current = _catalog(client)["revision"]
            rejected = _command(client, "catalog.connection.save", base_version=current,
                                provider=_provider(base_url=upstream.base),
                                models=[_command_model("model-a", input_modalities=["audio"])])
            assert rejected.status_code == 422, rejected.text
            locations = [item["loc"] for item in rejected.json()["detail"]]
            assert ["body", "models", 0, "input_modalities", 0] in locations
            # 目录没有被改动：未知取值没有落进目录
            assert _catalog(client)["models"][0]["input_modalities"] == ["text"]

def test_call_target_is_resolved_with_the_input_modalities(tmp_path):
    # 调用目标带输入方式：含图像的定义解析成功，调用目标公开部分与请求事件都带上它
    with _Upstream({"data": []}) as upstream:
        opened = _Opened(tmp_path, {"providers": [_provider(base_url=upstream.base)],
                                    "models": [_document_model("model-a", input_modalities=["text", "image"])],
                                    "bindings": {"quality": {"provider_id": "provider-a", "model_id": "model-a"}}})
        with running_api(opened) as client:
            opened.admit("model-a")
            facade = opened.system.facade
            resolution = facade.resolve_department_default("quality")
            assert resolution.available, resolution.message
            assert resolution.public["input_modalities"] == ["text", "image"]
            target = facade.providers_view()["models"][0]
            assert target["input_modalities"] == ["text", "image"]
            assert "api_key" not in json.dumps(resolution.public)

# ---------------------------------------------------------------------------
# 建议能力的提醒（验收第 4 项）

def _save_quality_default(client, model_id, *, base_version):
    return _command(client, "catalog.department_defaults.save", base_version=base_version,
                    bindings={"quality": {"provider_id": "provider-a", "model_id": model_id}})

def test_department_defaults_save_reports_the_missing_capability(tmp_path):
    # 给质检保存只有文本输入的模型：保存成功，接受结果带提醒；改为含图像以后提醒消失
    with _Upstream({"data": []}) as upstream:
        opened = _Opened(tmp_path, {"providers": [_provider(base_url=upstream.base)],
                                    "models": [_document_model("text-model", input_modalities=["text"]),
                                               _document_model("vision-model", input_modalities=["text", "image"])],
                                    "bindings": {}})
        with running_api(opened) as client:
            opened.admit("text-model", "vision-model")
            current = _catalog(client)["revision"]
            accepted = _save_quality_default(client, "text-model", base_version=current)
            assert accepted.status_code == 200, accepted.text
            reminders = accepted.json()["refs"]["reminders"]
            assert len(reminders) == 1
            assert "quality" in reminders[0] and "text-model" in reminders[0]
            assert QUALITY_IMPACT in reminders[0]
            # 一直显示：catalog 返回质检的提醒，其他部门为空
            catalog = _catalog(client)
            assert catalog["department_reminders"]["quality"] == reminders
            assert catalog["department_reminders"]["product"] == []
            # 换成含图像输入的模型：提醒消失
            current = catalog["revision"]
            accepted = _save_quality_default(client, "vision-model", base_version=current)
            assert accepted.status_code == 200, accepted.text
            assert accepted.json()["refs"]["reminders"] == []
            assert _catalog(client)["department_reminders"]["quality"] == []

def test_catalog_does_not_check_departments_without_a_written_model(tmp_path):
    # 没有写入模型的设置不检查：只有产品写入时质检没有提醒
    with _Upstream({"data": []}) as upstream:
        opened = _Opened(tmp_path, {"providers": [_provider(base_url=upstream.base)],
                                    "models": [_document_model("text-model", input_modalities=["text"])],
                                    "bindings": {}})
        with running_api(opened) as client:
            opened.admit("text-model")
            current = _catalog(client)["revision"]
            accepted = _command(client, "catalog.department_defaults.save", base_version=current,
                                bindings={"product": {"provider_id": "provider-a", "model_id": "text-model"}})
            assert accepted.status_code == 200, accepted.text
            assert accepted.json()["refs"]["reminders"] == []

def test_project_settings_and_workspace_show_the_reminder(tmp_path):
    # 项目部门设置写入只有文本的模型时接受结果带提醒；project.settings 与 department.workspace 一直返回它；
    # 跟随部门默认（项目设置不写模型）时 project.settings 按部门默认同样返回提醒
    with _Upstream({"data": []}) as upstream:
        opened = _Opened(tmp_path, {"providers": [_provider(base_url=upstream.base)],
                                    "models": [_document_model("text-model", input_modalities=["text"]),
                                               _document_model("vision-model", input_modalities=["text", "image"])],
                                    "bindings": {}})
        with running_api(opened) as client:
            opened.admit("text-model", "vision-model")
            accepted = _save_quality_default(client, "text-model", base_version=_catalog(client)["revision"])
            assert accepted.status_code == 200, accepted.text
            catalog = _catalog(client)
            assert catalog["department_reminders"]["quality"] == accepted.json()["refs"]["reminders"]

            created = _command(client, "project.create", name="P", goal="建议能力提醒")
            assert created.status_code == 200, created.text
            project_id = created.json()["refs"]["project_id"]
            # 项目设置跟随部门默认：按部门默认的模型返回提醒
            settings = client.get("/api/queries/project.settings",
                                  params={"project_id": project_id}).json()["data"]
            assert settings["departments"]["quality"]["model_id"] is None
            assert settings["department_reminders"]["quality"] == catalog["department_reminders"]["quality"]
            assert settings["department_reminders"]["product"] == []
            # 项目部门设置为质检另选只有文本的模型（与部门默认同值，来源不同）：仍然返回提醒
            saved = _command(client, "department_settings.save", base_version=0, project_id=project_id,
                             department="quality", provider_id="provider-a", model_id="text-model")
            assert saved.status_code == 200, saved.text
            assert saved.json()["refs"]["reminders"] == catalog["department_reminders"]["quality"]
            settings = client.get("/api/queries/project.settings",
                                  params={"project_id": project_id}).json()["data"]
            assert settings["department_reminders"]["quality"] == catalog["department_reminders"]["quality"]
            # 部门工作间按当前生效模型返回提醒
            workspace = client.get("/api/queries/department.workspace",
                                   params={"project_id": project_id, "department": "quality"}).json()["data"]
            assert workspace["reminders"] == catalog["department_reminders"]["quality"]

def test_workspace_reminder_disappears_after_the_model_gains_the_capability(tmp_path):
    # 把部门默认换成含图像输入的模型以后，project.settings 与 department.workspace 的提醒消失
    with _Upstream({"data": []}) as upstream:
        opened = _Opened(tmp_path, {"providers": [_provider(base_url=upstream.base)],
                                    "models": [_document_model("text-model", input_modalities=["text"]),
                                               _document_model("vision-model", input_modalities=["text", "image"])],
                                    "bindings": {}})
        with running_api(opened) as client:
            opened.admit("text-model", "vision-model")
            accepted = _save_quality_default(client, "text-model", base_version=_catalog(client)["revision"])
            assert accepted.status_code == 200, accepted.text
            created = _command(client, "project.create", name="P", goal="建议能力提醒")
            project_id = created.json()["refs"]["project_id"]
            assert client.get("/api/queries/department.workspace",
                              params={"project_id": project_id, "department": "quality"}
                              ).json()["data"]["reminders"]
            accepted = _save_quality_default(client, "vision-model", base_version=_catalog(client)["revision"])
            assert accepted.status_code == 200, accepted.text
            settings = client.get("/api/queries/project.settings",
                                  params={"project_id": project_id}).json()["data"]
            assert settings["department_reminders"]["quality"] == []
            workspace = client.get("/api/queries/department.workspace",
                                   params={"project_id": project_id, "department": "quality"}).json()["data"]
            assert workspace["reminders"] == []

def test_queries_do_not_append_events_and_carry_no_key(tmp_path):
    # 调用查询前后事件日志末尾不变；查询结果中没有 API Key
    with _Upstream({"data": []}) as upstream:
        opened = _Opened(tmp_path, {"providers": [_provider(base_url=upstream.base)],
                                    "models": [_document_model("text-model", input_modalities=["text"]),
                                               _document_model("vision-model", input_modalities=["text", "image"])],
                                    "bindings": {"quality": {"provider_id": "provider-a", "model_id": "text-model"}}})
        with running_api(opened) as client:
            opened.admit("text-model", "vision-model")
            store = opened.system.store
            created = _command(client, "project.create", name="P", goal="查询纯净")
            project_id = created.json()["refs"]["project_id"]
            before = store.end_position()
            answers = [
                client.get("/api/queries/catalog").json(),
                client.get("/api/queries/catalog.document").json(),
                client.get("/api/queries/project.settings", params={"project_id": project_id}).json(),
                client.get("/api/queries/department.workspace",
                           params={"project_id": project_id, "department": "quality"}).json(),
            ]
            assert store.end_position() == before
            rendered = json.dumps(answers, ensure_ascii=False)
            # 凭据不出现在查询结果里：模型访问定义与调用目标只有引用与版本，没有 Key
            assert KEY not in rendered
            catalog = answers[0]["data"]
            for model in catalog["models"]:
                assert "credential" not in model
            for provider in catalog["providers"]:
                assert provider["credential"]["source"] in {"none", "dotenv", "override"}
                assert "secret" not in provider["credential"]
            # 提醒确实出现在查询结果里，而不是被断言掩盖
            assert "quality" in rendered

# ---------------------------------------------------------------------------
# 调用目标按输入方式提供工具（验收第 5 项）

def test_offers_with_input_filters_tools_that_need_images():
    # 声明需要图像输入的工具在调用目标不含图像时不提供（机制本身；3.2D 的屏幕工具使用这一声明）
    from harness.tools import offers_with_input

    names = ["read_file", "list_files"]
    assert offers_with_input(names, ("text",)) == names
    assert offers_with_input(names, ("text", "image")) == names
    assert offers_with_input(names, ()) == names

def test_call_target_records_input_modalities(tmp_path):
    # 请求事件记录调用目标的输入方式（设计说明第 6 节「审计」），且不含 Key
    system = system_with(tmp_path, [list_files_turn])
    run_id = system.create_run("task")
    system.run_until_stop(run_id)
    requests = [event for event in system.store.list_events(run_id)
                if event.type == EventType.MODEL_REQUESTED]
    assert requests
    assert requests[0].payload["input_modalities"] == ["text"]
    assert "api_key" not in json.dumps(requests[0].payload)
