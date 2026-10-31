"""结构化提案构造器。只生成 payload，校验和状态改变仍由控制层完成。"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .adapters.fake import FakeTurn, prompt_part
from .providers.call import ModelCall


def default_requirement_mapping(requirements: list[str], acceptance: list[str]) -> list[dict[str, Any]]:
    # 测试脚本的默认对应声明（工单 #1178）：第 n 条要求指向 AC<n>，多出来的要求写明写不出验收标准的原因
    mapping: list[dict[str, Any]] = []
    for position in range(1, len(requirements) + 1):
        if position <= len(acceptance):
            mapping.append({"requirement": position, "criteria": [f"AC{position}"]})
        else:
            mapping.append({"requirement": position,
                            "gap": "no separate acceptance criterion is defined for this requirement"})
    return mapping


def product_spec(
    goal: str = "build an echo CLI",
    requirements: list[str] | None = None,
    acceptance: list[str] | None = None,
    basis_product_spec_hash: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    requirements = requirements or ["print the given argument to stdout"]
    acceptance = acceptance or ["running the program with a word prints that word"]
    payload = {
        "kind": "product_spec",
        "goal": goal,
        "requirements": requirements,
        "boundaries": extra.get("boundaries", ["do not read files"]),
        "constraints": extra.get("constraints", ["single file implementation"]),
        "acceptance_criteria": acceptance,
        "requirement_mapping": extra.get("requirement_mapping") or default_requirement_mapping(requirements, acceptance),
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


def product_decision(statement: str, rationale: str) -> dict[str, Any]:
    return {"kind": "product_decision", "statement": statement, "rationale": rationale}


def delivery(
    summary: str = "implemented echo CLI",
    check_names: list[str] | None = None,
    known_risks: list[str] | None = None,
    basis_product_spec_hash: str | None = None,
) -> dict[str, Any]:
    # 交付的文件清单由主机从封存的交付快照得出，工程不再填（工单 #677）
    return {
        "kind": "delivery_spec",
        "summary": summary,
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


def default_criteria(count: int, checks: list[str], *,
                     method: str = "check", result: str = "passed") -> list[dict[str, Any]]:
    # 逐条结论的默认项（工单 #151）：每条验收条件一项，AC1 起按位置编号，都用给出的检查名当证据。
    # 要写别的检验方式或结果的用例显式传 criteria
    return [{"criterion": f"AC{position}", "method": method, "result": result,
             "checks": list(checks), "trial_cases": [], "note": ""}
            for position in range(1, count + 1)]


def judgement(
    checks: list[str] | None = None,
    criteria: list[dict[str, Any]] | None = None,
    basis_delivery_spec_hash: str | None = None,
    criteria_count: int = 1,
) -> dict[str, Any]:
    # 独立判断的提案（验证的独立性设计说明第 4 节，工单 #358）：先判断后看解释——
    # 在只看事实的上下文里对当前交付的每条验收条件写出判断，门（提交结论前必须有它）读这个事件
    names = checks or ["smoke"]
    return {
        "kind": "independent_judgement",
        "checks": list(names),
        "criteria": default_criteria(criteria_count, list(names)) if criteria is None else criteria,
        "basis_delivery_spec_hash": basis_delivery_spec_hash,
    }


def judgement_turn(
    checks: dict[str, int | dict[str, Any]] | None = None,
    *,
    basis_delivery_spec_hash: str | None = None,
    criteria: list[dict[str, Any]] | None = None,
    transcript: str = "",
) -> Callable[[Any], FakeTurn]:
    # 独立判断的假模型轮次：按请求里的当前交付填依据版本，检查名与回执同名（与 review_turn 的做法一致）。
    # 逐条结论的条数按请求里当前 ProductSpec 的验收条件数生成（acceptance_criteria_count）
    checks = checks or {"smoke": 0}

    def factory(call: Any) -> FakeTurn:
        declared = basis_delivery_spec_hash
        if declared is None:
            raw = prompt_part(call, "current_delivery_spec")
            declared = json.loads(raw).get("content_hash") if raw else None
        return FakeTurn(
            proposal=judgement(list(checks), criteria=criteria, basis_delivery_spec_hash=declared,
                               criteria_count=acceptance_criteria_count(call)),
            checks=checks,
            transcript=transcript,
        )

    return factory


def acceptance_criteria_count(call: Any) -> int:
    # 请求里的当前 ProductSpec 有几条验收条件：逐条结论按这个条数生成，与真实模型从上下文读到的一样
    raw = prompt_part(call, "current_product_spec")
    if not raw:
        return 1
    spec = json.loads(raw)
    return max(1, len(spec.get("acceptance_criteria") or []))


def review(
    verdict: str,
    rationale: str,
    checks: list[str] | None = None,
    defects: list[dict[str, str]] | None = None,
    basis_delivery_spec_hash: str | None = None,
    criteria: list[dict[str, Any]] | None = None,
    criteria_count: int = 1,
) -> dict[str, Any]:
    names = checks or ["smoke"]
    return {
        "kind": "qa_review",
        "verdict": verdict,
        "rationale": rationale,
        "checks": names,
        "defects": defects or [],
        "criteria": default_criteria(criteria_count, list(names)) if criteria is None else criteria,
        "basis_delivery_spec_hash": basis_delivery_spec_hash,
    }


def delivery_turn(
    summary: str = "implemented echo CLI",
    *,
    files: dict[str, str] | None = None,
    checks: dict[str, int | dict[str, Any]] | None = None,
    basis_product_spec_hash: str | None = None,
    known_risks: list[str] | None = None,
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
            proposal=delivery(summary, check_names=list(checks), known_risks=known_risks,
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
    criteria: list[dict[str, Any]] | None = None,
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
                            basis_delivery_spec_hash=declared, criteria=criteria,
                            criteria_count=acceptance_criteria_count(call)),
            checks=checks,
            transcript=transcript,
        )

    return factory
def ask_turn(
    recipient: str = "product",
    question: str = "Should the output format be revised?",
    *,
    background: str = "Clarification needed during implementation.",
    expected: str = "Clarified requirement or spec revision.",
    call_id: str = "ask-1",
) -> Any:
    from .providers.call import ModelResponse
    return ModelResponse(output=[{
        "id": call_id,
        "call_id": call_id,
        "type": "function_call",
        "name": "ask",
        "arguments": json.dumps({
            "recipient": recipient,
            "question": question,
            "background": background,
            "expected": expected,
        }),
    }])


def answer_turn(
    answer: str = "Clarification given.",
    *,
    goal: str | None = None,
    requirements: list[str] | None = None,
    acceptance: list[str] | None = None,
    basis_product_spec_hash: str | None = None,
    change_record: dict[str, Any] | None = None,
    call_id: str = "ans-1",
    **extra: Any,
) -> Callable[[Any], Any]:
    from .providers.call import ModelResponse

    def factory(call: Any) -> ModelResponse:
        args: dict[str, Any] = {"answer": answer}
        if requirements is not None:
            args["requirements"] = requirements
            args["goal"] = goal or "build an echo CLI"
            args["acceptance_criteria"] = acceptance or ["prints the argument"]
            # 修订也要带要求与验收标准的对应声明（工单 #1178），默认每条要求指向同序的验收标准
            args["requirement_mapping"] = extra.get("requirement_mapping") or default_requirement_mapping(
                list(requirements), list(args["acceptance_criteria"]))
            declared = basis_product_spec_hash
            if declared is None:
                raw = prompt_part(call, "current_product_spec")
                declared = json.loads(raw).get("content_hash") if raw else None
            args["basis_product_spec_hash"] = declared
            if change_record is not None:
                cr = dict(change_record)
                cr.setdefault("retired", [])
                cr.setdefault("rationale", "Clarification revision.")
                args["change_record"] = cr
            for k in ("boundaries", "constraints", "fatal_conditions", "non_goals", "decision_changes"):
                if k in extra:
                    args[k] = extra[k]
        return ModelResponse(output=[{
            "id": call_id,
            "call_id": call_id,
            "type": "function_call",
            "name": "answer",
            "arguments": json.dumps(args),
        }])

    return factory
