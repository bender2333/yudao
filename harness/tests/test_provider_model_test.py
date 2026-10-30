"""R3：模型目录准入经真实 HTTP 验证最小问答、完整工具往返、失败归因与凭据隔离。"""
from __future__ import annotations

import json

import pytest

from harness.providers import ProviderFacade
from harness.tests.protocol_helpers import ScriptedProvider, facade_with, model_test_responder, send_reply

PROTOCOLS = ["responses", "chat_completions", "messages"]


def reply(protocol, *, without_tool=False, arguments="{}", call_id="probe-call", actual_model="tested-model"):
    def respond(_provider, handler):
        body = {**handler.body, "tools": []} if without_tool else handler.body
        status, content_type, chunks = model_test_responder(body, protocol=protocol,
                                                         arguments=arguments, call_id=call_id,
                                                         actual_model=actual_model)
        send_reply(handler, status, content_type, b"".join(chunks))
    return respond


def rejected(status, message, *, param=None):
    def respond(_provider, handler):
        error = {"type": "invalid_request_error", "message": message}
        if param is not None:
            error["param"] = param
        send_reply(handler, status, "application/json", json.dumps({"error": error}).encode())
    return respond


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_both_groups_admit_and_persist_detected_tool_capability(protocol, tmp_path):
    provider = ScriptedProvider([reply(protocol)] * 3)
    try:
        facade = facade_with(provider.base + "/v1", protocol=protocol, accepts_required_tool_call=False)
        path = tmp_path / "providers.json"
        facade.configure_paths(path)
        facade.persist_document(path)
        tested = facade.model_test("go", "m-go")
        assert tested["ok"] is True and tested["admitted"] is True, tested
        assert tested["model"] == "tested-model" and tested["elapsed_ms"] >= 0
        assert tested["accepts_required_tool_call"] is True
        assert tested["failure_group"] is None and tested["failure_step"] is None
        assert tested["usage_reported"] is True
        assert not provider.requests[0].get("tools")
        assert provider.requests[1]["tool_choice"] == ({"type": "any"} if protocol == "messages" else "required")
        assert "probe-call" in json.dumps(provider.requests[2])
        record = next(row for row in facade.model_admissions() if row["model_id"] == "m-go")
        assert record["admitted"] is True and record["admitted_model"] == "tested-model"
        restarted = ProviderFacade(credentials={"GO_KEY": "local-secret"})
        restarted.load_document(path)
        assert restarted.providers_view()["models"][0]["accepts_required_tool_call"] is True
    finally:
        provider.close()


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_a_text_answer_does_not_pass_the_tool_round_trip(protocol):
    provider = ScriptedProvider([reply(protocol), reply(protocol, without_tool=True)])
    try:
        facade = facade_with(provider.base + "/v1", protocol=protocol)
        tested = facade.model_test("go", "m-go")
        assert tested["ok"] is False and tested["admitted"] is False, tested
        assert tested["failure_group"] == "tool_round_trip" and tested["failure_step"] == "tool_call"
        assert "工具往返" in tested["error"]
        assert not any(row["admitted"] for row in facade.model_admissions())
    finally:
        provider.close()


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_missing_upstream_model_identity_stays_unknown(protocol):
    provider = ScriptedProvider([reply(protocol, actual_model=None)] * 3)
    try:
        facade = facade_with(provider.base + "/v1", protocol=protocol)
        tested = facade.model_test("go", "m-go")
        assert tested["ok"] is True and tested["admitted"] is True, tested
        assert tested["model"] is None
        assert facade.model_admissions()[0]["admitted_model"] == ""
    finally:
        provider.close()


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("with_param", [True, False])
def test_explicit_tool_choice_rejection_retries_once_without_requiring_tools(protocol, with_param, tmp_path):
    provider = ScriptedProvider([reply(protocol), rejected(400, "tool_choice is not supported",
                                param="tool_choice" if with_param else None), reply(protocol), reply(protocol)])
    try:
        facade = facade_with(provider.base + "/v1", protocol=protocol)
        path = tmp_path / "providers.json"
        facade.configure_paths(path)
        facade.persist_document(path)
        tested = facade.model_test("go", "m-go")
        assert tested["ok"] is True and tested["admitted"] is True, tested
        assert tested["accepts_required_tool_call"] is False
        assert "tool_choice" not in provider.requests[2]
        assert provider.requests[2]["tools"] == provider.requests[1]["tools"]
        assert facade.providers_view()["models"][0]["accepts_required_tool_call"] is False
        restarted = ProviderFacade(credentials={"GO_KEY": "local-secret"})
        restarted.load_document(path)
        assert restarted.providers_view()["models"][0]["accepts_required_tool_call"] is False
    finally:
        provider.close()


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("status,param,message", [
    (400, "tools", "tools schema is not supported"),
    (400, None, "unsupported tools parameter"),
    (500, "tool_choice", "tool_choice temporarily unavailable"),
    (400, None, "request rejected"),
])
def test_other_upstream_errors_fail_without_a_tool_choice_retry(protocol, status, param, message):
    provider = ScriptedProvider([reply(protocol), rejected(status, message, param=param)])
    try:
        facade = facade_with(provider.base + "/v1", protocol=protocol)
        tested = facade.model_test("go", "m-go")
        assert tested["ok"] is False and tested["admitted"] is False, tested
        assert tested["failure_group"] == "tool_round_trip" and tested["failure_step"] == "tool_call"
        assert message in tested["error"]
        assert len(provider.requests) == 2  # 本用例守「只有明确的参数拒绝才重试」这一行为。
    finally:
        provider.close()


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("step", ["request", "tool_call", "tool_result"])
def test_timeouts_are_failures_at_the_request_that_expired(protocol, step):
    def held(provider, _handler):
        provider.held.set()
        assert provider.release.wait(10), "等待测试客户端处理超时"
    before = {"request": 0, "tool_call": 1, "tool_result": 2}[step]
    provider = ScriptedProvider([*[reply(protocol)] * before, held])
    try:
        facade = facade_with(provider.base + "/v1", protocol=protocol)
        connection = facade.providers_view()["providers"][0]
        facade.save_provider({key: value for key, value in {**connection, "timeout_sec": 0.1}.items()
                              if key not in {"models", "credential", "credential_configured"}})
        tested = facade.model_test("go", "m-go")
        assert provider.held.is_set()
        assert tested["ok"] is False and tested["admitted"] is False, tested
        assert tested["failure_group"] == ("minimal_qa" if before == 0 else "tool_round_trip")
        assert tested["failure_step"] == step and "超时" in tested["error"]
    finally:
        provider.close()


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("status", [401, 403])
def test_authentication_errors_never_expose_response_bodies(protocol, status):
    secret_body = "untrusted-credential-echo local-secret"
    provider = ScriptedProvider([reply(protocol), rejected(status, secret_body)])
    try:
        tested = facade_with(provider.base + "/v1", protocol=protocol).model_test("go", "m-go")
        assert tested["ok"] is False and tested["admitted"] is False, tested
        assert str(status) in tested["error"] and tested["failure_step"] == "tool_call"
        assert "untrusted-credential-echo" not in json.dumps(tested)
        assert "local-secret" not in json.dumps(tested)
    finally:
        provider.close()


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_model_test_caps_a_longer_connection_timeout_at_sixty_seconds(protocol):
    # R3：用真实等待证明模型测试的默认上限独立于连接的较长时限，没有替换计时器。
    def held(provider, _handler):
        provider.held.set()
        assert provider.release.wait(120), "等待模型测试触发逐请求上限"
    provider = ScriptedProvider([held])
    try:
        facade = facade_with(provider.base + "/v1", protocol=protocol)
        connection = facade.to_document()["providers"][0]
        facade.save_provider({**connection, "timeout_sec": 600})
        tested = facade.model_test("go", "m-go")
        assert provider.held.is_set()
        assert tested["ok"] is False and tested["admitted"] is False, tested
        assert tested["request_timeout_sec"] == 60
        assert tested["failure_group"] == "minimal_qa" and tested["failure_step"] == "request"
        assert 59_000 <= tested["elapsed_ms"] < 120_000
        assert "超时" in tested["error"]
    finally:
        provider.close()


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("before,step", [(0, "request"), (2, "tool_result")])
def test_upstream_errors_identify_the_failing_group_and_step(protocol, before, step):
    provider = ScriptedProvider([*[reply(protocol)] * before, rejected(400, "upstream rejected this step")])
    try:
        tested = facade_with(provider.base + "/v1", protocol=protocol).model_test("go", "m-go")
        assert tested["ok"] is False and tested["admitted"] is False, tested
        assert tested["failure_group"] == ("minimal_qa" if before == 0 else "tool_round_trip")
        assert tested["failure_step"] == step and "upstream rejected this step" in tested["error"]
    finally:
        provider.close()


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_the_retry_still_requires_a_complete_tool_call(protocol):
    provider = ScriptedProvider([reply(protocol), rejected(422, "tool_choice is unsupported", param="tool_choice"),
                                 reply(protocol, without_tool=True)])
    try:
        facade = facade_with(provider.base + "/v1", protocol=protocol)
        tested = facade.model_test("go", "m-go")
        assert tested["ok"] is False and tested["admitted"] is False, tested
        assert tested["failure_group"] == "tool_round_trip" and tested["failure_step"] == "tool_call_retry"
        assert facade.providers_view()["models"][0]["accepts_required_tool_call"] is True
    finally:
        provider.close()


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("arguments,call_id", [("{", "probe-call"), ("[]", "probe-call"), ("{}", "")])
def test_incomplete_tool_calls_do_not_admit(protocol, arguments, call_id):
    provider = ScriptedProvider([reply(protocol), reply(protocol, arguments=arguments, call_id=call_id)])
    try:
        tested = facade_with(provider.base + "/v1", protocol=protocol).model_test("go", "m-go")
        assert tested["ok"] is False and tested["admitted"] is False, tested
        assert tested["failure_group"] == "tool_round_trip" and tested["failure_step"] == "tool_call"
    finally:
        provider.close()
