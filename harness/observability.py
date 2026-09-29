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
from .views import compaction_coverage, event_card, run_payload


SCHEMA_VERSION = 1
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
ATTEMPT_STATUSES = frozenset({"prepared", "requesting", "completed", "failed", "cancelled"})
STREAM_PROGRESS_EVENT = "model_stream_progress"
USAGE_SOURCES = frozenset({"reported", "missing", "unknown"})
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
        provider: str | None = None,
        requested_model: str | None = None,
        actual_model: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        records = self._filtered_attempts(
            run_id, department=department, status=status, q=q,
            provider=provider, requested_model=requested_model, actual_model=actual_model,
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
        lifecycle_events = [
            event_card(event) for event in events
            if _same_attempt(event, attempt)
            and event.type in {
                EventType.CONTEXT_ASSEMBLED,
                EventType.MODEL_REQUESTED,
                EventType.MODEL_REQUEST_SERIALIZED,
                EventType.MODEL_MESSAGE,
                EventType.MODEL_ATTEMPT_FINISHED,
                EventType.MODEL_ATTEMPT_FAILED,
                EventType.MODEL_RETRY_SCHEDULED,
                STREAM_PROGRESS_EVENT,
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
        return self.attempt_detail(run_id, attempt, records, context_event=context_event,
                                   lifecycle_events=lifecycle_events, tool_events=tool_events)

    def attempt_detail(self, run_id: str, attempt: dict[str, Any], records: dict[str, dict[str, Any]], *,
                       context_event: Event | None = None, lifecycle_events: list[dict[str, Any]] | None = None,
                       tool_events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        # 一次尝试的详情；记录可以由调用方给出（读取模型的调用尝试表按运行给出这个 run 的记录），
        # 事件列表与工具回执只在给出时出现（旧控制台给出，读取模型按引用读取工件）
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

    def export_run(self, run_id: str) -> dict[str, Any]:
        """Return the complete read-only observation bundle for one run."""

        records = self._attempt_records(run_id)
        attempts = [
            self.model_attempt_detail(run_id, item["id"])
            for item in sorted(records.values(), key=lambda value: (value.get("seq", 0), value.get("attempt", 0)))
        ]
        return {
            "run_id": run_id,
            "version": SCHEMA_VERSION,
            "attempts": attempts,
            "usage": self.model_usage(run_id),
            "departments": {department: self.department(run_id, department) for department in DEPARTMENTS},
        }

    def model_usage(
        self,
        run_id: str,
        *,
        department: str | None = None,
        status: str | None = None,
        q: str | None = None,
        provider: str | None = None,
        requested_model: str | None = None,
        actual_model: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        records = self._filtered_attempts(
            run_id, department=department, status=status, q=q,
            provider=provider, requested_model=requested_model, actual_model=actual_model,
        )
        # Usage intentionally uses the complete filtered set. Cursor/limit are
        # accepted for the shared filter contract but never narrow the sum.
        _cursor_offset(cursor, len(records))
        _limit(limit)
        return {"run_id": run_id, **self.usage_summary(
            records, department=department, status=status, q=q,
            provider=provider, requested_model=requested_model, actual_model=actual_model,
        )}

    def attempt_records(
        self,
        run_id: str,
        *,
        department: str | None = None,
        status: str | None = None,
        q: str | None = None,
        provider: str | None = None,
        requested_model: str | None = None,
        actual_model: str | None = None,
    ) -> list[dict[str, Any]]:
        """Complete filtered attempt records for one run, in seq order (project-level callers merge them)."""

        return self._filtered_attempts(
            run_id, department=department, status=status, q=q,
            provider=provider, requested_model=requested_model, actual_model=actual_model,
        )

    @staticmethod
    def public_attempt(record: dict[str, Any]) -> dict[str, Any]:
        return _public_attempt(record)

    def usage_summary(
        self,
        records: list[dict[str, Any]],
        *,
        department: str | None = None,
        status: str | None = None,
        q: str | None = None,
        provider: str | None = None,
        requested_model: str | None = None,
        actual_model: str | None = None,
    ) -> dict[str, Any]:
        """Usage body for an already filtered record set; the same shape serves one run or a whole project."""

        prepared_count = sum(not record.get("sent") for record in records)
        records = [record for record in records if record.get("sent")]
        total = _usage_totals(records, source="reported")
        department_groups: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
        model_groups: dict[tuple[str | None, str | None, str | None], list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            department_groups[record.get("department")].append(record)
            model_groups[(
                record.get("requested_provider"),
                record.get("requested_model"),
                record.get("actual_model"),
            )].append(record)

        def group_payload(label: str, items: list[dict[str, Any]], **identity: Any) -> dict[str, Any]:
            summary = _usage_totals(items, source="reported")
            reported = sum(_has_reported_usage(item) for item in items)
            group_coverage = _coverage(reported, len(items))
            group_coverage["fields"] = _field_coverage(items)
            return {
                "key": label,
                "label": label,
                **identity,
                **{field: summary[field] for field in USAGE_FIELDS},
                "currency": summary.get("currency"),
                "cost_status": summary.get("cost_status"),
                "coverage": group_coverage,
                "running_attempts": sum(_public_status(item) == "running" for item in items),
            }

        department_payload = [
            group_payload(str(department_name or "未知部门"), items, department=department_name)
            for department_name, items in department_groups.items()
        ]
        model_payload = [
            group_payload(
                (
                    f"{provider or '未知 Provider'} · {model}"
                    if model
                    else f"{provider or '未知 Provider'} · {requested or '未知模型'}（请求） · 实际模型未知"
                ),
                items,
                provider=provider,
                model=model,
                requested_model=requested,
            )
            for (provider, requested, model), items in model_groups.items()
        ]
        department_payload.sort(key=lambda item: item["label"])
        model_payload.sort(key=lambda item: item["label"])
        reported = sum(_has_reported_usage(item) for item in records)
        coverage = _coverage(reported, len(records))
        coverage["fields"] = _field_coverage(records)
        return {
            "version": SCHEMA_VERSION,
            "totals": {field: total[field] for field in USAGE_FIELDS},
            "currency": total.get("currency"),
            "cost_status": total.get("cost_status"),
            "coverage": coverage,
            "groups": {"departments": department_payload, "models": model_payload},
            "total_attempts": len(records),
            "prepared_attempts": prepared_count,
            "filters": {
                "department": department,
                "status": status,
                "q": q,
                "provider": provider,
                "requested_model": requested_model,
                "actual_model": actual_model,
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
                if event.type == EventType.MODEL_MESSAGE:
                    attempt = records.get(_attempt_id_for(payload, role))
                    if attempt is not None and attempt.get("status") in {"failed", "cancelled"}:
                        continue
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
                    "seq": event.stream_version,
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
                    "seq": event.stream_version,
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
                        "seq": event.stream_version,
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
                    "seq": event.stream_version,
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
                        "seq": event.stream_version,
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
                "stage": attempt.get("stage", attempt.get("status")),
                "purpose": attempt.get("purpose"),
                "partial_output": attempt.get("partial_output", False),
                "output_item_count": attempt.get("output_item_count", 0),
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

    def _filtered_attempts(
        self,
        run_id: str,
        *,
        department: str | None,
        status: str | None,
        q: str | None,
        provider: str | None = None,
        requested_model: str | None = None,
        actual_model: str | None = None,
    ) -> list[dict[str, Any]]:
        if department is not None and department not in DEPARTMENTS:
            raise ValueError("unknown department")
        if status is not None and status not in {"success", "failed", "cancelled", "running"}:
            raise ValueError("unknown model attempt status")
        records = list(self._attempt_records(run_id).values())
        needle = q.strip().casefold() if isinstance(q, str) and q.strip() else None
        provider_needle = provider.strip() if isinstance(provider, str) and provider.strip() else None
        requested_needle = requested_model.strip() if isinstance(requested_model, str) and requested_model.strip() else None
        actual_needle = actual_model.strip() if isinstance(actual_model, str) and actual_model.strip() else None
        result = []
        for record in records:
            if department is not None and record.get("department") != department:
                continue
            if status is not None and _public_status(record) != status:
                continue
            if provider_needle is not None and provider_needle not in {
                record.get("requested_provider"), record.get("actual_provider"),
            }:
                continue
            if requested_needle is not None and record.get("requested_model") != requested_needle:
                continue
            if actual_needle is not None:
                # 超时/断连等失败拿不到 actual_model 时回退到 requested_model，
                # 按 actual_model 筛选才不会漏掉这些记录；有实际返回的仍只按实际值匹配。
                effective_actual = record.get("actual_model") or record.get("requested_model")
                if effective_actual != actual_needle:
                    continue
            if needle is not None and needle not in search_text(record):
                continue
            result.append(record)
        result.sort(key=lambda item: (item.get("seq", 0), item.get("attempt", 0)))
        return result

    def _attempt_records(self, run_id: str) -> dict[str, dict[str, Any]]:
        events = self.store.list_events(run_id)
        if not events:
            raise RunNotFoundError(run_id)
        fold = AttemptFold(self.artifacts, run_id)
        for event in events:
            fold.merge(event)
        return fold.records()

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


def export_observability(store: EventStore, artifacts: ArtifactStore, run_id: str) -> dict[str, Any]:
    return ObservabilityQuery(store, artifacts).export_run(run_id)


def department_view(store: EventStore, artifacts: ArtifactStore, run_id: str, department: str) -> dict[str, Any]:
    return ObservabilityQuery(store, artifacts).department(run_id, department)


def artifact_json(artifacts: ArtifactStore, run_id: str, ref: Any) -> Any:
    if not isinstance(ref, dict):
        return None
    try:
        raw = artifacts.get_for_run(run_id, ArtifactRef(**ref))
        return json.loads(raw)
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def attempt_usage(artifacts: ArtifactStore, run_id: str, record: dict[str, Any]) -> dict[str, Any]:
    # 一次尝试的用量：上游原文按引用读取，标准化的汇总只补齐原文里没有的字段
    raw = artifact_json(artifacts, run_id, record.get("raw_usage_ref"))
    if isinstance(raw, dict) and isinstance(raw.get("usage"), dict):
        raw = raw["usage"]
    summary = record.get("usage_summary")
    values: dict[str, Any] = {field: None for field in USAGE_FIELDS}
    currency = None
    cost_source = None
    source = "missing"
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
        source = "reported" if _has_usage_values(values) else "missing"
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
        if _has_usage_values(values):
            source = "reported" if summary["reported"] else "unknown"
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

    与整段扫描使用同一套合并规则：merge 一次事件，records() 得到与 ObservabilityQuery._attempt_records 相同的记录。
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
            record = self._record(_attempt_id_for(payload, event.role), event, payload)
            _merge_context(record, event, payload)
        elif event.type == EventType.MODEL_REQUESTED:
            record = self._record(_attempt_id_for(payload, event.role), event, payload)
            _merge_started(record, event, payload)
        elif event.type == EventType.MODEL_REQUEST_SERIALIZED:
            record = self._record(_attempt_id_for(payload, event.role), event, payload)
            record["sdk_request_ref"] = payload.get("request_ref")
            record["request_serialized_event_id"] = event.event_id
            record["request_digest"] = payload.get("request_digest")
        elif event.type in {EventType.MODEL_ATTEMPT_FINISHED, EventType.MODEL_ATTEMPT_FAILED}:
            record = self._record(_attempt_id_for(payload, event.role), event, payload)
            _merge_finished(record, event, payload)
        elif event.type == EventType.MODEL_RETRY_SCHEDULED:
            record = self._record(_attempt_id_for(payload, event.role), event, payload)
            record["retry_scheduled_event_id"] = event.event_id
            record["retry_delay_sec"] = payload.get("delay_sec")
        elif event.type == EventType.MODEL_MESSAGE:
            self.output_item_counts[_attempt_id_for(payload, event.role)] += 1
        elif event.type == STREAM_PROGRESS_EVENT:
            attempt_id = _attempt_id_for(payload, event.role)
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


def _department_provider(binding: dict[str, Any] | None) -> dict[str, Any] | None:
    # 部门最近一次请求解析出的调用目标：字段取自请求事件的载荷
    if not isinstance(binding, dict):
        return None
    return {
        "provider": binding.get("provider_name") or binding.get("provider_config_id"),
        "model": binding.get("requested_model"),
        "protocol": binding.get("protocol"),
        "base_url": binding.get("base_url"),
        "context_window": binding.get("context_window"),
        "max_output_tokens": binding.get("configured_max_output_tokens"),
        "temperature": None,
        "selection_source": binding.get("selection_source"),
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
        "seq": event.stream_version,
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


def search_text(record: dict[str, Any]) -> str:
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


def _has_usage_values(values: dict[str, Any]) -> bool:
    return any(values.get(field) is not None for field in USAGE_FIELDS if field != "latency_ms")


def _usage_field_state(field: str, value: Any, source: str) -> str:
    if value is None:
        return "missing"
    if field == "latency_ms":
        return "measured"
    return source if source in {"reported", "unknown"} else "unknown"


def _usage_source(usage: Any) -> str:
    if not isinstance(usage, dict):
        return "missing"
    source = usage.get("source")
    if source in USAGE_SOURCES:
        return source
    if usage.get("reported") is True:
        return "reported"
    if usage.get("reported") is False and _has_usage_values(usage):
        return "unknown"
    return "missing" if not _has_usage_values(usage) else "unknown"


def _usage_totals(
    records: Iterable[dict[str, Any]],
    *,
    source: str | None = None,
) -> dict[str, Any]:
    items = list(records)
    selected = [item for item in items if source is None or _usage_source(item.get("usage")) == source]
    values: dict[str, Any] = {}
    coverage: dict[str, dict[str, Any]] = {}
    currency: str | None = None
    cost_status = "missing"
    for field in USAGE_FIELDS:
        candidates = items if field == "latency_ms" else selected
        known = [item.get("usage", {}).get(field) for item in candidates if item.get("usage", {}).get(field) is not None]
        if field == "cost":
            if not known:
                values[field] = None
                cost_status = "missing"
            else:
                currencies = {
                    item.get("usage", {}).get("currency")
                    for item in candidates if item.get("usage", {}).get(field) is not None
                }
                if len(currencies) == 1 and None not in currencies:
                    currency = next(iter(currencies))
                    values[field] = sum(known)
                    cost_status = "reported"
                else:
                    values[field] = None
                    currency = None
                    cost_status = "mixed_currency"
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
        "cost_status": cost_status,
        "coverage": coverage,
        "attempt_count": len(items),
        "in_progress_count": sum(status in {"prepared", "requesting"} for status in statuses),
        "completed_count": sum(status == "completed" for status in statuses),
        "failed_count": sum(status == "failed" for status in statuses),
        "cancelled_count": sum(status == "cancelled" for status in statuses),
    }


def _has_reported_usage(record: dict[str, Any]) -> bool:
    usage = record.get("usage") or {}
    return _usage_source(usage) == "reported" and _has_usage_values(usage)


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
        reported = sum(
            _usage_source(item.get("usage")) == "reported"
            and item.get("usage", {}).get(field) is not None
            for item in items
        )
        result[field] = _coverage(reported, total)
    return result
