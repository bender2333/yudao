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
from harness.models import EventType
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
    run_id = system.create_run("build echo")
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
    system.close()


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
