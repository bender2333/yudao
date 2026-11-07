# 检验覆盖的查询与离开期间的报告新增的两项（工单 #399；应用层与接口层 docs/design/app-and-interface.md「查询清单」
# `acceptance.coverage` 与 System 首页；验证的独立性 docs/design/independent-verification.md「检验覆盖与开环」、「口径」）。
#
# 这里核对：查询读的是放行记录里一次算好的数与逐条结论（不重新计算），逐条结论带检验方式与结果、
# 开环明细；按位置回放同一段事件流得到同一份结果，放行之前的那个位置没有结果；
# 离开期间的报告多出「收敛状态的变化」与「带开环条件的放行」两项，开环明细列出条件编号。
# 两项的明细按事项标题写、不出现 wi_ 与 run_ 标识，另给只增的结构化字段（工单 #1583）。
#
# 层：模块层（真实事件日志、真实运行与假模型脚本，三次 activate_once；不进完整的三部门循环）。
# 守 R2（查询交换的字段与位置）与 R3（验收条件的检验方式、开环与放行的口径）。

from __future__ import annotations

import json
import sys

import pytest

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.app.coverage_queries import AcceptanceCoverage
from harness.app.home import (AwayReportRequest, LAYER_NAMES, ReportEntry, ReportItem, STATE_NAMES,
                              UNNAMED_WORK_ITEM, _convergence_detail, _open_release_detail)
from harness.app.project_queries import NotFound
from harness.models import EventType, json_dumps
from harness.providers.call import ModelResponse
from harness.proposals import delivery_turn, judgement_turn, product_spec, review_turn
from harness.runtime import LoopSystem
from harness.tests.helpers import explore_turn

GOAL = "把文本按行处理清楚"
ACCEPTANCE = ["打印传入的文本", "空参数时打印用法", "退出码为 0"]
# 交付检查跑交付里的新文件（工单 #1181）：起点树还没有它，基线副本（起点树，声明不带交付文件）上
# 这条命令失败，交付快照上通过——这一条检验满足「基线失败、交付通过」，计入覆盖
PYTHON = sys.executable.replace("\\", "/")
SMOKE_COMMAND = f'"{PYTHON}" src/lib.py'


def _criteria() -> list[dict]:
    # 三条验收条件：一条命令检查（可执行、通过）、一条带参照材料的判定点（模型阅读、无法运行）、
    # 一条开环。可执行检验的条件放行时必须是 passed，不可执行的可以是 unverified（docs/design/independent-verification.md「口径」第 3 点）
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
        "engineering": [delivery_turn(files={"src/lib.py": "print('delivered')\n"},
                                      checks={"smoke": {"command": SMOKE_COMMAND}})],
        # 先判断后看解释（工单 #358）：交付到达以后先交独立判断（一轮），再带本激活的检查回执下结论。
        # 判断的逐条结论与结论相同（工单 #1190 比对两者：结果不同的条目要写改判理由，这里没有改判）。
        # 检验的有效性（工单 #1181）：下结论以前用 run_baseline_check 在基线副本上跑同名的交付检查；
        # 声明不带交付文件，基线副本只有事项起点树（本项目还没有起点）——命令失败，交付通过
        "quality": [explore_turn(),
                    _baseline_turn,
                    judgement_turn(checks={"smoke": 0}, criteria=_criteria()),
                    review_turn("release", "checks passed on the current snapshot",
                                checks={"smoke": 0}, criteria=_criteria())],
    }


