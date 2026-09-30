"""从状态投影装配最小上下文，并记录 ContextManifest。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from copy import deepcopy
from typing import Any

from .adjudication import offered_tools
from .contracts import current_contract_hash, current_plan_hash
from .collaboration import guidance_result_summaries
from .artifacts import ArtifactStore
from .definitions import DEFINITIONS
from .models import (
    ArtifactRef,
    ContextExclusion,
    ContextManifest,
    ContextSource,
    DepartmentGuidance,
    DeliverySpec,
    DepartmentPrompt,
    ProductDecision,
    RunProjection,
    canonical_hash,
    estimate_tokens,
    json_dumps,
)

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


def department_work_text(pinned: AssembledContext) -> str:
    static = {"intend", "project", "department_rules", "professional_completion", "collaboration_rules", "input_handling",
              "proposal_contract", "allowed_tools", "department_history", "tool_schemas"}
    return "\n\n".join(f"[{part.source}]\n{part.text}" for part in pinned.parts if part.source not in static)


class ContextAssembler:
    def __init__(self, artifacts: ArtifactStore | None = None) -> None:
        self.artifacts = artifacts

    def assemble(self, projection: RunProjection, *, department: str, session_id: str, activation_id: str,
                 step_id: int = 1, history: list[dict[str, Any]] | None = None,
                 compaction_event_id: str | None = None, prompt: DepartmentPrompt | None = None,
                 context_window: int | None = None, max_output_tokens: int | None = None,
                 guidance: list[DepartmentGuidance] | None = None,
                 guidance_only: bool = False,
                 events: list[Any] | None = None,
                 snapshot_hash: str | None = None) -> AssembledContext:
        effective_window = projection.context_window if context_window is None else context_window
        if (not isinstance(effective_window, int) or isinstance(effective_window, bool)
                or effective_window < 1):
            raise ValueError("context_window must be a positive integer")
        if max_output_tokens is not None and (
                not isinstance(max_output_tokens, int) or isinstance(max_output_tokens, bool)
                or max_output_tokens < 1):
            raise ValueError("max_output_tokens must be a positive integer")
        if prompt is None:
            raise ValueError("a department prompt is required to assemble a request")
        if prompt.department != department:
            raise ValueError("the prompt must belong to the activated department")
        guidance_items = list(guidance or [])
        if any(item.department != department for item in guidance_items):
            raise ValueError("department guidance must belong to the activated department")
        tool_names = offered_tools(projection, department, guidance_only=guidance_only)
        # 全体角色共同的规则文字与本角色的可见范围取自定义
        rules = DEFINITIONS.organization.rules
        visible = DEFINITIONS.role(department).visibility
        # 钉住材料顺序：intend → current_work → project（项目 run）→ department_guidance（有待处理指导）→ department_rules。
        parts: list[ContextPart] = [
            ContextPart("intend", str(projection.input_version), projection.task),
            ContextPart("current_work", projection.phase, json_dumps(_current_work(projection, department))),
        ]
        if projection.project_context_ref is not None:
            if self.artifacts is None:
                raise ValueError("project context requires an artifact store")
            project_text = self.artifacts.get_for_run(
                projection.run_id, ArtifactRef(**projection.project_context_ref),
            ).decode("utf-8")
            parts.append(ContextPart(
                "project",
                projection.project_context_ref["content_hash"].split(":", 1)[1][:12],
                project_text,
            ))
        if guidance_items:
            parts.append(ContextPart(
                "department_guidance",
                str(max(item.version for item in guidance_items)),
                json_dumps([
                    {
                        "id": item.id,
                        "department": item.department,
                        "version": item.version,
                        "text": item.text,
                        "guidance_ref": asdict(item.guidance_ref),
                        "created_event_id": item.created_event_id,
                        "status": item.status,
                    }
                    for item in guidance_items
                ]),
            ))
        parts.extend([
            ContextPart("department_rules", str(prompt.version), prompt.text),
            ContextPart("input_progress", str(projection.input_version), json_dumps({
                "received": projection.input_version, "assigned_to_product": projection.product_work_input_version,
                "accepted_in_requirements": projection.processed_input_version,
            })),
            ContextPart("input_handling", None, rules.input_handling),
            ContextPart("professional_completion", None, rules.professional_completion),
            ContextPart("collaboration_rules", None, rules.collaboration_rules),
            ContextPart("proposal_contract", department, json_dumps(DEFINITIONS.proposal_contract(department))),
            ContextPart("binding_refs", None, json_dumps(_binding_refs(projection, department))),
            ContextPart("allowed_tools", department, json_dumps(tool_names)),
        ])
        pending_inputs = [item for item in projection.inputs
                          if item.version > projection.processed_input_version and item.kind == "text"]
        if pending_inputs:
            parts.append(ContextPart("pending_inputs", str(projection.product_work_input_version), json_dumps(pending_inputs)))
        feedback = _validation_feedback(projection, department)
        if feedback:
            parts.append(ContextPart("validation_feedback", feedback.get("event_id"), json_dumps(feedback)))
        if projection.effective_contract is not None:
            parts.append(ContextPart("current_contract", projection.effective_contract.content_hash,
                                     json_dumps(projection.effective_contract)))
        if projection.engineering_plan is not None:
            parts.append(ContextPart("current_engineering_plan", projection.engineering_plan.content_hash,
                                     json_dumps(projection.engineering_plan)))
        if projection.pending_request is not None:
            request = projection.pending_request
            parts.append(ContextPart("pending_request", request.id, json_dumps(request)))
            parts.append(ContextPart("request_results", request.id, json_dumps([
                item for item in projection.request_results if item["request_id"] == request.id
            ])))
        pending_for_results = [item for item in projection.department_guidance
                               if item.department == department and item.status in {"received", "in_input"}]
        if pending_for_results and events:
            parts.append(ContextPart(
                "guidance_results",
                None,
                json_dumps(guidance_result_summaries(projection, department, events, snapshot_hash or "")),
            ))
        prior_request = next((item for item in reversed(projection.requests) if item.requester == department and item.status != "open"), None)
        if prior_request is not None:
            response = next((item for item in reversed(projection.responses) if item.request_id == prior_request.id), None)
            parts.append(ContextPart("latest_response", prior_request.id, json_dumps({"request": prior_request, "response": response})))
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
                            "created_event_id": spec.created_event_id,
                            "non_goals": spec.non_goals,
                            "requirements": spec.requirements,
                            "revision": spec.revision,
                            "status": spec.status,
                            "decision_changes": spec.decision_changes,
                            "change_record": spec.change_record,
                            "input_version": spec.input_version,
                        }
                    ),
                )
            )
        if projection.effective_decisions:
            parts.append(
                ContextPart(
                    "current_product_decisions",
                    f"{len(projection.effective_decisions)}",
                    json_dumps([_decision_payload(item) for item in projection.effective_decisions]),
                )
            )
        current_delivery = projection.delivery_spec
        if current_delivery is not None and current_delivery.status != "active":
            current_delivery = None
        if current_delivery is not None and "current_delivery_spec" in visible:
            parts.append(
                ContextPart(
                    "current_delivery_spec",
                    f"r{current_delivery.revision}",
                    json_dumps(_delivery_payload(current_delivery)),
                )
            )
        elif current_delivery is None and "prior_delivery" in visible:
            prior = _prior_delivery_for_repair(projection)
            if prior is not None:
                parts.append(
                    ContextPart(
                        "prior_delivery",
                        f"r{prior.revision}",
                        json_dumps(_delivery_payload(prior, purpose="repair_basis")),
                    )
                )
        if "qa_defects" in visible and projection.last_review and projection.last_review.verdict.startswith("rework"):
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
        from .tools import tool_definitions

        tools = [
            {"type": "function", "name": item["name"], "description": item["description"],
             "parameters": item["parameters"], "strict": False}
            for item in tool_definitions(tool_names)
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
            ContextExclusion("expired_product_decisions", "earlier decisions enter the current contract only when the current ProductSpec explicitly retains them"),
            ContextExclusion("invalid_delivery_as_current", "superseded deliveries are not injected as current_delivery_spec"),
        ]
        input_token_estimate = estimate_tokens(json_dumps({"input": input_items, "tools": tools}))
        if max_output_tokens is not None:
            # The request may spend whatever the window leaves after its input, up to the
            # model's declared limit; compaction keeps the input below the response reserve.
            max_output_tokens = min(max_output_tokens, effective_window - input_token_estimate)
            if max_output_tokens < 1:
                raise ValueError("the model request leaves no room for model output")
        actual_request = {"input": input_items, "tools": tools}
        if max_output_tokens is not None:
            actual_request["max_output_tokens"] = max_output_tokens
        token_estimate = estimate_tokens(json_dumps(actual_request))
        digest = canonical_hash(actual_request)
        manifest = ContextManifest(
            session_id=session_id,
            department=department,
            activation_id=activation_id,
            injected=injected,
            excluded=excluded,
            token_estimate=token_estimate,
            budget=effective_window,
            digest=digest,
            truncated=False,
            step_id=step_id,
            compaction_event_id=compaction_event_id,
            effective_contract_hash=current_contract_hash(projection),
            engineering_plan_hash=current_plan_hash(projection),
            request_id=None if projection.pending_request is None else projection.pending_request.id,
            input_version=projection.input_version,
            prompt_version=prompt.version,
            prompt_hash=prompt.prompt_ref.content_hash,
            max_output_tokens=max_output_tokens,
            input_token_estimate=input_token_estimate,
            output_reserve_tokens=max_output_tokens or 0,
            guidance_ids=[item.id for item in guidance_items],
            guidance_only=guidance_only,
        )
        return AssembledContext(department=department, prompt_text=prompt_text, parts=parts, manifest=manifest,
                                input_items=input_items, tools=tools)

    def assemble_compaction(self, pinned: AssembledContext, *, input_items: list[dict[str, Any]],
                            source_refs: list[dict[str, Any]], max_output_tokens: int,
                            compaction_event_id: str | None) -> AssembledContext:
        if (not isinstance(max_output_tokens, int) or isinstance(max_output_tokens, bool)
                or max_output_tokens < 1):
            raise ValueError("max_output_tokens must be a positive integer")
        if max_output_tokens > pinned.manifest.budget:
            raise ValueError("max_output_tokens cannot exceed the effective context window")
        parts = [ContextPart("pinned_work", pinned.department, pinned.prompt_text),
                 ContextPart("compaction_request", compaction_event_id, json_dumps(input_items)),
                 ContextPart("compaction_sources", pinned.department, json_dumps(source_refs))]
        request = {"input": input_items, "tools": [], "max_output_tokens": max_output_tokens}
        input_token_estimate = estimate_tokens(json_dumps({"input": input_items, "tools": []}))
        manifest = ContextManifest(
            session_id=pinned.manifest.session_id, department=pinned.department,
            activation_id=pinned.manifest.activation_id, step_id=pinned.manifest.step_id,
            injected=[ContextSource(part.source, part.version, estimate_tokens(part.text), canonical_hash(part.text)) for part in parts],
            excluded=pinned.manifest.excluded, token_estimate=estimate_tokens(json_dumps(request)),
            budget=pinned.manifest.budget, digest=canonical_hash(request), purpose="compaction",
            max_output_tokens=max_output_tokens, compaction_event_id=compaction_event_id,
            effective_contract_hash=pinned.manifest.effective_contract_hash,
            engineering_plan_hash=pinned.manifest.engineering_plan_hash,
            request_id=pinned.manifest.request_id,
            input_version=pinned.manifest.input_version,
            prompt_version=pinned.manifest.prompt_version,
            prompt_hash=pinned.manifest.prompt_hash,
            input_token_estimate=input_token_estimate,
            output_reserve_tokens=max_output_tokens,
            guidance_ids=list(pinned.manifest.guidance_ids),
            guidance_only=pinned.manifest.guidance_only,
        )
        return AssembledContext(pinned.department, pinned.prompt_text, parts, manifest, deepcopy(input_items), [])


def _current_work(projection: RunProjection, department: str) -> dict[str, Any]:
    work = {
        "product": "形成并提交当前产品要求。",
        "engineering": "依据当前产品要求实现、运行检查并提交交付。",
        "quality": "独立验证当前交付，提交放行或返工决定。",
    }[department]
    if department == "product" and projection.phase == "REWORK_PRODUCT":
        work = "根据当前质检缺陷修改产品要求，并提交新的 ProductSpec。"
    elif department == "engineering" and projection.effective_decisions:
        work = "依据 current_product_decisions 中已正式接纳的有效决定继续当前工程工作。"
    if department == "engineering" and projection.engineering_plan is None:
        work += " 当前没有有效工程计划，请先提交绑定 current_contract.content_hash 的 submit_plan，接纳后再修改代码。"
    if projection.pending_request is not None and projection.pending_request.recipient == department:
        request = projection.pending_request
        work = (f"处理来自 {request.requester} 的请求 {request.id}：{request.question}。"
                f"预期结果：{request.expected_result}。完成正常动作或形成意见后用 submit_response 回应；"
                "已经正式接纳的结果会列在 request_results 中，回复不能替代正常需求、计划或交付接纳。")
    pending_guidance = [item for item in projection.department_guidance
                        if item.department == department and item.status in {"received", "in_input"}]
    if pending_guidance:
        work += (f" 当前有 {len(pending_guidance)} 条待处理部门指导。先阅读 department_guidance 中的原文，"
                 "然后用 submit_guidance_response 逐条回应：explained 表示已解释或无需新动作，"
                 "completed 表示本指导被采用后的动作已有主机结果。"
                 "guidance_results 只列出本指导被采用后可由宿主绑定的结果；completed 时宿主绑定这些结果，不必手抄事件 id；"
                 "指导不能替代产品要求、工程计划或质检放行。")
    return {
        "department": department, "phase": projection.phase, "work": work,
        "current_goal": projection.product_spec.goal if projection.product_spec else None,
        "precedence": "本次列出的当前有效要求和决定优先；后附部门历史保留过往信息，不会使已过时的要求重新生效。",
    }


def _binding_refs(projection: RunProjection, department: str) -> dict[str, Any]:
    spec = projection.product_spec
    delivery = projection.delivery_spec if projection.delivery_spec is not None and projection.delivery_spec.status == "active" else None
    return {
        "department": department,
        "phase": projection.phase,
        "product_spec_id": None if spec is None else spec.id,
        "product_spec_hash": None if spec is None else spec.content_hash,
        "product_spec_revision": None if spec is None else spec.revision,
        "effective_contract_hash": current_contract_hash(projection),
        "engineering_plan_hash": current_plan_hash(projection),
        "delivery_spec_id": None if delivery is None else delivery.id,
        "delivery_spec_hash": None if delivery is None else delivery.content_hash,
        "delivery_code_tree_digest": None if delivery is None else delivery.code_tree_digest,
        "request_id": None if projection.pending_request is None else projection.pending_request.id,
        "effective_decision_count": len(projection.effective_decisions),
        "pending_guidance_ids": [item.id for item in projection.department_guidance
                                 if item.department == department and item.status in {"received", "in_input"}],
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
    for request in projection.requests[-3:]:
        chain.append({"kind": "collaboration_request", "id": request.id, "hash": request.content_hash, "status": request.status})
    for response in projection.responses[-3:]:
        chain.append({"kind": "collaboration_response", "status": response.status, "hash": response.content_hash, "id": response.id})
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
    return asdict(item)


def _delivery_payload(delivery: DeliverySpec, *, purpose: str | None = None) -> dict[str, Any]:
    payload = {
        "check_names": delivery.check_names,
        "checks": delivery.checks,
        "code_tree_digest": delivery.code_tree_digest,
        "tree_ref": delivery.tree_ref,
        "content_hash": delivery.content_hash,
        "files": delivery.files,
        "id": delivery.id,
        "created_event_id": delivery.created_event_id,
        "invalidation_reason": delivery.invalidation_reason,
        "known_risks": delivery.known_risks,
        "product_spec_hash": delivery.product_spec_hash,
        "effective_contract_hash": delivery.effective_contract_hash,
        "engineering_plan_hash": delivery.engineering_plan_hash,
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
