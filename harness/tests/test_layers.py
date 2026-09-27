from pathlib import Path

from importlinter.cli import lint_imports

# 分层的依赖规则（应用层与接口层设计说明第 2.4 节）：接口层只导入应用层；控制核心不导入应用层与接口层，
# 应用层不导入接口层。合同写在 pyproject.toml 的 [tool.importlinter]，这里按源码中的导入语句检查。

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_the_layer_contracts_hold(capsys):
    passed = lint_imports(config_filename=str(PYPROJECT), no_cache=True, no_logo=True) == 0
    report = capsys.readouterr().out
    assert passed, report
    assert "2 kept, 0 broken" in report
