"""run_solo — assemble provider + client + workspace + agent loop for solo mode.

CLI:
    python -m harness.run_solo "<task>" [--run-dir runs/<ts>] [--max-steps N] [--max-calls N]
"""

from __future__ import annotations

import argparse
import copy
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .agent_loop import LoopStopped
from .artifacts import EventWriter, _write_jsonl_atomic, write_json_atomic
from .contracts import SUBMIT_DONE, TERMINAL_TOOL_DEFS, TicketValidationError, validate_payload
from .llm import LlmClient
from .local_tools import LocalToolRuntime, load_check_manifest
from .provider import load_provider, make_client
from .role_session import RoleSession
from .seed import seed_workspace
from .workspace import Workspace, diff_manifests

SOLO_SYSTEM = (
    "You are a software engineering agent working in an isolated workspace directory.\n"
    "You solve the user's task by using the provided tools to read, write, edit files "
    "and run commands.\n"
    "Work autonomously: investigate, implement, and verify your own work by running it.\n"
    "When the task is fully complete and you have verified it works, stop calling tools "
    "and give a brief final summary.\n"
    "Do not ask questions — make reasonable decisions and proceed."
)

SOLO_LOOP_SYSTEM = (
    "Keep a private persistent history for this solo run. The immutable original task, "
    "current workspace, and registered checks are the only sources of truth. Use only "
    "the provided local tools. Implement and verify the task, then end with submit_done; "
    "a natural-language claim of completion is not completion."
)


class SoloCompletionError(Exception):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code.replace("_", " "))
        self.code = code


@dataclass
class SoloResult:
    outcome: str
    stopped_reason: str
    session: RoleSession
    completion: dict | None
    calls: int
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    duration_ms: int
    tool_invocations: int
    transient_retry_attempts: int
    content_filter_retries: int
    per_role: dict


