"""工单 #1394：开环完成（形态与核验角色设计说明「开环完成」「定义的校验」第 4 条；骨架与应用设计说明
「路由契约」；总图第三节「开环完成」、第四节「路由」缝）。

没有核验角色核验最后采纳的成果的定义里（没有核验角色，或者核验角色只核验中途的成果），事项创建时按冻结的
定义标为开环，记进创建事件（字段只增）；它正常结束时结束原因由路由给：路由读创建事件里的标记，给出开环完成，
结果是完成，采纳照常进行、不发决定请求；离开期间的报告与汇总不把它算进「完成与放行」，另起「开环完成」一项。
默认三部门有核验角色核验交付，创建事件的标记为否：行为与事件序列基准都不变；没有声明这个方法的第二种路由
照旧按事项种类取。

层：集成层（每一条都开真实事件库与真实工作区，跑完整的部门循环，模型回答由假模型按部门给出）。
守 R2（骨架事件与对外合同只增：创建事件多一个取值为否的字段、停止原因清单多一条）与 R3（开环完成与放行
分开记、分开算）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from harness import orchestrator, routing_contract, watched_outputs
from harness.adapters.fake import FakeAdapter
from harness.app.application import Application
from harness.app.home import AwayReportRequest
from harness.app.labels import OPEN_LOOP_LABEL, event_label
from harness.app.payloads import RunCreatedPayload
from harness.definitions import (DEFAULT_FORM, DEFINITIONS, VerificationDeclaration, VerifiedOutcomes,
                                 VerifierRole)
from harness.event_store import project_stream
from harness.models import EventType, ProjectEventType
from harness.runtime import LoopSystem
from harness.tests import second_routing
from harness.tests.helpers import delivery_turn, merge_scripts, product_spec, quality_turns
from harness.tightening import WATCHED_OUTPUTS
from harness.watched_outputs import OPEN_LOOP_STOP_REASON
from harness.write_path import NewProjectEvent

GOAL = "做一个可以长期演进的逐行文本处理工具。"

# 没有核验角色的形态（工单 #1402 的形态机制）：定义内容与三部门相同，只有核验声明为空。
# 发布带里「一个角色直做」「几个角色直做」就是这个样子，本单先按成果驱动的那一份核对
OPEN_LOOP_FORM = "three_departments_without_verifier"
OPEN_LOOP_DEFINITIONS = DEFINITIONS.model_copy(update={
    "version": "sha256:three-departments-without-verifier",
    "organization": DEFINITIONS.organization.model_copy(
        update={"verification": VerificationDeclaration(verifiers=())}),
})
# 有核验角色、但它只核验中途的成果（docs/design/forms-and-verifier-role.md「定义的校验」中「开环的标记」后半句）：最后采纳的成果（交付）没有人核验，
# 同样标为开环。核验角色在定义里，检查也是它做，只是它核验的不是交付
MIDWAY_FORM = "three_departments_verifier_of_a_midway_outcome"
MIDWAY_DEFINITIONS = DEFINITIONS.model_copy(update={
    "version": "sha256:three-departments-verifier-of-a-midway-outcome",
    "organization": DEFINITIONS.organization.model_copy(update={"verification": VerificationDeclaration(
        verifiers=(VerifierRole(role="quality", verifies=(
            VerifiedOutcomes(role="engineering", outcomes=("product_spec",)),)),))}),
})
FORMS = {
    DEFAULT_FORM: (DEFINITIONS, WATCHED_OUTPUTS),
    OPEN_LOOP_FORM: (OPEN_LOOP_DEFINITIONS, WATCHED_OUTPUTS),
    MIDWAY_FORM: (MIDWAY_DEFINITIONS, WATCHED_OUTPUTS),
}


def _script() -> dict[str, list[Any]]:
    # 三部门跑完一个事项：产品交 PRD、工程交交付、质检先独立判断再放行
    return {
        "product": [product_spec()],
        "engineering": [delivery_turn(summary="补了用法一节")],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }


def _system(data_dir: Path, script: dict[str, list[Any]] | None = None) -> LoopSystem:
    return LoopSystem.for_testing(data_dir, FakeAdapter(script or _script()), forms=FORMS,
                                  resume_on_startup=False)


def _set_form(system: LoopSystem, project_id: str, previous: str, form: str) -> None:
    # 改形态的命令在 #1402：这里经写入口直接写这条项目事件（与 #1392 的用例同一个做法）
    system.writes.append(project_stream(project_id), NewProjectEvent(
        ProjectEventType.PROJECT_FORM_SET,
        {"previous_form": previous, "form": form, "reason": ""}, actor="user:local"))


def _run_created(system: LoopSystem, run_id: str) -> dict[str, Any]:
    return next(event.payload for event in system.store.list_events(run_id)
                if event.type == EventType.RUN_CREATED)


def _run_done(system: LoopSystem, run_id: str):
    return next(event for event in system.store.list_events(run_id)
                if event.type == EventType.RUN_DONE)


def _decisions(system: LoopSystem, run_id: str) -> list[Any]:
    return [event for event in system.store.list_events(run_id)
            if event.type == EventType.DECISION_REQUESTED]


def test_an_item_without_a_verifier_is_created_open_loop_and_ends_open_loop(tmp_path):
    # 验收第 1 条：没有核验角色的定义跑一个脚本化事项——创建事件标为开环，结束原因是开环完成、
    # 结果是完成，采纳照常进行，全程没有决定请求
    system = _system(tmp_path / "loop")
    project_id = system.projects.register("开环形态", GOAL)
    _set_form(system, project_id, DEFAULT_FORM, OPEN_LOOP_FORM)
    item_id, run_id = system.projects.start_work_item(project_id, "补一份用法说明")

    # 创建事件按冻结的定义算出开环，记在同一个字段里（旧事件没有它时按不是开环读）
    created = _run_created(system, run_id)
    assert created["open_loop"] is True
    assert created["form"] == OPEN_LOOP_FORM
    assert created["work_item_id"] == item_id

    ended = system.run_until_stop(run_id)

    # 结果是完成，结束原因是开环完成：运行结束事件上写明了它
    assert (ended.status, ended.stop_reason) == ("done", "open_loop")
    done = _run_done(system, run_id)
    assert (done.stop_reason, done.state_after) == ("open_loop", "done")
    assert event_label(EventType.RUN_DONE, done.payload) == "运行结束：开环完成"
    assert "放行" not in OPEN_LOOP_LABEL
    # 不因为缺少核验发决定请求
    assert _decisions(system, run_id) == []
    # 采纳照常进行：交付被采纳，项目流上的采纳事件照常写下
    assert system.projects.settle(run_id).type == ProjectEventType.DELIVERABLE_ADOPTED
    system.close()


def test_a_verifier_of_a_midway_outcome_still_marks_the_item_open_loop(tmp_path):
    # 验收第 2 条的后半句（docs/design/forms-and-verifier-role.md「定义的校验」中「开环的标记」）：核验角色只核验中途的成果时，事项最后采纳的成果
    # （交付）没有人核验，创建时同样标为开环，结束时同样写开环完成、不算放行
    system = _system(tmp_path / "loop")
    application = Application(system)
    project_id = system.projects.register("只核验中途成果的形态", GOAL)
    _set_form(system, project_id, DEFAULT_FORM, MIDWAY_FORM)
    _item_id, run_id = system.projects.start_work_item(project_id, "补一份用法说明")

    created = _run_created(system, run_id)
    assert created["form"] == MIDWAY_FORM
    assert created["open_loop"] is True

    ended = system.run_until_stop(run_id)
    assert (ended.status, ended.stop_reason) == ("done", "open_loop")
    assert system.projects.settle(run_id).type == ProjectEventType.DELIVERABLE_ADOPTED
    report = application.query("home.away_report", AwayReportRequest(range="24h")).data
    items = {item.id: item for item in report.summary}
    assert "released" not in items, sorted(items)
    assert items["open_loop"].value == 1
    system.close()


def test_the_default_three_departments_stay_released_and_are_not_marked_open_loop(tmp_path):
    # 验收第 3 条：默认三部门有核验角色，创建事件的标记为否，结束原因照旧是放行
    system = _system(tmp_path / "loop")
    project_id = system.projects.register("默认三部门", GOAL)
    _item_id, run_id = system.projects.start_work_item(project_id, "补一份用法说明")

    created = _run_created(system, run_id)
    assert created["open_loop"] is False
    assert created["form"] == DEFAULT_FORM

    ended = system.run_until_stop(run_id)
    assert (ended.status, ended.stop_reason) == ("done", "released")
    assert system.projects.settle(run_id).type == ProjectEventType.DELIVERABLE_ADOPTED
    system.close()


def test_the_away_report_counts_open_loop_completions_apart_from_releases(tmp_path):
    # 验收第 2 条：报告与汇总里，开环完成的事项不进「完成与放行」，出现在开环完成一项里，中文名写
    # 「开环完成」、没有「放行」二字；放行结束的事项仍在「完成与放行」里
    system = _system(tmp_path / "loop", merge_scripts(_script(), _script()))
    application = Application(system)

    # 一个放行的三部门事项
    released_project = system.projects.register("放行的事项", GOAL)
    _released_item, released_run = system.projects.start_work_item(released_project, "补一份用法说明")
    assert system.run_until_stop(released_run).status == "done"
    assert system.projects.settle(released_run).type == ProjectEventType.DELIVERABLE_ADOPTED

    # 一个开环完成的事项
    open_loop_project = system.projects.register("开环完成的事项", GOAL)
    _set_form(system, open_loop_project, DEFAULT_FORM, OPEN_LOOP_FORM)
    open_loop_item, open_loop_run = system.projects.start_work_item(open_loop_project, "补一份用法说明")
    assert system.run_until_stop(open_loop_run).stop_reason == "open_loop"
    assert system.projects.settle(open_loop_run).type == ProjectEventType.DELIVERABLE_ADOPTED

    report = application.query("home.away_report", AwayReportRequest(range="24h")).data
    items = {item.id: item for item in report.summary}
    # 开环完成另起一项：中文名取自停止原因的定义，值数与来源事件都对
    assert "open_loop" in items, sorted(items)
    open_loop = items["open_loop"]
    assert (open_loop.label, open_loop.unit) == (OPEN_LOOP_LABEL, "项")
    assert open_loop.label == "开环完成" and "放行" not in open_loop.label
    assert open_loop.value == 1
    assert open_loop.refs == [_run_done(system, open_loop_run).position]
    # 放行一项只剩放行结束的那一件事项
    assert "released" in items, sorted(items)
    assert items["released"].value == 1
    assert items["released"].refs
    # 开环完成的事项不管是采纳还是结束原因，都不在「完成与放行」的来源事件里
    released_positions = set(items["released"].refs)
    assert _run_done(system, open_loop_run).position not in released_positions
    adopted = [event for event in system.store.list_project_events(open_loop_project)
               if event.type == ProjectEventType.DELIVERABLE_ADOPTED]
    assert adopted and all(event.position not in released_positions for event in adopted)
    # 关键事实里这条结束按开环完成分类，不按放行
    kinds = {fact.type: fact.kind for fact in report.facts}
    assert kinds[EventType.RUN_DONE] == "open_loop"
    system.close()


def test_a_creation_event_without_the_field_reads_as_not_open_loop():
    # 验收第 5 条：旧事项的创建事件没有这个字段，经真实的读取路径读作「不是开环」——那时只有默认的三部门，
    # 有核验角色。读的是路由取这个事实的那一处（`watched_outputs.recorded_open_loop`，经契约方法
    # `completion_reason` 调用，薄驱动进入完成状态时走的就是这一条）：把那一处的缺省读反，这条用例会失败
    assert RunCreatedPayload.model_fields["open_loop"].default is False
    old = SimpleNamespace(type=EventType.RUN_CREATED, payload={"task": "旧事项", "kind": "change"})
    with_field = SimpleNamespace(type=EventType.RUN_CREATED, payload={"task": "新事项", "open_loop": True})
    view = SimpleNamespace()
    for events, expected in (([old], False), ([with_field], True), ([old, with_field], False)):
        assert watched_outputs.recorded_open_loop(events) is expected
        given = watched_outputs.ROUTING.completion_reason(view, events)
        assert (given is not None) is expected
        assert given is None or given.stop_reason == OPEN_LOOP_STOP_REASON


def test_the_thin_driver_writes_the_completion_reason_the_routing_gives(tmp_path, monkeypatch):
    # 验收第 4 条：结束原因由路由给。薄驱动进入完成状态时问路由、把它给的原因原样写进事实。
    # 让路由对默认三部门（创建时没有标开环）给出开环完成，运行结束事件上就是它——原因不是薄驱动自己判断的；
    # 薄驱动里也没有这个停止原因的名字（取用它的常量已经挪到路由那一侧）
    assert not hasattr(orchestrator, "OPEN_LOOP_STOP_REASON")
    system = _system(tmp_path / "loop")
    project_id = system.projects.register("默认三部门", GOAL)
    _item_id, run_id = system.projects.start_work_item(project_id, "补一份用法说明")
    assert _run_created(system, run_id)["open_loop"] is False
    monkeypatch.setattr(
        watched_outputs.WatchedOutputs, "completion_reason",
        lambda self, view, events: routing_contract.CompletionReason(stop_reason=OPEN_LOOP_STOP_REASON))
    ended = system.run_until_stop(run_id)
    assert (ended.status, ended.stop_reason) == ("done", "open_loop")
    assert _run_done(system, run_id).stop_reason == OPEN_LOOP_STOP_REASON
    system.close()


def test_a_routing_without_the_completion_method_ends_by_the_item_kind(tmp_path, monkeypatch):
    # 验收第 4 条后半：没有声明这个方法的路由照旧按事项种类取（测试里的第二种路由就是这一种）。
    # 把成果驱动的这个方法去掉，标了开环的事项照旧以事项种类的原因结束，与这一改动之前一样
    monkeypatch.delattr(watched_outputs.WatchedOutputs, "completion_reason")
    system = _system(tmp_path / "loop")
    project_id = system.projects.register("开环形态", GOAL)
    _set_form(system, project_id, DEFAULT_FORM, OPEN_LOOP_FORM)
    _item_id, run_id = system.projects.start_work_item(project_id, "补一份用法说明")
    assert _run_created(system, run_id)["open_loop"] is True
    ended = system.run_until_stop(run_id)
    assert (ended.status, ended.stop_reason) == ("done", "released")
    system.close()


def test_the_second_routing_declares_no_completion_reason():
    # 验收第 4 条：测试里的第二种路由（任务池）不改，它不声明这个方法，事项结束照旧由它自己的一份定义给原因
    assert not hasattr(second_routing.ROUTING, "completion_reason")
    assert not hasattr(second_routing.ROUTING, "recorded_open_loop")
