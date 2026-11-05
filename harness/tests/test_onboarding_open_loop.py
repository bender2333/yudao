"""工单 #1510：没有核验角色的建档（形态与核验角色设计说明「开环完成」第 6 条；接入已有项目设计说明「总体」
第 4.1 节；项目的组织设计说明「新建的入口」；总图第三节「开环完成」、第四节「定义」缝）。

没有核验角色的组织（一个角色直做）也能接入已有项目：建档由接「建档」这一来源的部门（工程）接，交初始 PRD 与
现有结构说明，**没有基线核验这一步**，交完成以后 run 以开环完成结束；结算照常提出初始 PRD 候选并请用户确认，
确认请求与资料页写明这份基线没有经过基线核验；用户确认以后基线照常采纳，当前有效要求与第一次采纳照常。
默认三部门的建档一点不变：仍然由质检做基线核验、run 以 baseline_verified 结束、确认请求带着基线核验。

层：集成层（每条都开真实事件库与真实工作区，跑完整的部门循环，模型回答由假模型按部门给出）。
守 R1（没有核验角色的组织接得进已有项目：建档的每一步都有，只少核验这一步）与 R3（开环完成与放行分开记：
这条基线在记录上写明没有经过基线核验）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.app.application import Application
from harness.app.labels import NO_BASELINE_REVIEW_LABEL
from harness.app.project_queries import WorkItemMaterials
from harness.definitions import DEFAULT_FORM
from harness.event_store import Command, project_stream
from harness.models import ArtifactRef, EventType, ProjectEventType, new_id
from harness.projection import saved_decisions
from harness.proposals import baseline_review_turn, completion_turn, product_spec, structure_turn
from harness.runtime import SINGLE_ROLE_DIRECT, SINGLE_ROLE_DIRECT_DEFINITIONS, LoopSystem
from harness.tests.onboarding_project import (
    ONBOARDING_GOAL as GOAL,
    ONBOARDING_REQUIREMENT as REQUIREMENT,
    onboarding_source as _source,
)
from harness.watched_outputs import OPEN_LOOP_STOP_REASON
from harness.write_path import NewProjectEvent


def _set_form(system: LoopSystem, project_id: str, previous: str, form: str) -> None:
    # 改形态的命令在 #1402：这里经写入口直接写这条项目事件（与 #1392 的用例同一个做法）
    system.writes.append(project_stream(project_id), NewProjectEvent(
        ProjectEventType.PROJECT_FORM_SET,
        {"previous_form": previous, "form": form, "reason": ""}, actor="user:local"))


def _answer_command() -> Command:
    # 回答决定请求经应用层的命令：测试直接调用流程编排时造一个身份（与 #1392 的用例相同）
    return Command(new_id("cmd"), "decision.answer", "test", "user")


def _single_role_script() -> dict[str, list[Any]]:
    # 一个角色直做的建档：工程先交初始 PRD，再交现有结构说明，最后交完成；第四项给建档以后的普通事项。
    # 没有基线核验这一步，也没有质量这一份回答
    return {"engineering": [
        FakeTurn(proposal=product_spec(requirements=[REQUIREMENT], acceptance=["run the CLI with a word"])),
        structure_turn(requirement_locations=[{"requirement": REQUIREMENT, "locations": ["src/echo.py"]}]),
        completion_turn(summary="写好了初始 PRD 与现有结构说明"),
        completion_turn(summary="补了用法说明"),
    ]}


def _three_departments_script() -> dict[str, list[Any]]:
    # 默认三部门的建档：产品写初始 PRD、工程写结构说明、质检做基线核验（结论全部为已验证）。
    # 质检给两条同一内容的回答（工单 #1255）：结构说明到达前后它各可能被唤醒一次
    return {
        "product": [FakeTurn(proposal=product_spec(requirements=[REQUIREMENT],
                                                   acceptance=["run the CLI with a word"]))],
        "engineering": [structure_turn(requirement_locations=[{"requirement": REQUIREMENT,
                                                               "locations": ["src/echo.py"]}])],
        "quality": [baseline_review_turn(conclusions=[
            {"requirement": REQUIREMENT, "status": "verified", "evidence": "smoke"}]) for _ in range(2)],
    }


def _onboarding(tmp_path: Path, script: dict[str, list[Any]], *, form: str | None) -> tuple[LoopSystem, str, str, str]:
    # 接一个已有项目并开始建档：形态给 form 时先改项目形态（一个角色直做的形态），不给时是默认三部门。
    # 返回系统、项目、事项与建档 run
    system = LoopSystem.for_testing(tmp_path / "loop", FakeAdapter(script), resume_on_startup=False)
    project_id = system.projects.register("已有项目", GOAL, source="existing")
    system.projects.configure_source_directory(project_id, "src", str(_source(tmp_path / "source")),
                                               base_version=0)
    if form is not None:
        _set_form(system, project_id, DEFAULT_FORM, form)
    item_id, run_id = system.projects.restart_onboarding(project_id, "src")
    return system, project_id, item_id, run_id


def _run_created(system: LoopSystem, run_id: str) -> dict[str, Any]:
    return next(event.payload for event in system.store.list_events(run_id)
                if event.type == EventType.RUN_CREATED)


def _project_context(system: LoopSystem, run_id: str) -> str:
    # 这个 run 的项目上下文原文：事项创建时按项目的当前采纳成果写出
    reference = ArtifactRef(**_run_created(system, run_id)["project_context_ref"])
    return system.artifacts.get(reference).decode("utf-8")


def _open_decision(system: LoopSystem):
    _position, open_decisions = saved_decisions(system.store, statuses=("open",))
    [decision] = open_decisions
    return decision


def test_a_single_role_direct_project_onboards_without_a_baseline_review(tmp_path):
    # 验收第 1 条：一个角色直做的项目接入已有仓库——工程接建档、交结构说明与初始 PRD；事件里没有基线核验；
    # 确认请求写明没有经过基线核验；确认以后事项以开环完成结束，建档基线写入项目
    system, project_id, item_id, run_id = _onboarding(tmp_path, _single_role_script(), form=SINGLE_ROLE_DIRECT)
    created = _run_created(system, run_id)
    # 建档按事项冻结的形态建：一个角色直做，创建时按定义标为开环
    assert (created["form"], created["kind"], created["open_loop"]) == (SINGLE_ROLE_DIRECT, "onboarding", True)

    result = system.run_until_stop(run_id)
    assert (result.status, result.stop_reason) == ("done", OPEN_LOOP_STOP_REASON), result.error
    kinds = [event.type for event in system.store.list_events(run_id)]
    assert EventType.SPEC_ACCEPTED in kinds and EventType.STRUCTURE_ACCEPTED in kinds
    # 没有基线核验这一步：run 流里没有这一条接纳事件
    assert EventType.BASELINE_REVIEW_ACCEPTED not in kinds
    assert result.baseline_review is None and result.structure is not None and result.product_spec is not None

    # 结算照常：初始 PRD 候选与确认请求在同一个事务里写入。候选里没有基线核验的内容，
    # 项目流只增加字段（ADR-0019），所以这一份是空记录，另由 baseline_verified 记下没有经过基线核验
    proposed = system.projects.settle(run_id)
    assert proposed is not None and proposed.type == ProjectEventType.INITIAL_PRD_PROPOSED
    candidate = system.projects.projection(project_id).initial_prd_candidates[-1]
    assert candidate.round == 1 and candidate.baseline_verified is False
    assert (candidate.baseline_review["event_id"], candidate.baseline_review["content_hash"]) == ("", "")
    assert candidate.baseline_review["conclusions"] == []
    assert candidate.prd["content_hash"] == result.product_spec.content_hash

    decision = _open_decision(system)
    assert decision.kind == "initial_prd"
    # 确认请求写明这一轮没有经过基线核验
    assert decision.request["baseline_verified"] is False
    assert decision.request["baseline_review"]["content_hash"] == ""
    assert NO_BASELINE_REVIEW_LABEL in decision.request["description"]
    # 资料页同样写明：基线核验是空的一份，另有一句「没有经过基线核验」
    materials = Application(system).query(
        "work_item.materials", WorkItemMaterials(project_id=project_id, work_item=item_id)).data
    [round_view] = materials.onboarding_rounds
    assert (round_view.baseline_review.content_hash, round_view.baseline_review.conclusions) == ("", [])
    assert round_view.baseline_review_note == NO_BASELINE_REVIEW_LABEL

    # 用户确认：基线照常采纳，第一次采纳的成果是快照本身
    system.orchestrator.answer_decision(decision.decision_id, "confirm", None,
                                        base_version=decision.version, command=_answer_command())
    project = system.projects.projection(project_id)
    adoption = project.current_adoption
    assert adoption is not None
    assert (adoption.code_tree_digest, adoption.previous_adoption_id) == (result.snapshot["tree_digest"], None)
    assert adoption.prd_ref == candidate.prd["prd_ref"]
    assert adoption.product_spec_hash == candidate.prd["content_hash"]
    # 采纳记录写明没有经过基线核验；没有这一份产物，现有缺陷、基线检查与已知风险都为空
    assert NO_BASELINE_REVIEW_LABEL in adoption.summary
    assert (adoption.existing_defects, adoption.check_names, adoption.known_risks) == ([], [], [])
    item = project.work_item(item_id)
    assert (item.status, item.stop_reason) == ("adopted", OPEN_LOOP_STOP_REASON)


def test_a_change_item_after_the_open_loop_onboarding_reads_the_current_requirements(tmp_path):
    # 验收第 2 条：建档完成以后再建一个普通事项，读得到当前有效要求，能跑完
    system, project_id, _item_id, run_id = _onboarding(tmp_path, _single_role_script(), form=SINGLE_ROLE_DIRECT)
    assert system.run_until_stop(run_id).status == "done"
    system.projects.settle(run_id)
    decision = _open_decision(system)
    system.orchestrator.answer_decision(decision.decision_id, "confirm", None,
                                        base_version=decision.version, command=_answer_command())
    adoption = system.projects.projection(project_id).current_adoption

    _new_item, new_run = system.projects.start_work_item(project_id, "补一份用法说明")
    finished = system.run_until_stop(new_run)
    assert (finished.status, finished.stop_reason) == ("done", OPEN_LOOP_STOP_REASON), finished.error
    # 当前有效要求来自确认的初始 PRD：项目上下文里带着那条要求与这一版 PRD 的内容摘要
    context = _project_context(system, new_run)
    assert REQUIREMENT in context
    assert adoption.product_spec_hash in context


def test_the_default_three_departments_onboarding_still_has_the_baseline_review(tmp_path):
    # 验收第 3 条：默认三部门的建档一点不变——质检做基线核验，run 以 baseline_verified 结束，
    # 候选与确认请求带着这一份产物，请求上写着经过了基线核验
    system, _project_id, _item_id, run_id = _onboarding(tmp_path, _three_departments_script(), form=None)
    result = system.run_until_stop(run_id)
    assert (result.status, result.stop_reason) == ("done", "baseline_verified"), result.error
    kinds = [event.type for event in system.store.list_events(run_id)]
    assert EventType.BASELINE_REVIEW_ACCEPTED in kinds
    assert system.projects.settle(run_id).type == ProjectEventType.INITIAL_PRD_PROPOSED
    decision = _open_decision(system)
    assert decision.request["baseline_verified"] is True
    assert decision.request["baseline_review"]["content_hash"] == result.baseline_review["content_hash"]
    assert NO_BASELINE_REVIEW_LABEL not in decision.request["description"]


def test_the_single_role_direct_form_defines_the_onboarding_kind_without_a_baseline_review():
    # 定义里建档这一种：接「建档」这一来源的是工程，交初始 PRD、现有结构说明与交完成，没有基线核验；
    # run 以开环完成结束；这份形态的交完成仍然是事项最后采纳的那一份
    definitions = SINGLE_ROLE_DIRECT_DEFINITIONS
    work = definitions.work_item("onboarding")
    assert work.stop_reason == OPEN_LOOP_STOP_REASON
    assert definitions.item_source("onboarding") == "onboarding"
    assert definitions.source_department("onboarding") == "engineering"
    tools = set(definitions.tools_for("engineering", "onboarding"))
    assert {"submit_product_spec", "submit_structure", "submit_completion"} <= tools
    assert "submit_baseline_review" not in tools
    assert not (tools & {"write_file", "edit_range", "delete_file", "move_file"})
    assert definitions.is_open_loop(definitions.routing_definition().final_outcome)
    # 普通事项仍然只有交完成：建档的两份产物不出现在这一种里
    assert set(definitions.proposal_contract("engineering", "change")["submit_tools"]) == {"submit_completion"}
