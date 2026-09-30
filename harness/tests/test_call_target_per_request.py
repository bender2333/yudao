# 调用目标按每次请求解析（#45）：解析在步骤驱动的每次逻辑调用之前发生，解析失败时运行停在这次请求之前进入待恢复，
# 用户修复配置或凭据并回答「继续执行」以后，下一次逻辑调用按当时的部门默认与凭据来源重新解析。
# 真实 Provider：本机 HTTP 服务实现 Responses 协议，凭据来自 .env 文件或进程内的凭据来源。

from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from harness.engine import StepLimits
from harness.models import DEPARTMENTS, EventType
from harness.observability import department_view
from harness.proposals import engineering_plan, product_spec
from harness.providers import CredentialChain, CredentialMaterial, ProviderFacade
from harness.providers.errors import CatalogValidationError
from harness.runtime import LoopSystem
from harness.tests.protocol_helpers import serve, sse
from harness.event_store import Command
from harness.projection import saved_decisions

MILLISECOND_RETRIES = StepLimits(retry_initial_delay_sec=0.001, retry_max_delay_sec=0.001)


def _event(kind: str, **payload: Any) -> str:
    return f"event: {kind}\ndata: {json.dumps({'type': kind, **payload}, ensure_ascii=False)}\n\n"


def _call_item(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"item-{call_id}",
        "type": "function_call",
        "name": name,
        "call_id": call_id,
        "arguments": json.dumps(arguments, ensure_ascii=False, separators=(",", ":")),
        "status": "completed",
    }


def _responses_reply(items: list[dict[str, Any]], *, response_id: str, model: str) -> bytes:
    response = {
        "id": response_id, "object": "response", "created_at": 1, "status": "completed", "model": model,
        "output": items,
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2,
                  "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}},
        "error": None, "incomplete_details": None,
    }
    frames = [
        _event("response.created", sequence_number=0,
               response={**response, "status": "in_progress", "output": [], "usage": None}),
    ]
    for index, item in enumerate(items):
        frames.append(_event("response.output_item.done", output_index=index, sequence_number=index + 1, item=item))
    frames.append(_event("response.completed", sequence_number=len(frames), response=response))
    return sse(*frames)


def _product_spec_stream(*, response_id: str, model: str) -> bytes:
    payload = product_spec()
    payload.pop("kind")
    return _responses_reply([_call_item("product-spec", "submit_product_spec", payload)],
                            response_id=response_id, model=model)


def _plan_stream(*, response_id: str, model: str) -> bytes:
    payload = engineering_plan()
    payload.pop("kind")
    return _responses_reply([_call_item("engineering-plan", "submit_plan", payload)],
                            response_id=response_id, model=model)


def _stream_reply(body: bytes) -> tuple[int, str, list[bytes]]:
    return 200, "text/event-stream", [body]


def _transient_error() -> tuple[int, str, list[bytes]]:
    return 500, "application/json", [b'{"error": {"code": "server_error", "message": "transient"}}']


def _document(base_url: str) -> dict[str, Any]:
    # 一份目录：本机服务上一个 Responses 模型，三个部门都绑定它
    return {
        "providers": [{"id": "local", "name": "Local", "base_url": base_url,
                       "credential_ref": "SCENARIO_KEY", "timeout_sec": 20}],
        "models": [{"id": "m-local", "provider_id": "local", "model": "m-local-target",
                    "protocol": "responses", "context_window": 32000, "max_output_tokens": 2048}],
        "bindings": {department: {"provider_id": "local", "model_id": "m-local"} for department in DEPARTMENTS},
    }


def _file_system(tmp_path, base_url: str, *, dotenv_text: str) -> tuple[LoopSystem, ProviderFacade, Any]:
    # 目录与 .env 都从文件读取：修复凭据就是把这些文件写成可解析的内容，再让运行中的门面读到
    config = tmp_path / "providers.json"
    dotenv = tmp_path / ".env"
    config.write_text(json.dumps(_document(base_url), ensure_ascii=False), encoding="utf-8")
    dotenv.write_text(dotenv_text, encoding="utf-8")
    facade = ProviderFacade(credentials=CredentialChain(use_env=False))
    facade.configure_paths(config, dotenv)
    facade.reload()
    facade.record_admission("local", "m-local", admitted_model="m-local-target")
    return LoopSystem(tmp_path / "data", facade=facade), facade, dotenv


def _answer_open_decision(system: LoopSystem, option: str) -> None:
    # 只经公开接口回答待恢复：按保存的投影列出未回答的决定请求，经流程编排的回答入口回答
    _position, decisions = saved_decisions(system.store, statuses=("open",))
    assert len(decisions) == 1, [decision.decision_id for decision in decisions]
    [decision] = decisions
    assert (decision.request["kind"], decision.request["blocks"]) == ("model_unavailable", "run")
    command = Command(str(uuid.uuid4()), "decision.answer", f"sha256:{option}:1", "user:local")
    system.orchestrator.answer_decision(decision.decision_id, option, None, base_version=1, command=command)


