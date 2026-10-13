# 协作回答带上发问方与回答方（工单 #275）：一次咨询请求与回答以后，collaboration_responded 载荷带
# requester 与 recipient，与对应请求相同；run.export 与事件流同样如此。旧事件没有这两个字段时按声明的
# 缺省含义读取（按 request_id 查找对应请求），不出错。运行的系统、真实 HTTP 与事件日志。

import json
import sqlite3
import time
import uuid
from dataclasses import replace

from harness.adapters.fake import FakeAdapter
from harness.app.application import DEFAULT_REGISTRY, Application
from harness.event_store import run_stream
from harness.models import EventType
from harness.proposals import collaboration_request, delivery_turn, product_spec, response_turn, review_turn
from harness.runtime import LoopSystem
from harness.tests.api_helpers import running_api
from harness.tests.saved_rewrite import rewrite_saved_event

CONSULTATION_SCRIPT = [
    product_spec(),
    delivery_turn(),
    # 质检向产品提出咨询，产品回答，质检继续独立放行
    collaboration_request("product", "Unknown flags 应该怎么处理？"),
    response_turn("answered", "按当前有效合同处理：原样打印。"),
    review_turn("release", "回答以后重新放行"),
]

class _Opened:
    # 服务生命周期中建立的应用层；测试经它直接读取事件日志核对结果
    def __init__(self, data_dir) -> None:
        self.data_dir = data_dir
        self.applications: list[Application] = []

    def __call__(self) -> Application:
        application = Application(LoopSystem.for_testing(self.data_dir, FakeAdapter(CONSULTATION_SCRIPT)),
                                  registry=DEFAULT_REGISTRY)
        self.applications.append(application)
        return application

    @property
    def system(self):
        return self.applications[-1].system

    @property
    def store(self):
        return self.system.store

def _post(client, command: str, **body):
    return client.post(f"/api/commands/{command}", json={"command_id": str(uuid.uuid4()), **body})

def _finish(system, run_id: str) -> None:
    # 事项的执行在接口进程的事件循环中作为任务运行；等它结束（停在阻塞处或终止）
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        task = system.orchestrator.work_item_execution(run_id)
        if task is None or task.done():
            return
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not stop")

def _start_and_finish(client, opened, name: str = "协作两端"):
    project_id = _post(client, "project.create", name=name, goal="核对回答事件的两端").json()["refs"]["project_id"]
    started = _post(client, "work_item.create", project_id=project_id, text="做一件事")
    assert started.status_code == 200, started.text
    run_id = started.json()["refs"]["run_id"]
    _finish(opened.system, run_id)
    return run_id

def test_the_responded_payload_carries_both_parties_matching_the_request(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        run_id = _start_and_finish(client, opened)
        exported = client.get("/api/queries/run.export", params={"run_id": run_id})
        assert exported.status_code == 200, exported.text
        exported_events = exported.json()["data"]["events"]
        events = opened.store.list_events(run_id)
    request = next(event for event in events if event.type == EventType.COLLABORATION_REQUESTED)
    responded = next(event for event in events if event.type == EventType.COLLABORATION_RESPONDED)
    assert (responded.payload["requester"], responded.payload["recipient"]) == (
        request.payload["requester"], request.payload["recipient"])
    assert responded.payload["requester"] == "quality"
    assert responded.payload["recipient"] == "product"
    # run.export 的事件流同样带这两个字段
    exported = next(item for item in exported_events if item["type"] == EventType.COLLABORATION_RESPONDED)
    assert (exported["payload"]["requester"], exported["payload"]["recipient"]) == ("quality", "product")

def test_the_event_stream_carries_both_parties(data_dir):
    opened = _Opened(data_dir)
    with running_api(opened) as client:
        run_id = _start_and_finish(client, opened, name="事件流")
        count = len(opened.store.list_events(run_id))
        frames = _read_events(client, f"/api/events?after=0&run_id={run_id}", limit=count)
    responded = next(frame for frame in frames if frame["type"] == EventType.COLLABORATION_RESPONDED)
    assert (responded["payload"]["requester"], responded["payload"]["recipient"]) == ("quality", "product")

def _read_events(client, url: str, *, limit: int):
    frames = []
    with client.stream("GET", url, timeout=30) as response:
        assert response.status_code == 200
        event = None
        for line in response.iter_lines():
            if line.startswith("event: "):
                event = line.removeprefix("event: ")
            elif line.startswith("data: ") and event == "event":
                frames.append(json.loads(line.removeprefix("data: ")))
            if len(frames) >= limit:
                break
        response.close()
    return frames

def test_an_old_responded_event_without_the_parties_reads_by_request_id(data_dir):
    # 旧事件（没有 requester 与 recipient）按声明的缺省含义读取：按 request_id 查找对应请求补齐两端
    system = LoopSystem.for_testing(data_dir, FakeAdapter(CONSULTATION_SCRIPT))
    project_id = system.projects.register("旧事件", "核对缺省含义")
    _work_item, run_id = system.projects.start_work_item(project_id, "做一件事")
    assert system.run_until_stop(run_id).phase == "DONE"

    responded = next(event for event in system.store.list_events(run_id)
                     if event.type == EventType.COLLABORATION_RESPONDED)
    stripped = dict(responded.payload)
    stripped.pop("requester")
    stripped.pop("recipient")
    rewrite_saved_event(system.store, replace(responded, payload=stripped))

    # 从事件日志重建保存的投影：旧事件没有这两个字段，读取时按 request_id 查找对应请求补齐
    rebuilt = system.writes.rebuild(run_stream(run_id))
    response = next(item for item in rebuilt.responses if item.request_id == stripped["request_id"])
    request = next(item for item in rebuilt.requests if item.id == stripped["request_id"])
    assert (response.requester, response.recipient) == (request.requester, request.recipient) == ("quality", "product")
    assert system.replay(run_id).canonical_state() == rebuilt.canonical_state()

def test_an_old_saved_projection_without_the_parties_loads_with_unknown(data_dir):
    # 旧版本保存的投影里回答记录没有这两个字段：读取时按缺省含义得到未知（None），不报错
    system = LoopSystem.for_testing(data_dir, FakeAdapter(CONSULTATION_SCRIPT))
    project_id = system.projects.register("旧投影", "核对缺省含义")
    _work_item, run_id = system.projects.start_work_item(project_id, "做一件事")
    assert system.run_until_stop(run_id).phase == "DONE"

    connection = sqlite3.connect(system.store.path)
    try:
        saved = connection.execute("SELECT state FROM projections WHERE stream = ?",
                                   (run_stream(run_id),)).fetchone()
        state = json.loads(saved[0])
        for item in state["responses"]:
            item.pop("requester")
            item.pop("recipient")
        connection.execute("UPDATE projections SET state = ? WHERE stream = ?",
                           (json.dumps(state), run_stream(run_id)))
        connection.commit()
    finally:
        connection.close()

    projection = system.project(run_id)
    response = next(item for item in projection.responses)
    assert (response.requester, response.recipient) == (None, None)
    # 对应的请求仍带两端：客户端可按 request_id 找回
    request = next(item for item in projection.requests if item.id == response.request_id)
    assert (request.requester, request.recipient) == ("quality", "product")
