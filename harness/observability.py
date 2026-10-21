"""只读的模型尝试、Context、Provider 原文和用量查询。

该模块只读取 Event Store 与 Artifact Store。它不会创建模型调用、执行工具，
也不会把查询结果写回投影或事件事实。
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from typing import Any

from .artifacts import ArtifactStore
from .event_store import EventStore
from .models import (
    ArtifactRef,
    Event,
    EventType,
    canonical_hash,
    json_dumps,
)
from .providers.resolve import CALL_TARGET_FIELDS
from .views import compaction_coverage


SCHEMA_VERSION = 1
STREAM_PROGRESS_EVENT = "model_stream_progress"
USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "total_tokens",
    "cost",
    "latency_ms",
)


class AttemptNotFoundError(KeyError):
    """The requested physical attempt does not belong to the run."""


class ObservabilityQuery:
    """Build observability responses from immutable events and artifacts."""

    def __init__(self, store: EventStore, artifacts: ArtifactStore) -> None:
        self.store = store
        self.artifacts = artifacts

    def attempt_detail(self, run_id: str, attempt: dict[str, Any], records: dict[str, dict[str, Any]], *,
                       context_event: Event | None = None, lifecycle_events: list[dict[str, Any]] | None = None,
                       tool_events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        # 一次尝试的详情；记录可以由调用方给出（读取模型的调用尝试表按运行给出这个 run 的记录），
        # 事件列表与工具回执只在调用方给出时出现，工件按引用读取
        context = self._context_detail(run_id, context_event, attempt)
        sdk_request = self._artifact_json(run_id, attempt.get("sdk_request_ref"))
        sdk_response = self._artifact_json(run_id, attempt.get("response_ref"))
        sdk_events = self._stream_events(run_id, attempt.get("stream_events_ref"))
        sibling_records = [
            item for item in records.values()
            if item.get("logical_call_id") == attempt.get("logical_call_id")
            and item.get("id") != attempt.get("id")
        ]
        sibling_records.sort(key=lambda item: (item.get("seq", 0), item.get("attempt", 0)))
        siblings = [_public_attempt(item) for item in sibling_records]
        scope = attempt.get("collection_scope") or _collection_scope()
        detail = {
            "run_id": run_id,
            "version": SCHEMA_VERSION,
            "attempt": _public_attempt(attempt),
            "siblings": siblings,
            "context": context,
            "request": sdk_request,
            "response": sdk_response,
            "events": _detail_events(lifecycle_events or [], sdk_events),
            "event_order": "source_grouped",
            "tools": tool_events or [],
            "observed_scope": scope,
            "artifact_refs": {
                "request": attempt.get("sdk_request_ref"),
                "response": attempt.get("response_ref"),
                "events": attempt.get("stream_events_ref"),
                "usage": attempt.get("raw_usage_ref"),
            },
        }
        return detail

    @staticmethod
    def public_attempt(record: dict[str, Any]) -> dict[str, Any]:
        return _public_attempt(record)

    def _context_detail(self, run_id: str, event: Event | None,
                        attempt: dict[str, Any]) -> dict[str, Any] | None:
        if event is None:
            return None
        payload = event.payload or {}
        request = self._artifact_json(run_id, payload.get("request_ref"))
        if request is not None and payload.get("digest") and canonical_hash(request) != payload.get("digest"):
            raise ValueError("context request artifact does not match its manifest digest")
        parts_ref = payload.get("parts_ref")
        parts = None
        if parts_ref is not None:
            if not isinstance(parts_ref, dict):
                raise ValueError("context parts reference is invalid")
            if parts_ref.get("content_hash") not in event.artifact_hashes:
                raise ValueError("context parts artifact is not bound to its event")
            parts = self._artifact_json(run_id, parts_ref)
            if not isinstance(parts, list):
                raise ValueError("context parts artifact is unavailable")
            _validate_context_parts(parts, payload.get("injected"))
        compaction_id = payload.get("compaction_event_id")
        coverage = None
        if compaction_id:
            coverage = compaction_coverage(self.store.get_event(compaction_id))
        summaries = _summaries_from_parts(parts)
        return {
            "event_id": event.event_id,
            "seq": event.stream_version,
            "manifest": payload,
            "request": request,
            "parts": parts,
            "parts_ref": parts_ref,
            "source_event_ids": [event.event_id],
            "coverage": coverage,
            "summaries": summaries,
        }

    def _artifact_json(self, run_id: str, ref: Any) -> Any:
        return artifact_json(self.artifacts, run_id, ref)

    def _stream_events(self, run_id: str, ref: Any) -> list[dict[str, Any]]:
        if not isinstance(ref, dict):
            return []
        try:
            raw = self.artifacts.get_for_run(run_id, ArtifactRef(**ref)).decode("utf-8")
        except (FileNotFoundError, KeyError, TypeError, ValueError, UnicodeDecodeError):
            return []
        result = []
        for line in raw.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                result.append(item)
        return result

def artifact_json(artifacts: ArtifactStore, run_id: str, ref: Any) -> Any:
    if not isinstance(ref, dict):
        return None
    try:
        raw = artifacts.get_for_run(run_id, ArtifactRef(**ref))
        return json.loads(raw)
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def attempt_usage(artifacts: ArtifactStore, run_id: str, record: dict[str, Any]) -> dict[str, Any]:
    # 一次尝试的用量：上游原文按引用读取，标准化的汇总逐字段补齐原文里没有的字段（工单 #656）
    raw = artifact_json(artifacts, run_id, record.get("raw_usage_ref"))
    if isinstance(raw, dict) and isinstance(raw.get("usage"), dict):
        raw = raw["usage"]
    summary = record.get("usage_summary")
    values: dict[str, Any] = {field: None for field in USAGE_FIELDS}
    currency = None
    cost_source = None
    raw_reported = False
    if isinstance(raw, dict):
        values["input_tokens"] = _count_value(raw.get("input_tokens"))
        if values["input_tokens"] is None:
            # Chat Completions 协议的原文用 prompt_tokens（工单 #656）
            values["input_tokens"] = _count_value(raw.get("prompt_tokens"))
        details = raw.get("input_tokens_details")
        if not isinstance(details, dict):
            details = raw.get("prompt_tokens_details")
        if isinstance(details, dict):
            values["cache_read_tokens"] = _count_value(details.get("cached_tokens"))
            values["cache_write_tokens"] = _count_value(
                details.get("cache_write_tokens")
                if "cache_write_tokens" in details else details.get("cache_write")
            )
        values["cache_write_tokens"] = values["cache_write_tokens"] if values["cache_write_tokens"] is not None else _count_value(raw.get("cache_write_tokens"))
        values["output_tokens"] = _count_value(raw.get("output_tokens"))
        if values["output_tokens"] is None:
            # Chat Completions 协议的原文用 completion_tokens（工单 #656）
            values["output_tokens"] = _count_value(raw.get("completion_tokens"))
        values["total_tokens"] = _count_value(raw.get("total_tokens"))
        values["cost"] = _cost_value(raw.get("cost"))
        currency = raw.get("currency") or raw.get("cost_currency")
        cost_source = raw.get("cost_source") or ("provider" if values["cost"] is not None else None)
        if values["cost"] is not None and not isinstance(currency, str):
            values["cost"] = None
        raw_reported = _has_usage_values(values)
    if isinstance(summary, dict):
        # 摘要逐字段补齐原文里没有的字段（工单 #656）：原文读到了也照样补。
        # Chat Completions 原文里的分项在原文分支读不到，靠这里的规范化取值补上。
        for field in USAGE_FIELDS:
            if values[field] is None and summary.get(field) is not None:
                values[field] = _cost_value(summary[field]) if field == "cost" else (
                    _count_value(summary[field]) if field != "latency_ms" else _count_value(summary[field])
                )
        if not isinstance(currency, str) and isinstance(summary.get("currency"), str):
            currency = summary["currency"]
        if not isinstance(cost_source, str) and isinstance(summary.get("cost_source"), str):
            cost_source = summary["cost_source"]
        if values["cost"] is not None and not isinstance(currency, str):
            values["cost"] = None
    # 来源按补齐后的值重新判定（工单 #656）：原文报了就是原文，
    # 补齐出来的分项跟着摘要自己说的算（摘要说已上报才是已上报，否则是未知）
    if raw_reported:
        source = "reported"
    elif _has_usage_values(values):
        source = "reported" if isinstance(summary, dict) and summary.get("reported") else "unknown"
    else:
        source = "missing"
    values["latency_ms"] = record.get("duration_ms")
    return {
        **values,
        "currency": currency if isinstance(currency, str) and currency else None,
        "cost_source": cost_source if isinstance(cost_source, str) and cost_source else None,
        "source": source,
        "reported": source == "reported",
        "coverage": {
            field: _usage_field_state(field, values[field], source)
            for field in USAGE_FIELDS
        },
    }


class AttemptFold:
    """把 run 事件逐步并入调用尝试记录（应用层的调用尝试表使用）。

    merge 一次事件，records() 得到完整的调用尝试记录：应用层的调用尝试表从它建立。
    state() 与 load_state() 用于把折叠状态保存在读取模型里，按订阅逐步更新；用量只在它依据的字段变化时重新计算。
    """

    def __init__(self, artifacts: ArtifactStore, run_id: str) -> None:
        self.artifacts = artifacts
        self.run_id = run_id
        self._records: dict[str, dict[str, Any]] = {}
        self.positions: dict[str, int] = {}
        self.activation_rounds: dict[str, Any] = {}
        self.output_item_counts: dict[str, int] = defaultdict(int)
        self.progress_attempts: set[str] = set()
        self.progress_facts: dict[str, dict[str, Any]] = {}
        self.usage_signatures: dict[str, Any] = {}

    @classmethod
    def load_state(cls, artifacts: ArtifactStore, run_id: str, state: str) -> "AttemptFold":
        fold = cls(artifacts, run_id)
        saved = json.loads(state)
        fold._records = saved["records"]
        fold.positions = {key: int(value) for key, value in saved["positions"].items()}
        fold.activation_rounds = saved["activation_rounds"]
        fold.output_item_counts = defaultdict(int, {key: int(value) for key, value in saved["output_item_counts"].items()})
        fold.progress_attempts = set(saved["progress_attempts"])
        fold.progress_facts = saved["progress_facts"]
        fold.usage_signatures = saved["usage_signatures"]
        return fold

    def state(self) -> str:
        return json_dumps({
            "records": self._records,
            "positions": self.positions,
            "activation_rounds": self.activation_rounds,
            "output_item_counts": dict(self.output_item_counts),
            "progress_attempts": sorted(self.progress_attempts),
            "progress_facts": self.progress_facts,
            "usage_signatures": self.usage_signatures,
        })

    def merge(self, event: Event) -> None:
        payload = event.payload or {}
        record: dict[str, Any] | None = None
        if event.type == EventType.DEPARTMENT_ACTIVATED and payload.get("activation_id"):
            self.activation_rounds[str(payload["activation_id"])] = payload.get("cycle")
        elif event.type == EventType.CONTEXT_ASSEMBLED and payload.get("purpose") in {"work", "compaction"}:
            record = self._record(_attempt_id_for(payload, event.department), event, payload)
            _merge_context(record, event, payload)
        elif event.type == EventType.MODEL_REQUESTED:
            record = self._record(_attempt_id_for(payload, event.department), event, payload)
            _merge_started(record, event, payload)
        elif event.type == EventType.MODEL_REQUEST_SERIALIZED:
            record = self._record(_attempt_id_for(payload, event.department), event, payload)
            record["sdk_request_ref"] = payload.get("request_ref")
            record["request_serialized_event_id"] = event.event_id
            record["request_digest"] = payload.get("request_digest")
        elif event.type in {EventType.MODEL_ATTEMPT_FINISHED, EventType.MODEL_ATTEMPT_FAILED}:
            record = self._record(_attempt_id_for(payload, event.department), event, payload)
            _merge_finished(record, event, payload)
        elif event.type == EventType.MODEL_RETRY_SCHEDULED:
            record = self._record(_attempt_id_for(payload, event.department), event, payload)
            record["retry_scheduled_event_id"] = event.event_id
            record["retry_delay_sec"] = payload.get("delay_sec")
        elif event.type == EventType.MODEL_MESSAGE:
            self.output_item_counts[_attempt_id_for(payload, event.department)] += 1
        elif event.type == STREAM_PROGRESS_EVENT:
            attempt_id = _attempt_id_for(payload, event.department)
            stage = payload.get("stage")
            if stage in {"output", "output_item_done"} or payload.get("first_output_at"):
                self.progress_attempts.add(attempt_id)
            self.progress_facts[attempt_id] = {
                "stream_first_observed_at": payload.get("first_observed_at"),
                "stream_first_output_at": payload.get("first_output_at"),
                "stream_last_stage": stage,
            }
        if record is not None:
            self._refresh_usage(record)

    def records(self) -> dict[str, dict[str, Any]]:
        for record in self._records.values():
            record["work_round"] = self.activation_rounds.get(str(record.get("activation_id")))
            output_count = self.output_item_counts.get(record["id"], 0)
            record.update(self.progress_facts.get(record["id"], {}))
            record["output_item_count"] = output_count
            record["partial_output"] = bool(
                record.get("status") in {"requesting", "failed", "cancelled"}
                and (output_count or record["id"] in self.progress_attempts)
            )
            record["stage"] = (
                "partial" if record.get("status") == "requesting" and record["partial_output"]
                else record.get("status")
            )
        counts: dict[str, int] = defaultdict(int)
        for record in self._records.values():
            if record.get("sent"):
                counts[str(record.get("logical_call_id"))] += 1
        for record in self._records.values():
            record["attempt_count"] = counts[str(record.get("logical_call_id"))]
        return self._records

    def _record(self, attempt_id: str, event: Event, payload: dict[str, Any]) -> dict[str, Any]:
        record = self._records.get(attempt_id)
        if record is None:
            record = _new_attempt(attempt_id, event, payload)
            self._records[attempt_id] = record
            self.positions[attempt_id] = event.position
        return record

    def _refresh_usage(self, record: dict[str, Any]) -> None:
        signature = json_dumps([record.get("raw_usage_ref"), record.get("usage_summary")])
        if self.usage_signatures.get(record["id"]) != signature:
            record["usage"] = attempt_usage(self.artifacts, self.run_id, record)
            self.usage_signatures[record["id"]] = signature


def _public_attempt(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record.get("id"),
        "logical_call_id": record.get("logical_call_id"),
        "collaboration_request_id": record.get("collaboration_request_id"),
        "provider_response_id": record.get("provider_response_id"),
        "context_event_id": record.get("context_event_id"),
        "activation_id": record.get("activation_id"),
        "step": record.get("step"),
        "attempt": record.get("attempt"),
        "root_step_id": record.get("root_step_id"),
        "department": record.get("department"),
        "purpose": record.get("purpose"),
        "prompt_version": record.get("prompt_version"),
        "provider": record.get("actual_provider") or record.get("requested_provider"),
        "model": record.get("actual_model"),
        "created_at": record.get("started_at") or record.get("prepared_at"),
        "attempt_count": record.get("attempt_count"),
        "work_round": record.get("work_round"),
        "requested_provider": record.get("requested_provider"),
        "requested_model": record.get("requested_model"),
        "actual_provider": record.get("actual_provider"),
        "actual_model": record.get("actual_model"),
        # 这次请求的调用目标公开部分（不含 Key）、选择来源与请求/实际发送的档位（设计说明第 6 节）
        "call_target": record.get("call_target"),
        "status": _public_status(record),
        "stage": record.get("stage", record.get("status")),
        "partial_output": record.get("partial_output", False),
        "output_item_count": record.get("output_item_count", 0),
        "stream_first_observed_at": record.get("stream_first_observed_at"),
        "stream_first_output_at": record.get("stream_first_output_at"),
        "stream_last_stage": record.get("stream_last_stage"),
        "prepared_at": record.get("prepared_at"),
        "started_at": record.get("started_at"),
        "finished_at": record.get("finished_at"),
        "duration_ms": record.get("duration_ms"),
        "usage": record.get("usage"),
        "observed_scope": record.get("collection_scope"),
        "error_class": record.get("reason") or record.get("error_class"),
        "reason": record.get("reason"),
        "diagnostics": record.get("diagnostics"),
        "error": record.get("error"),
        "retryable": record.get("retryable"),
        "will_retry": record.get("will_retry"),
    }


def _public_status(record: dict[str, Any]) -> str:
    status = record.get("status")
    if status == "completed":
        return "success"
    if status in {"prepared", "requesting"}:
        return "running"
    if status == "cancelled":
        return "cancelled"
    return "failed"




def _new_attempt(attempt_id: str, event: Event, payload: dict[str, Any]) -> dict[str, Any]:
    root = payload.get("root_step_id")
    purpose = payload.get("purpose", "work")
    logical = payload.get("logical_call_id") or _logical_call_id(payload.get("activation_id"), root, purpose)
    return {
        "id": attempt_id,
        "logical_call_id": logical,
        "collaboration_request_id": payload.get("collaboration_request_id", payload.get("request_id")),
        "provider_response_id": None,
        "context_event_id": payload.get("context_event_id"),
        "activation_id": payload.get("activation_id"),
        "step": payload.get("step_id"),
        "attempt": payload.get("attempt", 1),
        "root_step_id": root,
        "department": event.department or payload.get("department"),
        "purpose": purpose,
        "prompt_version": payload.get("prompt_version"),
        "requested_provider": payload.get("requested_provider"),
        "requested_model": payload.get("requested_model"),
        "actual_provider": None,
        "actual_model": None,
        "call_target": None,
        "status": "prepared",
        "sent": False,
        "prepared_at": event.created_at if event.type == EventType.CONTEXT_ASSEMBLED else None,
        "started_at": None,
        "finished_at": None,
        "duration_ms": None,
        "seq": event.stream_version,
        "sdk_request_ref": None,
        "response_ref": None,
        "stream_events_ref": None,
        "stream_event_count": 0,
        "raw_usage_ref": None,
        "usage_summary": None,
        "collection_scope": _collection_scope(),
        "stream_first_observed_at": None,
        "stream_first_output_at": None,
        "stream_last_stage": None,
    }


def _merge_context(record: dict[str, Any], event: Event, payload: dict[str, Any]) -> None:
    record.update({
        "context_event_id": event.event_id,
        "prepared_at": event.created_at,
        "seq": min(record.get("seq", event.stream_version), event.stream_version),
        "requested_provider": payload.get("requested_provider", record.get("requested_provider")),
        "requested_model": payload.get("requested_model", record.get("requested_model")),
        "prompt_version": payload.get("prompt_version", record.get("prompt_version")),
    })


# 调用目标的公开字段：请求、尝试与压缩事件把 call_target_public 的结果连同选择来源写入载荷（设计说明第 6 节）；
# 字段清单由 Provider 模块给出，观察与分析按它取出
def _call_target_public(payload: dict[str, Any]) -> dict[str, Any]:
    # 从请求事件载荷取出调用目标的公开部分（不含 Key）、选择来源与请求/实际发送的档位
    return {key: payload.get(key) for key in (*CALL_TARGET_FIELDS, "selection_source")}

def _merge_started(record: dict[str, Any], event: Event, payload: dict[str, Any]) -> None:
    record.update({
        "status": "requesting",
        "sent": True,
        "started_at": payload.get("started_at") or event.created_at,
        "seq": min(record.get("seq", event.stream_version), event.stream_version),
        "requested_provider": payload.get("requested_provider", record.get("requested_provider")),
        "requested_model": payload.get("requested_model", record.get("requested_model")),
        "actual_provider": payload.get("actual_provider", record.get("actual_provider")),
        "actual_model": payload.get("actual_model", record.get("actual_model")),
        "started_event_id": event.event_id,
        # 这次请求的调用目标公开部分（不含 Key）、选择来源与请求/实际发送的档位（设计说明第 6 节）；
        # run.attempt 从它读取（工单 #92）
        "call_target": _call_target_public(payload),
    })


def _merge_finished(record: dict[str, Any], event: Event, payload: dict[str, Any]) -> None:
    status = payload.get("status")
    if not isinstance(status, str):
        status = "completed" if event.type == EventType.MODEL_ATTEMPT_FINISHED else (
            "cancelled" if payload.get("reason") == "cancelled" or event.stop_reason == "cancelled" else "failed"
        )
    response_id = payload.get("provider_response_id")
    actual_model = payload.get("actual_model") or event.model
    has_response = bool(payload.get("response_ref") or response_id or actual_model)
    record.update({
        "status": status,
        "finished_at": payload.get("finished_at") or event.created_at,
        "duration_ms": payload.get("duration_ms"),
        "response_ref": payload.get("response_ref"),
        "stream_events_ref": payload.get("stream_events_ref"),
        "stream_event_count": payload.get("stream_event_count", 0),
        "provider_response_id": response_id,
        "raw_usage_ref": payload.get("raw_usage_ref"),
        "usage_summary": payload.get("usage"),
        "collection_scope": payload.get("collection_scope") or record.get("collection_scope") or _collection_scope(),
        "stream_first_observed_at": payload.get("stream_first_observed_at"),
        "stream_first_output_at": payload.get("stream_first_output_at"),
        "stream_last_stage": payload.get("stream_last_stage"),
        "finished_event_id": event.event_id,
        "actual_provider": (payload.get("actual_provider") or event.provider) if has_response else record.get("actual_provider"),
        "actual_model": actual_model if has_response else record.get("actual_model"),
        "reason": payload.get("reason"),
        "error_class": payload.get("reason"),
        "diagnostics": payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else None,
        "retryable": payload.get("retryable"),
        "will_retry": payload.get("will_retry"),
        "error": event.error or payload.get("error"),
    })


def _attempt_id_for(payload: dict[str, Any], role: str | None) -> str:
    supplied = payload.get("attempt_id")
    if isinstance(supplied, str) and supplied:
        return supplied
    activation = payload.get("activation_id") or "activation"
    root = payload.get("root_step_id") or payload.get("step_id") or 1
    purpose = payload.get("purpose") or "work"
    logical = payload.get("logical_call_id") or _logical_call_id(activation, root, purpose)
    return f"{logical}:attempt-{payload.get('attempt', 1)}"


def _logical_call_id(activation: Any, root: Any, purpose: Any) -> str:
    return f"{activation or 'activation'}:root-{root or 1}:{purpose or 'work'}"








def _detail_events(lifecycle: list[dict[str, Any]], sdk_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for event in lifecycle:
        summary = event.get("summary") or event.get("error") or ""
        if not isinstance(summary, str):
            summary = json_dumps(summary)
        result.append({
            "event_id": event.get("event_id"),
            "time": event.get("created_at"),
            "type": event.get("type"),
            "summary": summary,
            "raw": event,
            "source": "yudao_event_store",
            "event_group": "event_store",
            "sequence": event.get("seq"),
            "sequence_source": "event_store",
            "observed_at": event.get("created_at"),
        })
    for item in sdk_events:
        raw = item["event"]
        observed_at = item["observed_at"]
        result.append({
            "event_id": None,
            "time": observed_at,
            "type": raw.get("type"),
            "summary": raw.get("type") or "sdk event",
            "raw": raw,
            "source": "sdk_decoded_stream",
            "event_group": "provider_stream",
            "sequence": item["sequence"],
            "sequence_source": "provider",
            "observed_at": observed_at,
        })
    return result


def _collection_scope() -> dict[str, str]:
    return {
        "request": "SDK request JSON object captured from the prepared HTTP request; authentication headers and raw HTTP bytes are excluded.",
        "response": "Complete SDK response object exposed by the provider SDK when a terminal response was received, with credential and header fields redacted.",
        "events": "SDK decoded stream event JSON objects captured as JSON Lines with credential and header fields redacted; raw HTTP/SSE bytes are not available.",
        "credentials": "excluded",
    }


def _count_value(value: Any) -> int | None:
    if isinstance(value, bool) or type(value) is not int or value < 0:
        return None
    return value


def _cost_value(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value








def _summaries_from_parts(parts: list[Any] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(parts, list):
        return result
    marker = "[department_memory]"
    blobs: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if not isinstance(text, str) or not text:
            continue
        if part.get("source") == "department_history":
            try:
                history = json.loads(text)
            except json.JSONDecodeError:
                history = None
            if isinstance(history, list):
                for item in history:
                    content = item.get("content") if isinstance(item, dict) else None
                    if isinstance(content, str) and marker in content:
                        blobs.append(content)
                continue
        if marker in text or part.get("source") == "department_memory":
            blobs.append(text)
    for blob in blobs:
        at = blob.find(marker)
        raw = blob[at + len(marker):].strip() if at >= 0 else blob
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"summary": raw}
        if not isinstance(parsed, dict):
            parsed = {"summary": raw}
        result.append({
            "source": "department_memory",
            "summary": parsed.get("summary") or "",
            "covered_through_event_id": parsed.get("covered_through_event_id"),
            "covered_digest": parsed.get("covered_digest"),
        })
    return result


def _validate_context_parts(parts: list[Any], injected: Any) -> None:
    if not isinstance(injected, list) or len(parts) != len(injected):
        raise ValueError("context parts do not match manifest sources")
    for part, source in zip(parts, injected):
        if not isinstance(part, dict) or not isinstance(source, dict):
            raise ValueError("context part is not a JSON object")
        if not isinstance(part.get("text"), str) or not isinstance(part.get("source"), str):
            raise ValueError("context part is missing structured text")
        digest = part.get("digest")
        if digest != canonical_hash(part["text"]) or digest != source.get("digest"):
            raise ValueError("context part digest does not match its manifest")
        if part.get("source") != source.get("source") or part.get("version") != source.get("version"):
            raise ValueError("context part identity does not match its manifest")








def search_text(record: dict[str, Any]) -> str:
    return " ".join(str(record.get(key) or "") for key in (
        "id", "logical_call_id", "collaboration_request_id", "context_event_id",
        "department", "purpose", "requested_provider", "requested_model",
        "actual_provider", "actual_model", "provider_response_id", "status",
    )).casefold()






def _has_usage_values(values: dict[str, Any]) -> bool:
    return any(values.get(field) is not None for field in USAGE_FIELDS if field != "latency_ms")


def _usage_field_state(field: str, value: Any, source: str) -> str:
    if value is None:
        return "missing"
    if field == "latency_ms":
        return "measured"
    return source if source in {"reported", "unknown"} else "unknown"











