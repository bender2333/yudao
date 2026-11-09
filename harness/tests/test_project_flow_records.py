# 工单 #1636：project.flow 的每条记录带第几轮，并增加你的输入、指导与放行三类记录。
# 轮次取自产生这条记录的那次主线激活；询问分支的激活不算一轮（循环结构 docs/design/department-loop.md「询问分支」）。
# 放行写明核验的是交付的哪一版（应用层与接口层 docs/design/app-and-interface.md「项目页四层读哪个查询」）。
#
# 守 R3（测试分层 docs/design/test-pyramid.md「测试按三环留」）：时序图按轮次折叠、按你的输入与指导摊开，
# 这些是路线图阶段二已经走到的行为；记录的种类、方向、轮次都经 project.flow 这一份对外合同看，不看内部行。

from __future__ import annotations

from typing import Any

from harness.adapters.fake import FakeAdapter, prompt_part
from harness.app.application import Application
from harness.app.project_queries import ProjectFlow, ProjectLoop
from harness.models import EventType
from harness.proposals import (
    answer_turn, ask_turn, delivery_turn, judgement_turn, product_spec, review_turn,
)
from harness.runtime import LoopSystem
from harness.tests.helpers import explore_turn, guidance_reply, quality_turns

GOAL = "把文本按行处理清楚"
INITIAL_INPUT = "做一件事"
EXTRA_INPUT = "再补一句：空输入也要打印一行。"
GUIDANCE = "请优先检查空输入。"


def _system(data_dir, script) -> LoopSystem:
    return LoopSystem.for_testing(data_dir, FakeAdapter(script))


def _flow(application: Application, project_id: str, work_item_id: str):
    return application.query("project.flow", ProjectFlow(project_id=project_id, work_item=work_item_id))


def _of_kind(records, kind: str):
    return [record for record in records if record.kind == kind]


def _rework_then_release_script() -> dict[str, list[Any]]:
    # 产品交一版 PRD、工程交付、质检退回、工程返工后再交付、质检放行：打回前后的轮次在这里看得出来
    return {
        "product": [product_spec()],
        "engineering": [delivery_turn(), delivery_turn(summary="处理空输入")],
        "quality": [
            explore_turn(),
            judgement_turn(),
            review_turn("rework_engineering", "质检退回",
                        defects=[{"severity": "minor", "summary": "空输入需要处理"}]),
            judgement_turn(),
            review_turn("release", "revised delivery checked"),
        ],
    }


def test_every_flow_record_carries_the_round_and_a_rework_puts_the_next_records_one_round_later(data_dir):
    # 验收第 1 条：走完产品、工程、质检、打回、再交付、放行的事项，按事项取 project.flow，
    # 每条记录都有第几轮；打回之后的记录轮次都大于打回那一条
    system = _system(data_dir, _rework_then_release_script())
    project_id = system.projects.register("轮次", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, INITIAL_INPUT)
    system.run_until_stop(run_id)
    application = Application(system)

    records = _flow(application, project_id, work_item_id).data.records
    # 场景确实走完了打回与放行
    assert _of_kind(records, "问题反馈"), [record.kind for record in records]
    assert _of_kind(records, "放行"), [record.kind for record in records]
    # 每条记录都有第几轮：事项创建时的那条是第 0 轮（还没有开始工作），其余来自产生它的那次激活
    assert all(isinstance(record.round, int) for record in records)
    created = _of_kind(records, "你的输入")
    assert [record.round for record in created] == [0]
    assert all(record.round >= 1 for record in records if record not in created)
    # 打回之后的每一条记录轮次都加一：返工交付与放行在新的激活里
    rework = _of_kind(records, "问题反馈")[0]
    after = [record for record in records if record.position > rework.position]
    assert after, "打回之后还有记录"
    assert all(record.round > rework.round for record in after), [
        (record.kind, record.round) for record in after]
    # 轮次与 project.loop 的事项轮次同一口径：最大轮次就是主线激活的次数
    loop = application.query("project.loop", ProjectLoop(project_id=project_id, work_item=work_item_id))
    assert max(record.round for record in records) == loop.data.work_items[0].round
    assert loop.data.work_items[0].round == system.project(run_id).cycle_count


def _deliver_once_the_spec_is_accepted():
    # 指导先到的那一轮还没有 PRD 可以依据：以文字回答收尾；PRD 被接纳以后的那一轮正常交付
    def turn(call):
        if not prompt_part(call, "current_product_spec"):
            return guidance_reply("看过指导，等 PRD 被接纳以后再交付。")(call)
        return delivery_turn()(call)

    return turn


