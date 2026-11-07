# 变异检查（docs/design/kernel-quality-gate.md「变异检查」「存活的出口与理由登记」「全量模式与「立住」」）：
# 在改到的、已覆盖的语句上用 poodle 生成变异，按两层判定（快层、慢层）运行直接执行到被改模块的
# 内核测试；超时的变异单列、重跑一次仍超时算被杀死；存活的变异先查理由登记，命中且理由成立的
# 单列、不算不通过，其余不通过，对不上任何存活变异的登记项算过期。
#
# poodle 只在生成变异时使用：它按语法树给出改动位置与替换文字，工具自己应用、筛选与运行。
# 判断只用内核目录的测试（harness/tests/kernel），不借别处的。
#
# 工具只读文件、起进程（pytest），不导入 harness/ 里的代码。

from __future__ import annotations

import ast
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from queue import Queue

from . import baseline, changes, registry

# 快慢层的默认阈值（秒），设计说明「常量」：单个内核测试文件超过它的算慢层
DEFAULT_SLOW_SECONDS = 5.0
SLOW_SECONDS_MIN = 1.0
SLOW_SECONDS_MAX = 30.0

# 单个变异的超时是它要运行的那一层在基线里耗时的 10 倍，且不少于 2 秒（设计说明「常量」）
TIMEOUT_MULTIPLIER = 10
TIMEOUT_MIN_SECONDS = 2.0

# 只给人看的文字：异常信息、日志文字、文档字符串（设计说明「边界与范围」）。日志取这些方法名。
LOG_METHODS = frozenset({"debug", "info", "warning", "warn", "error", "exception", "critical", "log"})

MODULE_LEVEL = "<module>"


class MutationError(Exception):
    """变异检查自己出错：poodle 起不来、生成不了变异、副本建不出来。"""


@dataclass(frozen=True)
class Statement:
    # 模块里的一条语句与它属于的函数：方法写成 Class.method；模块一级与类一级的语句记 <module>。
    # 函数里的嵌套函数归在它所在的函数里（与改动识别的口径一致）。occurrence 是同一函数里
    # 文字完全相同的语句里的第几处（从 1 数），理由登记用它定位。
    function: str
    node: ast.stmt
    start_line: int
    start_col: int
    end_line: int
    end_col: int
    text: str
    occurrence: int


@dataclass(frozen=True)
class Mutation:
    # 一处变异：poodle 的改动位置与替换文字，加上它所在的整条语句改动前后的文字
    mutator: str
    function: str
    statement_lineno: int
    statement_occurrence: int
    lineno: int
    col_offset: int
    end_lineno: int
    end_col_offset: int
    replacement: str
    before: str
    after: str

    def key(self) -> tuple:
        return (self.mutator, self.lineno, self.col_offset, self.end_lineno, self.end_col_offset, self.replacement)

    def description(self) -> dict:
        return {
            "mutator": self.mutator,
            "function": self.function,
            "lineno": self.statement_lineno,
            "occurrence": self.statement_occurrence,
            "before": self.before,
            "after": self.after,
        }


@dataclass(frozen=True)
class MutationResult:
    # 一个变异在两层里的结局
    mutation: Mutation
    outcome: str  # killed / survived
    layer: str  # fast / slow
    test_file: str | None


@dataclass(frozen=True)
class TimeoutResult:
    # 第一次超时的变异与重跑一次的结局
    mutation: Mutation
    first_layer: str
    second_outcome: str  # killed / survived / timeout
    second_layer: str | None
    second_test_file: str | None


