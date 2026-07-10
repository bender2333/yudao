"""orchestrator — the multi-mode state machine (spec §2).

UNDERSTAND -> PLAN_EXECUTE -> VERIFY, driven by the verify verdict:
  pass                -> DONE
  reject_execution    -> PLAN_EXECUTE (round += 1)
  reject_understanding-> UNDERSTAND   (round += 1)
Exhausting MAX_ROUNDS, or any stage that ends without its terminal_call,
-> ESCALATED.

Each role has one private AgentSession for the run over the SAME workspace. Tool access:
  PLAN_EXECUTE  — full toolset (read/write/edit/bash)
  UNDERSTAND / VERIFY / consult — no write_file/edit_file (judge/investigate only)
plus that stage's terminal tool. Context encapsulation (spec §4): verify only
sees understanding + file listing, never upstream implementation prose.

Gates (post-M2.1 tighten):
  UNDERSTAND — prefer submit_understanding; natural stop runs one structured extract
  PLAN       — must leave at least one non-empty deliverable file
  VERIFY     — submit_verdict preferred; natural stop classifies via router
  consult    — answers are appended into the shared understanding artifact
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .agent_loop import AgentSession, activate
from .llm import BudgetExhausted
from .stage_tools import (
    CONSULT_UNDERSTANDING,
    PLAN_TERMINAL,
    STAGE_TOOL_DEFS,
    UNDERSTAND_TERMINAL,
    VERIFY_TERMINAL,
    _CONSULT_DEF,
    parse_understanding,
)
from .tools import TOOL_DEFS, tool_defs_without_writes

# Full tools for implement; investigate/judge stages cannot rewrite deliverables.
_INVESTIGATE_TOOLS = tool_defs_without_writes()
_IMPLEMENT_TOOLS = TOOL_DEFS

UNDERSTAND_SYSTEM = (
    "You are the persistent UNDERSTANDING role for this run. You retain only your own "
    "transcript and receive other roles' information only through explicit handoffs. "
    "Investigate the task and the existing workspace "
    "using read/list/bash tools only — do NOT implement or write solution code.\n"
    "Your job is to deeply understand WHAT must be true when the task is done.\n"
    "When ready, you MUST call submit_understanding with all four fields: summary, "
    "requirements, constraints, and observable done-criteria (concrete checks a verifier "
    "can run). Prefer the terminal tool over free text; free-text stop is only a fallback "
    "and will be re-structured automatically."
    " When activated by a ConsultRequest, answer the question directly in final text "
    "without calling submit_understanding."
)

PLAN_SYSTEM = (
    "You are the persistent PLAN & EXECUTE role for this run. You retain only your own "
    "transcript and receive other roles' information only through explicit handoffs.\n"
    "The upstream understanding is the source of truth.\n"
    "Plan and implement it for real: write/edit files, then RUN commands to verify behavior. "
    "Realize every done-criterion as actually-working behavior.\n"
    "If you hit an ambiguity the understanding does not resolve, call consult_understanding "
    "with a specific question instead of guessing.\n"
    "Do not stop until the workspace contains the deliverable files AND you have run them. "
    "Prefer calling submit_ready with notes of what you built and how you verified; "
    "natural stop is accepted only when non-empty deliverable files already exist."
)

VERIFY_SYSTEM = (
    "You are the persistent VERIFICATION role for this run. You retain only your own "
    "transcript and receive other roles' information only through explicit handoffs.\n"
    "You are given the upstream understanding (source of truth "
    'for "done") and the workspace file listing.\n'
    "Independently verify whether the implementation satisfies the done-criteria: read "
    "delivered files and RUN functional checks via bash (invoke the program, one-liners, "
    "inline python -c). You cannot write or edit workspace files — judge only.\n"
    "Judge from real execution evidence, not code reading alone.\n"
    "You MUST call submit_verdict with status "
    "(pass | reject_execution | reject_understanding) and an evidence-based reason "
    "(observed vs expected). Prefer the terminal tool; free-text stop is a fallback that "
    "will be classified by a router (ambiguous → reject_execution, never a false pass).\n"
    "If a done-criterion is ambiguous, call consult_understanding with a specific question "
    "rather than guessing or looping. Do not modify the implementation."
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
    consult_errors: int = 0
    stopped_reason: str | None = None
    session_model: str = "persistent_roles_v1"
    sessions: dict[str, AgentSession] = field(default_factory=dict)
    per_role: dict = field(default_factory=dict)
    activates: int = 0
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


def _has_deliverables(workspace) -> bool:
    """True iff workspace has at least one non-empty deliverable file."""
    files = workspace.snapshot_files()
    return any(size > 0 for size in files.values())


def _has_changed_deliverable(workspace, before: dict[str, str]) -> bool:
    sizes = workspace.snapshot_files()
    after = workspace.snapshot_fingerprints()
    return any(
        size > 0 and after.get(name) != before.get(name)
        for name, size in sizes.items()
    )


def _understand_user(
    task: str,
    workspace,
    reject_reason: str | None,
    canonical_understanding: str | None,
) -> str:
    parts = [
        f"# Original task\n{task}\n",
        f"# Workspace files\n{_file_listing(workspace)}\n",
    ]
    if reject_reason:
        parts.append(
            "# Your previous understanding (canonical)\n"
            f"{canonical_understanding or '(none yet)'}\n\n"
            "# Previous verification rejected the understanding\n"
            f"{reject_reason}\n\n"
            "Revise the understanding (especially done-criteria) so it is "
            "checkable and aligned with the original task.\n"
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
            f"{reject_reason}\n\n"
            "Fix only what failed; keep already-correct behavior intact.\n"
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


def _base_tools_for(stage: str) -> list:
    if stage == "PLAN_EXECUTE":
        return _IMPLEMENT_TOOLS
    return _INVESTIGATE_TOOLS


def _run_stage(
    llm, session, user, workspace, max_steps, on_event, round_no, result,
    on_stop=None, extra_handlers=None,
):
    """Run one stage loop; emit stage_start/stage_end; record + accumulate.

    A stage ends when its loop stops naturally (the model stops calling tools) —
    that IS the end-of-stage signal. The optional on_stop hook extracts the
    stage's产出/routing from the final transcript. Terminal tools, if the model
    happens to call one, are still honored as an early, explicit stop.
    extra_handlers provide run-bound tools (e.g. consult_understanding).
    """
    stage = session.role
    terminal = {
        "UNDERSTAND": UNDERSTAND_TERMINAL,
        "PLAN_EXECUTE": PLAN_TERMINAL,
        "VERIFY": VERIFY_TERMINAL,
    }[stage]
    if on_event is not None:
        on_event({"type": "stage_start", "stage": stage, "round": round_no})

    loop = activate(
        session,
        user,
        llm=llm,
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


# ── Stop hooks ────────────────────────────────────────────
# on_stop fires ONLY on natural stop (no tool_calls). The terminal-tool path
# sets terminal_call itself. terminal_call is None after a stage IFF the loop
# hit max_steps without concluding, OR a gate rejected the natural产出.

_UNDERSTAND_EXTRACT_SYSTEM = (
    "You extract a structured understanding from a free-text conclusion. "
    "Call submit_understanding with all four required fields based only on the "
    "text given. done_criteria must be observable checks a verifier can run. "
    "Do not invent unrelated requirements. If the text is too vague to fill a "
    "field, write the best faithful short statement rather than leaving it empty."
)

_REQUIRED_U_FIELDS = ("summary", "requirements", "constraints", "done_criteria")


def _make_understand_hook(llm):
    """Natural stop → one cheap extract call into submit_understanding fields.

    If extraction fails or text is empty → None (escalate). No free-text
    understanding is accepted as a durable artifact.
    """
    def hook(final_text, messages):
        text = (final_text or "").strip()
        if not text:
            return None
        try:
            msgs = [
                {"role": "system", "content": _UNDERSTAND_EXTRACT_SYSTEM},
                {"role": "user", "content": f"Free-text understanding:\n\n{text}"},
            ]
            cr = llm.chat(
                msgs,
                STAGE_TOOL_DEFS["UNDERSTAND"],
                accounting_role="UNDERSTAND",
            )
            for tc in cr.tool_calls or []:
                if tc.function.name != UNDERSTAND_TERMINAL:
                    continue
                args = json.loads(tc.function.arguments or "{}")
                if all((args.get(k) or "").strip() for k in _REQUIRED_U_FIELDS):
                    return {"name": UNDERSTAND_TERMINAL, "args": args}
        except BudgetExhausted:
            raise
        except Exception:
            pass
        return None
    return hook


def _make_plan_hook(workspace):
    """Natural stop accepted only when non-empty deliverables exist on disk."""
    def hook(final_text, messages):
        if not _has_deliverables(workspace):
            return None  # empty workspace → escalate (do not pretend ready)
        return {
            "name": "ready_natural",
            "notes": (final_text or "").strip() or "(no notes; deliverables present)",
        }
    return hook


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
        default = {
            "name": "submit_verdict",
            "args": {
                "status": "reject_execution",
                "reason": (
                    "verification produced no explicit verdict; "
                    "defaulting to reject_execution (no false pass)."
                ),
            },
        }
        if not text:
            return default
        try:
            router_msgs = [
                {"role": "system", "content": _VERIFY_ROUTER_SYSTEM},
                {"role": "user", "content": f"Verification conclusion:\n\n{text}"},
            ]
            cr = llm.chat(
                router_msgs,
                STAGE_TOOL_DEFS["VERIFY"],
                accounting_role="VERIFY",
            )
            for tc in cr.tool_calls or []:
                if tc.function.name == VERIFY_TERMINAL:
                    args = json.loads(tc.function.arguments or "{}")
                    if (
                        args.get("status") in {
                            "pass",
                            "reject_execution",
                            "reject_understanding",
                        }
                        and isinstance(args.get("reason"), str)
                        and args["reason"].strip()
                    ):
                        return {"name": "submit_verdict", "args": args}
        except BudgetExhausted:
            raise
        except Exception:
            pass
        return default
    return hook


def _make_consult_handler(
    llm,
    session,
    workspace,
    task,
    get_understanding,
    set_understanding,
    on_event,
    counter,
):
    """激活常驻 UNDERSTAND，并将成功答复晋升到 canonical understanding。"""
    def fail(reason: str) -> str:
        counter["consult_errors"] += 1
        if on_event is not None:
            on_event({"type": "consult_error", "reason": _clip(reason)})
        return f"Error: {reason}"

    def handler(question: str = "") -> str:
        q = (question or "").strip()
        if not q:
            return fail("question is required")
        if on_event is not None:
            on_event({"type": "consult", "question": _clip(q)})
        user = (
            "# Handoff: ConsultRequest\n"
            f"# Original task\n{task}\n\n"
            "# Understanding (canonical)\n"
            f"{get_understanding() or '(none yet)'}\n\n"
            f"# Question from a downstream role\n{q}\n\n"
            "Answer this clarification directly in final text. Do not call "
            "submit_understanding in this activation."
        )
        try:
            sub = activate(
                session,
                user,
                llm=llm,
                handlers_ctx=workspace.dir,
                max_steps=8,
                on_event=on_event,
            )
        except BudgetExhausted:
            fail("consult exhausted the run budget")
            raise
        except Exception as exc:
            return fail(f"consult failed ({type(exc).__name__}: {exc})")
        if sub.stopped_reason == "budget_exhausted":
            fail("consult exhausted the run budget")
            raise BudgetExhausted("consult exhausted the run budget")
        if sub.stopped_reason != "natural":
            return fail(f"consult did not complete ({sub.stopped_reason})")
        answer = (sub.final_text or "").strip()
        if not answer:
            return fail("consult returned no answer")
        # Promote into shared understanding so VERIFY/PLAN see the clarification.
        base = get_understanding() or ""
        promoted = (
            f"{base.rstrip()}\n\n"
            f"## Clarification\n"
            f"**Q:** {q}\n"
            f"**A:** {answer}\n"
        )
        set_understanding(promoted)
        counter["consults"] += 1
        if on_event is not None:
            on_event(
                {
                    "type": "consult_promoted",
                    "question": _clip(q),
                    "answer": _clip(answer),
                }
            )
        return answer
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
    """运行一次 multi；llm 是本 run 三角色共享且独占的预算 client。"""
    result = MultiResult(outcome="escalated", rounds=0)
    state = "UNDERSTAND"
    round_no = 0
    understanding: str | None = None
    reject_reason: str | None = None
    understand_hook = _make_understand_hook(llm)
    plan_hook = _make_plan_hook(workspace)
    verify_hook = _make_verify_hook(llm)

    def _get_understanding() -> str | None:
        return understanding

    def _set_understanding(text: str) -> None:
        nonlocal understanding
        understanding = text
        result.understanding = text

    consult_defs = [_CONSULT_DEF]
    sessions = {
        "UNDERSTAND": AgentSession(
            "UNDERSTAND",
            UNDERSTAND_SYSTEM,
            _base_tools_for("UNDERSTAND") + STAGE_TOOL_DEFS["UNDERSTAND"],
        ),
        "PLAN_EXECUTE": AgentSession(
            "PLAN_EXECUTE",
            PLAN_SYSTEM,
            _base_tools_for("PLAN_EXECUTE")
            + STAGE_TOOL_DEFS["PLAN_EXECUTE"]
            + consult_defs,
        ),
        "VERIFY": AgentSession(
            "VERIFY",
            VERIFY_SYSTEM,
            _base_tools_for("VERIFY") + STAGE_TOOL_DEFS["VERIFY"] + consult_defs,
        ),
    }
    result.sessions = sessions
    usage_fields = (
        "calls",
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
        "llm_duration_ms",
    )
    usage_before = {
        role: {
            field: llm.usage_by_role.get(role, {}).get(field, 0)
            for field in usage_fields
        }
        for role in sessions
    }

    # PLAN_EXECUTE / VERIFY 的 consult 始终激活同一个 UNDERSTAND 会话。
    counter = {"consults": 0, "consult_errors": 0}
    consult = _make_consult_handler(
        llm,
        sessions["UNDERSTAND"],
        workspace,
        task,
        _get_understanding,
        _set_understanding,
        on_event,
        counter,
    )
    consult_handlers = {CONSULT_UNDERSTANDING: consult}

    # Soft-convergence: past this many reject rounds, nudge rather than hard-cut only.
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
            user = _understand_user(
                task,
                workspace,
                _nudge(reject_reason),
                understanding,
            )
            loop, tc = _run_stage(
                llm,
                sessions["UNDERSTAND"],
                user,
                workspace,
                max_steps,
                on_event,
                round_no,
                result,
                on_stop=understand_hook,
            )
            if tc is None:  # max_steps / empty / extract failed
                result.outcome = "escalated"
                result.stopped_reason = (
                    loop.stopped_reason
                    if loop.stopped_reason in {"max_steps", "budget_exhausted"}
                    else "understand_incomplete"
                )
                break
            _set_understanding(_understanding_from(tc))
            reject_reason = None
            state = "PLAN_EXECUTE"

        elif state == "PLAN_EXECUTE":
            user = _plan_user(understanding, workspace, _nudge(reject_reason))
            before = workspace.snapshot_fingerprints()
            loop, tc = _run_stage(
                llm,
                sessions["PLAN_EXECUTE"],
                user,
                workspace,
                max_steps,
                on_event,
                round_no,
                result,
                on_stop=plan_hook,
                extra_handlers=consult_handlers,
            )
            # PLAN 本轮必须创建或修改至少一个非空交付文件。
            if tc is None or not _has_changed_deliverable(workspace, before):
                result.outcome = "escalated"
                if loop.stopped_reason in {"max_steps", "budget_exhausted"}:
                    result.stopped_reason = loop.stopped_reason
                elif tc is None:
                    result.stopped_reason = "plan_incomplete"
                else:
                    result.stopped_reason = "plan_no_changed_deliverable"
                break
            reject_reason = None
            state = "VERIFY"

        elif state == "VERIFY":
            # Always pass the latest understanding (includes any consult promotions).
            user = _verify_user(understanding or "", workspace)
            loop, tc = _run_stage(
                llm,
                sessions["VERIFY"],
                user,
                workspace,
                max_steps,
                on_event,
                round_no,
                result,
                on_stop=verify_hook,
                extra_handlers=consult_handlers,
            )
            if tc is None:
                result.outcome = "escalated"
                result.stopped_reason = (
                    loop.stopped_reason
                    if loop.stopped_reason in {"max_steps", "budget_exhausted"}
                    else "verify_incomplete"
                )
                break
            status = tc["args"]["status"]
            verdict = {"status": status, "reason": tc["args"].get("reason", "")}
            result.verdict = verdict
            result.rounds += 1  # a verify verdict completes a round

            if status == "pass":
                result.outcome = "done"
                result.stopped_reason = "completed"
                break
            round_no += 1
            reject_reason = verdict["reason"]
            state = (
                "UNDERSTAND"
                if status == "reject_understanding"
                else "PLAN_EXECUTE"
            )
    else:
        # ran out of rounds without a pass verdict
        result.outcome = "escalated"
        result.stopped_reason = "max_rounds"

    result.consults = counter["consults"]
    result.consult_errors = counter["consult_errors"]
    result.activates = sum(session.activates for session in sessions.values())
    result.per_role = {}
    for role, session in sessions.items():
        current = llm.usage_by_role.get(role, {})
        result.per_role[role] = {
            "activates": session.activates,
            **{
                field: current.get(field, 0) - usage_before[role][field]
                for field in usage_fields
            },
            "messages": len(session.messages),
        }
    return result


def _understanding_from(tc: dict) -> str:
    """Normalize UNDERSTAND terminal_call into understanding text.

    Accepts submit_understanding args (structured) or a rare understanding_text
    key (legacy); structured is the only path produced by current hooks.
    """
    if "understanding_text" in tc:
        return tc["understanding_text"]
    return parse_understanding(tc.get("args", {}))
