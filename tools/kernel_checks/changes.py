# 改动识别（docs/design/kernel-quality-gate.md「改到的语句与函数」）：当前提交与相对 main 的
# 合并基点相比，按语法树找出内容有变的语句（新增或改写）与改到的函数（函数体里有语句新增、改写或
# 删除；类里的方法按单独的函数算）。注释、空行与排版的改动不进语法树，因此不算改动。
#
# 一条语句的「内容」指它自己的部分：复合语句（if、for、try 等）只比头部与其中的表达式，子语句
# 各自再比。改 if 的分支条件报 if 这一条，改它里面的一条语句报那一条，两层都改了报两条。
#
# 工具只读文件、起进程（git），不导入 harness/ 里的代码。

from __future__ import annotations

import ast
import difflib
import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(Exception):
    """git 命令失败：合并基点不存在、改动或文件内容读不出来。"""


@dataclass(frozen=True)
class StatementChange:
    lineno: int
    text: str


@dataclass(frozen=True)
class FunctionChange:
    name: str  # 模块级函数是函数名，方法写成 Class.method，嵌套类写成 Outer.Inner.method
    node: ast.FunctionDef | ast.AsyncFunctionDef
    statements: tuple[StatementChange, ...]  # 新增或改写的语句（新版本里的文字）
    removed: int  # 删掉的语句条数
    is_new: bool  # 合并基点里没有这个函数，整段都是新增


@dataclass(frozen=True)
class FileChanges:
    functions: tuple[FunctionChange, ...]
    removed_functions: tuple[str, ...]  # 新版本里没有了的函数

    @property
    def changed(self) -> bool:
        return bool(self.functions or self.removed_functions)


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=root,
        capture_output=True,
        check=False,
    )


def merge_base(root: Path, base: str) -> str:
    done = _run(root, "merge-base", base, "HEAD")
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", "replace").strip() or done.stdout.decode("utf-8", "replace").strip()
        raise GitError(f"合并基点不存在：{base}（git merge-base {base} HEAD 失败：{detail}）")
    merge_base_commit = done.stdout.decode("utf-8", "replace").strip()
    if not merge_base_commit:
        raise GitError(f"合并基点不存在：{base}（git merge-base {base} HEAD 没有给出提交）")
    return merge_base_commit


def changed_python_files(root: Path, from_commit: str, to_commit: str = "HEAD") -> tuple[tuple[str, str], ...]:
    # 返回 (仓库内相对路径, 状态字母)：A 新增、M 改动、D 删除、T 类型变化。改名按删除加新增算
    done = _run(
        root,
        "diff",
        "--name-status",
        "--no-renames",
        "--diff-filter=ACDMT",
        from_commit,
        to_commit,
        "--",
        "*.py",
    )
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", "replace").strip()
        raise GitError(f"读不了 {from_commit}..{to_commit} 的改动：{detail}")
    rows: list[tuple[str, str]] = []
    for line in done.stdout.decode("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        status, path = line.split("\t", 1)
        rows.append((path, status[:1]))
    return tuple(rows)


def show(root: Path, commit: str, path: str) -> str | None:
    # 这个提交里这个文件的内容；文件不在这个提交里时返回 None
    done = _run(root, "show", f"{commit}:{path}")
    if done.returncode != 0:
        return None
    return done.stdout.decode("utf-8")


def detect(old_source: str | None, new_source: str) -> FileChanges:
    # old_source 为 None 表示文件是新增的
    new_functions = _functions(ast.parse(new_source))
    old_functions = _functions(ast.parse(old_source)) if old_source is not None else {}
    changes: list[FunctionChange] = []
    for name, node in new_functions.items():
        old_node = old_functions.get(name)
        if old_node is None:
            statements = tuple(StatementChange(lineno=stmt.lineno, text=_text(new_source, stmt)) for stmt in _statements(node))
            changes.append(FunctionChange(name=name, node=node, statements=statements, removed=0, is_new=True))
            continue
        added, removed = _diff_statements(old_node, node, new_source)
        if added or removed:
            changes.append(FunctionChange(name=name, node=node, statements=tuple(added), removed=removed, is_new=False))
    removed_functions = tuple(name for name in old_functions if name not in new_functions)
    return FileChanges(functions=tuple(changes), removed_functions=removed_functions)


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    # 模块级函数与方法各是一个单元；函数里的嵌套函数归在它所在的函数里，不单独算
    found: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}

    def walk(body: list[ast.stmt], prefix: str) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found[prefix + node.name] = node
            elif isinstance(node, ast.ClassDef):
                walk(node.body, prefix + node.name + ".")
            else:
                for nested in _nested_statement_lists(node):
                    walk(nested, prefix)

    walk(tree.body, "")
    return found


