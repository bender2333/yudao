from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# 模型调用合同：步骤驱动与 Provider 之间一次调用尝试的输入、流式输出与结果。
# 全部是可以序列化的数据，不含线程标志、回调或适配器实例。
# Provider 以异步迭代逐条交回流式输出，最后一条是 ModelResponse；调用方处理完一条（例如写成事件）
# 再取下一条，Provider 才继续。请求发出前的记录与输出片段的记录因此都在调用方一侧完成，
# 不计入单次请求的时限：时限只计算等待提供方的时间（D09）。
# 取消按 attempt_id 生效。


class CallUsage(BaseModel):
    # 提供方报告的用量；没有报告时 reported 为 False，数值不估算
    model_config = ConfigDict(extra="forbid")

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    latency_ms: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reported: bool = False
    cost_reported: bool = False


class ModelCall(BaseModel):
    # 一次调用尝试：身份（run、部门、会话、激活、步骤、逻辑调用、尝试）与装配好的请求
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    department: str
    session_id: str
    activation_id: str
    step_id: int
    logical_call_id: str
    attempt: int
    attempt_id: str
    purpose: Literal["work", "compaction"]
    input_items: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    max_output_tokens: int | None = None
    # 是否要求调用工具；#102 在最后一次主机提示时增加 required
    tool_choice: Literal["auto"] = "auto"


class ModelDelta(BaseModel):
    # 一次调用尝试中某个通道的一段文字片段（设计说明第 5.6 节）：offset 是这段文字在该通道中的起始字数。
    # 片段由协议实现从解码后的流事件中读出，不写入事件日志，只经输出片段通道转发
    model_config = ConfigDict(frozen=True, extra="forbid")

    channel: Literal["output", "reasoning", "tool_arguments"]
    offset: int
    text: str

class ModelStreamEvent(BaseModel):
    # 调用进行中交回的一条观察：发送的请求、解码后的流事件、完整响应、用量或一条输出。
    # 解码后的流事件由协议实现按协议读出流式进度阶段（stage）、提供方的回答身份（response_id）
    # 与这段事件里的文字片段（deltas）；调用方不解析协议的事件形状
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["request", "stream_event", "response", "usage", "message"]
    id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    text: str = ""
    usage: CallUsage | None = None
    provider: str | None = None
    model: str | None = None
    source: str = "provider_sdk"
    sequence: int | None = None
    stage: Literal["response_created", "output", "output_item_done", "completed", "error", "event"] = "event"
    response_id: str | None = None
    deltas: tuple[ModelDelta, ...] = ()


class ModelResponse(BaseModel):
    # 一次调用尝试的结果：输出条目、用量与提供方实际返回的身份
    model_config = ConfigDict(extra="forbid")

    output: list[dict[str, Any]] = Field(default_factory=list)
    usage: CallUsage = Field(default_factory=CallUsage)
    finish_reason: str = "completed"
    error: str | None = None
    provider: str = ""
    model: str = ""
    response_id: str | None = None
    sdk_response: dict[str, Any] | None = None
