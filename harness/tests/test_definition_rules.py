# 定义、限额与视图计算的纯规则：定义只加载一次并带内容摘要、限额规则的现值与 bounds、
# 建档工作说明写明的材料种类、压缩覆盖范围的序列区间。这些结论只读取仓库内的定义与纯函数，登记为单元层。

from harness.definitions import DEFINITIONS, load_definitions


def test_shipped_definitions_are_loaded_once_at_import():
    loaded = load_definitions()
    assert loaded == DEFINITIONS
    assert DEFINITIONS.version.startswith("sha256:") and len(DEFINITIONS.version) == len("sha256:") + 64


