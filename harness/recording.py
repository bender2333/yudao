# 记录接口：一次激活内每一步的记录都经过这里写成工件与事件——部门工作消息、请求（装配结果与开始）、
# 序列化请求、流式进度、模型输出、用量、调用尝试的完成与失败、重试安排、主机提示、压缩检查点、
# 工具开始、完成与跳过。只记录，不判断：是否仍然可以记录由调用方决定。
# 带 transaction 参数的方法在调用方的事务中追加：调用方在同一事务中读取运行状态、判断以后调用；
# 其余方法自己在写入口开一个事务追加。一次调用的记录在同一个事务中追加，记录的阶段取追加时的运行状态。

from __future__ import annotations

import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from .adapters.base import ModelRequest, ProviderError
from .artifacts import ArtifactStore
from .assembly import CompactionResult, StepRequest
from .definitions import DEFINITIONS
from .event_store import run_stream
# 激活的范围（身份、版本与工作依据）是执行契约的输入，定义在契约模块里；这里照旧导出同一个名字
from .execution_contract import ActivationScope
from .write_path import NewEvent, Transaction, WritePath
from .models import Event, EventType, Usage, canonical_hash, json_dumps, utc_now
from .providers.call import ModelResponse, ModelStreamEvent
from .redact import redact_tool_args

# 一条待追加的记录：阶段在追加的事务中填入。返回 None 表示按事务里的运行状态这一刻没有要记的事实
Draft = Callable[[Transaction], NewEvent | None]

_SENSITIVE_OBSERVATION_KEYS = frozenset({
    "authorization", "api_key", "apikey", "access_token", "refresh_token",
    "client_secret", "password", "cookie", "set_cookie", "credential",
    "credentials", "headers", "proxy_authorization",
})

# 改了工作区的工具（工单 #858）：结果成功时当前交付失效，由成果驱动记一条成果失效事件
_WRITE_TOOLS = frozenset({"write_file", "delete_file", "move_file"})

_COLLECTION_SCOPE = {
    "request": "SDK request JSON object captured from the prepared HTTP request; authentication headers and raw HTTP bytes are excluded.",
    "response": "Complete SDK response object exposed by the provider SDK when a terminal response was received, with credential and header fields redacted.",
    "events": "SDK decoded stream event JSON objects captured as JSON Lines with credential and header fields redacted; raw HTTP/SSE bytes are not available.",
    "credentials": "excluded",
}


@dataclass
class _Observation:
    # 一条要记录的观察：模型调用交回的流式输出，或者工具执行与跳过的结果。
    # 解码后的流事件带着协议实现读出的流式进度阶段与提供方回答身份
    id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    usage: Usage | None = None
    provider: str | None = None
    model: str | None = None
    sequence: int | None = None
    stage: str = "event"
    response_id: str | None = None

    @classmethod
    def from_stream(cls, event: ModelStreamEvent) -> _Observation:
        usage = None if event.usage is None else Usage(**event.usage.model_dump())
        return cls(event.id, event.kind, dict(event.payload), event.text, usage, event.provider,
                   event.model, event.sequence, event.stage, event.response_id)


@dataclass
class _AttemptCapture:
    # 一次调用尝试采集到的解码流事件、完整响应与用量；流事件超过 1 MiB 时转存到临时文件
    stream: Any | None = None
    stream_event_count: int = 0
    stream_bytes: int = 0
    stream_ref: dict[str, Any] | None = None
    response_ref: dict[str, Any] | None = None
    provider_response_id: str | None = None
    actual_provider: str | None = None
    actual_model: str | None = None
    usage: Usage | None = None
    usage_ref: dict[str, Any] | None = None
    progress_stage: str | None = None
    first_observed_at: str | None = None
    first_output_at: str | None = None

    def add_stream_event(self, sequence: int | None, payload: dict[str, Any], observed_at: str) -> None:
        if self.stream is None:
            self.stream = tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
        record = {"sequence": sequence if sequence is not None else self.stream_event_count,
                  "observed_at": observed_at, "event": payload}
        raw = (json_dumps(record) + "\n").encode("utf-8")
        self.stream.write(raw)
        self.stream_event_count += 1
        self.stream_bytes += len(raw)

    def stream_chunks(self, chunk_size: int = 64 * 1024):
        if self.stream is None:
            return
        self.stream.seek(0)
        while True:
            chunk = self.stream.read(chunk_size)
            if not chunk:
                return
            yield chunk

    def close(self) -> None:
        if self.stream is not None:
            self.stream.close()


def _stream_progress_summary(payload: dict[str, Any]) -> str:
    event_type = str(payload.get("type") or "provider_event")
    if event_type == "response.output_item.done":
        item = payload.get("item")
        if isinstance(item, dict):
            return f"{event_type}: {item.get('type') or 'output_item'}"
    response = payload.get("response")
    if isinstance(response, dict) and response.get("status"):
        return f"{event_type}: {response['status']}"
    return event_type


