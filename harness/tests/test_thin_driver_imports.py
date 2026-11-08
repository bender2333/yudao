# 薄驱动的导入只有内核模块、契约模块、标准库与 pydantic（骨架与应用 docs/design/skeleton-and-application.md「薄驱动」与
# 「可信内核」；总图第二节四层；工单 #1512）。
#
# 薄驱动把路由、边界、执行、写入口与最小投影连接起来，不导入应用：应用一侧的流程编排经钩子协议接在它上面。
# 允许的导入分三类：
# - 内核清单里 kind 为 module 的文件（harness/definitions/kernel-manifest.json）；
# - 契约圈的五个模块（三道槽位契约、收紧检查契约与契约版本），它们与内核模块同一条规矩；
# - 标准库与 pydantic。
# 其余任何导入（例如运行流的投影 projection、执行环境 environment、路由实现 watched_outputs）都失败，
# 失败说明写出文件、行号与导入的模块，以及它在仓库里的位置。
#
# 用例同时证明这项检查会失败：给一段故意写了 projection 导入的源码，检查报出它；再给一段只导入内核、
# 契约、标准库与 pydantic 的源码，检查通过。检查用 ast 读静态文件，不执行被检查的代码，
# 不开数据库、不用子进程与网络，属于单元层。
#
# 守 R1（测试分层 docs/design/test-pyramid.md「测试按三环留」）：只由你批准的一环的不变式——薄驱动只经内核与契约连接。

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
THIN_DRIVER = "harness/thin_driver.py"
MANIFEST = REPO_ROOT / "harness" / "definitions" / "kernel-manifest.json"

# 契约圈的五个模块（与 harness/tests/test_thin_driver_names.py 的清单一致）
CONTRACT_MODULES = (
    "harness/assembly_contract.py",
    "harness/execution_contract.py",
    "harness/routing_contract.py",
    "harness/tightening_contract.py",
    "harness/contract_versions.py",
)


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def kernel_modules() -> set[str]:
    # 内核清单里 kind 为 module 的文件：薄驱动可以导入它们
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {entry["path"] for entry in manifest["paths"] if entry["kind"] == "module"}


def allowed_modules() -> set[str]:
    return kernel_modules() | set(CONTRACT_MODULES)


def _package_of(relative: str) -> str:
    # 这个源文件所在的包：薄驱动在 harness/ 顶层，包名是 harness
    stem = relative[len("harness/"):]
    if stem.endswith("/__init__.py"):
        return "harness." + stem[: -len("/__init__.py")].replace("/", ".")
    parent = Path(stem).parent.as_posix()
    return "harness" if parent == "." else "harness." + parent.replace("/", ".")


def _resolve(module: str) -> str | None:
    # 仓库里这个模块的位置；仓库里没有这个模块时为空
    relative = module[len("harness."):] if module.startswith("harness.") else module
    for candidate in (relative + ".py", relative + "/__init__.py"):
        path = "harness/" + candidate
        if (REPO_ROOT / path).exists():
            return path
    return None


def imported_modules(source: str, relative: str) -> list[tuple[int, str]]:
    # 一段源码里的导入语句按模块名给出，不执行任何代码；相对导入按文件所在的包展开
    package = _package_of(relative)
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                up = node.level - 1
                base = ".".join(parts[: len(parts) - up]) if up else parts[0]
                if node.module:
                    found.append((node.lineno, f"{base}.{node.module}"))
                else:
                    found.extend((node.lineno, f"{base}.{alias.name}") for alias in node.names)
            else:
                found.append((node.lineno, node.module or ""))
    return found


def foreign_imports(source: str, relative: str) -> list[str]:
    """这份源码里不在允许范围内的导入，逐条写成一行。

    允许的是内核模块、契约模块、标准库与 pydantic；模块名以 harness 开头时按仓库里的位置判定，
    仓库里没有这个模块也算一条。
    """
    allowed = allowed_modules()
    found: list[str] = []
    for line, module in imported_modules(source, relative):
        top = module.split(".")[0]
        if top == "harness":
            resolved = _resolve(module)
            if resolved is None:
                found.append(f"{relative}:{line}: {module}（仓库里没有这个模块）")
            elif resolved not in allowed:
                found.append(f"{relative}:{line}: {module} → {resolved}")
        elif top not in sys.stdlib_module_names and top != "pydantic":
            found.append(f"{relative}:{line}: {module}（不是内核模块、契约模块、标准库或 pydantic）")
    return found


def test_the_thin_driver_imports_only_kernel_modules_contract_modules_the_standard_library_and_pydantic():
    found = foreign_imports(_read(THIN_DRIVER), THIN_DRIVER)
    assert found == [], (
        "薄驱动导入了不允许的模块。应用一侧的流程编排经钩子协议接在薄驱动上，薄驱动不导入应用"
        "（骨架与应用 docs/design/skeleton-and-application.md「薄驱动」）：\n" + "\n".join(found))


def test_the_import_check_reads_kernel_and_contract_modules_in_the_thin_driver():
    # 检查本身要能作用在真实的导入上：薄驱动确实导入了内核模块与契约模块，不是因为没有导入而通过
    imported = {_resolve(module) for _line, module in imported_modules(_read(THIN_DRIVER), THIN_DRIVER)}
    assert imported & kernel_modules(), "薄驱动没有导入任何内核模块，这项检查失去了对象"
    assert imported & set(CONTRACT_MODULES), "薄驱动没有导入任何契约模块，这项检查失去了对象"


def test_a_projection_import_is_reported_with_the_file_the_line_and_the_module():
    # 故意加一个 projection 的导入时用例失败（验收第 1 条）：同一段检查报出文件、行号与模块
    probe = "from . import projection\nfrom .projection import RunProjection\nimport harness.projection\n"
    found = foreign_imports(probe, "harness/thin_driver.py")
    assert found == [
        "harness/thin_driver.py:1: harness.projection → harness/projection.py",
        "harness/thin_driver.py:2: harness.projection → harness/projection.py",
        "harness/thin_driver.py:3: harness.projection → harness/projection.py",
    ], found


def test_kernel_contract_standard_library_and_pydantic_imports_pass():
    # 允许的范围也守：内核模块、契约模块、标准库与 pydantic 的导入不报
    probe = (
        "from __future__ import annotations\n"
        "import asyncio\n"
        "from collections.abc import Callable\n"
        "from pydantic import BaseModel\n"
        "from . import execution_contract\n"
        "from .write_path import Transaction\n"
    )
    assert foreign_imports(probe, "harness/thin_driver.py") == []


def test_the_allowed_module_list_is_not_empty_and_lists_existing_files():
    # 允许清单来自内核清单与契约清单：两张清单都要有内容，契约模块都在仓库里（清单写错时这条失败）
    assert kernel_modules(), "内核清单里没有 kind 为 module 的文件"
    assert len(CONTRACT_MODULES) == 5
    missing = [name for name in CONTRACT_MODULES if not (REPO_ROOT / name).is_file()]
    assert missing == [], "契约模块清单里有不存在的文件：" + "、".join(missing)
