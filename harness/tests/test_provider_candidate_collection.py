import json
import ssl

import trustme

from harness.providers import ProviderDefinition, refresh_candidates
from harness.providers import capabilities
from harness.tests.protocol_helpers import ScriptedProvider, send_reply
from harness.tests.wait_limits import WAIT_FOR_HOST_WORK_SEC

# 候选采集从上游模型列表取窗口与输出上限（模型管理设计说明第 4.3 节）：上游用 context_length 与
# max_completion_tokens 两种顶层字段时，采集结果里的候选带着这两项，来源仍是上游模型列表；
# 列表没有返回容量的候选里没有这两个键。模型列表由测试内启动的真实 HTTP 服务给出（集成层）。

UPSTREAM_MODELS = {"data": [
    {"id": "gemini", "object": "model", "owned_by": "combo",
     "context_length": 1048576, "max_completion_tokens": 65536},
    {"id": "model-without-limits", "object": "model", "owned_by": "combo"},
]}


def _model_list(_provider: ScriptedProvider, handler) -> None:
    send_reply(handler, 200, "application/json", json.dumps(UPSTREAM_MODELS).encode("utf-8"))


def test_collected_candidates_carry_the_window_and_output_limit_from_the_model_list():
    provider = ScriptedProvider([_model_list])
    try:
        result = refresh_candidates(ProviderDefinition(id="custom", name="Custom",
                                                       models_url=provider.base + "/v1/models"),
                                    api_key="list-secret")
    finally:
        provider.close()
    assert result["status"] == "ok", result["error"]
    by_id = {candidate["id"]: candidate for candidate in result["candidates"]}
    gemini = by_id["gemini"]
    assert (gemini["context_window"], gemini["context_window_source"]) == (1048576, "models_url")
    assert (gemini["max_output_tokens"], gemini["max_output_tokens_source"]) == (65536, "models_url")
    assert "context_window" not in by_id["model-without-limits"]
    assert "max_output_tokens" not in by_id["model-without-limits"]


def test_collected_candidates_take_the_window_by_the_priority_when_several_writings_appear():
    # R3：上游同时给出 context_length 与 model_info 两种写法时按次序取值，来源仍是上游模型列表。
    models = {"data": [{"id": "model-with-two-writings", "context_length": 1048576,
                        "model_info": {"gemma3.context_length": 131072}}]}
    upstream = ScriptedProvider([lambda _provider, handler: send_reply(
        handler, 200, "application/json", json.dumps(models).encode("utf-8"))])
    try:
        result = refresh_candidates(ProviderDefinition(id="custom", name="Custom",
                                                       models_url=upstream.base + "/v1/models"),
                                    api_key="list-secret")
    finally:
        upstream.close()
    assert result["status"] == "ok", result["error"]
    [candidate] = result["candidates"]
    assert (candidate["context_window"], candidate["context_window_source"]) == (1048576, "models_url")


def test_candidates_use_table_metadata_and_upstream_modalities_without_inferring_from_names():
    # R2、R3：列表优先、能力表来源与适用性的公开候选合同，通过真实服务读取。
    models = {"data": [
        {"id": "deepseek-v4-pro", "context_length": 500000},
        {"id": "deepseek-v4-flash-vision-exp", "input_modalities": ["text"],
         "output_modalities": ["audio"], "reasoning": False},
        {"id": "unknown-image-embedding-model"},
        {"id": "text-and-audio", "modalities": {"output": ["text", "audio"]}},
    ]}
    upstream = ScriptedProvider([lambda _provider, handler: send_reply(
        handler, 200, "application/json", json.dumps(models).encode("utf-8"))])
    try:
        result = refresh_candidates(ProviderDefinition(id="go", name="Go", preset_id="opencode-go",
                                                       base_url="https://opencode.ai/zen/go/v1",
                                                       models_url=upstream.base + "/models"), api_key="local-key")
    finally:
        upstream.close()
    assert result["status"] == "ok", result["error"]
    by_id = {candidate["id"]: candidate for candidate in result["candidates"]}
    table = by_id["deepseek-v4-pro"]
    # 协议先取能力表（识别出的服务商之内），再取方案的默认协议
    assert table["protocol"] == "chat_completions" and table["protocol_source"] == "capability_table"
    assert (table["context_window"], table["context_window_source"]) == (500000, "models_url")
    assert (table["max_output_tokens"], table["max_output_tokens_source"]) == (384000, "capability_table")
    assert table["source_details"]["max_output_tokens"] == {
        "source": "capability_table", "provider": "opencode-go", "revision": capabilities.CAPABILITY_TABLE_REVISION}
    assert table["reasoning"] is True and table["reasoning_source"] == "capability_table"
    overridden = by_id["deepseek-v4-flash-vision-exp"]
    assert overridden["input_modalities"] == ["text"] and overridden["input_modalities_source"] == "models_url"
    assert overridden["applicable"] is False and overridden["applicable_source"] == "models_url"
    assert overridden["reasoning"] is False and overridden["reasoning_source"] == "models_url"
    unknown = by_id["unknown-image-embedding-model"]
    assert unknown["applicable"] is True and unknown["input_modalities"] == ["text"]
    assert unknown["reasoning"] is None
    assert by_id["text-and-audio"]["applicable"] is True


def test_candidate_timeout_reports_the_requested_address_and_timeout():
    # R3：服务确实接收请求并保持回应，客户端自己的 HTTP 超时产生失败。
    def hold(provider, _handler):
        provider.held.set()
        provider.release.wait(WAIT_FOR_HOST_WORK_SEC)
    upstream = ScriptedProvider([hold])
    address = upstream.base + "/models"
    try:
        result = refresh_candidates(ProviderDefinition(id="slow", name="Slow", models_url=address),
                                    api_key="local-key", timeout_sec=0.1)
        assert upstream.held.is_set()
    finally:
        upstream.close()
    assert result["reason"] == "unreachable" and address in result["error"]
    assert "超时" in result["error"]


def test_candidate_certificate_failure_reports_the_requested_address():
    # R3：真实自签名 HTTPS 服务，没有把签发 CA 加入信任来源。
    ca = trustme.CA()
    certificate = ca.issue_cert("127.0.0.1")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    certificate.configure_cert(context)
    upstream = ScriptedProvider([], tls=context)
    address = upstream.base + "/models"
    try:
        result = refresh_candidates(ProviderDefinition(id="tls", name="TLS", models_url=address), api_key="local-key")
    finally:
        upstream.close()
    assert result["reason"] == "unreachable" and address in result["error"]
    assert "证书校验失败" in result["error"]
