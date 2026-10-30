# 模型能力表（工单 #146，模型管理设计说明第 4.1 节）：提取脚本的取材规则与运行时访问。
# 提取脚本用仓库内的真实数据 fixtures（harness/tests/data/models_dev_snapshot.json，
# 从 models.dev 的 api.json 裁剪，含一个未被任何预置服务方案引用的 provider）；不使用假数据。

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "harness" / "tests" / "data" / "models_dev_snapshot.json"
# 另一份 fixtures：同一个服务方案下的模型带三种取值以外的 provider.npm，提取脚本要报出它
OTHER_FIXTURE = REPO_ROOT / "harness" / "tests" / "data" / "models_dev_snapshot_other_npm.json"
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


def test_shipped_capability_table_preserves_preset_plans():
    table = DEFINITIONS.model_capabilities
    assert table.revision and table.snapshot_date and table.source
    preset_ids = {preset.id for preset in DEFINITIONS.service_presets.presets}
    assert set(table.presets) <= preset_ids
    # 预置表里记录了 models_dev_id 的服务方案都有条目（当前只有 OpenCode Go）
    for preset in DEFINITIONS.service_presets.presets:
        if preset.models_dev_id:
            assert preset.id in table.presets
            assert table.presets[preset.id]


def test_extractor_keeps_section_4_1_fields_for_all_providers():
    # R2：定义格式增加服务商资料，保留旧服务方案字段的读法。
    module = _extractor()
    table = module.build_table(_presets(), _fixture_copy(), "2026-10-11.1", "2026-10-11", "https://models.dev")
    assert table["version"] == 2
    assert set(table["providers"]) == {"anthropic", "opencode-go"}
    assert table["providers"]["anthropic"]["api"] == "https://api.anthropic.com"
    assert table["providers"]["anthropic"]["npm"] == "@ai-sdk/anthropic"
    assert table["providers"]["opencode-go"]["models"] == table["presets"]["opencode-go"]
    entries = {entry["model"]: entry for entry in table["presets"]["opencode-go"]}
    assert set(entries) == {"claude-haiku-5-5", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp",
                            "glm-5.3-flash", "grok-4.7", "kimi-k2.7-code"}
    assert entries["deepseek-v4-flash"] == {
        "model": "deepseek-v4-flash",
        "protocol": "chat_completions",
        "input_modalities": ["text"],
        "output_modalities": ["text"],
        "context_window": 1000000,
        "max_output_tokens": 384000,
        "tool_call": True,
        "reasoning": True,
    }
    assert entries["deepseek-v4-flash-vision-exp"]["input_modalities"] == ["image", "text"]
    # 协议按 provider.npm 映射：openai → responses，anthropic → messages，openai-compatible → chat_completions
    assert entries["grok-4.7"]["protocol"] == "responses"
    assert entries["claude-haiku-5-5"]["protocol"] == "messages"
    # 模型没有单独声明 provider.npm 时记录服务方案的默认协议
    assert entries["glm-5.3-flash"]["protocol"] == "chat_completions"
    assert entries["kimi-k2.7-code"]["protocol"] == "chat_completions"
    assert entries["deepseek-v4-flash-vision-exp"]["protocol"] == "chat_completions"


def test_extractor_skips_missing_modalities_and_unknown_limit():
    module = _extractor()
    # fixtures 中 kimi-k2.7-code 的记录缺少 modalities 字段（上游允许缺少）：不记录输入与输出方式
    table = module.build_table(_presets(), _fixture_copy(), "2026-10-11.1", "2026-10-11", "https://models.dev")
    kimi = {entry["model"]: entry for entry in table["presets"]["opencode-go"]}["kimi-k2.7-code"]
    assert "input_modalities" not in kimi and "output_modalities" not in kimi
    assert kimi["context_window"] == 262144 and kimi["max_output_tokens"] == 262144
    # limit 缺少时容量记为 null，预填留空由用户填写
    stripped = _fixture_copy()
    del stripped["opencode-go"]["models"]["deepseek-v4-flash"]["limit"]
    second = module.build_table(_presets(), stripped, "2026-10-11.1", "2026-10-11", "https://models.dev")
    flash = {entry["model"]: entry for entry in second["presets"]["opencode-go"]}["deepseek-v4-flash"]
    assert flash["context_window"] is None and flash["max_output_tokens"] is None


def test_extractor_fails_fast_when_preset_plan_is_absent_upstream():
    module = _extractor()
    models_dev = {key: value for key, value in _fixture_copy().items() if key != "opencode-go"}
    with pytest.raises(ValueError, match="opencode-go"):
        module.build_table(_presets(), models_dev, "2026-10-11.1", "2026-10-11", "https://models.dev")


def test_extractor_fails_fast_on_unmapped_provider_npm():
    # 三种取值以外的 provider.npm：以错误结束，并列出这些模型（设计说明第 4.1 节）
    module = _extractor()
    models_dev = json.loads(OTHER_FIXTURE.read_text(encoding="utf-8"))
    with pytest.raises(ValueError) as raised:
        module.build_table(_presets(), models_dev, "2026-10-11.1", "2026-10-11", "https://models.dev")
    message = str(raised.value)
    assert "provider.npm 不在协议映射中" in message
    assert "mistral-large-4（@ai-sdk/mistral）" in message


