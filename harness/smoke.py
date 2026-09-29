"""真实 provider 三部门 smoke。读取环境变量，不读取 provider.md，不用 fake 冒充成功。"""

from __future__ import annotations

import asyncio
import json
import math
import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .adjudication import offered_tools
from .app.application import Application
from .app.contracts import Rejected
from .app.project_and_work_item_commands import WorkItemCreate
from .app.project_commands import ProjectCreate
from .artifacts import ArtifactStore
from .assembly import PENDING_GUIDANCE, ContextAssembly, StepFrame, model_limits, pending_guidance
from .compaction import SUMMARY_PREFACE, SUMMARY_RULES
from .contracts import current_contract_hash, current_plan_hash
from .definitions import DEFINITIONS
from .engine import tool_call_required_text
from .event_store import EventStore, run_stream
from .git_audit import verify_git_history
from .models import (ArtifactRef, EventType, RunProjection, canonical_hash, department_for_phase, estimate_tokens,
                     json_dumps)
from .projection import apply_event, project_run
from .providers import ProviderFacade
from .public_tree import capture_public_tree, materialize_tree
from .runtime import LoopSystem
from .tree_archive import load_tree


DEFAULT_DIR = Path(".yudao") / "native-validation"
DEFAULT_PROVIDER_CONFIG = Path(".yudao") / "providers.json"

MODEL_ATTEMPT_FAILED = EventType.MODEL_ATTEMPT_FAILED
MODEL_RETRY_SCHEDULED = EventType.MODEL_RETRY_SCHEDULED
RETRY_EVENTS = frozenset({MODEL_ATTEMPT_FAILED, MODEL_RETRY_SCHEDULED})

HAPPY_TASK = (
    "Implement a local Python CLI at src/echo.py. "
    "Running `python src/echo.py hello` must print hello and exit 0. "
    "Do not add network access, extra files, or configuration. "
    "Engineering must write the file and have the host run a check. "
    "Quality must independently have the host run a check before release."
)

COLLABORATION_TASK = (
    "Implement a local Python CLI at src/echo.py that prints its first argument. "
    "The product spec must leave unspecified whether arguments starting with '-' "
    "are unknown flags or ordinary text. "
    "Before the initial product spec, Product must consult Engineering about feasibility using submit_request. "
    "Engineering must answer with submit_response and return to Product's initial requirements work. "
    "Later Engineering must request a revise_requirements action from Product for the flag decision. "
    "Product must publish a product decision or a revised product spec, then submit a completed response citing its accepted event. "
    "Quality independently checks the delivered CLI."
)


def run_smoke(
    data_dir: str | Path = DEFAULT_DIR,
    *,
    provider_config: str | Path | None = None,
    dotenv_path: str | Path | None = None,
    scenarios: list[str] | None = None,
) -> dict[str, Any]:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    selected = scenarios or ["happy", "collaboration"]
    if any(name not in {"happy", "collaboration"} for name in selected):
        raise ValueError("unknown smoke scenario")
    config_path = Path(provider_config) if provider_config is not None else DEFAULT_PROVIDER_CONFIG
    report: dict[str, Any] = {
        "provider_config": str(config_path),
        "available": False,
        "scenarios": {},
    }
    # 短命 CLI 执行前读取一致版本，缺可用配置明确失败，不偷换 Fake
    facade = ProviderFacade()
    facade.configure_paths(config_path, None if dotenv_path is None else Path(dotenv_path))
    facade.reload()
    system = LoopSystem(data_dir, facade=facade)
    status = system.provider_status()
    report.update({
        "available": bool(status.get("available")),
        "provider_bindings": status.get("departments", {}),
        "provider": None,
        "model": None,
        "adapter": "directory",
    })
    if not report["available"]:
        report["error"] = status.get("message", "provider unavailable")
        report["stop_reason"] = status.get("reason", "provider_unavailable")
        _write_report(data_dir, report)
        return report
    for name in selected:
        report["scenarios"][name] = _run_scenario(system, name)
    _write_report(data_dir, report)
    return report


def _run_scenario(system: LoopSystem, name: str) -> dict[str, Any]:
    # smoke 经应用层的命令新建项目与事项（应用层与接口层设计说明第 7.4 节）：
    # run 结束时由流程编排结算（采纳）
    task = HAPPY_TASK if name == "happy" else COLLABORATION_TASK
    application = Application(system)
    try:
        _work_item_id, run_id = asyncio.run(_create_and_run(application, task))
    except _ScenarioFailed as failure:
        try:
            failed_projection = system.project(failure.run_id)
        except Exception:  # noqa: BLE001 - preserve the original smoke failure
            failed_projection = None
        return {
            "run_id": failure.run_id,
            "scenario": name,
            "phase": "FAILED",
            "stop_reason": "provider_error",
            "error": str(failure.cause),
            "fake_used": _fake_used(failed_projection),
        }
    return summarize_run(system, run_id, scenario=name)


class _ScenarioFailed(Exception):
    # 场景的 run 没有正常结束：带上 run_id 以便报告里记录失败的一次
    def __init__(self, run_id: str, cause: Exception) -> None:
        super().__init__(str(cause))
        self.run_id = run_id
        self.cause = cause


async def _create_and_run(application: Application, task: str) -> tuple[str, str]:
    created_project = await application.command(
        "project.create", ProjectCreate(command_id=str(uuid.uuid4()), name="Smoke 项目", goal=task),
        actor="user:local")
    if isinstance(created_project, Rejected):
        raise RuntimeError(f"project.create rejected: {created_project.reason} {created_project.message}")
    created = await application.command(
        "work_item.create", WorkItemCreate(command_id=str(uuid.uuid4()), project_id=created_project.refs.project_id,
                                           text=task), actor="user:local")
    if isinstance(created, Rejected):
        raise RuntimeError(f"work_item.create rejected: {created.reason} {created.message}")
    run_id = created.refs.run_id
    try:
        await application.system.orchestrator.work_item_execution(run_id)
    except Exception as exc:  # noqa: BLE001 - smoke must record provider failure
        raise _ScenarioFailed(run_id, exc) from exc
    return created.refs.work_item_id, run_id


