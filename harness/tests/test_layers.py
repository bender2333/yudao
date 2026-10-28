from pathlib import Path

from importlinter.cli import lint_imports

# 分层的依赖规则（应用层与接口层设计说明第 2.4 节）：接口层只导入应用层；控制核心不导入应用层与接口层，
# 应用层不导入接口层。合同写在 pyproject.toml 的 [tool.importlinter]，这里按源码中的导入语句检查。
#
# S6a（工单 #829）：合同从两条加到五条——契约模块只导入内核与标准库（骨架与应用设计说明第 3.2、5 节）、
# 应用层只导入控制核心的公开接口（#620，清单按第 2.4 节分类，见 pyproject.toml 里的注释）、
# 应用不导入薄驱动的内部。五条都在报告里出现，少一条这条断言就不过：合同被删掉时能看出来。

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

# 合同的名字与条目：报告里逐个出现，顺序取自 pyproject.toml
CONTRACT_NAMES = (
    "接口层只导入应用层",
    "控制核心不导入应用层与接口层，应用层不导入接口层",
    "契约模块只导入内核与标准库",
    "应用层只导入控制核心的公开接口",
    "应用不导入薄驱动的内部",
)


def test_the_layer_contracts_hold(capsys):
    passed = lint_imports(config_filename=str(PYPROJECT), no_cache=True, no_logo=True) == 0
    report = capsys.readouterr().out
    assert passed, report
    assert f"{len(CONTRACT_NAMES)} kept, 0 broken" in report
    for name in CONTRACT_NAMES:
        assert f"{name} KEPT" in report, f"合同 {name} 不在检查报告里：{report}"
