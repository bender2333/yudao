# 工单 #92：生效模型与调用目标的查询（设计说明第 6、9.3 节；应用层与接口层设计说明第 4.3 节）。
# 从运行系统整体测试：真实启动 FastAPI 应用，目录文件与 .env 是真实文件，事件日志是真实 SQLite；
# 模型回答由测试内启动的本机 HTTP 服务按 Responses 协议给出。
# 覆盖：department.workspace 的生效模型与来源（项目部门设置、部门默认）、引用无法使用与未设置、
# 最近一次调用目标与请求事件一致；run.attempt 的调用目标公开部分（不含 Key）、选择来源与档位、部门 Prompt 版本；
# project.attempts 按 Provider 配置、请求模型与实际模型筛选；查询前后事件日志末尾不变。

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

from harness.app.application import Application
from harness.models import DEPARTMENTS, EventType
from harness.tests.api_helpers import running_api
from harness.tests.protocol_helpers import serve, sse
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

KEY_A = "issue92-key-a"
KEY_B = "issue92-key-b"

def _event(kind: str, **payload: Any) -> str:
    return f"event: {kind}\ndata: {json.dumps({'type': kind, **payload}, ensure_ascii=False)}\n\n"

def _reply(items: list[dict[str, Any]], *, response_id: str, model: str) -> bytes:
    response = {
        "id": response_id, "object": "response", "created_at": 1, "status": "completed", "model": model,
        "output": items,
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2,
                  "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}},
        "error": None, "incomplete_details": None,
    }
    frames = [_event("response.created", sequence_number=0,
                     response={**response, "status": "in_progress", "output": [], "usage": None})]
    for index, item in enumerate(items):
        frames.append(_event("response.output_item.done", output_index=index, sequence_number=index + 1, item=item))
    frames.append(_event("response.completed", sequence_number=len(frames), response=response))
    return sse(*frames)

