# 定义、限额与视图计算的纯规则：定义只加载一次并带内容摘要、限额规则的现值与 bounds、
# 建档工作说明写明的材料种类、压缩覆盖范围的序列区间。这些结论只读取仓库内的定义与纯函数，登记为单元层。

from harness.definitions import DEFINITIONS, load_definitions


def test_shipped_definitions_are_loaded_once_at_import():
    loaded = load_definitions()
    assert loaded == DEFINITIONS
    assert DEFINITIONS.version.startswith("sha256:") and len(DEFINITIONS.version) == len("sha256:") + 64


def test_check_timeout_is_six_hundred():
    # 登记里的现值与 bounds 一致；由 rules.registry 读出
    rule = DEFINITIONS.rule("check_timeout_sec")
    assert rule.value == 600 and list(rule.bounds) == [1, 86400]
    assert DEFINITIONS.rule_value("command_timeout_max_sec") == 600


def test_onboarding_prompts_state_the_two_material_kinds():
    # 工单 #346：建档的工作说明写明两类材料与读取顺序，现有行为的材料在前
    product = DEFINITIONS.department_work("product", "onboarding")
    assert "描述现有行为" in product.prompt
    assert "描述要求" in product.prompt
    assert "设计中，未实施" in product.prompt
    assert "设计中，未实施" in DEFINITIONS.department_work("quality", "onboarding").prompt


def test_compaction_coverage_exposes_seq_range_and_covered_through():
    from harness.views import compaction_coverage

    coverage = compaction_coverage({
        "source_event_id": "cmp-1",
        "checkpoint": {"covered_through_event_id": "evt-9"},
        "source_refs": [
            {"event_id": "evt-1", "seq": 4},
            {"event_id": "evt-9", "seq": 12},
        ],
    })
    assert coverage["compaction_event_id"] == "cmp-1"
    assert coverage["covered_through_event_id"] == "evt-9"
    assert coverage["covered_through_seq"] == 12
    assert coverage["source_seq_from"] == 4
    assert coverage["source_seq_through"] == 12
