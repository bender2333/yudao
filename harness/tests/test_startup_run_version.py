# 启动时 run 事件版本不同的处理（ADR-0019，恢复契约第 1 节，工单 #322）：用一份由较早 run 事件版本写入的
# 数据目录启动，版本不同的未结束 run 记为因升级停止，对应的事项用项目的起点重新开始并排在队列最前面，
# 没有决定请求；重新开始以后的 run 由启动序列自动继续到结束。版本相同的未结束 run 与已结束的 run 不受影响。
# 数据目录是真实的 SQLite 事件日志，较早版本由删除 run_created 中的版本字段得到（旧事件没有这个字段）。

import json
import sqlite3

from harness.adapters.fake import FakeAdapter
from harness.event_store import run_stream
from harness.models import EventType, ProjectEventType
from harness.project_projection import saved_project
from harness.projection import project_run
from harness.providers.selection import ModelSelection
from harness.proposals import baseline_review_turn, product_spec, structure_turn
from harness.runtime import LoopSystem
from harness.streams import PRIORITY_UPGRADE_RESTART, PRIORITY_USER, RUN_EVENT_VERSION, STOP_REASON_UPGRADE
from harness.tests.helpers import happy_script

REQUIREMENT = "print the given argument to stdout"
ECHO_FILE = "src/echo.py"


def _adopted_project(data_dir):
    # 一个项目：第一个事项完成并被采纳，项目有了当前采纳成果
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    project_id = system.projects.register("升级项目", "核对启动时的版本核对")
    system.projects.configure_department_settings(
        project_id, "engineering", ModelSelection(department_prompt="先写计划再写代码。"), 0)
    _work_item_id, run_id = system.projects.start_work_item(project_id, "第一个事项")
    system.run_until_stop(run_id)
    adopted = system.projects.settle(run_id)
    return system, project_id, run_id, adopted


def _unstarted_run(system, project_id):
    # 第二个事项：登记以后还没有执行，run 停在非终态
    _work_item_id, run_id = system.projects.start_work_item(project_id, "第二个事项")
    projection = project_run(system.store, run_id)
    assert projection.status not in {"done", "paused", "failed"}, projection.status
    return run_id


def _older_version_runs(data_dir, run_ids):
    # 得到一份由较早 run 事件版本写入的数据目录：给出的 run 的 run_created 事件里没有 run 事件版本字段，
    # 保存的投影一并删掉——启动时由事件重放补建，这与较早版本留下的数据目录一致
    connection = sqlite3.connect(data_dir / "events.sqlite")
    try:
        rows = connection.execute(
            "SELECT event_id, run_id, payload_json FROM events WHERE type = ?",
            (EventType.RUN_CREATED,)).fetchall()
        changed = 0
        for event_id, run_id, payload in rows:
            if run_id not in run_ids:
                continue
            document = json.loads(payload)
            document.pop("run_event_version", None)
            connection.execute("UPDATE events SET payload_json = ? WHERE event_id = ?",
                               (json.dumps(document, ensure_ascii=False, sort_keys=True), event_id))
            changed += 1
        assert changed == len(run_ids), changed
        connection.execute("DELETE FROM projections")
        connection.commit()
    finally:
        connection.close()


def _source(root):
    # 一份最小的已有项目：建档 run 从它的快照开始
    (root / "src").mkdir(parents=True)
    (root / "src" / "echo.py").write_text("import sys\nprint(sys.argv[1])\n", encoding="utf-8")
    (root / "README.md").write_text("# Echo\n", encoding="utf-8")
    return root


def _onboarding_script():
    # 脚本按部门给出（工单 #557、#879）：PRD 被接纳以后工程与质检同时开始一轮工作，
    # 一条按先后排队的列表脚本被两个部门取用时谁拿到哪一项随调度变化
    return {
        "product": [product_spec(requirements=[REQUIREMENT], acceptance=["run the CLI with a word"])],
        "engineering": [structure_turn(requirement_locations=[{"requirement": REQUIREMENT, "locations": [ECHO_FILE]}])],
        "quality": [baseline_review_turn(conclusions=[{"requirement": REQUIREMENT, "status": "verified",
                                                      "evidence": "smoke"}])],
    }


