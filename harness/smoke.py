"""真实 provider 三部门 smoke。读取环境变量，不读取 provider.md，不用 fake 冒充成功。"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .adapters.responses import ResponsesConfig, ResponsesAdapter
from .artifacts import ArtifactStore
from .event_store import EventStore
from .models import ArtifactRef, EventType, canonical_hash
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


def _model_input_audit(store: EventStore, artifacts: ArtifactStore, run_id: str) -> dict[str, Any]:
    from .tools import tools_for

    notes: list[str] = []
    histories: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    activations: dict[str, tuple[str, str, str]] = {}
    steps: dict[str, int] = {}
    digests: dict[str, str] = {}
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
        if event.type not in {EventType.DEPARTMENT_INPUT, EventType.CONTEXT_ASSEMBLED, EventType.MODEL_REQUESTED, EventType.MODEL_MESSAGE,
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
                histories.setdefault(event.role, []).append((activation, event.type, item))
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
                if set(request) != {"input", "tools"}:
                    raise ValueError("unexpected model input fields")
                items, schemas = request["input"], request["tools"]
                if not isinstance(items, list) or not items or items[0].get("role") != "developer":
                    raise ValueError("missing explicit department instructions")
                instructions = items[0].get("content")
                if (intend is None or not isinstance(instructions, str)
                        or not instructions.startswith(f"[intend]\n{intend}\n\n[current_work]\n")):
                    raise ValueError("model input does not start with the verbatim task followed by current work")
                history = [item for source_activation, kind, item in histories.get(event.role, [])
                           if not (source_activation == activation and kind == EventType.DEPARTMENT_INPUT)]
                if items[1:] != history:
                    raise ValueError("input history differs from this department's recorded outputs")
                names = [item.get("name") for item in schemas]
                if len(names) != len(set(names)) or set(names) != set(tools_for(event.role)):
                    raise ValueError("actual tool schemas do not match the department's tools")
            elif event.type == EventType.MODEL_REQUESTED:
                key = (activation, payload.get("step_id"))
                if (activation not in steps or key[1] != steps[activation]
                        or event.context_digest != digests[activation] or key in attempted
                        or payload.get("attempted") is not True):
                    raise ValueError("model request attempt does not match a unique prepared input")
                attempted.add(key)
            else:
                if (activation not in steps or payload.get("step_id") != steps[activation]
                        or (activation, steps[activation]) not in attempted):
                    raise ValueError("model/tool output is not bound to its model step")
                if event.type == EventType.MODEL_MESSAGE:
                    item = _read_artifact(artifacts, run_id, payload["message_ref"])
                else:
                    item = payload["input_item"]
                    if item.get("type") != "function_call_output" or item.get("call_id") != payload.get("id"):
                        raise ValueError("tool input item does not match its call")
                    output = _read_artifact(artifacts, run_id, payload["output_ref"]) if payload.get("output_ref") else None
                    if json.loads(item["output"]) != {"ok": payload.get("ok"), "output": output, "error": payload.get("error")}:
                        raise ValueError("tool input item does not match its recorded result")
                histories.setdefault(event.role, []).append((activation, event.type, item))
        except (AttributeError, KeyError, TypeError, ValueError, OSError) as exc:
            notes.append(f"event {event.seq}: {exc}")
    if not attempted:
        notes.append("no model request attempts recorded")
    return {
        "status": "unverified" if notes else "verified",
        "request_count": len(attempted),
        "prepared_count": sum(steps.values()),
        "activation_count": len(steps),
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
        if "proposal_contract" not in injected:
            ok = False
            notes.append(f"{department}: proposal_contract was not injected")
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
    for department in ("engineering", "quality"):
        valid = [receipt for receipt in receipts
                 if receipt.get("department") == department and receipt.get("exit_code") == 0
                 and not receipt.get("tree_changed") and receipt.get("activation_id")
                 and receipt.get("snapshot_hash") == snapshot and spec is not None
                 and receipt.get("product_spec_hash") == spec.content_hash
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
