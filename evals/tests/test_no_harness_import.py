"""The eval tooling must not import the harness package.

It observes Yudao only through public interfaces, so the same tooling can score
different Yudao versions. This test reads every eval Python file and fails if a
top-level import names `harness`.
"""

import ast
import os

EVALS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _python_files():
    for root, _dirs, files in os.walk(EVALS_DIR):
        if "__pycache__" in root or ".pytest_cache" in root:
            continue
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(root, name)


def _imported_roots(path):
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_eval_files_do_not_import_harness():
    offenders = []
    for path in _python_files():
        if "harness" in _imported_roots(path):
            offenders.append(os.path.relpath(path, EVALS_DIR))
    assert offenders == []