def _started_work_items(system, project_id):
    return [event for event in system.store.list_project_events(project_id)
            if event.type == ProjectEventType.WORK_ITEM_CREATED]


def _definitions_changed(system, run_id):
    return [decision for decision in system.writes.read(run_stream(run_id)).decisions.values()
            if decision.request["kind"] == "definitions_changed"]


def test_starting_from_an_older_run_event_version_stops_and_restarts_the_work_item(data_dir):
    # 验收一：版本不同的未结束 run 记为因升级停止，对应的事项出现新的 run（当前版本、优先级 upgrade_restart），
    # 自动继续运行到结束，没有决定请求；项目流的长期事实完整重建
    system, project_id, first_run, adopted = _adopted_project(data_dir)
    assert adopted is not None and adopted.type == ProjectEventType.DELIVERABLE_ADOPTED
    second_run = _unstarted_run(system, project_id)
    before = saved_project(system.store, project_id).to_dict()
    facts_before = {key: before[key] for key in ("name", "goal", "department_settings")}
    adoption_before = system.projects.projection(project_id).current_adoption
    end = system.store.end_position()
    system.close()

    _older_version_runs(data_dir, [second_run])

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    after = saved_project(restarted.store, project_id).to_dict()
    assert {key: after[key] for key in facts_before} == facts_before
    project = restarted.projects.projection(project_id)
    assert project.department_settings["engineering"].source == "configured"
    # 第一个事项的采纳成果保留在采纳历史中，没有被改写
    assert [item["adoption_id"] for item in after["adoptions"]][:1] == [adoption_before.adoption_id]

    # 旧 run 记为因升级停止，没有决定请求，也不由恢复继续
    stopped = project_run(restarted.store, second_run)
    assert (stopped.status, stopped.stop_reason) == ("failed", STOP_REASON_UPGRADE)
    assert _definitions_changed(restarted, second_run) == []
    assert second_run not in restarted.resumed_runs

    # 事项重新开始一个 run：优先级 upgrade_restart，run 事件版本是当前版本
    created = _started_work_items(restarted, project_id)
    assert [event.payload["priority"] for event in created] == \
        [PRIORITY_USER, PRIORITY_USER, PRIORITY_UPGRADE_RESTART]
    new_run_id = created[-1].payload["run_id"]
    assert new_run_id != second_run
    assert project_run(restarted.store, new_run_id).run_event_version == RUN_EVENT_VERSION

    # 重新开始以后的 run 由启动序列自动继续到结束
    assert new_run_id in restarted.resumed_runs, restarted.resumed_runs
    assert project_run(restarted.store, new_run_id).status == "done"

    # 第一个事项已经结束，不因版本不同停止；旧版本的 run 事件保留供查阅
    assert project_run(restarted.store, first_run).stop_reason == "released"
    assert restarted.store.end_position() > end
    restarted.close()


def test_the_restarted_run_starts_from_the_adopted_tree(data_dir):
    # 验收三（有采纳成果）：重新开始的 run 从采纳成果开始，基线是这个采纳成果，没有起始文件夹快照
    system, project_id, first_run, _adopted = _adopted_project(data_dir)
    second_run = _unstarted_run(system, project_id)
    adoption = system.projects.projection(project_id).current_adoption
    system.close()

    _older_version_runs(data_dir, [second_run])

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    created = _started_work_items(restarted, project_id)[-1]
    assert created.payload["baseline"]["adoption_id"] == adoption.adoption_id
    assert created.payload["baseline"]["source_run_id"] == first_run
    assert created.payload["snapshot"] is None
    workspace = restarted.workspace(created.payload["run_id"])
    assert (workspace.root / ECHO_FILE).read_text(encoding="utf-8") == "import sys\nprint(sys.argv[1])\n"
    restarted.close()


