import ast
import re
from pathlib import Path

import harness

# 所有写入都经过写入口：事件日志只有两个写入函数（EventStore.commit 追加事件并保存投影，
# EventStore.replace_projection 用重放的结果替换保存的投影），只由写入口（write_path.py）调用；
# 只有事件日志（event_store.py）打开数据库、写日志的表。按源码检查控制核心之外的全部模块。
#
# 例外：应用层保存的读取模型（app/read_models.py，设计说明第 4.2 节）有自己的、可以删除后重建的数据库；
# 它不写事件日志的 events、projections、commands 三张表，也不作为事件的读取来源。架构问题已登记，等待架构师确认。

_STORE_WRITES = {"commit", "replace_projection"}
_TABLE_WRITE = re.compile(r"\b(INSERT INTO|UPDATE|DELETE FROM|REPLACE INTO)\s+(events|projections|commands)\b")
_OWN_DATABASE = {"read_models.py"}


def _modules():
    root = Path(harness.__file__).parent
    return [path for path in root.rglob("*.py") if "tests" not in path.relative_to(root).parts]


def test_only_the_write_path_calls_the_event_log_write_functions():
    callers = []
    for path in _modules():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in _STORE_WRITES):
                callers.append((path.name, node.lineno, node.func.attr))
    assert callers and {name for name, _line, _attr in callers} == {"write_path.py"}, callers


def test_only_the_event_log_opens_the_database_and_writes_its_tables():
    offenders = []
    for path in _modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported = (isinstance(node, ast.Import) and any(alias.name == "sqlite3" for alias in node.names)) or (
                isinstance(node, ast.ImportFrom) and node.module == "sqlite3")
            writes_table = (isinstance(node, ast.Constant) and isinstance(node.value, str)
                            and _TABLE_WRITE.search(node.value) is not None)
            if (imported or writes_table) and path.name not in {"event_store.py", *_OWN_DATABASE}:
                offenders.append((path.name, node.lineno))
    assert offenders == []