def generate(source: str, scope_lines: set[int] | None = None) -> list[Mutation]:
    # 在源码上生成全部变异。scope_lines 给定时只保留落在这些语句（按语句第一行）上的变异；
    # None 表示整个模块的全部语句（全量模式）。
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise MutationError(f"源码不是有效的 Python：{exc}") from exc
    lines = source.splitlines()
    statements = _statements(tree, source)
    parents = _parents(tree)
    mutants: list[Mutation] = []
    seen: set[tuple] = set()
    for mutator_name, mutation in _poodle_mutations(tree, lines):
        statement = _containing(statements, mutation.lineno, mutation.end_lineno)
        if statement is None:
            continue
        if scope_lines is not None and statement.node.lineno not in scope_lines:
            continue
        if mutation.mutator_name == "String" and _is_human_text(tree, parents, mutation):
            continue
        key = (
            mutation.mutator_name,
            mutation.lineno,
            mutation.col_offset,
            mutation.end_lineno,
            mutation.end_col_offset,
            mutation.text,
        )
        if key in seen:
            continue
        seen.add(key)
        mutants.append(
            Mutation(
                mutator=mutation.mutator_name,
                function=statement.function,
                statement_lineno=statement.node.lineno,
                statement_occurrence=statement.occurrence,
                lineno=mutation.lineno,
                col_offset=mutation.col_offset,
                end_lineno=mutation.end_lineno,
                end_col_offset=mutation.end_col_offset,
                replacement=mutation.text,
                before=statement.text,
                after=_replace_in_statement(statement, mutation),
            )
        )
    mutants.sort(key=lambda item: (item.lineno, item.col_offset, item.mutator, item.after))
    return mutants


def covered_and_uncovered(source: str, scope_lines: set[int] | None, executed: frozenset[int]) -> tuple[list[Statement], list[Statement]]:
    # 范围里的语句分成已覆盖与未覆盖两组。覆盖按语句第一行算。
    tree = ast.parse(source)
    statements = _statements(tree, source)
    chosen = [item for item in statements if scope_lines is None or item.node.lineno in scope_lines]
    covered = [item for item in chosen if item.node.lineno in executed]
    uncovered = [item for item in chosen if item.node.lineno not in executed]
    return covered, uncovered


def run_module(
    module: str,
    source: str,
    file_changes: changes.FileChanges | None,
    mode: str,
    module_baseline: baseline.Baseline,
    reasons: tuple[registry.Reason, ...],
    slow_seconds: float,
    jobs: int,
) -> dict:
    # 对一个模块做变异检查，返回写进报告的一段。mode 是 change 或 full。
    scope_lines, functions = _scope(source, file_changes, mode)
    covered, uncovered = covered_and_uncovered(source, scope_lines, module_baseline.executed_lines(module))
    covered_lines = {item.node.lineno for item in covered}
    mutants = generate(source, covered_lines) if covered_lines else []
    files = module_baseline.files_covering(module)
    fast = tuple(sorted((item for item in files if item.seconds <= slow_seconds), key=lambda item: (item.seconds, item.test_file)))
    slow = tuple(sorted((item for item in files if item.seconds > slow_seconds), key=lambda item: (item.seconds, item.test_file)))
    fast_seconds = sum(item.seconds for item in fast)
    slow_layer_seconds = sum(item.seconds for item in slow)
    results, timeouts = _run_all(module, mutants, module_baseline, fast, slow, fast_seconds, slow_layer_seconds, jobs)
    survived = [item for item in results if item.outcome == "survived"]
    survived.sort(key=lambda item: (item.mutation.statement_lineno, item.mutation.col_offset, item.mutation.mutator))
    timeouts.sort(key=lambda item: (item.mutation.statement_lineno, item.mutation.col_offset, item.mutation.mutator))
    candidates = [
        registry.Candidate(
            file=module,
            function=item.mutation.function,
            before=item.mutation.before,
            after=item.mutation.after,
            lineno=item.mutation.statement_lineno,
            occurrence=item.mutation.statement_occurrence,
            col_offset=item.mutation.col_offset,
        )
        for item in survived
    ]
    match = registry.match(reasons, module, functions, candidates)
    accepted = {candidate.key() for candidate in match.accepted}
    unaccepted = [item for item in survived if _candidate_key(item) not in accepted]
    passed = not uncovered and not unaccepted and not match.stale
    return {
        "module": module,
        "mode": mode,
        "functions": sorted(functions) if functions is not None else None,
        "fast_files": [{"test_file": item.test_file, "seconds": round(item.seconds, 3)} for item in fast],
        "slow_files": [{"test_file": item.test_file, "seconds": round(item.seconds, 3)} for item in slow],
        "fast_seconds": round(fast_seconds, 3),
        "slow_seconds": round(slow_layer_seconds, 3),
        "generated": len(mutants),
        "killed": len(results) - len(survived),
        "killed_by_layer": {
            "fast": sum(1 for item in results if item.outcome == "killed" and item.layer == "fast"),
            "slow": sum(1 for item in results if item.outcome == "killed" and item.layer == "slow"),
        },
        "survived": [
            {
                **item.mutation.description(),
                "accepted": _candidate_key(item) in accepted,
            }
            for item in survived
        ],
        "uncovered": [
            {"function": item.function, "lineno": item.node.lineno, "text": item.text}
            for item in uncovered
        ],
        "matched": [
            {**registry.describe(item.reason), "mutation": item.candidate.describe()}
            for item in match.matched
        ],
        "stale": [registry.describe(reason) for reason in match.stale],
        "timeouts": [
            {
                **item.mutation.description(),
                "first_layer": item.first_layer,
                "second_outcome": item.second_outcome,
                "second_layer": item.second_layer,
                "second_test_file": item.second_test_file,
            }
            for item in timeouts
        ],
        "passed": passed,
    }