def summarize_run(system: LoopSystem, run_id: str, *, scenario: str) -> dict[str, Any]:
    projection = system.project(run_id)
    replayed = project_run(system.store, run_id)
    workspace = system.workspace(run_id)
    receipts = [_receipt(item) for item in workspace.receipts()]
    tool_calls = _tool_events(system.store, run_id)
    isolation = isolation_fields(system.store, system.artifacts, run_id)
    receipts_ok, receipt_notes = _receipt_evidence(system, run_id, receipts)
    return {
        "run_id": run_id,
        "scenario": scenario,
        "phase": projection.phase,
        "outcome": projection.outcome,
        "stop_reason": projection.stop_reason,
        "error": projection.error,
        # 运行停下等待用户回答时，未回答的请求说明原因（例如模型引用无法使用时的待恢复）
        "decisions": [{"kind": decision.kind, "status": decision.status,
                       "description": decision.request["description"]}
                      for decision in system.writes.read(run_stream(run_id)).decisions.values()],
        "adapter": projection.adapter,
        "provider": projection.provider,
        "model": projection.model,
        "provider_bindings": projection.provider_bindings,
        "model_requests": projection.model_requests,
        "requested_provider": projection.requested_provider,
        "requested_model": projection.requested_model,
        "actual_provider": projection.actual_provider,
        "actual_model": projection.actual_model,
        "route": list(projection.transitions),
        "request_count": projection.request_count,
        "collaboration_requests": [asdict(item) for item in projection.requests],
        "collaboration_responses": [asdict(item) for item in projection.responses],
        "collaboration_audit": _collaboration_evidence(system, run_id),
        "rework_count": projection.rework_count,
        "cycle_count": projection.cycle_count,
        "token_used": projection.token_used,
        "tool_calls": tool_calls,
        "check_receipts": receipts,
        "check_receipts_verified": receipts_ok,
        "check_receipt_notes": receipt_notes,
        "delivery_archive": _archive_evidence(system, run_id),
        "git_audit": _git_evidence(system, run_id),
        "replay_consistent": replayed.canonical_state() == projection.canonical_state(),
        **isolation,
        "fake_used": _fake_used(projection),
        "product_spec_hash": None if projection.product_spec is None else projection.product_spec.content_hash,
        "delivery_files": [] if projection.delivery_spec is None else list(projection.delivery_spec.files),
        "qa_verdict": None if projection.last_review is None else projection.last_review.verdict,
    }


def _fake_used(projection: RunProjection | None) -> bool:
    """判断任务是否使用了明确的 fake 协议或测试适配器。"""

    if projection is None:
        return False
    if projection.adapter == "fake":
        return True
    if any(item.get("protocol") == "fake" for item in projection.provider_bindings.values()):
        return True
    return any(
        item.get("protocol") == "fake" or item.get("requested_protocol") == "fake"
        for item in projection.model_requests
    )


def _git_evidence(system: LoopSystem, run_id: str) -> dict[str, Any]:
    try:
        history = verify_git_history(system.git_versions, system.artifacts, system.store.list_events(run_id))
        return {"status": "verified", "version_count": len(history), "versions": history, "notes": []}
    except (ValueError, OSError, KeyError, TypeError, AttributeError):
        return {"status": "unverified", "version_count": 0,
                "notes": ["Git history or its accepted event materials could not be verified"]}


def _tool_events(store: EventStore, run_id: str) -> list[dict[str, Any]]:
    items = []
    for event in store.list_events(run_id):
        if event.type != EventType.TOOL_CALLED:
            continue
        payload = event.payload or {}
        if payload.get("name") == "provider_usage":
            continue
        items.append(
            {
                "department": event.role,
                "name": payload.get("name"),
                "ok": payload.get("ok"),
                "exit_code": payload.get("exit_code"),
                "snapshot_hash": payload.get("snapshot_hash"),
                "executor": payload.get("executor"),
                "args": payload.get("args"),
            }
        )
    return items


def isolation_fields(store: EventStore, artifacts: ArtifactStore, run_id: str) -> dict[str, Any]:
    manifest_ok, manifest_notes = _manifest_boundary(store, run_id)
    audit = _model_input_audit(store, artifacts, run_id)
    isolated = manifest_ok and audit["status"] == "verified"
    return {
        "manifest_boundary": manifest_ok,
        "manifest_boundary_notes": manifest_notes,
        "model_input_audit": audit,
        "context_isolated": isolated,
        "context_isolation_notes": manifest_notes + audit["notes"],
    }


def _read_artifact(artifacts: ArtifactStore, run_id: str, ref: dict[str, Any]) -> Any:
    return json.loads(artifacts.get_for_run(run_id, ArtifactRef(**ref)))


def _collaboration_evidence(system: LoopSystem, run_id: str) -> dict[str, Any]:
    projection = system.project(run_id)
    events = {event.event_id: event for event in system.store.list_events(run_id)}
    responses = {item.request_id: item for item in projection.responses}
    notes, directions = [], []
    pre_spec_consultation = requirements_action = False
    for request in projection.requests:
        source = events.get(request.created_event_id)
        response = responses.get(request.id)
        result = events.get(response.created_event_id) if response else None
        if (source is None or source.type != EventType.COLLABORATION_REQUESTED
                or source.role != request.requester or source.run_id != run_id
                or response is None or result is None or result.type != EventType.COLLABORATION_RESPONDED
                or result.role != request.recipient or result.run_id != run_id
                or result.stream_version <= source.stream_version
                or result.payload.get("request_id") != request.id):
            notes.append(f"request {request.id}: missing or unrelated recipient response")
            continue
        directions.append(f"{request.requester}->{request.recipient}")
        results = [events.get(event_id) for event_id in response.result_event_ids]
        if any(event is None or event.run_id != run_id or event.role != request.recipient
               or event.payload.get("request_id") != request.id
               or not source.stream_version < event.stream_version < result.stream_version
               for event in results):
            notes.append(f"request {request.id}: result is not bound to its recipient work")
            continue
        if (request.requester == "product" and request.recipient == "engineering"
                and request.request_type == "consultation" and response.status == "answered"
                and not any(event.type == EventType.SPEC_ACCEPTED and event.stream_version < source.stream_version
                            for event in events.values())):
            pre_spec_consultation = True
        if (request.requester == "engineering" and request.recipient == "product"
                and request.action == "revise_requirements" and response.status == "completed"
                and any(event.type in {EventType.SPEC_ACCEPTED, EventType.PRODUCT_DECISION_ACCEPTED} for event in results)):
            requirements_action = True
    if projection.pending_request is not None:
        notes.append("a collaboration request is still pending")
    return {"status": "unverified" if notes else "verified", "directions": directions,
            "pre_spec_consultation": pre_spec_consultation, "requirements_action": requirements_action, "notes": notes}


def _archive_evidence(system: LoopSystem, run_id: str) -> dict[str, Any]:
    delivery = system.project(run_id).delivery_spec
    if delivery is None:
        return {"status": "unverified", "notes": ["no accepted delivery archive"]}
    try:
        tree = load_tree(system.artifacts, run_id, delivery.tree_ref)
        if tree.digest != delivery.code_tree_digest:
            raise ValueError("archived tree does not match its accepted delivery")
        with tempfile.TemporaryDirectory(prefix="yudao-archive-audit-") as folder:
            restored = materialize_tree(tree, Path(folder) / "workspace")
            if capture_public_tree(restored).digest != delivery.code_tree_digest:
                raise ValueError("restored tree does not match its accepted delivery")
        return {"status": "verified", "tree_digest": tree.digest, "manifest_ref": asdict(delivery.tree_ref),
                "files": len(tree.files), "directories": len(tree.directories), "notes": []}
    except (KeyError, TypeError, ValueError, OSError) as exc:
        return {"status": "unverified", "notes": [str(exc)]}


