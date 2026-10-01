# 模型能力表（工单 #146，设计说明第 4.1 节、ADR-0003）：提取脚本的取材规则与运行时访问。
# 提取脚本用仓库内的真实数据 fixtures（harness/tests/data/models_dev_snapshot.json，
# 从 models.dev 的 api.json 裁剪，含一个未被任何预置服务方案引用的 provider）；不使用假数据。

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "harness" / "tests" / "data" / "models_dev_snapshot.json"
SPEC = REPO_ROOT / "scripts" / "generate_model_capabilities.py"

from harness.definitions import DEFINITIONS, DEFINITIONS_DIR, DefinitionError, load_definitions
from harness.providers import capabilities


def _extractor():
    # 按文件路径加载提取脚本（scripts 目录不是安装包）
    spec = importlib.util.spec_from_file_location("generate_model_capabilities", SPEC)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _presets():
    return json.loads((DEFINITIONS_DIR / "service_presets.json").read_text(encoding="utf-8"))["presets"]


def _fixture_copy():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_shipped_capability_table_covers_only_preset_plans():
    table = DEFINITIONS.model_capabilities
    assert table.revision and table.snapshot_date and table.source
    preset_ids = {preset.id for preset in DEFINITIONS.service_presets.presets}
    assert set(table.presets) <= preset_ids
    # 预置表里记录了 models_dev_id 的服务方案都有条目（当前只有 OpenCode Go）
    for preset in DEFINITIONS.service_presets.presets:
        if preset.models_dev_id:
            assert preset.id in table.presets
            assert table.presets[preset.id]


def test_extractor_keeps_section_4_1_fields_and_filters_providers():
    module = _extractor()
    table = module.build_table(_presets(), _fixture_copy(), "2026-10-02.1", "2026-10-02", "https://models.dev")
    assert set(table["presets"]) == {"opencode-go"}  # fixtures 里的 anthropic 不被收录
    entries = {entry["model"]: entry for entry in table["presets"]["opencode-go"]}
    assert set(entries) == {"deepseek-v4-flash", "deepseek-v4-flash-vision-exp", "kimi-k2.7-code"}
    assert entries["deepseek-v4-flash"] == {
        "model": "deepseek-v4-flash",
        "input_modalities": ["text"],
        "output_modalities": ["text"],
        "context_window": 1000000,
        "max_output_tokens": 384000,
        "tool_call": True,
        "reasoning": True,
    }
    assert entries["deepseek-v4-flash-vision-exp"]["input_modalities"] == ["image", "text"]


def test_extractor_skips_missing_modalities_and_unknown_limit():
    module = _extractor()
    # fixtures 中 kimi-k2.7-code 的记录缺少 modalities 字段（上游允许缺少）：不记录输入与输出方式
    table = module.build_table(_presets(), _fixture_copy(), "2026-10-02.1", "2026-10-02", "https://models.dev")
    kimi = {entry["model"]: entry for entry in table["presets"]["opencode-go"]}["kimi-k2.7-code"]
    assert "input_modalities" not in kimi and "output_modalities" not in kimi
    assert kimi["context_window"] == 262144 and kimi["max_output_tokens"] == 262144
    # limit 缺少时容量记为 null，预填留空由用户填写
    stripped = _fixture_copy()
    del stripped["opencode-go"]["models"]["deepseek-v4-flash"]["limit"]
    second = module.build_table(_presets(), stripped, "2026-10-02.1", "2026-10-02", "https://models.dev")
    flash = {entry["model"]: entry for entry in second["presets"]["opencode-go"]}["deepseek-v4-flash"]
    assert flash["context_window"] is None and flash["max_output_tokens"] is None


def test_extractor_fails_fast_when_preset_plan_is_absent_upstream():
    module = _extractor()
    models_dev = {key: value for key, value in _fixture_copy().items() if key != "opencode-go"}
    with pytest.raises(ValueError, match="opencode-go"):
        module.build_table(_presets(), models_dev, "2026-10-02.1", "2026-10-02", "https://models.dev")


