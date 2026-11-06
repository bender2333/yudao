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
        "files": [],
        "functions": [],
        "violations": [],
        "reasons": {"path": "harness/tests/kernel/mutation_reasons.json", "count": None, "problems": []},
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
        lines.append("模式：忽略清单里的开关，检查全部内核模块")
    else:
        lines.append("模式：按清单里的复杂度开关")
    checked = report["checked_modules"]
    lines.append("检查的内核模块：" + ("、".join(checked) if checked else "无"))
    skipped = report["skipped_modules"]
    if skipped:
        lines.append("没检查的内核模块：" + "、".join(f"{item['module']}（{item['why']}）" for item in skipped))
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
    lines.append("结论：" + ("通过" if report["verdict"] == PASS else "不通过"))
    return "\n".join(lines) + "\n"
