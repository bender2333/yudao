# CI 中的分层摘要与用例变化（测试分层设计说明第 4.3、4.4 节）。只用标准库，不导入 harness，
# 在没有安装项目依赖的作业里也能运行。
#
# 用法：
#   python scripts/ci_layers.py summary --layers harness/tests/layers.toml \
#       --junit unit=unit.xml --junit module=module.xml --junit evals=evals.xml --pending integration
#   python scripts/ci_layers.py inventory --base base.txt --head head.txt \
#       --base-layers base-layers.toml --head-layers harness/tests/layers.toml
#
# summary：读取各层的 junit 结果，输出每层的文件数、用例数、通过、失败、跳过与用时；--pending 的层
# 这次不运行，只列出登记的文件数与运行的时机。
# inventory：比较 PR 合并前后 `pytest --collect-only` 收集到的用例，按层列出用例数、新增、删除与换层。
# 两个子命令都把 Markdown 写到标准输出，CI 追加到运行摘要；读不到的输入写成说明，不让作业失败。

from __future__ import annotations

import argparse
import re
import sys
import tomllib
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# 登记表中的层与显示的名字，按金字塔从下往上排列；评测工具的测试不在登记表中，单列一行
LAYERS = ("unit", "module", "integration", "evals")
LAYER_NAMES = {"unit": "① 单元层", "module": "② 模块层", "integration": "③ 集成层", "evals": "评测工具"}
UNREGISTERED = "未登记"
PENDING_NOTES = {"integration": "合并到 main 以后运行"}
HARNESS_TESTS = "harness/tests/"
EVALS_TESTS = "evals/tests/"
NODEID = re.compile(r"^[^\s:]+\.py::\S")


@dataclass(frozen=True)
class LayerResult:
    tests: int
    failures: int
    errors: int
    skipped: int
    seconds: float
    files: int


def load_layers(text: str) -> dict[str, str]:
    # 登记表 [layers]：键是相对 harness/tests/ 的文件路径，值是 unit、module 或 integration
    return dict(tomllib.loads(text).get("layers", {}))


def layer_of(nodeid: str, layers: dict[str, str]) -> str:
    path = nodeid.split("::", 1)[0].replace("\\", "/")
    if path.startswith(HARNESS_TESTS):
        return layers.get(path[len(HARNESS_TESTS):], UNREGISTERED)
    if path.startswith(EVALS_TESTS):
        return "evals"
    return UNREGISTERED


def parse_nodeids(text: str) -> set[str]:
    # `pytest --collect-only` 在项目的 -q 设置下每行一个用例编号（「文件.py::名字」），结尾是收集计数与警告
    return {line.rstrip() for line in text.splitlines() if NODEID.match(line)}


def parse_junit(text: str) -> LayerResult:
    root = ET.fromstring(text)
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    modules = set()
    for case in root.iter("testcase"):
        modules.add(_module_of(case.get("classname", "")))
    return LayerResult(
        tests=sum(int(suite.get("tests", 0)) for suite in suites),
        failures=sum(int(suite.get("failures", 0)) for suite in suites),
        errors=sum(int(suite.get("errors", 0)) for suite in suites),
        skipped=sum(int(suite.get("skipped", 0)) for suite in suites),
        seconds=sum(float(suite.get("time", 0)) for suite in suites),
        files=len(modules - {""}),
    )


def _module_of(classname: str) -> str:
    # junit 的 classname 是「模块路径」或「模块路径.测试类」；测试类以大写的 Test 开头
    parts = classname.split(".")
    while parts and parts[-1][:1].isupper():
        parts.pop()
    return ".".join(parts)


def _duration(seconds: float) -> str:
    minutes, rest = divmod(int(round(seconds)), 60)
    return f"{minutes}:{rest:02d}"


