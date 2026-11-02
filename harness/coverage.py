# 检验覆盖的三个数（验证的独立性设计说明第 7.1 节第 4 点，工单 #151）：放行记录一次算好，
# 查询（#399）与画面（#154）读这个数，不重新计算。纯函数：输入是质检逐条结论的清单，
# 不读事件、不读文件、不算模型调用。检验方式的代码名在 kernel_events.QA_METHODS（封闭取值，只增），
# 两端共读的同一份夹具在 harness/tests/fixtures/check_methods.json 与客户端各一份。
#
# 改判（验证的独立性设计说明第 4 节，工单 #1190）：质检看过解释以后改了判断的条目，
# 放行记录里记下条数，以后要算解释翻转率时从这里取。改判由这里的纯函数比对得出：
# 判断的逐条结果与结论的逐条结果按 AC 序号一一对照，不看别的字段。

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


def coverage_report(criteria: Sequence[Mapping[str, Any]], *, changed: int = 0) -> dict[str, Any]:
    # 检验覆盖比例 = 可执行检验的条件里已在当前快照上运行并通过的条数 ÷ 条件总数；
    # 开环的条件数 = 条件总数 − 可执行检验的条件数；模型阅读的条件数含于开环。
    # 条件总数为 0 时比例是 0.0（放行不会走到这里：criteria 必须覆盖当前 ProductSpec 的每条验收条件）。
    # changed 是改判的条数（工单 #1190）：与三个数一起写进放行记录，查询与画面读存下的这一份
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
        "changed": changed,
    }


def open_criteria(criteria: Sequence[Mapping[str, Any]]) -> list[str]:
    # 放行记录里的开环明细：不可执行检验的验收条件，按 AC 序号
    return [str(item.get("criterion")) for item in criteria
            if not method_is_executable(str(item.get("method")))]


def changed_criteria(judged: Sequence[Mapping[str, Any]],
                     concluded: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """改判的条目（验证的独立性设计说明第 4 节，工单 #1190）。

    独立判断的逐条结果与结论的逐条结果按 AC 序号对照：结果不同的条目列出来，带序号、
    判断的结果与结论的结果（后两个方向分开，算解释翻转率时按它们分类）。只看 result，
    不看检验方式与说明；判断里没有的条件不当改判（结论覆盖全部验收条件由别的检查负责）。
    """
    judged_by_criterion = {str(item.get("criterion")): str(item.get("result")) for item in judged}
    changes: list[dict[str, Any]] = []
    for item in concluded:
        criterion = str(item.get("criterion"))
        if criterion not in judged_by_criterion:
            continue
        before = judged_by_criterion[criterion]
        after = str(item.get("result"))
        if before != after:
            changes.append({"criterion": criterion, "judged": before, "result": after})
    return changes
