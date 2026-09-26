from harness.adapters.fake import FakeAdapter
from harness.models import DEPARTMENTS, Event, EventType, ProjectEvent
from harness.runtime import LoopSystem
from harness.tests.helpers import happy_script

# 一份事件日志：按全局位置与范围分批读取。系统整体运行，模型回答由 FakeAdapter 脚本给出。


def _two_projects_and_a_bare_run(data_dir):
    # 两个项目各完成一个事项并采纳，另有一个不属于项目的 run
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script() + happy_script() + happy_script()))
    owners = {}
    for name in ("A", "B"):
        project_id = system.projects.register(f"项目 {name}", "逐行文本处理工具")
        work_item_id, run_id = system.projects.start_work_item(project_id, f"事项 {name}")
        system.run_until_stop(run_id)
        system.projects.settle(run_id)
        owners[name] = (project_id, work_item_id, run_id)
    bare = system.create_run("bare run")
    system.run_until_stop(bare)
    system.projects.rename(owners["A"][0], "项目 A2")
    return system, owners, bare


def _membership(system, event):
    # 按事件的内容得出它所属的项目、事项、run 与部门，不读取日志保存的范围列
    if isinstance(event, ProjectEvent):
        payload = event.payload
        return event.project_id, payload.get("work_item_id"), payload.get("run_id"), payload.get("department")
    created = system.store.list_events(event.run_id)[0]
    assert created.type == EventType.RUN_CREATED
    department = event.role if event.role in DEPARTMENTS else None
    return created.payload["project_id"], created.payload["work_item_id"], event.run_id, department


def _matches(system, event, *, projects=(), work_items=(), runs=(), departments=(), types=()):
    project, work_item, run, department = _membership(system, event)
    return ((not projects or project in projects) and (not work_items or work_item in work_items)
            and (not runs or run in runs) and (not departments or department in departments)
            and (not types or event.type in types))


def test_range_reads_equal_filtering_the_whole_log(data_dir):
    system, owners, bare = _two_projects_and_a_bare_run(data_dir)
    everything = system.store.read(limit=100_000)
    assert [event.position for event in everything] == sorted(event.position for event in everything)
    assert len({event.position for event in everything}) == len(everything)
    assert {type(event) for event in everything} == {Event, ProjectEvent}
    project_a, work_item_a, run_a = owners["A"]
    project_b, _work_item_b, run_b = owners["B"]
    scopes = [
        {"projects": [project_a]},
        {"projects": [project_a, project_b]},
        {"work_items": [work_item_a]},
        {"runs": [run_a]},
        {"runs": [bare]},
        {"departments": ["engineering"]},
        {"departments": ["product", "quality"]},
        {"types": [EventType.TRANSITION, "deliverable_adopted"]},
        {"projects": [project_b], "departments": ["quality"], "types": [EventType.QA_SUBMITTED]},
    ]
    for scope in scopes:
        expected = [event.event_id for event in everything if _matches(system, event, **scope)]
        assert expected, scope
        assert [event.event_id for event in system.store.read(limit=100_000, **scope)] == expected, scope
    assert system.store.read(limit=100_000, projects=[project_a], runs=[run_b]) == []


def test_reading_in_batches_by_position_gives_the_whole_log_once(data_dir):
    system, owners, _bare = _two_projects_and_a_bare_run(data_dir)
    everything = system.store.read(limit=100_000)
    batched, after = [], 0
    while True:
        batch = system.store.read(after, limit=7)
        if not batch:
            break
        assert len(batch) <= 7
        batched.extend(batch)
        after = batch[-1].position
    assert [event.event_id for event in batched] == [event.event_id for event in everything]
    assert system.store.end_position() == everything[-1].position
    project_a = owners["A"][0]
    middle = everything[len(everything) // 2].position
    assert ([event.event_id for event in system.store.read(middle, projects=[project_a], limit=100_000)]
            == [event.event_id for event in everything
                if event.position > middle and _matches(system, event, projects=[project_a])])


def test_cross_project_reads_follow_the_order_of_writing(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    first = system.projects.register("甲", "目标")
    second = system.projects.register("乙", "目标")
    system.projects.rename(first, "甲二")
    system.projects.pin(second, True)
    events = system.store.read(projects=[first, second])
    assert [(event.project_id, event.type) for event in events] == [
        (first, "project_registered"), (second, "project_registered"),
        (first, "project_renamed"), (second, "project_pinned"),
    ]
    assert [event.stream_version for event in events] == [1, 1, 2, 2]
    assert [event.position for event in events] == sorted(event.position for event in events)
