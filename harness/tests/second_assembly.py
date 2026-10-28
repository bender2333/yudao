# 第二种装配实现（工单 #979；只在测试里用，产品代码不导入它）。
#
# 装配契约第一版（`harness/assembly_contract.py`；骨架与应用设计说明第 5.2 节；总图第四节「装配」缝）的
# 第二种实现。与真实现（`assembly.py` 的 `ContextAssembly`）的差别是形状与取法，不是合同：
#
# - 固定部分只有两栏：定义里的部门提示，加这一轮任务的那一句（带路由原样交来的工作引用）。
# - 它不从事件日志里减历史：事件里记下的输入条目按顺序原样接上，不看调用目标、不切换、不压缩。
#   这一版没有压缩，`finish_compaction` 一律回答空（契约允许：摘要为空时不记录这次压缩）。
# - 仍然交出装配好的请求与上下文清单，两者由执行实现记进日志；它自己一条事件都不写（装配不改事实）。
#
# 契约固定的是输入与不变量，固定部分的形状是实现自己的：这里用 `SecondPinnedStep` 与 `SecondStepRequest`
# 两个自己的类型，只有执行实现要读的几样（固定的部分、装配好的请求、上下文清单与估算）与真实现同名。

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from harness import assembly_contract
from harness.context import AssembledContext, ContextPart
from harness.models import (
    ContextExclusion,
    ContextManifest,
    ContextSource,
    Event,
    RunProjection,
    canonical_hash,
    estimate_tokens,
    json_dumps,
)


@dataclass(frozen=True)
class SecondPinnedStep:
    # 这一步固定的部分：只有部门提示与这一轮任务那一句两栏，不含部门历史
    projection: RunProjection
    frame: assembly_contract.StepFrame
    limits: assembly_contract.ModelLimits
    step_id: int
    context: AssembledContext

    @property
    def department_input(self) -> dict[str, Any] | None:
        # 激活第一步写入部门历史的工作消息：这一版就是这一轮任务那一句
        if self.step_id != 1:
            return None
        return {"role": "user", "content": _round_task_text(self.context)}

    @property
    def fills_window(self) -> bool:
        return self.context.manifest.token_estimate >= self.limits.context_window - self.limits.reserve


@dataclass(frozen=True)
class SecondStepRequest:
    # 一步装配好的请求：发给模型的内容、上下文清单与各段材料；这一版没有压缩计划
    context: AssembledContext
    limits: assembly_contract.ModelLimits
    payload: dict[str, Any]
    parts: list[dict[str, Any]]
    input_token_estimate: int
    output_reserve_tokens: int
    # 这一版不压缩：压缩计划是实现的形状，这里永远是空，执行实现的 finish_compaction 因此总回答空
    compaction_plan: None = None

    @property
    def admitted(self) -> bool:
        return self.input_token_estimate + self.output_reserve_tokens <= self.limits.context_window


class SecondAssembly:
    # 装配契约第一版的第二种实现；薄驱动在开始一轮工作之前核对下面这一版
    CONTRACT_VERSION = assembly_contract.CURRENT_VERSION

    def department_history(self, events: list[Event], department: str, *,
                           session_id: str | None = None) -> list[dict[str, Any]]:
        # 不减历史：这个部门（与这个会话）在事件里记下的输入条目按顺序原样交出，
        # 失败的尝试、压缩请求的输出都不筛掉
        items: list[dict[str, Any]] = []
        for event in events:
            if event.department != department:
                continue
            if session_id is not None and event.session_id != session_id:
                continue
            item = (event.payload or {}).get("input_item")
            if isinstance(item, dict):
                items.append(item)
        return items

    def pin(self, projection: RunProjection, frame: assembly_contract.StepFrame,
            limits: assembly_contract.ModelLimits, *, step_id: int, events: list[Event],
            snapshot_hash: str, call_target: dict[str, Any] | None = None,
            input_modalities: tuple[str, ...] = ("text",)) -> SecondPinnedStep:
        # 固定部分不带历史：历史在 request 里整段接上
        return SecondPinnedStep(projection, frame, limits, step_id,
                                _context(projection, frame, limits, step_id=step_id, history=[]))

    def request(self, pinned: SecondPinnedStep, history: list[dict[str, Any]]) -> SecondStepRequest:
        context = _context(pinned.projection, pinned.frame, pinned.limits,
                           step_id=pinned.step_id, history=history)
        payload: dict[str, Any] = {"input": context.input_items, "tools": context.tools}
        if context.manifest.max_output_tokens is not None:
            payload["max_output_tokens"] = context.manifest.max_output_tokens
        return SecondStepRequest(
            context=context, limits=pinned.limits, payload=payload, parts=_parts(context),
            input_token_estimate=estimate_tokens(json_dumps(payload)),
            output_reserve_tokens=context.manifest.max_output_tokens or 0,
        )

    def finish_compaction(self, step: SecondStepRequest, output: list[dict[str, Any]]) -> None:
        # 这一版不压缩：回答空，不记录这次压缩（契约：摘要为空或超过上限时为空）
        return None


