import asyncio
import json
import time
import uuid

import httpx

from harness.adapters.fake import FakeAdapter
from harness.app.application import DEFAULT_REGISTRY, Application
from harness.models import EventType, ProjectEventType
from harness.adapters.base import Availability
from harness.providers.call import CallUsage, ModelDelta, ModelResponse, ModelStreamEvent
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_api

_USAGE = CallUsage(input_tokens=10, output_tokens=5, total_tokens=15, reported=True)

class _Opened:
    # 服务生命周期中建立的应用层；测试经它核对事件日志与进行中的片段
    def __init__(self, data_dir, adapter=None) -> None:
        self.data_dir = data_dir
        self.adapter = adapter if adapter is not None else FakeAdapter([])
        self.applications: list[Application] = []

    def __call__(self) -> Application:
        application = Application(LoopSystem.for_testing(self.data_dir, self.adapter),
                                  registry=DEFAULT_REGISTRY)
        self.applications.append(application)
        return application

class _BlockingDeltas:
    # 在给出三段片段之后阻塞，供测试在调用尝试进行中订阅片段与查询 attempt.live
    name = "stub"
    model = "stub-model"

    def __init__(self) -> None:
        self.streamed = asyncio.Event()
        self.release = asyncio.Event()

    def availability(self):
        return Availability(True)

    def cancel(self, _attempt_id):
        self.release.set()

    async def stream(self, call):
        for index, text in enumerate(["第一段", "第二段", "第三段"]):
            yield ModelStreamEvent(kind="stream_event", id=f"stream-{index}",
                                   payload={"type": "response.output_text.delta"}, sequence=index,
                                   stage="output",
                                   deltas=(ModelDelta(channel="output", offset=index * 3, text=text),))
        self.streamed.set()
        await asyncio.wait_for(self.release.wait(), 15)
        yield ModelStreamEvent(kind="response", id="response", payload={
            "id": "resp-stub", "object": "response", "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "第一段第二段第三段"}]}]})
        yield ModelResponse(output=[{"type": "message", "content": [
            {"type": "output_text", "text": "第一段第二段第三段"}]}],
            usage=_USAGE, provider=self.name, model=self.model)

def _wait_for(event: "asyncio.Event", timeout: float = 15.0) -> bool:
    # 事件在服务的事件循环里被置位，测试线程轮询它的状态
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if event.is_set():
            return True
        time.sleep(0.02)
    return event.is_set()

def _wait_for_live_release(application: Application, attempt_id: str, timeout: float = 20.0) -> bool:
    # 等这次调用尝试结束（片段已经释放）：调用尝试的结束与释放都在服务的事件循环里完成
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if application.live_attempt(attempt_id) == {}:
            return True
        time.sleep(0.02)
    return application.live_attempt(attempt_id) == {}

def _wait_for_attempt_response(client: httpx.Client, run_id: str, attempt_id: str, timeout: float = 20.0):
    # 等调用尝试的结果写进读取模型：模型输出与用量在调用结束以后记录
    deadline = time.monotonic() + timeout
    attempt = None
    while time.monotonic() < deadline:
        attempt = client.get("/api/queries/run.attempt",
                             params={"run_id": run_id, "attempt_id": attempt_id}).json()
        if attempt["data"]["response"] is not None:
            return attempt
        time.sleep(0.05)
    return attempt

def _read_deltas(client: httpx.Client, url: str, *, count: int, headers=None):
    # 一直读到拿到 count 条 delta 帧为止：片段在调用进行中到达，可能排在若干日志事件之后
    frames = []
    with client.stream("GET", url, headers=headers, timeout=30) as response:
        assert response.status_code == 200
        name, identity, data = None, None, []
        try:
            for line in response.iter_lines():
                if line == "":
                    if name is not None or data:
                        frames.append((name, identity, json.loads("".join(data)) if data else None))
                    name, identity, data = None, None, []
                    if sum(1 for item in frames if item[0] == "delta") >= count:
                        break
                    continue
                if line.startswith("event:"):
                    name = line[len("event:"):].strip()
                elif line.startswith("id:"):
                    identity = line[len("id:"):].strip()
                elif line.startswith("data:"):
                    data.append(line[len("data:"):].strip())
        finally:
            response.close()
    return frames

def _read_stream(client: httpx.Client, url: str, *, limit: int, headers=None):
    # 逐个读取 SSE 帧：返回 (event, id, data) 列表，读够 limit 条后停止；停止时直接关闭响应，
    # 不把连接未读完当作错误
    frames = []
    with client.stream("GET", url, headers=headers, timeout=30) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        name, identity, data = None, None, []
        try:
            for line in response.iter_lines():
                if line == "":
                    if name is not None or data:
                        frames.append((name, identity, json.loads("".join(data)) if data else None))
                    name, identity, data = None, None, []
                    if len(frames) >= limit:
                        break
                    continue
                if line.startswith("event:"):
                    name = line[len("event:"):].strip()
                elif line.startswith("id:"):
                    identity = line[len("id:"):].strip()
                elif line.startswith("data:"):
                    data.append(line[len("data:"):].strip())
        finally:
            response.close()
    return frames

def _create_project(client) -> str:
    response = client.post("/api/commands/project.create",
                           json={"command_id": str(uuid.uuid4()), "name": "事件流", "goal": "订阅事件"})
    assert response.status_code == 200
    return response.json()["refs"]["project_id"]

def _record(client, project_id: str, index: int) -> None:
    response = client.post("/api/commands/material.record",
                           json={"command_id": str(uuid.uuid4()), "project_id": project_id,
                                 "text": f"材料 {index}"})
    assert response.status_code == 200

def test_event_stream_backfills_by_position_with_labels_and_previous(data_dir):
    # 断线以后按位置补齐：事件带位置 id、previous 链与中文说明；跨项目按全局位置排列
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        project_id = _create_project(client)
        _record(client, project_id, 1)
        end = opened.applications[0].system.store.end_position()
        frames = _read_stream(client, "/api/events?after=0", limit=end)

    assert all(name == "event" for name, _, _ in frames)
    assert [int(identity) for _, identity, _ in frames] == list(range(1, end + 1))
    positions = [frame[2]["position"] for frame in frames]
    assert positions == sorted(positions) == list(range(1, end + 1))
    assert frames[0][2]["previous"] == 0
    assert all(frame[2]["label"] for frame in frames)
    kinds = [frame[2]["type"] for frame in frames]
    assert ProjectEventType.PROJECT_REGISTERED in kinds
    create = next(frame for frame in frames if frame[2]["type"] == ProjectEventType.PROJECT_REGISTERED)
    assert "事件流" in create[2]["label"]
    assert create[2]["actor"] == "user:local"

def test_event_stream_resumes_after_the_last_received_position(data_dir):
    # 从最后收到的位置续上：没有遗漏与重复
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        project_id = _create_project(client)
        _record(client, project_id, 1)
        _record(client, project_id, 2)
        first = _read_stream(client, "/api/events?after=0", limit=2)
        last = int(first[-1][1])
        resumed = _read_stream(client, f"/api/events?after={last}", limit=10)

    assert all(int(identity) > last for _, identity, _ in resumed)
    assert resumed[0][2]["previous"] == last

def test_last_event_id_header_takes_priority_over_the_after_parameter(data_dir):
    # Last-Event-ID 请求头优先于 after 参数：after 给 0，请求头给最后一条的位置，只应收到之后的新事件
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        project_id = _create_project(client)
        _record(client, project_id, 1)
        end = opened.applications[0].system.store.end_position()
        _record(client, project_id, 2)
        frames = _read_stream(client, "/api/events?after=0", limit=1,
                              headers={"Last-Event-ID": str(end)})

    assert int(frames[0][1]) == end + 1
    assert frames[0][2]["previous"] == end

def test_event_stream_filters_match_reading_the_log(data_dir):
    # 各范围参数的筛选结果与按相同条件读取事件日志的结果相同
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        project_id = _create_project(client)
        _record(client, project_id, 1)
        _record(client, project_id, 2)
        types = f"type={ProjectEventType.MATERIAL_RECORDED}"
        frames = _read_stream(client, f"/api/events?{types}", limit=2)
        store = opened.applications[0].system.store
        expected = [event.position for event in
                    store.read(after=0, limit=100, types=(ProjectEventType.MATERIAL_RECORDED,))]
        project_frames = _read_stream(client, f"/api/events?project={project_id}&{types}", limit=2)
        # 范围内没有事件时，连接按空闲（5 秒）发送一次检查点，位置为已扫描到的位置
        idle_frame = _read_stream(client, "/api/events?project=another-project&type=run_created", limit=1)
        end = store.end_position()

    assert [frame[2]["position"] for frame in frames] == expected
    assert [frame[2]["position"] for frame in project_frames] == expected
    assert all(frame[2]["project_id"] == project_id for frame in frames)
    assert idle_frame[0][0] == "checkpoint"
    assert idle_frame[0][1] == str(end)

def test_resync_when_after_is_beyond_the_log_end(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        _create_project(client)
        end = opened.applications[0].system.store.end_position()
        frames = _read_stream(client, f"/api/events?after={end + 100}", limit=1)

    name, identity, data = frames[0]
    assert name == "resync"
    assert identity is None
    assert data == {"reason": "position_unknown", "end_position": end}

def test_live_connection_receives_deltas_and_attempt_live_matches_them(data_dir):
    # 调用尝试进行中，带 live=1 的连接收到按 offset 连续的片段；attempt.live 的文字与片段拼接一致；
    # 片段不出现在事件日志中；不带 live 的连接收不到片段
    adapter = _BlockingDeltas()
    opened = _Opened(data_dir, adapter=adapter)
    with running_api(opened) as client:
        project_id = _create_project(client)
        response = client.post("/api/commands/work_item.create",
                               json={"command_id": str(uuid.uuid4()), "project_id": project_id,
                                     "title": "跑一次", "text": "让模型输出文字"})
        assert response.status_code == 200, response.text
        system = opened.applications[0].system
        # 事项的执行由流程编排在服务的事件循环中开始；适配器给出三段片段以后阻塞，测试在此期间订阅与查询
        assert _wait_for(adapter.streamed)

        live = _read_deltas(client, "/api/events?live=true", count=3)
        deltas = [data for name, _, data in live if name == "delta"]
        assert len(deltas) == 3
        attempt_id = deltas[0]["attempt_id"]
        body = client.get("/api/queries/attempt.live", params={"attempt_id": attempt_id}).json()
        channel_text = body["data"]["channels"]["output"]
        adapter.release.set()

        # 片段按 offset 连续，拼接与 attempt.live 的文字一致；片段的事件名为 delta、不带 id
        assert [data["offset"] for data in deltas] == [0, 3, 6]
        assert "".join(data["text"] for data in deltas) == channel_text == "第一段第二段第三段"
        assert all(identity is None for name, identity, _ in live if name == "delta")
        events = system.store.list_events(system.list_run_ids()[0])
        assert "第一段" not in json.dumps([event.payload for event in events], ensure_ascii=False)
        # 等待这次调用尝试结束：结束以后 attempt.live 释放，最终输出以 run.attempt 为准
        assert _wait_for_live_release(opened.applications[0], attempt_id)
        assert opened.applications[0].live_attempt(attempt_id) == {}
        attempt = _wait_for_attempt_response(client, system.list_run_ids()[0], attempt_id)
        assert "第一段第二段第三段" in json.dumps(attempt["data"]["response"], ensure_ascii=False)

def test_plain_connection_does_not_receive_deltas(data_dir):
    adapter = _BlockingDeltas()
    opened = _Opened(data_dir, adapter=adapter)
    with running_api(opened) as client:
        project_id = _create_project(client)
        assert client.post("/api/commands/work_item.create",
                           json={"command_id": str(uuid.uuid4()), "project_id": project_id,
                                 "title": "跑一次", "text": "让模型输出文字"}).status_code == 200
        system = opened.applications[0].system
        assert _wait_for(adapter.streamed)
        frames = _read_stream(client, "/api/events?live=false&type=model_stream_progress", limit=1)
        adapter.release.set()

    assert all(name != "delta" for name, _, _ in frames)
    assert frames[0][2]["type"] == EventType.MODEL_STREAM_PROGRESS

def test_two_live_connections_each_receive_the_full_fragments(data_dir):
    # 两个带 live=1 的连接同时订阅：各自收到完整的片段（第 5.6 节发给每个范围匹配的 live 连接），
    # 一个连接先读取不影响另一个连接收到的片段
    adapter = _BlockingDeltas()
    opened = _Opened(data_dir, adapter=adapter)
    with running_api(opened) as client:
        project_id = _create_project(client)
        assert client.post("/api/commands/work_item.create",
                           json={"command_id": str(uuid.uuid4()), "project_id": project_id,
                                 "title": "跑一次", "text": "让模型输出文字"}).status_code == 200
        assert _wait_for(adapter.streamed)
        # 两个连接先后建立：后建立的连接同样收到全部片段，不因泵的片段已被先到的连接取走而缺失
        first_frames = _read_deltas(client, "/api/events?live=true", count=3)
        second_frames = _read_deltas(client, "/api/events?live=true", count=3)
        first_deltas = [data for name, _, data in first_frames if name == "delta"]
        second_deltas = [data for name, _, data in second_frames if name == "delta"]
        adapter.release.set()

    assert [data["offset"] for data in first_deltas] == [0, 3, 6]
    assert [data["offset"] for data in second_deltas] == [0, 3, 6]
    assert "".join(data["text"] for data in first_deltas) == "第一段第二段第三段"
    assert "".join(data["text"] for data in second_deltas) == "第一段第二段第三段"

def test_keepalive_comment_is_sent_when_the_stream_is_idle(data_dir):
    # 空闲超过保活间隔时连接收到一条 SSE 注释（第 5.4 节第 5 项）；注释没有 id，不改变续传位置
    opened = _Opened(data_dir)
    with running_api(opened, keepalive_sec=0.2) as client:
        project_id = _create_project(client)
        _record(client, project_id, 1)
        end = opened.applications[0].system.store.end_position()
        # 从日志末尾订阅：历史为空、范围内也没有新事件，连接进入空闲等待
        with client.stream("GET", f"/api/events?after={end}", timeout=10) as response:
            assert response.status_code == 200
            lines = []
            for line in response.iter_lines():
                lines.append(line)
                if line.startswith(":") and "keep-alive" in line:
                    break
    assert any(line.startswith(":") and "keep-alive" in line for line in lines)

def test_last_event_id_that_is_not_a_number_resyncs(data_dir):
    # Last-Event-ID 不是非负整数：按位置未知处理，发送 resync 并关闭连接，不使连接异常
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        project_id = _create_project(client)
        _record(client, project_id, 1)
        frames = _read_stream(client, "/api/events?after=0", limit=1,
                              headers={"Last-Event-ID": "not-a-position"})

    assert frames[0][0] == "resync"
    assert frames[0][2]["reason"] == "position_unknown"

def test_capabilities_list_the_stream_capability(data_dir):
    with running_api(_Opened(data_dir)) as client:
        stream = client.get("/api/capabilities").json()["stream"]
    assert stream["deltas"] is True
    assert stream["scopes"] == ["project", "work_item", "run", "department", "role", "type"]

def test_attempt_live_query_is_registered_and_empty_for_unknown_attempts(data_dir):
    with running_api(_Opened(data_dir)) as client:
        response = client.get("/api/queries/attempt.live", params={"attempt_id": "unknown"})
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == {"attempt_id": "unknown", "live": False, "channels": {}}
