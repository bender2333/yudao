"""真实 provider 三部门 smoke。读取环境变量，不读取 provider.md，不用 fake 冒充成功。"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .adapters.responses import ResponsesConfig, ResponsesAdapter
from .artifacts import ArtifactStore
from .event_store import EventStore
from .models import ArtifactRef, EventType, canonical_hash, json_dumps
from .projection import project_run
from .runtime import LoopSystem


DEFAULT_DIR = Path(".yudao") / "native-validation"

HAPPY_TASK = (
    "Implement a local Python CLI at src/echo.py. "
    "Running `python src/echo.py hello` must print hello and exit 0. "
    "Do not add network access, extra files, or configuration. "
    "Engineering must write the file and have the host run a check. "
    "Quality must independently have the host run a check before release."
)

ASK_TASK = (
    "Implement a local Python CLI at src/echo.py that prints its first argument. "
    "The product spec must leave unspecified whether arguments starting with '-' "
    "are unknown flags or ordinary text. "
    "Engineering must submit an AskRequest for that decision and wait for a "
    "ProductReaction before delivering. Product must accept, reply, or reject. "
    "Quality independently checks the delivered CLI."
)


def run_smoke(
    data_dir: str | Path = DEFAULT_DIR,
    *,
    scenarios: list[str] | None = None,
) -> dict[str, Any]:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    selected = scenarios or ["happy", "ask"]
    if any(name not in {"happy", "ask"} for name in selected):
        raise ValueError("unknown smoke scenario")
    config = ResponsesConfig.from_env()
    adapter = ResponsesAdapter(config)
    availability = adapter.availability()
    report: dict[str, Any] = {
        "provider": config.provider,
        "model": config.model,
        "adapter": adapter.name,
        "available": availability.available,
        "scenarios": {},
    }
    if not availability.available:
        report["error"] = availability.message
        report["stop_reason"] = availability.reason
        _write_report(data_dir, report)
        return report
    system = LoopSystem(data_dir, adapter)
    for name in selected:
        report["scenarios"][name] = _run_scenario(system, name)
    _write_report(data_dir, report)
    return report


def _run_scenario(system: LoopSystem, name: str) -> dict[str, Any]:
    task = HAPPY_TASK if name == "happy" else ASK_TASK
    max_cycles = 12 if name == "happy" else 16
    run_id = system.create_run(
        task,
        max_cycles=max_cycles,
        context_window=32_000,
    )
    try:
        projection = system.run_until_stop(run_id)
    except Exception as exc:  # noqa: BLE001 - smoke must record provider failure
        return {
            "run_id": run_id,
            "scenario": name,
            "phase": "FAILED",
            "stop_reason": "provider_error",
            "error": str(exc),
            "fake_used": False,
        }
    return summarize_run(system, run_id, scenario=name)


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
        "adapter": projection.adapter,
        "provider": projection.provider,
        "model": projection.model,
        "route": list(projection.transitions),
        "ask_count": projection.ask_count,
        "rework_count": projection.rework_count,
        "cycle_count": projection.cycle_count,
        "token_used": projection.token_used,
        "tool_calls": tool_calls,
        "check_receipts": receipts,
        "check_receipts_verified": receipts_ok,
        "check_receipt_notes": receipt_notes,
        "replay_consistent": replayed.canonical_state() == projection.canonical_state(),
        **isolation,
        "fake_used": projection.adapter == "fake",
        "product_spec_hash": None if projection.product_spec is None else projection.product_spec.content_hash,
        "delivery_files": [] if projection.delivery_spec is None else list(projection.delivery_spec.files),
        "qa_verdict": None if projection.last_review is None else projection.last_review.verdict,
    }


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


def _history_record(event: Any, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": event.event_id, "seq": event.seq, "activation_id": event.payload["activation_id"],
        "step_id": event.payload["step_id"], "type": event.type, "item": item, "item_digest": canonical_hash(item),
    }


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


def _audited_visible_history(records: list[dict[str, Any]], previous: dict[str, Any] | None) -> list[dict[str, Any]]:
    index, offset = _checkpoint_cursor(records, previous)
    result = []
    if previous is not None:
        checkpoint = previous["checkpoint"]
        if offset or not checkpoint["boundary"]:
            raise ValueError("work resumed inside an incomplete compressed message/tool round")
        result.append({"role": "user", "content": "[department_memory]\n" + json_dumps({
            "summary": checkpoint["summary"], "covered_through_event_id": checkpoint["covered_through_event_id"],
            "covered_digest": checkpoint["covered_digest"],
        })})
    result.extend(record["item"] for record in records[index:])
    return result


def _audit_compaction_input(request: dict[str, Any], records: list[dict[str, Any]],
                            previous: dict[str, Any] | None) -> dict[str, Any]:
    items = request["input"]
    if len(items) != 3 or items[1].get("role") != "developer" or items[2].get("role") != "user":
        raise ValueError("compaction input must contain pinned context, summary instructions and source material")
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
    if (plan["input_items"] != audit["request"]["input"] or plan["source_refs"] != audit["source_refs"]
            or payload["source_refs"] != audit["source_refs"] or plan["next_checkpoint"] != audit["next_checkpoint"]
            or plan["previous_summary_digest"] != audit["previous_summary_digest"]
            or plan["max_output_tokens"] != audit["request"]["max_output_tokens"]
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


def _model_input_audit(store: EventStore, artifacts: ArtifactStore, run_id: str) -> dict[str, Any]:
    from .tools import tools_for

    notes: list[str] = []
    histories: dict[str, list[dict[str, Any]]] = {}
    activations: dict[str, tuple[str, str, str]] = {}
    steps: dict[str, int] = {}
    digests: dict[str, str] = {}
    purposes: dict[str, str] = {}
    compacting: dict[tuple[str, int], dict[str, Any]] = {}
    checkpoints: dict[str, dict[str, Any]] = {}
    attempted: set[tuple[str, int]] = set()
    intend: str | None = None
    for event in store.list_events(run_id):
        payload = event.payload or {}
        activation = payload.get("activation_id")
        if event.type == EventType.RUN_CREATED:
            intend = payload.get("task")
            try:
                recorded = artifacts.get_for_run(run_id, ArtifactRef(**payload["intend_ref"]))
                if not isinstance(intend, str) or recorded != intend.encode("utf-8"):
                    raise ValueError("original task differs from its recorded intend artifact")
            except (KeyError, TypeError, ValueError, OSError) as exc:
                notes.append(f"event {event.seq}: {exc}")
            continue
        if event.type == EventType.DEPARTMENT_ACTIVATED:
            if not activation or activation in activations:
                notes.append(f"event {event.seq}: missing or duplicate department activation")
            else:
                activations[activation] = (event.role, event.session_id, event.event_id)
            continue
        if event.type not in {EventType.DEPARTMENT_INPUT, EventType.CONTEXT_ASSEMBLED, EventType.MODEL_REQUESTED,
                              EventType.COMPACTION_RECORDED, EventType.MODEL_MESSAGE,
                              EventType.TOOL_CALLED, EventType.TOOL_SKIPPED}:
            continue
        if event.type == EventType.TOOL_CALLED and payload.get("name") == "provider_usage":
            continue
        try:
            if not activation or not event.role or not event.session_id:
                raise ValueError("missing activation/department/session binding")
            binding = (event.role, event.session_id, event.parent_event_id)
            if activations.get(activation) != binding:
                raise ValueError("input or output does not match its department activation")
            if event.type == EventType.DEPARTMENT_INPUT:
                if payload.get("step_id") != 1:
                    raise ValueError("department input does not belong to its activation start")
                item = _read_artifact(artifacts, run_id, payload["input_ref"])
                if item.get("role") != "user":
                    raise ValueError("department input must be a work message")
                histories.setdefault(event.role, []).append(_history_record(event, item))
            elif event.type == EventType.CONTEXT_ASSEMBLED:
                if (payload.get("department") != event.role or payload.get("session_id") != event.session_id
                        or payload.get("run_id") != run_id):
                    raise ValueError("manifest run/department/session does not match its event")
                step = payload.get("step_id")
                if type(step) is not int or step != steps.get(activation, 0) + 1:
                    raise ValueError("model steps are missing, duplicated, or out of order")
                steps[activation] = step
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
                if not isinstance(items, list) or not items or items[0].get("role") != "developer":
                    raise ValueError("missing explicit department instructions")
                instructions = items[0].get("content")
                if (intend is None or not isinstance(instructions, str)
                        or not instructions.startswith(f"[intend]\n{intend}\n\n[current_work]\n")):
                    raise ValueError("model input does not start with the verbatim task followed by current work")
                previous = checkpoints.get(event.role)
                if payload.get("compaction_event_id") != (previous or {}).get("event_id"):
                    raise ValueError("model request uses an unrelated compaction checkpoint")
                records = histories.get(event.role, [])
                if purpose == "compaction":
                    if schemas or limit is None:
                        raise ValueError("compaction must have no tools and an explicit output limit")
                    compacting[(activation, step)] = _audit_compaction_input(request, records, previous)
                else:
                    if items[1:] != _audited_visible_history(records, previous):
                        raise ValueError("input history differs from this department's recorded outputs")
                    names = [item.get("name") for item in schemas]
                    if len(names) != len(set(names)) or set(names) != set(tools_for(event.role)):
                        raise ValueError("actual tool schemas do not match the department's tools")
            elif event.type == EventType.MODEL_REQUESTED:
                key = (activation, payload.get("step_id"))
                if (activation not in steps or key[1] != steps[activation]
                        or event.context_digest != digests[activation] or key in attempted
                        or payload.get("attempted") is not True or payload.get("purpose") != purposes[activation]):
                    raise ValueError("model request attempt does not match a unique prepared input")
                attempted.add(key)
            elif event.type == EventType.COMPACTION_RECORDED:
                key = (activation, payload.get("step_id"))
                if (key not in attempted or key not in compacting or payload.get("purpose") != "compaction"
                        or event.context_digest != digests[activation]):
                    raise ValueError("compaction checkpoint does not match its model request")
                checkpoint = _audit_compaction_output(event, artifacts, compacting.pop(key), checkpoints.get(event.role))
                checkpoints[event.role] = {"event_id": event.event_id, "checkpoint": checkpoint}
            else:
                if (activation not in steps or payload.get("step_id") != steps[activation]
                        or (activation, steps[activation]) not in attempted or payload.get("purpose") != purposes[activation]):
                    raise ValueError("model/tool output is not bound to its model step")
                if event.type == EventType.MODEL_MESSAGE:
                    item = _read_artifact(artifacts, run_id, payload["message_ref"])
                    if purposes[activation] == "compaction":
                        compacting[(activation, steps[activation])]["outputs"].append(item)
                        continue
                else:
                    if purposes[activation] == "compaction":
                        raise ValueError("compaction request executed a tool")
                    item = payload["input_item"]
                    if item.get("type") != "function_call_output" or item.get("call_id") != payload.get("id"):
                        raise ValueError("tool input item does not match its call")
                    output = _read_artifact(artifacts, run_id, payload["output_ref"]) if payload.get("output_ref") else None
                    if json.loads(item["output"]) != {"ok": payload.get("ok"), "output": output, "error": payload.get("error")}:
                        raise ValueError("tool input item does not match its recorded result")
                histories.setdefault(event.role, []).append(_history_record(event, item))
        except (AttributeError, IndexError, KeyError, TypeError, ValueError, OSError) as exc:
            notes.append(f"event {event.seq}: {exc}")
    if not attempted:
        notes.append("no model request attempts recorded")
    return {
        "status": "unverified" if notes else "verified",
        "request_count": len(attempted),
        "prepared_count": sum(steps.values()),
        "activation_count": len(steps),
        "compaction_count": sum(event.type == EventType.COMPACTION_RECORDED for event in store.list_events(run_id)),
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
        if event.type != EventType.TOOL_CALLED or payload.get("name") not in {"run_check", "collect_evidence"}:
            continue
        if not payload.get("output_ref"):
            continue
        try:
            output = _read_artifact(system.artifacts, run_id, payload["output_ref"])
            if isinstance(output, dict) and output.get("executor") == "host":
                if not payload.get("activation_id") or output.get("activation_id") != payload.get("activation_id"):
                    notes.append(f"check event {event.seq}: receipt activation does not match its execution")
                    continue
                executions.append((event.role, output))
        except (KeyError, TypeError, ValueError, OSError) as exc:
            notes.append(f"check event {event.seq}: {exc}")
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
    snapshot = system.workspace(run_id).digest()
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
                f"- route: `{' | '.join(scenario.get('route') or [])}`",
                f"- asks: `{scenario.get('ask_count')}` reworks: `{scenario.get('rework_count')}`",
                f"- replay consistent: `{scenario.get('replay_consistent')}`",
                f"- manifest boundary: `{scenario.get('manifest_boundary')}`",
                f"- model input audit: `{(scenario.get('model_input_audit') or {}).get('status', 'unverified')}`",
                f"- model requests: `{(scenario.get('model_input_audit') or {}).get('request_count', 0)}`",
                f"- context isolated: `{scenario.get('context_isolated')}`",
                f"- host receipts verified: `{scenario.get('check_receipts_verified')}`",
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
    ask = scenarios.get("ask")
    if ask is not None and ask.get("ask_count", 0) < 1:
        return 1
    return 0
