# 排空与强制升级（应用层与接口层设计说明第 3.2 节「升级」，ADR-0019，工单 #126）：真实启动 FastAPI 应用，
# 经 HTTP 提交命令与读取查询；控制核心在服务生命周期中建立，模型回答由 FakeAdapter 给出。
# 排空期间新建的事项排队不开始，正在进行的 run 照常结束；强制升级只在排空期间可用。

import uuid

from harness.watched_outputs import has_new_work
from harness.adapters.fake import FakeAdapter
from harness.event_store import catalog_stream
from harness.models import EventType, ProjectEventType
from harness.projection import project_run
from harness.proposals import product_spec
from harness.streams import DRAIN_STARTED, PRIORITY_UPGRADE_RESTART, STOP_REASON_UPGRADE
from harness.tests.api_helpers import running_api
from harness.tests.helpers import quality_turns
from harness.tests.onboarding_project import (
    OpenedFake as _Opened,
    post_command as _post,
    wait_until as _wait_for,
)


def _blocked_script():
    # 产品提交规格以后工程部门的请求失败：run 停在非终态（ENGINEERING），可以用来检查排空与强制升级
    # 脚本按部门给出（工单 #557：同时运行的会话各自取用自己的脚本，不共用一个队列）
    from harness.adapters.base import ProviderError
    return {
        "product": [product_spec()],
        "engineering": [ProviderError("Missing configuration: provider credential",
                                       reason="provider_unavailable")],
        "quality": quality_turns("release", "checks passed on the current snapshot"),
    }

def test_force_upgrade_outside_a_drain_is_rejected(data_dir):
    opened = _Opened(data_dir, adapter=FakeAdapter(_blocked_script()))
    with running_api(opened) as client:
        project_id = _post(client, "project.create", name="升级项目", goal="核对强制升级").json()["refs"]["project_id"]
        item = _post(client, "work_item.create", project_id=project_id, text="进行中的事项")
        assert item.status_code == 200, item.text
        run_id = item.json()["refs"]["run_id"]
        assert _wait_for(lambda: has_new_work(project_run(opened.store, run_id), "engineering"))

        # 还没有开始排空：强制升级以 not_allowed 拒绝
        rejected = _post(client, "runtime.force_upgrade")
        assert rejected.status_code == 409
        assert rejected.json()["reason"] == "not_allowed"
        assert project_run(opened.store, run_id).stop_reason is None

def test_start_drain_queues_new_work_items_and_reports_the_state(data_dir):
    opened = _Opened(data_dir, adapter=FakeAdapter(_blocked_script()))
    with running_api(opened) as client:
        project_id = _post(client, "project.create", name="排空项目", goal="核对排空").json()["refs"]["project_id"]
        item = _post(client, "work_item.create", project_id=project_id, text="进行中的事项")
        run_id = item.json()["refs"]["run_id"]
        assert _wait_for(lambda: has_new_work(project_run(opened.store, run_id), "engineering"))

        # 未排空
        assert client.get("/api/queries/system.status").json()["data"]["drain"]["state"] == "idle"

        started = _post(client, "runtime.start_drain")
        assert started.status_code == 200, started.text
        draining = client.get("/api/queries/system.status").json()["data"]["drain"]
        assert draining["state"] == "draining"
        assert draining["running_runs"] == 1
        assert draining["version"] == 1

        # 排空期间新建的事项排队：不创建 run，也不开始执行
        queued = _post(client, "work_item.create", project_id=project_id, text="排队的事项")
        assert queued.status_code == 200, queued.text
        after = client.get("/api/queries/system.status").json()["data"]["drain"]
        assert after["queued_work_items"] == 1
        queued_item = opened.system.projects.projection(project_id).work_item(
            queued.json()["refs"]["work_item_id"])
        assert queued_item.status == "not_started"
        assert opened.store.list_events(queued_item.run_id) == []

        # 已经开始排空以后再次开始被拒绝
        again = _post(client, "runtime.start_drain")
        assert again.status_code == 409 and again.json()["reason"] == "not_allowed"

def test_drain_becomes_ready_when_the_run_finishes(data_dir):
    opened = _Opened(data_dir, adapter=FakeAdapter(_blocked_script()))
    with running_api(opened) as client:
        project_id = _post(client, "project.create", name="结束项目", goal="核对排空完成").json()["refs"]["project_id"]
        item = _post(client, "work_item.create", project_id=project_id, text="要结束的事项")
        run_id = item.json()["refs"]["run_id"]
        assert _wait_for(lambda: has_new_work(project_run(opened.store, run_id), "engineering"))
        assert _post(client, "runtime.start_drain").status_code == 200

        # 正在进行的 run 照常结束：取消它以后没有剩余的 run，排空完成可以升级
        cancelled = client.post("/api/commands/work_item.cancel", json={
            "command_id": str(uuid.uuid4()), "work_item_id": item.json()["refs"]["work_item_id"]})
        assert cancelled.status_code == 200, cancelled.text
        assert _wait_for(lambda: project_run(opened.store, run_id).status == "failed")
        assert _wait_for(
            lambda: client.get("/api/queries/system.status").json()["data"]["drain"]["state"] == "ready")
        ready = client.get("/api/queries/system.status").json()["data"]["drain"]
        assert ready["running_runs"] == 0

