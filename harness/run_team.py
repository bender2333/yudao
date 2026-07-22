"""CLI assembly for the three-department treatment."""

from __future__ import annotations

import argparse

from .llm import LlmClient
from .local_tools import load_check_manifest
from .provider import load_provider, make_client
from .runner_common import finalize_artifacts, prepare_runner, validate_accounting
from .work_order_loop import run_team





def run_team_cli(task: str, task_id: str, run_dir: str, seed_dir: str, checks_file: str, max_steps: int = 40, max_reworks: int = 8, max_calls: int = 200, max_tokens: int | None = None, max_seconds: float = 5400, provider_path: str = "provider.md") -> dict:
    setup = prepare_runner(
        task, task_id, run_dir, seed_dir, checks_file, max_steps, max_calls,
        max_tokens, max_seconds, provider_path, load_provider=load_provider,
        make_client=make_client, llm_class=LlmClient,
        load_check_manifest=load_check_manifest, max_reworks=max_reworks,
    )
    try:
        result = run_team(
            setup.llm, setup.workspace, setup.runtime, task_id, task,
            max_reworks=max_reworks, max_steps=max_steps,
            on_event=setup.events.append,
        )
    finally:
        setup.events.close()
    validate_accounting(result, setup.root / "events.jsonl")
    return finalize_artifacts(
        setup, result, task_id=task_id, treatment="T",
        limits={"max_steps": max_steps, "max_reworks": max_reworks, "max_calls": max_calls, "max_tokens": max_tokens, "max_seconds": max_seconds},
        sessions={role: session.messages for role, session in result.sessions.items()},
        tickets=result.tickets,
        extras={"tickets": [ticket["ticket_id"] for ticket in result.tickets], "reworks": result.reworks, "transitions": result.transitions},
    )


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
