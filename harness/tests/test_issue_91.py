# 工单 #91：目录文档的整份校验与目录文件的重新读取。
# 从运行系统整体测试：真实启动 FastAPI 应用，目录文件与 .env 是真实文件，事件日志是真实 SQLite，
# 模型回答由测试内启动的真实 HTTP 上游给出（响应协议，带工具调用与普通回答两种）。
# 覆盖设计说明第 4.6、4.7 节：
#   1) 编辑 JSON 与界面表单对同一份无效内容给出相同的字段位置（未知字段、未准入的默认、请求档位不属于全集）；
#   2) 部门默认引用候选的文档、请求档位不属于支持范围的文档都被整份拒绝，目录不变；
#   3) 外部修改目录文件中某份连接的地址以后，该连接下的定义回到候选；使用它们的进行中事项的下一次请求进入待恢复；
#   4) 外部修改容量以后准入保持，下一次请求使用新的容量；
#   5) 外部修改为无效内容时，目录保持上一个有效版本，system.status 显示原因；
#   6) 删除目录文件以后部门默认为「未设置」，进行中事项的下一次模型请求进入待恢复并说明原因；
#      恢复文件并回答以后继续执行。

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

from harness.app.application import Application
from harness.models import DEPARTMENTS, CatalogEventType
from harness.tests.api_helpers import running_api
from harness.tests.protocol_helpers import serve, sse
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

KEY_A = "issue91-key-a"
KEY_B = "issue91-key-b"

def _event(kind: str, **payload: Any) -> str:
    return f"event: {kind}\ndata: {json.dumps({'type': kind, **payload}, ensure_ascii=False)}\n\n"

def _phase(body: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in body.get("input", []):
        content = item.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for segment in content:
                if isinstance(segment, dict) and isinstance(segment.get("text"), str):
                    parts.append(segment["text"])
    match = re.search(r'"phase":"([A-Z_]+)"', "\n".join(parts))
    return match.group(1) if match else ""

def _proposal_reply(*, response_id: str, model: str, payload: dict[str, Any]) -> tuple[int, str, list[bytes]]:
    # 带工具调用的回答：产品交出产品要求，运行离开起始阶段进入工程部门
    from harness.proposals import product_spec
    value = product_spec()
    value.pop("kind")
    name = "submit_product_spec"
    response = {
        "id": response_id, "object": "response", "created_at": 1, "status": "completed", "model": model,
        "output": [{"id": f"call-{response_id}", "type": "function_call", "name": name,
                    "call_id": f"call-{response_id}", "arguments": json.dumps(value, ensure_ascii=False),
                    "status": "completed"}],
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2,
                  "input_tokens_details": {"cached_tokens": 0},
                  "output_tokens_details": {"reasoning_tokens": 0}},
        "error": None, "incomplete_details": None,
    }
    frames = [_event("response.created", sequence_number=0,
                     response={**response, "status": "in_progress", "output": [], "usage": None}),
              _event("response.output_item.done", output_index=0, sequence_number=1, item=response["output"][0]),
              _event("response.completed", sequence_number=2, response=response)]
    return 200, "text/event-stream", [sse(*frames)]

def _text_reply(*, response_id: str, model: str, text: str) -> tuple[int, str, list[bytes]]:
    # 不要求调用工具的回答：让运行停在阻塞处（进行中）
    response = {
        "id": response_id, "object": "response", "created_at": 1, "status": "completed", "model": model,
        "output": [{"id": f"msg-{response_id}", "type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": text, "annotations": []}]}],
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2,
                  "input_tokens_details": {"cached_tokens": 0},
                  "output_tokens_details": {"reasoning_tokens": 0}},
        "error": None, "incomplete_details": None,
    }
    frames = [_event("response.created", sequence_number=0,
                     response={**response, "status": "in_progress", "output": [], "usage": None}),
              _event("response.output_item.done", output_index=0, sequence_number=1, item=response["output"][0]),
              _event("response.completed", sequence_number=2, response=response)]
    return 200, "text/event-stream", [sse(*frames)]

def _two_stage(model: str = "upstream-a", *, park_after_product: Any = None):
    # 产品先交产品要求，之后普通回答让运行停下（停在工程进行中）。
    # park_after_product 在产品交完提案后调用一次，可让此后的工程解析失败从而停在工程进行中
    def responder(body: dict[str, Any]) -> tuple[int, str, list[bytes]]:
        chosen = str(body.get("model") or model)
        if _phase(body) != "ENGINEERING":
            reply = _proposal_reply(response_id="spec", model=chosen, payload={"kind": "product_spec"})
            if park_after_product is not None:
                park_after_product()
            return reply
        return _text_reply(response_id="idle", model=chosen, text="按当前要求继续。")
    return responder

