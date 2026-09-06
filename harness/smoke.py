"""真实 provider 三部门 smoke。读取环境变量，不读取 provider.md，不用 fake 冒充成功。"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .adapters.omp import OmpConfig, OmpRpcAdapter
from .adapters.omp_isolation import evaluate_capture
from .event_store import EventStore
from .models import EventType
from .projection import project_run
from .runtime import LoopSystem


DEFAULT_DIR = Path(".yudao") / "provider-validation"

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
    config = OmpConfig.from_env()
    if os_timeout_override() is not None:
        config.timeout_sec = os_timeout_override() or config.timeout_sec
    adapter = OmpRpcAdapter(config)
    availability = adapter.availability()
    previous = _read_report(data_dir)
    report: dict[str, Any] = {
        "provider": config.provider,
        "model": config.model,
        "adapter": adapter.name,
        "available": availability.available,
        "scenarios": dict((previous or {}).get("scenarios") or {}),
    }
    if not availability.available:
        report["error"] = availability.message
        report["stop_reason"] = availability.reason
        _write_report(data_dir, report)
        return report
    selected = scenarios or ["happy", "ask"]
    system = LoopSystem(data_dir, adapter)
    for name in selected:
        report["scenarios"][name] = _run_scenario(system, name)
    _write_report(data_dir, report)
    return report


def os_timeout_override() -> float | None:
    import os

    raw = os.environ.get("YUDAO_SMOKE_TIMEOUT")
    if not raw:
        return 600.0
    try:
        return float(raw)
    except ValueError:
        return 600.0


def _run_scenario(system: LoopSystem, name: str) -> dict[str, Any]:
    task = HAPPY_TASK if name == "happy" else ASK_TASK
    max_cycles = 12 if name == "happy" else 16
    run_id = system.create_run(
        task,
        max_cycles=max_cycles,
        token_budget=250_000,
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
    isolation = isolation_fields(system.store, run_id)
    return {
        "run_id": run_id,
        "scenario": scenario,
        "phase": projection.phase,
        "outcome": projection.outcome,
        "stop_reason": projection.stop_reason,
        "error": projection.error,
        "provider": projection.provider,
        "model": projection.model,
        "route": list(projection.transitions),
        "ask_count": projection.ask_count,
        "rework_count": projection.rework_count,
        "cycle_count": projection.cycle_count,
        "token_used": projection.token_used,
        "tool_calls": tool_calls,
        "check_receipts": receipts,
        "replay_consistent": replayed.canonical_state() == projection.canonical_state(),
        **isolation,
        "fake_used": projection.provider == "fake",
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


def isolation_fields(store: EventStore, run_id: str) -> dict[str, Any]:
    manifest_ok, manifest_notes = _manifest_boundary(store, run_id)
    launches = host_launch_records(store, run_id)
    capture = evaluate_capture(launches)
    binding_notes = _launch_binding_notes(store, run_id, launches)
    if binding_notes:
        capture = {"status": "unverified", "evidence": None, "notes": binding_notes}
    verified = capture.get("status") == "verified"
    isolated = bool(manifest_ok and verified)
    notes = [f"manifest: {item}" for item in manifest_notes]
    notes.append(f"omp policy capture: {capture.get('status')}")
    notes.extend(str(item) for item in (capture.get("notes") or []))
    if not isolated:
        notes.append("isolation not verified; manifest boundary is not sufficient")
    policy = launches[-1] if launches else {
        "recorded": False,
        "policy_id": None,
        "omp_generated": ["environment", "footer"],
        "byte_identical_to_manifest": False,
    }
    return {
        "manifest_boundary": manifest_ok,
        "manifest_boundary_notes": manifest_notes,
        "omp_launch_policy": policy,
        "omp_policy_capture": capture,
        "context_isolated": isolated,
        "context_isolation_notes": notes,
    }


def host_launch_records(store: EventStore, run_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for event in store.list_events(run_id):
        if event.type != EventType.CONTEXT_ASSEMBLED:
            continue
        payload = event.payload or {}
        if payload.get("host_launch") or payload.get("kind") == "host_launch_diagnostics":
            record = dict(payload)
            if event.session_id != payload.get("session_id") or event.context_digest != payload.get("context_digest"):
                record["verifiable"] = False
                record["unverifiable_reasons"] = ["宿主诊断与持久事件的 session/context 绑定不符"]
            records.append(record)
    return records


def _launch_binding_notes(store: EventStore, run_id: str, launches: list[dict[str, Any]]) -> list[str]:
    expected = []
    for event in store.list_events(run_id):
        payload = event.payload
        if event.type == EventType.CONTEXT_ASSEMBLED and not payload.get("usage_only") and not payload.get("host_launch"):
            expected.append((payload.get("activation_id"), event.session_id, event.context_digest))
    actual = [(item.get("activation_id"), item.get("session_id"), item.get("context_digest")) for item in launches]
    if not expected or any(not all(isinstance(value, str) and value for value in binding) for binding in expected):
        return ["装配事件缺少完整 activation/session/context 绑定"]
    if any(not all(isinstance(value, str) and value for value in binding) for binding in actual):
        return ["实际启动诊断缺少完整 activation/session/context 绑定"]
    if len(set(expected)) != len(expected) or len(actual) != len(expected) or set(actual) != set(expected):
        return ["每次上下文装配都需要唯一且匹配的实际 OMP 启动诊断"]
    for record in launches:
        sources = record.get("prompt_sources") or {}
        prompt = sources.get("host_system_prompt") or {}
        if record.get("run_id") != run_id or prompt.get("manifest_digest") != record.get("context_digest"):
            return ["实际启动与 run 或系统提示的上下文绑定不符"]
    return []


def _manifest_boundary(store: EventStore, run_id: str) -> tuple[bool, list[str]]:
    notes: list[str] = []
    ok = True
    seen = 0
    for event in store.list_events(run_id):
        if event.type != EventType.CONTEXT_ASSEMBLED:
            continue
        if event.payload.get("usage_only") or event.payload.get("host_launch"):
            continue
        seen += 1
        injected = {item.get("source") for item in event.payload.get("injected", [])}
        excluded = {item.get("source") for item in event.payload.get("excluded", [])}
        department = event.payload.get("department")
        if "other_department_transcript" in injected or "historical_transcript" in injected:
            ok = False
            notes.append(f"{department}: injected a forbidden transcript source")
        for required in ("other_department_transcript", "historical_transcript", "omp_autodiscovery"):
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


def _read_report(data_dir: Path) -> dict[str, Any] | None:
    path = data_dir / "smoke-report.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


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
                f"- provider/model: `{scenario.get('provider')}` / `{scenario.get('model')}`",
                f"- route: `{' | '.join(scenario.get('route') or [])}`",
                f"- asks: `{scenario.get('ask_count')}` reworks: `{scenario.get('rework_count')}`",
                f"- replay consistent: `{scenario.get('replay_consistent')}`",
                f"- manifest boundary: `{scenario.get('manifest_boundary')}`",
                f"- omp launch policy: `{((scenario.get('omp_launch_policy') or {}).get('policy_id'))}`",
                f"- omp policy capture: `{(scenario.get('omp_policy_capture') or {}).get('status', 'unverified')}`",
                f"- context isolated: `{scenario.get('context_isolated')}`",
                f"- fake used: `{scenario.get('fake_used')}`",
                f"- delivery files: `{', '.join(scenario.get('delivery_files') or [])}`",
                f"- qa verdict: `{scenario.get('qa_verdict')}`",
                "",
            ]
        )
        if scenario.get("error"):
            lines.append(f"- error: {scenario['error']}")
            lines.append("")
        policy = scenario.get("omp_launch_policy") or {}
        if policy:
            lines.append(
                f"- omp generated sections: `{', '.join(policy.get('omp_generated') or [])}`"
            )
            lines.append(
                f"- byte identical to manifest: `{policy.get('byte_identical_to_manifest', False)}`"
            )
            lines.append("")
        for note in scenario.get("context_isolation_notes") or []:
            lines.append(f"- isolation note: {note}")
        if scenario.get("context_isolation_notes"):
            lines.append("")
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
        if not scenario.get("check_receipts"):
            return 1
    ask = scenarios.get("ask")
    if ask is not None and ask.get("ask_count", 0) < 1:
        return 1
    return 0
