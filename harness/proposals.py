"""结构化提案构造器。只生成 payload，校验和状态改变仍由控制层完成。"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .adapters.fake import FakeTurn, pending_request_id, prompt_part
from .providers.call import ModelCall


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
        "decision_changes": extra.get("decision_changes", []),
        "change_record": extra.get("change_record"),
    }
    payload.update({key: value for key, value in extra.items() if key in payload})
    return payload


def collaboration_request(
    recipient: str = "product",
    question: str = "How should unknown flags be handled?",
    *,
    request_type: str = "consultation",
    background: str = "The current work needs another department's expertise.",
    expected_result: str = "Explain the appropriate behavior and its basis.",
    action: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": "collaboration_request",
        "recipient": recipient,
        "request_type": request_type,
        "question": question,
        "background": background,
        "expected_result": expected_result,
        "action": action,
    }


def collaboration_response(request_id: str, status: str, text: str,
                           result_event_ids: list[str] | None = None) -> dict[str, Any]:
    return {
        "kind": "collaboration_response", "request_id": request_id, "status": status,
        "text": text, "result_event_ids": [] if result_event_ids is None else result_event_ids,
    }


def guidance_response(guidance_id: str, status: str = "completed",
                      text: str = "The department reviewed and handled this guidance.",
                      result_event_ids: list[str] | None = None) -> dict[str, Any]:
    return {
        "kind": "department_guidance_response",
        "guidance_id": guidance_id,
        "status": status,
        "text": text,
        "result_event_ids": [] if result_event_ids is None else result_event_ids,
    }


def product_decision(statement: str, rationale: str) -> dict[str, Any]:
    return {"kind": "product_decision", "statement": statement, "rationale": rationale}


def response_turn(status: str = "answered", text: str = "The existing contract already defines this behavior.",
                  *, result_event_ids: list[str] | None = None,
                  result_types: list[str] | None = None) -> Callable[[ModelCall], dict[str, Any]]:
    # 回应请求中写明的待处理请求；结果事件从请求中的 request_results 取得
    def submit(call: ModelCall) -> dict[str, Any]:
        request_id = pending_request_id(call)
        if request_id is None:
            raise ValueError("response_turn requires an actual pending request")
        references = list(result_event_ids or [])
        if result_types:
            results = json.loads(prompt_part(call, "request_results") or "[]")
            for event_type in result_types:
                matches = [item["event_id"] for item in results if item["type"] == event_type]
                if not matches:
                    raise ValueError(f"response_turn has no accepted result of type {event_type}")
                references.extend(matches)
        return collaboration_response(request_id, status, text, references)

    return submit


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


def engineering_plan(
    objective: str = "Implement and verify the current echo CLI requirements",
    *,
    scope: list[str] | None = None,
    tasks: list[dict[str, Any]] | None = None,
    refactoring: list[str] | None = None,
    assumptions: list[dict[str, str]] | None = None,
    reason: str = "",
) -> dict[str, Any]:
    return {
        "kind": "engineering_plan",
        "objective": objective,
        "scope": ["src/"] if scope is None else scope,
        "tasks": [{
            "title": "Implement the current contract",
            "outputs": ["src/echo.py"],
            "verification": "Run the CLI through host checks against the current requirements",
        }] if tasks is None else tasks,
        "refactoring": [] if refactoring is None else refactoring,
        "assumptions": [] if assumptions is None else assumptions,
        "reason": reason,
    }


def plan_turn(**kwargs: Any) -> Callable[[ModelCall], dict[str, Any]]:
    def submit(call: ModelCall) -> dict[str, Any]:
        return engineering_plan(**kwargs)

    return submit


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
    checks: dict[str, int | dict[str, Any]] | None = None,
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
    checks: dict[str, int | dict[str, Any]] | None = None,
    defects: list[dict[str, str]] | None = None,
    transcript: str = "",
) -> FakeTurn:
    checks = checks or {"smoke": 0}
    return FakeTurn(
        proposal=review(verdict, rationale, checks=list(checks), defects=defects),
        checks=checks,
        transcript=transcript,
    )
