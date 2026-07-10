"""run_multi — assemble provider + client + workspace + multi-stage orchestrator.

CLI:
    python -m harness.run_multi "<task>" [--run-dir runs/<ts>] \
        [--max-rounds N] [--max-steps N] [--max-calls N]

Summary is同构 with run_solo plus mode="multi", outcome, rounds, per-stage
cost, and the final verdict.
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


def run_multi_cli(
    task: str,
    run_dir: str,
    max_rounds: int = 4,
    max_steps: int = 40,
    max_calls: int | None = None,
    provider_path: str = "provider.md",
) -> dict:
    os.makedirs(run_dir, exist_ok=False)
    cfg = load_provider(provider_path)
    client = make_client(cfg)
    llm = LlmClient(client, cfg["model"], max_calls=max_calls)

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
        )
    finally:
        events_file.close()

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
    )
    _print_summary(summary)
    print(f"\nrun_dir: {run_dir}")


if __name__ == "__main__":
    main()
