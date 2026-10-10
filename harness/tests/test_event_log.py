import pytest

from harness.adapters.fake import FakeAdapter
from harness.models import DEPARTMENTS, Event, EventType, ProjectEvent, ProjectEventType
from harness.runtime import LoopSystem
from harness.tests.helpers import happy_script, system_on_copy

# 一份事件日志：按全局位置与范围分批读取。系统整体运行，模型回答由 FakeAdapter 脚本给出。
# 需要一份真实运行记录的文件：module 作用域的夹具各跑一次日志并保存数据目录，
# 每项测试复制一份数据目录，在自己的副本上读取与检查。日志来自真实运行，登记为集成层。


def _saved_log(builder, directory):
    system, extra = builder(directory)
    system.close()
    return system.data_dir, extra


def _two_projects_source(data_dir):
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
    return system, {"owners": owners, "bare": bare}


@pytest.fixture(scope="module")
def saved_two_projects(tmp_path_factory):
    return _saved_log(_two_projects_source, tmp_path_factory.mktemp("two-projects"))


@pytest.fixture
def two_projects_log(saved_two_projects, tmp_path):
    saved, extra = saved_two_projects
    system = system_on_copy(saved, tmp_path / "two-projects")
    return system, extra["owners"], extra["bare"]


def _actor_source(data_dir):
    # 一个事项走完，中间有一条用户补充输入：三种提出者都出现在日志里
    system = LoopSystem.for_testing(data_dir, FakeAdapter(happy_script()))
    project_id = system.projects.register("项目", "工具")
    _work_item_id, run_id = system.projects.start_work_item(project_id, "事项")
    system.add_input(run_id, "补充一句要求")  # 用户输入：提出者为 user:local
    system.run_until_stop(run_id)
    system.projects.settle(run_id)
    return system, {}


@pytest.fixture(scope="module")
def saved_actor_log(tmp_path_factory):
    return _saved_log(_actor_source, tmp_path_factory.mktemp("actors"))


@pytest.fixture
def actor_log(saved_actor_log, tmp_path):
    saved, _extra = saved_actor_log
    return system_on_copy(saved, tmp_path / "actors")


def _membership(system, event):
    # 按事件的内容得出它所属的项目、事项、run 与部门，不读取日志保存的范围列
    if isinstance(event, ProjectEvent):
        payload = event.payload
        return event.project_id, payload.get("work_item_id"), payload.get("run_id"), payload.get("department")
    created = system.store.list_events(event.run_id)[0]
    assert created.type == EventType.RUN_CREATED
    return created.payload["project_id"], created.payload["work_item_id"], event.run_id, event.department


def _matches(system, event, *, projects=(), work_items=(), runs=(), departments=(), types=()):
    project, work_item, run, department = _membership(system, event)
    return ((not projects or project in projects) and (not work_items or work_item in work_items)
            and (not runs or run in runs) and (not departments or department in departments)
            and (not types or event.type in types))


def test_range_reads_equal_filtering_the_whole_log(two_projects_log):
    system, owners, bare = two_projects_log
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


def test_reading_in_batches_by_position_gives_the_whole_log_once(two_projects_log):
    system, owners, _bare = two_projects_log
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

def test_every_event_declares_its_actor_and_the_department_lives_in_the_department_column(actor_log):
    # 提出者由写入方声明（设计第 5.2 节）：命令写入的事件为命令的提出者、角色任务中的记录与提案为
    # department:<部门>、流程编排与控制核心自己的判断为 system；role 列为空，部门只在 department 列
    user_events = {EventType.USER_INPUT_RECEIVED, EventType.DEPARTMENT_GUIDANCE_RECEIVED}
    system_events = {EventType.RUN_CREATED, EventType.TRANSITION, EventType.DEPARTMENT_ACTIVATED,
                     EventType.ACTIVATION_FINISHED, EventType.PRODUCT_INPUT_ASSIGNED,
                     EventType.COLLABORATION_CLOSED, EventType.RUN_DONE, EventType.RUN_PAUSED,
                     EventType.RUN_FAILED, EventType.DECISION_REQUESTED}
    system_projects = {ProjectEventType.DELIVERABLE_ADOPTED, ProjectEventType.ADOPTION_HELD,
                       ProjectEventType.WORK_ITEM_START_FAILED}
    system = actor_log
    events = system.store.read(limit=100_000)
    assert events
    # 每条事件都有提出者
    assert all(event.actor for event in events)
    # run 事件的角色列为空，部门写在 department 列
    assert all(event.role is None for event in events if isinstance(event, Event))
    seen_user = seen_system = seen_department = False
    for event in events:
        if isinstance(event, ProjectEvent):
            # 项目事件：由命令写入的为命令的提出者，结算等由流程编排自己的判断为 system
            expected = "system" if event.type in system_projects else "user:local"
            assert event.actor == expected, event.type
            continue
        if event.type in user_events:
            assert event.actor == "user:local", event.type
            seen_user = True
        elif event.type in system_events:
            # 流程编排与控制核心自己的判断：激活的开始与结束、交接、停止、结算
            assert event.actor == "system", event.type
            seen_system = True
        else:
            # 角色任务中的记录与提案：部门提出，部门在 department 列
            assert event.department is not None, event.type
            assert event.actor == f"department:{event.department}", event.type
            seen_department = True
    assert seen_user and seen_system and seen_department
    # 部门列覆盖三个部门，说明部门没有被搬进角色列
    assert {event.department for event in events if isinstance(event, Event) and event.department} == set(DEPARTMENTS)