def _summary_material(record: dict[str, Any]) -> dict[str, Any]:
    material = dict(record["item"])
    encrypted = material.get("encrypted_content") if material.get("type") == "reasoning" else None
    if isinstance(encrypted, str) and encrypted:
        material["encrypted_content"] = {
            "source_event_id": record["event_id"], "field": "encrypted_content",
            "length": len(encrypted), "digest": canonical_hash(encrypted),
        }
    return material


def _coverage(records: list[dict[str, Any]], index: int, offset: int) -> dict[str, Any]:
    pending: set[str] = set()
    for record in records[:index]:
        item = record["item"]
        if item.get("type") == "function_call":
            pending.add(item["call_id"])
        elif item.get("type") == "function_call_output":
            pending.discard(item["call_id"])
    same_step = index > 0 and index < len(records) and all(
        records[index - 1][key] == records[index][key] for key in ("activation_id", "step_id")
    )
    partial = None if not offset else {
        "event_id": records[index]["event_id"], "item_digest": records[index]["item_digest"],
        "end_offset": offset, "text_digest": canonical_hash(json_dumps(_summary_material(records[index]))[:offset]),
    }
    return {
        "summary": "",
        "covered_through_event_id": records[index - 1]["event_id"] if index else None,
        "covered_digest": canonical_hash({
            "records": [{"event_id": item["event_id"], "item_digest": item["item_digest"]} for item in records[:index]],
            "partial": partial,
        }),
        "partial_event_id": records[index]["event_id"] if offset else None,
        "partial_offset": offset,
        "boundary": not offset and not pending and not same_step,
    }


def _checkpoint_cursor(records: list[dict[str, Any]], previous: dict[str, Any] | None) -> tuple[int, int]:
    if previous is None:
        return 0, 0
    checkpoint = previous["checkpoint"]
    identities = [item["event_id"] for item in records]
    covered = checkpoint["covered_through_event_id"]
    index = identities.index(covered) + 1 if covered is not None else 0
    offset = checkpoint["partial_offset"]
    if type(offset) is not int or offset < 0:
        raise ValueError("invalid summary coverage offset")
    if offset and (index >= len(records) or not offset < len(json_dumps(_summary_material(records[index])))):
        raise ValueError("summary coverage offset exceeds its source")
    if {**checkpoint, "summary": ""} != _coverage(records, index, offset):
        raise ValueError("summary coverage does not match this department's original history")
    return index, offset


def _audit_compaction_input(request: dict[str, Any], records: list[dict[str, Any]],
                            previous: dict[str, Any] | None) -> dict[str, Any]:
    items = request["input"]
    if (len(items) != 3 or items[0].get("role") != "developer" or items[1].get("role") != "developer"
            or items[2].get("role") != "user"):
        raise ValueError("compaction input must contain summary instructions, pinned context and source material")
    rules = items[0].get("content")
    if not isinstance(rules, str) or not rules.startswith(SUMMARY_PREFACE + SUMMARY_RULES):
        raise ValueError("compaction input does not start with the summarizer instructions")
    material = json.loads(items[2]["content"])
    prior_summary = previous["checkpoint"]["summary"] if previous else None
    if set(material) != {"previous_summary", "source_fragments"} or material["previous_summary"] != prior_summary:
        raise ValueError("compaction input uses an unrelated previous summary")
    fragments = material["source_fragments"]
    if not isinstance(fragments, list) or not fragments:
        raise ValueError("compaction input has no source fragments")
    index, offset = _checkpoint_cursor(records, previous)
    source_refs = []
    for fragment in fragments:
        if index >= len(records):
            raise ValueError("compaction source exceeds this department's recorded history")
        record = records[index]
        material_item = _summary_material(record)
        text = json_dumps(material_item)
        end = fragment.get("end_offset")
        if type(end) is not int or not offset < end <= len(text):
            raise ValueError("compaction source fragment does not advance its coverage")
        expected = {
            "event_id": record["event_id"], "seq": record["seq"], "activation_id": record["activation_id"],
            "step_id": record["step_id"], "item_digest": record["item_digest"], "start_offset": offset,
            "material_digest": canonical_hash(material_item),
            "end_offset": end, "total_chars": len(text), "text_digest": canonical_hash(text[offset:end]),
            "text": text[offset:end],
        }
        if fragment != expected:
            raise ValueError("compaction source fragment differs from this department's original event")
        source_refs.append({key: value for key, value in expected.items() if key != "text"})
        offset = end
        if offset == len(text):
            index += 1
            offset = 0
    return {
        "request": request, "source_refs": source_refs, "next_checkpoint": _coverage(records, index, offset),
        "previous_summary_digest": canonical_hash(prior_summary) if prior_summary is not None else None,
        "outputs": [],
    }


def _audit_compaction_output(event: Any, artifacts: ArtifactStore, audit: dict[str, Any],
                             previous: dict[str, Any] | None) -> dict[str, Any]:
    payload = event.payload
    if payload.get("run_id") != event.run_id or payload.get("department") != event.role:
        raise ValueError("summary is not bound to its task and department")
    if payload.get("previous_compaction_event_id") != (previous or {}).get("event_id"):
        raise ValueError("summary does not extend the previous department checkpoint")
    for field in ("summary_ref", "plan_ref"):
        if payload[field]["content_hash"] not in event.artifact_hashes:
            raise ValueError("summary or plan artifact is not bound to its event")
    summary = artifacts.get_for_run(event.run_id, ArtifactRef(**payload["summary_ref"])).decode("utf-8")
    plan = _read_artifact(artifacts, event.run_id, payload["plan_ref"])
    limit = plan["summary_token_limit"]
    if ((payload.get("effective_context_window") is not None
         and payload.get("effective_context_window") != audit["effective_context_window"])
            or payload.get("configured_max_output_tokens") != audit["configured_max_output_tokens"]
            or payload.get("context_window") != audit["target_context_window"]
            or plan["input_items"] != audit["request"]["input"] or plan["source_refs"] != audit["source_refs"]
            or payload["source_refs"] != audit["source_refs"] or plan["next_checkpoint"] != audit["next_checkpoint"]
            or plan["previous_summary_digest"] != audit["previous_summary_digest"]
            or plan["max_output_tokens"] != audit["effective_max_output_tokens"]
            or plan.get("input_token_estimate") != estimate_tokens(json_dumps({
                "input": plan["input_items"],
                "tools": [],
            }))
            or payload["max_output_tokens"] != plan["max_output_tokens"]
            or type(limit) is not int or not 0 < limit <= plan["max_output_tokens"]
            or payload["summary_token_limit"] != limit):
        raise ValueError("recorded compaction plan differs from its audited input and coverage")
    paragraphs = []
    for item in audit["outputs"]:
        if item.get("type") == "reasoning":
            continue
        if item.get("type") != "message" or item.get("role") != "assistant" or item.get("status") not in {None, "completed"}:
            raise ValueError("compaction output is not a completed assistant summary")
        for part in item.get("content") or []:
            if part.get("type") != "output_text" or not isinstance(part.get("text"), str):
                raise ValueError("compaction output contains non-summary content")
            paragraphs.append(part["text"])
    if not summary or summary != "\n".join(paragraphs).strip() or (len(summary) + 3) // 4 > limit:
        raise ValueError("summary artifact does not match the bounded model output")
    expected = {**audit["next_checkpoint"], "summary": summary}
    if payload["checkpoint"] != expected:
        raise ValueError("summary checkpoint coverage differs from its original sources")
    return expected


