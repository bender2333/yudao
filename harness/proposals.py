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
    basis_product_spec_hash: str | None = None,
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
        "basis_product_spec_hash": basis_product_spec_hash,
    }
    payload.update({key: value for key, value in extra.items() if key in payload})
    return payload


def product_spec_turn(
    goal: str = "build an echo CLI",
    requirements: list[str] | None = None,
    acceptance: list[str] | None = None,
    basis_product_spec_hash: str | None = None,
    **extra: Any,
) -> Callable[[ModelCall], dict[str, Any]]:
    # 返回按请求里的当前 ProductSpec 填依据版本的假模型轮次（工单 #471）：
    # 第一次提交依据 null，修订版依据请求里写明的当前版本，与真实模型从上下文读到的一样
    def submit(call: ModelCall) -> dict[str, Any]:
        declared = basis_product_spec_hash
        if declared is None:
            raw = prompt_part(call, "current_product_spec")
            declared = json.loads(raw).get("content_hash") if raw else None
        return product_spec(goal, requirements, acceptance, declared, **extra)

    return submit


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
    basis_product_spec_hash: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": "delivery_spec",
        "summary": summary,
        "files": files or ["src/echo.py"],
        "check_names": check_names or ["smoke"],
        "known_risks": known_risks or [],
        "basis_product_spec_hash": basis_product_spec_hash,
    }



def structure(
    *,
    overall: str = "The repository is a single Python package with a console entry point.",
    modules: list[dict[str, str]] | None = None,
    entry_points: list[dict[str, str]] | None = None,
    build_and_test: list[dict[str, Any]] | None = None,
    requirement_locations: list[dict[str, Any]] | None = None,
    conventions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "kind": "structure",
        "overall": overall,
        "modules": modules or [{"path": "src/", "responsibility": "the package implementation"}],
        "entry_points": entry_points or [{"kind": "command_line", "path": "src/echo.py", "how_to_run": "python src/echo.py"}],
        "build_and_test": build_and_test or [{"name": "smoke", "command": "python src/echo.py", "purpose": "run the CLI"}],
        "requirement_locations": requirement_locations or [
            {"requirement": "print the given argument to stdout", "locations": ["src/echo.py"]},
        ],
        "conventions": conventions or [],
    }

def structure_turn(
    *,
    overall: str = "The repository is a single Python package with a console entry point.",
    modules: list[dict[str, str]] | None = None,
    entry_points: list[dict[str, str]] | None = None,
    checks: dict[str, int | dict[str, Any]] | None = None,
    build_and_test: list[dict[str, Any]] | None = None,
    requirement_locations: list[dict[str, Any]] | None = None,
    conventions: list[str] | None = None,
    transcript: str = "",
) -> FakeTurn:
    checks = {"smoke": 0} if checks is None else checks
    if build_and_test is None:
        build_and_test = [{"name": name, "command": "python src/echo.py", "purpose": "run the CLI"} for name in checks]
    return FakeTurn(
        proposal=structure(overall=overall, modules=modules, entry_points=entry_points,
                           build_and_test=build_and_test, requirement_locations=requirement_locations,
                           conventions=conventions),
        checks=checks,
        transcript=transcript,
    )

def baseline_review(
    verdict: str = "consistent",
    *,
    conclusions: list[dict[str, str]] | None = None,
    omissions: list[dict[str, str]] | None = None,
    checks: list[str] | None = None,
    other_failures: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "kind": "baseline_review",
        "verdict": verdict,
        "conclusions": conclusions or [
            {"requirement": "print the given argument to stdout", "status": "verified", "evidence": "smoke"},
        ],
        "omissions": omissions or [],
        "checks": checks or ["smoke"],
        "other_failures": other_failures or [],
    }

def baseline_review_turn(
    verdict: str = "consistent",
    *,
    conclusions: list[dict[str, str]] | None = None,
    omissions: list[dict[str, str]] | None = None,
    checks: dict[str, int | dict[str, Any]] | None = None,
    other_failures: list[dict[str, str]] | None = None,
    transcript: str = "",
) -> FakeTurn:
    checks = {"smoke": 0} if checks is None else checks
    return FakeTurn(
        proposal=baseline_review(verdict, conclusions=conclusions, omissions=omissions,
                                 checks=list(checks), other_failures=other_failures),
        checks=checks,
        transcript=transcript,
    )


def review(
    verdict: str,
    rationale: str,
    checks: list[str] | None = None,
    defects: list[dict[str, str]] | None = None,
    basis_delivery_spec_hash: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": "qa_review",
        "verdict": verdict,
        "rationale": rationale,
        "checks": checks or ["smoke"],
        "defects": defects or [],
        "basis_delivery_spec_hash": basis_delivery_spec_hash,
    }


def delivery_turn(
    summary: str = "implemented echo CLI",
    *,
    files: dict[str, str] | None = None,
    checks: dict[str, int | dict[str, Any]] | None = None,
    basis_product_spec_hash: str | None = None,
    transcript: str = "",
) -> Callable[[Any], FakeTurn]:
    # 返回按请求里的当前 ProductSpec 填依据版本的假模型轮次（工单 #471）：
    # 调用方拿到的是脚本项而不是 FakeTurn，写出的提交才能通过依据版本校验
    files = files or {"src/echo.py": "import sys\nprint(sys.argv[1])\n"}
    checks = checks or {"smoke": 0}

    def factory(call: Any) -> FakeTurn:
        declared = basis_product_spec_hash
        if declared is None:
            raw = prompt_part(call, "current_product_spec")
            declared = json.loads(raw).get("content_hash") if raw else None
        return FakeTurn(
            proposal=delivery(summary, files=list(files), check_names=list(checks),
                              basis_product_spec_hash=declared),
            writes=files,
            checks=checks,
            transcript=transcript,
        )

    return factory


def review_turn(
    verdict: str,
    rationale: str,
    *,
    checks: dict[str, int | dict[str, Any]] | None = None,
    defects: list[dict[str, str]] | None = None,
    basis_delivery_spec_hash: str | None = None,
    transcript: str = "",
) -> Callable[[Any], FakeTurn]:
    checks = checks or {"smoke": 0}

    def factory(call: Any) -> FakeTurn:
        declared = basis_delivery_spec_hash
        if declared is None:
            raw = prompt_part(call, "current_delivery_spec")
            declared = json.loads(raw).get("content_hash") if raw else None
        return FakeTurn(
            proposal=review(verdict, rationale, checks=list(checks), defects=defects,
                            basis_delivery_spec_hash=declared),
            checks=checks,
            transcript=transcript,
        )

    return factory
