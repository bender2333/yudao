# 检验覆盖的三个数（验证的独立性设计说明「口径」第 4 点，工单 #151）：放行记录一次算好，
# 查询（#399）与画面（#154）读这个数，不重新计算。纯函数：输入是质检逐条结论的清单，
# 不读事件、不读文件、不算模型调用。检验方式的代码名在 kernel_events.QA_METHODS（封闭取值，只增），
# 两端共读的同一份夹具在 harness/tests/fixtures/check_methods.json 与客户端各一份。
#
# 改判（验证的独立性设计说明「先判断后看解释」，工单 #1190）：质检看过解释以后改了判断的条目，
# 放行记录里记下条数，以后要算解释翻转率时从这里取。改判由这里的纯函数比对得出：
# 判断的逐条结果与结论的逐条结果按 AC 序号一一对照，不看别的字段。
#
# 检验的有效性（「检验的有效性」，工单 #1181）：命令检查的覆盖还要求这条检验在基线副本上失败、
# 在交付快照上通过。基线回执由主机在基线副本上写下，退出码非零且不是 124（超时）与 130（取消）
# 才是可用的失败；基线通过、缺少回执、超时或取消都不计入覆盖，写进放行记录。

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .kernel_events import QA_METHODS
from .tools import BROWSER_TOOL_NAMES

# 可执行的检验：命令检查、试用用例、主机测量。其余三种（带参照材料的判定点、人、开环）不可执行
EXECUTABLE_METHODS = frozenset({"check", "trial", "measure"})
# 模型阅读：只凭模型读截图或读文字作判断的条件，含于开环
MODEL_READING_METHODS = frozenset({"judgement"})

# 试用用例的步骤按工具分类（浏览器与 computer use 设计说明「试用用例」，工单 #1180）：含断言工具
# （browser_verify_*）或检查回执（run_check）的一步是可执行的检验；只凭截图由质检的模型判断的是模型阅读
ASSERTION_TOOL_PREFIX = "browser_verify"
RECEIPT_TOOL = "run_check"

# 基线退出码的两种无法运行：124 与 timeout 命令相同，130 是被中断的进程的惯例
BASELINE_TIMEOUT_EXIT_CODE = 124
BASELINE_CANCELLED_EXIT_CODE = 130
# 放行记录里基线异常的写法：通过、缺少回执与超时取消各有一种记录
BASELINE_UNAVAILABLE = "unable_to_run"


def is_trial_step_tool(name: str) -> bool:
    # 用例打开期间算作它的一步的工具：浏览器与屏幕动作，以及产生检查回执的 run_check
    return name in BROWSER_TOOL_NAMES or name.startswith("screen_") or name == RECEIPT_TOOL


def step_is_executable(tool: str) -> bool:
    # 一步是不是可执行的检验：断言工具或检查回执
    return tool.startswith(ASSERTION_TOOL_PREFIX) or tool == RECEIPT_TOOL


def _step_tool(step: Any) -> str:
    if isinstance(step, Mapping):
        return str(step.get("tool") or "")
    return str(getattr(step, "tool", "") or "")


def case_steps_are_executable(steps: Sequence[Any]) -> bool:
    # 用例的步骤里有没有可执行的检验：一步都没有时不算（只凭模型判断）
    return any(step_is_executable(_step_tool(step)) for step in steps)


def _case_is_model_reading(cases: Mapping[str, Any] | None, case_ids: Sequence[str]) -> bool:
    # 一条验收条件引用的用例是不是只凭模型阅读：至少一个用例，且每个用例都没有可执行的检验
    if not cases or not case_ids:
        return False
    described = [cases.get(str(case_id)) for case_id in case_ids]
    if any(item is None for item in described):
        return False
    return not any(case_steps_are_executable(item) for item in described)


def method_is_executable(method: str) -> bool:
    return method in EXECUTABLE_METHODS