def test_the_restarted_run_starts_from_the_empty_tree_without_an_adoption(data_dir):
    # 验收三（没有采纳成果）：项目既没有采纳成果也没有起始文件夹，重新开始的 run 从空树开始，没有基线
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    project_id = system.projects.register("空项目", "核对没有采纳成果时的起点")
    run_id = _unstarted_run(system, project_id)
    system.close()

    _older_version_runs(data_dir, [run_id])

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    created = _started_work_items(restarted, project_id)[-1]
    assert created.payload["priority"] == PRIORITY_UPGRADE_RESTART
    assert created.payload["baseline"] is None
    assert created.payload["snapshot"] is None
    restarted.close()


def test_same_version_and_finished_runs_are_left_alone_at_startup(data_dir):
    # 验收二：版本相同的未结束 run 照常自动继续；已结束的 run 不受启动时的升级处理影响
    system, project_id, first_run, _adopted = _adopted_project(data_dir)
    second_run = _unstarted_run(system, project_id)
    system.close()

    # 只把已经结束的 run 写成较早版本：它不停止，也不重新开始事项
    _older_version_runs(data_dir, [first_run])

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    assert restarted.startup_runs.other_version == ()
    assert restarted.startup_runs.finished == (first_run,)
    assert project_run(restarted.store, first_run).stop_reason == "released"
    assert [event.payload["priority"] for event in _started_work_items(restarted, project_id)] == \
        [PRIORITY_USER, PRIORITY_USER]
    # 版本相同的未结束 run 照常自动继续到结束
    assert second_run in restarted.resumed_runs
    assert project_run(restarted.store, second_run).status == "done"
    assert project_run(restarted.store, second_run).stop_reason != STOP_REASON_UPGRADE
    restarted.close()


def test_an_onboarding_run_is_restarted_from_the_recorded_snapshot(data_dir, tmp_path):
    # 建档事项的 run 同样按强制升级处理：仍是同一个建档事项，新 run 从事项记录的快照开始并跑到终态
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    project_id, work_item_id, run_id = system.projects.onboard(
        "已有项目", "把已有项目接入 Yudao", "src", str(_source(tmp_path / "source")))
    system.close()

    _older_version_runs(data_dir, [run_id])

    restarted = LoopSystem.for_testing(data_dir, FakeAdapter(_onboarding_script()))
    stopped = project_run(restarted.store, run_id)
    assert (stopped.status, stopped.stop_reason) == ("failed", STOP_REASON_UPGRADE)
    created = _started_work_items(restarted, project_id)[-1]
    assert created.payload["priority"] == PRIORITY_UPGRADE_RESTART
    assert created.payload["kind"] == "onboarding"
    assert created.payload["work_item_id"] == work_item_id, "仍然是同一个建档事项"
    restarted_run = project_run(restarted.store, created.payload["run_id"])
    assert restarted_run.kind == "onboarding" and restarted_run.round == 1
    assert restarted_run.baseline is None
    snapshot = restarted.projects.projection(project_id).work_item(work_item_id).snapshot
    assert restarted_run.snapshot == snapshot, "从建档事项记录的快照开始"
    # 重新开始以后的建档 run 照常跑到它的终态
    assert created.payload["run_id"] in restarted.resumed_runs
    assert project_run(restarted.store, created.payload["run_id"]).status == "done"
    restarted.close()


def test_a_work_item_created_by_the_user_has_the_user_priority(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    project_id = system.projects.register("优先级", "核对用户新建事项的优先级")
    _work_item_id, run_id = system.projects.start_work_item(project_id, "用户新要求")
    [created] = _started_work_items(system, project_id)
    assert created.payload["priority"] == PRIORITY_USER
    assert project_run(system.store, run_id).run_event_version == RUN_EVENT_VERSION
    system.close()