def test_the_flow_records_your_input_your_guidance_and_the_release_with_the_delivery_version(data_dir):
    # 验收第 2 条：你的输入、追加输入、发给某个职能的指导、放行各有一条记录，时间与方向对；
    # 放行写明核验的是哪一版交付
    system = _system(data_dir, {
        "product": [product_spec()],
        # 指导先到的那一轮与 PRD 被接纳以后的那一轮各取一项（指导先到时以文字回答收尾）
        "engineering": [_deliver_once_the_spec_is_accepted()] * 3,
        "quality": quality_turns("release", "checks passed"),
    })
    project_id = system.projects.register("输入与指导", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, INITIAL_INPUT)
    # 指导发给工程、追加输入发给产品：都在第一轮工作开始之前写好，到达哪个部门由事件自己带着
    system.add_guidance(run_id, "engineering", GUIDANCE)
    system.add_input(run_id, EXTRA_INPUT)
    system.run_until_stop(run_id)
    application = Application(system)

    records = _flow(application, project_id, work_item_id).data.records
    # 你的输入：新事项的那一句与追加的那一句各一条，都发给收输入的部门，来源不是某个部门（是你）
    inputs = _of_kind(records, "你的输入")
    assert [(record.content, record.direction_to, record.direction_from) for record in inputs] == [
        (INITIAL_INPUT, "product", None),
        (EXTRA_INPUT, "product", None),
    ]
    assert inputs[0].created_at <= inputs[1].created_at
    assert inputs[0].status == inputs[1].status == "已收到"    # 指导：一条，发给收到它的那个职能；时间在事项创建之后（这条指导在第一次工作之前写好）
    guidance = _of_kind(records, "指导")
    assert [(record.content, record.direction_to, record.direction_from) for record in guidance] == [
        (GUIDANCE, "engineering", None),
    ]
    assert guidance[0].created_at > inputs[0].created_at
    assert inputs[0].created_at <= inputs[1].created_at
    # 放行：一条，质检 → 交付的那个职能，写明核验的是哪一版
    released = _of_kind(records, "放行")
    assert len(released) == 1, [(record.kind, record.content) for record in records]
    release = released[0]
    assert (release.direction_from, release.direction_to) == ("quality", "engineering")
    assert release.status == "已放行"
    deliveries = [event for event in system.store.list_events(run_id)
                  if event.type == EventType.DELIVERY_ACCEPTED]
    assert f"第 {deliveries[-1].payload['revision']} 版" in release.content
    # 放行的记录排在最后那一版交付之后
    assert release.position > deliveries[-1].position


def test_records_inside_an_ask_branch_do_not_add_a_round(data_dir):
    # 验收第 3 条：询问分支里发生的记录不让轮次增加。质检在工程交付的那一轮里向工程发问，
    # 询问与它同一轮里的退回结论、分支里的回答都在同一轮；轮次的最大值仍是主线激活的次数
    system = _system(data_dir, {
        "product": [product_spec()],
        "engineering": [delivery_turn(), delivery_turn(summary="处理空输入")],
        "quality": [
            ask_turn(recipient="engineering",
                     question="Which acceptance line governs the rework?",
                     background="Quality is preparing its verdict.",
                     expected="Name the acceptance line to follow."),
            explore_turn(),
            judgement_turn(),
            review_turn("rework_engineering", "质检退回",
                        defects=[{"severity": "minor", "summary": "空输入需要处理"}]),
            judgement_turn(),
            review_turn("release", "revised delivery checked"),
        ],
        "engineering:ask": [answer_turn("Follow the acceptance line recorded in the requirement.")],
    })
    project_id = system.projects.register("询问分支", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, INITIAL_INPUT)
    system.run_until_stop(run_id)
    application = Application(system)

    records = _flow(application, project_id, work_item_id).data.records
    asked = _of_kind(records, "询问")
    assert [record.status for record in asked] == ["已回答"]
    rework = _of_kind(records, "问题反馈")[0]
    events = system.store.list_events(run_id)
    branches = {event.payload["branch_session_id"] for event in events
                if event.type == EventType.ASK_STARTED}
    activations = [event for event in events if event.type == EventType.DEPARTMENT_ACTIVATED]
    # 场景里确实有一次询问分支的激活，否则这条用例证明不了什么
    assert any(event.session_id in branches for event in activations)
    # 第几轮就是这条记录之前的主线激活次数：分支会话的激活不在其中
    def main_activations_before(position: int) -> int:
        return len([event for event in activations
                    if event.position < position and event.session_id not in branches])

    assert asked[0].round == main_activations_before(asked[0].position)
    assert rework.round == main_activations_before(rework.position)
    # 分支的激活若算一轮，后面记录的轮次会超过主线激活的次数
    assert max(record.round for record in records) == len(
        [event for event in activations if event.session_id not in branches])
    loop = application.query("project.loop", ProjectLoop(project_id=project_id, work_item=work_item_id))
    assert loop.data.work_items[0].round == system.project(run_id).cycle_count


def test_old_events_rebuild_the_same_records_and_the_replay_does_not_change(data_dir):
    # 验收第 4 条：老事件重建读取模型以后结果与新写入的一致；重放不变
    system = _system(data_dir, _rework_then_release_script())
    project_id = system.projects.register("重建", GOAL)
    work_item_id, run_id = system.projects.start_work_item(project_id, INITIAL_INPUT)
    system.run_until_stop(run_id)
    application = Application(system)
    written = _flow(application, project_id, work_item_id)

    # 删掉读取模型以后按老事件重放重建：轮次、种类与方向都与新写入的一致
    application.rebuild_read_models()
    rebuilt = _flow(application, project_id, work_item_id)
    assert [record.model_dump() for record in rebuilt.data.records] == [
        record.model_dump() for record in written.data.records]
    assert rebuilt.position == written.position
    # 再重建一次：重放不变
    application.rebuild_read_models()
    assert [record.model_dump() for record in _flow(application, project_id, work_item_id).data.records] == [
        record.model_dump() for record in written.data.records]

    # 另起一份只读打开：读取模型在内存里从同一批老事件重建，结果相同
    system.close()
    readonly = Application.open_readonly(data_dir)
    try:
        assert [record.model_dump() for record
                in _flow(readonly, project_id, work_item_id).data.records] == [
            record.model_dump() for record in written.data.records]
    finally:
        readonly.close()
