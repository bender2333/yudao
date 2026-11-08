# 故障矩阵第 5 行的写入口一侧：旧执行者失权以后拿被取代的派发编号提交的写入只记录、不生效
# （恢复契约与故障矩阵 docs/design/recovery-contract-and-fault-matrix.md「故障矩阵」）。
# 派发编号（工单 #1397；总图第四节「写入口」的缝、第三节「重派与迟到的结果」；骨架与应用设计说明「薄驱动」第 6 件事）：
# 每开始一轮工作，写入口在一个事务里写一条取得编号的事件，这一轮写入的事件都带它；重派先写事件、编号加一。
# 写入口核对派发编号：拿已经被重派取代的旧编号提交的写入只记录，不并入投影与决定请求（不改事项的状态）。
# 旧版本写入的数据目录里没有这一列，照常读取与重放。
#
# 守 R2（第二环的合同：写入口在同一事务里核对执行权编号、派发编号与流版本）与 R1（同样的事件重放出同样的状态）。
# 用真实的 SQLite 事件库与写入口，不起服务、不用网络；读事件日志、写数据目录，属于模块层。

import sqlite3

from harness.adapters.fake import FakeAdapter
from harness.event_store import EventStore, run_stream
from harness.kernel_events import (
    CatalogEvent, CatalogEventType, Event, ProjectEvent, ProjectEventType, replay_decisions,
)
from harness.models import DEPARTMENTS, EventType
from harness.runtime import LoopSystem
from harness.write_path import NewEvent

SESSION = "ses_pro_1"


def _activated(cycle: int = 1) -> NewEvent:
    # 这一轮里一条会改变事项状态的写入：department_activated 让投影记下这一轮的周期数
    return NewEvent(
        EventType.DEPARTMENT_ACTIVATED, actor="system", department="product", state_before="running",
        state_after="running", session_id=SESSION, payload={"activation_id": "act_1", "cycle": cycle},
    )


def _append(cycle: int = 1):
    def decide(transaction):
        return transaction.append(_activated(cycle))[0]

    return decide


def _claim(system, stream: str, session_id: str = SESSION) -> int:
    # 开始一轮工作：取得派发编号并在同一个事务里写一条事件
    def decide(transaction):
        number = transaction.claim_dispatch_number(session_id)
        transaction.append(NewEvent(
            EventType.DISPATCH_NUMBER_ACQUIRED, actor="system", state_before="running", state_after="running",
            session_id=session_id, payload={"activation_id": "act_1", "cycle": number},
        ))
        return number

    return system.writes.transact(stream, decide)


def _system(tmp_path):
    system = LoopSystem.for_testing(tmp_path / "data", FakeAdapter([]))
    # 带项目与事项的 run：只记录的事件要能按项目与按事项读出来（项目归属的四项参数要么全给，要么全不给）
    run_id = system.create_run("build echo", project_id="proj_1397", work_item_id="wi_1397",
                               project_context="开发一个回显工具",
                               prompt_config_versions={department: 0 for department in DEPARTMENTS})
    return system, run_id, run_stream(run_id)


def test_a_round_takes_a_dispatch_number_and_records_it_in_one_event(tmp_path):
    # 验收第 2 条：每开始一轮工作，事实里有一条取得派发编号的事件；这一轮写入的事件都带这个编号
    system, run_id, stream = _system(tmp_path)
    assert _claim(system, stream) == 1
    event = system.writes.transact(stream, _append())
    assert event.dispatch_number == 1
    events = system.store.list_events(run_id)
    assert [item.type for item in events][-2:] == [EventType.DISPATCH_NUMBER_ACQUIRED,
                                                  EventType.DEPARTMENT_ACTIVATED]
    # 开始取编号之前写入的事件（run_created）没有编号：旧版本写入的流也是这个样子
    assert events[0].dispatch_number is None
    assert {item.dispatch_number for item in events[1:]} == {1}
    system.close()


def test_a_write_that_carries_the_recorded_number_is_committed_as_usual(tmp_path):
    # 「编号相符照常提交」：编号与这个会话已记录的编号相同时，写入照常并入投影与最小投影
    system, run_id, stream = _system(tmp_path)
    number = _claim(system, stream)
    event = system.writes.transact(stream, _append(), dispatch_number=number)
    assert event.dispatch_number == number
    assert system.project(run_id).cycle_count == 1
    assert system.writes.minimal(stream).used.activations == 1
    system.close()


def test_a_write_that_carries_a_superseded_number_is_only_recorded(tmp_path):
    # 「旧编号不生效」：重派以后拿旧编号提交的写入只记录，事项的状态与最小投影都不变
    system, run_id, stream = _system(tmp_path)
    first = _claim(system, stream)
    assert system.writes.transact(stream, _append(), dispatch_number=first).dispatch_number == first
    second = _claim(system, stream)
    assert second == first + 1
    before = system.project(run_id).to_dict()
    before_minimal = system.writes.minimal(stream).used.activations
    late = system.writes.transact(stream, _append(cycle=9), dispatch_number=first)
    assert late.dispatch_number == first
    assert system.project(run_id).to_dict() == before
    assert system.project(run_id).cycle_count == 1
    assert system.writes.minimal(stream).used.activations == before_minimal
    # 只记录：这一条在日志里查得到（投影没有并进去的那一条也在），编号是旧的
    recorded = [item for item in system.store.list_events(run_id) if item.type == EventType.DEPARTMENT_ACTIVATED]
    assert [item.dispatch_number for item in recorded] == [first, first]
    assert [item.payload["cycle"] for item in recorded] == [1, 9]
    # 只记录不等于看不见（审查要求修改 2）：项目与事项也带在它上面，按项目与按事项订阅的事件流都读得到它
    projection = system.project(run_id)
    assert late.project_id == projection.project_id and late.work_item_id == projection.work_item_id
    assert late.event_id in {item.event_id for item in system.store.read(projects=[projection.project_id])}
    assert late.event_id in {item.event_id for item in system.store.read(work_items=[projection.work_item_id])}
    system.close()