def _baseline_turn(call) -> ModelResponse:
    # 基线检查的假模型轮：主机在基线副本上运行同名交付检查记录的命令（工单 #1181）
    return ModelResponse(output=[{
        "id": "qa-baseline", "call_id": "qa-baseline", "type": "function_call", "name": "run_baseline_check",
        "arguments": json_dumps({"name": "smoke"}),
    }])


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
    # 三个数与放行记录里存的那一份逐项相同：查询不重新计算。
    # 这一次激活没有跑基线检查（工单 #1181）：命令检查的覆盖不计入分子，基线明细写明缺少回执
    recorded = stored["coverage"]
    assert data.numbers.model_dump() == {key: recorded[key] for key in data.numbers.model_dump()}
    assert data.numbers.criteria_total == 3 and data.numbers.executable == 1
    assert data.numbers.covered == 1 and data.numbers.model_reading == 1 and data.numbers.open == 2
    assert stored["coverage"]["baseline_valid"] is True
    assert stored["baseline_checks"] == [{"criterion": "AC1", "checks": "smoke", "outcome": "failed"}]
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
    project_id = system.project(run_id).project_id
    report = application.query("home.away_report", AwayReportRequest(range="24h")).data
    items = {item.id: item for item in report.summary}
    assert "open_release" in items, sorted(items)
    open_release = items["open_release"]
    assert open_release.value == 1 and open_release.unit and open_release.refs
    assert open_release.refs == [_review_event(system, run_id).position]
    detail = open_release.detail or ""
    # 明细按事项标题写，不出现事项标识与 run 标识（工单 #1583）
    assert "做一件事" in detail
    assert "AC2" in detail and "AC3" in detail
    assert work_item_id not in detail and run_id not in detail
    assert "wi_" not in detail and "run_" not in detail
    # 只增的结构化字段给出事项标识、所在项目与开环条件，供页面拼文字与回链
    [entry] = open_release.entries or []
    assert entry.work_item_id == work_item_id
    assert entry.project_id == project_id
    assert entry.open_criteria == ["AC2", "AC3"]
    assert entry.layer is None and entry.state_from is None and entry.state_to is None


def test_the_away_report_lists_the_changes_of_the_convergence_state(tmp_path):
    system, application, work_item_id, run_id = _finished_run(tmp_path)
    project_id = system.project(run_id).project_id
    report = application.query("home.away_report", AwayReportRequest(range="24h")).data
    items = {item.id: item for item in report.summary}
    assert "convergence" in items, sorted(items)
    convergence = items["convergence"]
    assert convergence.value >= 1 and convergence.unit and convergence.refs
    detail = convergence.detail or ""
    # 明细按事项标题写，层名与状态名是中文，不出现事项标识与 run 标识（工单 #1583）
    assert "做一件事" in detail
    assert work_item_id not in detail and run_id not in detail
    assert "wi_" not in detail and "run_" not in detail
    assert convergence.entries
    for entry in convergence.entries:
        assert entry.work_item_id == work_item_id
        assert entry.project_id == project_id
        assert entry.layer in LAYER_NAMES.values()
        assert entry.state_from in STATE_NAMES.values()
        assert entry.state_to in STATE_NAMES.values()
        assert entry.state_from != entry.state_to
        assert f"{entry.layer}：{entry.state_from} → {entry.state_to}" in detail
    # 范围内没有事件时不出现这一项（自上次查看且刚看过）
    end = system.store.end_position()
    assert system.mark_seen(end) == end
    quiet = application.query("home.away_report", AwayReportRequest(range="since_seen")).data
    assert "convergence" not in {item.id for item in quiet.summary}


def test_two_details_write_the_unnamed_work_item_when_the_title_is_missing():
    # 标题取不到时写「未命名事项」，不拿事项标识凑数（工单 #1583 验收第 1 条）
    release_entry = ReportEntry(work_item_id="wi_missing", project_id="proj_missing", open_criteria=["AC1"])
    release_detail = _open_release_detail([release_entry], {})
    assert release_detail == f"{UNNAMED_WORK_ITEM}：AC1"
    change = ReportEntry(work_item_id="wi_missing", project_id="proj_missing", layer="部门之间的循环",
                         state_from="无法判定", state_to="收敛中")
    convergence_detail = _convergence_detail([change], {})
    assert convergence_detail == f"{UNNAMED_WORK_ITEM} · 部门之间的循环：无法判定 → 收敛中"
    for text in (release_detail, convergence_detail):
        assert "wi_" not in text and "run_" not in text


def test_report_items_without_the_new_optional_fields_still_load():
    # 只增的可选字段：旧读取方拿到的 JSON 没有 entries 时照样读得回来（工单 #1583 验收第 2 条）
    item = ReportItem.model_validate({
        "id": "usage", "label": "用量", "value": 3, "unit": "token", "refs": [1, 2], "detail": "2 次模型请求",
    })
    assert item.entries is None
