import json
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
