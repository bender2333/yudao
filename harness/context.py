"""从状态投影装配最小上下文，并记录 ContextManifest。"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from .models import (
    ContextExclusion,
    ContextManifest,
    ContextSource,
    RunProjection,
    canonical_hash,
    estimate_tokens,
    json_dumps,
)

DEPARTMENT_RULES = {
    "product": (
        "你是产品部门。只定义目标、用户价值、范围、约束、验收标准和不可接受结果。"
        "不能修改交付代码，不能直接放行任务。"
        "对 AskRequest 只能 accept、reply 或 reject；需要改合同时提交新的 ProductSpec。"
        "使用 submit_product_spec 或 submit_reaction 提交；自然语言中的“完成”不会改变任务状态。"
    ),
    "engineering": (
        "你是工程部门。依据当前有效 ProductSpec 修改代码、运行公开检查并提交 DeliverySpec。"
        "无法从 spec 推导的取舍必须提交 AskRequest，不能静默代替产品决策。"
        "必须实际写文件，并用 run_check 让主机执行检查；不能自报 exit_code。"
        "使用 submit_ask 或 submit_delivery 提交。不能宣布任务完成。"
    ),
    "quality": (
        "你是质检部门。独立读取当前 ProductSpec、DeliverySpec 和真实代码，亲自运行检查并提交 QAReview。"
        "不能修改交付代码，不能只凭交付单文字放行。"
        "使用 collect_evidence 或 run_check 让主机执行检查，再 submit_review。"
        "只有绑定当前 ProductSpec 和代码快照的 release 才允许结束任务。"
        "自然语言中的“完成”不会改变任务状态。"
    ),
}

PROPOSAL_CONTRACTS: dict[str, dict[str, Any]] = {
    "product": {
        "submit_tools": ["submit_product_spec", "submit_reaction"],
        "kinds": {
            "product_spec": {
                "when": ["PRODUCT_SPEC", "REWORK_PRODUCT"],
                "required": ["kind=product_spec", "goal", "requirements", "acceptance_criteria"],
                "optional": ["boundaries", "constraints", "fatal_conditions", "non_goals"],
            },
            "product_reaction": {
                "when": ["PRODUCT_REACT"],
                "required": ["kind=product_reaction", "decision", "rationale"],
                "optional": ["spec_update"],
                "decision": ["accept", "reply", "reject"],
                "bind": ["pending_ask.id", "pending_ask.content_hash"],
            },
        },
        "notes": [
            "spec_update 在改写合同时提供，字段与 ProductSpec 相同。",
            "控制层校验失败会返回字段级错误，下一轮按 validation_feedback 修正。",
        ],
    },
    "engineering": {
        "submit_tools": ["submit_ask", "submit_delivery"],
        "kinds": {
            "ask_request": {
                "when": ["ENGINEERING", "REWORK_ENGINEERING"],
                "required": [
                    "kind=ask_request",
                    "question",
                    "background",
                    "options",
                    "impact",
                    "recommendation",
                    "decide_fields",
                ],
                "bind": ["current_product_spec.content_hash"],
            },
            "delivery_spec": {
                "when": ["ENGINEERING", "REWORK_ENGINEERING"],
                "required": ["kind=delivery_spec", "summary", "files", "check_names"],
                "optional": ["known_risks"],
                "bind": [
                    "current_product_spec.content_hash",
                    "workspace files must exist",
                    "engineering host check receipts on the current snapshot",
                ],
            },
        },
        "notes": [
            "先 write_file，再 run_check（argv 由主机执行），最后 submit_delivery。",
            "check_names 必须对应主机回执，模型自报 exit_code 无效。",
        ],
    },
    "quality": {
        "submit_tools": ["submit_review"],
        "kinds": {
            "qa_review": {
                "when": ["QUALITY"],
                "required": ["kind=qa_review", "verdict", "rationale", "checks"],
                "optional": ["defects"],
                "verdict": ["rework_product", "rework_engineering", "release"],
                "bind": [
                    "current_product_spec.content_hash",
                    "current_delivery_spec.content_hash",
                    "current code snapshot",
                    "quality host check receipts; engineering receipts are rejected",
                ],
            },
        },
        "notes": [
            "release 要求缺陷为空且质量检查 exit_code 均为 0。",
            "rework 至少包含一条缺陷。",
        ],
    },
}


@dataclass(frozen=True)
class ContextPart:
    source: str
    version: str | None
    text: str


@dataclass(frozen=True)
class AssembledContext:
    department: str
    prompt_text: str
    parts: list[ContextPart]
    manifest: ContextManifest


class ContextAssembler:
    def assemble(self, projection: RunProjection, *, department: str, session_id: str, activation_id: str) -> AssembledContext:
        parts: list[ContextPart] = [
            ContextPart("department_rules", department, DEPARTMENT_RULES[department]),
            ContextPart("task_summary", None, projection.task),
            ContextPart("proposal_contract", department, json_dumps(PROPOSAL_CONTRACTS[department])),
            ContextPart("binding_refs", None, json_dumps(_binding_refs(projection, department))),
            ContextPart(
                "remaining_budget",
                None,
                json_dumps(
                    {
                        "cycles_remaining": max(0, projection.max_cycles - projection.cycle_count),
                        "token_budget": projection.token_budget,
                        "token_used": projection.token_used,
                        "token_remaining": max(0, projection.token_budget - projection.token_used),
                    }
                ),
            ),
            ContextPart("allowed_tools", department, json_dumps(_tools_for(department))),
        ]
        feedback = _validation_feedback(projection, department)
        if feedback:
            parts.append(ContextPart("validation_feedback", feedback.get("event_id"), json_dumps(feedback)))
        if projection.product_spec and projection.product_spec.status == "active":
            spec = projection.product_spec
            parts.append(
                ContextPart(
                    "current_product_spec",
                    f"r{spec.revision}",
                    json_dumps(
                        {
                            "acceptance_criteria": spec.acceptance_criteria,
                            "boundaries": spec.boundaries,
                            "constraints": spec.constraints,
                            "content_hash": spec.content_hash,
                            "fatal_conditions": spec.fatal_conditions,
                            "goal": spec.goal,
                            "id": spec.id,
                            "non_goals": spec.non_goals,
                            "requirements": spec.requirements,
                            "revision": spec.revision,
                        }
                    ),
                )
            )
        if department in {"engineering", "quality"} and projection.delivery_spec:
            delivery = projection.delivery_spec
            parts.append(
                ContextPart(
                    "current_delivery_spec",
                    f"r{delivery.revision}",
                    json_dumps(
                        {
                            "check_names": delivery.check_names,
                            "checks": delivery.checks,
                            "code_tree_digest": delivery.code_tree_digest,
                            "content_hash": delivery.content_hash,
                            "files": delivery.files,
                            "id": delivery.id,
                            "known_risks": delivery.known_risks,
                            "product_spec_hash": delivery.product_spec_hash,
                            "summary": delivery.summary,
                        }
                    ),
                )
            )
        if department == "product" and projection.pending_ask:
            ask = projection.pending_ask
            parts.append(
                ContextPart(
                    "pending_ask",
                    ask.id,
                    json_dumps(
                        {
                            "background": ask.background,
                            "content_hash": ask.content_hash,
                            "decide_fields": ask.decide_fields,
                            "id": ask.id,
                            "impact": ask.impact,
                            "options": ask.options,
                            "product_spec_hash": ask.product_spec_hash,
                            "question": ask.question,
                            "recommendation": ask.recommendation,
                            "revision": ask.revision,
                        }
                    ),
                )
            )
        if department == "engineering" and projection.last_reaction:
            reaction = projection.last_reaction
            parts.append(
                ContextPart(
                    "last_reaction",
                    reaction.id,
                    json_dumps(
                        {
                            "ask_id": reaction.ask_id,
                            "ask_hash": reaction.ask_hash,
                            "content_hash": reaction.content_hash,
                            "decision": reaction.decision,
                            "id": reaction.id,
                            "new_spec_hash": reaction.new_spec_hash,
                            "rationale": reaction.rationale,
                        }
                    ),
                )
            )
        if department in {"product", "engineering"} and projection.last_review and projection.last_review.verdict.startswith("rework"):
            review = projection.last_review
            parts.append(
                ContextPart(
                    "qa_defects",
                    review.id,
                    json_dumps(
                        {
                            "defects": [item.__dict__ for item in review.defects],
                            "rationale": review.rationale,
                            "verdict": review.verdict,
                        }
                    ),
                )
            )
        parts.append(ContextPart("causal_chain", None, json_dumps(_causal_chain(projection))))

        injected = [
            ContextSource(source=part.source, version=part.version, tokens=estimate_tokens(part.text), digest=canonical_hash(part.text))
            for part in parts
        ]
        excluded = [
            ContextExclusion("other_department_transcript", "cross-department transcripts are never injected"),
            ContextExclusion("superseded_spec_fulltext", "old spec bodies are not injected; only current spec and thin causal markers"),
            ContextExclusion("historical_transcript", "department history is not passed; context is rebuilt from the projection"),
            ContextExclusion("private_reasoning", "private model reasoning is stored as an artifact and not shared"),
            ContextExclusion("omp_autodiscovery", "OMP skills, extensions, rules, builtins, LSP, and persistent sessions are disabled"),
        ]
        token_estimate = sum(item.tokens for item in injected)
        digest = canonical_hash(
            {
                "budget": projection.context_window,
                "department": department,
                "excluded": [asdict(item) for item in excluded],
                "injected": [{"source": item.source, "version": item.version} for item in injected],
                "token_estimate": token_estimate,
            }
        )
        prompt_text = "\n\n".join(f"[{part.source}]\n{part.text}" for part in parts)
        manifest = ContextManifest(
            session_id=session_id,
            department=department,
            activation_id=activation_id,
            injected=injected,
            excluded=excluded,
            token_estimate=token_estimate,
            budget=projection.context_window,
            digest=digest,
            truncated=False,
        )
        return AssembledContext(department=department, prompt_text=prompt_text, parts=parts, manifest=manifest)


def _binding_refs(projection: RunProjection, department: str) -> dict[str, Any]:
    spec = projection.product_spec
    delivery = projection.delivery_spec
    ask = projection.pending_ask
    return {
        "department": department,
        "phase": projection.phase,
        "product_spec_id": None if spec is None else spec.id,
        "product_spec_hash": None if spec is None else spec.content_hash,
        "product_spec_revision": None if spec is None else spec.revision,
        "delivery_spec_id": None if delivery is None else delivery.id,
        "delivery_spec_hash": None if delivery is None else delivery.content_hash,
        "delivery_code_tree_digest": None if delivery is None else delivery.code_tree_digest,
        "pending_ask_id": None if ask is None else ask.id,
        "pending_ask_hash": None if ask is None else ask.content_hash,
    }


def _validation_feedback(projection: RunProjection, department: str) -> dict[str, Any] | None:
    for item in reversed(projection.rejections):
        if item.get("department") == department:
            return item
    return None


def _causal_chain(projection: RunProjection) -> list[dict[str, str]]:
    chain: list[dict[str, str]] = []
    for spec in projection.product_specs[-4:]:
        chain.append(
            {
                "kind": "product_spec",
                "revision": f"r{spec.revision}",
                "status": spec.status,
                "hash": spec.content_hash,
                "id": spec.id,
            }
        )
    for ask in projection.asks[-3:]:
        chain.append({"kind": "ask_request", "id": ask.id, "hash": ask.content_hash, "status": ask.status})
    for reaction in projection.reactions[-3:]:
        chain.append({"kind": "product_reaction", "decision": reaction.decision, "hash": reaction.content_hash, "id": reaction.id})
    for review in projection.reviews[-3:]:
        chain.append({"kind": "qa_review", "verdict": review.verdict, "hash": review.content_hash, "id": review.id})
    for route in projection.transitions[-8:]:
        chain.append({"kind": "transition", "route": route})
    return chain


def _tools_for(department: str) -> list[str]:
    from .tools import tools_for

    return tools_for(department)
