"""从状态投影装配最小上下文，并记录 ContextManifest。"""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
from copy import deepcopy
from typing import Any

from .adjudication import offered_tools
from .compaction import request_input_tokens
from .contracts import artifact_hash
from .providers.invoke import ToolImage, tool_image_part, tool_text_part
from .watched_outputs import has_new_baseline_review
from .artifacts import ArtifactStore
from .definitions import DEFINITIONS
from .event_store import EventStore
from .models import (
    ArtifactRef,
    ContextExclusion,
    ContextManifest,
    ContextSource,
    DepartmentGuidance,
    DeliverySpec,
    DepartmentPrompt,
    Event,
    EventType,
    ProductDecision,
    ProjectEventType,
    RunProjection,
    canonical_hash,
    estimate_tokens,
    hash_bytes,
    json_dumps,
)
from .validation import Tightening

# 调用目标没有给出窗口时按这个值处理（工单 #669）：窗口是调用目标的属性，run 不再冻结它
DEFAULT_CONTEXT_WINDOW = 32_000


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
    static = {"intend", "project", "department_rules", "work_item_guidance", "professional_completion",
              "collaboration_rules", "input_handling", "proposal_contract", "allowed_tools",
              "department_history", "tool_schemas"}
    return "\n\n".join(f"[{part.source}]\n{part.text}" for part in pinned.parts if part.source not in static)


# 工具结果里的图像放进请求的张数与换出的粒度（浏览器与 computer use 设计说明第 6.2 节，取值参照
# Anthropic 参考实现 `_maybe_filter_to_n_most_recent_images`：保留最近 3 张，换出按 3 张一组）
REQUEST_IMAGE_KEPT = 3
REQUEST_IMAGE_BATCH = 3


def evidence_placeholder(evidence: str) -> str:
    # 换出请求的图像换成这一行占位文字：模型仍知道这张截图已保存为证据，可以按编号引用
    return f"截图 {evidence} 已保存为证据"


def frozen_visibility(projection: RunProjection, department: str) -> tuple[str, ...]:
    # 三条 roles.<部门>.visibility 在建 run 时冻结（工单 #1189）：上下文装配只读这一份；
    # 旧 run 的事件没有冻结字典时按定义初值解释（不取参数现值，也不取较新的定义）
    from .parameters import frozen_run_parameters

    declared = frozen_run_parameters(projection).get(f"roles.{department}.visibility")
    if declared is None:
        return tuple(DEFINITIONS.role(department).visibility)
    return tuple(str(item) for item in declared)


def request_history(history: list[dict[str, Any]], *, run_id: str, artifacts: ArtifactStore | None,
                    input_modalities: tuple[str, ...] = ("text",)) -> list[dict[str, Any]]:
    """部门历史里的工具结果按调用目标的输入方式放进请求（设计说明第 6.2 节）。

    调用目标包含图像时读出图像字节，只保留最近 3 张，更早的换成一行占位文字，换出按 3 张一组；
    不含图像时截图不放进请求，历史里已有的图像全部换成占位文字。
    """
    total = sum(len(item.get("images") or ()) for item in history)
    if not total:
        return list(history)
    removed = 0 if "image" in input_modalities else total
    if "image" in input_modalities:
        removed = total - REQUEST_IMAGE_KEPT
        removed -= removed % REQUEST_IMAGE_BATCH
    result: list[dict[str, Any]] = []
    for item in history:
        images = item.get("images") or ()
        if not images:
            result.append(item)
            continue
        cut = max(0, min(len(images), removed))
        removed -= cut
        result.append(_request_tool_result(item, images[:cut], images[cut:],
                                           run_id=run_id, artifacts=artifacts))
    return result


def _request_tool_result(item: dict[str, Any], replaced: list[dict[str, Any]], kept: list[dict[str, Any]],
                         *, run_id: str, artifacts: ArtifactStore | None) -> dict[str, Any]:
    # 一张工具结果在请求里的样子：文字块在前，换出的图像按原位置换成占位文字，保留的图像读成图像块
    result = {key: value for key, value in item.items() if key != "images"}
    text = item.get("output") if isinstance(item.get("output"), str) else ""
    result["output"] = [
        tool_text_part(text),
        *(tool_text_part(evidence_placeholder(str(image["content_hash"]))) for image in replaced),
        *(_request_image(image, run_id=run_id, artifacts=artifacts) for image in kept),
    ]
    return result


