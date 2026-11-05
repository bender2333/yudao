# 检验覆盖的查询（工单 #399；应用层与接口层设计说明第 4.3 节 `acceptance.coverage`；
# 验证的独立性设计说明第 7、7.1 节）：读核验角色放行记录里一次算好的数与逐条结论（工单 #151 在
# 提交放行时用 harness/coverage.py 算好写进事实），这里不重新计算；查询只读，按位置回放同一段事件流
# 得到同一份结果。
#
# 逐条结论的检验方式与结果词表（第 7.1 节）：`check`、`trial`、`measure` 是可执行的检验，
# `judgement`、`human`、`open` 不可执行；结果是 `passed`、`failed`、`unverified`。
# 是否开环按可执行与否判定，开环明细读放行记录里存下的那一份。

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from .. import coverage
from ..models import EventType
from .contracts import Contract, Snapshot
from .project_queries import NotFound
from .registry import QueryDefinition
from .replay import ReplayRequest, check_position

if TYPE_CHECKING:
    from .application import Application


class CoverageNumbers(Contract):
    # 放行记录里的三个数（第 7.1 节第 4 点）：条件总数、可执行检验的条件数、已在当前快照上运行并通过的条数、
    # 检验覆盖比例、模型阅读的条件数（含于开环）与开环的条件数。原样取自放行记录，不重新计算
    criteria_total: int
    executable: int
    covered: int
    coverage_ratio: float
    model_reading: int
    open: int


class CoverageCriterion(Contract):
    # 一条验收条件：编号（AC 序号）、检验方式、结果，以及它是不是可执行的检验、是不是开环条件
    criterion: str
    method: str
    result: Literal["passed", "failed", "unverified"]
    executable: bool
    open: bool


class AcceptanceCoverageResult(Contract):
    # 一个 run 的检验覆盖：覆盖的数、逐条结论与开环明细；verdict 是这份放行记录的结论，
    # review_event_id 与 revision 指明逐条结论取自哪一条事实
    run_id: str
    work_item_id: str | None
    verdict: str
    review_event_id: str
    revision: int
    numbers: CoverageNumbers
    criteria: list[CoverageCriterion]
    open_criteria: list[str]


class AcceptanceCoverage(ReplayRequest):
    # 可回放（设计说明第 4.1 节）：at 是全局位置，省略时读取现在的事实
    run_id: str


def _criterion(item: Any) -> CoverageCriterion:
    if not isinstance(item, dict):
        raise NotFound("核验结论里的逐条结论不是对象")
    method = str(item.get("method"))
    return CoverageCriterion(
        criterion=str(item.get("criterion")),
        method=method,
        result=str(item.get("result")),
        executable=coverage.method_is_executable(method),
        open=not coverage.method_is_executable(method),
    )


def _acceptance_coverage(application: Application,
                         request: AcceptanceCoverage) -> Snapshot[AcceptanceCoverageResult]:
    store = application.system.store
    through = check_position(application, request.at)
    events = store.list_events(request.run_id, through_position=through)
    reviews = [event for event in events if event.type == EventType.QA_SUBMITTED]
    if not reviews:
        raise NotFound(f"没有核验结论：{request.run_id}")
    event = reviews[-1]
    payload = event.payload or {}
    numbers = payload.get("coverage") or {}
    if not isinstance(numbers, dict) or not numbers:
        raise NotFound(f"这份核验结论没有检验覆盖的数：{event.event_id}")
    return Snapshot[AcceptanceCoverageResult](
        position=store.end_position() if through is None else through,
        data=AcceptanceCoverageResult(
            run_id=request.run_id,
            work_item_id=event.work_item_id,
            verdict=str(payload.get("verdict") or ""),
            review_event_id=event.event_id,
            revision=int(payload.get("revision") or 0),
            numbers=CoverageNumbers(
                criteria_total=int(numbers.get("criteria_total") or 0),
                executable=int(numbers.get("executable") or 0),
                covered=int(numbers.get("covered") or 0),
                coverage_ratio=float(numbers.get("coverage_ratio") or 0.0),
                model_reading=int(numbers.get("model_reading") or 0),
                open=int(numbers.get("open") or 0),
            ),
            criteria=[_criterion(item) for item in payload.get("criteria") or []],
            open_criteria=[str(item) for item in payload.get("open_criteria") or []],
        ),
    )


ACCEPTANCE_COVERAGE = QueryDefinition(
    name="acceptance.coverage", request=AcceptanceCoverage, result=AcceptanceCoverageResult,
    handle=_acceptance_coverage,
    replayable=True,
    # 核验角色提交放行记录（或再次提交）时逐条结论与三个数才变；别的事件不改变这份结果
    changed_by=(EventType.QA_SUBMITTED,),
)
