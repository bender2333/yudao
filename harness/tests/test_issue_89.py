# 工单 #89：项目部门设置（模型访问定义引用、请求档位、部门 Prompt 三项，一起保存、一个版本）。
# 从运行系统整体测试：真实启动 FastAPI 应用，目录文件与 .env 是真实文件，事件日志是真实 SQLite；
# 模型回答由测试内启动的本机 HTTP 服务按 Responses 协议给出。
# 覆盖：按项目解析与选择来源、未写入项继承部门默认、按版本拒绝后提交的修改、准入作废时保存被拒绝、
# 某个部门无法解析时新建事项被拒绝并说明部门与具体项、run 内没有部门 Prompt 的副本。

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from harness.app.application import Application
from harness.models import DEPARTMENTS, EventType
from harness.tests.api_helpers import running_api
from harness.tests.protocol_helpers import serve, sse
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

KEY_A = "issue89-key-a"
KEY_B = "issue89-key-b"

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
    import re
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
    from harness.proposals import engineering_plan, product_spec
    kind = payload["kind"]
    value = product_spec() if kind == "product_spec" else engineering_plan()
    value.pop("kind")
    name = "submit_product_spec" if kind == "product_spec" else "submit_plan"
    item = {"id": f"call-{response_id}", "type": "function_call", "name": name, "call_id": f"call-{response_id}",
            "arguments": json.dumps(value, ensure_ascii=False), "status": "completed"}
    return 200, "text/event-stream", [_reply([item], response_id=response_id, model=model)]

def _department_aware(model: str):
    # 产品部门先提交产品要求，工程部门再提交一次工程计划，之后返回不带工具调用的回答让运行停下来
    state = {"plan": 0}
    def responder(body: dict[str, Any]) -> tuple[int, str, list[bytes]]:
        if _phase(body) != "ENGINEERING":
            return _proposal_reply(response_id="spec", model=model, payload={"kind": "product_spec"})
        if state["plan"] == 0:
            state["plan"] += 1
            return _proposal_reply(response_id="plan", model=model, payload={"kind": "engineering_plan"})
        return _text_reply(response_id="idle", model=model, text="waiting")
    return responder

def _provider(provider_id: str, base_url: str, ref: str) -> dict[str, Any]:
    return {"id": provider_id, "name": provider_id, "protocol": "responses", "base_url": base_url,
            "credential_ref": ref, "timeout_sec": 20, "preset_id": "", "models_url": ""}