def _round_task_text(context: AssembledContext) -> str:
    # 这一轮任务那一句在上下文里的位置
    for part in context.parts:
        if part.source == _ROUND_TASK_SOURCE:
            return part.text
    return ""


_ROUND_TASK_SOURCE = "round_task"


def _task_line(projection: RunProjection, frame: assembly_contract.StepFrame) -> str:
    # 这一轮的任务一句：事项的任务，加上路由原样交来的工作引用（第 5.4 节第 4 条，骨架不解释它）
    line = f"这一轮的任务：{projection.task}"
    if frame.work_ref is not None:
        line += f"\n这一轮的工作引用：{json_dumps(frame.work_ref)}"
    return line


def _context(projection: RunProjection, frame: assembly_contract.StepFrame,
             limits: assembly_contract.ModelLimits, *, step_id: int,
             history: list[dict[str, Any]]) -> AssembledContext:
    # 固定部分两栏，接上整段历史；上下文清单逐段记下来源、版本、token 估算与摘要
    parts = [
        ContextPart("department_prompt", str(frame.prompt.version), frame.prompt.text),
        ContextPart(_ROUND_TASK_SOURCE, frame.department, _task_line(projection, frame)),
    ]
    if history:
        parts.append(ContextPart("department_history", frame.department, json_dumps(history)))
    prompt_text = "\n\n".join(f"[{part.source}]\n{part.text}" for part in parts)
    input_items: list[dict[str, Any]] = [{"role": "developer", "content": prompt_text},
                                        *deepcopy(history)]
    # 这一版不给工具：它只证明缝，不证明部门能用哪些工具（工具清单照旧归定义与装配实现）
    tools: list[dict[str, Any]] = []
    injected = [ContextSource(source=part.source, version=part.version,
                              tokens=estimate_tokens(part.text), digest=canonical_hash(part.text))
                for part in parts]
    excluded = [ContextExclusion("department_history_compaction",
                                 "this implementation never compresses history")]
    input_token_estimate = estimate_tokens(json_dumps({"input": input_items, "tools": tools}))
    max_output_tokens = limits.output_limit
    if max_output_tokens is not None:
        max_output_tokens = min(max_output_tokens, limits.context_window - input_token_estimate)
        if max_output_tokens < 1:
            # 窗口已经被固定部分占满：与真实现一样以装配失败交出（执行实现换成 context_overflow）
            raise ValueError("the model request leaves no room for model output")
    request_payload: dict[str, Any] = {"input": input_items, "tools": tools}
    if max_output_tokens is not None:
        request_payload["max_output_tokens"] = max_output_tokens
    manifest = ContextManifest(
        session_id=frame.session_id,
        department=frame.department,
        activation_id=frame.activation_id,
        injected=injected,
        excluded=excluded,
        token_estimate=estimate_tokens(json_dumps(request_payload)),
        budget=limits.context_window,
        digest=canonical_hash(request_payload),
        step_id=step_id,
        effective_contract_hash=frame.effective_contract_hash,
        input_version=frame.input_version,
        prompt_version=frame.prompt.version,
        prompt_hash=frame.prompt.prompt_ref.content_hash,
        max_output_tokens=max_output_tokens,
        input_token_estimate=input_token_estimate,
        output_reserve_tokens=max_output_tokens or 0,
    )
    return AssembledContext(department=frame.department, prompt_text=prompt_text, parts=parts,
                            manifest=manifest, input_items=input_items, tools=tools)


def _parts(context: AssembledContext) -> list[dict[str, Any]]:
    # 上下文清单里每一段材料连同原文：与真实现写进 context_parts 工件的形状相同
    return [{"source": part.source, "version": part.version, "text": part.text,
             "digest": canonical_hash(part.text)} for part in context.parts]
