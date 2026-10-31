# 按位置取事件（工单 #1342；#398 登记的边界：事实回链只给位置与来源种类，接口层没有按位置取事件的查询，
# 页面只能缓存整条事件流）。
#
# 核对：按 run_id、project_id 或两个都给，一组位置取回与事件流同形状的字段（种类、提出者与部门的可读名、
# 中文说明、对外载荷）；越界、已归档、已被压缩与「位置上是别的流的事件」四种取不到分别有明确回答；
# 调用前后事件数与保存的投影不变（纯读）。
#
# 层：模块层（真实的事件日志在临时目录里，不开子进程、不联网）。守 R1（接口层按位置读事件合同的交换字段）。

from __future__ import annotations

import sqlite3

import pytest

from harness.adapters.fake import FakeAdapter
from harness.app.application import Application, ReadOnlyCore
from harness.app.project_queries import EventPositions, QueryInputInvalid, NotFound
from harness.event_store import project_stream, run_stream
from harness.models import EventType, ProjectEventType
from harness.runtime import LoopSystem
from harness.write_path import NewEvent


@pytest.fixture
def scenario(tmp_path):
    # 一个项目与一个 run：项目流里有 project_registered 与 work_item_created，run 流里有 run_created
    # 与一条正常载荷、一条旧版本载荷（与当前类型对不上）的 department_activated
    data_dir = tmp_path / "data"
    system = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    try:
        project_id = system.projects.register("取事件", "按位置读事件")
        _work_item_id, run_id = system.projects.start_work_item(project_id, "echo")

        def append(transaction):
            transaction.append(NewEvent(
                EventType.DEPARTMENT_ACTIVATED, actor="department:product", department="product",
                state_before=transaction.projection.status, state_after=transaction.projection.status,
                payload={"cycle": 1, "reason": "input", "activation_id": "act-1"}))
            transaction.append(NewEvent(
                EventType.MODEL_ATTEMPT_FINISHED, actor="system", department="engineering",
                state_before=transaction.projection.status, state_after=transaction.projection.status,
                payload={"not_a_field_of_this_kind": True}))

        system.writes.transact(run_stream(run_id), append)
        run_positions = [event.position for event in system.store.list_events(run_id)]
        project_positions = [event.position for event in system.store.list_project_events(project_id)]
        end = system.store.end_position()
    finally:
        system.close()
    return {"data_dir": data_dir, "project_id": project_id, "run_id": run_id,
            "run_positions": run_positions, "project_positions": project_positions, "end": end}


def _application(data_dir):
    return Application(ReadOnlyCore(data_dir))


def _query(application, **request):
    return application.query("event.positions", EventPositions(**request)).data


def test_a_run_reads_its_events_by_position_with_the_fields_the_event_stream_has(scenario):
    application = _application(scenario["data_dir"])
    try:
        result = _query(application, run_id=scenario["run_id"], positions=scenario["run_positions"])
    finally:
        application.close()
    assert result.streams == [run_stream(scenario["run_id"])]
    assert [item.position for item in result.events] == scenario["run_positions"]
    assert [item.status for item in result.events] == ["available", "available", "available"]
    created = result.events[0]
    # 事件种类、提出者与部门的可读名、中文说明
    assert created.type == EventType.RUN_CREATED
    assert created.label
    assert created.actor == "system"
    assert created.actor_label == "系统"
    assert created.at
    assert created.event_id
    assert isinstance(created.payload, dict)
    activated = result.events[1]
    assert activated.type == EventType.DEPARTMENT_ACTIVATED
    assert activated.actor == "department:product"
    assert activated.actor_label == "产品部门"
    assert activated.department == "product"
    assert activated.department_label == "产品部门"
    assert activated.payload["cycle"] == 1
    # 旧版本写入的载荷与当前类型对不上时原样交出，不让整次查询失败
    assert result.events[2].payload == {"not_a_field_of_this_kind": True}


def test_a_project_reads_its_own_events_and_both_streams_can_be_asked_together(scenario):
    application = _application(scenario["data_dir"])
    try:
        project_only = _query(application, project_id=scenario["project_id"],
                              positions=scenario["project_positions"])
        both = _query(application, run_id=scenario["run_id"], project_id=scenario["project_id"],
                      positions=scenario["project_positions"] + scenario["run_positions"])
        mixed = _query(application, run_id=scenario["run_id"], project_id=scenario["project_id"],
                       positions=[scenario["project_positions"][0], scenario["run_positions"][0]])
    finally:
        application.close()
    assert project_only.streams == [project_stream(scenario["project_id"])]
    assert {item.type for item in project_only.events} == {
        ProjectEventType.PROJECT_REGISTERED, ProjectEventType.WORK_ITEM_CREATED}
    # 两条流一起问：各自的位置都取得到，顺序按请求里的位置
    assert both.streams == [project_stream(scenario["project_id"]), run_stream(scenario["run_id"])]
    assert all(item.status == "available" for item in both.events)
    # 一条项目事件、一条 run 事件混在一组位置上：来源卡片的回链正是这样
    assert [item.type for item in mixed.events] == [ProjectEventType.PROJECT_REGISTERED, EventType.RUN_CREATED]


def test_positions_outside_the_log_answer_out_of_range(scenario):
    application = _application(scenario["data_dir"])
    try:
        result = _query(application, run_id=scenario["run_id"],
                        positions=[scenario["end"] + 1, 0, -5, 10**9])
    finally:
        application.close()
    assert [(item.status, item.reason) for item in result.events] == [
        ("missing", "out_of_range"), ("missing", "out_of_range"),
        ("missing", "out_of_range"), ("missing", "out_of_range")]
    assert all(item.type is None and item.payload is None for item in result.events)