def test_missing_credential_blocks_until_the_dotenv_file_is_fixed(tmp_path):
    server, capture, base = serve(lambda _body: _stream_reply(
        _product_spec_stream(response_id="resp-1", model="m-local-target")))
    try:
        system, facade, dotenv = _file_system(tmp_path, base, dotenv_text="")
        run_id = system.create_run("build an echo CLI")

        blocked = system.run_until_stop(run_id)
        # 凭据起初缺失：请求没有发出，运行停在这次请求之前等待修复，不因「凭据已不在本进程」结束
        assert (blocked.phase, blocked.outcome) == ("PRODUCT_SPEC", "running")
        assert capture.requests == []
        _position, decisions = saved_decisions(system.store, statuses=("open",))
        assert [decision.request["kind"] for decision in decisions] == ["model_unavailable"]
        assert "SCENARIO_KEY" in decisions[0].request["description"]

        # 把 Key 写入 .env 文件并重新读取；不用内存覆盖，也不改动已经解析过的目标
        dotenv.write_text("SCENARIO_KEY=dotenv-secret-1\n", encoding="utf-8")
        facade.reload()

        _answer_open_decision(system, "continue")
        finished = system.activate_once(run_id)

        assert finished.phase == "ENGINEERING", finished.error
        assert [item["authorization"] for item in capture.headers] == ["Bearer dotenv-secret-1"]
        requests = [event for event in system.store.list_events(run_id)
                    if event.type == EventType.MODEL_REQUESTED]
        assert [(event.payload["provider_config_id"], event.payload["credential_version"],
                 event.payload["selection_source"]) for event in requests] == [
            ("local", "dotenv", "department_default")]
        # 界面显示的调用目标与请求事件记录的一致
        view = department_view(system.store, system.artifacts, run_id, "product")["provider"]
        assert (view["provider"], view["model"], view["protocol"], view["context_window"]) == (
            "Local", "m-local-target", "responses", 32000)
        assert view["selection_source"] == "department_default"
        public = json.dumps([event.__dict__ for event in system.store.list_events(run_id)],
                            ensure_ascii=False, default=str)
        assert "dotenv-secret-1" not in public
    finally:
        server.shutdown()
        server.server_close()


def test_a_running_request_and_its_retry_keep_the_resolved_target(tmp_path):
    # 请求进行中修改部门默认：这次逻辑调用（含重试）仍发往解析当时的目标，下一次逻辑调用按新默认解析
    held = threading.Event()
    release = threading.Event()
    first = {"attempts": 0}

    def provider_a(_body: dict[str, Any]) -> tuple[int, str, list[bytes]]:
        first["attempts"] += 1
        if first["attempts"] == 1:
            held.set()
            release.wait(30)
            return _transient_error()
        return _stream_reply(_product_spec_stream(response_id="resp-retry", model="m-a-target"))

    server_a, capture_a, base_a = serve(lambda body: provider_a(body))
    server_b, capture_b, base_b = serve(lambda _body: _stream_reply(_plan_stream(response_id="resp-plan",
                                                                                model="m-b-target")))
    try:
        facade = ProviderFacade(credentials=CredentialChain(overrides={
            "KEY_A": CredentialMaterial("key-a", version="a-v1"),
            "KEY_B": CredentialMaterial("key-b", version="b-v1"),
        }, use_env=False))
        def document(target_base: str, provider_id: str, model_id: str, ref: str, upstream: str):
            return {"providers": [{"id": provider_id, "name": provider_id, "base_url": target_base,
                                   "credential_ref": ref, "timeout_sec": 20}],
                    "models": [{"id": model_id, "provider_id": provider_id, "model": upstream,
                                "protocol": "responses", "context_window": 32000, "max_output_tokens": 2048}]}
        document_a = document(base_a, "provider-a", "m-a", "KEY_A", "m-a-target")
        document_b = document(base_b, "provider-b", "m-b", "KEY_B", "m-b-target")
        facade.store_document({
            "providers": document_a["providers"] + document_b["providers"],
            "models": document_a["models"] + document_b["models"],
            "bindings": {department: {"provider_id": "provider-a", "model_id": "m-a"}
                         for department in DEPARTMENTS},
        })
        for provider_id, model_id, upstream in (("provider-a", "m-a", "m-a-target"),
                                                ("provider-b", "m-b", "m-b-target")):
            facade.record_admission(provider_id, model_id, admitted_model=upstream)

        system = LoopSystem(tmp_path / "data", facade=facade, step_limits=MILLISECOND_RETRIES)
        run_id = system.create_run("build an echo CLI")

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(system.activate_once, run_id)
            assert held.wait(30)
            # 请求进行中把三个部门的默认改成另一个连接
            try:
                facade.save_bindings({department: {"provider_id": "provider-b", "model_id": "m-b"}
                                      for department in DEPARTMENTS})
            except CatalogValidationError as exc:  # 目录校验失败时测试立即失败，不掩盖原因
                raise AssertionError(f"binding update rejected: {exc}") from exc
            release.set()
            result = future.result(timeout=30)

        assert result.phase == "ENGINEERING", result.error
        # 这一次逻辑调用的重试仍发往原目标
        assert [item["model"] for item in capture_a.requests] == ["m-a-target", "m-a-target"]
        assert [item["authorization"] for item in capture_a.headers] == ["Bearer key-a", "Bearer key-a"]
        # 下一次逻辑调用（engineering）按新的部门默认解析
        system.activate_once(run_id)
        assert [item["model"] for item in capture_b.requests] == ["m-b-target"]
        attempts = [(event.department, event.payload["provider_config_id"])
                    for event in system.store.list_events(run_id)
                    if event.type == EventType.MODEL_REQUESTED]
        assert attempts == [("product", "provider-a"), ("product", "provider-a"), ("engineering", "provider-b")]
        bindings = system.project(run_id).provider_bindings
        assert bindings["product"]["provider_config_id"] == "provider-a"
        assert bindings["engineering"]["provider_config_id"] == "provider-b"
    finally:
        server_a.shutdown()
        server_a.server_close()
        server_b.shutdown()
        server_b.server_close()