def _scope(source: str, file_changes: changes.FileChanges | None, mode: str) -> tuple[set[int] | None, set[str] | None]:
    if mode == "full":
        return None, None
    if file_changes is None:
        return set(), set()
    lines: set[int] = set()
    functions: set[str] = set()
    for change in file_changes.functions:
        functions.add(change.name)
        for statement in change.statements:
            lines.add(statement.lineno)
    return lines, functions


def _candidate_key(item: MutationResult) -> tuple:
    # 存活结果与理由候选用同一组字段对应：文件、函数、整条语句改动前后的文字、第几处
    return (
        item.mutation.function,
        item.mutation.before,
        item.mutation.after,
        item.mutation.statement_lineno,
        item.mutation.statement_occurrence,
        item.mutation.col_offset,
    )


def _run_all(
    module: str,
    mutants: list[Mutation],
    module_baseline: baseline.Baseline,
    fast: tuple[baseline.TestFileRun, ...],
    slow: tuple[baseline.TestFileRun, ...],
    fast_seconds: float,
    slow_seconds: float,
    jobs: int,
) -> tuple[list[MutationResult], list[TimeoutResult]]:
    if not mutants:
        return [], []
    worker_count = max(1, min(jobs, len(mutants)))
    trees: Queue[Path] = Queue()
    created: list[Path] = []
    try:
        for index in range(worker_count):
            tree = module_baseline.work_dir / f"worker-{index}"
            try:
                baseline.clone_tree(module_baseline.tree, tree)
            except OSError as exc:
                raise MutationError(f"建不出变异运行的副本 {tree}：{exc}") from exc
            created.append(tree)
            trees.put(tree)
        fast_timeout = max(TIMEOUT_MIN_SECONDS, fast_seconds * TIMEOUT_MULTIPLIER)
        slow_timeout = max(TIMEOUT_MIN_SECONDS, slow_seconds * TIMEOUT_MULTIPLIER)
        lock = threading.Lock()
        results: list[MutationResult] = []
        timeouts: list[TimeoutResult] = []
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = [
                pool.submit(
                    _run_one,
                    module,
                    mutant,
                    module_baseline,
                    trees,
                    fast,
                    slow,
                    fast_timeout,
                    slow_timeout,
                )
                for mutant in mutants
            ]
            for future in futures:
                result, timeout = future.result()
                with lock:
                    if timeout is not None:
                        timeouts.append(timeout)
                    if result is not None:
                        results.append(result)
        return results, timeouts
    finally:
        for tree in created:
            baseline.cleanup(tree)


