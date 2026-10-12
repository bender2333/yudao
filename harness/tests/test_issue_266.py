# 工单 #266：重新启动以后从准入文件恢复已准入的定义。
# 从运行系统整体测试：真实目录文件、真实准入文件与真实 HTTP 上游（Responses 协议）。
# 覆盖设计说明第 4.3、4.4 节与 ADR-0002：
#   1) 模型测试通过后写入准入记录，重新启动系统（新建 LoopSystem 指向同一数据目录与目录文件）以后，
#      describe_readiness 与部门的调用目标解析都把该定义当作已准入，不需要再运行模型测试；
#   2) 目录文件被外部修改使准入作废（地址变化）以后重新启动，该定义不被当作已准入；
#      删除目录文件以后重新启动，准入为空；
#   3) harness smoke 在真实目录与准入文件存在时不再报「模型尚未通过模型测试准入」。

from __future__ import annotations

import json
from typing import Any

from harness.models import DEPARTMENTS
from harness.runtime import LoopSystem
from harness.smoke import run_smoke
from harness.tests.protocol_helpers import serve, sse

KEY_A = "issue266-key-a"

def _event(kind: str, **payload: Any) -> str:
    return f"event: {kind}\ndata: {json.dumps({'type': kind, **payload}, ensure_ascii=False)}\n\n"

def _text_reply(*, response_id: str, model: str, text: str) -> tuple[int, str, list[bytes]]:
    # Responses 协议的最小回答：模型测试只要求拿到一次回应
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

def _model_reply(model: str = "upstream-a"):
    def responder(body: dict[str, Any]) -> tuple[int, str, list[bytes]]:
        chosen = str(body.get("model") or model)
        return _text_reply(response_id="ping", model=chosen, text="pong")
    return responder

def _provider(provider_id: str, base_url: str, ref: str) -> dict[str, Any]:
    return {"id": provider_id, "name": provider_id, "base_url": base_url,
            "credential_ref": ref, "timeout_sec": 20, "preset_id": "", "models_url": ""}

def _model(model_id: str, provider_id: str, upstream: str) -> dict[str, Any]:
    return {"id": model_id, "provider_id": provider_id, "model": upstream,
            "protocol": "responses",
            "context_window": 32000, "max_output_tokens": 2048, "capability_source": ""}

class _Opened:
    # 真实目录文件、真实 .env、真实数据目录；base_url 指向测试内启动的本机模型服务
    def __init__(self, tmp_path, *, base_url: str):
        self.data_dir = tmp_path / "data"
        self.config = tmp_path / "providers.json"
        self.admissions = tmp_path / "admissions.json"
        self.dotenv = tmp_path / ".env"
        self._base_url = base_url
        self.systems: list[LoopSystem] = []
        self.write_document()

    def document(self) -> dict[str, Any]:
        return {
            "providers": [_provider("provider-a", self._base_url, "KEY_A")],
            "models": [_model("model-a", "provider-a", "upstream-a"),
                       _model("model-a2", "provider-a", "upstream-a2")],
            "bindings": {department: {"provider_id": "provider-a", "model_id": "model-a"}
                         for department in DEPARTMENTS},
        }

    def write_document(self, document: dict[str, Any] | None = None) -> None:
        self.config.write_text(json.dumps(document or self.document(), ensure_ascii=False), encoding="utf-8")

    def start(self) -> LoopSystem:
        # 新建一个指向同一数据目录与目录文件的系统：走 configure_paths 加 reload 的启动路径
        self.dotenv.write_text(f"KEY_A={KEY_A}\n", encoding="utf-8")
        system = LoopSystem(self.data_dir, provider_config_path=self.config, dotenv_path=self.dotenv)
        self.systems.append(system)
        return system

    def restart(self) -> LoopSystem:
        # 重新启动：先关闭上一个系统的写入口（数据目录同一时刻只允许一个写者），再新建系统
        if self.systems:
            self.systems[-1].store.close()
        return self.start()

def _admitted_ids(system: LoopSystem) -> set[str]:
    return {item["model_id"] for item in system.facade.model_admissions() if item["admitted"]}

def _department_target_ok(system: LoopSystem, department: str) -> bool:
    resolution = system.facade.resolve_department_default(department)
    if resolution.handle_id is not None:
        system.facade.release_call_handle(resolution.handle_id)
    return bool(resolution.available)

