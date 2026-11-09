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
# 薄驱动只读最小投影（工单 #1678，骨架与应用 docs/design/skeleton-and-application.md「薄驱动」第 1 条、
# 「最小投影」）：运行视图里的字段不在最小投影里，要读它们的判断归路由实现或钩子；薄驱动问钩子要答案，
# 从钩子拿到的运行视图只原样交回钩子或路由。这个文件的后半段用 ast 查薄驱动没有读运行视图的字段：
# 字段名从 harness/models.py 的 RunProjection 取，运行视图对象的来路是钩子返回的（project、run_view、
# settled、assign_new_inputs、read_run）与事务、快照上的 `.projection`。检查本身也证明会失败：给一段故意写
# `projection.cycle_count` 的源码，检查报出它；给一段只读最小投影、钩子的答案与契约类型的源码，检查通过。
#
# 守 R1（测试分层 docs/design/test-pyramid.md「测试按三环留」）：只由你批准的一环的不变式——薄驱动只经内核与契约连接。

from __future__ import annotations

import ast
import dataclasses
import json
import sys
from pathlib import Path

from harness.models import RunProjection

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


# 薄驱动不读运行视图的字段（工单 #1678） ----------------------------------------------------

# 运行视图的字段：以 harness/models.py 的 RunProjection 为准，不从别处另抄一份
PROJECTION_FIELDS = frozenset(item.name for item in dataclasses.fields(RunProjection))

# 薄驱动里表示运行视图的变量名：从钩子或 `.projection` 赋值的变量按赋值追下去，这几个是按名字认的
DEFAULT_VIEW_NAMES = frozenset({"projection", "current", "view", "run_view"})


# 交回运行视图的钩子：project、run_view、settled、assign_new_inputs 直接交回运行视图；
# read_run 交回的是写入口的快照，快照上的 `.projection` 另有一条检查。
# settled 实际经 `asyncio.to_thread` 调用，方法本身作为值传出去，不写成一次直接调用
VIEW_HOOKS = frozenset({"project", "read_run", "run_view", "settled", "assign_new_inputs"})


def _hook_reference(node: ast.AST) -> bool:
    # 钩子方法本身作为值传出去（`asyncio.to_thread(self._hooks.settled, run_id)` 这样调用）
    return isinstance(node, ast.Attribute) and node.attr in VIEW_HOOKS


def _hook_returns_a_view(node: ast.AST) -> bool:
    if isinstance(node, ast.Await):
        return _hook_returns_a_view(node.value)
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Attribute) and node.func.attr in VIEW_HOOKS:
        return True
    # 经 asyncio.to_thread 之类转调的钩子：返回值仍是运行视图
    return any(_hook_reference(argument) for argument in node.args)


def _is_view_expression(node: ast.AST | None, names: set[str]) -> bool:
    # 这个表达式是运行视图：按名字认的变量、`.projection`、钩子的返回值，或钩子方法本身
    if node is None:
        return False
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, ast.Attribute):
        return node.attr == "projection" or _hook_reference(node)
    return _hook_returns_a_view(node)


def _view_names(tree: ast.AST) -> set[str]:
    # 源码里表示运行视图的变量名：按赋值一路追下去（`view = current` 也算）
    names = set(DEFAULT_VIEW_NAMES)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue
            if not _is_view_expression(value, names):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in names:
                    names.add(target.id)
                    changed = True
    return names


def projection_reads(source: str, file: str) -> list[str]:
    """这份源码里读运行视图的地方，逐条写出文件、行与读法。

    `.projection` 直接取运行视图本身也算一条：薄驱动只把它原样交回钩子或路由。
    """
    tree = ast.parse(source)
    names = _view_names(tree)
    found: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if node.attr == "projection":
            found.add((node.lineno, ".projection（运行视图只原样转交，不在薄驱动里取）"))
        elif node.attr in PROJECTION_FIELDS and _is_view_expression(node.value, names):
            found.add((node.lineno, ast.unparse(node)))
    return [f"{file}:{line}: {text}" for line, text in sorted(found)]


def test_the_thin_driver_reads_only_the_minimal_projection():
    # 验收第 1 条：薄驱动自己只读最小投影，运行视图的字段一个也不读（工单 #1678）
    found = projection_reads(_read(THIN_DRIVER), THIN_DRIVER)
    assert found == [], (
        "薄驱动读了运行视图的字段：薄驱动自己只读最小投影，要读运行视图的判断归路由实现或钩子，"
        "薄驱动问钩子要答案（docs/design/skeleton-and-application.md「薄驱动」第 1 条）：\n"
        + "\n".join(found))