def test_extractor_output_is_stable(tmp_path):
    module = _extractor()
    out_a, out_b = tmp_path / "a.json", tmp_path / "b.json"
    argv = ["--input", str(FIXTURE), "--date", "2026-10-02"]
    module.main([*argv, "--out", str(out_a)])
    module.main([*argv, "--out", str(out_b)])
    assert out_a.read_bytes() == out_b.read_bytes()


def test_committed_table_matches_the_extractor():
    # 提交的能力表与提取脚本按仓库内 fixtures 的取材结果一致（同一脚本、同一预置表）。
    # fixtures 里 kimi 的记录被有意裁掉 modalities 覆盖缺少的形状，逐条比对只看未裁剪的记录
    module = _extractor()
    table = module.build_table(_presets(), _fixture_copy(), "2026-10-02.1", "2026-10-02", "https://models.dev")
    committed = json.loads((DEFINITIONS_DIR / "model_capabilities.json").read_text(encoding="utf-8"))
    by_model = {row["model"]: row for row in committed["presets"]["opencode-go"]}
    for entry in table["presets"]["opencode-go"]:
        if entry["model"] == "kimi-k2.7-code":
            continue
        assert by_model[entry["model"]] == entry


def test_table_public_lists_entries_with_metadata():
    view = capabilities.table_public()
    assert view["revision"] == capabilities.CAPABILITY_TABLE_REVISION
    assert view["snapshot_date"] == capabilities.CAPABILITY_TABLE_SNAPSHOT_DATE
    assert view["source"] == capabilities.CAPABILITY_TABLE_SOURCE
    assert set(view["presets"]) == set(DEFINITIONS.model_capabilities.presets)
    entry = view["presets"]["opencode-go"][0]
    assert set(entry) == {"model", "input_modalities", "output_modalities",
                          "context_window", "max_output_tokens", "tool_call", "reasoning"}


def test_capability_lookup_by_preset_and_model():
    hit = capabilities.capability("opencode-go", "deepseek-v4-flash-vision-exp")
    assert hit is not None and "image" in hit.input_modalities
    assert capabilities.capability("opencode-go", "不存在的模型") is None
    assert capabilities.capability("custom", "deepseek-v4-flash") is None
    assert capabilities.entries("custom") == ()
    listed = capabilities.entries("opencode-go")
    assert [entry.model for entry in listed] == sorted(entry.model for entry in listed)


def _copy_definitions(target: Path) -> Path:
    for name in ("organization.json", "roles.json", "tools.json", "proposal_contracts.json",
                 "limits.json", "stop_reasons.json", "service_presets.json",
                 "model_capabilities.json", "work_items.json"):
        (target / name).write_bytes((DEFINITIONS_DIR / name).read_bytes())
    return target


def test_capability_entry_for_unknown_preset_is_rejected(tmp_path):
    directory = _copy_definitions(tmp_path)
    table = json.loads((directory / "model_capabilities.json").read_text(encoding="utf-8"))
    table["presets"]["no-such-preset"] = table["presets"]["opencode-go"][:1]
    (directory / "model_capabilities.json").write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    assert ("model_capabilities.json", "presets.no-such-preset",
            "能力表中有预置表没有的服务方案") in raised.value.issues


def test_missing_entry_for_recorded_models_dev_id_is_rejected(tmp_path):
    directory = _copy_definitions(tmp_path)
    table = json.loads((directory / "model_capabilities.json").read_text(encoding="utf-8"))
    table["presets"].pop("opencode-go")
    (directory / "model_capabilities.json").write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    assert any(issue[0] == "model_capabilities.json" and issue[1] == "presets.opencode-go"
               for issue in raised.value.issues)


def test_duplicate_model_in_one_preset_is_rejected(tmp_path):
    directory = _copy_definitions(tmp_path)
    table = json.loads((directory / "model_capabilities.json").read_text(encoding="utf-8"))
    rows = table["presets"]["opencode-go"]
    table["presets"]["opencode-go"] = [*rows, rows[0]]
    (directory / "model_capabilities.json").write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    assert any(issue[0] == "model_capabilities.json" and issue[1].startswith("presets.opencode-go[")
               for issue in raised.value.issues)
