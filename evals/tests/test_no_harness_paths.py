"""评测工具不得引用被测方内部文件的路径。

`test_no_harness_import.py` 检查顶层 import；本测试检查源码里的路径字面量。
纯文本匹配会被字符串拼接（`"rules." + "json"`）或 `os.path.join` 拆散绕过，
因此用 `ast` 扫描全部字符串常量，并折叠相邻字符串拼接与 `os.path.join` 的
字面量参数，再用折叠后的值比对。本文件自身不参与目录扫描（`__file__` 跳过），
正例夹具只放在测试函数内的字符串里，不写成真实源文件。
"""

import ast
import os

EVALS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BANNED = ("harness/definitions", "definitions/rules.json", "rules.json")


def _fold(node):
    """折叠字符串表达式：常量、相邻 `+` 拼接、`os.path.join` 字面量参数。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _fold(node.left)
        right = _fold(node.right)
        if isinstance(left, str) and isinstance(right, str):
            return left + right
        return None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "join" and not node.keywords:
        parts = [_fold(arg) for arg in node.args]
        if parts and all(isinstance(part, str) for part in parts):
            return "/".join(parts)
        return None
    return None


def _folded_strings(tree):
    """收集语法树里全部字符串：每个常量原文，外加折叠后的拼接与 join 结果。"""
    values = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            values.append(node.value)
        elif isinstance(node, (ast.BinOp, ast.Call)):
            folded = _fold(node)
            if isinstance(folded, str):
                values.append(folded)
    return values


def _offenders_in_strings(strings):
    offenders = []
    for value in strings:
        for token in BANNED:
            if token in value:
                offenders.append("%r contains %r" % (value, token))
    return offenders


def _python_files():
    for root, _dirs, files in os.walk(EVALS_DIR):
        if "__pycache__" in root or ".pytest_cache" in root:
            continue
        for name in files:
            if name.endswith(".py"):
                path = os.path.join(root, name)
                if os.path.abspath(path) == os.path.abspath(__file__):
                    continue
                yield path


def test_eval_files_do_not_reference_internal_parameter_files():
    offenders = []
    for path in _python_files():
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        for offender in _offenders_in_strings(_folded_strings(tree)):
            offenders.append("%s: %s" % (os.path.relpath(path, EVALS_DIR), offender))
    assert offenders == []


def test_bypass_attempts_are_caught():
    bypasses = [
        'path = "rules." + "json"',
        'path = "definitions/" + "rules.json"',
        'path = os.path.join("definitions", "rules.json")',
        'path = os.path.join("harness", "definitions")',
        'path = "harness" + "/" + "definitions"',
        'path = "harness/definitions"',
    ]
    for source in bypasses:
        strings = _folded_strings(ast.parse(source))
        assert _offenders_in_strings(strings) != [], source
    innocent = _folded_strings(ast.parse('args = ["-m", "harness", "api"]'))
    assert _offenders_in_strings(innocent) == []
