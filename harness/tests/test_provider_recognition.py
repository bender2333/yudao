# 按连接地址识别服务商并在这家服务商之内查能力资料（模型管理 docs/design/model-management.md「模型访问定义与准入」）。
# 资料取自从 2026-10-30 的真实快照裁剪的 fixtures（harness/tests/data/models_dev_snapshot_20261030.json）；
# 识别、查找与候选补全走同一条路径。

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from harness.definitions import DEFINITIONS, DEFINITIONS_DIR, ModelCapabilities
from harness.providers import capabilities
from harness.providers.discovery import _parse_candidates

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "harness/tests/data/models_dev_snapshot_20261030.json"


def _index():
    spec = importlib.util.spec_from_file_location("recognition_extractor", REPO_ROOT / "scripts/generate_model_capabilities.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    presets = json.loads((DEFINITIONS_DIR / "service_presets.json").read_text(encoding="utf-8"))["presets"]
    table = module.build_table(presets, raw, "2026-10-30.1", "2026-10-30", "https://models.dev/api.json")
    definition = ModelCapabilities.model_validate_json(json.dumps(table), strict=True)
    return capabilities.CapabilityIndex(definition, DEFINITIONS.service_presets)


@pytest.mark.parametrize(("address", "expected"), [
    ("https://opencode.ai/zen/go/v1", "opencode-go"),
    ("https://OPENCODE.ai/zen/go/v1/", "opencode-go"),
    ("https://api.openai.com/another/path", "openai"),
    ("https://api.anthropic.com/v1", "anthropic"),
    ("https://api.moonshot.cn/v1", "moonshotai-cn"),
    ("https://opencode.ai/another/path", None),
    ("https://unrecognized.example/v1", None),
    ("", None),
])
def test_provider_recognition_uses_preset_then_one_api_host(address, expected):
    # R3：预置方案先取对应服务商，其余只接受唯一接口主机。
    assert _index().recognize_provider(address) == expected


def test_model_lookup_stays_in_the_provider_and_keeps_upstream_prefix():
    # R3：真实快照中相同模型 ID 的容量依赖服务商；前缀属于上游 ID。
    index = _index()
    go = index.lookup("https://opencode.ai/zen/go/v1", "kimi-k3")
    other = index.lookup("https://api.moonshot.cn/v1", "kimi-k3")
    assert go is not None and other is not None
    assert (go.context_window, go.max_output_tokens) == (1048576, 131072)
    assert (other.context_window, other.max_output_tokens) == (1048576, 1048576)
    assert index.lookup("https://api.openai.com/v1", "ag/gpt-6-luna") is None
    assert index.lookup("https://unrecognized.example/v1", "gpt-6-luna") is None


def test_candidates_and_lookup_use_the_same_provider_and_source():
    # R2、R3：候选补全使用与选用补全相同的查找对象；上游逐项优先。
    index = _index()
    address = "https://api.openai.com/v1"
    entry = index.lookup(address, "gpt-6-luna")
    assert entry is not None
    [candidate] = _parse_candidates({"data": [{"id": "gpt-6-luna", "context_length": 123456}]},
                                    "", base_url=address, capability_index=index)
    assert candidate["context_window"] == 123456
    assert candidate["context_window_source"] == "models_url"
    assert candidate["max_output_tokens"] == entry.max_output_tokens
    assert candidate["protocol"] == entry.protocol == "responses"
    assert candidate["max_input_tokens"] == entry.max_input_tokens == 922000
    assert candidate["source_details"]["max_output_tokens"] == {
        "source": "capability_table", "provider": "openai", "revision": "2026-10-30.1"}


def test_unrecognized_address_ignores_a_saved_preset_and_other_provider_models():
    # R3：连接地址决定能力资料的服务商，不借用保存的方案标签或模型名。
    [candidate] = _parse_candidates({"data": [{"id": "grok-4.7", "context_length": 100000}]},
                                    "opencode-go", base_url="https://unrecognized.example/v1",
                                    capability_index=_index())
    assert candidate["context_window"] == 100000
    assert candidate["context_window_source"] == "models_url"
    assert "max_output_tokens" not in candidate
    assert candidate["protocol"] == "chat_completions"
    assert candidate["protocol_source"] == "default"


def test_protocol_comes_from_the_capability_table_first():
    # R3：预置方案下能力表有协议的模型取能力表的值；协议为空或表里没有时取方案的默认协议。
    index = _index()
    address = "https://opencode.ai/zen/go/v1"
    [anthropic_model] = _parse_candidates({"data": [{"id": "minimax-m3"}]}, "opencode-go",
                                          base_url=address, capability_index=index)
    assert anthropic_model["protocol"] == "messages"
    assert anthropic_model["protocol_source"] == "capability_table"
    [empty_protocol] = _parse_candidates({"data": [{"id": "gemini-4-argon"}]}, "opencode-go",
                                          base_url=address, capability_index=index)
    assert empty_protocol["protocol"] == "chat_completions"
    assert empty_protocol["protocol_source"] == "preset_default"
    [not_in_table] = _parse_candidates({"data": [{"id": "model-not-in-the-table"}]}, "opencode-go",
                                        base_url=address, capability_index=index)
    assert not_in_table["protocol"] == "chat_completions"
    assert not_in_table["protocol_source"] == "preset_default"
    # 能力表里的容量照常生效（协议为空不影响容量）
    assert empty_protocol["context_window"] == 1048576
    assert empty_protocol["context_window_source"] == "capability_table"
    assert empty_protocol["max_output_tokens"] == 65536


@pytest.mark.parametrize(("raw", "expected"), [
    ("ag/gemini-3.8-flash-high", "gemini-3.8-flash"),
    ("wb/cn:deepseek-v4.1-flash", "deepseek-v4.1-flash"),
    ("hf:deepseek-ai/DeepSeek-V4.1-Flash", "deepseek-v4.1-flash"),
    ("vertex:claude-fable-5:thinking", "claude-fable-5"),
    ("proxy/model-a-minimal", "model-a"),
    ("proxy/model-a-low", "model-a"),
    ("proxy/model-a-medium", "model-a"),
    ("proxy/model-a-high", "model-a"),
    ("proxy/model-a-xhigh", "model-a"),
    ("proxy/model-a-max", "model-a"),
    ("proxy/model-a-thinking", "model-a"),
    ("proxy/model-a-latest", "model-a"),
    ("proxy/model-a:thinking", "model-a"),
    ("proxy/model-a:free", "model-a"),
    ("amazon/amazon.nova-lite-v1:0", "amazon.nova-lite-v1:0"),
    ("ollama/gemma4:31b", "gemma4:31b"),
])
def test_normalized_model_name_strips_prefixes_and_mode_suffixes(raw, expected):
    # R2、R3：归一化按既定顺序剥离前缀与全部声明后缀，同时保留版本号与参数量后缀。
    assert capabilities.normalize_model_name(raw) == expected


def test_capacity_and_protocol_do_not_cross_providers_while_normalized_modality_applies():
    # R2、R3：带渠道前缀的模型在未识别或同家地址上不借用容量与协议，但跨表一致时预填图像输入。
    index = _index()
    [candidate] = _parse_candidates(
        {"data": [{"id": "ag/gpt-6-luna"}]},
        "opencode-go",
        base_url="https://unrecognized.example/v1",
        capability_index=index,
    )
    assert "context_window" not in candidate
    assert "max_output_tokens" not in candidate
    assert candidate["protocol"] == "chat_completions"
    assert candidate["protocol_source"] == "default"
    assert candidate["input_modalities"] == ["text", "image"]
    assert candidate["input_modalities_source"] == "capability_table"
    assert candidate["source_details"]["input_modalities"] == {
        "source": "capability_table",
        "provider": "gpt-6-luna",
        "revision": "2026-10-30.1",
    }


def test_normalized_modality_requires_cross_provider_consistency():
    # R2、R3：跨服务商按归一化模型名查找输入模态时，仅非空记录结论完全一致才采用能力表，冲突则回退 default。
    table = ModelCapabilities.model_validate_json(json.dumps({
        "version": 2,
        "revision": "2026-10-30.1",
        "snapshot_date": "2026-10-30",
        "source": "test-fixture",
        "providers": {
            "provider-a": {
                "api": "https://a.example/v1",
                "npm": "@ai-sdk/openai-compatible",
                "models": [
                    {"model": "vendor/agree-vision:free", "input_modalities": ["text", "image"]},
                    {"model": "agree-text", "input_modalities": ["text"]},
                    {"model": "conflict-model", "input_modalities": ["text", "image"]},
                ],
            },
            "provider-b": {
                "api": "https://b.example/v1",
                "npm": "@ai-sdk/openai-compatible",
                "models": [
                    {"model": "agree-vision-high", "input_modalities": ["text", "image"]},
                    {"model": "vendor/agree-text-latest", "input_modalities": ["text"]},
                    {"model": "vendor/conflict-model-high", "input_modalities": ["text"]},
                ],
            },
            "provider-c": {
                "api": "https://c.example/v1",
                "npm": "@ai-sdk/openai-compatible",
                "models": [
                    {"model": "agree-vision-low", "input_modalities": []},
                ],
            },
        },
        "presets": {},
    }))
    index = capabilities.CapabilityIndex(table, DEFINITIONS.service_presets)
    parsed = _parse_candidates(
        {"data": [
            {"id": "wb/cn:agree-vision-thinking"},
            {"id": "ag/agree-text-xhigh"},
            {"id": "wb/cn:conflict-model"},
            {"id": "unknown-model"},
        ]},
        "",
        base_url="https://unrecognized.example/v1",
        capability_index=index,
    )
    by_id = {item["id"]: item for item in parsed}
    assert by_id["wb/cn:agree-vision-thinking"]["input_modalities"] == ["text", "image"]
    assert by_id["wb/cn:agree-vision-thinking"]["input_modalities_source"] == "capability_table"
    assert by_id["ag/agree-text-xhigh"]["input_modalities"] == ["text"]
    assert by_id["ag/agree-text-xhigh"]["input_modalities_source"] == "capability_table"
    assert by_id["wb/cn:conflict-model"]["input_modalities"] == ["text"]
    assert by_id["wb/cn:conflict-model"]["input_modalities_source"] == "default"
    assert by_id["wb/cn:conflict-model"]["source_details"]["input_modalities"] == {"source": "default"}
    assert by_id["unknown-model"]["input_modalities"] == ["text"]
    assert by_id["unknown-model"]["input_modalities_source"] == "default"
