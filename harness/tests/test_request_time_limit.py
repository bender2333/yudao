import time
from dataclasses import replace
from pathlib import Path

import pytest

from harness.engine import StepLimits
from harness.models import EventType
from harness.providers import ProviderError
from harness.tests.protocol_helpers import bound_target, facade_with, invoke, model_call, provider_system, serve
from harness.tests.provider_replies import HTTP_REPLIES, HTTP_SCRIPT

# 单次模型请求的时限只计算等待模型提供方的时间，按多久没有收到新数据计算（D09）：从请求发出到收到第一段回复、
# 以及之后相邻两段数据之间，各段等待分别与时限比较，回复持续输出时不按总时长切断。
# SDK 的一次性初始化、请求发出前的记录与输出片段的记录都不计入。三种协议相同。

PROTOCOLS = ["responses", "chat_completions", "messages"]
REPOSITORY = Path(__file__).resolve().parents[2]


def _reply(protocol: str) -> bytes:
    # 产品部门提交规格的流式回复
    return HTTP_REPLIES[protocol](1, HTTP_SCRIPT[0])


def _delayed(protocol: str, delay: float):
    # 收到请求以后等待 delay 秒，再发送完整的流式回复
    def responder(_body):
        time.sleep(delay)
        return 200, "text/event-stream", [_reply(protocol)]

    return responder


def _close(server) -> None:
    server.shutdown()
    server.server_close()


# 新进程中创建 Provider 门面并读入模型目录（服务启动），目录用到三种协议；
# 列出解析流事件要用的 SDK 模型是否已经构建
CATALOG_WITH_THE_THREE_PROTOCOLS = """
from harness.providers import ProviderFacade
ProviderFacade().store_document({
    "providers": [{"id": "go", "name": "Go", "base_url": "http://127.0.0.1:1/v1",
                   "credential_ref": "GO_KEY", "timeout_sec": 20.0, "preset_id": ""}],
    "models": [{"id": "m-" + protocol, "provider_id": "go", "model": "target-model", "protocol": protocol,
                "context_window": 32000, "max_output_tokens": 2048, "capability_source": "preset-v1"}
               for protocol in ("responses", "chat_completions", "messages")],
    "bindings": {},
})
"""

SDK_MODELS_BUILT = CATALOG_WITH_THE_THREE_PROTOCOLS + """
import json
from anthropic.types import RawContentBlockDeltaEvent, RawMessageStartEvent
from openai.types.chat import ChatCompletionChunk
from openai.types.responses import (
    Response, ResponseCompletedEvent, ResponseFunctionToolCall, ResponseOutputMessage, ResponseUsage,
)
from pydantic_core import SchemaSerializer, SchemaValidator
models = [Response, ResponseCompletedEvent, ResponseFunctionToolCall, ResponseOutputMessage, ResponseUsage,
          ChatCompletionChunk, RawMessageStartEvent, RawContentBlockDeltaEvent]
print(json.dumps({model.__name__: isinstance(model.__pydantic_validator__, SchemaValidator)
                  and isinstance(model.__pydantic_serializer__, SchemaSerializer) for model in models}))
"""


# 新进程中读入用到三种协议的模型目录（服务启动），再按两个 SDK 的方式识别平台（platform.system 与 platform.platform），
# 打印识别期间查询系统版本（platform.win32_ver）的次数
PLATFORM_IDENTIFIED = CATALOG_WITH_THE_THREE_PROTOCOLS + """
import platform
from harness.tests.helpers import calls_during as _calls_during
print(_calls_during(platform.win32_ver, lambda: (platform.system(), platform.platform())))
"""


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_provider_delay_beyond_the_limit_is_a_provider_timeout(protocol, data_dir):
    server, capture, base = serve(_delayed(protocol, 2.0))
    try:
        system, run_id = provider_system(data_dir, base, protocol, timeout_sec=1.0,
                                         step_limits=StepLimits(max_provider_attempts=1))
        try:
            result = system.activate_once(run_id)
            failed = [event for event in system.store.list_events(run_id)
                      if event.type == EventType.MODEL_ATTEMPT_FAILED]
        finally:
            system.close()
    finally:
        _close(server)
    assert result.status == "failed" and result.stop_reason == "provider_timeout"
    assert [event.payload["reason"] for event in failed] == ["provider_timeout"]
    assert failed[0].payload["retryable"] is True
    assert len(capture.requests) == 1


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_caller_handling_of_each_observation_is_outside_the_limit(protocol):
    # 调用方同步记录每一条观察（与部门循环写事件相同，处理期间事件循环不运行）；记录的总用时超过请求时限，
    # 等待提供方的时间远小于时限，请求仍然成功
    pause, limit = 0.5, 2.0
    server, _capture, base = serve(lambda _body: (200, "text/event-stream", [_reply(protocol)]))
    observed = []

    def record(event):
        observed.append(event.kind)
        time.sleep(pause)

    try:
        facade = facade_with(base + "/v1", protocol=protocol)
        target = replace(bound_target(facade), timeout_sec=limit)
        response = invoke(facade, target, model_call([{"role": "user", "content": "write the spec"}],
                                                     max_output_tokens=256), observe=record)
    finally:
        _close(server)
    assert [item["name"] for item in response.output] == ["submit_product_spec"]
    assert observed[0] == "request"
    assert len(observed) * pause > limit


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_stream_completes_when_total_time_exceeds_limit_but_intervals_do_not(protocol):
    # 收到请求 0.8 秒以后送出回复头，再过 0.8 秒送出回复体：两段等待都短于 1 秒的时限，合计超过时限。
    # 回复持续输出且各段间隔小于时限，请求正常完成，不记 provider_timeout
    body = _reply(protocol)

    def responder(_body):
        time.sleep(0.8)

        def late_body():
            time.sleep(0.8)
            yield body

        return 200, "text/event-stream", late_body()

    server, _capture, base = serve(responder)
    try:
        facade = facade_with(base + "/v1", protocol=protocol)
        target = replace(bound_target(facade), timeout_sec=1.0)
        response = invoke(facade, target, model_call([{"role": "user", "content": "write the spec"}],
                                                     max_output_tokens=256))
        assert [item["name"] for item in response.output] == ["submit_product_spec"]
    finally:
        _close(server)


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_delay_between_stream_chunks_beyond_the_limit_is_a_provider_timeout(protocol):
    # 两段数据之间的等待超过时限时，记 provider_timeout，按 D17 重试
    body = _reply(protocol)
    first_chunk, separator, remaining_body = body.partition(b"\n\n")

    def responder(_body):
        def slow_body():
            yield first_chunk + separator
            time.sleep(1.2)
            yield remaining_body

        return 200, "text/event-stream", slow_body()

    server, capture, base = serve(responder)
    try:
        facade = facade_with(base + "/v1", protocol=protocol)
        target = replace(bound_target(facade), timeout_sec=1.0)
        with pytest.raises(ProviderError) as caught:
            invoke(facade, target, model_call([{"role": "user", "content": "write the spec"}],
                                              max_output_tokens=256))
        assert caught.value.reason == "provider_timeout"
        assert caught.value.retryable is True
    finally:
        _close(server)
    assert len(capture.requests) == 1