def test_a_project_decision_request_survives_a_numbered_event_without_a_session():
    # 审查要求修改 1：回放会把 run、项目、目录三条流的事件合在一起（decisions_through）；
    # 没有编号的事件（项目流与目录流不取编号）不被 run 的流级事件（带编号、没有会话）挤成「只记录」
    paused = Event(
        event_id="evt_pause", run_id="run_1", type=EventType.RUN_PAUSED, role=None, parent_event_id=None,
        state_before="running", state_after="paused", payload={"human_action": "retry"}, artifact_hashes=[],
        session_id=None, provider=None, model=None, context_digest=None, stop_reason="input_needed",
        error=None, created_at="2026-10-28T00:00:00+00:00", position=1, stream="run:run_1", stream_version=1,
        project_id="proj_1", work_item_id="wi_1", department=None, dispatch_number=1,
    )
    request = ProjectEvent(
        event_id="pevt_q", project_id="proj_1", type=ProjectEventType.PROJECT_DECISION_REQUESTED,
        payload={"kind": "confirm_initial_prd", "blocks": "project", "work_item_id": "wi_1"},
        created_at="2026-10-28T00:00:00+00:00", position=2, stream="project:proj_1", stream_version=1,
        work_item_id=None, run_id=None, department=None,
    )
    upgrade = CatalogEvent(
        event_id="cevt_q", type=CatalogEventType.INSTANCE_UPGRADE_REQUESTED,
        payload={"kind": "instance_upgrade", "blocks": "instance"},
        created_at="2026-10-28T00:00:00+00:00", position=3, stream="catalog:main", stream_version=1,
    )
    assert list(replay_decisions([paused, request, upgrade])) == ["pevt_q", "cevt_q"]


def test_a_redispatch_increments_the_number(tmp_path):
    # 「重派以后编号加一」：同一个会话重派时先写事件、编号加一；别的部门的会话各数各的
    system, _run_id, stream = _system(tmp_path)
    assert _claim(system, stream, SESSION) == 1
    assert _claim(system, stream, SESSION) == 2
    assert _claim(system, stream, "ses_eng_1") == 1
    assert _claim(system, stream, SESSION) == 3
    system.close()


def test_an_old_data_directory_without_dispatch_numbers_still_replays(tmp_path):
    # 验收第 4 条：旧版本写入的数据目录（没有派发编号）照常读取与重放，读出来这一列是空
    system, run_id, stream = _system(tmp_path)
    system.writes.transact(stream, _append())
    assert [item.dispatch_number for item in system.store.list_events(run_id)] == [None, None]
    before = system.project(run_id).to_dict()
    assert system.writes.rebuild(stream).to_dict() == before == system.project(run_id).to_dict()
    system.close()


def test_a_rebuild_does_not_rewrite_the_recorded_events(tmp_path):
    # 验收第 1 条的行为一侧：重放与保存投影都不改写已经写进日志的事件
    system, run_id, stream = _system(tmp_path)
    _claim(system, stream)
    system.writes.transact(stream, _append())

    def snapshot():
        return [(item.event_id, item.type, item.position, item.dispatch_number, dict(item.payload))
                for item in system.store.list_events(run_id)]

    before = snapshot()
    system.writes.rebuild(stream)
    assert snapshot() == before
    system.close()


def test_a_data_directory_written_by_an_older_version_still_opens(tmp_path):
    # 验收第 4 条的行为一侧：旧版本写出的数据目录，事件表里没有这一列，照常读取与重放
    system, run_id, stream = _system(tmp_path)
    system.writes.transact(stream, _append())
    data = tmp_path / "data"
    system.close()
    with sqlite3.connect(data / "events.sqlite") as connection:
        connection.execute("ALTER TABLE events DROP COLUMN dispatch_number")
    # 只读子命令不补列：同样读得出这些事件，这一列读作空
    readonly = EventStore(data / "events.sqlite", read_only=True)
    assert [item.dispatch_number for item in readonly.list_events(run_id)] == [None, None]
    readonly.close()
    reopened = LoopSystem.for_testing(data, FakeAdapter([]))
    events = reopened.store.list_events(run_id)
    assert [item.dispatch_number for item in events[:2]] == [None, None]
    assert reopened.writes.rebuild(stream).to_dict() == reopened.project(run_id).to_dict()
    reopened.close()


def test_a_late_write_does_not_make_the_replay_check_disagree(tmp_path):
    # 「只记录」在重放核对上同样成立：旧编号的写入不并入重放，system.replay 不报投影不一致
    system, run_id, stream = _system(tmp_path)
    first = _claim(system, stream)
    system.writes.transact(stream, _append(), dispatch_number=first)
    second = _claim(system, stream)
    assert second == first + 1
    system.writes.transact(stream, _append(cycle=9), dispatch_number=first)
    assert system.replay(run_id).to_dict() == system.project(run_id).to_dict()
    system.close()