def _run_one(
    module: str,
    mutant: Mutation,
    module_baseline: baseline.Baseline,
    trees: Queue[Path],
    fast: tuple[baseline.TestFileRun, ...],
    slow: tuple[baseline.TestFileRun, ...],
    fast_timeout: float,
    slow_timeout: float,
) -> tuple[MutationResult | None, TimeoutResult | None]:
    tree = trees.get()
    try:
        target = tree / module
        pristine = module_baseline.tree / module
        original = pristine.read_text(encoding="utf-8")
        try:
            _write(target, _apply(original, mutant))
            first = _run_layers(tree, module, fast, slow, fast_timeout, slow_timeout)
            if first[0] != "timeout":
                outcome, layer, test_file = first
                return MutationResult(mutant, outcome, layer, test_file), None
            second_outcome, second_layer, second_test_file = _run_layers(tree, module, fast, slow, fast_timeout, slow_timeout)
            killed = second_outcome in ("killed", "timeout")
            return (
                MutationResult(mutant, "killed" if killed else "survived", second_layer or first[1], second_test_file),
                TimeoutResult(mutant, first[1], second_outcome, second_layer, second_test_file),
            )
        finally:
            _write(target, original)
    finally:
        trees.put(tree)


def _run_layers(
    tree: Path,
    module: str,
    fast: tuple[baseline.TestFileRun, ...],
    slow: tuple[baseline.TestFileRun, ...],
    fast_timeout: float,
    slow_timeout: float,
) -> tuple[str, str, str | None]:
    # 快层按耗时从短到长，遇到第一个失败就停；快层都通过才跑慢层。返回结局、层与失败的测试文件。
    for layer, files, timeout in (("fast", fast, fast_timeout), ("slow", slow, slow_timeout)):
        if not files:
            continue
        deadline = _now() + timeout
        for item in files:
            remaining = deadline - _now()
            if remaining <= 0:
                return "timeout", layer, None
            try:
                done = baseline.run_process(
                    baseline.pytest_command(item.test_file),
                    tree,
                    baseline.environment(tree),
                    remaining,
                )
            except subprocess.TimeoutExpired:
                return "timeout", layer, None
            except OSError as exc:
                raise MutationError(f"起不了变异判定的测试进程（{item.test_file}）：{exc}") from exc
            if done.returncode != 0:
                return "killed", layer, item.test_file
    return "survived", "slow", None


def _now() -> float:
    return time.monotonic()


def _poodle_mutations(tree: ast.Module, lines: list[str]) -> list[tuple[str, object]]:
    # 用 poodle 的变异器生成全部改动。poodle 自己不按行过滤，也不认识本工具的范围与文字规则。
    try:
        from poodle.data_types import FileMutation, Mutator, PoodleConfig, PoodleWork
        from poodle.mutate import initialize_mutators
    except ImportError as exc:  # poodle 装不上或起不来：算工具出错
        raise MutationError(f"poodle 起不来（导入失败）：{exc}") from exc
    # poodle 没有「删一行」的变异器，按它的扩展方式补一个：整条语句删掉（留空行）。
    # 会删空的语句体（唯一一条语句）、导入语句与文档字符串不删。
    class StatementDeletionMutator(Mutator):
        mutator_name = "Delete"

        def create_mutations(self, parsed_ast: ast.Module, *_args, **_kwargs) -> list[FileMutation]:
            return _deletion_mutations(parsed_ast, FileMutation)

    config = PoodleConfig(
        project_name=None,
        project_version=None,
        config_file=None,
        source_folders=[Path("harness")],
        only_files=[],
        file_flags=None,
        file_filters=[],
        file_copy_flags=None,
        file_copy_filters=[],
        work_folder=Path(".tmp") / "kernel-checks-poodle",
        max_workers=1,
        log_format="",
        log_level="ERROR",
        echo_enabled=False,
        echo_no_color=True,
        mutator_opts={},
        skip_mutators=[],
        add_mutators=[StatementDeletionMutator],
        min_timeout=2,
        timeout_multiplier=TIMEOUT_MULTIPLIER,
        runner="command_line",
        runner_opts={},
        reporters=[],
        reporter_opts={},
        fail_under=None,
        skip_delete_folder=True,
    )
    work = PoodleWork(config)
    try:
        mutators = initialize_mutators(work)
    except Exception as exc:  # poodle 自己的初始化失败也算起不来
        raise MutationError(f"poodle 起不来（初始化失败）：{exc}") from exc
    generated: list[tuple[str, object]] = []
    for mutator in mutators:
        try:
            mutations = mutator.create_mutations(parsed_ast=deepcopy(tree), file_lines=deepcopy(lines))
        except Exception as exc:  # 单个变异器崩了也是工具出错，不当作通过
            raise MutationError(f"poodle 生成变异失败：{exc}") from exc
        name = getattr(mutator, "mutator_name", type(mutator).__name__)
        generated.extend((name, mutation) for mutation in mutations)
    return generated


