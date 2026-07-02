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

import json
from dataclasses import dataclass, field

from .agent_loop import run_agent_loop
from .stage_tools import (
    CONSULT_UNDERSTANDING,
    PLAN_TERMINAL,
    STAGE_TOOL_DEFS,
    UNDERSTAND_TERMINAL,
    VERIFY_TERMINAL,
    _CONSULT_DEF,
    parse_understanding,
)
from .tools import TOOL_DEFS

UNDERSTAND_SYSTEM = (
    "You are the UNDERSTANDING stage. Investigate the task and the existing workspace "
    "using tools. Your job is NOT to implement — it is to deeply understand WHAT must "
    "be true when the task is done. Produce a crisp statement of the task summary, the "
    "concrete requirements, the constraints, and the observable done-criteria. You may "
    "call submit_understanding to record it in a structured form, but simply writing it "
    "out and stopping is also fine. Do not write solution code."
)

PLAN_SYSTEM = (
    "You are the PLAN & EXECUTE stage, given the upstream understanding. Plan and "
    "implement it for real using tools (write/edit files, run commands to check your "
    "work). Realize every done-criterion as actually-working behavior. Run it to confirm "
    "it works. If you hit an ambiguity the understanding does not resolve, call "
    "consult_understanding with a specific question instead of guessing. When you are "
    "done, stop; you may optionally call submit_ready to note what you built and how "
    "you verified it."
)

VERIFY_SYSTEM = (
    "You are the VERIFICATION stage, given the upstream understanding (source of truth "
    'for "done") and the workspace. Independently verify whether the implementation '
    "satisfies the done-criteria: read delivered files and RUN functional checks "
    "(write/execute test scripts, invoke the program, inspect outputs). Judge from real "
    "execution evidence, not code reading alone. State your verdict clearly: whether every "
    "criterion is met, or which one fails (observed vs expected), or whether the "
    "understanding itself was wrong. Call submit_verdict with status "
    "(pass | reject_execution | reject_understanding) and an evidence-based reason. "
    "If a done-criterion is ambiguous and the understanding does not settle it, call "
    "consult_understanding with a specific question rather than guessing or looping. "
    "Do not modify the implementation; your role is to judge and route."
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
    consults: int = 0
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
    llm, stage, system, user, workspace, max_steps, on_event, round_no, result,
    on_stop=None, extra_tool_defs=None, extra_handlers=None,
):
    """Run one stage loop; emit stage_start/stage_end; record + accumulate.

    A stage ends when its loop stops naturally (the model stops calling tools) —
    that IS the end-of-stage signal. The optional on_stop hook extracts the
    stage's产出/routing from the final transcript. Terminal tools, if the model
    happens to call one, are still honored as an early, explicit stop.
    extra_tool_defs/extra_handlers add cross-stage tools (e.g. consult_understanding).
    """
    terminal = {
        "UNDERSTAND": UNDERSTAND_TERMINAL,
        "PLAN_EXECUTE": PLAN_TERMINAL,
        "VERIFY": VERIFY_TERMINAL,
    }[stage]
    stage_tools = TOOL_DEFS + STAGE_TOOL_DEFS[stage] + (extra_tool_defs or [])

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
        on_stop=on_stop,
        extra_handlers=extra_handlers,
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


# ── Stop hooks (spec: 自然停止 = 阶段结束) ───────────────────
# on_stop fires ONLY on natural stop (no tool_calls). The terminal-tool path
# sets terminal_call itself. So after a stage, terminal_call is None IFF the
# loop hit max_steps without concluding → that (and only that) escalates.

def _understand_hook(final_text, messages):
    """Understanding produced as free text (model didn't call the tool)."""
    text = (final_text or "").strip()
    if not text:
        return None  # produced nothing → escalate
    return {"name": "understanding_natural", "understanding_text": text}


def _plan_hook(final_text, messages):
    """Plan/execute ended naturally — its产出 is the files on disk. Always concludes."""
    return {"name": "ready_natural", "notes": (final_text or "").strip()}


_VERIFY_ROUTER_SYSTEM = (
    "You are a strict router. You are given a verification stage's own written "
    "conclusion about whether an implementation meets its done-criteria. Classify "
    "it into exactly one routing verdict by calling submit_verdict:\n"
    "- pass: the conclusion clearly states every criterion is met with evidence.\n"
    "- reject_execution: the conclusion finds the implementation fails a criterion.\n"
    "- reject_understanding: the conclusion finds the understanding itself was wrong.\n"
    "Do not invent findings; classify only what the conclusion says. If it is "
    "ambiguous or gives no clear pass, choose reject_execution (never falsely pass)."
)