def baseline_outcome(exit_code: Any) -> str:
    """一条基线回执的结果词：failed、passed 或 unable_to_run。

    退出码非零且不是 124（超时）与 130（取消）时是可用的失败；通过、超时与取消分别记为
    基线也通过与无法运行。主机只记录运行结果，不判断失败原因。
    """
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        return BASELINE_UNAVAILABLE
    if exit_code == 0:
        return "passed"
    if exit_code in (BASELINE_TIMEOUT_EXIT_CODE, BASELINE_CANCELLED_EXIT_CODE):
        return BASELINE_UNAVAILABLE
    return "failed"


def baseline_records(receipts: Sequence[Any], checks: Sequence[str]) -> dict[str, Any]:
    """本次激活的基线回执按检查名归并（工单 #1181）。

    输入是工作区事实里本部门的回执（新的在前取最新），`checks` 是逐条结论引用的检查名；
    输出是检查名 → {outcome, exit_code, summary, tree_changed}，以及 `complete`（引用的每个名字
    都有回执）。tree_changed 的回执不是证据：它与改动树的交付回执一样不绑定到原来的快照。
    """
    by_name: dict[str, Any] = {}
    for receipt in receipts:
        if not getattr(receipt, "baseline", False):
            continue
        if getattr(receipt, "tree_changed", False):
            continue
        name = str(getattr(receipt, "name", ""))
        if name in by_name:
            continue
        by_name[name] = {
            "name": name,
            "outcome": baseline_outcome(getattr(receipt, "exit_code", None)),
            "exit_code": getattr(receipt, "exit_code", None),
            "summary": str(getattr(receipt, "summary", "")),
        }
    known = {name: by_name[name] for name in checks if name in by_name}
    return {"complete": all(name in known for name in checks) if checks else True,
            "records": known}


def criterion_baseline_covered(row: Mapping[str, Any], baseline: Mapping[str, Any]) -> bool:
    """一条命令检查的结论满足检验的有效性没有（「检验的有效性」）：交付通过且同名基线回执失败。

    只有命令检查受它约束；试用用例与主机测量沿用各自的证据路径，其他方式不可执行、本来不进分子。
    """
    if str(row.get("method")) != "check" or row.get("result") != "passed":
        return False
    names = [str(name) for name in row.get("checks") or ()]
    if not names:
        return False
    records = baseline.get("records") if isinstance(baseline, Mapping) else None
    if not isinstance(records, Mapping):
        return False
    return all(records.get(name, {}).get("outcome") == "failed" for name in names)


def criterion_is_executable(criterion: Mapping[str, Any], cases: Mapping[str, Any] | None = None) -> bool:
    """一条验收条件的检验是不是可执行的（工单 #1180）。

    检验方式是可执行的那三种，并且试用用例引用的用例里有可执行的检验：只凭截图由模型判断的用例算模型阅读，
    它的条件含于开环（验证的独立性设计说明「口径」第 4 点）。
    """
    if not method_is_executable(str(criterion.get("method"))):
        return False
    trial_cases = [str(item) for item in criterion.get("trial_cases") or ()]
    if str(criterion.get("method")) == "trial" and _case_is_model_reading(cases, trial_cases):
        return False
    return True