def _expected_guidance_only(projection: RunProjection, department: str) -> bool:
    """部门因待处理指导被提前安排（不是该阶段的正常部门）时只拿只读与回应工具；产品照常处理。"""

    if projection.pending_request is not None or department == "product":
        return False
    pending = [item for item in projection.department_guidance if item.status in PENDING_GUIDANCE]
    return bool(pending) and pending[0].department == department and department != department_for_phase(projection.phase)


def _assembly_snapshot_hash(events: list[Any], index: int) -> str:
    """装配所用的工作区快照记录在 context_assembled；同一模型步骤的其他事件与它共用同一份快照。"""

    event = events[index]
    if event.type == EventType.CONTEXT_ASSEMBLED:
        source = event
    else:
        payload = event.payload or {}
        source = next((item for item in events
                       if item.type == EventType.CONTEXT_ASSEMBLED
                       and item.payload.get("activation_id") == payload.get("activation_id")
                       and item.payload.get("step_id") == payload.get("step_id")), None)
        if source is None:
            raise ValueError("model step has no assembled context recording its workspace snapshot")
    snapshot = source.payload.get("snapshot_hash")
    if not isinstance(snapshot, str):
        raise ValueError("context_assembled does not record the workspace snapshot used for assembly")
    return snapshot


def _model_input_audit(store: EventStore, artifacts: ArtifactStore, run_id: str) -> dict[str, Any]:
    # 逐条核对事件的绑定与顺序；每个请求由上下文装配（P）按它之前的事件重新装配，与记录下来的请求比较
    notes: list[str] = []
    activations: dict[str, tuple[str, str, str]] = {}
    activation_bases: dict[str, dict[str, Any]] = {}
    activation_prompts = {}
    activation_intends: dict[str, str] = {}
    activation_guidance_only: dict[str, bool] = {}
    steps: dict[str, int] = {}
    digests: dict[str, str] = {}
    purposes: dict[str, str] = {}
    compacting: dict[tuple[str, int], dict[str, Any]] = {}
    checkpoints: dict[tuple[Any, ...], dict[str, Any]] = {}
    attempted: set[tuple[str, int]] = set()
    failed_steps: set[tuple[str, int]] = set()
    failed_attempts: dict[tuple[str, int], dict[str, Any]] = {}
    step_meta: dict[tuple[str, int], dict[str, Any]] = {}
    retry_schedules: dict[tuple[str, int], dict[str, Any]] = {}
    tool_steps: set[tuple[str, int]] = set()
    replies_without_tool_call: dict[str, int] = {}
    intend_bytes = b""
    received_version = 0
    prompt_versions: dict[str, int] = {}
    current_work = RunProjection()
    assembly = ContextAssembly(artifacts)
    events = store.list_events(run_id)
    # 重新装配使用当前加载的定义，只能审计按同一版本定义发出的请求；版本不同时先写明，之后的不一致由它引起
    recorded = {event.payload.get("definitions_version") for event in events
                if event.type in {EventType.RUN_CREATED, EventType.MODEL_REQUESTED}}
    if recorded != {DEFINITIONS.version}:
        notes.append(f"run used definitions {sorted(map(str, recorded))}; the audit loads {DEFINITIONS.version}")
    has_retry_evidence = any(event.type in RETRY_EVENTS for event in events)
    for index, event in enumerate(events):
        try:
            apply_event(current_work, event)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            notes.append(f"event {event.stream_version}: could not rebuild current work: {exc}")
            continue
        payload = event.payload or {}
        activation = payload.get("activation_id")
        work_basis = {
            "effective_contract_hash": current_contract_hash(current_work),
            "engineering_plan_hash": current_plan_hash(current_work),
            "request_id": None if current_work.pending_request is None else current_work.pending_request.id,
        }
        if event.type in {EventType.RUN_CREATED, EventType.USER_INPUT_RECEIVED, EventType.DEPARTMENT_PROMPT_UPDATED}:
            try:
                if event.type != EventType.DEPARTMENT_PROMPT_UPDATED:
                    item = payload["initial_input"] if event.type == EventType.RUN_CREATED else payload
                    if not isinstance(item["text"], str) or item["version"] != received_version + 1:
                        raise ValueError("input version or original text is invalid")
                    raw = item["text"].encode("utf-8")
                    if (artifacts.get_for_run(run_id, ArtifactRef(**item["input_ref"])) != raw
                            or item["byte_start"] != len(intend_bytes)
                            or item["byte_end"] != len(intend_bytes) + len(raw)):
                        raise ValueError("input bytes or range differ from their recorded original")
                    intend_bytes += raw
                    received_version += 1
                    if artifacts.get_for_run(run_id, ArtifactRef(**item["intend_ref"])) != intend_bytes:
                        raise ValueError("intend artifact is not the exact concatenation of received inputs")
                    if current_work.task.encode("utf-8") != intend_bytes:
                        raise ValueError("projected intend differs from received input originals")
                updates = payload["department_prompts"].values() if event.type == EventType.RUN_CREATED else (
                    [payload] if event.type == EventType.DEPARTMENT_PROMPT_UPDATED else []
                )
                for item in updates:
                    department = item["department"]
                    if item["version"] != prompt_versions.get(department, 0) + 1:
                        raise ValueError("prompt version is not sequential")
                    if artifacts.get_for_run(run_id, ArtifactRef(**item["prompt_ref"])) != item["text"].encode("utf-8"):
                        raise ValueError("prompt differs from its recorded original")
                    prompt_versions[department] = item["version"]
            except (KeyError, TypeError, ValueError, OSError) as exc:
                notes.append(f"event {event.stream_version}: {exc}")
            continue
        if event.type == EventType.DEPARTMENT_ACTIVATED:
            if not activation or activation in activations:
                notes.append(f"event {event.stream_version}: missing or duplicate department activation")
            else:
                activations[activation] = (event.role, event.session_id, event.event_id)
                prompt = current_work.department_prompts[event.role]
                activation_prompts[activation] = prompt
                activation_intends[activation] = current_work.task
                basis = {**work_basis, "input_version": current_work.input_version,
                         "prompt_version": prompt.version, "prompt_hash": prompt.prompt_ref.content_hash}
                activation_bases[activation] = basis
                guidance_only = _expected_guidance_only(current_work, event.role)
                activation_guidance_only[activation] = guidance_only
                expected_guidance = {"guidance_ids": [item.id for item in pending_guidance(current_work, event.role)],
                                     "guidance_only": guidance_only}
                for field, value in {**basis, **expected_guidance}.items():
                    if field not in payload or payload[field] != value:
                        notes.append(f"event {event.stream_version}: activation {field} does not match current work")
            continue
        if event.type not in {EventType.DEPARTMENT_INPUT, EventType.CONTEXT_ASSEMBLED, EventType.MODEL_REQUESTED,
                              EventType.COMPACTION_RECORDED, EventType.MODEL_MESSAGE,
                              EventType.TOOL_STARTED, EventType.TOOL_CALLED, EventType.TOOL_SKIPPED,
                              EventType.TOOL_CALL_REQUIRED, *RETRY_EVENTS}:
            continue
        try:
            if not activation or not event.role or not event.session_id:
                raise ValueError("missing activation/department/session binding")
            binding = (event.role, event.session_id, event.parent_event_id)
            if activations.get(activation) != binding:
                raise ValueError("input or output does not match its department activation")
            basis = activation_bases[activation]
            for field in ("input_version", "prompt_version", "prompt_hash"):
                if payload.get(field) != basis[field]:
                    raise ValueError(f"{field} does not match the version adopted at activation")
            if event.type == EventType.TOOL_STARTED or (
                event.type == EventType.TOOL_CALLED and payload.get("name") == "provider_usage"
            ):
                continue
            if event.type in RETRY_EVENTS:
                # A late failure describes the request that was already admitted.  The
                # user may have cancelled, appended input, or closed an expert request
                # before the provider reported that failure, so its adopted work basis
                # must be checked against the activation only.  A retry schedule is a
                # new decision and therefore must still match the current projection.
                for field in work_basis:
                    value = basis[field]
                    if field not in payload or payload[field] != value:
                        raise ValueError(f"{field} does not match the activation basis")
                    if event.type == MODEL_RETRY_SCHEDULED and work_basis[field] != value:
                        raise ValueError(f"{field} does not match the activation and current work")
                step = payload.get("step_id")
                if type(step) is not int or step <= 0:
                    raise ValueError("retry event has an invalid step_id")
                key = (activation, step)
                meta = step_meta.get(key)
                if meta is None:
                    raise ValueError("retry event does not match a prepared model step")
                if "attempt" not in payload:
                    raise ValueError("retry event is missing attempt")
                attempt = payload["attempt"]
                if type(attempt) is not int or attempt != meta["attempt"] or not 1 <= attempt <= 3:
                    raise ValueError("retry event attempt does not match its model step")
                max_attempts = payload.get("max_attempts")
                if type(max_attempts) is not int or max_attempts != 3:
                    raise ValueError("retry event has an invalid max_attempts")
                for field in ("root_step_id", "retry_of_step_id"):
                    expected = meta[field]
                    if field not in payload or payload[field] != expected:
                        raise ValueError(f"retry event {field} does not match its model step")
                if event.type == MODEL_ATTEMPT_FAILED:
                    if key not in attempted or key in failed_steps:
                        raise ValueError("attempt failure does not match one unique model request")
                    failed_steps.add(key)
                    failed_attempts[key] = {**payload, "_context_digest": event.context_digest}
                    compacting.pop(key, None)
                    if payload.get("retryable") not in {True, False}:
                        raise ValueError("attempt failure must record retryable")
                else:
                    failure = failed_attempts.get(key)
                    if failure is None:
                        raise ValueError("retry schedule does not follow a failed model step")
                    next_step = payload.get("next_step_id")
                    delay = payload.get("delay_sec")
                    if type(next_step) is not int or next_step != step + 1:
                        raise ValueError("retry schedule does not point to the next model step")
                    if (type(delay) not in {int, float} or not math.isfinite(delay)
                            or delay < 0 or delay > 60):
                        raise ValueError("retry schedule has an invalid delay_sec")
                    next_attempt = payload.get("next_attempt")
                    if (payload.get("retryable") is not True or failure.get("retryable") is not True
                            or attempt >= max_attempts or next_attempt != attempt + 1
                            or payload.get("purpose") != failure.get("purpose")
                            or event.context_digest != failure.get("_context_digest")
                            or (activation, next_step) in retry_schedules):
                        raise ValueError("retry schedule has an invalid retryability or attempt")
                    retry_schedules[(activation, next_step)] = payload
                continue
            if event.type in {EventType.DEPARTMENT_INPUT, EventType.CONTEXT_ASSEMBLED,
                              EventType.MODEL_REQUESTED, EventType.COMPACTION_RECORDED}:
                for field in work_basis:
                    value = basis[field]
                    if field not in payload or payload[field] != value or work_basis[field] != value:
                        raise ValueError(f"{field} does not match the activation and current work")
            checkpoint_key = (event.role, basis["effective_contract_hash"], basis["engineering_plan_hash"],
                              basis["input_version"], basis["prompt_version"], basis["prompt_hash"])
            # 按记录下来的事件由 P 重新装配：调用目标取这次请求事件记录的解析结果，
            # 部门身份、提示词与只能回应指导按激活时的记录，guidance_results 使用装配时已有的事件与记录下来的工作区快照。
            # 工具与部门工作消息本身没有调用目标，用这次激活里同一步请求记录下来的窗口
            if "context_window" in payload:
                target_window = payload["context_window"]
                configured_output_limit = payload.get("configured_max_output_tokens")
            else:
                recorded = next(
                    (item for item in events
                     if item.type == EventType.CONTEXT_ASSEMBLED
                     and item.payload.get("activation_id") == activation
                     and item.payload.get("step_id") == payload.get("step_id")),
                    None,
                )
                if recorded is None:
                    raise ValueError("event has no recorded model request to take the call target from")
                target_window = recorded.payload["context_window"]
                configured_output_limit = recorded.payload.get("configured_max_output_tokens")
            limits = model_limits(target_window, configured_output_limit)
            frame = StepFrame(
                department=event.role, session_id=event.session_id, activation_id=activation,
                prompt=activation_prompts[activation], guidance_only=activation_guidance_only[activation],
                effective_contract_hash=basis["effective_contract_hash"],
                engineering_plan_hash=basis["engineering_plan_hash"], input_version=basis["input_version"],
            )
            before = events[:index]
            pinned = assembly.pin(current_work, frame, limits, step_id=payload.get("step_id", 1), events=before,
                                  snapshot_hash=_assembly_snapshot_hash(events, index))
            if event.type == EventType.DEPARTMENT_INPUT:
                if payload.get("step_id") != 1:
                    raise ValueError("department input does not belong to its activation start")
                item = _read_artifact(artifacts, run_id, payload["input_ref"])
                if item.get("role") != "user":
                    raise ValueError("department input must be a work message")
                if item != pinned.department_input:
                    raise ValueError("department input differs from the current allowed work materials")
            elif event.type == EventType.CONTEXT_ASSEMBLED:
                if (payload.get("department") != event.role or payload.get("session_id") != event.session_id
                        or payload.get("run_id") != run_id):
                    raise ValueError("manifest run/department/session does not match its event")
                step = payload.get("step_id")
                if type(step) is not int or step != steps.get(activation, 0) + 1:
                    raise ValueError("model steps are missing, duplicated, or out of order")
                steps[activation] = step
                previous_key = (activation, step - 1)
                retry_schedule = retry_schedules.pop((activation, step), None)
                attempt = payload.get("attempt", 1)
                root_step_id = payload.get("root_step_id", step)
                retry_of_step_id = payload.get("retry_of_step_id")
                if retry_schedule is not None:
                    failure = failed_attempts.get(previous_key)
                    expected_attempt = (failure or {}).get("attempt", 0) + 1
                    expected_root = (failure or {}).get("root_step_id", step - 1)
                    if failure is None or payload.get("purpose") != failure.get("purpose"):
                        raise ValueError("retry context purpose does not match the failed model step")
                    if attempt != expected_attempt:
                        raise ValueError("retry context has a non-sequential attempt")
                    if retry_of_step_id != step - 1 or root_step_id != expected_root:
                        raise ValueError("retry context is not linked to the failed step")
                elif attempt != 1 or root_step_id != step or retry_of_step_id is not None:
                    raise ValueError("new model step has invalid retry metadata")
                if type(attempt) is not int or not 1 <= attempt <= 3:
                    raise ValueError("model step has an invalid attempt")
                step_meta[(activation, step)] = {
                    "attempt": attempt, "root_step_id": root_step_id,
                    "retry_of_step_id": retry_of_step_id,
                }
                ref = payload.get("request_ref") or {}
                if ref.get("content_hash") not in event.artifact_hashes:
                    raise ValueError("request artifact is not bound to its event")
                request = _read_artifact(artifacts, run_id, ref)
                digest = canonical_hash(request)
                if digest != payload.get("digest") or digest != event.context_digest:
                    raise ValueError("actual model input digest mismatch")
                digests[activation] = digest
                purpose = payload.get("purpose")
                if purpose not in {"work", "compaction"}:
                    raise ValueError("unknown model request purpose")
                purposes[activation] = purpose
                allowed = {"input", "tools"}
                limit = payload.get("max_output_tokens")
                if limit is not None:
                    allowed.add("max_output_tokens")
                    if type(limit) is not int or limit <= 0 or request.get("max_output_tokens") != limit:
                        raise ValueError("model output limit does not match its manifest")
                if set(request) != allowed:
                    raise ValueError("unexpected model input fields")
                items, schemas = request["input"], request["tools"]
                # Work requests open with the pinned department material; compaction requests
                # open with the summarizer rules and pin the department material second.
                pinned_index = 1 if purpose == "compaction" else 0
                if (not isinstance(items, list) or len(items) <= pinned_index
                        or items[pinned_index].get("role") != "developer"):
                    raise ValueError("missing explicit department instructions")
                instructions = items[pinned_index].get("content")
                if (not isinstance(instructions, str)
                        or not instructions.startswith(f"[intend]\n{activation_intends[activation]}\n\n[current_work]\n")):
                    raise ValueError("model input does not carry the verbatim task followed by current work")
                if items[pinned_index] != pinned.context.input_items[0]:
                    raise ValueError("pinned developer input differs from current allowed materials")
                records = assembly.department_history(before, event.role)
                expected = assembly.request(pinned, records)
                manifest = expected.context.manifest
                if payload.get("compaction_event_id") != manifest.compaction_event_id:
                    raise ValueError("model request uses an unrelated compaction checkpoint")
                if payload.get("effective_context_window") != limits.context_window:
                    raise ValueError("effective context window does not match the resolved call target")
                if purpose == "compaction":
                    if schemas or limit is None:
                        raise ValueError("compaction must have no tools and an explicit output limit")
                    plan = expected.compaction_plan
                    if plan is None or request["input"] != plan.input_items or limit != plan.max_output_tokens:
                        raise ValueError("compaction input differs from its allowed source assembly")
                    compacting[(activation, step)] = _audit_compaction_input(request, records,
                                                                             checkpoints.get(checkpoint_key))
                    compacting[(activation, step)].update(
                        effective_context_window=limits.context_window,
                        target_context_window=target_window,
                        configured_max_output_tokens=configured_output_limit,
                        effective_max_output_tokens=plan.max_output_tokens,
                    )
                else:
                    if items[1:] != expected.payload["input"][1:]:
                        raise ValueError("input history differs from this department's recorded outputs")
                    names = [item.get("name") for item in schemas]
                    offered = set(offered_tools(current_work, event.role, guidance_only=frame.guidance_only))
                    if len(names) != len(set(names)) or set(names) != offered:
                        raise ValueError("actual tool schemas do not match the department's tools")
                    if schemas != expected.context.tools:
                        raise ValueError("actual tool schemas differ from the allowed definitions")
                    if limit != manifest.max_output_tokens:
                        raise ValueError("effective output limit does not match the resolved call target")
                if request != expected.payload:
                    raise ValueError("model request differs from the request rebuilt from the recorded events")
                if (payload.get("input_token_estimate") != expected.input_token_estimate
                        or payload.get("token_estimate") != manifest.token_estimate
                        or payload.get("output_reserve_tokens") != expected.output_reserve_tokens
                        or payload.get("budget") != limits.context_window
                        or payload.get("admitted") != expected.admitted):
                    raise ValueError("context token accounting or admission differs from the effective model limits")
                if (payload.get("guidance_ids") != manifest.guidance_ids
                        or payload.get("guidance_only") != manifest.guidance_only):
                    raise ValueError("guidance metadata differs from the department's pending guidance")
                if payload.get("injected") != [asdict(item) for item in manifest.injected]:
                    raise ValueError("injected source metadata differs from current allowed materials")
                if payload.get("excluded") != [asdict(item) for item in manifest.excluded]:
                    raise ValueError("excluded source metadata differs from current allowed materials")
            elif event.type == EventType.MODEL_REQUESTED:
                key = (activation, payload.get("step_id"))
                if (activation not in steps or key[1] != steps[activation]
                        or event.context_digest != digests[activation] or key in attempted
                        or payload.get("attempted") is not True or payload.get("purpose") != purposes[activation]):
                    raise ValueError("model request attempt does not match a unique prepared input")
                meta = step_meta.get(key)
                if meta is None:
                    raise ValueError("model request has no prepared attempt metadata")
                if has_retry_evidence:
                    for field in ("attempt", "max_attempts", "root_step_id", "retry_of_step_id"):
                        if field not in payload:
                            raise ValueError(f"model request is missing retry metadata: {field}")
                    if type(payload["max_attempts"]) is not int or payload["max_attempts"] != 3:
                        raise ValueError("model request has an invalid max_attempts")
                if "attempt" in payload and payload["attempt"] != meta["attempt"]:
                    raise ValueError("model request attempt does not match its prepared step")
                if "root_step_id" in payload and payload["root_step_id"] != meta["root_step_id"]:
                    raise ValueError("model request root_step_id does not match its prepared step")
                if "retry_of_step_id" in payload and payload["retry_of_step_id"] != meta["retry_of_step_id"]:
                    raise ValueError("model request retry_of_step_id does not match its prepared step")
                attempted.add(key)
            elif event.type == EventType.COMPACTION_RECORDED:
                key = (activation, payload.get("step_id"))
                if (key not in attempted or key not in compacting or payload.get("purpose") != "compaction"
                        or event.context_digest != digests[activation]):
                    raise ValueError("compaction checkpoint does not match its model request")
                checkpoint = _audit_compaction_output(event, artifacts, compacting.pop(key), checkpoints.get(checkpoint_key))
                checkpoints[checkpoint_key] = {"event_id": event.event_id, "checkpoint": checkpoint}
            else:
                if (activation not in steps or payload.get("step_id") != steps[activation]
                        or (activation, steps[activation]) not in attempted or payload.get("purpose") != purposes[activation]):
                    raise ValueError("model/tool output is not bound to its model step")
                if (activation, steps[activation]) in failed_steps:
                    raise ValueError("failed model step produced output after its failure was recorded")
                if event.type == EventType.MODEL_MESSAGE:
                    item = _read_artifact(artifacts, run_id, payload["message_ref"])
                    if purposes[activation] == "compaction":
                        compacting[(activation, steps[activation])]["outputs"].append(item)
                        continue
                elif event.type == EventType.TOOL_CALL_REQUIRED:
                    # 主机只在工作步骤没有调用工具时追加这条消息，计数连续且不超过上限
                    count = replies_without_tool_call.get(activation, 0) + 1
                    item = _read_artifact(artifacts, run_id, payload["input_ref"])
                    limit = DEFINITIONS.limits.tool_call_required_limit
                    if (purposes[activation] != "work" or (activation, steps[activation]) in tool_steps
                            or payload.get("count") != count or count > limit
                            or payload.get("limit") != limit
                            or item != {"role": "user", "content": tool_call_required_text(count)}):
                        raise ValueError("appended tool call message does not follow a reply without tool calls")
                    replies_without_tool_call[activation] = count
                else:
                    if purposes[activation] == "compaction":
                        raise ValueError("compaction request executed a tool")
                    tool_steps.add((activation, steps[activation]))
                    replies_without_tool_call[activation] = 0
                    item = payload["input_item"]
                    if item.get("type") != "function_call_output" or item.get("call_id") != payload.get("id"):
                        raise ValueError("tool input item does not match its call")
                    output = _read_artifact(artifacts, run_id, payload["output_ref"]) if payload.get("output_ref") else None
                    if json.loads(item["output"]) != {"ok": payload.get("ok"), "output": output, "error": payload.get("error")}:
                        raise ValueError("tool input item does not match its recorded result")
        except (AttributeError, IndexError, KeyError, TypeError, ValueError, OSError) as exc:
            notes.append(f"event {event.stream_version}: {exc}")
    prepared_keys = set(step_meta)
    unrequested = prepared_keys - attempted
    orphaned = attempted - prepared_keys
    if orphaned:
        notes.append(f"model request has no prepared model step: {sorted(orphaned)}")
    if not attempted:
        notes.append("no model request attempts recorded")
    return {
        "status": "unverified" if notes else "verified",
        "request_count": len(attempted),
        "attempt_count": len(attempted),
        "retry_count": sum(step_meta[key]["attempt"] > 1 for key in attempted),
        "logical_request_count": len({(activation, step_meta[(activation, step)]["root_step_id"])
                                       for activation, step in attempted}),
        "prepared_count": len(step_meta),
        "unrequested_count": len(unrequested),
        "orphaned_request_count": len(orphaned),
        "activation_count": len(steps),
        "compaction_count": sum(event.type == EventType.COMPACTION_RECORDED for event in events),
        "notes": notes,
    }


