# 调用目标按每次请求解析（#45）：解析在步骤驱动的每次逻辑调用之前发生，解析失败时运行停在这次请求之前进入待恢复，
# 用户修复配置或凭据并回答「继续执行」以后，下一次逻辑调用按当时的部门默认与凭据来源重新解析。
# 真实 Provider：本机 HTTP 服务实现 Responses 协议，凭据来自 .env 文件或进程内的凭据来源。

from __future__ import annotations

import asyncio
import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from harness.collaboration import has_new_work
from harness.engine import StepDriver, StepLimits
from harness.models import DEPARTMENTS, EventType
from harness.proposals import product_spec
from harness.providers import CredentialChain, CredentialMaterial, ProviderFacade
from harness.providers.errors import CatalogValidationError
from harness.event_store import Command
from harness.projection import saved_decisions
from harness.runtime import LoopSystem
from harness.tests.protocol_helpers import serve, sse
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

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

def _delivery_stream(*, response_id: str, model: str, basis_product_spec_hash: str | None) -> bytes:
    # 工程部门返回一次可接纳的交付：同一次运行要跨越两个部门。交付按依据版本声明（工单 #471）：
    # 依据取自工程请求里写明的当前 ProductSpec content_hash
    return _responses_reply([
        _call_item("engineering-write", "write_file", {"path": "src/echo.py", "content": "print('echo')\n"}),
        _call_item("engineering-check", "run_check", {"name": "smoke", "command": "python src/echo.py"}),
        _call_item("engineering-delivery", "submit_delivery",
                   {"summary": "implemented echo CLI", "check_names": ["smoke"],
                    "basis_product_spec_hash": basis_product_spec_hash}),
    ], response_id=response_id, model=model)

def _stream_reply(body: bytes) -> tuple[int, str, list[bytes]]:
    return 200, "text/event-stream", [body]

def _request_department(body: dict[str, Any]) -> str:
    # 从请求内容里取当前工作的部门：步骤驱动把 [current_work] 的 department 放进请求文本
    parts: list[str] = []
    for item in body.get("input", []):
        content = item.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for segment in content:
                if isinstance(segment, dict) and isinstance(segment.get("text"), str):
                    parts.append(segment["text"])

    match = re.search(r'"department":"(\w+)"', "\n".join(parts))
    return match.group(1) if match else ""

def _request_spec_hash(body: dict[str, Any]) -> str | None:
    # 从请求内容里取当前有效 ProductSpec 的 content_hash：交付按依据版本声明（工单 #471）
    parts: list[str] = []
    for item in body.get("input", []):
        content = item.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for segment in content:
                if isinstance(segment, dict) and isinstance(segment.get("text"), str):
                    parts.append(segment["text"])
    match = re.search(r"\[current_product_spec\]\n(\{.*?\})\n", "\n".join(parts))
    return json.loads(match.group(1))["content_hash"] if match else None

def _department_aware_reply(body: dict[str, Any]) -> tuple[int, str, list[bytes]]:
    # 产品部门返回产品要求，工程部门返回一次可接纳的交付：同一次运行要跨越两个部门
    if _request_department(body) == "engineering":
        return _stream_reply(_delivery_stream(response_id="resp-plan", model="m-local-target",
                                              basis_product_spec_hash=_request_spec_hash(body)))
    return _stream_reply(_product_spec_stream(response_id="resp-1", model="m-local-target"))

def _transient_error() -> tuple[int, str, list[bytes]]:
    return 500, "application/json", [b'{"error": {"code": "server_error", "message": "transient"}}']

def _document(base_url: str) -> dict[str, Any]:
    # 一份目录：本机服务上一个 Responses 模型，三个部门都绑定它
    return {
        "providers": [{"id": "local", "name": "Local", "base_url": base_url,
                       "credential_ref": "SCENARIO_KEY", "timeout_sec": 20}],
        "models": [{"id": "m-local", "provider_id": "local", "model": "m-local-target",
                    "protocol": "responses",
                    "context_window": 32000, "max_output_tokens": 2048}],
        "bindings": {department: {"provider_id": "local", "model_id": "m-local"} for department in DEPARTMENTS},
    }

class _RecordingFacade(ProviderFacade):
    # 记录每个部门解析调用目标的结果：解析不出来（模型引用无法使用）就是被挡住的那一步。
    # 夹具据此把「两个会话各自走到被挡住的那一步」变成可核对的事实，用例不再假定它（工单 #893）。
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.blocked_departments: list[str] = []

    def resolve_department_default(self, department: str, requested_tier: str | None = None, *,
                                   project: Any = None) -> Any:
        resolution = super().resolve_department_default(department, requested_tier, project=project)
        if not resolution.available:
            self.blocked_departments.append(department)
        return resolution

