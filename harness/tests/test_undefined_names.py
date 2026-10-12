# 全部源文件的未定义名称检查（测试分层设计说明第 2、3 节）。
#
# 搬移共用代码时容易删掉同一文件里仍在使用的 import 行，这类缺漏只在测试跑到那一行时才报
# NameError，集成层的用例要完整跑一次才暴露。这项检查用 pyflakes 的 F821 一次找出来。
# 它要读完 harness/ 下全部源文件再逐个检查（267 个文件，约 4 秒），机器有其他任务在跑时
# 超过单元层 5 秒的上限，按第 2 节登记为 module。

import ast
from pathlib import Path

from pyflakes.checker import Checker
from pyflakes.messages import UndefinedName

TESTS = Path(__file__).resolve().parent
SOURCES = TESTS.parent


def _undefined_names(source: str, name: str) -> list[str]:
    # UndefinedName 报告带着行列，按文件逐个登记，便于指出缺少哪一行 import
    return [str(message) for message in Checker(ast.parse(source), name).messages
            if isinstance(message, UndefinedName)]


def test_no_module_has_an_undefined_name():
    offenders = []
    for path in sorted(SOURCES.rglob("*.py")):
        offenders.extend(_undefined_names(path.read_text(encoding="utf-8"), str(path)))
    assert not offenders, "不应有未定义名称：\n" + "\n".join(offenders)


def test_the_check_rejects_an_undefined_name():
    # 证明上面的检查会抓住未定义名称，而不是因为当前恰好没有缺 import 的文件
    found = _undefined_names("import time\nprint(time.time(), missing_name)\n", "probe.py")
    assert any("undefined name 'missing_name'" in line for line in found), found
