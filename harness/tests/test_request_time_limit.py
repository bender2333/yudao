import json
import ssl
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from harness.engine import StepLimits
from harness.models import EventType
from harness.providers import ProviderError
from harness.tests.protocol_helpers import bound_target, facade_with, invoke, model_call, provider_system, serve
from harness.tests.test_event_sequence import HTTP_REPLIES, HTTP_SCRIPT

# 单次模型请求的时限只计算等待模型提供方的时间（D09）：从请求发出开始，到收到最后一段输出为止；
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


# 新进程中只导入 Provider 模块（服务启动），列出解析流事件要用的 SDK 模型是否已经构建
SDK_MODELS_BUILT = """
import json
import harness.providers
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


def test_sdk_stream_models_are_built_when_the_provider_module_is_imported():
    completed = subprocess.run([sys.executable, "-c", SDK_MODELS_BUILT], cwd=REPOSITORY,
                               capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0, completed.stderr
    built = json.loads(completed.stdout.strip().splitlines()[-1])
    assert built and all(built.values()), built


def _calls_during(function, operation) -> int:
    # 用 sys.setprofile 记录 function 在 operation 期间（当前线程中）被调用的次数；只观察，不替换
    code, calls = function.__code__, []

    def profile(frame, event, _arg):
        if event == "call" and frame.f_code is code:
            calls.append(1)

    previous = sys.getprofile()
    sys.setprofile(profile)
    try:
        operation()
    finally:
        sys.setprofile(previous)
    return len(calls)


# 新进程中只导入 Provider 模块（服务启动），再按两个 SDK 的方式识别平台（platform.system 与 platform.platform），
# 打印识别期间查询系统版本（platform.win32_ver）的次数
PLATFORM_IDENTIFIED = """
import platform
import harness.providers
from harness.tests.test_request_time_limit import _calls_during
print(_calls_during(platform.win32_ver, lambda: (platform.system(), platform.platform())))
"""


def test_platform_is_identified_when_the_provider_module_is_imported():
    # 两个 SDK 在每个客户端的第一次请求之前识别平台，进程内第一次识别在 Windows 上要查询系统版本（约 0.4 秒）；
    # 这项一次性工作在服务启动时完成
    completed = subprocess.run([sys.executable, "-c", PLATFORM_IDENTIFIED], cwd=REPOSITORY,
                               capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().splitlines()[-1] == "0"


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_calls_reuse_one_ssl_context_instead_of_loading_certificates_each_time(protocol):
    # 各次调用的客户端共用服务启动时创建的 SSL 上下文，请求发出之前不再创建上下文、加载证书
    server, _capture, base = serve(lambda _body: (200, "text/event-stream", [_reply(protocol)]))
    try:
        facade = facade_with(base + "/v1", protocol=protocol)
        target = bound_target(facade)

        def two_calls():
            for attempt_id in ("activation:1:attempt-1", "activation:2:attempt-1"):
                invoke(facade, target, model_call([{"role": "user", "content": "write the spec"}],
                                                  max_output_tokens=256, attempt_id=attempt_id))

        created = _calls_during(ssl.create_default_context, two_calls)
    finally:
        _close(server)
    assert created == 0


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_first_request_in_a_new_process_fits_provider_delay_plus_one_second(protocol, tmp_path):
    delay = 1.0
    server, capture, base = serve(_delayed(protocol, delay))
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "harness.tests.first_request", base, protocol, str(delay + 1.0),
             str(tmp_path / "data")],
            cwd=REPOSITORY, capture_output=True, text=True, timeout=300,
        )
    finally:
        _close(server)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result == {"phase": "ENGINEERING", "stop_reason": None, "failed": []}
    assert len(capture.requests) == 1


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
    assert result.phase == "FAILED" and result.stop_reason == "provider_timeout"
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
def test_provider_waits_add_up_across_the_stream(protocol):
    # 收到请求 0.8 秒以后送出回复头，再过 0.8 秒送出回复体：两段等待都短于 1 秒的时限，合计超过时限。
    # 两段等待期间主机都没有要处理的输出
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
        with pytest.raises(ProviderError) as caught:
            invoke(facade, target, model_call([{"role": "user", "content": "write the spec"}],
                                              max_output_tokens=256))
    finally:
        _close(server)
    assert caught.value.reason == "provider_timeout"
