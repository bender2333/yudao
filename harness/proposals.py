"""结构化提案构造器。只生成 payload，校验和状态改变仍由控制层完成。"""

from __future__ import annotations

from typing import Any

from .adapters.fake import FakeTurn


def product_spec(
    goal: str = "build an echo CLI",
    requirements: list[str] | None = None,
    acceptance: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload = {
        "kind": "product_spec",
        "goal": goal,
        "requirements": requirements or ["print the given argument to stdout"],
        "boundaries": extra.get("boundaries", ["do not read files"]),
        "constraints": extra.get("constraints", ["single file implementation"]),
        "acceptance_criteria": acceptance or ["running the program with a word prints that word"],
        "fatal_conditions": extra.get("fatal_conditions", ["non-zero exit on valid input"]),
        "non_goals": extra.get("non_goals", ["network access"]),
    }
    payload.update({key: value for key, value in extra.items() if key in payload})
    return payload


def ask_request(
    question: str = "How should unknown flags be handled?",
    options: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "kind": "ask_request",
        "question": question,
        "background": extra.get("background", "The current spec does not mention flags."),
        "options": options or ["exit 2 with an error", "ignore unknown flags"],
        "impact": extra.get("impact", "Error handling changes the public contract."),
        "recommendation": extra.get("recommendation", "exit 2 with an error"),
        "decide_fields": extra.get("decide_fields", ["unknown flag behavior"]),
    }


def reaction(decision: str, rationale: str, spec_update: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "product_reaction",
        "decision": decision,
        "rationale": rationale,
    }
    if spec_update is not None:
        payload["spec_update"] = spec_update
    return payload


def delivery(
    summary: str = "implemented echo CLI",
    files: list[str] | None = None,
    check_names: list[str] | None = None,
    known_risks: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "kind": "delivery_spec",
        "summary": summary,
        "files": files or ["src/echo.py"],
        "check_names": check_names or ["smoke"],
        "known_risks": known_risks or [],
    }


def review(
    verdict: str,
    rationale: str,
    checks: list[str] | None = None,
    defects: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "kind": "qa_review",
        "verdict": verdict,
        "rationale": rationale,
        "checks": checks or ["smoke"],
        "defects": defects or [],
    }


def delivery_turn(
    summary: str = "implemented echo CLI",
    *,
    files: dict[str, str] | None = None,
    checks: dict[str, int] | None = None,
    transcript: str = "",
) -> FakeTurn:
    files = files or {"src/echo.py": "import sys\nprint(sys.argv[1])\n"}
    checks = checks or {"smoke": 0}
    return FakeTurn(
        proposal=delivery(summary, files=list(files), check_names=list(checks)),
        writes=files,
        checks=checks,
        transcript=transcript,
    )


def review_turn(
    verdict: str,
    rationale: str,
    *,
    checks: dict[str, int] | None = None,
    defects: list[dict[str, str]] | None = None,
    transcript: str = "",
) -> FakeTurn:
    checks = checks or {"smoke": 0}
    return FakeTurn(
        proposal=review(verdict, rationale, checks=list(checks), defects=defects),
        checks=checks,
        transcript=transcript,
    )