def _deletion_mutations(tree: ast.Module, file_mutation: type) -> list:
    lengths = _body_lengths(tree)
    mutants = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if lengths.get(id(node), 0) <= 1:
            continue
        lineno, col, end_lineno, end_col = _location(node)
        mutants.append(
            file_mutation(
                mutator_name="Delete",
                lineno=lineno,
                col_offset=col,
                end_lineno=end_lineno,
                end_col_offset=end_col,
                text="",
            )
        )
    return mutants


def _body_lengths(tree: ast.Module) -> dict[int, int]:
    # 每条语句所在的语句列表有多长：只有一条语句的列表不能删（删了函数体为空）
    lengths: dict[int, int] = {}
    for node in ast.walk(tree):
        for _name, value in ast.iter_fields(node):
            if isinstance(value, list) and value and all(isinstance(item, ast.stmt) for item in value):
                for item in value:
                    lengths[id(item)] = len(value)
    return lengths


def _location(node: ast.AST) -> tuple[int, int, int, int]:
    # 与 poodle 的取法一致：函数与类连同装饰器一起算
    lineno = getattr(node, "lineno", 1)
    col = getattr(node, "col_offset", 0)
    end_lineno = getattr(node, "end_lineno", None) or lineno
    end_col = getattr(node, "end_col_offset", None) or col
    for decorator in getattr(node, "decorator_list", []):
        if decorator.lineno < lineno or (decorator.lineno == lineno and decorator.col_offset < col):
            lineno, col = decorator.lineno, decorator.col_offset
    return lineno, col, end_lineno, end_col


def _statements(tree: ast.Module, source: str) -> list[Statement]:
    found: list[Statement] = []

    def walk(body: list[ast.stmt], function: str, prefix: str = "") -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if function == MODULE_LEVEL:
                    name = prefix + node.name
                    found.append(_statement(name, node, source))
                    walk(node.body, name)
                else:
                    # 函数里的嵌套函数归在所在的函数里（与改动识别的口径一致）
                    found.append(_statement(function, node, source))
                    walk(node.body, function)
                continue
            if isinstance(node, ast.ClassDef) and function == MODULE_LEVEL:
                found.append(_statement(MODULE_LEVEL, node, source))
                walk(node.body, MODULE_LEVEL, prefix + node.name + ".")
                continue
            found.append(_statement(function, node, source))
            for nested in _nested_lists(node):
                walk(nested, function, prefix)

    walk(tree.body, MODULE_LEVEL)
    return _with_occurrences(found)


def _with_occurrences(statements: list[Statement]) -> list[Statement]:
    # 同一函数里文字完全相同的语句按源码位置编号，理由登记用它定位「第几处」
    groups: dict[tuple[str, str], list[Statement]] = {}
    for statement in statements:
        groups.setdefault((statement.function, statement.text), []).append(statement)
    numbers: dict[int, int] = {}
    for group in groups.values():
        for number, statement in enumerate(sorted(group, key=lambda item: (item.start_line, item.start_col)), start=1):
            numbers[id(statement)] = number
    return [replace(statement, occurrence=numbers[id(statement)]) for statement in statements]


def _statement(function: str, node: ast.stmt, source: str) -> Statement:
    start_line, start_col, end_line, end_col = _location(node)
    return Statement(
        function=function,
        node=node,
        start_line=start_line,
        start_col=start_col,
        end_line=end_line,
        end_col=end_col,
        text=_segment(source, start_line, start_col, end_line, end_col),
        occurrence=1,
    )


def _nested_lists(node: ast.AST) -> list[list[ast.stmt]]:
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