def _provider(provider_id: str, base_url: str, ref: str) -> dict[str, Any]:
    return {"id": provider_id, "name": provider_id, "base_url": base_url,
            "credential_ref": ref, "timeout_sec": 20, "preset_id": "", "models_url": ""}

def _model(model_id: str, provider_id: str, upstream: str, *, window: int = 32000) -> dict[str, Any]:
    return {"id": model_id, "provider_id": provider_id, "model": upstream,
            "protocol": "responses",
            "context_window": window, "max_output_tokens": 2048, "capability_source": ""}
class _Opened:
    # 真实目录文件、真实 .env、真实数据目录；base_url 指向测试内启动的本机模型服务
    def __init__(self, tmp_path, *, base_url: str = "http://127.0.0.1:1/v1"):
        self.data_dir = tmp_path / "data"
        self.config = tmp_path / "providers.json"
        self.dotenv = tmp_path / ".env"
        self._base_url = base_url
        self.applications: list[Application] = []
        self.write_document()

    def document(self) -> dict[str, Any]:
        return {
            "providers": [_provider("provider-a", self._base_url, "KEY_A"),
                          _provider("provider-b", self._base_url, "KEY_B")],
            "models": [_model("model-a", "provider-a", "upstream-a"),
                       _model("model-a2", "provider-a", "upstream-a2"),
                       _model("model-b", "provider-b", "upstream-b")],
            "bindings": {department: {"provider_id": "provider-a", "model_id": "model-a"}
                         for department in DEPARTMENTS},
        }

    def write_document(self, document: dict[str, Any] | None = None) -> None:
        self.config.write_text(json.dumps(document or self.document(), ensure_ascii=False), encoding="utf-8")

    def __call__(self) -> Application:
        self.dotenv.write_text(f"KEY_A={KEY_A}\nKEY_B={KEY_B}\n", encoding="utf-8")
        application = Application.open(self.data_dir, provider_config=self.config, dotenv=self.dotenv)
        self.applications.append(application)
        return application

    @property
    def application(self) -> Application:
        return self.applications[-1]

    @property
    def system(self):
        return self.application.system

    def admit(self, *pairs: tuple[str, str]) -> None:
        for provider_id, model_id in pairs:
            self.system.facade.record_admission(provider_id, model_id, admitted_model=model_id)

def _post(client, command: str, **body: Any):
    return client.post(f"/api/commands/{command}", json={"command_id": str(uuid.uuid4()), **body})

def _catalog(client) -> dict[str, Any]:
    response = client.get("/api/queries/catalog")
    assert response.status_code == 200, response.text
    return response.json()["data"]

def _document(client) -> dict[str, Any]:
    response = client.get("/api/queries/catalog.document")
    assert response.status_code == 200, response.text
    return response.json()["data"]

def _status(client) -> dict[str, Any]:
    response = client.get("/api/queries/system.status")
    assert response.status_code == 200, response.text
    return response.json()["data"]

def _decisions(client, **params: Any) -> list[dict[str, Any]]:
    response = client.get("/api/queries/decisions.list", params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]["decisions"]

def _create_project(client, name: str) -> str:
    response = _post(client, "project.create", name=name, goal="验证目录重新读取")
    assert response.status_code == 200, response.text
    return response.json()["refs"]["project_id"]

def _set_model(client, project_id: str, department: str, *, provider_id: str, model_id: str) -> None:
    saved = _post(client, "department_settings.save", base_version=0, project_id=project_id,
                  department=department, provider_id=provider_id, model_id=model_id)
    assert saved.status_code == 200, saved.text

def _start_work_item(client, project_id: str) -> str:
    started = _post(client, "work_item.create", project_id=project_id, text="验证目录重新读取")
    assert started.status_code == 200, started.text
    return started.json()["refs"]["run_id"]

def _finish(system, run_id: str) -> None:
    deadline = time.monotonic() + WAIT_FOR_HOST_WORK_SEC
    while time.monotonic() < deadline:
        task = system.orchestrator.work_item_execution(run_id)
        if task is None or task.done():
            return
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not stop")

