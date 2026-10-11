"""评测工具不得引用被测方内部文件的路径。

`test_no_harness_import.py` 检查顶层 import；本测试检查源码里的路径字面量。判定规则：
把被测方内部文件路径按「被测方名 + definitions + 文件名」的部件分别比对，
命中任何部件的组合即算违规；本文件自身的部件表经由 `str.__add__` 拼接，
不会出现在扫描文本里。
"""

import os

EVALS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_PARAMETER_FILE = "rule" + "s.json"
_SUBJECT = "harness"
_SETTINGS_FOLDER = "definitions"
BANNED = (_SUBJECT + "/" + _SETTINGS_FOLDER,
          _SETTINGS_FOLDER + "/" + _PARAMETER_FILE,
          _PARAMETER_FILE)


def _python_files():
    for root, _dirs, files in os.walk(EVALS_DIR):
        if "__pycache__" in root or ".pytest_cache" in root:
            continue
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(root, name)


def test_eval_files_do_not_reference_internal_parameter_files():
    offenders = []
    for path in _python_files():
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        for token in BANNED:
            if token in text:
                offenders.append("%s: %s" % (os.path.relpath(path, EVALS_DIR), token))
    assert offenders == []
