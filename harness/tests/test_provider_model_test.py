"""R3：模型目录准入经真实 HTTP 验证最小问答、完整工具往返、失败归因与凭据隔离。"""
from __future__ import annotations

import json

import pytest

from harness.providers import ProviderFacade
from harness.providers.capabilities import CAPABILITY_TABLE_REVISION
from harness.tests.protocol_helpers import ScriptedProvider, facade_with, model_test_responder, send_reply

PROTOCOLS = ["responses", "chat_completions", "messages"]


def reply(protocol, *, without_tool=False, arguments="{}", call_id="probe-call", actual_model="tested-model",
          tool_name=None):
    def respond(_provider, handler):
        body = {**handler.body, "tools": []} if without_tool else handler.body
        status, content_type, chunks = model_test_responder(body, protocol=protocol,
                                                         arguments=arguments, call_id=call_id,
                                                         actual_model=actual_model, tool_name=tool_name)
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
    provider = ScriptedProvider([reply(protocol)])
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
        assert len(provider.requests) == 1
        assert provider.requests[0].get("tools")
        assert provider.requests[0]["tool_choice"] == ({"type": "any"} if protocol == "messages" else "required")
        record = next(row for row in facade.model_admissions() if row["model_id"] == "m-go")
        assert record["admitted"] is True and record["admitted_model"] == "tested-model"
        restarted = ProviderFacade(credentials={"GO_KEY": "local-secret"})
        restarted.load_document(path)
        assert restarted.providers_view()["models"][0]["accepts_required_tool_call"] is True
    finally:
        provider.close()


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_a_text_answer_does_not_pass_the_tool_round_trip(protocol):
    provider = ScriptedProvider([reply(protocol, without_tool=True)])
    try:
        facade = facade_with(provider.base + "/v1", protocol=protocol)
        tested = facade.model_test("go", "m-go")
        assert tested["ok"] is False and tested["admitted"] is False, tested
        assert tested["failure_group"] == "tool_round_trip" and tested["failure_step"] == "tool_call"
        assert "工具往返" in tested["error"]
        assert len(provider.requests) == 1
        assert not any(row["admitted"] for row in facade.model_admissions())
    finally:
        provider.close()


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_missing_upstream_model_identity_stays_unknown(protocol):
    provider = ScriptedProvider([reply(protocol, actual_model=None)])
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
    provider = ScriptedProvider([rejected(400, "tool_choice is not supported",
                                         param="tool_choice" if with_param else None),
                                 reply(protocol)])
    try:
        facade = facade_with(provider.base + "/v1", protocol=protocol)
        path = tmp_path / "providers.json"
        facade.configure_paths(path)
        facade.persist_document(path)
        tested = facade.model_test("go", "m-go")
        assert tested["ok"] is True and tested["admitted"] is True, tested
        assert tested["accepts_required_tool_call"] is False
        assert len(provider.requests) == 2
        assert "tool_choice" not in provider.requests[1]
        assert provider.requests[1]["tools"] == provider.requests[0]["tools"]
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
    (400, None, "tools schema invalid; tool_choice=required"),
    (400, None, "unknown model target-model; tool_choice was required"),
])
def test_other_upstream_errors_fail_without_a_tool_choice_retry(protocol, status, param, message):
    provider = ScriptedProvider([rejected(status, message, param=param)])
    try:
        facade = facade_with(provider.base + "/v1", protocol=protocol)
        tested = facade.model_test("go", "m-go")
        assert tested["ok"] is False and tested["admitted"] is False, tested
        assert tested["failure_group"] == "tool_round_trip" and tested["failure_step"] == "tool_call"
        assert message in tested["error"]
        assert len(provider.requests) == 1  # 本用例守「只有明确的参数拒绝才重试」这一行为。
    finally:
        provider.close()


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("step", ["tool_call", "tool_call_retry"])
def test_timeouts_are_failures_at_the_request_that_expired(protocol, step):
    def held(provider, _handler):
        provider.held.set()
        assert provider.release.wait(10), "等待测试客户端处理超时"
    before = [rejected(400, "tool_choice is not supported", param="tool_choice")] if step == "tool_call_retry" else []
    provider = ScriptedProvider([*before, held])
    try:
        facade = facade_with(provider.base + "/v1", protocol=protocol)
        connection = facade.providers_view()["providers"][0]
        facade.save_provider({key: value for key, value in {**connection, "timeout_sec": 0.1}.items()
                              if key not in {"models", "credential", "credential_configured"}})
        tested = facade.model_test("go", "m-go")
        assert provider.held.is_set()
        assert tested["ok"] is False and tested["admitted"] is False, tested
        assert tested["failure_group"] == "tool_round_trip"
        assert tested["failure_step"] == step and "超时" in tested["error"]
    finally:
        provider.close()


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("status", [401, 403])
def test_authentication_errors_never_expose_response_bodies(protocol, status):
    secret_body = "untrusted-credential-echo local-secret"
    provider = ScriptedProvider([rejected(status, secret_body)])
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
        assert tested["failure_group"] == "tool_round_trip" and tested["failure_step"] == "tool_call"
        assert 59_000 <= tested["elapsed_ms"] < 120_000
        assert "超时" in tested["error"]
    finally:
        provider.close()


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("retry_first,step", [(False, "tool_call"), (True, "tool_call_retry")])
def test_upstream_errors_identify_the_failing_group_and_step(protocol, retry_first, step):
    before = [rejected(400, "tool_choice is not supported", param="tool_choice")] if retry_first else []
    provider = ScriptedProvider([*before, rejected(400, "upstream rejected this step")])
    try:
        tested = facade_with(provider.base + "/v1", protocol=protocol).model_test("go", "m-go")
        assert tested["ok"] is False and tested["admitted"] is False, tested
        assert tested["failure_group"] == "tool_round_trip"
        assert tested["failure_step"] == step and "upstream rejected this step" in tested["error"]
    finally:
        provider.close()


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_the_retry_still_requires_a_complete_tool_call(protocol):
    provider = ScriptedProvider([rejected(422, "tool_choice is unsupported", param="tool_choice"),
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
    provider = ScriptedProvider([reply(protocol, arguments=arguments, call_id=call_id)])
    try:
        tested = facade_with(provider.base + "/v1", protocol=protocol).model_test("go", "m-go")
        assert tested["ok"] is False and tested["admitted"] is False, tested
        assert tested["failure_group"] == "tool_round_trip" and tested["failure_step"] == "tool_call"
    finally:
        provider.close()


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_a_call_to_another_tool_does_not_admit(protocol):
    # R3（工单 #1341）：多传参数放行以后，工具名不对仍然不通过——放行的是参数形状，不是工具身份
    provider = ScriptedProvider([reply(protocol, tool_name="other_tool")])
    try:
        facade = facade_with(provider.base + "/v1", protocol=protocol)
        tested = facade.model_test("go", "m-go")
        assert tested["ok"] is False and tested["admitted"] is False, tested
        assert tested["failure_group"] == "tool_round_trip" and tested["failure_step"] == "tool_call"
        assert "工具名称不符" in tested["error"], tested["error"]
        assert not any(row["admitted"] for row in facade.model_admissions())
    finally:
        provider.close()


def test_default_input_modalities_backfill_image_from_actual_model_and_persist(tmp_path):
    # R2、R3：source 仍为 default 时，actual_model 按归一化规则匹配支持图像后自动回填并写盘。
    provider = ScriptedProvider([reply("responses", actual_model="ag/gemini-3.8-flash-high")])
    try:
        facade = facade_with(provider.base + "/v1", protocol="responses")
        document = facade.to_document()
        document["models"][0]["input_modalities"] = ["text"]
        document["models"][0]["source_details"] = {"input_modalities": {"source": "default"}}
        facade.store_document(document)
        path = tmp_path / "providers.json"
        facade.configure_paths(path)
        facade.persist_document(path)
        tested = facade.model_test("go", "m-go")
        assert tested["ok"] is True and tested["admitted"] is True
        saved = facade.providers_view()["models"][0]
        assert saved["input_modalities"] == ["text", "image"]
        assert saved["source_details"]["input_modalities"] == {
            "source": "capability_table",
            "provider": "gemini-3.8-flash",
            "revision": CAPABILITY_TABLE_REVISION,
        }
        restarted = ProviderFacade(credentials={"GO_KEY": "local-secret"})
        restarted.load_document(path)
        assert restarted.providers_view()["models"][0]["input_modalities"] == ["text", "image"]
    finally:
        provider.close()


@pytest.mark.parametrize("source", ["models_url", "capability_table", "manual"])
def test_non_default_input_modalities_are_never_overwritten_by_actual_model(source, tmp_path):
    # R2、R3：已有 models_url、capability_table 或 manual 来源的输入模态不被 actual_model 改写。
    provider = ScriptedProvider([reply("responses", actual_model="ag/gemini-3.8-flash-high")])
    try:
        facade = facade_with(provider.base + "/v1", protocol="responses")
        document = facade.to_document()
        detail = ({"source": source, "provider": "opencode-go", "revision": CAPABILITY_TABLE_REVISION}
                  if source == "capability_table" else {"source": source})
        document["models"][0]["input_modalities"] = ["text"]
        document["models"][0]["source_details"] = {"input_modalities": detail}
        facade.store_document(document)
        path = tmp_path / "providers.json"
        facade.configure_paths(path)
        facade.persist_document(path)
        tested = facade.model_test("go", "m-go")
        assert tested["ok"] is True and tested["admitted"] is True
        saved = facade.providers_view()["models"][0]
        assert saved["input_modalities"] == ["text"]
        assert saved["source_details"]["input_modalities"] == detail
    finally:
        provider.close()


def test_saving_edited_input_modalities_without_source_details_records_manual_and_blocks_backfill(tmp_path):
    # R2、R3：连接保存请求省略 source_details 且修改了 input_modalities 时记为 manual，后续测试不再覆盖。
    provider = ScriptedProvider([reply("responses", actual_model="ag/gemini-3.8-flash-high")])
    try:
        facade = facade_with(provider.base + "/v1", protocol="responses")
        document = facade.to_document()
        document["models"][0]["input_modalities"] = ["text", "image"]
        document["models"][0]["source_details"] = {
            "input_modalities": {
                "source": "capability_table",
                "provider": "gemini-3.8-flash",
                "revision": CAPABILITY_TABLE_REVISION,
            }
        }
        facade.store_document(document)
        path = tmp_path / "providers.json"
        facade.configure_paths(path)
        facade.persist_document(path)
        view = facade.providers_view()
        connection = {key: value for key, value in view["providers"][0].items()
                      if key not in {"models", "credential", "credential_configured"}}
        model = {key: value for key, value in view["models"][0].items()
                 if key not in {"provider_id", "source_details"}}
        model["input_modalities"] = ["text"]
        facade.save_provider_entry(connection, [model])
        tested = facade.model_test("go", "m-go")
        assert tested["ok"] is True and tested["admitted"] is True
        saved = facade.providers_view()["models"][0]
        assert saved["input_modalities"] == ["text"]
        assert saved["source_details"]["input_modalities"] == {"source": "manual"}
    finally:
        provider.close()