def test_restart_restores_admitted_definitions_from_the_admission_file(tmp_path):
    # 模型测试通过写入准入记录，重新启动系统以后 describe_readiness 与部门调用目标解析都当作已准入
    server, _capture, base_url = serve(_model_reply())
    try:
        opened = _Opened(tmp_path, base_url=base_url)
        first = opened.start()
        # 未执行模型测试之前，部门默认引用的定义尚未准入
        assert first.facade.describe_readiness()["available"] is False
        assert "尚未通过模型测试准入" in first.provider_status()["message"]
        result = first.facade.model_test("provider-a", "model-a")
        assert result["ok"] is True, result
        assert result["admitted"] is True and result["persisted"] is True
        assert opened.admissions.is_file() and "model-a" in opened.admissions.read_text(encoding="utf-8")

        restarted = opened.restart()
        # describe_readiness 视为可用，部门调用目标解析成功，不需要再运行模型测试
        readiness = restarted.facade.describe_readiness()
        assert readiness["available"] is True, readiness
        assert _admitted_ids(restarted) == {"model-a"}
        for department in DEPARTMENTS:
            assert _department_target_ok(restarted, department), department
        restarted.close()
    finally:
        server.shutdown()
        server.server_close()

def test_restart_does_not_admit_a_definition_whose_admission_became_stale(tmp_path):
    # 目录文件被外部修改使准入作废（地址变化）以后重新启动，该定义不被当作已准入
    server, _capture, base_url = serve(_model_reply())
    try:
        opened = _Opened(tmp_path, base_url=base_url)
        first = opened.start()
        assert first.facade.model_test("provider-a", "model-a")["admitted"] is True
        first.store.close()

        changed = opened.document()
        changed["providers"][0]["base_url"] = "http://127.0.0.1:2/v1"
        opened.write_document(changed)

        restarted = opened.start()
        readiness = restarted.facade.describe_readiness()
        assert readiness["available"] is False
        assert _admitted_ids(restarted) == set()
        assert not _department_target_ok(restarted, "product")
        restarted.close()
    finally:
        server.shutdown()
        server.server_close()

def test_restart_after_deleting_the_catalog_clears_admissions(tmp_path):
    # 删除目录文件以后重新启动，准入为空
    server, _capture, base_url = serve(_model_reply())
    try:
        opened = _Opened(tmp_path, base_url=base_url)
        first = opened.start()
        assert first.facade.model_test("provider-a", "model-a")["admitted"] is True
        first.store.close()

        opened.config.unlink()
        restarted = opened.start()
        assert restarted.facade.model_admissions() == []
        assert restarted.facade.describe_readiness()["available"] is False
        restarted.close()
    finally:
        server.shutdown()
        server.server_close()

def test_smoke_reads_admissions_from_the_file_next_to_the_catalog(tmp_path):
    # harness smoke 在真实目录与准入文件存在时不再报「模型尚未通过模型测试准入」。
    # 上游是测试内启动的真实 HTTP 服务；上游只给固定回答，happy 场景会停在等待回答，
    # 这里核对的是 smoke 从准入文件恢复准入以后不再把定义当作未准入
    server, capture, base_url = serve(_model_reply())
    try:
        opened = _Opened(tmp_path, base_url=base_url)
        # 未准入时 smoke 明确报告尚未通过模型测试准入，且不向上游发请求
        opened.dotenv.write_text(f"KEY_A={KEY_A}\n", encoding="utf-8")
        blocked = run_smoke(opened.data_dir, provider_config=opened.config, dotenv_path=opened.dotenv,
                            scenarios=["happy"])
        assert blocked["available"] is False
        assert "尚未通过模型测试准入" in blocked["error"]
        assert capture.requests == []

        first = opened.start()
        assert first.facade.model_test("provider-a", "model-a")["admitted"] is True
        first.store.close()

        report = run_smoke(opened.data_dir, provider_config=opened.config, dotenv_path=opened.dotenv,
                           scenarios=["happy"])
        assert report["available"] is True, report
        assert "尚未通过模型测试准入" not in json.dumps(report, ensure_ascii=False)
        # 上游确实收到了请求：smoke 经准入文件恢复准入以后进入真实调用
        assert capture.requests
    finally:
        server.shutdown()
        server.server_close()
