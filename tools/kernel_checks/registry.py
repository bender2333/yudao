# 理由登记的格式与读取（docs/design/kernel-quality-gate.md「4.5 存活的出口与理由登记」「4.8 评价材料」）：
# 登记放在 harness/tests/kernel/mutation_reasons.json，初始是空列表。
#
# 一项写这些字段：file（文件，仓库内相对路径）、function（函数，方法写成 Class.method）、
# before（整条语句改动前的文字）、after（改动后的文字）、reason（为什么这处改动不影响行为）、
# registered_by（登记人）、registered_at（登记时间，ISO 8601）。同一函数里有两处完全相同的语句时
# 再写 occurrence（第几处，从 1 数）。
#
# 读取时校验字段齐全、理由非空；有问题的项不被接受，报出是第几项与哪个字段。过期项的核对由变异
# 检查做，这一版只做格式、读取与校验。

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REQUIRED_FIELDS = ("file", "function", "before", "after", "reason", "registered_by", "registered_at")
OPTIONAL_FIELDS = ("occurrence",)


class RegistryReadError(Exception):
    """理由登记这个文件读不了，或者不是有效的 JSON。"""


class RegistryFormatError(Exception):
    """理由登记里有不被接受的项；problems 逐项写是第几项、哪个字段。"""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Reason:
    file: str
    function: str
    before: str
    after: str
    reason: str
    registered_by: str
    registered_at: str
    occurrence: int | None


def load(path: Path) -> tuple[Reason, ...]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistryReadError(f"读不了理由登记 {path}：{exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RegistryReadError(f"理由登记不是有效的 JSON（{path}）：{exc}") from exc
    if not isinstance(data, list):
        raise RegistryFormatError([f"顶层必须是列表，现在写的是 {type(data).__name__}"])
    problems: list[str] = []
    reasons: list[Reason] = []
    for index, item in enumerate(data, start=1):
        item_problems = _item_problems(index, item)
        problems.extend(item_problems)
        if not item_problems:
            reasons.append(
                Reason(
                    file=item["file"],
                    function=item["function"],
                    before=item["before"],
                    after=item["after"],
                    reason=item["reason"],
                    registered_by=item["registered_by"],
                    registered_at=item["registered_at"],
                    occurrence=item.get("occurrence"),
                )
            )
    if problems:
        raise RegistryFormatError(problems)
    return tuple(reasons)


def _item_problems(index: int, item: object) -> list[str]:
    if not isinstance(item, dict):
        return [f"第 {index} 项必须是对象，现在写的是 {type(item).__name__}"]
    problems = [f"第 {index} 项缺少 {name}" for name in REQUIRED_FIELDS if name not in item]
    for name in REQUIRED_FIELDS:
        if name not in item:
            continue
        value = item[name]
        if not isinstance(value, str) or not value.strip():
            problems.append(f"第 {index} 项的 {name} 必须是内容非空的字符串")
    if "occurrence" in item:
        occurrence = item["occurrence"]
        if not isinstance(occurrence, int) or isinstance(occurrence, bool) or occurrence < 1:
            problems.append(f"第 {index} 项的 occurrence 必须是大于等于 1 的整数")
    unknown = sorted(set(item) - set(REQUIRED_FIELDS) - set(OPTIONAL_FIELDS))
    if unknown:
        problems.append(f"第 {index} 项有没定义的字段：{'、'.join(unknown)}")
    return problems
