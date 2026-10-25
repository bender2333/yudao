import asyncio

from harness.app.application import Application
from harness.app.event_stream import EventScope
from harness.adapters.fake import FakeAdapter
from harness.event_store import project_stream
from harness.models import ProjectEventType
from harness.runtime import LoopSystem
from harness.write_path import NewProjectEvent

def _application(tmp_path) -> Application:
    # 真实应用层与真实事件日志；本文件不驱动模型调用，脚本为空
    system = LoopSystem.for_testing(tmp_path, FakeAdapter([]))
    return Application(system)

def _record(application: Application, project_id: str, index: int) -> None:
    # 用真实的写入口追加一条项目事件（提出者是用户）
    application.system.writes.append(
        project_stream(project_id),
        NewProjectEvent(ProjectEventType.PROJECT_RENAMED, {"name": f"project {index}"}, actor="user:local"),
    )

def _collect(stream, limit: int, timeout: float = 5.0):
    async def run():
        messages = []
        async for message in stream.messages():
            messages.append(message)
            if len(messages) >= limit:
                break
        return messages

    return asyncio.run(asyncio.wait_for(run(), timeout))

def test_backfill_and_range_filters_match_reading_the_log(tmp_path):
    application = _application(tmp_path)
    store = application.system.store
    run_id = application.system.create_run("stream")
    application.system.activate_once(run_id)
    assert store.read(after=0, limit=1000)

    scope = EventScope(types=(ProjectEventType.PROJECT_RENAMED,))
    for index in range(3):
        _record(application, "p1", index)

    stream = application.open_event_stream(scope, after=0, live=False)
    messages = _collect(stream, 3)
    expected = store.read(after=0, limit=1000, types=(ProjectEventType.PROJECT_RENAMED,))
    assert [message.event.position for message in messages] == [event.position for event in expected]
    assert all(message.event.type == ProjectEventType.PROJECT_RENAMED for message in messages)

def test_positions_are_continuous_and_previous_chains_the_connection(tmp_path):
    application = _application(tmp_path)
    run_id = application.system.create_run("stream")
    application.system.activate_once(run_id)

    stream = application.open_event_stream(EventScope(), after=0, live=False)
    messages = _collect(stream, 5)
    positions = [message.position for message in messages]
    assert positions == sorted(positions)
    assert len(set(positions)) == len(positions)
    assert messages[0].previous == 0
    for earlier, later in zip(messages, messages[1:]):
        assert later.previous == earlier.position

def test_resume_after_a_position_has_no_gap_and_no_repeat(tmp_path):
    application = _application(tmp_path)
    run_id = application.system.create_run("stream")
    application.system.activate_once(run_id)
    for index in range(5):
        _record(application, "p1", index)

    first = _collect(application.open_event_stream(EventScope(), after=0, live=False), 3)
    resumed = _collect(application.open_event_stream(EventScope(), after=first[-1].position, live=False), 3)
    assert resumed[0].position > first[-1].position
    assert all(message.position > first[-1].position for message in resumed)
    assert resumed[0].previous == first[-1].position

def test_after_beyond_the_log_end_resyncs_and_closes(tmp_path):
    application = _application(tmp_path)
    run_id = application.system.create_run("stream")
    application.system.activate_once(run_id)
    end = application.system.store.end_position()

    messages = _collect(application.open_event_stream(EventScope(), after=end + 10, live=False), 1)
    assert messages[0].kind == "resync"
    assert messages[0].reason == "position_unknown"
    assert messages[0].end_position == end

def test_queue_overflow_resyncs_when_the_client_is_too_slow(tmp_path):
    # 客户端处理太慢：订阅队列写满以后服务端发送 resync 并关闭连接
    application = _application(tmp_path)
    # 先写入一条范围内的历史事件：它从历史补发返回，订阅在此之前已经登记
    _record(application, "p1", 0)
    stream = application.open_event_stream(EventScope(projects=("p1",)), after=0, live=False,
                                           queue_limit=8)

    async def run():
        generator = stream.messages()
        messages = [await generator.__anext__()]  # 订阅已登记：此后写入的事件进入订阅队列
        for index in range(40):
            _record(application, "p1", index + 1)
        async for message in generator:
            messages.append(message)
        return messages

    messages = asyncio.run(asyncio.wait_for(run(), 10))
    assert messages[-1].kind == "resync"
    assert messages[-1].reason == "queue_overflow"


def test_idle_emits_a_checkpoint_at_the_scanned_position(tmp_path):
    application = _application(tmp_path)
    _record(application, "p1", 0)
    stream = application.open_event_stream(EventScope(projects=("p1",)), after=0, live=False,
                                           checkpoint_idle_sec=0.2)

    messages = _collect(stream, 2, timeout=10)
    assert messages[0].kind == "event"
    assert messages[1].kind == "checkpoint"
    assert messages[1].position == messages[0].position
    assert messages[1].previous == messages[0].position


