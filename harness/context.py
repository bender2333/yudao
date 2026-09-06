"""从状态投影装配最小上下文，并记录 ContextManifest。"""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from typing import Any

from .models import (
    ContextExclusion,
    ContextManifest,
    ContextSource,
    DeliverySpec,
    ProductDecision,
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
        "你是工程部门。依据当前有效产品合同修改代码、运行公开检查并提交 DeliverySpec。"
        "当前有效产品合同是 ProductSpec 以及绑定在该 spec 上、尚未被新 spec 取代的已回答产品决策。"
        "无法从当前合同推导的取舍必须提交 AskRequest，不能静默代替产品决策。"
        "必须实际写文件，并用 run_check 让主机执行检查；不能自报 exit_code。"
        "失效交付只作为修复依据，不是当前有效交付。"
        "使用 submit_ask 或 submit_delivery 提交。不能宣布任务完成。"
    ),
    "quality": (
        "你是质检部门。独立读取当前有效产品合同、当前有效 DeliverySpec 和真实代码，亲自运行检查并提交 QAReview。"
        "当前有效产品合同是 ProductSpec 以及绑定在该 spec 上、尚未被新 spec 取代的已回答产品决策。"
        "不能修改交付代码，不能只凭交付单文字放行，也不能把失效交付当作当前交付。"
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
    input_items: list[dict[str, Any]]
    tools: list[dict[str, Any]]


class ContextAssembler:
    def assemble(self, projection: RunProjection, *, department: str, session_id: str, activation_id: str,
                 step_id: int = 1, history: list[dict[str, Any]] | None = None,
                 compaction_event_id: str | None = None) -> AssembledContext:
        parts: list[ContextPart] = [
            ContextPart("intend", None, projection.task),
            ContextPart("current_work", projection.phase, json_dumps(_current_work(projection, department))),
            ContextPart("department_rules", department, DEPARTMENT_RULES[department]),
            ContextPart("proposal_contract", department, json_dumps(PROPOSAL_CONTRACTS[department])),
            ContextPart("binding_refs", None, json_dumps(_binding_refs(projection, department))),
            ContextPart(
                "loop_limits",
                None,
                json_dumps(
                    {
                        "cycles_remaining": max(0, projection.max_cycles - projection.cycle_count),
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
                            "status": spec.status,
                        }
                    ),
                )
            )
        if department in {"engineering", "quality"} and projection.effective_decisions:
            parts.append(
                ContextPart(
                    "current_product_decisions",
                    f"{len(projection.effective_decisions)}",
                    json_dumps([_decision_payload(item) for item in projection.effective_decisions]),
                )
            )
        if department in {"engineering", "quality"}:
            current_delivery = projection.delivery_spec
            if current_delivery is not None and current_delivery.status == "active":
                parts.append(
                    ContextPart(
                        "current_delivery_spec",
                        f"r{current_delivery.revision}",
                        json_dumps(_delivery_payload(current_delivery)),
                    )
                )
            elif department == "engineering":
                prior = _prior_delivery_for_repair(projection)
                if prior is not None:
                    parts.append(
                        ContextPart(
                            "prior_delivery",
                            f"r{prior.revision}",
                            json_dumps(_delivery_payload(prior, purpose="repair_basis")),
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

        prompt_text = "\n\n".join(f"[{part.source}]\n{part.text}" for part in parts)
        input_items = [{"role": "developer", "content": prompt_text}, *deepcopy(history or [])]
        from .tools import host_tool_definitions

        tools = [
            {"type": "function", "name": item["name"], "description": item["description"],
             "parameters": item["parameters"], "strict": False}
            for item in host_tool_definitions(_tools_for(department))
        ]
        if history:
            parts.append(ContextPart("department_history", department, json_dumps(history)))
        parts.append(ContextPart("tool_schemas", department, json_dumps(tools)))
        injected = [
            ContextSource(source=part.source, version=part.version, tokens=estimate_tokens(part.text), digest=canonical_hash(part.text))
            for part in parts
        ]
        excluded = [
            ContextExclusion("other_department_transcript", "cross-department transcripts are never injected"),
            ContextExclusion("superseded_spec_as_current", "older specs remain in department history but are never presented as current requirements"),
            ContextExclusion("expired_product_decisions", "decisions bound to a superseded ProductSpec are not in the current contract"),
            ContextExclusion("invalid_delivery_as_current", "superseded deliveries are not injected as current_delivery_spec"),
        ]
        actual_request = {"input": input_items, "tools": tools}
        token_estimate = estimate_tokens(json_dumps(actual_request))
        digest = canonical_hash(actual_request)
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
            step_id=step_id,
            compaction_event_id=compaction_event_id,
        )
        return AssembledContext(department=department, prompt_text=prompt_text, parts=parts, manifest=manifest,
                                input_items=input_items, tools=tools)

    def assemble_compaction(self, pinned: AssembledContext, *, input_items: list[dict[str, Any]],
                            source_refs: list[dict[str, Any]], max_output_tokens: int,
                            compaction_event_id: str | None) -> AssembledContext:
        parts = [ContextPart("pinned_work", pinned.department, pinned.prompt_text),
                 ContextPart("compaction_request", compaction_event_id, json_dumps(input_items)),
                 ContextPart("compaction_sources", pinned.department, json_dumps(source_refs))]
        request = {"input": input_items, "tools": [], "max_output_tokens": max_output_tokens}
        manifest = ContextManifest(
            session_id=pinned.manifest.session_id, department=pinned.department,
            activation_id=pinned.manifest.activation_id, step_id=pinned.manifest.step_id,
            injected=[ContextSource(part.source, part.version, estimate_tokens(part.text), canonical_hash(part.text)) for part in parts],
            excluded=pinned.manifest.excluded, token_estimate=estimate_tokens(json_dumps(request)),
            budget=pinned.manifest.budget, digest=canonical_hash(request), purpose="compaction",
            max_output_tokens=max_output_tokens, compaction_event_id=compaction_event_id,
        )
        return AssembledContext(pinned.department, pinned.prompt_text, parts, manifest, deepcopy(input_items), [])


def _current_work(projection: RunProjection, department: str) -> dict[str, Any]:
    work = {
        "product": "形成并提交当前产品要求。",
        "engineering": "依据当前产品要求实现、运行检查并提交交付。",
        "quality": "独立验证当前交付，提交放行或返工决定。",
    }[department]
    if department == "product" and projection.pending_ask is not None:
        work = f"当前收到问题 {projection.pending_ask.id}，请回答该问题并使用 submit_reaction 提交决定；此前提交产品要求的工作已经结束。"
    elif department == "product" and projection.phase == "REWORK_PRODUCT":
        work = "根据当前质检缺陷修改产品要求，并提交新的 ProductSpec。"
    elif department == "engineering" and projection.effective_decisions:
        work = "产品回复已经到达。依据 current_product_decisions 中的有效决定继续实现、运行检查并提交交付；已回答的问题无需再次等待回复。"
    return {
        "department": department, "phase": projection.phase, "work": work,
        "current_goal": projection.product_spec.goal if projection.product_spec else None,
        "precedence": "本次列出的当前有效要求和决定优先；后附部门历史保留过往信息，不会使已过时的要求重新生效。",
    }


def _binding_refs(projection: RunProjection, department: str) -> dict[str, Any]:
    spec = projection.product_spec
    delivery = projection.delivery_spec if projection.delivery_spec is not None and projection.delivery_spec.status == "active" else None
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
        "effective_decision_count": len(projection.effective_decisions),
    }


def _validation_feedback(projection: RunProjection, department: str) -> dict[str, Any] | None:
    return projection.pending_feedback.get(department)


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
    for delivery in projection.delivery_specs[-3:]:
        item = {
            "kind": "delivery_spec",
            "revision": f"r{delivery.revision}",
            "status": delivery.status,
            "hash": delivery.content_hash,
            "id": delivery.id,
        }
        if delivery.invalidation_reason:
            item["invalidation_reason"] = delivery.invalidation_reason
        chain.append(item)
    for review in projection.reviews[-3:]:
        chain.append({"kind": "qa_review", "verdict": review.verdict, "hash": review.content_hash, "id": review.id})
    for route in projection.transitions[-8:]:
        chain.append({"kind": "transition", "route": route})
    return chain


def _decision_payload(item: ProductDecision) -> dict[str, Any]:
    return {
        "ask_hash": item.ask_hash,
        "ask_id": item.ask_id,
        "background": item.background,
        "decide_fields": list(item.decide_fields),
        "decision": item.decision,
        "impact": item.impact,
        "options": list(item.options),
        "product_spec_hash": item.product_spec_hash,
        "question": item.question,
        "rationale": item.rationale,
        "reaction_hash": item.reaction_hash,
        "reaction_id": item.reaction_id,
        "recommendation": item.recommendation,
    }


def _delivery_payload(delivery: DeliverySpec, *, purpose: str | None = None) -> dict[str, Any]:
    payload = {
        "check_names": delivery.check_names,
        "checks": delivery.checks,
        "code_tree_digest": delivery.code_tree_digest,
        "content_hash": delivery.content_hash,
        "files": delivery.files,
        "id": delivery.id,
        "invalidation_reason": delivery.invalidation_reason,
        "known_risks": delivery.known_risks,
        "product_spec_hash": delivery.product_spec_hash,
        "revision": delivery.revision,
        "status": delivery.status,
        "summary": delivery.summary,
    }
    if purpose is not None:
        payload["purpose"] = purpose
    return payload


def _prior_delivery_for_repair(projection: RunProjection) -> DeliverySpec | None:
    if projection.delivery_spec is not None and projection.delivery_spec.status == "active":
        return None
    for item in reversed(projection.delivery_specs):
        if item.status != "active":
            return item
    return None


def _tools_for(department: str) -> list[str]:
    from .tools import tools_for

    return tools_for(department)
