"""只读的模型尝试、Context、Provider 原文和用量查询。

该模块只读取 Event Store 与 Artifact Store。它不会创建模型调用、执行工具，
也不会把查询结果写回投影或事件事实。
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import asdict
from typing import Any, Iterable

from .artifacts import ArtifactStore
from .event_store import EventStore
from .models import ArtifactRef, DEPARTMENTS, Event, EventType, Usage, canonical_hash, json_dumps
from .projection import RunNotFoundError, project_run
from .views import event_card, run_payload


SCHEMA_VERSION = 1
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
ATTEMPT_STATUSES = frozenset({"prepared", "requesting", "completed", "failed", "cancelled"})
USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "total_tokens",
    "cost",
    "latency_ms",
)
DEPARTMENT_MATERIAL_EVENTS = frozenset({
    EventType.SPEC_ACCEPTED,
    EventType.PRODUCT_DECISION_ACCEPTED,
    EventType.CONTRACT_ACCEPTED,
    EventType.PLAN_ACCEPTED,
    EventType.DELIVERY_ACCEPTED,
    EventType.QA_SUBMITTED,
})


class AttemptNotFoundError(KeyError):
    """The requested physical attempt does not belong to the run."""


class ObservabilityQuery:
    """Build observability responses from immutable events and artifacts."""

    def __init__(self, store: EventStore, artifacts: ArtifactStore) -> None:
        self.store = store
        self.artifacts = artifacts

    def list_model_attempts(
        self,
        run_id: str,
        *,
        department: str | None = None,
        status: str | None = None,
        q: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        records = self._filtered_attempts(
            run_id, department=department, status=status, q=q,
        )
        offset = _cursor_offset(cursor, len(records))
        page = [_public_attempt(record) for record in records[offset : offset + _limit(limit)]]
        next_offset = offset + len(page)
        sent_records = [record for record in records if record.get("sent")]
        return {
            "run_id": run_id,
            "version": SCHEMA_VERSION,
            "items": page,
            "total": len(records),
            "next_cursor": str(next_offset) if next_offset < len(records) else None,
            "total_attempts": len(sent_records),
            "running_attempts": sum(_public_status(record) == "running" for record in sent_records),
            "prepared_attempts": len(records) - len(sent_records),
        }

    def model_attempt_detail(self, run_id: str, attempt_id: str) -> dict[str, Any]:
        records = self._attempt_records(run_id)
        attempt = records.get(attempt_id)
        if attempt is None:
            raise AttemptNotFoundError(attempt_id)
        events = self.store.list_events(run_id)
        context_event = _event_by_id(events, attempt.get("context_event_id"))
        if context_event is None:
            context_event = next(
                (event for event in events
                 if event.type == EventType.CONTEXT_ASSEMBLED
                 and _attempt_id_for(event.payload, event.role) == attempt_id),
                None,
            )
        context = self._context_detail(run_id, context_event, attempt)
        sdk_request = self._artifact_json(run_id, attempt.get("sdk_request_ref"))
        sdk_response = self._artifact_json(run_id, attempt.get("response_ref"))
        sdk_events = self._stream_events(run_id, attempt.get("stream_events_ref"))
        lifecycle_events = [
            event_card(event) for event in events
            if _same_attempt(event, attempt)
            and event.type in {
                EventType.CONTEXT_ASSEMBLED,
                EventType.MODEL_REQUESTED,
                EventType.MODEL_REQUEST_SERIALIZED,
                EventType.MODEL_ATTEMPT_FINISHED,
                EventType.MODEL_ATTEMPT_FAILED,
                EventType.MODEL_RETRY_SCHEDULED,
            }
        ]
        tool_events = [
            _event_detail(event) for event in events
            if _same_attempt(event, attempt)
            and event.type in {
                EventType.TOOL_STARTED,
                EventType.TOOL_CALLED,
                EventType.TOOL_SKIPPED,
            }
            and event.payload.get("name") != "provider_usage"
        ]
        sibling_records = [
            item for item in records.values()
            if item.get("logical_call_id") == attempt.get("logical_call_id")
            and item.get("id") != attempt_id
        ]
        sibling_records.sort(key=lambda item: (item.get("seq", 0), item.get("attempt", 0)))
        siblings = [_public_attempt(item) for item in sibling_records]
        scope = attempt.get("collection_scope") or _collection_scope()
        detail_events = _detail_events(lifecycle_events, sdk_events)
        return {
            "run_id": run_id,
            "version": SCHEMA_VERSION,
            "attempt": _public_attempt(attempt),
            "siblings": siblings,
            "context": context,
            "request": sdk_request,
            "response": sdk_response,
            "events": detail_events,
            "tools": tool_events,
            "observed_scope": scope,
            "artifact_refs": {
                "request": attempt.get("sdk_request_ref"),
                "response": attempt.get("response_ref"),
                "events": attempt.get("stream_events_ref"),
                "usage": attempt.get("raw_usage_ref"),
            },
        }

    def model_usage(
        self,
        run_id: str,
        *,
        department: str | None = None,
        status: str | None = None,
        q: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        records = self._filtered_attempts(
            run_id, department=department, status=status, q=q,
        )
        prepared_count = sum(not record.get("sent") for record in records)
        all_records = records
        records = [record for record in records if record.get("sent")]
        # Usage intentionally uses the complete filtered set. Cursor/limit are
        # accepted for the shared filter contract but never narrow the sum.
        _cursor_offset(cursor, len(all_records))
        _limit(limit)
        total = _usage_totals(records)
        department_groups: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
        model_groups: dict[tuple[str | None, str | None], list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            department_groups[record.get("department")].append(record)
            model_groups[(record.get("requested_provider"), record.get("actual_model"))].append(record)

        def group_payload(label: str, items: list[dict[str, Any]], **identity: Any) -> dict[str, Any]:
            summary = _usage_totals(items)
            reported = sum(_has_reported_usage(item) for item in items)
            group_coverage = _coverage(reported, len(items))
            group_coverage["fields"] = _field_coverage(items)
            return {
                "key": label,
                "label": label,
                **identity,
                **{field: summary[field] for field in USAGE_FIELDS},
                "currency": summary.get("currency"),
                "coverage": group_coverage,
                "running_attempts": sum(_public_status(item) == "running" for item in items),
            }

        department_payload = [
            group_payload(str(department_name or "未知部门"), items, department=department_name)
            for department_name, items in department_groups.items()
        ]
        model_payload = [
            group_payload(
                f"{provider or '未知 Provider'} · {model or '未知模型'}",
                items,
                provider=provider,
                model=model,
                requested_model=next((item.get("requested_model") for item in items if item.get("requested_model")), None),
            )
            for (provider, model), items in model_groups.items()
        ]
        department_payload.sort(key=lambda item: item["label"])
        model_payload.sort(key=lambda item: item["label"])
        reported = sum(_has_reported_usage(item) for item in records)
        coverage = _coverage(reported, len(records))
        coverage["fields"] = _field_coverage(records)
        return {
            "run_id": run_id,
            "version": SCHEMA_VERSION,
            "totals": {field: total[field] for field in USAGE_FIELDS},
            "currency": total.get("currency"),
            "coverage": coverage,
            "groups": {"departments": department_payload, "models": model_payload},
            "total_attempts": len(records),
            "prepared_attempts": prepared_count,
            "filters": {
                "department": department,
                "status": status,
                "q": q,
            },
        }

    def department(self, run_id: str, department: str) -> dict[str, Any]:
        if department not in DEPARTMENTS:
            raise ValueError("unknown department")
        projection = project_run(self.store, run_id)
        events = self.store.list_events(run_id)
        records = self._attempt_records(run_id)
        attempts = [item for item in records.values() if item.get("department") == department]
        attempts.sort(key=lambda item: item.get("seq", 0))

        messages = []
        handovers = []
        for event in events:
            payload = event.payload or {}
            role = event.role
            if event.type in {
                EventType.USER_INPUT_RECEIVED,
                EventType.DEPARTMENT_INPUT,
                EventType.MODEL_MESSAGE,
                EventType.DEPARTMENT_GUIDANCE_RECEIVED,
            }:
                if event.type == EventType.USER_INPUT_RECEIVED:
                    source_type = "user"
                    source_role = "user"
                    text = payload.get("text", "")
                elif event.type == EventType.DEPARTMENT_GUIDANCE_RECEIVED:
                    if payload.get("department") != department:
                        continue
                    source_type = "user"
                    source_role = "user"
                    text = payload.get("text", "")
                elif role == department:
                    source_type = "department"
                    source_role = role
                    text = self._message_text(run_id, payload, event.type)
                else:
                    continue
                messages.append({
                    "event_id": event.event_id,
                    "seq": event.seq,
                    "type": event.type,
                    "source_type": source_type,
                    "source_role": source_role,
                    "source": "用户指导" if event.type == EventType.DEPARTMENT_GUIDANCE_RECEIVED else {
                        "user": "用户", "department": "本部门", "other_department": "其他部门"
                    }[source_type],
                    "kind": {"user": "user", "department": "self", "other_department": "other"}[source_type],
                    "detail": f"{event.type} · {event.event_id}",
                    "text": text,
                    "created_at": event.created_at,
                    "attempt_id": payload.get("attempt_id"),
                    "context_event_id": payload.get("context_event_id"),
                    "guidance_id": payload.get("id") if event.type == EventType.DEPARTMENT_GUIDANCE_RECEIVED else None,
                })
            if event.type == EventType.DEPARTMENT_GUIDANCE_RESPONDED and payload.get("department") == department:
                messages.append({
                    "event_id": event.event_id,
                    "seq": event.seq,
                    "type": event.type,
                    "source_type": "department",
                    "source_role": department,
                    "source": "本部门",
                    "kind": "self",
                    "detail": f"部门指导回应 · {event.event_id}",
                    "text": payload.get("text", ""),
                    "created_at": event.created_at,
                    "guidance_id": payload.get("guidance_id"),
                    "status": payload.get("status"),
                })
            if event.type in {EventType.COLLABORATION_REQUESTED, EventType.COLLABORATION_RESPONDED}:
                requester = payload.get("requester")
                recipient = payload.get("recipient")
                request_id = payload.get("request_id")
                related = department in {requester, recipient}
                if not related:
                    related_request = next(
                        (item for item in events
                         if item.type == EventType.COLLABORATION_REQUESTED
                         and item.payload.get("id") == request_id),
                        None,
                    )
                    related = related_request is not None and department in {
                        related_request.payload.get("requester"), related_request.payload.get("recipient"),
                    }
                    if related and requester is None:
                        requester = related_request.payload.get("requester")
                        recipient = related_request.payload.get("recipient")
                if related:
                    source_role = recipient if event.type == EventType.COLLABORATION_RESPONDED else requester
                    is_self = source_role == department
                    text = payload.get("text") or payload.get("question") or payload.get("background") or ""
                    messages.append({
                        "event_id": event.event_id,
                        "seq": event.seq,
                        "type": event.type,
                        "source_type": "department" if is_self else "other_department",
                        "source_role": source_role,
                        "source": "本部门" if is_self else "其他部门",
                        "kind": "self" if is_self else "other",
                        "detail": f"{event.type} · {event.event_id}",
                        "text": text,
                        "created_at": event.created_at,
                        "collaboration_request_id": request_id,
                    })
            if event.type in DEPARTMENT_MATERIAL_EVENTS and role == department:
                messages.append({
                    "event_id": event.event_id,
                    "seq": event.seq,
                    "type": event.type,
                    "source_type": "department",
                    "source_role": role,
                    "source": "本部门",
                    "kind": "self",
                    "detail": f"{event.type} · {event.event_id}",
                    "text": _material_summary(event),
                    "created_at": event.created_at,
                })
            if event.type in {
                EventType.TRANSITION,
                EventType.COLLABORATION_REQUESTED,
                EventType.COLLABORATION_RESPONDED,
                EventType.COLLABORATION_CLOSED,
            }:
                request_department = payload.get("requester") or payload.get("request_id")
                recipient = payload.get("recipient")
                if event.type == EventType.TRANSITION or department in {role, request_department, recipient}:
                    handovers.append({
                        "event_id": event.event_id,
                        "seq": event.seq,
                        "type": event.type,
                        "source_role": role,
                        "created_at": event.created_at,
                        "title": _handover_title(event),
                        "body": _handover_body(event),
                        "detail": _handover_detail(event),
                        "payload": payload,
                    })

        adopted_activation = next(
            (event for event in reversed(events)
             if event.type == EventType.DEPARTMENT_ACTIVATED and event.role == department),
            None,
        )
        latest_prompt = projection.department_prompts.get(department)
        prompt = None
        adopted_prompt_version = None if adopted_activation is None else adopted_activation.payload.get("prompt_version")
        adopted_prompt_hash = None if adopted_activation is None else adopted_activation.payload.get("prompt_hash")
        if adopted_activation is not None:
            prompt = next(
                (item for item in reversed(projection.prompt_versions)
                 if item.department == department
                 and (adopted_prompt_version is None or item.version == adopted_prompt_version)
                 and (adopted_prompt_hash is None or item.prompt_ref.content_hash == adopted_prompt_hash)),
                None,
            )
        binding = projection.provider_bindings.get(department)
        provider = _department_provider(binding)
        run = run_payload(self.store, run_id)
        context_items = []
        for attempt in attempts:
            context_items.append({
                "id": attempt.get("id"),
                "title": f"模型输入 · 第 {attempt.get('attempt') or '?'} 次",
                "meta": f"{_public_status(attempt)} · {attempt.get('context_event_id') or 'Context 未记录'}",
                "body": f"Context 快照 {attempt.get('context_event_id') or '未记录'}，对应尝试 {attempt.get('id')}",
                "snapshot_at": attempt.get("prepared_at"),
                "status": _public_status(attempt),
                "stage": attempt.get("status"),
            })
        department_status = (
            "failed" if projection.phase == "FAILED" else
            "success" if projection.phase == "DONE" else
            "running" if projection.active_department == department else "waiting"
        )
        return {
            "run_id": run_id,
            "version": SCHEMA_VERSION,
            "department": department,
            "task": projection.task,
            "role": {"product": "需求与方案", "engineering": "实现与交付", "quality": "验证与反馈"}[department],
            "status": department_status,
            "overview": run["board"],
            "history": run["timeline"],
            "materials": run["evidence"],
            "api": {
                "run": f"/api/runs/{run_id}",
                "events": f"/api/runs/{run_id}/events",
                "model_attempts": f"/api/runs/{run_id}/model-attempts",
                "model_usage": f"/api/runs/{run_id}/model-usage",
            },
            "messages": messages,
            "handovers": handovers,
            "contexts": context_items,
            "guidance": [
                {
                    **asdict(item),
                    "guidance_ref": asdict(item.guidance_ref),
                }
                for item in projection.department_guidance if item.department == department
            ],
            "pending_guidance": [
                item.id for item in projection.department_guidance
                if item.department == department and item.status in {"received", "in_input"}
            ],
            "provider": provider,
            "prompt": {
                "department": department,
                "version": None if prompt is None else prompt.version,
                "text": None if prompt is None else prompt.text,
                "prompt_ref": None if prompt is None else asdict(prompt.prompt_ref),
                "created_event_id": None if prompt is None else prompt.created_event_id,
                "status": "adopted" if adopted_activation is not None and prompt is not None else "unknown" if adopted_activation is not None else "pending",
                "adopted_activation_id": None if adopted_activation is None else adopted_activation.payload.get("activation_id"),
                "adopted_event_id": None if adopted_activation is None else adopted_activation.event_id,
            },
            "prompt_latest": None if latest_prompt is None else {**asdict(latest_prompt), "status": "pending"},
        }

    def _filtered_attempts(self, run_id: str, *, department: str | None,
                           status: str | None, q: str | None) -> list[dict[str, Any]]:
        if department is not None and department not in DEPARTMENTS:
            raise ValueError("unknown department")
        if status is not None and status not in {"success", "failed", "running"}:
            raise ValueError("unknown model attempt status")
        records = list(self._attempt_records(run_id).values())
        needle = q.strip().casefold() if isinstance(q, str) and q.strip() else None
        result = []
        for record in records:
            if department is not None and record.get("department") != department:
                continue
            if status is not None and _public_status(record) != status:
                continue
            if needle is not None and needle not in _search_text(record):
                continue
            result.append(record)
        result.sort(key=lambda item: (item.get("seq", 0), item.get("attempt", 0)))
        return result

    def _attempt_records(self, run_id: str) -> dict[str, dict[str, Any]]:
        events = self.store.list_events(run_id)
        if not events:
            raise RunNotFoundError(run_id)
        records: dict[str, dict[str, Any]] = {}
        contexts: dict[str, Event] = {}
        activation_rounds: dict[str, Any] = {}
        for event in events:
            payload = event.payload or {}
            if event.type == EventType.DEPARTMENT_ACTIVATED and payload.get("activation_id"):
                activation_rounds[str(payload["activation_id"])] = payload.get("cycle")
            elif event.type == EventType.CONTEXT_ASSEMBLED and payload.get("purpose") in {"work", "compaction"}:
                attempt_id = _attempt_id_for(payload, event.role)
                contexts[attempt_id] = event
                record = records.setdefault(attempt_id, _new_attempt(attempt_id, event, payload))
                _merge_context(record, event, payload)
            elif event.type == EventType.MODEL_REQUESTED:
                attempt_id = _attempt_id_for(payload, event.role)
                record = records.setdefault(attempt_id, _new_attempt(attempt_id, event, payload))
                _merge_started(record, event, payload)
            elif event.type == EventType.MODEL_REQUEST_SERIALIZED:
                attempt_id = _attempt_id_for(payload, event.role)
                record = records.setdefault(attempt_id, _new_attempt(attempt_id, event, payload))
                record["sdk_request_ref"] = payload.get("request_ref")
                record["request_serialized_event_id"] = event.event_id
                record["request_digest"] = payload.get("request_digest")
            elif event.type in {EventType.MODEL_ATTEMPT_FINISHED, EventType.MODEL_ATTEMPT_FAILED}:
                attempt_id = _attempt_id_for(payload, event.role)
                record = records.setdefault(attempt_id, _new_attempt(attempt_id, event, payload))
                _merge_finished(record, event, payload)
            elif event.type == EventType.MODEL_RETRY_SCHEDULED:
                attempt_id = _attempt_id_for(payload, event.role)
                record = records.setdefault(attempt_id, _new_attempt(attempt_id, event, payload))
                record["retry_scheduled_event_id"] = event.event_id
                record["retry_delay_sec"] = payload.get("delay_sec")

        for record in records.values():
            context = contexts.get(record["id"])
            if context is not None:
                record["context_event_id"] = context.event_id
                record["context"] = context.payload
            record["usage"] = self._attempt_usage(run_id, record)
            record["work_round"] = activation_rounds.get(str(record.get("activation_id")))
            record.pop("context", None)
        counts: dict[str, int] = defaultdict(int)
        for record in records.values():
            if record.get("sent"):
                counts[str(record.get("logical_call_id"))] += 1
        for record in records.values():
            record["attempt_count"] = counts[str(record.get("logical_call_id"))]
        return records

    def _attempt_usage(self, run_id: str, record: dict[str, Any]) -> dict[str, Any]:
        raw = self._artifact_json(run_id, record.get("raw_usage_ref"))
        if isinstance(raw, dict) and isinstance(raw.get("usage"), dict):
            raw = raw["usage"]
        summary = record.get("usage_summary")
        duration = record.get("duration_ms")
        values: dict[str, Any] = {field: None for field in USAGE_FIELDS}
        currency = None
        cost_source = None
        if isinstance(raw, dict):
            values["input_tokens"] = _count_value(raw.get("input_tokens"))
            details = raw.get("input_tokens_details")
            if isinstance(details, dict):
                values["cache_read_tokens"] = _count_value(details.get("cached_tokens"))
                values["cache_write_tokens"] = _count_value(
                    details.get("cache_write_tokens")
                    if "cache_write_tokens" in details else details.get("cache_write")
                )
            values["cache_write_tokens"] = values["cache_write_tokens"] if values["cache_write_tokens"] is not None else _count_value(raw.get("cache_write_tokens"))
            values["output_tokens"] = _count_value(raw.get("output_tokens"))
            values["total_tokens"] = _count_value(raw.get("total_tokens"))
            values["cost"] = _cost_value(raw.get("cost"))
            currency = raw.get("currency") or raw.get("cost_currency")
            cost_source = raw.get("cost_source") or ("provider" if values["cost"] is not None else None)
            if values["cost"] is not None and not isinstance(currency, str):
                values["cost"] = None
        if raw is None and isinstance(summary, dict):
            # Persisted normalized summaries are used only for fields absent
            # from the raw provider usage object.
            for field in USAGE_FIELDS:
                if values[field] is None and summary.get(field) is not None:
                    values[field] = _cost_value(summary[field]) if field == "cost" else (
                        _count_value(summary[field]) if field != "latency_ms" else _count_value(summary[field])
                    )
            currency = summary.get("currency")
            cost_source = summary.get("cost_source")
            if values["cost"] is not None and not isinstance(currency, str):
                values["cost"] = None
        values["latency_ms"] = _count_value(duration)
        return {
            **values,
            "currency": currency if isinstance(currency, str) and currency else None,
            "cost_source": cost_source if isinstance(cost_source, str) and cost_source else None,
            "reported": any(values[field] is not None for field in (
                "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "total_tokens", "cost",
            )),
            "coverage": {
                field: "reported" if values[field] is not None else "missing"
                for field in USAGE_FIELDS
            },
        }

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
        return {
            "event_id": event.event_id,
            "seq": event.seq,
            "manifest": payload,
            "request": request,
            "parts": parts,
            "parts_ref": parts_ref,
            "source_event_ids": [event.event_id],
        }

    def _artifact_json(self, run_id: str, ref: Any) -> Any:
        if not isinstance(ref, dict):
            return None
        try:
            raw = self.artifacts.get_for_run(run_id, ArtifactRef(**ref))
            return json.loads(raw)
        except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

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

    def _message_text(self, run_id: str, payload: dict[str, Any], event_type: str) -> str:
        key = "message_ref" if event_type == EventType.MODEL_MESSAGE else "input_ref"
        item = self._artifact_json(run_id, payload.get(key))
        if isinstance(item, dict):
            content = item.get("content")
            if isinstance(content, str):
                if event_type == EventType.DEPARTMENT_INPUT:
                    return _work_description(content)
                return content
            if isinstance(content, list):
                text = "\n".join(
                    str(part.get("text", "")) for part in content
                    if isinstance(part, dict) and part.get("text") is not None
                )
                if text:
                    return text
            item_type = item.get("type")
            if item_type == "function_call":
                name = item.get("name") or "unknown tool"
                arguments = item.get("arguments")
                return f"工具调用：{name} · 参数 {_short_text(arguments)}"
            if item_type == "reasoning":
                return "模型返回 reasoning item，SDK 未提供可显示文本"
            if event_type == EventType.MODEL_MESSAGE:
                return f"模型返回 {item_type or '非文本 item'}，没有可显示文本"
        return str(payload.get("summary") or "")


def list_model_attempts(store: EventStore, artifacts: ArtifactStore, run_id: str, **filters: Any) -> dict[str, Any]:
    return ObservabilityQuery(store, artifacts).list_model_attempts(run_id, **filters)


def model_attempt_detail(store: EventStore, artifacts: ArtifactStore, run_id: str, attempt_id: str) -> dict[str, Any]:
    return ObservabilityQuery(store, artifacts).model_attempt_detail(run_id, attempt_id)


def model_usage(store: EventStore, artifacts: ArtifactStore, run_id: str, **filters: Any) -> dict[str, Any]:
    return ObservabilityQuery(store, artifacts).model_usage(run_id, **filters)


def department_view(store: EventStore, artifacts: ArtifactStore, run_id: str, department: str) -> dict[str, Any]:
    return ObservabilityQuery(store, artifacts).department(run_id, department)


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
        "status": _public_status(record),
        "stage": record.get("status"),
        "prepared_at": record.get("prepared_at"),
        "started_at": record.get("started_at"),
        "finished_at": record.get("finished_at"),
        "duration_ms": record.get("duration_ms"),
        "usage": record.get("usage"),
        "observed_scope": record.get("collection_scope"),
    }


def _public_status(record: dict[str, Any]) -> str:
    status = record.get("status")
    return "success" if status == "completed" else "running" if status in {"prepared", "requesting"} else "failed"


def _department_provider(binding: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(binding, dict):
        return None
    return {
        "provider": binding.get("provider_name") or binding.get("provider_id"),
        "model": binding.get("model"),
        "protocol": binding.get("protocol"),
        "base_url": binding.get("base_url"),
        "context_window": binding.get("context_window"),
        "max_output_tokens": binding.get("max_output_tokens"),
        "temperature": None,
        "snapshot_id": binding.get("snapshot_id"),
    }


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
        "department": event.role or payload.get("department"),
        "purpose": purpose,
        "prompt_version": payload.get("prompt_version"),
        "requested_provider": payload.get("requested_provider"),
        "requested_model": payload.get("requested_model"),
        "actual_provider": None,
        "actual_model": None,
        "status": "prepared",
        "sent": False,
        "prepared_at": event.created_at if event.type == EventType.CONTEXT_ASSEMBLED else None,
        "started_at": None,
        "finished_at": None,
        "duration_ms": None,
        "seq": event.seq,
        "sdk_request_ref": None,
        "response_ref": None,
        "stream_events_ref": None,
        "stream_event_count": 0,
        "raw_usage_ref": None,
        "usage_summary": None,
        "collection_scope": _collection_scope(),
    }


def _merge_context(record: dict[str, Any], event: Event, payload: dict[str, Any]) -> None:
    record.update({
        "context_event_id": event.event_id,
        "prepared_at": event.created_at,
        "seq": min(record.get("seq", event.seq), event.seq),
        "requested_provider": payload.get("requested_provider", record.get("requested_provider")),
        "requested_model": payload.get("requested_model", record.get("requested_model")),
        "prompt_version": payload.get("prompt_version", record.get("prompt_version")),
    })


def _merge_started(record: dict[str, Any], event: Event, payload: dict[str, Any]) -> None:
    record.update({
        "status": "requesting",
        "sent": True,
        "started_at": payload.get("started_at") or event.created_at,
        "seq": min(record.get("seq", event.seq), event.seq),
        "requested_provider": payload.get("requested_provider", record.get("requested_provider")),
        "requested_model": payload.get("requested_model", record.get("requested_model")),
        "actual_provider": payload.get("actual_provider", record.get("actual_provider")),
        "actual_model": payload.get("actual_model", record.get("actual_model")),
        "started_event_id": event.event_id,
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
        "finished_event_id": event.event_id,
        "actual_provider": (payload.get("actual_provider") or event.provider) if has_response else record.get("actual_provider"),
        "actual_model": actual_model if has_response else record.get("actual_model"),
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


def _same_attempt(event: Event, record: dict[str, Any]) -> bool:
    payload = event.payload or {}
    attempt_id = payload.get("attempt_id")
    if attempt_id and attempt_id == record.get("id"):
        return True
    return (
        payload.get("activation_id") == record.get("activation_id")
        and payload.get("step_id") == record.get("step")
        and payload.get("attempt", 1) == record.get("attempt", 1)
    )


def _event_by_id(events: Iterable[Event], event_id: Any) -> Event | None:
    return next((event for event in events if event.event_id == event_id), None)


def _event_detail(event: Event) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "seq": event.seq,
        "type": event.type,
        "role": event.role,
        "created_at": event.created_at,
        "payload": event.payload,
        "artifact_hashes": event.artifact_hashes,
    }


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
        })
    for item in sdk_events:
        raw = item.get("event") if isinstance(item.get("event"), dict) else item
        result.append({
            "event_id": None,
            "time": None,
            "type": raw.get("type"),
            "summary": raw.get("type") or "sdk event",
            "raw": raw,
            "source": "sdk_decoded_stream",
            "sequence": item.get("sequence"),
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


def _work_description(content: str) -> str:
    lines = content.splitlines()
    start = next((index + 1 for index, line in enumerate(lines) if line.strip() == "[current_work]"), None)
    if start is None:
        return _short_text(content, 1200)
    end = next((index for index in range(start, len(lines)) if lines[index].startswith("[")), len(lines))
    description = "\n".join(lines[start:end]).strip()
    return _short_text(description, 1200)


def _short_text(value: Any, limit: int = 240) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = json_dumps(value)
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 3] + "..."


def _material_summary(event: Event) -> str:
    payload = event.payload or {}
    values = {
        EventType.SPEC_ACCEPTED: payload.get("goal") or "已接纳产品要求",
        EventType.PRODUCT_DECISION_ACCEPTED: payload.get("statement") or "已接纳产品决定",
        EventType.CONTRACT_ACCEPTED: "已形成当前有效合同",
        EventType.PLAN_ACCEPTED: payload.get("objective") or "已接纳工程计划",
        EventType.DELIVERY_ACCEPTED: payload.get("summary") or "已接纳工程交付",
        EventType.QA_SUBMITTED: payload.get("rationale") or payload.get("verdict") or "已提交质检结果",
    }
    return _short_text(values.get(event.type) or event.type, 1200)


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


def _handover_title(event: Event) -> str:
    payload = event.payload or {}
    if event.type == EventType.TRANSITION:
        return payload.get("route") or f"{event.state_before} -> {event.state_after}"
    if event.type == EventType.COLLABORATION_REQUESTED:
        return f"{payload.get('requester') or event.role or '未知'} -> {payload.get('recipient') or '未知'}"
    if event.type == EventType.COLLABORATION_RESPONDED:
        return f"协作回应 · {payload.get('request_id') or '未知请求'}"
    if event.type == EventType.COLLABORATION_CLOSED:
        return f"协作关闭 · {payload.get('request_id') or '未知请求'}"
    return event.type


def _handover_body(event: Event) -> str:
    payload = event.payload or {}
    if event.type == EventType.COLLABORATION_REQUESTED:
        return _short_text(payload.get("question") or payload.get("background"), 1200)
    if event.type == EventType.COLLABORATION_RESPONDED:
        return _short_text(payload.get("text"), 1200)
    if event.type == EventType.COLLABORATION_CLOSED:
        return _short_text(payload.get("reason"), 1200)
    if event.type == EventType.TRANSITION:
        return _short_text(payload.get("route"), 1200)
    return _material_summary(event)


def _handover_detail(event: Event) -> str:
    payload = event.payload or {}
    if event.type == EventType.COLLABORATION_REQUESTED:
        return _short_text(payload.get("expected_result") or payload.get("background"), 1200)
    if event.type == EventType.COLLABORATION_RESPONDED:
        return str(payload.get("status") or "")
    if event.type == EventType.COLLABORATION_CLOSED:
        return str(payload.get("status") or "")
    return str(payload.get("reason") or "")


def _search_text(record: dict[str, Any]) -> str:
    return " ".join(str(record.get(key) or "") for key in (
        "id", "logical_call_id", "collaboration_request_id", "context_event_id",
        "department", "purpose", "requested_provider", "requested_model",
        "actual_provider", "actual_model", "provider_response_id", "status",
    )).casefold()


def _limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= MAX_LIMIT:
        raise ValueError(f"limit must be an integer between 1 and {MAX_LIMIT}")
    return value


def _cursor_offset(cursor: str | None, total: int) -> int:
    if cursor in (None, ""):
        return 0
    try:
        offset = int(cursor)
    except (TypeError, ValueError) as exc:
        raise ValueError("cursor must be a non-negative integer") from exc
    if offset < 0 or offset > total:
        raise ValueError("cursor is outside the result set")
    return offset


def _usage_totals(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    items = list(records)
    values: dict[str, Any] = {}
    coverage: dict[str, dict[str, Any]] = {}
    currency: str | None = None
    for field in USAGE_FIELDS:
        known = [item.get("usage", {}).get(field) for item in items if item.get("usage", {}).get(field) is not None]
        if field == "cost" and known:
            currencies = {
                item.get("usage", {}).get("currency")
                for item in items if item.get("usage", {}).get(field) is not None
            }
            if len(currencies) == 1 and None not in currencies:
                currency = next(iter(currencies))
                values[field] = sum(known)
            else:
                values[field] = None
        else:
            values[field] = sum(known) if known else None
        total = len(items)
        values_count = len(known)
        coverage[field] = {
            "reported": values_count,
            "total": total,
            "ratio": values_count / total if total else 0.0,
        }
    statuses = [item.get("status") for item in items]
    return {
        **values,
        "currency": currency,
        "coverage": coverage,
        "attempt_count": len(items),
        "in_progress_count": sum(status in {"prepared", "requesting"} for status in statuses),
        "completed_count": sum(status == "completed" for status in statuses),
        "failed_count": sum(status == "failed" for status in statuses),
        "cancelled_count": sum(status == "cancelled" for status in statuses),
    }


def _has_reported_usage(record: dict[str, Any]) -> bool:
    usage = record.get("usage") or {}
    return any(usage.get(field) is not None for field in (
        "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "total_tokens", "cost",
    ))


def _coverage(reported: int, total: int) -> dict[str, Any]:
    return {
        "reported_attempts": reported,
        "attempts": total,
        "percent": round(reported * 100 / total, 2) if total else 0.0,
    }


def _field_coverage(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    items = list(records)
    total = len(items)
    result = {}
    for field in USAGE_FIELDS:
        reported = sum(item.get("usage", {}).get(field) is not None for item in items)
        result[field] = _coverage(reported, total)
    return result
