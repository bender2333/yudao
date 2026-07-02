"""run_solo — assemble provider + client + workspace + agent loop for solo mode.

CLI:
    python -m harness.run_solo "<task>" [--run-dir runs/<ts>] [--max-steps N] [--max-calls N]
"""

from __future__ import annotations

import argparse
import json
import os
import time

from .agent_loop import run_agent_loop
from .llm import LlmClient
from .provider import load_provider, make_client
from .tools import TOOL_DEFS
from .workspace import Workspace

SOLO_SYSTEM = (
    "You are a software engineering agent working in an isolated workspace directory.\n"
    "You solve the user's task by using the provided tools to read, write, edit files "
    "and run commands.\n"
    "Work autonomously: investigate, implement, and verify your own work by running it.\n"
    "When the task is fully complete and you have verified it works, stop calling tools "
    "and give a brief final summary.\n"
    "Do not ask questions — make reasonable decisions and proceed."
)


def run_solo(
    task: str,
    run_dir: str,
    max_steps: int = 40,
    max_calls: int | None = None,
    provider_path: str = "provider.md",
) -> dict:
    os.makedirs(run_dir, exist_ok=True)
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
        result = run_agent_loop(
            llm=llm,
            system=SOLO_SYSTEM,
            user=task,
            tools=TOOL_DEFS,
            handlers_ctx=ws.dir,
            max_steps=max_steps,
            on_event=on_event,
        )
    finally:
        events_file.close()

    summary = {
        "task": task,
        "model": cfg["model"],
        "stopped_reason": result.stopped_reason,
        "steps": result.steps,
        "tool_invocations": result.tool_invocations,
        "calls": result.calls,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "reasoning_tokens": result.reasoning_tokens,
        "duration_ms": result.duration_ms,
        "files": ws.snapshot_files(),
        "final_text": result.final_text,
    }
    with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return summary


def _print_summary(summary: dict) -> None:
    print("=" * 60)
    print(f"model:            {summary['model']}")
    print(f"stopped_reason:   {summary['stopped_reason']}")
    print(f"steps:            {summary['steps']}")
    print(f"tool_invocations: {summary['tool_invocations']}")
    print(f"calls:            {summary['calls']}")
    print(
        f"tokens:           prompt={summary['prompt_tokens']} "
        f"completion={summary['completion_tokens']} "
        f"reasoning={summary['reasoning_tokens']}"
    )
    print(f"duration_ms:      {summary['duration_ms']}")
    print(f"files:            {summary['files']}")
    print("-" * 60)
    print("final_text:")
    print(summary["final_text"])
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(prog="harness.run_solo")
    parser.add_argument("task", help="Task description for the agent.")
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--max-calls", type=int, default=None)
    args = parser.parse_args()

    run_dir = args.run_dir or os.path.join("runs", time.strftime("%Y%m%d-%H%M%S"))
    summary = run_solo(
        task=args.task,
        run_dir=run_dir,
        max_steps=args.max_steps,
        max_calls=args.max_calls,
    )
    _print_summary(summary)
    print(f"\nrun_dir: {run_dir}")


if __name__ == "__main__":
    main()
