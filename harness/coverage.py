# 检验覆盖的三个数（验证的独立性设计说明第 7.1 节第 4 点，工单 #151）：放行记录一次算好，
# 查询（#399）与画面（#154）读这个数，不重新计算。纯函数：输入是质检逐条结论的清单，
# 不读事件、不读文件、不算模型调用。检验方式的代码名在 kernel_events.QA_METHODS（封闭取值，只增），
# 两端共读的同一份夹具在 harness/tests/fixtures/check_methods.json 与客户端各一份。

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .kernel_events import QA_METHODS

# 可执行的检验：命令检查、试用用例、主机测量。其余三种（带参照材料的判定点、人、开环）不可执行
EXECUTABLE_METHODS = frozenset({"check", "trial", "measure"})
# 模型阅读：只凭模型读截图或读文字作判断的条件，含于开环
MODEL_READING_METHODS = frozenset({"judgement"})


def method_is_executable(method: str) -> bool:
    return method in EXECUTABLE_METHODS


def coverage_report(criteria: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    # 检验覆盖比例 = 可执行检验的条件里已在当前快照上运行并通过的条数 ÷ 条件总数；
    # 开环的条件数 = 条件总数 − 可执行检验的条件数；模型阅读的条件数含于开环。
    # 条件总数为 0 时比例是 0.0（放行不会走到这里：criteria 必须覆盖当前 ProductSpec 的每条验收条件）
    total = len(criteria)
    executable = sum(1 for item in criteria if method_is_executable(str(item.get("method"))))
    covered = sum(1 for item in criteria
                  if method_is_executable(str(item.get("method"))) and item.get("result") == "passed")
    model_reading = sum(1 for item in criteria if str(item.get("method")) in MODEL_READING_METHODS)
    return {
        "criteria_total": total,
        "executable": executable,
        "covered": covered,
        "coverage_ratio": (covered / total) if total else 0.0,
        "model_reading": model_reading,
        "open": total - executable,
    }


def open_criteria(criteria: Sequence[Mapping[str, Any]]) -> list[str]:
    # 放行记录里的开环明细：不可执行检验的验收条件，按 AC 序号
    return [str(item.get("criterion")) for item in criteria
            if not method_is_executable(str(item.get("method")))]