def summary_markdown(results: dict[str, LayerResult | None], layers: dict[str, str],
                     pending: list[str]) -> str:
    registered = Counter(layers.values())
    lines = ["### 测试分层", "",
             "| 层 | 文件 | 用例 | 通过 | 失败 | 跳过 | 用时 |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for layer in LAYERS:
        name = LAYER_NAMES[layer]
        if layer in pending:
            files = registered.get(layer, 0)
            lines.append(f"| {name} | {files} | | | | | {PENDING_NOTES.get(layer, '这次不运行')} |")
            continue
        if layer not in results:
            continue
        result = results[layer]
        if result is None:
            lines.append(f"| {name} | | | | | | 没有结果（作业在测试之前失败或被取消） |")
            continue
        files = registered.get(layer, 0) if layer in registered else result.files
        failed = result.failures + result.errors
        passed = result.tests - failed - result.skipped
        lines.append(f"| {name} | {files} | {result.tests} | {passed} | {failed} | {result.skipped} "
                     f"| {_duration(result.seconds)} |")
    return "\n".join(lines) + "\n"


def inventory_markdown(base: set[str], head: set[str], base_layers: dict[str, str],
                       head_layers: dict[str, str]) -> str:
    before = {nodeid: layer_of(nodeid, base_layers) for nodeid in base}
    after = {nodeid: layer_of(nodeid, head_layers) for nodeid in head}
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    moved = sorted(nodeid for nodeid in set(after) & set(before) if after[nodeid] != before[nodeid])
    order = [*LAYERS, UNREGISTERED]
    lines = ["### 用例变化", "",
             "PR 合并前后收集到的用例（不运行）。删除的用例要与工单和交付说明逐条对上"
             "（测试分层设计说明第 10 节第 5 条）；改名的用例显示为一删一增。", "",
             "| 层 | 合并前 | 合并后 | 新增 | 删除 | 移入 | 移出 |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for layer in order:
        counts = (
            sum(1 for value in before.values() if value == layer),
            sum(1 for value in after.values() if value == layer),
            sum(1 for nodeid in added if after[nodeid] == layer),
            sum(1 for nodeid in removed if before[nodeid] == layer),
            sum(1 for nodeid in moved if after[nodeid] == layer),
            sum(1 for nodeid in moved if before[nodeid] == layer),
        )
        if layer == UNREGISTERED and not any(counts):
            continue
        lines.append(f"| {LAYER_NAMES.get(layer, layer)} | " + " | ".join(str(value) for value in counts) + " |")
    lines.append("")
    if removed:
        lines += [f"**删除的用例（{len(removed)}）**", ""]
        lines += [f"- {LAYER_NAMES.get(before[nodeid], before[nodeid])}：`{nodeid}`" for nodeid in removed]
        lines.append("")
    if moved:
        lines += [f"**换层的用例（{len(moved)}）**", ""]
        lines += [f"- {LAYER_NAMES.get(before[nodeid], before[nodeid])} → "
                  f"{LAYER_NAMES.get(after[nodeid], after[nodeid])}：`{nodeid}`" for nodeid in moved]
        lines.append("")
    if added:
        lines += [f"<details><summary>新增的用例（{len(added)}）</summary>", ""]
        lines += [f"- {LAYER_NAMES.get(after[nodeid], after[nodeid])}：`{nodeid}`" for nodeid in added]
        lines += ["", "</details>", ""]
    if not (added or removed or moved):
        lines += ["用例没有变化。", ""]
    return "\n".join(lines)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _summary(args: argparse.Namespace) -> str:
    layers = load_layers(_read(args.layers) or "")
    results: dict[str, LayerResult | None] = {}
    for item in args.junit:
        layer, _, path = item.partition("=")
        text = _read(Path(path))
        try:
            results[layer] = parse_junit(text) if text else None
        except ET.ParseError:
            results[layer] = None
    return summary_markdown(results, layers, args.pending)


def _inventory(args: argparse.Namespace) -> str:
    base, head = _read(args.base), _read(args.head)
    if base is None or head is None:
        missing = "合并前" if base is None else "合并后"
        return f"### 用例变化\n\n没有收集到{missing}的用例清单，这次不比较。\n"
    return inventory_markdown(parse_nodeids(base), parse_nodeids(head),
                              load_layers(_read(args.base_layers) or ""),
                              load_layers(_read(args.head_layers) or ""))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CI 的分层摘要与用例变化")
    commands = parser.add_subparsers(dest="command", required=True)
    summary = commands.add_parser("summary", help="各层的测试结果")
    summary.add_argument("--layers", type=Path, required=True, help="测试分层登记表")
    summary.add_argument("--junit", action="append", default=[], help="层=junit 结果文件，可重复")
    summary.add_argument("--pending", action="append", default=[], help="这次不运行的层，可重复")
    inventory = commands.add_parser("inventory", help="PR 合并前后的用例变化")
    inventory.add_argument("--base", type=Path, required=True, help="合并前的 --collect-only 输出")
    inventory.add_argument("--head", type=Path, required=True, help="合并后的 --collect-only 输出")
    inventory.add_argument("--base-layers", type=Path, required=True, help="合并前的登记表")
    inventory.add_argument("--head-layers", type=Path, required=True, help="合并后的登记表")
    args = parser.parse_args(argv)
    output = _summary(args) if args.command == "summary" else _inventory(args)
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
