"""orchestrator — the multi-mode state machine (spec §2).

UNDERSTAND -> PLAN_EXECUTE -> VERIFY, driven by the verify verdict:
  pass                -> DONE
  reject_execution    -> PLAN_EXECUTE (round += 1)
  reject_understanding-> UNDERSTAND   (round += 1)
Exhausting MAX_ROUNDS, or any stage that ends without its terminal_call,
-> ESCALATED.

Each stage is a fresh run_agent_loop over the SAME workspace + full toolset,
plus that stage's terminal tool. The orchestrator assembles each stage's
initial user message (context封装, spec §4): verify only sees the
understanding + file listing, never upstream implementation prose.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .agent_loop import run_agent_loop
from .stage_tools import (
    PLAN_TERMINAL,
    STAGE_TOOL_DEFS,
    UNDERSTAND_TERMINAL,
    VERIFY_TERMINAL,
    parse_understanding,
)
from .tools import TOOL_DEFS

UNDERSTAND_SYSTEM = (
    "You are the UNDERSTANDING stage. Investigate the task and the existing workspace "
    "using tools. Your job is NOT to implement — it is to deeply understand WHAT must "
    "be true when the task is done. When ready, call submit_understanding with a crisp "
    "summary, the concrete requirements, the constraints, and the observable "
    "done-criteria. Do not write solution code."
)

PLAN_SYSTEM = (
    "You are the PLAN & EXECUTE stage, given the upstream understanding. Plan and "
    "implement it for real using tools (write/edit files, run commands to check your "
    "work). Realize every done-criterion as actually-working behavior. When complete "
    "and you have run it to confirm, call submit_ready with a brief note of what you "
    "built and how you verified it."
)

VERIFY_SYSTEM = (
    "You are the VERIFICATION stage, given the upstream understanding (source of truth "
    'for "done") and the workspace. Independently verify whether the implementation '
    "satisfies the done-criteria: read delivered files and RUN functional checks "
    "(write/execute test scripts, invoke the program, inspect outputs). Judge from real "
    "execution evidence, not code reading alone. Then call submit_verdict: "
    'status="pass" if every criterion is met with evidence; "reject_execution" if the '
    'implementation fails a criterion (cite observed vs expected); '
    '"reject_understanding" if the understanding itself is wrong/insufficient (cite '
    "why). Do not modify the implementation; your role is to judge and route."
)


@dataclass
class StageRun:
    stage: str
    loop: object  # LoopResult
    terminal_call: dict | None


@dataclass
class MultiResult:
    outcome: str  # "done" | "escalated"
    rounds: int
    stages: list = field(default_factory=list)
    understanding: str | None = None
    verdict: dict | None = None
    # aggregated cost across all stages
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    duration_ms: int = 0
    tool_invocations: int = 0


def _file_listing(workspace) -> str:
    files = workspace.snapshot_files()
    if not files:
        return "(workspace is empty)"
    return "\n".join(f"- {name} ({size} bytes)" for name, size in sorted(files.items()))


def _understand_user(task: str, workspace, reject_reason: str | None) -> str:
    parts = [
        f"# Original task\n{task}\n",
        f"# Workspace files\n{_file_listing(workspace)}\n",
    ]
    if reject_reason:
        parts.append(
            "# Previous verification rejected the understanding\n"
            f"{reject_reason}\n"
        )
    return "\n".join(parts)


def _plan_user(understanding: str, workspace, reject_reason: str | None) -> str:
    parts = [
        f"# Understanding (from the upstream stage)\n{understanding}\n",
        f"# Workspace files\n{_file_listing(workspace)}\n",
    ]
    if reject_reason:
        parts.append(
            "# Previous verification rejected the execution\n"
            f"{reject_reason}\n"
        )
    return "\n".join(parts)


def _verify_user(understanding: str, workspace) -> str:
    return (
        f"# Understanding (source of truth for what 'done' means)\n{understanding}\n\n"
        f"# Workspace files\n{_file_listing(workspace)}\n"
    )


def _accumulate(agg: MultiResult, loop) -> None:
    agg.calls += loop.calls
    agg.prompt_tokens += loop.prompt_tokens
    agg.completion_tokens += loop.completion_tokens
    agg.reasoning_tokens += loop.reasoning_tokens
    agg.duration_ms += loop.duration_ms
    agg.tool_invocations += loop.tool_invocations


def _run_stage(
    llm, stage, system, user, workspace, max_steps, on_event, round_no, result
):
    """Run one stage loop; emit stage_start/stage_end; record + accumulate."""
    terminal = {
        "UNDERSTAND": UNDERSTAND_TERMINAL,
        "PLAN_EXECUTE": PLAN_TERMINAL,
        "VERIFY": VERIFY_TERMINAL,
    }[stage]
    stage_tools = TOOL_DEFS + STAGE_TOOL_DEFS[stage]

    if on_event is not None:
        on_event({"type": "stage_start", "stage": stage, "round": round_no})

    loop = run_agent_loop(
        llm=llm,
        system=system,
        user=user,
        tools=stage_tools,
        handlers_ctx=workspace.dir,
        max_steps=max_steps,
        on_event=on_event,
        terminal_tools={terminal},
    )
    tc = loop.terminal_call
    result.stages.append(StageRun(stage=stage, loop=loop, terminal_call=tc))
    _accumulate(result, loop)

    if on_event is not None:
        on_event(
            {
                "type": "stage_end",
                "stage": stage,
                "round": round_no,
                "stopped_reason": loop.stopped_reason,
                "terminal": (tc or {}).get("name"),
            }
        )
    return loop, tc


def run_multi(
    llm,
    workspace,
    task: str,
    max_rounds: int = 4,
    max_steps: int = 40,
    on_event=None,
) -> MultiResult:
    result = MultiResult(outcome="escalated", rounds=0)
    state = "UNDERSTAND"
    round_no = 0
    understanding: str | None = None
    reject_reason: str | None = None

    while round_no < max_rounds:
        if state == "UNDERSTAND":
            user = _understand_user(task, workspace, reject_reason)
            _, tc = _run_stage(
                llm, "UNDERSTAND", UNDERSTAND_SYSTEM, user, workspace,
                max_steps, on_event, round_no, result,
            )
            if tc is None:
                result.outcome = "escalated"
                break
            understanding = parse_understanding(tc["args"])
            result.understanding = understanding
            reject_reason = None
            state = "PLAN_EXECUTE"

        elif state == "PLAN_EXECUTE":
            user = _plan_user(understanding, workspace, reject_reason)
            _, tc = _run_stage(
                llm, "PLAN_EXECUTE", PLAN_SYSTEM, user, workspace,
                max_steps, on_event, round_no, result,
            )
            if tc is None:
                result.outcome = "escalated"
                break
            reject_reason = None
            state = "VERIFY"

        elif state == "VERIFY":
            user = _verify_user(understanding, workspace)
            _, tc = _run_stage(
                llm, "VERIFY", VERIFY_SYSTEM, user, workspace,
                max_steps, on_event, round_no, result,
            )
            if tc is None:
                result.outcome = "escalated"
                break
            status = tc["args"]["status"]
            verdict = {"status": status, "reason": tc["args"].get("reason", "")}
            result.verdict = verdict
            result.rounds += 1  # a verify verdict completes a round

            if status == "pass":
                result.outcome = "done"
                break
            round_no += 1
            reject_reason = verdict["reason"]
            state = "UNDERSTAND" if status == "reject_understanding" else "PLAN_EXECUTE"
    else:
        # ran out of rounds without a pass verdict
        result.outcome = "escalated"

    return result