def _manifest_boundary(store: EventStore, run_id: str) -> tuple[bool, list[str]]:
    notes: list[str] = []
    ok = True
    seen = 0
    for event in store.list_events(run_id):
        if event.type != EventType.CONTEXT_ASSEMBLED:
            continue
        seen += 1
        injected = {item.get("source") for item in event.payload.get("injected", [])}
        excluded = {item.get("source") for item in event.payload.get("excluded", [])}
        department = event.payload.get("department")
        if "other_department_transcript" in injected:
            ok = False
            notes.append(f"{department}: injected a forbidden transcript source")
        for required in ("other_department_transcript",):
            if required not in excluded:
                ok = False
                notes.append(f"{department}: missing exclusion {required}")
        required_source = "pinned_work" if event.payload.get("purpose") == "compaction" else "proposal_contract"
        if required_source not in injected:
            ok = False
            notes.append(f"{department}: {required_source} was not injected")
    if seen == 0:
        return False, ["no context_assembled events; manifest boundary not verified"]
    if ok:
        notes.append("cross-department transcripts excluded; proposal contracts injected")
    return ok, notes


def _receipt(item: Any) -> dict[str, Any]:
    return asdict(item) if hasattr(item, "__dataclass_fields__") else dict(item)


def _receipt_evidence(system: LoopSystem, run_id: str, receipts: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    notes: list[str] = []
    executions: list[tuple[str, dict[str, Any]]] = []
    for event in system.store.list_events(run_id):
        payload = event.payload or {}
        if event.type != EventType.TOOL_CALLED or payload.get("name") != "run_check":
            continue
        if not payload.get("output_ref"):
            continue
        try:
            output = _read_artifact(system.artifacts, run_id, payload["output_ref"])
            if isinstance(output, dict) and output.get("executor") == "host":
                if not payload.get("activation_id") or output.get("activation_id") != payload.get("activation_id"):
                    notes.append(f"check event {event.stream_version}: receipt activation does not match its execution")
                    continue
                executions.append((event.role, output))
        except (KeyError, TypeError, ValueError, OSError) as exc:
            notes.append(f"check event {event.stream_version}: {exc}")
    for receipt in receipts:
        match = next((index for index, (role, output) in enumerate(executions)
                      if role == receipt.get("department") and all(
                          output.get(key) == value for key, value in receipt.items() if key != "department"
                      )), None)
        if match is None:
            notes.append(f"{receipt.get('department')}/{receipt.get('name')}: no matching host execution")
        else:
            executions.pop(match)
    projection = system.project(run_id)
    try:
        snapshot = system.workspace(run_id).digest()
    except (ValueError, OSError) as exc:
        snapshot = None
        notes.append(f"current workspace could not be verified: {exc}")
    spec = projection.product_spec
    delivery = projection.delivery_spec
    contract = projection.effective_contract
    plan = projection.engineering_plan
    for department in ("engineering", "quality"):
        valid = [receipt for receipt in receipts
                 if receipt.get("department") == department and receipt.get("exit_code") == 0
                 and not receipt.get("tree_changed") and receipt.get("activation_id")
                 and receipt.get("snapshot_hash") == snapshot and spec is not None
                 and receipt.get("product_spec_hash") == spec.content_hash
                 and contract is not None and receipt.get("effective_contract_hash") == contract.content_hash
                 and plan is not None and plan.status == "active"
                 and plan.effective_contract_hash == contract.content_hash
                 and receipt.get("engineering_plan_hash") == plan.content_hash
                 and (department != "quality" or delivery is not None
                      and receipt.get("delivery_spec_hash") == delivery.content_hash)]
        if not valid:
            notes.append(f"{department}: no successful host check bound to the final contract and snapshot")
    return not notes, notes


def _write_report(data_dir: Path, report: dict[str, Any]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    json_path = data_dir / "smoke-report.json"
    md_path = data_dir / "smoke-report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Yudao 真实 provider smoke",
        "",
        f"- adapter: `{report.get('adapter')}`",
        f"- provider: `{report.get('provider')}`",
        f"- model: `{report.get('model')}`",
        f"- available: `{report.get('available')}`",
        f"- provider bindings: `{json.dumps(report.get('provider_bindings') or {}, ensure_ascii=False, sort_keys=True)}`",
        "",
    ]
    if report.get("error"):
        lines.append(f"- error: {report['error']}")
        lines.append("")
    for name, scenario in (report.get("scenarios") or {}).items():
        lines.extend(
            [
                f"## {name}",
                "",
                f"- run id: `{scenario.get('run_id')}`",
                f"- phase: `{scenario.get('phase')}`",
                f"- stop reason: `{scenario.get('stop_reason')}`",
                f"- adapter: `{scenario.get('adapter')}`",
                f"- provider/model: `{scenario.get('provider')}` / `{scenario.get('model')}`",
                f"- provider bindings: `{json.dumps(scenario.get('provider_bindings') or {}, ensure_ascii=False, sort_keys=True)}`",
                f"- route: `{' | '.join(scenario.get('route') or [])}`",
                f"- requests: `{scenario.get('request_count')}` reworks: `{scenario.get('rework_count')}`",
                f"- replay consistent: `{scenario.get('replay_consistent')}`",
                f"- manifest boundary: `{scenario.get('manifest_boundary')}`",
                f"- model input audit: `{(scenario.get('model_input_audit') or {}).get('status', 'unverified')}`",
                f"- model requests: `{(scenario.get('model_input_audit') or {}).get('request_count', 0)}`",
                f"- model attempts: `{(scenario.get('model_input_audit') or {}).get('attempt_count', 0)}` retries: `{(scenario.get('model_input_audit') or {}).get('retry_count', 0)}`",
                f"- context isolated: `{scenario.get('context_isolated')}`",
                f"- host receipts verified: `{scenario.get('check_receipts_verified')}`",
                f"- delivery archive: `{(scenario.get('delivery_archive') or {}).get('status', 'unverified')}`",
                f"- Git versions: `{(scenario.get('git_audit') or {}).get('status', 'unverified')}`",
                f"- collaboration audit: `{(scenario.get('collaboration_audit') or {}).get('status', 'unverified')}`",
                f"- fake used: `{scenario.get('fake_used')}`",
                f"- delivery files: `{', '.join(scenario.get('delivery_files') or [])}`",
                f"- qa verdict: `{scenario.get('qa_verdict')}`",
                "",
            ]
        )
        if scenario.get("error"):
            lines.append(f"- error: {scenario['error']}")
            lines.append("")
        for note in scenario.get("context_isolation_notes") or []:
            lines.append(f"- isolation note: {note}")
        if scenario.get("context_isolation_notes"):
            lines.append("")
        for note in scenario.get("check_receipt_notes") or []:
            lines.append(f"- receipt note: {note}")
        for note in (scenario.get("delivery_archive") or {}).get("notes", []):
            lines.append(f"- archive note: {note}")
        for note in (scenario.get("collaboration_audit") or {}).get("notes", []):
            lines.append(f"- collaboration note: {note}")
        receipts = scenario.get("check_receipts") or []
        if receipts:
            lines.append("检查回执：")
            for receipt in receipts:
                lines.append(
                    f"- {receipt.get('department')} `{receipt.get('name')}` exit={receipt.get('exit_code')} snapshot={receipt.get('snapshot_hash')}"
                )
            lines.append("")
        tools = scenario.get("tool_calls") or []
        if tools:
            lines.append("工具调用：")
            for call in tools:
                lines.append(
                    f"- {call.get('department')} `{call.get('name')}` ok={call.get('ok')} executor={call.get('executor')}"
                )
            lines.append("")
    return "\n".join(lines) + "\n"


def smoke_exit_code(report: dict[str, Any]) -> int:
    if not report.get("available"):
        return 2
    scenarios = report.get("scenarios") or {}
    if not scenarios:
        return 2
    for scenario in scenarios.values():
        if scenario.get("fake_used"):
            return 2
        if scenario.get("phase") != "DONE" or scenario.get("stop_reason") != "released":
            return 1
        if not scenario.get("replay_consistent") or not scenario.get("context_isolated"):
            return 1
        if (scenario.get("model_input_audit") or {}).get("status") != "verified":
            return 1
        if not scenario.get("check_receipts") or not scenario.get("check_receipts_verified"):
            return 1
        if (scenario.get("delivery_archive") or {}).get("status") != "verified":
            return 1
        if (scenario.get("git_audit") or {}).get("status") != "verified":
            return 1
    collaboration = scenarios.get("collaboration")
    if collaboration is not None:
        audit = collaboration.get("collaboration_audit") or {}
        if (collaboration.get("request_count", 0) < 2 or audit.get("status") != "verified"
                or not audit.get("pre_spec_consultation") or not audit.get("requirements_action")):
            return 1
    return 0
