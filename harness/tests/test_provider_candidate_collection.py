import json

from harness.providers import ProviderDefinition, refresh_candidates
from harness.tests.protocol_helpers import ScriptedProvider, send_reply

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
