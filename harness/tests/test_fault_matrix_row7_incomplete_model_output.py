# 故障矩阵第 7 行：模型输出不完整或无法解析（恢复契约与故障矩阵 docs/design/recovery-contract-and-fault-matrix.md「故障矩阵」）。
# 本机 HTTP Provider 返回一条真实的 Responses 流：回答条目与上报的用量已经到达，终止事件是 response.incomplete。
# 协议实现（harness/providers/responses.py）按真实流解析以后报出失败；主机一侧要保留原输出与已知用量，
# 沿用现有的错误分类与尝试次数，不添加通用自动重试。
#
# 层：集成层（真实的本机 Provider 服务与端口、真实事件库、真实 Provider 协议实现）。
# 守 R1（一定会停：失败的调用尝试沿用错误分类与次数上限；失败尝试的输出与用量作为事实只经写入口写入）
# 与 R2（调用尝试的交换字段：原输出的工件引用与用量摘要写在失败尝试的事件里）。

import json

from harness.engine import StepLimits
from harness.models import EventType
from harness.runtime import LoopSystem
from harness.tests.protocol_helpers import (
    STUB_TEXT,
    STUB_USAGE,
    ResponsesAdapter,
    stub_server,
    stub_stream,
    write_stub_reply,
)


def _incomplete(handler, _body):
    # 一条真实的 Responses 流：回答条目与用量都在，终止事件是 response.incomplete（输出被截断）
    write_stub_reply(handler, stub_stream([STUB_TEXT], status="incomplete", usage=STUB_USAGE))


def _artifact(system, ref):
    return json.loads(system.artifacts.get_text(ref["content_hash"]))


def test_an_incomplete_model_output_keeps_the_output_and_the_known_usage_without_a_retry(tmp_path):
    # 输出不完整：原输出（回答条目与原始回应）与已知用量保留在失败尝试的事实里；失败按现有的
    # 错误分类停止（provider_error），一次尝试以后不再自动重试，次数上限记在事件里
    limits = StepLimits()
    with stub_server([_incomplete]) as (config, captures, *_):
        system = LoopSystem.for_testing(tmp_path / "data", ResponsesAdapter(config), step_limits=limits)
        try:
            run_id = system.create_run("build echo")
            result = system.run_until_stop(run_id)
            assert result.status == "failed"
            assert result.stop_reason == "provider_error"
            assert "Model response incomplete" in result.error
            events = system.store.list_events(run_id)

            failed = [event for event in events if event.type == EventType.MODEL_ATTEMPT_FAILED]
            assert len(failed) == 1, [event.type for event in events]
            payload = failed[0].payload
            # 错误分类与次数限制沿用现有的一条：第一次尝试即失败，没有自动重试
            assert payload["attempt"] == 1
            assert payload["max_attempts"] == limits.max_provider_attempts
            assert payload["retryable"] is False
            assert payload["will_retry"] is False
            assert payload["status"] == "failed"
            assert not any(event.type == EventType.MODEL_RETRY_SCHEDULED for event in events)
            assert len(captures) == 1, "失败尝试被自动重试了"

            # 原输出保留：流里的回答条目写成模型消息，原始回应写成工件
            messages = [event for event in events
                        if event.type == EventType.MODEL_MESSAGE
                        and (event.payload or {}).get("summary") == "Local model output"]
            assert len(messages) == 1
            message = _artifact(system, messages[0].payload["message_ref"])
            assert message["content"][0]["text"] == "Local model output"
            assert payload["response_ref"] is not None
            response = _artifact(system, payload["response_ref"])
            assert response["output"][0]["content"][0]["text"] == "Local model output"

            # 已知用量保留：失败尝试带着上报的用量摘要与原始用量工件
            usage = payload["usage"]
            assert usage["reported"] is True
            assert usage["total_tokens"] == STUB_USAGE["total_tokens"]
            # 摘要里的输入是原文的输入（含缓存读取）：由上游原文与缓存的明细算出
            assert usage["input_tokens"] == STUB_USAGE["input_tokens"]
            assert usage["cache_read_tokens"] == STUB_USAGE["input_tokens_details"]["cached_tokens"]
            assert usage["output_tokens"] == STUB_USAGE["output_tokens"]
            raw_usage = _artifact(system, payload["raw_usage_ref"])
            assert raw_usage["usage"]["total_tokens"] == STUB_USAGE["total_tokens"]

            # 输出不完整的回答没有执行任何工具，也没有进入正式成果
            assert not any(event.type == EventType.TOOL_STARTED for event in events)
            assert not any(event.type == EventType.PROPOSAL_SUBMITTED for event in events)
        finally:
            system.close()
