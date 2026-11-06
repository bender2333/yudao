# 命令行入口（docs/design/kernel-quality-gate.md「合并检查」）：CI 的「内核检查」作业与执行者
# 交付前在本地运行的是同一条命令 `uv run python -m tools.kernel_checks check`，得到同一个结论。
# 不带选项时输入是当前提交相对 origin/main 合并基点的改动；--base、--report、--ignore-switches
# 三个选项见包的文档字符串与 --help。退出码：0 通过，1 不通过，2 工具自己出错。

from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path

from . import __doc__ as USAGE
from . import changes, complexity, registry, report

MANIFEST = Path("harness/definitions/kernel-manifest.json")
REASONS = Path("harness/tests/kernel/mutation_reasons.json")


class ManifestError(Exception):
    """内核清单读不了，或者结构不对。"""


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
        description="按相对合并基点的改动做检查：改到的函数圈复杂度不超过 10，理由登记的格式合格。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    check.add_argument("--base", default="origin/main", help="合并基点所取的引用（默认 origin/main）")
    check.add_argument("--report", type=Path, default=None, help="把 JSON 报告写到这个文件；目录不存在就建")
    check.add_argument("--ignore-switches", action="store_true", help="忽略清单里的开关，对全部内核模块检查")
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


def load_reasons(root: Path) -> dict:
    entry = {"path": REASONS.as_posix(), "count": None, "problems": []}
    try:
        reasons = registry.load(root / REASONS)
    except registry.RegistryFormatError as exc:
        entry["problems"] = exc.problems
        return entry
    entry["count"] = len(reasons)
    return entry


def check(root: Path, base: str, ignore_switches: bool) -> dict:
    manifest = load_manifest(root)
    modules = kernel_modules(manifest)
    selected = [module for module in modules if ignore_switches or module["checks"].get("complexity") is True]
    selected_paths = {module["path"] for module in selected}
    module_paths = {module["path"] for module in modules}
    merge_base = changes.merge_base(root, base)
    diff = changes.changed_python_files(root, merge_base)
    files: list[dict] = []
    functions: list[dict] = []
    violations: list[dict] = []
    skipped: list[dict] = []
    for path, status in diff:
        if path not in module_paths:
            continue
        if path not in selected_paths:
            checks = next(module["checks"] for module in modules if module["path"] == path)
            why = "只开了变异开关，这一版没有变异检查" if checks.get("mutation") is True else "清单里没有打开复杂度开关"
            skipped.append({"module": path, "why": why})
            continue
        entry = {"module": path, "status": status, "functions": [], "removed_functions": []}
        if status == "D":
            files.append(entry)
            continue
        new_source = changes.show(root, "HEAD", path)
        if new_source is None:
            raise changes.GitError(f"读不了 {path} 在当前提交里的内容")
        old_source = None if status == "A" else changes.show(root, merge_base, path)
        if status != "A" and old_source is None:
            raise changes.GitError(f"读不了 {path} 在合并基点里的内容")
        file_changes = changes.detect(old_source, new_source)
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
    reasons = load_reasons(root)
    verdict = report.FAIL if violations or reasons["problems"] else report.PASS
    return {
        "tool": "tools.kernel_checks",
        "base": base,
        "mode": "ignore-switches" if ignore_switches else "switches",
        "merge_base": merge_base,
        "limit": complexity.LIMIT,
        "checked_modules": [module["path"] for module in selected],
        "skipped_modules": skipped,
        "files": files,
        "functions": functions,
        "violations": violations,
        "reasons": reasons,
        "verdict": verdict,
        "error": None,
    }


def _run(argv: list[str] | None) -> int:
    args = parse_args(argv)
    mode = "ignore-switches" if args.ignore_switches else "switches"
    try:
        result = check(Path.cwd(), args.base, args.ignore_switches)
        code = 0 if result["verdict"] == report.PASS else 1
    except (changes.GitError, ManifestError, registry.RegistryReadError, complexity.ComplexityError) as exc:
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
