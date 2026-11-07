# 理由登记的格式与读取（docs/design/kernel-quality-gate.md「存活的出口与理由登记」「评价材料」）：
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


@dataclass(frozen=True)
class Candidate:
    # 一处存活的变异：与理由登记比对用的字段（文件、函数、整条语句改动前后的文字、第几处、位置）
    file: str
    function: str
    before: str
    after: str
    lineno: int
    occurrence: int = 1
    col_offset: int = 0

    def key(self) -> tuple:
        return (self.function, self.before, self.after, self.lineno, self.occurrence, self.col_offset)

    def describe(self) -> dict:
        return {
            "function": self.function,
            "lineno": self.lineno,
            "occurrence": self.occurrence,
            "before": self.before,
            "after": self.after,
        }


@dataclass(frozen=True)
class Match:
    reason: Reason
    candidate: Candidate


@dataclass(frozen=True)
class MatchResult:
    # 命中（单列、不算不通过）、过期（对不上任何存活变异，不通过）与没被登记覆盖的存活变异
    matched: tuple[Match, ...]
    stale: tuple[Reason, ...]
    unmatched: tuple[Candidate, ...]

    @property
    def accepted(self) -> tuple[Candidate, ...]:
        return tuple(match.candidate for match in self.matched)


def match(
    reasons: tuple[Reason, ...],
    module: str,
    functions: set[str] | None,
    candidates: list[Candidate],
) -> MatchResult:
    # 理由登记按「文件、函数、整条语句改动前后的文字、第几处」与存活的变异比对（设计说明
    # 「存活的出口与理由登记」）。functions 为 None 表示全量模式核对全部登记项；否则只核对落在
    # 改到的函数里的登记项（改动模式）。对不上任何存活变异的登记项是过期项。
    scoped = [
        reason
        for reason in reasons
        if reason.file == module and (functions is None or reason.function in functions)
    ]
    groups: dict[tuple[str, str, str, int], list[Candidate]] = {}
    for candidate in sorted(candidates, key=lambda item: (item.function, item.lineno, item.occurrence, item.col_offset)):
        key = (candidate.function, candidate.before, candidate.after, candidate.occurrence)
        groups.setdefault(key, []).append(candidate)
    matched: list[Match] = []
    stale: list[Reason] = []
    accepted: set[tuple] = set()
    for reason in scoped:
        occurrence = reason.occurrence or 1
        group = groups.get((reason.function, reason.before, reason.after, occurrence), [])
        if group:
            candidate = group[0]
            matched.append(Match(reason=reason, candidate=candidate))
            accepted.add(candidate.key())
        else:
            stale.append(reason)
    unmatched = tuple(candidate for candidate in candidates if candidate.key() not in accepted)
    return MatchResult(matched=tuple(matched), stale=tuple(stale), unmatched=unmatched)


def describe(reason: Reason) -> dict:
    # 报告里的一项登记：字段与登记文件的字段同名
    return {
        "file": reason.file,
        "function": reason.function,
        "before": reason.before,
        "after": reason.after,
        "reason": reason.reason,
        "registered_by": reason.registered_by,
        "registered_at": reason.registered_at,
        "occurrence": reason.occurrence,
    }