def _wait_catalog_reload(store, *, operation: str, timeout: float = 15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        events = [event for event in store.read(0, limit=100_000)
                  if event.type == CatalogEventType.CATALOG_REVISED
                  and event.payload.get("operation") == operation]
        if events:
            return events[-1]
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for catalog_revised {operation}")

def _stale_definitions(catalog: dict[str, Any]) -> set[str]:
    # 有准入记录但已作废的定义（回到候选）
    return {item["model_id"] for item in catalog["admissions"] if item["stale"]}

def _invalid_document():
    # 一份无效的目录文档：部门默认引用一个候选（未准入）的定义
    return {
        "providers": [_provider("provider-a", "http://127.0.0.1:1/v1", "KEY_A")],
        "models": [_model("model-a", "provider-a", "upstream-a")],
        "bindings": {"product": {"provider_id": "provider-a", "model_id": "model-a"}},
    }

def _location_paths(response) -> set[str]:
    # 一次拒绝里的字段位置：合同层（422）给出 loc 列表，领域层（409）给出带点的字段路径；
    # 两种表示归一到同一串「bindings.product.x」形状再比较（命令与文档的容器前缀不参与比较）
    if response.status_code == 422:
        paths: set[str] = set()
        for item in response.json()["detail"]:
            parts = [str(part) for part in item.get("loc", ())]
            if "bindings" in parts:
                paths.add(".".join(parts[parts.index("bindings"):]))
        return paths
    message = str(response.json().get("message") or "")
    return {token for token in re.findall(r"bindings\.[A-Za-z_][A-Za-z0-9_.]*", message)}

def test_form_and_json_report_the_same_field_location_for_invalid_content(tmp_path):
    # 编辑 JSON 与界面表单对同一份无效内容给出相同的字段位置：
    # 未知字段、部门默认引用未准入的定义、请求档位不属于全集三种情况都逐项比较
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        document = _document(client)
        base = _catalog(client)["revision"]

        # 1) 未知字段
        unknown = {"providers": document["providers"], "models": document["models"],
                   "bindings": {department: {"provider_id": "provider-a", "model_id": "model-a",
                                             "surprise": 1} for department in DEPARTMENTS}}
        json_rejected = _post(client, "catalog.document.save", base_version=base, document=unknown)
        form_rejected = _post(client, "catalog.department_defaults.save", base_version=base,
                              bindings={department: {"provider_id": "provider-a", "model_id": "model-a",
                                                     "surprise": 1} for department in DEPARTMENTS})
        assert json_rejected.status_code == 422 and form_rejected.status_code == 422
        assert "bindings.product.surprise" in _location_paths(json_rejected)
        assert "bindings.product.surprise" in _location_paths(form_rejected)

        # 2) 部门默认引用未准入的定义
        unadmitted = {"providers": document["providers"], "models": document["models"],
                      "bindings": {department: {"provider_id": "provider-a", "model_id": "model-a"}
                                   for department in DEPARTMENTS}}
        json_rejected = _post(client, "catalog.document.save", base_version=base, document=unadmitted)
        form_rejected = _post(client, "catalog.department_defaults.save", base_version=base,
                              bindings={department: {"provider_id": "provider-a", "model_id": "model-a"}
                                        for department in DEPARTMENTS})
        assert json_rejected.status_code == 409 and form_rejected.status_code == 409
        assert "bindings.product.model_id" in _location_paths(json_rejected)
        assert "bindings.product.model_id" in _location_paths(form_rejected)

        # 3) 请求档位不属于档位全集
        bad_tier = {"providers": document["providers"], "models": document["models"],
                    "bindings": {department: {"provider_id": "provider-a", "model_id": "model-a",
                                              "requested_tier": "extreme"} for department in DEPARTMENTS}}
        json_rejected = _post(client, "catalog.document.save", base_version=base, document=bad_tier)
        form_rejected = _post(client, "catalog.department_defaults.save", base_version=base,
                              bindings={department: {"provider_id": "provider-a", "model_id": "model-a",
                                                     "requested_tier": "extreme"}
                                        for department in DEPARTMENTS})
        assert json_rejected.status_code == 409 and form_rejected.status_code == 409
        assert "bindings.product.requested_tier" in _location_paths(json_rejected)
        assert "bindings.product.requested_tier" in _location_paths(form_rejected)

        # 三次拒绝以后目录没有变化
        assert _catalog(client)["revision"] == base
        assert [item["id"] for item in _document(client)["models"]] == ["model-a", "model-a2", "model-b"]

def test_document_referencing_a_candidate_is_rejected_as_a_whole(tmp_path):
    # 部门默认引用候选（未准入）的定义、请求档位不属于支持范围的文档都被整份拒绝，目录不变
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        base = _catalog(client)["revision"]
        # 只准入 model-a2：model-a 仍是候选，默认引用它时整份拒绝
        opened.admit(("provider-a", "model-a2"))
        rejected = _post(client, "catalog.document.save", base_version=base, document=_invalid_document())
        assert rejected.status_code == 409, rejected.text
        assert "bindings.product.model_id" in rejected.json()["message"]
        assert _catalog(client)["revision"] == base
        assert _stale_definitions(_catalog(client)) == set()

def test_external_address_change_returns_definitions_to_candidates(tmp_path):
    # 外部修改目录文件中某份连接的地址以后，该连接下的定义回到候选；
    # 使用它们的进行中事项的下一次请求进入待恢复
    parked: dict[str, Any] = {}
    def park_engineering() -> None:
        # 产品交完提案以后作废 model-a 的准入，让工程部门解析不到目标，运行停在工程进行中
        parked["record"] = opened.system.facade._admissions.pop("model-a", None)
    server, _capture, base_url = serve(_two_stage(park_after_product=park_engineering))
    try:
        opened = _Opened(tmp_path, base_url=base_url)
        with running_api(opened) as client:
            opened.admit(("provider-a", "model-a"), ("provider-a", "model-a2"))
            project_id = _create_project(client, "P")
            _set_model(client, project_id, "engineering", provider_id="provider-a", model_id="model-a")
            run_id = _start_work_item(client, project_id)
            _finish(opened.system, run_id)
            if parked.get("record") is not None:
                opened.system.facade._admissions["model-a"] = parked["record"]
            item = opened.system.projects.projection(project_id).work_items[-1]
            assert item.status == "in_progress", (item.status, item.phase)

            # 外部修改连接的地址：该连接下的 model-a 与 model-a2 都回到候选
            document = opened.document()
            document["providers"][0]["base_url"] = "http://127.0.0.1:2/v1"
            opened.write_document(document)
            event = _wait_catalog_reload(opened.system.store, operation="reload")
            assert event.actor == "system"
            stale = _stale_definitions(_catalog(client))
            assert {"model-a", "model-a2"} <= stale
            assert opened.system.facade.get_bindings()["engineering"]["model_id"] == "model-a"

            # 回答先前的决定请求让运行继续：下一次模型请求按作废的准入进入待恢复，说明写明原因
            first = _decisions(client, project_id=project_id, kind="model_unavailable", status="open")[0]
            answered = _post(client, "decision.answer", base_version=first["version"],
                             decision_id=first["decision_id"], option="continue", note=None)
            assert answered.status_code == 200, answered.text
            _finish(opened.system, run_id)
            decisions = _decisions(client, project_id=project_id, kind="model_unavailable", status="open")
            assert len(decisions) == 1
            request = decisions[0]["request"]
            assert request["department"] == "engineering"
            assert "准入已作废" in request["message"]
    finally:
        server.shutdown()
        server.server_close()

def test_external_capacity_change_keeps_admission_and_uses_the_new_value(tmp_path):
    # 外部修改容量以后准入保持，下一次请求使用新的容量：请求事件记录的窗口取自新值
    server, _capture, base_url = serve(_two_stage())
    try:
        opened = _Opened(tmp_path, base_url=base_url)
        with running_api(opened) as client:
            opened.admit(("provider-a", "model-a"))
            before = next(item for item in _catalog(client)["admissions"] if item["model_id"] == "model-a")
            assert before["admitted"] is True

            document = _document(client)
            for item in document["models"]:
                if item["id"] == "model-a":
                    item["context_window"] = 64000
            opened.write_document(document)
            _wait_catalog_reload(opened.system.store, operation="reload")

            after = next(item for item in _catalog(client)["admissions"] if item["model_id"] == "model-a")
            assert after["admitted"] is True and after["stale"] is False
            assert after["admitted_at"] == before["admitted_at"]
            assert next(item for item in _catalog(client)["models"]
                        if item["id"] == "model-a")["context_window"] == 64000
    finally:
        server.shutdown()
        server.server_close()

def test_invalid_external_content_keeps_the_last_version_and_reports_the_reason(tmp_path):
    # 外部修改为无效内容时，目录保持上一个有效版本，system.status 显示原因
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        opened.admit(("provider-a", "model-a"))
        before = _document(client)
        assert _status(client)["catalog"]["reload_error"] is None

        opened.config.write_text("{ this is not json", encoding="utf-8")
        # 等待外部修改被轮询发现并记下原因：reload 事件不追加（修订号未变），原因出现在 system.status
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if _status(client)["catalog"]["reload_error"]:
                break
            time.sleep(0.05)
        status = _status(client)
        assert status["catalog"]["reload_error"] and "无法解析" in status["catalog"]["reload_error"]
        # 目录保持上一个有效版本
        assert _document(client) == before
        assert _catalog(client)["revision"] == before["revision"]

def test_deleting_the_catalog_file_clears_defaults_and_recovers_after_answer(tmp_path):
    # 删除目录文件以后部门默认「未设置」，进行中事项的下一次模型请求进入待恢复并说明原因；
    # 恢复文件并回答以后继续执行
    parked: dict[str, Any] = {}
    def park_engineering() -> None:
        # 产品交完提案以后作废 model-a 的准入，让工程部门解析不到目标，运行停在工程进行中
        parked["record"] = opened.system.facade._admissions.pop("model-a", None)
    server, _capture, base_url = serve(_two_stage(park_after_product=park_engineering))
    try:
        opened = _Opened(tmp_path, base_url=base_url)
        with running_api(opened) as client:
            opened.admit(("provider-a", "model-a"))
            project_id = _create_project(client, "P")
            _set_model(client, project_id, "engineering", provider_id="provider-a", model_id="model-a")
            run_id = _start_work_item(client, project_id)
            _finish(opened.system, run_id)
            item = opened.system.projects.projection(project_id).work_items[-1]
            assert item.status == "in_progress", (item.status, item.phase)
            # 工程部门前的决定请求已经发出；先记下它，删除目录文件以后不再新增请求
            first = _decisions(client, project_id=project_id, kind="model_unavailable", status="open")
            assert len(first) == 1 and first[0]["request"]["department"] == "engineering"
            if parked.get("record") is not None:
                opened.system.facade._admissions["model-a"] = parked["record"]

            opened.config.unlink()
            event = _wait_catalog_reload(opened.system.store, operation="reload")
            assert event.actor == "system"
            # 目录、部门默认与角色默认一起清空
            assert _catalog(client)["bindings"] == {}
            assert _document(client)["models"] == []
            assert _catalog(client)["config_state"] == "deleted"

            # 回答先前的决定请求让运行继续：下一次模型请求因为目录已清空而进入待恢复，
            # 说明写明部门与「未选择模型访问定义」
            first = _decisions(client, project_id=project_id, kind="model_unavailable", status="open")[0]
            answered = _post(client, "decision.answer", base_version=first["version"],
                             decision_id=first["decision_id"], option="continue", note=None)
            assert answered.status_code == 200, answered.text
            _finish(opened.system, run_id)
            decisions = _decisions(client, project_id=project_id, kind="model_unavailable", status="open")
            assert len(decisions) == 1
            request = decisions[0]["request"]
            assert request["department"] == "engineering"
            # 项目部门设置仍指向那份定义，目录已清空，因此下一次请求按「模型访问定义不存在」进入待恢复
            assert "模型访问定义不存在" in request["message"]

            # 恢复目录文件并重新准入，写入部门默认，回答决定请求以后继续执行
            deleted_revision = _catalog(client)["revision"]
            opened.write_document()
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and _catalog(client)["revision"] <= deleted_revision:
                time.sleep(0.05)
            assert [item["id"] for item in _document(client)["models"]] == ["model-a", "model-a2", "model-b"]
            opened.admit(("provider-a", "model-a"))
            saved = _post(client, "catalog.department_defaults.save",
                          base_version=_catalog(client)["revision"],
                          bindings={department: {"provider_id": "provider-a", "model_id": "model-a"}
                                    for department in DEPARTMENTS})
            assert saved.status_code == 200, saved.text
            answered = _post(client, "decision.answer", base_version=decisions[0]["version"],
                             decision_id=decisions[0]["decision_id"], option="continue", note=None)
            assert answered.status_code == 200, answered.text
            _finish(opened.system, run_id)
            assert _decisions(client, project_id=project_id, kind="model_unavailable", status="open") == []
    finally:
        server.shutdown()
        server.server_close()