def _request_image(image: dict[str, Any], *, run_id: str, artifacts: ArtifactStore | None) -> dict[str, Any]:
    if artifacts is None:
        raise ValueError("tool result images require an artifact store")
    ref = ArtifactRef(**{key: image[key] for key in ("kind", "content_hash", "path", "media_type")})
    raw = artifacts.get_for_run(run_id, ref)
    return tool_image_part(ToolImage(media_type=str(image["media_type"]),
                                     data=base64.b64encode(raw).decode("ascii")))


def work_notifications(projection: RunProjection, events: list[Any] | None, department: str,
                       session_id: str | None) -> list[dict[str, Any]]:
    # 这个会话还没有看到的新东西（工单 #558、工单 #964）：PRD 的新版本、交付到达与用户追加的输入。
    # 判据是「这个会话上一次装配请求以后」写下的东西：它在这个会话的下一步作为通知送达，
    # 部门接着工作，这一轮不因此结束。通知只在会话之间比较，同一会话里下一次请求不再重复送达同一份通知。
    if session_id is None:
        return []
    items = list(events or [])
    positions: dict[str, int] = {}
    producers: dict[str, str | None] = {}
    seen = -1
    for event in items:
        positions[event.event_id] = event.position
        producers[event.event_id] = event.session_id
        if event.type == EventType.CONTEXT_ASSEMBLED and event.session_id == session_id:
            # 判据是这个会话上一次装配请求的位置：请求里的材料就是那时候算出来的。
            # 事件在装配以后到达（包括装配与发出之间到达的），在这个会话的下一步送达，
            # 不会因为请求晚一点发出而丢掉。
            seen = event.position
    notifications: list[dict[str, Any]] = []
    # 用户追加的输入（工单 #964）：输入到达不再结束部门当前这一轮，它作为通知在这个会话的下一步送达。
    # 输入仍然分派给产品部门处理（product_input_assigned），产品的 processed_input_version 照常前进。
    for event in items:
        if event.type != EventType.USER_INPUT_RECEIVED or event.position <= seen:
            continue
        payload = event.payload or {}
        notifications.append({
            "kind": "user_input_received",
            "version": payload.get("version"),
            "text": payload.get("text") or "",
        })
    for spec in projection.product_specs:
        if spec.status != "active":
            continue
        position = positions.get(spec.created_event_id)
        if position is None or position <= seen:
            continue
        if producers.get(spec.created_event_id) == session_id:
            # 这个会话自己写下的版本：不用通知自己
            continue
        notifications.append({
            "kind": "product_spec_revised",
            "revision": spec.revision,
            "content_hash": spec.content_hash,
            "change_record": spec.change_record,
            "decision_changes": spec.decision_changes,
        })
    if department == "quality":
        # 交付到达只通知质检：它面对的代码随交付变化，检查工作区因此重建（local-tools 第 2 节）
        for delivery in projection.delivery_specs:
            if delivery.status != "active":
                continue
            position = positions.get(delivery.created_event_id)
            if position is None or position <= seen:
                continue
            if producers.get(delivery.created_event_id) == session_id:
                continue
            notifications.append({
                "kind": "delivery_arrived",
                "revision": delivery.revision,
                "content_hash": delivery.content_hash,
                "files": delivery.files,
                "product_spec_hash": delivery.product_spec_hash,
            })
    # 产品决定（工单 #1079）：判据与 PRD 新版本相同，通知给所有部门。决定只重算有效合同、
    # 不产生新的 PRD 版本，没有这一条通知，部门不知道放行为什么被拒绝、交付为什么过期
    for decision in projection.product_decisions:
        position = positions.get(decision.created_event_id)
        if position is None or position <= seen:
            continue
        if producers.get(decision.created_event_id) == session_id:
            # 这个会话自己写下的决定：不用通知自己
            continue
        notifications.append({
            "kind": "product_decision_recorded",
            "statement": decision.statement,
            "rationale": decision.rationale,
            "content_hash": decision.content_hash,
        })
    return notifications