def test_the_checked_field_names_come_from_the_run_projection():
    # 检查的对象不是空的：工单点到的字段都在 RunProjection 里（改名或搬走时这条先失败）
    for name in ("status", "cycle_count", "input_version", "active_department", "provider", "model",
                 "token_used", "max_cycles", "stream_version"):
        assert name in PROJECTION_FIELDS, f"RunProjection 里没有 {name}，检查的对象变了"


def test_a_projection_field_read_is_reported_with_the_line():
    # 验收第 1 条后半：故意在薄驱动里加一处 `projection.cycle_count` 时检查失败，并写出行号
    probe = (
        "def begin_round(transaction):\n"
        "    projection = transaction.projection\n"
        "    return projection.cycle_count + 1\n"
    )
    assert projection_reads(probe, THIN_DRIVER) == [
        "harness/thin_driver.py:2: .projection（运行视图只原样转交，不在薄驱动里取）",
        "harness/thin_driver.py:3: projection.cycle_count",
    ]


def test_a_run_view_returned_by_a_hook_is_tracked_the_same_way():
    # 从钩子拿到的运行视图也照这条查：变量追到钩子的返回值上
    probe = (
        "def judge(self, run_id):\n"
        "    view = self._hooks.project(run_id)\n"
        "    if view.status == 'failed':\n"
        "        return view.stop_reason\n"
        "    return None\n"
    )
    assert projection_reads(probe, THIN_DRIVER) == [
        "harness/thin_driver.py:3: view.status",
        "harness/thin_driver.py:4: view.stop_reason",
    ]


def test_every_hook_that_answers_with_the_run_view_is_tracked():
    # run_view、settled 与 assign_new_inputs 也交回运行视图：原样传出去不算读，改名以后取字段或就地取字段都算
    # （独立审查发现 run_view 漏在检查外，工单 #1678）
    probe = (
        "def end(transaction, run_id):\n"
        "    current = self._hooks.run_view(transaction)\n"
        "    if current.status == 'failed':\n"
        "        return current.cycle_count\n"
        "    if self._hooks.settled(run_id).provider == 'fake':\n"
        "        return self._hooks.assign_new_inputs(transaction).stop_reason\n"
        "    return None\n"
    )
    assert projection_reads(probe, THIN_DRIVER) == [
        "harness/thin_driver.py:3: current.status",
        "harness/thin_driver.py:4: current.cycle_count",
        "harness/thin_driver.py:5: self._hooks.settled(run_id).provider",
        "harness/thin_driver.py:6: self._hooks.assign_new_inputs(transaction).stop_reason",
    ]


def test_a_view_hook_run_in_a_thread_is_tracked_too():
    # settled 实际写成 `asyncio.to_thread(self._hooks.settled, run_id)`：方法作为值传出去，
    # 交回的值仍是运行视图，改名以后取字段照样报（独立审查指出这条写法，工单 #1678）
    probe = (
        "async def end(self, run_id):\n"
        "    settled = await asyncio.to_thread(self._hooks.settled, run_id)\n"
        "    return settled.status\n"
    )
    assert projection_reads(probe, THIN_DRIVER) == ["harness/thin_driver.py:3: settled.status"]


def test_passing_the_run_view_to_a_hook_or_the_routing_is_allowed():
    # 允许的范围也守：钩子交回的运行视图原样传给路由，不算薄驱动读它
    probe = (
        "def end(self, transaction, run_id):\n"
        "    return self._hooks.routing(run_id).item_end(self._hooks.run_view(transaction))\n"
    )
    assert projection_reads(probe, THIN_DRIVER) == []


def test_the_minimal_projection_the_hook_answers_and_contract_types_are_allowed():
    # 允许的范围也守：最小投影、钩子的答案与契约类型上的字段不报
    probe = (
        "def end(transaction, fields, prepared, scope):\n"
        "    minimal = transaction.minimal()\n"
        "    if minimal.status in TERMINAL_STATUSES:\n"
        "        return fields.provider, fields.cycle_count, prepared.provider, scope.provider\n"
        "    return minimal.used.activations\n"
    )
    assert projection_reads(probe, THIN_DRIVER) == []
