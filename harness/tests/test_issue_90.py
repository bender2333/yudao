# 工单 #90：修改前的影响列表与删除时的引用检查。
# 从运行系统整体测试：真实启动 FastAPI 应用，目录文件与 .env 是真实文件，事件日志是真实 SQLite。
# 覆盖设计说明第 4.4 节最后一段（保存前的影响列表）与第 4.5 节（移除定义、删除 Provider 配置、导入整份文档）：
#   1) 修改被部门默认与两个项目引用的连接的地址：影响列表写出受影响定义、部门默认中的部门、
#      两个项目的部门与进行中事项；保存以后这些定义回到候选；
#   2) 移除被项目部门设置引用的定义返回 in_use 与引用方；没有引用时成功；
#   3) 删除其下有定义但都没有被引用的 Provider 配置，定义一并删除；有引用时返回 in_use 与引用方；
#   4) 导入移除了被引用定义的目录文档被整份拒绝，错误写出引用方。

from __future__ import annotations

import json
import uuid
from typing import Any

from harness.app.application import Application
from harness.models import DEPARTMENTS
from harness.tests.api_helpers import running_api
from harness.tests.protocol_helpers import serve, sse

KEY_A = "issue90-key-a"
KEY_B = "issue90-key-b"

def _event(kind: str, **payload: Any) -> str:
    return f"event: {kind}\ndata: {json.dumps({'type': kind, **payload}, ensure_ascii=False)}\n\n"

