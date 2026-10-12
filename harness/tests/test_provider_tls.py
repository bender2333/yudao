import json
import ssl

import pytest
import trustme

from harness.models import EventType
from harness.providers import ProviderDefinition, effective_models_url, refresh_candidates, ssl_context
from harness.providers.tls import service_address
from harness.tests.helpers import FAST_RETRIES
from harness.tests.protocol_helpers import ScriptedProvider, facade_with, provider_system, send_reply
from harness.tests.provider_replies import product_spec_reply

# Provider 的连接信任操作系统的证书库（D17，truststore）。测试内启动使用测试 CA 签发证书的真实 HTTPS 服务：
# 没有加入信任来源的 CA 签发的证书校验失败；加入信任来源的 CA 用 truststore 支持的方式（SSLContext.load_verify_locations）
# 在测试进程内加入，本机的系统证书库不变。Provider 的上下文每个线程一个，测试中的模型调用与模型列表都在测试自己的线程中
# 执行（asyncio.run），CA 加入这个线程的上下文

PROTOCOLS = ["responses", "chat_completions", "messages"]


@pytest.fixture(scope="module")
def trusted_ca() -> trustme.CA:
    ca = trustme.CA()
    ca.configure_trust(ssl_context())
    return ca


def _server_context(ca: trustme.CA) -> ssl.SSLContext:
    # 服务端证书由这个 CA 签发，证书的地址是 127.0.0.1
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ca.issue_cert("127.0.0.1").configure_cert(context)
    return context


def _certificate_error(provider: ScriptedProvider) -> str:
    return f"Model provider certificate verification failed: {provider.base}"


# 证书校验失败的诊断字段与其他传输错误相同，写明失败的传输阶段
CERTIFICATE_DIAGNOSTICS = {
    "error_type": "certificate_verification", "trace_available": True, "transport_phase": "start_tls",
    "transport_event": "connection.start_tls.failed", "cause_type": "ConnectError",
}


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_untrusted_certificate_is_a_nonretryable_failure_naming_the_service(protocol, data_dir):
    # 证书不在信任来源中：尝试记为不可重试的证书校验失败，只有一次尝试，错误写明服务地址，请求没有到达服务
    provider = ScriptedProvider([product_spec_reply(protocol)], tls=_server_context(trustme.CA()))
    try:
        system, run_id = provider_system(data_dir, provider.base, protocol, step_limits=FAST_RETRIES)
        try:
            system.activate_once(run_id)
            events = system.store.list_events(run_id)
        finally:
            system.close()
    finally:
        provider.close()
    requested = [event for event in events if event.type == EventType.MODEL_REQUESTED]
    failed = [event for event in events if event.type == EventType.MODEL_ATTEMPT_FAILED]
    assert len(requested) == 1
    assert [event.error for event in failed] == [_certificate_error(provider)]
    assert failed[0].payload["reason"] == "provider_error"
    assert failed[0].payload["retryable"] is False and failed[0].payload["will_retry"] is False
    assert failed[0].payload["diagnostics"] == CERTIFICATE_DIAGNOSTICS
    assert not any(event.type == EventType.MODEL_RETRY_SCHEDULED for event in events)
    assert provider.requests == []


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_certificate_from_an_authority_in_the_trust_source_is_accepted(protocol, data_dir, trusted_ca):
    provider = ScriptedProvider([product_spec_reply(protocol)], tls=_server_context(trusted_ca))
    try:
        system, run_id = provider_system(data_dir, provider.base, protocol, step_limits=FAST_RETRIES)
        try:
            result = system.activate_once(run_id)
        finally:
            system.close()
    finally:
        provider.close()
    assert result.phase == "ENGINEERING", result.error
    assert len(provider.requests) == 1


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_model_test_reports_the_certificate_verification_failure(protocol):
    # 模型测试遇到证书校验失败：结果写明同样的原因，不记录准入
    provider = ScriptedProvider([], tls=_server_context(trustme.CA()))
    try:
        facade = facade_with(provider.base + "/v1", protocol=protocol)
        result = facade.model_test("go", "m-go")
    finally:
        provider.close()
    assert result["ok"] is False and result["admitted"] is False
    assert result["error"] == _certificate_error(provider)
    assert provider.requests == []


def _model_list(_provider: ScriptedProvider, handler) -> None:
    send_reply(handler, 200, "application/json", json.dumps({"data": [{"id": "model-a"}]}).encode("utf-8"))


def test_model_list_is_read_over_the_same_trust_source(trusted_ca):
    # 模型列表同样是 Provider 的连接，信任同一个来源
    provider = ScriptedProvider([_model_list], tls=_server_context(trusted_ca))
    try:
        result = refresh_candidates(ProviderDefinition(id="go", name="Go", models_url=provider.base + "/v1/models"),
                                    api_key="tls-secret")
    finally:
        provider.close()
    assert result["status"] == "ok", result["error"]
    assert [candidate["id"] for candidate in result["candidates"]] == ["model-a"]
    assert provider.requests == [None]


def test_model_list_reports_the_certificate_verification_failure():
    provider = ScriptedProvider([_model_list], tls=_server_context(trustme.CA()))
    definition = ProviderDefinition(id="go", name="Go", models_url=provider.base + "/v1/models")
    try:
        result = refresh_candidates(definition, api_key="tls-secret")
    finally:
        provider.close()
    source_url = effective_models_url(definition)
    assert result["status"] == "unknown"
    assert result["error"] == f"模型列表请求 {source_url} 失败：证书校验失败（{service_address(source_url)}）"
    assert provider.requests == []