def _file_system(tmp_path, base_url: str, *, dotenv_text: str) -> tuple[LoopSystem, ProviderFacade, Any]:
    # 目录与 .env 都从文件读取：修复凭据就是把这些文件写成可解析的内容，再让运行中的门面读到
    config = tmp_path / "providers.json"
    dotenv = tmp_path / ".env"
    config.write_text(json.dumps(_document(base_url), ensure_ascii=False), encoding="utf-8")
    dotenv.write_text(dotenv_text, encoding="utf-8")
    facade = _RecordingFacade(credentials=CredentialChain(use_env=False))
    facade.configure_paths(config, dotenv)
    facade.reload()
    facade.record_admission("local", "m-local", admitted_model="m-local-target")
    return LoopSystem(tmp_path / "data", facade=facade), facade, dotenv

def _answer_open_decision(system: LoopSystem, option: str) -> None:
    # 只经公开接口回答待恢复：按保存的投影列出未回答的决定请求，经流程编排的回答入口回答
    # 同时运行的会话各自被挡住时各有一条（工单 #557），逐条回答
    _position, decisions = saved_decisions(system.store, statuses=("open",))
    assert decisions, "没有待恢复的决定请求"
    for decision in decisions:
        assert (decision.request["kind"], decision.request["blocks"]) == ("model_unavailable", "run")
        command = Command(str(uuid.uuid4()), "decision.answer", f"sha256:{option}:1", "user:local")
        system.orchestrator.answer_decision(decision.decision_id, option, None,
                                             base_version=decision.version, command=command)


def _answer_one(system: LoopSystem, decision, option: str) -> str | None:
    # 只回答一条待恢复的决定请求：交回需要继续执行的 run（没有时为空）
    command = Command(str(uuid.uuid4()), "decision.answer", f"sha256:{option}:1", "user:local")
    return system.orchestrator.answer_decision(decision.decision_id, option, None,
                                                base_version=decision.version, command=command)


def _yield_before_the_safe_node(monkeypatch, department: str) -> None:
    # 让一个部门的驱动器在安全节点以前让出一次（恢复上一次激活没有处置完的工具调用）：
    # 两个会话的驱动器任务在事件循环里前后相邻，余量只有一轮；后一个会话让出一次，
    # 先一个会话的决定请求就已经写下，后一个会话在自己的安全节点上看见它。
    # 用例因此确定地走到「两个会话同时被挡住」的场景，不靠时序碰运气（工单 #933）
    original = StepDriver._continue_unexecuted_calls

    async def patched(self):
        if self._scope.department == department:
            await asyncio.sleep(0)
        return await original(self)

    monkeypatch.setattr(StepDriver, "_continue_unexecuted_calls", patched)

def test_missing_credential_blocks_until_the_dotenv_file_is_fixed(tmp_path):
    server, capture, base = serve(lambda _body: _stream_reply(
        _product_spec_stream(response_id="resp-1", model="m-local-target")))
    try:
        system, facade, dotenv = _file_system(tmp_path, base, dotenv_text="")
        run_id = system.create_run("build an echo CLI")

        blocked = system.run_until_stop(run_id)
        # 凭据起初缺失：请求没有发出，运行停在这次请求之前等待修复，不因「凭据已不在本进程」结束
        assert (blocked.active_department, blocked.status) == ("product", "running")
        assert capture.requests == []
        _position, decisions = saved_decisions(system.store, statuses=("open",))
        assert [decision.request["kind"] for decision in decisions] == ["model_unavailable"]
        assert "SCENARIO_KEY" in decisions[0].request["description"]

        # 把 Key 写入 .env 文件并重新读取；不用内存覆盖，也不改动已经解析过的目标
        dotenv.write_text("SCENARIO_KEY=dotenv-secret-1\n", encoding="utf-8")
        facade.reload()

        _answer_open_decision(system, "continue")
        finished = system.activate_once(run_id)

        assert has_new_work(finished, "engineering"), finished.error
        assert [item["authorization"] for item in capture.headers] == ["Bearer dotenv-secret-1"]
        requests = [event for event in system.store.list_events(run_id)
                    if event.type == EventType.MODEL_REQUESTED]
        assert [(event.payload["provider_config_id"], event.payload["credential_version"],
                 event.payload["selection_source"]) for event in requests] == [
            ("local", "dotenv", "department_default")]
        # 请求事件记录的调用目标公开部分（界面经 department.workspace 与 run.attempt 读取，见 test_issue_92）
        [request] = requests
        assert (request.payload["provider_name"], request.payload["requested_model"],
                request.payload["protocol"], request.payload["context_window"]) == (
            "Local", "m-local-target", "responses", 32000)
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
    server_b, capture_b, base_b = serve(lambda body: _stream_reply(_delivery_stream(
        response_id="resp-plan", model="m-b-target", basis_product_spec_hash=_request_spec_hash(body))))
    try:
        facade = ProviderFacade(credentials=CredentialChain(overrides={
            "KEY_A": CredentialMaterial("key-a", version="a-v1"),
            "KEY_B": CredentialMaterial("key-b", version="b-v1"),
        }, use_env=False))
        def document(target_base: str, provider_id: str, model_id: str, ref: str, upstream: str):
            return {"providers": [{"id": provider_id, "name": provider_id,
                                   "base_url": target_base,
                                   "credential_ref": ref, "timeout_sec": 20}],
                    "models": [{"id": model_id, "provider_id": provider_id, "model": upstream,
                                "protocol": "responses",
                                "context_window": 32000, "max_output_tokens": 2048}]}
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
            result = future.result(timeout=WAIT_FOR_HOST_WORK_SEC)

        assert has_new_work(result, "engineering"), result.error
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