def _text_reply(*, response_id: str, model: str, text: str) -> tuple[int, str, list[bytes]]:
    item = {"id": f"msg-{response_id}", "type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}]}
    return 200, "text/event-stream", [_reply([item], response_id=response_id, model=model)]

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
    from harness.proposals import product_spec
    value = product_spec()
    value.pop("kind")
    item = {"id": f"call-{response_id}", "type": "function_call", "name": "submit_product_spec", "call_id": f"call-{response_id}",
            "arguments": json.dumps(value, ensure_ascii=False), "status": "completed"}
    return 200, "text/event-stream", [_reply([item], response_id=response_id, model=model)]

def _department_aware(model: str):
    # 产品部门先提交产品要求，之后返回不带工具调用的回答让运行停在工程进行中
    def responder(body: dict[str, Any]) -> tuple[int, str, list[bytes]]:
        if _phase(body) != "ENGINEERING":
            return _proposal_reply(response_id="spec", model=model, payload={"kind": "product_spec"})
        return _text_reply(response_id="idle", model=model, text="waiting")
    return responder

def _provider(provider_id: str, base_url: str, ref: str) -> dict[str, Any]:
    return {"id": provider_id, "name": provider_id, "base_url": base_url,
            "credential_ref": ref, "timeout_sec": 20, "preset_id": "", "models_url": ""}

def _model(model_id: str, provider_id: str, upstream: str, *, levels=None, default_level=None, mode="") -> dict[str, Any]:
    payload: dict[str, Any] = {"id": model_id, "provider_id": provider_id, "model": upstream,
                               "protocol": "responses",
                               "context_window": 32000, "max_output_tokens": 2048, "capability_source": ""}
    if levels:
        payload.update({"reasoning_levels": levels, "default_reasoning_level": default_level, "reasoning_mode": mode})
    return payload

class _Opened:
    def __init__(self, tmp_path, base_a: str, base_b: str, *, bindings: dict[str, dict[str, str]] | None = None):
        self.data_dir = tmp_path / "data"
        self.config = tmp_path / "providers.json"
        self.dotenv = tmp_path / ".env"
        self._base_a, self._base_b = base_a, base_b
        self._bindings = bindings if bindings is not None else {
            department: {"provider_id": "provider-a", "model_id": "model-a"} for department in DEPARTMENTS}
        self.applications: list[Application] = []
        self.write_document()

    def write_document(self, overrides: dict[str, Any] | None = None) -> None:
        document = {
            "providers": [_provider("provider-a", self._base_a, "KEY_A"),
                          _provider("provider-b", self._base_b, "KEY_B")],
            "models": [_model("model-a", "provider-a", "upstream-a",
                              levels=["low", "medium"], default_level="low", mode="effort"),
                       _model("model-b", "provider-b", "upstream-b")],
            "bindings": {key: dict(value) for key, value in self._bindings.items()},
        }
        if overrides:
            document.update(overrides)
        self.config.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

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

    def admit(self) -> None:
        self.system.facade.record_admission("provider-a", "model-a", admitted_model="upstream-a")
        self.system.facade.record_admission("provider-b", "model-b", admitted_model="upstream-b")

def _post(client, command: str, **body: Any):
    return client.post(f"/api/commands/{command}", json={"command_id": str(uuid.uuid4()), **body})

def _create_project(client, name: str) -> str:
    response = _post(client, "project.create", name=name, goal="验证生效模型与调用目标")
    assert response.status_code == 200, response.text
    return response.json()["refs"]["project_id"]

def _workspace(client, project_id: str, department: str, *, work_item: str | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"project_id": project_id, "department": department}
    if work_item is not None:
        params["work_item"] = work_item
    response = client.get("/api/queries/department.workspace", params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]

def _run_of(system, project_id: str) -> str:
    items = system.projects.projection(project_id).work_items
    assert items and items[-1].run_id
    return items[-1].run_id

def _finish(system, run_id: str) -> None:
    deadline = time.monotonic() + WAIT_FOR_HOST_WORK_SEC
    while time.monotonic() < deadline:
        task = system.orchestrator.work_item_execution(run_id)
        if task is None or task.done():
            return
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not stop")

def _close(*servers: Any) -> None:
    for server in servers:
        server.shutdown()
        server.server_close()

def test_workspace_reports_the_effective_model_and_its_source(tmp_path):
    # 项目部门设置与部门默认分别提供模型时，department.workspace 返回的模型与来源正确：
    # 项目写入了模型的部门取项目设置，没有写入的部门取部门默认
    server_a, _capture_a, base_a = serve(_department_aware("upstream-a"))
    server_b, _capture_b, base_b = serve(_department_aware("upstream-b"))
    try:
        opened = _Opened(tmp_path, base_a, base_b)
        with running_api(opened) as client:
            opened.admit()
            project_id = _create_project(client, "P")
            saved = _post(client, "department_settings.save", base_version=0, project_id=project_id,
                          department="engineering", provider_id="provider-b", model_id="model-b")
            assert saved.status_code == 200, saved.text

            engineering = _workspace(client, project_id, "engineering")["effective"]
            assert engineering["state"] == "effective"
            assert (engineering["provider_id"], engineering["model_id"]) == ("provider-b", "model-b")
            assert engineering["model"] == "upstream-b"
            assert engineering["protocol"] == "responses"
            assert engineering["selection_source"] == "project_department_setting"

            product = _workspace(client, project_id, "product")["effective"]
            assert product["state"] == "effective"
            assert (product["provider_id"], product["model_id"]) == ("provider-a", "model-a")
            assert product["model"] == "upstream-a"
            assert product["selection_source"] == "department_default"
    finally:
        _close(server_a, server_b)

def test_workspace_reports_unset_when_no_level_selects_a_model(tmp_path):
    # 部门默认未设置、项目也没有写入模型时返回「未设置」，不返回其他连接或模型
    server_a, _capture_a, base_a = serve(_department_aware("upstream-a"))
    server_b, _capture_b, base_b = serve(_department_aware("upstream-b"))
    try:
        opened = _Opened(tmp_path, base_a, base_b, bindings={})
        with running_api(opened) as client:
            opened.admit()
            project_id = _create_project(client, "P")
            effective = _workspace(client, project_id, "product")["effective"]
            assert effective["state"] == "unset"
            assert effective["model_id"] is None and effective["provider_id"] is None
            assert effective["model"] is None and effective["provider_name"] is None
    finally:
        _close(server_a, server_b)

def test_workspace_reports_unusable_with_the_reason_and_no_other_model(tmp_path):
    # 所选模型的准入作废时返回「无法使用」与原因，不返回其他连接或模型
    server_a, _capture_a, base_a = serve(_department_aware("upstream-a"))
    server_b, _capture_b, base_b = serve(_department_aware("upstream-b"))
    try:
        opened = _Opened(tmp_path, base_a, base_b)
        with running_api(opened) as client:
            opened.admit()
            project_id = _create_project(client, "P")
            # 修改 A 连接的地址会作废该连接下全部定义的准入；项目部门设置与部门默认仍引用它
            document = opened.system.facade.to_document()
            document["providers"][0]["base_url"] = "http://127.0.0.1:9/v1"
            opened.system.facade.store_document(document)

            effective = _workspace(client, project_id, "engineering")["effective"]
            assert effective["state"] == "unusable"
            assert effective["reason"] == "provider_unavailable"
            assert "准入" in effective["message"]
            # 不返回其他连接或模型
            assert effective["model_id"] is None and effective["provider_id"] is None
            assert effective["model"] is None and effective["provider_name"] is None
    finally:
        _close(server_a, server_b)

def test_last_call_matches_the_request_event_after_switching_models(tmp_path):
    # 运行中更换模型以后，最近一次调用目标与请求事件一致：第一个事项按 A，换模型后第二个事项按 B，
    # 工作间的最近一次调用目标与最后一个工程部门的请求事件逐项相同
    server_a, _capture_a, base_a = serve(_department_aware("upstream-a"))
    server_b, _capture_b, base_b = serve(_department_aware("upstream-b"))
    try:
        opened = _Opened(tmp_path, base_a, base_b)
        with running_api(opened) as client:
            opened.admit()
            project_id = _create_project(client, "P")
            first = _post(client, "work_item.create", project_id=project_id, text="echo")
            assert first.status_code == 200, first.text
            _finish(opened.system, first.json()["refs"]["run_id"])

            # 更换模型为 B
            saved = _post(client, "department_settings.save", base_version=0, project_id=project_id,
                          department="engineering", provider_id="provider-b", model_id="model-b")
            assert saved.status_code == 200, saved.text
            second = _post(client, "work_item.create", project_id=project_id, text="echo")
            assert second.status_code == 200, second.text
            run_id = second.json()["refs"]["run_id"]
            _finish(opened.system, run_id)

            last = [event for event in opened.system.store.list_events(run_id)
                    if event.type == EventType.MODEL_REQUESTED and event.department == "engineering"]
            assert last
            event = last[-1]
            work_item_id = second.json()["refs"]["work_item_id"]
            last_call = _workspace(client, project_id, "engineering", work_item=work_item_id)["last_call"]
            assert last_call["requested_provider"] == event.payload["requested_provider"]
            assert last_call["requested_model"] == event.payload["requested_model"]
            assert last_call["requested_tier"] == event.payload["requested_tier"]
            assert last_call["sent_tier"] == event.payload["sent_tier"]
            assert last_call["selection_source"] == event.payload["selection_source"]
            assert last_call["prompt_version"] == event.payload["prompt_version"]
            assert last_call["requested_provider"] == "provider-b"
    finally:
        _close(server_a, server_b)

def test_run_attempt_carries_the_call_target_without_a_key(tmp_path):
    # run.attempt 返回的调用目标公开部分、选择来源与档位、部门 Prompt 版本；没有 API Key
    server_a, _capture_a, base_a = serve(_department_aware("upstream-a"))
    server_b, _capture_b, base_b = serve(_department_aware("upstream-b"))
    try:
        opened = _Opened(tmp_path, base_a, base_b)
        with running_api(opened) as client:
            opened.admit()
            project_id = _create_project(client, "P")
            saved = _post(client, "department_settings.save", base_version=0, project_id=project_id,
                          department="engineering", provider_id="provider-b", model_id="model-b")
            assert saved.status_code == 200, saved.text
            started = _post(client, "work_item.create", project_id=project_id, text="echo")
            assert started.status_code == 200, started.text
            run_id = started.json()["refs"]["run_id"]
            _finish(opened.system, run_id)

            attempts = client.get("/api/queries/project.attempts",
                                  params={"project_id": project_id}).json()["data"]["attempts"]
            assert attempts
            engineering = [item for item in attempts if item["department"] == "engineering"]
            assert engineering
            attempt_id = engineering[0]["attempt_id"]
            detail = client.get("/api/queries/run.attempt",
                                params={"run_id": run_id, "attempt_id": attempt_id}).json()["data"]["attempt"]
            target = detail["call_target"]
            assert target["selection_source"] == "project_department_setting"
            assert target["model_id"] == "model-b"
            assert target["requested_model"] == "upstream-b"
            assert target["requested_tier"] is None
            assert target["sent_tier"] is None
            assert detail["prompt_version"] is not None
            # 没有 API Key
            assert KEY_A not in json.dumps(detail, ensure_ascii=False)
            assert KEY_B not in json.dumps(detail, ensure_ascii=False)
            assert "api_key" not in json.dumps(target, ensure_ascii=False)
    finally:
        _close(server_a, server_b)

def test_project_attempts_filters_by_provider_and_model(tmp_path):
    # project.attempts 按 Provider 配置、请求模型与实际模型筛选
    server_a, _capture_a, base_a = serve(_department_aware("upstream-a"))
    server_b, _capture_b, base_b = serve(_department_aware("upstream-b"))
    try:
        opened = _Opened(tmp_path, base_a, base_b)
        with running_api(opened) as client:
            opened.admit()
            project_id = _create_project(client, "P")
            saved = _post(client, "department_settings.save", base_version=0, project_id=project_id,
                          department="engineering", provider_id="provider-b", model_id="model-b")
            assert saved.status_code == 200, saved.text
            started = _post(client, "work_item.create", project_id=project_id, text="echo")
            assert started.status_code == 200, started.text
            _finish(opened.system, started.json()["refs"]["run_id"])

            def attempts(**params: Any) -> list[dict[str, Any]]:
                response = client.get("/api/queries/project.attempts",
                                      params={"project_id": project_id, **params})
                assert response.status_code == 200, response.text
                return response.json()["data"]["attempts"]

            all_attempts = attempts()
            by_provider_b = attempts(provider="provider-b")
            by_provider_a = attempts(provider="provider-a")
            assert by_provider_b and by_provider_a
            assert {item["requested_provider"] for item in by_provider_b} == {"provider-b"}
            assert {item["requested_provider"] for item in by_provider_a} == {"provider-a"}
            assert by_provider_b == [item for item in all_attempts if item["requested_provider"] == "provider-b"]
            requested = attempts(requested_model="upstream-b")
            assert requested and {item["requested_model"] for item in requested} == {"upstream-b"}
            actual = attempts(actual_model="upstream-b")
            assert actual and {item["actual_model"] for item in actual} == {"upstream-b"}
            assert attempts(requested_model="upstream-missing") == []
    finally:
        _close(server_a, server_b)

def test_queries_do_not_append_events(tmp_path):
    # 调用查询前后事件日志末尾不变
    server_a, _capture_a, base_a = serve(_department_aware("upstream-a"))
    server_b, _capture_b, base_b = serve(_department_aware("upstream-b"))
    try:
        opened = _Opened(tmp_path, base_a, base_b)
        with running_api(opened) as client:
            opened.admit()
            project_id = _create_project(client, "P")
            started = _post(client, "work_item.create", project_id=project_id, text="echo")
            assert started.status_code == 200, started.text
            run_id = started.json()["refs"]["run_id"]
            _finish(opened.system, run_id)

            attempts = client.get("/api/queries/project.attempts",
                                  params={"project_id": project_id}).json()["data"]["attempts"]
            attempt_id = attempts[0]["attempt_id"]
            store = opened.system.store
            before = store.end_position()
            assert client.get("/api/queries/department.workspace",
                              params={"project_id": project_id, "department": "product"}).status_code == 200
            assert client.get("/api/queries/project.attempts",
                              params={"project_id": project_id}).status_code == 200
            assert client.get("/api/queries/run.attempt",
                              params={"run_id": run_id, "attempt_id": attempt_id}).status_code == 200
            assert store.end_position() == before
    finally:
        _close(server_a, server_b)
