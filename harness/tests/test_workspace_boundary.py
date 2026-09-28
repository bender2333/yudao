import ast
from pathlib import Path

import harness

# 控制核心不直接读写工作区文件：工作区从封存快照建立、事实查询与交付封存都经过执行环境
# （environment.py 的 LocalEnvironment）。这里按源码检查控制核心的模块。

_CONTROL_CORE = {
    "orchestrator.py",   # 流程编排
    "engine.py",         # 步骤驱动
    "recording.py",      # 记录接口
    "assembly.py", "context.py", "compaction.py",   # 上下文装配 P
    "adjudication.py", "validation.py",             # 裁决规则 U
    "submissions.py", "interactions.py",            # 提交与交互的写入
}
# 直接读写工作区文件的公开树操作；只有执行环境与工件、快照模块可以调用
_TREE_IO = {"capture_public_tree", "materialize_tree", "verify_public_tree"}


def _modules():
    root = Path(harness.__file__).parent
    return [path for path in root.rglob("*.py") if "tests" not in path.relative_to(root).parts]


def test_control_core_does_not_read_or_write_workspace_files():
    root = Path(harness.__file__).parent
    seen = set()
    offenders = []
    for path in _modules():
        relative = path.relative_to(root).as_posix()
        if relative not in _CONTROL_CORE:
            continue
        seen.add(relative)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module == "workspace":
                offenders += [(relative, node.lineno, alias.name)
                              for alias in node.names if alias.name == "Workspace"]
            elif isinstance(node, ast.Name) and node.id == "Workspace":
                offenders.append((relative, node.lineno, "Workspace"))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _TREE_IO:
                offenders.append((relative, node.lineno, node.func.id))
    assert seen == _CONTROL_CORE, seen
    assert offenders == []