def _text_reply(*, response_id: str, model: str, text: str) -> tuple[int, str, list[bytes]]:
    # 不要求调用工具的回答：要让运行停下来，必须让事项处在进行中，因此这里给一个普通回答
    response = {
        "id": response_id, "object": "response", "created_at": 1, "status": "completed", "model": model,
        "output": [{"id": f"msg-{response_id}", "type": "message", "role": "assistant",
                    "status": "completed",
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

def _proposal_reply(*, response_id: str, model: str, payload: dict[str, Any]) -> tuple[int, str, list[bytes]]:
    # 带工具调用的回答：部门要交出结构化提案，运行才会离开起始阶段、进入下一个部门
    from harness.proposals import engineering_plan, product_spec
    kind = payload["kind"]
    value = product_spec() if kind == "product_spec" else engineering_plan()
    value.pop("kind")
    name = "submit_product_spec" if kind == "product_spec" else "submit_plan"
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

def _department_aware(model: str = "upstream-a", *, on_product=None):
    # 产品部门先提交产品要求，工程部门再提交工程计划，之后返回不带工具调用的普通回答让运行停下来。
    # on_product 在产品交完提案以后调用一次：可以让此时刻之后的工程部门解析不到目标，
    # 使运行停在工程进行中（不是终止阶段，事项保持「进行中」且部门是工程部门）
    state = {"plan": 0}
    def responder(body: dict[str, Any]) -> tuple[int, str, list[bytes]]:
        chosen = str(body.get("model") or model)
        if _phase(body) != "ENGINEERING":
            reply = _proposal_reply(response_id="spec", model=chosen, payload={"kind": "product_spec"})
            if on_product is not None:
                on_product()
            return reply
        if state["plan"] == 0:
            state["plan"] += 1
            return _proposal_reply(response_id="plan", model=chosen, payload={"kind": "engineering_plan"})
        return _text_reply(response_id="idle", model=chosen, text="按当前计划继续。")
    return responder

def _provider(provider_id: str, base_url: str, ref: str) -> dict[str, Any]:
    return {"id": provider_id, "name": provider_id, "protocol": "responses", "base_url": base_url,
            "credential_ref": ref, "timeout_sec": 20, "preset_id": "", "models_url": ""}

def _model(model_id: str, provider_id: str, upstream: str) -> dict[str, Any]:
    return {"id": model_id, "provider_id": provider_id, "model": upstream,
            "context_window": 32000, "max_output_tokens": 2048, "capability_source": ""}

class _Opened:
    # 与 issue89 相同的整体启动方式：真实目录文件、真实 .env、真实数据目录；base_url 指向测试内启动的本机模型服务
    def __init__(self, tmp_path, *, base_url: str = "http://127.0.0.1:1/v1"):
        self.data_dir = tmp_path / "data"
        self.config = tmp_path / "providers.json"
        self.dotenv = tmp_path / ".env"
        self._base_url = base_url
        self.applications: list[Application] = []
        self.write_document()

    def write_document(self) -> None:
        providers = [_provider("provider-a", self._base_url, "KEY_A"),
                     _provider("provider-b", self._base_url, "KEY_B")]
        models = [_model("model-a", "provider-a", "upstream-a"),
                  _model("model-a2", "provider-a", "upstream-a2"),
                  _model("model-b", "provider-b", "upstream-b")]
        document = {
            "providers": providers,
            "models": models,
            # 所有部门默认都指向 model-a：这样 model-a 被部门默认引用（移除/导入移除它被拒绝），
            # model-a2 与 model-b 没有被任何部门默认引用（移除它们成功，删除 provider-b 也成功）
            "bindings": {department: {"provider_id": "provider-a", "model_id": "model-a"}
                         for department in DEPARTMENTS},
        }
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

def _impact(client, **params: Any) -> dict[str, Any]:
    response = client.get("/api/queries/catalog.change_impact", params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]

def _create_project(client, name: str) -> str:
    response = _post(client, "project.create", name=name, goal="验证影响列表")
    assert response.status_code == 200, response.text
    return response.json()["refs"]["project_id"]

def _set_model(client, project_id: str, department: str, *, provider_id: str, model_id: str) -> None:
    saved = _post(client, "department_settings.save", base_version=0, project_id=project_id,
                  department=department, provider_id=provider_id, model_id=model_id)
    assert saved.status_code == 200, saved.text

def _start_work_item(client, project_id: str) -> str:
    started = _post(client, "work_item.create", project_id=project_id, text="验证影响列表")
    assert started.status_code == 200, started.text
    return started.json()["refs"]["run_id"]

def _finish(system, run_id: str) -> None:
    # 事项的执行在接口进程的事件循环中作为任务运行；等这个任务结束（停在阻塞处或终止）
    import time
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        task = system.orchestrator.work_item_execution(run_id)
        if task is None or task.done():
            return
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not stop")

def _stale_definitions(catalog: dict[str, Any]) -> set[str]:
    # 有准入记录但已作废的定义（回到候选）：视图里 admitted 与 stale 互斥
    return {item["model_id"] for item in catalog["admissions"] if item["stale"]}

def test_connection_address_change_lists_impact_and_returns_definitions_to_candidates(tmp_path):
    # 修改一份被部门默认与两个项目工程部门引用的连接的地址：保存之前的影响列表写出受影响定义、
    # 部门默认中的部门、两个项目的部门与正在使用它的进行中事项；保存以后这些定义回到候选
    parked: dict[str, Any] = {}
    def park_engineering() -> None:
        # 产品交完提案以后作废 model-a 的准入，让工程部门此时刻解析不到目标，运行停在工程进行中。
        # 暂存准入记录，停稳以后放回，使后续的影响列表与候选判断仍在有效准入上比较
        parked["record"] = opened.system.facade._admissions.pop("model-a", None)
    server, _capture, base_url = serve(_department_aware(on_product=park_engineering))
    try:
        opened = _Opened(tmp_path, base_url=base_url)
        with running_api(opened) as client:
            opened.admit(("provider-a", "model-a"), ("provider-a", "model-a2"))
            project_a = _create_project(client, "A")
            project_b = _create_project(client, "B")
            _set_model(client, project_a, "engineering", provider_id="provider-a", model_id="model-a")
            _set_model(client, project_b, "engineering", provider_id="provider-a", model_id="model-a")
            run_a = _start_work_item(client, project_a)
            _finish(opened.system, run_a)
            if parked.get("record") is not None:
                opened.system.facade._admissions["model-a"] = parked["record"]
            item_a = opened.system.projects.projection(project_a).work_items[-1]
            assert item_a.status == "in_progress", (item_a.status, item_a.phase)

            document = _document(client)
            proposed = _provider("provider-a", "http://127.0.0.1:2/v1", "KEY_A")
            impact = _impact(client, kind="connection", provider_id="provider-a",
                             document=json.dumps({"provider": proposed}, ensure_ascii=False))

            # 连接地址作废该连接下全部准入的定义：model-a2 也在该连接下，因此两条都受影响
            assert [item["model_id"] for item in impact["impacted"]] == ["model-a", "model-a2"]
            # 部门默认中引用 model-a 的部门包含工程部门（三个部门默认都指向 model-a）
            assert "engineering" in {item["department"] for item in impact["department_defaults"]}
            assert {item["project_id"] for item in impact["project_settings"]} == {project_a, project_b}
            assert {item["department"] for item in impact["project_settings"]} == {"engineering"}
            assert {item["project_id"] for item in impact["work_items"]} == {project_a}
            assert {item["work_item_id"] for item in impact["work_items"]} == {item_a.work_item_id}
            assert {item["department"] for item in impact["work_items"]} == {"engineering"}
            assert impact["revision"] == document["revision"]

            saved = _post(client, "catalog.connection.save", base_version=impact["revision"],
                          provider=proposed,
                          models=[{"id": item["id"], "model": item["model"],
                                   "context_window": item.get("context_window"),
                                   "max_output_tokens": item["max_output_tokens"],
                                   "capability_source": item.get("capability_source", ""),
                                   "capacity_confirmed": True}
                                  for item in document["models"]
                                  if item["provider_id"] == "provider-a"])
            assert saved.status_code == 200, saved.text
            # 保存以后这些定义回到候选（准入作废），引用保留
            assert "model-a" in _stale_definitions(_catalog(client))
            assert opened.system.facade.get_bindings()["engineering"]["model_id"] == "model-a"
    finally:
        server.shutdown()
        server.server_close()

def test_remove_definition_referenced_by_project_is_rejected_and_unreferenced_succeeds(tmp_path):
    # 移除被项目部门设置引用的定义返回 in_use 与引用方；移除没有被引用的定义成功
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        opened.admit(("provider-a", "model-a"), ("provider-a", "model-a2"))
        project_id = _create_project(client, "P")
        _set_model(client, project_id, "engineering", provider_id="provider-a", model_id="model-a")

        rejected = _post(client, "catalog.model.remove", base_version=_catalog(client)["revision"],
                         provider_id="provider-a", model_id="model-a")
        assert rejected.status_code == 409, rejected.text
        body = rejected.json()
        assert body["reason"] == "in_use"
        assert f"projects.{project_id}.department_settings.engineering" in body["message"]
        # 定义还在，目录没有变化
        assert any(item["id"] == "model-a" for item in _document(client)["models"])

        removed = _post(client, "catalog.model.remove", base_version=_catalog(client)["revision"],
                        provider_id="provider-a", model_id="model-a2")
        assert removed.status_code == 200, removed.text
        assert not any(item["id"] == "model-a2" for item in _document(client)["models"])

def test_remove_definition_referenced_by_department_default_is_rejected(tmp_path):
    # 移除被部门默认引用的定义返回 in_use，引用方是部门默认中的部门
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        opened.admit(("provider-a", "model-a"))
        rejected = _post(client, "catalog.model.remove", base_version=_catalog(client)["revision"],
                         provider_id="provider-a", model_id="model-a")
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["reason"] == "in_use"
        assert "bindings.engineering" in rejected.json()["message"]

def test_provider_delete_lists_definitions_and_deletes_unreferenced_ones(tmp_path):
    # 删除其下有定义但都没有被引用的 Provider 配置：删除之前的影响列表列出将一并删除的定义，删除以后定义消失；
    # 有引用时返回 in_use 与引用方
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        opened.admit(("provider-b", "model-b"))
        impact = _impact(client, kind="provider", provider_id="provider-b")
        assert [item["model_id"] for item in impact["deletions"]] == ["model-b"]

        deleted = _post(client, "catalog.connection.delete", base_version=_catalog(client)["revision"],
                        provider_id="provider-b")
        assert deleted.status_code == 200, deleted.text
        document = _document(client)
        assert not any(item["id"] == "provider-b" for item in document["providers"])
        assert not any(item["provider_id"] == "provider-b" for item in document["models"])

        # 有引用时：项目部门设置引用 provider-b 的定义，删除被拒绝并列出引用方
        project_id = _create_project(client, "P")
        saved = _post(client, "catalog.connection.save", base_version=_catalog(client)["revision"],
                      provider=_provider("provider-b", "http://127.0.0.1:1/v1", "KEY_B"),
                      models=[{"id": "model-b", "model": "upstream-b", "context_window": 32000,
                               "max_output_tokens": 2048, "capability_source": "",
                               "capacity_confirmed": True}])
        assert saved.status_code == 200, saved.text
        _set_model(client, project_id, "engineering", provider_id="provider-b", model_id="model-b")

        rejected = _post(client, "catalog.connection.delete", base_version=_catalog(client)["revision"],
                         provider_id="provider-b")
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["reason"] == "in_use"
        assert f"projects.{project_id}.department_settings.engineering" in rejected.json()["message"]

def test_import_removing_referenced_definition_is_rejected_as_a_whole(tmp_path):
    # 导入移除了被引用定义的目录文档：整份拒绝，错误写出引用方；目录没有变化
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        opened.admit(("provider-a", "model-a"))
        project_id = _create_project(client, "P")
        _set_model(client, project_id, "engineering", provider_id="provider-a", model_id="model-a")

        document = _document(client)
        # 文档里去掉 model-a，只保留 model-a2 与 model-b（部门默认指向 model-a，项目部门设置也指向它）
        trimmed = {
            "providers": [item for item in document["providers"]],
            "models": [item for item in document["models"] if item["id"] != "model-a"],
            "bindings": {key: value for key, value in document["bindings"].items()},
        }
        rejected = _post(client, "catalog.document.save", base_version=_catalog(client)["revision"],
                         document=trimmed)
        assert rejected.status_code == 409, rejected.text
        body = rejected.json()
        assert body["reason"] == "in_use"
        assert "bindings.engineering" in body["message"]
        # 目录没有变化
        assert any(item["id"] == "model-a" for item in _document(client)["models"])

def test_import_removing_unreferenced_definition_succeeds(tmp_path):
    # 导入移除了没有被引用定义的目录文档：整份接受（对照上一条）
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        opened.admit(("provider-a", "model-a"), ("provider-a", "model-a2"))
        document = _document(client)
        trimmed = {
            "providers": [item for item in document["providers"]],
            "models": [item for item in document["models"] if item["id"] != "model-a2"],
            "bindings": {key: value for key, value in document["bindings"].items()},
        }
        saved = _post(client, "catalog.document.save", base_version=_catalog(client)["revision"],
                      document=trimmed)
        assert saved.status_code == 200, saved.text
        assert not any(item["id"] == "model-a2" for item in _document(client)["models"])
