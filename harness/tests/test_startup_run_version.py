# 启动时核对 run 事件版本（ADR-0019，工单 #126）：用一份由较早 run 事件版本写入的数据目录启动，
# 项目、当前 PRD、采纳成果与项目设置完整重建；未结束的 run 记为因升级停止，事项用已采纳成果重新开始并带有
# 「因升级重新开始」的优先级。run 事件版本相同的未结束 run 不被本工单停止（交给 #16 自动继续）。
# 数据目录是真实的 SQLite 事件日志，较早版本由删除 run_created 中的版本字段得到（旧事件没有这个字段）。

import json
import sqlite3

from harness.adapters.fake import FakeAdapter, FakeTurn
from harness.models import EventType, ProjectEventType
from harness.projection import project_run, saved_project
from harness.providers.selection import ModelSelection
from harness.runtime import LoopSystem
from harness.streams import PRIORITY_UPGRADE_RESTART, PRIORITY_USER, RUN_EVENT_VERSION, STOP_REASON_UPGRADE
from harness.tests.helpers import happy_script

def _adopted_project(data_dir):
    # 一个项目：第一个事项完成并被采纳，项目有了当前采纳成果
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    project_id = system.projects.register("升级项目", "核对启动时的版本核对")
    system.projects.configure_department_settings(
        project_id, "engineering", ModelSelection(department_prompt="先写计划再写代码。"), 0)
    system.projects.configure_command(project_id, "lint", ["python", "-m", "flake8"], args=[])
    _work_item_id, run_id = system.projects.start_work_item(project_id, "第一个事项")
    system.run_until_stop(run_id)
    adopted = system.projects.settle(run_id)
    return system, project_id, run_id, adopted

def _second_unfinished_run(system, project_id):
    # 第二个事项：run 未结束就停下（模型脚本已经用完，run 停在非终态）
    _work_item_id, run_id = system.projects.start_work_item(project_id, "第二个事项")
    projection = project_run(system.store, run_id)
    assert projection.phase not in {"DONE", "PAUSED", "FAILED"}
    return run_id

def _older_version_data_dir(data_dir):
    # 得到一份由较早 run 事件版本写入的数据目录：run_created 事件里没有 run 事件版本字段，
    # 保存的投影也一并删掉——启动时由事件重放补建，这与较早版本留下的数据目录一致
    connection = sqlite3.connect(data_dir / "events.sqlite")
    try:
        rows = connection.execute(
            "SELECT event_id, payload_json FROM events WHERE type = ?", (EventType.RUN_CREATED,)).fetchall()
        assert rows, "no run_created events"
        for event_id, payload in rows:
            document = json.loads(payload)
            document.pop("run_event_version", None)
            connection.execute("UPDATE events SET payload_json = ? WHERE event_id = ?",
                               (json.dumps(document, ensure_ascii=False, sort_keys=True), event_id))
        connection.execute("DELETE FROM projections")
        connection.commit()
    finally:
        connection.close()

def test_starting_from_an_older_run_event_version_stops_and_restarts(data_dir):
    system, project_id, first_run, adopted = _adopted_project(data_dir)
    assert adopted is not None and adopted.type == ProjectEventType.DELIVERABLE_ADOPTED
    second_run = _second_unfinished_run(system, project_id)
    before = saved_project(system.store, project_id).to_dict()
    # 项目的长期事实：当前 PRD 与采纳成果、项目部门设置、登记命令
    facts_before = {key: before[key] for key in ("name", "goal", "current_adoption", "adoptions", "department_settings", "commands")}
    adoption_before = system.projects.projection(project_id).current_adoption
    assert adoption_before is not None
    end = system.store.end_position()
    system.close()

    _older_version_data_dir(data_dir)

    # 重启：项目流在任何版本下都完整读取与重建
    adapter = FakeAdapter([])
    restarted = LoopSystem.for_testing(data_dir, adapter)
    # 项目流的长期事实完整重建（重新开始的新事项不改动这些事实）
    after = saved_project(restarted.store, project_id).to_dict()
    assert {key: after[key] for key in facts_before} == facts_before
    project = restarted.projects.projection(project_id)
    assert project.current_adoption is not None
    assert project.current_adoption.adoption_id == adoption_before.adoption_id
    # 项目设置完整重建：部门 Prompt 与登记命令
    assert project.department_settings["engineering"].source == "configured"
    assert "lint" in project.commands
    # 重放不调用模型
    assert adapter.invocations == []

    # 版本不同的未结束 run 记为因升级停止
    stopped = project_run(restarted.store, second_run)
    assert (stopped.phase, stopped.stop_reason) == ("FAILED", STOP_REASON_UPGRADE)
    # 第一个事项已经结束，不因升级停止
    assert project_run(restarted.store, first_run).stop_reason == "released"

    # 对应的事项用已采纳成果重新开始，并记下「因升级重新开始」的优先级
    started = [event for event in restarted.store.list_project_events(project_id)
               if event.type == ProjectEventType.WORK_ITEM_CREATED]
    priorities = [event.payload["priority"] for event in started]
    assert priorities[-1] == PRIORITY_UPGRADE_RESTART
    new_run_id = started[-1].payload["run_id"]
    assert new_run_id != second_run
    new_run = project_run(restarted.store, new_run_id)
    assert new_run.baseline is not None
    assert new_run.baseline["adoption_id"] == adoption_before.adoption_id
    assert new_run.run_event_version == RUN_EVENT_VERSION
    # 旧版本的 run 事件保留供查阅
    assert restarted.store.end_position() > end
    restarted.close()

def test_same_version_unfinished_runs_are_left_to_automatic_continuation(data_dir):
    # run 事件版本相同的未结束 run 不被本工单停止，交给 #16 自动继续
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    project_id = system.projects.register("同版本项目", "核对同版本的启动")
    run_id = _second_unfinished_run(system, project_id)
    system.close()

    # 交给 #16 的同版本未结束 run：启动时被自动继续（不再记为因升级停止）。
    # 这里给一个不会推进 run 的回答，核对它不被版本核对停掉
    restarted = LoopSystem.for_testing(data_dir, FakeAdapter([FakeTurn(transcript="no tool call in this reply")]))
    assert restarted.startup_runs.same_version == (run_id,)
    assert restarted.startup_runs.other_version == ()
    projection = project_run(restarted.store, run_id)
    assert projection.stop_reason != STOP_REASON_UPGRADE
    restarted.close()

def test_a_work_item_created_by_the_user_has_the_user_priority(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    project_id = system.projects.register("优先级", "核对用户新建事项的优先级")
    _work_item_id, run_id = system.projects.start_work_item(project_id, "用户新要求")
    [created] = [event for event in system.store.list_project_events(project_id)
                 if event.type == ProjectEventType.WORK_ITEM_CREATED]
    assert created.payload["priority"] == PRIORITY_USER
    assert project_run(system.store, run_id).run_event_version == RUN_EVENT_VERSION
    system.close()