def test_swapping_the_department_model_limits_the_saved_tier_on_the_next_request(tmp_path):
    # 运行中把部门默认换成支持档位不同的模型：保存被接受，原请求档位保留；
    # 下一次请求按新模型的支持档位限制，请求事件同时记录请求档位与发送档位（#87）
    server, capture, base = serve(lambda _body: _stream_reply(
        _product_spec_stream(response_id="resp-1", model="m-local-target")))
    try:
        facade = ProviderFacade(credentials=CredentialChain(
            overrides={"KEY": CredentialMaterial("key", version="v1")}, use_env=False))
        facade.store_document({
            "providers": [{"id": "local", "name": "Local", "base_url": base,
                           "credential_ref": "KEY", "timeout_sec": 20}],
            "models": [
                {"id": "m-high", "provider_id": "local", "model": "m-local-target",
                 "protocol": "responses",
                 "context_window": 32000, "max_output_tokens": 2048,
                 "reasoning_levels": ["medium", "high"], "default_reasoning_level": "medium",
                 "reasoning_mode": "effort"},
                {"id": "m-low", "provider_id": "local", "model": "m-local-target",
                 "protocol": "responses",
                 "context_window": 32000, "max_output_tokens": 2048,
                 "reasoning_levels": ["low"], "default_reasoning_level": "low",
                 "reasoning_mode": "effort"},
            ],
            "bindings": {department: {"provider_id": "local", "model_id": "m-high",
                                      "requested_tier": "high"}
                         for department in DEPARTMENTS},
        })
        facade.record_admission("local", "m-high", admitted_model="m-local-target")
        facade.record_admission("local", "m-low", admitted_model="m-local-target")

        system = LoopSystem(tmp_path / "data", facade=facade, step_limits=MILLISECOND_RETRIES)
        run_id = system.create_run("build an echo CLI")
        system.activate_once(run_id)
        assert capture.requests[0]["reasoning"] == {"effort": "high"}

        # 换成只支持 low 的模型：保存被接受，请求档位 high 保留
        document = facade.to_document()
        for binding in document["bindings"].values():
            binding["model_id"] = "m-low"
        facade.store_document(document)
        assert facade.get_bindings()["product"]["requested_tier"] == "high"

        system.activate_once(run_id)
        assert capture.requests[1]["reasoning"] == {"effort": "low"}
        request = [event for event in system.store.list_events(run_id)
                   if event.type == EventType.MODEL_REQUESTED][-1]
        assert request.payload["requested_tier"] == "high"
        assert request.payload["sent_tier"] == "low"
    finally:
        server.shutdown()
        server.server_close()