def _statements(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    # 函数体里的全部语句，外层在前、子语句按源码顺序跟在后面
    collected: list[ast.stmt] = []

    def walk(body: list[ast.stmt]) -> None:
        for stmt in body:
            collected.append(stmt)
            for nested in _nested_statement_lists(stmt):
                walk(nested)

    walk(function.body)
    return collected


def _nested_statement_lists(node: ast.AST) -> list[list[ast.stmt]]:
    # 这个节点里直接属于它的语句列表：if 的两个分支、循环的体、try 的各个部分、except 的体等
    lists: list[list[ast.stmt]] = []
    for _name, value in ast.iter_fields(node):
        lists.extend(_statement_lists(value))
    return lists


def _statement_lists(value: object) -> list[list[ast.stmt]]:
    if isinstance(value, ast.stmt):
        return [[value]]
    if isinstance(value, list):
        direct = [item for item in value if isinstance(item, ast.stmt)]
        if direct:
            return [direct]
        found: list[list[ast.stmt]] = []
        for item in value:
            if isinstance(item, ast.AST) and not isinstance(item, ast.stmt):
                found.extend(_statement_lists(item))
        return found
    if isinstance(value, ast.AST) and not isinstance(value, ast.stmt):
        found = []
        for _name, field in ast.iter_fields(value):
            found.extend(_statement_lists(field))
        return found
    return []


def _own_shape(stmt: ast.stmt) -> str:
    # 一条语句自己的内容：它的字段里出现语句的地方换成占位符，子语句各自再比
    fields = ",".join(f"{name}={_shape(value)}" for name, value in ast.iter_fields(stmt))
    return f"{type(stmt).__name__}({fields})"


def _shape(value: object) -> str:
    if isinstance(value, ast.stmt):
        return "<stmt>"
    if isinstance(value, ast.AST):
        fields = ",".join(f"{name}={_shape(child)}" for name, child in ast.iter_fields(value))
        return f"{type(value).__name__}({fields})"
    if isinstance(value, list):
        return "[" + ",".join(_shape(item) for item in value) + "]"
    return repr(value)


def _diff_statements(
    old_node: ast.FunctionDef | ast.AsyncFunctionDef,
    new_node: ast.FunctionDef | ast.AsyncFunctionDef,
    new_source: str,
) -> tuple[list[StatementChange], int]:
    old_shapes = [_own_shape(stmt) for stmt in _statements(old_node)]
    new_statements = _statements(new_node)
    new_shapes = [_own_shape(stmt) for stmt in new_statements]
    matcher = difflib.SequenceMatcher(a=old_shapes, b=new_shapes, autojunk=False)
    added: list[StatementChange] = []
    removed = 0
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag in ("replace", "insert"):
            added.extend(
                StatementChange(lineno=stmt.lineno, text=_text(new_source, stmt))
                for stmt in new_statements[new_start:new_end]
            )
        if tag == "delete":
            # 改写按新增算（新版本的文字在 added 里），只有删掉的语句记进 removed
            removed += old_end - old_start
    return added, removed


def _text(source: str, stmt: ast.stmt) -> str:
    segment = ast.get_source_segment(source, stmt)
    return segment if segment is not None else ast.unparse(stmt)