def _notification_text(item: dict[str, Any]) -> str:
    if item["kind"] == "user_input_received":
        # 用户追加的输入（工单 #964）：通知写明新到的这一版输入；输入由产品部门处理成新的产品要求，
        # 部门接着当前工作，不因为输入到达而结束这一轮。
        return (f"用户追加了输入（第 {item.get('version')} 版）：{item.get('text') or ''}。"
                "这份输入分派给产品部门处理成新的产品要求；这一轮不因此结束，"
                "已有的工作还算不算数由你自己判断，接着当前工作。")
    if item["kind"] == "product_spec_revised":
        record = item.get("change_record") or {}
        changed = record.get("changed") if isinstance(record, dict) else None
        detail = f"；改动：{'；'.join(changed)}" if changed else ""
        return (f"产品要求有了新版本 r{item['revision']}{detail}。"
                "这份要求现在有效，已经做的工作还算不算数由你自己判断，接着当前工作。")
    if item["kind"] == "product_decision_recorded":
        # 产品决定只重算有效合同，不产生新的 PRD 版本（工单 #1079）：写明决定与理由，
        # 让收到的部门知道交付为什么过期、放行为什么被拒绝
        return (f"产品记录了补充决定：{item.get('statement') or ''}。理由：{item.get('rationale') or ''}。"
                "有效合同因此重算，在此之前依据旧合同的交付不再有效；"
                "按新的有效合同接着当前工作。")
    # 交付到达的通知只给事实部分（工单 #554）：交付说明里的解释部分在质检下结论以前不给
    return (f"新的交付到达了（r{item['revision']}，{len(item.get('files') or [])} 个文件）。"
            "检查工作区已经从这份交付重建，交付之前写的测试材料仍然在；接着当前工作。")


