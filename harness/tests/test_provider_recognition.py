# 按连接地址识别服务商并在这家服务商之内查能力资料（模型管理设计说明第 4.3 节）。
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


def test_preset_address_recognizes_the_provider_of_the_plan():
    # R3：预置方案的地址识别为该方案对应的服务商（models.dev 的 provider ID）。
    index = _index()
    assert index.recognize_provider("https://opencode.ai/zen/go/v1") == "opencode-go"
    entry = index.lookup("https://opencode.ai/zen/go/v1", "gemini-4-argon")
    assert entry is not None and entry.protocol is None
    assert entry.npm == "@ai-sdk/google"
