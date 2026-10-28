# 上下文装配（P）：部门历史的重建、每一步的请求装配（压缩计划、装配、请求构造与上下文清单）、
# 压缩完成以后的检查点。只读取投影、事件与工件，不写入；需要写入的内容交回调用方，由调用方写入。
# 这一份是装配契约第一版（assembly_contract）的实现：它声明 CONTRACT_VERSION，薄驱动在开始一轮工作之前核对；
# 输入与不变量在契约模块里，这里只实现。

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from . import assembly_contract
from .adapters.base import ProviderError
from .artifacts import ArtifactStore
# 每一步装配的输入（身份、版本、路由的工作引用）与窗口的取值是装配契约的输入，定义在契约模块里；这里照旧导出
from .assembly_contract import ModelLimits, StepFrame
from .compaction import (CompactionCheckpoint, CompactionError, CompactionPlan, finish_compaction, plan_compaction,
                         response_reserve, visible_history)
from .context import AssembledContext, ContextAssembler, department_work_text
from .event_store import EventStore
from .models import (ArtifactRef, DepartmentGuidance, Event, EventType, RunProjection,
                     canonical_hash, estimate_tokens, json_dumps)
from .validation import Tightening

PENDING_GUIDANCE = frozenset({"received", "in_input"})

# 判定「同一连接、同一协议、同一上游模型」的取值来自调用目标（设计说明第 7.6 节）
TARGET_KEYS = ("provider_config_id", "protocol", "requested_model")

def _same_target(record_target: dict[str, Any], call_target: dict[str, Any]) -> bool:
    return tuple(record_target.get(key) for key in TARGET_KEYS) == tuple(
        call_target.get(key) for key in TARGET_KEYS)

def replayable_history(history: list[dict[str, Any]], call_target: dict[str, Any]) -> list[dict[str, Any]]:
    # 把部门历史装配成可发给本次调用目标的形式（设计说明第 7.6 节）：
    # 同一条目产生时与本次调用目标同一连接、同一协议、同一上游模型时原样回放；
    # 不同时丢弃推理内容与该协议专用的条目 ID，消息与工具调用的配对（call_id）保持完整
    result: list[dict[str, Any]] = []
    for record in history:
        item = record["item"]
        same = _same_target(record.get("target") or {}, call_target)
        if isinstance(item, dict) and item.get("type") == "reasoning":
            if same:
                result.append(record)
            continue
        if same or not isinstance(item, dict) or "id" not in item:
            result.append(record)
            continue
        stripped = {key: value for key, value in item.items() if key != "id"}
        result.append({**record, "item": stripped, "item_digest": canonical_hash(stripped)})
    return result


def pending_guidance(projection: RunProjection, department: str) -> list[DepartmentGuidance]:
    # 部门还没有回应的指导
    return [item for item in projection.department_guidance
            if item.department == department and item.status in PENDING_GUIDANCE]


def model_limits(target_window: int, output_limit: int | None = None) -> ModelLimits:
    # 阈值只用本次调用目标的窗口。事项级 context_window 不再参与，字段的删除由 #74 完成
    reserve = response_reserve(target_window, output_limit)
    if reserve < 1:
        raise ValueError("the effective context window leaves no room for model output")
    return ModelLimits(target_window, output_limit, reserve)


@dataclass(frozen=True)
class PinnedStep:
    # 一步中固定的部分：部门材料与工具定义，不含部门历史
    projection: RunProjection
    frame: StepFrame
    limits: ModelLimits
    step_id: int
    guidance: list[DepartmentGuidance]
    events: list[Event]
    snapshot_hash: str
    # 调用目标的输入方式（设计说明第 5.6 节）：装配请求的工具定义时按它决定提供哪些工具
    input_modalities: tuple[str, ...]
    context: AssembledContext
    # 本次逻辑调用的调用目标（公开部分）；回放部门历史时按它筛掉来源不同的推理内容
    call_target: dict[str, Any] = field(default_factory=dict)

    @property
    def department_input(self) -> dict[str, Any] | None:
        # 激活第一步写入部门历史的工作消息
        if self.step_id != 1:
            return None
        return {"role": "user", "content": department_work_text(self.context)}

    @property
    def fills_window(self) -> bool:
        # 固定部分已经占满回复之外的窗口：历史无论怎样压缩都放不下
        return self.context.manifest.token_estimate >= self.limits.context_window - self.limits.reserve


@dataclass(frozen=True)
class StepRequest:
    # 一步装配好的请求：发给模型的内容、上下文清单与各段材料、这一步的压缩计划与估算
    context: AssembledContext
    compaction_plan: CompactionPlan | None
    limits: ModelLimits
    payload: dict[str, Any]
    parts: list[dict[str, Any]]
    input_token_estimate: int
    output_reserve_tokens: int

    @property
    def admitted(self) -> bool:
        return self.input_token_estimate + self.output_reserve_tokens <= self.limits.context_window


