import asyncio
import time

from harness.app.application import Application
from harness.app.event_stream import EventScope
from harness.app.labels import GENERIC_EVENT_LABEL, _LABELS
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

def test_live_events_arrive_within_a_hundred_milliseconds(tmp_path):
    # 写入以后推送不依赖定时查询：新事件在 100 毫秒以内到达
    application = _application(tmp_path)
    # 先写入一条历史事件：生成器读完它以后进入等待，新事件随后才写入
    _record(application, "p1", 0)
    stream = application.open_event_stream(EventScope(projects=("p1",)), after=0, live=False,
                                           checkpoint_idle_sec=5.0)

    async def run():
        generator = stream.messages()
        assert (await generator.__anext__()).kind == "event"
        # 把下一次取消息包成任务，用零时长让渡轮询等生成器挂在等待上（ag_await 非 None），
        # 此时它已经不看历史读取：写入之后到达的事件只能是实时推送
        pending = asyncio.ensure_future(generator.__anext__())
        deadline = asyncio.get_running_loop().time() + 3.0
        while generator.ag_await is None:
            assert asyncio.get_running_loop().time() < deadline, "生成器没有进入等待"
            await asyncio.sleep(0)
        started = time.monotonic()
        _record(application, "p1", 1)
        return await pending, time.monotonic() - started

    message, elapsed = asyncio.run(asyncio.wait_for(run(), 10))
    assert message.kind == "event"
    assert elapsed < 0.1

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


def test_an_event_without_a_label_does_not_break_the_stream(tmp_path):
    # 一条没有登记中文说明的事件不能让整条流断掉（工单 #664）：
    # 事件流播到这一条就断，客户端每秒重连一次，永远过不去。
    # 这里把这类事件的说明从标签表里去掉，复现「事件种类漏登记说明」的情形。
    application = _application(tmp_path)
    for index in range(3):
        _record(application, "p1", index)

    template = _LABELS.pop(ProjectEventType.PROJECT_RENAMED)
    try:
        stream = application.open_event_stream(
            EventScope(types=(ProjectEventType.PROJECT_RENAMED,)), after=0, live=False)
        messages = _collect(stream, 3)
    finally:
        _LABELS[ProjectEventType.PROJECT_RENAMED] = template

    assert len(messages) == 3
    assert [message.event.label for message in messages] == [GENERIC_EVENT_LABEL] * 3
    assert [message.event.position for message in messages] == sorted(
        message.event.position for message in messages)