def _make_verify_hook(llm):
    """Verify ended naturally without submit_verdict → recover a routing verdict
    with ONE cheap classification call. Defaults to reject_execution (never a
    false pass) if classification can't produce a clean verdict."""
    def hook(final_text, messages):
        text = (final_text or "").strip()
        default = {"name": "submit_verdict",
                   "args": {"status": "reject_execution",
                            "reason": "verification produced no explicit verdict; "
                                      "defaulting to reject_execution (no false pass)."}}
        if not text:
            return default
        try:
            router_msgs = [
                {"role": "system", "content": _VERIFY_ROUTER_SYSTEM},
                {"role": "user", "content": f"Verification conclusion:\n\n{text}"},
            ]
            cr = llm.chat(router_msgs, STAGE_TOOL_DEFS["VERIFY"])
            for tc in cr.tool_calls or []:
                if tc.function.name == VERIFY_TERMINAL:
                    args = json.loads(tc.function.arguments or "{}")
                    if args.get("status") in {"pass", "reject_execution", "reject_understanding"}:
                        args.setdefault("reason", "(classified from verify conclusion)")
                        return {"name": "submit_verdict", "args": args}
        except Exception:
            pass
        return default
    return hook


def _make_consult_handler(llm, workspace, task, get_understanding, on_event, counter):
    """Build a consult_understanding handler: a stage can freely call it to ask the
    UNDERSTANDING role to clarify an ambiguity. Runs a small understanding sub-loop
    bound to the task + current understanding; returns a concrete answer string.
    Fully free-form (per user's directive): any stage may call it any number of times."""
    def handler(question: str = "") -> str:
        q = (question or "").strip()
        if not q:
            return "Error: question is required"
        counter["consults"] += 1
        if on_event is not None:
            on_event({"type": "consult", "question": _clip(q)})
        system = (
            "You are the UNDERSTANDING stage being consulted mid-task. Answer the "
            "specific question concretely and decisively, grounded in the original "
            "task and the established understanding. If the task is silent, make the "
            "most reasonable decision and state it plainly. Investigate with tools if "
            "needed. Give a direct answer, not a restatement."
        )
        user = (
            f"# Original task\n{task}\n\n"
            f"# Established understanding\n{get_understanding() or '(none yet)'}\n\n"
            f"# Question from a downstream stage\n{q}\n"
        )
        sub = run_agent_loop(
            llm=llm, system=system, user=user,
            tools=TOOL_DEFS, handlers_ctx=workspace.dir,
            max_steps=8, on_event=on_event,
        )
        return sub.final_text or "(no answer)"
    return handler


def _clip(s: str, n: int = 300) -> str:
    return s if len(s) <= n else s[:n] + "..."


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
    verify_hook = _make_verify_hook(llm)

    # Cross-stage consult (point 1): PLAN_EXECUTE / VERIFY may freely call
    # consult_understanding any number of times to resolve ambiguity mid-task.
    counter = {"consults": 0}
    consult = _make_consult_handler(
        llm, workspace, task, lambda: understanding, on_event, counter
    )
    consult_defs = [_CONSULT_DEF]
    consult_handlers = {CONSULT_UNDERSTANDING: consult}

    # Soft-convergence (point 2): once we've looped past this many rounds,
    # inject a nudge to converge rather than hard-cutting.
    soft_at = max(1, max_rounds - 1)

    def _nudge(reason: str | None) -> str | None:
        if round_no >= soft_at:
            note = (
                f"\n\n# Convergence note\nYou have already iterated {round_no} rounds. "
                "If you cannot fully resolve remaining issues this round, converge to "
                "the best working result you can and finish."
            )
            return (reason or "") + note
        return reason

    while round_no < max_rounds:
        if state == "UNDERSTAND":
            user = _understand_user(task, workspace, _nudge(reject_reason))
            _, tc = _run_stage(
                llm, "UNDERSTAND", UNDERSTAND_SYSTEM, user, workspace,
                max_steps, on_event, round_no, result, on_stop=_understand_hook,
            )
            if tc is None:  # max_steps without concluding
                result.outcome = "escalated"
                break
            understanding = _understanding_from(tc)
            result.understanding = understanding
            reject_reason = None
            state = "PLAN_EXECUTE"

        elif state == "PLAN_EXECUTE":
            user = _plan_user(understanding, workspace, _nudge(reject_reason))
            _, tc = _run_stage(
                llm, "PLAN_EXECUTE", PLAN_SYSTEM, user, workspace,
                max_steps, on_event, round_no, result, on_stop=_plan_hook,
                extra_tool_defs=consult_defs, extra_handlers=consult_handlers,
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
                max_steps, on_event, round_no, result, on_stop=verify_hook,
                extra_tool_defs=consult_defs, extra_handlers=consult_handlers,
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

    result.consults = counter["consults"]
    return result


def _understanding_from(tc: dict) -> str:
    """Normalize UNDERSTAND terminal_call into understanding text, whether it
    came from the submit_understanding tool (structured) or natural stop (text)."""
    if "understanding_text" in tc:
        return tc["understanding_text"]
    return parse_understanding(tc.get("args", {}))