@pytest.mark.parametrize(("entry", "expected"), [
    ({}, ""),
    ({"provider": "openai"}, ""),
    ({"provider": {"npm": 3}}, ""),
    ({"provider": {"npm": "  @ai-sdk/openai  "}}, "@ai-sdk/openai"),
])
def test_declared_npm_reads_only_string_provider_npm(entry, expected):
    # 模型单独声明的 provider.npm：只有字符串取值有效，去掉首尾空白；其余输入返回空串，由调用方取默认协议
    module = _extractor()
    assert module.declared_npm(entry) == expected


def test_extractor_output_is_stable(tmp_path):
    module = _extractor()
    out_a, out_b = tmp_path / "a.json", tmp_path / "b.json"
    argv = ["--input", str(FIXTURE), "--date", "2026-10-11"]
    module.main([*argv, "--out", str(out_a)])
    module.main([*argv, "--out", str(out_b)])
    assert out_a.read_bytes() == out_b.read_bytes()


def test_committed_table_matches_the_extractor():
    # 提交的能力表与提取脚本按仓库内 fixtures 的取材结果一致（同一脚本、同一预置表）。
    # fixtures 里 kimi 的记录被有意裁掉 modalities 覆盖缺少的形状，逐条比对只看未裁剪的记录
    module = _extractor()
    table = module.build_table(_presets(), _fixture_copy(), "2026-10-11.1", "2026-10-11", "https://models.dev")
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
    assert set(entry) == {"model", "protocol", "input_modalities", "output_modalities",
                          "context_window", "max_output_tokens", "max_input_tokens", "tool_call", "reasoning"}


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
                 "rules.json", "stop_reasons.json", "service_presets.json",
                 "model_capabilities.json", "work_items.json", "routings.json", "event_sources.json"):
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

def test_reading_the_capability_table_never_reaches_the_network():
    # R2：通过真实审计事件核对离线读取；不替换网络实现。
    attempts: list[object] = []
    active = True

    def guard(event, args):
        if active and event == "socket.connect":
            attempts.append(args)
            raise AssertionError(f"能力表的读取不应连接网络：{args}")

    sys.addaudithook(guard)
    try:
        view = capabilities.table_public()
        assert capabilities.capability("opencode-go", view["presets"]["opencode-go"][0]["model"]) is not None
        assert capabilities.entries("opencode-go")
    finally:
        active = False
    assert attempts == []


def _version_two_table():
    return _extractor().build_table(_presets(), _fixture_copy(), "2026-10-30.1", "2026-10-30", "https://models.dev")


def test_version_two_definitions_load_provider_metadata_and_optional_input_limit(tmp_path):
    # R2：增加字段后的定义仍能通过同一加载入口读取，旧服务方案内容不变。
    directory = _copy_definitions(tmp_path)
    table = _version_two_table()
    (directory / "model_capabilities.json").write_text(json.dumps(table), encoding="utf-8")
    loaded = load_definitions(directory).model_capabilities
    assert loaded.version == 2
    assert set(loaded.providers) == {"anthropic", "opencode-go"}
    assert loaded.providers["opencode-go"].models == loaded.presets["opencode-go"]


@pytest.mark.parametrize("case", ["missing_provider", "inconsistent_models", "duplicate_model", "invalid_npm", "future_version"])
def test_invalid_version_two_provider_definitions_are_rejected(tmp_path, case):
    # R2：拒绝缺失的预置服务商、双份模型资料矛盾、重复模型和不合法的新字段。
    directory = _copy_definitions(tmp_path)
    table = _version_two_table()
    if case == "missing_provider":
        del table["providers"]["opencode-go"]
    elif case == "inconsistent_models":
        table["providers"]["opencode-go"]["models"] = []
    elif case == "duplicate_model":
        table["providers"]["anthropic"]["models"].append(table["providers"]["anthropic"]["models"][0])
    elif case == "invalid_npm":
        table["providers"]["anthropic"]["npm"] = ""
    else:
        table["version"] = 3
    (directory / "model_capabilities.json").write_text(json.dumps(table), encoding="utf-8")
    with pytest.raises(DefinitionError) as raised:
        load_definitions(directory)
    assert any(issue[0] == "model_capabilities.json" for issue in raised.value.issues)


def test_extractor_explicit_provider_exclusion_is_visible_and_cannot_remove_a_preset():
    # R2：排除由快照更新者明确指定，拼写错误及排除预置服务商都立即报错。
    module = _extractor()
    table = module.build_table(_presets(), _fixture_copy(), "r", "2026-10-30", "https://models.dev",
                               excluded_providers=("anthropic",))
    assert set(table["providers"]) == {"opencode-go"}
    for excluded in ("absent", "opencode-go"):
        with pytest.raises(ValueError, match=excluded):
            module.build_table(_presets(), _fixture_copy(), "r", "2026-10-30", "https://models.dev",
                               excluded_providers=(excluded,))


def test_extractor_reports_every_unmapped_provider_package_without_writing_a_file(tmp_path, capsys):
    # R2：严格处理服务商级与模型级接入包，失败时没有半份快照输出。
    module = _extractor()
    raw = _fixture_copy()
    raw["anthropic"]["npm"] = "unregistered-package"
    raw["opencode-go"]["models"]["grok-4.7"]["provider"]["npm"] = "another-unregistered-package"
    local_input = tmp_path / "unmapped.json"
    local_input.write_text(json.dumps(raw), encoding="utf-8")
    output = tmp_path / "result.json"
    assert module.main(["--input", str(local_input), "--out", str(output)]) == 1
    message = capsys.readouterr().err
    assert "anthropic（unregistered-package）" in message
    assert "opencode-go/grok-4.7（another-unregistered-package）" in message
    assert not output.exists()
