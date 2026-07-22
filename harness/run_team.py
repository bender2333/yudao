"""CLI assembly for the three-department treatment."""

from __future__ import annotations

import argparse
from pathlib import Path

from .artifacts import EventWriter, _write_jsonl_atomic, write_json_atomic
from .llm import LlmClient
from .local_tools import LocalToolRuntime, load_check_manifest
from .provider import load_provider, make_client
from .seed import seed_workspace
from .workspace import Workspace
from .work_order_loop import run_team


def _positive(name: str, value, *, allow_zero: bool = False) -> None:
    if type(value) not in (int, float) or (value < 0 if allow_zero else value <= 0):
        qualifier = "nonnegative" if allow_zero else "positive"
        raise ValueError(f"{name} must be {qualifier}")


def run_team_cli(task: str, task_id: str, run_dir: str, seed_dir: str, checks_file: str, max_steps: int = 40, max_reworks: int = 8, max_calls: int = 200, max_tokens: int | None = None, max_seconds: float = 5400, provider_path: str = "provider.md") -> dict:
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=False)
    _positive("max_steps", max_steps)
    _positive("max_reworks", max_reworks, allow_zero=True)
    _positive("max_calls", max_calls)
    if max_tokens is not None:
        _positive("max_tokens", max_tokens)
    _positive("max_seconds", max_seconds)

    cfg = load_provider(provider_path)
    client = make_client(cfg)
    llm = LlmClient(client, cfg["model"], max_calls=max_calls, max_tokens=max_tokens, max_seconds=max_seconds)
    workspace = Workspace(str(root / "workspace"))
    (root / "sessions").mkdir()
    (root / "tickets").mkdir()
    checks, protected = load_check_manifest(checks_file)
    runtime = LocalToolRuntime(workspace, checks, protected, root / "checks")
    seed_workspace(seed_dir, workspace.dir)
    events = EventWriter(root / "events.jsonl")
    try:
        result = run_team(
            llm, workspace, runtime, task_id, task,
            max_reworks=max_reworks,
            max_steps=max_steps,
            on_event=events.append,
        )
    finally:
        events.close()

    if result.calls != sum(metric["calls"] for metric in result.per_role.values()):
        raise RuntimeError("accounting mismatch: per-role calls")
    event_calls = sum(
        json_line.count('"type":"llm_call"')
        for json_line in (root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    )
    if result.calls != event_calls:
        raise RuntimeError("accounting mismatch: event calls")

    for role in ("requirements", "engineering", "quality"):
        _write_jsonl_atomic(root / "sessions" / f"{role}.jsonl", result.sessions[role].messages)
    for ticket in result.tickets:
        write_json_atomic(root / "tickets" / f"{ticket['ticket_id']}.json", ticket)
    manifest = workspace.tree_manifest()
    final_hash = workspace.tree_hash()
    write_json_atomic(root / "final_tree.json", manifest)
    llm_duration_ms = sum(metric["llm_duration_ms"] for metric in result.per_role.values())
    summary = {
        "schema_version": 1,
        "task_id": task_id,
        "treatment": "T",
        "model": cfg["model"],
        "outcome": result.outcome,
        "stopped_reason": result.stopped_reason,
        "limits": {
            "max_steps": max_steps,
            "max_reworks": max_reworks,
            "max_calls": max_calls,
            "max_tokens": max_tokens,
            "max_seconds": max_seconds,
        },
        "calls": result.calls,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "reasoning_tokens": result.reasoning_tokens,
        "transient_retry_attempts": result.transient_retry_attempts,
        "content_filter_retries": result.content_filter_retries,
        "tool_invocations": result.tool_invocations,
        "duration_ms": result.duration_ms,
        "llm_duration_ms": llm_duration_ms,
        "final_tree_hash": final_hash,
        "final_tree": manifest,
        "per_role": result.per_role,
        "tickets": [ticket["ticket_id"] for ticket in result.tickets],
        "reworks": result.reworks,
        "transitions": result.transitions,
    }
    write_json_atomic(root / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(prog="harness.run_team")
    parser.add_argument("task")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--seed-dir", required=True)
    parser.add_argument("--checks-file", required=True)
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--max-reworks", type=int, default=8)
    parser.add_argument("--max-calls", type=int, default=200)
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--max-seconds", type=float, default=5400)
    parser.add_argument("--provider-path", default="provider.md")
    args = parser.parse_args()
    run_team_cli(**vars(args))


if __name__ == "__main__":
    main()