def test_force_upgrade_stops_the_run_and_restarts_its_work_item(data_dir):
    opened = _Opened(data_dir, adapter=FakeAdapter(_blocked_script()))
    with running_api(opened) as client:
        project_id = _post(client, "project.create", name="强制升级", goal="核对强制升级").json()["refs"]["project_id"]
        item = _post(client, "work_item.create", project_id=project_id, text="被升级打断的事项")
        assert item.status_code == 200, item.text
        run_id = item.json()["refs"]["run_id"]
        assert _wait_for(lambda: has_new_work(project_run(opened.store, run_id), "engineering"))
        assert _post(client, "runtime.start_drain").status_code == 200

        upgraded = _post(client, "runtime.force_upgrade")
        assert upgraded.status_code == 200, upgraded.text

        # 正在进行的 run 记为因升级停止
        stopped = project_run(opened.store, run_id)
        assert (stopped.status, stopped.stop_reason) == ("failed", STOP_REASON_UPGRADE)
        # 对应的事项用采纳成果重新开始，并记下「因升级重新开始」的优先级
        created = [event for event in opened.store.list_project_events(project_id)
                   if event.type == ProjectEventType.WORK_ITEM_CREATED]
        assert created[-1].payload["priority"] == PRIORITY_UPGRADE_RESTART
        new_run_id = created[-1].payload["run_id"]
        assert new_run_id != run_id
        assert project_run(opened.store, new_run_id).run_event_version > 0
        # 旧版本的 run 事件保留供查阅
        assert any(event.type == EventType.RUN_CREATED for event in opened.store.list_events(run_id))


def _create_blocked_item(opened, client, name: str) -> tuple[str, str]:
    # 一个项目与一个停在非终态的事项（产品提交规格以后工程的请求失败）：可以开始排空与强制升级
    project_id = _post(client, "project.create", name=name, goal="核对排空区的读数").json()["refs"]["project_id"]
    item = _post(client, "work_item.create", project_id=project_id, text="进行中的事项")
    assert item.status_code == 200, item.text
    run_id = item.json()["refs"]["run_id"]
    assert _wait_for(lambda: has_new_work(project_run(opened.store, run_id), "engineering"))
    return project_id, run_id


def test_drain_reports_the_start_time_and_the_running_run(data_dir):
    # 验收一（工单 #1187）：开始排空以后 system.status.drain 带开始时间（来自「开始排空」事件）与
    # 进行中的 run（run 标识与事项标题）
    opened = _Opened(data_dir, adapter=FakeAdapter(_blocked_script()))
    with running_api(opened) as client:
        project_id, run_id = _create_blocked_item(opened, client, "排空区")
        assert _post(client, "runtime.start_drain").status_code == 200
        started = [event for event in opened.store.stream_events(catalog_stream())
                   if event.type == DRAIN_STARTED][-1]
        drain = client.get("/api/queries/system.status").json()["data"]["drain"]
        assert drain["state"] == "draining"
        assert drain["since"] == started.created_at
        assert drain["running_runs"] == 1
        assert [(entry["run_id"], entry["title"]) for entry in drain["running"]] == [(run_id, "进行中的事项")]


def test_force_upgrade_shows_the_forced_state_and_the_restarted_run(data_dir):
    # 验收二（工单 #1187）：强制升级以后排空状态是「已强制升级」，进行中的 run 列表换成重新开始的那个 run；
    # 开始时间仍记在这一处
    opened = _Opened(data_dir, adapter=FakeAdapter(_blocked_script()))
    with running_api(opened) as client:
        project_id, run_id = _create_blocked_item(opened, client, "强制升级后的排空区")
        assert _post(client, "runtime.start_drain").status_code == 200
        started = [event for event in opened.store.stream_events(catalog_stream())
                   if event.type == DRAIN_STARTED][-1]
        assert _post(client, "runtime.force_upgrade").status_code == 200
        created = [event for event in opened.store.list_project_events(project_id)
                   if event.type == ProjectEventType.WORK_ITEM_CREATED]
        new_run_id = created[-1].payload["run_id"]
        drain = client.get("/api/queries/system.status").json()["data"]["drain"]
        assert drain["state"] == "forced"
        assert drain["since"] == started.created_at
        assert [(entry["run_id"], entry["title"]) for entry in drain["running"]] == [
            (new_run_id, "进行中的事项")]
