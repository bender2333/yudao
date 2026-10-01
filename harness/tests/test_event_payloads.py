import pytest

from harness.adapters.fake import FakeAdapter
from harness.models import EventType, ProjectEventType
from harness.proposals import delivery_turn, plan_turn, product_spec, review_turn
from harness.providers.selection import ModelSelection
from harness.runtime import LoopSystem
from harness.tests.contract_checks import assert_payloads_follow_contract

# 应用层合同中的事件载荷类型与控制核心实际写入的载荷一致。run 事件的各种路径由事件序列对照的全部场景核对
# （test_event_sequence.py），这里从系统整体运行一个项目：登记、配置、材料、归档与恢复、事项开始失败、
# 两个事项一个采纳一个保留为未采纳候选，核对日志中的每条事件。


def _release_script(summary, files=None):
    return [product_spec(), plan_turn(), delivery_turn(summary=summary, files=files),
            review_turn("release", f"ok {summary}")]


def test_every_event_of_a_project_follows_the_payload_contract(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter([
        *_release_script("A"), *_release_script("B", files={"src/echo.py": "print('B')\n"}),
    ]))
    projects = system.projects
    project_id = projects.register("载荷", "核对每种事件的载荷")
    projects.rename(project_id, "载荷核对")
    projects.set_goal(project_id, "核对修改以后的长期目标")
    projects.pin(project_id, True)
    projects.configure_department_settings(
        project_id, "engineering", ModelSelection(department_prompt="先写计划再写代码。"), 0)
    projects.configure_command(project_id, "unit-tests", ["python", "-m", "unittest"], args=["-v"])
    projects.record_material(project_id, "一段原文", department="product")
    projects.record_material(project_id, "不属于部门的原文")
    projects.configure_source_directory(project_id, "src", "C:/repo/src", base_version=0)
    projects.archive(project_id)
    projects.restore(project_id)
    with pytest.raises(ValueError, match="max_cycles"):
        projects.start_work_item(project_id, "开始失败的事项", max_cycles=0)
    _work_item_a, run_a = projects.start_work_item(project_id, "事项 A")
    _work_item_b, run_b = projects.start_work_item(project_id, "事项 B（在 A 采纳前创建）")
    assert system.run_until_stop(run_a).phase == "DONE"
    assert projects.settle(run_a).type == ProjectEventType.DELIVERABLE_ADOPTED
    assert system.run_until_stop(run_b).phase == "DONE"
    assert projects.settle(run_b).type == ProjectEventType.ADOPTION_HELD

    events = system.store.read(0, limit=100_000)
    written = {event.type for event in events}
    assert {value for key, value in vars(ProjectEventType).items() if not key.startswith("_")} <= written
    assert {EventType.RUN_CREATED, EventType.DELIVERY_ACCEPTED, EventType.QA_SUBMITTED, EventType.RUN_DONE} <= written
    assert_payloads_follow_contract(events)
