"""组装 provider、共享预算 client、workspace 与多角色编排器。

CLI:
    python -m harness.run_multi "<task>" [--run-dir runs/<ts>] \
        [--max-rounds N] [--max-steps N] [--max-calls N] \
        [--max-tokens N] [--max-seconds N] \
        [--session-model cold|persistent]

summary 与 solo 共享预算口径，并增加 outcome、rounds、per-role、per-stage、
session_model 与最终 verdict。
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime

from .llm import LlmClient
from .orchestrator import run_multi
from .provider import load_provider, make_client
from .workspace import Workspace

_SESSION_FILES = {
    "UNDERSTAND": "understand.jsonl",
    "PLAN_EXECUTE": "plan_execute.jsonl",
    "VERIFY": "verify.jsonl",
}


def _write_jsonl(path: str, rows) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            )


def run_multi_cli(
    task: str,
    run_dir: str,
    max_rounds: int = 4,
    max_steps: int = 40,
    max_calls: int | None = None,
    max_tokens: int | None = None,
    max_seconds: float | None = None,
    provider_path: str = "provider.md",
    session_model: str = "persistent",
) -> dict:
    os.makedirs(run_dir, exist_ok=False)
    cfg = load_provider(provider_path)
    client = make_client(cfg)
    llm = LlmClient(
        client,
        cfg["model"],
        max_calls=max_calls,
        max_tokens=max_tokens,
        max_seconds=max_seconds,
    )

    ws = Workspace(os.path.join(run_dir, "workspace"))

    events_path = os.path.join(run_dir, "events.jsonl")
    events_file = open(events_path, "w", encoding="utf-8")

    def on_event(event: dict) -> None:
        events_file.write(json.dumps(event, ensure_ascii=False) + "\n")
        events_file.flush()

    try:
        result = run_multi(
            llm=llm,
            workspace=ws,
            task=task,
            max_rounds=max_rounds,
            max_steps=max_steps,
            on_event=on_event,
            session_model=session_model,
        )
    finally:
        events_file.close()

    sessions_dir = os.path.join(run_dir, "sessions")
    os.makedirs(sessions_dir, exist_ok=False)
    for role, filename in _SESSION_FILES.items():
        _write_jsonl(
            os.path.join(sessions_dir, filename),
            result.sessions[role].messages,
        )
    _write_jsonl(os.path.join(run_dir, "handoffs.jsonl"), result.handoffs)

    per_stage = [
        {
            "stage": s.stage,
            "stopped_reason": s.loop.stopped_reason,
            "steps": s.loop.steps,
            "tool_invocations": s.loop.tool_invocations,
            "calls": s.loop.calls,
            "prompt_tokens": s.loop.prompt_tokens,
            "completion_tokens": s.loop.completion_tokens,
            "reasoning_tokens": s.loop.reasoning_tokens,
            "duration_ms": s.loop.duration_ms,
            "terminal": (s.terminal_call or {}).get("name"),
        }
        for s in result.stages
    ]

    summary = {
        "task": task,
        "mode": "multi",
        "session_model": result.session_model,
        "model": cfg["model"],
        "outcome": result.outcome,
        "rounds": result.rounds,
        "activates": result.activates,
        "consults": result.consults,
        "consult_errors": result.consult_errors,
        "handoff_count": len(result.handoffs),
        "budget": {
            "max_calls": max_calls,
            "max_tokens": max_tokens,
            "max_seconds": max_seconds,
        },
        "verdict": result.verdict,
        "understanding": result.understanding,
        "stopped_reason": result.stopped_reason,
        "steps": sum(s.loop.steps for s in result.stages),
        "tool_invocations": result.tool_invocations,
        "calls": result.calls,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "reasoning_tokens": result.reasoning_tokens,
        "duration_ms": result.duration_ms,
        "files": ws.snapshot_files(),
        "per_role": result.per_role,
        "per_stage": per_stage,
        "final_text": result.stages[-1].loop.final_text if result.stages else "",
    }
    with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return summary


def _print_summary(summary: dict) -> None:
    print("=" * 60)
    print(f"model:            {summary['model']}")
    print(f"mode:             {summary['mode']}")
    print(f"session_model:    {summary['session_model']}")
    print(f"outcome:          {summary['outcome']}")
    print(f"rounds:           {summary['rounds']}")
    print(f"verdict:          {summary['verdict']}")
    print(f"calls:            {summary['calls']}")
    print(
        f"tokens:           prompt={summary['prompt_tokens']} "
        f"completion={summary['completion_tokens']} "
        f"reasoning={summary['reasoning_tokens']}"
    )
    print(f"duration_ms:      {summary['duration_ms']}")
    print(f"files:            {summary['files']}")
    print("-" * 60)
    print("per_stage:")
    for s in summary["per_stage"]:
        print(
            f"  {s['stage']:<13} stop={s['stopped_reason']:<9} "
            f"steps={s['steps']} terminal={s['terminal']}"
        )
    print("-" * 60)
    print("final_text:")
    print(summary["final_text"])
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(prog="harness.run_multi")
    parser.add_argument("task", help="Task description for the agent.")
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--max-rounds", type=int, default=4)
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--max-calls", type=int, default=None)
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--max-seconds", type=float, default=None)
    parser.add_argument(
        "--session-model",
        choices=("cold", "persistent"),
        default="persistent",
    )
    args = parser.parse_args()

    run_dir = args.run_dir or os.path.join(
        "runs", datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-multi"
    )
    summary = run_multi_cli(
        task=args.task,
        run_dir=run_dir,
        max_rounds=args.max_rounds,
        max_steps=args.max_steps,
        max_calls=args.max_calls,
        max_tokens=args.max_tokens,
        max_seconds=args.max_seconds,
        session_model=args.session_model,
    )
    _print_summary(summary)
    print(f"\nrun_dir: {run_dir}")


if __name__ == "__main__":
    main()
