# 检验覆盖的查询与离开期间的报告新增的两项（工单 #399；应用层与接口层设计说明第 4.3 节
# `acceptance.coverage` 与 System 首页；验证的独立性设计说明第 7、7.1 节）。
#
# 这里核对：查询读的是放行记录里一次算好的数与逐条结论（不重新计算），逐条结论带检验方式与结果、
# 开环明细；按位置回放同一段事件流得到同一份结果，放行之前的那个位置没有结果；
# 离开期间的报告多出「收敛状态的变化」与「带开环条件的放行」两项，开环明细列出条件编号。
#
# 层：模块层（真实事件日志、真实运行与假模型脚本，三次 activate_once；不进完整的三部门循环）。
# 守 R2（查询交换的字段与位置）与 R3（验收条件的检验方式、开环与放行的口径）。

from __future__ import annotations

import pytest

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.app.coverage_queries import AcceptanceCoverage
from harness.app.home import AwayReportRequest
from harness.app.project_queries import NotFound
from harness.models import EventType
from harness.proposals import delivery_turn, judgement_turn, product_spec, review_turn
from harness.runtime import LoopSystem
from harness.tests.helpers import explore_turn

GOAL = "把文本按行处理清楚"
ACCEPTANCE = ["打印传入的文本", "空参数时打印用法", "退出码为 0"]


def _criteria() -> list[dict]:
    # 三条验收条件：一条命令检查（可执行、通过）、一条带参照材料的判定点（模型阅读、无法运行）、
    # 一条开环。可执行检验的条件放行时必须是 passed，不可执行的可以是 unverified（第 7.1 节第 3 点）
    return [
        {"criterion": "AC1", "method": "check", "result": "passed", "checks": ["smoke"],
         "trial_cases": [], "note": ""},
        {"criterion": "AC2", "method": "judgement", "result": "unverified", "checks": [],
         "trial_cases": [], "note": "对照 Usage 段落人读"},
        {"criterion": "AC3", "method": "open", "result": "unverified", "checks": [],
         "trial_cases": [], "note": "没有可执行的检验"},
    ]


def _script() -> dict:
    return {
        "product": [product_spec(acceptance=ACCEPTANCE)],
        "engineering": [delivery_turn()],
        # 先判断后看解释（工单 #358）：交付到达以后先交独立判断（一轮），再带本激活的检查回执下结论
        "quality": [explore_turn(), judgement_turn(checks={"smoke": 0}),
                    review_turn("release", "checks passed on the current snapshot",
                                checks={"smoke": 0}, criteria=_criteria())],
    }


def _finished_run(tmp_path) -> tuple[LoopSystem, Application, str, str]:
    # 一个跑完的三部门事项：产品提交合同、工程交付、质检放行（带开环条件）
    system = LoopSystem.for_testing(tmp_path / "data", FakeAdapter(_script()))
    project_id = system.projects.register("覆盖", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, "做一件事")
    for _ in range(6):
        if system.project(run_id).status in ("done", "failed"):
            break
        system.activate_once(run_id)
    assert system.project(run_id).status == "done", system.project(run_id).stop_reason
    return system, Application(system), work_item_id, run_id


def _review_event(system: LoopSystem, run_id: str):
    events = [event for event in system.store.list_events(run_id) if event.type == EventType.QA_SUBMITTED]
    assert events
    return events[-1]


def test_the_query_reads_the_numbers_and_criteria_the_release_recorded(tmp_path):
    system, application, work_item_id, run_id = _finished_run(tmp_path)
    try:
        snapshot = application.query("acceptance.coverage", AcceptanceCoverage(run_id=run_id))
    finally:
        pass
    data = snapshot.data
    stored = _review_event(system, run_id).payload
    assert data.run_id == run_id and data.work_item_id == work_item_id
    assert data.verdict == "release"
    assert data.review_event_id == _review_event(system, run_id).event_id
    # 三个数与放行记录里存的那一份逐项相同：查询不重新计算
    recorded = stored["coverage"]
    assert data.numbers.model_dump() == {key: recorded[key] for key in data.numbers.model_dump()}
    assert data.numbers.criteria_total == 3 and data.numbers.executable == 1
    assert data.numbers.covered == 1 and data.numbers.model_reading == 1 and data.numbers.open == 2
    # 逐条结论：方式、结果、是否可执行、是否开环
    assert [(row.criterion, row.method, row.result, row.executable, row.open) for row in data.criteria] == [
        ("AC1", "check", "passed", True, False),
        ("AC2", "judgement", "unverified", False, True),
        ("AC3", "open", "unverified", False, True),
    ]
    # 开环明细取自放行记录
    assert data.open_criteria == stored["open_criteria"] == ["AC2", "AC3"]


def test_the_query_replays_to_a_position_and_has_nothing_before_the_release(tmp_path):
    system, application, _work_item_id, run_id = _finished_run(tmp_path)
    review = _review_event(system, run_id)
    now = application.query("acceptance.coverage", AcceptanceCoverage(run_id=run_id))
    replayed = application.query("acceptance.coverage", AcceptanceCoverage(run_id=run_id, at=review.position))
    assert replayed.position == review.position
    assert replayed.data == now.data
    with pytest.raises(NotFound):
        application.query("acceptance.coverage", AcceptanceCoverage(run_id=run_id, at=review.position - 1))
    with pytest.raises(NotFound):
        application.query("acceptance.coverage", AcceptanceCoverage(run_id="run_missing"))


def test_the_away_report_lists_open_releases_with_their_criteria(tmp_path):
    system, application, work_item_id, run_id = _finished_run(tmp_path)
    report = application.query("home.away_report", AwayReportRequest(range="24h")).data
    items = {item.id: item for item in report.summary}
    assert "open_release" in items, sorted(items)
    open_release = items["open_release"]
    assert open_release.value == 1 and open_release.unit and open_release.refs
    assert open_release.refs == [_review_event(system, run_id).position]
    assert "AC2" in (open_release.detail or "") and "AC3" in (open_release.detail or "")
    assert work_item_id in (open_release.detail or "")


def test_the_away_report_lists_the_changes_of_the_convergence_state(tmp_path):
    system, application, work_item_id, run_id = _finished_run(tmp_path)
    report = application.query("home.away_report", AwayReportRequest(range="24h")).data
    items = {item.id: item for item in report.summary}
    assert "convergence" in items, sorted(items)
    convergence = items["convergence"]
    assert convergence.value >= 1 and convergence.unit and convergence.refs
    assert work_item_id in (convergence.detail or "")
    # 范围内没有事件时不出现这一项（自上次查看且刚看过）
    end = system.store.end_position()
    assert system.mark_seen(end) == end
    quiet = application.query("home.away_report", AwayReportRequest(range="since_seen")).data
    assert "convergence" not in {item.id for item in quiet.summary}