def test_a_position_that_holds_another_streams_event_answers_not_in_stream(scenario):
    # 位置是全库自增的：run 的相邻位置之间可能夹着项目流的事件。按 run 取那一组位置时，
    # 这些位置不是「没有事件」，而是「这个位置上是别的流的事件」
    application = _application(scenario["data_dir"])
    try:
        foreign = scenario["project_positions"][0]
        result = _query(application, run_id=scenario["run_id"], positions=[foreign])
    finally:
        application.close()
    [item] = result.events
    assert (item.status, item.reason) == ("missing", "not_in_stream")


def _delete_events(data_dir, positions):
    # 现存储只追加、不压缩也不搬走事件：直接删掉事件行，构造「更早的事件已归档搬走」与
    # 「范围内这一条已压缩掉」两种存储状态，核对这条查询的回答（工单 #1342 的验收）
    with sqlite3.connect(str(data_dir / "events.sqlite")) as connection:
        connection.execute(f"DELETE FROM events WHERE position IN ({', '.join('?' * len(positions))})",
                           list(positions))
        connection.commit()


def _run_with_four_events(tmp_path, name):
    # 一个 run 里四条事件（run_created 与三条部门激活）：位置按写入的先后排列
    data_dir = tmp_path / name
    system = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    try:
        project_id = system.projects.register("存储形态", "归档与压缩")
        _work_item_id, run_id = system.projects.start_work_item(project_id, "echo")

        def append(transaction):
            transaction.append(NewEvent(
                EventType.DEPARTMENT_ACTIVATED, actor="department:product", department="product",
                state_before=transaction.projection.status, state_after=transaction.projection.status,
                payload={"cycle": 1}))

        system.writes.transact(run_stream(run_id), append)
        system.writes.transact(run_stream(run_id), append)
        system.writes.transact(run_stream(run_id), append)
        positions = [event.position for event in system.store.list_events(run_id)]
        assert len(positions) == 4
    finally:
        system.close()
    return data_dir, run_id, positions


def test_a_position_before_the_first_kept_event_answers_archived(tmp_path):
    # 更早的事件已经搬走（归档）：这个流现在的第一条在第三条位置上，请求开头两个位置回答「已归档」
    data_dir, run_id, positions = _run_with_four_events(tmp_path, "archived")
    _delete_events(data_dir, [positions[0], positions[1]])
    application = _application(data_dir)
    try:
        result = _query(application, run_id=run_id, positions=positions)
    finally:
        application.close()
    assert [(item.status, item.reason) for item in result.events] == [
        ("missing", "archived"), ("missing", "archived"), ("available", None), ("available", None)]


def test_a_missing_position_inside_the_range_answers_compacted(tmp_path):
    # 范围内的这一条被压缩掉：它之前与之后的事件都还在，回答「已压缩」而不是「越界」或「没有这个流」
    data_dir, run_id, positions = _run_with_four_events(tmp_path, "compacted")
    _delete_events(data_dir, [positions[1]])
    application = _application(data_dir)
    try:
        result = _query(application, run_id=run_id, positions=positions)
    finally:
        application.close()
    assert [(item.status, item.reason) for item in result.events] == [
        ("available", None), ("missing", "compacted"), ("available", None), ("available", None)]
    # 取得到的那些仍带上与事件流同形状的字段
    assert result.events[0].type == EventType.RUN_CREATED
    assert result.events[2].type == EventType.DEPARTMENT_ACTIVATED
    assert result.events[2].actor_label == "产品部门"


def test_the_query_is_a_pure_read(scenario):
    # 调用前后：事件条数、日志末尾位置与保存的投影都不变（设计说明接口部分：已登记的查询只读）
    application = _application(scenario["data_dir"])
    try:
        store = application.system.store
        before_events = (len(store.list_events(scenario["run_id"])),
                         len(store.list_project_events(scenario["project_id"])), store.end_position())
        before_projection = store.projection(run_stream(scenario["run_id"])).state
        _query(application, run_id=scenario["run_id"], project_id=scenario["project_id"],
               positions=[scenario["run_positions"][0], scenario["project_positions"][0], scenario["end"] + 1])
        after_events = (len(store.list_events(scenario["run_id"])),
                        len(store.list_project_events(scenario["project_id"])), store.end_position())
        after_projection = store.projection(run_stream(scenario["run_id"])).state
    finally:
        application.close()
    assert after_events == before_events
    assert after_projection == before_projection


def test_the_request_is_checked(scenario):
    application = _application(scenario["data_dir"])
    try:
        with pytest.raises(QueryInputInvalid, match="positions must not be empty"):
            _query(application, run_id=scenario["run_id"], positions=[])
        with pytest.raises(QueryInputInvalid, match="give run_id, project_id, or both"):
            _query(application, positions=[1])
        with pytest.raises(QueryInputInvalid, match="at most 200 positions"):
            _query(application, run_id=scenario["run_id"], positions=list(range(1, 202)))
        with pytest.raises(NotFound, match="run not found"):
            _query(application, run_id="run_does_not_exist", positions=[1])
        with pytest.raises(NotFound, match="project not found"):
            _query(application, project_id="proj_does_not_exist", positions=[1])
    finally:
        application.close()
def test_an_empty_position_list_reads_nothing(scenario):
    # 读取本身对空清单不查库（接口层在进到这里以前按输入不合法拒绝）：返回空表，
    # 没有事件的流也没有位置范围（工单 #1342）
    application = _application(scenario["data_dir"])
    try:
        store = application.system.store
        assert store.events_at([]) == {}
        assert store.stream_position_range("run:does_not_exist") is None
    finally:
        application.close()