def run_solo_loop(
    llm,
    workspace: Workspace,
    runtime: LocalToolRuntime,
    task_id: str,
    task: str,
    *,
    max_steps: int = 40,
    on_event=None,
) -> SoloResult:
    if not isinstance(workspace, Workspace):
        raise TypeError("workspace must be a Workspace")
    if not isinstance(runtime, LocalToolRuntime) or runtime.workspace is not workspace:
        raise ValueError("runtime must use the supplied workspace")
    if type(task_id) is not str or not task_id:
        raise ValueError("task_id must be a non-empty string")
    if type(task) is not str or not task:
        raise ValueError("task must be a non-empty string")
    if type(max_steps) is not int or max_steps <= 0:
        raise ValueError("max_steps must be a positive integer")

    submit_def = next(
        copy.deepcopy(definition)
        for definition in TERMINAL_TOOL_DEFS
        if definition["function"]["name"] == SUBMIT_DONE
    )
    session = RoleSession("solo", SOLO_LOOP_SYSTEM, runtime.tool_defs(True) + [submit_def])
    initial_manifest = workspace.tree_manifest()
    usage_fields = (
        "calls",
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
        "llm_duration_ms",
    )
    usage_before = {
        field: copy.deepcopy(
            getattr(llm, "usage_by_role", {}).get("solo", {}).get(field, 0)
        )
        for field in usage_fields
    }
    retry_before = getattr(
        llm, "transient_retry_attempts", getattr(llm, "retry_attempts", 0)
    )
    completion = None
    receipt_baseline = {}
    outcome = "failed"
    stopped_reason = "system_error"
    tool_invocations = 0
    content_filter_retries = 0

    def external(event: dict) -> None:
        if on_event is None:
            return
        try:
            on_event(event)
        except LoopStopped:
            raise
        except Exception as exc:
            raise LoopStopped(
                f"system_error:event_callback:{type(exc).__name__}"
            ) from None

    def emit(event: dict) -> None:
        nonlocal tool_invocations, content_filter_retries
        event_type = event.get("type")
        if event_type == "tool_call":
            tool_invocations += 1
        elif event_type == "provider_retry" and event.get("reason") == "content_filter":
            content_filter_retries += 1
        if event_type == "llm_call":
            external(
                {
                    "type": "llm_call",
                    "role": "solo",
                    "step": event.get("step"),
                    "failed": bool(event.get("failed")),
                }
            )

    def submit_done(**payload):
        nonlocal completion
        try:
            try:
                validated = validate_payload("solo_done", payload)
            except TicketValidationError as error:
                raise SoloCompletionError("payload_invalid", str(error)) from error
            manifest = workspace.tree_manifest()
            tree_hash = workspace.tree_hash()
            changed_files = diff_manifests(initial_manifest, manifest)
            if validated["changed_files"] != changed_files:
                raise SoloCompletionError(
                    "changed_files_mismatch",
                    "changed_files must exactly match the workspace diff",
                )
            checks = []
            for name in validated["check_names"]:
                key = (name, tree_hash)
                receipt = runtime.receipt(name, tree_hash)
                if receipt is None or receipt is receipt_baseline.get(key):
                    raise SoloCompletionError(
                        "receipt_missing_current_activation",
                        f"check_names missing current activation receipt: {name}",
                    )
                if receipt.exit_code != 0 or receipt.timed_out:
                    raise SoloCompletionError(
                        "check_failed", f"check_names check did not pass: {name}"
                    )
                checks.append(asdict(receipt))
            candidate = {
                "kind": "solo_done",
                "payload": validated,
                "bindings": {
                    "code_tree_hash": tree_hash,
                    "files": [item["path"] for item in manifest],
                    "changed_files": changed_files,
                    "checks": checks,
                },
            }
        except SoloCompletionError as error:
            external(
                {
                    "type": "completion_rejected",
                    "kind": "solo_done",
                    "reason": error.code,
                }
            )
            return f"Error: {error}"
        external({"type": "completion_accepted", "kind": "solo_done"})
        completion = candidate
        return "Accepted solo_done"

    try:
        handoff = json.dumps(
            {
                "immutable_task_id": task_id,
                "immutable_original_task": task,
                "code_tree_hash": workspace.tree_hash(),
                "files": [item["path"] for item in initial_manifest],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        for activate_number in (1, 2):
            receipt_baseline = dict(runtime.receipts)
            external(
                {
                    "type": "solo_activation",
                    "role": "solo",
                    "activate": session.activates + 1,
                    "tree_hash": workspace.tree_hash(),
                }
            )
            handlers = runtime.handlers()
            handlers[SUBMIT_DONE] = submit_done
            loop = session.activate(
                handoff,
                llm=llm,
                handlers_ctx=workspace.dir,
                max_steps=max_steps,
                terminal_tools={SUBMIT_DONE},
                extra_handlers=handlers,
                on_event=emit,
            )
            if loop.stopped_reason == "terminal" and completion is not None:
                outcome = "done"
                stopped_reason = "completed"
                break
            if loop.stopped_reason not in {"natural", "terminal"}:
                stopped_reason = loop.stopped_reason
                break
            if activate_number == 2:
                stopped_reason = "role_incomplete"
                break
            handoff = json.dumps(
                {
                    "correction": "A legal submit_done with new current checks is required.",
                    "immutable_task_id": task_id,
                    "immutable_original_task": task,
                    "last_stop": loop.stopped_reason,
                    "code_tree_hash": workspace.tree_hash(),
                    "files": [item["path"] for item in workspace.tree_manifest()],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
    except LoopStopped as exc:
        stopped_reason = exc.reason
    except Exception as exc:
        stopped_reason = f"system_error:solo_activation:{type(exc).__name__}"

    usage_after = getattr(llm, "usage_by_role", {}).get("solo", {})
    metric = {
        field: usage_after.get(field, 0) - usage_before[field]
        for field in usage_fields
    }
    metric.update(
        activates=session.activates,
        message_count=len(session.messages),
        message_chars=sum(
            len(str(message.get("content") or "")) for message in session.messages
        ),
        duration_ms=metric["llm_duration_ms"],
    )
    retry_after = getattr(
        llm, "transient_retry_attempts", getattr(llm, "retry_attempts", 0)
    )
    try:
        external(
            {"type": "solo_stop", "reason": stopped_reason, "outcome": outcome}
        )
    except LoopStopped as exc:
        stopped_reason = exc.reason
        outcome = "failed"
        completion = None
    if outcome != "done":
        completion = None
    return SoloResult(
        outcome=outcome,
        stopped_reason=stopped_reason,
        session=session,
        completion=copy.deepcopy(completion),
        calls=metric["calls"],
        prompt_tokens=metric["prompt_tokens"],
        completion_tokens=metric["completion_tokens"],
        reasoning_tokens=metric["reasoning_tokens"],
        duration_ms=metric["llm_duration_ms"],
        tool_invocations=tool_invocations,
        transient_retry_attempts=retry_after - retry_before,
        content_filter_retries=content_filter_retries,
        per_role={"solo": metric},
    )


def run_solo(task: str, task_id: str, run_dir: str, seed_dir: str, checks_file: str, max_steps: int = 200, max_calls: int = 200, max_tokens: int | None = None, max_seconds: float = 5400, provider_path: str = "provider.md") -> dict:
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=False)
    if type(max_steps) is not int or max_steps <= 0:
        raise ValueError("max_steps must be a positive integer")

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
        result = run_solo_loop(llm, workspace, runtime, task_id, task, max_steps=max_steps, on_event=events.append)
    finally:
        events.close()

    if result.calls != sum(metric["calls"] for metric in result.per_role.values()):
        raise RuntimeError("accounting mismatch: per-role calls")
    event_calls = sum(line.count('\"type\":\"llm_call\"') for line in (root / "events.jsonl").read_text(encoding="utf-8").splitlines())
    if result.calls != event_calls:
        raise RuntimeError("accounting mismatch: event calls")

    _write_jsonl_atomic(root / "sessions" / "solo.jsonl", result.session.messages)
    manifest = workspace.tree_manifest()
    final_hash = workspace.tree_hash()
    write_json_atomic(root / "final_tree.json", manifest)
    llm_duration_ms = sum(metric["llm_duration_ms"] for metric in result.per_role.values())
    summary = {
        "schema_version": 1,
        "task_id": task_id,
        "treatment": "S",
        "model": cfg["model"],
        "outcome": result.outcome,
        "stopped_reason": result.stopped_reason,
        "limits": {"max_steps": max_steps, "max_calls": max_calls, "max_tokens": max_tokens, "max_seconds": max_seconds},
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
        "completion": result.completion,
    }
    write_json_atomic(root / "summary.json", summary)
    return summary


def _print_summary(summary: dict) -> None:
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="harness.run_solo")
    parser.add_argument("task")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--seed-dir", required=True)
    parser.add_argument("--checks-file", required=True)
    parser.add_argument("--max-steps", type=int, default=200)
    parser.add_argument("--max-calls", type=int, default=200)
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--max-seconds", type=float, default=5400)
    parser.add_argument("--provider-path", default="provider.md")
    args = parser.parse_args()
    _print_summary(run_solo(**vars(args)))


if __name__ == "__main__":
    main()
