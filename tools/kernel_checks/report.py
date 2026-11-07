# 报告与结论（docs/design/kernel-quality-gate.md「接口」「合并检查」）：一份 JSON 报告按
# --report 写盘，一段给人看的文字写到标准输出（按 UTF-8，Windows 控制台的默认编码下也不报编码
# 错误）。结论只有通过、不通过、工具出错三种，退出码分别是 0、1、2；工具出错一律不算通过。

from __future__ import annotations

import json
import sys
from pathlib import Path

PASS = "pass"
FAIL = "fail"
ERROR = "error"

TITLE = "内核的代码质量检查（tools.kernel_checks check）"

# 存活变异不通过时给人看的三条出路（设计说明「存活的出口与理由登记」）：补测试、删死代码、
# 写理由登记（只限等价变异）。这段话跟着工具走，规则文件里不重复。
MUTATION_OUTLETS = "存活的变异只有三条出路：补一条检查它的测试、删掉死代码、在理由登记里写明理由（只限等价变异）。"

MODE_NAMES = {"change": "改动模式", "full": "全量模式"}


def use_utf8_stdout() -> None:
    # 标准输出的编码换成 UTF-8：控制台的默认编码编不了中文时也不会在写报告这一步报错
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="strict")


def write_stdout(text: str) -> None:
    stream = sys.stdout
    try:
        stream.write(text)
        stream.flush()
    except UnicodeEncodeError:
        buffer = getattr(stream, "buffer", None)
        if buffer is None:
            raise
        buffer.write(text.encode("utf-8"))
        buffer.flush()


def write_json(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def error_report(base: str, mode: str, message: str) -> dict:
    return {
        "tool": "tools.kernel_checks",
        "base": base,
        "mode": mode,
        "merge_base": None,
        "limit": None,
        "checked_modules": [],
        "skipped_modules": [],
        "churn": None,
        "files": [],
        "functions": [],
        "violations": [],
        "reasons": {"path": "harness/tests/kernel/mutation_reasons.json", "count": None, "problems": []},
        "mutation": None,
        "verdict": ERROR,
        "error": message,
    }


def render(report: dict) -> str:
    lines = [TITLE]
    if report["verdict"] == ERROR:
        lines.append(f"工具出错：{report['error']}")
        lines.append("结论：工具出错，不算通过")
        return "\n".join(lines) + "\n"
    lines.append(f"合并基点：{report['merge_base']}（--base {report['base']}）")
    if report["mode"] == "ignore-switches":
        lines.append("模式：忽略清单里的复杂度开关，检查全部内核模块的复杂度")
    else:
        lines.append("模式：按清单里的开关")
    checked = report["checked_modules"]
    lines.append("检查的内核模块：" + ("、".join(checked) if checked else "无"))
    skipped = report["skipped_modules"]
    if skipped:
        lines.append("没检查的内核模块：" + "、".join(f"{item['module']}（{item['why']}）" for item in skipped))
    lines.extend(_churn_lines(report.get("churn")))
    files = report["files"]
    lines.append("改到的内核模块：" + ("、".join(item["module"] for item in files) if files else "无"))
    for function in report["functions"]:
        lines.append(
            f"  {function['module']}: {function['function']} 圈复杂度 {function['complexity']}"
            f"（改了 {function['statements']} 条语句，删了 {function['removed']} 条）"
        )
    for violation in report["violations"]:
        lines.append(
            f"不通过：{violation['module']}: {violation['function']} 的圈复杂度 {violation['complexity']}"
            f" 超过 {violation['limit']}"
        )
    reasons = report["reasons"]
    if reasons["count"] is None:
        lines.append(f"理由登记：{reasons['path']} 有问题")
    else:
        lines.append(f"理由登记：{reasons['count']} 项（{reasons['path']}）")
    for problem in reasons["problems"]:
        lines.append(f"不通过：理由登记{problem}")
    lines.extend(_mutation_lines(report.get("mutation")))
    lines.append("结论：" + ("通过" if report["verdict"] == PASS else "不通过"))
    return "\n".join(lines) + "\n"


def _churn_lines(churn: dict | None) -> list[str]:
    # 近两周改动（设计说明「接口」）：清单里每个内核模块一行，只是读数，不进结论
    if churn is None:
        return []
    lines: list[str] = []
    for item in churn["modules"]:
        if item["ratio"] is None:
            lines.append(f"近两周改动：{item['module']} 比值留空（{item['why']}）")
            continue
        lines.append(
            f"近两周改动：{item['module']} {item['total']} 行"
            f"（新增 {item['added']}、删除 {item['deleted']}）÷ {item['lines']} 行 = {item['ratio']:.1f}%"
        )
    return lines


def _mutation_lines(mutation: dict | None) -> list[str]:
    if mutation is None:
        return []
    lines = [
        f"变异检查（快慢层阈值 {mutation['slow_seconds']:g} 秒，并行 {mutation['jobs']}）"
    ]
    if mutation.get("skipped"):
        lines.append(f"变异检查没有运行：{mutation['skipped']}")
        return lines
    baseline = mutation.get("baseline")
    if baseline is not None:
        lines.append(f"基线：{baseline['test_files']} 个测试文件，合计 {baseline['seconds']:.1f} 秒")
    for module in mutation.get("modules", []):
        lines.extend(_module_lines(module))
    return lines


def _module_lines(module: dict) -> list[str]:
    lines = [f"  {module['module']}（{MODE_NAMES.get(module['mode'], module['mode'])}）："]
    lines.append(
        f"    基线：快层 {len(module['fast_files'])} 个文件 {module['fast_seconds']:.1f} 秒；"
        f"慢层 {len(module['slow_files'])} 个文件 {module['slow_seconds']:.1f} 秒"
    )
    lines.append(
        f"    生成变异 {module['generated']} 处，杀死 {module['killed']} 处"
        f"（快层 {module['killed_by_layer']['fast']}、慢层 {module['killed_by_layer']['slow']}），"
        f"存活 {len(module['survived'])} 处"
    )
    if module["uncovered"]:
        lines.append("    未覆盖的语句：")
        lines.extend(f"      {item['function']}:{item['lineno']}: {item['text']}" for item in module["uncovered"])
    if module["survived"]:
        lines.append("    存活的变异：")
        for item in module["survived"]:
            mark = "（命中理由登记，单列）" if item["accepted"] else ""
            lines.append(f"      {item['function']}:{item['lineno']}: {item['before']} → {item['after']}{mark}")
    if module["matched"]:
        lines.append("    命中的登记项：")
        lines.extend(
            f"      {item['file']}: {item['function']}: {item['reason']}" for item in module["matched"]
        )
    if module["stale"]:
        lines.append("    过期的登记项：")
        lines.extend(
            f"      {item['file']}: {item['function']}: {item['before']} → {item['after']}" for item in module["stale"]
        )
    if module["timeouts"]:
        lines.append("    超时的变异：")
        lines.extend(
            f"      {item['function']}:{item['lineno']}: {item['before']} → {item['after']}"
            f"（第一次 {item['first_layer']} 层超时，重跑 {item['second_outcome']}）"
            for item in module["timeouts"]
        )
    if any(not item["accepted"] for item in module["survived"]):
        lines.append("    " + MUTATION_OUTLETS)
    return lines
