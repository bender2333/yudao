"""分层规则的事实（方案第 3.1、8 节，第 11 节第 1 步）：内核模块里点名下层实例的字符串常量。

事实只从正本读：`harness/definitions/kernel-manifest.json` 的内核模块、`organization.json` 的部门，
代码用 ast 现算。也查内核代码有没有点名脚手架的实例（方案第 10.1 节：共用概念，不共用实例）。
这是字符串级的近似：只认整个字符串常量等于实例名的地方。
"""

import ast
import json
from pathlib import Path

from ..scaffold import sym

DEPARTMENT = "部门"


def _scopes(tree):
    """每个节点 -> 所在函数或类的限定名，模块顶层是「<模块>」。"""
    out = {}

    def walk(node, scope):
        for child in ast.iter_child_nodes(node):
            s = scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                s = f"{scope}.{child.name}" if scope != "<模块>" else child.name
            out[id(child)] = s
            walk(child, s)

    walk(tree, "<模块>")
    return out


def mentions(source, names):
    """源码里等于 names 之一的字符串常量：(行, 值, 所在函数)。"""
    tree = ast.parse(source)
    scopes = _scopes(tree)
    hits = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in names:
            hits.append((n.lineno, n.value, scopes.get(id(n), "<模块>")))
    return sorted(hits)


def layering_facts(root, scaffold_names=()):
    root = Path(root)
    manifest = json.loads((root / "harness/definitions/kernel-manifest.json").read_text(encoding="utf-8"))
    org = json.loads((root / "harness/definitions/organization.json").read_text(encoding="utf-8"))
    depts = [d["id"] for d in org["departments"]]
    syms = {sym("kind", DEPARTMENT, "organization")}
    for d in depts:
        syms.add(sym("instance_of", d, DEPARTMENT))
    names = set(depts) | set(scaffold_names)
    for p in manifest["paths"]:
        if p["kind"] != "module":
            continue
        path = p["path"]
        syms.add(sym("module_layer", path, "kernel"))
        source = (root / path).read_text(encoding="utf-8")
        for line, value, scope in mentions(source, names):
            syms.add(sym("code_mentions", path, line, value, scope))
    return syms
