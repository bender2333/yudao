from __future__ import annotations

from typing import Any

from .store import REASONING_BUDGET_TOKENS

# 推理参数编码（设计说明第 7.4 节）：三个协议适配器共用这里的取值规则，
# 档位与推理参数方式都取自冻结目标，协议层不认识部门与请求档位
BUDGET_OUTPUT_RESERVE_TOKENS = 4000  # 预算式思考保留给可见输出的 token
BUDGET_MINIMUM_TOKENS = 1024  # 上游接受的最低思考预算


def reasoning_level(target: Any) -> str:
    # 本次请求实际发送的档位；模型没有声明支持档位时为空，请求不带推理参数
    return target.sent_tier or ""


def responses_reasoning(target: Any) -> dict[str, Any] | None:
    # Responses 协议的 effort 方式：reasoning.effort 取档位名
    level = reasoning_level(target)
    if target.reasoning_mode != "effort" or not level:
        return None
    return {"effort": level}


def chat_reasoning_effort(target: Any) -> str | None:
    # Chat Completions 协议的 effort 方式：reasoning_effort 取档位名
    level = reasoning_level(target)
    if target.reasoning_mode != "effort" or not level:
        return None
    return level


def messages_reasoning_params(target: Any, max_output_tokens: int | None) -> dict[str, Any]:
    # Anthropic Messages 协议的两种方式：adaptive 发送思考开关与 output_config.effort，
    # budget 按档位取思考预算，且不超过本次输出上限减去保留量
    level = reasoning_level(target)
    mode = target.reasoning_mode
    if not level or mode not in ("adaptive", "budget"):
        return {}
    if mode == "adaptive":
        return {"thinking": {"type": "adaptive"}, "output_config": {"effort": level}}
    limit = 0 if max_output_tokens is None else int(max_output_tokens)
    ceiling = limit - BUDGET_OUTPUT_RESERVE_TOKENS
    if ceiling < BUDGET_MINIMUM_TOKENS:
        # 输出上限不足以同时容纳思考预算与可见输出时不发送思考参数，交给上游按自身默认推理
        return {}
    table = REASONING_BUDGET_TOKENS[level]
    return {"thinking": {"type": "enabled", "budget_tokens": min(table, ceiling)}}