class ContextAssembler:
    def __init__(self, artifacts: ArtifactStore | None = None, store: EventStore | None = None, *,
                 tightening: Tightening) -> None:
        self.artifacts = artifacts
        # 修改轮的上一轮候选属于项目流，只能按事件编号取（设计第 4.7 节）
        self.store = store
        # 请求里提供哪些工具由路由的收紧检查取舍（工单 #1095）
        self.tightening = tightening


    def assemble(self, projection: RunProjection, *, department: str, session_id: str, activation_id: str,
                 step_id: int = 1, history: list[dict[str, Any]] | None = None,
                 compaction_event_id: str | None = None, prompt: DepartmentPrompt | None = None,
                 context_window: int | None = None, max_output_tokens: int | None = None,
                 guidance: list[DepartmentGuidance] | None = None,
                 events: list[Any] | None = None,
                 snapshot_hash: str | None = None,
                 input_modalities: tuple[str, ...] = ("text",)) -> AssembledContext:
        effective_window = context_window if context_window is not None else DEFAULT_CONTEXT_WINDOW
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
        tool_names = offered_tools(projection, department, tightening=self.tightening,
                                   session_id=session_id, input_modalities=input_modalities)
        # 全体角色共同的规则文字取自定义；本角色的可见范围读这个 run 冻结的取值（工单 #1189）
        rules = DEFINITIONS.organization.rules
        visible = frozen_visibility(projection, department)
        current_delivery = projection.delivery_spec
        if current_delivery is not None and current_delivery.status != "active":
            current_delivery = None
        # 质检请求里可以放入的工程内容（工单 #554）：事实部分总在，解释部分看质检有没有对当前交付下结论
        engineering = (quality_engineering_content(events or [], delivery=current_delivery)
                       if department == "quality" else None)
        # 这个会话要回答的那一次询问：询问分支看自己那一次（一个部门可以同时有几个分支，工单 #559），
        # 主线会话沿用询问链上最内层的那一次
        pending_ask = projection.ask_by_branch(session_id) or projection.active_ask
        # 钉住材料顺序：intend → current_work → project（项目 run）→ department_guidance（有待处理指导）→ department_rules。
        notifications = work_notifications(projection, events, department, session_id)
        current_work = _current_work(projection, department, engineering, notifications, ask=pending_ask)
        parts: list[ContextPart] = [
            ContextPart("intend", str(projection.input_version), projection.task),
            ContextPart("current_work", _current_work_version(current_work),
                        json_dumps(current_work)),
        ]
        if notifications:
            parts.append(ContextPart(
                "work_notification",
                canonical_hash(notifications)[:12],
                json_dumps(notifications),
            ))
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
        if projection.kind == "onboarding" and projection.overview_ref is not None:
            # 仓库概况：建档中三个部门都看得见的常驻栏目，由控制核心按快照生成（设计第 4.2 节）
            if self.artifacts is None:
                raise ValueError("the repository overview requires an artifact store")
            parts.append(ContextPart(
                "existing_overview",
                projection.overview_ref["content_hash"].split(":", 1)[1][:12],
                self.artifacts.get_for_run(
                    projection.run_id, ArtifactRef(**projection.overview_ref),
                ).decode("utf-8"),
            ))
        if "existing_structure" in visible and projection.structure is not None:
            # 现有结构说明：只有工程的可见范围包含它（设计第 4.4 节，工单 #134 验收第 5 项）
            if self.artifacts is None:
                raise ValueError("the structure description requires an artifact store")
            structure = projection.structure
            parts.append(ContextPart(
                "existing_structure",
                structure["content_hash"].split(":", 1)[1][:12],
                self.artifacts.get_for_run(
                    projection.run_id, ArtifactRef(**structure["structure_ref"]),
                ).decode("utf-8") + "\n\n" + json_dumps({
                    "code_tree_digest": structure["code_tree_digest"],
                    "product_spec_hash": structure["product_spec_hash"],
                    "revision": structure["revision"],
                }),
            ))
        parts.extend(self._prior_parts(projection, department))
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
        work = DEFINITIONS.department_work(department, projection.kind)
        work_text = work.prompt if work is not None else DEFINITIONS.role(department).prompt
        parts.extend([
            ContextPart("department_rules", str(prompt.version), prompt.text),
            ContextPart("work_item_guidance", projection.kind, work_text),
            ContextPart("input_progress", str(projection.input_version), json_dumps({
                "received": projection.input_version, "assigned_to_product": projection.product_work_input_version,
                "accepted_in_requirements": projection.processed_input_version,
            })),
            ContextPart("input_handling", None, rules.input_handling),
            ContextPart("professional_completion", None, rules.professional_completion),
            ContextPart("collaboration_rules", None, rules.collaboration_rules),
            ContextPart("proposal_contract", department, json_dumps(DEFINITIONS.proposal_contract(department, projection.kind))),
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
        if pending_ask is not None:
            ask = pending_ask
            if ask.get("recipient") == department:
                payload = dict(ask)
                if engineering is not None and not engineering["explanation_visible"]:
                    # 质检分支看到的问题：解释部分在质检对当前交付下结论以前不给（工单 #554）
                    payload.pop("explanation", None)
                parts.append(ContextPart("pending_ask", ask.get("branch_session_id"), json_dumps(payload)))
        if engineering is not None and engineering["explanations"]:
            # 质检对当前交付下结论以后，工程在问答里的解释部分进入它之后的请求（工单 #554）
            parts.append(ContextPart("engineering_explanation", None,
                                     json_dumps(engineering["explanations"])))
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
                            "requirement_mapping": spec.requirement_mapping,
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
        if current_delivery is not None and "current_delivery_spec" in visible:
            payload = (engineering["delivery"] if engineering is not None
                       else _delivery_payload(current_delivery))
            parts.append(
                ContextPart(
                    "current_delivery_spec",
                    f"r{current_delivery.revision}",
                    json_dumps(payload),
                )
            )
        elif current_delivery is None and "prior_delivery" in visible:
            prior = _prior_delivery_for_repair(projection)
            if prior is not None:
                payload = _delivery_payload(prior, purpose="repair_basis")
                if engineering is not None and not engineering["explanation_visible"]:
                    # 新的交付还没有结论：此前全部工程内容的解释部分都重新藏起来（工单 #554）
                    for field in _delivery_explanation_fields():
                        payload.pop(field, None)
                parts.append(
                    ContextPart(
                        "prior_delivery",
                        f"r{prior.revision}",
                        json_dumps(payload),
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
        input_items = [{"role": "developer", "content": prompt_text},
                       *deepcopy(request_history(history or [], run_id=projection.run_id,
                                                 artifacts=self.artifacts,
                                                 input_modalities=input_modalities))]
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
        input_token_estimate = request_input_tokens(input_items, tools)
        if max_output_tokens is not None:
            # The request may spend whatever the window leaves after its input, up to the
            # model's declared limit; compaction keeps the input below the response reserve.
            max_output_tokens = min(max_output_tokens, effective_window - input_token_estimate)
            if max_output_tokens < 1:
                raise ValueError("the model request leaves no room for model output")
        token_estimate = request_input_tokens(input_items, tools, max_output_tokens)
        actual_request = {"input": input_items, "tools": tools}
        if max_output_tokens is not None:
            actual_request["max_output_tokens"] = max_output_tokens
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
            effective_contract_hash=artifact_hash(projection.effective_contract),
            input_version=projection.input_version,
            prompt_version=prompt.version,
            prompt_hash=prompt.prompt_ref.content_hash,
            max_output_tokens=max_output_tokens,
            input_token_estimate=input_token_estimate,
            output_reserve_tokens=max_output_tokens or 0,
            guidance_ids=[item.id for item in guidance_items],
        )
        return AssembledContext(department=department, prompt_text=prompt_text, parts=parts, manifest=manifest,
                                input_items=input_items, tools=tools)

    def _prior_parts(self, projection: RunProjection, department: str) -> list[ContextPart]:
        # 修改轮的常驻材料：产品看到上一轮的初始 PRD 与这一轮用户的修改意见，工程看到上一轮的结构说明，
        # 质检只核验这一轮新写出的初始 PRD，上一轮的原文都不给它（设计第 4.7 节最后一段）
        if department not in {"product", "engineering"} or self.store is None or self.artifacts is None:
            return []
        basis = projection.onboarding_basis
        if basis is None:
            return []
        event = self.store.get_project_event(str(basis.get("candidate_event_id") or ""))
        if event is None or event.type != ProjectEventType.INITIAL_PRD_PROPOSED:
            return []
        candidate = event.payload
        prior_run_id, round_number = candidate["run_id"], candidate["round"]
        prd = candidate["prd"]
        parts: list[ContextPart] = []
        if department == "product":
            parts.append(ContextPart(
                "prior_initial_prd",
                prd["content_hash"].split(":", 1)[1][:12],
                f"上一轮（第 {round_number} 轮）的初始 PRD 原文。修改意见由这一轮新的 ProductSpec 处理，"
                f"这份 PRD 不直接沿用。\n\n"
                + self.artifacts.get_for_run(prior_run_id, ArtifactRef(**prd["prd_ref"])).decode("utf-8"),
            ))
            note_ref = basis.get("note_ref")
            if note_ref is not None:
                # 修改意见的工件按这一轮 run 的目录存放，它同时是这一轮的第一项用户输入
                parts.append(ContextPart(
                    "revision_note",
                    note_ref["content_hash"].split(":", 1)[1][:12],
                    self.artifacts.get_for_run(projection.run_id, ArtifactRef(**note_ref)).decode("utf-8"),
                ))
            return parts
        structure = candidate["structure"]
        parts.append(ContextPart(
            "prior_structure",
            structure["content_hash"].split(":", 1)[1][:12],
            self.artifacts.get_for_run(
                prior_run_id, ArtifactRef(**structure["structure_ref"]),
            ).decode("utf-8") + "\n\n" + json_dumps({
                "round": round_number,
                "code_tree_digest": structure["code_tree_digest"],
                "product_spec_hash": prd["content_hash"],
            }),
        ))
        return parts

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
            input_version=pinned.manifest.input_version,
            prompt_version=pinned.manifest.prompt_version,
            prompt_hash=pinned.manifest.prompt_hash,
            input_token_estimate=input_token_estimate,
            output_reserve_tokens=max_output_tokens,
            guidance_ids=list(pinned.manifest.guidance_ids),
        )
        return AssembledContext(pinned.department, pinned.prompt_text, parts, manifest, deepcopy(input_items), [])


def _current_work_version(current_work: dict[str, Any]) -> str:
    # 当前工作材料的版本：内容变了就是新的一份（阶段状态机删掉以后不再由阶段表示，工单 #556）
    return hash_bytes(json_dumps(current_work).encode("utf-8"))


def _current_work(projection: RunProjection, department: str,
                  engineering: dict[str, Any] | None = None,
                  notifications: list[dict[str, Any]] | None = None,
                  ask: dict[str, Any] | None = None) -> dict[str, Any]:
    if projection.kind == "onboarding":
        # 建档事项中的工作文字（工单 #134）：读取与核验现有代码，没有实现与放行
        work = {
            "product": "依据 existing_overview 与读取到的代码、文档、测试，形成并提交描述现有行为的初始 PRD。",
            "engineering": "读取现有代码，用 run_check 运行构建与测试的命令，提交绑定当前快照的现有结构说明。",
            "quality": "独立核验初始 PRD 与现有行为是否一致，提交基线核验。",
        }[department]
    else:
        work = {
            "product": "形成并提交当前产品要求。",
            "engineering": "依据当前产品要求实现、运行检查并提交交付。",
            "quality": "独立验证当前交付，提交放行或返工决定。",
        }[department]
    if department == "product" and has_new_baseline_review(projection):
        work = ("根据基线核验中 unsupported 的结论与遗漏修改初始 PRD 的描述，并提交新的 ProductSpec。"
                if projection.kind == "onboarding"
                else "根据当前质检缺陷修改产品要求，并提交新的 ProductSpec。")
    elif department == "engineering" and projection.effective_decisions:
        work = "依据 current_product_decisions 中已正式接纳的有效决定继续当前工程工作。"
    if ask is not None:
        if ask.get("recipient") == department:
            question = str(ask.get("question") or "")
            background = str(ask.get("background") or "")
            if engineering is not None:
                # 质检分支看到的问题：只留事实部分，解释部分等质检对当前交付下结论以后（工单 #554）
                question = str(ask.get("facts") or question)
                background = ""
            work = (f"回答来自 {ask.get('requester')} 的询问：{question}。"
                    f"背景：{background}。期望结果：{ask.get('expected', '')}。"
                    "使用 answer 工具提交回答。")
    pending_guidance = [item for item in projection.department_guidance
                        if item.department == department and item.status in {"received", "in_input"}]
    if pending_guidance:
        work += (f" 当前有 {len(pending_guidance)} 条待处理部门指导。先阅读 department_guidance 中的原文。"
                 "指导不能替代产品要求、交付说明或质检放行。"
                 "这一轮只有指导、没有要做的工作时，直接用文字回答即可。")
    for item in notifications or []:
        work += " " + _notification_text(item)
    return {
        "department": department, "work": work,
        "current_goal": projection.product_spec.goal if projection.product_spec else None,
        "precedence": "本次列出的当前有效要求和决定优先；后附部门历史保留过往信息，不会使已过时的要求重新生效。",
    }


def _binding_refs(projection: RunProjection, department: str) -> dict[str, Any]:
    spec = projection.product_spec
    delivery = projection.delivery_spec if projection.delivery_spec is not None and projection.delivery_spec.status == "active" else None
    return {
        "department": department,
        "product_spec_id": None if spec is None else spec.id,
        "product_spec_hash": None if spec is None else spec.content_hash,
        "product_spec_revision": None if spec is None else spec.revision,
        "effective_contract_hash": artifact_hash(projection.effective_contract),
        "delivery_spec_id": None if delivery is None else delivery.id,
        "delivery_spec_hash": None if delivery is None else delivery.content_hash,
        "delivery_code_tree_digest": None if delivery is None else delivery.code_tree_digest,
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
    return chain


def _decision_payload(item: ProductDecision) -> dict[str, Any]:
    return asdict(item)


def _delivery_payload(delivery: DeliverySpec, *, purpose: str | None = None,
                      explanation_visible: bool = True) -> dict[str, Any]:
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
        # 启动方式属于事实部分（工单 #148）：质检按它开始试用会话
        "launch": delivery.launch,
        "product_spec_hash": delivery.product_spec_hash,
        "effective_contract_hash": delivery.effective_contract_hash,
        "revision": delivery.revision,
        "status": delivery.status,
        "summary": delivery.summary,
    }
    if purpose is not None:
        payload["purpose"] = purpose
    if not explanation_visible:
        # 解释部分还没有到质检看的时候：只留事实部分（工单 #554）
        for field in _delivery_explanation_fields():
            payload.pop(field, None)
    return payload


def _delivery_explanation_fields() -> tuple[str, ...]:
    # 交付说明里属于解释部分的字段：提案合同里标明（工单 #554）
    contract = DEFINITIONS.proposal_contracts.roles["engineering"].kinds["delivery_spec"]
    parts = contract.get("parts") or {}
    return tuple(str(field) for field in parts.get("explanation") or ())


def quality_engineering_content(events: list[Event], *, delivery: DeliverySpec | None = None) -> dict[str, Any]:
    # 质检请求里可以放入的工程内容（工单 #554，验证的独立性设计说明第 4 节）：
    # 事实部分总在；解释部分只在质检对当前交付提交结论以后进入它之后的请求。
    # 新的交付到达后按新交付重新计算：解释部分重新藏起来，等质检对新交付的结论。
    # 三条通道：交付说明、质检收到的工程回答、质检分支看到的工程的问题。
    delivery_hash = delivery.content_hash if delivery is not None else _latest_delivery_hash(events)
    explanation_visible = delivery_hash is not None and any(
        event.type == EventType.QA_SUBMITTED
        and (event.payload or {}).get("delivery_spec_hash") == delivery_hash
        for event in events
    )
    asks: dict[str, dict[str, Any]] = {}
    questions: list[dict[str, Any]] = []
    answers: list[dict[str, Any]] = []
    for event in events:
        payload = event.payload or {}
        if event.type == EventType.ASK_STARTED:
            item = {
                "event_id": event.event_id,
                "branch_session_id": payload.get("branch_session_id"),
                "question": payload.get("question", ""),
                "background": payload.get("background", ""),
                "expected": payload.get("expected", ""),
                "facts": payload.get("facts", ""),
                "explanation": payload.get("explanation", ""),
            }
            asks[str(payload.get("branch_session_id"))] = item
            if payload.get("requester") == "engineering" and payload.get("recipient") == "quality":
                # 工程问质检的问题：分事实与解释两部分（工单 #554）
                questions.append(item)
        elif event.type == EventType.ASK_ANSWERED \
                and payload.get("requester") == "quality" and payload.get("recipient") == "engineering":
            # 工程回答质检的回答：分事实与解释两部分（工单 #554）
            asked = asks.get(event.session_id, {})
            answers.append({
                "event_id": event.event_id,
                "branch_session_id": event.session_id,
                "question": asked.get("question", ""),
                "question_facts": "",
                "question_explanation": "",
                "answer": payload.get("answer", ""),
                "facts": payload.get("facts", ""),
                "explanation": payload.get("explanation", ""),
            })
    return {
        "explanation_visible": explanation_visible,
        "delivery": None if delivery is None else _delivery_payload(
            delivery, explanation_visible=explanation_visible),
        "questions": questions,
        "answers": answers,
        # 问答的解释部分：质检对当前交付下结论以后进入它之后的请求（工单 #554）
        "explanations": [
            {
                "branch_session_id": item["branch_session_id"],
                "answer": engineering_facts_text(item, part="answer", explanation_visible=True),
            }
            for item in answers
            if explanation_visible and str(item.get("explanation") or "").strip()
        ],
    }


def _latest_delivery_hash(events: list[Event]) -> str | None:
    # 事件日志里最近一次封存的交付：质检对它的结论决定解释部分是否可见（工单 #554）
    for event in reversed(events):
        if event.type == EventType.DELIVERY_ACCEPTED:
            return str((event.payload or {}).get("content_hash") or "") or None
    return None


def engineering_facts_text(item: dict[str, Any], *, part: str = "answer",
                           explanation_visible: bool) -> str:
    # 一次问答在质检那里的样子：解释部分不可见时只留事实部分（工单 #554）
    if part == "question":
        facts = str(item.get("question_facts") or "").strip()
        fallback = str(item.get("question") or "")
        explanation = str(item.get("question_explanation") or "").strip()
    else:
        facts = str(item.get("facts") or "").strip()
        fallback = str(item.get("answer") or "")
        explanation = str(item.get("explanation") or "").strip()
    text = facts or fallback
    if explanation_visible and explanation:
        return f"{text}\n{explanation}" if text else explanation
    return text


def _prior_delivery_for_repair(projection: RunProjection) -> DeliverySpec | None:
    if projection.delivery_spec is not None and projection.delivery_spec.status == "active":
        return None
    for item in reversed(projection.delivery_specs):
        if item.status != "active":
            return item
    return None
