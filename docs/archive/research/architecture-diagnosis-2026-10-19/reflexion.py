"""反射模型：总体架构说明第 2、5、6.1 节写的「模块→层」与 harness/ 实际导入逐条比对。

用法（仓库根）：uv run python docs/research/architecture-diagnosis-2026-10-19/reflexion.py
只读源码，不导入 harness。输出：每条模块之间的依赖归为 一致 / 多出，文档写了但代码里没有的归为 缺失，
以及文档没有给出层的模块（未归属）。
"""
import ast
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
HARNESS = ROOT / "harness"

# 设计第 6.1 节与内核清单给出代码位置的模块；层号越小越底层（第 5 节依赖方向）
KERNEL = {m["path"] for m in json.loads((HARNESS / "definitions/kernel-manifest.json").read_text("utf-8"))["paths"]
          if m["kind"] == "module"}
KERNEL_MODULES = {p.removeprefix("harness/").removesuffix(".py").replace("/__init__", "").replace("/", ".")
                  for p in KERNEL}
LAYER = {"definitions": ("定义", 0)}
LAYER.update({m: ("可信内核", 1) for m in KERNEL_MODULES if m != "definitions"})
LAYER.update({m: ("P 上下文装配", 3) for m in ("assembly", "context", "compaction")})
LAYER.update({m: ("步骤驱动", 4) for m in ("engine", "recording")})
LAYER.update({"orchestrator": ("流程编排", 5)})
LAYER.update({"environment": ("执行层", 2), "providers": ("执行层", 2)})
LAYER.update({"app": ("应用层", 6), "api": ("接口层", 7), "__main__": ("界面与命令行", 8)})
# 文档写明应当存在的依赖（第 5、6.1 节）
EXPECTED = [("orchestrator", "engine", "流程编排调用步骤驱动"),
            ("engine", "assembly", "步骤驱动经 P 取得请求"),
            ("engine", "adjudication", "步骤驱动经 U 取得裁决"),
            ("orchestrator", "write_path", "所有写入只经过写入口"),
            ("engine", "write_path", "所有写入只经过写入口"),
            ("app", "orchestrator", "应用层的修改只经过控制核心"),
            ("api", "app", "接口层只调用应用层"),
            ("orchestrator", "environment", "控制核心经合同调用执行层"),
            ("engine", "providers", "步骤驱动的模型调用在执行层")]


def top(name):
    return name.split(".", 1)[0]


def owner(path):
    rel = path.relative_to(HARNESS).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def imports(path):
    tree = ast.parse(path.read_text("utf-8"), str(path))
    pkg = owner(path).split(".")
    if path.name != "__init__.py":
        pkg = pkg[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("harness."):
                    yield alias.name.removeprefix("harness.")
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg[:len(pkg) - node.level + 1] if node.level > 1 else pkg
                mod = ".".join(base + ([node.module] if node.module else []))
            elif node.module and (node.module == "harness" or node.module.startswith("harness.")):
                mod = node.module.removeprefix("harness").lstrip(".")
            else:
                continue
            if mod:
                yield mod
            else:
                for alias in node.names:
                    yield alias.name


def layer_of(module):
    if module in LAYER:
        return LAYER[module]
    return LAYER.get(top(module))


def main():
    edges = {}
    lines = {}
    for path in sorted(HARNESS.rglob("*.py")):
        if "tests" in path.relative_to(HARNESS).parts or "__pycache__" in path.parts:
            continue
        src = owner(path)
        if not src:
            continue  # harness/__init__.py
        unit = src if src in LAYER else top(src)
        lines[unit] = lines.get(unit, 0) + len(path.read_text("utf-8").splitlines())
        for target in imports(path):
            dst = target if target in LAYER else top(target)
            if dst != unit:
                edges.setdefault((unit, dst), set()).add(str(path.relative_to(ROOT)).replace("\\", "/"))
    rows = {"一致": [], "多出": [], "未归属": []}
    for (src, dst), files in sorted(edges.items()):
        a, b = layer_of(src), layer_of(dst)
        if a is None or b is None:
            rows["未归属"].append((src, dst, a and a[0], b and b[0], len(files)))
            continue
        kernel_rule = a[1] == 1 and b[1] != 1 and b[0] != "定义"
        upward = b[1] > a[1]
        exec_into_core = a[0] == "执行层" and b[1] >= 3
        verdict = "多出" if (kernel_rule or upward or exec_into_core) else "一致"
        rows[verdict].append((src, dst, a[0], b[0], len(files)))
    missing = [(s, d, why) for s, d, why in EXPECTED if (s, d) not in edges]
    unowned = sorted({u for u in lines if layer_of(u) is None})
    print("## 多出（违反第 5 节依赖方向或内核只导入内核）")
    for r in rows["多出"]:
        print("- %s -> %s（%s -> %s，%d 个文件）" % r)
    print("\n## 缺失（文档写了、代码里没有）")
    for r in missing:
        print("- %s -> %s：%s" % r)
    print("\n## 一致：%d 条" % len(rows["一致"]))
    print("\n## 未归属的模块（文档第 2、6.1 节没有给出层）：%d 个，共 %d 行" % (
        len(unowned), sum(lines[u] for u in unowned)))
    for u in sorted(unowned, key=lambda u: -lines[u]):
        fan_in = sum(1 for (s, d) in edges if d == u)
        print("- %s：%d 行，被 %d 个模块导入" % (u, lines[u], fan_in))
    owned = sorted({u for u in lines if layer_of(u) is not None}, key=lambda u: -lines[u])
    print("\n## 已归属：%d 个，共 %d 行" % (len(owned), sum(lines[u] for u in owned)))
    involving = [r for r in rows["未归属"]]
    print("\n## 涉及未归属模块的依赖：%d 条（无法判定方向）" % len(involving))
    if "-v" in sys.argv:
        for r in involving:
            print("- %s -> %s（%s -> %s，%d）" % r)


if __name__ == "__main__":
    main()
