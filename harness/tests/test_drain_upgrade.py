# 排空在服务下一次启动时结束（工单 #731，应用层与接口层设计说明第 3.2 节「升级」）：
# 排空 → 下一次启动 → 排空结束、排队的事项这一次开始、之后新建的事项直接开始。
# 排空结束的这件事记在目录流里（跨版本保存的长期事实），下一次启动不再重复记。
#
# 只跑真实代码，不使用 mock。

from harness.adapters.fake import FakeAdapter
from harness.event_store import catalog_stream
from harness.runtime import LoopSystem
from harness.streams import DRAIN_FINISHED, DRAIN_STARTED
from harness.tests.api_helpers import running_api
from harness.tests.onboarding_project import (
    OpenedFake as _Opened,
    post_command as _post,
    wait_until as _wait_for,
)
from harness.write_path import NewCatalogEvent


def _drain_event(system, payload):
    # 写一条「开始排空」事件：模拟排空的那一次服务
    system.writes.transact(catalog_stream(), lambda transaction: transaction.append(
        NewCatalogEvent(DRAIN_STARTED, payload, actor="system")))


def _drain_events(system):
    return [event for event in system.store.stream_events(catalog_stream())
            if event.type in (DRAIN_STARTED, DRAIN_FINISHED)]


def _phase(system, run_id):
    # run 的阶段；run 还没有建出来时是空
    from harness.projection import RunNotFoundError, project_run
    try:
        return project_run(system.store, run_id).status
    except RunNotFoundError:
        return None


def test_the_drain_ends_at_the_next_start(data_dir):
    system = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    _drain_event(system, {"version": 1, "running_runs": 0})
    assert system.drain.state == "ready"

    # 下一次启动：排空结束
    reopened = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    assert reopened.drain.state == "idle"
    # 排空结束这件事记在目录流里
    assert [event.type for event in _drain_events(reopened)] == [DRAIN_STARTED, DRAIN_FINISHED]
    assert _drain_events(reopened)[-1].payload["version"] == 1

    # 再一次启动：排空已经结束，不再重复记
    again = LoopSystem.for_testing(data_dir, FakeAdapter([]))
    assert again.drain.state == "idle"
    assert [event.type for event in _drain_events(again)] == [DRAIN_STARTED, DRAIN_FINISHED]


def test_the_queued_work_item_starts_after_the_restart(data_dir):
    from harness.tests.helpers import happy_script
    opened = _Opened(data_dir, adapter=FakeAdapter(happy_script()))
    with running_api(opened) as client:
        project_id = _post(client, "project.create", name="排空项目", goal="核对排空在下一次启动时结束").json()["refs"]["project_id"]
        # 先排空：实例不再开始新事项
        assert _post(client, "runtime.start_drain").status_code == 200
        assert client.get("/api/queries/system.status").json()["data"]["drain"]["state"] == "ready"

        # 排空期间新建的事项排队：不开始
        queued = _post(client, "work_item.create", project_id=project_id, text="排队的事项")
        assert queued.status_code == 200, queued.text
        queued_run = queued.json()["refs"]["run_id"]
        assert opened.store.list_events(queued_run) == []

    # 下一次启动（对应升级）：排空结束
    restarted = _Opened(data_dir, adapter=FakeAdapter(happy_script()))
    with running_api(restarted) as client:
        assert client.get("/api/queries/system.status").json()["data"]["drain"]["state"] == "idle"
        # 排队的事项这一次补建并跑完
        assert _wait_for(lambda: _phase(restarted.system, queued_run) in ("done", "failed"))
        assert restarted.system.projects.projection(project_id).work_item(
            queued.json()["refs"]["work_item_id"]).status != "not_started"
        # 之后新建的事项直接开始：不再排队
        fresh = _post(client, "work_item.create", project_id=project_id, text="排空结束以后的事项")
        assert fresh.status_code == 200, fresh.text
        assert _wait_for(lambda: restarted.system.store.list_events(fresh.json()["refs"]["run_id"]) != [])
        assert client.get("/api/queries/system.status").json()["data"]["drain"]["state"] == "idle"


