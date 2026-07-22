"""Shared setup and artifact finalization for S/T runners."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import shutil
import stat

from .artifacts import EventWriter, _write_jsonl_atomic, write_json_atomic
from .contracts import verify_ticket
from .local_tools import LocalToolRuntime
from .seed import seed_workspace
from .workspace import Workspace, _is_link_or_junction, _require_link_free_components


@dataclass(frozen=True)
class RunnerSetup:
    root: Path
    cfg: dict
    llm: object
    workspace: Workspace
    runtime: LocalToolRuntime
    events: EventWriter


def ensure_run_dir_available(run_dir: str) -> Path:
    if type(run_dir) is not str or not run_dir:
        raise ValueError("run_dir must be a non-empty string")
    root = Path(run_dir)
    _require_link_free_components(str(root), "run_dir", _is_link_or_junction)
    if os.path.lexists(root):
        raise FileExistsError(root)
    return root


def _existing_path(value: object, name: str, *, directory: bool) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"{name} must be a non-empty string")
    absolute = _require_link_free_components(value, name, _is_link_or_junction)
    try:
        mode = os.lstat(absolute).st_mode
    except FileNotFoundError:
        raise FileNotFoundError(f"{name} not found: {value}") from None
    if (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)) is False:
        raise ValueError(f"{name} must be an existing {'directory' if directory else 'regular file'}")
    return absolute


def prepare_runner(
    task: str, task_id: str, run_dir: str, seed_dir: str, checks_file: str,
    max_steps: int, max_calls: int, max_tokens: int | None, max_seconds: float,
    provider_path: str, *, load_provider, make_client, llm_class, load_check_manifest,
    max_reworks: int | None = None,
) -> RunnerSetup:
    root = ensure_run_dir_available(run_dir)
    if type(task) is not str or not task or type(task_id) is not str or not task_id:
        raise ValueError("task and task_id must be non-empty strings")
    for name, value in (("max_steps", max_steps), ("max_calls", max_calls)):
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if type(max_seconds) not in (int, float) or not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError("max_seconds must be finite and positive")
    if max_tokens is not None and (type(max_tokens) is not int or max_tokens <= 0):
        raise ValueError("max_tokens must be a positive integer or None")
    if max_reworks is not None and (type(max_reworks) is not int or max_reworks < 0):
        raise ValueError("max_reworks must be a nonnegative integer")
    seed = _existing_path(seed_dir, "seed_dir", directory=True)
    checks_path = _existing_path(checks_file, "checks_file", directory=False)
    provider = _existing_path(provider_path, "provider_path", directory=False)
    checks, protected = load_check_manifest(checks_path)
    cfg = load_provider(provider)
    client = make_client(cfg)
    llm = llm_class(client, cfg["model"], max_calls=max_calls, max_tokens=max_tokens, max_seconds=max_seconds)

    root.mkdir(parents=True, exist_ok=False)
    try:
        workspace = Workspace(str(root / "workspace"))
        (root / "sessions").mkdir()
        (root / "tickets").mkdir()
        runtime = LocalToolRuntime(workspace, checks, protected, root / "checks")
        seed_workspace(seed, workspace.dir)
        events = EventWriter(root / "events.jsonl")
        return RunnerSetup(root, cfg, llm, workspace, runtime, events)
    except Exception:
        if os.path.lexists(root) and not _is_link_or_junction(root):
            shutil.rmtree(root)
        raise


def validate_accounting(result, events_path: Path) -> None:
    if result.calls != sum(metric["calls"] for metric in result.per_role.values()):
        raise RuntimeError("accounting mismatch: per-role calls")
    event_calls = sum(
        json.loads(line).get("type") == "llm_call"
        for line in events_path.read_text(encoding="utf-8").splitlines()
    )
    if result.calls != event_calls:
        raise RuntimeError("accounting mismatch: event calls")


def common_summary(task_id: str, treatment: str, model: str, limits: dict, result, manifest: list[dict], final_hash: str, extras: dict) -> dict:
    return {
        "schema_version": 1, "task_id": task_id, "treatment": treatment,
        "model": model, "outcome": result.outcome, "stopped_reason": result.stopped_reason,
        "limits": limits, "calls": result.calls, "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens, "reasoning_tokens": result.reasoning_tokens,
        "transient_retry_attempts": result.transient_retry_attempts,
        "content_filter_retries": result.content_filter_retries,
        "tool_invocations": result.tool_invocations, "duration_ms": result.duration_ms,
        "llm_duration_ms": sum(metric["llm_duration_ms"] for metric in result.per_role.values()),
        "final_tree_hash": final_hash, "final_tree": manifest, "per_role": result.per_role,
        **extras,
    }


def finalize_artifacts(setup: RunnerSetup, result, *, task_id: str, treatment: str, limits: dict, sessions: dict[str, list[dict]], tickets: list[dict], extras: dict) -> dict:
    root = setup.root
    destinations = [*(root / "sessions" / f"{role}.jsonl" for role in sessions), *(root / "tickets" / f"{ticket['ticket_id']}.json" for ticket in tickets), root / "final_tree.json", root / "summary.json"]
    if any(os.path.lexists(path) or os.path.lexists(path.with_name(path.name + ".tmp")) for path in destinations):
        raise FileExistsError("artifact destination already exists")
    for ticket in tickets:
        verify_ticket(ticket)
    for role, messages in sessions.items():
        _write_jsonl_atomic(root / "sessions" / f"{role}.jsonl", messages)
    for ticket in tickets:
        write_json_atomic(root / "tickets" / f"{ticket['ticket_id']}.json", ticket)
    manifest = setup.workspace.tree_manifest()
    final_hash = setup.workspace.tree_hash()
    write_json_atomic(root / "final_tree.json", manifest)
    summary = common_summary(task_id, treatment, setup.cfg["model"], limits, result, manifest, final_hash, extras)
    write_json_atomic(root / "summary.json", summary)
    return summary
