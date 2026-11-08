# 故障矩阵第 9 行：页面/SSE 断开（恢复契约与故障矩阵 docs/design/recovery-contract-and-fault-matrix.md「故障矩阵」）。
# 一个已经中断、没有在执行的 run：页面经真实的 HTTP 事件流（SSE）读事实，读到第一条事件以后断开，
# 再从最后收到的位置重连。重连只补观察：断开与重连期间没有写入任何事件，没有新建执行、没有重新发出
# 模型请求或工具调用；重连补齐位置缺失的事件，与直接读事件日志的结果一致，恢复观察经查询读出。
#
# 层：集成层（真实 HTTP 服务与端口、真实事件库；事件流经 harness/app/event_stream.py 的真实实现）。
# 守 R2（事件流的位置、previous 链与 Last-Event-ID 续传合同）与 R3（页面重连只补观察，不新建执行、不重发）。
# 会让这条用例失败的反例：重连时启动一次恢复或新建执行（事件日志末尾前进，或适配器被调用一次），
# 或者按 last-event-id 续传时漏发、重发事件（位置列表与事件日志不一致）。

import json

from harness.adapters.fake import FakeAdapter
from harness.app.application import DEFAULT_REGISTRY, Application
from harness.models import EventType, TERMINAL_STATUSES
from harness.proposals import product_spec
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_api


class _Opened:
    # 服务生命周期里打开的应用：打开数据目录时不自动继续未结束的 run。
    # 重连若新建执行，事件日志末尾会前进，或适配器被调用；这个应用没有可用的模型脚本，调用就会失败
    def __init__(self, data_dir) -> None:
        self.data_dir = data_dir
        self.applications: list[Application] = []

    def __call__(self) -> Application:
        application = Application(
            LoopSystem.for_testing(self.data_dir, FakeAdapter([]), resume_on_startup=False),
            registry=DEFAULT_REGISTRY,
        )
        self.applications.append(application)
        return application


def _read_frames(client, url: str, *, limit: int, headers=None):
    # 逐个读取 SSE 帧：返回 (event, id, data) 列表，读够 limit 条就主动关闭连接（页面离开）
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


def test_a_reconnecting_event_stream_only_backfills_the_observation(tmp_path):
    # 故障矩阵第 9 行：页面连上、读到第一条事件以后断开，再从最后收到的位置重连。
    # 重连只补观察：断开与重连期间没有写入任何事件，没有新建执行、没有重发模型或工具
    data_dir = tmp_path / "data"
    system = LoopSystem.for_testing(data_dir, FakeAdapter({"product": [product_spec()]}))
    try:
        project_id = system.projects.register("事件流", "核对页面断线与重连")
        _work_item_id, run_id = system.projects.start_work_item(project_id, "被中断的事项")
        system.activate_once(run_id)
        interrupted = system.project(run_id)
        assert interrupted.status not in TERMINAL_STATUSES, interrupted.status
    finally:
        system.close()

    opened = _Opened(data_dir)
    with running_api(opened) as client:
        application = opened.applications[0]
        store = application.system.store
        end = store.end_position()
        assert end > 0

        # 页面连上、读到第一条事件以后断开
        first = _read_frames(client, "/api/events?after=0", limit=1)
        assert first[0][0] == "event", first[0]
        last_position = int(first[0][1])

        # 断开期间没有写入任何事件：没有新建执行，也没有重发模型或工具
        assert store.end_position() == end
        assert application.system.test_adapter.invocations == []
        assert run_id not in application.system.resumed_runs
        assert not any(event.type == EventType.RUN_RESUMED for event in store.list_events(run_id))

        # 从最后收到的位置重连：补齐位置缺失的事件，与直接读事件日志一致
        expected = [event.position for event in store.read(after=last_position, limit=1000)]
        assert expected == list(range(last_position + 1, end + 1)), expected
        remaining = _read_frames(client, "/api/events?after=0", limit=len(expected),
                                 headers={"Last-Event-ID": str(last_position)})
        assert [frame[2]["position"] for frame in remaining] == expected
        assert all(frame[1] == str(frame[2]["position"]) for frame in remaining)

        # 重连以后仍然只有观察：事件日志末尾、run 的状态与最后一条事实都没有变化
        assert store.end_position() == end
        assert application.system.test_adapter.invocations == []
        projection = application.system.project(run_id)
        assert (projection.status, projection.last_event_id) == (interrupted.status, interrupted.last_event_id)

        # 重连的页面经查询读出恢复观察：中断，继续执行不可用
        body = client.get("/api/queries/run.recovery", params={"run_id": run_id}).json()
        assert body["data"]["state"] == "interrupted", body["data"]["state"]
        assert body["data"]["can_continue"] is False
