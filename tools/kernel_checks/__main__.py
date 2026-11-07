# 命令行入口（docs/design/kernel-quality-gate.md「合并检查」）：CI 的「内核检查」作业与执行者
# 交付前在本地运行的是同一条命令 `uv run python -m tools.kernel_checks check`，得到同一个结论。
# 不带选项时输入是当前提交相对 origin/main 合并基点的改动；--base、--report、--ignore-switches
# 与变异检查的选项见包的文档字符串与 --help。退出码：0 通过，1 不通过，2 工具自己出错。

from __future__ import annotations

import argparse
import json
import os
import traceback
from pathlib import Path

from . import __doc__ as USAGE
from . import baseline, changes, churn, complexity, mutation, registry, report

MANIFEST = Path("harness/definitions/kernel-manifest.json")
REASONS = Path("harness/tests/kernel/mutation_reasons.json")


class ManifestError(Exception):
    """内核清单读不了，或者结构不对。"""


def _slow_seconds(value: str) -> float:
    number = float(value)
    if not mutation.SLOW_SECONDS_MIN <= number <= mutation.SLOW_SECONDS_MAX:
        raise argparse.ArgumentTypeError(
            f"快慢层阈值必须在 {mutation.SLOW_SECONDS_MIN:g} 至 {mutation.SLOW_SECONDS_MAX:g} 秒之间"
        )
    return number


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("并行数必须大于等于 1")
    return number


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tools.kernel_checks",
        description=USAGE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser(
        "check",
        help="按相对合并基点的改动做检查，写出报告与结论",
        description=(
            "按相对合并基点的改动做检查：改到的函数圈复杂度不超过 10，理由登记的格式合格；"
            "清单里变异开关已打开的模块在改到时做变异检查。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    check.add_argument("--base", default="origin/main", help="合并基点所取的引用（默认 origin/main）")
    check.add_argument("--report", type=Path, default=None, help="把 JSON 报告写到这个文件；目录不存在就建")
    check.add_argument(
        "--ignore-switches",
        action="store_true",
        help="忽略清单里的复杂度开关，对全部内核模块检查复杂度",
    )
    check.add_argument(
        "--module",
        action="append",
        dest="modules",
        default=None,
        metavar="路径",
        help="只检查这些内核模块（仓库内相对路径，可写多次；不看清单里的开关，复杂度与变异都检查）",
    )
    check.add_argument(
        "--mutation-mode",
        choices=("change", "full"),
        default="change",
        help="变异检查的模式：change 只检查改到的语句（默认），full 检查整个模块",
    )
    check.add_argument(
        "--mutation-slow-seconds",
        type=_slow_seconds,
        default=mutation.DEFAULT_SLOW_SECONDS,
        metavar="秒",
        help=f"单个测试文件超过它算慢层（默认 {mutation.DEFAULT_SLOW_SECONDS:g}，范围 1 至 30）",
    )
    check.add_argument(
        "--mutation-jobs",
        type=_positive,
        default=None,
        metavar="个数",
        help="变异检查的并行数（默认处理器核数减一，最少 1）",
    )
    return parser.parse_args(argv)


def load_manifest(root: Path) -> dict:
    path = root / MANIFEST
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"读不了内核清单 {path}：{exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"内核清单不是有效的 JSON（{path}）：{exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("paths"), list):
        raise ManifestError(f"内核清单缺少 paths 列表（{path}）")
    return data


def kernel_modules(manifest: dict) -> list[dict]:
    modules: list[dict] = []
    for entry in manifest["paths"]:
        if not isinstance(entry, dict):
            raise ManifestError("内核清单的 paths 里有不是对象的条目")
        if entry.get("kind") != "module":
            continue
        path = entry.get("path")
        if not isinstance(path, str) or not path.endswith(".py"):
            continue
        checks = entry.get("checks") or {}
        if not isinstance(checks, dict):
            raise ManifestError(f"内核清单里 {path} 的 checks 不是对象")
        modules.append({"path": path, "checks": checks})
    return modules


def load_reasons(root: Path) -> tuple[dict, tuple[registry.Reason, ...]]:
    entry = {"path": REASONS.as_posix(), "count": None, "problems": []}
    try:
        reasons = registry.load(root / REASONS)
    except registry.RegistryFormatError as exc:
        entry["problems"] = exc.problems
        return entry, ()
    entry["count"] = len(reasons)
    return entry, reasons


def switched_on_modules(root: Path, merge_base: str, modules: list[dict]) -> set[str]:
    # 相对合并基点，清单里 mutation 由关（或不存在）变成开的模块：那次合并对这个模块跑全量模式
    old_checks = checks_at(root, merge_base)
    return {
        module["path"]
        for module in modules
        if module["checks"].get("mutation") is True
        and (old_checks.get(module["path"]) or {}).get("mutation") is not True
    }


def checks_at(root: Path, commit: str) -> dict[str, dict]:
    # 合并基点上的清单里，每个模块的 checks。清单不在那个提交里时当作全部关着。
    text = changes.show(root, commit, MANIFEST.as_posix())
    if text is None:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"合并基点里的内核清单不是有效的 JSON：{exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("paths"), list):
        raise ManifestError("合并基点里的内核清单缺少 paths 列表")
    found: dict[str, dict] = {}
    for entry in data["paths"]:
        if not isinstance(entry, dict) or entry.get("kind") != "module":
            continue
        path = entry.get("path")
        if not isinstance(path, str):
            continue
        checks = entry.get("checks") or {}
        if isinstance(checks, dict):
            found[path] = checks
    return found


def check(
    root: Path,
    base: str,
    ignore_switches: bool,
    selected_modules: list[str] | None = None,
    mutation_mode: str = "change",
    slow_seconds: float = mutation.DEFAULT_SLOW_SECONDS,
    jobs: int | None = None,
) -> dict:
    manifest = load_manifest(root)
    modules = kernel_modules(manifest)
    module_by_path = {module["path"]: module for module in modules}
    requested = {Path(path).as_posix() for path in selected_modules or []}
    unknown = sorted(requested - set(module_by_path))
    if unknown:
        raise ManifestError("清单里没有这些内核模块：" + "、".join(unknown))
    selected = [
        module
        for module in modules
        if requested or ignore_switches or module["checks"].get("complexity") is True
    ]
    selected_paths = {module["path"] for module in selected}
    module_paths = set(module_by_path)
    merge_base = changes.merge_base(root, base)
    # 近两周改动只是读数：清单里每个内核模块都写，不看开关，也不进结论（设计说明「接口」）
    churn_section = churn.section(root, [module["path"] for module in modules])
    diff = changes.changed_python_files(root, merge_base)
    sources: dict[str, dict] = {}
    files: list[dict] = []
    functions: list[dict] = []
    violations: list[dict] = []
    skipped: list[dict] = []
    for path, status in diff:
        if path not in module_paths:
            continue
        source = {"status": status, "new_source": None, "old_source": None, "file_changes": None}
        sources[path] = source
        if status != "D":
            new_source = changes.show(root, "HEAD", path)
            if new_source is None:
                raise changes.GitError(f"读不了 {path} 在当前提交里的内容")
            old_source = None if status == "A" else changes.show(root, merge_base, path)
            if status != "A" and old_source is None:
                raise changes.GitError(f"读不了 {path} 在合并基点里的内容")
            file_changes = changes.detect(old_source, new_source)
            source.update(new_source=new_source, old_source=old_source, file_changes=file_changes)
        if path not in selected_paths:
            skipped.append({"module": path, "why": "清单里没有打开复杂度开关"})
            continue
        entry = {"module": path, "status": status, "functions": [], "removed_functions": []}
        if status == "D":
            files.append(entry)
            continue
        file_changes = source["file_changes"]
        if not file_changes.changed:
            continue
        for change in file_changes.functions:
            measurement = complexity.measure(change.node)
            entry["functions"].append(
                {
                    "function": change.name,
                    "complexity": measurement.value,
                    "statements": [{"lineno": item.lineno, "text": item.text} for item in change.statements],
                    "removed": change.removed,
                    "new": change.is_new,
                }
            )
            functions.append(
                {
                    "module": path,
                    "function": change.name,
                    "complexity": measurement.value,
                    "statements": len(change.statements),
                    "removed": change.removed,
                    "new": change.is_new,
                }
            )
            if measurement.over_limit:
                violations.append(
                    {"module": path, "function": change.name, "complexity": measurement.value, "limit": complexity.LIMIT}
                )
        entry["removed_functions"] = list(file_changes.removed_functions)
        files.append(entry)
    reason_entry, reason_items = load_reasons(root)
    mutation_section = _mutation_section(
        root,
        merge_base,
        modules,
        sources,
        requested,
        mutation_mode,
        slow_seconds,
        jobs,
        reason_items,
        reason_entry,
    )
    mutation_failed = bool(mutation_section and any(not item["passed"] for item in mutation_section["modules"]))
    verdict = report.FAIL if violations or reason_entry["problems"] or mutation_failed else report.PASS
    return {
        "tool": "tools.kernel_checks",
        "base": base,
        "mode": "ignore-switches" if ignore_switches else "switches",
        "merge_base": merge_base,
        "limit": complexity.LIMIT,
        "checked_modules": [module["path"] for module in selected],
        "skipped_modules": skipped,
        "churn": churn_section,
        "files": files,
        "functions": functions,
        "violations": violations,
        "reasons": reason_entry,
        "mutation": mutation_section,
        "verdict": verdict,
        "error": None,
    }


def _mutation_section(
    root: Path,
    merge_base: str,
    modules: list[dict],
    sources: dict[str, dict],
    requested: set[str],
    mutation_mode: str,
    slow_seconds: float,
    jobs: int | None,
    reasons: tuple[registry.Reason, ...],
    reason_entry: dict,
) -> dict | None:
    candidates = set(requested)
    # --ignore-switches 只对 #1477 写定的复杂度检查生效；要对任意模块跑变异检查用 --module
    candidates |= {module["path"] for module in modules if module["checks"].get("mutation") is True}
    switched = switched_on_modules(root, merge_base, modules) if candidates else set()
    to_run: list[tuple[str, str]] = []
    skipped: list[dict] = []
    for path in sorted(candidates):
        mode = "full" if mutation_mode == "full" or path in switched else "change"
        source = sources.get(path)
        if source is not None and source["status"] == "D":
            skipped.append({"module": path, "why": "模块在当前提交里被删除，没有可变的语句"})
            continue
        if mode == "change" and source is None:
            continue
        to_run.append((path, mode))
    if not to_run:
        return None
    worker_count = jobs if jobs is not None else max(1, (os.cpu_count() or 2) - 1)
    section = {
        "mode": mutation_mode,
        "slow_seconds": slow_seconds,
        "jobs": worker_count,
        "baseline": None,
        "skipped": None,
        "modules": [],
        "skipped_modules": skipped,
    }
    if reason_entry["count"] is None:
        section["skipped"] = "理由登记有问题，没有运行变异检查"
        return section
    baseline_result = baseline.run(root)
    try:
        section["baseline"] = {
            "test_files": len(baseline_result.test_files),
            "seconds": round(baseline_result.seconds, 3),
            "files": [
                {"test_file": item.test_file, "seconds": round(item.seconds, 3)} for item in baseline_result.test_files
            ],
        }
        for path, mode in to_run:
            source = sources.get(path)
            if source is None:
                new_source = changes.show(root, "HEAD", path)
                if new_source is None:
                    raise changes.GitError(f"读不了 {path} 在当前提交里的内容")
                file_changes = None
            else:
                new_source = source["new_source"]
                file_changes = source["file_changes"]
            section["modules"].append(
                mutation.run_module(
                    path,
                    new_source,
                    file_changes,
                    mode,
                    baseline_result,
                    reasons,
                    slow_seconds,
                    worker_count,
                )
            )
    finally:
        baseline.cleanup(baseline_result.work_dir)
    return section


def _run(argv: list[str] | None) -> int:
    args = parse_args(argv)
    mode = "ignore-switches" if args.ignore_switches else "switches"
    try:
        result = check(
            Path.cwd(),
            args.base,
            args.ignore_switches,
            args.modules,
            args.mutation_mode,
            args.mutation_slow_seconds,
            args.mutation_jobs,
        )
        code = 0 if result["verdict"] == report.PASS else 1
    except (
        changes.GitError,
        ManifestError,
        registry.RegistryReadError,
        complexity.ComplexityError,
        baseline.BaselineError,
        mutation.MutationError,
    ) as exc:
        result = report.error_report(args.base, mode, str(exc))
        code = 2
    if args.report is not None:
        try:
            report.write_json(args.report, result)
        except OSError as exc:
            result = report.error_report(args.base, mode, f"报告写不出来：{exc}")
            code = 2
    report.write_stdout(report.render(result))
    return code


def main(argv: list[str] | None = None) -> int:
    report.use_utf8_stdout()
    try:
        return _run(argv)
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 —— 任何没预料到的错误都算工具出错，不算通过
        traceback.print_exc()
        report.write_stdout(f"{report.TITLE}\n工具出错：未预料到的错误，见标准错误的回溯\n结论：工具出错，不算通过\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
