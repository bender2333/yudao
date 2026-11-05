# 定义、限额与视图计算的纯规则：定义只加载一次并带内容摘要、限额规则的现值与 bounds、
# 建档工作说明写明的材料种类、压缩覆盖范围的序列区间。这些结论只读取仓库内的定义与纯函数，登记为单元层。

from harness.definitions import DEFINITIONS, load_definitions


def test_shipped_definitions_are_loaded_once_at_import():
    loaded = load_definitions()
    assert loaded == DEFINITIONS
    assert DEFINITIONS.version.startswith("sha256:") and len(DEFINITIONS.version) == len("sha256:") + 64


def test_readiness_timeout_matches_the_design_range():
    # R2：规则登记的就绪时限与设计说明「启动方式」的参数表一致：初值 300、范围 10 至 1800；
    # origin 指向小节，不写行号（设计说明与登记的关系）
    rule = DEFINITIONS.rule("execution.readiness_timeout_sec")
    assert rule.value == 300 and list(rule.bounds) == [10, 1800]
    assert "浏览器与 computer use 设计说明" in rule.origin and "启动方式" in rule.origin
    assert "第" not in rule.origin and "行" not in rule.origin


