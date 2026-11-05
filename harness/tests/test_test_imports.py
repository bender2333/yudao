# 测试之间的导入（测试分层设计说明第 3 节）：测试文件只从辅助模块取共用代码，不互相导入。
# 互相导入会把一项检查绑到另一个测试文件里的局部安排上，也让按单个文件运行不可用。
# 这项检查只读源文件，不起子进程、不读数据目录。

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def _test_module(path: Path) -> str:
    # 测试文件按相对 harness/tests/ 的路径组成模块名，kernel/ 等子目录也按点号连接
    return "harness.tests." + ".".join(path.relative_to(TESTS).with_suffix("").parts)


def _imported_modules(source: str) -> list[tuple[str, str]]:
    # 返回（导入的模块，导入的具体名字）：函数内的 import 也算，子进程脚本里的字符串不算
    imported: list[tuple[str, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.extend((alias.name, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.extend((node.module, f"{node.module}.{alias.name}") for alias in node.names)
    return imported


def test_no_test_file_imports_another_test():
    files = sorted(TESTS.rglob("test_*.py"))
    test_modules = {_test_module(path) for path in files}
    offenders = []
    for path in files:
        for module, name in _imported_modules(path.read_text(encoding="utf-8")):
            if module in test_modules or name in test_modules:
                offenders.append(f"{path.relative_to(TESTS)} 导入 {name}")
    assert not offenders, "测试文件之间不应互相导入：\n" + "\n".join(offenders)


def test_the_check_rejects_a_cross_import():
    # 证明上面的检查会抓住互相导入，而不是因为当前恰好没有越界
    module = _test_module(sorted(TESTS.rglob("test_*.py"))[0])
    imported = _imported_modules(f"from {module} import anything\n")
    assert (module, f"{module}.anything") in imported, imported