def test_revoked_admission_blocks_the_next_request_until_retested(tmp_path, monkeypatch):
    # 部门默认所选模型的准入作废（改了连接的地址）以后，该部门的下一次模型请求进入待恢复，
    # 重新测试通过并回答以后继续执行；引用保留，已完成的工作与已用限额保留（工单 #86）
    # 同一次运行跨越产品与工程两个部门：产品请求返回产品要求，工程请求返回交付文件
    # 同时运行的会话（工单 #557）：工程与质检各自走到被挡住的那一步，各发一条待恢复的决定请求
    # （模型管理设计说明第 5.5 节：同一事项里同时有几个会话被挡住时，各发一条，各写明自己的部门、模型与问题，
    # 事项等这几条都回答以后再继续）
    # 质检的驱动器在安全节点以前让出一次：确定地走到「两个会话同时被挡住」的场景，不靠时序碰运气
    _yield_before_the_safe_node(monkeypatch, "quality")
    server, capture, base = serve(_department_aware_reply)
    try:
        system, facade, _dotenv = _file_system(tmp_path, base, dotenv_text="SCENARIO_KEY=secret-1\n")
        run_id = system.create_run("build an echo CLI")

        # 第一次请求按已准入的定义发出，运行推进到工程部门
        first = system.activate_once(run_id)
        assert has_new_work(first, "engineering"), first.error
        assert [item["model"] for item in capture.requests] == ["m-local-target"]
        positions_before = len(system.store.list_events(run_id))

        # 改连接的地址作废准入：引用保留，解析调用目标时判为不可用
        document = json.loads((tmp_path / "providers.json").read_text(encoding="utf-8"))
        document["providers"][0]["base_url"] = "http://127.0.0.1:9/v1"
        facade.store_document(document)
        assert facade.get_bindings()["engineering"]["model_id"] == "m-local"
        record = next(item for item in facade.model_admissions() if item["model_id"] == "m-local")
        assert record["stale"] is True

        # 下一次请求不发送，运行停在这次请求之前，发出待恢复的决定请求
        blocked = system.run_until_stop(run_id)
        assert blocked.status == "running"
        # 两个会话各自走到被挡住的那一步（工单 #557）：解析调用目标失败就是这一步，
        # 它紧跟在这个会话的第一个安全节点以后发生。
        # 别的会话写下请求以后，这个会话照常停下，但停下的不是取消（工单 #856）：
        # 它自己也被挡住时（这次的模型请求发不出去），它写下自己的那一条（设计第 5.5 节）。
        assert set(facade.blocked_departments) == {"engineering", "quality"}, facade.blocked_departments
        # 同时运行的会话（工单 #557）：工程与质检各发一条待恢复的决定请求，每条写明自己的部门
        # （模型管理设计说明第 5.5 节：这次模型请求不发送，事项停在这次请求之前）
        _position, decisions = saved_decisions(system.store, statuses=("open",))
        assert [decision.request["kind"] for decision in decisions] == ["model_unavailable", "model_unavailable"]
        assert {decision.request["department"] for decision in decisions} == {"engineering", "quality"}
        assert all("m-local" in decision.request["description"] for decision in decisions)
        # 事项投影的当前部门是最后激活的那一个会话的部门（同时运行以后不是一个部门）
        assert blocked.active_department in {"engineering", "quality"}
        assert [item["model"] for item in capture.requests] == ["m-local-target"]
        # 已完成的工作与已用限额保留：停止发生在这次请求之前，事件只增不改
        assert len(system.store.list_events(run_id)) > positions_before

        # 回答其中一条以后，另一条仍然待回答，事项仍然不继续（设计第 5.5 节：等这几条都回答以后再继续）
        assert _answer_one(system, decisions[0], "continue") is None
        _position, pending = saved_decisions(system.store, statuses=("open",))
        assert [decision.decision_id for decision in pending] == [decisions[1].decision_id]
        # 事项没有继续：没有新的模型请求发出去
        assert [item["model"] for item in capture.requests] == ["m-local-target"]

        # 把地址改回去并重新测试：准入重新有效，两条都回答以后从这次请求接着进行
        document["providers"][0]["base_url"] = base
        facade.store_document(document)
        facade.record_admission("local", "m-local", admitted_model="m-local-target")
        assert facade.model_admissions()[0]["stale"] is False

        assert _answer_one(system, decisions[1], "continue") is not None
        finished = system.activate_once(run_id)
        # 从被挡住的那次请求接着进行：工程部门的交付请求重新发出并被接受
        assert has_new_work(finished, "quality"), finished.error
        assert [item["model"] for item in capture.requests] == ["m-local-target", "m-local-target"]
        deliveries = [event for event in system.store.list_events(run_id) if event.type == EventType.DELIVERY_ACCEPTED]
        assert len(deliveries) == 1
        assert deliveries[0].department == "engineering" and deliveries[0].actor == "department:engineering"
        assert saved_decisions(system.store, statuses=("open",))[1] == []
    finally:
        server.shutdown()
        server.server_close()