def coverage_report(criteria: Sequence[Mapping[str, Any]], *, changed: int = 0,
                    cases: Mapping[str, Any] | None = None,
                    baseline: Mapping[str, Any] | None = None) -> dict[str, Any]:
    # 检验覆盖比例 = 可执行检验的条件里已在当前快照上运行并通过的条数 ÷ 条件总数；
    # 开环的条件数 = 条件总数 − 可执行检验的条件数；模型阅读的条件数含于开环。
    # 条件总数为 0 时比例是 0.0（放行不会走到这里：criteria 必须覆盖当前 ProductSpec 的每条验收条件）。
    # changed 是改判的条数（工单 #1190）：与三个数一起写进放行记录，查询与画面读存下的这一份。
    # cases 是用例身份到步骤的对照（工单 #1180）：只凭模型阅读的用例让它的条件算模型阅读。
    # baseline 是本次激活的基线回执归并（工单 #1181）：命令检查的覆盖还要基线失败；
    # 不给时保持旧的读法（基线还没有运行），命令检查按交付通过计入，放行记录里写明基线没有回执。
    total = len(criteria)
    executable = sum(1 for item in criteria if criterion_is_executable(item, cases))
    covered = sum(1 for item in criteria
                  if criterion_is_executable(item, cases) and item.get("result") == "passed")
    if baseline is not None:
        # docs/design/independent-verification.md「检验的有效性」：命令检查只有基线失败且交付通过才计入分子；其他基线异常不计入
        covered = sum(1 for item in criteria
                      if criterion_baseline_covered(item, baseline)
                      or (criterion_is_executable(item, cases) and item.get("result") == "passed"
                          and str(item.get("method")) != "check"))
    model_reading = sum(1 for item in criteria
                        if str(item.get("method")) in MODEL_READING_METHODS
                        or (str(item.get("method")) == "trial"
                            and _case_is_model_reading(cases, [str(case) for case in item.get("trial_cases") or ()])))
    # 基线是否全部成立（工单 #1181）：引用命令检查且写成 passed 的条目，它的每个检查名都要有失败的基线回执。
    # 不给基线归并时（旧调用方与旧事件）按没有回执处理，记 False，放行记录里写明缺少基线回执
    if baseline is not None:
        baseline_valid = bool(baseline.get("complete", False)) and all(
            criterion_baseline_covered(item, baseline)
            for item in criteria
            if str(item.get("method")) == "check" and item.get("result") == "passed")
    else:
        baseline_valid = not any(
            str(item.get("method")) == "check" and item.get("result") == "passed" for item in criteria)
    return {
        "criteria_total": total,
        "executable": executable,
        "covered": covered,
        "coverage_ratio": (covered / total) if total else 0.0,
        "model_reading": model_reading,
        "open": total - executable,
        "changed": changed,
        "baseline_valid": baseline_valid,
    }


def open_criteria(criteria: Sequence[Mapping[str, Any]],
                  cases: Mapping[str, Any] | None = None) -> list[str]:
    # 放行记录里的开环明细：不可执行检验的验收条件，按 AC 序号
    return [str(item.get("criterion")) for item in criteria
            if not criterion_is_executable(item, cases)]


def baseline_open_records(criteria: Sequence[Mapping[str, Any]],
                          baseline: Mapping[str, Any] | None) -> list[dict[str, str]]:
    """放行记录里的基线明细（docs/design/independent-verification.md「检验的有效性」的表，工单 #1181）：命令检查写成 passed 的条目逐条列出基线结果。

    每一项是 {criterion, checks, outcome}；outcome 取 failed（计入覆盖）、passed（基线也通过）、
    missing（缺少回执）或 unable_to_run（超时或取消）。放行不因此改变：结果词与准入保持现状。
    """
    if not baseline:
        return []
    records = baseline.get("records") if isinstance(baseline, Mapping) else None
    if not isinstance(records, Mapping):
        return []
    items: list[dict[str, str]] = []
    for row in criteria:
        if str(row.get("method")) != "check" or row.get("result") != "passed":
            continue
        names = [str(name) for name in row.get("checks") or ()]
        outcomes = [str(records.get(name, {}).get("outcome") or "missing") for name in names]
        worst = "failed"
        if any(outcome == "missing" for outcome in outcomes):
            worst = "missing"
        elif any(outcome == BASELINE_UNAVAILABLE for outcome in outcomes):
            worst = BASELINE_UNAVAILABLE
        elif any(outcome == "passed" for outcome in outcomes):
            worst = "passed"
        items.append({"criterion": str(row.get("criterion")), "checks": ", ".join(names),
                      "outcome": worst})
    return items


def changed_criteria(judged: Sequence[Mapping[str, Any]],
                     concluded: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """改判的条目（验证的独立性设计说明「先判断后看解释」，工单 #1190）。

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
