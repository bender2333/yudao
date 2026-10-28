"""核对回放是忠实的：规则全关时，`view()` 必须一字不差地还原记录下来的请求。

这是「回放脚本别人跑得出来、结果可信」的前提之一：如果视图层连记录下来的请求都还原
不出来，后面所有关于召回与浪费的数字都不可信。

只比较视图负责的两部分：`messages` 与 `tools`。请求体里其余字段（`max_tokens`、`model`、
`stream`、`stream_options`）由执行层按调用目标填，不属于装配。
"""

from __future__ import annotations

import sys

from .items import normalize_request
from .replay import IDENTITY
from .store import EventLog
from .view import canonical_bytes, view


def main(db_path: str, artifacts_root: str | None = None) -> int:
    checked = 0
    failures: list[tuple[str, int, str]] = []
    with EventLog(db_path, artifacts_root) as log:
        for run_id in log.runs():
            for step in log.steps(run_id):
                entries = normalize_request(step.body, step.step_id)
                rebuilt = view(entries, IDENTITY, tools=step.body.get("tools"))
                recorded = {"messages": step.body.get("messages"), "tools": step.body.get("tools")}
                if canonical_bytes(rebuilt) != canonical_bytes(recorded):
                    failures.append((run_id, step.step_id, _first_difference(rebuilt, recorded)))
                checked += 1
    print(f"核对 {checked} 步：逐字节一致 {checked - len(failures)} 步，不一致 {len(failures)} 步。")
    for run_id, step_id, detail in failures[:10]:
        print(f"  不一致：{run_id} 第 {step_id} 步：{detail}")
    return 0 if not failures else 1


def _first_difference(rebuilt: dict, recorded: dict) -> str:
    left = rebuilt.get("messages") or []
    right = recorded.get("messages") or []
    if len(left) != len(right):
        return f"条目数 {len(left)} != {len(right)}"
    for index, (one, other) in enumerate(zip(left, right)):
        if one != other:
            return f"第 {index} 条不同：{str(one)[:80]} != {str(other)[:80]}"
    return "tools 不同"


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "", sys.argv[2] if len(sys.argv) > 2 else None))