def _redact(value: Any, *, key: str | None = None) -> Any:
    normalized_key = key.casefold().replace("-", "_") if isinstance(key, str) else ""
    if normalized_key in _SENSITIVE_OBSERVATION_KEYS or normalized_key.endswith("_api_key"):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(child_key): _redact(child_value, key=str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_redact(item, key=key) for item in value]
    return value


def _usage_summary(usage: Usage | None) -> dict[str, Any] | None:
    if usage is None or not (usage.reported or usage.total_tokens or usage.input_tokens
                             or usage.output_tokens or usage.cache_read_tokens
                             or usage.cache_write_tokens or usage.cost):
        return None
    return {
        "input_tokens": usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
        "total_tokens": usage.total_tokens,
        "cost": usage.cost if usage.cost_reported else None,
        "currency": None,
        "cost_source": None,
        "latency_ms": usage.latency_ms if usage.latency_ms else None,
        "reported": bool(usage.reported),
    }


def _duration_ms(request: ModelRequest) -> int | None:
    started = request.attempt_started_monotonic
    finished = request.attempt_finished_monotonic or time.monotonic()
    return None if started is None else max(0, int((finished - started) * 1000))


class StepRecorder:
    # 一次激活的记录接口；也持有记录需要的累计状态：用量计费、每次调用尝试的采集、观察的去重与部门的发言
    def __init__(self, writes: WritePath, artifacts: ArtifactStore, scope: ActivationScope,
                 *, max_attempts: int) -> None:
        self._writes = writes
        self._artifacts = artifacts
        self.scope = scope
        self._max_attempts = max_attempts
        self._tokens_charged = 0
        self._cost_charged = 0.0
        self._usage = Usage(reported=False)
        self._has_usage = False
        self._previous_usage = Usage(reported=True, cost_reported=True)
        self._step_usage: Usage | None = None
        self._raw_usage_ref: dict[str, Any] | None = None
        self._provider: str | None = None
        self._model: str | None = None
        self._seen: set[tuple[str, str]] = set()
        self._tool_ids: set[str] = set()
        self._messages: list[str] = []
        self._message_steps: list[tuple[str, int]] = []
        self._captures: dict[str, _AttemptCapture] = {}
        self._guidance_applied = False

    @property
    def transcript(self) -> str:
        # 本次激活成功步骤中模型的发言，提交提案时写成工件
        return "\n".join(self._messages)

    def close(self) -> None:
        for capture in self._captures.values():
            capture.close()

    def _mark_guidance_applied(self) -> None:
        self._guidance_applied = True

    def department_input(self, transaction: Transaction, step_id: int, item: dict[str, Any]) -> None:
        scope = self.scope
        ref = self._artifacts.put(scope.run_id, "department_input", json_dumps(item), media_type="application/json")
        self._record_in(transaction, self._draft(
            EventType.DEPARTMENT_INPUT, artifact_hashes=[ref.content_hash],
            payload={"activation_id": scope.activation_id, "step_id": step_id, "input_ref": asdict(ref),
                     **scope.versions(), **scope.work_basis()}))

    def request_assembled(self, transaction: Transaction, request: ModelRequest, step: StepRequest,
                          snapshot_hash: str) -> None:
        # 一步装配好的请求：发给模型的内容与各段材料写成工件，上下文清单写成 context_assembled；
        # 这一步观察到的提供方、模型与用量从这里重新开始
        scope = self.scope
        self._provider = None
        self._model = None
        self._previous_usage = self._usage if self._has_usage else Usage(reported=True, cost_reported=True)
        self._step_usage = None
        self._raw_usage_ref = None
        assembled = step.context
        ref = self._artifacts.put(scope.run_id, "model_request", json_dumps(step.payload), media_type="application/json")
        parts_ref = self._artifacts.put(scope.run_id, "context_parts", json_dumps(step.parts),
                                        media_type="application/json")
        payload = asdict(assembled.manifest)
        payload.update(run_id=scope.run_id, request_ref=asdict(ref), admitted=step.admitted,
                       tokens_charged=0, step_id=request.step_id, attempt=request.attempt,
                       root_step_id=request.root_step_id, retry_of_step_id=request.retry_of_step_id,
                       **self._call_target(request),
                       effective_context_window=step.limits.context_window,
                       input_token_estimate=step.input_token_estimate,
                       output_reserve_tokens=step.output_reserve_tokens,
                       parts_ref=asdict(parts_ref),
                       snapshot_hash=snapshot_hash)
        payload.update(attempt_id=request.attempt_id, logical_call_id=request.logical_call_id)
        [event] = self._record_in(transaction, self._draft(
            EventType.CONTEXT_ASSEMBLED, provider=self._event_provider(request), context_digest=assembled.manifest.digest,
            artifact_hashes=[ref.content_hash, parts_ref.content_hash], payload=payload))
        request.context_event_id = event.event_id

    def request_started(self, transaction: Transaction, request: ModelRequest) -> None:
        # 请求开始：激活第一次带着待处理指导发出请求时记录指导已经采用，然后记录这次调用尝试开始。
        # 「已经记录」在事务提交以后才标记，事务重新判断时照样记录
        scope = self.scope
        drafts = []
        guidance_ids = request.context.manifest.guidance_ids
        if guidance_ids and not self._guidance_applied:
            transaction.on_commit(self._mark_guidance_applied)
            drafts.append(self._draft(
                EventType.DEPARTMENT_GUIDANCE_APPLIED,
                payload={
                    "guidance_ids": list(guidance_ids),
                    "activation_id": scope.activation_id,
                    "context_event_id": request.context_event_id,
                    "input_version": request.input_version,
                }))
        request.attempt_started_at = request.attempt_started_at or utc_now()
        drafts.append(self._draft(
            EventType.MODEL_REQUESTED, provider=self._event_provider(request),
            context_digest=request.context.manifest.digest,
            payload={"activation_id": scope.activation_id, "step_id": request.step_id,
                     **scope.versions(),
                     "attempt": request.attempt,
                     "max_attempts": self._max_attempts,
                     "root_step_id": request.root_step_id,
                     "retry_of_step_id": request.retry_of_step_id,
                     "attempt_id": request.attempt_id,
                     "logical_call_id": request.logical_call_id,
                     "context_event_id": request.context_event_id,
                     "started_at": request.attempt_started_at,
                     "attempted": True, "purpose": request.purpose,
                     "effective_contract_hash": request.effective_contract_hash,
                     **self._call_target(request),
                     "effective_context_window": request.context.manifest.budget,
                     "max_output_tokens": request.max_output_tokens,
                     "tool_choice": request.tool_choice,
                     "definitions_version": DEFINITIONS.version,
                     "parameters_version": transaction.projection.parameters_version}))
        self._record_in(transaction, *drafts)

    def stream(self, request: ModelRequest, event: ModelStreamEvent) -> None:
        # 模型调用交回的一条流式输出：序列化请求、解码后的流事件、完整响应、用量或一条输出
        self._record(*self._observe(request, _Observation.from_stream(event)))

    def _record_reasoning(self, request: ModelRequest, reasoning: dict[str, Any], *,
                          provider: str | None, model: str | None) -> list[Draft]:
        # response() 交回的推理内容：逐条写成模型输出事件，跳过已经在流式观察中写过的条目
        return self._reasoning_drafts(request, list(reasoning.get("items") or []),
                                      provider=provider, model=model)

    def _reasoning_drafts(self, request: ModelRequest, items: list[Any], *,
                          provider: str | None, model: str | None) -> list[Draft]:
        # 每条推理内容写成一条模型输出事件，保存为工件。回放时按事件里的调用目标判断是否原样发送：
        # 每条记录的调用目标与它产生时的一致（同一个步骤驱动在写观察时填的公开部分）
        scope = self.scope
        drafts: list[Draft] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            identity = str(item.get("id") or "")
            key = (f"{request.attempt_id or request.step_id}:reasoning", identity)
            if identity and key in self._seen:
                continue
            if identity:
                self._seen.add(key)
            payload = _redact(item)
            ref = self._artifacts.put(scope.run_id, "model_reasoning", json_dumps(payload),
                                      media_type="application/json")
            item_payload: dict[str, Any] = {
                "reasoning_ref": asdict(ref),
                "attempt_id": request.attempt_id,
                "logical_call_id": request.logical_call_id,
                "context_event_id": request.context_event_id,
                "activation_id": request.activation_id,
                "step_id": request.step_id,
                "purpose": request.purpose,
            }
            item_payload.update(scope.work_basis())
            item_payload.update(scope.versions())
            item_payload.update(self._call_target(request))
            drafts.append(self._draft(EventType.MODEL_REASONING, provider=provider, model=model,
                                      payload=item_payload, artifact_hashes=[ref.content_hash]))
        return drafts

    def response(self, request: ModelRequest, result: ModelResponse) -> None:
        # 调用尝试的结果：先写推理内容，再写每个输出条目，最后按这一步报告的用量记账。
        # 推理内容在回答里先于它伴随的消息与工具调用出现，回放时也保持这个顺序（设计说明第 7.6 节）
        provider = result.provider or self.scope.provider
        model = result.model
        drafts: list[Draft] = []
        if result.reasoning:
            drafts.extend(self._record_reasoning(request, result.reasoning, provider=provider, model=model))
        for index, item in enumerate(result.output):
            content = item.get("content") or []
            text = "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict)) if isinstance(content, list) else str(content)
            drafts.extend(self._observe(request, _Observation(
                str(item.get("id") or f"output-{index}"), "message", item, text,
                provider=provider, model=model,
            )))
        usage = Usage(**result.usage.model_dump())
        if not (usage.reported or usage.total_tokens or usage.cost):
            usage = self._step_usage or Usage(reported=False)
        self._step_usage = usage
        drafts.extend(self._charge(
            request,
            self._previous_usage.plus(usage),
            provider=provider,
            model=model,
            force=bool(result.model) and self._model != result.model,
            reported=usage.reported,
        ))
        self._record(*drafts)

    def tool_called(self, request: ModelRequest, call: dict[str, Any],
                    after_snapshot: dict[str, Any] | None = None,
                    qa_tests_saved: dict[str, Any] | None = None) -> None:
        # 动作后的公开树快照与结果一起写入（工单 #17）：与动作前的快照、动作参数一起构成核实依据，
        # 放在 run 自己的对象区域，不建立提交、不改动分支索引
        call = self._redacted_call(call)
        if after_snapshot is not None:
            after_ref = self._artifacts.put(request.run_id, "snapshot/after", json_dumps(after_snapshot),
                                            media_type="application/json")
            call["after_snapshot_ref"] = asdict(after_ref)
        drafts = []
        if qa_tests_saved is not None:
            drafts.append(self._draft(
                EventType.QA_TESTS_SAVED,
                provider=self._event_provider(request),
                artifact_hashes=[qa_tests_saved["archive_ref"]["content_hash"]],
                payload=qa_tests_saved,
            ))
        drafts.extend(self._observe(request, _Observation(call["id"], "tool", call)))
        self._record(*drafts)

    def tool_skipped(self, request: ModelRequest, call: dict[str, Any]) -> None:
        self._record(*self._observe(request, _Observation(call["id"], "skipped_tool", self._redacted_call(call))))

    def attempt_finished(self, request: ModelRequest, response: ModelResponse) -> None:
        self._record(self._attempt_finished(request, response))

    def attempt_failed(self, request: ModelRequest, error: ProviderError, will_retry: bool) -> None:
        # 失败尝试的发言不进入提交的发言记录；它的输出与工具结果只作为审计证据保留
        self._record(self._attempt_failed(request, error, will_retry))

    def tool_call_required(self, request: ModelRequest, item: dict[str, Any], count: int, limit: int) -> None:
        # 模型回复没有调用工具：主机追加的 user 消息写成事件，进入部门历史
        self._record(self._tool_call_required(request, item, count, limit))

    def _attempt_finished(self, request: ModelRequest, response: ModelResponse) -> Draft:
        scope = self.scope
        finished_at = utc_now()
        duration_ms = _duration_ms(request)
        capture = self._finalize_capture(request)
        if capture.response_ref is None and isinstance(response.sdk_response, dict):
            safe_response = _redact(response.sdk_response)
            response_ref = self._artifacts.put(
                scope.run_id,
                "sdk_response",
                json_dumps(safe_response),
                media_type="application/json",
            )
            capture.response_ref = asdict(response_ref)
            capture.provider_response_id = safe_response.get("id") or response.response_id
        provider = response.provider or self._event_provider(request)
        model = response.model or self._model
        payload = {
            "attempt_id": request.attempt_id,
            "logical_call_id": request.logical_call_id,
            "context_event_id": request.context_event_id,
            "activation_id": request.activation_id,
            "step_id": request.step_id,
            "root_step_id": request.root_step_id,
            "retry_of_step_id": request.retry_of_step_id,
            "attempt": request.attempt,
            "purpose": request.purpose,
            "status": "completed",
            "started_at": request.attempt_started_at,
            "finished_at": finished_at,
            "duration_ms": duration_ms,
            "duration_source": "monotonic",
            "provider_response_id": response.response_id or capture.provider_response_id,
            "actual_provider": capture.actual_provider or (provider if response.response_id or response.model else None),
            "actual_model": capture.actual_model or (response.model or None),
            "response_ref": capture.response_ref,
            "stream_events_ref": capture.stream_ref,
            "stream_event_count": capture.stream_event_count,
            "stream_first_observed_at": capture.first_observed_at,
            "stream_first_output_at": capture.first_output_at,
            "stream_last_stage": capture.progress_stage,
            "collection_scope": dict(_COLLECTION_SCOPE),
            "usage": _usage_summary(capture.usage or self._step_usage),
            "raw_usage_ref": capture.usage_ref or self._raw_usage_ref,
            **scope.versions(),
            **self._call_target(request),
        }
        return self._draft(
            EventType.MODEL_ATTEMPT_FINISHED,
            provider=provider, model=model or None, context_digest=request.context.manifest.digest,
            artifact_hashes=[ref["content_hash"] for ref in (capture.response_ref, capture.stream_ref) if ref],
            payload=payload)

    def _attempt_failed(self, request: ModelRequest, error: ProviderError, will_retry: bool) -> Draft:
        scope = self.scope
        failed_key = (request.activation_id, request.step_id)
        kept = [(text, key) for text, key in zip(self._messages, self._message_steps) if key != failed_key]
        self._messages = [text for text, _key in kept]
        self._message_steps = [key for _text, key in kept]
        capture = self._finalize_capture(request)
        finished_at = utc_now()
        duration_ms = _duration_ms(request)
        status = "cancelled" if error.reason == "cancelled" else "failed"
        safe_error = _redact(str(error))
        safe_diagnostics = _redact(dict(error.diagnostics or {}))
        return self._draft(
            EventType.MODEL_ATTEMPT_FAILED,
            provider=self._provider or self._event_provider(request), model=self._model,
            context_digest=request.context.manifest.digest, error=safe_error,
            artifact_hashes=[ref["content_hash"] for ref in (capture.response_ref, capture.stream_ref) if ref],
            payload={
                "attempt_id": request.attempt_id,
                "logical_call_id": request.logical_call_id,
                "context_event_id": request.context_event_id,
                "activation_id": request.activation_id,
                "step_id": request.step_id,
                **scope.versions(),
                "attempt": request.attempt,
                "max_attempts": self._max_attempts,
                "root_step_id": request.root_step_id,
                "retry_of_step_id": request.retry_of_step_id,
                "purpose": request.purpose,
                "status": status,
                "started_at": request.attempt_started_at,
                "finished_at": finished_at,
                "duration_ms": duration_ms,
                "duration_source": "monotonic",
                "actual_provider": capture.actual_provider,
                "actual_model": capture.actual_model,
                "provider_response_id": capture.provider_response_id,
                "response_ref": capture.response_ref,
                "stream_events_ref": capture.stream_ref,
                "stream_event_count": capture.stream_event_count,
                "stream_first_observed_at": capture.first_observed_at,
                "stream_first_output_at": capture.first_output_at,
                "stream_last_stage": capture.progress_stage,
                "collection_scope": dict(_COLLECTION_SCOPE),
                "usage": _usage_summary(capture.usage or self._step_usage),
                "raw_usage_ref": capture.usage_ref or self._raw_usage_ref,
                "effective_contract_hash": request.effective_contract_hash,
                "reason": error.reason,
                "retryable": error.retryable,
                "will_retry": will_retry,
                "diagnostics": safe_diagnostics,
                **self._call_target(request),
            })

    def _tool_call_required(self, request: ModelRequest, item: dict[str, Any], count: int, limit: int) -> Draft:
        scope = self.scope
        ref = self._artifacts.put(scope.run_id, "tool_call_required", json_dumps(item), media_type="application/json")
        return self._draft(
            EventType.TOOL_CALL_REQUIRED, artifact_hashes=[ref.content_hash],
            payload={"activation_id": scope.activation_id, "step_id": request.step_id,
                     "attempt_id": request.attempt_id, "context_event_id": request.context_event_id,
                     "purpose": request.purpose, "count": count,
                     "limit": limit, "input_ref": asdict(ref),
                     **scope.versions(), **scope.work_basis()})

    def retry_scheduled(self, transaction: Transaction, request: ModelRequest, error: ProviderError, delay: float,
                        next_step_id: int) -> None:
        scope = self.scope
        self._record_in(transaction, self._draft(
            EventType.MODEL_RETRY_SCHEDULED, provider=self._event_provider(request),
            context_digest=request.context.manifest.digest,
            payload={
                "activation_id": request.activation_id,
                "step_id": request.step_id,
                **scope.versions(),
                "attempt": request.attempt,
                "max_attempts": self._max_attempts,
                "root_step_id": request.root_step_id,
                "retry_of_step_id": request.retry_of_step_id,
                "attempt_id": request.attempt_id,
                "logical_call_id": request.logical_call_id,
                "context_event_id": request.context_event_id,
                "next_step_id": next_step_id,
                "next_attempt": request.attempt + 1,
                "purpose": request.purpose,
                "effective_contract_hash": request.effective_contract_hash,
                "reason": error.reason,
                "retryable": True,
                "delay_sec": delay,
                **self._call_target(request),
            }))

    def compaction(self, transaction: Transaction, request: ModelRequest, result: CompactionResult,
                   response: ModelResponse) -> None:
        # 压缩请求的回答生成的检查点：摘要与压缩计划写成工件，检查点写成 compaction_recorded
        scope = self.scope
        checkpoint, plan = result.checkpoint, result.plan
        summary_ref = self._artifacts.put(scope.run_id, "department_summary", checkpoint.summary,
                                          media_type="text/plain")
        plan_ref = self._artifacts.put(scope.run_id, "compaction_plan", json_dumps(asdict(plan)),
                                       media_type="application/json")
        self._record_in(transaction, self._draft(
            EventType.COMPACTION_RECORDED, provider=response.provider or self._event_provider(request),
            model=response.model,
            context_digest=request.context.manifest.digest,
            artifact_hashes=[summary_ref.content_hash, plan_ref.content_hash],
            payload={"run_id": scope.run_id, "department": scope.department,
                     **scope.versions(),
                     "activation_id": scope.activation_id, "step_id": request.step_id,
                     "purpose": "compaction", "checkpoint": asdict(checkpoint),
                     "source_refs": plan.source_refs, "summary_ref": asdict(summary_ref),
                     "plan_ref": asdict(plan_ref), "summary_token_limit": plan.summary_token_limit,
                     "max_output_tokens": plan.max_output_tokens,
                     **scope.work_basis(),
                     **self._call_target(request),
                     "previous_compaction_event_id": result.previous_compaction_event_id}))

    def tool_started(self, transaction: Transaction, request: ModelRequest, call: dict[str, Any],
                     before_snapshot: dict[str, Any] | None = None) -> None:
        # 工具许可允许以后、执行之前记录。
        # 动作前的公开树快照与这条事件一起写入（工单 #17，恢复契约第 4 节）：中断以后按这份快照与
        # 动作参数核对实际效果，快照放在 run 自己的对象区域，不建立提交、不改动分支索引
        scope = self.scope
        payload = {**self._redacted_call(call), "activation_id": request.activation_id,
                   "attempt_id": request.attempt_id,
                   "logical_call_id": request.logical_call_id,
                   "context_event_id": request.context_event_id,
                   "attempt": request.attempt,
                   **scope.versions(),
                   **scope.work_basis()}
        if before_snapshot is not None:
            before_ref = self._artifacts.put(scope.run_id, "snapshot/before", json_dumps(before_snapshot),
                                             media_type="application/json")
            payload["before_snapshot_ref"] = asdict(before_ref)
        self._record_in(transaction, self._draft(EventType.TOOL_STARTED, payload=payload))

    def _redacted_call(self, call: dict[str, Any]) -> dict[str, Any]:
        # 动作参数里的命令按 ADR-0038 只留凭据的名称：事件里不出现密钥原文
        args = call.get("args")
        if not isinstance(args, dict):
            return call
        return {**call, "args": redact_tool_args(args)}

    def _draft(self, type: str, **fields: Any) -> Draft:
        # 这次激活的一条记录：部门、上级事件与会话取自激活，阶段在追加的事务中填入。
        # 角色任务中的记录由部门提出（设计第 5.2 节）
        scope = self.scope
        return lambda transaction: NewEvent(type, state_before=transaction.projection.status,
                                           state_after=transaction.projection.status,
                                           actor=f"department:{scope.department}", department=scope.department,
                                           parent_event_id=scope.parent_event_id, session_id=scope.session_id,
                                           **fields)

    def _delivery_invalidated(self, reason: str) -> Draft:
        # 成果失效事件（骨架事件，S1b，设计说明第 4 节）：工作区被这个部门改了以后当前交付失效。
        # 没有当前交付时没有要失效的成果，那一刻不记事件。
        # 记的是事务里的那一版交付：它与这条工具结果在同一个事务里，先后由事件的顺序决定
        scope = self.scope

        def build(transaction: Transaction) -> NewEvent | None:
            delivery = transaction.projection.delivery_spec
            if delivery is None:
                return None
            return NewEvent(EventType.ARTIFACT_INVALIDATED, state_before=transaction.projection.status,
                            state_after=transaction.projection.status,
                            actor=f"department:{scope.department}", department=scope.department,
                            parent_event_id=scope.parent_event_id, session_id=scope.session_id,
                            payload={"artifact_kind": "delivery_spec", "artifact_version": delivery.revision,
                                     "reason": reason})
        return build

    def _call_target(self, request: ModelRequest) -> dict[str, Any]:
        # 这次逻辑调用解析出的调用目标公开部分：写入请求、尝试与压缩事件，不含密钥
        return dict(request.call_target or {})

    def _event_provider(self, request: ModelRequest | None = None) -> str | None:
        # 事件上的提供方：解析出的连接标识优先，没有解析结果时用激活开始时的名称
        if request is not None:
            config_id = self._call_target(request).get("provider_config_id")
            if isinstance(config_id, str) and config_id:
                return config_id
        return self.scope.provider

    def _record(self, *drafts: Draft) -> list[Event]:
        # 在写入口开一个事务追加一次调用的全部记录
        if not drafts:
            return []
        return self._writes.transact(run_stream(self.scope.run_id),
                                     lambda transaction: self._record_in(transaction, *drafts))

    @staticmethod
    def _record_in(transaction: Transaction, *drafts: Draft) -> list[Event]:
        # 在调用方的事务中追加记录，状态取这个事务中的运行状态；
        # 这一刻没有要记的事实的草稿（例如没有当前交付时的成果失效）不追加
        entries = [entry for entry in (draft(transaction) for draft in drafts) if entry is not None]
        if not entries:
            return []
        return transaction.append(*entries)

    def _capture(self, request: ModelRequest) -> _AttemptCapture:
        capture = self._captures.get(request.attempt_id)
        if capture is None:
            capture = _AttemptCapture()
            self._captures[request.attempt_id] = capture
        return capture

    def _finalize_capture(self, request: ModelRequest) -> _AttemptCapture:
        capture = self._captures.pop(request.attempt_id or "", None)
        if capture is None:
            capture = _AttemptCapture()
        try:
            if capture.stream_event_count:
                ref = self._artifacts.put_stream(
                    self.scope.run_id,
                    "sdk_stream_events",
                    capture.stream_chunks(),
                    media_type="application/x-ndjson",
                )
                capture.stream_ref = asdict(ref)
        finally:
            capture.close()
        return capture

    def _observe(self, request: ModelRequest, observation: _Observation) -> list[Draft]:
        # 一条观察要追加的记录；工件在这里写好，累计状态在这里更新
        scope = self.scope
        if observation.kind != "stream_event":
            key = (f"{request.attempt_id or request.step_id}:{observation.kind}", observation.id)
            if key in self._seen:
                return []
            if observation.kind != "reasoning":
                # 推理内容的去重由 _reasoning_drafts 按条目身份完成
                self._seen.add(key)
        if observation.kind == "request":
            if not isinstance(observation.payload, dict):
                raise ProviderError("Serialized provider request is not a JSON object", reason="provider_protocol")
            ref = self._artifacts.put(
                scope.run_id,
                "sdk_request",
                json_dumps(observation.payload),
                media_type="application/json",
            )
            payload = {
                "attempt_id": request.attempt_id,
                "logical_call_id": request.logical_call_id,
                "context_event_id": request.context_event_id,
                "activation_id": request.activation_id,
                "step_id": request.step_id,
                "attempt": request.attempt,
                "root_step_id": request.root_step_id,
                "retry_of_step_id": request.retry_of_step_id,
                "purpose": request.purpose,
                "request_ref": asdict(ref),
                "request_digest": canonical_hash(observation.payload),
                "serialization": "sdk_request_json_object",
                **scope.work_basis(),
                **scope.versions(),
                **self._call_target(request),
            }
            return [self._draft(
                EventType.MODEL_REQUEST_SERIALIZED, provider=self._event_provider(request),
                context_digest=request.context.manifest.digest, artifact_hashes=[ref.content_hash],
                payload=payload)]
        if observation.provider:
            self._provider = observation.provider
        if observation.model:
            self._model = observation.model
        provider = self._provider or self._event_provider(request)
        model = self._model
        if observation.kind == "stream_event":
            if not isinstance(observation.payload, dict):
                raise ProviderError("Decoded provider stream event is not a JSON object", reason="provider_protocol")
            capture = self._capture(request)
            observation.payload = _redact(observation.payload)
            capture.actual_provider = observation.provider or capture.actual_provider
            capture.actual_model = observation.model or capture.actual_model
            capture.provider_response_id = observation.response_id or capture.provider_response_id
            observed_at = utc_now()
            capture.add_stream_event(observation.sequence, observation.payload, observed_at)
            return self._stream_progress(request, capture, observation, observed_at)
        if observation.kind == "response":
            if not isinstance(observation.payload, dict):
                raise ProviderError("Provider response is not a JSON object", reason="provider_protocol")
            capture = self._capture(request)
            observation.payload = _redact(observation.payload)
            capture.actual_provider = observation.provider or capture.actual_provider
            capture.actual_model = observation.model or capture.actual_model
            ref = self._artifacts.put(
                scope.run_id,
                "sdk_response",
                json_dumps(observation.payload),
                media_type="application/json",
            )
            capture.response_ref = asdict(ref)
            capture.provider_response_id = (
                observation.payload.get("id") if isinstance(observation.payload.get("id"), str) else observation.id
            )
            return []
        if observation.kind == "usage":
            if observation.usage is None:
                return []
            capture = self._capture(request)
            safe_usage = _redact(observation.payload)
            ref = self._artifacts.put(scope.run_id, "model_usage", json_dumps(safe_usage),
                                      media_type="application/json")
            self._raw_usage_ref = asdict(ref)
            capture.usage = observation.usage
            capture.usage_ref = asdict(ref)
            has_usage = bool(
                observation.usage.reported
                or observation.usage.total_tokens
                or observation.usage.cost
            )
            if has_usage:
                self._step_usage = observation.usage
                usage = self._previous_usage.plus(observation.usage)
            else:
                usage = self._usage if self._has_usage else Usage(reported=False)
            return self._charge(
                request,
                usage,
                provider=provider,
                model=model,
                force=bool(observation.model),
                reported=(observation.usage.reported if has_usage else False),
            )
        if observation.kind in {"tool", "skipped_tool"}:
            payload = _redact(dict(observation.payload))
            tool_id = f"{request.step_id}:{payload.get('id') or observation.id}"
            if tool_id in self._tool_ids:
                return []
            self._tool_ids.add(tool_id)
            output = payload.pop("output", None)
            if output is not None:
                ref = self._artifacts.put(scope.run_id, "tool_output", json_dumps(output),
                                          media_type="application/json")
                payload["output_ref"] = asdict(ref)
            event_type = EventType.TOOL_CALLED if observation.kind == "tool" else EventType.TOOL_SKIPPED
        elif observation.kind == "message":
            safe_text = _redact(observation.text)
            self._messages.append(safe_text)
            self._message_steps.append((request.activation_id, request.step_id))
            message = _redact(observation.payload or {"role": "assistant", "content": safe_text})
            ref = self._artifacts.put(scope.run_id, "model_message", json_dumps(message),
                                      media_type="application/json")
            payload = {
                "message_ref": asdict(ref),
                "message_index": len(self._messages),
                "response_id": message.get("id"),
                "stop_reason": message.get("status"),
                "summary": safe_text[:160],
            }
            event_type = EventType.MODEL_MESSAGE
        elif observation.kind == "reasoning":
            return self._reasoning_drafts(request, [observation.payload], provider=provider, model=model)
        else:
            raise ValueError(f"unknown adapter observation: {observation.kind}")
        payload["attempt_id"] = request.attempt_id
        payload["logical_call_id"] = request.logical_call_id
        payload["context_event_id"] = request.context_event_id
        payload["activation_id"] = request.activation_id
        payload["step_id"] = request.step_id
        payload["purpose"] = request.purpose
        payload.update(scope.work_basis())
        payload.update(scope.versions())
        payload.update(self._call_target(request))
        drafts = [self._draft(event_type, provider=provider, model=model, payload=payload)]
        if (event_type == EventType.TOOL_CALLED and scope.department != "quality"
                and payload.get("ok") and payload.get("name") in _WRITE_TOOLS):
            # 非质检部门写了文件：当前交付失效，紧跟着这条工具结果记一条成果失效事件（S1b，设计说明第 4 节）。
            # 质检改的是自己的检查工作区，运行工作区与交付不变
            drafts.append(self._delivery_invalidated("workspace_changed"))
        if observation.usage is not None and (observation.usage.reported or observation.usage.total_tokens
                                              or observation.usage.cost):
            self._step_usage = observation.usage
            drafts.extend(self._charge(request, self._previous_usage.plus(observation.usage), provider=provider,
                                       model=model))
        return drafts

    def _stream_progress(self, request: ModelRequest, capture: _AttemptCapture, observation: _Observation,
                         observed_at: str) -> list[Draft]:
        # 流式进度：同一次调用尝试中只在阶段变化时记录一条（设计说明第 10 节第 5 项）。
        # 阶段之内的文字增量由输出片段通道转发，不写入事件日志
        scope = self.scope
        payload = observation.payload
        stage = observation.stage
        if capture.first_observed_at is None:
            capture.first_observed_at = observed_at
        if stage in {"output", "output_item_done"} and capture.first_output_at is None:
            capture.first_output_at = observed_at
        changed = stage != capture.progress_stage
        capture.progress_stage = stage
        if not changed:
            return []
        return [self._draft(
            EventType.MODEL_STREAM_PROGRESS,
            provider=self._provider or self._event_provider(request), model=observation.model or self._model,
            context_digest=request.context.manifest.digest,
            payload={
                "attempt_id": request.attempt_id,
                "logical_call_id": request.logical_call_id,
                "context_event_id": request.context_event_id,
                "activation_id": request.activation_id,
                "step_id": request.step_id,
                "attempt": request.attempt,
                "root_step_id": request.root_step_id,
                "purpose": request.purpose,
                "source": "sdk_decoded_stream",
                "stage": stage,
                "event_type": payload.get("type"),
                "sequence": observation.sequence,
                "observed_at": observed_at,
                "first_observed_at": capture.first_observed_at,
                "first_output_at": capture.first_output_at,
                "summary": _stream_progress_summary(payload),
                **scope.versions(),
            })]

    def _charge(self, request: ModelRequest, usage: Usage, *, provider: str, model: str | None,
                force: bool = False, reported: bool | None = None) -> list[Draft]:
        # 用量按激活累计，每条记录带着相对上一条的增量；增量为零且不是第一条时不记录
        scope = self.scope
        token_delta = usage.total_tokens - self._tokens_charged
        cost_delta = usage.cost - self._cost_charged
        first = not self._has_usage
        self._has_usage = True
        self._usage = usage
        self._tokens_charged = usage.total_tokens
        self._cost_charged = usage.cost
        if not (first or token_delta or cost_delta or force):
            return []
        return [self._draft(
            EventType.TOOL_CALLED, provider=provider, model=model,
            payload={
                "name": "provider_usage", "ok": True,
                **scope.versions(),
                "activation_id": request.activation_id,
                "step_id": request.step_id,
                "purpose": request.purpose,
                "accounting": "activation_total_with_charge_delta",
                "scope": "observable_main_dialogue",
                "source": "reported" if (usage.reported if reported is None else reported) else "unreported",
                "cost_reported": usage.cost_reported,
                "raw_usage_ref": self._raw_usage_ref,
                "tokens_charged": token_delta,
                "total_tokens": usage.total_tokens,
                "input_tokens": usage.input_tokens,
                "cache_read_tokens": usage.cache_read_tokens,
                "cache_write_tokens": usage.cache_write_tokens,
                "input_total_tokens": usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens,
                "output_tokens": usage.output_tokens,
                "cost": cost_delta, "total_cost": usage.cost,
                **self._call_target(request),
            })]