@dataclass(frozen=True)
class CompactionResult:
    # 压缩请求的回答生成的检查点，连同它的压缩计划与它所接续的上一次压缩
    checkpoint: CompactionCheckpoint
    plan: CompactionPlan
    previous_compaction_event_id: str | None


class ContextAssembly:
    # 装配契约第一版的实现；薄驱动在开始一轮工作之前核对下面这一版
    CONTRACT_VERSION = assembly_contract.CURRENT_VERSION

    def __init__(self, artifacts: ArtifactStore, store: EventStore, *, tightening: Tightening) -> None:
        self.artifacts = artifacts
        self.assembler = ContextAssembler(artifacts, store, tightening=tightening)

    def department_history(self, events: list[Event], department: str, *, session_id: str | None = None) -> list[dict[str, Any]]:
        # 部门历史按事件顺序排列：本部门的工作消息、模型输出、主机提示与工具结果；
        # 失败尝试的模型输出与工具结果、压缩请求的输出不进入历史。
        # 询问分支的内部读取过程不进入部门后续历史，分支结束后只增加一条问题与回答的记录
        branch_starts = {
            event.payload["branch_session_id"]: event
            for event in events
            if event.type == EventType.ASK_STARTED and "branch_session_id" in event.payload
        }
        is_branch = session_id is not None and session_id in branch_starts
        branch_start_event = branch_starts.get(session_id) if is_branch else None

        # 外层会话还没结果的询问调用不进分支的历史（工单 #473 的嵌套询问）：
        # 这个分支就是那次调用的继续，它从那次调用之前的历史开始。
        # 同一个部门的嵌套分支才会遇到：外层主线的询问调用在分支开出来时还没有结果。
        outer_pending_steps: set[tuple[str | None, Any, Any]] = set()
        # 别的会话正在进行的这一步不进分支的历史（同时运行，工单 #557）：
        # 分支开出来的时候，被询问部门的主线会话可能正在一步的中途，这一步的模型输出与工具结果
        # 还没有成对出现。历史以没有结果的工具调用收尾，装配与压缩因此拒绝这个历史。
        # 这一整个步不进分支的历史：模型输出与工具结果成对出现，只留一半同样不成对。
        unfinished_steps: set[tuple[str | None, Any, Any]] = set()
        if is_branch:
            disposed = {
                event.payload.get("id")
                for event in events
                if event.type in (EventType.TOOL_CALLED, EventType.TOOL_SKIPPED)
            }
            for event in events:
                if event.type != EventType.TOOL_STARTED or event.payload.get("name") != "ask":
                    continue
                if event.session_id == session_id or event.payload.get("id") in disposed:
                    continue
                outer_pending_steps.add((event.session_id, event.payload.get("activation_id"),
                                         event.payload.get("step_id")))
            started: dict[tuple[str | None, Any, Any], set[str]] = {}
            answered: dict[tuple[str | None, Any, Any], set[str]] = {}
            for event in events:
                if event.type == EventType.TOOL_STARTED:
                    key = (event.session_id, event.payload.get("activation_id"), event.payload.get("step_id"))
                    started.setdefault(key, set()).add(str(event.payload.get("id")))
                elif event.type in (EventType.TOOL_CALLED, EventType.TOOL_SKIPPED):
                    key = (event.session_id, event.payload.get("activation_id"), event.payload.get("step_id"))
                    answered.setdefault(key, set()).add(str(event.payload.get("id")))
            for key, identities in started.items():
                if identities - answered.get(key, set()):
                    unfinished_steps.add(key)
            # 模型输出里带工具调用、还没有对应结果的整一步同样不进分支的历史（工单 #561）：
            # 别的会话的这一步可能还没有任何工具开始，只有模型输出那一半（等待放行的调用、或者并发时
            # 恰好停在输出与工具开始之间）。工具调用写在模型输出的内容里，所以要看输出的每一项
            for event in events:
                if event.type != EventType.MODEL_MESSAGE or event.session_id == session_id:
                    continue
                if event.payload.get("purpose") == "compaction":
                    continue
                key = (event.session_id, event.payload.get("activation_id"), event.payload.get("step_id"))
                if key in unfinished_steps:
                    continue
                ref = ArtifactRef(**event.payload["message_ref"])
                item = json.loads(self.artifacts.get_for_run(event.run_id, ref))
                if isinstance(item, dict) and item.get("type") == "function_call" \
                        and str(item.get("id")) not in disposed:
                    unfinished_steps.add(key)

        failed_steps = {
            (event.payload.get("activation_id"), event.payload.get("step_id"))
            for event in events
            if event.type == EventType.MODEL_ATTEMPT_FAILED and event.department == department
        }
        records: list[dict[str, Any]] = []
        for event in events:
            if is_branch:
                if (event.session_id, event.payload.get("activation_id"),
                        event.payload.get("step_id")) in outer_pending_steps:
                    continue
                if (event.session_id != session_id
                        and (event.session_id, event.payload.get("activation_id"),
                             event.payload.get("step_id")) in unfinished_steps
                        and event.type not in (EventType.DEPARTMENT_INPUT, EventType.TOOL_CALL_REQUIRED)):
                    # 别的会话正在进行的这一步：模型输出与工具结果都不进分支的历史
                    continue
                if event.session_id in branch_starts and event.session_id != session_id:
                    continue
                if event.session_id != session_id and branch_start_event is not None and event.stream_version >= branch_start_event.stream_version:
                    continue
                if event.session_id not in branch_starts and event.department != department:
                    continue
            else:
                if event.session_id in branch_starts and event.type != EventType.ASK_ANSWERED:
                    continue

            if event.type == EventType.ASK_ANSWERED:
                if event.department == department:
                    q = event.payload.get("question")
                    if not q:
                        for prev in events:
                            if prev.type == EventType.ASK_STARTED and prev.payload.get("branch_session_id") == event.session_id:
                                q = prev.payload.get("question")
                                break
                    ans = event.payload.get("answer", "")
                    item = {"role": "user", "content": f"询问：{q}\n回答：{ans}"}
                    records.append({
                        "event_id": event.event_id,
                        "seq": event.stream_version,
                        "activation_id": event.payload.get("activation_id", ""),
                        "step_id": event.payload.get("step_id", 1),
                        "type": event.type,
                        "item": item,
                        "item_digest": canonical_hash(item),
                        "target": {key: event.payload.get(key) for key in TARGET_KEYS},
                    })
                continue

            if event.department != department:
                continue
            if event.type in {EventType.MODEL_REASONING, EventType.MODEL_MESSAGE,
                              EventType.DEPARTMENT_INPUT, EventType.TOOL_CALL_REQUIRED}:
                if event.payload.get("purpose") == "compaction":
                    continue
                if event.type in {EventType.MODEL_REASONING, EventType.MODEL_MESSAGE} and (
                    event.payload.get("activation_id"), event.payload.get("step_id")
                ) in failed_steps:
                    continue
                key = {
                    EventType.MODEL_REASONING: "reasoning_ref",
                    EventType.MODEL_MESSAGE: "message_ref",
                }.get(event.type, "input_ref")
                ref = ArtifactRef(**event.payload[key])
                item = json.loads(self.artifacts.get_for_run(event.run_id, ref))
                if event.type == EventType.MODEL_MESSAGE and isinstance(item, dict) \
                        and item.get("type") == "reasoning":
                    # 适配器为界面汇总发出的推理观测不进入历史；推理内容由 MODEL_REASONING 保存（设计说明第 7.6 节）
                    continue
            elif event.type in {EventType.TOOL_CALLED, EventType.TOOL_SKIPPED, EventType.ACTION_VERIFIED} and "input_item" in event.payload:
                if (event.payload.get("activation_id"), event.payload.get("step_id")) in failed_steps:
                    continue
                item = event.payload["input_item"]
            else:
                continue
            records.append({"event_id": event.event_id, "seq": event.stream_version,
                            "activation_id": event.payload["activation_id"], "step_id": event.payload["step_id"],
                            "type": event.type, "item": item, "item_digest": canonical_hash(item),
                            "target": {key: event.payload.get(key) for key in TARGET_KEYS}})
        return records

    def pin(self, projection: RunProjection, frame: StepFrame, limits: ModelLimits, *, step_id: int,
            events: list[Event], snapshot_hash: str, call_target: dict[str, Any] | None = None,
            input_modalities: tuple[str, ...] = ("text",)) -> PinnedStep:
        # 装配这一步的固定部分。待处理指导的原文在这个会话的每一步交给部门：
        # 指导在工作期间到达时，它在这个会话的下一步作为通知加入它的历史
        # （工单 #558，循环结构第 6 节）；guidance_results 按给定的事件与工作区快照计算
        guidance = pending_guidance(projection, frame.department)
        context = self.assembler.assemble(
            projection, department=frame.department, session_id=frame.session_id,
            activation_id=frame.activation_id, step_id=step_id, prompt=frame.prompt,
            context_window=limits.context_window, max_output_tokens=limits.output_limit,
            guidance=guidance, events=events, snapshot_hash=snapshot_hash,
            input_modalities=input_modalities,
        )
        return PinnedStep(projection, frame, limits, step_id, guidance, events, snapshot_hash,
                          input_modalities, context, dict(call_target or {}))

    def request(self, pinned: PinnedStep, history: list[dict[str, Any]], *,
                defer_compaction: bool = False) -> StepRequest:
        # 在固定部分之后接上部门历史：按激活采用的版本取最近一次压缩的检查点，
        # 历史放不进窗口时装配一次压缩请求，否则装配工作请求。
        # defer_compaction：上一次整理请求失败过，这一步按未压缩的历史照常交出工作请求，整理放到下一步
        # （设计说明第 8.7 节，工单 #1155）
        # 回放前按本次调用目标筛掉来源不同的推理内容与该协议专用的条目 ID（设计说明第 7.6 节）
        frame, limits = pinned.frame, pinned.limits
        replay_history = replayable_history(history, pinned.call_target)
        checkpoint, checkpoint_id = self._checkpoint(pinned)
        plan = None if defer_compaction else plan_compaction(
            replay_history, checkpoint, limits.context_window, pinned.context.input_items,
            pinned.context.tools, output_limit=limits.output_limit)
        if plan is not None:
            context = self.assembler.assemble_compaction(
                pinned.context, input_items=plan.input_items, source_refs=plan.source_refs,
                max_output_tokens=plan.max_output_tokens, compaction_event_id=checkpoint_id,
            )
        else:
            context = self.assembler.assemble(
                pinned.projection, department=frame.department, session_id=frame.session_id,
                activation_id=frame.activation_id, step_id=pinned.step_id, prompt=frame.prompt,
                history=visible_history(replay_history, checkpoint), compaction_event_id=checkpoint_id,
                context_window=limits.context_window, max_output_tokens=limits.output_limit,
                guidance=pinned.guidance,
                events=pinned.events, snapshot_hash=pinned.snapshot_hash,
                input_modalities=pinned.input_modalities,
            )
        payload: dict[str, Any] = {"input": context.input_items, "tools": context.tools}
        if context.manifest.max_output_tokens is not None:
            payload["max_output_tokens"] = context.manifest.max_output_tokens
        return StepRequest(
            context=context, compaction_plan=plan, limits=limits, payload=payload, parts=_context_parts(context),
            input_token_estimate=estimate_tokens(json_dumps({"input": context.input_items, "tools": context.tools})),
            output_reserve_tokens=context.manifest.max_output_tokens or 0,
        )

    def finish_compaction(self, step: StepRequest, output: list[dict[str, Any]]) -> CompactionResult | None:
        # 压缩请求的回答只能是摘要文字（可以带推理），否则抛出 CompactionError；
        # 摘要为空或超过上限时返回 None，不记录这次压缩，之后的激活重新压缩
        checkpoint = finish_compaction(step.compaction_plan, output)
        if checkpoint is None:
            return None
        return CompactionResult(checkpoint, step.compaction_plan, step.context.manifest.compaction_event_id)

    def _checkpoint(self, pinned: PinnedStep) -> tuple[CompactionCheckpoint | None, str | None]:
        # 摘要必须与它的原始工件一致
        frame, projection = pinned.frame, pinned.projection
        recorded = next((item for item in reversed(projection.compactions)
                         if item["department"] == frame.department
                         and item["effective_contract_hash"] == frame.effective_contract_hash
                         and item["input_version"] == frame.input_version
                         and item["prompt_version"] == frame.prompt.version
                         and item["prompt_hash"] == frame.prompt.prompt_ref.content_hash), None)
        if recorded is None:
            return None, None
        if recorded["run_id"] != projection.run_id:
            raise CompactionError("Compaction checkpoint belongs to a different run")
        checkpoint = CompactionCheckpoint(**recorded["checkpoint"])
        summary = self.artifacts.get_for_run(projection.run_id, ArtifactRef(**recorded["summary_ref"])).decode("utf-8")
        if summary != checkpoint.summary:
            raise CompactionError("Compaction summary does not match its original artifact")
        return checkpoint, recorded["source_event_id"]


def _context_parts(context: AssembledContext) -> list[dict[str, Any]]:
    # 上下文清单列出的每一段材料连同原文，写成 context_parts 工件
    if len(context.parts) != len(context.manifest.injected):
        raise ProviderError("assembled context sources do not match its manifest", reason="provider_protocol")
    result = []
    for part, source in zip(context.parts, context.manifest.injected):
        digest = canonical_hash(part.text)
        if source.digest != digest:
            raise ProviderError("assembled context source digest is inconsistent", reason="provider_protocol")
        result.append({"source": part.source, "version": part.version, "text": part.text, "digest": digest})
    return result
