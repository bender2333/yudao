"""Stage terminal tools for multi mode (spec §3).

Each stage has exactly one terminal tool. Handlers only validate + record
and return a receipt string; they never touch the filesystem. Deliverables
are written by the ordinary tools during the stage.

Handlers are registered into tools.TOOL_HANDLERS at import so the existing
dispatch() finds them. A stage tool is only reachable when it is included in
that stage's tools list (and honored only when in terminal_tools).
"""

from __future__ import annotations

from . import tools as _tools

UNDERSTAND_TERMINAL = "submit_understanding"
PLAN_TERMINAL = "submit_ready"
VERIFY_TERMINAL = "submit_verdict"

_VALID_STATUS = {"pass", "reject_understanding", "reject_execution"}


def _has_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


# ── handlers (workspace_dir, **kwargs) -> str ──────────────
def submit_understanding(
    workspace_dir: str,
    summary: str = "",
    requirements: str = "",
    constraints: str = "",
    done_criteria: str = "",
) -> str:
    for field_name, value in (
        ("summary", summary),
        ("requirements", requirements),
        ("constraints", constraints),
        ("done_criteria", done_criteria),
    ):
        if not _has_text(value):
            return f"Error: {field_name} is required"
    return "understanding recorded"


def submit_ready(workspace_dir: str, notes: str = "") -> str:
    if not _has_text(notes):
        return "Error: notes is required"
    return "ready recorded"


def submit_verdict(workspace_dir: str, status: str = "", reason: str = "") -> str:
    if not isinstance(status, str) or status not in _VALID_STATUS:
        return "Error: invalid status"
    if not _has_text(reason):
        return "Error: reason is required"
    return f"verdict recorded: {status}"


def _fn(name: str, description: str, properties: dict, required: list) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


_UNDERSTAND_DEF = _fn(
    UNDERSTAND_TERMINAL,
    "Submit your understanding of the task. Call this when you fully understand "
    "WHAT must be true when the task is done. All four fields are required.",
    {
        "summary": {"type": "string", "description": "Crisp summary of the task."},
        "requirements": {"type": "string", "description": "Concrete requirements."},
        "constraints": {"type": "string", "description": "Constraints that apply."},
        "done_criteria": {
            "type": "string",
            "description": "Observable done-criteria (what to check).",
        },
    },
    ["summary", "requirements", "constraints", "done_criteria"],
)

_PLAN_DEF = _fn(
    PLAN_TERMINAL,
    "Declare the implementation ready. Call after you have implemented AND run it "
    "to confirm it works.",
    {
        "notes": {
            "type": "string",
            "description": "What you built and how you verified it.",
        }
    },
    ["notes"],
)

_VERIFY_DEF = _fn(
    VERIFY_TERMINAL,
    "Submit the verification verdict and route the workflow.",
    {
        "status": {
            "type": "string",
            "enum": sorted(_VALID_STATUS),
            "description": "pass | reject_execution | reject_understanding",
        },
        "reason": {
            "type": "string",
            "description": "Evidence-based justification (observed vs expected).",
        },
    },
    ["status", "reason"],
)


STAGE_TOOL_DEFS: dict[str, list] = {
    "UNDERSTAND": [_UNDERSTAND_DEF],
    "PLAN_EXECUTE": [_PLAN_DEF],
    "VERIFY": [_VERIFY_DEF],
}

CONSULT_UNDERSTANDING = "consult_understanding"

_CONSULT_DEF = _fn(
    CONSULT_UNDERSTANDING,
    "Ask the UNDERSTANDING stage to clarify or supplement the understanding when "
    "you hit an ambiguity the current understanding does not resolve (e.g. an "
    "unspecified edge case). Provide a specific question; you get back a concrete "
    "answer that is also appended to the shared understanding for later stages. "
    "Use this instead of guessing or looping.",
    {
        "question": {
            "type": "string",
            "description": "The specific ambiguity you need the understanding to resolve.",
        }
    },
    ["question"],
)

STAGE_TOOL_HANDLERS = {
    UNDERSTAND_TERMINAL: submit_understanding,
    PLAN_TERMINAL: submit_ready,
    VERIFY_TERMINAL: submit_verdict,
}

# Register so the shared dispatch() can find them.
_tools.TOOL_HANDLERS.update(STAGE_TOOL_HANDLERS)


def parse_understanding(call_args: dict) -> str:
    """Assemble the four understanding fields into a single text block."""
    return (
        f"## Summary\n{call_args.get('summary', '').strip()}\n\n"
        f"## Requirements\n{call_args.get('requirements', '').strip()}\n\n"
        f"## Constraints\n{call_args.get('constraints', '').strip()}\n\n"
        f"## Done-criteria\n{call_args.get('done_criteria', '').strip()}\n"
    )
