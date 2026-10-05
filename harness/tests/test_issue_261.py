# 工单 #261：catalog.change_impact 对结构非法的拟议目录文档返回 422。
# 从运行系统整体测试：真实启动 FastAPI 应用，目录文件与 .env 是真实文件，事件日志是真实 SQLite。
# 拟议文档缺少必填项（max_output_tokens）或带有保存命令才有的字段（capacity_confirmed）时都不再是 500：
# 应用层把 Provider 模块的 CatalogValidationError 转成 CatalogQueryInvalid，接口层映射为 422，
# 响应体沿用查询错误的形状 {"error": <原因>}，原因写出字段位置（与命令被拒绝时 catalog_invalid 的字段位置同一写法）；
# 查询只读取，事件日志末尾不变。

from __future__ import annotations

import json
from typing import Any

from harness.tests.api_helpers import running_api
from harness.tests.test_issue_90 import _Opened, _document, _provider

DEPARTMENTS = ("product", "engineering", "quality")

def _model(model_id: str, provider_id: str) -> dict[str, Any]:
    return {"id": model_id, "provider_id": provider_id, "model": f"upstream-{model_id}",
            "context_window": 32000, "max_output_tokens": 2048, "capability_source": ""}

def _document_of(*, capacity_confirmed: bool = False, missing_required: bool = False) -> dict[str, Any]:
    model = _model("model-a", "provider-a")
    if missing_required:
        # max_output_tokens 是模型访问定义的必填项（store._parse_model）
        model.pop("max_output_tokens")
    if capacity_confirmed:
        model["capacity_confirmed"] = True
    return {"providers": [_provider("provider-a", "http://127.0.0.1:1/v1", "KEY_A")],
            "models": [model],
            "bindings": {department: {"provider_id": "provider-a", "model_id": "model-a"}
                         for department in DEPARTMENTS}}

def _impact(client, **params: Any):
    return client.get("/api/queries/catalog.change_impact", params=params)

def test_change_impact_refuses_a_document_missing_a_required_field(tmp_path):
    # 拟议文档缺少必填项 max_output_tokens：返回 422，响应体写出 models[0].max_output_tokens 的位置；事件日志末尾不变
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        opened.admit(("provider-a", "model-a"))
        document = json.dumps(_document_of(missing_required=True), ensure_ascii=False)
        end = opened.system.store.end_position()
        response = _impact(client, kind="document", document=document)
        assert response.status_code == 422, response.text
        assert "models[0].max_output_tokens" in response.json()["error"]
        assert opened.system.store.end_position() == end

def test_change_impact_refuses_a_document_with_a_save_only_field(tmp_path):
    # 拟议文档带有保存命令才有的 capacity_confirmed：返回 422，响应体写出 models[0].capacity_confirmed
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        opened.admit(("provider-a", "model-a"))
        document = json.dumps(_document_of(capacity_confirmed=True), ensure_ascii=False)
        end = opened.system.store.end_position()
        response = _impact(client, kind="document", document=document)
        assert response.status_code == 422, response.text
        assert "models[0].capacity_confirmed" in response.json()["error"]
        assert opened.system.store.end_position() == end

def test_change_impact_refuses_an_invalid_connection_document(tmp_path):
    # kind=connection 的拟议文档同样经 Provider 模块校验：带未知字段时返回 422 并写出字段位置
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        opened.admit(("provider-a", "model-a"))
        proposed = {"provider": {"id": "provider-a", "name": "provider-a", "protocol": "responses",
                                 "base_url": "http://127.0.0.1:2/v1", "credential_ref": "KEY_A",
                                 "timeout_sec": 20, "preset_id": "", "models_url": ""},
                    "models": [{"id": "model-a", "model": "upstream-a", "max_output_tokens": 2048,
                                "capacity_confirmed": True}]}
        document = json.dumps(proposed, ensure_ascii=False)
        end = opened.system.store.end_position()
        response = _impact(client, kind="connection", provider_id="provider-a", document=document)
        assert response.status_code == 422, response.text
        assert "capacity_confirmed" in response.json()["error"]
        assert opened.system.store.end_position() == end

def test_change_impact_keeps_working_for_a_valid_document(tmp_path):
    # 合法的拟议文档行为不变：仍返回 200，受影响定义与将一并删除的定义照常给出
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        opened.admit(("provider-a", "model-a"), ("provider-a", "model-a2"))
        document = _document(client)
        proposed = {"providers": document["providers"],
                    "models": [item for item in document["models"] if item["id"] != "model-a2"],
                    "bindings": document["bindings"]}
        response = _impact(client, kind="document",
                           document=json.dumps(proposed, ensure_ascii=False))
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert [item["model_id"] for item in data["deletions"]] == ["model-a2"]
        assert [item["model_id"] for item in data["impacted"]] == []

def test_change_impact_refuses_a_non_object_document_as_not_found(tmp_path):
    # 查询参数不是 JSON 对象：沿用查询目标不存在的 404，不是 422（既有口径不变）
    opened = _Opened(tmp_path)
    with running_api(opened) as client:
        opened.admit(("provider-a", "model-a"))
        end = opened.system.store.end_position()
        response = _impact(client, kind="document", document=json.dumps([1, 2, 3]))
        assert response.status_code == 404, response.text
        assert response.json()["error"]
        assert opened.system.store.end_position() == end
