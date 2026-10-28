# 任务池的装配实现（工单 #864；**只在测试里用，产品代码不导入它**）。
#
# 形状与第二种装配（`second_assembly.SecondAssembly`，工单 #979）相同：固定部分只有部门提示与这一轮任务的
# 那一句，不减历史、不压缩、不写事件。只多一件事——把这一轮请求的工具清单交给模型：任务池的部门要看得到
# 自己那份定义里的工具（提交类工具由它交任务、交完成说明、给结论），而第二种装配这一版不给工具。
#
# 工具清单来自**事项所用的那份定义**（`task_pool_definitions/`），不读模块加载时的产品定义：
# 产品定义里没有任务池的三种成果，按它取会取到空。哪几个工具给这个部门由它的角色决定（`tools_for`）。

from __future__ import annotations

from dataclasses import replace
from typing import Any

from harness.context import AssembledContext
from harness.models import ContextManifest, RunProjection, canonical_hash, estimate_tokens, json_dumps
from harness.tests import second_assembly
from harness.tests.second_routing import DEFINITIONS
from harness.tools import offers_with_input, tool_definitions, tools_for


class TaskPoolAssembly(second_assembly.SecondAssembly):
    """第二种装配的一层：同一份契约，另外把这一轮的工具清单放进请求。"""

    CONTRACT_VERSION = second_assembly.SecondAssembly.CONTRACT_VERSION

    def request(self, pinned: second_assembly.SecondPinnedStep,
                history: list[dict[str, Any]]) -> second_assembly.SecondStepRequest:
        step = super().request(pinned, history)
        tools = _tools(pinned.projection, pinned.frame.department)
        if not tools:
            return step
        payload = {**step.payload, "tools": tools}
        context = _with_tools(step.context, tools, payload)
        return replace(step, context=context, payload=payload,
                       input_token_estimate=estimate_tokens(json_dumps(payload)))


def _tools(projection: RunProjection, department: str) -> list[dict[str, Any]]:
    # 这个部门这一刻能用的工具（按它自己那份定义），写成请求里工具定义的样子
    names = offers_with_input(list(tools_for(department, projection.kind, definitions=DEFINITIONS)),
                              ("text",), definitions=DEFINITIONS)
    return [{"type": "function", "name": item["name"], "description": item["description"],
             "parameters": item["parameters"], "strict": False}
            for item in tool_definitions(names, definitions=DEFINITIONS)]


def _with_tools(context: AssembledContext, tools: list[dict[str, Any]],
                payload: dict[str, Any]) -> AssembledContext:
    # 装配好的上下文换上一份带工具的清单与请求：清单里的估算与摘要按新的请求重算
    estimate = estimate_tokens(json_dumps(payload))
    manifest: ContextManifest = replace(context.manifest, token_estimate=estimate,
                                        input_token_estimate=estimate,
                                        digest=canonical_hash(payload))
    return replace(context, tools=tools, manifest=manifest)
