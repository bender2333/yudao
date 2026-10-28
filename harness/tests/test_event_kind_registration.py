# 应用登记自己的事件种类（设计说明第 5.4 节第 1 条，S5a 工单 #828）：一种新的应用事件种类经写入口写入，
# 重放读得回来，改动的只有登记它的应用与它的测试，内核文件不变。
#
# 用的资源是真实的 SQLite 事件库与写入口的一次事务，没有完整的三部门循环，属于模块层。
# 守第 13 节的 R1（事实只经写入口写入；同样的事件重放出同样的状态）与 R2（骨架事件只增：
# 应用加一种种类不进骨架事件的登记表）。

from harness.adapters.fake import FakeAdapter
from harness.app.payloads import APPLICATION_EVENT_TYPES, APPLICATION_EVENT_OWNER
from harness.event_store import run_stream
from harness.kernel_events import (
    SKELETON_RUN_EVENTS,
    application_event_types,
    event_type_owner,
    register_application_event_types,
)
from harness.projection import replay_events
from harness.runtime import LoopSystem
from harness.streams import RUN_EVENT_TYPES
from harness.write_path import NewEvent

# 测试里的第二种路由带来的一种事件：它不写进产品的载荷声明，只在这一次登记里出现
NEW_KIND = "task_pool_task_published"


def test_the_application_registers_the_run_events_it_owns():
    # 应用登记的正是 run 流里除骨架事件以外的那些种类：骨架事件由内核给出，其余归应用（第 5.4 节第 1 条）
    assert set(APPLICATION_EVENT_TYPES) == set(RUN_EVENT_TYPES) - set(SKELETON_RUN_EVENTS)
    registered = application_event_types()
    for kind in APPLICATION_EVENT_TYPES:
        assert registered.get(kind) == APPLICATION_EVENT_OWNER, f"{kind} 没有登记到内核的登记表"
        assert event_type_owner(kind) == APPLICATION_EVENT_OWNER


def test_a_new_application_event_kind_is_written_and_replayed(data_dir):
    register_application_event_types("测试里的任务池路由", [NEW_KIND])
    assert NEW_KIND not in SKELETON_RUN_EVENTS
    system = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    stream = run_stream("run_task_pool")

    def publish(transaction):
        return transaction.append(NewEvent(
            NEW_KIND, state_before="running", state_after="running", payload={"task": "T-1"}, actor="user:local",
        ))

    system.writes.transact(stream, publish)
    events = system.store.list_events("run_task_pool")
    assert [event.type for event in events] == [NEW_KIND]
    assert events[0].payload == {"task": "T-1"}
    # 重放：内核的投影不认识这种应用事件，照常跳过，不报错、事件还在流里
    assert replay_events(events).stream_version == 1
    assert event_type_owner(NEW_KIND) == "测试里的任务池路由"