def _model(model_id: str, provider_id: str, upstream: str, *, levels=None, default_level=None, mode="") -> dict[str, Any]:
    payload: dict[str, Any] = {"id": model_id, "provider_id": provider_id, "model": upstream,
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
        self._bindings = bindings or {department: {"provider_id": "provider-a", "model_id": "model-a"}
                                      for department in DEPARTMENTS}
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
    response = _post(client, "project.create", name=name, goal="验证项目部门设置")
    assert response.status_code == 200, response.text
    return response.json()["refs"]["project_id"]

def _settings(client, project_id: str, department: str) -> dict[str, Any]:
    response = client.get("/api/queries/project.settings", params={"project_id": project_id})
    assert response.status_code == 200, response.text
    return response.json()["data"]["departments"][department]

def _run_requests(system, run_id: str) -> list[Any]:
    return [event for event in system.store.list_events(run_id) if event.type == EventType.MODEL_REQUESTED]

def _run_of(system, project_id: str) -> str:
    items = system.projects.projection(project_id).work_items
    assert items and items[-1].run_id
    return items[-1].run_id

def test_a_project_department_setting_selects_its_own_model_with_its_source(tmp_path):
    # 项目 A 的工程部门另选模型以后，项目 A 工程部门的请求使用该模型，选择来源为项目部门设置；
    # 项目 B 与部门默认不变
    server_a, capture_a, base_a = serve(_department_aware("upstream-a"))
    server_b, capture_b, base_b = serve(_department_aware("upstream-b"))
    try:
        opened = _Opened(tmp_path, base_a, base_b)
        with running_api(opened) as client:
            opened.admit()
            project_a = _create_project(client, "A")
            project_b = _create_project(client, "B")

            saved = _post(client, "department_settings.save", base_version=0, project_id=project_a,
                          department="engineering", provider_id="provider-b", model_id="model-b")
            assert saved.status_code == 200, saved.text
            setting_a = _settings(client, project_a, "engineering")
            assert (setting_a["provider_id"], setting_a["model_id"], setting_a["version"]) == (
                "provider-b", "model-b", 1)
            # 项目 B 与部门默认不变
            assert _settings(client, project_b, "engineering")["model_id"] is None
            assert opened.system.facade.get_bindings()["engineering"]["model_id"] == "model-a"

            started_a = _post(client, "work_item.create", project_id=project_a, text="echo")
            assert started_a.status_code == 200, started_a.text
            run_a = started_a.json()["refs"]["run_id"]
            _finish(opened.system, run_a)
            started_b = _post(client, "work_item.create", project_id=project_b, text="echo")
            assert started_b.status_code == 200, started_b.text
            run_b = started_b.json()["refs"]["run_id"]
            _finish(opened.system, run_b)

            # 项目 A 的工程部门请求全部发往 provider-b；项目 B 的请求全部发往 provider-a
            assert {item["model"] for item in capture_b.requests} == {"upstream-b"}
            assert {item["model"] for item in capture_a.requests} == {"upstream-a"}
            engineering = [event for event in _run_requests(opened.system, run_a)
                           if event.department == "engineering"]
            assert engineering
            assert {event.payload["selection_source"] for event in engineering} == {"project_department_setting"}
            product = [event for event in _run_requests(opened.system, run_a) if event.department == "product"]
            assert product and {event.payload["selection_source"] for event in product} == {"department_default"}
    finally:
        _close(server_a, server_b)

def test_writing_only_the_model_keeps_the_default_tier_limited_to_the_model(tmp_path):
    # 项目部门设置只写入模型、没有写入档位时，请求档位取自部门默认并按新模型的支持范围限制
    server_a, _capture_a, base_a = serve(_department_aware("upstream-a"))
    server_b, capture_b, base_b = serve(_department_aware("upstream-b"))
    try:
        bindings = {department: {"provider_id": "provider-a", "model_id": "model-a"} for department in DEPARTMENTS}
        bindings["engineering"] = {"provider_id": "provider-a", "model_id": "model-a", "requested_tier": "medium"}
        opened = _Opened(tmp_path, base_a, base_b, bindings=bindings)
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
            engineering = [event for event in _run_requests(opened.system, run_id)
                           if event.department == "engineering"]
            assert engineering
            assert engineering[0].payload["requested_tier"] == "medium"
            # 新模型没有声明支持档位，实际不发送推理参数
            assert engineering[0].payload["sent_tier"] is None
            assert capture_b.requests
    finally:
        _close(server_a, server_b)

def test_setting_only_a_prompt_clears_the_project_model_choice(tmp_path):
    # 选择「跟随部门默认」清除本项目的模型选择：只写入部门 Prompt 的保存不保留本项目的模型
    server_a, capture_a, base_a = serve(lambda _body: _text_reply(response_id="ra", model="upstream-a", text="ok"))
    server_b, capture_b, base_b = serve(lambda _body: _text_reply(response_id="rb", model="upstream-b", text="ok"))
    try:
        opened = _Opened(tmp_path, base_a, base_b)
        with running_api(opened) as client:
            opened.admit()
            project_id = _create_project(client, "P")
            assert _post(client, "department_settings.save", base_version=0, project_id=project_id,
                         department="engineering", provider_id="provider-b", model_id="model-b").status_code == 200
            # 再保存一次只带部门 Prompt：模型选择被清除（跟随部门默认）
            saved = _post(client, "department_settings.save", base_version=1, project_id=project_id,
                          department="engineering", department_prompt="工程规则")
            assert saved.status_code == 200, saved.text
            setting = _settings(client, project_id, "engineering")
            assert setting["model_id"] is None and setting["provider_id"] is None
            assert setting["prompt_configured"] is True

            started = _post(client, "work_item.create", project_id=project_id, text="echo")
            run_id = started.json()["refs"]["run_id"]
            _finish(opened.system, run_id)
            # 工程部门回到部门默认 provider-a
            assert capture_a.requests and not capture_b.requests
    finally:
        _close(server_a, server_b)

def test_two_saves_on_the_same_version_reject_the_second_with_the_current_version(tmp_path):
    server_a, _capture_a, base_a = serve(lambda _body: _text_reply(response_id="ra", model="upstream-a", text="ok"))
    server_b, _capture_b, base_b = serve(lambda _body: _text_reply(response_id="rb", model="upstream-b", text="ok"))
    try:
        opened = _Opened(tmp_path, base_a, base_b)
        with running_api(opened) as client:
            project_id = _create_project(client, "P")
            first = _post(client, "department_settings.save", base_version=0, project_id=project_id,
                          department="engineering", department_prompt="v1")
            assert first.status_code == 200, first.text
            stale = _post(client, "department_settings.save", base_version=0, project_id=project_id,
                          department="engineering", department_prompt="v2")
            assert stale.status_code == 409, stale.text
            assert stale.json()["reason"] == "stale_base" and stale.json()["current_version"] == 1
            assert _settings(client, project_id, "engineering")["version"] == 1
    finally:
        _close(server_a, server_b)

def test_a_project_setting_cannot_select_a_definition_whose_admission_is_revoked(tmp_path):
    server_a, _capture_a, base_a = serve(lambda _body: _text_reply(response_id="ra", model="upstream-a", text="ok"))
    server_b, _capture_b, base_b = serve(lambda _body: _text_reply(response_id="rb", model="upstream-b", text="ok"))
    try:
        opened = _Opened(tmp_path, base_a, base_b)
        with running_api(opened) as client:
            opened.admit()
            project_id = _create_project(client, "P")
            # 改连接的地址作废该连接下全部定义的准入
            document = opened.system.facade.to_document()
            document["providers"][1]["base_url"] = "http://127.0.0.1:9/v1"
            opened.system.facade.store_document(document)
            rejected = _post(client, "department_settings.save", base_version=0, project_id=project_id,
                             department="engineering", provider_id="provider-b", model_id="model-b")
            assert rejected.status_code == 409, rejected.text
            assert rejected.json()["reason"] == "not_allowed" and "准入" in rejected.json()["message"]
            assert _settings(client, project_id, "engineering")["version"] == 0
    finally:
        _close(server_a, server_b)

def test_work_item_creation_is_rejected_when_a_department_cannot_resolve(tmp_path):
    # 项目 A 的工程部门选中的定义准入作废：新建事项被拒绝，原因写明部门与具体项；
    # 没有写入任何项目部门设置的项目按部门默认检查
    server_a, _capture_a, base_a = serve(lambda _body: _text_reply(response_id="ra", model="upstream-a", text="ok"))
    server_b, _capture_b, base_b = serve(lambda _body: _text_reply(response_id="rb", model="upstream-b", text="ok"))
    try:
        opened = _Opened(tmp_path, base_a, base_b)
        with running_api(opened) as client:
            opened.admit()
            project_a = _create_project(client, "A")
            project_b = _create_project(client, "B")
            assert _post(client, "department_settings.save", base_version=0, project_id=project_a,
                         department="engineering", provider_id="provider-b",
                         model_id="model-b").status_code == 200
            # 项目 B 没有写入任何项目部门设置，按部门默认检查，可以新建
            allowed = _post(client, "work_item.create", project_id=project_b, text="B 的事项")
            assert allowed.status_code == 200, allowed.text
            _finish(opened.system, allowed.json()["refs"]["run_id"])

            document = opened.system.facade.to_document()
            document["providers"][1]["base_url"] = "http://127.0.0.1:9/v1"
            opened.system.facade.store_document(document)
            rejected = _post(client, "work_item.create", project_id=project_a, text="A 的事项")
            assert rejected.status_code == 409, rejected.text
            assert rejected.json()["reason"] == "provider_unavailable"
            assert "engineering" in rejected.json()["message"]
            assert "模型访问定义" in rejected.json()["message"]
    finally:
        _close(server_a, server_b)

def test_the_run_has_no_department_prompt_copy_and_records_the_project_version(tmp_path):
    server_a, _capture_a, base_a = serve(_department_aware("upstream-a"))
    server_b, _capture_b, base_b = serve(_department_aware("upstream-b"))
    try:
        opened = _Opened(tmp_path, base_a, base_b)
        with running_api(opened) as client:
            opened.admit()
            project_id = _create_project(client, "P")
            assert _post(client, "department_settings.save", base_version=0, project_id=project_id,
                         department="engineering", department_prompt="工程规则 v1").status_code == 200
            started = _post(client, "work_item.create", project_id=project_id, text="echo")
            run_id = started.json()["refs"]["run_id"]
            _finish(opened.system, run_id)
            run = opened.system.project(run_id)
            assert not hasattr(run, "department_prompts")
            created = next(event for event in opened.system.store.list_events(run_id)
                           if event.type == EventType.RUN_CREATED)
            assert "department_prompts" not in created.payload
            requests = [event for event in _run_requests(opened.system, run_id)
                        if event.department == "engineering"]
            assert requests and all(event.payload["prompt_version"] == 1 for event in requests)
            assert all("工程规则 v1" not in json.dumps(event.payload, ensure_ascii=False) for event in requests)
    finally:
        _close(server_a, server_b)

def test_a_project_setting_tier_outside_the_model_levels_is_saved_and_limited_on_request(tmp_path):
    # 项目部门设置与部门默认同一套保存规则（设计说明第 4.6、7.3 节）：保存只核对请求档位属于档位全集，
    # 超出所选模型支持档位的档位照常保存，下一次请求按该模型的支持档位限制
    server_a, capture_a, base_a = serve(_department_aware("upstream-a"))
    server_b, capture_b, base_b = serve(_department_aware("upstream-b"))
    try:
        opened = _Opened(tmp_path, base_a, base_b)
        with running_api(opened) as client:
            opened.admit()
            project_id = _create_project(client, "P")
            # model-b 没有声明支持档位，high 仍属于档位全集，保存被接受
            saved = _post(client, "department_settings.save", base_version=0, project_id=project_id,
                          department="engineering", provider_id="provider-b", model_id="model-b",
                          requested_tier="high")
            assert saved.status_code == 200, saved.text
            assert _settings(client, project_id, "engineering")["requested_tier"] == "high"

            started = _post(client, "work_item.create", project_id=project_id, text="echo")
            assert started.status_code == 200, started.text
            run_id = started.json()["refs"]["run_id"]
            _finish(opened.system, run_id)
            engineering = [event for event in _run_requests(opened.system, run_id)
                           if event.department == "engineering"]
            assert engineering
            assert engineering[0].payload["requested_tier"] == "high"
            # 新模型没有声明支持档位，请求不带推理参数
            assert engineering[0].payload["sent_tier"] is None
            # 产品部门仍用部门默认的 model-a，工程部门用项目部门设置选中的 model-b
            assert {item["model"] for item in capture_b.requests} == {"upstream-b"}
            assert {item["model"] for item in capture_a.requests} == {"upstream-a"}
    finally:
        _close(server_a, server_b)

def test_a_project_setting_rejects_a_tier_outside_the_full_set(tmp_path):
    # 请求档位不属于档位全集时保存被拒绝，并指出字段位置
    server_a, _capture_a, base_a = serve(lambda _body: _text_reply(response_id="ra", model="upstream-a", text="ok"))
    server_b, _capture_b, base_b = serve(lambda _body: _text_reply(response_id="rb", model="upstream-b", text="ok"))
    try:
        opened = _Opened(tmp_path, base_a, base_b)
        with running_api(opened) as client:
            opened.admit()
            project_id = _create_project(client, "P")
            rejected = _post(client, "department_settings.save", base_version=0, project_id=project_id,
                             department="engineering", provider_id="provider-b", model_id="model-b",
                             requested_tier="extreme")
            assert rejected.status_code == 409, rejected.text
            assert "departments.engineering.requested_tier" in rejected.json()["message"]
            assert _settings(client, project_id, "engineering")["version"] == 0
    finally:
        _close(server_a, server_b)

def test_a_project_setting_rejects_a_tier_outside_the_full_set_without_writing_a_model(tmp_path):
    # 模型访问定义与请求档位分别继承（设计说明第 5.2、5.3、9.2 节）：只写入请求档位、模型跟随部门默认时，
    # 写入的请求档位同样要属于档位全集，不因此跳过核对
    server_a, _capture_a, base_a = serve(lambda _body: _text_reply(response_id="ra", model="upstream-a", text="ok"))
    server_b, _capture_b, base_b = serve(lambda _body: _text_reply(response_id="rb", model="upstream-b", text="ok"))
    try:
        opened = _Opened(tmp_path, base_a, base_b)
        with running_api(opened) as client:
            opened.admit()
            project_id = _create_project(client, "P")
            rejected = _post(client, "department_settings.save", base_version=0, project_id=project_id,
                             department="engineering", requested_tier="extreme")
            assert rejected.status_code == 409, rejected.text
            assert "departments.engineering.requested_tier" in rejected.json()["message"]
            assert _settings(client, project_id, "engineering")["version"] == 0
    finally:
        _close(server_a, server_b)

def _finish(system, run_id: str) -> None:
    # 事项的执行在接口进程的事件循环中作为任务运行；等这个任务结束（停在阻塞处或终止）
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