def _parents(tree: ast.Module) -> dict[int, ast.AST]:
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _containing(statements: list[Statement], lineno: int, end_lineno: int) -> Statement | None:
    # 改动落在哪条语句上：包含它的语句里范围最小的那一条（嵌套语句各自算）
    best: Statement | None = None
    for statement in statements:
        if statement.start_line <= lineno and end_lineno <= statement.end_line:
            if best is None or (statement.end_line - statement.start_line) < (best.end_line - best.start_line):
                best = statement
    return best


def _is_human_text(tree: ast.Module, parents: dict[int, ast.AST], mutation: object) -> bool:
    # String 变异落在只给人看的文字上：文档字符串、异常信息、日志文字。
    node = _constant_at(tree, mutation)
    if node is None:
        return False
    child = node
    parent = parents.get(id(child))
    while parent is not None:
        if isinstance(parent, ast.Expr) and isinstance(child, (ast.Constant, ast.JoinedStr)):
            # 只有整条语句就是一段文字（文档字符串、单独一段字符串）才算只给人看的文字；
            # 调用里的字符串是业务取值，照常变异
            return True
        if isinstance(parent, ast.Raise):
            return True
        if isinstance(parent, ast.Call) and _is_log_call(parent):
            if child in parent.args and isinstance(child, (ast.Constant, ast.JoinedStr)):
                return True
            for keyword in parent.keywords:
                if keyword.arg in ("msg", "message") and child is keyword.value and isinstance(
                    child, (ast.Constant, ast.JoinedStr)
                ):
                    return True
        child = parent
        parent = parents.get(id(child))
    return False


def _constant_at(tree: ast.Module, mutation: object) -> ast.Constant | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            lineno, col, end_lineno, end_col = _location(node)
            if (
                lineno == mutation.lineno
                and col == mutation.col_offset
                and end_lineno == mutation.end_lineno
                and end_col == mutation.end_col_offset
            ):
                return node
    return None


def _is_log_call(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr in LOG_METHODS
    if isinstance(func, ast.Name):
        return func.id in LOG_METHODS
    return False


def _replace_in_statement(statement: Statement, mutation: object) -> str:
    source = statement.text
    start = _offset_in_segment(statement, mutation.lineno, mutation.col_offset)
    end = _offset_in_segment(statement, mutation.end_lineno, mutation.end_col_offset)
    return source[:start] + mutation.text + source[end:]


def _offset_in_segment(statement: Statement, lineno: int, col: int) -> int:
    # 把源码坐标换算成语句文字里的下标。col 是 UTF-8 字节偏移，按字符数换算。
    # 语句文字从 start_line 的 start_col 开始，第一行要减掉这段缩进；后面的行按整行算。
    rows = statement.text.splitlines(keepends=True)
    row_index = lineno - statement.start_line
    index = sum(len(row) for row in rows[:row_index])
    row = rows[row_index]
    return index + _chars(row, col - (statement.start_col if row_index == 0 else 0))


def _segment(source: str, start_line: int, start_col: int, end_line: int, end_col: int) -> str:
    rows = source.splitlines(keepends=True)
    start = sum(len(row) for row in rows[: start_line - 1]) + _chars(rows[start_line - 1], start_col)
    end = sum(len(row) for row in rows[: end_line - 1]) + _chars(rows[end_line - 1], end_col)
    return source[start:end]


def _chars(row: str, byte_col: int) -> int:
    if byte_col <= 0:
        return 0
    return len(row.encode("utf-8")[:byte_col].decode("utf-8"))


def _apply(source: str, mutation: Mutation) -> str:
    rows = source.splitlines(keepends=True)
    first = rows[mutation.lineno - 1]
    last = rows[mutation.end_lineno - 1]
    start = _chars(first, mutation.col_offset)
    end = _chars(last, mutation.end_col_offset)
    merged = first[:start] + mutation.replacement + last[end:]
    return "".join(rows[: mutation.lineno - 1] + [merged] + rows[mutation.end_lineno :])


def _write(path: Path, text: str) -> None:
    # 副本里的文件可能是硬链接：先删掉再写，避免改到基线副本与别的并行任务
    path.unlink(missing_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
